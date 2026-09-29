"""Per-entity field contracts: declared fields, defaults, computed money and identity.

Each test pins one entity's persisted shape at the moment it is written, so an
implementation that silently drops a defaulted field or lets a client set a
server-computed one is caught.
"""

from test_helpers import (
    ADMIN,
    AGENT,
    LOGISTICS,
    ApiErrorId,
    api_client,
    assert_append_only_fields,
    assert_common_fields,
    assert_instant,
    assert_refund_ledger_identity,
    create_bundle,
    create_customer_row,
    create_model,
    customer_payload,
    mattress_model_payload,
    open_return_case,
    pickup_route_payload,
    read_customer,
    set_clock,
    setup_delivered_order,
    trial_abuse_signal_payload,
    trial_order_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestMattressModelCreation:
    """The catalogue row carries its five inputs plus five defaulted policy fields."""

    def test_creating_a_model_returns_every_declared_field_including_the_defaults(self):
        """PRD §3.1: "The trial policy for the model travels with it: `break_in_nights` is the minimum number of nights that must elapse after delivery before a return or a comfort exchange may be requested and defaults to 21 nights with zero permitted as a lower bound, while `trial_nights` is the total in-home trial length counted from delivery and defaults to 100 nights, and must always be strictly greater than `break_in_nights`."

        A KING FIRM model registered with only the five required inputs comes
        back with break_in_nights 21, trial_nights 100, a 25-millimetre
        indentation threshold, a ten-year warranty term and donation_eligible
        true, at version 1 and created_at equal to the logical clock.

        Design: Corner/entities/create_mattress_model_returns_every_declared_field
        """
        set_clock("2026-08-01T00:00:00Z")
        response = api_client.create_mattress_model(
            mattress_model_payload(
                sku="MDL-K-FIRM-E1",
                name="Comfort K Firm",
                firmness="FIRM",
                size="KING",
                list_price_cents=189000,
            ),
            ADMIN,
        )
        model = validate_success(response, 201)

        assert model["sku"] == "MDL-K-FIRM-E1"
        assert model["name"] == "Comfort K Firm"
        assert model["firmness"] == "FIRM"
        assert model["size"] == "KING"
        assert model["list_price_cents"] == 189000
        assert model["break_in_nights"] == 21
        assert model["trial_nights"] == 100
        assert model["indentation_warranty_threshold_mm"] == 25
        assert model["warranty_years"] == 10
        assert model["donation_eligible"] is True
        assert_common_fields(model)
        assert model["version"] == 1
        assert_instant(model["created_at"], "2026-08-01T00:00:00Z", "created_at")

    def test_an_unknown_firmness_value_is_a_malformed_request(self):
        """PRD §3.1: "Registering a mattress model captures its `sku`, which must be unique and non-empty across the catalog, a marketing `name`, the comfort level it ships at as `firmness` (one of `SOFT`, `MEDIUM` or `FIRM`), its `size` (one of `TWIN`, `QUEEN` or `KING`), and its `list_price_cents`, which must be greater than zero and serves as the reference price whenever a comfort exchange has to price a difference between two models."

        PLUSH is not a declared member of the firmness enumeration, so the write
        is refused and no catalogue row is written.

        Design: Corner/entities/create_mattress_model_with_an_unknown_firmness_returns_invalid_request
        """
        set_clock("2026-08-01T00:00:00Z")
        response = api_client.create_mattress_model(
            mattress_model_payload(
                sku="MDL-Q-E9",
                name="Comfort Q Plush",
                firmness="PLUSH",
                size="QUEEN",
                list_price_cents=120000,
            ),
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

        accepted = api_client.create_mattress_model(
            mattress_model_payload(
                sku="MDL-Q-E9",
                name="Comfort Q Plush",
                firmness="MEDIUM",
                size="QUEEN",
                list_price_cents=120000,
            ),
            ADMIN,
        )
        # The rejected write must not have consumed the unique sku, which is only
        # possible if no catalogue row was persisted for it.
        validate_success(accepted, 201)


class TestTrialOrderPersistedShape:
    """What POST /trial-orders wrote is exactly what GET /trial-orders/{id} reads back."""

    def test_reading_an_order_returns_the_stored_entity_with_both_axes_at_their_openings(self):
        """PRD §3.3: "A new order also starts with `goodwill_credit_cents` and `price_match_credit_cents` at zero, `exchange_chain_depth` at zero unless the order was minted by an exchange or a replacement, `exchanged_from_order_id` null unless likewise, `nights_slept` null, `delivered_at` null, and both `break_in_ends_at` and `trial_ends_at` null, since none of the three windows can be computed before the mattress arrives."

        A bundle-free 120000-cent DTC order reads back with the same customer and
        model, a 120000-cent paid principal, no bundle discount, the fulfillment
        axis at CREATED and the trial axis at NOT_STARTED.

        Design: Corner/entities/get_trial_order_by_id_returns_the_stored_entity
        """
        model = create_model(sku="MDL-Q-E2", name="Comfort Q", list_price_cents=120000)
        customer = create_customer_row(
            email="e2@example.com", full_name="Ed Two", household_hash="HH-E2"
        )
        created = validate_success(
            api_client.create_trial_order(
                trial_order_payload(
                    customer["id"], model["id"], channel="DTC", gross_price_cents=120000
                ),
                AGENT,
            ),
            201,
        )

        loaded = validate_success(api_client.get_trial_order(created["id"], AGENT), 200)

        assert loaded["id"] == created["id"]
        assert loaded["customer_id"] == customer["id"]
        assert loaded["model_id"] == model["id"]
        assert loaded["paid_amount_cents"] == 120000
        assert loaded["bundle_discount_cents"] == 0
        assert loaded["fulfillment_status"] == "CREATED"
        assert loaded["trial_status"] == "NOT_STARTED"
        assert loaded["delivered_at"] is None
        assert loaded["nights_slept"] is None
        assert loaded["break_in_ends_at"] is None
        assert loaded["trial_ends_at"] is None

    def test_the_bundle_percent_off_is_computed_into_the_paid_principal(self):
        """PRD §3.3: "When a bundle is attached, `bundle_discount_cents` is the quoted `gross_price_cents` multiplied by the bundle's `percent_off_bps` and divided by 10000, rounded to the nearest whole cent with ties away from zero."

        A 1000-basis-point bundle on a 120000-cent quote discounts 12000 cents,
        so the refundable principal opens at 108000 with the whole of it
        outstanding and nothing yet refunded or retained.

        Design: Corner/entities/trial_order_paid_amount_is_computed_from_the_bundle_percent_off
        """
        model = create_model(sku="MDL-Q-E7", name="Comfort Q", list_price_cents=120000)
        bundle = create_bundle(
            code="BUNDLE-E7",
            unwind_policy="DEDUCT_PRORATED",
            accessory_retail_cents=12340,
            gift_card_cents=7701,
            percent_off_bps=1000,
            requires_accessory_return=False,
        )
        customer = create_customer_row(
            email="e7@example.com", full_name="Gus Seven", household_hash="HH-E7"
        )

        order = validate_success(
            api_client.create_trial_order(
                trial_order_payload(
                    customer["id"],
                    model["id"],
                    gross_price_cents=120000,
                    bundle_id=bundle["id"],
                ),
                AGENT,
            ),
            201,
        )

        assert order["bundle_discount_cents"] == 12000, (
            f"120000 * 1000 / 10000 is 12000 cents, got {order['bundle_discount_cents']}"
        )
        assert order["paid_amount_cents"] == 108000
        assert order["outstanding_refundable_cents"] == 108000
        assert order["refunded_total_cents"] == 0
        assert order["retained_amount_cents"] == 0
        assert order["exchange_chain_depth"] == 0
        assert order["exchanged_from_order_id"] is None
        assert_refund_ledger_identity(order)

    def test_an_absent_order_id_answers_the_order_not_found_code(self):
        """PRD §3.3: "An unknown trial-order identifier — whether it appears in a URL or as an `order_id` in a request body — answers `ERR_ORDER_NOT_FOUND`."

        The caller is authenticated and the identifier is well-formed, so the
        only thing wrong is that no such order exists; the read writes nothing.

        Design: Corner/entities/get_trial_order_with_unknown_id_returns_order_not_found
        """
        customer = create_customer_row(
            email="e4@example.com", full_name="Eve Four", household_hash="HH-E4"
        )

        response = api_client.get_trial_order(
            "00000000-0000-0000-0000-000000000404", AGENT
        )
        validate_error(response, ApiErrorId.ERR_ORDER_NOT_FOUND)

        unchanged = read_customer(customer["id"])
        assert unchanged["version"] == customer["version"], (
            "a read miss must not mutate anything"
        )
        assert unchanged["lifetime_trial_count"] == 0

    def test_an_absent_model_id_in_the_body_answers_the_catalog_not_found_code(self):
        """PRD §3.3: "An unknown customer answers `ERR_CUSTOMER_NOT_FOUND`, an unknown `model_id` or `bundle_id` answers `ERR_CATALOG_NOT_FOUND`, and an unknown `retail_partner_id` answers `ERR_PARTNER_NOT_FOUND`."

        The customer resolves and only the model foreign key is dangling, so the
        create is refused with the catalogue code and no order row is written.

        Design: Corner/entities/create_trial_order_with_an_unknown_model_id_returns_catalog_not_found
        """
        customer = create_customer_row(
            email="e11@example.com", full_name="Jon Eleven", household_hash="HH-E11"
        )

        response = api_client.create_trial_order(
            trial_order_payload(
                customer["id"], "00000000-0000-0000-0000-0000000000cc"
            ),
            AGENT,
        )
        validate_error(response, ApiErrorId.ERR_CATALOG_NOT_FOUND)

        _rows, meta = validate_paginated(
            api_client.list_trial_orders(AGENT, params={"customer_id": customer["id"]})
        )
        assert meta["total_count"] == 0
        assert read_customer(customer["id"])["lifetime_trial_count"] == 0


class TestCustomerIdentityAndCounters:
    """A fresh household record starts clean on every counter."""

    def test_a_new_customer_carries_system_identity_and_clock_stamped_timestamps(self):
        """PRD §3.2: "On creation a customer starts with `status` `ACTIVE`, both abuse scores at zero, and every counter at zero."

        The identity fields are entirely server-assigned: a UUID id, created_at
        equal to the logical clock, updated_at equal to created_at and version 1.

        Design: Corner/entities/create_customer_stamps_system_id_and_clock_timestamps
        """
        clock = set_clock("2026-08-01T00:00:00Z")
        assert_instant(clock["current_utc"], "2026-08-01T00:00:00Z", "current_utc")

        customer = validate_success(
            api_client.create_customer(
                customer_payload(
                    email="e8@example.com",
                    full_name="Hal Eight",
                    household_hash="HH-E8",
                ),
                AGENT,
            ),
            201,
        )

        assert_common_fields(customer)
        assert_instant(customer["created_at"], "2026-08-01T00:00:00Z", "created_at")
        assert_instant(customer["updated_at"], customer["created_at"], "updated_at")
        assert customer["version"] == 1
        assert customer["status"] == "ACTIVE"
        assert customer["abuse_score_rolling"] == 0
        assert customer["abuse_score_lifetime"] == 0
        assert customer["signal_count"] == 0
        assert customer["lifetime_trial_count"] == 0
        assert customer["completed_return_count"] == 0
        assert customer["trial_block_until"] is None

    def test_omitting_the_household_hash_is_a_malformed_request(self):
        """PRD §3.2: "A customer record carries a unique, non-empty `email`, a display `full_name`, and a `household_hash` — an opaque hash of shipping address and surname that acts as the household fraud key."

        household_hash is a required input with no default, so a body that omits
        it is refused before any row is written — proved by the fact that the
        same email is still free afterwards.

        Design: Corner/entities/create_customer_without_household_hash_returns_invalid_request
        """
        set_clock("2026-08-01T00:00:00Z")
        response = api_client.create_customer(
            {"email": "e5@example.com", "full_name": "Fay Five"}, ADMIN
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

        retried = api_client.create_customer(
            {
                "email": "e5@example.com",
                "full_name": "Fay Five",
                "household_hash": "HH-E5",
            },
            ADMIN,
        )
        validate_success(retried, 201)


class TestTrialAbuseSignalIsAppendOnly:
    """The one entity in the system that carries no version counter."""

    def test_a_recorded_signal_exposes_only_the_append_only_common_fields(self):
        """PRD §2.4: "The one exception in this system is the abuse signal record: because signals are append-only and are never edited after they are written, a `TrialAbuseSignal` carries only `id` and `created_at` — it has no `updated_at` and no `version` field at all."

        A HOUSEHOLD_MATCH signal is worth 30 points by type, the server derives
        that weight rather than accepting it, and appending one recomputes the
        customer's scores while leaving the posture ACTIVE at 30 points.

        Design: Corner/entities/trial_abuse_signal_is_append_only_and_exposes_no_version_field
        """
        customer = create_customer_row(
            email="e10@example.com", full_name="Ida Ten", household_hash="HH-E10"
        )

        signal = validate_success(
            api_client.create_trial_abuse_signal(
                trial_abuse_signal_payload(
                    customer["id"],
                    "HOUSEHOLD_MATCH",
                    recorded_at="2026-08-01T00:00:00Z",
                    source_note="same household hash",
                ),
                ADMIN,
            ),
            201,
        )

        assert signal["weight"] == 30, (
            f"HOUSEHOLD_MATCH is worth 30 points by type, got {signal['weight']}"
        )
        assert_instant(signal["recorded_at"], "2026-08-01T00:00:00Z", "recorded_at")
        assert_append_only_fields(signal)

        rows, meta = validate_paginated(
            api_client.list_customer_abuse_signals(
                customer["id"], ADMIN, params={"signal_type": "HOUSEHOLD_MATCH"}
            )
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1

        loaded = read_customer(customer["id"])
        assert loaded["signal_count"] == 1
        assert loaded["abuse_score_rolling"] == 30
        assert loaded["status"] == "ACTIVE"


class TestPickupRouteDefaults:
    """A route created without a buffer takes the declared 30-minute default."""

    def test_omitting_buffer_minutes_applies_the_default_of_thirty(self):
        """PRD §3.7: "An optional `buffer_minutes` sets the mandatory drive buffer that must separate two slots on the route; it defaults to 30 minutes and may not be negative."

        The route also opens at DRAFT with an empty capacity ledger: zero units
        booked and all seven units available.

        Design: Corner/entities/create_pickup_route_without_buffer_minutes_applies_the_default_30
        """
        set_clock("2026-08-01T00:00:00Z")
        payload = pickup_route_payload(
            region_code="CA",
            route_date="2026-09-15",
            window_start_at="2026-09-15T08:00:00Z",
            window_end_at="2026-09-15T18:00:00Z",
            capacity_units=7,
        )
        payload.pop("buffer_minutes", None)

        route = validate_success(api_client.create_pickup_route(payload, LOGISTICS), 201)

        assert route["buffer_minutes"] == 30, (
            f"buffer_minutes defaults to 30, got {route['buffer_minutes']}"
        )
        assert route["status"] == "DRAFT"
        assert route["capacity_units"] == 7
        assert route["booked_units"] == 0
        assert route["available_units"] == 7


class TestReturnCaseListingPagination:
    """Three cases split across two pages of two."""

    def test_the_two_pages_report_one_total_count_and_flip_has_more(self):
        """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`, `total_count` (the number of records matching the filters before pagination is applied) and `has_more` (true when records remain beyond the current page)."

        With three return cases open, a two-row window at offset 0 reports
        total_count 3 with has_more true, and the same window at offset 2 returns
        the last row with has_more false; together the pages hold the three
        distinct case ids and no duplicates.

        Design: Corner/entities/list_return_cases_paginates_with_total_count_and_has_more
        """
        model = create_model(sku="MDL-Q-E3", name="Comfort Q", list_price_cents=120000)
        opened = []
        for tag, name in (("a", "Ann Three"), ("b", "Ben Three"), ("c", "Cal Three")):
            scenario = setup_delivered_order(
                model=model,
                customer_overrides={
                    "email": f"e3{tag}@example.com",
                    "full_name": name,
                    "household_hash": f"HH-E3{tag.upper()}",
                },
            )
            opened.append(scenario)

        set_clock("2026-08-25T00:00:00Z")
        case_ids = {
            open_return_case(s["order"]["id"], s["customer_headers"])["id"]
            for s in opened
        }
        assert len(case_ids) == 3

        first_rows, first_meta = validate_paginated(
            api_client.list_return_cases(AGENT, params={"limit": 2, "offset": 0})
        )
        assert len(first_rows) == 2, f"a limit of 2 must return 2 rows, got {len(first_rows)}"
        assert first_meta["total_count"] == 3, (
            "total_count counts every matching record before pagination, got "
            f"{first_meta['total_count']}"
        )
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0

        second_rows, second_meta = validate_paginated(
            api_client.list_return_cases(AGENT, params={"limit": 2, "offset": 2})
        )
        assert len(second_rows) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert second_meta["offset"] == 2

        paged_ids = [row["id"] for row in first_rows + second_rows]
        assert len(paged_ids) == len(set(paged_ids)), (
            f"the two pages must not repeat a row, got {paged_ids}"
        )
        assert set(paged_ids) == case_ids
