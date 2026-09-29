"""Payload factories — one per creating/modifying operation, input fields only."""

from typing import List, Optional

from .constants import TEST_DEFAULTS, TEST_INSTANTS
from .test_users import DEFAULT_CUSTOMER_REP_USER_ID


def create_project_payload(**overrides) -> dict:
    """POST /projects body (PRD §3.1)."""
    payload = {
        "customer_name": "Northstar Grocers",
        "facility_code": "DC-ATL-04",
        "customer_rep_user_id": DEFAULT_CUSTOMER_REP_USER_ID,
        "required_throughput_cph": TEST_DEFAULTS["REQUIRED_THROUGHPUT_CPH"],
        "contract_base_cents": TEST_DEFAULTS["CONTRACT_BASE_CENTS"],
        "authorized_ceiling_cents": TEST_DEFAULTS["AUTHORIZED_CEILING_CENTS"],
        "spares_budget_cents": TEST_DEFAULTS["SPARES_BUDGET_CENTS"],
        "service_tier": TEST_DEFAULTS["SERVICE_TIER"],
    }
    payload.update(overrides)
    return payload


def create_segment_payload(project_id: str, **overrides) -> dict:
    """POST /segments body (PRD §3.2).

    ``source_share_bps`` is optional: pass ``source_share_bps=None`` for an
    interior segment and the key is omitted from the body entirely.
    """
    payload = {
        "project_id": project_id,
        "segment_code": "IB-01",
        "equipment_class": "BELT",
        "rated_capacity_cph": 1500,
        "availability_pct": 96,
        "source_share_bps": 10000,
    }
    payload.update(overrides)
    if payload.get("source_share_bps", "keep") is None:
        payload.pop("source_share_bps")
    return payload


def patch_segment_payload(**overrides) -> dict:
    """PATCH /segments/{id} body — any subset of the three revisable fields."""
    payload = {}
    payload.update(overrides)
    return payload


def create_flow_link_payload(
    project_id: str, from_segment_id: str, to_segment_id: str, split_share_bps: int = 10000
) -> dict:
    """POST /flow-links body (PRD §3.2)."""
    return {
        "project_id": project_id,
        "from_segment_id": from_segment_id,
        "to_segment_id": to_segment_id,
        "split_share_bps": split_share_bps,
    }


def create_simulation_payload(method: str = "DEGRADED_AVAILABILITY") -> dict:
    """POST /projects/{id}/simulations body (PRD §3.3)."""
    return {"method": method}


def create_staging_bay_payload(**overrides) -> dict:
    """POST /staging-bays body (PRD §3.4)."""
    payload = {"bay_code": "BAY-1", "concurrent_capacity": 2}
    payload.update(overrides)
    return payload


def create_fabrication_lot_payload(
    project_id: str, staging_bay_id: str, segment_codes: Optional[List[str]] = None, **overrides
) -> dict:
    """POST /fabrication-lots body (PRD §3.4)."""
    payload = {
        "project_id": project_id,
        "lot_code": "LOT-100",
        "staging_bay_id": staging_bay_id,
        "segment_codes": segment_codes if segment_codes is not None else ["IB-01", "TR-02"],
        "occupancy_start_utc": TEST_INSTANTS["OCCUPANCY_START_UTC"],
        "occupancy_end_utc": TEST_INSTANTS["OCCUPANCY_END_UTC"],
    }
    payload.update(overrides)
    return payload


def create_fat_test_payload(
    fabrication_lot_id: str,
    expected_fabrication_lot_version: int,
    measured_cph: int = 1320,
    defect_count: int = 1,
) -> dict:
    """POST /fat-tests body (PRD §3.5)."""
    return {
        "fabrication_lot_id": fabrication_lot_id,
        "expected_fabrication_lot_version": expected_fabrication_lot_version,
        "measured_cph": measured_cph,
        "defect_count": defect_count,
    }


def create_site_zone_payload(project_id: str, **overrides) -> dict:
    """POST /site-zones body (PRD §3.6)."""
    payload = {
        "project_id": project_id,
        "zone_code": "Z-INBOUND",
        "throughput_share_bps": 10000,
        "protected_shift_start_minute": 480,
        "protected_shift_end_minute": 1080,
        "buffer_minutes": 60,
    }
    payload.update(overrides)
    return payload


def create_cutover_window_payload(
    project_id: str, site_zone_id: str, fabrication_lot_id: str, **overrides
) -> dict:
    """POST /cutover-windows body (PRD §3.6)."""
    payload = {
        "project_id": project_id,
        "site_zone_id": site_zone_id,
        "fabrication_lot_id": fabrication_lot_id,
        "start_utc": TEST_INSTANTS["WINDOW_START_UTC"],
        "end_utc": TEST_INSTANTS["WINDOW_END_UTC"],
    }
    payload.update(overrides)
    return payload


def abort_window_payload(abort_reason: str = "Legacy sorter PLC fault during changeover") -> dict:
    """POST /cutover-windows/{id}/abort body (PRD §3.6)."""
    return {"abort_reason": abort_reason}


def create_commissioning_ramp_payload(
    project_id: str, step_pct: int, measured_cph: int, sustained_minutes: int
) -> dict:
    """POST /commissioning-ramps body (PRD §3.7)."""
    return {
        "project_id": project_id,
        "step_pct": step_pct,
        "measured_cph": measured_cph,
        "sustained_minutes": sustained_minutes,
    }


def create_change_order_payload(project_id: str, **overrides) -> dict:
    """POST /change-orders body (PRD §3.8)."""
    payload = {
        "project_id": project_id,
        "title": "Add high-rate divert lane",
        "scope_delta_cph": 0,
        "price_delta_cents": 0,
        "schedule_delta_days": 0,
    }
    payload.update(overrides)
    return payload


def review_decision_payload(decision: str, expected_project_version: int, **overrides) -> dict:
    """POST /change-orders/{id}/review-decision body (PRD §3.8)."""
    payload = {
        "decision": decision,
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def create_spare_part_line_payload(project_id: str, **overrides) -> dict:
    """POST /spare-part-lines body (PRD §3.9)."""
    payload = {
        "project_id": project_id,
        "part_no": "MOTOR-3KW",
        "criticality": "CRITICAL",
        "unit_cost_cents": 850_000,
        "min_stock_qty": 2,
        "lead_time_days": 90,
    }
    payload.update(overrides)
    return payload


def spares_provisioning_payload(expected_project_version: int) -> dict:
    """POST /projects/{id}/spares-provisioning body (PRD §3.9)."""
    return {"expected_project_version": expected_project_version}


def create_acceptance_certificate_payload(project_id: str) -> dict:
    """POST /acceptance-certificates body (PRD §3.7)."""
    return {"project_id": project_id}


def create_performance_dispute_payload(
    acceptance_certificate_id: str, claimed_cph: int, damages_basis: str = "NAMEPLATE"
) -> dict:
    """POST /performance-disputes body (PRD §3.9)."""
    return {
        "acceptance_certificate_id": acceptance_certificate_id,
        "claimed_cph": claimed_cph,
        "damages_basis": damages_basis,
    }


def joint_retest_payload(retest_measured_cph: int) -> dict:
    """POST /performance-disputes/{id}/joint-retest body (PRD §3.9)."""
    return {"retest_measured_cph": retest_measured_cph}
