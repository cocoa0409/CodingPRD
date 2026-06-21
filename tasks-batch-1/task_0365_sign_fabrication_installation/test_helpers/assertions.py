"""Entity assertions and domain invariant checkers for the Sign Fabrication &
Installation API. Built on the framework's generic validators.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_PHASES = ["DESIGN", "ESTIMATING", "PERMITTING", "FABRICATION", "INSTALL",
           "WARRANTY", "CLOSED", "CANCELLED"]
_PROOF_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED"]
_ESTIMATE_STATUSES = ["DRAFT", "SENT", "ACCEPTED", "DECLINED", "EXPIRED", "SUPERSEDED"]
_SURVEY_STATUSES = ["PENDING", "PASSED", "FAILED"]
_PERMIT_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "DENIED", "EXPIRED"]
_WO_STATUSES = ["RELEASED", "IN_PRODUCTION", "QC_HOLD", "READY_FOR_INSTALL", "CANCELLED"]
_JOB_STATUSES = ["SCHEDULED", "DISPATCHED", "INSTALLED", "FAILED", "CANCELLED"]
_CO_STATUSES = ["PROPOSED", "APPROVED", "APPLIED", "REJECTED"]
_CLAIM_STATUSES = ["OPEN", "APPROVED", "DENIED", "RESOLVED"]
_REORDER_STATUSES = ["REQUESTED", "CONFIRMED", "CANCELLED"]
_REQ_EQUIP_CLASSES = ["NONE", "LADDER", "BUCKET_TRUCK"]


def _assert_common(data: dict):
    """Common fields carried by every entity (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_sign_project(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_name"], str)
    assert isinstance(data["site_address"], str)
    assert data["jurisdiction_code"] in ["CITY_A", "CITY_B", "COUNTY_C"]
    assert data["sign_type"] in ["MONUMENT", "PYLON", "WALL", "BLADE"]
    assert data["phase"] in _PHASES, f"unexpected phase {data['phase']}"
    assert isinstance(data["permit_required"], bool)
    assert isinstance(data["contract_total_cents"], int)


def assert_art_proof(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["sign_project_id"])
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1
    assert isinstance(data["color_count"], int) and data["color_count"] >= 1
    assert data["status"] in _PROOF_STATUSES, f"unexpected status {data['status']}"


def assert_estimate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["sign_project_id"])
    assert data["substrate"] in ["ALUMINUM", "ACRYLIC", "STEEL"]
    for f in ("material_rate_cents_per_sqft", "material_cost_cents",
              "labor_cost_cents", "subtotal_cents", "surcharge_cents", "total_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    assert data["status"] in _ESTIMATE_STATUSES, f"unexpected status {data['status']}"


def assert_site_survey(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["sign_project_id"])
    assert isinstance(data["overhead_obstruction"], bool)
    assert isinstance(data["ground_bearing_ok"], bool)
    assert data["status"] in _SURVEY_STATUSES, f"unexpected status {data['status']}"


def assert_permit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["sign_project_id"])
    assert data["permit_kind"] in ["STRUCTURAL", "ELECTRICAL"]
    assert isinstance(data["fee_cents"], int)
    assert data["status"] in _PERMIT_STATUSES, f"unexpected status {data['status']}"


def assert_work_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["sign_project_id"])
    assert isinstance(data["snapshot_total_cents"], int)
    assert data["status"] in _WO_STATUSES, f"unexpected status {data['status']}"


def assert_install_job(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["sign_project_id"])
    assert data["required_equipment_class"] in _REQ_EQUIP_CLASSES
    assert data["status"] in _JOB_STATUSES, f"unexpected status {data['status']}"


def assert_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["certified_aerial"], bool)
    assert isinstance(data["active"], bool)


def assert_equipment(data: dict):
    _assert_common(data)
    assert isinstance(data["asset_tag"], str)
    assert data["equipment_class"] in ["LADDER", "BUCKET_TRUCK"]
    assert isinstance(data["in_service"], bool)


def assert_change_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["sign_project_id"])
    assert isinstance(data["delta_total_cents"], int)
    assert data["status"] in _CO_STATUSES, f"unexpected status {data['status']}"


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["sign_project_id"])
    assert data["defect_kind"] in ["ELECTRICAL", "STRUCTURAL", "COSMETIC"]
    assert isinstance(data["covered"], bool)
    assert data["status"] in _CLAIM_STATUSES, f"unexpected status {data['status']}"


def assert_reorder(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["sign_project_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["reprice"], bool)
    assert data["status"] in _REORDER_STATUSES, f"unexpected status {data['status']}"


def assert_contract_ledger_invariant(project: dict, accepted_estimate_total: int,
                                     applied_deltas):
    """PRD §3.2: contract_total_cents == accepted estimate total + sum of
    APPLIED change-order deltas (no drift, integer cents)."""
    expected = accepted_estimate_total + sum(applied_deltas)
    assert project["contract_total_cents"] == expected, (
        f"contract_total_cents {project['contract_total_cents']} != "
        f"baseline {accepted_estimate_total} + applied deltas {applied_deltas}"
    )
