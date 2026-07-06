"""Difficulty rule: transitive_cascade.

Depth-3 chains where each link causes the next:
  (A) citation issue -> vehicle crosses boot threshold -> AUTO boot order ->
      registration hold placed;
  (B) payment settle -> citation PAID -> vehicle de-escalates -> boot order
      CANCELLED -> registration hold CLEARED.
"""
from test_helpers import (
    validate_success,
    validate_paginated,
    TEST_USERS,
    setup_issuing_context,
    issue_in_context,
    setup_boot_eligible_vehicle,
    create_payment,
)

ADMIN = TEST_USERS["admin_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
MOTORIST = TEST_USERS["motorist_headers"]


class TestIssueEscalatesToBoot:
    def _setup_two_then_third(self):
        ctx = setup_issuing_context(base_fine_cents=15000, code="HYDRANT")
        issue_in_context(ctx, evidence_photo_url="https://ev/t1.jpg")
        issue_in_context(ctx, evidence_photo_url="https://ev/t2.jpg")
        third = issue_in_context(ctx, evidence_photo_url="https://ev/t3.jpg")
        return ctx, third

    def test_third_citation_escalates_vehicle_to_boot_eligible(self, api):
        """PRD §3.4: "Otherwise, if it is at least 50,000 cents, the vehicle is
        `BOOT_ELIGIBLE`."

        Design: Difficulty/transitive_cascade/citation_issue_to_boot_to_reghold
        """
        ctx, _ = self._setup_two_then_third()
        veh = validate_success(api.get_vehicle(ctx["vehicle"]["id"], ADMIN))
        assert veh["outstanding_balance_cents"] == 62500, \
            f"expected 62500 outstanding, got {veh['outstanding_balance_cents']}"
        assert veh["scofflaw_status"] == "BOOT_ELIGIBLE", \
            f"expected BOOT_ELIGIBLE, got {veh['scofflaw_status']}"

    def test_escalation_autocreates_order_and_places_hold(self, api):
        """PRD §3.4: "Whenever a citation issue pushes the vehicle to `BOOT_ELIGIBLE`
        or `TOW_ELIGIBLE`, the system automatically creates a boot/tow enforcement
        order (with `origin` of `AUTO`) and that order's creation places a
        `RegistrationHold`, so the vehicle's `has_active_registration_hold` becomes
        true."

        Design: Difficulty/transitive_cascade/citation_issue_to_boot_to_reghold
        """
        ctx, _ = self._setup_two_then_third()
        vid = ctx["vehicle"]["id"]

        orders, ometa = validate_paginated(
            api.list_boot_tow_orders(ADMIN, params={"vehicle_id": vid}))
        assert ometa["total_count"] == 1, f"expected exactly 1 order, got {ometa['total_count']}"
        assert orders[0]["status"] == "ORDERED"
        assert orders[0]["origin"] == "AUTO"

        holds, hmeta = validate_paginated(
            api.list_registration_holds(ADMIN, params={"vehicle_id": vid}))
        assert hmeta["total_count"] == 1, f"expected exactly 1 hold, got {hmeta['total_count']}"
        assert holds[0]["status"] == "PLACED"

        veh = validate_success(api.get_vehicle(vid, ADMIN))
        assert veh["has_active_registration_hold"] is True


class TestSettleDeescalatesAndClears:
    def test_settle_marks_citation_paid_and_deescalates_vehicle(self, api):
        """PRD §3.5: "If that brings the amount due to 0 — that is, once the paid
        amount reaches or exceeds the fine — the citation transitions to `PAID` (from
        either `ISSUED` or `UPHELD`), and the vehicle ledger and scofflaw tier are
        recomputed; this de-escalation may cancel a still-`ORDERED` boot/tow order and
        clear its hold, as described in §3.8."

        Design: Difficulty/transitive_cascade/payment_settle_to_paid_to_clear
        """
        ctx = setup_boot_eligible_vehicle()
        c3 = ctx["citations"][2]
        pay = create_payment(c3["id"], 25000, method="CARD")
        validate_success(api.settle_payment(pay["id"], MOTORIST))

        cit = validate_success(api.get_citation(c3["id"], ADMIN))
        assert cit["status"] == "PAID"
        veh = validate_success(api.get_vehicle(ctx["vehicle"]["id"], ADMIN))
        assert veh["outstanding_balance_cents"] == 37500, \
            f"remaining balance must be 37500, got {veh['outstanding_balance_cents']}"
        assert veh["scofflaw_status"] == "NONE", \
            f"vehicle must de-escalate to NONE, got {veh['scofflaw_status']}"

    def test_deescalation_cancels_order_and_clears_hold(self, api):
        """PRD §3.8: "When a payment settlement, a refund reversal, a void, or a
        dismissal recomputes a vehicle down to a `scofflaw_status` of `NONE` or
        `SCOFFLAW`, the system cancels the vehicle's still-`ORDERED` enforcement
        order, moving it from `ORDERED` to `CANCELLED`; an order that has already been
        `APPLIED` is not auto-cancelled. Cancelling an order in turn clears the
        `PLACED` `RegistrationHold` it placed, moving that hold from `PLACED` to
        `CLEARED`, and once no `PLACED` hold remains for the vehicle its
        `has_active_registration_hold` is recomputed to false."

        Design: Difficulty/transitive_cascade/payment_settle_to_paid_to_clear
        """
        ctx = setup_boot_eligible_vehicle()
        c3 = ctx["citations"][2]
        pay = create_payment(c3["id"], 25000, method="CARD")
        validate_success(api.settle_payment(pay["id"], MOTORIST))

        order = validate_success(api.get_boot_tow_order(ctx["boot_order"]["id"], ADMIN))
        assert order["status"] == "CANCELLED", \
            f"still-ORDERED order must be cancelled, got {order['status']}"

        holds, hmeta = validate_paginated(
            api.list_registration_holds(ADMIN, params={"vehicle_id": ctx["vehicle"]["id"]}))
        assert hmeta["total_count"] == 1
        assert holds[0]["status"] == "CLEARED", \
            f"placing hold must be cleared, got {holds[0]['status']}"

        veh = validate_success(api.get_vehicle(ctx["vehicle"]["id"], ADMIN))
        assert veh["has_active_registration_hold"] is False
