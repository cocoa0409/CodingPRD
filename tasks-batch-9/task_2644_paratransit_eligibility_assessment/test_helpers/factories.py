"""Request payload factories.

Each factory returns only the fields a client is allowed to send for that
operation, with valid defaults, and every field can be overridden by keyword.
Server-minted values — identifiers, timestamps, versions, derived mirrors —
never appear here.

Passing ``None`` explicitly for an optional field keeps the key with a null
value, which is what the tests that probe the null-versus-absent distinction
need; to drop a key entirely, pop it from the returned dictionary.
"""
from .constants import DEFAULT_CLOCK

_SENTINEL = object()


def _merge(base, overrides):
    """Apply overrides onto a default payload, honouring explicit nulls."""
    payload = dict(base)
    for key, value in overrides.items():
        payload[key] = value
    return payload


# ---------------------------------------------------------------------------
# Riders
# ---------------------------------------------------------------------------
def applicant_payload(**overrides):
    """Register a rider. Optional: mobility_aid, primary_language, home_agency_name."""
    return _merge(
        {
            "full_name": "Rosa Vance",
            "date_of_birth": "1958-03-14",
            "residence_zone": "IN_SERVICE_AREA",
        },
        overrides,
    )


def out_of_area_applicant_payload(**overrides):
    """Register a rider who lives outside the complementary service area."""
    return _merge(
        {
            "full_name": "Vera Lindqvist",
            "date_of_birth": "1951-11-02",
            "residence_zone": "OUT_OF_SERVICE_AREA",
            "home_agency_name": "Northern Transit Authority",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Intake packets
# ---------------------------------------------------------------------------
def functional_answers(**overrides):
    """A complete five-key questionnaire."""
    return _merge(
        {
            "can_board_bus_steps": False,
            "can_navigate_unfamiliar_route": False,
            "max_walk_distance_meters": 250,
            "uses_mobility_aid_outdoors": True,
            "has_cognitive_impairment": False,
        },
        overrides,
    )


def application_payload(applicant_id, **overrides):
    """Open an intake packet. Optional: claimed_conditions."""
    return _merge(
        {
            "applicant_id": applicant_id,
            "application_type": "NEW",
            "functional_answers": functional_answers(),
            "claimed_conditions": ["limited stamina"],
        },
        overrides,
    )


def submit_payload(**overrides):
    """Submit or resubmit a packet. The questionnaire is optional here."""
    return _merge({}, overrides)


def return_incomplete_payload(**overrides):
    """Return a submitted packet as incomplete."""
    return _merge({"missing_items": ["proof of residence"]}, overrides)


# ---------------------------------------------------------------------------
# Professional verification
# ---------------------------------------------------------------------------
def verification_request_payload(**overrides):
    """Ask a licensed professional to verify the claimed limitations."""
    return _merge(
        {
            "provider_name": "Dr. Imogen Sarraf",
            "provider_type": "PHYSICIAN",
            "provider_license_number": "MD-448211",
        },
        overrides,
    )


def verification_accepted_payload(**overrides):
    """Record an accepted attestation."""
    return _merge(
        {
            "outcome": "ACCEPTED",
            "attests_conditions": ["limited stamina"],
            "attests_permanent": True,
        },
        overrides,
    )


def verification_insufficient_payload(**overrides):
    """Record an insufficient attestation."""
    return _merge(
        {
            "outcome": "INSUFFICIENT",
            "insufficiency_reason": "The attestation did not address outdoor mobility.",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Assessment slots, assessments, vehicles and rides
# ---------------------------------------------------------------------------
def assessment_slot_payload(**overrides):
    """Publish an in-person assessment slot. Optional: site_is_wheelchair_accessible."""
    return _merge(
        {
            "site_name": "Central Mobility Center",
            "evaluator_user_id": "eval-1",
            "starts_at": "2026-08-05T09:00:00Z",
            "ends_at": "2026-08-05T10:00:00Z",
            "capacity": 1,
        },
        overrides,
    )


def assessment_booking_payload(slot_id, **overrides):
    """Book the in-person assessment into a slot.

    Optional: requires_wheelchair_position, rescheduled_from_assessment_id.
    """
    return _merge({"slot_id": slot_id}, overrides)


def vehicle_payload(**overrides):
    """Register an accessible vehicle. Optional: wheelchair_positions,
    ambulatory_seats, status."""
    return _merge(
        {
            "vehicle_number": "V-0001",
            "wheelchair_positions": 1,
            "ambulatory_seats": 2,
        },
        overrides,
    )


def transportation_booking_payload(assessment_id, vehicle_id, **overrides):
    """Reserve the agency-provided ride. Optional: requires_wheelchair_position."""
    return _merge(
        {
            "assessment_id": assessment_id,
            "vehicle_id": vehicle_id,
            "pickup_window_start": "2026-08-05T08:00:00Z",
            "pickup_window_end": "2026-08-05T08:45:00Z",
        },
        overrides,
    )


def booking_cancel_payload(**overrides):
    """Cancel a reserved ride."""
    return _merge({"cancelled_reason": "Rider arranged their own ride"}, overrides)


def attendance_payload(attendance_status="ATTENDED", **overrides):
    """Record attendance at an in-person assessment."""
    return _merge({"attendance_status": attendance_status}, overrides)


def scores_payload(**overrides):
    """Record the evaluator's observed scores. Optional: evaluator_notes."""
    return _merge(
        {
            "board_alight_score": 2,
            "wayfinding_score": 3,
            "distance_meters_walked": 250,
            "heat_sensitivity_flag": True,
        },
        overrides,
    )


def sign_off_payload(**overrides):
    """Sign off on an assessment's scores; the acting header carries the signer."""
    return _merge({}, overrides)


# ---------------------------------------------------------------------------
# Determinations and trip conditions
# ---------------------------------------------------------------------------
def trip_condition_payload(**overrides):
    """One entry of a draft's trip_conditions array. Optional: threshold_value, note."""
    return _merge(
        {
            "condition_type": "HEAT_INDEX_ABOVE",
            "comparator": "GTE",
            "threshold_value": 90,
            "note": "Paratransit applies when the forecast heat index reaches 90F.",
        },
        overrides,
    )


def boolean_trip_condition_payload(condition_type="PRECIPITATION", **overrides):
    """One boolean trip condition, which must use the IS_TRUE comparator."""
    return _merge(
        {
            "condition_type": condition_type,
            "comparator": "IS_TRUE",
            "threshold_value": None,
            "note": "Paratransit applies in wet weather.",
        },
        overrides,
    )


def determination_draft_payload(expected_application_version, **overrides):
    """Draft a determination. Optional: trip_conditions."""
    return _merge(
        {
            "expected_application_version": expected_application_version,
            "category": "UNCONDITIONAL",
            "effective_date": "2026-08-05",
            "rationale": "Observed inability to board a fixed-route vehicle unaided.",
        },
        overrides,
    )


def issue_payload(**overrides):
    """Issue a drafted determination."""
    return _merge({}, overrides)


def trip_eligibility_check_payload(**overrides):
    """Evaluate one requested trip. Only trip_date is required."""
    return _merge({"trip_date": "2026-08-10"}, overrides)


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------
def appeal_payload(determination_id, **overrides):
    """File an appeal. Optional: request_hearing."""
    return _merge(
        {
            "determination_id": determination_id,
            "grounds": "The observed walking distance does not reflect a bad day.",
        },
        overrides,
    )


def assign_reviewer_payload(reviewer_user_id="rev-1", **overrides):
    """Assign an independent reviewer."""
    return _merge({"reviewer_user_id": reviewer_user_id}, overrides)


def paper_hearing_payload(**overrides):
    """Open the review on the paper branch, where hearing_at must be omitted."""
    return _merge({}, overrides)


def scheduled_hearing_payload(hearing_at="2026-08-25T14:00:00Z", **overrides):
    """Open the review on the hearing branch."""
    return _merge({"hearing_at": hearing_at}, overrides)


def appeal_decision_payload(outcome="UPHELD", **overrides):
    """Record the reviewer's disposition. granted_category is coupled to outcome."""
    payload = {"outcome": outcome, "decision_note": "Reviewed the full record."}
    if outcome in ("OVERTURNED", "MODIFIED"):
        payload["granted_category"] = "CONDITIONAL"
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Trip conduct
# ---------------------------------------------------------------------------
def trip_event_payload(applicant_id, **overrides):
    """Ingest one trip outcome."""
    return _merge(
        {
            "applicant_id": applicant_id,
            "trip_date": "2026-07-15",
            "event_type": "NO_SHOW",
        },
        overrides,
    )


def excuse_payload(**overrides):
    """Excuse a recorded missed trip."""
    return _merge({"excuse_reason": "Hospital admission on the trip date"}, overrides)


# ---------------------------------------------------------------------------
# Suspension proceedings
# ---------------------------------------------------------------------------
def suspension_proposal_payload(expected_applicant_version, **overrides):
    """Propose a suspension by hand. Optional: grounds_note."""
    return _merge(
        {
            "expected_applicant_version": expected_applicant_version,
            "review_window_end_date": "2026-08-01",
        },
        overrides,
    )


def send_notice_payload(**overrides):
    """Send the written suspension notice."""
    return _merge({}, overrides)


def rider_response_payload(**overrides):
    """Record the rider's written response to a notice."""
    return _merge(
        {"rider_response_note": "Two of the misses were hospital transfers."},
        overrides,
    )


def suspension_decision_payload(decision="UPHELD", **overrides):
    """Decide a proceeding. suspension_start_date is coupled to the decision."""
    payload = {"decision": decision}
    if decision == "UPHELD":
        payload["suspension_start_date"] = "2026-09-01"
    else:
        payload["suspension_start_date"] = None
    return _merge(payload, overrides)


def rescind_payload(**overrides):
    """Rescind a proceeding in UPHELD_PENDING or ACTIVE."""
    return _merge({}, overrides)


# ---------------------------------------------------------------------------
# Travel-training referrals
# ---------------------------------------------------------------------------
def referral_payload(**overrides):
    """Refer a rider to fixed-route travel training. Optional: determination_id."""
    return _merge({"referral_reason": "STAFF_REFERRAL"}, overrides)


def referral_response_payload(decision="ENROLLED", **overrides):
    """Record the rider's response to a referral."""
    return _merge({"decision": decision}, overrides)


def referral_completion_payload(fixed_route_competency_score=85, **overrides):
    """Record post-training competency."""
    return _merge(
        {"fixed_route_competency_score": fixed_route_competency_score}, overrides
    )


# ---------------------------------------------------------------------------
# Visitor eligibility
# ---------------------------------------------------------------------------
def visitor_eligibility_payload(**overrides):
    """Grant visitor eligibility to an out-of-area rider."""
    return _merge(
        {
            "home_agency_name": "Northern Transit Authority",
            "home_agency_certification_provided": True,
            "visit_start_date": "2026-08-01",
        },
        overrides,
    )


def service_day_payload(service_date="2026-08-01", **overrides):
    """Record one visitor service day."""
    return _merge({"service_date": service_date}, overrides)


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------
def clock_payload(current_utc=DEFAULT_CLOCK, **overrides):
    """Set the server's logical clock."""
    return _merge({"current_utc": current_utc}, overrides)
