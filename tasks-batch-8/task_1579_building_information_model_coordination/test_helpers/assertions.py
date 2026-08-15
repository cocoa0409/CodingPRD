"""Entity assertions and domain invariant checkers (PRD §2.4, §3).

Field presence/type checks follow the PRD narratives; nullable computed fields
are checked only when the entity has reached the lifecycle point that sets them.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

PHASES = ["SCHEMATIC_DESIGN", "DESIGN_DEVELOPMENT", "CONSTRUCTION_DOCUMENTS",
          "CONSTRUCTION_ADMINISTRATION", "CLOSEOUT"]
POSTURES = ["NORMAL", "COORDINATION_HOLD"]
DISCIPLINES = ["ARCHITECTURAL", "STRUCTURAL", "MECHANICAL", "ELECTRICAL",
               "PLUMBING", "FIRE_PROTECTION"]
PLATFORMS = ["REVIT", "TEKLA", "ARCHICAD", "IFC_ONLY"]
FILE_FORMATS = ["RVT", "IFC", "NWC", "DWG"]
INTEROP_STATUSES = ["NATIVE", "CONVERTIBLE", "INCOMPATIBLE"]
PARTNER_STATUSES = ["ACTIVE", "PROBATION"]
MODEL_STATUSES = ["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED", "SUPERSEDED"]
FED_STATUSES = ["DRAFT", "ASSEMBLED", "FROZEN", "RELEASED", "SUPERSEDED"]
FREEZE_PURPOSES = ["COORDINATION_FREEZE", "FABRICATION_HOLD", "HANDOVER_FREEZE"]
RUN_STATUSES = ["QUEUED", "RUNNING", "COMPLETED"]
SEVERITIES = ["CRITICAL", "MAJOR", "MINOR"]
CLASH_STATUSES = ["NEW", "ASSIGNED", "RESOLVED", "VERIFIED", "REOPENED"]
MEETING_STATUSES = ["SCHEDULED", "IN_SESSION", "ADJOURNED"]
COMMITMENT_STATUSES = ["COMMITTED", "FULFILLED", "BREACHED", "WAIVED"]
PACKAGE_STATUSES = ["DRAFT", "SIGNOFF_IN_PROGRESS", "READY_FOR_RELEASE",
                    "RELEASED", "VOID"]
SIGNOFF_STATUSES = ["REQUESTED", "SIGNED", "DECLINED", "REVOKED"]
AS_BUILT_STATUSES = ["DRAFT", "SUBMITTED", "FIELD_VERIFIED", "REJECTED"]
TAKEOFF_STATUSES = ["EXTRACTED", "APPROVED", "SUPERSEDED"]
HANDOVER_STATUSES = ["ASSEMBLING", "READY", "TRANSMITTED", "FM_ACCEPTED",
                     "FM_REJECTED"]


def _assert_common_fields(data: dict):
    """PRD §2.4: every resource carries id / created_at / updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer starting at 1, got {data.get('version')!r}"


def assert_project(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert data["current_phase"] in PHASES
    assert data["coordination_posture"] in POSTURES
    cri = data["coordination_readiness_index"]
    assert isinstance(cri, int) and 0 <= cri <= 100, f"CRI out of [0,100]: {cri!r}"
    for counter in ("open_critical_count", "open_major_count",
                    "unassigned_minor_count", "overdue_commitment_count",
                    "ops_sweep_index"):
        assert isinstance(data.get(counter), int) and data[counter] >= 0, \
            f"{counter} must be a non-negative integer, got {data.get(counter)!r}"


def assert_lod_requirement(data: dict):
    _assert_common_fields(data)
    assert data["discipline"] in DISCIPLINES
    assert data["phase"] in PHASES
    assert data["min_lod"] in (100, 200, 300, 350, 400, 500)
    assert data["clearance_requirement_mm"] > 0


def assert_trade_partner(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("company_name"), str) and data["company_name"]
    assert data["discipline"] in DISCIPLINES
    assert data["software_platform"] in PLATFORMS
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] > 0
    assert data["coordination_budget_hours"] >= 0
    assert data["consumed_resolution_hours"] >= 0
    assert 0 <= data["reliability_score"] <= 100
    assert isinstance(data["breach_count"], int) and data["breach_count"] >= 0
    assert data["status"] in PARTNER_STATUSES


def assert_trade_model(data: dict):
    _assert_common_fields(data)
    assert data["status"] in MODEL_STATUSES
    assert data["file_format"] in FILE_FORMATS
    assert data["interop_status"] in INTEROP_STATUSES
    assert data["discipline"] in DISCIPLINES
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert isinstance(data["declared_lod"], int) and 0 <= data["declared_lod"] <= 500
    for cls in ("life_safety", "envelope", "finish"):
        assert data[f"{cls}_elements"] >= 0
        assert 0 <= data[f"{cls}_compliant"] <= data[f"{cls}_elements"]
    assert (data["life_safety_elements"] + data["envelope_elements"]
            + data["finish_elements"]) >= 1


def assert_federated_model(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("label"), str) and data["label"]
    assert data["target_format"] in ("IFC", "NWC")
    assert data["status"] in FED_STATUSES
    assert isinstance(data["is_stale"], bool)
    assert isinstance(data["assembly_index"], int) and data["assembly_index"] >= 1
    assert isinstance(data["open_critical_count"], int) and data["open_critical_count"] >= 0


def assert_federated_model_member(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("trade_model_id", ""))
    assert data["discipline"] in DISCIPLINES
    assert isinstance(data["pinned_model_version"], int) and data["pinned_model_version"] >= 1


def assert_freeze_window(data: dict):
    _assert_common_fields(data)
    assert data["purpose"] in FREEZE_PURPOSES
    assert data["ends_at"] > data["starts_at"], "ends_at must be strictly after starts_at"


def assert_clash_run(data: dict):
    _assert_common_fields(data)
    assert data["status"] in RUN_STATUSES
    assert isinstance(data["run_index"], int) and data["run_index"] >= 1
    assert data["tolerance_mm"] > 0
    assert_run_clash_counts_conserved(data)


def assert_run_clash_counts_conserved(data: dict):
    """PRD §3.4: open + closed == total at every point of the verify/reopen cycle."""
    total = data["total_clash_count"]
    opened = data["open_clash_count"]
    closed = data["closed_clash_count"]
    assert isinstance(total, int) and isinstance(opened, int) and isinstance(closed, int)
    assert opened + closed == total, \
        f"run counters not conserved: open {opened} + closed {closed} != total {total}"


def assert_clash_issue(data: dict):
    _assert_common_fields(data)
    assert data["status"] in CLASH_STATUSES
    assert data["severity"] in SEVERITIES
    assert data["overlap_mm"] >= 0
    assert isinstance(data["spans_disciplines"], bool)
    assert isinstance(data["cycle_count"], int) and data["cycle_count"] >= 0


def assert_coordination_meeting(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("room_id"), str) and data["room_id"]
    assert data["status"] in MEETING_STATUSES
    assert data["ends_at"] > data["starts_at"]
    for counter in ("commitment_count", "fulfilled_commitment_count",
                    "breached_commitment_count"):
        assert isinstance(data.get(counter), int) and data[counter] >= 0


def assert_resolution_commitment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in COMMITMENT_STATUSES
    assert is_valid_uuid(data.get("clash_issue_id", ""))
    assert is_valid_uuid(data.get("committed_by_partner_id", ""))
    assert is_iso8601_timestamp(data.get("due_at", ""))


def assert_fabrication_package(data: dict):
    _assert_common_fields(data)
    assert data["status"] in PACKAGE_STATUSES
    scopes = data["scope_disciplines"]
    assert isinstance(scopes, list) and 1 <= len(scopes) <= 3
    assert len(set(scopes)) == len(scopes), "scope disciplines must be unique"
    assert all(d in DISCIPLINES for d in scopes)
    assert data["required_signoff_count"] == len(scopes), \
        "required_signoff_count must equal the number of scope disciplines"
    assert isinstance(data["signed_count"], int) and 0 <= data["signed_count"]
    assert data["signed_count"] <= data["required_signoff_count"]


def assert_signoff(data: dict):
    _assert_common_fields(data)
    assert data["status"] in SIGNOFF_STATUSES
    assert data["discipline"] in DISCIPLINES
    assert is_valid_uuid(data.get("trade_model_id", ""))
    assert isinstance(data["pinned_model_version"], int) and data["pinned_model_version"] >= 1


def assert_as_built_model(data: dict):
    _assert_common_fields(data)
    assert data["status"] in AS_BUILT_STATUSES
    assert is_valid_uuid(data.get("trade_model_id", ""))
    assert is_valid_uuid(data.get("trade_partner_id", ""))


def assert_quantity_takeoff(data: dict):
    _assert_common_fields(data)
    assert data["status"] in TAKEOFF_STATUSES
    assert data["extraction_mode"] in ("GROSS", "NET")
    assert isinstance(data["element_count"], int) and data["element_count"] >= 1
    assert data["element_count"] == len(data["elements"]), \
        "element_count must equal the number of supplied elements"
    assert data["total_quantity"] >= 0


def assert_handover_package(data: dict):
    _assert_common_fields(data)
    assert data["status"] in HANDOVER_STATUSES
    assert isinstance(data.get("label"), str) and data["label"]
    assert is_valid_uuid(data.get("includes_takeoff_id", ""))
