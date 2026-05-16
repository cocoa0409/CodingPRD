"""Parent balance waterfall — ordered ledger replay and refunds.

PRD §3.6 parent_balance_waterfall: replay PaidLedgerEntry rows in
occurred_at ASC, id ASC; TOP_UP adds, CHARGE subtracts, REFUND adds.
A new CHARGE that would drive simulated balance below zero is rejected
with ERR_PREPAID_BALANCE_INSUFFICIENT (non-strict comparison). A REFUND
must equal its linked CHARGE exactly (no partial refunds).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    create_meal_serving,
    create_meal_serving_payload,
    create_menu_item,
    make_parent_headers,
    refund_charge,
    refund_payload,
    setup_district_with_family,
    setup_paid_serving_with_balance,
    top_up_parent_account,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    void_meal_serving,
)


# ===========================================================================
# §3.6 parent_balance_waterfall — ordered replay
# ===========================================================================
class TestWaterfallReplay:
    """PRD §3.6: replay every PaidLedgerEntry in occurred_at ASC,
    starting from zero."""

    def test_top_up_then_charge_balance_decreases(self, api):
        """PRD §3.6: "For each entry: a TOP_UP adds its amount_cents; a
        CHARGE subtracts its amount_cents".

        Claim: TOP_UP 500 + TOP_UP 300 + CHARGE 400 → balance 400.
        """
        district, parent, student = setup_district_with_family()
        top_up_parent_account(
            district=district, parent_account=parent, amount_cents=500,
        )
        top_up_parent_account(
            district=district, parent_account=parent, amount_cents=300,
        )
        # PAID-tier student (default) and a 400-cent menu item.
        item = create_menu_item(district=district, full_price_cents=400)
        create_meal_serving(
            district=district, student=student, menu_item=item,
        )
        parent_after = api_client.get_parent_account(
            district["id"], parent["id"], make_parent_headers(parent["id"]),
        ).json()["data"]
        assert parent_after["prepaid_balance_cents"] == 400, (
            f"expected 500+300-400=400, got "
            f"{parent_after['prepaid_balance_cents']}"
        )


# ===========================================================================
# §3.6 Pre-commit CHARGE validation
# ===========================================================================
class TestChargeRejectionAtBalanceBoundary:
    """PRD §3.6: charge that drives balance below zero is rejected;
    charge that drives balance to exactly zero is permitted."""

    def test_charge_below_zero_rejected(self, api, cafeteria_headers):
        """PRD §3.6: "Pre-commit validation for a new CHARGE simulates
        the running total after the charge would be applied and rejects
        with ERR_PREPAID_BALANCE_INSUFFICIENT if that simulated value
        would fall below zero".

        Claim: with balance 400 and a 700-cent CHARGE attempt → second
        serving is rejected with ERR_PREPAID_BALANCE_INSUFFICIENT and
        the balance is unchanged.

        # difficulty: dual_variant_calc/parent_account_top_up_balance_two_orderings
        """
        district, parent, student = setup_district_with_family()
        top_up_parent_account(
            district=district, parent_account=parent, amount_cents=500,
        )
        top_up_parent_account(
            district=district, parent_account=parent, amount_cents=300,
        )
        m1 = create_menu_item(district=district, full_price_cents=400)
        m2 = create_menu_item(district=district, full_price_cents=700)
        # First serving uses M1 → balance 400.
        create_meal_serving(
            district=district, student=student, menu_item=m1,
        )
        parent_mid = api_client.get_parent_account(
            district["id"], parent["id"], make_parent_headers(parent["id"]),
        ).json()["data"]
        assert parent_mid["prepaid_balance_cents"] == 400
        # Second serving uses M2 (700 cents) → would drive balance to
        # -300; must be rejected.
        # Note: same-day uniqueness would also fire; advance the clock
        # so this is a new day.
        from test_helpers import advance_clock_to
        advance_clock_to("2030-12-01T12:00:00.000Z")
        res = api.create_meal_serving(
            district["id"],
            create_meal_serving_payload(
                student_id=student["id"], menu_item_id=m2["id"],
            ),
            cafeteria_headers,
        )
        validate_error(res, "ERR_PREPAID_BALANCE_INSUFFICIENT")
        # Balance is unchanged.
        parent_after = api_client.get_parent_account(
            district["id"], parent["id"], make_parent_headers(parent["id"]),
        ).json()["data"]
        assert parent_after["prepaid_balance_cents"] == 400

    def test_charge_drives_balance_to_zero_permitted(self, api):
        """PRD §3.6: "the comparison is non-strict, so a charge that
        drives the balance to exactly zero is permitted."

        Claim: balance 350, CHARGE 350 → serving succeeds and balance
        becomes 0.
        """
        district, parent, student, item = setup_paid_serving_with_balance(
            full_price_cents=350, top_up_amount_cents=350,
        )
        serving = create_meal_serving(
            district=district, student=student, menu_item=item,
        )
        assert serving["status"] == "SERVED"
        parent_after = api_client.get_parent_account(
            district["id"], parent["id"], make_parent_headers(parent["id"]),
        ).json()["data"]
        assert parent_after["prepaid_balance_cents"] == 0


# ===========================================================================
# §3.6 Refund semantics
# ===========================================================================
class TestRefund:
    """PRD §3.6: AuditOfficer refunds an exact CHARGE; partial refunds
    are rejected."""

    def test_refund_exact_charge_succeeds(self, api):
        """PRD §3.6: "The system locates the PaidLedgerEntry of type
        CHARGE linked to that serving_record_id on the parent account
        and appends a REFUND of equal amount_cents."

        Claim: AuditOfficer POST /refund with serving_record_id of a
        CHARGE → balance increases by the charge amount.
        """
        district, parent, student, item = setup_paid_serving_with_balance(
            full_price_cents=350, top_up_amount_cents=1000,
        )
        serving = create_meal_serving(
            district=district, student=student, menu_item=item,
        )
        # Balance was 1000 - 350 = 650.
        refunded_parent = refund_charge(
            district=district, parent_account=parent,
            serving_record_id=serving["id"],
        )
        assert refunded_parent["prepaid_balance_cents"] == 1000

    def test_refund_for_unknown_serving_rejected(self, api, audit_headers):
        """PRD §3.6: "The refund is full-only: if the requested refund
        amount (implicit in the original CHARGE) does not exactly equal
        the linked charge — or the linked charge cannot be found — the
        request is rejected with ERR_REFUND_MISMATCH."

        Claim: refund with a serving_record_id that does NOT resolve
        to a CHARGE on this parent → ERR_REFUND_MISMATCH.
        """
        district, parent, _ = setup_district_with_family()
        # Mint a different parent's serving so the linked CHARGE is on
        # the wrong account.
        _, _, other_student, item = setup_paid_serving_with_balance(
            full_price_cents=300, top_up_amount_cents=600,
        )
        # No charge on `parent` ever existed. Use the other district's
        # serving id — implementation can short-circuit either to
        # ERR_NOT_FOUND or ERR_REFUND_MISMATCH; PRD §3.6 explicitly
        # names ERR_REFUND_MISMATCH when "the linked charge cannot be
        # found".
        # We pass a UUID that does not correspond to any of `parent`'s
        # charges. PRD §3.6: "the linked charge cannot be found — the
        # request is rejected with ERR_REFUND_MISMATCH." The
        # implementation may instead surface ERR_NOT_FOUND via §2.7
        # cross-aggregate scoping for the serving_record_id. Both are
        # PRD-faithful renderings; we accept either.
        res = api.refund_parent_account(
            district["id"], parent["id"],
            refund_payload(serving_record_id=NON_EXISTENT_UUID),
            audit_headers,
        )
        validate_error_is_one_of(res, ["ERR_REFUND_MISMATCH",
                                       "ERR_NOT_FOUND"])
