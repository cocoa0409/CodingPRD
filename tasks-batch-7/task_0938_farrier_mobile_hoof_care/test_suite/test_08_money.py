"""Money: pricing one visit, splitting one stop and settling one client."""

from test_helpers import *  # noqa: F401,F403


def test_invoice_lines_subresource_lists_an_append_only_labor_line(api, billing):
    """PRD §3.9: "There is one `LABOR` line per `PERFORMED` service line, carrying
    that line's `limb` and `service_type`, a `quantity` of 1, a `unit_amount_cents`
    and an `amount_cents` both equal to the line's `labor_cents`."
    PRD §3.9: "Only `PRODUCT` and `PAD` lines carry `taxable` true; every other kind
    carries `taxable` false."
    PRD §2.4: "The sole exception is `InvoiceLine`: an invoice line is immutable
    once written, so it carries only `id` and `created_at` — it has neither
    `updated_at` nor `version`, and an implementation must not emit those two keys
    on an invoice line."

    Design: Corner/entities/corner_invoice_lines_subresource_lists_an_append_only_labor_line
    """
    world = setup_reference(clock="2026-05-06T08:00:00Z", with_sku=False)
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    setup_completed_visit(
        world, limbs=("LF",), service_type="TRIM", scheduled_date="2026-05-06"
    )
    invoice = sole_invoice(world["appointment"]["id"])

    rows, _meta = validate_paginated(api.list_invoice_lines(invoice["id"], billing))

    assert len(rows) == 1, "one LABOR line and nothing else on a bare trim"
    line = rows[0]
    assert_invoice_line(line)
    assert line["line_kind"] == "LABOR"
    assert line["limb"] == "LF"
    assert line["service_type"] == "TRIM"
    assert line["quantity"] == 1
    assert line["unit_amount_cents"] == 2200
    assert line["amount_cents"] == 2200
    assert line["taxable"] is False
    assert invoice["labor_subtotal_cents"] == 2200
    assert invoice["total_cents"] == 2200
    assert_invoice_invariants(invoice)


def test_effective_rate_card_never_selects_a_draft_card(api):
    """PRD §3.3: "Selection is chronological and deliberately admits superseded
    cards. Given a service date, the candidates are every card whose `status` is
    `ACTIVE` or `SUPERSEDED` and whose `effective_from` is on or before that date;
    `DRAFT` cards are never candidates."
    PRD §3.3: "A card is minted `DRAFT` and prices nothing."

    Design: Corner/calculations/corner_effective_rate_card_never_selects_a_draft_card
    """
    world = setup_reference(clock="2026-05-06T08:00:00Z", with_sku=False)
    never_activated = create_rate_card(
        label="never activated",
        effective_from="2026-01-15",
        price_trim_cents=4400,
        price_reset_cents=7600,
        price_new_shoes_cents=13000,
        price_corrective_cents=19600,
        price_glue_on_cents=16800,
        pad_price_cents=3200,
    )
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    setup_completed_visit(
        world, limbs=("LF",), service_type="TRIM", scheduled_date="2026-05-06"
    )

    assert read_rate_card(never_activated["id"])["status"] == "DRAFT"
    appointment = read_appointment(world["appointment"]["id"])
    assert appointment["rate_card_id"] == world["rate_card"]["id"]
    invoice = sole_invoice(appointment["id"])
    assert invoice["labor_subtotal_cents"] == 2200, "priced off the ACTIVE card"
    assert invoice["total_cents"] == 2200


def test_tax_exempt_client_pays_no_product_tax(api):
    """PRD §3.9: "When the client's `tax_exempt` is false, it is
    `taxable_product_base_cents` multiplied by 725 basis points
    (`PRODUCT_TAX_RATE_BP`), divided by 10000, rounded half up. When `tax_exempt` is
    true, `tax_cents` is 0 while `taxable_product_base_cents` keeps the value
    computed at step 8, so the total falls by exactly the tax that would otherwise
    have been charged."
    PRD §3.9: "`taxable_product_base_cents` is `product_subtotal_cents` minus
    `loyalty_discount_product_cents`."

    Design: Corner/calculations/corner_tax_exempt_client_pays_no_product_tax
    """
    world = setup_reference(
        clock="2026-05-06T08:00:00Z", client={"tax_exempt": True}
    )
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    setup_completed_visit(
        world, service_type="NEW_SHOES", use_sku=True, scheduled_date="2026-05-06"
    )

    invoice = sole_invoice(world["appointment"]["id"])
    # 4 limbs x 6500 labour; 2 pairs x 5600 product; no loyalty at one visit.
    assert invoice["labor_subtotal_cents"] == 26000
    assert invoice["product_subtotal_cents"] == 11200
    assert invoice["taxable_product_base_cents"] == 11200
    assert invoice["tax_cents"] == 0
    assert invoice["total_cents"] == 37200
    assert_invoice_invariants(invoice)


def test_payment_with_a_stale_client_version_is_refused(api, billing):
    """PRD §2.8: "Applying a payment requires `expected_client_version` matching the
    current `version` of the `Client`. A mismatch is `ERR_STALE_CLIENT_VERSION`
    (HTTP 412)."
    PRD §3.9: "A deposit carries an `amount_cents` that must be strictly positive;
    it raises the client's `deposit_balance_cents` by that amount, re-derives the
    client's `billing_standing`, and increments the client's `version` by 1."

    Design: Corner/cross_cutting_layers/corner_occ_payment_with_a_stale_client_version_returns_412
    """
    barn = create_barn()
    client = create_client(barn["id"])
    version_at_creation = client["version"]
    post_deposit(client["id"], 5000)

    response = api.apply_payment(
        client["id"],
        {"amount_cents": 1000, "expected_client_version": version_at_creation},
        billing,
    )

    validate_error(response, ApiErrorId.ERR_STALE_CLIENT_VERSION.value)
    assert response.status_code == 412
    after = read_client(client["id"])
    assert after["credit_balance_cents"] == 0
    assert after["deposit_balance_cents"] == 5000


# ---------------------------------------------------------------------------
# The estimate prices off the scheduled date, the invoice off the completion date
# ---------------------------------------------------------------------------


def _setup_price_uplift_world():
    """A 2026-05-04 visit estimated under the 6500-cent card, then completed on
    2026-05-06 once the 7000-cent card of 2026-05-05 has taken effect."""
    world = setup_reference()
    world["uplift"] = create_rate_card(
        label="2026 May uplift",
        effective_from="2026-05-05",
        price_trim_cents=2400,
        price_reset_cents=4000,
        price_new_shoes_cents=7000,
        price_corrective_cents=10400,
        price_glue_on_cents=8900,
        pad_price_cents=1700,
        trip_fee_zone_a_cents=4800,
        trip_fee_zone_b_cents=7400,
        trip_fee_zone_c_cents=11600,
        supersedes_rate_card_id=world["rate_card"]["id"],
    )
    activate_rate_card(world["uplift"]["id"])
    setup_route_with_stop(world, route_date="2026-05-04", planned_start_minute=480)
    appointment, lines = setup_scheduled_visit(
        world, service_type="NEW_SHOES", use_sku=True, scheduled_date="2026-05-04"
    )
    world["estimate_at_attach"] = read_appointment(appointment["id"])[
        "estimated_total_cents"
    ]
    plan_route(world["route"]["id"])
    dispatch_route(world["route"]["id"])
    set_clock("2026-05-06T08:00:00Z")
    arrive_stop(world["stop"]["id"], world["farrier"]["id"])
    start_visit(appointment["id"], world["farrier"]["id"])
    complete_visit(
        appointment["id"], [line["id"] for line in lines], world["farrier"]["id"]
    )
    return world


def test_the_estimate_prices_off_the_scheduled_dates_card(api):
    """PRD §3.9: "The **estimate** is a forward look, refreshed into
    `estimated_total_cents` on every service-line change and on attachment. It
    prices the appointment's `PLANNED` lines off the rate card effective on the
    appointment's `scheduled_date`."
    PRD §3.3: "The service date is never the invoice's `issued_on` and never the
    logical clock date. For a finalised visit it is the appointment's
    `completed_on`; for an estimate it is the appointment's `scheduled_date`."
    PRD §3.7: "the appointment's `completed_on` is set to the logical clock date and
    its `rate_card_id` is pinned by selecting the effective card for that completion
    date"

    Design: Difficulty/dual_variant_calc/visit_price_final_prices_off_completion_date_not_scheduled_date
    """
    world = _setup_price_uplift_world()

    # 4 limbs x 6500 from the 2026-01-01 card + 2 pairs x 5600 = 37200.
    assert world["estimate_at_attach"] == 37200
    appointment = read_appointment(world["appointment"]["id"])
    assert_same_date(appointment["completed_on"], "2026-05-06")
    assert appointment["rate_card_id"] == world["uplift"]["id"], (
        "the completion date falls under the uplift card"
    )
    assert read_rate_card(world["rate_card"]["id"])["status"] == "SUPERSEDED"


def test_the_invoice_prices_off_the_completion_dates_card(api):
    """PRD §3.9: "The **final** price is the invoice, built at completion off the
    rate card effective on the appointment's `completed_on`. A card that took effect
    between the scheduled date and the completion date changes the answer, and the
    invoice — not the estimate — is what the client owes."
    PRD §3.9: "**Products.** `product_subtotal_cents` is the sum, over the
    appointment's reservations whose `status` is `COMMITTED`, of that reservation's
    `pairs` multiplied by its SKU's `price_cents_per_pair`, plus the rate card's
    `pad_price_cents` multiplied by the number of `PERFORMED` lines whose `with_pad`
    is true."

    Design: Difficulty/dual_variant_calc/visit_price_final_prices_off_completion_date_not_scheduled_date
    """
    world = _setup_price_uplift_world()

    invoice = sole_invoice(world["appointment"]["id"])
    assert invoice["labor_subtotal_cents"] == 28000, "4 limbs x 7000"
    assert invoice["product_subtotal_cents"] == 11200, "2 pairs x 5600"
    assert invoice["tax_cents"] == apply_basis_points(11200, PRODUCT_TAX_RATE_BP)
    assert invoice["tax_cents"] == 812
    assert invoice["total_cents"] == 40012
    assert_invoice_invariants(invoice)


# ---------------------------------------------------------------------------
# The sedation surcharge rounds per line and only then sums
# ---------------------------------------------------------------------------


def _setup_sedated_odd_price_world():
    world = setup_reference(
        horse={"name": "Nervy", "requires_sedation": True},
        rate_card={"price_new_shoes_cents": 6524},
    )
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    appointment, lines = setup_scheduled_visit(
        world,
        service_type="NEW_SHOES",
        use_sku=True,
        scheduled_date="2026-05-06",
        appointment_overrides={"vet_present": True},
    )
    plan_route(world["route"]["id"])
    dispatch_route(world["route"]["id"])
    set_clock("2026-05-06T08:00:00Z")
    arrive_stop(world["stop"]["id"], world["farrier"]["id"])
    start_visit(appointment["id"], world["farrier"]["id"])
    complete_visit(
        appointment["id"], [line["id"] for line in lines], world["farrier"]["id"]
    )
    return world


def test_each_line_rounds_its_own_sedation_surcharge(api):
    """PRD §3.9: "When the horse's `requires_sedation` is true, a surcharge of 1250
    basis points (`SEDATION_LABOR_SURCHARGE_BP`) of that base is added — computed as
    the base multiplied by 1250, divided by 10000, and rounded half up **for this
    line alone**; when it is false the surcharge is 0."
    PRD §3.9: "**Rounding order is pinned and is the commonest way to get this
    wrong.** Each line's sedation surcharge is rounded on its own, and the
    already-rounded line amounts are then summed into `labor_subtotal_cents`,
    counting only lines whose `status` is `PERFORMED`."

    Design: Difficulty/combinatorial_formula/labor_subtotal_rounds_the_sedation_surcharge_per_line_then_sums
    """
    world = _setup_sedated_odd_price_world()

    # 6524 * 1250 / 10000 = 815.5, half up = 816, so each line is 7340.
    per_line = 6524 + apply_basis_points(6524, SEDATION_LABOR_SURCHARGE_BP)
    assert per_line == 7340
    lines = service_lines_for(world["appointment"]["id"])
    assert len(lines) == 4
    for line in lines:
        assert line["status"] == "PERFORMED"
        assert line["labor_cents"] == 7340

    invoice = sole_invoice(world["appointment"]["id"])
    assert invoice["labor_subtotal_cents"] == 4 * 7340
    assert invoice["labor_subtotal_cents"] == 29360
    # Rounding one combined surcharge would have given 26096 + 3262 = 29358.
    assert invoice["labor_subtotal_cents"] != 29358


def test_the_sedated_visit_totals_up_from_the_rounded_line_amounts(api):
    """PRD §3.9: "`total_cents` is `labor_net_cents` plus
    `taxable_product_base_cents` plus `trip_fee_share_cents` plus `fee_cents` plus
    `tax_cents`."
    PRD §3.5: "For a horse that requires sedation, the handling term is multiplied
    by 15000 basis points (`SEDATION_HANDLING_MULTIPLIER_BP`), divided by 10000 and
    rounded half up, which turns 6 minutes into 9, and a further 15 minutes
    (`SEDATION_EXTRA_MINUTES`) of sedation time is added on top — 18 minutes more
    than the unsedated case in total."

    Design: Difficulty/combinatorial_formula/labor_subtotal_rounds_the_sedation_surcharge_per_line_then_sums
    """
    world = _setup_sedated_odd_price_world()

    appointment = read_appointment(world["appointment"]["id"])
    assert appointment["service_minutes"] == expected_service_minutes(
        ["NEW_SHOES"] * 4, True
    )
    assert appointment["service_minutes"] == 104
    invoice = sole_invoice(appointment["id"])
    assert invoice["product_subtotal_cents"] == 11200
    assert invoice["tax_cents"] == 812
    assert invoice["total_cents"] == 41372
    assert_invoice_invariants(invoice)


# ---------------------------------------------------------------------------
# Loyalty is taken on both legs, split back, and only the product leg is taxed
# ---------------------------------------------------------------------------


def _setup_twelfth_visit_world():
    world = setup_reference(
        clock="2026-05-06T08:00:00Z",
        client={"opening_completed_visit_count": 11},
        rate_card={"price_new_shoes_cents": 6537},
    )
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)
    setup_completed_visit(
        world, service_type="NEW_SHOES", use_sku=True, scheduled_date="2026-05-06"
    )
    return world


def test_loyalty_discount_is_taken_on_both_legs_and_split_by_the_product_share(api):
    """PRD §3.9: "The loyalty base is labour-after-multi-horse plus
    `product_subtotal_cents`. The rate is chosen from the client's
    `completed_visit_count` **as it stands after this visit has been counted**: at
    30 visits or more (`LOYALTY_PREMIER_THRESHOLD_VISITS`) the rate is 600 basis
    points (`LOYALTY_PREMIER_BP`); at 12 visits or more (`LOYALTY_THRESHOLD_VISITS`)
    but fewer than 30 the rate is 300 basis points (`LOYALTY_STANDARD_BP`); below 12
    the rate is 0."
    PRD §3.9: "Otherwise it is `loyalty_discount_cents` multiplied by
    `product_subtotal_cents`, divided by the loyalty base, rounded half up.
    `loyalty_discount_labor_cents` is then `loyalty_discount_cents` minus
    `loyalty_discount_product_cents` — the product leg is the rounded one and the
    labour leg absorbs whatever remainder is left, which is what makes the
    loyalty-split invariant hold exactly."

    Design: Difficulty/combinatorial_formula/loyalty_split_then_taxable_base_then_tax_evaluation_order
    """
    world = _setup_twelfth_visit_world()

    assert read_client(world["client"]["id"])["completed_visit_count"] == 12
    invoice = sole_invoice(world["appointment"]["id"])
    assert invoice["labor_subtotal_cents"] == 26148, "4 limbs x 6537, no sedation"
    assert invoice["product_subtotal_cents"] == 11200
    assert invoice["multi_horse_discount_cents"] == 0, "the stop has not closed out"
    # Loyalty base 26148 + 11200 = 37348 at 300bp = 1120.44 -> 1120.
    assert invoice["loyalty_discount_cents"] == apply_basis_points(
        37348, LOYALTY_STANDARD_BP
    )
    assert invoice["loyalty_discount_cents"] == 1120
    # Product leg 1120 * 11200 / 37348 = 335.87 -> 336; labour leg takes the rest.
    assert invoice["loyalty_discount_product_cents"] == round_half_up(1120 * 11200, 37348)
    assert invoice["loyalty_discount_product_cents"] == 336
    assert invoice["loyalty_discount_labor_cents"] == 784
    assert_loyalty_split(invoice)


def test_only_the_product_leg_of_the_loyalty_discount_reduces_the_taxable_base(api):
    """PRD §3.9: "`labor_net_cents` is labour-after-multi-horse minus
    `loyalty_discount_labor_cents`."
    PRD §3.9: "`taxable_product_base_cents` is `product_subtotal_cents` minus
    `loyalty_discount_product_cents`."
    PRD §3.9: "`tax_cents`. When the client's `tax_exempt` is false, it is
    `taxable_product_base_cents` multiplied by 725 basis points
    (`PRODUCT_TAX_RATE_BP`), divided by 10000, rounded half up."

    Design: Difficulty/combinatorial_formula/loyalty_split_then_taxable_base_then_tax_evaluation_order
    """
    world = _setup_twelfth_visit_world()

    invoice = sole_invoice(world["appointment"]["id"])
    assert invoice["labor_net_cents"] == 26148 - 784
    assert invoice["labor_net_cents"] == 25364
    assert invoice["taxable_product_base_cents"] == 11200 - 336
    assert invoice["taxable_product_base_cents"] == 10864
    # 10864 * 725 / 10000 = 787.64 -> 788.
    assert invoice["tax_cents"] == apply_basis_points(10864, PRODUCT_TAX_RATE_BP)
    assert invoice["tax_cents"] == 788
    assert invoice["total_cents"] == 25364 + 10864 + 788
    assert invoice["total_cents"] == 37016
    assert_invoice_invariants(invoice)


# ---------------------------------------------------------------------------
# One stop's trip fee splits across its billable horses to the cent
# ---------------------------------------------------------------------------


def _setup_three_completed_visits_at_one_zone_b_stop():
    world = setup_reference(
        clock="2026-05-06T08:00:00Z",
        barn={"name": "Hollow Creek", "zone": "B"},
        with_sku=False,
    )
    setup_route_with_stop(world, route_date="2026-05-06", planned_start_minute=480)

    horses = [(world["horse"], world["limbs"])]
    for name in ("Dusty", "Echo"):
        horses.append(add_horse(world, name=name))

    visits = []
    for horse, limb_map in horses:
        appointment = create_appointment(horse["id"], "2026-05-06")
        lines = add_lines(
            appointment["id"], lines_for_limbs(ALL_LIMBS, limb_map, "TRIM")
        )
        attach(world["stop"]["id"], appointment["id"], world["route"]["id"])
        visits.append((appointment, lines))

    dispatch_and_arrive(world)
    for appointment, lines in visits:
        start_visit(appointment["id"], world["farrier"]["id"])
        complete_visit(
            appointment["id"], [line["id"] for line in lines], world["farrier"]["id"]
        )
    world["visits"] = visits
    return world


def test_trip_fee_shares_sum_back_to_the_stops_fee_to_the_cent(api):
    """PRD §3.9: "Otherwise the stop's `trip_fee_cents` is the card's zone fee, its
    `billable_horse_count` is the size of the billable set, the base share is the
    fee divided by that count and rounded **down**, the remainder is the fee minus
    the base share multiplied by the count, and the **first** appointments in the
    sorted order — as many as the remainder — each receive one cent more than the
    base share while the rest receive the base share exactly."
    PRD §2.9: "**Trip-fee split.** For a stop whose `status` is `COMPLETED` and
    whose `billable_horse_count` is greater than zero, the sum of
    `trip_fee_share_cents` over the invoices of the appointments attached to that
    stop whose `status` is `COMPLETED`, `NO_SHOW` or `CANCELLED_ONSITE` equals that
    stop's `trip_fee_cents` exactly."

    Design: Difficulty/compensating_invariant/trip_fee_shares_always_sum_back_to_the_stop_fee
    """
    world = _setup_three_completed_visits_at_one_zone_b_stop()
    for appointment, _lines in world["visits"]:
        invoice = sole_invoice(appointment["id"])
        assert invoice["trip_fee_share_cents"] == 0
        assert invoice["multi_horse_discount_cents"] == 0
        assert invoice["total_cents"] == 8800, "4 limbs x 2200 with nothing else yet"

    stop = validate_success(
        api.complete_route_stop(
            world["stop"]["id"], make_farrier_headers(world["farrier"]["id"])
        )
    )

    assert_route_stop(stop)
    assert stop["trip_fee_cents"] == 7000, "the zone B fee of the effective card"
    assert stop["billable_horse_count"] == 3
    invoices = [sole_invoice(appointment["id"]) for appointment, _l in world["visits"]]
    # 7000 // 3 = 2333 with a remainder of 1, which goes to the first appointment.
    assert invoices[0]["trip_fee_share_cents"] == 2334
    assert invoices[1]["trip_fee_share_cents"] == 2333
    assert invoices[2]["trip_fee_share_cents"] == 2333
    assert_trip_fee_split(stop, invoices)


def test_stop_completion_rebuilds_each_invoice_with_the_multi_horse_discount(api):
    """PRD §3.9: "When the appointment is attached to a stop whose
    `billable_horse_count` is at least 3 (`MULTI_HORSE_DISCOUNT_MIN_HORSES`), this
    is `labor_subtotal_cents` multiplied by 500 basis points
    (`MULTI_HORSE_DISCOUNT_BP`), divided by 10000 and rounded half up; otherwise it
    is 0."
    PRD §3.9: "Each billable appointment's invoice receives its
    `trip_fee_share_cents` and a `TRIP_FEE` line, and each affected invoice is then
    rebuilt from step 1 with the new `billable_horse_count` in place."

    Design: Difficulty/compensating_invariant/trip_fee_shares_always_sum_back_to_the_stop_fee
    """
    world = _setup_three_completed_visits_at_one_zone_b_stop()

    complete_stop(world["stop"]["id"], world["farrier"]["id"])

    invoices = [sole_invoice(appointment["id"]) for appointment, _l in world["visits"]]
    for invoice in invoices:
        # 8800 * 500 / 10000 = 440 exactly; labour after the discount is 8360.
        assert invoice["multi_horse_discount_cents"] == apply_basis_points(
            8800, MULTI_HORSE_DISCOUNT_BP
        )
        assert invoice["multi_horse_discount_cents"] == 440
        assert invoice["labor_net_cents"] == 8360
        assert_invoice_invariants(invoice)
    assert invoices[0]["total_cents"] == 8360 + 2334
    assert invoices[0]["total_cents"] == 10694
    assert invoices[1]["total_cents"] == 10693
    assert invoices[2]["total_cents"] == 10693
