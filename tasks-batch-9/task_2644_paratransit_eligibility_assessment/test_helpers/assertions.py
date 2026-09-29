"""Entity-shape and domain-invariant assertions.

The shape helpers check that a returned record carries every field the contract
declares for that entity, and that the identity, timestamp and version
conventions hold. The invariant helpers check the conserved quantities and the
derived mirrors the contract describes.
"""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import SUSPENSION_LADDER_DAYS, TERM_DAYS_BY_CATEGORY

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


# ---------------------------------------------------------------------------
# Primitive conventions
# ---------------------------------------------------------------------------
def assert_server_minted_id(record):
    """The identifier is a server-minted UUID and carries no type prefix."""
    value = record.get("id")
    assert isinstance(value, str), f"id must be a string, got {value!r}"
    assert is_valid_uuid(value), f"id must be a UUID, got {value!r}"
    assert ":" not in value and "_" not in value, (
        f"id must carry no type prefix, got {value!r}"
    )


def assert_creation_timestamp(value):
    """An ISO 8601 UTC timestamp with exactly three fractional digits."""
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    assert _TIMESTAMP_RE.match(value), (
        f"expected an ISO 8601 UTC timestamp with three fractional digits, got {value!r}"
    )
    assert is_iso8601_timestamp(value), f"not a parseable ISO 8601 instant: {value!r}"


def assert_calendar_date(value):
    """An ISO 8601 calendar date in year-month-day form."""
    assert isinstance(value, str), f"expected a date string, got {value!r}"
    assert _DATE_RE.match(value), f"expected a YYYY-MM-DD date, got {value!r}"


def assert_fields_present(record, fields, entity_name):
    """Every named field appears in the representation, null or not."""
    missing = [field for field in fields if field not in record]
    assert not missing, f"{entity_name} is missing declared fields: {missing}"


def assert_fields_absent(record, fields, entity_name):
    """None of the named fields appears in the representation."""
    present = [field for field in fields if field in record]
    assert not present, f"{entity_name} must not carry: {present}"


def assert_versioned_record(record, entity_name, expected_version=None):
    """Identity, creation stamp, update stamp and version, the common shape."""
    assert_server_minted_id(record)
    assert_creation_timestamp(record.get("created_at"))
    assert_creation_timestamp(record.get("updated_at"))
    assert isinstance(record.get("version"), int), (
        f"{entity_name}.version must be an integer, got {record.get('version')!r}"
    )
    assert record["version"] >= 1, f"{entity_name}.version starts at 1"
    if expected_version is not None:
        assert record["version"] == expected_version, (
            f"{entity_name}.version expected {expected_version}, got {record['version']}"
        )


# ---------------------------------------------------------------------------
# Declared field sets, entity by entity
# ---------------------------------------------------------------------------
APPLICANT_FIELDS = [
    "id",
    "full_name",
    "date_of_birth",
    "residence_zone",
    "mobility_aid",
    "primary_language",
    "home_agency_name",
    "current_eligibility_status",
    "eligibility_category",
    "active_determination_id",
    "service_status",
    "continued_service_during_appeal",
    "fixed_route_competency_confirmed",
    "no_show_points_event_basis",
    "no_show_points_report_basis",
    "chargeable_miss_count_90d",
    "scheduled_trip_count_90d",
    "no_show_ratio_pct",
    "prior_upheld_suspension_count",
    "suspension_days_ledger_total",
    "created_at",
    "updated_at",
    "version",
]

APPLICATION_FIELDS = [
    "id",
    "applicant_id",
    "application_type",
    "status",
    "functional_answers",
    "claimed_conditions",
    "attests_permanent",
    "submitted_at",
    "completeness_established_at",
    "determination_due_date",
    "presumptive_granted_at",
    "missing_items",
    "resubmission_count",
    "verification_excluded_days",
    "applicant_delay_days",
    "days_pending_statutory",
    "days_pending_net_agency",
    "created_at",
    "updated_at",
    "version",
]

VERIFICATION_FIELDS = [
    "id",
    "application_id",
    "provider_name",
    "provider_type",
    "provider_license_number",
    "status",
    "requested_at",
    "received_at",
    "wait_days",
    "attests_conditions",
    "attests_permanent",
    "insufficiency_reason",
    "created_at",
    "updated_at",
    "version",
]

ASSESSMENT_SLOT_FIELDS = [
    "id",
    "site_name",
    "evaluator_user_id",
    "starts_at",
    "ends_at",
    "capacity",
    "site_is_wheelchair_accessible",
    "booked_count",
    "status",
    "created_at",
    "updated_at",
    "version",
]

ASSESSMENT_FIELDS = [
    "id",
    "application_id",
    "slot_id",
    "attendance_status",
    "scoring_status",
    "requires_wheelchair_position",
    "rescheduled_from_assessment_id",
    "attendance_recorded_at",
    "board_alight_score",
    "wayfinding_score",
    "distance_meters_walked",
    "heat_sensitivity_flag",
    "evaluator_notes",
    "recommended_category",
    "recommended_term_days",
    "scored_by_user_id",
    "signed_off_by_user_id",
    "created_at",
    "updated_at",
    "version",
]

VEHICLE_FIELDS = [
    "id",
    "vehicle_number",
    "wheelchair_positions",
    "ambulatory_seats",
    "status",
    "open_wheelchair_reservations",
    "open_ambulatory_reservations",
    "created_at",
    "updated_at",
    "version",
]

BOOKING_FIELDS = [
    "id",
    "assessment_id",
    "vehicle_id",
    "pickup_window_start",
    "pickup_window_end",
    "requires_wheelchair_position",
    "status",
    "cancelled_reason",
    "created_at",
    "updated_at",
    "version",
]

DETERMINATION_FIELDS = [
    "id",
    "application_id",
    "applicant_id",
    "category",
    "status",
    "origin",
    "effective_date",
    "term_days",
    "issued_at",
    "expires_at",
    "rationale",
    "determined_by_user_id",
    "under_appeal",
    "trip_condition_count",
    "fixed_route_competency_confirmed",
    "created_at",
    "updated_at",
    "version",
]

TRIP_CONDITION_FIELDS = [
    "id",
    "determination_id",
    "condition_type",
    "comparator",
    "threshold_value",
    "note",
    "created_at",
]

APPEAL_FIELDS = [
    "id",
    "determination_id",
    "grounds",
    "request_hearing",
    "status",
    "filed_at",
    "filing_deadline_date",
    "reviewer_user_id",
    "hearing_at",
    "heard_at",
    "decision_due_date",
    "outcome",
    "granted_category",
    "decided_at",
    "decision_note",
    "continued_service_extended",
    "created_at",
    "updated_at",
    "version",
]

TRIP_EVENT_FIELDS = [
    "id",
    "applicant_id",
    "trip_date",
    "event_type",
    "points_assessed",
    "excused",
    "excuse_reason",
    "recorded_at",
    "created_at",
    "updated_at",
    "version",
]

PROCEEDING_FIELDS = [
    "id",
    "applicant_id",
    "status",
    "origin",
    "proposed_by_user_id",
    "grounds_note",
    "review_window_end_date",
    "points_at_proposal",
    "notice_sent_at",
    "response_deadline_date",
    "rider_response_at",
    "rider_response_note",
    "decision",
    "decided_by_user_id",
    "duration_days",
    "suspension_start_date",
    "suspension_end_date",
    "days_served",
    "days_forgiven",
    "created_at",
    "updated_at",
    "version",
]

REFERRAL_FIELDS = [
    "id",
    "applicant_id",
    "determination_id",
    "referral_reason",
    "status",
    "referral_response_deadline_date",
    "fixed_route_competency_score",
    "completed_at",
    "withdrawal_reason",
    "created_at",
    "updated_at",
    "version",
]

VISITOR_ELIGIBILITY_FIELDS = [
    "id",
    "applicant_id",
    "home_agency_name",
    "home_agency_certification_provided",
    "visit_start_date",
    "status",
    "service_dates",
    "days_used_365",
    "days_remaining_365",
    "created_at",
    "updated_at",
    "version",
]


# ---------------------------------------------------------------------------
# Per-entity shape assertions
# ---------------------------------------------------------------------------
def assert_applicant_shape(record, expected_version=None):
    assert_fields_present(record, APPLICANT_FIELDS, "Applicant")
    assert_versioned_record(record, "Applicant", expected_version)
    assert_calendar_date(record["date_of_birth"])


def assert_application_shape(record, expected_version=None):
    assert_fields_present(record, APPLICATION_FIELDS, "Application")
    assert_versioned_record(record, "Application", expected_version)


def assert_verification_shape(record, expected_version=None):
    assert_fields_present(record, VERIFICATION_FIELDS, "ProfessionalVerification")
    assert_versioned_record(record, "ProfessionalVerification", expected_version)


def assert_assessment_slot_shape(record, expected_version=None):
    assert_fields_present(record, ASSESSMENT_SLOT_FIELDS, "AssessmentSlot")
    assert_versioned_record(record, "AssessmentSlot", expected_version)


def assert_assessment_shape(record, expected_version=None):
    assert_fields_present(record, ASSESSMENT_FIELDS, "FunctionalAssessment")
    assert_versioned_record(record, "FunctionalAssessment", expected_version)


def assert_vehicle_shape(record, expected_version=None):
    assert_fields_present(record, VEHICLE_FIELDS, "Vehicle")
    assert_versioned_record(record, "Vehicle", expected_version)


def assert_booking_shape(record, expected_version=None):
    assert_fields_present(record, BOOKING_FIELDS, "TransportationBooking")
    assert_versioned_record(record, "TransportationBooking", expected_version)


def assert_determination_shape(record, expected_version=None):
    assert_fields_present(record, DETERMINATION_FIELDS, "Determination")
    assert_versioned_record(record, "Determination", expected_version)


def assert_trip_condition_shape(record):
    """A trip condition is immutable: only an identifier and a creation stamp.

    Both an update stamp and a version are absent from its representation.
    """
    assert_fields_present(record, TRIP_CONDITION_FIELDS, "TripCondition")
    assert_server_minted_id(record)
    assert_creation_timestamp(record["created_at"])
    assert_fields_absent(record, ["updated_at", "version"], "TripCondition")


def assert_appeal_shape(record, expected_version=None):
    assert_fields_present(record, APPEAL_FIELDS, "Appeal")
    assert_versioned_record(record, "Appeal", expected_version)


def assert_trip_event_shape(record, expected_version=None):
    assert_fields_present(record, TRIP_EVENT_FIELDS, "TripEvent")
    assert_versioned_record(record, "TripEvent", expected_version)


def assert_proceeding_shape(record, expected_version=None):
    assert_fields_present(record, PROCEEDING_FIELDS, "SuspensionProceeding")
    assert_versioned_record(record, "SuspensionProceeding", expected_version)


def assert_referral_shape(record, expected_version=None):
    assert_fields_present(record, REFERRAL_FIELDS, "TravelTrainingReferral")
    assert_versioned_record(record, "TravelTrainingReferral", expected_version)


def assert_visitor_eligibility_shape(record, expected_version=None):
    assert_fields_present(record, VISITOR_ELIGIBILITY_FIELDS, "VisitorEligibility")
    assert_versioned_record(record, "VisitorEligibility", expected_version)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_conduct_mirrors(
    applicant,
    event_basis=None,
    report_basis=None,
    miss_count=None,
    scheduled_count=None,
    ratio_pct=None,
):
    """Check whichever of the five recomputed conduct mirrors a test pins."""
    if event_basis is not None:
        assert applicant["no_show_points_event_basis"] == event_basis, (
            f"no_show_points_event_basis expected {event_basis}, "
            f"got {applicant['no_show_points_event_basis']}"
        )
    if report_basis is not None:
        assert applicant["no_show_points_report_basis"] == report_basis, (
            f"no_show_points_report_basis expected {report_basis}, "
            f"got {applicant['no_show_points_report_basis']}"
        )
    if miss_count is not None:
        assert applicant["chargeable_miss_count_90d"] == miss_count, (
            f"chargeable_miss_count_90d expected {miss_count}, "
            f"got {applicant['chargeable_miss_count_90d']}"
        )
    if scheduled_count is not None:
        assert applicant["scheduled_trip_count_90d"] == scheduled_count, (
            f"scheduled_trip_count_90d expected {scheduled_count}, "
            f"got {applicant['scheduled_trip_count_90d']}"
        )
    if ratio_pct is not None:
        actual = applicant["no_show_ratio_pct"]
        assert abs(actual - ratio_pct) < 0.05, (
            f"no_show_ratio_pct expected {ratio_pct}, got {actual}"
        )


def assert_eligibility_mirrors(applicant, status, category, active_determination_id):
    """Check the three eligibility mirrors together."""
    assert applicant["current_eligibility_status"] == status, (
        f"current_eligibility_status expected {status}, "
        f"got {applicant['current_eligibility_status']}"
    )
    assert applicant["eligibility_category"] == category, (
        f"eligibility_category expected {category}, "
        f"got {applicant['eligibility_category']}"
    )
    assert applicant["active_determination_id"] == active_determination_id, (
        f"active_determination_id expected {active_determination_id}, "
        f"got {applicant['active_determination_id']}"
    )


def assert_vehicle_counters(vehicle, wheelchair, ambulatory):
    """Both conserved open-reservation counters at once."""
    assert vehicle["open_wheelchair_reservations"] == wheelchair, (
        f"open_wheelchair_reservations expected {wheelchair}, "
        f"got {vehicle['open_wheelchair_reservations']}"
    )
    assert vehicle["open_ambulatory_reservations"] == ambulatory, (
        f"open_ambulatory_reservations expected {ambulatory}, "
        f"got {vehicle['open_ambulatory_reservations']}"
    )


def assert_slot_mirror(slot, booked_count, status):
    """A slot's booked_count and the status derived from it."""
    assert slot["booked_count"] == booked_count, (
        f"booked_count expected {booked_count}, got {slot['booked_count']}"
    )
    assert slot["status"] == status, (
        f"slot status expected {status}, got {slot['status']}"
    )


def assert_term_matches_category(determination):
    """term_days follows the category through the contract's term table."""
    category = determination["category"]
    expected = TERM_DAYS_BY_CATEGORY[category]
    assert determination["term_days"] == expected, (
        f"term_days for {category} expected {expected}, got {determination['term_days']}"
    )


def assert_day_ledger_conserved(proceeding):
    """days_served plus days_forgiven equals duration_days, whatever the status."""
    served = proceeding["days_served"]
    forgiven = proceeding["days_forgiven"]
    duration = proceeding["duration_days"]
    assert served + forgiven == duration, (
        f"days_served ({served}) plus days_forgiven ({forgiven}) must equal "
        f"duration_days ({duration}) for proceeding in {proceeding['status']}"
    )


def assert_ladder_duration(proceeding, prior_upheld_count):
    """duration_days comes from the escalating ladder at the prior-offence index."""
    index = min(prior_upheld_count, len(SUSPENSION_LADDER_DAYS) - 1)
    expected = SUSPENSION_LADDER_DAYS[index]
    assert proceeding["duration_days"] == expected, (
        f"a rider with {prior_upheld_count} prior upheld suspensions draws "
        f"{expected} days, got {proceeding['duration_days']}"
    )


def assert_sweep_counters(body, **expected):
    """Check whichever of the sweep's six counters a test pins by name."""
    for counter, value in expected.items():
        assert counter in body, f"the sweep response must report {counter}"
        assert body[counter] == value, (
            f"{counter} expected {value}, got {body[counter]}"
        )


def assert_all_sweep_counters_present(body):
    """The sweep response reports all six counters."""
    from .constants import SWEEP_COUNTERS

    assert_fields_present(body, SWEEP_COUNTERS, "the day-close sweep response")


def assert_paginated_defaults(meta, total_count=None):
    """The default page window when no pagination parameters were supplied."""
    from .constants import DEFAULT_LIMIT, DEFAULT_OFFSET

    assert meta["limit"] == DEFAULT_LIMIT, (
        f"the default limit is {DEFAULT_LIMIT}, got {meta['limit']}"
    )
    assert meta["offset"] == DEFAULT_OFFSET, (
        f"the default offset is {DEFAULT_OFFSET}, got {meta['offset']}"
    )
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count expected {total_count}, got {meta['total_count']}"
        )


def assert_created_at_ascending(records):
    """A listing's default order is by creation stamp ascending."""
    stamps = [record["created_at"] for record in records]
    assert stamps == sorted(stamps), (
        f"records must be ordered by created_at ascending, got {stamps}"
    )


def assert_envelope_meta(response):
    """The request identifier and timestamp conventions of the envelope."""
    body = response.json()
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_creation_timestamp(meta["api_request_timestamp"])
