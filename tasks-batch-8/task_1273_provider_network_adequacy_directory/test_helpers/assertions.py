"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

GEO_CLASSES = ["URBAN", "SUBURBAN", "RURAL"]
SPECIALTIES = ["PRIMARY_CARE", "CARDIOLOGY", "DERMATOLOGY", "BEHAVIORAL_HEALTH"]
PROVIDER_STATUSES = ["PENDING_LOAD", "EFFECTIVE", "SUSPENDED", "TERMINATED"]
LISTING_STATUSES = ["DRAFT", "LISTED", "UNDER_REVIEW", "SUPPRESSED", "REMOVED"]
SUPPRESS_REASONS = ["NONE", "MANUAL", "ATTESTATION_FAILURE", "GHOST_CONFIRMED", "PROVIDER_SUSPENDED"]
CYCLE_STATUSES = ["SCHEDULED", "OPEN", "OUTREACH", "CLOSED"]
RECORD_STATUSES = ["PENDING", "ATTESTED", "CORRECTION_REQUESTED", "NON_RESPONSIVE", "CANCELLED"]
PROBE_RESULTS = ["PASS", "FAIL"]
EVALUATION_STATUSES = ["OPEN", "FINALIZED"]
OVERALL_STATUSES = ["COMPLIANT", "DEFICIENT", "EXCUSED"]
DEFICIENCY_STATUSES = ["OPEN", "EXCUSED", "CLOSED"]
REQUEST_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "DENIED", "SUPERSEDED"]
MEMBER_STATUSES = ["ENROLLED", "DISENROLLED"]
COMPLAINT_STATUSES = ["OPEN", "CONFIRMED_ERROR", "UNFOUNDED", "CLOSED"]
CORRECTION_STATUSES = ["SUBMITTED", "VERIFIED", "REJECTED"]


def _assert_common(data: dict, entity: str, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_region(data: dict):
    _assert_common(data, "ServiceRegion")
    assert isinstance(data["county_fips"], str) and data["county_fips"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["geo_class"] in GEO_CLASSES
    assert isinstance(data["enrolled_member_count"], int) and data["enrolled_member_count"] >= 0


def assert_standard(data: dict):
    _assert_common(data, "NetworkStandard")
    assert data["specialty"] in SPECIALTIES
    assert data["geo_class"] in GEO_CLASSES
    for f in ("max_members_per_provider", "max_travel_minutes", "max_travel_miles",
              "max_wait_days_routine", "max_wait_days_urgent"):
        assert isinstance(data[f], int), f"NetworkStandard.{f} must be an integer"


def assert_provider(data: dict):
    _assert_common(data, "Provider")
    assert isinstance(data["npi"], str) and data["npi"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["specialty"] in SPECIALTIES
    assert isinstance(data["contract_effective_date"], str)
    assert data["status"] in PROVIDER_STATUSES


def assert_location(data: dict):
    _assert_common(data, "PracticeLocation")
    assert is_valid_uuid(data.get("provider_id", "")), "PracticeLocation.provider_id must be a UUID"
    assert is_valid_uuid(data.get("region_id", "")), "PracticeLocation.region_id must be a UUID"
    assert isinstance(data["address_line"], str) and data["address_line"]
    assert data["panel_status"] in ["OPEN", "CLOSED"]
    assert isinstance(data["avg_travel_minutes"], int)
    assert isinstance(data["avg_travel_miles"], int)


def assert_listing(data: dict):
    _assert_common(data, "DirectoryListing")
    assert is_valid_uuid(data.get("provider_id", ""))
    assert is_valid_uuid(data.get("location_id", ""))
    assert data["specialty"] in SPECIALTIES
    assert isinstance(data["display_name"], str)
    assert isinstance(data["phone"], str)
    assert isinstance(data["accepts_new_patients"], bool)
    assert data["status"] in LISTING_STATUSES
    assert data["suppress_reason"] in SUPPRESS_REASONS
    assert isinstance(data["ghost_strike_count"], int) and data["ghost_strike_count"] >= 0
    assert isinstance(data["has_confirmed_data_error"], bool)


def assert_cycle(data: dict):
    _assert_common(data, "AttestationCycle")
    assert isinstance(data["cycle_label"], str) and data["cycle_label"]
    assert data["status"] in CYCLE_STATUSES
    for f in ("total_records", "pending_count", "responded_count", "non_responsive_count"):
        assert isinstance(data[f], int) and data[f] >= 0, f"AttestationCycle.{f} must be a non-negative integer"


def assert_record(data: dict):
    _assert_common(data, "AttestationRecord")
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert is_valid_uuid(data.get("listing_id", ""))
    assert data["status"] in RECORD_STATUSES
    assert isinstance(data["outreach_attempts"], int) and data["outreach_attempts"] >= 0


def assert_probe(data: dict):
    _assert_common(data, "AvailabilityProbe")
    assert is_valid_uuid(data.get("listing_id", ""))
    assert data["probe_type"] in ["ROUTINE", "URGENT"]
    assert isinstance(data["requested_date"], str)
    assert data["status"] in ["SCHEDULED", "RECORDED"]
    if data["status"] == "RECORDED":
        assert data["outcome"] in ["KEPT", "UNREACHABLE", "NO_APPOINTMENT_OFFERED"]
        assert data["result"] in PROBE_RESULTS
        if data["outcome"] == "KEPT":
            assert isinstance(data["days_to_appointment"], int) and data["days_to_appointment"] >= 0
        else:
            assert data["days_to_appointment"] is None


def assert_evaluation(data: dict):
    _assert_common(data, "AdequacyEvaluation")
    assert isinstance(data["measurement_period"], str)
    assert isinstance(data["period_start_date"], str)
    assert isinstance(data["period_end_date"], str)
    assert data["status"] in EVALUATION_STATUSES
    assert isinstance(data["total_penalty_cents"], int) and data["total_penalty_cents"] >= 0


def assert_result(data: dict):
    """RegionSpecialtyResult: immutable snapshot — id + created_at only, no updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "RegionSpecialtyResult.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "RegionSpecialtyResult.created_at must be ISO 8601"
    assert "updated_at" not in data, "RegionSpecialtyResult must not carry updated_at"
    assert "version" not in data, "RegionSpecialtyResult must not carry version"
    assert data["specialty"] in SPECIALTIES
    assert isinstance(data["member_count"], int)
    assert isinstance(data["provider_count"], int) and data["provider_count"] >= 0
    assert isinstance(data["listing_count"], int) and data["listing_count"] >= 0
    assert isinstance(data["ratio_ok"], bool)
    assert isinstance(data["time_distance_compliant"], bool)
    assert isinstance(data["wait_time_compliant"], bool)
    assert data["overall_status"] in OVERALL_STATUSES


def assert_deficiency(data: dict):
    _assert_common(data, "DeficiencyRecord")
    assert is_valid_uuid(data.get("evaluation_id", ""))
    assert is_valid_uuid(data.get("region_id", ""))
    assert data["specialty"] in SPECIALTIES
    assert data["status"] in DEFICIENCY_STATUSES
    assert isinstance(data["prior_closure_count"], int) and data["prior_closure_count"] >= 0
    for f in ("last_accrual_cents", "accrued_penalty_cents", "reversed_penalty_cents", "outstanding_penalty_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"DeficiencyRecord.{f} must be a non-negative integer"


def assert_access_plan_request(data: dict):
    _assert_common(data, "AccessPlanRequest")
    assert is_valid_uuid(data.get("deficiency_id", ""))
    assert isinstance(data["remedy_summary"], str)
    assert isinstance(data["excuse_start_date"], str)
    assert isinstance(data["excuse_through_date"], str)
    assert data["status"] in REQUEST_STATUSES
    assert isinstance(data["submission_seq"], int) and data["submission_seq"] >= 1


def assert_member(data: dict):
    _assert_common(data, "Member")
    assert is_valid_uuid(data.get("region_id", ""))
    assert isinstance(data["member_ref"], str) and data["member_ref"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in MEMBER_STATUSES


def assert_complaint(data: dict):
    _assert_common(data, "MemberComplaint")
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("listing_id", ""))
    assert data["error_type"] in ["WRONG_PHONE", "WRONG_ADDRESS", "NOT_ACCEPTING", "NO_APPOINTMENT", "OTHER"]
    assert isinstance(data["error_observed_date"], str)
    assert data["status"] in COMPLAINT_STATUSES


def assert_correction(data: dict):
    _assert_common(data, "DirectoryCorrection")
    assert is_valid_uuid(data.get("listing_id", ""))
    assert isinstance(data["changes"], dict) and len(data["changes"]) > 0
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]
    assert is_iso8601_timestamp(data.get("sla_due_at", "")), "DirectoryCorrection.sla_due_at must be ISO 8601"
    assert data["status"] in CORRECTION_STATUSES
    assert isinstance(data["is_late"], bool)


def assert_deficiency_money_invariant(data: dict):
    """PRD §3.7: outstanding_penalty_cents == accrued_penalty_cents - reversed_penalty_cents."""
    assert data["outstanding_penalty_cents"] == data["accrued_penalty_cents"] - data["reversed_penalty_cents"], (
        f"money invariant violated: outstanding {data['outstanding_penalty_cents']} != "
        f"accrued {data['accrued_penalty_cents']} - reversed {data['reversed_penalty_cents']}"
    )
