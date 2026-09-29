"""Entity creation, read and list contracts of the home-cook meal marketplace API.

The concerns covered here are the ones the PRD fixes per entity rather than per
workflow: which input fields a creation requires, which fields the server fills
in from a declared default, which fields it computes or stamps itself, which
values an enum or a typed field will accept, the not-found identity each
collection owns, and the order in which a body's foreign keys are resolved.

The harness restarts the API server before every test, so each test builds all
of its own state from scratch through PRD-declared endpoints only.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ANONYMOUS_HEADERS,
    DEFAULT_WEEKLY_CAPACITY_MEALS,
    DINER_ONE,
    DINER_ONE_HEADERS,
    NON_EXISTENT_UUID,
    REVIEWER_ONE_HEADERS,
    STANDARD_LABEL_FIELDS,
    ApiErrorId,
    assert_common_fields,
    assert_fields,
    assert_money_is_integer,
    cook_payload,
    food_handler_cert_payload,
    make_cook_headers,
    menu_item_payload,
    order_payload,
    pickup_hub_payload,
    state_policy_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

ALL_KITCHEN_TYPES = ["HOME_COTTAGE", "HOME_INSPECTED", "COMMERCIAL_SHARED"]


def test_01_state_policy_creation_echoes_every_declared_field(api):
    """Registering a state policy echoes all seven declared configuration fields verbatim.

    PRD: "Alongside the code the administrator declares `cottage_food_annual_cap_cents`, the per-calendar-year gross cottage-food revenue ceiling for one cook in that state, which must be zero or greater; `allowed_kitchen_types`, a non-empty subset of `HOME_COTTAGE`, `HOME_INSPECTED` and `COMMERCIAL_SHARED`; `tcs_requires_commercial_kitchen`, a flag that when true confines time-and-temperature-control-for-safety dishes to cooks whose verified kitchen is `COMMERCIAL_SHARED`; `max_shelf_life_days_non_refrigerated`, at least 1, the ceiling on a declarable shelf life for a dish that needs no refrigeration; `label_required_fields`, a non-empty array of lower-snake-case label keys every dish sold in that state must print; and `cert_validity_max_days`, at least 1, the longest span the state will honour between a food-handler certificate's issue and expiry dates."
    Design: Corner/entities/state_policy_creation_returns_all_declared_fields
    """
    payload = state_policy_payload(
        state_code="CA",
        cottage_food_annual_cap_cents=5_000_000,
        allowed_kitchen_types=list(ALL_KITCHEN_TYPES),
        tcs_requires_commercial_kitchen=True,
        max_shelf_life_days_non_refrigerated=14,
        label_required_fields=list(STANDARD_LABEL_FIELDS),
        cert_validity_max_days=1825,
    )
    policy = validate_success(api.create_state_policy(payload, ADMIN_HEADERS), 201)

    assert_money_is_integer(policy, "cottage_food_annual_cap_cents")
    assert_fields(
        policy,
        state_code="CA",
        cottage_food_annual_cap_cents=5_000_000,
        allowed_kitchen_types=list(ALL_KITCHEN_TYPES),
        tcs_requires_commercial_kitchen=True,
        max_shelf_life_days_non_refrigerated=14,
        label_required_fields=list(STANDARD_LABEL_FIELDS),
        cert_validity_max_days=1825,
    )
    assert len(policy["label_required_fields"]) == 5, policy["label_required_fields"]
    assert "cottage_food_disclaimer" in policy["label_required_fields"]


def test_02_state_policy_creation_stamps_identity_and_first_version(api):
    """A created state policy carries a minted id, both timestamps and version 1.

    PRD: "`version` starts at 1 when the row is created and increments by one on every mutation of that row, including mutations the row suffers as a downstream consequence of somebody else's write."
    Design: Corner/entities/state_policy_creation_returns_all_declared_fields
    """
    response = api.create_state_policy(state_policy_payload(state_code="CA"), ADMIN_HEADERS)
    policy = validate_success(response, 201)

    assert response.json()["response_type"] == "object", response.json()["response_type"]
    assert_common_fields(policy, expected_version=1)


def test_03_cook_creation_defaults_weekly_capacity_meals_to_40(api):
    """Self-registration that omits weekly_capacity_meals lands on the declared default 40.

    PRD: "Optionally the cook may set `weekly_capacity_meals`, an upper bound of at least 1 on the capacity of any single production window they later open; when omitted it defaults to 40."
    Design: Corner/entities/cook_creation_applies_declared_defaults
    """
    fx.create_state_policy(api, state_code="CA", allowed_kitchen_types=list(ALL_KITCHEN_TYPES))

    payload = cook_payload(
        legal_name="Dara Osei",
        state_code="CA",
        claimed_kitchen_type="HOME_COTTAGE",
        weekly_capacity_meals=None,
    )
    assert "weekly_capacity_meals" not in payload, payload

    cook = validate_success(api.create_cook(payload, ANONYMOUS_HEADERS), 201)
    assert_fields(cook, weekly_capacity_meals=DEFAULT_WEEKLY_CAPACITY_MEALS)


def test_04_cook_creation_starts_in_declared_initial_values(api):
    """A new cook starts DRAFT / CLEAR with score 100, UNDER_CAP and four zeroed counters.

    PRD: "A new cook starts with `onboarding_status` `DRAFT`, `compliance_standing` `CLEAR`, `safety_score` 100, a null `standing_reason`, a null `verified_kitchen_type`, `cap_status` `UNDER_CAP`, and every money counter — `ytd_gross_sales_cents`, `ytd_cottage_revenue_cents`, `pending_payout_cents`, `lifetime_paid_cents` — at zero."
    Design: Corner/entities/cook_creation_applies_declared_defaults
    """
    fx.create_state_policy(api, state_code="CA", allowed_kitchen_types=list(ALL_KITCHEN_TYPES))

    cook = validate_success(
        api.create_cook(
            cook_payload(
                legal_name="Dara Osei", state_code="CA", claimed_kitchen_type="HOME_COTTAGE"
            ),
            ANONYMOUS_HEADERS,
        ),
        201,
    )

    assert_money_is_integer(
        cook,
        "ytd_gross_sales_cents",
        "ytd_cottage_revenue_cents",
        "pending_payout_cents",
        "lifetime_paid_cents",
    )
    assert_fields(
        cook,
        onboarding_status="DRAFT",
        compliance_standing="CLEAR",
        safety_score=100,
        standing_reason=None,
        verified_kitchen_type=None,
        cap_status="UNDER_CAP",
        ytd_gross_sales_cents=0,
        ytd_cottage_revenue_cents=0,
        pending_payout_cents=0,
        lifetime_paid_cents=0,
    )
    assert_common_fields(cook, expected_version=1)


def test_05_cook_creation_missing_email_is_rejected_as_invalid_request(api):
    """A self-registration with no `email` field is rejected as a body-shape failure.

    PRD: "Request-body well-formedness on every creating or mutating request: the body parses, every required input field is present, every field carries its declared JSON type, every enum-valued field carries a declared member, money and quantity fields are integers, and date and timestamp fields are ISO 8601 — `ERR_INVALID_REQUEST`, 422."
    Design: Corner/entities/cook_creation_missing_required_field_rejected
    """
    fx.create_state_policy(api, state_code="CA", allowed_kitchen_types=list(ALL_KITCHEN_TYPES))

    response = api.create_cook(
        {"legal_name": "No Email", "state_code": "CA", "claimed_kitchen_type": "HOME_COTTAGE"},
        ANONYMOUS_HEADERS,
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST, 422)

    rows, meta = validate_paginated(api.list_cooks(ADMIN_HEADERS, {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


def test_06_cook_creation_rejects_undeclared_enum_and_non_integer_capacity(api):
    """A kitchen type outside the three declared members and a non-integer capacity are both body-shape failures.

    PRD: "Request-body well-formedness on every creating or mutating request: the body parses, every required input field is present, every field carries its declared JSON type, every enum-valued field carries a declared member, money and quantity fields are integers, and date and timestamp fields are ISO 8601 — `ERR_INVALID_REQUEST`, 422."
    Design: Corner/entities/cook_creation_rejects_undeclared_enum_and_wrong_type
    """
    fx.create_state_policy(api, state_code="CA", allowed_kitchen_types=list(ALL_KITCHEN_TYPES))

    enum_response = api.create_cook(
        cook_payload(
            legal_name="Garage Cook",
            email="garage@example.com",
            state_code="CA",
            claimed_kitchen_type="GARAGE",
        ),
        ANONYMOUS_HEADERS,
    )
    validate_error(enum_response, ApiErrorId.INVALID_REQUEST, 422)

    type_response = api.create_cook(
        cook_payload(
            legal_name="Wordy Capacity",
            email="wordy@example.com",
            state_code="CA",
            claimed_kitchen_type="HOME_COTTAGE",
            weekly_capacity_meals="forty",
        ),
        ANONYMOUS_HEADERS,
    )
    validate_error(type_response, ApiErrorId.INVALID_REQUEST, 422)

    # An undeclared member is a shape failure, not the allowed-kitchen-types gate,
    # which only judges values that are declared members.
    for response in (enum_response, type_response):
        assert response.json()["data"]["error_id"] != ApiErrorId.KITCHEN_TYPE_NOT_ALLOWED

    rows, meta = validate_paginated(api.list_cooks(ADMIN_HEADERS, {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 0, meta
    assert rows == [], rows


def test_07_menu_item_label_compliance_status_is_computed_from_the_state_policy(api):
    """Two dishes created back to back diverge on label_compliance_status by their label_fields alone.

    PRD: "It reads `COMPLIANT` when the set of `label_fields` contains every key in the governing state policy's `label_required_fields`, and `MISSING_FIELDS` otherwise; its default before any computation is `MISSING_FIELDS`."
    Design: Corner/entities/menu_item_label_compliance_status_computed_from_state_policy
    """
    fx.create_state_policy(
        api,
        state_code="CA",
        allowed_kitchen_types=list(ALL_KITCHEN_TYPES),
        label_required_fields=list(STANDARD_LABEL_FIELDS),
    )
    cook = fx.register_cook(api, state_code="CA", claimed_kitchen_type="HOME_COTTAGE")
    cook_headers = make_cook_headers(cook["id"])
    incomplete_label_fields = [key for key in STANDARD_LABEL_FIELDS if key != "net_weight"]

    incomplete_item = validate_success(
        api.create_menu_item(
            menu_item_payload(
                cook["id"],
                name="Unlabelled Bun",
                food_category="BAKED_NON_TCS",
                allergens=["WHEAT"],
                shelf_life_days=5,
                unit_price_cents=500,
                label_fields=list(incomplete_label_fields),
            ),
            cook_headers,
        ),
        201,
    )
    complete_item = validate_success(
        api.create_menu_item(
            menu_item_payload(
                cook["id"],
                name="Fully Labelled Bun",
                food_category="BAKED_NON_TCS",
                allergens=["WHEAT"],
                shelf_life_days=5,
                unit_price_cents=500,
                label_fields=list(STANDARD_LABEL_FIELDS),
            ),
            cook_headers,
        ),
        201,
    )

    assert_fields(
        incomplete_item,
        label_fields=list(incomplete_label_fields),
        label_compliance_status="MISSING_FIELDS",
    )
    assert_fields(
        complete_item,
        label_fields=list(STANDARD_LABEL_FIELDS),
        label_compliance_status="COMPLIANT",
    )


def test_08_menu_item_creation_applies_declared_review_defaults(api):
    """A drafted dish starts DRAFT at revision_round 0 with the three approval fields null.

    PRD: "The item is created in `review_status` `DRAFT` with `revision_round` at 0, a null `approved_by_user_id`, a null `approved_at` and a null `delist_reason`."
    Design: Corner/entities/menu_item_label_compliance_status_computed_from_state_policy
    """
    fx.create_state_policy(
        api,
        state_code="CA",
        allowed_kitchen_types=list(ALL_KITCHEN_TYPES),
        label_required_fields=list(STANDARD_LABEL_FIELDS),
    )
    cook = fx.register_cook(api, state_code="CA", claimed_kitchen_type="HOME_COTTAGE")

    item = validate_success(
        api.create_menu_item(
            menu_item_payload(
                cook["id"],
                name="Fully Labelled Bun",
                food_category="BAKED_NON_TCS",
                allergens=["WHEAT"],
                shelf_life_days=5,
                unit_price_cents=500,
                label_fields=list(STANDARD_LABEL_FIELDS),
            ),
            make_cook_headers(cook["id"]),
        ),
        201,
    )

    assert_money_is_integer(item, "unit_price_cents")
    assert_fields(
        item,
        cook_id=cook["id"],
        review_status="DRAFT",
        revision_round=0,
        approved_by_user_id=None,
        approved_at=None,
        delist_reason=None,
    )
    assert_common_fields(item, expected_version=1)


def test_09_order_cook_id_is_copied_from_the_referenced_menu_item(api):
    """A client-supplied cook_id on order placement is ignored in favour of the dish's owner.

    PRD: "The order's `cook_id` is **not** a client input — it is copied from the referenced menu item's `cook_id`, and a client-supplied value is ignored."
    Design: Corner/entities/order_system_fields_stamped_from_headers_and_parent_rows
    """
    setup = fx.selling_cook(api)

    payload = order_payload(
        setup.menu_item["id"],
        setup.window["id"],
        setup.zone["id"],
        quantity=2,
        diner_contact_email="dx@example.com",
        cook_id=NON_EXISTENT_UUID,
    )
    order = validate_success(api.create_order(payload, DINER_ONE_HEADERS), 201)

    assert_fields(
        order,
        cook_id=setup.cook_id,
        menu_item_id=setup.menu_item["id"],
        production_window_id=setup.window["id"],
        delivery_zone_id=setup.zone["id"],
        quantity=2,
    )
    assert order["cook_id"] != NON_EXISTENT_UUID, order["cook_id"]


def test_10_order_records_the_acting_diner_user_id_from_the_header(api):
    """The order's diner_user_id is taken from the acting caller's X-User-ID, not from the body.

    PRD: "The acting diner's `X-User-ID` is recorded as `diner_user_id`."
    Design: Corner/entities/order_system_fields_stamped_from_headers_and_parent_rows
    """
    setup = fx.selling_cook(api)

    order = validate_success(
        api.create_order(
            order_payload(
                setup.menu_item["id"],
                setup.window["id"],
                setup.zone["id"],
                quantity=2,
                diner_contact_email="dx@example.com",
            ),
            DINER_ONE_HEADERS,
        ),
        201,
    )

    assert_fields(order, diner_user_id=DINER_ONE, diner_contact_email="dx@example.com")


def test_11_order_placement_leaves_routing_and_capture_fields_null(api):
    """A placed order sits PLACED / AUTHORIZED with null routing and capture fields and zeroed refund counters.

    PRD: "Finally the meals are admitted against the window using the pinned evaluation order of §3.3, and the order comes into existence with `fulfillment_status` `PLACED`, `payment_status` `AUTHORIZED`, a null `routing_mode`, a null `pickup_hub_id`, a null `captured_at`, a null `effective_year`, a null `cancelled_reason`, and all four refund counters — `refunded_cents`, `cook_chargeback_cents`, `commission_reversed_cents` and `platform_absorbed_cents` — at zero."
    Design: Corner/entities/order_system_fields_stamped_from_headers_and_parent_rows
    """
    setup = fx.selling_cook(api)

    order = validate_success(
        api.create_order(
            order_payload(
                setup.menu_item["id"],
                setup.window["id"],
                setup.zone["id"],
                quantity=2,
                diner_contact_email="dx@example.com",
            ),
            DINER_ONE_HEADERS,
        ),
        201,
    )

    assert_money_is_integer(
        order,
        "refunded_cents",
        "cook_chargeback_cents",
        "commission_reversed_cents",
        "platform_absorbed_cents",
    )
    assert_fields(
        order,
        fulfillment_status="PLACED",
        payment_status="AUTHORIZED",
        routing_mode=None,
        pickup_hub_id=None,
        captured_at=None,
        effective_year=None,
        cancelled_reason=None,
        refunded_cents=0,
        cook_chargeback_cents=0,
        commission_reversed_cents=0,
        platform_absorbed_cents=0,
    )
    assert_common_fields(order, expected_version=1)


def test_12_state_policy_read_is_public_and_round_trips_every_stored_field(api):
    """An anonymous caller reads a state policy by id and every stored field comes back unchanged.

    PRD: "Anonymous callers may self-register a cook and read the public catalogue of state policies, menu items, delivery zones and pickup hubs."
    Design: Corner/entities/state_policy_retrieval_returns_stored_row
    """
    policy = fx.create_state_policy(
        api,
        state_code="CA",
        cottage_food_annual_cap_cents=5_000_000,
        allowed_kitchen_types=list(ALL_KITCHEN_TYPES),
        label_required_fields=list(STANDARD_LABEL_FIELDS),
        cert_validity_max_days=1825,
    )

    response = api.get_state_policy(policy["id"], ANONYMOUS_HEADERS)
    read_back = validate_success(response, 200)

    assert response.json()["response_type"] == "object", response.json()["response_type"]
    assert_fields(
        read_back,
        id=policy["id"],
        state_code="CA",
        cottage_food_annual_cap_cents=5_000_000,
        allowed_kitchen_types=list(ALL_KITCHEN_TYPES),
        label_required_fields=list(STANDARD_LABEL_FIELDS),
        cert_validity_max_days=1825,
    )


def test_13_menu_item_listing_reports_total_count_and_has_more_across_pages(api):
    """Three dishes read two at a time give has_more true then false with total_count 3 throughout.

    PRD: "Four pagination fields appear in the `meta` object of a list response — `limit`, `offset`, `total_count` and `has_more` — where `total_count` is the number of rows matching the filter before pagination is applied and `has_more` is true exactly when rows remain beyond the current page."
    Design: Corner/entities/menu_items_listing_paginates_with_total_count_and_has_more
    """
    fx.create_state_policy(
        api,
        state_code="CA",
        allowed_kitchen_types=list(ALL_KITCHEN_TYPES),
        label_required_fields=list(STANDARD_LABEL_FIELDS),
    )
    cook = fx.register_cook(api, state_code="CA", claimed_kitchen_type="HOME_COTTAGE")
    created = [
        fx.draft_menu_item(
            api,
            cook,
            name=name,
            food_category="BAKED_NON_TCS",
            allergens=["WHEAT"],
            shelf_life_days=5,
            unit_price_cents=price,
            label_fields=list(STANDARD_LABEL_FIELDS),
        )
        for name, price in (("Item One", 500), ("Item Two", 600), ("Item Three", 700))
    ]

    page_one, meta_one = validate_paginated(
        api.list_menu_items(ANONYMOUS_HEADERS, {"cook_id": cook["id"], "limit": 2, "offset": 0})
    )
    page_two, meta_two = validate_paginated(
        api.list_menu_items(ANONYMOUS_HEADERS, {"cook_id": cook["id"], "limit": 2, "offset": 2})
    )

    assert len(page_one) == 2, page_one
    assert meta_one["total_count"] == 3, meta_one
    assert meta_one["limit"] == 2 and meta_one["offset"] == 0, meta_one
    assert meta_one["has_more"] is True, meta_one

    assert len(page_two) == 1, page_two
    assert meta_two["total_count"] == 3, meta_two
    assert meta_two["limit"] == 2 and meta_two["offset"] == 2, meta_two
    assert meta_two["has_more"] is False, meta_two

    served = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert len(set(served)) == 3, served
    assert set(served) == {item["id"] for item in created}


def test_14_onboarding_document_listing_composes_the_cook_and_doc_type_filters(api):
    """Filtering onboarding documents by cook_id and then also by doc_type narrows two rows to one.

    PRD: "Onboarding documents filter by `cook_id`, by `doc_type`, by `review_status`, and by `superseded_by_document_id` — that last one lets a reviewer walk the supersession chain backwards from the document that replaced an older row."
    Design: Corner/entities/onboarding_documents_listing_filters_by_cook_and_doc_type
    """
    fx.create_state_policy(api, state_code="CA", allowed_kitchen_types=list(ALL_KITCHEN_TYPES))
    cook = fx.register_cook(api, state_code="CA", claimed_kitchen_type="HOME_COTTAGE")
    certificate = fx.submit_food_handler_cert(api, cook)
    inspection = fx.submit_kitchen_inspection(api, cook)

    all_rows, all_meta = validate_paginated(
        api.list_onboarding_documents(
            REVIEWER_ONE_HEADERS, {"cook_id": cook["id"], "limit": 10, "offset": 0}
        )
    )
    assert all_meta["total_count"] == 2, all_meta
    assert all_meta["has_more"] is False, all_meta
    assert {row["id"] for row in all_rows} == {certificate["id"], inspection["id"]}

    cert_rows, cert_meta = validate_paginated(
        api.list_onboarding_documents(
            REVIEWER_ONE_HEADERS,
            {
                "cook_id": cook["id"],
                "doc_type": "FOOD_HANDLER_CERT",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert cert_meta["total_count"] == 1, cert_meta
    assert [row["id"] for row in cert_rows] == [certificate["id"]], cert_rows
    assert inspection["id"] not in {row["id"] for row in cert_rows}


def test_15_unknown_path_id_returns_the_collection_specific_not_found_code(api):
    """Each single-resource read of an unknown id answers with its own collection's 404 code.

    PRD: "First, the identifier in the URL path segment is resolved; if it does not exist, the request fails with the not-found code for that collection — `ERR_COOK_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_MENU_ITEM_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_HUB_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_REFUND_NOT_FOUND` or `ERR_STATE_POLICY_NOT_FOUND`, each HTTP 404."
    Design: Corner/entities/unknown_path_id_returns_entity_specific_not_found
    """
    probes = [
        (api.get_state_policy, ApiErrorId.STATE_POLICY_NOT_FOUND),
        (api.get_cook, ApiErrorId.COOK_NOT_FOUND),
        (api.get_onboarding_document, ApiErrorId.DOCUMENT_NOT_FOUND),
        (api.get_menu_item, ApiErrorId.MENU_ITEM_NOT_FOUND),
        (api.get_production_window, ApiErrorId.WINDOW_NOT_FOUND),
        (api.get_delivery_zone, ApiErrorId.ZONE_NOT_FOUND),
        (api.get_pickup_hub, ApiErrorId.HUB_NOT_FOUND),
        (api.get_order, ApiErrorId.ORDER_NOT_FOUND),
        (api.get_safety_incident, ApiErrorId.INCIDENT_NOT_FOUND),
        (api.get_payout_statement, ApiErrorId.STATEMENT_NOT_FOUND),
        (api.get_refund_event, ApiErrorId.REFUND_NOT_FOUND),
    ]

    for read_one, expected_error_id in probes:
        response = read_one(NON_EXISTENT_UUID, ADMIN_HEADERS)
        assert response.json()["response_type"] == "error", response.json()
        validate_error(response, expected_error_id, 404)


def test_16_body_foreign_keys_are_resolved_before_any_other_check(api):
    """An unresolvable cook_id or delivery_zone_id in the body fails with that collection's 404 code.

    PRD: "Every foreign-key identifier in the request body resolves, checked left to right in declaration order — the collection-specific 404 code."
    Design: Corner/entities/body_foreign_keys_validated_left_to_right_not_found
    """
    fx.create_state_policy(api, state_code="CA", allowed_kitchen_types=list(ALL_KITCHEN_TYPES))
    cook = fx.register_cook(api, state_code="CA", claimed_kitchen_type="HOME_COTTAGE")
    assert cook["version"] == 1, cook["version"]

    # The document carries the version guard, yet the unresolvable cook_id is reported first.
    document_response = api.create_onboarding_document(
        food_handler_cert_payload(
            NON_EXISTENT_UUID,
            cook["version"],
            certificate_number="FH-0001",
            issuing_authority="CA DPH",
            issued_on="2026-01-15",
            expires_on="2028-01-15",
        ),
        ADMIN_HEADERS,
    )
    validate_error(document_response, ApiErrorId.COOK_NOT_FOUND, 404)

    hub_response = api.create_pickup_hub(
        pickup_hub_payload(
            NON_EXISTENT_UUID,
            name="Ghost Hub",
            address="1 Nowhere St",
            slot_capacity_orders=4,
            hub_window_start_at="2026-08-08T15:00:00Z",
            hub_window_end_at="2026-08-08T19:00:00Z",
        ),
        ADMIN_HEADERS,
    )
    validate_error(hub_response, ApiErrorId.ZONE_NOT_FOUND, 404)

    documents, document_meta = validate_paginated(
        api.list_onboarding_documents(REVIEWER_ONE_HEADERS, {"limit": 10, "offset": 0})
    )
    assert document_meta["total_count"] == 0, document_meta
    assert documents == [], documents

    hubs, hub_meta = validate_paginated(
        api.list_pickup_hubs(ADMIN_HEADERS, {"limit": 10, "offset": 0})
    )
    assert hub_meta["total_count"] == 0, hub_meta
    assert hubs == [], hubs

    assert fx.read_cook(api, cook["id"])["version"] == 1
