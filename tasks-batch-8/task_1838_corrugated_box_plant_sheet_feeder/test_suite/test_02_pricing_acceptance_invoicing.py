"""Pricing engine (PROVISIONAL and FINAL variants), quote acceptance,
invoicing, and credit exposure."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_order_to_produced,
    assert_box_order,
    assert_money,
    assert_msf,
    assert_price_quote,
    create_accepted_order,
    create_box_order_payload,
    create_clock_payload,
    create_customer,
    create_draft_order,
    create_grade,
    create_grade_44bc,
    create_price_quote_payload,
    create_work_shift,
    create_corrugator_run,
    quote_order,
    setup_customer_and_grade,
    setup_invoiced_order_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

SALES = TEST_USERS["sales_rep_headers"]
ADMIN = TEST_USERS["plant_admin_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


def _create_acme_die_cut_order(customer, grade):
    """Canonical DIE_CUT INTERNAL 29x36 qty 2000, min_ect 32, inks
    [BLACK, RED] — area 7.25 sqft, billable 14.5 MSF at qty 2000."""
    return create_draft_order(customer["id"], grade["id"])


def test_quote_pricing_combines_color_surcharge_and_die_cut_multiplier(
    api, sales_rep_headers
):
    """PRD 3.3: "Third, the merchandise rate per thousand square feet: the
    locked `unit_price_per_msf` plus a color surcharge of 1.50 per MSF for each
    entry in `color_count`. Fourth, a routing multiplier of 1.12 when
    `routing_type` is `DIE_CUT` and 1.00 when it is `SLOTTED`. Fifth,
    `merchandise_total_dollars` — `billable_msf` times the surcharged rate
    times the routing multiplier, rounded half-up to 2 decimal places."

    Design: Difficulty/combinatorial_formula/freight_tier_routing_multiplier_color_surcharge_interaction
    """
    customer, grade = setup_customer_and_grade()
    order = _create_acme_die_cut_order(customer, grade)
    quote = quote_order(order, unit_price=60.00)
    assert_price_quote(quote)
    # area 7.25 -> billable 2000 * 7.25 / 1000 = 14.5 MSF
    assert_msf(quote["billable_msf"], 14.5)
    # rate = 60.00 + 1.50 * 2 = 63.00; merch = 14.5 * 63.00 * 1.12
    assert_money(quote["merchandise_total_dollars"], 1023.12)


def test_quote_freight_tier_local_and_total(api, sales_rep_headers):
    """PRD 3.3: "Sixth, the freight tier from the customer's
    `distance_miles_from_plant`: `LOCAL` when the distance is at most 150.00
    miles, `REGIONAL` when greater than 150.00 and at most 400.00, `NATIONAL`
    when greater than 400.00. Seventh, `freight_charge_dollars` —
    `billable_msf` times the tier rate (18.00 for `LOCAL`, 32.00 for
    `REGIONAL`, 47.00 for `NATIONAL`), rounded half-up to 2 decimal places."
    PRD 3.3: "Finally `quote_total_dollars` is the merchandise total minus the
    discount plus the freight charge — an exact 2-decimal subtraction and
    addition with no further rounding."

    Design: Difficulty/combinatorial_formula/freight_tier_routing_multiplier_color_surcharge_interaction
    """
    customer, grade = setup_customer_and_grade()  # 120.0 miles -> LOCAL
    order = _create_acme_die_cut_order(customer, grade)
    quote = quote_order(order, unit_price=60.00)
    assert quote["freight_tier"] == "LOCAL"
    assert_money(quote["freight_charge_dollars"], 261.00)  # 14.5 * 18.00
    # 1023.12 - 0.00 discount (merchandise < 5000) + 261.00
    assert_money(quote["discount_dollars"], 0.00)
    assert_money(quote["quote_total_dollars"], 1284.12)


def test_volume_discount_tier_read_off_merchandise_alone(api, sales_rep_headers):
    """PRD 3.3: "The volume discount is keyed on the merchandise total only —
    never on merchandise plus freight, and never on the post-discount total —
    which removes any circular reading of "total sets tier, tier sets total".
    `discount_pct` is 0.00 when `merchandise_total_dollars` is below 5000.00,
    0.02 when it is at least 5000.00 but below 20000.00, and 0.04 when it is at
    least 20000.00. `discount_dollars` is the merchandise total multiplied by
    the percentage, rounded half-up to 2 decimal places."

    Design: Difficulty/combinatorial_formula/volume_discount_tier_keyed_on_merchandise_only_pinned_order
    """
    customer = create_customer(
        name="Beacon Retail", city="Reno", miles=500.0, credit_limit=100000.00
    )
    grade = create_grade_44bc()
    order = create_draft_order(
        customer["id"],
        grade["id"],
        routing_type="SLOTTED",
        quantity=48000,
        blank_width_in=20.0,
        blank_length_in=30.0,
        min_ect_required=40,
        ink_colors=[],
    )
    quote = quote_order(order, unit_price=80.00)
    # area = 600/144 -> 4.1667; billable = round4(48000 * 4.1667 / 1000) = 200.0016
    # merchandise = 200.0016 * 80.00 * 1.00 = 16000.13
    assert_money(quote["merchandise_total_dollars"], 16000.13)
    # Tier keyed on merchandise 16000.13 in [5000, 20000) -> 0.02, NOT on
    # merchandise+freight 25400.21 which would select 0.04
    assert quote["discount_pct"] == pytest.approx(0.02, abs=1e-9)
    assert_money(quote["discount_dollars"], 320.00)


def test_quote_total_is_merchandise_minus_discount_plus_freight(
    api, sales_rep_headers
):
    """PRD 3.3: "Finally `quote_total_dollars` is the merchandise total minus
    the discount plus the freight charge — an exact 2-decimal subtraction and
    addition with no further rounding."
    PRD 3.3: "Seventh, `freight_charge_dollars` — `billable_msf` times the
    tier rate (18.00 for `LOCAL`, 32.00 for `REGIONAL`, 47.00 for `NATIONAL`),
    rounded half-up to 2 decimal places."

    Design: Difficulty/combinatorial_formula/volume_discount_tier_keyed_on_merchandise_only_pinned_order
    """
    customer = create_customer(
        name="Beacon Retail", city="Reno", miles=500.0, credit_limit=100000.00
    )
    grade = create_grade_44bc()
    order = create_draft_order(
        customer["id"],
        grade["id"],
        routing_type="SLOTTED",
        quantity=48000,
        blank_width_in=20.0,
        blank_length_in=30.0,
        min_ect_required=40,
        ink_colors=[],
    )
    quote = quote_order(order, unit_price=80.00)
    assert quote["freight_tier"] == "NATIONAL"
    assert_money(quote["freight_charge_dollars"], 9400.08)  # 200.0016 * 47.00
    # 16000.13 - 320.00 + 9400.08
    assert_money(quote["quote_total_dollars"], 25080.21)


def test_distance_exactly_150_miles_is_local_tier(api, sales_rep_headers):
    """PRD 3.3: "`LOCAL` when the distance is at most 150.00 miles, `REGIONAL`
    when greater than 150.00 and at most 400.00, `NATIONAL` when greater than
    400.00."

    Design: Difficulty/boundary_precision_check/freight_tier_boundary_at_exactly_150_miles
    """
    customer = create_customer(name="Cinder Freight", city="Modesto", miles=150.00)
    grade = create_grade()
    order = create_draft_order(
        customer["id"],
        grade["id"],
        routing_type="SLOTTED",
        quantity=1000,
        blank_width_in=24.0,
        blank_length_in=20.0,
        min_ect_required=30,
        ink_colors=[],
    )
    quote = quote_order(order, unit_price=50.00)
    assert quote["freight_tier"] == "LOCAL"
    # billable 3.3333 MSF: freight = 3.3333 * 18.00 = 60.00
    assert_money(quote["freight_charge_dollars"], 60.00)
    # merchandise = 3.3333 * 50.00 = 166.67; total = 166.67 + 60.00
    assert_money(quote["quote_total_dollars"], 226.67)


def test_distance_150_01_miles_is_regional_tier(api, sales_rep_headers):
    """PRD 3.3: "`LOCAL` when the distance is at most 150.00 miles, `REGIONAL`
    when greater than 150.00 and at most 400.00, `NATIONAL` when greater than
    400.00."

    Design: Difficulty/boundary_precision_check/freight_tier_boundary_at_exactly_150_miles
    """
    customer = create_customer(name="Edge Logistics", city="Merced", miles=150.01)
    grade = create_grade()
    order = create_draft_order(
        customer["id"],
        grade["id"],
        routing_type="SLOTTED",
        quantity=1000,
        blank_width_in=24.0,
        blank_length_in=20.0,
        min_ect_required=30,
        ink_colors=[],
    )
    quote = quote_order(order, unit_price=50.00)
    assert quote["freight_tier"] == "REGIONAL"
    # freight = 3.3333 * 32.00 = 106.67
    assert_money(quote["freight_charge_dollars"], 106.67)
    assert_money(quote["quote_total_dollars"], 273.34)


def test_billable_msf_rounded_at_four_decimals(api, sales_rep_headers):
    """PRD 3.3: "Second, `billable_msf` — the quantity (ordered for
    PROVISIONAL, produced for FINAL) multiplied by `area_sqft_per_box` and
    divided by 1000, rounded half-up to 4 decimal places."
    PRD 2.5: "Where a formula names an intermediate — `area_sqft_per_box` at 4
    decimals, `billable_msf` at 4 decimals, `per_box_price_dollars` at 4
    decimals, money outputs at 2 decimals — that intermediate is rounded
    half-up to its pinned precision before it feeds the next step."

    Design: Corner/calculations/billable_msf_four_decimal_rounding_precision
    """
    customer = create_customer(
        name="Delta Regional", city="Stockton", miles=200.0, credit_limit=50000.00
    )
    grade = create_grade()
    order = create_draft_order(
        customer["id"],
        grade["id"],
        routing_type="SLOTTED",
        quantity=4000,
        blank_width_in=30.0,
        blank_length_in=40.0,
        min_ect_required=30,
        ink_colors=[],
    )
    quote = quote_order(order, unit_price=90.00)
    # area = 1200/144 = 8.3333 (4dp); billable = round4(4000 * 8.3333 / 1000)
    assert_msf(quote["billable_msf"], 33.3332)
    assert_money(quote["merchandise_total_dollars"], 2999.99)  # 33.3332 * 90.00
    assert quote["freight_tier"] == "REGIONAL"
    assert_money(quote["freight_charge_dollars"], 1066.66)  # 33.3332 * 32.00
    assert_money(quote["quote_total_dollars"], 4066.65)


def test_invoice_computes_final_variant_from_produced_qty(api, sales_rep_headers):
    """PRD 3.3: "The PROVISIONAL variant runs at quote creation and uses the
    ordered `quantity`; the FINAL variant runs at invoicing and uses the actual
    `produced_qty`, with the rate re-derived from the same locked
    `unit_price_per_msf`, so quote and invoice totals diverge whenever the
    produced count differs from the ordered count."
    PRD 3.6: "The FINAL pricing variant (§3.3) computes
    `invoice_billable_msf` and `invoice_merchandise_dollars` from
    `produced_qty` at the accepted quote's locked `unit_price_per_msf`, and the
    volume-discount rule computes `invoice_discount_dollars`,
    `invoice_freight_dollars`, and `invoice_total_dollars`."

    Design: Difficulty/dual_variant_calc/order_pricing_provisional_quote_vs_final_invoice
    """
    scenario = setup_invoiced_order_scenario(produced_qty=2100)
    order = scenario["order"]
    assert order["status"] == "INVOICED"
    # FINAL variant: Q = 2100 (PROVISIONAL billed 2000)
    assert_msf(order["invoice_billable_msf"], 15.225)  # 2100 * 7.25 / 1000
    assert_money(order["invoice_merchandise_dollars"], 1074.28)  # 15.225*63*1.12
    assert_money(order["invoice_discount_dollars"], 0.00)
    assert_money(order["invoice_freight_dollars"], 274.05)  # 15.225 * 18.00
    assert_money(order["invoice_total_dollars"], 1348.33)
    assert order["produced_qty"] == 2100


def test_invoice_marks_accepted_quote_invoiced_and_diverges_from_provisional(
    api, sales_rep_headers
):
    """PRD 3.6: "The order's `ACCEPTED` quote flips to `INVOICED`, the order
    itself becomes `INVOICED`, the customer's `credit_exposure_dollars` is
    recomputed (the invoiced order leaves the exposure set), and the order's
    `version` increments."
    PRD 3.3: "The PROVISIONAL variant runs at quote creation and uses the
    ordered `quantity`; the FINAL variant runs at invoicing and uses the actual
    `produced_qty`, with the rate re-derived from the same locked
    `unit_price_per_msf`, so quote and invoice totals diverge whenever the
    produced count differs from the ordered count."

    Design: Difficulty/dual_variant_calc/order_pricing_provisional_quote_vs_final_invoice
    """
    scenario = setup_invoiced_order_scenario(produced_qty=2100)
    order = scenario["order"]
    quote_id = scenario["quote"]["id"]
    quotes, meta = validate_paginated(
        api.list_price_quotes(order["id"], sales_rep_headers)
    )
    assert meta["total_count"] == 1
    quote = quotes[0]
    assert quote["id"] == quote_id
    assert quote["status"] == "INVOICED"
    # PROVISIONAL snapshot stays on the quote; FINAL diverges on billed qty
    assert_money(quote["quote_total_dollars"], 1284.12)
    assert_money(order["invoice_total_dollars"], 1348.33)
    assert float(order["invoice_total_dollars"]) != float(
        quote["quote_total_dollars"]
    ), "FINAL and PROVISIONAL totals must diverge when produced != ordered"


def test_credit_exposure_accept_then_invoice(api, sales_rep_headers):
    """PRD 3.1: "it is the sum of `committed_value_dollars` over that
    customer's orders whose status is one of `ACCEPTED`, `SCHEDULED`,
    `AWAITING_CONVERTING`, `DIE_CUT_QUEUED`, `SLOTTED_QUEUED`, `CONVERTING`, or
    `PRODUCED`. Orders in `DRAFT` or `QUOTED` are uncommitted and excluded;
    orders that reach `INVOICED` or `CANCELLED` leave the exposure set."
    PRD 3.6: "the customer's `credit_exposure_dollars` is recomputed (the
    invoiced order leaves the exposure set)".

    Design: Corner/calculations/credit_exposure_rollup_accept_then_invoice
    """
    customer, grade = setup_customer_and_grade()
    order = _create_acme_die_cut_order(customer, grade)
    quote = quote_order(order, unit_price=60.00)

    before = validate_success(api.get_customer_account(customer["id"], sales_rep_headers))
    assert_money(before["credit_exposure_dollars"], 0.00)  # QUOTED excluded

    validate_success(api.accept_price_quote(quote["id"], sales_rep_headers))
    after_accept = validate_success(
        api.get_customer_account(customer["id"], sales_rep_headers)
    )
    assert_money(after_accept["credit_exposure_dollars"], 1284.12)

    # Walk through production and invoice
    order = validate_success(api.get_box_order(order["id"], sales_rep_headers))
    order, _ = advance_order_to_produced(order["id"], grade["id"], 2100)
    validate_success(api.invoice_box_order(order["id"], sales_rep_headers))
    after_invoice = validate_success(
        api.get_customer_account(customer["id"], sales_rep_headers)
    )
    assert_money(after_invoice["credit_exposure_dollars"], 0.00)


def test_accept_accepted_quote_rejected_not_open(api, sales_rep_headers):
    """PRD 3.2: "The checks, in evaluation order: the quote must be `OPEN`
    (otherwise `ERR_QUOTE_NOT_OPEN`)".

    Design: Corner/state_machines/accept_already_accepted_quote_returns_quote_not_open
    """
    customer, grade = setup_customer_and_grade()
    order = _create_acme_die_cut_order(customer, grade)
    quote = quote_order(order, unit_price=60.00)
    validate_success(api.accept_price_quote(quote["id"], sales_rep_headers))

    res = api.accept_price_quote(quote["id"], sales_rep_headers)
    validate_error(res, ApiErrorId.ERR_QUOTE_NOT_OPEN, expected_status=409)

    exposure = validate_success(
        api.get_customer_account(customer["id"], sales_rep_headers)
    )
    assert_money(
        exposure["credit_exposure_dollars"], 1284.12
    )  # not double-counted


def test_requote_supersedes_prior_open_quote(api, sales_rep_headers):
    """PRD 3.2: "On success a `PriceQuote` is created in `OPEN` status with its
    full PROVISIONAL pricing computed (see §3.3), its `order_id` pointing back
    at the parent box order, and any other `OPEN` quote on the same order flips
    to `SUPERSEDED`, and the order's `version` increments."

    Design: Corner/state_machines/requote_supersedes_prior_open_quote
    """
    customer, grade = setup_customer_and_grade()
    order = _create_acme_die_cut_order(customer, grade)
    quote1 = quote_order(order, unit_price=60.00)

    order_now = validate_success(api.get_box_order(order["id"], sales_rep_headers))
    assert order_now["status"] == "QUOTED"
    assert order_now["version"] == 2

    quote2 = validate_success(
        api.create_price_quote(
            order["id"],
            create_price_quote_payload(
                order_now["version"], unit_price_per_msf=65.00
            ),
            sales_rep_headers,
        ),
        201,
    )
    assert quote2["status"] == "OPEN"
    assert_money(quote2["unit_price_per_msf"], 65.00)

    order_after = validate_success(api.get_box_order(order["id"], sales_rep_headers))
    assert order_after["status"] == "QUOTED"
    assert order_after["version"] == 3

    quotes, meta = validate_paginated(
        api.list_price_quotes(order["id"], sales_rep_headers)
    )
    assert meta["total_count"] == 2
    by_id = {q["id"]: q for q in quotes}
    assert by_id[quote1["id"]]["status"] == "SUPERSEDED"
    assert by_id[quote2["id"]]["status"] == "OPEN"
    open_quotes = [q for q in quotes if q["status"] == "OPEN"]
    assert len(open_quotes) == 1


def test_stale_expected_order_version_rejected(api, sales_rep_headers):
    """PRD 2.6: "The request body must carry `expected_order_version`, a
    non-optional field holding the client-side last-observed `version` of the
    parent `BoxOrder`. If the order's current `version` no longer equals
    `expected_order_version` — because a prior quote creation already advanced
    it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_quote_create_rejected
    """
    customer, grade = setup_customer_and_grade()
    order = _create_acme_die_cut_order(customer, grade)
    assert order["version"] == 1

    quote1 = quote_order(order, unit_price=50.00)
    assert quote1["status"] == "OPEN"

    # Stale create: still carries the pre-first-quote version (1)
    stale = api.create_price_quote(
        order["id"],
        create_price_quote_payload(1, unit_price_per_msf=55.00),
        sales_rep_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    order_now = validate_success(api.get_box_order(order["id"], sales_rep_headers))
    assert order_now["version"] == 2

    # Retry with the current version succeeds and supersedes the first quote
    quote2 = validate_success(
        api.create_price_quote(
            order["id"],
            create_price_quote_payload(
                order_now["version"], unit_price_per_msf=55.00
            ),
            sales_rep_headers,
        ),
        201,
    )
    quotes, meta = validate_paginated(
        api.list_price_quotes(order["id"], sales_rep_headers)
    )
    assert meta["total_count"] == 2  # the stale create persisted nothing
    by_id = {q["id"]: q for q in quotes}
    assert by_id[quote2["id"]]["status"] == "OPEN"
    assert_money(by_id[quote2["id"]]["unit_price_per_msf"], 55.00)
    assert by_id[quote1["id"]]["status"] == "SUPERSEDED"


def test_credit_limit_equality_passes_then_exceeds(api, sales_rep_headers):
    """PRD 3.2: "the customer's `credit_exposure_dollars` plus the quote's
    `quote_total_dollars` must not exceed the customer's
    `credit_limit_dollars`, with equality allowed (otherwise
    `ERR_CREDIT_LIMIT_EXCEEDED`)".

    Design: Corner/validations/credit_limit_exact_equality_then_exceeded
    """
    customer = create_customer(
        name="Edge Credit", city="Fresno", miles=120.0, credit_limit=1284.12
    )
    grade = create_grade()
    order1 = _create_acme_die_cut_order(customer, grade)
    quote1 = quote_order(order1, unit_price=60.00)
    assert_money(quote1["quote_total_dollars"], 1284.12)

    order2 = create_draft_order(
        customer["id"],
        grade["id"],
        routing_type="SLOTTED",
        quantity=1000,
        blank_width_in=24.0,
        blank_length_in=20.0,
        min_ect_required=30,
        ink_colors=[],
    )
    quote2 = quote_order(order2, unit_price=50.00)
    assert_money(quote2["quote_total_dollars"], 226.67)

    accepted = validate_success(
        api.accept_price_quote(quote1["id"], sales_rep_headers)
    )
    assert accepted["status"] == "ACCEPTED"  # 0 + 1284.12 <= 1284.12

    over = api.accept_price_quote(quote2["id"], sales_rep_headers)
    validate_error(over, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, expected_status=422)

    quotes, _ = validate_paginated(
        api.list_price_quotes(order2["id"], sales_rep_headers)
    )
    assert quotes[0]["status"] == "OPEN"
    order2_after = validate_success(api.get_box_order(order2["id"], sales_rep_headers))
    assert order2_after["status"] == "QUOTED"


def test_quote_expiry_against_logical_clock(api, sales_rep_headers,
                                            plant_admin_headers):
    """PRD 3.2: "the logical clock's current date must be on or before the
    quote's `expires_on` — a later date flips the quote to `EXPIRED`, increments
    the quote's `version`, and rejects the request with `ERR_QUOTE_EXPIRED`".
    PRD 2.4: "Date-sensitive behavior never reads the wall clock. A logical
    clock governs quote expiry and any other date comparison, and before any
    administrator call the logical clock reads exactly 2026-08-01T00:00:00Z."

    Design: Corner/validations/quote_expired_accept_marks_expired
    """
    customer, grade = setup_customer_and_grade()
    order1 = create_draft_order(
        customer["id"], grade["id"], routing_type="SLOTTED", quantity=100,
        blank_width_in=24.0, blank_length_in=20.0, min_ect_required=30,
        ink_colors=[],
    )
    quote1 = quote_order(order1, unit_price=50.00)
    # Default clock 2026-08-01 is on/before expires_on 2026-12-31
    accepted = validate_success(
        api.accept_price_quote(quote1["id"], sales_rep_headers)
    )
    assert accepted["status"] == "ACCEPTED"

    order2 = create_draft_order(
        customer["id"], grade["id"], routing_type="SLOTTED", quantity=100,
        blank_width_in=24.0, blank_length_in=20.0, min_ect_required=30,
        ink_colors=[],
    )
    quote2 = quote_order(order2, unit_price=50.00)

    validate_success(
        api.set_current_utc(
            create_clock_payload("2027-01-02T00:00:00Z"), plant_admin_headers
        )
    )
    expired = api.accept_price_quote(quote2["id"], sales_rep_headers)
    validate_error(expired, ApiErrorId.ERR_QUOTE_EXPIRED, expected_status=409)

    quotes, _ = validate_paginated(
        api.list_price_quotes(order2["id"], sales_rep_headers)
    )
    assert quotes[0]["status"] == "EXPIRED"
    order2_after = validate_success(api.get_box_order(order2["id"], sales_rep_headers))
    assert order2_after["status"] == "QUOTED"


def test_discontinued_grade_blocks_create_and_accept(api, sales_rep_headers,
                                                     plant_admin_headers):
    """PRD 3.1: "Existing orders are unaffected, but from that moment any new
    order creation or quote acceptance that references the grade fails with
    `ERR_GRADE_DISCONTINUED` — the grade must be `ACTIVE` at both of those two
    moments, and only those two."

    Design: Corner/validations/grade_discontinued_blocks_order_create_and_quote_accept
    """
    customer = create_customer()
    grade_32 = create_grade()
    validate_success(
        api.discontinue_board_grade(grade_32["id"], plant_admin_headers)
    )
    res = api.create_box_order(
        create_box_order_payload(
            customer["id"],
            grade_32["id"],
            routing_type="SLOTTED",
            quantity=100,
            blank_width_in=24.0,
            blank_length_in=20.0,
            min_ect_required=30,
            ink_colors=[],
        ),
        sales_rep_headers,
    )
    validate_error(res, ApiErrorId.ERR_GRADE_DISCONTINUED, expected_status=422)

    grade_44 = create_grade_44bc()
    order2 = create_draft_order(
        customer["id"],
        grade_44["id"],
        routing_type="SLOTTED",
        quantity=100,
        blank_width_in=24.0,
        blank_length_in=20.0,
        min_ect_required=40,
        ink_colors=[],
    )
    quote2 = quote_order(order2, unit_price=50.00)
    validate_success(
        api.discontinue_board_grade(grade_44["id"], plant_admin_headers)
    )
    res2 = api.accept_price_quote(quote2["id"], sales_rep_headers)
    validate_error(res2, ApiErrorId.ERR_GRADE_DISCONTINUED, expected_status=422)

    quotes, _ = validate_paginated(
        api.list_price_quotes(order2["id"], sales_rep_headers)
    )
    assert quotes[0]["status"] == "OPEN"
    order2_after = validate_success(api.get_box_order(order2["id"], sales_rep_headers))
    assert order2_after["status"] == "QUOTED"


def test_cancel_invoiced_order_rejected(api, sales_rep_headers):
    """PRD 3.6: "An order can be cancelled by a `SalesRep` from any state in
    the cancellable set — `DRAFT`, `QUOTED`, `ACCEPTED`, `SCHEDULED`,
    `AWAITING_CONVERTING`, `DIE_CUT_QUEUED`, or `SLOTTED_QUEUED` (a
    `CONVERTING`, `PRODUCED`, `INVOICED`, or already-`CANCELLED` order rejects
    with `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/cancel_invoiced_order_rejected
    """
    scenario = setup_invoiced_order_scenario(produced_qty=2100)
    order = scenario["order"]
    res = api.cancel_box_order(order["id"], sales_rep_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_box_order(order["id"], sales_rep_headers))
    assert after["status"] == "INVOICED"


def test_immediate_read_after_write_consistency(api, sales_rep_headers,
                                                production_planner_headers):
    """PRD 2.8: "None of these are writable by clients; each is recomputed by
    the server whenever an operation that feeds it commits."
    PRD 3.4: "cancelled runs and bookings contribute nothing, and the rollup
    recomputes on every run or booking create, start, complete, or cancel."

    Design: Corner/consistency_model/immediate_read_after_write_consistency
    """
    customer, grade = setup_customer_and_grade()
    order = _create_acme_die_cut_order(customer, grade)
    quote_order(order, unit_price=50.00)
    read_back = validate_success(api.get_box_order(order["id"], sales_rep_headers))
    assert read_back["status"] == "QUOTED"
    assert read_back["version"] == 2

    shift = create_work_shift(machine_code="CORRUGATOR")
    create_corrugator_run(shift["id"], grade["id"], start_minute=480, end_minute=720)
    shift_after = validate_success(
        api.get_work_shift(shift["id"], production_planner_headers)
    )
    assert shift_after["scheduled_minutes"] == 240
    assert shift_after["available_minutes"] == 240
