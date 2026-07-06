"""Pricing calculations: provisional vs final divergence on catalog price edits,
per-shipment rounding order (round-then-sum), and the forward-looking vs
chronological component-availability variants.

Difficulty-queue translations for the two dual_variant_calc and one
combinatorial_formula (shipping mode-b) instances.

Two combinatorial_formula instances (mode-a "TIER_1 waives rush" and mode-c
"loyalty tier pinned before total") are SKIPPED under the PRD-first Core rule
because their pre-computed literals contradict PRD when applied to their own
setup: mode-a's account budget of 100,000,000 puts remaining_budget above
GOLD_THRESHOLD_CENTS so PRD requires a 3% loyalty discount not baked into the
literal 98563; mode-c's seed order (subtotal 1,000,000) violates the account's
own monthly_budget_cents=200,000, which PRD's ERR_BUDGET_EXCEEDED check at
budget-decision APPROVE would reject, preventing the seed from ever reaching
APPROVED as the setup requires.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, factories, fixtures,
)
from test_helpers.test_users import (
    TEST_USERS, make_account_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
FIN = TEST_USERS["finance_approver_headers"]


class TestOrderTotalCostProvisionalVsFinal:
    """Same 10-unit recipient data priced twice: at submit-for-approval (provisional
    variant, live template price) vs at APPROVE (final variant, price pinned via
    locked_template_version). A PATCH between the two calls makes the two figures
    numerically diverge — the instance's distinguishing evidence."""

    def test_provisional_uses_live_template_price(self, api):
        """PRD §3.4: "a provisional variant, used whenever approval_status is
        DRAFT or PENDING_APPROVAL, that reads the template's and branding
        profile's current (live) base_price_cents/version and is recomputed on
        every submission — so a catalog price edit landing between one submission
        and the next changes the provisional figure"

        Design: Difficulty/dual_variant_calc/order_total_cost_provisional_vs_final_diverge_on_catalog_price_edit
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=100_000,
            approval_threshold_cents=1000,
            template_kwargs=dict(name="Starter Basket",
                                 category="CORPORATE_WELCOME",
                                 base_price_cents=4000))
        p = fixtures.setup_pending_approval_order(
            api, base=base, rows=[factories.recipient_row(quantity=10)])
        order = validate_success(api.get_order(p["order"]["id"], ADMIN))
        # provisional: per_unit=4000, 10 units, TIER_0 0% discount, no rush;
        # remaining_budget=100000 < SILVER (250000) so 0% loyalty; total=40000.
        assert order["total_cost_cents"] == 40000
        assert order["approval_status"] == "PENDING_APPROVAL"

    def test_final_variant_uses_locked_template_version_after_catalog_edit(self, api):
        """PRD §3.4: "a final variant, used once approval_status is APPROVED,
        that instead reads the template and branding profile pinned at
        locked_template_version/locked_branding_version, freezing the figure at
        the price snapshot taken the moment of approval even if the catalog
        changes afterward"
        PRD §3.4: "for identical recipient data, the final figure can therefore
        differ numerically from the last provisional figure whenever a
        PlatformAdmin edited base_price_cents in between."

        Design: Difficulty/dual_variant_calc/order_total_cost_provisional_vs_final_diverge_on_catalog_price_edit
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=100_000,
            approval_threshold_cents=1000,
            template_kwargs=dict(name="Starter Basket",
                                 category="CORPORATE_WELCOME",
                                 base_price_cents=4000))
        p = fixtures.setup_pending_approval_order(
            api, base=base, rows=[factories.recipient_row(quantity=10)])
        # Catalog price edit lands between submit and APPROVE.
        validate_success(
            api.update_template(base["template"]["id"],
                                {"base_price_cents": 4500}, ADMIN))
        fixtures.budget_decision(
            api, order_id=p["order"]["id"], decision="APPROVE",
            approver_user_id="fin-appr-1",
            station_id=base["station"]["id"],
            scheduled_date="2026-03-05T00:00:00Z")
        order = validate_success(api.get_order(p["order"]["id"], ADMIN))
        assert order["approval_status"] == "APPROVED"
        # final: per_unit=4500, 10 units, TIER_0 0%, no rush; remaining_budget
        # 100000 < SILVER so 0% loyalty; total=45000 — different numeric answer
        # than the earlier provisional 40000 from the same recipient data.
        assert order["total_cost_cents"] == 45000
        assert order["total_cost_cents"] != 40000


class TestComponentAvailabilityForwardLookingVsChronological:
    """The forward-looking variant excludes reservations projected to have expired
    by the fulfillment date, while the chronological variant ignores future
    expiry and walks all still-active reservations in created_at order. On
    identical stock data (on_hand_qty=5 with an earlier 5-unit reservation
    expiring 2026-03-04, then a new 5-unit request scheduled for 2026-03-10) the
    two variants disagree: forward-looking accepts, chronological rejects."""

    def test_forward_looking_accepts_when_projected_expiry_frees_stock(self, api):
        """PRD §3.6: "The forward-looking variant, used per recipient row during
        CSV import ... takes a SKU's on_hand_qty and subtracts the reserved_qty
        of every existing reservation on that SKU that is still RESERVED or
        ALLOCATED and whose expires_at is either unset or lies after the
        importing order's scheduled_send_date (or the current instant, for
        unscheduled orders) — reservations that will have already spoiled by the
        relevant fulfillment date are excluded from the competing set, projecting
        availability forward to when the basket would actually be needed."

        Design: Difficulty/dual_variant_calc/component_available_qty_forward_looking_accepts_but_chronological_rejects
        """
        account = fixtures.create_account(
            api, monthly_budget_cents=1_000_000, approval_threshold_cents=1000)
        sku = fixtures.create_sku(
            api, name="Fresh Truffles", unit_cost_cents=800,
            is_perishable=True, shelf_life_days=3, on_hand_qty=5)
        template = fixtures.create_template(
            api, name="Truffle Box", category="CLIENT_APPRECIATION",
            base_price_cents=3000, is_perishable=True, shelf_life_days=3,
            sku_id=sku["id"])
        # Order_A: an existing 5-unit reservation, expires_at=2026-03-04.
        order_a, _ = fixtures.setup_order_with_recipients(
            api, account=account, template_id=template["id"],
            rows=[factories.recipient_row(email="old@example.com", quantity=5)],
            occasion="THANK_YOU")
        # Refresh account.version bumped by order_a creation.
        account = fixtures.get_account(api, account_id=account["id"])
        # Order_B with a scheduled_send_date well past R_old's expiry.
        order_b = fixtures.create_order(
            api, account=account, template_id=template["id"],
            occasion="THANK_YOU",
            scheduled_send_date="2026-03-10T00:00:00Z")
        hdrs = make_account_manager_headers(account["id"])
        resp = api.import_recipients(
            order_b["id"],
            {"rows": [factories.recipient_row(
                email="new@example.com", quantity=5)]}, hdrs)
        rows = validate_success(resp, 201)
        # forward_looking: R_old projected expired by 2026-03-10, so 5 units
        # available; the row is ACCEPTED.
        assert rows[0]["import_row_status"] == "ACCEPTED"

    def test_chronological_rejects_at_approve_ignoring_future_expiry(self, api):
        """PRD §3.6: "The chronological variant, used once per reservation at the
        moment an order's budget decision moves it toward ALLOCATED, ignores
        future expiry entirely: it walks every RESERVED/ALLOCATED reservation on
        the SKU strictly in ascending created_at order (ties are broken by
        created_at alone, no other field), accumulating reserved quantity as it
        goes, and a reservation is only satisfiable if that running total —
        including the reservation being checked — does not exceed on_hand_qty."
        PRD §3.6: "that shortfall is rejected with
        ERR_INSUFFICIENT_INVENTORY_CHRONOLOGICAL (409)."

        Design: Difficulty/dual_variant_calc/component_available_qty_forward_looking_accepts_but_chronological_rejects
        """
        account = fixtures.create_account(
            api, monthly_budget_cents=1_000_000, approval_threshold_cents=1000)
        sku = fixtures.create_sku(
            api, name="Fresh Truffles", unit_cost_cents=800,
            is_perishable=True, shelf_life_days=3, on_hand_qty=5)
        template = fixtures.create_template(
            api, name="Truffle Box", category="CLIENT_APPRECIATION",
            base_price_cents=3000, is_perishable=True, shelf_life_days=3,
            sku_id=sku["id"])
        station = fixtures.create_station(api, name="Station B", daily_capacity=1000)
        # Order_A: existing 5-unit reservation, still RESERVED (clock not advanced).
        order_a, _ = fixtures.setup_order_with_recipients(
            api, account=account, template_id=template["id"],
            rows=[factories.recipient_row(email="old2@example.com", quantity=5)],
            occasion="THANK_YOU")
        account = fixtures.get_account(api, account_id=account["id"])
        # Order_B with a scheduled_send_date well past R_old's expiry.
        order_b_rec = fixtures.setup_order_with_recipients(
            api, account=account, template_id=template["id"],
            rows=[factories.recipient_row(email="new2@example.com", quantity=5)],
            occasion="THANK_YOU",
            scheduled_send_date="2026-03-10T00:00:00Z")
        order_b = order_b_rec[0]
        fixtures.submit_for_approval(
            api, account_id=account["id"], order_id=order_b["id"],
            requested_by_user_id="emp-req-2")
        resp = api.budget_decision(
            order_b["id"],
            factories.budget_decision_payload(
                decision="APPROVE", approver_user_id="fin-appr-2",
                station_id=station["id"],
                scheduled_date="2026-03-02T00:00:00Z"),
            FIN)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY_CHRONOLOGICAL.value)


class TestShippingCostRoundPerShipmentThenSum:
    """Two shipments whose raw per-shipment cost is 664.4 cents each: rounding
    per-shipment first gives 664 + 664 = 1328; sum-then-round would give
    round(1328.8) = 1329. The PRD's pinned ordering (round per shipment before
    summing) must produce 1328."""

    def test_first_shipment_cost_rounded_half_up_to_664(self, api):
        """PRD §3.8: "An estimated weight in kilograms is formed by multiplying
        a fixed per-basket weight of 1.2 kg by the recipient's quantity; that
        weight is multiplied by the zone's per_kg_rate_cents and added to the
        zone's flat base_rate_cents, and the sum is rounded half-up to the
        nearest cent to produce shipping_cost_cents for that one shipment"

        Design: Difficulty/combinatorial_formula/shipping_cost_round_per_shipment_then_sum_mode_b
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=1_000_000,
            approval_threshold_cents=1_000_000,
            template_kwargs=dict(name="Candle Box", category="CLIENT_APPRECIATION",
                                 base_price_cents=2500))
        zone = fixtures.create_shipping_zone(
            api, zone_code="US-CENTRAL",
            country_codes=["US"], carrier="SwiftShip",
            base_rate_cents=500, per_kg_rate_cents=137,
            transit_days_min=2, transit_days_max=5, blackout_dates=[])
        order, rec = fixtures.setup_order_with_recipients(
            api, account=base["account"], template_id=base["template"]["id"],
            rows=[factories.recipient_row(email="one@example.com", quantity=1),
                  factories.recipient_row(email="two@example.com", quantity=1)],
            occasion="HOLIDAY")
        # Lock both proofs so shipment creation is unblocked.
        fixtures.lock_message_proof_for_recipient(
            api, account_id=base["account"]["id"], recipient_id=rec[0]["id"])
        fixtures.lock_message_proof_for_recipient(
            api, account_id=base["account"]["id"], recipient_id=rec[1]["id"],
            submitted_by="emp-msg-x", decided_by="proof-appr-y")
        s1 = fixtures.create_shipment(
            api, recipient_id=rec[0]["id"], zone_id=zone["id"],
            ship_date="2026-03-05T00:00:00Z")
        # raw = 500 + 137*(1.2*1) = 500 + 164.4 = 664.4 -> round_half_up 664
        assert s1["shipping_cost_cents"] == 664

    def test_order_shipping_total_is_sum_of_rounded_per_shipment(self, api):
        """PRD §3.8: "Any order-wide shipping total shown to a caller is simply
        the sum of its shipments' already-rounded shipping_cost_cents values —
        summing unrounded fractional costs first and rounding once at the end is
        explicitly not how this figure is produced, since it would understate the
        total whenever any shipment carries a fractional-cent remainder."

        Design: Difficulty/combinatorial_formula/shipping_cost_round_per_shipment_then_sum_mode_b
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=1_000_000,
            approval_threshold_cents=1_000_000,
            template_kwargs=dict(name="Candle Box", category="CLIENT_APPRECIATION",
                                 base_price_cents=2500))
        zone = fixtures.create_shipping_zone(
            api, zone_code="US-CENTRAL",
            country_codes=["US"], carrier="SwiftShip",
            base_rate_cents=500, per_kg_rate_cents=137,
            transit_days_min=2, transit_days_max=5, blackout_dates=[])
        order, rec = fixtures.setup_order_with_recipients(
            api, account=base["account"], template_id=base["template"]["id"],
            rows=[factories.recipient_row(email="a@example.com", quantity=1),
                  factories.recipient_row(email="b@example.com", quantity=1)],
            occasion="HOLIDAY")
        for r in rec:
            fixtures.lock_message_proof_for_recipient(
                api, account_id=base["account"]["id"], recipient_id=r["id"],
                submitted_by=f"emp-msg-{r['id'][:6]}",
                decided_by=f"proof-appr-{r['id'][:6]}")
        s1 = fixtures.create_shipment(
            api, recipient_id=rec[0]["id"], zone_id=zone["id"],
            ship_date="2026-03-05T00:00:00Z")
        s2 = fixtures.create_shipment(
            api, recipient_id=rec[1]["id"], zone_id=zone["id"],
            ship_date="2026-03-05T00:00:00Z")
        assert s1["shipping_cost_cents"] == 664
        assert s2["shipping_cost_cents"] == 664
        # The pinned round-per-shipment-then-sum ordering yields 1328, not 1329.
        assert (s1["shipping_cost_cents"] + s2["shipping_cost_cents"]) == 1328
