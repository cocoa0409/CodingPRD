"""Entity assertions: shape and PRD-named status values per resource."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

CLIENT_STATUSES = ["ACTIVE", "SUSPENDED", "TERMINATED"]
APPRAISER_STATUSES = ["ACTIVE", "INACTIVE"]
STANDINGS = ["GOOD_STANDING", "PROBATION", "PANEL_SUSPENDED"]
MEMBERSHIP_STATUSES = ["ACTIVE", "REMOVED"]
ORDER_STATUSES = [
    "RECEIVED",
    "SCOPE_DETERMINED",
    "ACCEPTED",
    "ASSIGNED",
    "INSPECTION_SCHEDULED",
    "INSPECTED",
    "IN_ANALYSIS",
    "DRAFTING",
    "QC_REVIEW",
    "DELIVERED",
    "IN_REVISION",
    "COMPLETED",
    "CANCELLED",
]
APPOINTMENT_STATUSES = ["PROPOSED", "CONFIRMED", "COMPLETED", "NO_SHOW", "CANCELLED"]
COMPARABLE_STATUSES = ["DRAFT", "VERIFIED", "LOCKED", "EXCLUDED"]
REPORT_STATUSES = ["DRAFT", "PENDING_QC", "QC_PASSED", "DELIVERED", "UNDER_REVISION"]
REVISION_STATUSES = ["OPEN", "ACCEPTED", "REBUTTED", "SUPERSEDED", "RESOLVED"]
WORKFILE_STATUSES = ["ACTIVE", "LEGAL_HOLD", "PURGED"]
COMPLAINT_STATUSES = [
    "RECEIVED",
    "RESPONSE_DRAFTED",
    "RESPONSE_SUBMITTED",
    "CLOSED_NO_ACTION",
    "CLOSED_SANCTIONED",
]
INELIGIBLE_REASONS = [
    "NET_ADJ_EXCEEDED",
    "GROSS_ADJ_EXCEEDED",
    "DISTANCE_EXCEEDED",
    "SALE_TOO_OLD",
]


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}.version must be an int"


def assert_client(data: dict):
    _assert_common(data, "Client")
    assert isinstance(data["name"], str) and data["name"]
    assert data["client_type"] in ["AMC", "DIRECT_LENDER", "PRIVATE"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["default_turn_time_days"], int)
    assert data["default_turn_time_days"] >= 1
    assert data["status"] in CLIENT_STATUSES


def assert_appraiser(data: dict):
    _assert_common(data, "Appraiser")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["license_level"] in ["TRAINEE", "LICENSED", "CERTIFIED_RESIDENTIAL"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["license_expiry"], str) and data["license_expiry"]
    assert data["status"] in APPRAISER_STATUSES
    assert isinstance(data["sanction_override"], bool)
    if data["license_level"] == "TRAINEE":
        assert data.get("supervisor_id"), "trainee must carry supervisor_id"


def assert_panel_membership(data: dict):
    _assert_common(data, "PanelMembership")
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert is_valid_uuid(data.get("appraiser_id", "")), "appraiser_id must be a UUID"
    assert data["status"] in MEMBERSHIP_STATUSES


def assert_fee_schedule(data: dict):
    _assert_common(data, "FeeSchedule")
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert data["complexity_tier"] in ["STANDARD", "COMPLEX", "HIGH_VALUE"]
    assert isinstance(data["base_fee_cents"], int) and data["base_fee_cents"] > 0
    assert isinstance(data["rush_multiplier_bps"], int)
    assert 0 <= data["rush_multiplier_bps"] <= 10000
    assert isinstance(data["revision_fee_cents"], int) and data["revision_fee_cents"] >= 0
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    effective_to = data.get("effective_to")
    assert effective_to is None or is_iso8601_timestamp(effective_to)


def assert_order(data: dict):
    _assert_common(data, "AppraisalOrder")
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert isinstance(data["property_address"], str) and data["property_address"]
    assert data["property_type"] in ["SFR", "CONDO", "MULTI_2_4", "MANUFACTURED"]
    assert isinstance(data["estimated_value_cents"], int)
    assert data["estimated_value_cents"] > 0
    assert data["loan_type"] in ["CONVENTIONAL", "FHA", "VA"]
    assert isinstance(data["requested_turn_days"], int)
    assert data["requested_turn_days"] >= 1
    assert data["status"] in ORDER_STATUSES
    assert isinstance(data["requires_inspection"], bool)
    assert isinstance(data["open_complaint_count"], int)
    assert data["open_complaint_count"] >= 0


def assert_appointment(data: dict):
    _assert_common(data, "Appointment")
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert is_valid_uuid(data.get("appraiser_id", "")), "appraiser_id must be a UUID"
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["status"] in APPOINTMENT_STATUSES


def assert_comparable(data: dict):
    _assert_common(data, "Comparable")
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert isinstance(data["address"], str) and data["address"]
    assert isinstance(data["sale_price_cents"], int) and data["sale_price_cents"] > 0
    assert isinstance(data["sale_date"], str) and data["sale_date"]
    assert isinstance(data["distance_miles"], (int, float))
    assert data["distance_miles"] >= 0
    assert data["status"] in COMPARABLE_STATUSES
    reasons = data.get("ineligible_reasons")
    if reasons is not None:
        assert isinstance(reasons, list)
        assert set(reasons) <= set(INELIGIBLE_REASONS)


def assert_report(data: dict):
    _assert_common(data, "Report")
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert data["report_type"] in ["FORM_1004", "FORM_1073", "FORM_1025"]
    assert data["condition_rating"] in ["C1", "C2", "C3", "C4", "C5", "C6"]
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert isinstance(data["qc_fail_count"], int) and data["qc_fail_count"] >= 0
    assert data["status"] in REPORT_STATUSES


def assert_revision_request(data: dict):
    _assert_common(data, "RevisionRequest")
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert data["kind"] in ["CORRECTION", "RECONSIDERATION_OF_VALUE"]
    assert isinstance(data["detail"], str)
    assert data["status"] in REVISION_STATUSES


def assert_workfile_record(data: dict):
    _assert_common(data, "WorkfileRecord")
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert data["snapshot_type"] in [
        "ORDER_FORM",
        "INSPECTION_NOTES",
        "COMP_DATA",
        "REPORT_PDF",
        "CERTIFICATION",
        "REVISION_CORRESPONDENCE",
    ]
    assert data["status"] in WORKFILE_STATUSES
    retention = data.get("retention_until")
    assert retention is None or is_iso8601_timestamp(retention)


def assert_complaint(data: dict):
    _assert_common(data, "Complaint")
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert is_valid_uuid(
        data.get("respondent_appraiser_id", "")
    ), "respondent_appraiser_id must be a UUID"
    assert isinstance(data["description"], str)
    assert data["status"] in COMPLAINT_STATUSES
    assert is_iso8601_timestamp(data.get("received_at", ""))
    assert is_iso8601_timestamp(data.get("response_due_at", ""))


def assert_scorecard(data: dict):
    """Shape of the computed panel scorecard payload (PRD 3.2)."""
    assert is_valid_uuid(data.get("appraiser_id", "")), "appraiser_id must be a UUID"
    assert isinstance(data["completed_count"], int) and data["completed_count"] >= 0
    assert isinstance(data["on_time_count"], int) and data["on_time_count"] >= 0
    rate = data.get("on_time_rate")
    assert rate is None or isinstance(rate, (int, float))
    assert isinstance(data["confirmed_minutes"], int)
    assert data["confirmed_minutes"] >= 0
    assert data["standing"] in STANDINGS
    assert isinstance(data["sanction_override"], bool)
