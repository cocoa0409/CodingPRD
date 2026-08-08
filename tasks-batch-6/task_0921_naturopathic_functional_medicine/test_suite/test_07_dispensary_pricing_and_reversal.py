"""The dispensary: lot selection, pricing, stock conservation and reversal."""

from test_helpers import (
    ApiErrorId,
    add_protocol_item,
    assert_dispense,
    assert_lot_conservation,
    assert_product_lot,
    create_product,
    dispense_units,
    draft_protocol,
    issue_protocol,
    make_director_headers,
    make_nd_headers,
    make_tech_headers,
    protocol_version,
    read_patient,
    receive_lot,
    register_director,
    register_tech,
    setup_active_protocol,
    setup_dispensed_line,
    setup_protocol_ready_patient,
    validate_error,
    validate_paginated,
    validate_success,
)


def _member_line_with_stock(api):
    """CORE member, one ACTIVE line, one lot of 20 units at 4995 retail."""
    return setup_active_protocol(api, membership_tier="CORE")


def test_member_discount_is_rounded_per_unit_before_multiplication(api):
    """PRD §2.8: "For dispensary pricing, the discounted price is rounded to a
    whole cent **per unit**, and only then multiplied by the dispensed quantity.
    Multiplying the raw discounted amount by the quantity and rounding the line
    total once is explicitly not the rule; the two procedures disagree whenever
    the retail price multiplied by the discount rate leaves a fractional cent."
    PRD §3.8: "Otherwise, if the patient holds a membership in status `ACTIVE`,
    the variant is `MEMBER`: the discount rate is that membership's
    `dispensary_discount_pct`, which is 0.05 on `FOUNDATION`, 0.10 on `CORE` and
    0.20 on `PREMIER`."

    Design: Difficulty/combinatorial_formula/dispense_rounds_per_unit_before_multiplying_by_quantity
    """
    ctx = _member_line_with_stock(api)
    dispense = dispense_units(
        api,
        ctx["tech"]["id"],
        ctx["protocol"]["id"],
        ctx["item"]["id"],
        quantity=3,
        nd_id=ctx["nd"]["id"],
    )

    assert_dispense(dispense)
    assert dispense["pricing_variant"] == "MEMBER"
    assert dispense["unit_price_cents"] == 4496
    assert dispense["total_price_cents"] == 13488


def test_the_per_unit_rounded_line_lands_on_the_lot_and_the_patient_ledger(api):
    """PRD §3.8: "A successful fill decrements the source lot's
    `quantity_on_hand` by the dispensed `quantity`, recomputes the owning
    product's `stock_on_hand` across its eligible lots, adds `total_price_cents`
    to the patient's `cash_charged_total_cents`, and increments the
    **protocol's** `version` by 1."
    PRD §3.8: "The `total_price_cents` is then `unit_price_cents` multiplied by
    `quantity`, and the ordering matters: the per-unit price is rounded to a
    whole cent **before** multiplication, never after."

    Design: Difficulty/combinatorial_formula/dispense_rounds_per_unit_before_multiplying_by_quantity
    """
    ctx = _member_line_with_stock(api)
    dispense = dispense_units(
        api,
        ctx["tech"]["id"],
        ctx["protocol"]["id"],
        ctx["item"]["id"],
        quantity=3,
        nd_id=ctx["nd"]["id"],
    )

    assert dispense["product_lot_id"] == ctx["lot"]["id"]

    lot = validate_success(
        api.get_product_lot(ctx["lot"]["id"], make_nd_headers(ctx["nd"]["id"]))
    )
    assert lot["quantity_on_hand"] == 17
    assert_lot_conservation(lot, [dispense["quantity"]])

    product = validate_success(
        api.get_dispensary_product(ctx["product"]["id"], make_nd_headers(ctx["nd"]["id"]))
    )
    assert product["stock_on_hand"] == 17

    assert read_patient(api, ctx["patient"]["id"])["cash_charged_total_cents"] == 13488


def test_the_practitioner_cost_floor_pins_a_deep_premier_discount(api):
    """PRD §3.8: "For both `MEMBER` and `RETAIL`, the raw unit price is the
    product's `retail_price_cents` reduced by the discount rate, that raw figure
    is rounded half up to a whole cent, and the `unit_price_cents` is the larger
    of that rounded figure and the product's `practitioner_cost_cents` — the
    practice never sells below acquisition cost, so a deep discount on a
    thin-margin product silently lands on the floor."

    Design: Corner/calculations/practitioner_cost_floor_binds_on_a_premier_discount
    """
    ctx = setup_active_protocol(
        api,
        membership_tier="PREMIER",
        product_overrides={
            "sku": "OMEGA-3-HI",
            "name": "High-potency omega 3",
            "supplement_class": "VITAMIN_MINERAL",
            "retail_price_cents": 4995,
            "practitioner_cost_cents": 4200,
        },
        lot_overrides={"lot_code": "L-OM-1", "quantity_initial": 10, "expiry_date": "2027-01-31"},
        item_overrides={"dose_amount_mg": 1000, "frequency_per_day": 2, "titration_interval_days": 30},
        protocol_overrides={"title": "Lipid support", "symptom_score_baseline": 20},
    )

    dispense = dispense_units(
        api,
        ctx["tech"]["id"],
        ctx["protocol"]["id"],
        ctx["item"]["id"],
        quantity=2,
        nd_id=ctx["nd"]["id"],
        product_lot_id=ctx["lot"]["id"],
    )

    assert dispense["pricing_variant"] == "MEMBER"
    assert dispense["unit_price_cents"] == 4200
    assert dispense["total_price_cents"] == 8400

    lot = validate_success(
        api.get_product_lot(ctx["lot"]["id"], make_nd_headers(ctx["nd"]["id"]))
    )
    assert lot["quantity_on_hand"] == 8
    product = validate_success(
        api.get_dispensary_product(ctx["product"]["id"], make_nd_headers(ctx["nd"]["id"]))
    )
    assert product["stock_on_hand"] == 8


def test_an_empty_candidate_pool_falls_back_to_no_eligible_lot(api):
    """PRD §3.8: "The candidate pool is every lot of the line's product that is
    not quarantined, not expired, and holds at least the requested `quantity` on
    hand."
    PRD §3.8: "If the pool is empty, the request is refused with
    `ERR_NO_ELIGIBLE_LOT`."

    Design: Difficulty/boundary_precision_check/fefo_pool_empty_when_every_lot_is_quarantined_or_expired
    """
    ctx = setup_active_protocol(
        api,
        with_lot=False,
        lot_overrides=None,
    )
    nd, tech, product = ctx["nd"], ctx["tech"], ctx["product"]
    receive_lot(
        api, product["id"], lot_code="L-QUAR", quantity_initial=25,
        expiry_date="2027-01-31", is_quarantined=True,
    )
    receive_lot(
        api, product["id"], lot_code="L-EXP", quantity_initial=25,
        expiry_date="2026-05-01",
    )

    version = protocol_version(api, ctx["protocol"]["id"], nd["id"])
    response = api.create_dispense(
        {
            "protocol_item_id": ctx["item"]["id"],
            "quantity": 1,
            "expected_protocol_version": version,
        },
        make_tech_headers(tech["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_LOT.value, 409)


def test_quarantined_and_expired_lots_stay_untouched_and_out_of_stock(api):
    """PRD §3.8: "A lot's `is_expired` flag is true once the logical clock's date
    has reached or passed its `expiry_date`, so a lot expiring today is already
    unusable; the flag is materialised whenever the lot is read."
    PRD §3.8: "A product's `stock_on_hand` starts at 0 and is never written
    directly — it is always the sum of `quantity_on_hand` across that product's
    lots that are neither quarantined nor expired."

    Design: Difficulty/boundary_precision_check/fefo_pool_empty_when_every_lot_is_quarantined_or_expired
    """
    ctx = setup_active_protocol(api, with_lot=False)
    nd, tech, product = ctx["nd"], ctx["tech"], ctx["product"]
    quarantined = receive_lot(
        api, product["id"], lot_code="L-QUAR", quantity_initial=25,
        expiry_date="2027-01-31", is_quarantined=True,
    )
    expired = receive_lot(
        api, product["id"], lot_code="L-EXP", quantity_initial=25,
        expiry_date="2026-05-01",
    )

    version = protocol_version(api, ctx["protocol"]["id"], nd["id"])
    validate_error(
        api.create_dispense(
            {
                "protocol_item_id": ctx["item"]["id"],
                "quantity": 1,
                "expected_protocol_version": version,
            },
            make_tech_headers(tech["id"]),
        ),
        ApiErrorId.ERR_NO_ELIGIBLE_LOT.value,
        409,
    )

    quarantined_now = validate_success(
        api.get_product_lot(quarantined["id"], make_nd_headers(nd["id"]))
    )
    expired_now = validate_success(
        api.get_product_lot(expired["id"], make_nd_headers(nd["id"]))
    )
    assert_product_lot(quarantined_now)
    assert quarantined_now["quantity_on_hand"] == 25
    assert expired_now["quantity_on_hand"] == 25
    assert expired_now["is_expired"] is True

    product_now = validate_success(
        api.get_dispensary_product(product["id"], make_nd_headers(nd["id"]))
    )
    assert product_now["stock_on_hand"] == 0


def test_naming_an_expired_or_short_lot_returns_that_lots_own_error(api):
    """PRD §3.8: "When the caller **does** name a `product_lot_id`, the selector
    does not run at all and that lot is checked directly: a quarantined or
    expired lot is refused with `ERR_LOT_EXPIRED`, and a lot holding fewer units
    than requested is refused with `ERR_INSUFFICIENT_STOCK`."

    Design: Corner/errors/explicit_lot_that_is_expired_or_short_returns_its_own_error
    """
    ctx = setup_active_protocol(api, with_lot=False)
    nd, tech, product = ctx["nd"], ctx["tech"], ctx["product"]
    expired = receive_lot(
        api, product["id"], lot_code="L-EXP", quantity_initial=25,
        expiry_date="2026-05-01",
    )
    short = receive_lot(
        api, product["id"], lot_code="L-SHORT", quantity_initial=2,
        expiry_date="2027-01-31",
    )
    version = protocol_version(api, ctx["protocol"]["id"], nd["id"])

    validate_error(
        api.create_dispense(
            {
                "protocol_item_id": ctx["item"]["id"],
                "quantity": 1,
                "expected_protocol_version": version,
                "product_lot_id": expired["id"],
            },
            make_tech_headers(tech["id"]),
        ),
        ApiErrorId.ERR_LOT_EXPIRED.value,
        422,
    )
    validate_error(
        api.create_dispense(
            {
                "protocol_item_id": ctx["item"]["id"],
                "quantity": 5,
                "expected_protocol_version": version,
                "product_lot_id": short["id"],
            },
            make_tech_headers(tech["id"]),
        ),
        ApiErrorId.ERR_INSUFFICIENT_STOCK.value,
        409,
    )

    assert validate_success(
        api.get_product_lot(expired["id"], make_nd_headers(nd["id"]))
    )["quantity_on_hand"] == 25
    assert validate_success(
        api.get_product_lot(short["id"], make_nd_headers(nd["id"]))
    )["quantity_on_hand"] == 2
    assert validate_success(
        api.get_dispensary_product(product["id"], make_nd_headers(nd["id"]))
    )["stock_on_hand"] == 2
    assert read_patient(api, ctx["patient"]["id"])["cash_charged_total_cents"] == 0


def test_reversal_returns_every_unit_to_the_source_lot(api):
    """PRD §2.9: "For any product lot, `quantity_initial` always equals
    `quantity_on_hand` plus the total `quantity` across every dispense drawn
    from that lot whose status is still `DISPENSED`."
    PRD §3.8: "The reversal returns the dispensed `quantity` to the source lot's
    `quantity_on_hand`, recomputes the product's `stock_on_hand` over its
    eligible lots, adds `total_price_cents` to the patient's
    `cash_refunded_total_cents`, restores the lot conservation identity, and
    increments the dispense's `version` by 1."

    Design: Difficulty/compensating_invariant/dispense_reversal_restores_lot_units_with_no_drift
    """
    ctx = setup_dispensed_line(api, quantity=3, membership_tier="CORE")
    nd, tech, lot, dispense = ctx["nd"], ctx["tech"], ctx["lot"], ctx["dispense"]
    assert dispense["total_price_cents"] == 13488

    reversed_dispense = validate_success(
        api.reverse_dispense(
            dispense["id"],
            {"reason": "wrong strength supplied"},
            make_tech_headers(tech["id"]),
        )
    )
    assert reversed_dispense["status"] == "REVERSED"

    restocked = validate_success(api.get_product_lot(lot["id"], make_nd_headers(nd["id"])))
    assert restocked["quantity_on_hand"] == 20
    assert restocked["quantity_initial"] == 20
    assert_lot_conservation(restocked, [])

    product = validate_success(
        api.get_dispensary_product(ctx["product"]["id"], make_nd_headers(nd["id"]))
    )
    assert product["stock_on_hand"] == 20


def test_reversal_grows_the_refunded_counter_and_leaves_the_charged_one_alone(api):
    """PRD §2.8: "`cash_refunded_total_cents` accumulates everything given back —
    cancelled cash lab orders, reversed dispenses and negative membership
    proration."
    PRD §2.9: "Because a reversal leaves the charged figure alone and grows
    `cash_refunded_total_cents` instead, a reversed dispense still contributes
    to the charged total — that is what makes the identity hold across
    reversals."

    Design: Difficulty/compensating_invariant/dispense_reversal_restores_lot_units_with_no_drift
    """
    ctx = setup_dispensed_line(api, quantity=3, membership_tier="CORE")
    tech, dispense = ctx["tech"], ctx["dispense"]

    reversed_dispense = validate_success(
        api.reverse_dispense(
            dispense["id"],
            {"reason": "wrong strength supplied"},
            make_tech_headers(tech["id"]),
        )
    )
    assert reversed_dispense["total_price_cents"] == 13488

    refreshed = read_patient(api, ctx["patient"]["id"])
    assert refreshed["cash_charged_total_cents"] == 13488
    assert refreshed["cash_refunded_total_cents"] == 13488


def test_a_high_value_self_authorised_reversal_is_refused(api):
    """PRD §3.8: "Where the dispense's `total_price_cents` is at or above 20000
    cents, the actor may not be the practitioner named in
    `dispensed_by_practitioner_id` — a high-value reversal needs a second pair
    of hands, and a self-authorised one is refused with
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.8: "Reversal is available to a `ClinicalDirector` or a
    `DispensaryTech`, is never blocked by the clinical write gate, and carries a
    `reason`. A dispense moves `DISPENSED → REVERSED`, recording `reversed_at`,
    storing the text as `reversal_reason`, and recording the acting `X-User-ID`
    as `reversal_authorized_by_user_id`."

    Design: Corner/rbac/dispenser_cannot_reverse_their_own_dispense_above_the_threshold
    """
    ctx = setup_dispensed_line(api, quantity=5)
    nd, tech, lot, dispense = ctx["nd"], ctx["tech"], ctx["lot"], ctx["dispense"]
    director = register_director(api)

    assert dispense["total_price_cents"] == 24975
    assert dispense["pricing_variant"] == "RETAIL"

    refused = api.reverse_dispense(
        dispense["id"], {"reason": "wrong patient"}, make_tech_headers(tech["id"])
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    unchanged = validate_success(api.get_dispense(dispense["id"], make_nd_headers(nd["id"])))
    assert unchanged["status"] == "DISPENSED"
    assert validate_success(
        api.get_product_lot(lot["id"], make_nd_headers(nd["id"]))
    )["quantity_on_hand"] == 15

    authorised = validate_success(
        api.reverse_dispense(
            dispense["id"], {"reason": "wrong patient"}, make_director_headers(director["id"])
        )
    )
    assert authorised["status"] == "REVERSED"
    assert authorised["reversal_authorized_by_user_id"] == director["id"]
    assert validate_success(
        api.get_product_lot(lot["id"], make_nd_headers(nd["id"]))
    )["quantity_on_hand"] == 20
    assert read_patient(api, ctx["patient"]["id"])["cash_refunded_total_cents"] == 24975


def _issued_but_not_activated_line(api):
    """A protocol left at ISSUED, with one line and a stocked lot."""
    ready = setup_protocol_ready_patient(api)
    nd, patient = ready["nd"], ready["patient"]
    tech = register_tech(api)
    product = create_product(api)
    lot = receive_lot(api, product["id"])
    protocol = draft_protocol(api, nd["id"], patient["id"], title="Repletion")
    item = add_protocol_item(api, nd["id"], protocol["id"], product["id"])
    issue_protocol(api, nd["id"], protocol["id"])
    return {
        "nd": nd,
        "tech": tech,
        "patient": patient,
        "product": product,
        "lot": lot,
        "protocol": protocol,
        "item": item,
    }


def test_dispensing_against_an_issued_protocol_is_a_dependent_state_failure(api):
    """PRD §3.8: "The line must be dispensable: its owning protocol must be
    `ACTIVE` and the line itself must be `ACTIVE` or `HELD`, or the request is
    refused with `ERR_DEPENDENT_STATE_INVALID`."
    PRD §2.6: "Cross-entity state preconditions hold — otherwise
    `ERR_DEPENDENT_STATE_INVALID` (409)."

    Design: Difficulty/cross_entity_state_dependency/dispensing_requires_the_owning_protocol_to_be_active
    """
    ctx = _issued_but_not_activated_line(api)
    nd, tech, lot = ctx["nd"], ctx["tech"], ctx["lot"]
    version = protocol_version(api, ctx["protocol"]["id"], nd["id"])

    response = api.create_dispense(
        {
            "protocol_item_id": ctx["item"]["id"],
            "quantity": 1,
            "expected_protocol_version": version,
        },
        make_tech_headers(tech["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DEPENDENT_STATE_INVALID.value, 409)

    untouched = validate_success(api.get_product_lot(lot["id"], make_nd_headers(nd["id"])))
    assert untouched["quantity_on_hand"] == 20

    rows, meta = validate_paginated(
        api.list_dispenses(
            make_nd_headers(nd["id"]), params={"protocol_item_id": ctx["item"]["id"]}
        )
    )
    assert meta["total_count"] == 0 and rows == []


def test_the_identical_dispense_succeeds_once_the_protocol_is_activated(api):
    """PRD §3.6: "Activation moves `ISSUED → ACTIVE`, again requires the gate to
    be `OPEN`, stamps `activated_at`, and increments the protocol's `version` by
    1."
    PRD §3.8: "A successful fill decrements the source lot's `quantity_on_hand`
    by the dispensed `quantity`, recomputes the owning product's `stock_on_hand`
    across its eligible lots, adds `total_price_cents` to the patient's
    `cash_charged_total_cents`, and increments the **protocol's** `version` by
    1."

    Design: Difficulty/cross_entity_state_dependency/dispensing_requires_the_owning_protocol_to_be_active
    """
    ctx = _issued_but_not_activated_line(api)
    nd, tech, lot = ctx["nd"], ctx["tech"], ctx["lot"]

    activated = validate_success(
        api.activate_protocol(ctx["protocol"]["id"], make_nd_headers(nd["id"]))
    )
    assert activated["status"] == "ACTIVE"

    version = protocol_version(api, ctx["protocol"]["id"], nd["id"])
    dispense = validate_success(
        api.create_dispense(
            {
                "protocol_item_id": ctx["item"]["id"],
                "quantity": 1,
                "expected_protocol_version": version,
            },
            make_tech_headers(tech["id"]),
        ),
        201,
    )
    assert dispense["status"] == "DISPENSED"

    drawn = validate_success(api.get_product_lot(lot["id"], make_nd_headers(nd["id"])))
    assert drawn["quantity_on_hand"] == 19
