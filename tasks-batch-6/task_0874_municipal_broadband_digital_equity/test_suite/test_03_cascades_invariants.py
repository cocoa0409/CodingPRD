"""Transitive cascades and compensating-action invariants: outage resolution
repricing invoices, service-area suspension cascade, device-inventory
conservation, and grant-fund money conservation.

Covers Difficulty queue rules transitive_cascade and compensating_invariant.
"""
import pytest

from test_helpers import (
    validate_success, validate_paginated,
    assert_grant_partition,
    TEST_USERS, make_officer_headers,
    fixtures as fx,
)

CARE = TEST_USERS["customer_care_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
NOC = TEST_USERS["noc_operator_headers"]
ANY_READER = TEST_USERS["program_admin_headers"]


# =====================================================================
# Rule 4 — transitive_cascade / outage_resolve_credit_invoice_paid_depth3
# =====================================================================
class TestOutageResolveCascade:
    def _setup(self, api):
        fx.set_clock(api, "2026-07-01T00:00:00Z")
        ctx = fx.setup_active_subscription(api, homes_passed=100, price=6000,
                                           install_start="2026-06-01T09:00:00Z")
        invoice = fx.generate_invoice(api, ctx["subscription"]["id"],
                                      "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
        outage = fx.report_outage(api, ctx["area"]["id"], "2026-06-01T00:00:00Z", severity="FULL")
        validate_success(api.resolve_outage(outage["id"], {"ended_at": "2026-07-01T00:00:00Z"}, NOC))
        return ctx, invoice, outage

    def test_credit_created_and_applied_zeroing_invoice(self, api):
        """PRD §3.6: "the server creates an SLA credit in `PENDING` whose
        `downtime_minutes` is the final whole-minute downtime and whose `credit_cents`
        is the final-variant amount, linking it to the subscription via
        `subscription_id` and to the outage via `outage_id`"
        PRD §3.6: "the credit's `applied_invoice_id` is set to that invoice, the
        invoice's `sla_credit_cents` and `total_due_cents` are recomputed per §3.5,
        and the credit's `status` becomes `APPLIED`"

        Design: Difficulty/transitive_cascade/outage_resolve_credit_invoice_paid_depth3
        """
        ctx, invoice, outage = self._setup(api)
        credits, _ = validate_paginated(
            api.list_sla_credits(ANY_READER, params={"outage_id": outage["id"]}))
        subject = [c for c in credits if c["subscription_id"] == ctx["subscription"]["id"]]
        assert len(subject) == 1
        assert subject[0]["credit_cents"] == 6000, \
            f"43200 downtime min -> full 6000 credit, got {subject[0]['credit_cents']}"
        assert subject[0]["status"] == "APPLIED"
        fetched = validate_success(api.get_invoice(invoice["id"], ANY_READER))
        assert fetched["sla_credit_cents"] == 6000
        assert fetched["total_due_cents"] == 0

    def test_invoice_paid_and_billing_returns_current(self, api):
        """PRD §3.6: "if a recomputed invoice's `total_due_cents` is at or below its
        `amount_paid_cents`, the invoice moves to `PAID`, and if every invoice for the
        subscription is then settled, the subscription's `billing_status` returns to
        `CURRENT`"

        Design: Difficulty/transitive_cascade/outage_resolve_credit_invoice_paid_depth3
        """
        ctx, invoice, outage = self._setup(api)
        fetched = validate_success(api.get_invoice(invoice["id"], ANY_READER))
        assert fetched["status"] == "PAID", f"zeroed invoice should be PAID, got {fetched['status']}"
        sub = validate_success(api.get_subscription(ctx["subscription"]["id"], ANY_READER))
        assert sub["billing_status"] == "CURRENT"


# =====================================================================
# Rule 4 — transitive_cascade / service_area_suspend_cascade_depth3
# =====================================================================
class TestServiceAreaSuspendCascade:
    def _setup(self, api):
        grant = fx.create_grant(api)
        area = fx.create_serviceable_area(api, grant["id"], homes_passed=100)
        plan = fx.create_plan(api)
        subscriber = fx.create_subscriber(api, area["id"])
        subscription = fx.create_pending_subscription(api, subscriber["id"], plan["id"], area["id"])
        tech = fx.create_technician(api)
        io = fx.schedule_install(api, subscription["id"], tech["id"], "2026-06-02T09:00:00Z")
        device = fx.create_device(api, serial_number="SN-1")
        validate_success(api.assign_device(device["id"], {"subscription_id": subscription["id"]}, DISPATCH))
        validate_success(api.suspend_service_area(area["id"], ANY_READER))
        return area, subscription, io, device

    def test_area_and_subscription_suspended(self, api):
        """PRD §3.1: "Suspending an area, optionally annotated with a `reason`,
        triggers a three-level cascade: every subscription in the area whose
        `service_status` is `PENDING_INSTALL` or `ACTIVE` moves to `SUSPENDED`
        (level 1)"

        Design: Difficulty/transitive_cascade/service_area_suspend_cascade_depth3
        """
        area, subscription, _, _ = self._setup(api)
        fetched_area = validate_success(api.get_service_area(area["id"], ANY_READER))
        assert fetched_area["status"] == "SUSPENDED"
        fetched_sub = validate_success(api.get_subscription(subscription["id"], ANY_READER))
        assert fetched_sub["service_status"] == "SUSPENDED"

    def test_install_cancelled_and_device_restocked(self, api):
        """PRD §3.1: "for each such subscription, every install order still in
        `SCHEDULED` moves to `CANCELLED` (level 2); and for each cancelled install
        order, its reserved `ASSIGNED` `CPE_MODEM` device is released back to
        `IN_STOCK` with its subscription link cleared (level 3)."

        Design: Difficulty/transitive_cascade/service_area_suspend_cascade_depth3
        """
        _, _, io, device = self._setup(api)
        fetched_io = validate_success(api.get_install_order(io["id"], ANY_READER))
        assert fetched_io["status"] == "CANCELLED"
        fetched_device = validate_success(api.get_device(device["id"], ANY_READER))
        assert fetched_device["status"] == "IN_STOCK"
        assert fetched_device["subscription_id"] is None


# =====================================================================
# Rule 9 — compensating_invariant / device_inventory_count_conservation
# =====================================================================
class TestDeviceInventoryConservation:
    def _setup(self, api):
        grant = fx.create_grant(api)
        area = fx.create_serviceable_area(api, grant["id"], homes_passed=100)
        plan = fx.create_plan(api)
        subscriber = fx.create_subscriber(api, area["id"])
        subscription = fx.create_pending_subscription(api, subscriber["id"], plan["id"], area["id"])
        d1 = fx.create_device(api, serial_number="SN-1")
        fx.create_device(api, serial_number="SN-2")
        fx.create_device(api, serial_number="SN-3")
        validate_success(api.assign_device(d1["id"], {"subscription_id": subscription["id"]}, DISPATCH))
        return d1

    def test_returned_device_back_in_stock_link_cleared(self, api):
        """PRD §3.3: "Returning a device restocks it: an `ASSIGNED` device returns to
        `IN_STOCK` with its `subscription_id` and `enrollment_id` links cleared so
        total inventory is conserved"

        Design: Difficulty/compensating_invariant/device_inventory_count_conservation
        """
        d1 = self._setup(api)
        returned = validate_success(api.return_device(d1["id"], DISPATCH))
        assert returned["status"] == "IN_STOCK"
        assert returned["subscription_id"] is None

    def test_total_inventory_count_conserved(self, api):
        """PRD §3.3: "an `ASSIGNED` device returns to `IN_STOCK` with its
        `subscription_id` and `enrollment_id` links cleared so total inventory is
        conserved"

        Design: Difficulty/compensating_invariant/device_inventory_count_conservation
        """
        d1 = self._setup(api)
        validate_success(api.return_device(d1["id"], DISPATCH))
        devices, meta = validate_paginated(api.list_devices(ANY_READER))
        assert meta["total_count"] == 3, f"inventory count conserved at 3, got {meta['total_count']}"
        assert all(d["status"] == "IN_STOCK" for d in devices), \
            "all three devices back in IN_STOCK after the return"


# =====================================================================
# Rule 9 — compensating_invariant / grant_funds_money_conservation
# =====================================================================
class TestGrantFundsConservation:
    def _submitted_claim(self, api):
        grant = fx.create_grant(api, award_amount_cents=1_000_000)
        g_v = grant["version"]
        ctx = fx.setup_active_subscription(api, grant=grant, homes_passed=100, price=6000)
        subsidy = fx.create_subsidy_program(api, monthly_discount_cents=3000)
        fx.create_active_enrollment(api, ctx["subscriber"]["id"], subsidy["id"],
                                    household_size=2, annual_income_cents=3_000_000)
        claim = fx.create_claim(api, grant["id"], [ctx["area"]["id"]], g_v)
        submitted = fx.submit_claim(api, claim["id"], analyst_user_id="analyst-1")
        return grant, claim, submitted

    def test_reject_releases_committed_funds(self, api):
        """PRD §3.7: "Rejection, optionally annotated with a `reason`, moves the claim
        to the terminal `REJECTED` and compensatingly releases the committed funds:
        `committed_balance_cents` decreases by `amount_claimed_cents` and
        `available_balance_cents` is restored, again preserving the partition."

        Design: Difficulty/compensating_invariant/grant_funds_money_conservation
        """
        grant, claim, _ = self._submitted_claim(api)
        rejected = validate_success(
            api.reject_grant_claim(claim["id"], make_officer_headers("officer-1"),
                                   {"reason": "insufficient documentation"}))
        assert rejected["status"] == "REJECTED"
        fetched = validate_success(api.get_grant(grant["id"], ANY_READER))
        assert fetched["committed_balance_cents"] == 0
        assert fetched["disbursed_balance_cents"] == 0
        assert fetched["available_balance_cents"] == 1_000_000

    def test_partition_invariant_holds_through_submit_and_reject(self, api):
        """PRD §2.10: "Submitting a claim moves funds from available into committed;
        approving a claim moves those same funds from committed into disbursed, leaving
        available unchanged; rejecting a claim moves the committed funds back to
        available."

        Design: Difficulty/compensating_invariant/grant_funds_money_conservation
        """
        grant, claim, submitted = self._submitted_claim(api)
        # After submit: committed = amount, available reduced, partition holds.
        after_submit = validate_success(api.get_grant(grant["id"], ANY_READER))
        assert after_submit["committed_balance_cents"] == 1000
        assert after_submit["available_balance_cents"] == 999_000
        assert_grant_partition(after_submit)
        # After reject: funds released, partition still holds.
        validate_success(api.reject_grant_claim(claim["id"], make_officer_headers("officer-1")))
        after_reject = validate_success(api.get_grant(grant["id"], ANY_READER))
        assert_grant_partition(after_reject)
