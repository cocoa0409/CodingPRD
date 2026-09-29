"""The one cycle in the system: HEARING_SCHEDULED to CONTINUED and back again.

Every other transition in the petition and hearing machines moves forward. A
continuance puts the matter over, a fresh listing brings it back, and the loop is
bounded at two turns.
"""

from test_helpers import (
    ApiErrorId,
    COMPLIANCE_OFFICER_HEADERS,
    CONTINUANCE_LIMIT,
    HearingOutcome,
    HearingStatus,
    HoldStatus,
    PetitionStatus,
    active_hold_case,
    assert_docket_minutes,
    assert_error,
    create_petition,
    hearing_outcome_payload,
    read_clinician,
    read_hearing,
    read_hold,
    read_petition,
    record_outcome,
    scheduled_hearing,
)

HEARING_DURATION = 30
FIRST_SLOT = "2026-09-04T09:00:00Z"
SECOND_SLOT = "2026-09-04T10:00:00Z"
THIRD_SLOT = "2026-09-04T11:00:00Z"


def _petition_on_an_active_hold(api, roster):
    """A certified hold with a petition filed against it."""
    case = active_hold_case(
        api,
        roster,
        mrn="MRN-2367-CY",
        legal_name="Cyrus Lambe",
        age_years=47,
        gender_care_category="NONBINARY",
    )
    case["petition"] = create_petition(
        api, roster.psychiatrist_headers, case["hold"]["id"]
    )
    return case


def _list_hearing(api, roster, petition_id, slot):
    """Book one thirty-minute slot on the advocate's docket."""
    return scheduled_hearing(
        api,
        roster.advocate_headers,
        petition_id,
        roster.advocate["id"],
        slot,
        HEARING_DURATION,
    )


class TestPetitionContinuanceCycle:
    """Two continuances are allowed; the third is refused."""

    def test_a_continuance_then_a_fresh_listing_returns_the_petition_to_hearing_scheduled(
        self, api, clock, roster
    ):
        """The petition goes over to another date and comes back on the second listing.

        PRD 3.4: "A continued petition can be scheduled again, which returns it
        `CONTINUED → HEARING_SCHEDULED` and creates a second hearing in
        `SCHEDULED` with the advocate's docket recomputed upward — this is the one
        cycle in the system, `HEARING_SCHEDULED → CONTINUED → HEARING_SCHEDULED`,
        and it is bounded: a continuance is permitted only while
        `continuance_count` is below 2, so the third attempt at a continuance on
        the same petition is refused with `ERR_CONTINUANCE_LIMIT_REACHED`."

        Design: Difficulty/non_linear_state_machine/petition_continuance_cycle_returns_to_hearing_scheduled
        """
        case = _petition_on_an_active_hold(api, roster)
        first = _list_hearing(api, roster, case["petition"]["id"], FIRST_SLOT)

        record_outcome(api, HearingOutcome.CONTINUED.value, first["id"])

        after_first = read_petition(api, case["petition"]["id"])
        assert after_first["status"] == PetitionStatus.CONTINUED.value
        assert after_first["continuance_count"] == 1
        assert read_hearing(api, first["id"])["status"] == HearingStatus.CONTINUED.value

        _list_hearing(api, roster, case["petition"]["id"], SECOND_SLOT)

        relisted = read_petition(api, case["petition"]["id"])
        assert relisted["status"] == PetitionStatus.HEARING_SCHEDULED.value
        assert relisted["continuance_count"] == 1

    def test_the_third_continuance_is_refused_and_the_hearing_stays_scheduled(
        self, api, clock, roster
    ):
        """Two turns of the loop exhaust it, and the refusal changes nothing.

        PRD 3.4: "When the outcome is `CONTINUED`, the matter is put over to
        another date. The hearing moves `SCHEDULED → CONTINUED` and the petition
        moves `HEARING_SCHEDULED → CONTINUED`, with `continuance_count`
        recomputed as the number of that petition's hearings now in `CONTINUED`."

        Design: Difficulty/non_linear_state_machine/petition_continuance_cycle_returns_to_hearing_scheduled
        """
        case = _petition_on_an_active_hold(api, roster)
        first = _list_hearing(api, roster, case["petition"]["id"], FIRST_SLOT)
        record_outcome(api, HearingOutcome.CONTINUED.value, first["id"])
        second = _list_hearing(api, roster, case["petition"]["id"], SECOND_SLOT)
        record_outcome(api, HearingOutcome.CONTINUED.value, second["id"])

        assert (
            read_petition(api, case["petition"]["id"])["continuance_count"]
            == CONTINUANCE_LIMIT
        )

        third = _list_hearing(api, roster, case["petition"]["id"], THIRD_SLOT)
        refusal = api.record_hearing_outcome(
            COMPLIANCE_OFFICER_HEADERS,
            third["id"],
            hearing_outcome_payload(HearingOutcome.CONTINUED.value),
        )
        assert_error(refusal, ApiErrorId.CONTINUANCE_LIMIT_REACHED)

        untouched = read_hearing(api, third["id"])
        assert untouched["status"] == HearingStatus.SCHEDULED.value
        assert untouched["outcome"] == HearingOutcome.PENDING.value
        assert (
            read_petition(api, case["petition"]["id"])["continuance_count"]
            == CONTINUANCE_LIMIT
        )

    def test_continuances_move_no_hold_and_leave_one_hearing_on_the_docket(
        self, api, clock, roster
    ):
        """Only the currently scheduled listing counts toward the advocate's booked minutes.

        PRD 3.4: "Note that no hold transition accompanies a continuance, and the
        open petition continues to hold the statutory clock open against the
        sweep."

        Design: Difficulty/non_linear_state_machine/petition_continuance_cycle_returns_to_hearing_scheduled
        """
        case = _petition_on_an_active_hold(api, roster)
        first = _list_hearing(api, roster, case["petition"]["id"], FIRST_SLOT)
        record_outcome(api, HearingOutcome.CONTINUED.value, first["id"])
        second = _list_hearing(api, roster, case["petition"]["id"], SECOND_SLOT)
        record_outcome(api, HearingOutcome.CONTINUED.value, second["id"])
        _list_hearing(api, roster, case["petition"]["id"], THIRD_SLOT)

        assert_docket_minutes(
            read_clinician(api, roster.advocate["id"]), HEARING_DURATION
        )
        assert read_hold(api, case["hold"]["id"])["status"] == HoldStatus.ACTIVE.value
