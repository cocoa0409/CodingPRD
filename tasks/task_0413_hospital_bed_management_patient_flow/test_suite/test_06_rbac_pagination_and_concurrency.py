"""RBAC denials, pagination bounds, list envelopes, OCC stale-bed guard,
derived-field reconciliation, and immediate consistency.

Queue B corner sections: validations, rbac, cross_cutting_complexity_layers,
consistency_model.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    set_clock, create_unit, add_clean_bed,
    create_unit_with_clean_bed, register_and_admit,
    create_queued_request, assign_request, confirm_request,
    create_transfer_payload, create_block_payload, create_confirm_payload,
    create_unit_payload, build_user_headers,
)
from test_helpers.fixtures import ADMIN, BCC, NURSE, TCA, CM


# ============================================================================
# Corner: validations / pagination_limit_zero_returns_invalid_pagination
# ============================================================================

def test_pagination_limit_zero_rejected(api, bed_control_headers):
    """PRD §2.3: "A limit outside the inclusive range of 1 through 100, or an offset
    below 0, is rejected with ERR_INVALID_PAGINATION (HTTP 422)."

    Design: Corner/validations/pagination_limit_zero_returns_invalid_pagination
    """
    res = api.list_units(bed_control_headers, params={"limit": 0})
    validate_error(res, "ERR_INVALID_PAGINATION", expected_status=422)


# ============================================================================
# Corner: validations / list_units_default_pagination_envelope
# ============================================================================

def test_list_units_default_envelope(api, flow_admin_headers, bed_control_headers):
    """PRD §2.3: "The response envelope's meta block carries limit, offset,
    total_count, and has_more for list responses, where total_count is the count of
    all matching records before the page window is applied and has_more is true when
    more records remain beyond the returned page."

    Design: Corner/validations/list_units_default_pagination_envelope
    """
    api.create_unit(create_unit_payload(name="L1", unit_type="MEDSURG"), flow_admin_headers)
    api.create_unit(create_unit_payload(name="L2", unit_type="ICU"), flow_admin_headers)

    data, meta = validate_paginated(api.list_units(bed_control_headers))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# ============================================================================
# Corner: rbac / charge_nurse_cannot_create_unit
# ============================================================================

def test_charge_nurse_cannot_create_unit(api, charge_nurse_headers):
    """PRD §2.1: "When the headers are present but the named role is not permitted to
    perform the requested operation under the authorization rules below, the request
    is rejected with ERR_FORBIDDEN (HTTP 403)." POST /units is FlowAdmin-only (§4).

    Design: Corner/rbac/charge_nurse_cannot_create_unit
    """
    res = api.create_unit(create_unit_payload(name="Nope", unit_type="MEDSURG"), charge_nurse_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ============================================================================
# Corner: rbac / case_manager_cannot_transfer_patient
# ============================================================================

def test_case_manager_cannot_transfer(api, case_manager_headers, bed_control_headers):
    """PRD §4: POST /encounters/{encounterId}/transfer is authorized for
    BedControlCoordinator only — PRD §2.1: "the request is rejected with ERR_FORBIDDEN
    (HTTP 403)."

    Design: Corner/rbac/case_manager_cannot_transfer_patient
    """
    set_clock("2026-06-05T08:00:00Z")
    unit = create_unit(name="RbWard", unit_type="MEDSURG")
    b1 = add_clean_bed(unit["id"], label="RB1")
    b2 = add_clean_bed(unit["id"], label="RB2")
    enc = register_and_admit(mrn="MS13", sex="MALE", origin="DIRECT")
    req = create_queued_request(enc["id"])
    assign_request(req["id"], b1["id"])
    confirm_request(req["id"], b1["version"])

    res = api.transfer_encounter(enc["id"], create_transfer_payload(b2["id"]), case_manager_headers)
    validate_error(res, "ERR_FORBIDDEN")
    fetched = validate_success(api.get_encounter(enc["id"], bed_control_headers), 200)
    assert fetched["current_bed_id"] == b1["id"]


# ============================================================================
# Corner: rbac / missing_role_header_returns_unauthenticated
# ============================================================================

def test_missing_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing or invalid, the request is rejected with
    ERR_UNAUTHENTICATED (HTTP 401) before any other processing."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    res = api.create_unit(create_unit_payload(name="Anon", unit_type="MEDSURG"), headers={})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ============================================================================
# Corner: rbac / evstech_shared_create_evs_task_allowed
# ============================================================================

def test_evstech_can_create_evs_task(api, flow_admin_headers, charge_nurse_headers, evs_tech_headers):
    """PRD §3.9: "Turnover tasks are created either automatically (when a bed becomes
    DIRTY on departure, as described above) or explicitly by a ChargeNurse,
    BedControlCoordinator, or EvsTech, who name the bed_id and an optional task_type of
    STAT, ISOLATION, or ROUTINE (defaulting to ROUTINE)."

    Design: Corner/rbac/evstech_shared_create_evs_task_allowed
    """
    unit = validate_success(
        api.create_unit({"name": "ShWard", "unit_type": "MEDSURG"}, flow_admin_headers), 201)
    bed = validate_success(
        api.create_bed(unit["id"], {"unit_id": unit["id"], "label": "SH1"},
                       charge_nurse_headers), 201)  # DIRTY
    res = api.create_evs_task({"bed_id": bed["id"], "task_type": "ROUTINE"}, evs_tech_headers)
    task = validate_success(res, 201)
    assert task["status"] == "REQUESTED"


# ============================================================================
# Corner: cross_cutting_complexity_layers / occ_stale_bed_version_on_confirm
# ============================================================================

def test_confirm_with_stale_bed_version_rejected(api, bed_control_headers, charge_nurse_headers):
    """PRD §2.10: "If that value does not equal the bed's current version, the
    confirmation is rejected with ERR_STALE_BED_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_bed_version_on_confirm
    """
    set_clock("2026-06-05T08:00:00Z")
    unit = create_unit(name="OcWard", unit_type="MEDSURG")
    bed = add_clean_bed(unit["id"], label="OC1")
    stale_version = bed["version"]
    enc = register_and_admit(mrn="MS15", sex="MALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    # A block+unblock+mark-clean cycle advances the bed version past stale_version.
    api.block_bed(unit["id"], bed["id"], create_block_payload("MAINTENANCE"), charge_nurse_headers)
    api.unblock_bed(unit["id"], bed["id"], charge_nurse_headers)
    api.mark_clean_bed(unit["id"], bed["id"], charge_nurse_headers)

    res = api.confirm_bed_request(req["id"], create_confirm_payload(stale_version), bed_control_headers)
    validate_error(res, "ERR_STALE_BED_VERSION", expected_status=412)
    fetched = validate_success(api.get_bed_request(req["id"], bed_control_headers), 200)
    assert fetched["status"] == "ASSIGNED"


# ============================================================================
# Corner: cross_cutting_complexity_layers / derived_field_reconciliation_unblock_restores_posture
# ============================================================================

def test_unblock_reconciles_posture_back_to_green(api, bed_control_headers, charge_nurse_headers):
    """PRD §2.7: "the system compares occupancy_pct against two inclusive thresholds:
    at 95.00 percent or above, posture is RED; at 85.00 percent or above but below
    95.00 percent, posture is YELLOW; below 85.00 percent, posture is GREEN."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_unblock_restores_posture
    """
    unit = create_unit(name="DfWard", unit_type="MEDSURG")
    bed = add_clean_bed(unit["id"], label="DF1")
    api.block_bed(unit["id"], bed["id"], create_block_payload("STAFFING"), charge_nurse_headers)
    api.unblock_bed(unit["id"], bed["id"], charge_nurse_headers)

    fetched = validate_success(api.get_unit(unit["id"], bed_control_headers), 200)
    assert fetched["staffed_bed_count"] == 1
    assert fetched["occupancy_pct"] == pytest.approx(0.0, abs=0.01)
    assert fetched["derived_posture"] == "GREEN"


# ============================================================================
# Corner: consistency_model / immediate_consistency_counts_visible_in_same_response
# ============================================================================

def test_occupied_count_immediately_visible_after_confirm(api, bed_control_headers):
    """PRD §2.8: "Any operation that changes a bed's status or membership refreshes the
    affected unit's counts, then refreshes its posture fields, in that order, so the
    two layers never disagree." PRD §3.5: "the assigned bed flips to OCCUPIED".

    Design: Corner/consistency_model/immediate_consistency_counts_visible_in_same_response
    """
    set_clock("2026-06-05T08:00:00Z")
    unit, bed = create_unit_with_clean_bed(unit_name="ImWard", unit_type="MEDSURG",
                                           bed_label="IM1")
    enc = register_and_admit(mrn="MS16", sex="FEMALE", origin="ED")
    req = create_queued_request(enc["id"], preferred_unit_id=unit["id"])
    assign_request(req["id"], bed["id"])
    confirm_request(req["id"], bed["version"])

    fetched_unit = validate_success(api.get_unit(unit["id"], bed_control_headers), 200)
    assert fetched_unit["occupied_bed_count"] == 1
    fetched_bed = validate_success(api.get_bed(unit["id"], bed["id"], bed_control_headers), 200)
    assert fetched_bed["status"] == "OCCUPIED"
