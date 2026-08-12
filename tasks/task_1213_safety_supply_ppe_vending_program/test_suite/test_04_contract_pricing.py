"""Contract pricing: tier resolution + fallback + admin-fee rounding
(PRD §3.1, §3.4, §3.7)."""
from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import (
    ADMIN,
    ANY,
    ApiErrorId,
    FINANCE,
    TECH,
    create_contract_price_payload,
    open_batch,
    set_clock,
    setup_cost_center,
    setup_employee,
    setup_item,
    setup_job_role,
    setup_machine_with_slot,
    setup_vend_scenario,
    stock_slot,
    vend,
    vend_ok,
)


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / contract_tier_resolution_cumulative_breakpoint
# ---------------------------------------------------------------------------


def _setup_tier_scenario():
    return setup_vend_scenario(
        sku="TIER-CF",
        base_price=500,
        period_limit_qty=100,
        period_window_days=30,
        capacity=100,
        par_level=0,
        initial_stock=50,
        contract_tiers=[
            {"min_period_qty": 0, "unit_price_cents": 450,
             "effective_from": "2026-01-01", "effective_to": "2026-12-31"},
            {"min_period_qty": 10, "unit_price_cents": 400,
             "effective_from": "2026-01-01", "effective_to": "2026-12-31"},
        ],
    )


def test_contract_tier_resolution_below_breakpoint(api):
    """PRD §3.4: "Candidate tiers are the item's contract price rows whose
    inclusive `effective_from`-to-`effective_to` window covers the vend date
    and whose `min_period_qty` is at most that cumulative; when candidates
    exist, the line's `unit_price_cents` comes from the candidate with the
    largest `min_period_qty`".

    Design: Difficulty/combinatorial_formula/contract_tier_resolution_cumulative_breakpoint
    """
    sc = _setup_tier_scenario()
    # First vend: 9 units at cumulative_before 0 -> 450.
    a = vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=9,
                idempotency_key="cf-1")
    assert a["unit_price_cents"] == 450
    # Second vend: cumulative_before 9 (still < 10 breakpoint) -> 450.
    b = vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
                idempotency_key="cf-2")
    assert b["unit_price_cents"] == 450, "cumulative_before 9 < breakpoint 10"


def test_contract_tier_resolution_at_breakpoint(api):
    """PRD §3.4: "when candidates exist, the line's `unit_price_cents` comes
    from the candidate with the largest `min_period_qty`, ties broken by the
    latest `effective_from` and then the earliest `created_at`."

    Design: Difficulty/combinatorial_formula/contract_tier_resolution_cumulative_breakpoint
    """
    sc = _setup_tier_scenario()
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=9,
            idempotency_key="cf-1")
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
            idempotency_key="cf-2")
    # Third vend: cumulative_before 10 -> 400.
    c = vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
                idempotency_key="cf-3")
    assert c["unit_price_cents"] == 400, "cumulative_before 10 >= breakpoint 10"
    slot_now = get_success_data(api.get_slot(sc["slot"]["id"], ANY))
    assert slot_now["on_hand_qty"] == 39


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / chargeback_snapshot_vs_rerate_diverge
# ---------------------------------------------------------------------------


def _setup_diverging_batch(api):
    """Set up the canonical snapshot/rerate divergence:
    cost center, role WELDER-DV, GENERAL item base 500 with tiers 0->450 and
    10->400, employee + manager, machine stocked to 60; vends A=6, B=6, C=4
    on three successive days; B reversed by manager; OPEN batch covering
    2026-05-01..2026-06-01.
    """
    sc = setup_vend_scenario(
        sku="GLOVE-DV",
        base_price=500,
        period_limit_qty=100,
        period_window_days=30,
        capacity=100,
        par_level=5,
        initial_stock=60,
        with_manager=True,
        contract_tiers=[
            {"min_period_qty": 0, "unit_price_cents": 450,
             "effective_from": "2026-01-01", "effective_to": "2026-12-31"},
            {"min_period_qty": 10, "unit_price_cents": 400,
             "effective_from": "2026-01-01", "effective_to": "2026-12-31"},
        ],
    )
    set_clock("2026-05-02T09:00:00Z")
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=6,
            idempotency_key="dv-a")
    set_clock("2026-05-03T09:00:00Z")
    vend_b = vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=6,
                     idempotency_key="dv-b")
    set_clock("2026-05-04T09:00:00Z")
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=4,
            idempotency_key="dv-c")
    # Reverse B; because B is unbilled, no OPEN batch is needed.
    get_success_data(api.reverse_issuance(vend_b["id"], sc["manager_headers"]))
    batch = open_batch(sc["cost_center"]["id"])
    sc["batch"] = batch
    return sc


def test_chargeback_snapshot_vs_rerate_divergence(api):
    """PRD §3.7: "Snapshot and rerate diverge precisely when a reversal
    removed lower-tier lines whose cumulative contribution had pushed later
    lines into a cheaper tier."

    Design: Difficulty/dual_variant_calc/chargeback_snapshot_vs_rerate_diverge
    """
    sc = _setup_diverging_batch(api)
    closed = validate_success(api.close_chargeback_batch(sc["batch"]["id"], FINANCE), 200)
    assert closed["line_count"] == 2
    assert closed["snapshot_total_cents"] == 4300
    assert closed["rerated_total_cents"] == 4500
    assert closed["snapshot_total_cents"] != closed["rerated_total_cents"], (
        "reversed line B removed its tier contribution on replay"
    )


def test_chargeback_admin_fee_and_total_from_rerate(api):
    """PRD §3.7: "The batch's `total_cents` is then the rerated total plus
    `adjustment_cents` plus `admin_fee_cents`, and the cost center's
    `ytd_charged_cents` rises by exactly that `total_cents`."
    PRD §3.7: "For each swept `POSTED` line, the fee is the line's rerated
    total multiplied by 250 ten-thousandths — two and a half percent —
    rounded half up to a whole cent; `admin_fee_cents` is the sum of those
    per-line fees."

    Design: Difficulty/dual_variant_calc/chargeback_snapshot_vs_rerate_diverge
    """
    sc = _setup_diverging_batch(api)
    closed = validate_success(api.close_chargeback_batch(sc["batch"]["id"], FINANCE), 200)
    # Two swept POSTED lines after reversal: A=6 units at vend-time cumulative 0
    # priced 450 (stored 2700); C=4 units at vend-time cumulative 12 -> 400
    # (stored 1600). Snapshot = 4300. Rerate replays A then C: cumulative before
    # A is 0 -> 450 * 6 = 2700; cumulative before C is 6 (< 10) -> 450 * 4 =
    # 1800. Rerated total = 4500.
    # Admin fee: round_half_up(2700*250/10000)=round_half_up(67.5)=68
    #            round_half_up(1800*250/10000)=round_half_up(45)=45  => 113.
    assert closed["admin_fee_cents"] == 113
    assert closed["total_cents"] == 4613
    cc_now = get_success_data(api.get_cost_center(sc["cost_center"]["id"], ANY))
    assert cc_now["ytd_charged_cents"] == 4613


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / restock_naive_qty_vs_committed_aware_suggestion
# ---------------------------------------------------------------------------


def _setup_restock_divergence(api):
    """Machine ACTIVE, slot cap 20 par 10; stock to 4 via first order, second
    order qty 6 left SUGGESTED (committed pipeline 6)."""
    item = setup_item(sku="REST-DV", base_list_price_cents=300)
    machine, slot = setup_machine_with_slot(item["id"], capacity=20, par_level=10,
                                            slot_code="S1")
    stock_slot(machine, slot, 4)
    second = get_success_data(
        api.create_restock_order(
            {"machine_id": machine["id"], "slot_id": slot["id"], "qty": 6}, TECH
        )
    )
    return machine, slot, second


def test_restock_manual_qty_naive_stored_verbatim(api):
    """PRD §3.6: "Manual orders start in `SUGGESTED` with `source` `MANUAL`,
    and their `qty` is exactly the requested amount: the naive
    fill-to-request variant."

    Design: Difficulty/dual_variant_calc/restock_naive_qty_vs_committed_aware_suggestion
    """
    machine, slot, _ = _setup_restock_divergence(api)
    resp = api.create_restock_order(
        {"machine_id": machine["id"], "slot_id": slot["id"], "qty": 8}, TECH
    )
    order = validate_success(resp, 201)
    assert order["qty"] == 8, "naive variant: requested qty stored verbatim"
    assert order["source"] == "MANUAL"
    assert order["status"] == "SUGGESTED"


def test_restock_suggested_qty_is_committed_aware(api):
    """PRD §3.6: "Every order, however created, also records a `suggested_qty`
    computed at creation as the committed-aware recommendation — `par_level`
    minus `on_hand_qty` minus the sum of `qty` over the slot's orders still
    in `SUGGESTED` or `PICKED`, floored at zero."

    Design: Difficulty/dual_variant_calc/restock_naive_qty_vs_committed_aware_suggestion
    """
    machine, slot, _ = _setup_restock_divergence(api)
    resp = api.create_restock_order(
        {"machine_id": machine["id"], "slot_id": slot["id"], "qty": 8}, TECH
    )
    order = validate_success(resp, 201)
    # par_level 10 - on_hand 4 - committed 6 = 0
    assert order["suggested_qty"] == 0, (
        "committed-aware: max(0, 10 - 4 - 6) == 0"
    )


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / chargeback_admin_fee_per_line_rounding
# ---------------------------------------------------------------------------


def _setup_three_line_fee_scenario(api):
    """Three vends of qty 3 at base 450 (no contract rows)."""
    sc = setup_vend_scenario(
        sku="FEE-CF",
        base_price=450,
        period_limit_qty=100,
        period_window_days=30,
        capacity=100,
        par_level=0,
        initial_stock=30,
    )
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=3,
            idempotency_key="ff-1")
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=3,
            idempotency_key="ff-2")
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=3,
            idempotency_key="ff-3")
    sc["batch"] = open_batch(sc["cost_center"]["id"])
    return sc


def test_admin_fee_rounding_per_line_then_sum(api):
    """PRD §3.7: "The rounding order is pinned: round each line first, then
    sum. Three 1350-cent lines make the difference concrete — each line's
    fee of 33.75 cents rounds to 34 and the three sum to 102, whereas
    summing first would round 101.25 to 101 and understate the fee by a
    cent."

    Design: Difficulty/combinatorial_formula/chargeback_admin_fee_per_line_rounding
    """
    sc = _setup_three_line_fee_scenario(api)
    closed = validate_success(api.close_chargeback_batch(sc["batch"]["id"], FINANCE), 200)
    assert closed["admin_fee_cents"] == 102, (
        "3 x round_half_up(33.75) = 3 x 34 = 102 (NOT 101 from sum-then-round)"
    )


def test_admin_fee_and_totals_three_lines(api):
    """PRD §3.7: "`line_count` counts the swept lines, and
    `snapshot_total_cents` sums their stored `line_total_cents` — vend-time
    pricing, frozen."
    PRD §3.7: "The batch's `total_cents` is then the rerated total plus
    `adjustment_cents` plus `admin_fee_cents`, and the cost center's
    `ytd_charged_cents` rises by exactly that `total_cents`."

    Design: Difficulty/combinatorial_formula/chargeback_admin_fee_per_line_rounding
    """
    sc = _setup_three_line_fee_scenario(api)
    closed = validate_success(api.close_chargeback_batch(sc["batch"]["id"], FINANCE), 200)
    assert closed["snapshot_total_cents"] == 4050
    assert closed["rerated_total_cents"] == 4050
    assert closed["total_cents"] == 4152  # 4050 + 0 + 102
    assert closed["line_count"] == 3
