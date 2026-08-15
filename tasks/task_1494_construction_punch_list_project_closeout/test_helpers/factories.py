"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import TEST_DEFAULTS


def create_project_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Project",
        "contract_value_cents": TEST_DEFAULTS["CONTRACT_VALUE_CENTS"],
        "retainage_pct": TEST_DEFAULTS["RETAINAGE_PCT"],
        "reduction_policy": "STANDARD",
        "warranty_sla_mode": "CALENDAR",
    }
    defaults.update(overrides)
    return defaults


def create_trade_package_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "trade_name": "ELECTRICAL",
        "responsible_type": "SUBCONTRACTOR",
        "subcontractor_org": "SparkyCo",
    }
    defaults.update(overrides)
    if defaults.get("subcontractor_org") is None:
        defaults.pop("subcontractor_org", None)
    return defaults


def create_punch_walk_payload(project_id: str, trade_package_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "trade_package_id": trade_package_id,
        "lead_inspector_id": "insp-lead-1",
        "scheduled_start": "2026-08-03T09:00:00Z",
        "scheduled_end": "2026-08-03T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_punch_item_payload(project_id: str, trade_package_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "trade_package_id": trade_package_id,
        "title": "Paint touch-up",
        "severity": "MINOR",
        "location_building": "B1",
        "location_floor": "L1",
        "location_area": "R1",
        "photo_ref": "img-1",
    }
    defaults.update(overrides)
    if defaults.get("punch_walk_id") is None:
        defaults.pop("punch_walk_id", None)
    return defaults


def create_closeout_document_payload(project_id: str, trade_package_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "trade_package_id": trade_package_id,
        "doc_type": "OM_MANUAL",
        "file_ref": "doc-ref-1",
    }
    defaults.update(overrides)
    return defaults


def create_training_session_payload(project_id: str, trade_package_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "trade_package_id": trade_package_id,
        "system_name": "AHU-1 controls",
        "location_room": "TR-1",
        "scheduled_start": "2026-08-05T09:00:00Z",
        "scheduled_end": "2026-08-05T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_retainage_release_payload(project_id: str, kind: str, expected_project_version: int) -> dict:
    return {
        "project_id": project_id,
        "kind": kind,
        "expected_project_version": expected_project_version,
    }


def create_warranty_case_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "title": "Lobby door drags",
        "severity": "MINOR",
        "description": "Door closer weak",
    }
    defaults.update(overrides)
    return defaults


def lien_waiver_submission_payload(**overrides) -> dict:
    defaults = {
        "waiver_type": "UNCONDITIONAL",
        "amount_cents": 1_000_000,
        "file_ref": "wvr-1",
    }
    defaults.update(overrides)
    return defaults


def lien_waiver_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
