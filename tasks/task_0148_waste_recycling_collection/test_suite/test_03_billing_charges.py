"""Invoice charge computation: pay-as-you-throw weight, contamination surcharge,
diversion penalty, invoice total evaluation order, and special-pickup fees.

Covers difficulty rules dual_variant_calc (PAYT free-allowance variant),
combinatorial_formula (marginal tiers, contamination round-per-pickup, invoice total
evaluation order), and boundary_precision_check (diversion rate at the floor / empty),
plus the calculations corner instances.

These scenarios require deep multi-step setup; each test builds its preconditions from
scratch via the API, threading the cart version through successive completions.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    create_route_payload,
    create_stop_payload,
    create_pickup_payload,
    complete_pickup_payload,
    create_weight_ticket_payload,
    create_contamination_tag_payload,
    create_special_pickup_payload,
    create_diversion_period_payload,
    create_account,
    create_active_cart,
    create_active_plan,
    setup_active_account,
    request_special_pickup,
    make_resident_headers,
)
import test_helpers as th
from datetime import datetime, timezone

api = th.api_client
DISPATCHER = TEST_USERS["dispatcher_headers"]
DRIVER = TEST_USERS["driver_headers"]
BILLING = TEST_USERS["billing_headers"]

# Per PRD §3.6/§3.8, weight/diversion billing keys off each WeightTicket's
# `created_at` (real server time at the moment the ticket is recorded) falling
# inside the half-open invoice/diversion window [period_start, period_end).
# The fixtures below record their tickets during the test run, so the window
# must bracket "now". We anchor it on the previous-month start through the
# next-month start so the current instant is always strictly inside the
# half-open interval regardless of the calendar date on which the suite runs.
def _bracket_now_window():
    now = datetime.now(timezone.utc)
    start_year, start_month = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    end_year, end_month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    start = f"{start_year:04d}-{start_month:02d}-01T00:00:00Z"
    end = f"{end_year:04d}-{end_month:02d}-01T00:00:00Z"
    return start, end


MAY_START, MAY_END = _bracket_now_window()


# ─── local helpers (period-spanning weighed pickups on one cart) ───────────

def _weigh_pickups(account_id, cart_id, route_id, stop_ids, specs):
    """For each (gross, diverted, tag_severity) spec, schedule+complete a pickup at the
    matching stop and record its weight ticket, threading the live cart version.
    Returns the list of completed pickup dicts."""
    pickups = []
    cart_version = validate_success(api.get_cart(cart_id, DRIVER), 200)["version"]
    for stop_id, (gross, diverted, tag) in zip(stop_ids, specs):
        pk = validate_success(api.create_pickup(stop_id, create_pickup_payload(cart_id), DISPATCHER), 201)
        validate_success(api.complete_pickup(pk["id"], complete_pickup_payload(cart_version), DRIVER), 200)
        cart_version = validate_success(api.get_cart(cart_id, DRIVER), 200)["version"]
        validate_success(api.create_weight_ticket(pk["id"], create_weight_ticket_payload(gross, diverted), DRIVER), 201)
        if tag:
            validate_success(api.create_contamination_tag(pk["id"], create_contamination_tag_payload(tag), DRIVER), 201)
        pickups.append(validate_success(api.get_pickup(pk["id"], DRIVER), 200))
    return pickups


def _new_in_progress_route(account_id, stream, num_stops, service_date):
    route = validate_success(api.create_route(create_route_payload(
        service_date=service_date, stream=stream, assigned_driver_id="drv-x"), DISPATCHER), 201)
    stops = []
    for seq in range(1, num_stops + 1):
        stops.append(validate_success(api.create_stop(
            route["id"], create_stop_payload(account_id, seq), DISPATCHER), 201))
    validate_success(api.dispatch_route(route["id"], DISPATCHER), 200)
    validate_success(api.start_route(route["id"], DRIVER), 200)
    return route, stops


def _issue_invoice_for_period(account_id, period_start=MAY_START, period_end=MAY_END):
    acct = validate_success(api.get_account(account_id, BILLING), 200)
    inv = validate_success(api.create_invoice(account_id, {
        "period_start": period_start, "period_end": period_end,
        "expected_account_version": acct["version"]}, BILLING), 201)
    return validate_success(api.issue_invoice(inv["id"], BILLING), 200)


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty / dual_variant_calc — PAYT free-allowance variant (RESIDENTIAL)
# ═══════════════════════════════════════════════════════════════════════════

def test_payt_residential_free_allowance_weight_charge():
    """PRD §3.6: "The billable pounds are the sum of `net_weight_lbs` over those trash
    tickets, reduced by the account's free allowance and floored at 0. The free
    allowance is 100 pounds for a `RESIDENTIAL` account and 0 pounds for both
    `COMMERCIAL_SMALL` and `COMMERCIAL_LARGE` accounts. The billable pounds are then
    charged at marginal stair-step rates across three tiers: the first 200 pounds at the
    tier-1 rate, the next portion above 200 pounds and up to 500 pounds at the tier-2
    rate, and any pounds beyond 500 at the tier-3 rate."
    PRD §3.6: "for `RESIDENTIAL` the three tier rates are 5, 8, and 12".

    Design: Difficulty/dual_variant_calc/payt_weight_charge_marginal_vs_free_allowance
    """
    # RESIDENTIAL, TRASH plan base 2000, TRASH cart tare 50; two pickups net 200 + 150 = 350.
    account = create_account(rate_class="RESIDENTIAL", diversion_floor_pct=0, address="1 Maple St")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=96, tare_weight_lbs=50)
    create_active_plan(account["id"], stream="TRASH", base_monthly_fee_cents=2000)
    validate_success(api.activate_account(account["id"], DISPATCHER), 200)
    route, stops = _new_in_progress_route(account["id"], "TRASH", 2, "2026-05-04T00:00:00Z")
    # gross 250 (net 200) and gross 200 (net 150); billable 350-100=250 -> 200*5 + 50*8 = 1400
    _weigh_pickups(account["id"], cart["id"], route["id"], [s["id"] for s in stops],
                   [(250, False, None), (200, False, None)])
    invoice = _issue_invoice_for_period(account["id"])
    assert invoice["weight_charge_cents"] == 1400, (
        f"expected weight_charge 1400, got {invoice['weight_charge_cents']}"
    )
    assert invoice["base_fee_cents"] == 2000, (
        f"expected base_fee 2000, got {invoice['base_fee_cents']}"
    )


def test_payt_commercial_small_no_free_allowance_same_weight_diverges():
    """PRD §3.6: "The free allowance is 100 pounds for a `RESIDENTIAL` account and 0
    pounds for both `COMMERCIAL_SMALL` and `COMMERCIAL_LARGE` accounts."
    PRD §3.6: "for `COMMERCIAL_SMALL` they are 7, 10, and 15".

    Design: Difficulty/dual_variant_calc/payt_weight_charge_marginal_vs_free_allowance
    """
    # The SAME 350 net lbs that bill 1400 for RESIDENTIAL bill differently for
    # COMMERCIAL_SMALL (no free allowance): 200*7 + 150*10 = 2900.
    account = create_account(rate_class="COMMERCIAL_SMALL", address="1c Maple St")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=96, tare_weight_lbs=50)
    create_active_plan(account["id"], stream="TRASH", base_monthly_fee_cents=2000)
    validate_success(api.activate_account(account["id"], DISPATCHER), 200)
    route, stops = _new_in_progress_route(account["id"], "TRASH", 2, "2026-05-04T00:00:00Z")
    # gross 250 (net 200) and gross 200 (net 150) -> 350 net, no allowance.
    _weigh_pickups(account["id"], cart["id"], route["id"], [s["id"] for s in stops],
                   [(250, False, None), (200, False, None)])
    invoice = _issue_invoice_for_period(account["id"])
    assert invoice["weight_charge_cents"] == 2900, (
        f"COMMERCIAL_SMALL 350 lbs (no free allowance) must be 2900, got {invoice['weight_charge_cents']}"
    )


def test_payt_commercial_small_no_free_allowance_marginal_tiers():
    """PRD §3.6: "The free allowance is 100 pounds for a `RESIDENTIAL` account and 0
    pounds for both `COMMERCIAL_SMALL` and `COMMERCIAL_LARGE` accounts. The billable
    pounds are then charged at marginal stair-step rates across three tiers: the first
    200 pounds at the tier-1 rate, the next portion above 200 pounds and up to 500
    pounds at the tier-2 rate, and any pounds beyond 500 at the tier-3 rate."
    PRD §3.6: "for `COMMERCIAL_SMALL` they are 7, 10, and 15".

    Design: Difficulty/combinatorial_formula/payt_marginal_tier_three_inputs_mode_a
    """
    # COMMERCIAL_SMALL, base 0, tare 0; one pickup net 600 -> 200*7 + 300*10 + 100*15 = 5900
    account = create_account(rate_class="COMMERCIAL_SMALL", address="5 Dock Rd")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=96, tare_weight_lbs=0)
    create_active_plan(account["id"], stream="TRASH", base_monthly_fee_cents=0)
    validate_success(api.activate_account(account["id"], DISPATCHER), 200)
    route, stops = _new_in_progress_route(account["id"], "TRASH", 1, "2026-05-06T00:00:00Z")
    _weigh_pickups(account["id"], cart["id"], route["id"], [stops[0]["id"]], [(600, False, None)])
    invoice = _issue_invoice_for_period(account["id"])
    assert invoice["weight_charge_cents"] == 5900, (
        f"expected weight_charge 5900, got {invoice['weight_charge_cents']}"
    )


def test_payt_marginal_tiers_at_six_hundred_pounds():
    """PRD §3.6: "The billable pounds are then charged at marginal stair-step rates
    across three tiers: the first 200 pounds at the tier-1 rate, the next portion above
    200 pounds and up to 500 pounds at the tier-2 rate, and any pounds beyond 500 at the
    tier-3 rate."
    PRD §3.6: "Each pound is billed at the rate of the tier it falls in."

    Design: Difficulty/combinatorial_formula/payt_marginal_tier_three_inputs_mode_a
    """
    # A second COMMERCIAL_SMALL straddle case confirming all three tiers engage.
    account = create_account(rate_class="COMMERCIAL_SMALL", address="5b Dock Rd")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=96, tare_weight_lbs=0)
    create_active_plan(account["id"], stream="TRASH", base_monthly_fee_cents=0)
    validate_success(api.activate_account(account["id"], DISPATCHER), 200)
    route, stops = _new_in_progress_route(account["id"], "TRASH", 1, "2026-05-06T00:00:00Z")
    _weigh_pickups(account["id"], cart["id"], route["id"], [stops[0]["id"]], [(600, False, None)])
    invoice = _issue_invoice_for_period(account["id"])
    assert invoice["weight_charge_cents"] == 5900, (
        f"expected weight_charge 5900, got {invoice['weight_charge_cents']}"
    )


def test_payt_recycle_excluded_from_weight_charge():
    """PRD §3.6: "counting only loads collected on `TRASH`-stream carts; recycle and
    organics weight is excluded entirely from the per-pound charge."
    PRD §2.9: "Only `TRASH`-stream weight is billable per pound under pay-as-you-throw;
    weight collected on `RECYCLE` and `ORGANICS` carts is treated as diversion".

    Design: Corner/calculations/payt_recycle_organics_excluded_from_weight_charge
    """
    # COMMERCIAL_SMALL with only a RECYCLE completed pickup net 600 -> weight charge 0.
    account = create_account(rate_class="COMMERCIAL_SMALL", address="120 Main St")
    cart = create_active_cart(account["id"], stream="RECYCLE", size_gallons=96, tare_weight_lbs=0)
    create_active_plan(account["id"], stream="RECYCLE", base_monthly_fee_cents=0)
    validate_success(api.activate_account(account["id"], DISPATCHER), 200)
    route, stops = _new_in_progress_route(account["id"], "RECYCLE", 1, "2026-05-04T00:00:00Z")
    _weigh_pickups(account["id"], cart["id"], route["id"], [stops[0]["id"]], [(600, True, None)])
    invoice = _issue_invoice_for_period(account["id"])
    assert invoice["weight_charge_cents"] == 0, (
        f"recycle-only weight charge must be 0, got {invoice['weight_charge_cents']}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty / combinatorial_formula — contamination round-per-pickup-then-sum
# ═══════════════════════════════════════════════════════════════════════════

def test_contamination_surcharge_round_per_pickup_then_sum():
    """PRD §3.6: "That pickup's surcharge is the pickup's net billable weight multiplied
    by the severity's per-pound rate, plus the severity's flat amount, with the result
    rounded half-up to whole cents per pickup. The per-pound severity rates in cents are
    2 for `MINOR`, 5 for `MAJOR`, and 10 for `REJECT`; the flat amounts in cents are 500
    for `MINOR`, 1500 for `MAJOR`, and 4000 for `REJECT`. Each pickup's surcharge is
    rounded first, and only the rounded per-pickup amounts are then summed
    (round-per-line-item-then-sum)".

    Design: Difficulty/combinatorial_formula/contamination_round_per_pickup_then_sum_mode_b
    """
    # RESIDENTIAL, base 0, tare 50; pk1 net 200 MAJOR -> 200*5+1500=2500; pk2 net 150 MINOR -> 150*2+500=800; sum 3300
    account = create_account(rate_class="RESIDENTIAL", diversion_floor_pct=0, address="7 Pine St")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=96, tare_weight_lbs=50)
    create_active_plan(account["id"], stream="TRASH", base_monthly_fee_cents=0)
    validate_success(api.activate_account(account["id"], DISPATCHER), 200)
    route, stops = _new_in_progress_route(account["id"], "TRASH", 2, "2026-05-07T00:00:00Z")
    _weigh_pickups(account["id"], cart["id"], route["id"], [s["id"] for s in stops],
                   [(250, False, "MAJOR"), (200, False, "MINOR")])
    invoice = _issue_invoice_for_period(account["id"])
    assert invoice["contamination_surcharge_cents"] == 3300, (
        f"expected contamination 3300, got {invoice['contamination_surcharge_cents']}"
    )


def test_contamination_highest_severity_dominates():
    """PRD §3.6: "For each such pickup, only the single highest-severity tag drives the
    surcharge (`REJECT` outranks `MAJOR`, which outranks `MINOR`); lower-severity tags
    on the same pickup are ignored and are not additive."

    Design: Difficulty/combinatorial_formula/contamination_round_per_pickup_then_sum_mode_b
    """
    # One pickup net 200 tagged MINOR and MAJOR; only MAJOR drives surcharge -> 200*5+1500=2500.
    account = create_account(rate_class="RESIDENTIAL", diversion_floor_pct=0, address="7b Pine St")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=96, tare_weight_lbs=50)
    create_active_plan(account["id"], stream="TRASH", base_monthly_fee_cents=0)
    validate_success(api.activate_account(account["id"], DISPATCHER), 200)
    route, stops = _new_in_progress_route(account["id"], "TRASH", 1, "2026-05-07T00:00:00Z")
    cart_v = validate_success(api.get_cart(cart["id"], DRIVER), 200)["version"]
    pk = validate_success(api.create_pickup(stops[0]["id"], create_pickup_payload(cart["id"]), DISPATCHER), 201)
    validate_success(api.complete_pickup(pk["id"], complete_pickup_payload(cart_v), DRIVER), 200)
    validate_success(api.create_weight_ticket(pk["id"], create_weight_ticket_payload(250, False), DRIVER), 201)
    validate_success(api.create_contamination_tag(pk["id"], create_contamination_tag_payload("MINOR"), DRIVER), 201)
    validate_success(api.create_contamination_tag(pk["id"], create_contamination_tag_payload("MAJOR"), DRIVER), 201)
    invoice = _issue_invoice_for_period(account["id"])
    assert invoice["contamination_surcharge_cents"] == 2500, (
        f"highest-severity (MAJOR) must dominate: expected 2500, got {invoice['contamination_surcharge_cents']}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty / combinatorial_formula — invoice total pinned evaluation order
# ═══════════════════════════════════════════════════════════════════════════

def _build_mode_c_account():
    """RESIDENTIAL floor 60, TRASH plan base 2000 + RECYCLE plan base 1000 (base 3000).
    Builds, in the MAY window:
      - TRASH pickup net 200 MAJOR-tagged  (contam 2500, contributes 200 to billable)
      - TRASH pickup net 150 untagged       (contributes 150 to billable -> total 350 -> weight 1400)
      - a carrier-fault MISSED TRASH pickup  (PENDING credit 1500)
      - RECYCLE pickup net 350 diverted      (diversion: 350 of 700 -> rate 50.00, floor 60 -> penalty 1000)
    Returns the account id.
    """
    account = create_account(rate_class="RESIDENTIAL", diversion_floor_pct=60, address="9 Elm St")
    tcart = create_active_cart(account["id"], stream="TRASH", size_gallons=96, tare_weight_lbs=50)
    rcart = create_active_cart(account["id"], stream="RECYCLE", size_gallons=96, tare_weight_lbs=0)
    create_active_plan(account["id"], stream="TRASH", base_monthly_fee_cents=2000)
    create_active_plan(account["id"], stream="RECYCLE", base_monthly_fee_cents=1000)
    validate_success(api.activate_account(account["id"], DISPATCHER), 200)

    # TRASH route: 3 stops (net200 MAJOR, net150 untagged, MISSED)
    troute, tstops = _new_in_progress_route(account["id"], "TRASH", 3, "2026-05-08T00:00:00Z")
    cart_v = validate_success(api.get_cart(tcart["id"], DRIVER), 200)["version"]
    # pickup 1: gross 250 -> net 200, MAJOR
    pk1 = validate_success(api.create_pickup(tstops[0]["id"], create_pickup_payload(tcart["id"]), DISPATCHER), 201)
    validate_success(api.complete_pickup(pk1["id"], complete_pickup_payload(cart_v), DRIVER), 200)
    cart_v = validate_success(api.get_cart(tcart["id"], DRIVER), 200)["version"]
    validate_success(api.create_weight_ticket(pk1["id"], create_weight_ticket_payload(250, False), DRIVER), 201)
    validate_success(api.create_contamination_tag(pk1["id"], create_contamination_tag_payload("MAJOR"), DRIVER), 201)
    # pickup 2: gross 200 -> net 150, untagged
    pk2 = validate_success(api.create_pickup(tstops[1]["id"], create_pickup_payload(tcart["id"]), DISPATCHER), 201)
    validate_success(api.complete_pickup(pk2["id"], complete_pickup_payload(cart_v), DRIVER), 200)
    cart_v = validate_success(api.get_cart(tcart["id"], DRIVER), 200)["version"]
    validate_success(api.create_weight_ticket(pk2["id"], create_weight_ticket_payload(200, False), DRIVER), 201)
    # pickup 3: carrier-fault MISS -> PENDING credit 1500
    pk3 = validate_success(api.create_pickup(tstops[2]["id"], create_pickup_payload(tcart["id"]), DISPATCHER), 201)
    validate_success(api.miss_pickup(pk3["id"], {"miss_reason": "MISSED_BY_CREW"}, DRIVER), 200)

    # RECYCLE route: one pickup net 350 diverted
    rroute, rstops = _new_in_progress_route(account["id"], "RECYCLE", 1, "2026-05-08T00:00:00Z")
    rcart_v = validate_success(api.get_cart(rcart["id"], DRIVER), 200)["version"]
    rpk = validate_success(api.create_pickup(rstops[0]["id"], create_pickup_payload(rcart["id"]), DISPATCHER), 201)
    validate_success(api.complete_pickup(rpk["id"], complete_pickup_payload(rcart_v), DRIVER), 200)
    validate_success(api.create_weight_ticket(rpk["id"], create_weight_ticket_payload(350, True), DRIVER), 201)

    # Finalize the diversion period over the MAY window: diverted 350, total 700 -> rate 50.00
    dp = validate_success(api.create_diversion_period(
        account["id"], create_diversion_period_payload(MAY_START, MAY_END), BILLING), 201)
    finalized = validate_success(api.finalize_diversion_period(dp["id"], BILLING), 200)
    assert finalized["diversion_rate_pct"] == 50.0, (
        f"setup expects rate 50.0, got {finalized['diversion_rate_pct']}"
    )
    return account["id"]


def test_invoice_total_pinned_evaluation_order_components():
    """PRD §3.6: "The `total_cents` is then the sum of the four charge components —
    `base_fee_cents`, `weight_charge_cents`, `contamination_surcharge_cents`, and
    `diversion_penalty_cents` — minus `credit_cents`, with the result floored at 0.
    Credits are subtracted only after all charges are summed".

    Design: Difficulty/combinatorial_formula/invoice_total_pinned_evaluation_order_mode_c
    """
    account_id = _build_mode_c_account()
    invoice = _issue_invoice_for_period(account_id)
    assert invoice["base_fee_cents"] == 3000, f"base_fee {invoice['base_fee_cents']}"
    assert invoice["weight_charge_cents"] == 1400, f"weight {invoice['weight_charge_cents']}"
    assert invoice["contamination_surcharge_cents"] == 2500, f"contam {invoice['contamination_surcharge_cents']}"
    assert invoice["diversion_penalty_cents"] == 1000, f"penalty {invoice['diversion_penalty_cents']}"
    assert invoice["credit_cents"] == 1500, f"credit {invoice['credit_cents']}"


def test_invoice_total_equals_charges_minus_credit():
    """PRD §3.6: "The `total_cents` is then the sum of the four charge components —
    `base_fee_cents`, `weight_charge_cents`, `contamination_surcharge_cents`, and
    `diversion_penalty_cents` — minus `credit_cents`, with the result floored at 0."

    Design: Difficulty/combinatorial_formula/invoice_total_pinned_evaluation_order_mode_c
    """
    account_id = _build_mode_c_account()
    invoice = _issue_invoice_for_period(account_id)
    # 3000 + 1400 + 2500 + 1000 - 1500 = 6400
    assert invoice["total_cents"] == 6400, f"expected total 6400, got {invoice['total_cents']}"


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty / boundary_precision_check — diversion rate at the floor / empty period
# ═══════════════════════════════════════════════════════════════════════════

def _build_rate_exactly_50_account(floor):
    """RESIDENTIAL floor `floor`, TRASH plan base 0. One TRASH pickup net 250 (not
    diverted) and one RECYCLE pickup net 250 (diverted) -> diversion rate exactly 50.00.
    Returns (account_id, finalized_period)."""
    account = create_account(rate_class="RESIDENTIAL", diversion_floor_pct=floor, address="21 Spruce St")
    tcart = create_active_cart(account["id"], stream="TRASH", size_gallons=96, tare_weight_lbs=0)
    rcart = create_active_cart(account["id"], stream="RECYCLE", size_gallons=96, tare_weight_lbs=0)
    create_active_plan(account["id"], stream="TRASH", base_monthly_fee_cents=0)
    validate_success(api.activate_account(account["id"], DISPATCHER), 200)

    troute, tstops = _new_in_progress_route(account["id"], "TRASH", 1, "2026-05-16T00:00:00Z")
    tcart_v = validate_success(api.get_cart(tcart["id"], DRIVER), 200)["version"]
    tpk = validate_success(api.create_pickup(tstops[0]["id"], create_pickup_payload(tcart["id"]), DISPATCHER), 201)
    validate_success(api.complete_pickup(tpk["id"], complete_pickup_payload(tcart_v), DRIVER), 200)
    validate_success(api.create_weight_ticket(tpk["id"], create_weight_ticket_payload(250, False), DRIVER), 201)

    rroute, rstops = _new_in_progress_route(account["id"], "RECYCLE", 1, "2026-05-16T00:00:00Z")
    rcart_v = validate_success(api.get_cart(rcart["id"], DRIVER), 200)["version"]
    rpk = validate_success(api.create_pickup(rstops[0]["id"], create_pickup_payload(rcart["id"]), DISPATCHER), 201)
    validate_success(api.complete_pickup(rpk["id"], complete_pickup_payload(rcart_v), DRIVER), 200)
    validate_success(api.create_weight_ticket(rpk["id"], create_weight_ticket_payload(250, True), DRIVER), 201)

    dp = validate_success(api.create_diversion_period(
        account["id"], create_diversion_period_payload(MAY_START, MAY_END), BILLING), 201)
    finalized = validate_success(api.finalize_diversion_period(dp["id"], BILLING), 200)
    return account["id"], finalized


def test_diversion_rate_computed_fifty_percent():
    """PRD §3.8: "The `diversion_rate_pct` is then 100 multiplied by `diverted_weight_lbs`
    divided by `total_weight_lbs`, rounded half-up to two decimal places".

    Design: Difficulty/boundary_precision_check/diversion_rate_meets_floor_exactly_no_penalty
    """
    _account_id, finalized = _build_rate_exactly_50_account(floor=50)
    assert finalized["diversion_rate_pct"] == 50.0, (
        f"250 diverted of 500 total must be 50.00, got {finalized['diversion_rate_pct']}"
    )


def test_diversion_penalty_zero_when_rate_meets_floor_exactly():
    """PRD §3.6: "If the diversion rate meets or exceeds the floor the shortfall is 0
    and so is the penalty — meeting the floor exactly is compliant."

    Design: Difficulty/boundary_precision_check/diversion_rate_meets_floor_exactly_no_penalty
    """
    account_id, _finalized = _build_rate_exactly_50_account(floor=50)
    invoice = _issue_invoice_for_period(account_id)
    assert invoice["diversion_penalty_cents"] == 0, (
        f"rate exactly at floor must yield 0 penalty, got {invoice['diversion_penalty_cents']}"
    )


def test_diversion_rate_empty_period_zero_total():
    """PRD §3.8: "except that when `total_weight_lbs` is 0 the rate is defined as exactly
    0 rather than undefined, so the empty-window case never divides by zero."

    Design: Difficulty/boundary_precision_check/diversion_rate_empty_period_zero_total
    """
    account = create_account(rate_class="RESIDENTIAL", address="23 Willow St")
    dp = validate_success(api.create_diversion_period(
        account["id"], create_diversion_period_payload(MAY_START, MAY_END), BILLING), 201)
    finalized = validate_success(api.finalize_diversion_period(dp["id"], BILLING), 200)
    assert finalized["total_weight_lbs"] == 0, (
        f"empty window total must be 0, got {finalized['total_weight_lbs']}"
    )
    assert finalized["diversion_rate_pct"] == 0, (
        f"empty window rate must be 0, got {finalized['diversion_rate_pct']}"
    )


def test_diversion_finalize_empty_is_terminal():
    """PRD §3.8: "The `diversion_rate_pct` is then 100 multiplied by `diverted_weight_lbs`
    divided by `total_weight_lbs`, rounded half-up to two decimal places — except that
    when `total_weight_lbs` is 0 the rate is defined as exactly 0 rather than undefined,
    so the empty-window case never divides by zero."

    Design: Difficulty/boundary_precision_check/diversion_rate_empty_period_zero_total
    """
    account = create_account(rate_class="RESIDENTIAL", address="23b Willow St")
    dp = validate_success(api.create_diversion_period(
        account["id"], create_diversion_period_payload(MAY_START, MAY_END), BILLING), 201)
    finalized = validate_success(api.finalize_diversion_period(dp["id"], BILLING), 200)
    assert finalized["status"] == "FINALIZED", f"expected FINALIZED, got {finalized['status']}"
    assert finalized["diverted_weight_lbs"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# Corner / calculations — special-pickup fee schedule
# ═══════════════════════════════════════════════════════════════════════════

def test_special_pickup_fee_hazard_toxic_multiplier():
    """PRD §3.7: "a `HAZARDOUS` request quotes 8000 cents scaled by the hazard-class
    multiplier — 1.5 for `FLAMMABLE`, 1.75 for `CORROSIVE`, 2.0 for `TOXIC`, and 1.25
    for `EWASTE` — rounded half-up to whole cents."

    Design: Corner/calculations/special_pickup_fee_hazard_toxic_multiplier
    """
    account, _cart, _plan = setup_active_account(address="119 Main St", stream="TRASH",
                                                 base_monthly_fee_cents=1000)
    sp = request_special_pickup(account["id"], kind="HAZARDOUS", hazard_class="TOXIC",
                                requested_date="2026-06-02T00:00:00Z")
    approved = validate_success(api.approve_special_pickup(sp["id"], DISPATCHER), 200)
    assert approved["quoted_fee_cents"] == 16000, (
        f"8000 * 2.0 = 16000 expected, got {approved['quoted_fee_cents']}"
    )
