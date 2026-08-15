"""Outside-vendor loop: lead-time gating, boundary inclusivity, RUSH halving."""
from datetime import timedelta

from test_helpers import (
    MGR,
    PLAN,
    ApiErrorId,
    accept_quote,
    complete_step,
    create_customer,
    create_full_sheet,
    create_grade,
    create_machine,
    create_submitted_quote,
    create_vendor,
    get_order,
    get_order_steps,
    get_step_by_station,
    parse_instant,
    release_order,
    set_clock,
    validate_error,
    validate_success,
)

CRS_GRADE = {
    "alloy_family": "CARBON_STEEL",
    "density_g_per_cm3": 7.85,
    "hardness_factor": 1.0,
    "base_cut_rate_cents_per_sec": 2.0,
    "material_cost_cents_per_cm2": 0.045,
    "scrap_rate_cents_per_cm2": 0.015,
}
PLATING_LINE = {"bbox_width_mm": 100, "bbox_height_mm": 100, "hole_count": 0,
                "corner_fillet_count": 0, "bend_count": 0, "weld_inches": 0,
                "finish": "PLATING"}
ANODIZING_LINE = dict(PLATING_LINE, finish="ANODIZING")
ACCEPT_INSTANT = "2026-08-01T00:00:00Z"


def _awaiting_outside_order(process="PLATING", lead_time_days=7,
                            expedite_tier="STANDARD", vendor_cost=350,
                            line=None):
    """Order released, laser completed, waiting on the outside vendor."""
    grade = create_grade(**CRS_GRADE)
    vendor = create_vendor(process, lead_time_days=lead_time_days,
                           base_cost_cents_per_part=vendor_cost)
    customer = create_customer()
    create_full_sheet(grade["id"])
    create_machine("LASER")
    submitted = create_submitted_quote(
        customer["id"], grade["id"],
        line_overrides=line or (PLATING_LINE if process == "PLATING"
                                else ANODIZING_LINE),
        expedite_tier=expedite_tier,
    )
    order = accept_quote(submitted["id"], customer["id"])
    release_order(order["id"])
    steps = get_order_steps(order["id"])
    complete_step(get_step_by_station(steps, "LASER")["id"])
    order = get_order(order["id"])
    assert order["status"] == "AWAITING_OUTSIDE", (
        f"Setup failed: expected AWAITING_OUTSIDE, got {order['status']}"
    )
    return {"grade": grade, "vendor": vendor, "customer": customer,
            "order": order}


# --- lead-time gate (Difficulty: outside_vendor_step_gates_receive_and_order_advance)

def test_receive_outside_rejected_before_lead_time(api):
    """PRD §3.7: "The order must be in AWAITING_OUTSIDE — otherwise
    `ERR_ORDER_NOT_AWAITING_OUTSIDE` — and the logical clock must be at or
    past the outside step's `due_date`; an early receive is rejected with
    `ERR_VENDOR_LEAD_TIME_NOT_ELAPSED`."

    Design: Difficulty/cross_entity_state_dependency/outside_vendor_step_gates_receive_and_order_advance
    """
    world = _awaiting_outside_order(lead_time_days=7)
    order = world["order"]

    set_clock("2026-08-05T00:00:00Z")  # day 4 of a 7-day lead time
    resp = api.receive_outside(order["id"], PLAN)
    validate_error(resp, ApiErrorId.ERR_VENDOR_LEAD_TIME_NOT_ELAPSED, 409)
    assert get_order(order["id"])["status"] == "AWAITING_OUTSIDE"


def test_receive_outside_succeeds_after_lead_time(api):
    """PRD §3.7: "A successful receive moves the outside step to COMPLETED,
    starts the next in-house step if one remains (the POWDER step of a
    plated-and-powdered order, for instance) or moves the order directly to
    INSPECTION when none does, transitions the order from AWAITING_OUTSIDE to
    FINISHING, and appends an ORDER_RECEIVED_OUTSIDE audit event."

    Design: Difficulty/cross_entity_state_dependency/outside_vendor_step_gates_receive_and_order_advance
    """
    world = _awaiting_outside_order(lead_time_days=7)
    order = world["order"]

    set_clock("2026-08-09T00:00:00Z")  # past the 7-day due instant
    validate_success(api.receive_outside(order["id"], PLAN))

    steps = get_order_steps(order["id"])
    assert get_step_by_station(steps, "OUTSIDE_VENDOR")["status"] == "COMPLETED"
    assert get_order(order["id"])["status"] == "INSPECTION", (
        "with no further in-house steps the order moves directly to INSPECTION"
    )


# --- half-open window (Difficulty: vendor_lead_time_window_exclusive_vs_inclusive)

def test_receive_outside_one_second_before_due_rejected(api):
    """PRD §3.7: "... the logical clock must be at or past the outside step's
    `due_date`; an early receive is rejected with
    `ERR_VENDOR_LEAD_TIME_NOT_ELAPSED`."

    Design: Difficulty/resource_temporal_overlap/vendor_lead_time_window_exclusive_vs_inclusive
    """
    world = _awaiting_outside_order(process="ANODIZING", lead_time_days=7,
                                    vendor_cost=200)
    order = world["order"]

    set_clock("2026-08-07T23:59:59Z")  # one second before the due instant
    resp = api.receive_outside(order["id"], PLAN)
    validate_error(resp, ApiErrorId.ERR_VENDOR_LEAD_TIME_NOT_ELAPSED, 409)


def test_receive_outside_at_exact_due_succeeds(api):
    """PRD §3.7: "... the logical clock must be at or past the outside step's
    `due_date`; an early receive is rejected with
    `ERR_VENDOR_LEAD_TIME_NOT_ELAPSED`." PRD §3.7: "the outside step goes to
    IN_PROGRESS, its `due_date` is set to the send time — the logical clock at
    that moment — plus the vendor's `lead_time_days` ..."

    Design: Difficulty/resource_temporal_overlap/vendor_lead_time_window_exclusive_vs_inclusive
    """
    world = _awaiting_outside_order(process="ANODIZING", lead_time_days=7,
                                    vendor_cost=200)
    order = world["order"]

    # The outside step's due is the send instant (2026-08-01) + 7 days.
    outside = get_step_by_station(get_order_steps(order["id"]), "OUTSIDE_VENDOR")
    assert parse_instant(outside["due_date"]) == (
        parse_instant(ACCEPT_INSTANT) + timedelta(days=7)
    )

    set_clock("2026-08-08T00:00:00Z")  # exactly at the due instant
    validate_success(api.receive_outside(order["id"], PLAN))
    assert get_order(order["id"])["status"] == "INSPECTION"


# --- RUSH tier flips price and schedule (Corner: expedite_tier_changes_rush_sla_chain)

def test_expedite_tier_changes_price_and_sla_chain(api):
    """PRD §3.3: "Step nine applies the expedite multiplier for the quote's
    `expedite_tier` — 1.00 for STANDARD, 1.25 for EXPEDITE, 1.50 for RUSH — to
    the discounted net, never to the pre-discount base, and rounds half-up to
    produce the per-part `line_total_cents`." PRD §3.7: "its `due_date` is set
    to the send time — the logical clock at that moment — plus the vendor's
    `lead_time_days`, halved and rounded up to a whole day when the order's
    expedite tier is RUSH ..."

    Design: Corner/cross_cutting_layers/expedite_tier_changes_rush_sla_chain
    """
    grade = create_grade(**CRS_GRADE)
    create_vendor("PLATING", lead_time_days=7, base_cost_cents_per_part=350)
    create_machine("LASER")
    customer = create_customer()
    create_full_sheet(grade["id"])
    create_full_sheet(grade["id"])

    q_std = create_submitted_quote(customer["id"], grade["id"],
                                   line_overrides=PLATING_LINE,
                                   expedite_tier="STANDARD")
    q_rush = create_submitted_quote(customer["id"], grade["id"],
                                    line_overrides=PLATING_LINE,
                                    expedite_tier="RUSH")

    # 100x100 PLATING qty 1: cut 28s*2.0 = 56; finish rhu(100*0.060)+350 = 356;
    # material rhu(max(100,300)*0.045) = 14; setup 900 -> base 1326.
    std_quote = validate_success(api.get_quote(q_std["id"], MGR))
    rush_quote = validate_success(api.get_quote(q_rush["id"], MGR))
    assert std_quote["quoted_total_cents"] == 1326
    assert rush_quote["quoted_total_cents"] == 1989  # round_half_up(1326*1.50)

    order_std = accept_quote(q_std["id"], customer["id"])
    order_rush = accept_quote(q_rush["id"], customer["id"])

    # SLA chain at LASER: STANDARD +5d, RUSH +1d (PRD §3.6).
    laser_std = get_step_by_station(get_order_steps(order_std["id"]), "LASER")
    laser_rush = get_step_by_station(get_order_steps(order_rush["id"]), "LASER")
    assert parse_instant(laser_std["due_date"]) == (
        parse_instant(ACCEPT_INSTANT) + timedelta(days=5))
    assert parse_instant(laser_rush["due_date"]) == (
        parse_instant(ACCEPT_INSTANT) + timedelta(days=1))

    # Send both out: outside due = send + 7d STANDARD, + ceil(7/2)=4d RUSH.
    for order in (order_std, order_rush):
        release_order(order["id"])
        complete_step(get_step_by_station(get_order_steps(order["id"]),
                                          "LASER")["id"])
    out_std = get_step_by_station(get_order_steps(order_std["id"]),
                                  "OUTSIDE_VENDOR")
    out_rush = get_step_by_station(get_order_steps(order_rush["id"]),
                                   "OUTSIDE_VENDOR")
    assert parse_instant(out_std["due_date"]) == (
        parse_instant(ACCEPT_INSTANT) + timedelta(days=7))
    assert parse_instant(out_rush["due_date"]) == (
        parse_instant(ACCEPT_INSTANT) + timedelta(days=4))
