"""Cross-entity cascades and ledger invariants.

Covers PRD §2.8 (cascade chains), §2.9 (ledger invariant), §3.3 (approve
cascade: card + ledger + balance recompute).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
    ERR_INVALID_STATE,
    TEST_USERS, make_household_head_headers, make_merchant_headers,
    assert_card_balance_matches_ledger,
    create_household, add_member,
    create_draft_application, walk_to_interview_done, approve_application,
    setup_approved_household_with_active_card,
    setup_full_purchase_scene,
    dob_for_age,
    create_transaction_payload,
)


CASEWORKER = TEST_USERS["caseworker_headers"]


class TestApplicationApproveCascade:
    def test_approve_creates_card_and_seeds_ledger(self, api):
        """PRD §3.3: "if no `EbtCard` currently exists in `ISSUED`, `ACTIVE`,
        or `SUSPENDED`, a new one is auto-issued in `ISSUED` and a
        `REGULAR_ALLOTMENT` `BenefitLedger` entry is posted to it for the
        current `benefit_month`."

        Claim (cascade depth 3): approve -> EbtCard ISSUED + ledger entry
        REGULAR_ALLOTMENT + balance recomputed to monthly_allotment_cents.

        Approach: pre-issue a card BEFORE approve so we can capture the card
        id. PRD §3.3 says auto-issue only when no card exists; with a card
        already ISSUED, approval reuses it and seeds REGULAR_ALLOTMENT.
        """
        # difficulty: transitive_cascade/application_approve_to_card_to_ledger_to_balance
        hh = create_household()
        add_member(hh["id"], full_name="A", date_of_birth=dob_for_age(30),
                   earned_income_cents=0, unearned_income_cents=0)
        app = create_draft_application(hh["id"])
        walk_to_interview_done(hh["id"], app["id"])
        # Pre-issue a card so we know its id
        card_issued = validate_success(api.create_card(hh["id"], CASEWORKER), expected_status=201)
        approve_application(hh["id"], app["id"])
        # Re-read household and card
        hh_after = validate_success(api.get_household(hh["id"], CASEWORKER))
        card_after = validate_success(api.get_card(hh["id"], card_issued["id"], CASEWORKER))
        assert hh_after["certification_status"] == "APPROVED"
        # The card balance must equal monthly_allotment_cents
        assert card_after["balance_cents"] == hh_after["monthly_allotment_cents"], (
            f"Card balance {card_after['balance_cents']} != "
            f"monthly_allotment {hh_after['monthly_allotment_cents']}"
        )
        # Verify ledger has a REGULAR_ALLOTMENT entry
        ledger_data, _ = validate_paginated(
            api.get_card_ledger(hh["id"], card_issued["id"], CASEWORKER, params={"limit": 100})
        )
        regular = [e for e in ledger_data if e["entry_type"] == "REGULAR_ALLOTMENT"]
        assert len(regular) >= 1, "Expected at least one REGULAR_ALLOTMENT ledger entry"


class TestLedgerInvariant:
    def test_ledger_sum_equals_card_balance_after_purchase(self, api):
        """PRD §2.9: "`EbtCard.balance_cents` is **derived**, never stored
        independently of the ledger. At all times, `balance_cents` for a card
        equals the sum of `amount_cents` over every `BenefitLedger` entry
        whose `card_id` points to that card."

        Claim: after one purchase, card.balance_cents == sum(ledger.amount_cents).
        """
        ctx = setup_full_purchase_scene(size=1, age=30)
        m_headers = make_merchant_headers(ctx["merchant"]["id"])
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=ctx["merchant"]["id"],
            line_items=[{"item_category": "STAPLE", "unit_price_cents": 500, "quantity": 1}],
        )
        validate_success(api.create_transaction(payload, m_headers), expected_status=201)
        # Read card + ledger
        card = validate_success(api.get_card(ctx["household"]["id"], ctx["card"]["id"], CASEWORKER))
        ledger, _ = validate_paginated(
            api.get_card_ledger(ctx["household"]["id"], ctx["card"]["id"], CASEWORKER,
                                params={"limit": 100})
        )
        assert_card_balance_matches_ledger(card, ledger)

    def test_purchase_and_refund_pair_is_zero_sum(self, api):
        """PRD §2.9: "Credit entry types (`REGULAR_ALLOTMENT`,
        `EMERGENCY_ALLOTMENT`, `REFUND`, positive `ADJUSTMENT`) are stored
        with positive `amount_cents`; debit entries (`PURCHASE`, negative
        `ADJUSTMENT`) are stored with negative `amount_cents`."

        Claim: after purchase + reverse, the linked PURCHASE+REFUND entries
        sum to zero, and overall balance is unchanged.
        """
        # difficulty: compensating_invariant/purchase_then_reverse_leaves_card_balance_unchanged
        ctx = setup_full_purchase_scene(size=1, age=30)
        m_headers = make_merchant_headers(ctx["merchant"]["id"])
        pre = validate_success(api.get_card(ctx["household"]["id"], ctx["card"]["id"], CASEWORKER))
        balance_before = pre["balance_cents"]
        payload = create_transaction_payload(
            card_id=ctx["card"]["id"], merchant_id=ctx["merchant"]["id"],
            line_items=[{"item_category": "STAPLE", "unit_price_cents": 1500, "quantity": 1}],
        )
        tx = validate_success(api.create_transaction(payload, m_headers), expected_status=201)
        validate_success(api.reverse_transaction(tx["id"], m_headers))
        post = validate_success(api.get_card(ctx["household"]["id"], ctx["card"]["id"], CASEWORKER))
        assert post["balance_cents"] == balance_before, (
            f"Net change must be zero; before={balance_before}, after={post['balance_cents']}"
        )
        # Verify both entries exist on the ledger with opposite signs
        ledger, _ = validate_paginated(
            api.get_card_ledger(ctx["household"]["id"], ctx["card"]["id"], CASEWORKER,
                                params={"limit": 100})
        )
        purchases = [e for e in ledger if e["entry_type"] == "PURCHASE"]
        refunds = [e for e in ledger if e["entry_type"] == "REFUND"]
        assert len(purchases) >= 1
        assert len(refunds) >= 1
        # Find the matching pair by reference_id == tx id
        matched_p = [e for e in purchases if e.get("reference_id") == tx["id"]]
        matched_r = [e for e in refunds if e.get("reference_id") == tx["id"]]
        assert len(matched_p) == 1
        assert len(matched_r) == 1
        assert matched_p[0]["amount_cents"] == -1500
        assert matched_r[0]["amount_cents"] == 1500


class TestApplicationCloseCascade:
    def test_close_application_closes_active_card(self, api):
        """PRD §3.3: "Closing an approved application — either manually by a
        caseworker or automatically by the sweep at expiry — transitions it
        from `APPROVED` to `CLOSED`, flips `Household.certification_status`
        to `CLOSED`, and cascades any `ACTIVE` `EbtCard` into `CLOSED` (with
        its remaining balance forfeited to zero as described in §2.8)."

        Claim: closing an APPROVED application cascades the ACTIVE card into
        CLOSED with balance forfeited to zero.
        """
        ctx = setup_approved_household_with_active_card(size=1, age=30)
        validate_success(api.close_application(
            ctx["household"]["id"], ctx["application"]["id"], CASEWORKER
        ))
        card_after = validate_success(api.get_card(
            ctx["household"]["id"], ctx["card"]["id"], CASEWORKER
        ))
        assert card_after["status"] == "CLOSED"
        assert card_after["balance_cents"] == 0
