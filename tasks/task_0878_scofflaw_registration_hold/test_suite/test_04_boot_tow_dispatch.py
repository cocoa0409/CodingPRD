"""Boot/tow dispatch: scofflaw gating, boot-count boundary, state-vs-fiscal precedence,
tow-yard capacity, slot conservation, four-eyes apply, and re-apply rejection.

Covers difficulty rules cross_entity_state_dependency (boot_requires_case_scofflaw),
boundary_precision_check (boot_count_eligibility_boundary),
priority_pair_validation_conflict (boot_dispatch_state_vs_fiscal),
resource_temporal_overlap (tow_yard_capacity_full),
compensating_invariant (towyard_slots_conserved_dispatch_cancel),
plus corner state/validation (apply_twice, sod_apply_same_user).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, TEST_USERS,
    setup_owner_vehicle_case, setup_case_with_violations, file_violation,
    setup_scofflaw_boot_eligible, setup_scofflaw_tow_eligible, setup_applied_boot_order,
    get_case, case_version, create_tow_yard, dispatch_boot, dispatch_tow, apply_order,
    create_boot_tow_order_payload, make_enforcement_headers,
)

EO = TEST_USERS["enforcement_officer_headers"]


def _yard_slot_count(api, yard_id):
    data, _ = validate_paginated(api.list_tow_yards(EO))
    for y in data:
        if y["id"] == yard_id:
            return y["occupied_slot_count"]
    raise AssertionError("tow yard not found in listing")


# ─── cross_entity_state_dependency / boot_requires_case_scofflaw ───────────

def test_boot_dispatch_succeeds_when_case_scofflaw(api):
    """PRD §3.6: "A successful dispatch creates the order in DISPATCHED status, records
    dispatched_by_user_id from the acting X-User-ID, and increments the case's version."

    Design: Difficulty/cross_entity_state_dependency/boot_requires_case_scofflaw
    """
    _, _, case, _ = setup_scofflaw_boot_eligible()
    assert get_case(case["id"])["case_status"] == "SCOFFLAW"
    order = dispatch_boot(case["id"])
    assert order["status"] == "DISPATCHED"
    assert order["scofflaw_case_id"] == case["id"]


def test_boot_dispatch_rejected_when_case_not_scofflaw(api):
    """PRD §3.6: "Dispatch requires case_status to be SCOFFLAW, failing which the order
    is refused with ERR_CASE_NOT_SCOFFLAW (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/boot_requires_case_scofflaw
    """
    _, _, case = setup_owner_vehicle_case()
    file_violation(case["id"], fine_amount_cents=10000)
    file_violation(case["id"], fine_amount_cents=10000)  # collectible 20000, count 2 -> COMPLIANT
    ver = case_version(case["id"])
    res = api.create_boot_tow_order(
        case["id"], create_boot_tow_order_payload(ver, action_type="BOOT"),
        make_enforcement_headers("eo-dispatch"))
    validate_error(res, "ERR_CASE_NOT_SCOFFLAW", expected_status=409)


# ─── boundary_precision_check / boot_count_eligibility_boundary ────────────

def test_exactly_five_outstanding_is_boot_eligible(api):
    """PRD §2.7: "A case is eligible_for_boot when it is in SCOFFLAW posture and its
    outstanding_count is at least the BOOT_COUNT_THRESHOLD of five outstanding citations."

    Design: Difficulty/boundary_precision_check/boot_count_eligibility_boundary
    """
    _, _, case, _ = setup_scofflaw_boot_eligible(fine_each=13000, count=5)
    fresh = get_case(case["id"])
    assert fresh["outstanding_count"] == 5
    assert fresh["eligible_for_boot"] is True
    order = dispatch_boot(case["id"])
    assert order["status"] == "DISPATCHED"


def test_four_outstanding_below_boot_threshold_rejected(api):
    """PRD §3.6: "a boot dispatch requires the case's outstanding_count to be at least the
    BOOT_COUNT_THRESHOLD of five, and if it is not the dispatch is rejected with
    ERR_BOOT_THRESHOLD_NOT_MET (HTTP 422)"

    Design: Difficulty/boundary_precision_check/boot_count_eligibility_boundary
    """
    # 4 x 13000 = collectible 52000 (>= 50000 -> SCOFFLAW) but count 4 (< 5).
    _, _, case, _ = setup_case_with_violations(4, 13000)
    fresh = get_case(case["id"])
    assert fresh["case_status"] == "SCOFFLAW"
    assert fresh["outstanding_count"] == 4
    ver = fresh["version"]
    res = api.create_boot_tow_order(
        case["id"], create_boot_tow_order_payload(ver, action_type="BOOT"),
        make_enforcement_headers("eo-dispatch"))
    validate_error(res, "ERR_BOOT_THRESHOLD_NOT_MET", expected_status=422)


# ─── priority_pair_validation_conflict / boot_dispatch_state_vs_fiscal ─────

def _state_and_fiscal_conflict(api, case):
    """COMPLIANT case with count 2: both the SCOFFLAW state gate and the boot-count
    fiscal gate fail on a boot dispatch."""
    ver = case_version(case["id"])
    return api.create_boot_tow_order(
        case["id"], create_boot_tow_order_payload(ver, action_type="BOOT"),
        make_enforcement_headers("eo-dispatch"))


def test_boot_state_error_wins_over_fiscal(api):
    """PRD §2.9: "then resource-state legality (the state errors of §3), then the
    domain-specific business rules — temporal windows, capacity, uniqueness, plan terms,
    separation of duties, fiscal thresholds, release conditions"

    Design: Difficulty/priority_pair_validation_conflict/boot_dispatch_state_vs_fiscal
    """
    _, _, case, _ = setup_case_with_violations(2, 10000)  # 20000, count 2 -> COMPLIANT
    res = _state_and_fiscal_conflict(api, case)
    validate_error(res, "ERR_CASE_NOT_SCOFFLAW", expected_status=409)


def test_boot_state_fiscal_conflict_creates_no_order(api):
    """PRD §3.6: "Dispatch requires case_status to be SCOFFLAW, failing which the order
    is refused with ERR_CASE_NOT_SCOFFLAW (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/boot_dispatch_state_vs_fiscal
    """
    _, _, case, _ = setup_case_with_violations(2, 10000)
    _state_and_fiscal_conflict(api, case)
    data, meta = validate_paginated(api.list_boot_tow_orders(
        EO, params={"scofflaw_case_id": case["id"]}))
    assert meta["total_count"] == 0


# ─── resource_temporal_overlap / tow_yard_capacity_full ────────────────────

def _fill_yard_then_overlap(api, capacity=1):
    _, _, caseA, _ = setup_scofflaw_tow_eligible()
    yard = create_tow_yard(capacity=capacity)
    dispatch_tow(caseA["id"], yard["id"], "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z")
    _, _, caseB, _ = setup_scofflaw_tow_eligible()
    verB = case_version(caseB["id"])
    res = api.create_boot_tow_order(
        caseB["id"],
        create_boot_tow_order_payload(
            verB, action_type="TOW", tow_yard_id=yard["id"],
            stored_from="2026-06-15T00:00:00Z", stored_until="2026-06-20T00:00:00Z"),
        make_enforcement_headers("eo-dispatch"))
    return yard, res


def test_overlapping_tow_at_capacity_rejected(api):
    """PRD §3.6: "if the chosen yard already has a number of overlapping active tows equal
    to or exceeding its capacity for the requested stored_from–stored_until interval, the
    dispatch is rejected with ERR_TOW_YARD_FULL (HTTP 409)"

    Design: Difficulty/resource_temporal_overlap/tow_yard_capacity_full
    """
    _, res = _fill_yard_then_overlap(api, capacity=1)
    validate_error(res, "ERR_TOW_YARD_FULL", expected_status=409)


def test_full_yard_occupied_slot_count_at_capacity(api):
    """PRD §3.6: "a yard's occupied_slot_count counts its tow orders that are DISPATCHED
    or APPLIED."

    Design: Difficulty/resource_temporal_overlap/tow_yard_capacity_full
    """
    yard, res = _fill_yard_then_overlap(api, capacity=1)
    validate_error(res, "ERR_TOW_YARD_FULL", expected_status=409)
    assert _yard_slot_count(api, yard["id"]) == 1


# ─── compensating_invariant / towyard_slots_conserved_dispatch_cancel ──────

def test_cancel_frees_reserved_tow_slot(api):
    """PRD §3.6: "An officer may instead cancel a DISPATCHED order (DISPATCHED → CANCELLED),
    which likewise frees a reserved tow slot"

    Design: Difficulty/compensating_invariant/towyard_slots_conserved_dispatch_cancel
    """
    _, _, case, _ = setup_scofflaw_tow_eligible()
    yard = create_tow_yard(capacity=2)
    order = dispatch_tow(case["id"], yard["id"], "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z")
    cancelled = validate_success(api.cancel_order(order["id"], EO), 200)
    assert cancelled["status"] == "CANCELLED"
    assert _yard_slot_count(api, yard["id"]) == 0


def test_tow_slot_reserved_on_dispatch_then_conserved(api):
    """PRD §3.6: "A tow dispatch reserves a slot (its yard's occupied_slot_count rises by 1)"

    Design: Difficulty/compensating_invariant/towyard_slots_conserved_dispatch_cancel
    """
    _, _, case, _ = setup_scofflaw_tow_eligible()
    yard = create_tow_yard(capacity=2)
    assert _yard_slot_count(api, yard["id"]) == 0
    order = dispatch_tow(case["id"], yard["id"], "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z")
    assert _yard_slot_count(api, yard["id"]) == 1
    api.cancel_order(order["id"], EO)
    assert _yard_slot_count(api, yard["id"]) == 0


# ─── corner: apply twice / segregation of duties ───────────────────────────

def test_apply_already_applied_order_rejected(api):
    """PRD §3.6: "An order in the wrong status for apply, release, or cancel is rejected
    with ERR_ORDER_NOT_ACTIVE (HTTP 409)."

    Design: Corner/state_machines/apply_twice_order_rejected
    """
    _, _, _, order = setup_applied_boot_order(fine_each=13000, count=5)
    res = api.apply_order(order["id"], make_enforcement_headers("eo-apply-2"))
    validate_error(res, "ERR_ORDER_NOT_ACTIVE", expected_status=409)


def test_apply_by_dispatcher_violates_segregation_of_duties(api):
    """PRD §3.6: "the acting X-User-ID must differ from dispatched_by_user_id, and if they
    are equal the request is rejected with ERR_SEGREGATION_OF_DUTIES (HTTP 403)."

    Design: Corner/validations/sod_apply_same_user_returns_403
    """
    _, _, case, _ = setup_scofflaw_boot_eligible(fine_each=13000, count=5)
    order = dispatch_boot(case["id"], dispatcher="eo-same")
    res = api.apply_order(order["id"], make_enforcement_headers("eo-same"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
