"""Pricing, settlement, and fleet-invoice calculations.

Covers monthly proration vs daily tiered cost, buyout equity decay (and its 60% cap),
the return-settlement waterfall, late-fee boundary, and fleet-invoice round-then-sum order.
"""
from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    make_subscriber_headers,
    make_field_tech_headers,
    make_ops_admin_headers,
    setup_fleet_with_active_monthly_lines,
    advance_cycles,
    inspect_payload,
)
from test_helpers.fixtures import (
    set_clock, create_model, add_bikes, create_account, read_model_version,
    reserve, schedule_and_complete_initial_delivery, activate,
)

OPS = make_ops_admin_headers()
TECH = make_field_tech_headers()


# ===========================================================================
# Difficulty/dual_variant_calc/cost_of_rental_monthly_vs_daily_diverge
# ===========================================================================
def test_monthly_first_cycle_prorated_charge(api):
    """PRD §3.8: "The first-cycle charge is the effective monthly amount multiplied by
    the remaining days, divided by 30, rounded half up to whole cents, and that value
    is stored as accrued_charge_cents."
    PRD §3.8: "Each model_class carries a surcharge: STANDARD adds nothing, EBIKE adds
    2000 cents, and CARGO_EBIKE adds 4000 cents."

    EBIKE monthly_fee 12000 + surcharge 2000 = 14000; reserved 2026-06-01, activated
    2026-06-11 (offset 10 whole days, remaining 20): round_half_up(14000*20/30) == 9333.

    Design: Difficulty/dual_variant_calc/cost_of_rental_monthly_vs_daily_diverge
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(model_class="EBIKE", monthly_fee_cents=12000,
                         daily_rate_cents=4000, purchase_price_cents=180000,
                         deposit_cents=20000, fleet_size=10)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=2)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv, rental_mode="MONTHLY",
                     return_due_clock="2026-12-01T00:00:00Z")
    schedule_and_complete_initial_delivery(rental["id"])
    set_clock("2026-06-11T00:00:00Z")
    resp = api_client.activate_rental(rental["id"], make_subscriber_headers(account["id"]))
    data = validate_success(resp, 200)
    assert data["accrued_charge_cents"] == 9333, (
        f"Expected prorated 9333, got {data['accrued_charge_cents']}"
    )
    assert data["rental_mode"] == "MONTHLY"


def test_daily_tiered_cost_differs_from_monthly(api):
    """PRD §3.8: "For a DAILY rental no equity is earned" / "There is no proration for
    daily rentals."
    PRD §3.8: "each of the first 6 days bills the full effective daily amount; each day
    from the 7th through the 29th inclusive bills the effective daily amount multiplied
    by 0.85, rounded half up to whole cents".

    A DAILY EBIKE rental (daily_rate 4000 + surcharge 2000 = 6000/day) over 10 days
    accrues 6*6000 + 4*round(6000*0.85) = 36000 + 4*5100 = 56400, distinct from the
    monthly prorated charge for the same model.

    Design: Difficulty/dual_variant_calc/cost_of_rental_monthly_vs_daily_diverge
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(model_class="EBIKE", monthly_fee_cents=12000,
                         daily_rate_cents=4000, purchase_price_cents=180000,
                         deposit_cents=20000, fleet_size=10)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=2)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv, rental_mode="DAILY",
                     return_due_clock="2026-06-21T00:00:00Z")
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    get_success_data(api_client.request_return(rental["id"], {"return_address": "1 A St"}, sub))
    set_clock("2026-06-11T00:00:00Z")
    get_success_data(api_client.inspect_rental(rental["id"], inspect_payload(), TECH))
    data = get_success_data(api_client.get_rental(rental["id"], sub))
    assert data["accrued_charge_cents"] == 56400, (
        f"Expected daily tiered 56400, got {data['accrued_charge_cents']}"
    )
    assert data["rental_mode"] == "DAILY"


# ===========================================================================
# Difficulty/dual_variant_calc/buyout_subscription_equity_vs_daily_flat
# ===========================================================================
def test_buyout_subscription_equity_after_ten_cycles(api):
    """PRD §3.8: "the raw equity is the base multiplied by 0.03 per completed cycle
    (that is, base × 0.03 × completed_cycles), rounded half up; an equity cap equal to
    the base multiplied by 0.60, rounded half up, bounds it; the equity_credit_cents is
    the smaller of the raw equity and the cap; and the quoted_price_cents is the base
    minus equity_credit_cents."

    Base 180000, 10 cycles: raw_equity = round(180000*0.03*10) = 54000 (< cap 108000),
    quoted_price = 180000 - 54000 = 126000.

    Design: Difficulty/dual_variant_calc/buyout_subscription_equity_vs_daily_flat
    """
    # Build directly so we can advance exactly 10 cycles before quoting.
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(model_class="EBIKE", monthly_fee_cents=12000,
                         daily_rate_cents=4000, purchase_price_cents=180000,
                         deposit_cents=20000, fleet_size=10)
    add_bikes(model["id"], 2)
    account = create_account(rental_cap=2)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv, rental_mode="MONTHLY",
                     return_due_clock="2027-06-01T00:00:00Z")
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    advance_cycles(rental["id"], 10)
    sub = make_subscriber_headers(account["id"])
    resp = api_client.create_buyout_offer(
        rental["id"], {"expires_at_clock": "2026-06-30T00:00:00Z"}, sub)
    data = validate_success(resp, 201)
    assert data["quoted_price_cents"] == 126000
    assert data["equity_credit_cents"] == 54000


def test_buyout_daily_flat_no_equity(api):
    """PRD §3.8: "For a DAILY rental no equity is earned: equity_credit_cents is 0 and
    quoted_price_cents equals the base purchase price regardless of how long the bike
    was held."

    Base 180000, DAILY mode: equity_credit 0, quoted_price 180000.

    Design: Difficulty/dual_variant_calc/buyout_subscription_equity_vs_daily_flat
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(model_class="EBIKE", monthly_fee_cents=12000,
                         daily_rate_cents=4000, purchase_price_cents=180000,
                         deposit_cents=20000, fleet_size=10)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=2)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv, rental_mode="DAILY",
                     return_due_clock="2026-07-01T00:00:00Z")
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    resp = api_client.create_buyout_offer(
        rental["id"], {"expires_at_clock": "2026-06-30T00:00:00Z"}, sub)
    data = validate_success(resp, 201)
    assert data["quoted_price_cents"] == 180000
    assert data["equity_credit_cents"] == 0


# ===========================================================================
# Difficulty/combinatorial_formula/daily_tiered_rate_three_tier_selection
# ===========================================================================
def test_daily_tiered_cargo_ebike_two_tier_sum(api):
    """PRD §3.8: "each of the first 6 days bills the full effective daily amount; each
    day from the 7th through the 29th inclusive bills the effective daily amount
    multiplied by 0.85, rounded half up to whole cents ... Each day's rounded amount is
    summed (round-then-sum), and the total is stored as accrued_charge_cents."

    CARGO_EBIKE daily_rate 4000 + surcharge 4000 = 8000/day over 10 days:
    6*8000 + 4*round(8000*0.85) = 48000 + 4*6800 = 75200.

    Design: Difficulty/combinatorial_formula/daily_tiered_rate_three_tier_selection
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(name="Cargo X", model_class="CARGO_EBIKE",
                         monthly_fee_cents=20000, daily_rate_cents=4000,
                         purchase_price_cents=300000, deposit_cents=20000, fleet_size=5)
    add_bikes(model["id"], 1, prefix="C")
    account = create_account(display_name="Dee", email="dee@x.com", rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv, rental_mode="DAILY",
                     return_due_clock="2026-06-12T00:00:00Z")
    schedule_and_complete_initial_delivery(rental["id"], window_start="2026-06-01T08:00:00Z",
                                           window_end="2026-06-01T12:00:00Z")
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    get_success_data(api_client.request_return(rental["id"], {"return_address": "2 B St"}, sub))
    set_clock("2026-06-11T00:00:00Z")
    insp = get_success_data(api_client.inspect_rental(rental["id"], inspect_payload(), TECH))
    assert insp["late_fee_cents"] == 0, "returned 2026-06-11 < due 2026-06-12"
    data = get_success_data(api_client.get_rental(rental["id"], sub))
    assert data["accrued_charge_cents"] == 75200, (
        f"Expected 75200, got {data['accrued_charge_cents']}"
    )


def test_daily_tiered_late_fee_zero_when_before_due(api):
    """PRD §3.9: "If returned_at_clock is at or before the rental's return_due_clock,
    the late fee is 0."

    Returned 2026-06-11 strictly before due 2026-06-12 yields late_fee_cents 0.

    Design: Difficulty/combinatorial_formula/daily_tiered_rate_three_tier_selection
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(name="Cargo X", model_class="CARGO_EBIKE",
                         monthly_fee_cents=20000, daily_rate_cents=4000,
                         purchase_price_cents=300000, deposit_cents=20000, fleet_size=5)
    add_bikes(model["id"], 1, prefix="C")
    account = create_account(display_name="Dee", email="dee@x.com", rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv, rental_mode="DAILY",
                     return_due_clock="2026-06-12T00:00:00Z")
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    get_success_data(api_client.request_return(rental["id"], {"return_address": "2 B St"}, sub))
    set_clock("2026-06-11T00:00:00Z")
    resp = api_client.inspect_rental(rental["id"], inspect_payload(), TECH)
    data = validate_success(resp, 201)
    assert data["late_fee_cents"] == 0


# ===========================================================================
# Difficulty/combinatorial_formula/fleet_invoice_round_then_sum_order
# ===========================================================================
def test_fleet_invoice_round_then_sum_amount_due(api):
    """PRD §3.11: "each line's charge is multiplied by (1 − 0.10), rounded half up per
    line, and amount_due_cents is the sum of those discounted per-line amounts (discount
    applied per line, then rounded half up, then summed — round-then-sum, not
    sum-then-round)."

    5 STANDARD monthly lines of 8333: 5*round(8333*0.9) = 5*7500 = 37500
    (sum-then-round would give round(5*8333*0.9) = 37499).

    Design: Difficulty/combinatorial_formula/fleet_invoice_round_then_sum_order
    """
    bundle = setup_fleet_with_active_monthly_lines(5, monthly_fee_cents=8333)
    fm = make_ops_admin_headers()  # OpsAdmin may also generate the invoice
    resp = api_client.create_fleet_invoice(
        bundle["account"]["id"], {"cycle_index": 0}, fm)
    data = validate_success(resp, 201)
    assert data["amount_due_cents"] == 37500, (
        f"round-then-sum expects 37500, got {data['amount_due_cents']}"
    )


def test_fleet_invoice_line_count_gross_and_discount(api):
    """PRD §3.11: "The line_count is the number of such lines. Each line's charge is the
    line's model monthly_fee_cents plus that model's class surcharge, and
    gross_amount_cents is the sum of those per-line charges before any discount."
    PRD §3.11: "The discount_cents is gross_amount_cents minus amount_due_cents."

    5 STANDARD lines of 8333: line_count 5, gross 41665, discount 41665-37500 = 4165.

    Design: Difficulty/combinatorial_formula/fleet_invoice_round_then_sum_order
    """
    bundle = setup_fleet_with_active_monthly_lines(5, monthly_fee_cents=8333)
    from test_helpers import make_fleet_manager_headers
    fm = make_fleet_manager_headers(bundle["account"]["id"])
    resp = api_client.create_fleet_invoice(
        bundle["account"]["id"], {"cycle_index": 0}, fm)
    data = validate_success(resp, 201)
    assert data["line_count"] == 5
    assert data["gross_amount_cents"] == 41665
    assert data["discount_cents"] == 4165


# ===========================================================================
# Difficulty/boundary_precision_check/late_fee_on_time_vs_one_day_late
# ===========================================================================
def test_late_fee_zero_at_exact_due_boundary(api):
    """PRD §3.9: "The boundary is exact: a return at precisely return_due_clock incurs
    no fee, while a return strictly after it does."

    DAILY rental due 2026-06-10T00:00:00Z, returned at exactly that instant: late_fee 0.

    Design: Difficulty/boundary_precision_check/late_fee_on_time_vs_one_day_late
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(deposit_cents=20000, fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv, rental_mode="DAILY",
                     return_due_clock="2026-06-10T00:00:00Z")
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    get_success_data(api_client.request_return(rental["id"], {"return_address": "1 A St"}, sub))
    set_clock("2026-06-10T00:00:00Z")
    resp = api_client.inspect_rental(rental["id"], inspect_payload(), TECH)
    data = validate_success(resp, 201)
    assert data["late_fee_cents"] == 0, (
        f"At-due boundary must incur no fee, got {data['late_fee_cents']}"
    )


def test_late_fee_one_day_when_strictly_late(api):
    """PRD §3.9: "Otherwise the platform computes the overage as the elapsed time from
    return_due_clock to returned_at_clock, divided by one day and rounded up to the next
    whole day (any strictly positive overage rounds up to at least one day), and
    multiplies that whole-day count by the per-day late fee of 1500 cents to obtain
    late_fee_cents."

    Returned 1 hour after due (any strictly positive overage) rounds up to 1 day: 1500.

    Design: Difficulty/boundary_precision_check/late_fee_on_time_vs_one_day_late
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(deposit_cents=20000, fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv, rental_mode="DAILY",
                     return_due_clock="2026-06-10T00:00:00Z")
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    get_success_data(api_client.request_return(rental["id"], {"return_address": "1 A St"}, sub))
    set_clock("2026-06-10T01:00:00Z")
    resp = api_client.inspect_rental(rental["id"], inspect_payload(), TECH)
    data = validate_success(resp, 201)
    assert data["late_fee_cents"] == 1500, (
        f"1 hour late rounds up to 1 day -> 1500, got {data['late_fee_cents']}"
    )


# ===========================================================================
# Difficulty/boundary_precision_check/fleet_volume_discount_threshold_at_five
# ===========================================================================
def test_fleet_volume_discount_absent_at_four_lines(api):
    """PRD §3.11: "When the line count is below 5, no discount applies and
    amount_due_cents equals gross_amount_cents."

    4 STANDARD lines of 8333 (one below the threshold of 5): discount_cents 0 and
    amount_due_cents 4*8333 = 33332.

    Design: Difficulty/boundary_precision_check/fleet_volume_discount_threshold_at_five
    """
    bundle = setup_fleet_with_active_monthly_lines(4, monthly_fee_cents=8333)
    from test_helpers import make_fleet_manager_headers
    fm = make_fleet_manager_headers(bundle["account"]["id"])
    resp = api_client.create_fleet_invoice(
        bundle["account"]["id"], {"cycle_index": 0}, fm)
    data = validate_success(resp, 201)
    assert data["line_count"] == 4
    assert data["discount_cents"] == 0
    assert data["amount_due_cents"] == 33332


def test_fleet_volume_discount_applies_at_five_lines(api):
    """PRD §3.11: "A volume discount applies when the line count is at least 5: in that
    case each line's charge is multiplied by (1 − 0.10), rounded half up per line, and
    amount_due_cents is the sum of those discounted per-line amounts".

    Crossing into 5 lines applies the discount: discount_cents 4165 > 0 (vs 0 at 4).

    Design: Difficulty/boundary_precision_check/fleet_volume_discount_threshold_at_five
    """
    bundle = setup_fleet_with_active_monthly_lines(5, monthly_fee_cents=8333)
    from test_helpers import make_fleet_manager_headers
    fm = make_fleet_manager_headers(bundle["account"]["id"])
    resp = api_client.create_fleet_invoice(
        bundle["account"]["id"], {"cycle_index": 0}, fm)
    data = validate_success(resp, 201)
    assert data["line_count"] == 5
    assert data["discount_cents"] == 4165
    assert data["amount_due_cents"] == 37500


# ===========================================================================
# Corner/calculations/return_settlement_overflow_billed_beyond_deposit
# ===========================================================================
def test_return_settlement_overflow_billed_beyond_deposit(api):
    """PRD §3.9: "The deposit absorbs charges first: deposit_applied_cents is the smaller
    of the rental's deposit_cents and total_assessed_cents. Any excess beyond the deposit
    is billed to the account: overflow_billed_cents is the greater of zero and
    total_assessed_cents minus the deposit. The remainder of the deposit is refunded to
    the wallet: deposit_refund_cents is the greater of zero and the deposit minus
    total_assessed_cents."
    PRD §3.9: "The total_assessed_cents is the sum of damage_charge_cents,
    cleaning_fee_cents, and late_fee_cents."

    Deposit 20000; damage 15000 + cleaning 2000 + late 4500 (50h late -> 3 days * 1500)
    = 21500 assessed: deposit_applied 20000, overflow 1500, refund 0.

    Design: Corner/calculations/return_settlement_overflow_billed_beyond_deposit
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(deposit_cents=20000, fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv, rental_mode="DAILY",
                     return_due_clock="2026-06-10T00:00:00Z")
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    sub = make_subscriber_headers(account["id"])
    get_success_data(api_client.request_return(rental["id"], {"return_address": "1 A St"}, sub))
    set_clock("2026-06-12T02:00:00Z")
    resp = api_client.inspect_rental(
        rental["id"],
        inspect_payload(bike_condition="DAMAGED", damage_charge_cents=15000,
                        cleaning_fee_cents=2000),
        TECH)
    data = validate_success(resp, 201)
    assert data["late_fee_cents"] == 4500, "ceil(50h/24)=3 days * 1500"
    assert data["total_assessed_cents"] == 21500
    assert data["deposit_applied_cents"] == 20000
    assert data["overflow_billed_cents"] == 1500
    assert data["deposit_refund_cents"] == 0


# ===========================================================================
# Corner/calculations/buyout_equity_capped_at_sixty_percent
# ===========================================================================
def test_buyout_equity_capped_at_sixty_percent(api):
    """PRD §3.8: "an equity cap equal to the base multiplied by 0.60, rounded half up,
    bounds it; the equity_credit_cents is the smaller of the raw equity and the cap; and
    the quoted_price_cents is the base minus equity_credit_cents."

    Base 180000, 25 cycles: raw equity 0.03*25 = 0.75 of base exceeds the 0.60 cap, so
    equity_credit caps at 108000 and quoted_price == 72000.

    Design: Corner/calculations/buyout_equity_capped_at_sixty_percent
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(model_class="EBIKE", monthly_fee_cents=12000,
                         daily_rate_cents=4000, purchase_price_cents=180000,
                         deposit_cents=20000, fleet_size=5)
    add_bikes(model["id"], 1, prefix="E")
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv, rental_mode="MONTHLY",
                     return_due_clock="2029-06-01T00:00:00Z")
    schedule_and_complete_initial_delivery(rental["id"])
    activate(rental["id"], account["id"])
    advance_cycles(rental["id"], 25)
    sub = make_subscriber_headers(account["id"])
    resp = api_client.create_buyout_offer(
        rental["id"], {"expires_at_clock": "2026-12-01T00:00:00Z"}, sub)
    data = validate_success(resp, 201)
    assert data["equity_credit_cents"] == 108000, "capped at 60% of 180000"
    assert data["quoted_price_cents"] == 72000
