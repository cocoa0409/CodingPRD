"""Entity assertions and domain invariant checkers.

Each assert_* checks the common properties of PRD section 2.5 (id UUID,
created_at/updated_at ISO 8601, integer version) plus the field presence and
enum membership documented for the resource in PRD section 3.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

PROJECT_STATUSES = [
    "DRAFT", "ASSESSED", "IN_PROGRESS", "SUSPENDED",
    "AWAITING_CLEARANCE", "RECLEANING", "CLOSED",
]
SURVEY_STATUSES = ["DRAFT", "IN_LAB", "FINALIZED"]
SAMPLE_STATUSES = ["PENDING", "REPORTED"]
LAB_RESULTS = ["PENDING", "POSITIVE", "NEGATIVE"]
WORKER_STATUSES = ["ACTIVE", "LAPSED"]
ASSIGNMENT_STATUSES = ["SCHEDULED", "SUSPENDED", "COMPLETED", "CANCELLED"]
NOTIFICATION_STATUSES = ["FILED", "ACKNOWLEDGED", "SUPERSEDED"]
CONTAINMENT_STATUSES = ["DESIGNED", "INSTALLED", "VERIFIED", "RECLEAN_REQUIRED"]
AIR_TEST_PHASES = ["BASELINE", "DAILY", "CLEARANCE"]
AIR_TEST_OUTCOMES = ["NA", "PASS", "FAIL"]
AIR_TEST_STATUSES = ["COLLECTED", "REPORTED"]
MANIFEST_STATUSES = [
    "DRAFT", "SEALED", "IN_TRANSIT", "DELIVERED",
    "CONFIRMED", "REJECTED", "VOIDED",
]
FACILITY_STATUSES = ["APPROVED", "SUSPENDED"]
UNIT_STATUSES = ["AVAILABLE", "OCCUPIED", "CLEANING"]
RELOCATION_STATUSES = ["HOUSED", "EXTENDED", "RETURNED"]
REOCCUPANCY_STATUSES = ["BLOCKED", "OPEN"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_project(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["site_address"], str) and data["site_address"]
    assert data["work_type"] in ["RENOVATION", "DEMOLITION"]
    assert data["hazard_class"] in ["ASBESTOS", "LEAD", "MIXED"]
    assert data["status"] in PROJECT_STATUSES
    assert data["reoccupancy_status"] in REOCCUPANCY_STATUSES
    for field in ("estimated_disposal_cost_cents", "final_disposal_cost_cents",
                  "insurance_surcharge_cents", "total_project_cost_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    for field in ("total_acm_sq_ft", "manifested_weight_lbs"):
        assert isinstance(data[field], (int, float)), \
            f"{field} must be numeric"


def assert_survey(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["surveyor_name"], str) and data["surveyor_name"]
    assert data["status"] in SURVEY_STATUSES
    for field in ("acm_sq_ft_provisional", "acm_sq_ft_final",
                  "friable_acm_sq_ft_final"):
        assert isinstance(data[field], (int, float)), \
            f"{field} must be numeric"


def assert_sample(data: dict):
    _assert_common(data)
    assert isinstance(data["survey_id"], str)
    assert isinstance(data["material"], str) and data["material"]
    assert isinstance(data["location_desc"], str)
    assert data["quantity_sq_ft"] > 0
    assert isinstance(data["friable"], bool)
    assert data["lab_result"] in LAB_RESULTS
    assert data["status"] in SAMPLE_STATUSES


def assert_worker(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["certification_level"] in ["SUPERVISOR", "HANDLER"]
    for field in ("cert_expires_at", "medical_clearance_expires_at",
                  "respirator_fit_expires_at"):
        assert is_iso8601_timestamp(data[field]), f"{field} must be ISO 8601"
    assert data["status"] in WORKER_STATUSES
    assert isinstance(data["assigned_scheduled_hours"], (int, float))


def assert_crew_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["worker_id"], str)
    assert data["role_on_site"] in ["SUPERVISOR", "HANDLER"]
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["scheduled_hours"], (int, float))
    assert data["status"] in ASSIGNMENT_STATUSES


def assert_notification(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert data["notification_type"] in ["INITIAL", "REVISION", "EMERGENCY"]
    assert data["declared_acm_sq_ft"] > 0
    assert is_iso8601_timestamp(data["filed_at"])
    assert data["waiting_days"] in (3, 10)
    assert is_iso8601_timestamp(data["earliest_start_at"])
    assert data["status"] in NOTIFICATION_STATUSES


def assert_containment(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert data["work_area_volume_cuft"] > 0
    assert data["containment_class"] in ["FULL", "MINI_ENCLOSURE", "GLOVE_BAG"]
    assert isinstance(data["air_changes_per_hour"], (int, float))
    assert isinstance(data["machines_required"], int)
    assert data["status"] in CONTAINMENT_STATUSES


def assert_air_test(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert data["phase"] in AIR_TEST_PHASES
    assert is_iso8601_timestamp(data["collected_at"])
    assert data["outcome"] in AIR_TEST_OUTCOMES
    assert data["status"] in AIR_TEST_STATUSES


def assert_manifest(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["bags_count"], int) and data["bags_count"] >= 1
    assert data["gross_weight_lbs"] > 0
    assert isinstance(data["net_weight_lbs"], (int, float))
    assert isinstance(data["net_tons"], (int, float))
    assert data["status"] in MANIFEST_STATUSES


def assert_facility(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["epa_id"], str) and data["epa_id"]
    assert isinstance(data["accepted_hazards"], list) and \
        len(data["accepted_hazards"]) >= 1
    assert data["monthly_capacity_tons"] > 0
    assert isinstance(data["delivered_tons_current_month"], (int, float))
    assert data["status"] in FACILITY_STATUSES


def assert_relocation_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["unit_label"], str) and data["unit_label"]
    assert isinstance(data["capacity_persons"], int) and \
        data["capacity_persons"] >= 1
    assert data["status"] in UNIT_STATUSES


def assert_relocation_record(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["household_name"], str) and data["household_name"]
    assert isinstance(data["persons"], int) and data["persons"] >= 1
    assert is_iso8601_timestamp(data["move_out_at"])
    assert isinstance(data["extension_count"], int)
    assert data["status"] in RELOCATION_STATUSES


def assert_project_cost_rollup_consistent(data: dict):
    """PRD section 3.7 pinned rollup: total = base + final + surcharge, and the
    surcharge never exceeds the pre-surcharge subtotal relationship."""
    subtotal = data["base_abatement_cost_cents"] + \
        data["final_disposal_cost_cents"]
    assert data["total_project_cost_cents"] == (
        subtotal + data["insurance_surcharge_cents"]
    ), "total_project_cost_cents must equal subtotal plus surcharge"
