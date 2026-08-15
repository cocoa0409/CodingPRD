"""Invoice and settlement calculations (queue A rules 1, 2; queue B calculations)."""
import pytest

from test_helpers import (
    ApiErrorId,
    CSR,
    PARTS_BUYER,
    SHOP_MANAGER,
    TECHNICIAN,
    api_client,
    approve_quote,
    book_cell,
    close_work_order,
    complete_repair,
    core_return_exchange,
    create_customer,
    create_exchange_agreement,
    create_part,
    create_parts_requisition,
    create_test_cell,
    create_unit,
    create_work_order,
    fulfill_exchange,
    generate_invoice,
    get_customer,
    get_exchange_agreement,
    get_unit,
    get_work_order,
    issue_received_requisition,
    make_customer_headers,
    parse_instant,
    record_test_results,
    release_work_order,
    review_warranty_claim,
    set_clock,
    setup_exchange_fulfilled,
    setup_warranty_claim_submitted,
    setup_work_order_closed,
    submit_quote,
    validate_error,
    validate_paginated,
    validate_success,
)


def _drive_overhaul_to_released(
        customer,
        part,
        unit,
        approve_delay_iso=None,
        test_clock="2026-08-02T02:00:00Z",
        booking_window=("2026-08-02T01:00:00Z", "2026-08-02T05:00:00Z"),
        labor_estimate_cents=2000000,
        parts_estimate_cents=1000000,
        cell_name="CELL-A",
        requisition_specs=None,
        technician_user_id="tech-1",
        inspector_user_id="insp-9"):
    wo = create_work_order(customer["id"], unit["id"], work_scope="OVERHAUL")
    api_client.teardown_complete(wo["id"], TECHNICIAN)
    quoted = submit_quote(wo["id"], labor_estimate_cents=labor_estimate_cents,
                          parts_estimate_cents=parts_estimate_cents,
                          scrap_option_ack=False)
    if approve_delay_iso is not None:
        set_clock(approve_delay_iso)
    approve_quote(wo["id"], customer["id"], quoted["version"])
    for spec in (requisition_specs or []):
        spec = dict(spec)
        unit_cost = spec.pop("unit_cost_cents")
        req = create_parts_requisition(wo["id"], **spec)
        issue_received_requisition(req["id"], unit_cost)
    complete_repair(wo["id"], technician_user_id=technician_user_id)
    cell = create_test_cell(name=cell_name)
    book_cell(cell["id"], wo["id"],
              start_time=booking_window[0], end_time=booking_window[1])
    set_clock(test_clock)
    record_test_results(wo["id"], result="PASS", inspector_user_id=inspector_user_id)
    return release_work_order(wo["id"], inspector_user_id=inspector_user_id)


# ---------------------------------------------------------------------------
# Difficulty queue A — dual-variant TAT penalty
# ---------------------------------------------------------------------------

def _setup_dual_variant_pair():
    """Build two identical customers (one ADJUSTED, one CALENDAR), each with
    an identical unit and OVERHAUL work order quoted but not yet approved."""
    c_adj = create_customer(name="AeroAdj", certificate_number="AIR-A",
                            penalty_delay_rule="ADJUSTED")
    c_cal = create_customer(name="AeroCal", certificate_number="AIR-B",
                            penalty_delay_rule="CALENDAR")
    part = create_part()
    u_adj = create_unit(part["id"], serial_number="SN-A1", ownership="CUSTOMER",
                        owner_customer_id=c_adj["id"])
    u_cal = create_unit(part["id"], serial_number="SN-B1", ownership="CUSTOMER",
                        owner_customer_id=c_cal["id"])
    wo_adj = create_work_order(c_adj["id"], u_adj["id"], work_scope="OVERHAUL")
    api_client.teardown_complete(wo_adj["id"], TECHNICIAN)
    q_adj = submit_quote(wo_adj["id"], labor_estimate_cents=2000000,
                         parts_estimate_cents=1000000, scrap_option_ack=False)
    wo_cal = create_work_order(c_cal["id"], u_cal["id"], work_scope="OVERHAUL")
    api_client.teardown_complete(wo_cal["id"], TECHNICIAN)
    q_cal = submit_quote(wo_cal["id"], labor_estimate_cents=2000000,
                         parts_estimate_cents=1000000, scrap_option_ack=False)
    return c_adj, c_cal, part, q_adj, q_cal


def _drive_pair_to_release(c_adj, c_cal, q_adj, q_cal):
    """Approve both quotes at 2026-08-03T12:00:00Z, book each a 4h cell
    window on its own cell, advance to 2026-08-09T02:00:00Z, pass & release."""
    set_clock("2026-08-03T12:00:00Z")
    approve_quote(q_adj["id"], c_adj["id"], q_adj["version"])
    approve_quote(q_cal["id"], c_cal["id"], q_cal["version"])
    complete_repair(q_adj["id"], technician_user_id="tech-1")
    complete_repair(q_cal["id"], technician_user_id="tech-1")
    cell_a = create_test_cell(name="CELL-A")
    cell_b = create_test_cell(name="CELL-B")
    book_cell(cell_a["id"], q_adj["id"],
              start_time="2026-08-09T00:00:00Z", end_time="2026-08-09T04:00:00Z")
    book_cell(cell_b["id"], q_cal["id"],
              start_time="2026-08-09T00:00:00Z", end_time="2026-08-09T04:00:00Z")
    set_clock("2026-08-09T02:00:00Z")
    record_test_results(q_adj["id"], result="PASS", atp_reference="ATP-A1",
                        inspector_user_id="insp-9")
    release_work_order(q_adj["id"], inspector_user_id="insp-9")
    record_test_results(q_cal["id"], result="PASS", atp_reference="ATP-B1",
                        inspector_user_id="insp-9")
    release_work_order(q_cal["id"], inspector_user_id="insp-9")


def test_tat_penalty_adjusted_vs_calendar_variant_diverges(api):
    """PRD §3.6: "Under the `ADJUSTED` variant the penalty basis is the
    elapsed hours minus `accumulated_delay_hours`, so customer decision time
    is excluded; under the `CALENDAR` variant the basis is the raw elapsed
    hours with delay not excluded, yielding a strictly larger penalty for
    identical timestamps whenever any delay accumulated."

    Design: Difficulty/dual_variant_calc/tat_penalty_adjusted_vs_calendar_variant
    """
    c_adj, c_cal, part, q_adj, q_cal = _setup_dual_variant_pair()
    _drive_pair_to_release(c_adj, c_cal, q_adj, q_cal)

    inv_adj = generate_invoice(q_adj["id"])
    inv_cal = generate_invoice(q_cal["id"])

    # received 2026-08-01T00:00:00Z; approve at 2026-08-03T12:00:00Z (delay 60h);
    # release at 2026-08-09T02:00:00Z -> elapsed 194h. Guarantee 100h, rate 5000.
    # ADJUSTED basis 134h -> excess 34h -> penalty 170000.
    # CALENDAR basis 194h -> excess 94h -> penalty 470000 (cap 0.5 * 3400000 = 1700000 not binding).
    assert inv_adj["penalty_variant"] == "ADJUSTED"
    assert inv_adj["penalty_credit_cents"] == 170000
    assert inv_cal["penalty_variant"] == "CALENDAR"
    assert inv_cal["penalty_credit_cents"] == 470000


def test_tat_penalty_adjusted_vs_calendar_total_divergence(api):
    """PRD §3.6: "The invoice `total_cents` for `REPAIR` or `OVERHAUL` scope
    is the sum of labor, parts, and test fees minus the penalty credit,
    floored at zero". Identical timestamps therefore produce a
    variant-driven 300000-cent total divergence.

    Design: Difficulty/dual_variant_calc/tat_penalty_adjusted_vs_calendar_variant
    """
    c_adj, c_cal, part, q_adj, q_cal = _setup_dual_variant_pair()
    _drive_pair_to_release(c_adj, c_cal, q_adj, q_cal)

    inv_adj = generate_invoice(q_adj["id"])
    inv_cal = generate_invoice(q_cal["id"])

    # Subtotal for both: labor 2000000 + parts 0 + test fee 4h*100000 = 400000.
    # ADJUSTED: 2400000 - 170000 = 2230000. CALENDAR: 2400000 - 470000 = 1930000.
    assert inv_adj["total_cents"] == 2230000
    assert inv_cal["total_cents"] == 1930000
    assert inv_adj["total_cents"] - inv_cal["total_cents"] == 300000


# ---------------------------------------------------------------------------
# Difficulty queue A — dual-variant warranty credit
# ---------------------------------------------------------------------------

def _setup_warranty_dual_variant_base():
    """Two units each driven to CLOSED with OVERHAUL work orders: WO1 has
    one 2x250000 requisition (tier-2 markup 15% -> 575000 parts); WO2 has no
    parts. Both use labor 2000000 and one 4h booking."""
    customer = create_customer()
    part = create_part()
    u1 = create_unit(part["id"], serial_number="SN-U1", ownership="CUSTOMER",
                     owner_customer_id=customer["id"])
    # WO1 with parts
    wo1 = create_work_order(customer["id"], u1["id"], work_scope="OVERHAUL")
    api_client.teardown_complete(wo1["id"], TECHNICIAN)
    q1 = submit_quote(wo1["id"], labor_estimate_cents=2000000,
                      parts_estimate_cents=1000000, scrap_option_ack=False)
    approve_quote(wo1["id"], customer["id"], q1["version"])
    req = create_parts_requisition(wo1["id"], part_number="BRG-32-99",
                                    quantity=2, requested_source="OEM")
    issue_received_requisition(req["id"], 250000)
    complete_repair(wo1["id"], technician_user_id="tech-1")
    cell = create_test_cell(name="CELL-A")
    book_cell(cell["id"], wo1["id"],
              start_time="2026-08-02T01:00:00Z", end_time="2026-08-02T05:00:00Z")
    set_clock("2026-08-02T02:00:00Z")
    record_test_results(wo1["id"], result="PASS", atp_reference="ATP-1",
                        inspector_user_id="insp-9")
    release_work_order(wo1["id"], inspector_user_id="insp-9")
    generate_invoice(wo1["id"])
    close_work_order(wo1["id"])

    u2 = create_unit(part["id"], serial_number="SN-U2", ownership="CUSTOMER",
                     owner_customer_id=customer["id"], total_cycles=3900,
                     cycles_since_overhaul=250, manufactured_at="2016-01-15")
    wo2 = create_work_order(customer["id"], u2["id"], work_scope="OVERHAUL")
    api_client.teardown_complete(wo2["id"], TECHNICIAN)
    q2 = submit_quote(wo2["id"], labor_estimate_cents=2000000,
                      parts_estimate_cents=500000, scrap_option_ack=False)
    approve_quote(wo2["id"], customer["id"], q2["version"])
    complete_repair(wo2["id"], technician_user_id="tech-1")
    book_cell(cell["id"], wo2["id"],
              start_time="2026-08-02T05:00:00Z", end_time="2026-08-02T09:00:00Z")
    set_clock("2026-08-02T06:00:00Z")
    record_test_results(wo2["id"], result="PASS", atp_reference="ATP-2",
                        inspector_user_id="insp-9")
    release_work_order(wo2["id"], inspector_user_id="insp-9")
    generate_invoice(wo2["id"])
    close_work_order(wo2["id"])
    return customer, part, wo1, wo2


def test_warranty_credit_full_vs_prorated_variant_variants(api):
    """PRD §3.9: "The `credit_variant` is `FULL` when twice
    `claim_cycles_used` is at most `warranty_cycle_limit` — the customer
    used no more than half the warranted cycles — and `credit_cents` then
    equals the base; identical claim data under the prorated policy would
    pay strictly less. Otherwise the variant is `PRORATED`: the remaining
    cycles are `warranty_cycle_limit` minus `claim_cycles_used`, floored at
    zero, and `credit_cents` is the base multiplied by the remaining cycles
    and divided by `warranty_cycle_limit`, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/warranty_credit_full_vs_prorated_variant
    """
    from test_helpers import create_warranty_claim
    customer, part, wo1, wo2 = _setup_warranty_dual_variant_base()

    # claim1: 200 cycles -> 2*200=400 <= 500 -> FULL; base = 2000000 + 575000 = 2575000
    cl1 = create_warranty_claim(wo1["id"], customer["id"],
                                claim_cycles_used=200, claim_months_used=10,
                                failure_description="Bearing spalling within warranty")
    accepted1 = review_warranty_claim(cl1["id"], "ACCEPT")
    assert accepted1["credit_variant"] == "FULL"
    assert accepted1["credit_cents"] == 2575000

    # claim2: 300 cycles -> 600 > 500 -> PRORATED; remaining = 200; base = 2000000
    # credit = round_half_up(2000000 * 200 / 500) = 800000
    cl2 = create_warranty_claim(wo2["id"], customer["id"],
                                claim_cycles_used=300, claim_months_used=10,
                                failure_description="Seal leak within warranty")
    accepted2 = review_warranty_claim(cl2["id"], "ACCEPT")
    assert accepted2["credit_variant"] == "PRORATED"
    assert accepted2["credit_cents"] == 800000


def test_warranty_credit_full_vs_prorated_variant_diverge(api):
    """PRD §3.9: "identical claim data under the prorated policy would pay
    strictly less" — the two variants select different credits for the same
    acceptance action; FULL credits the entire base while PRORATED scales it.

    Design: Difficulty/dual_variant_calc/warranty_credit_full_vs_prorated_variant
    """
    from test_helpers import create_warranty_claim
    customer, part, wo1, wo2 = _setup_warranty_dual_variant_base()
    cl1 = create_warranty_claim(wo1["id"], customer["id"],
                                claim_cycles_used=200, claim_months_used=10,
                                failure_description="Bearing spalling")
    accepted1 = review_warranty_claim(cl1["id"], "ACCEPT")
    cl2 = create_warranty_claim(wo2["id"], customer["id"],
                                claim_cycles_used=300, claim_months_used=10,
                                failure_description="Seal leak")
    accepted2 = review_warranty_claim(cl2["id"], "ACCEPT")
    assert accepted1["credit_cents"] != accepted2["credit_cents"]
    assert accepted1["credit_cents"] == 2575000
    assert accepted2["credit_cents"] == 800000


# ---------------------------------------------------------------------------
# Difficulty queue A — combinatorial formula
# ---------------------------------------------------------------------------

def test_tat_penalty_five_input_max_min_cap_formula(api):
    """PRD §3.6: "Elapsed hours are the difference between `released_at` and
    `received_at`, expressed in hours at two decimal places. Under the
    `ADJUSTED` variant the penalty basis is the elapsed hours minus
    `accumulated_delay_hours` ... The excess is the amount by which the
    basis exceeds the customer's `contract_tat_hours`, floored at zero; the
    raw penalty is the excess multiplied by `tat_penalty_rate_cents_per_hour`;
    and the cap is `tat_penalty_cap_pct` percent of the subtotal of
    `labor_cents`, `parts_cents`, and `test_fee_cents`, rounded half up to
    whole cents. The resulting `penalty_credit_cents` is the smaller of the
    raw penalty and the cap — the cap applies last, after the raw penalty".

    Design: Difficulty/combinatorial_formula/tat_penalty_five_input_max_min_cap
    """
    # received 2026-08-01T00:00:00Z; approve at 2026-08-03T12:00:00Z (60h delay);
    # release 2026-08-09T02:00:00Z (elapsed 194h); ADJUSTED basis 134h; excess 34h;
    # raw penalty 170000. Subtotal 2000000 + 575000 + 400000 = 2975000;
    # cap 50% = 1487500 — non-binding.
    customer = create_customer(penalty_delay_rule="ADJUSTED")
    part = create_part()
    unit = create_unit(part["id"], ownership="CUSTOMER",
                       owner_customer_id=customer["id"])
    wo = create_work_order(customer["id"], unit["id"], work_scope="OVERHAUL")
    api_client.teardown_complete(wo["id"], TECHNICIAN)
    quoted = submit_quote(wo["id"], labor_estimate_cents=2000000,
                          parts_estimate_cents=1000000, scrap_option_ack=False)
    set_clock("2026-08-03T12:00:00Z")
    approve_quote(wo["id"], customer["id"], quoted["version"])
    req = create_parts_requisition(wo["id"], part_number="BRG-32-99",
                                    quantity=2, requested_source="OEM")
    issue_received_requisition(req["id"], 250000)
    complete_repair(wo["id"], technician_user_id="tech-1")
    cell = create_test_cell()
    book_cell(cell["id"], wo["id"],
              start_time="2026-08-09T00:00:00Z", end_time="2026-08-09T04:00:00Z")
    set_clock("2026-08-09T02:00:00Z")
    record_test_results(wo["id"], result="PASS", atp_reference="ATP-1",
                        inspector_user_id="insp-9")
    release_work_order(wo["id"], inspector_user_id="insp-9")
    invoice = generate_invoice(wo["id"])

    assert invoice["penalty_credit_cents"] == 170000
    assert invoice["parts_cents"] == 575000
    assert invoice["test_fee_cents"] == 400000
    assert invoice["total_cents"] == 2805000

    wo_after = get_work_order(wo["id"])
    assert wo_after["accumulated_delay_hours"] == pytest.approx(60.0, abs=0.01)
    # received 2026-08-01T00:00:00Z + 100h = 2026-08-05T04:00:00Z
    # (instant comparison — PRD does not pin the serialization format of
    # promised_return_at).
    assert parse_instant(wo_after["promised_return_at"]) == parse_instant("2026-08-05T04:00:00Z")


def test_tat_penalty_five_input_cap_binding_branch(api):
    """PRD §3.6: "the cap is `tat_penalty_cap_pct` percent of the subtotal
    of `labor_cents`, `parts_cents`, and `test_fee_cents`, rounded half up
    to whole cents. The resulting `penalty_credit_cents` is the smaller of
    the raw penalty and the cap — the cap applies last, after the raw
    penalty".

    Design: Corner/calculations/tat_penalty_cap_binds_on_huge_delay
    """
    # Quote and approve at receipt (delay 0); release at 2026-09-11T14:00:00Z
    # (elapsed 998h); excess 898h * 5000 = 4490000 raw. Subtotal 2400000;
    # cap 50% = 1200000 — binding.
    customer = create_customer(penalty_delay_rule="ADJUSTED")
    part = create_part()
    unit = create_unit(part["id"], ownership="CUSTOMER",
                       owner_customer_id=customer["id"])
    wo = create_work_order(customer["id"], unit["id"], work_scope="OVERHAUL")
    api_client.teardown_complete(wo["id"], TECHNICIAN)
    quoted = submit_quote(wo["id"], labor_estimate_cents=2000000,
                          parts_estimate_cents=1000000, scrap_option_ack=False)
    approve_quote(wo["id"], customer["id"], quoted["version"])
    complete_repair(wo["id"], technician_user_id="tech-1")
    cell = create_test_cell()
    book_cell(cell["id"], wo["id"],
              start_time="2026-09-11T11:00:00Z", end_time="2026-09-11T15:00:00Z")
    set_clock("2026-09-11T14:00:00Z")
    record_test_results(wo["id"], result="PASS", atp_reference="ATP-1",
                        inspector_user_id="insp-9")
    release_work_order(wo["id"], inspector_user_id="insp-9")
    invoice = generate_invoice(wo["id"])

    # min(4490000, 1200000) = 1200000; total = 2400000 - 1200000 = 1200000.
    assert invoice["penalty_credit_cents"] == 1200000
    assert invoice["total_cents"] == 1200000


def test_invoice_per_line_rounding_then_sum(api):
    """PRD §2.6: "Aggregation order is pinned for the two per-line money
    sources on a work-order invoice: each parts requisition's
    `extended_price_cents` is rounded half up to whole cents at receive
    time, and each test-cell booking's `fee_cents` is rounded half up to
    whole cents at booking creation; invoice lines then sum the
    already-rounded per-line values. Summing first and rounding once at the
    end is forbidden, because the two orders can diverge by cents."

    Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
    """
    # Two qty-1 requisitions at unit_cost 33333 with 25% markup.
    # Per-line: round_half_up(33333 * 1.25) = round_half_up(41666.25) = 41666
    # Sum: 41666 + 41666 = 83332 (NOT 83333 from sum-then-round).
    customer = create_customer()
    part = create_part()
    unit = create_unit(part["id"], ownership="CUSTOMER",
                       owner_customer_id=customer["id"])
    wo = create_work_order(customer["id"], unit["id"], work_scope="OVERHAUL")
    api_client.teardown_complete(wo["id"], TECHNICIAN)
    quoted = submit_quote(wo["id"], labor_estimate_cents=2000000,
                          parts_estimate_cents=100000, scrap_option_ack=False)
    set_clock("2026-08-02T00:00:00Z")
    approve_quote(wo["id"], customer["id"], quoted["version"])
    for pn in ("SEAL-1", "SEAL-2"):
        req = create_parts_requisition(wo["id"], part_number=pn,
                                        quantity=1, requested_source="OEM")
        issue_received_requisition(req["id"], 33333)
    complete_repair(wo["id"], technician_user_id="tech-1")
    cell = create_test_cell()
    book_cell(cell["id"], wo["id"],
              start_time="2026-08-02T01:00:00Z", end_time="2026-08-02T05:00:00Z")
    set_clock("2026-08-02T02:00:00Z")
    record_test_results(wo["id"], result="PASS", atp_reference="ATP-1",
                        inspector_user_id="insp-9")
    release_work_order(wo["id"], inspector_user_id="insp-9")
    invoice = generate_invoice(wo["id"])

    assert invoice["parts_cents"] == 83332
    # Adjusted elapsed 2h (delay 0; received 2026-08-01, approved 2026-08-02
    # — 24h delay actually! Let's recompute.)
    # received_at = 2026-08-01T00:00:00Z (clock default at induction).
    # After quote at same clock; we set clock to 2026-08-02T00:00:00Z before
    # approve, so delay = 24h. Released at 2026-08-02T02:00:00Z, elapsed = 50h.
    # Adjusted = 50 - 24 = 26h <= 100h guarantee -> penalty 0.
    assert invoice["penalty_credit_cents"] == 0
    # total = 2000000 (labor) + 83332 (parts) + 400000 (test fee) - 0 = 2483332
    assert invoice["total_cents"] == 2483332


def test_invoice_per_line_rounding_then_sum_tier_markup(api):
    """PRD §3.4: "The markup tier is keyed on `unit_cost_cents`: a unit cost
    at or below $1,000.00 marks up 25 percent; a unit cost above $1,000.00
    and at or below $10,000.00 marks up 15 percent; a unit cost above
    $10,000.00 marks up 10 percent." PRD §3.4: "At that moment the line's
    `extended_price_cents` is computed: `quantity` multiplied by
    `unit_cost_cents` multiplied by the applicable markup factor, rounded
    half up to whole cents as a per-line rounding."

    Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_then_sum
    """
    customer = create_customer()
    part = create_part()
    unit = create_unit(part["id"], ownership="CUSTOMER",
                       owner_customer_id=customer["id"])
    wo = create_work_order(customer["id"], unit["id"], work_scope="OVERHAUL")
    api_client.teardown_complete(wo["id"], TECHNICIAN)
    quoted = submit_quote(wo["id"], scrap_option_ack=False)
    approve_quote(wo["id"], customer["id"], quoted["version"])

    # Tier 1: unit_cost 100000 ($1000) -> 25% markup -> qty 1 -> 125000
    req1 = create_parts_requisition(wo["id"], part_number="T1", quantity=1,
                                     requested_source="OEM")
    issue_received_requisition(req1["id"], 100000)
    # Tier 2: unit_cost 250000 -> 15% markup -> qty 2 -> 575000
    req2 = create_parts_requisition(wo["id"], part_number="T2", quantity=2,
                                     requested_source="OEM")
    issue_received_requisition(req2["id"], 250000)
    # Tier 3: unit_cost 2000000 -> 10% markup -> qty 1 -> 2200000
    req3 = create_parts_requisition(wo["id"], part_number="T3", quantity=1,
                                     requested_source="OEM")
    issue_received_requisition(req3["id"], 2000000)

    complete_repair(wo["id"], technician_user_id="tech-1")
    cell = create_test_cell()
    book_cell(cell["id"], wo["id"],
              start_time="2026-08-02T01:00:00Z", end_time="2026-08-02T05:00:00Z")
    set_clock("2026-08-02T02:00:00Z")
    record_test_results(wo["id"], result="PASS", inspector_user_id="insp-9")
    release_work_order(wo["id"], inspector_user_id="insp-9")
    invoice = generate_invoice(wo["id"])

    # parts = 125000 + 575000 + 2200000 = 2900000
    assert invoice["parts_cents"] == 2900000


# ---------------------------------------------------------------------------
# Difficulty queue A — exchange settlement pinned evaluation order
# ---------------------------------------------------------------------------

def test_exchange_settlement_pinned_evaluation_order_ber_late(api):
    """PRD §3.7: "Second, `core_charge_cents` is set: zero for a non-BER
    core; for a BER core, 80 percent of the part's `replacement_value_cents`,
    rounded half up to whole cents; for a missing core, the full
    `replacement_value_cents`. Third, the late days are the whole days
    between `core_due_date` and the return date, never below zero ...
    Fourth, `late_fee_cents` is the smaller of the late days multiplied by
    $500.00 per day and the remaining headroom of `replacement_value_cents`
    minus `core_charge_cents`, floored at zero ... Fifth,
    `settlement_total_cents` is the flat $250.00 `admin_fee_cents` plus
    `core_charge_cents` plus `late_fee_cents`."

    Design: Difficulty/combinatorial_formula/exchange_settlement_pinned_evaluation_order
    """
    customer, part, pool_unit, core_unit, agreement = setup_exchange_fulfilled()
    # Agreement fulfilled at clock default 2026-08-01 -> core_due_date 2026-08-16.
    # Advance to 2026-08-19 -> 3 late days, inside 5-day grace (no DEFAULTED sweep).
    set_clock("2026-08-19T00:00:00Z")

    # BER core: estimate 7000000 >= 6500000 (65% of 10000000).
    res = api.core_return_exchange(
        agreement["id"],
        {"core_unit_id": core_unit["id"], "core_teardown_estimate_cents": 7000000},
        TECHNICIAN)
    settled = validate_success(res, 200)
    assert settled["status"] == "CLOSED"
    assert settled["core_ber_flag"] is True
    # core_charge = round_half_up(0.80 * 10000000) = 8000000
    assert settled["core_charge_cents"] == 8000000
    # late_fee = min(3 * 50000, max(0, 10000000 - 8000000)) = min(150000, 2000000) = 150000
    assert settled["late_fee_cents"] == 150000
    # settlement = 25000 + 8000000 + 150000 = 8175000
    assert settled["settlement_total_cents"] == 8175000


def test_exchange_settlement_pinned_evaluation_order_unit_mutation(api):
    """PRD §3.7: "a BER core moves to custody `IN_SHOP` and its condition
    stays `UNSERVICEABLE`" and "its ownership flips from `CUSTOMER` to
    `SHOP`".

    Design: Difficulty/combinatorial_formula/exchange_settlement_pinned_evaluation_order
    """
    customer, part, pool_unit, core_unit, agreement = setup_exchange_fulfilled()
    set_clock("2026-08-19T00:00:00Z")
    api.core_return_exchange(
        agreement["id"],
        {"core_unit_id": core_unit["id"], "core_teardown_estimate_cents": 7000000},
        TECHNICIAN)

    core_after = get_unit(core_unit["id"])
    assert core_after["ownership"] == "SHOP"
    assert core_after["custody_status"] == "IN_SHOP"
    assert core_after["condition_status"] == "UNSERVICEABLE"
