"""Credit conservation: referral earn/revoke compensating pair (PRD 3.8, 3.9)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_referral_qualify_revoke_credit_conservation(api):
    """PRD 3.8: "Compensating pairs leave the balance unchanged: an `EARN_REFERRAL` of some amount followed by a `REVOKE_REFERRAL` of its negation restores the prior balance, and a `REDEEM_INVOICE` followed by a `RESTORE_VOID_INVOICE` of the same magnitude does the same."
    PRD 3.9: "Revoking a `QUALIFIED` referral posts a compensating `REVOKE_REFERRAL` ledger entry of the negated `qualified_credit_cents` to the referrer; revoking a `PENDING` one carries no compensation."

    Design: Difficulty/compensating_invariant/referral_qualify_revoke_credit_conservation
    """
    result = th.setup_qualified_referral(
        box_qty=3, referrer_email="inv-r@x.com", referee_email="inv-e@x.com"
    )
    referrer_id = result["referrer"]["id"]
    referral_id = result["referral"]["id"]
    assert th.get_customer_balance(referrer_id) == 480, (
        "qualification posts EARN_REFERRAL of qualified_credit_cents to the referrer"
    )

    revoked = th.validate_success(api.revoke_referral(referral_id, ADMIN))
    assert revoked["status"] == "REVOKED"

    entries = th.list_ledger(customer_id=referrer_id)
    assert len(entries) == 2, "exactly the earn/revoke pair may exist"
    by_type = {e["entry_type"]: e for e in entries}
    assert by_type["EARN_REFERRAL"]["amount_cents"] == 480
    assert by_type["EARN_REFERRAL"]["reference_id"] == referral_id
    assert by_type["REVOKE_REFERRAL"]["amount_cents"] == -480
    assert by_type["REVOKE_REFERRAL"]["reference_id"] == referral_id

    # Invariant: the forward + compensating pair leaves the balance unchanged.
    assert th.get_customer_balance(referrer_id) == 0


def test_referral_credit_posts_to_referrer_not_referee(api):
    """PRD 3.9: "The referral records the triggering invoice in `referee_first_invoice_id` and posts an `EARN_REFERRAL` ledger entry of `qualified_credit_cents` to the referrer — only the qualified amount is ever posted, never the provisional figure."
    PRD 3.8: "A customer's `credit_balance_cents` is always the sum of `amount_cents` across all of that customer's entries, with no status filtering — the log is append-only."

    Design: Difficulty/compensating_invariant/referral_qualify_revoke_credit_conservation
    """
    result = th.setup_qualified_referral(
        box_qty=3, referrer_email="side-r@x.com", referee_email="side-e@x.com"
    )
    referrer_id = result["referrer"]["id"]
    referee_id = result["referee"]["id"]

    referrer_entries = th.list_ledger(customer_id=referrer_id)
    assert [e["entry_type"] for e in referrer_entries] == ["EARN_REFERRAL"]
    assert referrer_entries[0]["amount_cents"] == 480
    assert th.get_customer_balance(referrer_id) == 480

    # The referee earned nothing: no entries, zero balance.
    assert th.list_ledger(customer_id=referee_id) == []
    assert th.get_customer_balance(referee_id) == 0
