"""Dual-variant pricing (estimated vs reconciled), change-order re-pricing
cascades, the change-order branching fork, and OCC on change-order create.

Translates Difficulty/dual_variant_calc, Difficulty/transitive_cascade
(change-order arm), Difficulty/non_linear_state_machine (change-order fork),
and Corner/cross_cutting_complexity_layers (OCC).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_accepted_estimate,
    project_version, draft_change_order,
    find_draw_by_milestone,
    FENCE_120_GATE_SLOPE10, DECK_200_STAIRS_SLOPE20,
    create_change_order_payload,
)

PM = TEST_USERS["project_manager_headers"]


# ===========================================================================
# dual_variant_calc instance 1: estimated vs reconciled total diverge
# ===========================================================================
def test_reconciled_total_overrides_contract_after_site_measure_approve(api):
    """PRD §3.3: "the rollup is re-run with the same round-per-line tax rule to produce the estimate's `reconciled_total`. The `reconciled_total` is null until this approval happens. The project's `contract_total` is overwritten with the `reconciled_total`."
    Same two-line estimate (fence 120 -> measured 132, deck 200 unchanged):
    estimated contract_total 21605.04 vs reconciled_total 22266.02.

    Design: Difficulty/dual_variant_calc/estimate_estimated_vs_reconciled_total_diverge
    """
    ctx = setup_accepted_estimate(line_specs=[FENCE_120_GATE_SLOPE10, DECK_200_STAIRS_SLOPE20])
    pid = ctx["project"]["id"]
    fence_li = ctx["line_items"][0]
    est_id = ctx["estimate"]["id"]
    # Estimated contract_total before reconciliation.
    assert ctx["project"]["contract_total"] == 21605.04
    sm = get_success_data(api.create_site_measure(pid, {
        "measured_quantities": [{"line_item_id": fence_li["id"], "measured_units": 132}],
        "property_line_note": "5ft setback respected, no encroachment",
        "setback_ok": True,
    }, TEST_USERS["field_tech_headers"]))
    get_success_data(api.approve_site_measure(pid, sm["id"], PM))
    estimates = get_success_data(api.list_estimates(pid, PM))
    est = [e for e in estimates if e["id"] == est_id][0]
    assert est["contract_total"] == 21605.04
    assert est["reconciled_total"] == 22266.02


def test_reconciled_total_diverges_from_estimated_by_known_delta(api):
    """PRD §3.3: "for every `measured_quantities` entry, that line's quantity is treated as `measured_units` in place of the original `quantity_units` (material, style, accessory and slope all unchanged), and the rollup is re-run with the same round-per-line tax rule to produce the estimate's `reconciled_total`."
    PRD §3.3: "The project's `contract_total` is overwritten with the `reconciled_total`, the project bubbles from `ESTIMATED` to `MEASURED`, and the draws are rebalanced."
    Fence 120 -> 132 raises the reconciled basis: project contract_total flips
    to 22266.02, exactly 660.98 above the estimated 21605.04.

    Design: Difficulty/dual_variant_calc/estimate_estimated_vs_reconciled_total_diverge
    """
    ctx = setup_accepted_estimate(line_specs=[FENCE_120_GATE_SLOPE10, DECK_200_STAIRS_SLOPE20])
    pid = ctx["project"]["id"]
    fence_li = ctx["line_items"][0]
    sm = get_success_data(api.create_site_measure(pid, {
        "measured_quantities": [{"line_item_id": fence_li["id"], "measured_units": 132}],
        "property_line_note": "5ft setback respected, no encroachment",
        "setback_ok": True,
    }, TEST_USERS["field_tech_headers"]))
    get_success_data(api.approve_site_measure(pid, sm["id"], PM))
    proj = get_success_data(api.get_project(pid, PM))
    assert proj["contract_total"] == 22266.02
    assert round(22266.02 - 21605.04, 2) == 660.98


# ===========================================================================
# dual_variant_calc instance 2: change order estimate-basis reprice diverges
# ===========================================================================
def test_change_order_applied_on_estimate_basis_sets_total_delta(api):
    """PRD §3.7: "On apply, the target line's `quantity_units` is replaced by `new_quantity_units` when one was provided and its `accessory` by `new_accessory` when one was provided, and the line's `line_material_cost` is recomputed."
    PRD §3.7: "The estimate totals and the project's `contract_total` are then recomputed, the change order's `total_delta` is set to the new contract total minus the prior contract total".
    PRD §3.7: "When the project is still `ESTIMATED` (no `APPROVED` site measure yet), the untouched sibling lines keep their original `quantity_units` and the rollup runs on the estimate basis, so the new contract total derives from estimate quantities." Fence 120 -> 150 yields total_delta 1652.44.

    Design: Difficulty/dual_variant_calc/change_order_estimate_basis_vs_measured_basis_reprice_diverge
    """
    ctx = setup_accepted_estimate(line_specs=[FENCE_120_GATE_SLOPE10, DECK_200_STAIRS_SLOPE20])
    pid = ctx["project"]["id"]
    fence_li = ctx["line_items"][0]
    pv = project_version(pid)
    co = draft_change_order(pid, fence_li["id"], pv, new_quantity_units=150)
    resp = api.apply_change_order(co["id"], PM)
    co_after = validate_success(resp, expected_status=200)
    assert co_after["status"] == "APPLIED"
    assert co_after["total_delta"] == 1652.44


def test_change_order_applied_on_estimate_basis_new_contract_total(api):
    """PRD §3.7: "When the project is still `ESTIMATED` (no `APPROVED` site measure yet), the untouched sibling lines keep their original `quantity_units` and the rollup runs on the estimate basis, so the new contract total derives from estimate quantities."
    Applying fence 120 -> 150 on the estimate basis lifts the project's
    contract_total from 21605.04 to 23257.48.

    Design: Difficulty/dual_variant_calc/change_order_estimate_basis_vs_measured_basis_reprice_diverge
    """
    ctx = setup_accepted_estimate(line_specs=[FENCE_120_GATE_SLOPE10, DECK_200_STAIRS_SLOPE20])
    pid = ctx["project"]["id"]
    fence_li = ctx["line_items"][0]
    pv = project_version(pid)
    co = draft_change_order(pid, fence_li["id"], pv, new_quantity_units=150)
    get_success_data(api.apply_change_order(co["id"], PM))
    proj = get_success_data(api.get_project(pid, PM))
    assert proj["contract_total"] == 23257.48


# ===========================================================================
# transitive_cascade instance 1: CO apply cascades line -> contract -> draws
# ===========================================================================
def test_change_order_apply_cascades_to_lineitem_and_draws(api):
    """PRD §3.7: "the line's `line_material_cost` is recomputed."
    PRD §3.7: "The estimate totals and the project's `contract_total` are then recomputed, the change order's `total_delta` is set to the new contract total minus the prior contract total, the draws are rebalanced (with any deposit-paid amount locked exactly as in §3.3)".
    Fence 120 -> 150 recomputes the fence line to 6660.00, drives contract_total
    to 23257.48, and rebalances the (unpaid) DELIVERY draw to 6977.24.

    Design: Difficulty/transitive_cascade/change_order_apply_cascades_lineitem_estimate_draws_depth3
    """
    ctx = setup_accepted_estimate(line_specs=[FENCE_120_GATE_SLOPE10, DECK_200_STAIRS_SLOPE20])
    pid = ctx["project"]["id"]
    fence_li = ctx["line_items"][0]
    pv = project_version(pid)
    co = draft_change_order(pid, fence_li["id"], pv, new_quantity_units=150)
    get_success_data(api.apply_change_order(co["id"], PM))
    li_after = get_success_data(api.get_line_item(fence_li["id"], PM))
    proj = get_success_data(api.get_project(pid, PM))
    assert li_after["line_material_cost"] == 6660.00
    assert proj["contract_total"] == 23257.48
    draws = get_success_data(api.list_draws(pid, PM))
    delivery = find_draw_by_milestone(draws, "DELIVERY")
    assert delivery["amount"] == 6977.24


def test_change_order_apply_rebalances_final_draw(api):
    """PRD §3.3: "`FINAL`, if it is not already paid, absorbs the remainder so that the paid amounts plus the rebalanced amounts equal the contract total exactly."
    After fence 120 -> 150 (contract_total 23257.48, no deposit paid), the FINAL
    draw rebalances to 4651.50.

    Design: Difficulty/transitive_cascade/change_order_apply_cascades_lineitem_estimate_draws_depth3
    """
    ctx = setup_accepted_estimate(line_specs=[FENCE_120_GATE_SLOPE10, DECK_200_STAIRS_SLOPE20])
    pid = ctx["project"]["id"]
    fence_li = ctx["line_items"][0]
    pv = project_version(pid)
    co = draft_change_order(pid, fence_li["id"], pv, new_quantity_units=150)
    get_success_data(api.apply_change_order(co["id"], PM))
    draws = get_success_data(api.list_draws(pid, PM))
    final = find_draw_by_milestone(draws, "FINAL")
    assert final["amount"] == 4651.50


# ===========================================================================
# non_linear_state_machine instance 2: CO branching fork (reject path)
# ===========================================================================
def test_change_order_reject_lands_rejected_no_reprice(api):
    """PRD §3.7: "A `ProjectManager` may instead reject a draft change order, carrying a `decision`, which moves it from `DRAFT` to `REJECTED`, or withdraw it, moving it from `DRAFT` to `WITHDRAWN`."
    PRD §3.7: "The `total_delta` is null until the change order is applied."
    The reject branch does not re-price: the project's contract_total stays
    21605.04 and total_delta stays null (only an apply sets it).

    Design: Difficulty/non_linear_state_machine/change_order_branching_apply_reject_withdraw_fork
    """
    ctx = setup_accepted_estimate(line_specs=[FENCE_120_GATE_SLOPE10, DECK_200_STAIRS_SLOPE20])
    pid = ctx["project"]["id"]
    fence_li = ctx["line_items"][0]
    pv = project_version(pid)
    co = draft_change_order(pid, fence_li["id"], pv, new_quantity_units=150)
    resp = api.decide_change_order(co["id"], {"decision": "REJECT"}, PM)
    co_after = validate_success(resp, expected_status=200)
    assert co_after["status"] == "REJECTED"
    assert co_after["total_delta"] is None
    proj = get_success_data(api.get_project(pid, PM))
    assert proj["contract_total"] == 21605.04


def test_change_order_withdraw_lands_withdrawn(api):
    """PRD §3.7: "or withdraw it, moving it from `DRAFT` to `WITHDRAWN`. The terminal change-order states are `APPLIED`, `REJECTED`, and `WITHDRAWN`."
    PRD §3.7: "The `total_delta` is null until the change order is applied." — the
    withdraw branch leaves total_delta null.

    Design: Difficulty/non_linear_state_machine/change_order_branching_apply_reject_withdraw_fork
    """
    ctx = setup_accepted_estimate(line_specs=[FENCE_120_GATE_SLOPE10, DECK_200_STAIRS_SLOPE20])
    pid = ctx["project"]["id"]
    fence_li = ctx["line_items"][0]
    pv = project_version(pid)
    co = draft_change_order(pid, fence_li["id"], pv, new_quantity_units=150)
    resp = api.withdraw_change_order(co["id"], PM)
    co_after = validate_success(resp, expected_status=200)
    assert co_after["status"] == "WITHDRAWN"
    assert co_after["total_delta"] is None


# ===========================================================================
# Corner/cross_cutting: OCC stale + correct version
# ===========================================================================
def test_occ_stale_project_version_on_second_change_order_create(api):
    """PRD §2.8: "If they do not match — because a prior change-order apply or a site-measure reconciliation has already re-priced the project and advanced its `version` since the client last read it — the create is rejected with `ERR_STALE_PROJECT_VERSION` at HTTP 412."
    PRD §3.7: "the very act of creating the draft **increments the project's `version` by one**, claiming the pricing baseline" — so the pre-apply version
    is stale for a later create.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_project_version_on_change_order_create
    """
    ctx = setup_accepted_estimate(line_specs=[FENCE_120_GATE_SLOPE10, DECK_200_STAIRS_SLOPE20])
    pid = ctx["project"]["id"]
    fence_li, deck_li = ctx["line_items"]
    pv0 = project_version(pid)
    co1 = draft_change_order(pid, fence_li["id"], pv0, new_quantity_units=150)
    get_success_data(api.apply_change_order(co1["id"], PM))
    # Second create carrying the now-stale pv0.
    resp = api.create_change_order(
        create_change_order_payload(pid, deck_li["id"], pv0, new_quantity_units=220), PM)
    validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION.value)


def test_occ_correct_project_version_succeeds_after_reread(api):
    """PRD §2.8: "A request to create a change order must carry `expected_project_version`, a non-optional field holding the `version` of the target `Project` that the requester last observed. The server compares it against the project's current `version`."
    Re-reading the project after the first apply yields the fresh version; a
    second create carrying that version succeeds (201, DRAFT).

    Design: Corner/cross_cutting_complexity_layers/occ_correct_project_version_succeeds_after_reread
    """
    ctx = setup_accepted_estimate(line_specs=[FENCE_120_GATE_SLOPE10, DECK_200_STAIRS_SLOPE20])
    pid = ctx["project"]["id"]
    fence_li, deck_li = ctx["line_items"]
    pv0 = project_version(pid)
    co1 = draft_change_order(pid, fence_li["id"], pv0, new_quantity_units=150)
    get_success_data(api.apply_change_order(co1["id"], PM))
    pv1 = project_version(pid)
    resp = api.create_change_order(
        create_change_order_payload(pid, deck_li["id"], pv1, new_quantity_units=220), PM)
    co2 = validate_success(resp, expected_status=201)
    assert co2["status"] == "DRAFT"
