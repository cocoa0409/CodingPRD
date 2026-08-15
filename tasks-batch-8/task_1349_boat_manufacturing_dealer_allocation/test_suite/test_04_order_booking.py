"""Dealer order booking: initial-state routing, show linkage, option
compatibility, foreign-key existence, and the deposit gate (PRD §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_dealer_order,
    book_order,
    book_order_no_options,
    create_boat_show_event_payload,
    create_dealer,
    create_dealer_order_payload,
    create_model,
    create_option,
    create_run,
    create_show,
    create_slot,
    make_dealer_principal_headers,
    set_clock,
    setup_bookable_world,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
ALLOC = TEST_USERS["allocation_manager_headers"]
ANY = TEST_USERS["any_headers"]


class TestInitialStateRouting:
    def test_initial_state_allocated_when_slot_secured(self, api):
        """PRD §3.4: "A secured slot puts the order straight into `ALLOCATED`:
        the slot's `reserved_hours` grows by the order's hours with its
        `version` and `updated_at` refreshed, the dealer's `allocation_used` is
        recounted and `version` incremented, and the order is born at `version`
        1."

        Design: Corner/state_machines/dealer_order_initial_state_allocated_when_slot_secured
        """
        world = setup_bookable_world(api, with_options=False)
        resp = api.create_dealer_order(
            create_dealer_order_payload(
                world["dealer"]["id"], world["model"]["id"],
                deposit_paid_cents=257500, slot_id=world["slot"]["id"],
            ),
            make_dealer_principal_headers(world["dealer"]["id"]),
        )
        order = validate_success(resp, 201)
        assert_dealer_order(order)
        assert order["status"] == "ALLOCATED"
        assert order["slot_id"] == world["slot"]["id"]
        assert order["version"] == 1, "the order is born at version 1"

    def test_initial_state_waitlisted_when_no_slot_fits(self, api):
        """PRD §3.4: "When no slot fits, the order lands in `WAITLISTED` with
        `slot_id` null — the quota gate does not apply to waitlisted entries,
        which by definition hold no committed production."

        Design: Corner/state_machines/dealer_order_initial_state_waitlisted_when_no_slot_fits
        """
        model = create_model(api)
        dealer = create_dealer(api)
        resp = api.create_dealer_order(
            create_dealer_order_payload(
                dealer["id"], model["id"], deposit_paid_cents=257500
            ),
            make_dealer_principal_headers(dealer["id"]),
        )
        order = validate_success(resp, 201)
        assert_dealer_order(order)
        assert order["status"] == "WAITLISTED"
        assert order["slot_id"] is None


class TestModelAndShowLinkage:
    def test_model_not_orderable_blocks_booking(self, api):
        """PRD §3.1: "Orders referencing a `DISCONTINUED` model are refused with
        `ERR_MODEL_NOT_ORDERABLE`."

        Design: Corner/validations/model_not_orderable_blocks_booking
        """
        model = create_model(api, model_code="OLD", status="DISCONTINUED")
        dealer = create_dealer(api)
        resp = api.create_dealer_order(
            create_dealer_order_payload(
                dealer["id"], model["id"], deposit_paid_cents=100000
            ),
            make_dealer_principal_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MODEL_NOT_ORDERABLE)

    def test_boat_show_source_requires_show_event_id(self, api):
        """PRD §3.4: "a `show_event_id` is required when and only when the
        source is `BOAT_SHOW` — supplying one for a `RETAIL` or `FLEET` order,
        or omitting it for a show order, is an `ERR_INVALID_REQUEST`"

        Design: Corner/endpoints/boat_show_source_requires_show_event_id
        """
        model = create_model(api)
        dealer = create_dealer(api)
        payload = create_dealer_order_payload(
            dealer["id"], model["id"], source="BOAT_SHOW",
            deposit_paid_cents=257500,
        )
        resp = api.create_dealer_order(
            payload, make_dealer_principal_headers(dealer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_retail_source_forbids_show_event_id(self, api):
        """PRD §3.4: "a `show_event_id` is required when and only when the
        source is `BOAT_SHOW` — supplying one for a `RETAIL` or `FLEET` order,
        or omitting it for a show order, is an `ERR_INVALID_REQUEST`"

        Design: Corner/endpoints/retail_source_forbids_show_event_id
        """
        model = create_model(api)
        dealer = create_dealer(api)
        show = create_show(api)
        payload = create_dealer_order_payload(
            dealer["id"], model["id"], source="RETAIL",
            deposit_paid_cents=257500, show_event_id=show["id"],
        )
        resp = api.create_dealer_order(
            payload, make_dealer_principal_headers(dealer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_show_order_outside_window_rejected(self, api):
        """PRD §3.4: "A show-sourced order must be created while the clock date
        falls inside its event's closed window, first day through last day
        inclusive; outside it the booking fails with
        `ERR_SHOW_EVENT_NOT_ACTIVE`."

        Design: Corner/validations/boat_show_order_outside_window_rejected
        """
        model = create_model(api)
        dealer = create_dealer(api)
        show = create_show(api, start_date="2026-08-10", end_date="2026-08-15")
        # Default clock is 2026-08-01 (PRD §2.5) — before the window opens.
        resp = api.create_dealer_order(
            create_dealer_order_payload(
                dealer["id"], model["id"], source="BOAT_SHOW",
                show_event_id=show["id"], deposit_paid_cents=257500,
            ),
            make_dealer_principal_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SHOW_EVENT_NOT_ACTIVE)

    def test_show_event_not_found(self, api):
        """PRD §2.9: "Body-referenced foreign keys exist — `model_id`,
        `dealer_id`, `slot_id`, `show_event_id`, `run_id`, `order_id`,
        `hull_id`, `registration_id`, `recall_notice_id`, each element of
        `option_package_ids`, and `incompatible_with_option_id` — otherwise the
        corresponding `ERR_MODEL_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`,
        `ERR_SLOT_NOT_FOUND`, `ERR_SHOW_EVENT_NOT_FOUND`, `ERR_RUN_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_HULL_NOT_FOUND`,
        `ERR_REGISTRATION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, or
        `ERR_OPTION_NOT_FOUND`."

        Design: Corner/errors/error_show_event_not_found_triggerable
        """
        model = create_model(api)
        dealer = create_dealer(api)
        resp = api.create_dealer_order(
            create_dealer_order_payload(
                dealer["id"], model["id"], source="BOAT_SHOW",
                show_event_id=NON_EXISTENT_UUID, deposit_paid_cents=257500,
            ),
            make_dealer_principal_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SHOW_EVENT_NOT_FOUND)


class TestOptionCompatibility:
    def test_option_incompatible_pair_rejected(self, api):
        """PRD §3.1: "incompatibility is symmetric, so if option A declares B,
        then B is treated as incompatible with A even though B's own row says
        nothing."
        PRD §3.5: "the replacement set is re-checked for compatibility, and a
        declared incompatible pair — in either direction — or an option
        belonging to a different model fails with `ERR_OPTION_INCOMPATIBLE`."

        Design: Corner/validations/option_incompatible_pair_rejected
        """
        world = setup_bookable_world(api, with_options=False)
        model, dealer = world["model"], world["dealer"]
        opt_a = create_option(
            api, model["id"], option_code="A", price_cents=100000, production_hours=2
        )
        opt_b = create_option(
            api, model["id"], option_code="B", price_cents=100000, production_hours=2,
            incompatible_with_option_id=opt_a["id"],
        )
        resp = api.create_dealer_order(
            create_dealer_order_payload(
                dealer["id"], model["id"], deposit_paid_cents=300000,
                option_package_ids=[opt_a["id"], opt_b["id"]],
            ),
            make_dealer_principal_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OPTION_INCOMPATIBLE)

    def test_option_from_wrong_model_rejected(self, api):
        """PRD §3.5: "the replacement set is re-checked for compatibility, and a
        declared incompatible pair — in either direction — or an option
        belonging to a different model fails with `ERR_OPTION_INCOMPATIBLE`."

        Design: Corner/validations/option_from_wrong_model_rejected
        """
        m1 = create_model(api, model_code="SP190")
        m2 = create_model(
            api, model_code="SP210", base_price_cents=3000000, production_hours=50
        )
        opt_xl = create_option(
            api, m2["id"], option_code="TOWER-XL", price_cents=450000,
            production_hours=8,
        )
        dealer = create_dealer(api)
        resp = api.create_dealer_order(
            create_dealer_order_payload(
                dealer["id"], m1["id"], deposit_paid_cents=300000,
                option_package_ids=[opt_xl["id"]],
            ),
            make_dealer_principal_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OPTION_INCOMPATIBLE)

    def test_duplicate_option_ids_rejected(self, api):
        """PRD §3.4: "and repeating the same option identifier twice within one
        order is likewise an `ERR_INVALID_REQUEST`."

        Design: Corner/errors/error_duplicate_option_ids_in_order_rejected
        """
        world = setup_bookable_world(api, with_options=True)
        tower = world["tower"]
        resp = api.create_dealer_order(
            create_dealer_order_payload(
                world["dealer"]["id"], world["model"]["id"],
                deposit_paid_cents=500000,
                option_package_ids=[tower["id"], tower["id"]],
            ),
            make_dealer_principal_headers(world["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_option_not_found(self, api):
        """PRD §2.9: "Body-referenced foreign keys exist — `model_id`,
        `dealer_id`, `slot_id`, `show_event_id`, `run_id`, `order_id`,
        `hull_id`, `registration_id`, `recall_notice_id`, each element of
        `option_package_ids`, and `incompatible_with_option_id` — otherwise the
        corresponding `ERR_MODEL_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`,
        `ERR_SLOT_NOT_FOUND`, `ERR_SHOW_EVENT_NOT_FOUND`, `ERR_RUN_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_HULL_NOT_FOUND`,
        `ERR_REGISTRATION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, or
        `ERR_OPTION_NOT_FOUND`."

        Design: Corner/errors/error_option_not_found_triggerable
        """
        model = create_model(api)
        dealer = create_dealer(api)
        resp = api.create_dealer_order(
            create_dealer_order_payload(
                dealer["id"], model["id"], deposit_paid_cents=257500,
                option_package_ids=[NON_EXISTENT_UUID],
            ),
            make_dealer_principal_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OPTION_NOT_FOUND)


class TestForeignKeyExistence:
    def test_body_fk_model_not_found(self, api):
        """PRD §2.9: "Body-referenced foreign keys exist — `model_id`,
        `dealer_id`, `slot_id`, `show_event_id`, `run_id`, `order_id`,
        `hull_id`, `registration_id`, `recall_notice_id`, each element of
        `option_package_ids`, and `incompatible_with_option_id` — otherwise the
        corresponding `ERR_MODEL_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`,
        `ERR_SLOT_NOT_FOUND`, `ERR_SHOW_EVENT_NOT_FOUND`, `ERR_RUN_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_HULL_NOT_FOUND`,
        `ERR_REGISTRATION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, or
        `ERR_OPTION_NOT_FOUND`."

        Design: Corner/validations/body_fk_not_found_returns_404
        """
        dealer = create_dealer(api)
        resp = api.create_dealer_order(
            create_dealer_order_payload(
                dealer["id"], NON_EXISTENT_UUID, deposit_paid_cents=257500
            ),
            make_dealer_principal_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MODEL_NOT_FOUND)

    def test_slot_not_found(self, api):
        """PRD §2.9: "Body-referenced foreign keys exist — `model_id`,
        `dealer_id`, `slot_id`, `show_event_id`, `run_id`, `order_id`,
        `hull_id`, `registration_id`, `recall_notice_id`, each element of
        `option_package_ids`, and `incompatible_with_option_id` — otherwise the
        corresponding `ERR_MODEL_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`,
        `ERR_SLOT_NOT_FOUND`, `ERR_SHOW_EVENT_NOT_FOUND`, `ERR_RUN_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_HULL_NOT_FOUND`,
        `ERR_REGISTRATION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, or
        `ERR_OPTION_NOT_FOUND`."

        Design: Corner/errors/error_slot_not_found_triggerable
        """
        model = create_model(api)
        dealer = create_dealer(api)
        resp = api.create_dealer_order(
            create_dealer_order_payload(
                dealer["id"], model["id"], deposit_paid_cents=257500,
                slot_id=NON_EXISTENT_UUID,
            ),
            make_dealer_principal_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_NOT_FOUND)


class TestDepositGate:
    def test_deposit_insufficient_at_create(self, api):
        """PRD §3.4: "The tendered `deposit_paid_cents` must be at least the
        required amount at booking, amendment, and confirmation alike;
        shortfalls are refused with `ERR_DEPOSIT_INSUFFICIENT`."

        The canonical WAKE-TOWER + BALLAST order invoices 3093605 cents, so the
        RETAIL/STANDARD required deposit is rhu(3093605 * 0.10) = 309361; one
        cent short must fail.

        Design: Corner/validations/deposit_insufficient_at_create
        """
        world = setup_bookable_world(api)
        resp = api.create_dealer_order(
            create_dealer_order_payload(
                world["dealer"]["id"], world["model"]["id"],
                deposit_paid_cents=309360,
                option_package_ids=[world["tower"]["id"], world["ballast"]["id"]],
            ),
            make_dealer_principal_headers(world["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT)


class TestOrderListFilter:
    def test_orders_list_filter_by_status(self, api):
        """PRD §3.4: "The orders collection supports reverse-channel filters by
        `dealer_id`, `model_id`, `slot_id`, `show_event_id`, or `status`."

        Design: Corner/endpoints/dealer_orders_list_filter_by_status
        """
        model = create_model(api)
        dealer = create_dealer(api)
        # No runs or slots exist yet: auto-placement finds nothing, so this
        # order lands WAITLISTED.
        o_wait = book_order(api, dealer, model, deposit_paid_cents=257500)
        assert o_wait["status"] == "WAITLISTED"
        # Now open capacity and book a second order onto it explicitly.
        run = create_run(api)
        slot = create_slot(api, run["id"], slot_code="S1", capacity_hours=200)
        o_al = book_order(
            api, dealer, model, deposit_paid_cents=257500, slot_id=slot["id"]
        )
        assert o_al["status"] == "ALLOCATED"
        data, _meta = validate_paginated(
            api.list_dealer_orders(ANY, params={"status": "WAITLISTED"})
        )
        ids = {row["id"] for row in data}
        assert o_wait["id"] in ids
        assert o_al["id"] not in ids, "ALLOCATED order must not appear in a WAITLISTED filter"
        for row in data:
            assert row["status"] == "WAITLISTED"
