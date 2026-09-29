"""What a row looks like the instant the API mints it, and what a read gives back."""

from test_helpers import (
    ADMIN_HEADERS,
    NON_EXISTENT_UUID,
    OFFICER_A_HEADERS,
    ApiErrorId,
    assert_cents,
    assert_common_fields,
    assert_created_at_ascending,
    assert_line_snapshot,
    assert_page_meta,
    assert_units_equal,
    assert_versionless_row,
    factories as f,
    fixtures as fx,
    ids_of,
    make_customer_headers,
    make_partner_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-20T12:00:00Z"
EVENING = "2026-08-20T18:00:00Z"
CAPTURED_AT = "2026-08-20T18:05:00Z"
RETENTION_HORIZON = "2033-08-18T18:05:00"
PROMISED_DAYS = ("2026-08-21T16:00:00Z", "2026-08-22T16:00:00Z", "2026-08-23T16:00:00Z")


def _instant(value):
    """The instant a timestamp names, without the fractional digits of PRD 2.4."""
    assert value is not None, "the timestamp must not be null"
    return value.replace("Z", "").split(".")[0]


def test_01_registering_a_jurisdiction_echoes_every_field_and_seeds_the_counter(api):
    """PRD 3.1: "A freshly registered jurisdiction reports `active_policy_count` of 0;
    that counter is the number of restriction policy rows whose `jurisdiction_id` points
    at this jurisdiction, counted across **all** effective periods with no filtering by
    state or by whether the period is currently in force, and it is incremented as each
    policy is published."

    Design: Corner/entities/corner_jurisdiction_creation_returns_all_declared_fields
    """
    fx.set_clock(api, CLOCK)

    response = api.create_jurisdiction(
        f.jurisdiction_payload(
            code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
        ),
        ADMIN_HEADERS,
    )

    created = validate_success(response, expected_status=201)
    assert created["code"] == "US-NY"
    assert created["name"] == "New York"
    assert created["dry_status"] == "WET"
    assert created["utc_offset_minutes"] == -240
    assert created["active_policy_count"] == 0, (
        "the counter is a derived field of the entity, never taken from the request; got "
        f"{created['active_policy_count']}"
    )
    assert_common_fields(created, expected_version=1)
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")


def test_02_reading_a_product_returns_the_row_that_was_written(api):
    """PRD 3.1: "A product carries a `sku` that is globally unique — a reused `sku` also
    reports `ERR_DUPLICATE_CODE` — a display `name`, a `restriction_type` drawn from the
    same five classes plus the additional value `NONE` for unrestricted goods, a
    `restricted_units_per_item` figure of zero or more with up to two decimal places, and
    a `list_price_cents` that must be strictly positive."

    Design: Corner/entities/corner_product_retrieval_returns_the_stored_row
    """
    fx.set_clock(api, CLOCK)
    stored = fx.create_product(api, f.wine_product_payload(name="Cabernet 750ml"))

    fetched = validate_success(api.get_product(stored["id"], OFFICER_A_HEADERS))

    assert fetched["id"] == stored["id"]
    assert fetched["sku"] == f.WINE_SKU
    assert fetched["name"] == "Cabernet 750ml"
    assert fetched["restriction_type"] == "ALCOHOL"
    assert_units_equal(
        fetched["restricted_units_per_item"], 1.50, "restricted_units_per_item"
    )
    assert_cents(fetched["list_price_cents"], 6800, "list_price_cents")


def _three_orders_for_one_customer(api):
    """One customer holding three orders promised on three consecutive days."""
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    orders = [
        fx.create_order(
            api, customer["id"], jurisdiction["id"], partner["id"], promised, 600
        )
        for promised in PROMISED_DAYS
    ]
    return {"customer": customer, "orders": orders}


def test_03_an_order_listing_reports_the_page_and_the_unpaginated_total(api):
    """PRD 2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more`
    inside `meta`, where `total_count` is the number of rows matching the filters before
    pagination is applied and `has_more` is true exactly when rows remain beyond the
    returned page."

    Design: Corner/entities/corner_order_listing_paginates_with_total_count_and_has_more
    """
    world = _three_orders_for_one_customer(api)
    customer_id = world["customer"]["id"]

    first_page, first_meta = validate_paginated(
        api.list_orders(
            OFFICER_A_HEADERS, {"customer_id": customer_id, "limit": 2, "offset": 0}
        )
    )
    second_page, second_meta = validate_paginated(
        api.list_orders(
            OFFICER_A_HEADERS, {"customer_id": customer_id, "limit": 2, "offset": 2}
        )
    )

    assert len(first_page) == 2, f"the first page holds the limit; got {len(first_page)}"
    assert_page_meta(first_meta, total_count=3, has_more=True, limit=2, offset=0)
    assert len(second_page) == 1, f"one row remains beyond the page; got {len(second_page)}"
    assert_page_meta(second_meta, total_count=3, has_more=False, limit=2, offset=2)
    assert_created_at_ascending(first_page + second_page)
    for row in first_page + second_page:
        assert row["customer_id"] == customer_id


def test_04_a_well_formed_identifier_that_names_no_product_is_a_not_found(api):
    """PRD 2.6: "The catalogue of not-found codes is one per entity:
    `ERR_JURISDICTION_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`,
    `ERR_PARTNER_NOT_FOUND`, `ERR_COURIER_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`,
    `ERR_ATTEMPT_NOT_FOUND`, `ERR_SHOPPER_TEST_NOT_FOUND`, `ERR_CASE_NOT_FOUND` and
    `ERR_PLAN_NOT_FOUND`."

    Design: Corner/entities/corner_product_not_found_for_unknown_id
    """
    fx.set_clock(api, CLOCK)

    response = api.get_product(NON_EXISTENT_UUID, OFFICER_A_HEADERS)

    validate_error(response, ApiErrorId.PRODUCT_NOT_FOUND.value)
    body = response.json()
    assert body["response_type"] == "error", (
        "an unresolvable identifier is an error, never an empty success body; got "
        f"{body['response_type']}"
    )


def test_05_a_product_registration_missing_its_price_is_rejected_and_stores_nothing(api):
    """PRD 2.7: "**Request shape.** Required fields present, JSON types correct, enum
    members recognised, declared numeric ranges respected, date and timestamp strings
    parseable, and `limit`/`offset` inside their bounds — otherwise `ERR_VALIDATION` with
    HTTP 400."

    Design: Corner/entities/corner_product_creation_missing_required_field_is_rejected
    """
    fx.set_clock(api, CLOCK)
    payload = f.wine_product_payload(name="Cabernet 750ml")
    payload.pop("list_price_cents")

    response = api.create_product(payload, ADMIN_HEADERS)

    validate_error(response, ApiErrorId.VALIDATION.value)
    products, meta = validate_paginated(api.list_products(ADMIN_HEADERS))
    assert products == [], f"no product row may survive the rejection; got {len(products)}"
    assert_page_meta(meta, total_count=0)


def test_06_a_new_customer_lands_on_its_declared_defaults(api):
    """PRD 3.2: "A new customer starts with `attestation_state` of `NOT_ATTESTED`,
    `latest_identity_check_result` of `NONE`, `refusal_strikes` of 0, and `blocked_until`,
    `attested_dob`, `attestation_at` and `attestation_channel` all null."

    Design: Corner/entities/corner_new_customer_carries_declared_defaults
    """
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )

    response = api.create_customer(
        f.customer_payload(jurisdiction["id"], full_name="Ada Lin"), ADMIN_HEADERS
    )

    created = validate_success(response, expected_status=201)
    assert created["jurisdiction_id"] == jurisdiction["id"]
    assert created["attestation_state"] == "NOT_ATTESTED"
    assert created["latest_identity_check_result"] == "NONE"
    assert created["refusal_strikes"] == 0
    for field in (
        "blocked_until",
        "attested_dob",
        "attestation_at",
        "attestation_channel",
    ):
        assert created[field] is None, (
            f"a new customer's `{field}` must be null, got {created[field]!r}"
        )
    assert_common_fields(created, expected_version=1)


def _one_order_awaiting_its_first_line(api):
    """A wine catalogue entry and an empty order belonging to one purchaser."""
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    wine = fx.create_product(api, f.wine_product_payload(name="Cabernet 750ml"))
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    order = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], EVENING, 600
    )
    return {"wine": wine, "customer": customer, "order": order}


def test_07_a_line_snapshots_the_catalogue_and_derives_its_own_total(api):
    """PRD 3.3: "At the moment of creation the line snapshots two values from the
    catalogue and never re-reads them: `unit_price_cents` copies the product's
    `list_price_cents`, and `units_per_item_snapshot` copies the product's
    `restricted_units_per_item`. Its `line_total_cents` is the `quantity` multiplied by
    `unit_price_cents`."

    Design: Corner/entities/corner_order_line_snapshots_and_totals_are_computed_not_supplied
    """
    world = _one_order_awaiting_its_first_line(api)

    response = api.create_order_line(
        world["order"]["id"],
        f.order_line_payload(world["wine"]["id"], 3),
        make_customer_headers(world["customer"]["id"]),
    )

    line = validate_success(response, expected_status=201)
    assert_line_snapshot(line, unit_price_cents=6800, units_per_item_snapshot=1.50, quantity=3)
    assert_units_equal(line["line_restricted_units"], 0.00, "line_restricted_units")
    order = fx.read_order(api, world["order"]["id"])
    assert_cents(order["item_subtotal_cents"], 20400, "item_subtotal_cents")
    assert order["restriction_types"] == ["ALCOHOL"]
    assert_cents(order["charged_cents"], 0, "charged_cents")


def test_08_submission_stamps_the_system_timestamps_the_caller_cannot_supply(api):
    """PRD 3.3: "On every successful submission — whatever the compliance outcome — the
    physical dimension advances `CREATED → SUBMITTED` and `submitted_at` is stamped from
    the logical clock, `item_subtotal_cents` is frozen as the sum of `line_total_cents`
    across **all** of the order's lines regardless of their `line_state`, and
    `charged_cents` is frozen as `item_subtotal_cents` plus `delivery_fee_cents`."

    Design: Corner/entities/corner_submit_stamps_system_fields_from_the_logical_clock
    """
    world = fx.build_unrestricted_world(api, clock=CLOCK, scheduled_delivery_at=EVENING)

    submitted = validate_success(
        api.submit_order(world["order"]["id"], world["customer_headers"])
    )

    assert _instant(submitted["submitted_at"]) == _instant(CLOCK), (
        "the stamp is read off the logical clock, not off any request field; got "
        f"{submitted['submitted_at']!r}"
    )
    assert submitted["dispatched_at"] is None
    assert submitted["delivered_at"] is None
    assert submitted["compliance_state"] == "AUTO_CLEARED"
    assert submitted["fulfillment_state"] == "SUBMITTED"
    assert_cents(submitted["item_subtotal_cents"], 2000, "item_subtotal_cents")
    assert_cents(submitted["charged_cents"], 2600, "charged_cents")


def test_09_a_policy_out_of_range_and_a_policy_off_the_enum_are_both_refused(api):
    """PRD 3.1: "Its `min_age_years` is the minimum completed age in years demanded of
    both purchaser and doorstep recipient, and it must lie between 18 and 25 inclusive."

    Design: Corner/entities/corner_restriction_policy_out_of_range_and_bad_enum_are_rejected
    """
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )

    out_of_range = api.create_restriction_policy(
        f.restriction_policy_payload(jurisdiction["id"], min_age_years=26), ADMIN_HEADERS
    )
    off_the_enum = api.create_restriction_policy(
        f.restriction_policy_payload(jurisdiction["id"], restriction_type="TOBACCO"),
        ADMIN_HEADERS,
    )

    validate_error(out_of_range, ApiErrorId.VALIDATION.value)
    validate_error(off_the_enum, ApiErrorId.VALIDATION.value)
    reread = validate_success(api.get_jurisdiction(jurisdiction["id"], ADMIN_HEADERS))
    assert reread["active_policy_count"] == 0
    policies, meta = validate_paginated(
        api.list_jurisdiction_restriction_policies(jurisdiction["id"], ADMIN_HEADERS)
    )
    assert policies == [], f"neither rejection may have stored a row; got {len(policies)}"
    assert_page_meta(meta, total_count=0)


def _courier_at_the_door_of_an_unrestricted_order(api):
    """An unrestricted order carried to the doorstep with the attempt open."""
    world = fx.build_unrestricted_world(api, clock=CLOCK, scheduled_delivery_at=EVENING)
    order = fx.submit_order(api, world["order"])
    fx.dispatch_order(api, order)
    attempt = fx.open_attempt(api, order, world["courier"], EVENING)
    world.update({"order": order, "attempt": attempt})
    return world


def test_10_a_capture_is_stored_without_a_version_and_reads_back_unchanged(api):
    """PRD 3.6: "Captures are immutable audit rows: as 2.4 states, they carry only `id`
    and `created_at`, with no `updated_at` and no `version`, and no operation modifies or
    deletes them."

    Design: Corner/entities/corner_capture_artifact_row_is_immutable_and_versionless
    """
    world = _courier_at_the_door_of_an_unrestricted_order(api)

    response = api.create_capture(
        world["attempt"]["id"],
        f.capture_payload(
            kind="SIGNATURE", content_hash=f.SIGNATURE_HASH, captured_at=CAPTURED_AT
        ),
        world["courier_headers"],
    )

    created = validate_success(response, expected_status=201)
    assert_versionless_row(created)
    captures, meta = validate_paginated(
        api.list_captures(world["attempt"]["id"], OFFICER_A_HEADERS, {"kind": "SIGNATURE"})
    )
    assert_page_meta(meta, total_count=1)
    stored = captures[0]
    assert stored["kind"] == "SIGNATURE"
    assert stored["content_hash"] == f.SIGNATURE_HASH
    assert _instant(stored["retention_until"]) == RETENTION_HORIZON, (
        "`retention_until` is `captured_at` plus 2555 days; got "
        f"{stored['retention_until']!r}"
    )


def test_11_a_certification_naming_no_courier_is_a_not_found_before_any_score_rule(api):
    """PRD 2.7: "**Body foreign-key existence.** Every foreign key in the request body
    must resolve, in the endpoint's declared field order, else the corresponding not-found
    code with HTTP 404. This tier applies to every creating operation that accepts
    foreign-key fields."

    Design: Corner/entities/corner_courier_certification_with_unknown_parent_courier_not_found
    """
    fx.set_clock(api, CLOCK)
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )

    response = api.create_courier_certification(
        f.courier_certification_payload(NON_EXISTENT_UUID, training_score=92),
        make_partner_manager_headers(partner["id"]),
    )

    validate_error(response, ApiErrorId.COURIER_NOT_FOUND.value)


def test_12_the_auto_opened_case_is_reachable_from_both_of_its_parents(api):
    """PRD 3.7: "**Link two** fires only when link one recorded a *compliance* refusal —
    that is, when `refusal_reason` is one of `UNDERAGE_RECIPIENT`, `ID_MISMATCH`,
    `NO_ACCEPTABLE_ID` or `INTOXICATED_RECIPIENT` — and opens a violation case
    automatically: its `origin` is `AUTO_REFUSAL`, its `delivery_attempt_id` names this
    attempt, its `delivery_partner_id` copies the order's, its `state` opens at `OPEN`,
    and its `severity` is read off a fixed mapping from the refusal reason —
    `UNDERAGE_RECIPIENT` maps to `CRITICAL`, `ID_MISMATCH` to `MAJOR`,
    `INTOXICATED_RECIPIENT` to `MAJOR` and `NO_ACCEPTABLE_ID` to `MINOR`."

    Design: Corner/entities/corner_violation_case_is_reverse_reachable_from_attempt_and_partner
    """
    world = _courier_at_the_door_of_an_unrestricted_order(api)
    partner_id = world["partner"]["id"]
    fx.record_refusal(api, world["attempt"], world["courier"]["id"], "NO_ACCEPTABLE_ID")

    by_attempt, attempt_meta = validate_paginated(
        api.list_violation_cases(
            OFFICER_A_HEADERS, {"delivery_attempt_id": world["attempt"]["id"]}
        )
    )
    by_partner, partner_meta = validate_paginated(
        api.list_violation_cases(
            OFFICER_A_HEADERS, {"delivery_partner_id": partner_id, "state": "OPEN"}
        )
    )

    assert_page_meta(attempt_meta, total_count=1)
    case = by_attempt[0]
    assert case["delivery_attempt_id"] == world["attempt"]["id"]
    assert case["origin"] == "AUTO_REFUSAL"
    assert case["severity"] == "MINOR"
    assert case["state"] == "OPEN"
    assert case["delivery_partner_id"] == partner_id
    assert case["secret_shopper_test_id"] is None
    assert_page_meta(partner_meta, total_count=1)
    assert ids_of(by_partner) == [case["id"]], (
        "the same row must answer both filters, since the edge is reverse-reachable from "
        "each parent"
    )
    partner = fx.read_partner(api, partner_id)
    assert partner["open_case_count"] == 1
    assert partner["open_critical_case_count"] == 0
    assert partner["posture"] == "OPEN"
