"""Priority-pair conflicts (state-before-business-constraint, safety-before-referential)
and resource-temporal overlap (assembly-station daily capacity, shipping-zone
blackout adjacency).

Translations of Difficulty/priority_pair_validation_conflict (2) and
Difficulty/resource_temporal_overlap (2).
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
SHIP = TEST_USERS["shipping_ops_headers"]


class TestCancelledOrderWithZeroRecipients:
    """A submit-for-approval on an order that is BOTH production_status=CANCELLED
    AND has zero ACCEPTED recipients must surface the state-check failure
    (priority 11) rather than the business-constraint failure (priority 22)."""

    def test_state_check_precedes_empty_recipient_check(self, api):
        """PRD §2.9: "every request is evaluated against the full validation
        table in strict ascending priority order: header authentication failures
        surface before role-authorization failures, which surface before any
        not-found error for a referenced resource ..., which surface before
        state-machine legality failures, which surface before business-safety
        and referential failures ..., which surface before business-constraint
        failures (self-approval, self-proof-approval, empty recipient list, ...)"

        Design: Difficulty/priority_pair_validation_conflict/cancelled_order_with_zero_recipients_fails_state_before_business_constraint
        """
        account = fixtures.create_account(
            api, monthly_budget_cents=1_000_000, approval_threshold_cents=1000)
        sku = fixtures.create_sku(api, name="Keychain", unit_cost_cents=150,
                                  is_perishable=False, on_hand_qty=100)
        template = fixtures.create_template(
            api, name="Keychain Basket", category="CORPORATE_WELCOME",
            base_price_cents=2000, sku_id=sku["id"])
        order = fixtures.create_order(
            api, account=account, template_id=template["id"], occasion="CUSTOM")
        hdrs = make_account_manager_headers(account["id"])
        # Cancel while DRAFT (production_status still DRAFT).
        validate_success(api.cancel_order(order["id"], hdrs))
        # Now attempt submit — both checks would fail; state precedes constraint.
        resp = api.submit_for_approval(
            order["id"],
            factories.submit_for_approval_payload(
                requested_by_user_id="emp-req-9"),
            hdrs)
        validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE.value)

    def test_isolated_empty_recipient_check_when_state_is_legal(self, api):
        """PRD §3.4: "It further requires at least one ACCEPTED recipient on
        the order, or ERR_EMPTY_RECIPIENT_LIST (422)"

        Design: Difficulty/priority_pair_validation_conflict/cancelled_order_with_zero_recipients_fails_state_before_business_constraint
        """
        # Same conditions but WITHOUT the CANCELLED prior state — isolates the
        # priority-22 check by removing the priority-11 conflict.
        account = fixtures.create_account(
            api, monthly_budget_cents=1_000_000, approval_threshold_cents=1000)
        sku = fixtures.create_sku(api, name="Keychain2", unit_cost_cents=150,
                                  is_perishable=False, on_hand_qty=100)
        template = fixtures.create_template(
            api, name="Keychain Basket 2", category="CORPORATE_WELCOME",
            base_price_cents=2000, sku_id=sku["id"])
        order = fixtures.create_order(
            api, account=account, template_id=template["id"], occasion="CUSTOM")
        hdrs = make_account_manager_headers(account["id"])
        resp = api.submit_for_approval(
            order["id"],
            factories.submit_for_approval_payload(
                requested_by_user_id="emp-req-9b"),
            hdrs)
        validate_error(resp, ApiErrorId.ERR_EMPTY_RECIPIENT_LIST.value)


class TestExpiredPerishableAndUnapprovedBranding:
    """A budget-decision APPROVE where BOTH perishable safety (priority 16) AND
    branding-profile-approval (priority 18) would fail must surface the safety
    failure — the earlier priority."""

    def test_perishable_safety_precedes_branding_approval_check(self, api):
        """PRD §2.9: "which surface before business-safety and referential
        failures (perishable safety, chronological inventory sufficiency,
        branding approval, message-proof lock)"
        PRD §3.6: "A second safety check runs alongside the chronological
        availability check whenever an order moves toward approval: every
        ComponentSKU in the order's basket composition must still have unexpired
        shelf life — computed as that SKU's created_at plus its shelf_life_days
        — on the calendar day named by scheduled_date for the assembly station
        handling the order"
        PRD §3.6: "A violation is rejected with ERR_PERISHABLE_SAFETY_VIOLATION
        (422)."

        Design: Difficulty/priority_pair_validation_conflict/expired_perishable_and_unapproved_branding_fails_safety_before_referential
        """
        account = fixtures.create_account(
            api, monthly_budget_cents=1_000_000, approval_threshold_cents=1000)
        sku = fixtures.create_sku(
            api, name="Fresh Cheese", unit_cost_cents=700,
            is_perishable=True, shelf_life_days=5, on_hand_qty=100)
        template = fixtures.create_template(
            api, name="Cheese Basket", category="CLIENT_APPRECIATION",
            base_price_cents=4500, is_perishable=True, shelf_life_days=5,
            sku_id=sku["id"])
        station = fixtures.create_station(api, name="Station L", daily_capacity=1000)
        profile = fixtures.create_branding_profile(
            api, account=account, name="Unreviewed Kit",
            accent_color="#445566", card_stock="GLOSS")
        account = fixtures.get_account(api, account_id=account["id"])
        order = fixtures.create_order(
            api, account=account, template_id=template["id"],
            occasion="CLIENT_APPRECIATION",
            branding_profile_id=profile["id"])
        fixtures.import_recipients(
            api, account_id=account["id"], order_id=order["id"],
            rows=[factories.recipient_row(email="priority@example.com",
                                          quantity=2)])
        fixtures.submit_for_approval(
            api, account_id=account["id"], order_id=order["id"],
            requested_by_user_id="emp-req-10")
        # scheduled_date is 2026-03-20; SKU created at clock default
        # 2026-03-01 + shelf_life_days=5 → expires 2026-03-06 (before the
        # scheduled 2026-03-20). Priority-16 must fire, not priority-18.
        resp = api.budget_decision(
            order["id"],
            factories.budget_decision_payload(
                decision="APPROVE", approver_user_id="fin-appr-10",
                station_id=station["id"],
                scheduled_date="2026-03-20T00:00:00Z"),
            FIN)
        validate_error(resp, ApiErrorId.ERR_PERISHABLE_SAFETY_VIOLATION.value)

    def test_branding_check_surfaces_when_safety_is_clean(self, api):
        """PRD §3.3: "the order cannot advance out of PENDING_APPROVAL into
        APPROVED while its branding_profile_id points at a profile whose
        approved is still false — that attempt is rejected with
        ERR_BRANDING_PROFILE_NOT_APPROVED (422)."

        Design: Difficulty/priority_pair_validation_conflict/expired_perishable_and_unapproved_branding_fails_safety_before_referential
        """
        # Same setup, but with non-perishable SKU/template so priority-16 no
        # longer applies — leaving priority-18 to fire alone.
        account = fixtures.create_account(
            api, monthly_budget_cents=1_000_000, approval_threshold_cents=1000)
        sku = fixtures.create_sku(
            api, name="Aged Cheese", unit_cost_cents=700,
            is_perishable=False, on_hand_qty=100)
        template = fixtures.create_template(
            api, name="Cheese Basket 2", category="CLIENT_APPRECIATION",
            base_price_cents=4500, is_perishable=False, sku_id=sku["id"])
        station = fixtures.create_station(api, name="Station L2", daily_capacity=1000)
        profile = fixtures.create_branding_profile(
            api, account=account, name="Still Unreviewed Kit",
            accent_color="#445566", card_stock="GLOSS")
        account = fixtures.get_account(api, account_id=account["id"])
        order = fixtures.create_order(
            api, account=account, template_id=template["id"],
            occasion="CLIENT_APPRECIATION",
            branding_profile_id=profile["id"])
        fixtures.import_recipients(
            api, account_id=account["id"], order_id=order["id"],
            rows=[factories.recipient_row(email="p2@example.com", quantity=2)])
        fixtures.submit_for_approval(
            api, account_id=account["id"], order_id=order["id"],
            requested_by_user_id="emp-req-10b")
        resp = api.budget_decision(
            order["id"],
            factories.budget_decision_payload(
                decision="APPROVE", approver_user_id="fin-appr-10b",
                station_id=station["id"],
                scheduled_date="2026-03-04T00:00:00Z"),
            FIN)
        validate_error(resp, ApiErrorId.ERR_BRANDING_PROFILE_NOT_APPROVED.value)


class TestAssemblyStationDailyCapacityOverlap:
    """Two orders competing for the same station+date must not exceed the
    station's daily_capacity summed across all orders."""

    def test_second_approve_rejected_when_capacity_summed_exceeds_ceiling(self, api):
        """PRD §3.6: "Separately, the target AssemblyStation named by station_id
        has a daily_capacity ceiling: summing the quantity of every AssemblyTask
        — across every order, not just this one — already scheduled at that
        station on that scheduled_date, plus this order's own total recipient
        quantity, must not exceed that ceiling, or the request fails with
        ERR_ASSEMBLY_CAPACITY_EXCEEDED (409)."

        Design: Difficulty/resource_temporal_overlap/assembly_station_daily_capacity_aggregate_overlap
        """
        account = fixtures.create_account(
            api, monthly_budget_cents=10_000_000, approval_threshold_cents=1000)
        sku = fixtures.create_sku(api, name="Puzzle Box", unit_cost_cents=500,
                                  is_perishable=False, on_hand_qty=1000)
        template = fixtures.create_template(
            api, name="Puzzle Basket", base_price_cents=4000, sku_id=sku["id"])
        station = fixtures.create_station(api, name="Station P", daily_capacity=15)
        base = {"account": account, "sku": sku, "template": template, "station": station}
        # Order_A: 10 units on 2026-03-04 (uses 10 of 15).
        fixtures.setup_approved_order(
            api, base=base,
            rows=[factories.recipient_row(email="capa@example.com", quantity=10)],
            requested_by_user_id="emp-req-14",
            approver_user_id="fin-appr-14",
            scheduled_date="2026-03-04T00:00:00Z")
        account = fixtures.get_account(api, account_id=account["id"])
        # Order_B: 6 additional units → 10+6=16 > 15.
        order_b_rec = fixtures.setup_order_with_recipients(
            api, account=account, template_id=template["id"],
            rows=[factories.recipient_row(email="capb@example.com", quantity=6)],
            occasion="ONBOARDING")
        order_b = order_b_rec[0]
        fixtures.submit_for_approval(
            api, account_id=account["id"], order_id=order_b["id"],
            requested_by_user_id="emp-req-15")
        resp = api.budget_decision(
            order_b["id"],
            factories.budget_decision_payload(
                decision="APPROVE", approver_user_id="fin-appr-15",
                station_id=station["id"],
                scheduled_date="2026-03-04T00:00:00Z"),
            FIN)
        validate_error(resp, ApiErrorId.ERR_ASSEMBLY_CAPACITY_EXCEEDED.value)

    def test_order_b_stays_draft_when_capacity_rejected(self, api):
        """PRD §3.4: "If any of these fail during the auto-fire, the entire
        submit-for-approval call fails as one atomic unit"
        PRD §3.4: "APPROVE is held to the fuller ordered check list already
        enumerated in the auto-approval paragraph above, with the
        fulfillment-reference existence check firing first, then the
        decision-state check, then perishable safety, chronological inventory
        sufficiency, branding approval, self-approval (here it does apply,
        since a human decider is present), assembly capacity, and finally the
        budget hard cap."

        Design: Difficulty/resource_temporal_overlap/assembly_station_daily_capacity_aggregate_overlap
        """
        # An APPROVE rejected for ERR_ASSEMBLY_CAPACITY_EXCEEDED leaves the
        # order still in PENDING_APPROVAL, and — critically — production_status
        # unchanged at DRAFT (Cascade A never fired).
        account = fixtures.create_account(
            api, monthly_budget_cents=10_000_000, approval_threshold_cents=1000)
        sku = fixtures.create_sku(api, name="Puzzle Box2", unit_cost_cents=500,
                                  is_perishable=False, on_hand_qty=1000)
        template = fixtures.create_template(
            api, name="Puzzle Basket 2", base_price_cents=4000, sku_id=sku["id"])
        station = fixtures.create_station(api, name="Station P2", daily_capacity=15)
        base = {"account": account, "sku": sku, "template": template, "station": station}
        fixtures.setup_approved_order(
            api, base=base,
            rows=[factories.recipient_row(email="capa2@example.com", quantity=10)],
            requested_by_user_id="emp-req-14b",
            approver_user_id="fin-appr-14b",
            scheduled_date="2026-03-04T00:00:00Z")
        account = fixtures.get_account(api, account_id=account["id"])
        order_b_rec = fixtures.setup_order_with_recipients(
            api, account=account, template_id=template["id"],
            rows=[factories.recipient_row(email="capb2@example.com", quantity=6)],
            occasion="ONBOARDING")
        order_b = order_b_rec[0]
        fixtures.submit_for_approval(
            api, account_id=account["id"], order_id=order_b["id"],
            requested_by_user_id="emp-req-15b")
        api.budget_decision(
            order_b["id"],
            factories.budget_decision_payload(
                decision="APPROVE", approver_user_id="fin-appr-15b",
                station_id=station["id"],
                scheduled_date="2026-03-04T00:00:00Z"),
            FIN)
        after = validate_success(api.get_order(order_b["id"], ADMIN))
        assert after["production_status"] == "DRAFT"


class TestShippingZoneBlackoutDateAdjacency:
    """A shipment whose transit window [ship_date, ship_date+transit_days_min)
    intersects any of the zone's blackout dates is rejected."""

    def test_shipment_rejected_when_blackout_falls_inside_transit_window(self, api):
        """PRD §3.8: "A temporal check then applies: every calendar day from
        ship_date up to, but not including, ship_date plus the zone's
        transit_days_min must contain none of that zone's blackout_dates"
        PRD §3.8: "Either failure is rejected with ERR_SHIPPING_BLACKOUT_CONFLICT
        (409)."

        Design: Difficulty/resource_temporal_overlap/shipping_zone_blackout_date_buffer_adjacency_overlap
        """
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=1_000_000,
            approval_threshold_cents=1_000_000,
            template_kwargs=dict(name="Blanket Basket", category="HOLIDAY",
                                 base_price_cents=4500))
        zone = fixtures.create_shipping_zone(
            api, zone_code="US-SNOW", country_codes=["US"],
            carrier="WinterFreight", base_rate_cents=600, per_kg_rate_cents=120,
            transit_days_min=2, transit_days_max=6,
            blackout_dates=["2026-03-15"])
        _, rec = fixtures.setup_order_with_recipients(
            api, account=base["account"], template_id=base["template"]["id"],
            rows=[factories.recipient_row(email="blackout@example.com",
                                          quantity=1)],
            occasion="HOLIDAY")
        fixtures.lock_message_proof_for_recipient(
            api, account_id=base["account"]["id"], recipient_id=rec[0]["id"],
            submitted_by="emp-msg-4", decided_by="proof-appr-4")
        # ship_date=2026-03-14 → transit window [2026-03-14, 2026-03-16) contains
        # the blackout date 2026-03-15.
        resp = api.create_shipment(
            rec[0]["id"],
            factories.create_shipment_payload(
                zone_id=zone["id"], ship_date="2026-03-14T00:00:00Z"),
            SHIP)
        validate_error(resp, ApiErrorId.ERR_SHIPPING_BLACKOUT_CONFLICT.value)

    def test_shipment_accepted_when_transit_window_clears_blackout(self, api):
        """PRD §3.8: "every calendar day from ship_date up to, but not
        including, ship_date plus the zone's transit_days_min must contain
        none of that zone's blackout_dates"

        Design: Difficulty/resource_temporal_overlap/shipping_zone_blackout_date_buffer_adjacency_overlap
        """
        # Move ship_date to 2026-03-16 → window [2026-03-16, 2026-03-18)
        # clears the 2026-03-15 blackout. This isolates the temporal check
        # from any other setup difference.
        base = fixtures.setup_catalog(
            api, monthly_budget_cents=1_000_000,
            approval_threshold_cents=1_000_000,
            template_kwargs=dict(name="Blanket Basket 2", category="HOLIDAY",
                                 base_price_cents=4500))
        zone = fixtures.create_shipping_zone(
            api, zone_code="US-SNOW-2", country_codes=["US"],
            carrier="WinterFreight", base_rate_cents=600, per_kg_rate_cents=120,
            transit_days_min=2, transit_days_max=6,
            blackout_dates=["2026-03-15"])
        _, rec = fixtures.setup_order_with_recipients(
            api, account=base["account"], template_id=base["template"]["id"],
            rows=[factories.recipient_row(email="blackout2@example.com",
                                          quantity=1)],
            occasion="HOLIDAY")
        fixtures.lock_message_proof_for_recipient(
            api, account_id=base["account"]["id"], recipient_id=rec[0]["id"],
            submitted_by="emp-msg-4b", decided_by="proof-appr-4b")
        shipment = fixtures.create_shipment(
            api, recipient_id=rec[0]["id"], zone_id=zone["id"],
            ship_date="2026-03-16T00:00:00Z")
        assert shipment["status"] == "CREATED"
