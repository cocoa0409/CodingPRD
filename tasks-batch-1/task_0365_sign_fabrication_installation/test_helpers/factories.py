"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Optional fields (those with defaults in the PRD,
e.g. illuminated/rush on a project, certified_aerial/active on a crew) are
omitted from the defaults so callers can exercise server-side defaulting.
"""
from .constants import FAR_FUTURE_ISO


def create_sign_project_payload(**overrides) -> dict:
    """POST /sign-projects input. illuminated and rush default server-side."""
    defaults = {
        "customer_name": "Test Sign Co",
        "site_address": "1 Test St",
        "jurisdiction_code": "COUNTY_C",
        "sign_type": "WALL",
        "face_width_in": 36,
        "face_height_in": 24,
        "placement_height_ft": 6,
    }
    defaults.update(overrides)
    return defaults


def create_art_proof_payload(**overrides) -> dict:
    """POST /sign-projects/{id}/art-proofs input."""
    defaults = {
        "artwork_uri": "s3://artwork/test.svg",
        "color_count": 3,
    }
    defaults.update(overrides)
    return defaults


def create_estimate_payload(art_proof_id, **overrides) -> dict:
    """POST /sign-projects/{id}/estimates input."""
    defaults = {
        "art_proof_id": art_proof_id,
        "substrate": "ALUMINUM",
        "valid_until_iso": FAR_FUTURE_ISO,
    }
    defaults.update(overrides)
    return defaults


def create_site_survey_payload(**overrides) -> dict:
    """POST /sign-projects/{id}/site-surveys input."""
    defaults = {
        "measured_clearance_ft": 30,
        "overhead_obstruction": False,
        "ground_bearing_ok": True,
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(**overrides) -> dict:
    """POST /sign-projects/{id}/permits input. expires_iso is optional."""
    defaults = {
        "permit_kind": "STRUCTURAL",
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    """POST /crews input. certified_aerial and active default server-side."""
    defaults = {
        "name": "Test Crew",
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(**overrides) -> dict:
    """POST /equipment input. in_service defaults server-side."""
    defaults = {
        "asset_tag": "EQ-TEST",
        "equipment_class": "BUCKET_TRUCK",
        "max_reach_ft": 40,
    }
    defaults.update(overrides)
    return defaults


def create_install_job_payload(work_order_id, crew_id, window_start_iso,
                               window_end_iso, **overrides) -> dict:
    """POST /sign-projects/{id}/install-jobs input. equipment_id is optional."""
    defaults = {
        "work_order_id": work_order_id,
        "crew_id": crew_id,
        "window_start_iso": window_start_iso,
        "window_end_iso": window_end_iso,
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(reason="scope change", **overrides) -> dict:
    """POST /sign-projects/{id}/change-orders input. All overrides optional."""
    defaults = {
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(install_job_id, defect_kind, reported_iso,
                                  **overrides) -> dict:
    """POST /sign-projects/{id}/warranty-claims input."""
    defaults = {
        "install_job_id": install_job_id,
        "defect_kind": defect_kind,
        "reported_iso": reported_iso,
    }
    defaults.update(overrides)
    return defaults


def create_reorder_payload(quantity=1, **overrides) -> dict:
    """POST /sign-projects/{id}/reorders input. reprice defaults server-side."""
    defaults = {
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults
