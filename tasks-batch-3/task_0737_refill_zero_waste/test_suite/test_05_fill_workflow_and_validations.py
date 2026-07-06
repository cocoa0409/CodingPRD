"""Filling workflow and its gated validations: the parallel order axes, the
empty-order guard, the fixed check-priority ordering on fill (state vs fiscal,
safety vs referential), the quarantined-bin cross-entity block, and the
tare/stock structural checks.

Difficulty-queue instances plus two Corner/validations instances.
"""
from test_helpers import fixtures, validate_success, validate_error, ApiErrorId
from test_helpers.test_users import TEST_USERS

CLERK = TEST_USERS["store_clerk_headers"]
IM = TEST_USERS["inventory_manager_headers"]


class TestOrderParallelStateAxes:
    """fulfillment_status and payment_status evolve independently: start-fill
    advances fulfillment only; checkout advances payment (and fulfillment)."""

    def test_start_fill_advances_fulfillment_not_payment(self, api):
        """PRD §3.5: "Before any weighing, a clerk **starts the fill**, moving the
        order `CART → FILLING`."
        PRD §3.4: "it evolves independently of the `payment_status`, which is
        either `UNPAID` or `CAPTURED`."

        Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_payment_independent
        """
        s = fixtures.setup_cart_line(api, channel="DELIVERY", estimated_gross_g=700)
        order = fixtures.start_fill(api, order_id=s["order"]["id"])
        assert order["fulfillment_status"] == "FILLING"
        assert order["payment_status"] == "UNPAID", "payment stays UNPAID until checkout"

    def test_checkout_advances_both_dimensions(self, api):
        """PRD §3.6: "In a single atomic step, checkout advances
        `fulfillment_status` `FILLING → FILLED` and `payment_status`
        `UNPAID → CAPTURED`".
        PRD §3.6: "a `DELIVERY` order instead completes later through its
        delivery."

        Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_payment_independent
        """
        # DELIVERY channel: checkout leaves fulfillment at FILLED (not auto-COMPLETED).
        s = fixtures.setup_final_line(api, channel="DELIVERY", estimated_gross_g=700,
                                      gross_weight_g=750, measured_tare_g=200)
        order = fixtures.checkout_order(api, order_id=s["order"]["id"])
        assert order["fulfillment_status"] == "FILLED"
        assert order["payment_status"] == "CAPTURED"


class TestEmptyOrderStartFill:
    """start-fill requires at least one non-voided line."""

    def test_start_fill_empty_order_rejected(self, api):
        """PRD §3.5: "This is permitted only when the order is `CART`, the order
        has at least one non-voided line (otherwise `ERR_EMPTY_ORDER`), and the
        station's `station_status` is `OPEN`".

        Design: Difficulty/boundary_precision_check/empty_order_start_fill_rejected
        """
        member = fixtures.create_member(api)
        station = fixtures.create_station(api)
        order = fixtures.create_order(api, member_id=member["id"], station_id=station["id"])
        resp = api.start_fill(order["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER.value)

    def test_start_fill_all_lines_voided_rejected(self, api):
        """PRD §3.5: "This is permitted only when the order is `CART`, the order
        has at least one non-voided line (otherwise `ERR_EMPTY_ORDER`), and the
        station's `station_status` is `OPEN`".

        Design: Difficulty/boundary_precision_check/empty_order_start_fill_rejected
        """
        s = fixtures.setup_cart_line(api, estimated_gross_g=500)  # one PROVISIONAL line
        validate_success(api.void_line(s["line"]["id"], CLERK), 200)  # -> VOIDED
        resp = api.start_fill(s["order"]["id"], CLERK)  # zero non-voided lines remain
        validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER.value)


class TestStateCheckBeatsFiscalCheckOnFill:
    """A fill that violates both the order-state precondition (order still CART)
    and the stock check reports the earlier-priority state error."""

    def test_fill_on_cart_order_returns_invalid_order_state(self, api):
        """PRD §2.9: "the checks are evaluated in a fixed priority order and the
        first failure wins; lower-priority-number checks are decided before higher
        ones."
        PRD §3.5: "First, the parent order must be `FILLING`, else
        `ERR_INVALID_ORDER_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_fill
        """
        # Order still CART (state fail) AND net 300 > on_hand 50 (fiscal fail).
        s = fixtures.setup_cart_line(
            api, estimated_gross_g=500,
            bin_overrides={"reorder_threshold_g": 0, "last_recount_g": 50})
        resp = api.fill_line(s["line"]["id"],
                             {"gross_weight_g": 500, "measured_tare_g": 200}, CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE.value)

    def test_rejected_fill_leaves_bin_and_line_unchanged(self, api):
        """PRD §3.5: "On a successful fill, ... the bin's `on_hand_g` is decreased
        by the line's net weight".
        PRD §3.5: "Filling drives the line `PROVISIONAL → FINAL`".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_fill
        """
        s = fixtures.setup_cart_line(
            api, estimated_gross_g=500,
            bin_overrides={"reorder_threshold_g": 0, "last_recount_g": 50})
        api.fill_line(s["line"]["id"], {"gross_weight_g": 500, "measured_tare_g": 200}, CLERK)
        bin_after = validate_success(api.get_bin(s["bin"]["id"], CLERK), 200)
        line_after = validate_success(api.get_refill_line(s["line"]["id"], CLERK), 200)
        assert bin_after["on_hand_g"] == 50, "rejected fill dispenses nothing"
        assert line_after["pricing_stage"] == "PROVISIONAL", "rejected fill does not finalize"


class TestSafetyCheckBeatsReferentialCheckOnFill:
    """A fill into a container carrying incompatible allergen residue that is also
    owned by a different member reports the earlier-priority safety error."""

    @staticmethod
    def _setup_contaminated_cross_owner(api):
        m_a = fixtures.create_member(api)
        m_b = fixtures.create_member(api)
        p_pea = fixtures.create_product(
            api, name="Peanuts", category="GRAINS", unit_price_cents_per_100g=50,
            bulk_tier_threshold_g=100000, bulk_tier_price_cents_per_100g=50,
            allergen_tags=["PEANUT"])
        p_oats = fixtures.create_product(api)
        station = fixtures.create_station(api)
        fixtures.create_bin(api, product_id=p_pea["id"], station_id=station["id"],
                            reorder_threshold_g=100, last_recount_g=5000)
        fixtures.create_bin(api, product_id=p_oats["id"], station_id=station["id"],
                            reorder_threshold_g=100, last_recount_g=5000)
        cc = fixtures.create_container(api, declared_tare_g=100, member_id=m_a["id"])
        o_a = fixtures.create_order(api, member_id=m_a["id"], station_id=station["id"],
                                    fill_window_start_at="2026-03-02T09:00:00Z",
                                    fill_window_end_at="2026-03-02T10:00:00Z")
        l_a = fixtures.add_line(api, order_id=o_a["id"], product_id=p_pea["id"],
                                container_id=cc["id"], estimated_gross_g=300)
        fixtures.start_fill(api, order_id=o_a["id"])
        fixtures.fill_line(api, line_id=l_a["id"], gross_weight_g=300, measured_tare_g=100)
        o_b = fixtures.create_order(api, member_id=m_b["id"], station_id=station["id"],
                                    fill_window_start_at="2026-03-02T11:00:00Z",
                                    fill_window_end_at="2026-03-02T12:00:00Z")
        l_b = fixtures.add_line(api, order_id=o_b["id"], product_id=p_oats["id"],
                                container_id=cc["id"], estimated_gross_g=300)
        fixtures.start_fill(api, order_id=o_b["id"])
        return {"container": cc, "line_b": l_b}

    def test_peanut_fill_sets_container_allergen_hold(self, api):
        """PRD §3.5: "if the product carries any `allergen_tags`, the container's
        `allergen_hold` is set to the first of those tags; if the product carries
        none, the hold is left unchanged."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_fill
        """
        s = self._setup_contaminated_cross_owner(api)
        container = validate_success(api.get_container(s["container"]["id"], CLERK), 200)
        assert container["allergen_hold"] == "PEANUT"

    def test_allergen_conflict_beats_ownership_on_fill(self, api):
        """PRD §3.5: "the container's `allergen_hold` must be `NONE` or must be an
        allergen the product itself carries in its `allergen_tags` (so a residual
        peanut hold is acceptable only when refilling a peanut product); otherwise
        the fill is rejected with `ERR_ALLERGEN_CONFLICT`."
        PRD §2.9: "the checks are evaluated in a fixed priority order and the
        first failure wins; lower-priority-number checks are decided before higher
        ones."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_fill
        """
        s = self._setup_contaminated_cross_owner(api)
        resp = api.fill_line(s["line_b"]["id"],
                             {"gross_weight_g": 300, "measured_tare_g": 100}, CLERK)
        validate_error(resp, ApiErrorId.ERR_ALLERGEN_CONFLICT.value)


class TestFillBlockedByQuarantinedBin:
    """A recount revealing shrink above the allowance quarantines the bin, and a
    subsequent fill against that resolved bin is refused."""

    def test_recount_high_shrink_quarantines_bin(self, api):
        """PRD §3.9: "Shrink is that book on-hand minus the counted `physical_g`,
        and a positive shrink means inventory is missing; the result is stored in
        `last_shrink_g`."
        PRD §3.9: "If the computed shrink is strictly greater than 200 grams, the
        bin is moved to `QUARANTINED`, blocking dispensing pending investigation".

        Design: Difficulty/cross_entity_state_dependency/fill_blocked_by_quarantined_bin
        """
        product = fixtures.create_product(api)
        station = fixtures.create_station(api)
        bin_ = fixtures.create_bin(api, product_id=product["id"], station_id=station["id"],
                                   reorder_threshold_g=100, last_recount_g=5000)
        recounted = fixtures.recount_bin(api, bin_id=bin_["id"], physical_g=4000)
        assert recounted["last_shrink_g"] == 1000, "book 5000 - physical 4000"
        assert recounted["status"] == "QUARANTINED"

    def test_fill_into_quarantined_bin_rejected(self, api):
        """PRD §3.5: "if the resolved bin is `QUARANTINED` it fails with
        `ERR_BIN_QUARANTINED` (a bin in `OPEN` or `LOW` is fine to dispense
        from)."

        Design: Difficulty/cross_entity_state_dependency/fill_blocked_by_quarantined_bin
        """
        member = fixtures.create_member(api)
        product = fixtures.create_product(api)
        station = fixtures.create_station(api)
        bin_ = fixtures.create_bin(api, product_id=product["id"], station_id=station["id"],
                                   reorder_threshold_g=100, last_recount_g=5000)
        fixtures.recount_bin(api, bin_id=bin_["id"], physical_g=4000)  # -> QUARANTINED
        container = fixtures.create_container(api, declared_tare_g=200, member_id=member["id"])
        order = fixtures.create_order(api, member_id=member["id"], station_id=station["id"])
        line = fixtures.add_line(api, order_id=order["id"], product_id=product["id"],
                                 container_id=container["id"], estimated_gross_g=500)
        fixtures.start_fill(api, order_id=order["id"])
        resp = api.fill_line(line["id"], {"gross_weight_g": 500, "measured_tare_g": 200}, CLERK)
        validate_error(resp, ApiErrorId.ERR_BIN_QUARANTINED.value)


def test_fill_zero_net_weight_rejected(api):
    """PRD §3.5: "The weighed values must yield a positive net: `gross_weight_g`
    minus `measured_tare_g` must be greater than zero, else
    `ERR_TARE_EXCEEDS_GROSS`."

    Design: Corner/validations/corner_err_tare_exceeds_gross_on_fill
    """
    s = fixtures.setup_filling_line(api, estimated_gross_g=500)
    resp = api.fill_line(s["line"]["id"],
                         {"gross_weight_g": 200, "measured_tare_g": 200}, CLERK)  # net 0
    validate_error(resp, ApiErrorId.ERR_TARE_EXCEEDS_GROSS.value)


def test_fill_exceeds_bin_stock_rejected(api):
    """PRD §3.5: "Finally, the line's net weight must not exceed the bin's
    `on_hand_g`, else `ERR_INSUFFICIENT_STOCK`."

    Design: Corner/validations/corner_err_insufficient_stock_on_fill
    """
    # Order is FILLING (state passes), so the priority-9 fiscal check is reached.
    s = fixtures.setup_filling_line(
        api, estimated_gross_g=500,
        bin_overrides={"reorder_threshold_g": 0, "last_recount_g": 50})
    resp = api.fill_line(s["line"]["id"],
                         {"gross_weight_g": 500, "measured_tare_g": 200}, CLERK)  # net 300 > 50
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)
