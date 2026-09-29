"""Rescinding an active hold answers the patient's pending discharge request.

Four links fire in the one request: the hold closes, the patient's hold count
falls to zero, the admission's legal axis flips to voluntary, the pending request
is granted, and the placement axis advances to discharge-ready.
"""

from test_helpers import (
    BedStatus,
    DischargeDecision,
    DischargeRequestStatus,
    HoldStatus,
    LegalStatus,
    PlacementStatus,
    RequestedBy,
    UnitPosture,
    assert_ok,
    assert_unit_availability,
    involuntary_placed_admission,
    read_admission,
    read_bed,
    read_discharge_request,
    read_patient,
    read_unit,
    request_discharge,
    rescind_payload,
)

RESCIND_REASON = "Criteria no longer met on reassessment."
RESPONSE_DEADLINE = "2026-09-08T14:00:00.000Z"


def _placed_patient_with_a_pending_request(api, roster, ward):
    """An involuntary placed admission carrying a pending patient discharge request."""
    case = involuntary_placed_admission(
        api,
        roster,
        ward,
        mrn="MRN-2367-R1",
        legal_name="Rita Callan",
        age_years=36,
        gender_care_category="FEMALE",
        bed_id=ward.beds[0]["id"],
    )
    case["request"] = request_discharge(
        api, roster, case["admission"]["id"], RequestedBy.PATIENT.value
    )
    return case


def _rescind(api, roster, hold_id):
    """The second psychiatrist rescinds the hold, which is who answers the request."""
    return assert_ok(
        api.rescind_hold(
            roster.second_psychiatrist_headers,
            hold_id,
            rescind_payload(rescind_reason=RESCIND_REASON),
        )
    )


class TestRescissionCascade:
    """One rescission, four links, one freed patient still in their bed."""

    def test_rescission_closes_the_hold_and_flips_the_admission_to_voluntary(
        self, api, clock, roster, ward
    ):
        """The reason is stored verbatim and the patient is left with no active hold.

        PRD 3.3: "Rescinding an `ACTIVE` hold starts a four-link chain: the
        patient's `active_hold_count` is recomputed and reaches 0 when no other
        `ACTIVE` hold remains; because the patient now has no `ACTIVE` hold, every
        admission of theirs in `PENDING_PLACEMENT` or `PLACED` flips `legal_status`
        from `INVOLUNTARY` to `VOLUNTARY`; because such an admission is now
        voluntary, every discharge request against it that is still `PENDING`
        flips to `GRANTED_DISCHARGE` with its `decision` set to `GRANT` and its
        `responding_clinician_id` set to the rescinding psychiatrist's
        `X-User-ID`; and because a discharge request was granted, that admission's
        `placement_status` advances `PLACED → DISCHARGE_READY`."

        Design: Difficulty/transitive_cascade/hold_rescission_cascades_to_voluntary_then_grants_discharge_request
        """
        case = _placed_patient_with_a_pending_request(api, roster, ward)

        rescinded = _rescind(api, roster, case["hold"]["id"])

        assert rescinded["status"] == HoldStatus.RESCINDED.value
        assert rescinded["closure_reason"] == RESCIND_REASON
        assert read_patient(api, case["patient"]["id"])["active_hold_count"] == 0
        assert (
            read_admission(api, case["admission"]["id"])["legal_status"]
            == LegalStatus.VOLUNTARY.value
        )

    def test_the_pending_request_is_answered_in_the_patients_favour(
        self, api, clock, roster, ward
    ):
        """The rescinding psychiatrist is recorded as the responder to a request they never read.

        PRD 2.8: "Closing a hold recomputes the patient's `active_hold_count`; if
        that leaves the patient with no `ACTIVE` hold, each of the patient's
        admissions still in `PENDING_PLACEMENT` or `PLACED` flips its legal axis
        from `INVOLUNTARY` to `VOLUNTARY`; because those admissions are now
        voluntary, any `PENDING` discharge request against them is answered in the
        patient's favour; and because a discharge request was granted, the
        admission's placement axis advances."

        Design: Difficulty/transitive_cascade/hold_rescission_cascades_to_voluntary_then_grants_discharge_request
        """
        case = _placed_patient_with_a_pending_request(api, roster, ward)

        _rescind(api, roster, case["hold"]["id"])

        answered = read_discharge_request(api, case["request"]["id"])
        assert answered["status"] == DischargeRequestStatus.GRANTED_DISCHARGE.value
        assert answered["decision"] == DischargeDecision.GRANT.value
        assert answered["responding_clinician_id"] == roster.second_psychiatrist["id"]

    def test_the_granted_request_advances_placement_while_the_bed_stays_occupied(
        self, api, clock, roster, ward
    ):
        """Discharge-ready is not discharged: the bed is still held and the unit still open.

        PRD 3.8: "Granting moves the request `PENDING → GRANTED_DISCHARGE` and
        advances the admission's placement axis: an admission in `PLACED` becomes
        `DISCHARGE_READY` while keeping its bed `OCCUPIED` until the physical
        discharge, and an admission still in `PENDING_PLACEMENT` becomes
        `CANCELLED`, which changes no unit counter because no bed was ever held."

        Design: Difficulty/transitive_cascade/hold_rescission_cascades_to_voluntary_then_grants_discharge_request
        """
        case = _placed_patient_with_a_pending_request(api, roster, ward)

        _rescind(api, roster, case["hold"]["id"])

        admission = read_admission(api, case["admission"]["id"])
        assert admission["placement_status"] == PlacementStatus.DISCHARGE_READY.value
        assert admission["discharged_at"] is None
        assert (
            read_bed(api, ward.beds[0]["id"], ward.id)["status"]
            == BedStatus.OCCUPIED.value
        )

        unit = read_unit(api, ward.id)
        assert_unit_availability(unit, licensed=3, raw_available=2, occupied=1)
        assert unit["posture"] == UnitPosture.OPEN.value

    def test_the_request_carried_a_twenty_four_business_hour_response_deadline(
        self, api, clock, roster, ward
    ):
        """A Thursday-morning request is due at two on the Tuesday after the holiday.

        PRD 3.8: "The response deadline is 24 business hours from `requested_at`,
        measured on the business calendar of §2.6 — nine hours a day between
        08:00:00 and 17:00:00 UTC, with Saturdays, Sundays and the recognized
        holidays skipped entirely."

        PRD 3.8: "Whatever remains between the candidate and that
        day's close is the day's available time; if it covers the remaining budget,
        the deadline is the candidate plus the remaining budget and the computation
        ends; otherwise the available time is subtracted from the budget and the
        candidate moves to the next day at `08:00:00.000Z`."

        Design: Difficulty/transitive_cascade/hold_rescission_cascades_to_voluntary_then_grants_discharge_request
        """
        case = _placed_patient_with_a_pending_request(api, roster, ward)

        assert case["request"]["response_deadline_at"] == RESPONSE_DEADLINE
