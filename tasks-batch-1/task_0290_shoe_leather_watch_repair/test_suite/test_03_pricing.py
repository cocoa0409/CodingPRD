"""Pricing engine: estimate totals (provisional vs final), parts markup, the
tiered rush surcharge with its half-open boundary, the ready-by SLA, the warranty
window, and the sla_breached flag.
"""
import pytest

from test_helpers import (
    validate_success,
    create_service_type_payload, create_parts_order_payload, present_estimate_payload,
    TEST_USERS, make_technician_headers,
    set_clock, create_customer, create_service_type, create_technician,
    create_ticket, add_item, add_service_line, add_part, create_draft_estimate,
    present_estimate, approve_estimate, get_ticket_version, complete_line,
    setup_ticket_with_line, setup_in_repair,
    capture_full_payment,
    api_client,
)

FRONT_DESK = TEST_USERS["front_desk_headers"]
SHOP_MANAGER = TEST_USERS["shop_manager_headers"]


# ── Difficulty: PROVISIONAL vs FINAL diverge (≥2 tests) ──────────────────
def _setup_dual_variant_through_in_repair():
    """Two QUOTED lines (4000 SHOE, 2500 LEATHER) + one part (1000x2 RETAIL=2700).
    Estimate presented, approved, part received, start-repair. Returns context."""
    set_clock("2026-03-01T09:00:00Z")
    customer = create_customer()
    st_shoe = create_service_type(base_price_cents=4000, item_category="SHOE",
                                  standard_turnaround_days=3, warranty_days=90)
    st_leather = create_service_type(base_price_cents=2500, item_category="LEATHER",
                                     standard_turnaround_days=2, warranty_days=30)
    tech = create_technician(skills=["SHOE", "LEATHER"])
    ticket = create_ticket(customer["id"], priority="STANDARD", assigned_technician_id=tech["id"])
    item_shoe = add_item(ticket["id"], item_category="SHOE")
    item_leather = add_item(ticket["id"], item_category="LEATHER")
    line_a = add_service_line(ticket["id"], item_shoe["id"], st_shoe["id"], tech["id"])
    line_b = add_service_line(ticket["id"], item_leather["id"], st_leather["id"], tech["id"])
    part = add_part(ticket["id"], line_a["id"], 1000, 1, tech["id"], quantity=2)
    est = create_draft_estimate(ticket["id"], tech["id"])
    est = present_estimate(est["id"], ticket["id"], tech["id"])
    approve_estimate(est["id"], customer["id"])
    validate_success(api_client.order_part(part["id"], make_technician_headers(tech["id"])), 200)
    validate_success(api_client.receive_part(part["id"], make_technician_headers(tech["id"])), 200)
    validate_success(api_client.start_repair(ticket["id"], make_technician_headers(tech["id"])), 200)
    return customer, tech, ticket, line_a, line_b, part, est


def test_provisional_total_sums_quoted_lines_and_parts(api):
    """PRD §3.5: "The **provisional** variant runs when an estimate is presented (the ticket entering `AWAITING_APPROVAL`). Each line is priced at its `quoted_price_cents`; the lines in scope are those with status `QUOTED`; the parts in scope are those with status `REQUESTED`, `ORDERED`, or `RECEIVED`."

    Design: Difficulty/dual_variant_calc/estimate_total_provisional_vs_final_diverge
    """
    customer, tech, ticket, line_a, line_b, part, est = _setup_dual_variant_through_in_repair()
    est_now = validate_success(api.get_estimate(est["id"], FRONT_DESK), 200)
    # labor 4000+2500=6500, parts round(1000*2*1.35)=2700 -> 9200.
    assert est_now["estimate_total_cents"] == 9200


def test_final_charge_diverges_from_provisional_via_adjusted_price(api):
    """PRD §3.5: "The **final** variant runs when the ticket is marked ready (entering `READY_FOR_PICKUP`). Each line is priced at its `adjusted_price_cents` when that override is present and at its `quoted_price_cents` otherwise; the lines in scope are those with status `COMPLETED`; the parts in scope are those with status `RECEIVED` only. The result is written to the ticket's `final_charge_cents`."
    PRD §3.6: "A supplied `adjusted_price_cents` overrides `quoted_price_cents` for that line in the final totals."

    Design: Difficulty/dual_variant_calc/estimate_total_provisional_vs_final_diverge
    """
    customer, tech, ticket, line_a, line_b, part, est = _setup_dual_variant_through_in_repair()
    # Provisional priced line A at quoted 4000; the technician overrides it to 4500
    # during repair, so the FINAL charge must diverge from the provisional total.
    complete_line(line_a["id"], tech["id"], adjusted_price_cents=4500)
    complete_line(line_b["id"], tech["id"])
    ready = validate_success(api.mark_ready(ticket["id"], make_technician_headers(tech["id"])), 200)
    # FINAL = adjusted 4500 (line A) + quoted 2500 (line B) + 2700 (part RECEIVED) = 9700.
    assert ready["final_charge_cents"] == 9700
    est_now = validate_success(api.get_estimate(est["id"], FRONT_DESK), 200)
    # PROVISIONAL was 9200 (quoted 4000 + 2500 + parts 2700); the two legitimately diverge.
    assert ready["final_charge_cents"] != est_now["estimate_total_cents"]


# ── Difficulty: rush tiered nonlinear surcharge (≥2 tests) ───────────────
def _setup_rush_two_line_part():
    set_clock("2026-03-01T09:00:00Z")
    customer = create_customer()
    st_shoe = create_service_type(base_price_cents=4000, item_category="SHOE",
                                  standard_turnaround_days=3, rush_eligible=True, warranty_days=90)
    st_leather = create_service_type(base_price_cents=2500, item_category="LEATHER",
                                     standard_turnaround_days=2, rush_eligible=True, warranty_days=30)
    tech = create_technician(skills=["SHOE", "LEATHER"])
    ticket = create_ticket(customer["id"], priority="RUSH", assigned_technician_id=tech["id"])
    item_shoe = add_item(ticket["id"], item_category="SHOE")
    item_leather = add_item(ticket["id"], item_category="LEATHER")
    line_a = add_service_line(ticket["id"], item_shoe["id"], st_shoe["id"], tech["id"])
    line_b = add_service_line(ticket["id"], item_leather["id"], st_leather["id"], tech["id"])
    add_part(ticket["id"], line_a["id"], 1000, 1, tech["id"], quantity=2)
    est = create_draft_estimate(ticket["id"], tech["id"])
    return customer, tech, ticket, est


def test_rush_surcharge_tiered_on_pre_rush(api):
    """PRD §3.5: "The portion of the pre-rush total from 0 up to but not including 5000 cents is charged at a rate of 0.30; the portion from 5000 up to but not including 20000 cents is charged at 0.20; and the portion at or above 20000 cents is charged at 0.10."
    PRD §3.5: "The three tier portions are each multiplied by their rate, the three results are summed, and that sum is rounded once, half-up, to a whole cent (sum first, then round)."

    Design: Difficulty/combinatorial_formula/estimate_total_rush_tiered_nonlinear
    """
    customer, tech, ticket, est = _setup_rush_two_line_part()
    presented = present_estimate(est["id"], ticket["id"], tech["id"])
    # pre_rush = 6500 labor + 2700 parts = 9200; surcharge = 5000*0.30 + 4200*0.20 = 2340.
    assert presented["rush_surcharge_cents"] == 2340
    assert presented["parts_subtotal_cents"] == 2700


def test_rush_estimate_total_adds_surcharge(api):
    """PRD §3.5: "Step five, the estimate total is the pre-rush total plus the rush surcharge."

    Design: Difficulty/combinatorial_formula/estimate_total_rush_tiered_nonlinear
    """
    customer, tech, ticket, est = _setup_rush_two_line_part()
    presented = present_estimate(est["id"], ticket["id"], tech["id"])
    # 9200 pre_rush + 2340 surcharge = 11540.
    assert presented["estimate_total_cents"] == 11540


# ── Difficulty: parts markup rounding order pinned (≥2 tests) ─────────────
def _setup_single_line_ticket():
    set_clock("2026-03-01T09:00:00Z")
    customer = create_customer()
    st = create_service_type(base_price_cents=4000, item_category="SHOE",
                             standard_turnaround_days=3, warranty_days=90)
    tech = create_technician(skills=["SHOE"])
    ticket = create_ticket(customer["id"], assigned_technician_id=tech["id"])
    item = add_item(ticket["id"], item_category="SHOE")
    line = add_service_line(ticket["id"], item["id"], st["id"], tech["id"])
    return customer, tech, ticket, line


def test_parts_markup_rounds_full_product_once(api):
    """PRD §3.5: "When a parts order is created, its `marked_up_cost_cents` is computed by multiplying `supplier_cost_cents` by `quantity` and then by a markup multiplier, taking the full product and rounding it once, half-up, to a whole cent."
    PRD §3.5: "The single rounding happens after the full product is formed; rounding per unit and then multiplying by quantity is incorrect."

    Design: Difficulty/combinatorial_formula/parts_markup_rounding_order_pinned
    """
    customer, tech, ticket, line = _setup_single_line_ticket()
    res = api.create_parts_order(
        create_parts_order_payload(ticket["id"], line["id"], 333, 2, quantity=3),
        make_technician_headers(tech["id"]),
    )
    part = validate_success(res, 201)
    # round_half_up(333*3*1.35) = round(1348.65) = 1349 (NOT round(333*1.35)*3 = 1350).
    assert part["marked_up_cost_cents"] == 1349


def test_parts_markup_retail_multiplier_applied(api):
    """PRD §3.5: "The multiplier is the retail markup of 1.35 for a part on a normal (non-redo) ticket, whose marked-up cost flows into the customer-billed estimate and final charge."

    Design: Difficulty/combinatorial_formula/parts_markup_rounding_order_pinned
    """
    customer, tech, ticket, line = _setup_single_line_ticket()
    res = api.create_parts_order(
        create_parts_order_payload(ticket["id"], line["id"], 1000, 0, quantity=2),
        make_technician_headers(tech["id"]),
    )
    part = validate_success(res, 201)
    # round_half_up(1000*2*1.35) = 2700.
    assert part["marked_up_cost_cents"] == 2700


# ── Difficulty: rush tier-1 cap boundary (≥2 tests) ──────────────────────
def _setup_rush_single_line(base_price):
    set_clock("2026-03-01T09:00:00Z")
    customer = create_customer()
    st = create_service_type(base_price_cents=base_price, item_category="SHOE",
                             standard_turnaround_days=4, rush_eligible=True, warranty_days=90)
    tech = create_technician(skills=["SHOE"])
    ticket = create_ticket(customer["id"], priority="RUSH", assigned_technician_id=tech["id"])
    item = add_item(ticket["id"], item_category="SHOE")
    add_service_line(ticket["id"], item["id"], st["id"], tech["id"])
    est = create_draft_estimate(ticket["id"], tech["id"])
    return customer, tech, ticket, est


def test_rush_surcharge_at_tier1_cap_boundary(api):
    """PRD §3.5: "Because the boundaries are half-open, a pre-rush total of exactly 5000 cents places the full 5000 in the first tier and nothing in the second."
    PRD §3.5: "As a worked boundary, a pre-rush of exactly 5000 cents yields a raw surcharge of 1500 cents, which equals the floor and is applied as 1500."

    Design: Difficulty/boundary_precision_check/rush_surcharge_tier1_cap_boundary
    """
    customer, tech, ticket, est = _setup_rush_single_line(5000)
    presented = present_estimate(est["id"], ticket["id"], tech["id"])
    assert presented["rush_surcharge_cents"] == 1500


def test_rush_estimate_total_at_tier1_cap_boundary(api):
    """PRD §3.5: "Step five, the estimate total is the pre-rush total plus the rush surcharge."

    Design: Difficulty/boundary_precision_check/rush_surcharge_tier1_cap_boundary
    """
    customer, tech, ticket, est = _setup_rush_single_line(5000)
    presented = present_estimate(est["id"], ticket["id"], tech["id"])
    # pre_rush 5000 + surcharge 1500 = 6500.
    assert presented["estimate_total_cents"] == 6500


# ── Corner: ready-by SLA, standard ───────────────────────────────────────
def test_ready_by_sla_standard_base_plus_parts(api):
    """PRD §3.5: "First, a base number of business days is the maximum, over the ticket's non-`VOIDED` service lines, of each line's service type `standard_turnaround_days`. Second, a parts contribution is the maximum, over the ticket's non-`CANCELLED` parts orders, of their `lead_time_days`, taken as 0 when there are no parts. The SLA day count is the base plus the parts contribution."
    PRD §3.5: "The promised `ready_by` is then `drop_off_at` advanced by that many whole calendar days in UTC."

    Design: Corner/calculations/ready_by_sla_standard_sum_of_base_and_parts
    """
    set_clock("2026-03-01T09:00:00Z")
    customer = create_customer()
    st = create_service_type(base_price_cents=4000, item_category="SHOE",
                             standard_turnaround_days=3, warranty_days=90)
    tech = create_technician(skills=["SHOE"])
    ticket = create_ticket(customer["id"], priority="STANDARD", assigned_technician_id=tech["id"])
    item = add_item(ticket["id"], item_category="SHOE")
    line = add_service_line(ticket["id"], item["id"], st["id"], tech["id"])
    part = add_part(ticket["id"], line["id"], 500, 2, tech["id"])
    est = create_draft_estimate(ticket["id"], tech["id"])
    est = present_estimate(est["id"], ticket["id"], tech["id"])
    validate_success(api.order_part(part["id"], make_technician_headers(tech["id"])), 200)
    approved = approve_estimate(est["id"], customer["id"])
    ticket_after = validate_success(api.get_repair_ticket(ticket["id"], FRONT_DESK), 200)
    # 3 base + 2 parts = 5 days; 2026-03-01 + 5 = 2026-03-06.
    assert ticket_after["ready_by"].startswith("2026-03-06T09:00:00")
    assert ticket_after["repair_status"] == "AWAITING_PARTS"


# ── Corner: ready-by SLA, rush ceil + floor ──────────────────────────────
def test_ready_by_sla_rush_ceil_half(api):
    """PRD §3.5: "If the ticket's `priority` is `RUSH`, the SLA day count is replaced by the larger of a rush minimum of 1 day and the SLA day count multiplied by 0.5 and rounded up to the next whole day."
    PRD §3.5: "As a worked boundary, a 5-business-day job at rush priority becomes the ceiling of 2.5, which is 3 days, floored at the 1-day rush minimum."

    Design: Corner/calculations/rush_sla_ceil_half_and_floor
    """
    set_clock("2026-03-01T09:00:00Z")
    customer = create_customer()
    st = create_service_type(base_price_cents=4000, item_category="SHOE",
                             standard_turnaround_days=3, rush_eligible=True, warranty_days=90)
    tech = create_technician(skills=["SHOE"])
    ticket = create_ticket(customer["id"], priority="RUSH", assigned_technician_id=tech["id"])
    item = add_item(ticket["id"], item_category="SHOE")
    line = add_service_line(ticket["id"], item["id"], st["id"], tech["id"])
    part = add_part(ticket["id"], line["id"], 500, 2, tech["id"])
    est = create_draft_estimate(ticket["id"], tech["id"])
    est = present_estimate(est["id"], ticket["id"], tech["id"])
    validate_success(api.order_part(part["id"], make_technician_headers(tech["id"])), 200)
    approve_estimate(est["id"], customer["id"])
    ticket_after = validate_success(api.get_repair_ticket(ticket["id"], FRONT_DESK), 200)
    # base 3 + parts 2 = 5; ceil(5*0.5)=3; 2026-03-01 + 3 = 2026-03-04.
    assert ticket_after["ready_by"].startswith("2026-03-04T09:00:00")


# ── Corner: warranty window = max over completed lines ───────────────────
def test_warranty_window_max_over_completed_lines(api):
    """PRD §3.6: "Pickup stamps `picked_up_at` from the clock and computes the ticket's `warranty_expires_at` as `picked_up_at` advanced by a coverage window equal to the maximum, over the ticket's `COMPLETED` service lines, of their service type `warranty_days`".

    Design: Corner/calculations/warranty_window_max_over_completed_lines
    """
    set_clock("2026-03-01T09:00:00Z")
    customer = create_customer()
    st_shoe = create_service_type(base_price_cents=4000, item_category="SHOE",
                                  standard_turnaround_days=1, warranty_days=90)
    st_leather = create_service_type(base_price_cents=2500, item_category="LEATHER",
                                     standard_turnaround_days=1, warranty_days=30)
    tech = create_technician(skills=["SHOE", "LEATHER"])
    ticket = create_ticket(customer["id"], assigned_technician_id=tech["id"])
    item_shoe = add_item(ticket["id"], item_category="SHOE")
    item_leather = add_item(ticket["id"], item_category="LEATHER")
    line_a = add_service_line(ticket["id"], item_shoe["id"], st_shoe["id"], tech["id"])
    line_b = add_service_line(ticket["id"], item_leather["id"], st_leather["id"], tech["id"])
    est = create_draft_estimate(ticket["id"], tech["id"])
    est = present_estimate(est["id"], ticket["id"], tech["id"])
    approve_estimate(est["id"], customer["id"])
    validate_success(api.start_repair(ticket["id"], make_technician_headers(tech["id"])), 200)
    complete_line(line_a["id"], tech["id"])
    complete_line(line_b["id"], tech["id"])
    ready = validate_success(api.mark_ready(ticket["id"], make_technician_headers(tech["id"])), 200)
    capture_full_payment(ticket["id"], ready["final_charge_cents"])
    picked = validate_success(api.pickup(ticket["id"], FRONT_DESK), 200)
    # max(30, 90) = 90 days; 2026-03-01 + 90 = 2026-05-30.
    assert picked["warranty_expires_at"].startswith("2026-05-30T09:00:00")


# ── Corner: sla_breached flag on late mark-ready ─────────────────────────
def test_sla_breached_true_on_late_mark_ready(api):
    """PRD §3.6: "Mark-ready stamps `ready_at` from the server clock, computes `final_charge_cents` via the final variant of the totals engine, and sets `sla_breached` to true exactly when `ready_at` is later than the promised `ready_by` and false otherwise."

    Design: Corner/calculations/sla_breached_flag_on_late_mark_ready
    """
    set_clock("2026-03-01T09:00:00Z")
    customer = create_customer()
    st = create_service_type(base_price_cents=4000, item_category="SHOE",
                             standard_turnaround_days=3, warranty_days=90)
    tech = create_technician(skills=["SHOE"])
    ticket = create_ticket(customer["id"], assigned_technician_id=tech["id"])
    item = add_item(ticket["id"], item_category="SHOE")
    line = add_service_line(ticket["id"], item["id"], st["id"], tech["id"])
    est = create_draft_estimate(ticket["id"], tech["id"])
    est = present_estimate(est["id"], ticket["id"], tech["id"])
    approve_estimate(est["id"], customer["id"])  # ready_by = 2026-03-04 (no parts, std 3)
    validate_success(api.start_repair(ticket["id"], make_technician_headers(tech["id"])), 200)
    complete_line(line["id"], tech["id"])
    set_clock("2026-03-06T09:00:00Z")  # past ready_by
    ready = validate_success(api.mark_ready(ticket["id"], make_technician_headers(tech["id"])), 200)
    assert ready["sla_breached"] is True
    assert ready["final_charge_cents"] == 4000
