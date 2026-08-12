"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
import uuid


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


DEFAULTS = {
    "BASE_CONTRACT_CENTS": 4_000_000,
    "BASEMENT_SQFT": 800,
    "ALLOWANCE_BUDGET_CENTS": 100_000,
}


def create_contractor_payload(**overrides) -> dict:
    defaults = {"name": _uniq("GC"), "license_no": _uniq("LIC")}
    defaults.update(overrides)
    return defaults


def create_homeowner_payload(**overrides) -> dict:
    tag = uuid.uuid4().hex[:8]
    defaults = {
        "name": _uniq("Homeowner"),
        "email": f"ho-{tag}@example.com",
        "phone": f"555-{tag[:4]}",
    }
    defaults.update(overrides)
    return defaults


def create_subcontractor_payload(**overrides) -> dict:
    defaults = {"name": _uniq("Sub"), "trade": "GENERAL"}
    defaults.update(overrides)
    return defaults


def create_project_payload(homeowner_id: str, **overrides) -> dict:
    defaults = {
        "homeowner_id": homeowner_id,
        "address": f"{uuid.uuid4().hex[:6]} Fixture Way",
        "basement_sqft": DEFAULTS["BASEMENT_SQFT"],
        "base_contract_cents": DEFAULTS["BASE_CONTRACT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_moisture_assessment_payload(**overrides) -> dict:
    """Benign SCREENING-grade readings by default: score 0 / LOW / ACCEPTED."""
    defaults = {
        "slab_moisture_lbs": 2.0,
        "interior_rh_pct": 50,
        "efflorescence_observed": False,
        "grading_deficit": False,
        "egress_windows_existing": 1,
        "ceiling_height_in": 86,
    }
    defaults.update(overrides)
    return defaults


def reopen_moisture_assessment_payload(**overrides) -> dict:
    defaults = {
        "remediation_notes": "interior drain tile + dehumidifier installed",
        "slab_moisture_lbs": 2.0,
        "interior_rh_pct": 50,
        "efflorescence_observed": False,
        "grading_deficit": False,
    }
    defaults.update(overrides)
    return defaults


def create_design_package_payload(**overrides) -> dict:
    defaults = {
        "layout_notes": "open rec room with wet bar",
        "mechanical_relocations": [],
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(**overrides) -> dict:
    """Compliant by default: R1 vacuous (0 bedrooms), R2 and R3 satisfied."""
    defaults = {
        "bedroom_count": 0,
        "windows": [],
        "ceiling_height_in": 86,
        "finished_area_sqft": 800,
        "low_area_sqft": 100,
        "prohibited_area_sqft": 0,
    }
    defaults.update(overrides)
    return defaults


def create_allowance_line_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("LINE"),
        "budgeted_cents": DEFAULTS["ALLOWANCE_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_scope_item(**overrides) -> dict:
    defaults = {"description": _uniq("item"), "qty": 1, "unit_cost_cents": 1000}
    defaults.update(overrides)
    return defaults


def create_change_order_payload(expected_project_version: int, **overrides) -> dict:
    defaults = {
        "scope_description": "additional scope",
        "kind": "ADD",
        "scope_items": [create_scope_item()],
        "allowance_draws": [],
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_work_phase_payload(subcontractor_id: str, **overrides) -> dict:
    defaults = {
        "trade": "PAINT",
        "zone": "REC",
        "start_date": "2026-06-01",
        "end_date": "2026-06-20",
        "crew_count": 2,
        "subcontractor_id": subcontractor_id,
    }
    defaults.update(overrides)
    return defaults


def create_site_log_payload(**overrides) -> dict:
    """Compliant log by default: no violation under the strike rule."""
    defaults = {
        "work_date": "2026-06-05",
        "containment_intact": True,
        "hepa_run_hours": 4,
        "noise_db_max": 55,
        "cleanup_completed": True,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    defaults = {"type": "FINAL"}
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(certificate_id: str, **overrides) -> dict:
    defaults = {
        "certificate_id": certificate_id,
        "description": "moisture damage behind drywall",
        "claimed_cents": 100000,
        "fresh_slab_moisture_lbs": 2.5,
        "fresh_interior_rh_pct": 55,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
