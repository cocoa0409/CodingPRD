"""Payload factories — one per creatable entity, input fields only.

Defaults produce PRD-valid payloads; tests override the fields they care
about. All monetary figures are integer cents (PRD §2.6).
"""
from .constants import TEST_DEFAULTS, TIER_SCHEDULE_T1


def create_coop_payload(**overrides) -> dict:
    defaults = {"name": TEST_DEFAULTS["COOP_NAME"]}
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {
        "legal_name": TEST_DEFAULTS["MEMBER_LEGAL_NAME"],
        "commitment_level": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "legal_name": TEST_DEFAULTS["SUPPLIER_LEGAL_NAME"],
        "onboarding_notes": "",
    }
    defaults.update(overrides)
    return defaults


def create_supplier_program_payload(**overrides) -> dict:
    """Default: valid non-exclusivity program with the standard 3-tier
    schedule and FLAT holdback policy, born in DRAFT (PRD §3.3)."""
    defaults = {
        "program_code": TEST_DEFAULTS["PROGRAM_CODE"],
        "exclusivity_required": False,
        "exclusivity_threshold_pct": 0,
        "tier_schedule": [dict(t) for t in TIER_SCHEDULE_T1],
        "holdback_policy": "FLAT",
    }
    defaults.update(overrides)
    return defaults


def amend_supplier_program_payload(expected_program_version: int, **overrides) -> dict:
    """OCC-guarded amendment payload; expected_program_version is
    non-optional (PRD §2.8)."""
    payload = {"expected_program_version": expected_program_version}
    payload.update(overrides)
    return payload


def create_enrollment_payload(member_id: str, program_id: str, **overrides) -> dict:
    payload = {"member_id": member_id, "program_id": program_id}
    payload.update(overrides)
    return payload


def create_purchase_report_payload(**overrides) -> dict:
    defaults = {
        "quarter_index": 0,
        "self_report_qty": TEST_DEFAULTS["REPORT_QTY"],
        "self_report_cents": TEST_DEFAULTS["REPORT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def revise_purchase_report_payload(**overrides) -> dict:
    defaults = {"self_report_qty": 8, "self_report_cents": 8000}
    defaults.update(overrides)
    return defaults


def create_volume_audit_payload(purchase_report_id: str, **overrides) -> dict:
    payload = {"purchase_report_id": purchase_report_id}
    payload.update(overrides)
    return payload


def resolve_audit_payload(audited_qty: int, audited_cents: int, **overrides) -> dict:
    """Both audited_qty and audited_cents are required at resolve time
    (PRD §3.5)."""
    payload = {"audited_qty": audited_qty, "audited_cents": audited_cents}
    payload.update(overrides)
    return payload


def calculate_distribution_payload(expected_distribution_version: int) -> dict:
    """OCC-guarded calculate payload; expected_distribution_version is
    non-optional (PRD §2.8)."""
    return {"expected_distribution_version": expected_distribution_version}


def dispute_clawback_payload(**overrides) -> dict:
    defaults = {"dispute_note": "We dispute the computed amounts."}
    defaults.update(overrides)
    return defaults
