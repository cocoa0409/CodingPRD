"""Order amendment (self-loop with repricing and slot delta), the option-change
cutoff boundary, amendment/confirmation state gates, and order OCC
(PRD §3.5, §2.7, §2.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    amend_order,
    assert_dealer_order,
    book_order,
    book_order_no_options,
    book_order_tower,
    confirm_order,
    create_amend_order_payload,
    create_model,
    create_dealer,
    get_slot,
    make_dealer_principal_headers,
    set_clock,
    setup_bookable_world,
    validate_error,
    validate_success,
)

ANY = TEST_USERS["any_headers"]


class TestAmendSelfLoop:
    def test_amend_allocated_self_loop_preserves_state_and_reprices(self, api):
        """PRD §3.5: "Amendment is a self-loop available only from `WAITLISTED`
        and `ALLOCATED`"
        PRD §3.5: "A successful amendment atomically replaces the
        `OrderOptionLine` rows (old lines deleted, new lines written with fresh
        price and discount snapshots), recomputes `options_total_cents`,
        `surcharge_cents`, `invoice_total_cents`, `required_deposit_cents`, and
        `production_hours`, adjusts an allocated slot's `reserved_hours` by the
        hours delta with the slot's `version` incremented, and increments the
        order's `version`."

        [WAKE-TOWER] (46h, invoice 2917475) amended to [WAKE-TOWER, BALLAST]
        (50h, invoice 3093605): state stays ALLOCATED, version bumps, the slot
        gains the 4-hour delta.

        Design: Difficulty/non_linear_state_machine/dealer_order_self_loop_amend_with_state_preservation
        """
        world = setup_bookable_world(api, capacity_hours=50)
        dealer, model, slot = world["dealer"], world["model"], world["slot"]
        order = book_order_tower(
            api, dealer, model, world["tower"], slot_id=slot["id"]
        )
        v1 = order["version"]
        amended = amend_order(
            api, order, dealer,
            option_package_ids=[world["tower"]["id"], world["ballast"]["id"]],
            deposit_paid_cents=309361,
        )
        assert amended["status"] == "ALLOCATED", "self-loop preserves state"
        assert amended["version"] == v1 + 1, "version bumps despite no state change"
        assert amended["production_hours"] == 50  # 40 base + 6 + 4
        assert amended["invoice_total_cents"] == 3093605
        assert amended["options_total_cents"] == 503500
        assert amended["required_deposit_cents"] == 309361
        assert_dealer_order(amended)
        slot_after = get_slot(api, slot["id"])
        assert slot_after["reserved_hours"] == 50, (
            f"reserved_hours must grow by the 4-hour delta: {slot_after['reserved_hours']}"
        )

    def test_amend_waitlisted_self_loop_no_cutoff(self, api):
        """PRD §3.5: "For a `WAITLISTED` order no cutoff applies at all, since
        no run is bound."
        PRD §3.5: "A successful amendment atomically replaces the
        `OrderOptionLine` rows (old lines deleted, new lines written with fresh
        price and discount snapshots), recomputes `options_total_cents`,
        `surcharge_cents`, `invoice_total_cents`, `required_deposit_cents`, and
        `production_hours`, adjusts an allocated slot's `reserved_hours` by the
        hours delta with the slot's `version` incremented, and increments the
        order's `version`."

        A WAITLISTED order (no slot booked) amends freely even with the clock
        far past any would-be cutoff: state stays WAITLISTED, version bumps,
        pricing recomputes.

        Design: Difficulty/non_linear_state_machine/dealer_order_self_loop_amend_with_state_preservation
        """
        # Book BEFORE any capacity exists so the order lands WAITLISTED.
        model = create_model(api)
        dealer = create_dealer(api)
        order = book_order(api, dealer, model, deposit_paid_cents=257500)
        assert order["status"] == "WAITLISTED"
        assert order["slot_id"] is None
        set_clock(api, "2027-01-01T00:00:00Z")  # far past any run cutoff
        amended = amend_order(api, order, dealer, deposit_paid_cents=300000)
        assert amended["status"] == "WAITLISTED", "self-loop preserves state"
        assert amended["version"] == order["version"] + 1
        assert amended["deposit_paid_cents"] == 300000
        assert_dealer_order(amended)


class TestAmendOcc:
    def test_amend_stale_order_version_returns_412(self, api):
        """PRD §2.7: "Amending an order (`PATCH /dealer-orders/{id}`) requires a
        non-optional `expected_order_version` carrying the client's last
        observed `version` of that order. If the order's current `version` has
        advanced past the supplied value — because another amendment, a
        promotion, or a lifecycle transition landed in between — the request is
        rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412)."

        Design: Corner/validations/occ_stale_order_version_returns_412
        """
        world = setup_bookable_world(api)
        dealer = world["dealer"]
        order = book_order_tower(
            api, dealer, world["model"], world["tower"],
            slot_id=world["slot"]["id"],
        )
        v1 = order["version"]
        amended = amend_order(api, order, dealer, deposit_paid_cents=291748)
        assert amended["version"] == v1 + 1
        # Replay with the now-stale v1.
        resp = api.amend_dealer_order(
            order["id"],
            create_amend_order_payload(v1, deposit_paid_cents=291748),
            make_dealer_principal_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION)


class TestAmendCutoff:
    def test_cutoff_exactly_equal_rejects(self, api):
        """PRD §3.5: "For an `ALLOCATED` order, the clock must be strictly
        before the run's `option_change_cutoff_at` — arriving exactly at the
        cutoff already rejects with `ERR_OPTION_CUTOFF_PASSED`"

        Design: Corner/validations/option_cutoff_passed_boundary_exactly_equal_rejects
        """
        world = setup_bookable_world(api, with_options=False)
        order = book_order_no_options(
            api, world["dealer"], world["model"], slot_id=world["slot"]["id"]
        )
        # Cutoff is 2026-08-05T12:00:00Z; set the clock to exactly that instant.
        set_clock(api, "2026-08-05T12:00:00Z")
        resp = api.amend_dealer_order(
            order["id"],
            create_amend_order_payload(order["version"], deposit_paid_cents=300000),
            make_dealer_principal_headers(world["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OPTION_CUTOFF_PASSED)

    def test_one_second_before_cutoff_allows(self, api):
        """PRD §3.5: "For an `ALLOCATED` order, the clock must be strictly
        before the run's `option_change_cutoff_at` — arriving exactly at the
        cutoff already rejects with `ERR_OPTION_CUTOFF_PASSED`"

        One second before the cutoff the strict inequality holds and the
        amendment succeeds.

        Design: Corner/validations/option_cutoff_one_second_before_allows
        """
        world = setup_bookable_world(api, with_options=False)
        order = book_order_no_options(
            api, world["dealer"], world["model"], slot_id=world["slot"]["id"]
        )
        set_clock(api, "2026-08-05T11:59:59Z")
        amended = validate_success(
            api.amend_dealer_order(
                order["id"],
                create_amend_order_payload(order["version"], deposit_paid_cents=300000),
                make_dealer_principal_headers(world["dealer"]["id"]),
            ),
            200,
        )
        assert amended["version"] == order["version"] + 1
        assert amended["deposit_paid_cents"] == 300000


class TestAmendPriorityPairs:
    def test_cutoff_passed_masks_deposit_shortfall(self, api):
        """PRD §2.9: "Inbound requests are validated against eleven families of
        rules, evaluated in the fixed priority order below; a failure in an
        earlier family surfaces its error and masks every later check."
        PRD §2.9: "9. Temporal business rules: amendment before the option
        cutoff (`ERR_OPTION_CUTOFF_PASSED`)" precedes "11. Fiscal guards: ...
        deposit covers the required amount (`ERR_DEPOSIT_INSUFFICIENT`)".

        Amending after the cutoff with a 1-cent deposit (below any required
        amount) surfaces the temporal error, not the fiscal one.

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_beats_business_fiscal_on_amend_after_cutoff
        """
        world = setup_bookable_world(api)
        dealer = world["dealer"]
        order = book_order_tower(
            api, dealer, world["model"], world["tower"],
            slot_id=world["slot"]["id"],
        )
        set_clock(api, "2026-08-06T00:00:00Z")  # past the 2026-08-05T12:00 cutoff
        resp = api.amend_dealer_order(
            order["id"],
            create_amend_order_payload(
                order["version"],
                option_package_ids=[world["tower"]["id"], world["ballast"]["id"]],
                deposit_paid_cents=1,
            ),
            make_dealer_principal_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OPTION_CUTOFF_PASSED)

    def test_cutoff_passed_masks_capacity_overflow(self, api):
        """PRD §2.9: "Inbound requests are validated against eleven families of
        rules, evaluated in the fixed priority order below; a failure in an
        earlier family surfaces its error and masks every later check."
        PRD §2.9: "9. Temporal business rules: amendment before the option
        cutoff (`ERR_OPTION_CUTOFF_PASSED`)" precedes "11. Fiscal guards:
        dealer quota headroom (`ERR_QUOTA_EXCEEDED`); slot hours capacity
        (`ERR_SLOT_CAPACITY_EXCEEDED`)".

        Amending after the cutoff to a build that would also overflow the slot
        surfaces the temporal error, not the capacity one.

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_beats_business_fiscal_on_amend_after_cutoff
        """
        world = setup_bookable_world(api, capacity_hours=48)
        dealer = world["dealer"]
        order = book_order_tower(
            api, dealer, world["model"], world["tower"],
            slot_id=world["slot"]["id"],
        )
        assert order["production_hours"] == 46  # 46 <= 48 fits at booking
        set_clock(api, "2026-08-06T00:00:00Z")
        # Adding BALLAST would take the build to 50h > 48h capacity.
        resp = api.amend_dealer_order(
            order["id"],
            create_amend_order_payload(
                order["version"],
                option_package_ids=[world["tower"]["id"], world["ballast"]["id"]],
                deposit_paid_cents=309361,
            ),
            make_dealer_principal_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OPTION_CUTOFF_PASSED)


class TestAmendStateGate:
    def test_amend_rejected_on_committed(self, api):
        """PRD §3.5: "Amendment is a self-loop available only from `WAITLISTED`
        and `ALLOCATED`; attempting it from `COMMITTED`, `IN_PRODUCTION`,
        `DELIVERED`, `RETAILED`, or `CANCELLED` is rejected with
        `ERR_INVALID_ORDER_STATE`."

        Design: Corner/state_machines/dealer_order_amend_rejected_on_committed
        """
        world = setup_bookable_world(api, with_options=False)
        dealer = world["dealer"]
        order = book_order_no_options(
            api, dealer, world["model"], slot_id=world["slot"]["id"]
        )
        order = confirm_order(api, order, dealer)
        assert order["status"] == "COMMITTED"
        resp = api.amend_dealer_order(
            order["id"],
            create_amend_order_payload(order["version"], deposit_paid_cents=300000),
            make_dealer_principal_headers(dealer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE)


class TestConfirmStateGate:
    def test_second_confirm_on_committed_rejected(self, api):
        """PRD §3.5: "Confirmation moves an order `ALLOCATED` → `COMMITTED`. It
        requires the order to be `ALLOCATED` — any other state yields
        `ERR_INVALID_ORDER_STATE` — and re-verifies that `deposit_paid_cents`
        covers `required_deposit_cents`, failing with `ERR_DEPOSIT_INSUFFICIENT`
        if a price shift has opened a gap."
        PRD §2.9: entity state preconditions (family 7) surface before fiscal
        guards (family 11).

        A second confirmation of a COMMITTED order fails the state gate with
        ERR_INVALID_ORDER_STATE (HTTP 409), not any fiscal recheck.

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_business_fiscal_on_confirm
        """
        world = setup_bookable_world(api)
        dealer = world["dealer"]
        order = book_order_tower(
            api, dealer, world["model"], world["tower"],
            slot_id=world["slot"]["id"],
        )
        order = confirm_order(api, order, dealer)
        assert order["status"] == "COMMITTED"
        resp = api.confirm_dealer_order(
            order["id"], make_dealer_principal_headers(dealer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE)
        assert resp.status_code == 409, "state family maps to 409, not 422" 

    def test_confirm_waitlisted_rejected(self, api):
        """PRD §3.5: "Confirmation moves an order `ALLOCATED` → `COMMITTED`. It
        requires the order to be `ALLOCATED` — any other state yields
        `ERR_INVALID_ORDER_STATE`"

        A WAITLISTED order holds no slot and cannot be confirmed.

        Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_business_fiscal_on_confirm
        """
        model = create_model(api)
        dealer = create_dealer(api)
        order = book_order_no_options(api, dealer, model)
        assert order["status"] == "WAITLISTED"
        resp = api.confirm_dealer_order(
            order["id"], make_dealer_principal_headers(dealer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE)
