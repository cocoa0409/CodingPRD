"""Numbers the API works out for itself: confidence, weights, money and quotas."""

from test_helpers import (
    ADMIN_HEADERS,
    OFFICER_A_HEADERS,
    ApiErrorId,
    assert_cents,
    assert_confidence_equal,
    assert_courier_gates,
    assert_money_conserved,
    assert_page_meta,
    assert_partner_gate,
    assert_score_equal,
    assert_units_equal,
    factories as f,
    fixtures as fx,
    make_customer_headers,
    make_partner_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-20T12:00:00Z"
EVENING = "2026-08-20T18:00:00Z"
NINETY_DAYS_ON = "2026-11-18T12:00:00Z"
DAY_AFTER_EPOCH = "2026-08-02T12:00:00Z"
NINETY_DAYS_AFTER_THE_DECISION = "2026-10-31T12:00:00Z"
NEXT_DAY_EVENING = "2026-08-03T18:00:00Z"
DAY_AFTER_EPOCH_EVENING = "2026-08-02T18:00:00Z"
SECOND_PROMISE = "2026-08-22T16:00:00Z"
THIRD_PROMISE = "2026-08-24T16:00:00Z"


def _instant(value):
    """The instant a timestamp names, without the fractional digits of PRD 2.4."""
    assert value is not None, "the timestamp must not be null"
    return value.replace("Z", "").split(".")[0]


def _attested_purchaser(api, attestation_channel="WEB_CHECKBOX"):
    """One purchaser who has declared an adult date of birth and nothing more."""
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    attested = fx.attest_customer(
        api, customer["id"], f.ADULT_DOB, attestation_channel=attestation_channel
    )
    return {
        "jurisdiction": jurisdiction,
        "customer": customer,
        "version": attested["version"],
    }


def test_01_a_confidence_landing_exactly_on_the_match_boundary_is_a_match(api):
    """PRD 3.2: "Both boundaries are inclusive at the bottom, so a confidence of exactly
    0.8500 — the value produced when the government identity database, the credit bureau
    and the negative watchlist all match — is a `MATCH`, and all four signals matching
    alongside a date-of-birth disagreement yields 0.8000 and lands in `PARTIAL`."

    Design: Corner/calculations/corner_identity_confidence_exactly_at_the_match_threshold_is_match
    """
    purchaser = _attested_purchaser(api)

    response = api.create_identity_check(
        purchaser["customer"]["id"],
        f.identity_check_payload(
            purchaser["version"],
            provided_dob=f.ADULT_DOB,
            source_dob=f.ADULT_DOB,
            provider="STATE_DMV_GATEWAY",
            validity_days=90,
            source_signals=f.source_signals(
                government_id_db=True,
                credit_bureau=True,
                mobile_carrier=False,
                watchlist_negative=True,
            ),
        ),
        ADMIN_HEADERS,
    )

    check = validate_success(response, expected_status=201)
    assert_confidence_equal(check["confidence"], 0.8500)
    assert check["result"] == "MATCH", (
        "the banding test is at-or-above, so exactly 0.8500 bands as `MATCH` rather than "
        f"`PARTIAL`; got {check['result']}"
    )
    assert check["verified_dob"] == f.ADULT_DOB, (
        "a `MATCH` takes `verified_dob` from the provider's `source_dob`; got "
        f"{check['verified_dob']!r}"
    )
    assert check["status"] == "VALID"
    assert _instant(check["expires_at"]) == _instant(NINETY_DAYS_ON), (
        "the row expires 90 days after it was written; got "
        f"{check['expires_at']!r}"
    )
    customer = fx.read_customer(api, purchaser["customer"]["id"])
    assert customer["latest_identity_check_result"] == "MATCH"
    assert customer["attestation_state"] == "ATTESTED"


def test_02_a_date_of_birth_disagreement_costs_two_tenths_and_lands_in_partial(api):
    """PRD 3.2: "Then a single penalty applies: if `provided_dob` differs from
    `source_dob` **and** a `GOVERNMENT_ID_DB` signal was among those matched, two tenths of
    a point are subtracted, the result is rounded half up to four decimal places again, and
    the value is floored at 0.0000 so confidence is never negative."

    Design: Corner/calculations/corner_identity_confidence_dob_mismatch_penalty_drops_to_partial
    """
    purchaser = _attested_purchaser(api)

    response = api.create_identity_check(
        purchaser["customer"]["id"],
        f.identity_check_payload(
            purchaser["version"],
            provided_dob="2000-03-15",
            source_dob="2000-03-16",
            provider="NATIONAL_ID_VENDOR",
            validity_days=90,
            source_signals=f.source_signals(
                government_id_db=True,
                credit_bureau=True,
                mobile_carrier=True,
                watchlist_negative=True,
            ),
        ),
        OFFICER_A_HEADERS,
    )

    check = validate_success(response, expected_status=201)
    assert_confidence_equal(check["confidence"], 0.8000)
    assert check["result"] == "PARTIAL", (
        "all four weights sum to 1.0000 and the penalty carries the total below the "
        f"0.8500 boundary; got {check['result']}"
    )
    assert check["verified_dob"] == "2000-03-15", (
        "a `PARTIAL` takes `verified_dob` from the purchaser-supplied `provided_dob`; got "
        f"{check['verified_dob']!r}"
    )
    assert fx.read_customer(api, purchaser["customer"]["id"])[
        "latest_identity_check_result"
    ] == "PARTIAL"


def test_03_a_single_matched_signal_falls_below_the_partial_floor(api):
    """PRD 3.2: "Banding turns that number into `result`. A confidence of 0.8500 or above
    is `MATCH`; a confidence below 0.8500 but at or above 0.6000 is `PARTIAL`; anything
    lower is `NO_MATCH`."

    Design: Corner/calculations/corner_identity_confidence_below_partial_threshold_is_no_match
    """
    purchaser = _attested_purchaser(api, attestation_channel="MOBILE_APP")

    response = api.create_identity_check(
        purchaser["customer"]["id"],
        f.identity_check_payload(
            purchaser["version"],
            provided_dob=f.ADULT_DOB,
            source_dob=f.ADULT_DOB,
            provider="TELCO_VERIFY",
            validity_days=90,
            source_signals=f.source_signals(
                government_id_db=True,
                credit_bureau=False,
                mobile_carrier=False,
                watchlist_negative=False,
            ),
        ),
        ADMIN_HEADERS,
    )

    check = validate_success(response, expected_status=201)
    assert_confidence_equal(check["confidence"], 0.5000)
    assert check["result"] == "NO_MATCH", (
        "an unmatched signal contributes nothing rather than a fraction of its weight, so "
        f"the total stops at half a point; got {check['result']}"
    )
    assert check["verified_dob"] is None, (
        f"a `NO_MATCH` leaves `verified_dob` null; got {check['verified_dob']!r}"
    )
    assert fx.read_customer(api, purchaser["customer"]["id"])[
        "latest_identity_check_result"
    ] == "NO_MATCH"


def _newly_hired_courier(api):
    """One partner and the courier it has just taken on, certified for nothing yet."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    courier = fx.create_courier(api, partner["id"], full_name="Dana Reyes")
    return {"partner": partner, "courier": courier}


def test_04_the_training_floor_of_eighty_is_inclusive(api):
    """PRD 3.5: "Issuance demands a `training_score` of at least 80; below that the
    request is refused with `ERR_TRAINING_SCORE_TOO_LOW`."

    Design: Corner/calculations/corner_training_score_exactly_at_the_minimum_constant_is_accepted
    """
    world = _newly_hired_courier(api)
    manager_headers = make_partner_manager_headers(world["partner"]["id"])

    one_short = api.create_courier_certification(
        f.courier_certification_payload(
            world["courier"]["id"], training_score=79, training_completed_at="2026-07-15"
        ),
        manager_headers,
    )
    exactly_at_the_floor = api.create_courier_certification(
        f.courier_certification_payload(
            world["courier"]["id"], training_score=80, training_completed_at="2026-07-15"
        ),
        manager_headers,
    )

    validate_error(one_short, ApiErrorId.TRAINING_SCORE_TOO_LOW.value)
    certification = validate_success(exactly_at_the_floor, expected_status=201)
    assert certification["state"] == "ACTIVE", (
        "a score of exactly 80 satisfies an at-least test; got "
        f"{certification['state']}"
    )
    assert certification["training_score"] == 80
    assert_courier_gates(
        fx.read_courier(api, world["courier"]["id"]),
        certification_state="CERTIFIED",
        dispatch_eligible=True,
    )
    rows, meta = validate_paginated(
        api.list_courier_certifications(world["courier"]["id"], ADMIN_HEADERS)
    )
    assert_page_meta(meta, total_count=1)
    assert len(rows) == 1, (
        "only the accepted issuance may have written a row; got " f"{len(rows)}"
    )


def _one_major_case_decided_then_left_to_age(api):
    """A `MAJOR` case substantiated on one day, with the clock then carried 90 days on."""
    fx.set_clock(api, DAY_AFTER_EPOCH)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    partner = fx.create_partner(
        api,
        legal_name="Empire Last Mile",
        contract_tier="STANDARD",
        license_reference="NY-DEL-0001",
    )
    courier = fx.create_courier(api, partner["id"], full_name="Dana Reyes")
    decoy = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], NEXT_DAY_EVENING, 600
    )
    probe = fx.schedule_shopper_test(
        api,
        courier["id"],
        decoy["id"],
        scenario_type="EXPIRED_DOCUMENT",
        scheduled_at=DAY_AFTER_EPOCH_EVENING,
        expected_outcome="REFUSAL",
    )
    case = fx.build_substantiated_case(
        api,
        partner["id"],
        secret_shopper_test_id=probe["id"],
        severity="MAJOR",
        assessed_severity="MAJOR",
        officer_headers=OFFICER_A_HEADERS,
    )
    fx.set_clock(api, NINETY_DAYS_AFTER_THE_DECISION)
    return {"partner": partner, "case": case}


def test_05_at_ninety_days_the_rolling_variant_still_counts_what_lifetime_has_decayed(api):
    """PRD 3.9: "The **rolling** variant, written to `license_risk_score`, includes only
    cases whose age is 90 days or fewer and weights every included case at 1.00 — a case
    older than ninety days vanishes from it entirely. This is the only variant that drives
    posture derivation. The **lifetime** variant, written to `lifetime_risk_score`, includes
    every substantiated case forever and weights each by a decaying factor: one full point
    minus a tenth for each complete 90-day step of age, floored at a quarter point, so the
    weight never decays below 0.25."

    Design: Corner/calculations/corner_lifetime_weight_steps_down_at_exactly_ninety_days
    """
    world = _one_major_case_decided_then_left_to_age(api)

    assessment = validate_success(
        api.get_risk_assessment(world["partner"]["id"], OFFICER_A_HEADERS)
    )

    assert_score_equal(assessment["rolling_90d_score"], 15.00, "rolling_90d_score")
    assert_score_equal(assessment["lifetime_weighted_score"], 13.50, "lifetime_weighted_score")
    assert_score_equal(assessment["tier_multiplier"], 1.00, "tier_multiplier")
    assert _instant(assessment["evaluated_at"]) == _instant(NINETY_DAYS_AFTER_THE_DECISION)
    breakdown = assessment["case_breakdown"]
    assert len(breakdown) == 1, (
        f"the partner holds exactly one scoring case; got {len(breakdown)} breakdown rows"
    )
    entry = breakdown[0]
    assert entry["violation_case_id"] == world["case"]["id"]
    assert entry["assessed_severity"] == "MAJOR"
    assert entry["age_days"] == 90, (
        "the age is the whole days from `decided_at` to the clock now; got "
        f"{entry['age_days']}"
    )
    assert entry["included_in_rolling"] is True, (
        "an age of exactly 90 days is still 90 days or fewer, so the rolling variant "
        "keeps the case"
    )
    assert_score_equal(entry["rolling_points"], 15.00, "rolling_points")
    assert_score_equal(entry["lifetime_weight"], 0.90, "lifetime_weight")
    assert_score_equal(entry["lifetime_points"], 13.50, "lifetime_points")
    assert_partner_gate(
        fx.read_partner(api, world["partner"]["id"]),
        posture="OPEN",
        license_risk_score=15.00,
        lifetime_risk_score=13.50,
    )


def _premium_hamper_refused_because_the_courier_failed(api):
    """A 20400c order of unrestricted goods, refused at the door for `COURIER_FAULT`."""
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    hamper = fx.create_product(
        api,
        f.product_payload(
            sku="GROCERY-P",
            name="Premium Pantry Hamper",
            restriction_type="NONE",
            restricted_units_per_item=0,
            list_price_cents=6800,
        ),
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    courier = fx.create_courier(api, partner["id"], full_name="Dana Reyes")
    fx.issue_certification(api, courier)
    order = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], EVENING, 600
    )
    line = fx.add_line(api, order, hamper["id"], 3)
    order = fx.submit_order(api, order)
    fx.dispatch_order(api, order)
    fx.set_clock(api, EVENING)
    attempt = fx.open_attempt(api, order, courier, EVENING)
    fx.record_refusal(
        api,
        attempt,
        courier["id"],
        "COURIER_FAULT",
        observed_indicators=["Courier vehicle breakdown"],
    )
    return {
        "order": order,
        "line": line,
        "attempt": attempt,
        "partner": partner,
        "courier": courier,
    }


def test_06_a_courier_fault_refusal_waives_the_fee_and_gives_the_delivery_charge_back(api):
    """PRD 3.7: "Fourth, the fee itself: a refusal for `COURIER_FAULT` waives the
    restocking fee entirely and sets `restocking_fee_cents` to 0, and for every other reason
    the fee is the gross figure multiplied by the tier's basis points, divided by ten
    thousand, and **floored** to whole cents. Fifth, the delivery fee is refunded only when
    the platform was at fault: a `COURIER_FAULT` refusal refunds the order's
    `delivery_fee_cents` in full, and every other reason refunds none of it."

    Design: Corner/calculations/corner_courier_fault_refusal_waives_restocking_and_refunds_the_delivery_fee
    """
    world = _premium_hamper_refused_because_the_courier_failed(api)

    settled = validate_success(
        api.create_return_settlement(
            world["order"]["id"], f.return_settlement_payload(restock_confirmed=True), ADMIN_HEADERS
        )
    )

    assert_cents(settled["item_subtotal_cents"], 20400, "item_subtotal_cents")
    assert_cents(settled["charged_cents"], 21000, "charged_cents")
    assert_cents(settled["restocking_fee_cents"], 0, "restocking_fee_cents")
    assert_cents(settled["refunded_cents"], 21000, "refunded_cents")
    assert_cents(settled["retained_cents"], 0, "retained_cents")
    assert_money_conserved(settled)
    assert settled["fulfillment_state"] == "RETURN_COMPLETED"
    assert_units_equal(settled["final_restricted_units"], 0.00, "final_restricted_units")
    lines, _meta = validate_paginated(
        api.list_order_lines(ADMIN_HEADERS, {"order_id": world["order"]["id"]})
    )
    assert [row["line_state"] for row in lines] == ["WITHDRAWN"]
    assert fx.read_attempt(api, world["attempt"]["id"])["state"] == "REFUSED"
    assert_partner_gate(fx.read_partner(api, world["partner"]["id"]), open_case_count=0)
    assert_courier_gates(
        fx.read_courier(api, world["courier"]["id"]), compliance_score=100.00
    )


def _three_lines_on_one_unrestricted_order(api):
    """One order carrying three unrestricted lines priced 6800, 3200 and 900."""
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    catalogue = [
        fx.create_product(
            api,
            f.product_payload(
                sku=sku,
                name=name,
                restriction_type="NONE",
                restricted_units_per_item=0,
                list_price_cents=price,
            ),
        )
        for sku, name, price in (
            ("GROCERY-P", "Premium Pantry Hamper", 6800),
            ("GROCERY-Q", "Cheese Board", 3200),
            ("GROCERY-R", "Sparkling Water 1L", 900),
        )
    ]
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    order = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], EVENING, 600
    )
    lines = [
        fx.add_line(api, order, product["id"], quantity)
        for product, quantity in zip(catalogue, (3, 2, 1))
    ]
    return {"order": order, "lines": lines, "customer": customer}


def test_07_the_delivery_fee_is_added_once_to_the_sum_of_every_line(api):
    """PRD 3.3: "On every successful submission — whatever the compliance outcome — the
    physical dimension advances `CREATED → SUBMITTED` and `submitted_at` is stamped from the
    logical clock, `item_subtotal_cents` is frozen as the sum of `line_total_cents` across
    **all** of the order's lines regardless of their `line_state`, and `charged_cents` is
    frozen as `item_subtotal_cents` plus `delivery_fee_cents`."

    Design: Corner/calculations/corner_order_money_totals_aggregate_every_line
    """
    world = _three_lines_on_one_unrestricted_order(api)

    submitted = validate_success(
        api.submit_order(
            world["order"]["id"], make_customer_headers(world["customer"]["id"])
        )
    )

    assert [line["line_total_cents"] for line in world["lines"]] == [20400, 6400, 900]
    assert_cents(submitted["item_subtotal_cents"], 27700, "item_subtotal_cents")
    assert_cents(submitted["charged_cents"], 28300, "charged_cents")
    assert_units_equal(
        submitted["provisional_restricted_units"], 0.00, "provisional_restricted_units"
    )
    assert submitted["restriction_types"] == []
    assert submitted["applied_policy_ids"] == []
    assert submitted["compliance_state"] == "AUTO_CLEARED"


def _one_delivered_order_and_one_merely_submitted(api):
    """Six units already handed over, three more only submitted, one more still a draft."""
    world = fx.build_restricted_world(api, clock=CLOCK)
    delivered = fx.build_delivered_order(
        api, world, quantity=4, started_at=EVENING, scheduled_delivery_at=EVENING
    )
    submitted = fx.build_submitted_restricted_order(
        api, world, quantity=2, scheduled_delivery_at=SECOND_PROMISE
    )
    draft = fx.add_restricted_order(
        api, world, quantity=1, scheduled_delivery_at=THIRD_PROMISE
    )
    return {
        "world": world,
        "delivered": delivered["order"],
        "submitted": submitted["order"],
        "draft": draft["order"],
    }


def test_08_only_a_delivered_order_consumes_the_rolling_window(api):
    """PRD 3.3: "Within that interval it visits the same customer's *other* orders — the
    order being submitted is always excluded — whose `fulfillment_state` is exactly
    `DELIVERED`, whose `delivered_at` falls at or after the window start and strictly before
    the anchor, and whose `restriction_types` contains the class under evaluation, in
    `delivered_at` ascending then `created_at` ascending order, and sums their
    `final_restricted_units`, rounding the sum half up to two decimal places."

    Design: Corner/calculations/corner_window_consumption_counts_only_delivered_orders
    """
    world = _one_delivered_order_and_one_merely_submitted(api)

    evaluation = validate_success(
        api.get_compliance_evaluation(world["draft"]["id"], OFFICER_A_HEADERS)
    )

    assert_units_equal(evaluation["window_units_consumed"], 6.00, "window_units_consumed")
    assert_units_equal(
        evaluation["provisional_restricted_units"], 1.50, "provisional_restricted_units"
    )
    assert evaluation["purchaser_age_years"] == 26
    assert evaluation["min_age_required"] == 21
    assert evaluation["identity_result"] == "MATCH"
    assert evaluation["local_delivery_minute"] == 720
    assert evaluation["in_delivery_window"] is True
    assert evaluation["would_route_to"] == "PREVERIFIED"
    assert evaluation["first_blocking_error_id"] is None, (
        "the replay finds no objection, so the field is null rather than an error name; got "
        f"{evaluation['first_blocking_error_id']!r}"
    )
    delivered = fx.read_order(api, world["delivered"]["id"])
    assert delivered["fulfillment_state"] == "DELIVERED"
    assert_units_equal(delivered["final_restricted_units"], 6.00, "final_restricted_units")
    merely_submitted = fx.read_order(api, world["submitted"]["id"])
    assert merely_submitted["fulfillment_state"] == "SUBMITTED", (
        "the second order never reached the door, which is the whole point of the "
        f"admission criterion; got {merely_submitted['fulfillment_state']}"
    )
    assert_units_equal(
        merely_submitted["provisional_restricted_units"],
        3.00,
        "provisional_restricted_units",
    )
