"""Customer onboarding defaults, standing-order line economics (per-line
rounding, pinned round-then-sum order), confirm/cancel rules, the
state-before-variety validation order, and the order-lines sub-resource."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_order_line,
    add_order_line_payload,
    assert_customer,
    assert_order_item,
    assert_standing_order,
    confirm_standing_order,
    create_customer,
    create_listed_variety,
    create_standing_order,
    create_variety,
    expected_line_extension_cents,
    get_standing_order,
    make_chef_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import OPS


class TestCustomerOnboarding:
    def test_customer_created_with_zero_credit_and_active(self, api):
        """PRD §3.5: "The customer's `credit_balance_cents` starts at zero — it
        only ever grows through resolved spoilage credits, §3.7 — and
        `is_active` starts true; a deactivated customer cannot place changes."

        Design: Corner/entities/customer_creation_defaults_credit_balance_zero
        """
        resp = api.create_customer(
            {"business_name": "New Resto", "contact_email": "n@n.com",
             "delivery_zone": "NORTH"},
            OPS,
        )
        customer = validate_success(resp, 201)
        assert_customer(customer)
        assert customer["credit_balance_cents"] == 0
        assert customer["is_active"] is True

        fetched = validate_success(api.get_customer(customer["id"], OPS))
        assert fetched["credit_balance_cents"] == 0
        assert fetched["is_active"] is True

    def test_get_missing_customer_returns_404(self, api):
        """PRD §2.9: "Third, the existence of every resource named in the path
        and every foreign key in the body is verified; each resource type has
        its own 404 — `ERR_CUSTOMER_NOT_FOUND`, `ERR_VARIETY_NOT_FOUND`,
        `ERR_SEED_LOT_NOT_FOUND`, `ERR_GERMINATION_TEST_NOT_FOUND`,
        `ERR_CROP_PLAN_NOT_FOUND`, `ERR_TRAY_BATCH_NOT_FOUND`,
        `ERR_STANDING_ORDER_NOT_FOUND`, `ERR_ORDER_ITEM_NOT_FOUND`,
        `ERR_ROUTE_NOT_FOUND`, `ERR_STOP_NOT_FOUND`, `ERR_CREDIT_NOT_FOUND`,
        and `ERR_TRIAL_NOT_FOUND`."

        Design: Corner/entities/get_customer_not_found_returns_404
        """
        resp = api.get_customer(NON_EXISTENT_UUID, OPS)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)


class TestLineEconomics:
    def test_line_extension_rounded_half_up_per_line(self, api):
        """PRD §3.5: "its `line_extension_cents` is computed as the `qty_kg`
        multiplied by the line's `unit_price_cents_per_kg`, rounded half-up to
        whole cents, with each line rounded before any summing."
        PRD §3.5: "optionally a `unit_price_cents_per_kg` — which defaults from
        the variety's `listed_price_cents_per_kg` when omitted"

        Design: Corner/entities/order_item_line_extension_computed
        """
        variety = create_listed_variety(name="Cress", listed_price_cents_per_kg=800)
        customer = create_customer(business_name="R")
        order = create_standing_order(customer)

        item = add_order_line(order["id"], customer, variety["id"], 1.255)
        assert_order_item(item)
        assert item["unit_price_cents_per_kg"] == 800, (
            "Omitted unit price defaults from the variety's listed price")
        assert item["line_extension_cents"] == 1004, (
            "1.255 kg * 800 c/kg = 1004 cents, rounded half-up per line")
        assert item["fulfillment"] == "PLANNED"

    def test_per_line_rounding_then_sum_pins_subtotal(self, api):
        """PRD §2.7: "Where a total is built from per-line amounts, the rounding
        order is pinned: each line is rounded first, and only then are the
        rounded lines summed."
        PRD §3.5: "The order's `weekly_subtotal_cents` — the sum of the
        `line_extension_cents` over all of the order's current lines — is
        recomputed on every line change, and the order's `version` increments
        with each accepted line."

        Design: Difficulty/combinatorial_formula/order_subtotal_per_line_round_then_sum
        """
        variety = create_listed_variety(name="Basil", crop_category="SPECIALTY_HERB",
                                        listed_price_cents_per_kg=100,
                                        days_to_harvest=21,
                                        expected_yield_grams_per_tray=5000,
                                        min_order_grams=100)
        customer = create_customer(business_name="Bakery")
        order = create_standing_order(customer)

        item1 = add_order_line(order["id"], customer, variety["id"], 1.005)
        item2 = add_order_line(order["id"], customer, variety["id"], 1.005)

        # 1.005 kg * 100 c/kg = 100.5 -> 101 per line (half-up).
        assert item1["line_extension_cents"] == 101
        assert item2["line_extension_cents"] == 101

        order_after = get_standing_order(order["id"], customer)
        assert order_after["weekly_subtotal_cents"] == 202, (
            "Round each line first (101 + 101); summing the raw products would "
            "give 201 and is not the pinned order")

    def test_subtotal_is_sum_of_rounded_lines(self, api):
        """PRD §2.7: "Where a total is built from per-line amounts, the rounding
        order is pinned: each line is rounded first, and only then are the
        rounded lines summed."
        PRD §3.5: "The order's `weekly_subtotal_cents` — the sum of the
        `line_extension_cents` over all of the order's current lines — is
        recomputed on every line change, and the order's `version` increments
        with each accepted line."

        Design: Difficulty/combinatorial_formula/order_subtotal_per_line_round_then_sum
        """
        variety = create_listed_variety(name="Basil Trio",
                                        crop_category="SPECIALTY_HERB",
                                        listed_price_cents_per_kg=100,
                                        days_to_harvest=21,
                                        expected_yield_grams_per_tray=5000,
                                        min_order_grams=100)
        customer = create_customer(business_name="Bakery Trio")
        order = create_standing_order(customer)

        item1 = add_order_line(order["id"], customer, variety["id"], 1.005)
        item2 = add_order_line(order["id"], customer, variety["id"], 2.0,
                               unit_price_cents_per_kg=800)
        item3 = add_order_line(order["id"], customer, variety["id"], 1.255,
                               unit_price_cents_per_kg=800)

        expected_total = sum(
            expected_line_extension_cents(i["qty_kg"], i["unit_price_cents_per_kg"])
            for i in (item1, item2, item3))
        assert (item1["line_extension_cents"], item2["line_extension_cents"],
                item3["line_extension_cents"]) == (101, 1600, 1004)
        assert expected_total == 2705

        order_after = get_standing_order(order["id"], customer)
        assert order_after["weekly_subtotal_cents"] == expected_total


class TestConfirmAndCancel:
    def test_confirm_empty_order_rejected(self, api):
        """PRD §3.5: "A confirm requires at least one line — an empty order is
        rejected with `ERR_EMPTY_ORDER` — and carries
        `expected_standing_order_version` like any other guarded write"

        Design: Corner/validations/confirm_empty_order_returns_empty_order
        """
        customer = create_customer(business_name="R5")
        order = create_standing_order(customer)

        resp = api.confirm_standing_order(
            order["id"], {"expected_standing_order_version": order["version"]},
            make_chef_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER)

        after = get_standing_order(order["id"], customer)
        assert after["status"] == "DRAFT", "A rejected confirm leaves the order DRAFT"

    def test_cancelled_order_rejects_line_changes(self, api):
        """PRD §3.5: "the order must still be editable — line edits against an
        order that is neither `DRAFT` nor `CONFIRMED` are rejected with
        `ERR_ORDER_NOT_EDITABLE`"
        PRD §3.5: "Either way the order lands in the terminal `CANCELLED`
        state."

        Design: Corner/state_machines/terminal_state_lockdown_cancelled_order_rejects_lines
        """
        variety = create_listed_variety(name="Dill", crop_category="SPECIALTY_HERB",
                                        days_to_harvest=18,
                                        expected_yield_grams_per_tray=4000,
                                        listed_price_cents_per_kg=2200,
                                        min_order_grams=100)
        customer = create_customer(business_name="R3")
        order = create_standing_order(customer)
        cancelled = validate_success(api.cancel_standing_order(
            order["id"], make_chef_headers(customer["id"])))
        assert cancelled["status"] == "CANCELLED"

        current = get_standing_order(order["id"], customer)
        payload = add_order_line_payload(variety["id"], 1.0, current["version"])
        resp = api.add_order_line(order["id"], payload,
                                  make_chef_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_EDITABLE)


class TestLineAddValidationOrder:
    def test_line_add_reports_state_before_variety_listed_check(self, api):
        """PRD §2.9: "Every request is validated in a fixed priority order, and
        a failure at any step masks all later checks."
        PRD §2.9: "Fourth, state preconditions are checked — the target resource
        must be in a state that admits the operation — producing the
        per-resource 409 rejections such as `ERR_ORDER_NOT_EDITABLE`,
        `ERR_BATCH_NOT_READY`, and `ERR_ROUTE_NOT_DISPATCHED`, with
        `ERR_INVALID_STATE` as the generic state-precondition failure."
        PRD §2.9: "Seventh, temporal business rules are evaluated — the weekly
        change cutoff and the requirement that an orderable variety be listed."

        Design: Difficulty/priority_pair_validation_conflict/line_add_blocked_by_state_before_variety_check
        """
        customer = create_customer(business_name="Pizzeria")
        order = create_standing_order(customer)
        validate_success(api.cancel_standing_order(
            order["id"], make_chef_headers(customer["id"])))
        # The variety is still TRIAL: the temporal/listed check would also fail.
        trial_variety = create_variety(name="Sorrel", crop_category="SPECIALTY_HERB")

        current = get_standing_order(order["id"], customer)
        payload = add_order_line_payload(trial_variety["id"], 1.0, current["version"])
        resp = api.add_order_line(order["id"], payload,
                                  make_chef_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_EDITABLE)

    def test_line_add_with_trial_variety_rejected_not_listed(self, api):
        """PRD §3.5: "then the temporal checks — if the logical clock has moved
        the order into `LOCKED` the add is rejected with
        `ERR_WEEKLY_CHANGE_LOCKED`, and a line naming a variety whose `stage` is
        anything other than `LISTED` is rejected with `ERR_VARIETY_NOT_LISTED`"

        Design: Difficulty/priority_pair_validation_conflict/line_add_blocked_by_state_before_variety_check
        """
        customer = create_customer(business_name="Pizzeria Duo")
        order = create_standing_order(customer)
        trial_variety = create_variety(name="Sorrel", crop_category="SPECIALTY_HERB")
        assert trial_variety["stage"] == "TRIAL"

        payload = add_order_line_payload(trial_variety["id"], 1.0, order["version"])
        resp = api.add_order_line(order["id"], payload,
                                  make_chef_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_VARIETY_NOT_LISTED)


class TestOrderLinesSubResource:
    def test_order_lines_listed_beneath_order(self, api):
        """PRD §3.5: "Order lines may be listed filtered by `standing_order_id`,
        by `variety_id`, and by `fulfillment`, and the lines of one order may be
        listed beneath it."

        Design: Corner/entities/fk_reverse_reachability_standing_order_lines
        """
        variety = create_listed_variety(name="Mache", crop_category="PETITE_GREEN",
                                        listed_price_cents_per_kg=1300)
        customer = create_customer(business_name="FK")
        order = create_standing_order(customer)
        item1 = add_order_line(order["id"], customer, variety["id"], 1.0)
        item2 = add_order_line(order["id"], customer, variety["id"], 2.0)

        resp = api.list_order_lines(order["id"], make_chef_headers(customer["id"]))
        lines, meta = validate_paginated(resp)
        assert len(lines) == 2, "The order's lines are listed beneath it"
        assert {l["id"] for l in lines} == {item1["id"], item2["id"]}
        for line in lines:
            assert_order_item(line)
            assert line["standing_order_id"] == order["id"]


class TestImmediateConsistency:
    def test_confirm_mutation_immediately_visible(self, api):
        """PRD §3.5: "Confirming moves the order from `DRAFT` to `CONFIRMED`."
        PRD §3.5: "A confirm requires at least one line — an empty order is
        rejected with `ERR_EMPTY_ORDER` — and carries
        `expected_standing_order_version` like any other guarded write;
        confirmation recomputes the `weekly_subtotal_cents` and increments
        `version`."

        Design: Corner/consistency_model/mutation_immediately_visible_on_read
        """
        variety = create_listed_variety(name="Borage", crop_category="EDIBLE_FLOWER",
                                        listed_price_cents_per_kg=800,
                                        days_to_harvest=26,
                                        expected_yield_grams_per_tray=2500,
                                        min_order_grams=100)
        customer = create_customer(business_name="R10")
        order = create_standing_order(customer)
        add_order_line(order["id"], customer, variety["id"], 2.4)

        confirmed = confirm_standing_order(order["id"], customer)
        assert confirmed["status"] == "CONFIRMED"

        fetched = get_standing_order(order["id"], customer)
        assert_standing_order(fetched)
        assert fetched["status"] == "CONFIRMED", (
            "The confirm mutation is visible on the very next read")
        assert fetched["weekly_subtotal_cents"] == 1920, (
            "2.4 kg * 800 c/kg = 1920, recomputed at confirm")
