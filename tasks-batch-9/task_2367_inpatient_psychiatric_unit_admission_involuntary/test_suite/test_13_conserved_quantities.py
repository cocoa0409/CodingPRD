"""Two aggregates that must be restored exactly, not reset and not left stale.

A discharge returns the one bed the placement took and reconciles the unit's
counters with its rows. A withdrawal returns only the withdrawn petition's hearing
minutes and leaves the other booking, and the hold, alone.
"""

from test_helpers import (
    BedStatus,
    COMPLIANCE_OFFICER_HEADERS,
    HearingStatus,
    HoldStatus,
    PetitionStatus,
    PlacementStatus,
    UnitPosture,
    active_hold_case,
    assert_ok,
    assert_page,
    assert_posture_threshold,
    assert_unit_availability,
    create_petition,
    discharge,
    read_admission,
    read_bed,
    read_clinician,
    read_hearing,
    read_hold,
    read_patient,
    read_petition,
    read_unit,
    scheduled_hearing,
    secure_discharge_plan,
    voluntary_placed_admission,
    withdraw_payload,
)

FOLLOW_UP_AT = "2026-09-10T09:00:00Z"
DISCHARGE_INSTANT = "2026-09-03T08:00:00.000Z"

FIRST_HEARING_START = "2026-09-04T10:00:00Z"
FIRST_HEARING_MINUTES = 60
SECOND_HEARING_START = "2026-09-04T11:30:00Z"
SECOND_HEARING_MINUTES = 30
WITHDRAW_REASON = "Treatment team no longer seeks an extension."


def _two_occupied_beds_and_a_secured_plan(api, roster, ward):
    """Two placed voluntary admissions, the first cleared for discharge."""
    leaving = voluntary_placed_admission(
        api,
        roster,
        ward,
        mrn="MRN-2367-B1",
        legal_name="Bess Lindqvist",
        age_years=33,
        gender_care_category="FEMALE",
        bed_id=ward.beds[0]["id"],
    )
    staying = voluntary_placed_admission(
        api,
        roster,
        ward,
        mrn="MRN-2367-B2",
        legal_name="Brigid Nyholm",
        age_years=47,
        gender_care_category="FEMALE",
        bed_id=ward.beds[1]["id"],
    )
    secure_discharge_plan(api, roster, leaving["admission"]["id"], FOLLOW_UP_AT)
    return leaving, staying


def _two_petitions_listed_with_one_advocate(api, roster):
    """Ninety booked minutes across two petitions on the same advocate's docket."""
    first = active_hold_case(
        api,
        roster,
        mrn="MRN-2367-K1",
        legal_name="Kira Ozdemir",
        age_years=44,
        gender_care_category="FEMALE",
    )
    second = active_hold_case(
        api,
        roster,
        mrn="MRN-2367-K2",
        legal_name="Kaleb Rusu",
        age_years=37,
        gender_care_category="MALE",
    )
    for case, start_at, minutes in (
        (first, FIRST_HEARING_START, FIRST_HEARING_MINUTES),
        (second, SECOND_HEARING_START, SECOND_HEARING_MINUTES),
    ):
        case["petition"] = create_petition(
            api, roster.psychiatrist_headers, case["hold"]["id"]
        )
        case["hearing"] = scheduled_hearing(
            api,
            roster.advocate_headers,
            case["petition"]["id"],
            roster.advocate["id"],
            start_at,
            minutes,
        )
    return first, second


class TestBedOccupancyConservation:
    """occupied plus raw available equals licensed, before and after the discharge."""

    def test_the_discharge_restores_the_counters_and_re_derives_the_posture(
        self, api, clock, roster, ward
    ):
        """A restricted unit holding one free bed reopens with both beds spendable.

        PRD 3.1: "Step two derives `posture` from `raw_available_bed_count` and
        nothing else: first compute a restriction threshold equal to the greater of
        1 and one fifth of `licensed_placement_bed_count` rounded down to a whole
        number; then the posture is `CLOSED` when `raw_available_bed_count` is zero,
        `RESTRICTED` when it is greater than zero but no greater than that
        threshold, and `OPEN` otherwise. Step three derives a safety reserve from
        the posture: one bed is held back when the posture is `RESTRICTED`, and none
        otherwise. Step four sets `effective_available_bed_count` to
        `raw_available_bed_count` minus the reserve, floored at zero."

        Design: Difficulty/compensating_invariant/bed_occupancy_conserved_across_place_and_discharge
        """
        leaving, _ = _two_occupied_beds_and_a_secured_plan(api, roster, ward)

        before = read_unit(api, ward.id)
        assert_unit_availability(before, licensed=3, raw_available=1, occupied=2)
        assert before["posture"] == UnitPosture.RESTRICTED.value
        assert_posture_threshold(3, 1)

        discharge(api, roster, leaving["admission"]["id"])

        after = read_unit(api, ward.id)
        assert_unit_availability(after, licensed=3, raw_available=2, occupied=1)
        assert after["posture"] == UnitPosture.OPEN.value
        assert (
            after["occupied_bed_count"] + after["raw_available_bed_count"]
            == after["licensed_placement_bed_count"]
        )

    def test_the_row_level_truth_reconciles_with_the_restored_counters(
        self, api, clock, roster, ward
    ):
        """Exactly one bed and one admission are still occupied, and the audit trail keeps the rest.

        PRD 3.8: "First, `placement_status` becomes `DISCHARGED` and `discharged_at`
        is stamped from the logical clock, while `bed_id` is deliberately retained
        on the record for audit rather than nulled. Second, because the admission
        has released its bed, that bed's `status` flips `OCCUPIED → AVAILABLE` and
        `Bed.version` increments by one."

        Design: Difficulty/compensating_invariant/bed_occupancy_conserved_across_place_and_discharge
        """
        leaving, staying = _two_occupied_beds_and_a_secured_plan(api, roster, ward)

        discharged = discharge(api, roster, leaving["admission"]["id"])

        assert discharged["placement_status"] == PlacementStatus.DISCHARGED.value
        assert discharged["discharged_at"] == DISCHARGE_INSTANT
        assert discharged["bed_id"] == ward.beds[0]["id"]

        assert (
            read_bed(api, ward.beds[0]["id"], ward.id)["status"]
            == BedStatus.AVAILABLE.value
        )
        assert (
            read_bed(api, ward.beds[1]["id"], ward.id)["status"]
            == BedStatus.OCCUPIED.value
        )
        assert (
            read_bed(api, ward.beds[2]["id"], ward.id)["status"]
            == BedStatus.AVAILABLE.value
        )

        survivor = read_admission(api, staying["admission"]["id"])
        assert survivor["placement_status"] == PlacementStatus.PLACED.value
        assert survivor["bed_id"] == ward.beds[1]["id"]

        assert_page(
            api.list_unit_beds(
                COMPLIANCE_OFFICER_HEADERS, ward.id, status=BedStatus.OCCUPIED.value
            ),
            1,
        )
        assert_page(
            api.list_admissions(
                COMPLIANCE_OFFICER_HEADERS,
                unit_id=ward.id,
                placement_status=PlacementStatus.PLACED.value,
            ),
            1,
        )

    def test_the_discharge_writes_the_unit_exactly_once(self, api, clock, roster, ward):
        """No promotion follows, so the counters are recomputed a single time.

        PRD 3.8: "Third, because a bed became `AVAILABLE`, the unit's
        `occupied_bed_count`, `raw_available_bed_count`, `posture` and
        `effective_available_bed_count` are recomputed and `Unit.version`
        increments by one."

        Design: Difficulty/compensating_invariant/bed_occupancy_conserved_across_place_and_discharge
        """
        leaving, _ = _two_occupied_beds_and_a_secured_plan(api, roster, ward)
        before_version = read_unit(api, ward.id)["version"]

        discharge(api, roster, leaving["admission"]["id"])

        assert read_unit(api, ward.id)["version"] == before_version + 1


class TestDocketMinutesConservation:
    """Withdrawal returns the vacated minutes and nothing more."""

    def test_withdrawal_vacates_only_its_own_hearing_and_returns_only_its_minutes(
        self, api, clock, roster
    ):
        """Sixty minutes come back off a ninety-minute docket, leaving thirty booked.

        PRD 3.4: "Withdrawing a petition in `HEARING_SCHEDULED` runs a three-link
        chain: the petition moves to `WITHDRAWN`; because the petition is
        withdrawn, every hearing of that petition still in `SCHEDULED` flips
        `SCHEDULED → VACATED`; and because those hearings have left `SCHEDULED`, the
        advocate's `booked_docket_minutes` is recomputed downward by the vacated
        `duration_minutes` and `Clinician.version` increments by one."

        Design: Difficulty/compensating_invariant/advocate_docket_minutes_released_by_petition_withdrawal
        """
        first, second = _two_petitions_listed_with_one_advocate(api, roster)
        before = read_clinician(api, roster.advocate["id"])
        assert (
            before["booked_docket_minutes"]
            == FIRST_HEARING_MINUTES + SECOND_HEARING_MINUTES
        )

        assert_ok(
            api.withdraw_petition(
                roster.advocate_headers,
                first["petition"]["id"],
                withdraw_payload(withdraw_reason=WITHDRAW_REASON),
            )
        )

        assert (
            read_petition(api, first["petition"]["id"])["status"]
            == PetitionStatus.WITHDRAWN.value
        )
        assert (
            read_petition(api, second["petition"]["id"])["status"]
            == PetitionStatus.HEARING_SCHEDULED.value
        )
        assert (
            read_hearing(api, first["hearing"]["id"])["status"]
            == HearingStatus.VACATED.value
        )
        assert (
            read_hearing(api, second["hearing"]["id"])["status"]
            == HearingStatus.SCHEDULED.value
        )

        after = read_clinician(api, roster.advocate["id"])
        assert after["booked_docket_minutes"] == SECOND_HEARING_MINUTES
        assert after["version"] == before["version"] + 1

    def test_withdrawing_a_petition_leaves_the_underlying_hold_running(
        self, api, clock, roster
    ):
        """The statutory detention is unaffected and one listing survives on the docket.

        PRD 3.4: "Withdrawing a petition in `HEARING_SCHEDULED` runs a three-link
        chain: the petition moves to `WITHDRAWN`; because the petition is
        withdrawn, every hearing of that petition still in `SCHEDULED` flips
        `SCHEDULED → VACATED`; and because those hearings have left `SCHEDULED`, the
        advocate's `booked_docket_minutes` is recomputed downward by the vacated
        `duration_minutes` and `Clinician.version` increments by one."

        PRD 3.3: "The remaining three terminal statuses are reached without a client
        asking for them. A granted extension petition moves the predecessor
        `ACTIVE → SUPERSEDED`; a denied one moves it `ACTIVE →
        DISCHARGED_BY_COURT` with `closure_reason` set to
        `COURT_DENIED_EXTENSION`; both are detailed in §3.4."

        Design: Difficulty/compensating_invariant/advocate_docket_minutes_released_by_petition_withdrawal
        """
        first, _ = _two_petitions_listed_with_one_advocate(api, roster)

        assert_ok(
            api.withdraw_petition(
                roster.advocate_headers,
                first["petition"]["id"],
                withdraw_payload(withdraw_reason=WITHDRAW_REASON),
            )
        )

        assert read_hold(api, first["hold"]["id"])["status"] == HoldStatus.ACTIVE.value
        assert read_patient(api, first["patient"]["id"])["active_hold_count"] == 1
        assert_page(
            api.list_hearings(
                COMPLIANCE_OFFICER_HEADERS,
                advocate_clinician_id=roster.advocate["id"],
                status=HearingStatus.SCHEDULED.value,
            ),
            1,
        )
