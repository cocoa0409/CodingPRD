"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
import hashlib
import itertools
import uuid

_nonce = itertools.count(1)


def _unique(prefix: str) -> str:
    return f"{prefix}-{next(_nonce)}-{uuid.uuid4().hex[:8]}"


def unique_content_hash() -> str:
    """64-char lowercase hex digest, unique per call (PRD §3.5)."""
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "company_name": _unique("Company"),
        "site_state_code": "UT",
    }
    defaults.update(overrides)
    return defaults


def create_job_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "job_number": _unique("J"),
        "quoted_price_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_panel_payload(**overrides) -> dict:
    defaults = {
        "panel_tag": _unique("P"),
        "enclosure_rating": "NEMA_1",
        "design_engineer_id": "de-001",
    }
    defaults.update(overrides)
    return defaults


def create_component_payload(**overrides) -> dict:
    defaults = {
        "part_number": _unique("PN"),
        "component_class": "BRANCH_PROTECTIVE",
        "unit_cost_cents": 45000,
        "lead_time_days": 21,
        "sccr_ka": 100,
        "heat_dissipation_w": 12,
    }
    defaults.update(overrides)
    # sccr_ka is optional (PRD §3.3: "null only for classes without a fault
    # rating"); an explicit None override omits the key entirely.
    if defaults.get("sccr_ka") is None:
        defaults.pop("sccr_ka", None)
    return defaults


def create_panel_component_payload(component_id: str, **overrides) -> dict:
    defaults = {"component_id": component_id, "quantity": 1}
    defaults.update(overrides)
    return defaults


def create_substitution_request_payload(original_line_id: str, proposed_component_id: str,
                                        **overrides) -> dict:
    defaults = {
        "original_line_id": original_line_id,
        "proposed_component_id": proposed_component_id,
        "reason": "vendor stockout",
    }
    defaults.update(overrides)
    return defaults


def create_test_point_payload(**overrides) -> dict:
    defaults = {
        "point_label": _unique("TP"),
        "expected_signal": "CONTINUITY",
        "sequence_no": 1,
    }
    defaults.update(overrides)
    return defaults


def create_test_session_payload(**overrides) -> dict:
    defaults = {"technician_id": "tt-001"}
    defaults.update(overrides)
    return defaults


def create_program_version_payload(expected_panel_version: int, **overrides) -> dict:
    defaults = {
        "version_tag": _unique("v"),
        "content_hash": unique_content_hash(),
        "expected_panel_version": expected_panel_version,
    }
    defaults.update(overrides)
    return defaults


def create_startup_session_payload(**overrides) -> dict:
    defaults = {
        "scheduled_start": "2026-10-01T08:00:00Z",
        "scheduled_end": "2026-10-01T18:00:00Z",
        "engineer_id": "fe-001",
        "support_mode": "ONSITE",
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(**overrides) -> dict:
    defaults = {
        "description": _unique("CO"),
        "price_delta_cents": 120000,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(panel_id: str, **overrides) -> dict:
    defaults = {
        "panel_id": panel_id,
        "defect_description": "control logic defect",
        "claimed_labor_hours": 1,
    }
    defaults.update(overrides)
    return defaults
