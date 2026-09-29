"""The gates a request must pass, the order they fire in, and what a refusal leaves behind."""

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    NON_EXISTENT_UUID,
    OFFICER_A_HEADERS,
    ApiErrorId,
    assert_attempt_state,
    assert_cents,
    assert_courier_gates,
    assert_order_states,
    assert_page_meta,
    assert_partner_gate,
    assert_units_equal,
    factories as f,
    fixtures as fx,
    headers_without_auth,
    make_courier_headers,
    make_customer_headers,
    make_partner_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-20T12:00:00Z"
EVENING = "2026-08-20T18:00:00Z"
LATER_EVENING = "2026-08-20T19:00:00Z"
YESTERDAY_EVENING = "2026-08-19T18:00:00Z"
TOMORROW_PROBE = "2026-08-21T18:00:00Z"
SECOND_PROMISE = "2026-08-22T16:00:00Z"
SEPTEMBER = {"effective_from": "2026-09-01", "effective_to": "2026-09-30"}
GROCERY_HAMPER_SKU = "GROCERY-P"


def _instant(value):
    """The instant a timestamp names, without the fractional digits of PRD 2.4."""
    assert value is not None, "the timestamp must not be null"
    return value.replace("Z", "").split(".")[0]


def test_01_an_unauthenticated_read_of_a_missing_order_answers_on_authentication(api):
    """PRD 2.7: "**Authentication.** `X-User-ID` (and `X-User-Role`) must be present and
    non-empty, else `ERR_MISSING_AUTH_HEADER` with HTTP 401."

    Design: Corner/validations/corner_missing_auth_header_is_unauthorized_before_not_found
    """
    fx.set_clock(api, CLOCK)

    listing = api.list_products(headers_without_auth())
    unknown_order = api.get_order(NON_EXISTENT_UUID, headers_without_auth())

    validate_error(listing, ApiErrorId.MISSING_AUTH_HEADER.value)
    validate_error(unknown_order, ApiErrorId.MISSING_AUTH_HEADER.value)
    assert unknown_order.json()["data"]["error_id"] != ApiErrorId.ORDER_NOT_FOUND.value, (
        "authentication is never skipped to answer an existence question"
    )
    for response in (listing, unknown_order):
        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"], "an error body carries an `error_id`"
        assert body["data"]["message"], "an error body carries a `message`"


def _one_empty_order_and_one_courier(api):
    """An order with no lines yet, and a courier a decoy test could be aimed at."""
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    courier = fx.create_courier(api, partner["id"], full_name="Dana Reyes")
    order = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], EVENING, 600
    )
    return {"customer": customer, "courier": courier, "order": order}


def test_02_body_foreign_keys_report_the_code_of_the_entity_they_failed_to_find(api):
    """PRD 2.6: "Body-level foreign-key failures reuse the same per-entity codes:
    `ERR_JURISDICTION_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_ORDER_NOT_FOUND`, `ERR_PARTNER_NOT_FOUND` and `ERR_COURIER_NOT_FOUND`."

    Design: Corner/validations/corner_body_foreign_keys_are_rejected_with_their_own_not_found_errors
    """
    world = _one_empty_order_and_one_courier(api)

    unknown_product = api.create_order_line(
        world["order"]["id"],
        f.order_line_payload(NON_EXISTENT_UUID, 1),
        make_customer_headers(world["customer"]["id"]),
    )
    unknown_decoy = api.create_secret_shopper_test(
        f.secret_shopper_test_payload(
            world["courier"]["id"], NON_EXISTENT_UUID, scheduled_at=TOMORROW_PROBE
        ),
        AUDITOR_HEADERS,
    )

    validate_error(unknown_product, ApiErrorId.PRODUCT_NOT_FOUND.value)
    validate_error(unknown_decoy, ApiErrorId.ORDER_NOT_FOUND.value)
    order = fx.read_order(api, world["order"]["id"])
    assert_cents(order["item_subtotal_cents"], 0, "item_subtotal_cents")
    lines, line_meta = validate_paginated(
        api.list_order_lines(ADMIN_HEADERS, {"order_id": world["order"]["id"]})
    )
    assert lines == [], f"the refused line must not have been stored; got {len(lines)}"
    assert_page_meta(line_meta, total_count=0)
    probes, probe_meta = validate_paginated(
        api.list_secret_shopper_tests(AUDITOR_HEADERS, {"courier_id": world["courier"]["id"]})
    )
    assert probes == [], f"the refused decoy test must not have been stored; got {len(probes)}"
    assert_page_meta(probe_meta, total_count=0)


def test_03_a_policy_that_starts_next_month_governs_nothing_this_month(api):
    """PRD 3.3: "For every element of `restriction_types`, exactly one policy must exist
    for the pair of the order's `delivery_jurisdiction_id` and that class whose closed
    effective period contains the local calendar date of `scheduled_delivery_at`; zero
    matching rows is a hard failure reported as `ERR_NO_EFFECTIVE_POLICY`, and the
    no-overlap rule of 2.10 guarantees there is never more than one."

    Design: Corner/validations/corner_submit_with_no_policy_effective_on_the_delivery_date_is_rejected
    """
    world = fx.build_restricted_world(api, clock=CLOCK, policy_overrides=SEPTEMBER)
    built = fx.add_restricted_order(
        api, world, quantity=2, scheduled_delivery_at=EVENING
    )

    response = api.submit_order(built["order"]["id"], world["customer_headers"])

    validate_error(response, ApiErrorId.NO_EFFECTIVE_POLICY.value)
    order = fx.read_order(api, built["order"]["id"])
    assert_order_states(order, compliance_state="DRAFT_UNVERIFIED", fulfillment_state="CREATED")
    assert_cents(order["charged_cents"], 0, "charged_cents")
    assert order["applied_policy_ids"] == [], (
        "an unresolved class writes no policy identifier; got "
        f"{order['applied_policy_ids']}"
    )
    assert order["submitted_at"] is None, (
        f"a refused submission stamps nothing; got {order['submitted_at']!r}"
    )
    evaluation = validate_success(
        api.get_compliance_evaluation(built["order"]["id"], OFFICER_A_HEADERS)
    )
    assert evaluation["first_blocking_error_id"] == ApiErrorId.NO_EFFECTIVE_POLICY.value, (
        "the read-only evaluation names the same blocker the submission reported; got "
        f"{evaluation['first_blocking_error_id']!r}"
    )


def _one_unattested_purchaser_with_both_kinds_of_order(api):
    """A purchaser who never attested, holding one wine order and one grocery order."""
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    fx.create_policy(api, jurisdiction["id"])
    wine = fx.create_product(api, f.wine_product_payload(name="Cabernet 750ml"))
    hamper = fx.create_product(
        api,
        f.grocery_product_payload(
            sku=GROCERY_HAMPER_SKU, name="Premium Pantry Hamper", list_price_cents=6800
        ),
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    restricted = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], EVENING, 600
    )
    fx.add_line(api, restricted, wine["id"], 2)
    unrestricted = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], LATER_EVENING, 600
    )
    fx.add_line(api, unrestricted, hamper["id"], 1)
    return {
        "customer": customer,
        "restricted": restricted,
        "unrestricted": unrestricted,
        "customer_headers": make_customer_headers(customer["id"]),
    }


def test_04_the_attestation_gate_reads_the_box_not_the_purchaser(api):
    """PRD 3.3: "When the order's `restriction_types` is empty — every line's product is
    classified `NONE` — the compliance dimension moves `DRAFT_UNVERIFIED → AUTO_CLEARED`,
    `provisional_restricted_units` is set to 0.00 and `applied_policy_ids` stays empty.
    Such an order bypasses attestation, pre-verification, policy resolution, restricted
    hours, quantity quotas and door-side identification entirely; there is nothing
    age-restricted in the box."

    Design: Corner/validations/corner_attestation_is_required_only_when_the_order_carries_restricted_lines
    """
    world = _one_unattested_purchaser_with_both_kinds_of_order(api)

    refused = api.submit_order(world["restricted"]["id"], world["customer_headers"])
    cleared = validate_success(
        api.submit_order(world["unrestricted"]["id"], world["customer_headers"])
    )

    validate_error(refused, ApiErrorId.ATTESTATION_REQUIRED.value)
    still_draft = fx.read_order(api, world["restricted"]["id"])
    assert_order_states(still_draft, compliance_state="DRAFT_UNVERIFIED")
    assert_cents(still_draft["charged_cents"], 0, "charged_cents")
    assert_order_states(cleared, compliance_state="AUTO_CLEARED", fulfillment_state="SUBMITTED")
    assert_cents(cleared["charged_cents"], 7400, "charged_cents")
    assert cleared["restriction_types"] == [], (
        f"a box of groceries carries no restriction class; got {cleared['restriction_types']}"
    )
    customer = fx.read_customer(api, world["customer"]["id"])
    assert customer["attestation_state"] == "NOT_ATTESTED", (
        "clearing the grocery order must not have attested anybody; got "
        f"{customer['attestation_state']}"
    )


def test_05_a_nineteen_year_old_clears_attestation_and_still_fails_the_policy_minimum(api):
    """PRD 3.3: "First, the purchaser must be eligible, and the eligibility checks are
    evaluated in a fixed sub-order: the customer's `attestation_state` must be exactly
    `ATTESTED` (both `NOT_ATTESTED` and `ATTESTATION_REJECTED` report
    `ERR_ATTESTATION_REQUIRED`); then, if the customer's `blocked_until` is set and lies
    later than the logical clock now, the submission reports
    `ERR_CUSTOMER_DELIVERY_BLOCKED`; then the customer must have at least one identity check
    whose `status` is `VALID`, else `ERR_IDENTITY_PREVERIFICATION_REQUIRED`; and finally the
    completed age of the newest `VALID` check's `verified_dob`, measured as at the local
    calendar date of `scheduled_delivery_at` in the delivery jurisdiction, must be at least
    the largest `min_age_years` among the policies selected for this order, else
    `ERR_PURCHASER_UNDERAGE`."

    Design: Corner/validations/corner_purchaser_below_the_policy_minimum_age_is_rejected
    """
    world = fx.build_restricted_world(api, clock=CLOCK, attested_dob=f.MINOR_DOB)
    built = fx.add_restricted_order(api, world, quantity=1, scheduled_delivery_at=EVENING)

    response = api.submit_order(built["order"]["id"], world["customer_headers"])

    validate_error(response, ApiErrorId.PURCHASER_UNDERAGE.value)
    customer = fx.read_customer(api, world["customer"]["id"])
    assert customer["attestation_state"] == "ATTESTED", (
        "nineteen clears the global attestation age, so the attestation gate passed; got "
        f"{customer['attestation_state']}"
    )
    assert customer["latest_identity_check_result"] == "MATCH"
    assert_order_states(fx.read_order(api, built["order"]["id"]), compliance_state="DRAFT_UNVERIFIED")
    evaluation = validate_success(
        api.get_compliance_evaluation(built["order"]["id"], OFFICER_A_HEADERS)
    )
    assert evaluation["purchaser_age_years"] == 19, (
        f"completed years from 2007-05-10 to 2026-08-20; got {evaluation['purchaser_age_years']}"
    )
    assert evaluation["min_age_required"] == 21
    assert evaluation["first_blocking_error_id"] == ApiErrorId.PURCHASER_UNDERAGE.value


def test_06_the_window_ceiling_counts_units_a_previous_order_already_delivered(api):
    """PRD 3.3: "If the provisional exposure for the class plus that already-consumed
    figure exceeds the policy's `max_units_per_window`, the submission reports
    `ERR_WINDOW_UNIT_LIMIT_EXCEEDED`."

    Design: Corner/validations/corner_rolling_window_unit_ceiling_aggregates_across_orders
    """
    world = fx.build_restricted_world(
        api, clock=CLOCK, policy_overrides={"max_units_per_window": 7.00}
    )
    delivered = fx.build_delivered_order(
        api, world, quantity=4, started_at=EVENING, scheduled_delivery_at=EVENING
    )
    built = fx.add_restricted_order(
        api, world, quantity=1, scheduled_delivery_at=SECOND_PROMISE
    )

    response = api.submit_order(built["order"]["id"], world["customer_headers"])

    validate_error(response, ApiErrorId.WINDOW_UNIT_LIMIT_EXCEEDED.value)
    assert_units_equal(
        fx.read_order(api, delivered["order"]["id"])["final_restricted_units"],
        6.00,
        "final_restricted_units",
    )
    evaluation = validate_success(
        api.get_compliance_evaluation(built["order"]["id"], OFFICER_A_HEADERS)
    )
    assert_units_equal(evaluation["window_units_consumed"], 6.00, "window_units_consumed")
    assert_units_equal(
        evaluation["provisional_restricted_units"], 1.50, "provisional_restricted_units"
    )
    assert_units_equal(world["policy"]["max_units_per_order"], 6.97, "max_units_per_order")
    second = fx.read_order(api, built["order"]["id"])
    assert_order_states(second, compliance_state="DRAFT_UNVERIFIED")
    assert_cents(second["charged_cents"], 0, "charged_cents")


def test_07_the_promised_instant_is_measured_against_the_logical_clock(api):
    """PRD 3.3: "The promised `scheduled_delivery_at` must lie strictly later than the
    logical clock now; an instant at or before now reports `ERR_SCHEDULED_TIME_IN_PAST`."

    Design: Corner/validations/corner_scheduled_delivery_must_be_strictly_after_the_logical_clock
    """
    world = fx.build_restricted_world(api, clock=CLOCK)
    already_gone = fx.add_restricted_order(
        api, world, quantity=1, scheduled_delivery_at=YESTERDAY_EVENING
    )
    exactly_now = fx.add_restricted_order(api, world, quantity=1, scheduled_delivery_at=CLOCK)
    still_ahead = fx.add_restricted_order(api, world, quantity=1, scheduled_delivery_at=EVENING)

    past = api.submit_order(already_gone["order"]["id"], world["customer_headers"])
    boundary = api.submit_order(exactly_now["order"]["id"], world["customer_headers"])
    accepted = validate_success(
        api.submit_order(still_ahead["order"]["id"], world["customer_headers"])
    )

    validate_error(past, ApiErrorId.SCHEDULED_TIME_IN_PAST.value)
    validate_error(boundary, ApiErrorId.SCHEDULED_TIME_IN_PAST.value)
    assert (
        boundary.json()["data"]["error_id"] != ApiErrorId.OUTSIDE_RESTRICTED_HOURS.value
    ), (
        "an instant equal to the clock fails the strictly-later test before the window "
        "geometry is ever consulted"
    )
    assert _instant(accepted["scheduled_delivery_at"]) == _instant(EVENING), (
        f"the accepted promise reads back unchanged; got {accepted['scheduled_delivery_at']!r}"
    )
    assert_order_states(accepted, compliance_state="PREVERIFIED", fulfillment_state="SUBMITTED")
    assert_order_states(
        fx.read_order(api, already_gone["order"]["id"]),
        compliance_state="DRAFT_UNVERIFIED",
        fulfillment_state="CREATED",
    )
    _, meta = validate_paginated(
        api.list_orders(OFFICER_A_HEADERS, {"customer_id": world["customer"]["id"]})
    )
    assert_page_meta(meta, total_count=3)


def test_08_an_unacceptable_document_is_reported_before_the_missing_scan(api):
    """PRD 3.6: "First, `document_type` must be a member of **every** selected policy's
    `acceptable_document_types`; if it is not, `ERR_DOCUMENT_TYPE_NOT_ACCEPTABLE` follows —
    and because an `acceptable_document_types` array may be empty, a policy with an empty
    list rejects every document presented to it, however well-formed. Second, if any
    selected policy has `requires_scan` true while `scan_performed` is false,
    `ERR_SCAN_REQUIRED` follows."

    Design: Corner/validations/corner_document_gate_rejects_an_unacceptable_type_before_the_scan_check
    """
    world = fx.build_restricted_world(api, clock=CLOCK)
    built = fx.build_open_attempt(
        api, world, quantity=2, started_at=EVENING, scheduled_delivery_at=EVENING
    )
    courier_headers = make_courier_headers(world["courier"]["id"])

    wrong_document = api.record_id_check(
        built["attempt"]["id"],
        f.id_check_payload(
            document_type="MILITARY_ID", scan_performed=False, recipient_name="Ada Lin"
        ),
        courier_headers,
    )
    missing_scan = api.record_id_check(
        built["attempt"]["id"],
        f.id_check_payload(scan_performed=False, recipient_name="Ada Lin"),
        courier_headers,
    )

    validate_error(wrong_document, ApiErrorId.DOCUMENT_TYPE_NOT_ACCEPTABLE.value)
    assert (
        wrong_document.json()["data"]["error_id"] != ApiErrorId.SCAN_REQUIRED.value
    ), "a call defective twice over answers on the earlier sub-check"
    validate_error(missing_scan, ApiErrorId.SCAN_REQUIRED.value)
    untouched = fx.read_attempt(api, built["attempt"]["id"])
    assert_attempt_state(untouched, "INITIATED")
    assert untouched["document_type"] is None, (
        f"neither refusal may have written a document; got {untouched['document_type']!r}"
    )

    verified = validate_success(
        api.record_id_check(
            built["attempt"]["id"],
            f.id_check_payload(scan_performed=True, recipient_name="Ada Lin"),
            courier_headers,
        )
    )

    assert_attempt_state(verified, "ID_VERIFIED")
    assert verified["document_type"] == "DRIVERS_LICENSE"
    assert verified["scan_performed"] is True
    assert verified["id_check_compliant"] is True


def test_09_a_submission_that_satisfies_every_gate_routes_on_the_identity_result(api):
    """PRD 3.3: "Only once the whole battery has passed does the compliance dimension
    resolve, and it resolves purely on the `result` of the customer's newest `VALID`
    identity check. A `MATCH` routes `DRAFT_UNVERIFIED → PREVERIFIED`."

    Design: Corner/validations/corner_fully_compliant_submit_satisfies_every_gate_and_routes_to_preverified
    """
    world = fx.build_restricted_world(api, clock=CLOCK)
    built = fx.add_restricted_order(api, world, quantity=2, scheduled_delivery_at=EVENING)

    submitted = validate_success(
        api.submit_order(built["order"]["id"], world["customer_headers"])
    )

    assert_order_states(submitted, compliance_state="PREVERIFIED", fulfillment_state="SUBMITTED")
    assert_units_equal(
        submitted["provisional_restricted_units"], 3.00, "provisional_restricted_units"
    )
    assert_cents(submitted["item_subtotal_cents"], 13600, "item_subtotal_cents")
    assert_cents(submitted["charged_cents"], 14200, "charged_cents")
    assert submitted["restriction_types"] == ["ALCOHOL"]
    assert submitted["applied_policy_ids"] == [world["policy"]["id"]], (
        "the resolved policy is written positionally against `restriction_types`; got "
        f"{submitted['applied_policy_ids']}"
    )
    assert _instant(submitted["submitted_at"]) == _instant(CLOCK)
    assert submitted["hold_reason"] is None
    assert submitted["clearance_actor_user_id"] is None, (
        "a `MATCH` needs no human clearance; got "
        f"{submitted['clearance_actor_user_id']!r}"
    )


def _one_dispatched_order_and_a_courier_of_a_different_partner(api):
    """Partner A carries the order; the only certified courier works for partner B."""
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    hamper = fx.create_product(
        api,
        f.grocery_product_payload(
            sku=GROCERY_HAMPER_SKU, name="Premium Pantry Hamper", list_price_cents=6800
        ),
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    partner_a = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    partner_b = fx.create_partner(
        api, legal_name="Harbor Courier Co", license_reference="NY-DEL-0002"
    )
    courier_b = fx.create_courier(api, partner_b["id"], full_name="Sam Okafor")
    fx.issue_certification(api, courier_b, valid_days=365)
    order = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner_a["id"], EVENING, 600
    )
    fx.add_line(api, order, hamper["id"], 1)
    submitted = fx.submit_order(api, order)
    fx.dispatch_order(api, submitted)
    fx.set_clock(api, EVENING)
    return {"partner_a": partner_a, "courier_b": courier_b, "order": submitted}


def test_10_a_courier_of_another_partner_cannot_open_the_door_attempt(api):
    """PRD 3.6: "The courier's employing `delivery_partner_id` must equal the order's
    `delivery_partner_id`, else `ERR_COURIER_PARTNER_MISMATCH`; the courier's derived
    `certification_state` must be `CERTIFIED`, else `ERR_COURIER_NOT_CERTIFIED`; and the
    partner's `posture` must not be `SUSPENDED`, else `ERR_PARTNER_SUSPENDED`."

    Design: Corner/validations/corner_courier_from_another_partner_cannot_open_the_attempt
    """
    world = _one_dispatched_order_and_a_courier_of_a_different_partner(api)

    response = api.create_delivery_attempt(
        f.delivery_attempt_payload(world["order"]["id"], world["courier_b"]["id"], EVENING),
        make_courier_headers(world["courier_b"]["id"]),
    )

    validate_error(response, ApiErrorId.COURIER_PARTNER_MISMATCH.value)
    assert_courier_gates(
        fx.read_courier(api, world["courier_b"]["id"]),
        certification_state="CERTIFIED",
        dispatch_eligible=True,
    )
    assert_partner_gate(fx.read_partner(api, world["partner_a"]["id"]), posture="OPEN")
    assert_order_states(
        fx.read_order(api, world["order"]["id"]), fulfillment_state="DISPATCHED"
    )
    attempts, meta = validate_paginated(
        api.list_delivery_attempts(ADMIN_HEADERS, {"order_id": world["order"]["id"]})
    )
    assert attempts == [], (
        f"the mismatched courier opened nothing; got {len(attempts)} attempt rows"
    )
    assert_page_meta(meta, total_count=0)


def _one_restricted_order_nobody_ever_attested_for(api):
    """A wine order whose purchaser never attested, plus the partner and courier waiting."""
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    fx.create_policy(api, jurisdiction["id"])
    wine = fx.create_product(api, f.wine_product_payload(name="Cabernet 750ml"))
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    courier = fx.create_courier(api, partner["id"], full_name="Dana Reyes")
    fx.issue_certification(api, courier, valid_days=365)
    order = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], EVENING, 600
    )
    line = fx.add_line(api, order, wine["id"], 1)
    return {
        "customer": customer,
        "partner": partner,
        "courier": courier,
        "order": order,
        "line": line,
    }


def test_11_because_the_refused_submit_wrote_nothing_the_rest_of_the_chain_cannot_run(api):
    """PRD 2.7: "The system evaluates rules in strictly ascending tier order and the
    **first** violated rule determines the response; no later tier is evaluated, and no
    partial mutation survives a rejection."

    Design: Corner/validations/corner_a_rejected_submit_blocks_dispatch_and_the_door_chain
    """
    world = _one_restricted_order_nobody_ever_attested_for(api)
    order_id = world["order"]["id"]

    refused_submit = api.submit_order(order_id, make_customer_headers(world["customer"]["id"]))
    refused_dispatch = api.dispatch_order(
        order_id, make_partner_manager_headers(world["partner"]["id"])
    )
    refused_attempt = api.create_delivery_attempt(
        f.delivery_attempt_payload(order_id, world["courier"]["id"], EVENING),
        make_courier_headers(world["courier"]["id"]),
    )

    validate_error(refused_submit, ApiErrorId.ATTESTATION_REQUIRED.value)
    validate_error(refused_dispatch, ApiErrorId.INVALID_ORDER_STATE.value)
    validate_error(refused_attempt, ApiErrorId.INVALID_ORDER_STATE.value)
    order = fx.read_order(api, order_id)
    assert_order_states(order, compliance_state="DRAFT_UNVERIFIED", fulfillment_state="CREATED")
    assert order["dispatched_at"] is None
    attempts, meta = validate_paginated(
        api.list_delivery_attempts(ADMIN_HEADERS, {"order_id": order_id})
    )
    assert attempts == [], f"no attempt row is ever created; got {len(attempts)}"
    assert_page_meta(meta, total_count=0)
    line = validate_success(api.get_order_line(world["line"]["id"], ADMIN_HEADERS))
    assert line["line_state"] == "INCLUDED", (
        f"the untouched line keeps its state; got {line['line_state']}"
    )
