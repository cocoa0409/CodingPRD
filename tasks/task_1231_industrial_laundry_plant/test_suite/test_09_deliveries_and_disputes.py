"""Deliveries and disputes: shortfall/overage derivation, par on-site
movement, dispute preconditions, credit computation, and the failed-wash
shortage cascade."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_customer_contact_headers,
    create_plant, create_linen_category, create_customer,
    create_route, create_stop, dispatch_route, arrive_stop, pickup_stop,
    receive_stop_carts, get_stop, get_customer_version,
    manifest_delivery, mark_delivery_delivered, file_dispute, get_delivery,
    set_par_level, get_on_site_pieces,
    setup_stop_received, create_batch_posted, stage_wash_load,
)

DRIVER = TEST_USERS["route_driver_headers"]
OPERATOR = TEST_USERS["plant_operator_headers"]
CSR = TEST_USERS["csr_headers"]


def _delivered_ctx(api, promised=10, delivered=8, billing_mode="RENTAL",
                   par_pieces=None):
    """Stop picked up + cart received + one delivery marked delivered."""
    ctx = setup_stop_received(
        customer_overrides={"billing_mode": billing_mode},
        stop_overrides={"declared_soiled_weight_lb": 5.0},
        carts=[{"cart_tag": "CART-1", "scale_weight_lb": 5.0}],
    )
    if par_pieces is not None:
        set_par_level(ctx["customer"]["id"], ctx["category"]["id"], par_pieces)
    version = get_customer_version(ctx["customer"]["id"], DRIVER)
    delivery = manifest_delivery(
        ctx["stop"]["id"], ctx["category"]["id"], promised
    )
    resp_delivery = validate_success(api.mark_delivered(
        delivery["id"],
        {"pieces_delivered": delivered, "expected_customer_version": version},
        DRIVER,
    ), 200)
    ctx["delivery"] = resp_delivery
    return ctx


class TestShortfallDerivation:
    def test_par_on_site_increments_by_delivered_count(self, api):
        """PRD §3.7: "The par row's `current_on_site_pieces` for this customer and category is incremented by the delivered count, and a par-shortage alert is raised when the resulting shortfall — the category's `par_pieces` minus the new on-site count, floored at zero — is greater than or equal to the plant's `par_shortage_alert_pieces`; a plant whose threshold is zero suppresses these alerts entirely."

        Design: Difficulty/boundary_precision_check/par_shortfall_exactly_at_alert_pieces
        """
        # First delivery: 5 pieces against par 10 -> shortfall exactly 5,
        # equal to the plant's alert threshold of 5 pieces.
        ctx = _delivered_ctx(api, promised=5, delivered=5, par_pieces=10)
        assert ctx["delivery"]["shortfall_pieces"] == 0
        on_site = get_on_site_pieces(ctx["customer"]["id"], ctx["category"]["id"])
        assert on_site == 5, f"on-site must rise to 5, got {on_site}"

        # Second route/stop for the same customer: one more piece delivered
        # -> on-site 6, leaving shortfall 4, below the threshold.
        route2 = create_route(ctx["plant"]["id"], service_date="2026-05-03")
        stop2 = create_stop(route2["id"], ctx["customer"]["id"],
                            declared_soiled_weight_lb=0.0)
        dispatch_route(route2["id"])
        arrive_stop(stop2["id"])
        pickup_stop(stop2["id"],
                    carts=[{"cart_tag": "CART-2", "scale_weight_lb": 0.1}])
        receive_stop_carts(stop2["id"])
        version = get_customer_version(ctx["customer"]["id"], DRIVER)
        delivery2 = manifest_delivery(stop2["id"], ctx["category"]["id"], 1)
        validate_success(api.mark_delivered(
            delivery2["id"],
            {"pieces_delivered": 1, "expected_customer_version": version},
            DRIVER,
        ), 200)
        on_site2 = get_on_site_pieces(ctx["customer"]["id"], ctx["category"]["id"])
        assert on_site2 == 6, f"on-site must rise to 6, got {on_site2}"

    def test_overage_and_shortfall_floored_at_zero(self, api):
        """PRD §3.7: "On success the submitted `pieces_delivered` is recorded, and the system derives `shortfall_pieces` as the promised minus delivered count floored at zero, and `overage_pieces` as the delivered minus promised count floored at zero."
        PRD §3.7: "The par row's `current_on_site_pieces` for this customer and category is incremented by the delivered count"

        Design: Difficulty/boundary_precision_check/par_shortfall_exactly_at_alert_pieces
        """
        ctx = _delivered_ctx(api, promised=5, delivered=7, par_pieces=10)
        delivery = ctx["delivery"]
        assert delivery["shortfall_pieces"] == 0, (
            "over-delivery must not produce a negative shortfall"
        )
        assert delivery["overage_pieces"] == 2, (
            f"7 delivered against 5 promised is an overage of 2, "
            f"got {delivery['overage_pieces']}"
        )
        on_site = get_on_site_pieces(ctx["customer"]["id"], ctx["category"]["id"])
        assert on_site == 7, f"on-site must increment by delivered count, got {on_site}"


class TestDisputePreconditions:
    def test_dispute_without_shortfall_rejected(self, api):
        """PRD §3.7: "Alternatively, when the delivered count fell short — `shortfall_pieces` at least 1, otherwise the filing fails with `ERR_NO_SHORTAGE` — the contact files a shortage dispute with a `claimed_shortfall_pieces` of at least 1."

        Design: Corner/state_machines/delivery_dispute_without_shortfall_rejected
        """
        ctx = _delivered_ctx(api, promised=10, delivered=10)
        resp = api.file_dispute(
            ctx["delivery"]["id"], {"claimed_shortfall_pieces": 1},
            make_customer_contact_headers(ctx["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_SHORTAGE)

    def test_approve_quantity_above_claim_rejected(self, api):
        """PRD §3.7: "Approval moves `UNDER_REVIEW` to `APPROVED` and requires the submitted `approved_shortfall_pieces` to be at least 1, no more than `claimed_shortfall_pieces`, and no more than the parent delivery's `shortfall_pieces`; a quantity outside that band fails with `ERR_INVALID_APPROVED_QUANTITY`."

        Design: Corner/state_machines/discrepancy_approve_quantity_above_claim_rejected
        """
        ctx = _delivered_ctx(api, promised=10, delivered=8)
        discrepancy = file_dispute(ctx["delivery"]["id"], 2, ctx["customer"]["id"])
        validate_success(
            api.start_review_discrepancy(discrepancy["id"], CSR), 200)
        resp = api.approve_discrepancy(
            discrepancy["id"], {"approved_shortfall_pieces": 3}, CSR)
        validate_error(resp, ApiErrorId.ERR_INVALID_APPROVED_QUANTITY)

    def test_unresolved_carts_block_delivery(self, api):
        """PRD §3.7: "Once a stop is `PICKED_UP` and every cart of the stop has been resolved into `RECEIVED`, `SORTED`, or `VOIDED` — unresolved carts block the delivery phase with `ERR_CARTS_PENDING` — the `RouteDriver` manifests one delivery row per category at the stop, supplying the `category_id` and the `pieces_promised` the plant committed to return."

        Design: Corner/errors/error_carts_pending_blocks_delivery_manifest
        """
        plant = create_plant()
        category = create_linen_category(plant["id"])
        customer = create_customer(plant["id"], billing_mode="RENTAL")
        route = create_route(plant["id"])
        stop = create_stop(route["id"], customer["id"])
        dispatch_route(route["id"])
        arrive_stop(stop["id"])
        pickup_stop(stop["id"])  # one cart, never received
        # The carts-resolved condition gates the manifest act itself: the
        # sentence conditions "the RouteDriver manifests ..." on every cart
        # being resolved, so manifesting with a DECLARED cart fails here.
        resp = api.create_delivery(
            stop["id"],
            {"category_id": category["id"], "pieces_promised": 10},
            DRIVER,
        )
        validate_error(resp, ApiErrorId.ERR_CARTS_PENDING)


class TestCreditComputation:
    def test_credit_is_60_percent_of_replacement_cost(self, api):
        """PRD §3.7: "On approval the `credit_cents` is computed: the approved shortfall pieces multiplied by the category's `replacement_cost_cents`, multiplied by 60 percent, and rounded half-up to whole cents — the plant credits shortage at sixty percent of replacement cost, never one hundred."

        Design: Corner/calculations/discrepancy_credit_uses_60_pct_rate
        """
        ctx = _delivered_ctx(api, promised=10, delivered=7)
        discrepancy = file_dispute(ctx["delivery"]["id"], 3, ctx["customer"]["id"])
        validate_success(
            api.start_review_discrepancy(discrepancy["id"], CSR), 200)
        approved = validate_success(api.approve_discrepancy(
            discrepancy["id"], {"approved_shortfall_pieces": 3}, CSR), 200)
        assert approved["credit_cents"] == 900, (
            f"3 pieces * 500 cents * 60% must credit 900, "
            f"got {approved['credit_cents']}"
        )
        assert approved["status"] == "APPROVED"


class TestFailedWashShortageCascade:
    def _failed_load_ctx(self, api):
        """GOWN load (test required) driven to TESTED_FAIL; batch of 20."""
        ctx = setup_stop_received(
            category_overrides={
                "code": "GOWN", "piece_weight_lb": 1.5,
                "wash_formula_code": "WF_STANDARD",
                "hygienic_test_required": True, "replacement_cost_cents": 3000,
                "cog_wash_rate_cents_per_lb": 200,
            },
            customer_overrides={"customer_kind": "HEALTHCARE", "billing_mode": "COG"},
            stop_overrides={"declared_soiled_weight_lb": 30.0},
            carts=[{"cart_tag": "CART-1", "scale_weight_lb": 30.0}],
        )
        ctx["batch"] = create_batch_posted(ctx["stop"]["id"], [
            {"category_id": ctx["category"]["id"], "pieces": 20},
        ])
        load = stage_wash_load(ctx["batch"]["id"], ctx["category"]["id"])
        validate_success(api.start_wash_load(load["id"], OPERATOR), 200)
        validate_success(api.finish_cycle_wash_load(load["id"], OPERATOR), 200)
        failed = validate_success(api.record_test_wash_load(
            load["id"], {"outcome": "FAIL"}, OPERATOR), 200)
        ctx["load"] = failed
        return ctx

    def test_failed_load_leads_to_shortfall_and_dispute(self, api):
        """PRD §3.4: "When the category requires testing, the operator records the outcome: submitting an `outcome` of `PASS` moves the load from `AWAITING_TEST` to `TESTED_PASS`, and an `outcome` of `FAIL` moves it from `AWAITING_TEST` to `TESTED_FAIL`"
        PRD §3.7: "On success the submitted `pieces_delivered` is recorded, and the system derives `shortfall_pieces` as the promised minus delivered count floored at zero"
        PRD §3.7: "Filing creates a `Discrepancy` in `FILED` status under the delivery, moves the delivery from `DELIVERED` to `DISPUTED`, and moves the parent stop from `DELIVERED` to `DISPUTED` if it was not there already."

        Design: Difficulty/transitive_cascade/wash_test_fail_to_delivery_shortfall_chain
        """
        ctx = self._failed_load_ctx(api)
        assert ctx["load"]["status"] == "TESTED_FAIL"

        # The failed load never produces clean stock; only 15 of 20 promised
        # pieces can be physically delivered.
        version = get_customer_version(ctx["customer"]["id"], DRIVER)
        delivery = manifest_delivery(ctx["stop"]["id"], ctx["category"]["id"], 20)
        delivered = validate_success(api.mark_delivered(
            delivery["id"],
            {"pieces_delivered": 15, "expected_customer_version": version},
            DRIVER,
        ), 200)
        assert delivered["shortfall_pieces"] == 5, (
            f"promised 20 minus delivered 15 must shortfall 5, "
            f"got {delivered['shortfall_pieces']}"
        )

        discrepancy = validate_success(api.file_dispute(
            delivery["id"], {"claimed_shortfall_pieces": 5},
            make_customer_contact_headers(ctx["customer"]["id"]),
        ), 201)
        assert discrepancy["status"] == "FILED"
        delivery_after = get_delivery(delivery["id"])
        assert delivery_after["status"] == "DISPUTED"
        stop_after = get_stop(ctx["stop"]["id"])
        assert stop_after["status"] == "DISPUTED", (
            "filing a dispute must move the parent stop to DISPUTED"
        )

    def test_approved_shortfall_after_failed_load_computes_credit(self, api):
        """PRD §3.7: "On approval the `credit_cents` is computed: the approved shortfall pieces multiplied by the category's `replacement_cost_cents`, multiplied by 60 percent, and rounded half-up to whole cents — the plant credits shortage at sixty percent of replacement cost, never one hundred."
        PRD §3.7: "Filing creates a `Discrepancy` in `FILED` status under the delivery, moves the delivery from `DELIVERED` to `DISPUTED`, and moves the parent stop from `DELIVERED` to `DISPUTED` if it was not there already."

        Design: Difficulty/transitive_cascade/wash_test_fail_to_delivery_shortfall_chain
        """
        ctx = self._failed_load_ctx(api)
        version = get_customer_version(ctx["customer"]["id"], DRIVER)
        delivery = manifest_delivery(ctx["stop"]["id"], ctx["category"]["id"], 20)
        delivered = validate_success(api.mark_delivered(
            delivery["id"],
            {"pieces_delivered": 15, "expected_customer_version": version},
            DRIVER,
        ), 200)
        assert delivered["shortfall_pieces"] == 5
        discrepancy = validate_success(api.file_dispute(
            delivery["id"], {"claimed_shortfall_pieces": 5},
            make_customer_contact_headers(ctx["customer"]["id"]),
        ), 201)
        validate_success(
            api.start_review_discrepancy(discrepancy["id"], CSR), 200)
        approved = validate_success(api.approve_discrepancy(
            discrepancy["id"], {"approved_shortfall_pieces": 5}, CSR), 200)
        assert approved["status"] == "APPROVED"
        assert approved["credit_cents"] == 9000, (
            f"5 pieces * 3000 cents * 60% must credit 9000, "
            f"got {approved['credit_cents']}"
        )
        assert get_delivery(delivery["id"])["status"] == "DISPUTED", (
            "an APPROVED (not yet terminal) discrepancy leaves the delivery DISPUTED"
        )
