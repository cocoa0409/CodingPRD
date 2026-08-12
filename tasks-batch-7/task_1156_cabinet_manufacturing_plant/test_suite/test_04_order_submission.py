"""Order submission: preconditions, provisional pricing, tiers, credit gate."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_box_line_payload,
    create_dealer_payload,
    create_finish_spec_payload,
    create_modification_payload,
    get_success_data,
    is_iso8601_timestamp,
    make_dealer_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["plant_admin_headers"]
ENGINEER = TEST_USERS["engineer_headers"]


def _dealer_with_order(price_level="L3", credit=100000000, line_qty=2, line_unit=100000,
                       upcharge_pct=0.0, line_overrides=None):
    """Dealer + zero-upcharge finish + DRAFT order with one BOX line."""
    dealer = get_success_data(
        api_dealer_create(price_level=price_level, credit=credit)
    )
    return dealer


def api_dealer_create(price_level, credit):
    # Kept tiny and explicit; real work happens in the tests via test_helpers.
    from test_helpers import api_client
    return api_client.create_dealer(
        create_dealer_payload(price_level=price_level, credit_limit_cents=credit), ADMIN
    )


class TestSubmitPreconditions:
    def test_submit_empty_order_rejected(self, api, plant_admin_headers):
        """PRD §3.2: "The acting dealer must own the order
        (`ERR_RESOURCE_OWNERSHIP_MISMATCH`), the order must still be in `DRAFT`
        (`ERR_ORDER_NOT_SUBMITTABLE`), the order must contain at least one line
        (`ERR_ORDER_HAS_NO_LINES`), no modification request on any of the order's
        lines may sit in `UNDER_REVIEW` or `CHANGES_REQUESTED`
        (`ERR_MODS_PENDING_REVIEW`), and the resulting provisional total must not
        exceed the dealer's `credit_limit_cents` (`ERR_DEALER_CREDIT_EXCEEDED`,
        HTTP 402)."

        Design: Corner/validations/submit_empty_order_rejected
        """
        dealer = get_success_data(
            api.create_dealer(create_dealer_payload(price_level="L3"), plant_admin_headers)
        )
        order = get_success_data(api.create_order(make_dealer_headers(dealer["id"])))
        resp = api.submit_order(order["id"], make_dealer_headers(dealer["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_HAS_NO_LINES)

    def test_dealer_credit_exceeded_on_submit(self, api, plant_admin_headers):
        """PRD §3.2: "The acting dealer must own the order
        (`ERR_RESOURCE_OWNERSHIP_MISMATCH`), the order must still be in `DRAFT`
        (`ERR_ORDER_NOT_SUBMITTABLE`), the order must contain at least one line
        (`ERR_ORDER_HAS_NO_LINES`), no modification request on any of the order's
        lines may sit in `UNDER_REVIEW` or `CHANGES_REQUESTED`
        (`ERR_MODS_PENDING_REVIEW`), and the resulting provisional total must not
        exceed the dealer's `credit_limit_cents` (`ERR_DEALER_CREDIT_EXCEEDED`,
        HTTP 402)."

        Design: Corner/validations/dealer_credit_exceeded_on_submit
        """
        dealer = get_success_data(
            api.create_dealer(
                create_dealer_payload(price_level="L3", credit_limit_cents=1000000),
                plant_admin_headers,
            )
        )
        finish = get_success_data(
            api.create_finish_spec(create_finish_spec_payload(upcharge_pct=0.0), plant_admin_headers)
        )
        order = get_success_data(api.create_order(make_dealer_headers(dealer["id"])))
        # list 2,000,000 -> provisional net round_half_up(2,000,000 x 0.70) = 1,400,000
        get_success_data(
            api.create_order_line(
                order["id"],
                create_box_line_payload(finish["id"], qty=10, unit_list_price_cents=200000),
                make_dealer_headers(dealer["id"]),
            )
        )
        resp = api.submit_order(order["id"], make_dealer_headers(dealer["id"]))
        validate_error(resp, ApiErrorId.ERR_DEALER_CREDIT_EXCEEDED)
        reread = validate_success(api.get_order(order["id"], plant_admin_headers))
        assert reread["status"] == "DRAFT", "order must remain DRAFT after a credit rejection"


class TestProvisionalPricing:
    def test_submit_response_contains_computed_totals_immediately(self, api, plant_admin_headers):
        """PRD §3.2: "On successful submission every line moves `PENDING` →
        `QUOTED` with its provisional net set, `submitted_at` is stamped from the
        logical clock, and the order's `version` increments."
        PRD §2.6: "At server startup the logical clock reads exactly
        2026-05-01T00:00:00Z, and it never falls back to wall-clock time."

        Design: Corner/consistency_model/submit_response_contains_computed_totals_immediately
        """
        dealer = get_success_data(
            api.create_dealer(create_dealer_payload(price_level="L2"), plant_admin_headers)
        )
        finish = get_success_data(
            api.create_finish_spec(create_finish_spec_payload(upcharge_pct=0.10), plant_admin_headers)
        )
        order = get_success_data(api.create_order(make_dealer_headers(dealer["id"])))
        line = get_success_data(
            api.create_order_line(
                order["id"],
                create_box_line_payload(finish["id"], qty=10, unit_list_price_cents=200000),
                make_dealer_headers(dealer["id"]),
            )
        )
        resp = api.submit_order(order["id"], make_dealer_headers(dealer["id"]))
        data = validate_success(resp, 200)
        # Immediate consistency: the submit 200 response itself carries the
        # computed totals: round_half_up((2,000,000 + 200,000) x 0.65) = 1,430,000.
        assert data["status"] == "SUBMITTED"
        assert data["provisional_merchandise_cents"] == 1430000
        assert data["provisional_total_cents"] == 1430000
        assert is_iso8601_timestamp(data["submitted_at"])
        assert data["submitted_at"].startswith("2026-05-01"), (
            f"submitted_at must be stamped from the logical clock, got {data['submitted_at']}"
        )
        line_after = validate_success(api.get_order_line(line["id"], plant_admin_headers))
        assert line_after["status"] == "QUOTED"
        assert line_after["provisional_net_cents"] == 1430000


class TestVolumeDiscountTierBoundary:
    def test_tier_boundary_exact_hit_earns_five_percent(self, api, plant_admin_headers):
        """PRD §3.2: "A volume discount then applies by tier: merchandise of at
        least 10,000,000 cents ($100,000.00) earns eight percent, merchandise of at
        least 5,000,000 cents ($50,000.00) but below the upper threshold earns five
        percent, and smaller orders earn nothing; an exact hit on a threshold
        qualifies for that tier."
        PRD §3.2: "The dealer multiplier is read from the order's
        `price_level_snapshot` using the network schedule — `L1` prices at 0.60 of
        list, `L2` at 0.65, `L3` at 0.70, `L4` at 0.75, and `L5` at 0.80 — and each
        line's `provisional_net_cents` is the sum of `line_list_cents`,
        `finish_upcharge_cents`, and `mod_surcharge_cents`, multiplied by that
        multiplier and rounded half up to whole cents, per line."

        Design: Difficulty/boundary_precision_check/volume_discount_tier_boundary_exact_hit
        """
        dealer = get_success_data(
            api.create_dealer(create_dealer_payload(price_level="L5"), plant_admin_headers)
        )
        finish = get_success_data(
            api.create_finish_spec(create_finish_spec_payload(upcharge_pct=0.0), plant_admin_headers)
        )
        order = get_success_data(api.create_order(make_dealer_headers(dealer["id"])))
        # list 125,000 x 50 = 6,250,000 -> net round(6,250,000 x 0.80) = 5,000,000 exactly.
        get_success_data(
            api.create_order_line(
                order["id"],
                create_box_line_payload(finish["id"], qty=50, unit_list_price_cents=125000),
                make_dealer_headers(dealer["id"]),
            )
        )
        data = validate_success(api.submit_order(order["id"], make_dealer_headers(dealer["id"])))
        assert data["provisional_merchandise_cents"] == 5000000, (
            "merchandise must land exactly on the 5,000,000 tier edge"
        )
        # Exact hit qualifies for the 5% tier.
        assert data["provisional_discount_cents"] == 250000
        assert data["provisional_total_cents"] == 4750000

    def test_one_below_tier_boundary_earns_nothing(self, api, plant_admin_headers):
        """PRD §3.2: "A volume discount then applies by tier: merchandise of at
        least 10,000,000 cents ($100,000.00) earns eight percent, merchandise of at
        least 5,000,000 cents ($50,000.00) but below the upper threshold earns five
        percent, and smaller orders earn nothing; an exact hit on a threshold
        qualifies for that tier."

        Design: Difficulty/boundary_precision_check/volume_discount_tier_boundary_exact_hit
        """
        dealer = get_success_data(
            api.create_dealer(create_dealer_payload(price_level="L5"), plant_admin_headers)
        )
        finish = get_success_data(
            api.create_finish_spec(create_finish_spec_payload(upcharge_pct=0.0), plant_admin_headers)
        )
        order = get_success_data(api.create_order(make_dealer_headers(dealer["id"])))
        # list 125,000 x 49 = 6,125,000 -> net 4,900,000 < 5,000,000.
        get_success_data(
            api.create_order_line(
                order["id"],
                create_box_line_payload(finish["id"], qty=49, unit_list_price_cents=125000),
                make_dealer_headers(dealer["id"]),
            )
        )
        data = validate_success(api.submit_order(order["id"], make_dealer_headers(dealer["id"])))
        assert data["provisional_merchandise_cents"] == 4900000
        assert data["provisional_discount_cents"] == 0, "4,900,000 is below the tier: no discount"
        assert data["provisional_total_cents"] == 4900000


class TestSubmitGatedByEngineeringReview:
    def _order_with_open_mod(self, api):
        dealer = get_success_data(api.create_dealer(create_dealer_payload(price_level="L3"), ADMIN))
        finish = get_success_data(
            api.create_finish_spec(create_finish_spec_payload(upcharge_pct=0.0), ADMIN)
        )
        order = get_success_data(api.create_order(make_dealer_headers(dealer["id"])))
        line = get_success_data(
            api.create_order_line(
                order["id"],
                create_box_line_payload(finish["id"], qty=2, unit_list_price_cents=100000),
                make_dealer_headers(dealer["id"]),
            )
        )
        mod = get_success_data(
            api.create_modification(
                line["id"],
                create_modification_payload(mod_code="REDUCED_WIDTH", new_dimension_in=22),
                make_dealer_headers(dealer["id"]),
            )
        )
        return dealer, order, line, mod

    def test_submit_blocked_while_mod_under_review(self, api, plant_admin_headers):
        """PRD §3.3: "Because submission of the parent order is gated on no request
        being `UNDER_REVIEW` or `CHANGES_REQUESTED` (`ERR_MODS_PENDING_REVIEW`), an
        order cannot be submitted while any of its lines has a modification still
        inside the review loop."

        Design: Difficulty/cross_entity_state_dependency/submit_gated_by_engineering_review_state
        """
        dealer, order, _line, _mod = self._order_with_open_mod(api)
        resp = api.submit_order(order["id"], make_dealer_headers(dealer["id"]))
        validate_error(resp, ApiErrorId.ERR_MODS_PENDING_REVIEW)
        reread = validate_success(api.get_order(order["id"], plant_admin_headers))
        assert reread["status"] == "DRAFT", "order must stay DRAFT while a mod is under review"

    def test_submit_succeeds_after_mod_approved(self, api, plant_admin_headers):
        """PRD §3.3: "Because submission of the parent order is gated on no request
        being `UNDER_REVIEW` or `CHANGES_REQUESTED` (`ERR_MODS_PENDING_REVIEW`), an
        order cannot be submitted while any of its lines has a modification still
        inside the review loop."
        PRD §3.3: "`APPROVE` moves the request to `APPROVED`; the line's
        `mod_surcharge_cents` — always the sum of the surcharges of the line's
        `APPROVED` modification requests — then takes effect at the order's next
        pricing event, whether that is submission or dispatch."

        Design: Difficulty/cross_entity_state_dependency/submit_gated_by_engineering_review_state
        """
        dealer, order, _line, mod = self._order_with_open_mod(api)
        get_success_data(api.review_modification(mod["id"], {"decision": "APPROVE"}, ENGINEER))
        data = validate_success(api.submit_order(order["id"], make_dealer_headers(dealer["id"])))
        assert data["status"] == "SUBMITTED", (
            "the identical submit must succeed once no mod remains in the review loop"
        )


class TestDoubleSubmitPriority:
    def _submitted_order_then_credit_cut(self, api):
        dealer = get_success_data(
            api.create_dealer(
                create_dealer_payload(price_level="L3", credit_limit_cents=2000000), ADMIN
            )
        )
        finish = get_success_data(
            api.create_finish_spec(create_finish_spec_payload(upcharge_pct=0.0), ADMIN)
        )
        order = get_success_data(api.create_order(make_dealer_headers(dealer["id"])))
        # provisional total: round(2,000,000 x 0.70) = 1,400,000 <= 2,000,000 credit.
        get_success_data(
            api.create_order_line(
                order["id"],
                create_box_line_payload(finish["id"], qty=10, unit_list_price_cents=200000),
                make_dealer_headers(dealer["id"]),
            )
        )
        get_success_data(api.submit_order(order["id"], make_dealer_headers(dealer["id"])))
        # Cut the credit limit below the order's provisional total so a naive
        # re-evaluation would also trip the fiscal ceiling.
        get_success_data(api.update_dealer(dealer["id"], {"credit_limit_cents": 1000000}, ADMIN))
        return dealer, order

    def test_second_submit_surfaces_state_error_not_fiscal(self, api):
        """PRD §2.7: "When a single request violates several rules, the platform
        evaluates checks in a fixed priority order and surfaces only the first
        failure."
        PRD §2.7: "6. Single-resource state preconditions — whether the target
        resource is in the state the operation requires (for example an order in
        `DRAFT` for line addition, modification creation, or submit; a batch in
        `MIXING` for assignment or QC recording; a route in `PLANNED` for
        assignment or locking)."
        PRD §2.7: "13. Capacity and fiscal ceilings (`ERR_ROUTE_CUBE_EXCEEDED`,
        `ERR_DEALER_CREDIT_EXCEEDED`, `ERR_SUB_LOT_QTY_EXCEEDS_LINE`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_double_submit
        """
        dealer, order = self._submitted_order_then_credit_cut(api)
        resp = api.submit_order(order["id"], make_dealer_headers(dealer["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SUBMITTABLE)

    def test_second_submit_leaves_order_submitted(self, api, plant_admin_headers):
        """PRD §3.2: "The acting dealer must own the order
        (`ERR_RESOURCE_OWNERSHIP_MISMATCH`), the order must still be in `DRAFT`
        (`ERR_ORDER_NOT_SUBMITTABLE`), the order must contain at least one line
        (`ERR_ORDER_HAS_NO_LINES`), no modification request on any of the order's
        lines may sit in `UNDER_REVIEW` or `CHANGES_REQUESTED`
        (`ERR_MODS_PENDING_REVIEW`), and the resulting provisional total must not
        exceed the dealer's `credit_limit_cents` (`ERR_DEALER_CREDIT_EXCEEDED`,
        HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_double_submit
        """
        dealer, order = self._submitted_order_then_credit_cut(api)
        resp = api.submit_order(order["id"], make_dealer_headers(dealer["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SUBMITTABLE)
        reread = validate_success(api.get_order(order["id"], plant_admin_headers))
        assert reread["status"] == "SUBMITTED", "a rejected re-submit must not move the order"
