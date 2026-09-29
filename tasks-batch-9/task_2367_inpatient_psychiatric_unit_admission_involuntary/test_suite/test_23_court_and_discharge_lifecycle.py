"""Terminal rows refuse further work, and the refusal names the right guard.

A withdrawn petition vacates its listing and then locks: no second withdrawal, no
new listing, and an outcome attempt reports the petition guard rather than the
hearing guard. A continued hearing is likewise closed once its successor is booked.
A discharge request admits one open row per admission and one response.
"""

from test_helpers import (
    ApiErrorId,
    COMPLIANCE_OFFICER_HEADERS,
    DischargeDecision,
    DischargeRequestStatus,
    HearingOutcome,
    HearingStatus,
    HoldStatus,
    LegalStatus,
    PetitionStatus,
    PlacementStatus,
    RequestedBy,
    UnitPosture,
    active_hold_case,
    assert_created,
    assert_docket_minutes,
    assert_error,
    assert_ok,
    assert_page,
    assert_unit_availability,
    build_ward,
    create_admission,
    create_petition,
    discharge_response_payload,
    hearing_payload,
    read_admission,
    read_clinician,
    read_discharge_request,
    read_hearing,
    read_hold,
    read_petition,
    read_unit,
    record_outcome,
    request_discharge,
    scheduled_hearing,
    voluntary_case,
    withdraw_payload,
)

RELEASE_DEADLINE = "2026-09-06T08:00:00.000Z"

WITHDRAWN_HEARING_START = "2026-09-04T10:00:00Z"
WITHDRAWN_HEARING_MINUTES = 60
REPLACEMENT_HEARING_START = "2026-09-04T13:00:00Z"

FIRST_LISTING_START = "2026-09-04T09:00:00Z"
SECOND_LISTING_START = "2026-09-04T11:00:00Z"
LISTING_MINUTES = 30

REQUEST_UNIT = "Ward 24 Requests"
NO_BEDS = ()
REQUESTED_AT = "2026-09-03T08:00:00.000Z"
RESPONSE_DEADLINE = "2026-09-08T14:00:00.000Z"


def _petition_with_one_listing(api, roster, *, mrn, legal_name, age_years, gender, start_at, minutes):
    """An active hold, a filed petition and one hearing booked on the advocate's docket."""
    case = active_hold_case(
        api,
        roster,
        mrn=mrn,
        legal_name=legal_name,
        age_years=age_years,
        gender_care_category=gender,
    )
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
    return case


def _pending_voluntary_admission(api, roster, unit_id, *, mrn, legal_name, age_years, gender):
    """A voluntary admission opened on a bedless unit, so it stays in PENDING_PLACEMENT."""
    case = voluntary_case(
        api,
        roster,
        mrn=mrn,
        legal_name=legal_name,
        age_years=age_years,
        gender_care_category=gender,
        danger_to_self=False,
        danger_to_others=True,
        grave_disability=True,
    )
    case["admission"] = create_admission(
        api,
        roster,
        case["patient"]["id"],
        case["evaluation"]["id"],
        unit_id,
        requested_legal_status=LegalStatus.VOLUNTARY.value,
    )
    return case


class TestPetitionWithdrawalLocksTheRow:
    """Withdrawal vacates the listing, and the withdrawn petition accepts nothing further."""

    def test_withdrawal_vacates_the_listing_and_then_refuses_every_later_action(
        self, api, clock, roster
    ):
        """A second withdrawal, a fresh listing and an outcome all report the petition guard.

        PRD 3.4: "Withdrawing a petition in `HEARING_SCHEDULED` runs a three-link
        chain: the petition moves to `WITHDRAWN`; because the petition is withdrawn,
        every hearing of that petition still in `SCHEDULED` flips `SCHEDULED →
        VACATED`; and because those hearings have left `SCHEDULED`, the advocate's
        `booked_docket_minutes` is recomputed downward by the vacated
        `duration_minutes` and `Clinician.version` increments by one."

        PRD 2.9: "`ERR_PETITION_NOT_OPEN` — the petition is in the status the action
        needs: either `FILED` or `CONTINUED` for hearing scheduling; `FILED`,
        `HEARING_SCHEDULED` or `CONTINUED` for withdrawal; and `HEARING_SCHEDULED`
        for outcome recording."

        Design: Corner/state_machines/petition_withdrawal_vacates_hearing_and_locks_the_row
        """
        case = _petition_with_one_listing(
            api,
            roster,
            mrn="MRN-2367-WD",
            legal_name="Withdraw Case",
            age_years=52,
            gender="MALE",
            start_at=WITHDRAWN_HEARING_START,
            minutes=WITHDRAWN_HEARING_MINUTES,
        )
        assert case["hold"]["release_deadline_at"] == RELEASE_DEADLINE
        assert case["hearing"]["status"] == HearingStatus.SCHEDULED.value
        assert_docket_minutes(
            read_clinician(api, roster.advocate["id"]), WITHDRAWN_HEARING_MINUTES
        )

        assert_ok(
            api.withdraw_petition(
                roster.psychiatrist_headers, case["petition"]["id"], withdraw_payload()
            )
        )

        assert (
            read_petition(api, case["petition"]["id"])["status"]
            == PetitionStatus.WITHDRAWN.value
        )
        assert (
            read_hearing(api, case["hearing"]["id"])["status"]
            == HearingStatus.VACATED.value
        )
        assert_docket_minutes(read_clinician(api, roster.advocate["id"]), 0)
        assert read_hold(api, case["hold"]["id"])["status"] == HoldStatus.ACTIVE.value

        second_withdrawal = api.withdraw_petition(
            roster.advocate_headers, case["petition"]["id"], withdraw_payload()
        )
        assert_error(second_withdrawal, ApiErrorId.PETITION_NOT_OPEN)

        new_listing = api.create_hearing(
            roster.advocate_headers,
            hearing_payload(
                petition_id=case["petition"]["id"],
                advocate_clinician_id=roster.advocate["id"],
                scheduled_start_at=REPLACEMENT_HEARING_START,
                duration_minutes=WITHDRAWN_HEARING_MINUTES,
            ),
        )
        assert_error(new_listing, ApiErrorId.PETITION_NOT_OPEN)
        assert_docket_minutes(read_clinician(api, roster.advocate["id"]), 0)

    def test_an_outcome_on_the_vacated_hearing_reports_the_petition_before_the_hearing(
        self, api, clock, roster
    ):
        """Both guards fail at once, and the earlier numbered check is the one reported.

        PRD 2.9: "Many operations are guarded by several checks at once, and which
        error a client sees is part of the contract. Checks are evaluated in the
        following fixed order, and the first failing check terminates the request."

        PRD 3.4: "A `ComplianceOfficer` records the court's disposition against a
        `SCHEDULED` hearing, supplying an `outcome` and a `findings_note`. The hearing
        must be in `SCHEDULED` — otherwise `ERR_HEARING_NOT_SCHEDULED` — and its
        petition must be in `HEARING_SCHEDULED`, otherwise `ERR_PETITION_NOT_OPEN`."

        Design: Corner/state_machines/petition_withdrawal_vacates_hearing_and_locks_the_row
        """
        case = _petition_with_one_listing(
            api,
            roster,
            mrn="MRN-2367-WD",
            legal_name="Withdraw Case",
            age_years=52,
            gender="MALE",
            start_at=WITHDRAWN_HEARING_START,
            minutes=WITHDRAWN_HEARING_MINUTES,
        )
        assert_ok(
            api.withdraw_petition(
                roster.psychiatrist_headers, case["petition"]["id"], withdraw_payload()
            )
        )

        refusal = api.record_hearing_outcome(
            COMPLIANCE_OFFICER_HEADERS,
            case["hearing"]["id"],
            {
                "outcome": HearingOutcome.GRANTED.value,
                "findings_note": "Court granted the extension.",
            },
        )

        assert_error(refusal, ApiErrorId.PETITION_NOT_OPEN)
        vacated = read_hearing(api, case["hearing"]["id"])
        assert vacated["status"] == HearingStatus.VACATED.value
        assert vacated["outcome"] == HearingOutcome.PENDING.value
        assert vacated["findings_note"] is None
        assert read_hold(api, case["hold"]["id"])["status"] == HoldStatus.ACTIVE.value


class TestContinuedHearingIsSuperseded:
    """Once a continuance is booked again, the earlier listing is closed for good."""

    def test_an_outcome_on_the_continued_hearing_returns_hearing_not_scheduled(
        self, api, clock, roster
    ):
        """The petition is open again on its successor, so only the hearing guard fails.

        PRD 3.4: "When the outcome is `CONTINUED`, the matter is put over to another
        date. The hearing moves `SCHEDULED → CONTINUED` and the petition moves
        `HEARING_SCHEDULED → CONTINUED`, with `continuance_count` recomputed as the
        number of that petition's hearings now in `CONTINUED`."

        PRD 2.9: "`ERR_HEARING_NOT_SCHEDULED` — the hearing is in `SCHEDULED`; on
        outcome recording."

        Design: Corner/state_machines/record_outcome_on_superseded_hearing_returns_hearing_not_scheduled
        """
        case = _petition_with_one_listing(
            api,
            roster,
            mrn="MRN-2367-SH",
            legal_name="Superseded Hearing",
            age_years=45,
            gender="FEMALE",
            start_at=FIRST_LISTING_START,
            minutes=LISTING_MINUTES,
        )
        continued = record_outcome(
            api, HearingOutcome.CONTINUED.value, case["hearing"]["id"]
        )
        assert continued["status"] == HearingStatus.CONTINUED.value
        assert (
            read_petition(api, case["petition"]["id"])["status"]
            == PetitionStatus.CONTINUED.value
        )

        successor = assert_created(
            api.create_hearing(
                roster.advocate_headers,
                hearing_payload(
                    petition_id=case["petition"]["id"],
                    advocate_clinician_id=roster.advocate["id"],
                    scheduled_start_at=SECOND_LISTING_START,
                    duration_minutes=LISTING_MINUTES,
                ),
            )
        )

        refusal = api.record_hearing_outcome(
            COMPLIANCE_OFFICER_HEADERS,
            case["hearing"]["id"],
            {
                "outcome": HearingOutcome.GRANTED.value,
                "findings_note": "Court granted the extension.",
            },
        )
        assert_error(refusal, ApiErrorId.HEARING_NOT_SCHEDULED)

        superseded = read_hearing(api, case["hearing"]["id"])
        assert superseded["status"] == HearingStatus.CONTINUED.value
        assert (
            read_hearing(api, successor["id"])["status"] == HearingStatus.SCHEDULED.value
        )
        reopened = read_petition(api, case["petition"]["id"])
        assert reopened["status"] == PetitionStatus.HEARING_SCHEDULED.value
        assert reopened["continuance_count"] == 1
        assert_docket_minutes(
            read_clinician(api, roster.advocate["id"]), LISTING_MINUTES
        )


class TestDischargeRequestLifecycle:
    """One open request per admission, and one response per request."""

    def test_a_second_request_is_refused_while_the_first_is_still_pending(
        self, api, clock, roster
    ):
        """The duplicate leaves a single row on the admission's request listing.

        PRD 3.8: "A `ChargeNurse` or a `PatientRightsAdvocate` records the request
        against an `admission_id` with a `requested_by` value of `PATIENT` or
        `GUARDIAN`; the server stamps `requested_at` from the logical clock and
        `recorded_by_clinician_id` from the header, sets both `decision` and `status`
        to `PENDING`, and leaves `responding_clinician_id` and `response_note` null.
        Only one request per admission may be open at a time: a second recorded while
        one is still `PENDING` is refused with `ERR_DUPLICATE_DISCHARGE_REQUEST`."

        PRD 3.8: "The response deadline is 24 business hours from `requested_at`,
        measured on the business calendar of §2.6 — nine hours a day between 08:00:00
        and 17:00:00 UTC, with Saturdays, Sundays and the recognized holidays skipped
        entirely."

        Design: Corner/state_machines/discharge_request_lifecycle_rejects_duplicate_and_repeat_response
        """
        ward = build_ward(
            api,
            name=REQUEST_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=0,
            bed_specs=NO_BEDS,
        )
        case = _pending_voluntary_admission(
            api,
            roster,
            ward.id,
            mrn="MRN-2367-RQ",
            legal_name="Request Twice",
            age_years=37,
            gender="FEMALE",
        )
        first = request_discharge(api, roster, case["admission"]["id"])

        assert first["status"] == DischargeRequestStatus.PENDING.value
        assert first["decision"] == DischargeDecision.PENDING.value
        assert first["requested_by"] == RequestedBy.PATIENT.value
        assert first["requested_at"] == REQUESTED_AT
        assert first["response_deadline_at"] == RESPONSE_DEADLINE
        assert first["recorded_by_clinician_id"] == roster.charge_nurse["id"]
        assert first["responding_clinician_id"] is None
        assert first["response_note"] is None

        duplicate = api.create_discharge_request(
            roster.advocate_headers,
            {
                "admission_id": case["admission"]["id"],
                "requested_by": RequestedBy.GUARDIAN.value,
            },
        )
        assert_error(duplicate, ApiErrorId.DUPLICATE_DISCHARGE_REQUEST)
        assert_page(
            api.list_discharge_requests(
                COMPLIANCE_OFFICER_HEADERS, admission_id=case["admission"]["id"]
            ),
            1,
        )

    def test_the_grant_cancels_the_queued_admission_and_closes_the_request(
        self, api, clock, roster
    ):
        """A second response and a fresh request are both refused after the grant.

        PRD 3.8: "Granting moves the request `PENDING → GRANTED_DISCHARGE` and
        advances the admission's placement axis: an admission in `PLACED` becomes
        `DISCHARGE_READY` while keeping its bed `OCCUPIED` until the physical
        discharge, and an admission still in `PENDING_PLACEMENT` becomes `CANCELLED`,
        which changes no unit counter because no bed was ever held."

        PRD 2.9: "`ERR_DISCHARGE_REQUEST_NOT_PENDING` — the request is in `PENDING`;
        on responding."

        Design: Corner/state_machines/discharge_request_lifecycle_rejects_duplicate_and_repeat_response
        """
        ward = build_ward(
            api,
            name=REQUEST_UNIT,
            gender_mixing_policy="MIXED_ALLOWED",
            seclusion_room_count=0,
            bed_specs=NO_BEDS,
        )
        case = _pending_voluntary_admission(
            api,
            roster,
            ward.id,
            mrn="MRN-2367-RQ",
            legal_name="Request Twice",
            age_years=37,
            gender="FEMALE",
        )
        first = request_discharge(api, roster, case["admission"]["id"])

        granted = assert_ok(
            api.respond_to_discharge_request(
                roster.psychiatrist_headers,
                first["id"],
                discharge_response_payload(decision=DischargeDecision.GRANT.value),
            )
        )
        assert granted["status"] == DischargeRequestStatus.GRANTED_DISCHARGE.value
        assert granted["decision"] == DischargeDecision.GRANT.value
        assert granted["responding_clinician_id"] == roster.psychiatrist["id"]
        assert (
            read_admission(api, case["admission"]["id"])["placement_status"]
            == PlacementStatus.CANCELLED.value
        )

        unit = read_unit(api, ward.id)
        assert_unit_availability(unit, licensed=0, raw_available=0, occupied=0)
        assert unit["posture"] == UnitPosture.CLOSED.value

        second_response = api.respond_to_discharge_request(
            roster.psychiatrist_headers,
            first["id"],
            discharge_response_payload(decision=DischargeDecision.DENY.value),
        )
        assert_error(second_response, ApiErrorId.DISCHARGE_REQUEST_NOT_PENDING)
        assert (
            read_discharge_request(api, first["id"])["decision"]
            == DischargeDecision.GRANT.value
        )

        later_request = api.create_discharge_request(
            roster.charge_nurse_headers,
            {
                "admission_id": case["admission"]["id"],
                "requested_by": RequestedBy.PATIENT.value,
            },
        )
        assert_error(later_request, ApiErrorId.ADMISSION_NOT_DISCHARGEABLE)
