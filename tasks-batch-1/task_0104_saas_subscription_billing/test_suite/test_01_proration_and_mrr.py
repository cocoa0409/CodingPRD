"""Proration, committed MRR vs recognized revenue, and MRR conservation.

Queue A (difficulty) translations for:
  dual_variant_calc, transitive_cascade/change_plan_cascade_depth2_planid_to_mrr,
  compensating_invariant (both instances).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    make_account_owner_headers,
    TEST_USERS,
    change_plan_payload,
    create_plan_payload,
    add_addon_payload,
    find_line_by_kind,
    assert_invoice_total_consistent,
    setup_active_subscription,
    setup_converted_subscription,
    create_addon,
    set_clock,
    list_account_invoices,
)

ADMIN = TEST_USERS["billing_admin_headers"]


def _owner(account_id):
    return make_account_owner_headers(account_id)


def _make_pro_plan(api, fee=9000):
    return get_success_data(
        api.create_plan(
            create_plan_payload(tier="PRO", monthly_fee_cents=fee, trial_days=14), ADMIN
        )
    )


def _proration_invoice_lines(account_id):
    """Return the InvoiceLine rows for the invoice carrying proration lines."""
    invoices = list_account_invoices(account_id)
    # The proration invoice is the one whose lines include a PRORATION_CHARGE.
    for inv in invoices:
        lines_res = api_client.list_invoice_lines(inv["id"], _owner(account_id))
        lines = validate_success(lines_res)
        kinds = {ln["kind"] for ln in lines}
        if "PRORATION_CHARGE" in kinds or "PRORATION_CREDIT" in kinds:
            return inv, lines
    return None, []


class TestProrationCreditVsCharge:
    """Day-granular proration on an upgrade emits two divergent signed lines."""

    def test_proration_credit_and_charge_lines_diverge_on_upgrade(self, api):
        """PRD §3.5: "the old plan's `monthly_fee_cents` multiplied by the remaining days, divided by 30, rounded half-up to whole cents."
        PRD §3.5: "the new plan's `monthly_fee_cents` multiplied by the remaining days, divided by 30, rounded half-up to whole cents."
        PRD §3.5: "These surface as two signed invoice lines on a new draft invoice: a `PRORATION_CREDIT` line whose `amount_cents` is the negative of the credit, and a `PRORATION_CHARGE` line whose `amount_cents` is the positive charge; the net proration is the charge minus the credit."

        Design: Difficulty/dual_variant_calc/proration_credit_vs_charge_diverge_on_upgrade
        """
        basic, account, sub = setup_active_subscription(
            plan_fee_cents=3000, plan_tier="BASIC", email="acme@x.com"
        )
        pro = _make_pro_plan(api)
        set_clock("2026-06-11T00:00:00Z")
        sub_now = get_success_data(api.get_subscription(sub["id"], _owner(account["id"])))

        res = api.change_plan(
            account["id"],
            sub["id"],
            change_plan_payload(pro["id"], sub_now["version"]),
            _owner(account["id"]),
        )
        updated = validate_success(res, 200)
        assert updated["plan_id"] == pro["id"], "plan_id should switch to PRO"

        inv, lines = _proration_invoice_lines(account["id"])
        assert inv is not None, "expected a proration invoice"
        credit = find_line_by_kind(lines, "PRORATION_CREDIT")
        charge = find_line_by_kind(lines, "PRORATION_CHARGE")
        assert credit is not None and charge is not None
        assert credit["amount_cents"] == -2000, f"credit line, got {credit['amount_cents']}"
        assert charge["amount_cents"] == 6000, f"charge line, got {charge['amount_cents']}"

    def test_proration_invoice_subtotal_tax_total(self, api):
        """PRD §3.6: "`subtotal_cents` is the signed sum of every line's `amount_cents`, so proration-credit lines reduce it." PRD §3.6: "`tax_cents` is the taxable base multiplied by the jurisdiction's `tax_rate_bps`, divided by 10000, rounded half-up to whole cents — a single rounding applied to the discounted base, not a per-line rounding." PRD §3.6: "`total_cents` is the taxable base plus the tax."

        Design: Difficulty/dual_variant_calc/proration_credit_vs_charge_diverge_on_upgrade
        """
        basic, account, sub = setup_active_subscription(
            plan_fee_cents=3000, plan_tier="BASIC", email="acme2@x.com"
        )
        pro = _make_pro_plan(api)
        set_clock("2026-06-11T00:00:00Z")
        sub_now = get_success_data(api.get_subscription(sub["id"], _owner(account["id"])))
        validate_success(
            api.change_plan(
                account["id"],
                sub["id"],
                change_plan_payload(pro["id"], sub_now["version"]),
                _owner(account["id"]),
            ),
            200,
        )
        inv, _ = _proration_invoice_lines(account["id"])
        assert inv is not None
        invoice = validate_success(api.get_invoice(inv["id"], _owner(account["id"])), 200)
        assert invoice["subtotal_cents"] == 4000, f"subtotal, got {invoice['subtotal_cents']}"
        assert invoice["tax_cents"] == 350, f"tax, got {invoice['tax_cents']}"
        assert invoice["total_cents"] == 4350, f"total, got {invoice['total_cents']}"
        assert_invoice_total_consistent(invoice)


class TestCommittedMrrVsRecognizedRevenue:
    """The same subscription yields a forward MRR (9000) and a chronological
    recognized figure (4500 at the 15-day mark)."""

    def test_committed_mrr_is_full_forward_figure(self, api):
        """PRD §3.8: "the account's `mrr_cents` is the sum of `mrr_contribution_cents` across the account's subscriptions whose `lifecycle_status` is `ACTIVE`." PRD §3.8:
        "This committed figure projects the next full cycle and deliberately ignores
        partial-period proration and one-time overage."

        Design: Difficulty/dual_variant_calc/committed_mrr_vs_recognized_revenue_diverge
        """
        plan, account, sub = setup_converted_subscription(
            plan_fee_cents=9000, plan_tier="PRO", trial_days=14, email="rev@x.com"
        )
        set_clock("2026-06-16T00:00:00Z")
        acct = validate_success(api.get_account(account["id"], _owner(account["id"])), 200)
        assert acct["mrr_cents"] == 9000, f"committed MRR, got {acct['mrr_cents']}"

    def test_recognized_revenue_is_chronological_half(self, api):
        """PRD §3.8: "The `total_recognizable_cents` is the recurring portion of the paid invoice — only the `SUBSCRIPTION` and `ADDON` line kinds enter it". PRD §3.8: "The `recognized_to_date_cents` is the `total_recognizable_cents` multiplied by those elapsed days, divided by 30, rounded half-up to whole cents, and then clamped to the range from 0 through `total_recognizable_cents`."

        Design: Difficulty/dual_variant_calc/committed_mrr_vs_recognized_revenue_diverge
        """
        plan, account, sub = setup_converted_subscription(
            plan_fee_cents=9000, plan_tier="PRO", trial_days=14, email="rev2@x.com"
        )
        invoices = list_account_invoices(account["id"])
        assert invoices, "convert should have produced a first invoice"
        inv_id = invoices[0]["id"]
        set_clock("2026-06-16T00:00:00Z")
        rs = validate_success(api.get_revenue_schedule(inv_id, _owner(account["id"])), 200)
        entry = rs[0] if isinstance(rs, list) else rs
        assert entry["total_recognizable_cents"] == 9000, (
            f"total_recognizable, got {entry['total_recognizable_cents']}"
        )
        assert entry["recognized_to_date_cents"] == 4500, (
            f"recognized_to_date at 15 days, got {entry['recognized_to_date_cents']}"
        )


class TestChangePlanCascadeToMrr:
    """change-plan -> new plan_id -> recompute contribution -> bubble up MRR."""

    def test_change_plan_sets_plan_and_recomputes_contribution(self, api):
        """PRD §3.5: "Completing the change increments the subscription's `version` by one, finalizes the proration invoice (Section 3.6), sets the subscription's `plan_id` to the new plan, recomputes `mrr_contribution_cents`, and bubbles the result up into the account's `mrr_cents`."

        Design: Difficulty/transitive_cascade/change_plan_cascade_depth2_planid_to_mrr
        """
        basic, account, sub = setup_active_subscription(
            plan_fee_cents=3000, plan_tier="BASIC", email="chg@x.com"
        )
        pro = _make_pro_plan(api)
        set_clock("2026-06-11T00:00:00Z")
        sub_now = get_success_data(api.get_subscription(sub["id"], _owner(account["id"])))
        updated = validate_success(
            api.change_plan(
                account["id"],
                sub["id"],
                change_plan_payload(pro["id"], sub_now["version"]),
                _owner(account["id"]),
            ),
            200,
        )
        assert updated["mrr_contribution_cents"] == 9000, (
            f"contribution after upgrade, got {updated['mrr_contribution_cents']}"
        )

    def test_change_plan_bubbles_up_account_mrr(self, api):
        """PRD §2.9: "A subscription's `mrr_contribution_cents` is its normalized monthly recurring revenue, and an account's `mrr_cents` is the committed recurring revenue summed across that account's subscriptions." PRD §3.5: "recomputes `mrr_contribution_cents`, and bubbles the result up into the account's `mrr_cents`."

        Design: Difficulty/transitive_cascade/change_plan_cascade_depth2_planid_to_mrr
        """
        basic, account, sub = setup_active_subscription(
            plan_fee_cents=3000, plan_tier="BASIC", email="chg2@x.com"
        )
        pro = _make_pro_plan(api)
        set_clock("2026-06-11T00:00:00Z")
        sub_now = get_success_data(api.get_subscription(sub["id"], _owner(account["id"])))
        validate_success(
            api.change_plan(
                account["id"],
                sub["id"],
                change_plan_payload(pro["id"], sub_now["version"]),
                _owner(account["id"]),
            ),
            200,
        )
        acct = validate_success(api.get_account(account["id"], _owner(account["id"])), 200)
        assert acct["mrr_cents"] == 9000, f"account mrr after upgrade, got {acct['mrr_cents']}"


class TestMrrConservation:
    """MRR returns to its pre-action value after a compensating action."""

    def test_account_mrr_returns_to_zero_after_create_then_cancel(self, api):
        """PRD §3.2: "the system sets the billing period, generates and finalizes the first invoice (Section 3.6), attempts the first payment (Section 3.7), recomputes `mrr_contribution_cents`, and bubbles the change up into the account's `mrr_cents`."
        PRD §3.9: "Canceling an `ACTIVE` subscription moves `lifecycle_status` from `ACTIVE` to `CANCELED`, sets `mrr_contribution_cents` to 0, recomputes the account's `mrr_cents` so the subscription drops out — the voluntary-churn event".

        Design: Difficulty/compensating_invariant/mrr_conserved_across_subscription_create_then_cancel
        """
        plan, account, sub = setup_active_subscription(
            plan_fee_cents=9000, plan_tier="PRO", email="inv9@x.com"
        )
        mid = validate_success(api.get_account(account["id"], _owner(account["id"])), 200)
        assert mid["mrr_cents"] == 9000, f"mrr after ACTIVE create, got {mid['mrr_cents']}"

        validate_success(
            api.cancel_subscription(account["id"], sub["id"], _owner(account["id"])), 200
        )
        after = validate_success(api.get_account(account["id"], _owner(account["id"])), 200)
        assert after["mrr_cents"] == 0, f"mrr after cancel, got {after['mrr_cents']}"

    def test_canceled_subscription_contribution_is_zeroed(self, api):
        """PRD §3.9: "Canceling an `ACTIVE` subscription moves `lifecycle_status` from `ACTIVE` to `CANCELED`, sets `mrr_contribution_cents` to 0, recomputes the account's `mrr_cents` so the subscription drops out — the voluntary-churn event".

        Design: Difficulty/compensating_invariant/mrr_conserved_across_subscription_create_then_cancel
        """
        plan, account, sub = setup_active_subscription(
            plan_fee_cents=9000, plan_tier="PRO", email="inv9b@x.com"
        )
        canceled = validate_success(
            api.cancel_subscription(account["id"], sub["id"], _owner(account["id"])), 200
        )
        assert canceled["lifecycle_status"] == "CANCELED", (
            f"lifecycle, got {canceled['lifecycle_status']}"
        )
        assert canceled["mrr_contribution_cents"] == 0, (
            f"contribution after cancel, got {canceled['mrr_contribution_cents']}"
        )

    def test_subscription_contribution_returns_to_base_after_addon_add_then_remove(self, api):
        """PRD §2.9: "the base is the plan's `monthly_fee_cents` plus the sum of the `monthly_fee_cents` of every add-on whose `SubscriptionAddOn` status is `ACTIVE`."
        PRD §3.9: "Attaching an add-on recomputes the subscription's `mrr_contribution_cents` and the account's `mrr_cents`." PRD §3.9: "a removed add-on stops contributing to MRR, so removal likewise recomputes `mrr_contribution_cents` and `mrr_cents`."

        Design: Difficulty/compensating_invariant/contribution_conserved_across_addon_add_then_remove
        """
        plan, account, sub = setup_active_subscription(
            plan_fee_cents=9000, plan_tier="PRO", email="addon@x.com"
        )
        seats = create_addon(code="SEATS", monthly_fee_cents=2000)
        sa = get_success_data(
            api.add_subscription_addon(
                account["id"], sub["id"], add_addon_payload(seats["id"]), _owner(account["id"])
            )
        )
        mid = validate_success(api.get_subscription(sub["id"], _owner(account["id"])), 200)
        assert mid["mrr_contribution_cents"] == 11000, (
            f"contribution after add-on attach, got {mid['mrr_contribution_cents']}"
        )

        validate_success(
            api.remove_subscription_addon(account["id"], sub["id"], sa["id"], _owner(account["id"])),
            200,
        )
        after = validate_success(api.get_subscription(sub["id"], _owner(account["id"])), 200)
        assert after["mrr_contribution_cents"] == 9000, (
            f"contribution after add-on remove, got {after['mrr_contribution_cents']}"
        )

    def test_removed_addon_status_is_removed(self, api):
        """PRD §3.9: "Removing an add-on sets its `status` to `REMOVED` (terminal); a removed add-on stops contributing to MRR, so removal likewise recomputes `mrr_contribution_cents` and `mrr_cents`."

        Design: Difficulty/compensating_invariant/contribution_conserved_across_addon_add_then_remove
        """
        plan, account, sub = setup_active_subscription(
            plan_fee_cents=9000, plan_tier="PRO", email="addonb@x.com"
        )
        seats = create_addon(code="SEATS", monthly_fee_cents=2000)
        sa = get_success_data(
            api.add_subscription_addon(
                account["id"], sub["id"], add_addon_payload(seats["id"]), _owner(account["id"])
            )
        )
        removed = validate_success(
            api.remove_subscription_addon(account["id"], sub["id"], sa["id"], _owner(account["id"])),
            200,
        )
        assert removed["status"] == "REMOVED", f"add-on status, got {removed['status']}"
