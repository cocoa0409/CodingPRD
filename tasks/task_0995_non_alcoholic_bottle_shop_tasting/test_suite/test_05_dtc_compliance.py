"""DTC shipping compliance: state permission gating, quarantined-lot
exclusion, validation priority, and the on_hand_cached input set
(PRD §3.1, §3.2, §3.8, §3.11, §2.7).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_line,
    create_draft_order,
    get_lot,
    get_order,
    get_sku,
    make_category,
    make_lot,
    make_member,
    make_member_headers,
    make_shipping_rule,
    make_sku,
    set_clock,
    submit_order_fresh,
    validate_error,
)

ADMIN = TEST_USERS["platform_admin_headers"]
STAFF = TEST_USERS["shop_staff_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


def _setup_quarantined_only_stock(api):
    """SKU whose sole lot is QUARANTINED; CA rule allows DTC."""
    set_clock()
    category = make_category(code="tea2", display_name="Tea 2")
    sku = make_sku(category["id"], sku_code="sku-rt", base_price_cents=500)
    lot = make_lot(sku["id"], lot_code="L-A", qty_received=5)
    get_resp = api.quarantine_lot(lot["id"], {"quarantine_reason": "suspect batch"},
                                  OFFICER)
    assert get_resp.status_code == 200, get_resp.text
    member = make_member(email="m2@x.com")
    make_shipping_rule(state_code="CA", tax_rate_bps=0)
    return sku, lot, member


class TestQuarantinedLotDtc:
    def test_dtc_submit_with_only_quarantined_stock_rejected(self, api):
        """PRD §3.2: "On retail-channel orders, a `ShopStaff` operator may
        explicitly override and allocate from `QUARANTINED` lots; on
        direct-to-consumer orders no such override is permitted and the walk
        is restricted to non-quarantined lots."
        PRD §3.2: "If the walk ends with demand still outstanding — the
        non-`EXPIRED`, non-`QUARANTINED` lots cannot cover the request — the
        operation that triggered the walk is rejected with
        `ERR_INSUFFICIENT_INVENTORY`."

        Design: Difficulty/dual_variant_calc/lot_allocation_retail_vs_dtc_quarantine_handling
        """
        sku, lot, member = _setup_quarantined_only_stock(api)
        order = create_draft_order(member["id"], channel="DTC",
                                   ship_to_state_code="CA")
        add_line(order["id"], member["id"], sku["id"], qty=3)
        resp = submit_order_fresh(order["id"], member["id"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY)

    def test_failed_dtc_submit_leaves_quarantined_lot_untouched(self, api):
        """PRD §3.1: "The system also maintains a cached `on_hand_cached`
        integer on every SKU, equal to the sum of `qty_remaining` across all
        of the SKU's inventory lots whose status is `ACTIVE` or `DEPLETED` —
        lots in `QUARANTINED` or `EXPIRED` are deliberately excluded from this
        cached count."
        PRD §3.2: "on direct-to-consumer orders no such override is permitted
        and the walk is restricted to non-quarantined lots."

        Design: Difficulty/dual_variant_calc/lot_allocation_retail_vs_dtc_quarantine_handling
        """
        sku, lot, member = _setup_quarantined_only_stock(api)
        order = create_draft_order(member["id"], channel="DTC",
                                   ship_to_state_code="CA")
        add_line(order["id"], member["id"], sku["id"], qty=3)
        validate_error(
            submit_order_fresh(order["id"], member["id"]),
            ApiErrorId.ERR_INSUFFICIENT_INVENTORY,
        )
        lot_after = get_lot(lot["id"])
        assert lot_after["qty_remaining"] == 5, (
            "rejected DTC walk must not decrement the quarantined lot"
        )
        assert lot_after["status"] == "QUARANTINED"
        assert get_sku(sku["id"])["on_hand_cached"] == 0


def _setup_ut_prohibited(api, with_inventory, email):
    """DTC order to UT whose rule forbids DTC. When with_inventory is False
    the SKU has no lots, so the inventory check would also fail."""
    set_clock()
    category = make_category()
    sku = make_sku(category["id"], base_price_cents=500)
    if with_inventory:
        make_lot(sku["id"], qty_received=10)
    member = make_member(email=email)
    make_shipping_rule(state_code="UT", allows_dtc=False, min_age_years=21,
                       tax_rate_bps=0)
    order = create_draft_order(member["id"], channel="DTC",
                               ship_to_state_code="UT")
    add_line(order["id"], member["id"], sku["id"], qty=1 if with_inventory else 5)
    return order, member, sku


class TestDtcStateProhibition:
    def test_submit_to_dtc_prohibited_state_rejected(self, api):
        """PRD §3.11: "It carries a unique two-letter `state_code`, an
        `allows_dtc` flag (when false, no `DTC` order may ship to this state —
        submission is rejected with `ERR_DTC_STATE_PROHIBITED`)"

        Design: Difficulty/cross_entity_state_dependency/order_submit_depends_on_shipping_state_rule
        """
        order, member, sku = _setup_ut_prohibited(api, True, "m13@x.com")
        resp = submit_order_fresh(order["id"], member["id"])
        validate_error(resp, ApiErrorId.ERR_DTC_STATE_PROHIBITED)

    def test_rejected_submit_leaves_order_in_draft(self, api):
        """PRD §3.11: "It carries a unique two-letter `state_code`, an
        `allows_dtc` flag (when false, no `DTC` order may ship to this state —
        submission is rejected with `ERR_DTC_STATE_PROHIBITED`)"
        PRD §3.8: "Successful submission transitions the order from `DRAFT` to
        `PICKING` on the fulfillment axis, sets `payment_status` to
        `AUTHORIZED`"

        Design: Difficulty/cross_entity_state_dependency/order_submit_depends_on_shipping_state_rule
        """
        order, member, sku = _setup_ut_prohibited(api, True, "m13@x.com")
        resp = submit_order_fresh(order["id"], member["id"])
        validate_error(resp, ApiErrorId.ERR_DTC_STATE_PROHIBITED)
        after = get_order(order["id"], make_member_headers(member["id"]))
        assert after["fulfillment_status"] == "DRAFT", (
            "a rejected submission must not move the fulfillment axis"
        )
        assert after["payment_status"] == "UNPAID"


class TestValidationPriority:
    def test_dtc_prohibition_precedes_inventory_failure(self, api):
        """PRD §2.7: "13. DTC state permission — destination state permits
        direct-to-consumer shipping (`ERR_DTC_STATE_PROHIBITED`)."
        PRD §2.7: "17. Inventory sufficiency — the FEFO lot walk can satisfy
        every line (`ERR_INSUFFICIENT_INVENTORY`)."
        PRD §2.7: "Because checks are evaluated in this order, a single
        malformed call surfaces exactly one error — the earliest in this list
        that applies."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_fiscal_priority
        """
        # No lots at all: inventory would fail; the DTC prohibition (earlier
        # in the priority order) must be the error that surfaces.
        order, member, sku = _setup_ut_prohibited(api, False, "m10@x.com")
        resp = submit_order_fresh(order["id"], member["id"])
        validate_error(resp, ApiErrorId.ERR_DTC_STATE_PROHIBITED)

    def test_priority_loser_scenario_leaves_order_untouched(self, api):
        """PRD §2.7: "When a single request could fail more than one check,
        the server evaluates checks in a fixed priority order and returns the
        first failure."
        PRD §3.8: "Successful submission transitions the order from `DRAFT` to
        `PICKING` on the fulfillment axis, sets `payment_status` to
        `AUTHORIZED`"

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_fiscal_priority
        """
        order, member, sku = _setup_ut_prohibited(api, False, "m10@x.com")
        before = get_order(order["id"], make_member_headers(member["id"]))
        resp = submit_order_fresh(order["id"], member["id"])
        validate_error(resp, ApiErrorId.ERR_DTC_STATE_PROHIBITED)
        after = get_order(order["id"], make_member_headers(member["id"]))
        assert after["fulfillment_status"] == "DRAFT"
        assert after["payment_status"] == "UNPAID"
        assert after["version"] == before["version"], (
            "a rejected submission must not bump the order version"
        )


class TestOnHandInputSet:
    def test_on_hand_excludes_quarantined_and_expired(self, api):
        """PRD §3.1: "The system also maintains a cached `on_hand_cached`
        integer on every SKU, equal to the sum of `qty_remaining` across all
        of the SKU's inventory lots whose status is `ACTIVE` or `DEPLETED` —
        lots in `QUARANTINED` or `EXPIRED` are deliberately excluded from this
        cached count. The cache is recomputed every time any lot under the
        SKU is inserted, updated, or deleted."
        PRD §3.2: "A lot is `EXPIRED` when today's date is strictly after
        `expires_on`."

        Design: Corner/calculations/sku_on_hand_recompute_excludes_quarantined_and_expired
        """
        set_clock()
        category = make_category(code="cq", display_name="CQ")
        sku = make_sku(category["id"], sku_code="sq1", base_price_cents=100)
        make_lot(sku["id"], lot_code="L1", qty_received=10,
                 expires_on="2027-01-01")
        l2 = make_lot(sku["id"], lot_code="L2", qty_received=5,
                      expires_on="2027-01-01")
        resp = api.quarantine_lot(l2["id"], {"quarantine_reason": "test"}, OFFICER)
        assert resp.status_code == 200, resp.text
        # Expires 2026-04-01, strictly before the logical clock 2026-05-01.
        make_lot(sku["id"], lot_code="L3", qty_received=7,
                 expires_on="2026-04-01")
        data = get_sku(sku["id"])
        assert data["on_hand_cached"] == 10, (
            "only the ACTIVE lot may count; QUARANTINED and EXPIRED lots are excluded"
        )
