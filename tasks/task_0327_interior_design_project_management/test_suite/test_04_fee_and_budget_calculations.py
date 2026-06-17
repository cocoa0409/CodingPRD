"""Design-fee variants, order subtotals, and budget-health tiers.

Covers queue A: dual_variant_calc, combinatorial_formula, boundary_precision_check
(budget instance); and queue B: calculations (expected_delivery, flat-fee variant)
plus cross-cutting fee reconciliation / fee-model gating.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_client_headers,
    create_client_payload,
    create_project_payload,
    create_vendor_payload,
    create_ffe_item_payload,
    create_time_entry_payload,
    setup_project_with_approved_room,
    create_specified_selection,
    create_draft_order_with_lines,
    create_placed_order,
    create_delivered_order,
    project_version,
    advance_project_to,
    create_ffe_item,
)

ADMIN = TEST_USERS["studio_admin_headers"]
DESIGNER = TEST_USERS["designer_headers"]
PC = TEST_USERS["procurement_coordinator_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — dual_variant_calc / hourly_fee_provisional_vs_final_diverge_on_project
# ─────────────────────────────────────────────────────────────────────────────
def _hourly_project_to_installation():
    """HOURLY project (rate 15000) driven to INSTALLATION via one DELIVERED order."""
    s = setup_project_with_approved_room(
        fee_overrides={"fee_model": "HOURLY", "hourly_rate_cents": 15000}
    )
    project, room, vendor = s["project"], s["room"], s["vendor"]
    ffe = create_ffe_item(sku="HF-A", name="Sofa", category="FURNITURE",
                          list_unit_cost_cents=20000, lead_time_days=1)
    sel = create_specified_selection(project["id"], room["id"], ffe["id"], quantity=1,
                                     spec_note="a")
    create_delivered_order(project["id"], vendor["id"], [sel["id"]])
    advance_project_to(project["id"], "IN_DESIGN", actor=DESIGNER)
    advance_project_to(project["id"], "PROCUREMENT", actor=DESIGNER)
    advance_project_to(project["id"], "INSTALLATION", actor=PC)
    return s


def test_hourly_provisional_fee_counts_submitted_plus_approved_time(api):
    """PRD §3.9: "The provisional fee, shown while the project's status is anything
    other than CLOSED, is more inclusive: it counts time entries that are billable
    and in either SUBMITTED or APPROVED status, so not-yet-approved hours are
    reflected in the running estimate."
    PRD §3.9: "an entry's minutes are divided by fifteen, rounded up to the next
    whole increment, and each increment counts as a quarter of an hour."

    Design: Difficulty/dual_variant_calc/hourly_fee_provisional_vs_final_diverge_on_project
    """
    s = _hourly_project_to_installation()
    pid = s["project"]["id"]
    # 50min -> 1.0h, 95min -> 1.75h (APPROVED); 40min -> 0.75h (SUBMITTED).
    t1 = get_success_data(api.create_time_entry(pid, create_time_entry_payload(minutes=50), DESIGNER))
    t2 = get_success_data(api.create_time_entry(pid, create_time_entry_payload(minutes=95), DESIGNER))
    get_success_data(api.create_time_entry(pid, create_time_entry_payload(minutes=40), DESIGNER))
    validate_success(api.approve_time_entry(t1["id"], ADMIN), 200)
    validate_success(api.approve_time_entry(t2["id"], ADMIN), 200)

    quote = validate_success(api.fee_quote(pid, ADMIN), 200)
    # provisional = (1.0 + 1.75 + 0.75) h * 15000 = 3.5 * 15000 = 52500.
    # PRD §3.9: the fee-quote "returns both the provisional and final design-fee figures";
    # the provisional figure is the one under test here.
    assert quote["provisional_design_fee_cents"] == 52500, (
        f"provisional HOURLY fee should be 52500, got {quote['provisional_design_fee_cents']}"
    )


def test_hourly_final_fee_counts_only_approved_time_at_close(api):
    """PRD §3.9: "The final fee counts only time entries whose status is APPROVED
    and whose billable flag is true."
    PRD §3.2: "On a successful close, the project's status becomes CLOSED, the design
    fee is finalized and written into design_fee_cents (using the final-fee
    computation of §3.9)"

    Design: Difficulty/dual_variant_calc/hourly_fee_provisional_vs_final_diverge_on_project
    """
    s = _hourly_project_to_installation()
    pid = s["project"]["id"]
    t1 = get_success_data(api.create_time_entry(pid, create_time_entry_payload(minutes=50), DESIGNER))
    t2 = get_success_data(api.create_time_entry(pid, create_time_entry_payload(minutes=95), DESIGNER))
    get_success_data(api.create_time_entry(pid, create_time_entry_payload(minutes=40), DESIGNER))
    validate_success(api.approve_time_entry(t1["id"], ADMIN), 200)
    validate_success(api.approve_time_entry(t2["id"], ADMIN), 200)

    closed = validate_success(api.close_project(pid, ADMIN), 200)
    assert closed["status"] == "CLOSED"
    # final = (1.0 + 1.75) h * 15000 = 2.75 * 15000 = 41250.
    assert closed["design_fee_cents"] == 41250, (
        f"final HOURLY fee should be 41250, got {closed['design_fee_cents']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — dual_variant_calc / markup_fee_provisional_vs_final_diverge_on_committed_base
# ─────────────────────────────────────────────────────────────────────────────
def _markup_project_with_placed_and_draft_order():
    """MARKUP project (0.30); O1 placed (subtotal 64893), O2 still DRAFT (subtotal 40000)."""
    s = setup_project_with_approved_room(
        fee_overrides={"fee_model": "MARKUP", "markup_pct": 0.30}
    )
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    f1 = create_ffe_item(sku="S-A", name="Chair", category="FURNITURE", list_unit_cost_cents=12999, lead_time_days=10)
    f2 = create_ffe_item(sku="S-B", name="Lamp", category="LIGHTING", list_unit_cost_cents=4550, lead_time_days=5)
    f3 = create_ffe_item(sku="S-C", name="Vase", category="DECOR", list_unit_cost_cents=899, lead_time_days=2)
    f4 = create_ffe_item(sku="S-D", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=7)
    s1 = create_specified_selection(pid, rid, f1["id"], quantity=3, trade_discount_pct=0.125, spec_note="oak")
    s2 = create_specified_selection(pid, rid, f2["id"], quantity=7, trade_discount_pct=0.175, spec_note="brass")
    s3 = create_specified_selection(pid, rid, f3["id"], quantity=5, trade_discount_pct=0.0, spec_note="glass")
    s4 = create_specified_selection(pid, rid, f4["id"], quantity=2, trade_discount_pct=0.0, spec_note="linen")
    o1 = create_placed_order(pid, vid, [s1["id"], s2["id"], s3["id"]])
    o2 = create_draft_order_with_lines(pid, vid, [s4["id"]],
                                       window_start="2026-08-01T00:00:00Z",
                                       window_end="2026-08-02T00:00:00Z")
    return s, o1, o2


def test_markup_order_subtotals_round_then_sum(api):
    """PRD §3.6: "the order subtotal is then the exact integer sum of those
    already-rounded snapshots across the order's lines."
    PRD §3.4: "That line net is the snapshotted unit cost multiplied by the quantity,
    multiplied by one minus the trade discount fraction, with the product rounded to
    whole cents using round-half-up."

    Design: Difficulty/dual_variant_calc/markup_fee_provisional_vs_final_diverge_on_committed_base
    """
    s, o1, o2 = _markup_project_with_placed_and_draft_order()
    # round-then-sum: 34122 + 26276 + 4495 = 64893.
    assert o1["order_subtotal_cents"] == 64893, o1["order_subtotal_cents"]
    assert o2["order_subtotal_cents"] == 40000, o2["order_subtotal_cents"]


def test_markup_provisional_fee_includes_draft_order_base(api):
    """PRD §3.9: "The provisional fee uses a broader base: it adds to that set the
    subtotals of orders still in DRAFT, so the committed base for the provisional
    markup fee covers orders in DRAFT, ORDERED, IN_TRANSIT, or DELIVERED."
    PRD §3.6: "The project's committed_cents is the sum of order_subtotal_cents over
    every procurement order of the project whose status is ORDERED, IN_TRANSIT, or
    DELIVERED."

    Design: Difficulty/dual_variant_calc/markup_fee_provisional_vs_final_diverge_on_committed_base
    """
    s, o1, o2 = _markup_project_with_placed_and_draft_order()
    pid = s["project"]["id"]
    quote = validate_success(api.fee_quote(pid, ADMIN), 200)
    # provisional = round(0.30 * (64893 + 40000)) = round(31467.9) = 31468.
    # PRD §3.9: the fee-quote returns both the provisional and final design-fee figures.
    assert quote["provisional_design_fee_cents"] == 31468, quote["provisional_design_fee_cents"]
    # committed only counts the placed ORDERED order O1.
    project = validate_success(api.get_project(pid, ADMIN), 200)
    assert project["committed_cents"] == 64893, project["committed_cents"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — combinatorial_formula / order_subtotal_round_then_sum_pinned
# ─────────────────────────────────────────────────────────────────────────────
def _flat_project_three_fractional_selections():
    s = setup_project_with_approved_room(fee_overrides={"fee_model": "FLAT", "flat_fee_cents": 100000})
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    f1 = create_ffe_item(sku="RC-A", name="Chair", category="FURNITURE", list_unit_cost_cents=12999, lead_time_days=1)
    f2 = create_ffe_item(sku="RC-B", name="Lamp", category="LIGHTING", list_unit_cost_cents=4550, lead_time_days=1)
    f3 = create_ffe_item(sku="RC-C", name="Vase", category="DECOR", list_unit_cost_cents=899, lead_time_days=1)
    s1 = create_specified_selection(pid, rid, f1["id"], quantity=3, trade_discount_pct=0.125, spec_note="a")
    s2 = create_specified_selection(pid, rid, f2["id"], quantity=7, trade_discount_pct=0.175, spec_note="b")
    s3 = create_specified_selection(pid, rid, f3["id"], quantity=5, trade_discount_pct=0.0, spec_note="c")
    return s, [s1, s2, s3], vid


def test_selection_line_nets_round_half_up_per_line(api):
    """PRD §3.4: "That line net is the snapshotted unit cost multiplied by the
    quantity, multiplied by one minus the trade discount fraction, with the product
    rounded to whole cents using round-half-up."

    Design: Difficulty/combinatorial_formula/order_subtotal_round_then_sum_pinned
    """
    s, sels, _vid = _flat_project_three_fractional_selections()
    # 12999*3*0.875 = 34122.375 -> 34122; 4550*7*0.825 = 26276.25 -> 26276; 899*5 = 4495.
    assert sels[0]["line_net_cents"] == 34122, sels[0]["line_net_cents"]
    assert sels[1]["line_net_cents"] == 26276, sels[1]["line_net_cents"]
    assert sels[2]["line_net_cents"] == 4495, sels[2]["line_net_cents"]


def test_order_subtotal_is_round_then_sum_not_sum_then_round(api):
    """PRD §3.6: "Each selection line is rounded to whole cents first, when its
    line_net_cents is computed in §3.4; the order subtotal is then the exact integer
    sum of those already-rounded snapshots across the order's lines. The system does
    not sum the exact fractional products and round once at the end."

    Design: Difficulty/combinatorial_formula/order_subtotal_round_then_sum_pinned
    """
    s, sels, vid = _flat_project_three_fractional_selections()
    pid = s["project"]["id"]
    order = create_draft_order_with_lines(pid, vid, [x["id"] for x in sels])
    # round-then-sum = 34122 + 26276 + 4495 = 64893 (NOT 64894 from sum-then-round).
    assert order["order_subtotal_cents"] == 64893, order["order_subtotal_cents"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — combinatorial_formula / budget_health_tiered_threshold_three_inputs
# ─────────────────────────────────────────────────────────────────────────────
def _flat_project_budget_at_exactly_080():
    """FLAT budget=100000, flat_fee=15107; one placed order subtotal 64893 -> util 0.80."""
    s = setup_project_with_approved_room(
        fee_overrides={"fee_model": "FLAT", "flat_fee_cents": 15107, "budget_cents": 100000}
    )
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    f1 = create_ffe_item(sku="BG-A", name="Chair", category="FURNITURE", list_unit_cost_cents=12999, lead_time_days=1)
    f2 = create_ffe_item(sku="BG-B", name="Lamp", category="LIGHTING", list_unit_cost_cents=4550, lead_time_days=1)
    f3 = create_ffe_item(sku="BG-C", name="Vase", category="DECOR", list_unit_cost_cents=899, lead_time_days=1)
    s1 = create_specified_selection(pid, rid, f1["id"], quantity=3, trade_discount_pct=0.125, spec_note="a")
    s2 = create_specified_selection(pid, rid, f2["id"], quantity=7, trade_discount_pct=0.175, spec_note="b")
    s3 = create_specified_selection(pid, rid, f3["id"], quantity=5, trade_discount_pct=0.0, spec_note="c")
    o1 = create_placed_order(pid, vid, [s1["id"], s2["id"], s3["id"]])
    return s, o1


def test_budget_remaining_is_budget_minus_committed_minus_fee(api):
    """PRD §3.8: "the project's budget_remaining_cents (the budget less committed
    spend less the design fee) is recomputed alongside it."

    Design: Difficulty/combinatorial_formula/budget_health_tiered_threshold_three_inputs
    """
    s, _o1 = _flat_project_budget_at_exactly_080()
    project = validate_success(api.get_project(s["project"]["id"], ADMIN), 200)
    assert project["committed_cents"] == 64893, project["committed_cents"]
    # 100000 - 64893 - 15107 = 20000.
    assert project["budget_remaining_cents"] == 20000, project["budget_remaining_cents"]


def test_budget_status_green_at_exactly_080_utilization(api):
    """PRD §3.8: "The tier boundaries belong to the lower band: a utilization of
    exactly eighty percent is GREEN, and a utilization of exactly one hundred percent
    is AMBER."
    PRD §3.8: "Utilization is the ratio of committed spend plus the design fee to the
    total budget"

    Design: Difficulty/combinatorial_formula/budget_health_tiered_threshold_three_inputs
    """
    s, _o1 = _flat_project_budget_at_exactly_080()
    project = validate_success(api.get_project(s["project"]["id"], ADMIN), 200)
    # (64893 + 15107) / 100000 = 0.80 exactly -> GREEN.
    assert project["budget_status"] == "GREEN", project["budget_status"]
    assert project["posture"] == "OPEN", project["posture"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — boundary_precision_check / budget_utilization_exactly_080_is_green_not_amber
# ─────────────────────────────────────────────────────────────────────────────
def _flat_project_080_with_second_draft_order():
    """First order placed at util exactly 0.80 (GREEN); a second small DRAFT order ready."""
    s = setup_project_with_approved_room(
        fee_overrides={"fee_model": "FLAT", "flat_fee_cents": 15107, "budget_cents": 100000}
    )
    pid, rid = s["project"]["id"], s["room"]["id"]
    v1 = s["vendor"]
    v2 = get_success_data(api_client.create_vendor(create_vendor_payload(name="V2", trade="MILLWORK"), PC))
    f1 = create_ffe_item(sku="B8-A", name="Chair", category="FURNITURE", list_unit_cost_cents=12999, lead_time_days=1)
    f2 = create_ffe_item(sku="B8-B", name="Lamp", category="LIGHTING", list_unit_cost_cents=4550, lead_time_days=1)
    f3 = create_ffe_item(sku="B8-C", name="Vase", category="DECOR", list_unit_cost_cents=899, lead_time_days=1)
    f4 = create_ffe_item(sku="B8-D", name="Pillow", category="TEXTILE", list_unit_cost_cents=1000, lead_time_days=1)
    s1 = create_specified_selection(pid, rid, f1["id"], quantity=3, trade_discount_pct=0.125, spec_note="a")
    s2 = create_specified_selection(pid, rid, f2["id"], quantity=7, trade_discount_pct=0.175, spec_note="b")
    s3 = create_specified_selection(pid, rid, f3["id"], quantity=5, trade_discount_pct=0.0, spec_note="c")
    s4 = create_specified_selection(pid, rid, f4["id"], quantity=1, trade_discount_pct=0.0, spec_note="d")
    create_placed_order(pid, v1["id"], [s1["id"], s2["id"], s3["id"]])
    o2 = create_draft_order_with_lines(pid, v2["id"], [s4["id"]],
                                       window_start="2026-09-01T00:00:00Z",
                                       window_end="2026-09-02T00:00:00Z")
    return s, o2


def test_green_at_080_does_not_gate_a_second_order(api):
    """PRD §3.8: "The tier boundaries belong to the lower band: a utilization of
    exactly eighty percent is GREEN"
    PRD §3.8: "An AMBER status drives the posture to BUDGET_REVIEW, which blocks the
    placement of new orders with ERR_BUDGET_GATE."

    Design: Difficulty/boundary_precision_check/budget_utilization_exactly_080_is_green_not_amber
    """
    s, o2 = _flat_project_080_with_second_draft_order()
    pid = s["project"]["id"]
    project = validate_success(api.get_project(pid, ADMIN), 200)
    assert project["budget_status"] == "GREEN", project["budget_status"]
    pv = project_version(pid)
    placed = validate_success(api.place_order(o2["id"], {"expected_project_version": pv}, PC), 200)
    assert placed["status"] == "ORDERED", placed["status"]


def test_one_cent_over_080_is_amber_and_gates_second_order(api):
    """PRD §3.8: "it is AMBER when utilization is greater than eighty percent but at
    most one hundred percent"
    PRD §3.5: "an AMBER-driven BUDGET_REVIEW posture surfaces as ERR_BUDGET_GATE"

    Design: Difficulty/boundary_precision_check/budget_utilization_exactly_080_is_green_not_amber
    """
    # flat_fee 15108 (one cent more): (64893 + 15108)/100000 = 0.80001 -> AMBER.
    s = setup_project_with_approved_room(
        fee_overrides={"fee_model": "FLAT", "flat_fee_cents": 15108, "budget_cents": 100000}
    )
    pid, rid = s["project"]["id"], s["room"]["id"]
    v1 = s["vendor"]
    v2 = get_success_data(api.create_vendor(create_vendor_payload(name="V2", trade="MILLWORK"), PC))
    f1 = create_ffe_item(sku="B9-A", name="Chair", category="FURNITURE", list_unit_cost_cents=12999, lead_time_days=1)
    f2 = create_ffe_item(sku="B9-B", name="Lamp", category="LIGHTING", list_unit_cost_cents=4550, lead_time_days=1)
    f3 = create_ffe_item(sku="B9-C", name="Vase", category="DECOR", list_unit_cost_cents=899, lead_time_days=1)
    f4 = create_ffe_item(sku="B9-D", name="Pillow", category="TEXTILE", list_unit_cost_cents=1000, lead_time_days=1)
    s1 = create_specified_selection(pid, rid, f1["id"], quantity=3, trade_discount_pct=0.125, spec_note="a")
    s2 = create_specified_selection(pid, rid, f2["id"], quantity=7, trade_discount_pct=0.175, spec_note="b")
    s3 = create_specified_selection(pid, rid, f3["id"], quantity=5, trade_discount_pct=0.0, spec_note="c")
    s4 = create_specified_selection(pid, rid, f4["id"], quantity=1, trade_discount_pct=0.0, spec_note="d")
    create_placed_order(pid, v1["id"], [s1["id"], s2["id"], s3["id"]])
    o2 = create_draft_order_with_lines(pid, v2["id"], [s4["id"]],
                                       window_start="2026-09-01T00:00:00Z",
                                       window_end="2026-09-02T00:00:00Z")
    project = validate_success(api.get_project(pid, ADMIN), 200)
    assert project["budget_status"] == "AMBER", project["budget_status"]
    pv = project_version(pid)
    res = api.place_order(o2["id"], {"expected_project_version": pv}, PC)
    validate_error(res, "ERR_BUDGET_GATE")


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — calculations / expected_delivery_uses_max_lead_plus_vendor_buffer
# ─────────────────────────────────────────────────────────────────────────────
def test_expected_delivery_uses_max_lead_plus_vendor_buffer(api):
    """PRD §3.6: "The order's lead time is the maximum of those per-line sums across
    all lines. The expected delivery instant is the moment at which the order entered
    ORDERED, advanced forward by that many whole days."

    Design: Corner/calculations/expected_delivery_uses_max_lead_plus_vendor_buffer
    """
    s = setup_project_with_approved_room()
    pid, rid = s["project"]["id"], s["room"]["id"]
    vendor = get_success_data(api.create_vendor(
        create_vendor_payload(name="V", trade="SUPPLIER", lead_time_buffer_days=3), PC))
    f1 = create_ffe_item(sku="ED-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=10)
    f2 = create_ffe_item(sku="ED-B", name="Lamp", category="LIGHTING", list_unit_cost_cents=4000, lead_time_days=5)
    s1 = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    s2 = create_specified_selection(pid, rid, f2["id"], quantity=1, spec_note="b")
    order = create_draft_order_with_lines(
        pid, vendor["id"], [s1["id"], s2["id"]],
        window_start="2026-07-01T00:00:00Z", window_end="2026-07-10T00:00:00Z")
    pv = project_version(pid)
    placed = validate_success(api.place_order(order["id"], {"expected_project_version": pv}, PC), 200)
    # lead = MAX(10+3, 5+3) = 13 days. Verify expected_delivery_at = ordered + 13 days.
    assert placed["expected_delivery_at"] is not None
    from datetime import datetime, timedelta

    def _parse(ts):
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))

    eta = _parse(placed["expected_delivery_at"])
    ordered_at = _parse(placed["updated_at"])
    delta_days = (eta - ordered_at).total_seconds() / 86400.0
    assert abs(delta_days - 13) < 0.01, (
        f"expected_delivery_at should be ORDERED + 13 days, got {delta_days} days"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — calculations / flat_fee_provisional_equals_final
# ─────────────────────────────────────────────────────────────────────────────
def test_flat_fee_provisional_equals_final(api):
    """PRD §3.9: "Under the FLAT model the fee is simply flat_fee_cents, and the
    provisional and final figures are identical."

    Design: Corner/calculations/flat_fee_provisional_equals_final
    """
    s = setup_project_with_approved_room(
        fee_overrides={"fee_model": "FLAT", "flat_fee_cents": 250000})
    pid, rid, vid = s["project"]["id"], s["room"]["id"], s["vendor"]["id"]
    advance_project_to(pid, "IN_DESIGN", actor=DESIGNER)
    advance_project_to(pid, "PROCUREMENT", actor=DESIGNER)
    f1 = create_ffe_item(sku="FF-A", name="Sofa", category="FURNITURE", list_unit_cost_cents=20000, lead_time_days=1)
    sel = create_specified_selection(pid, rid, f1["id"], quantity=1, spec_note="a")
    create_delivered_order(pid, vid, [sel["id"]])
    advance_project_to(pid, "INSTALLATION", actor=PC)

    quote = validate_success(api.fee_quote(pid, ADMIN), 200)
    # PRD §3.9: FLAT provisional == final; the fee-quote returns both figures.
    assert quote["provisional_design_fee_cents"] == 250000, quote["provisional_design_fee_cents"]
    assert quote["final_design_fee_cents"] == 250000, quote["final_design_fee_cents"]
    closed = validate_success(api.close_project(pid, ADMIN), 200)
    assert closed["design_fee_cents"] == 250000, closed["design_fee_cents"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — cross_cutting / time_entry_approve_recomputes_design_fee
# ─────────────────────────────────────────────────────────────────────────────
def test_approve_time_entry_recomputes_provisional_fee(api):
    """PRD §3.9: "A successful approval moves the entry to APPROVED, recomputes the
    project's design fee (both its provisional and final figures) and consequently
    its budget tier and posture, and increments the entry's version."

    Design: Corner/cross_cutting_complexity_layers/time_entry_approve_recomputes_design_fee
    """
    client = get_success_data(api.create_client(create_client_payload(email="tr.c1@x.com"), ADMIN))
    project = get_success_data(api.create_project(
        create_project_payload(client["id"], client_name="Tr", brief_summary="x",
                               budget_cents=100000000, fee_model="HOURLY",
                               hourly_rate_cents=15000, flat_fee_cents=0), ADMIN))
    pid = project["id"]
    t1 = get_success_data(api.create_time_entry(pid, create_time_entry_payload(minutes=60), DESIGNER))
    approved = validate_success(api.approve_time_entry(t1["id"], ADMIN), 200)
    assert approved["status"] == "APPROVED"
    quote = validate_success(api.fee_quote(pid, ADMIN), 200)
    # 60min -> 1.0h * 15000 = 15000.
    # PRD §3.9: the fee-quote returns both the provisional and final design-fee figures.
    assert quote["provisional_design_fee_cents"] == 15000, quote["provisional_design_fee_cents"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — cross_cutting / approve_time_entry_on_flat_project_rejected
# ─────────────────────────────────────────────────────────────────────────────
def test_approve_time_entry_on_flat_project_rejected(api):
    """PRD §3.9: "A studio administrator approves a submitted entry, but only when
    the project's fee_model is HOURLY; approving against any other fee model is
    rejected with ERR_FEE_MODEL_MISMATCH."

    Design: Corner/cross_cutting_complexity_layers/approve_time_entry_on_flat_project_rejected
    """
    client = get_success_data(api.create_client(create_client_payload(email="fm.c1@x.com"), ADMIN))
    project = get_success_data(api.create_project(
        create_project_payload(client["id"], client_name="Fm", brief_summary="x",
                               budget_cents=100000000, fee_model="FLAT",
                               flat_fee_cents=100000), ADMIN))
    pid = project["id"]
    t1 = get_success_data(api.create_time_entry(pid, create_time_entry_payload(minutes=30), DESIGNER))
    res = api.approve_time_entry(t1["id"], ADMIN)
    validate_error(res, "ERR_FEE_MODEL_MISMATCH")
    te = validate_success(api.get_time_entry(t1["id"], ADMIN), 200)
    assert te["status"] == "SUBMITTED"
