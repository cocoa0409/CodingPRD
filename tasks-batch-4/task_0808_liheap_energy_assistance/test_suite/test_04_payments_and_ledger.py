"""Payment remittance, the bill-credit waterfall, and account-ledger conservation
(PRD §2.8, §3.7)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_account_conservation,
    setup_approved_application, create_pledge_on, create_initiated_payment, remit,
    make_vendoragent_headers, TEST_USERS,
)

CW = TEST_USERS["caseworker_headers"]


def _arrearage_pledge_payment(api):
    """APPROVED application on a HEATING pool, a disconnected account with
    current 30000 + arrearage 20000, a 20000 ARREARAGE pledge, and a 20000
    INITIATED payment. Returns (ctx, pledge, payment)."""
    ctx = setup_approved_application(api, account_overrides={
        "current_balance_cents": 30000, "arrearage_cents": 20000, "is_disconnected": True})
    pledge = validate_success(create_pledge_on(
        api, ctx, pledge_type="ARREARAGE", pledged_amount_cents=20000), expected_status=201)
    payment = create_initiated_payment(api, pledge["id"], 20000)
    return ctx, pledge, payment


class TestRemitBillCreditReconnectionChain:
    def test_remit_creates_bill_credit_with_arrearage_first_waterfall(self, api):
        """PRD §3.7: "That credit is applied to the account through an arrearage-first
        waterfall: the `applied_to_arrearage_cents` is the lesser of the credit amount
        and the account's current `arrearage_cents`; the remainder of the credit after
        arrears is the `applied_to_current_cents`, computed as the lesser of that
        remainder and the account's `current_balance_cents`."

        Design: Difficulty/transitive_cascade/payment_remit_billcredit_reconnection_chain
        """
        ctx, pledge, payment = _arrearage_pledge_payment(api)
        remit(api, payment["id"], ctx["vendor_id"])
        credits, _meta = validate_paginated(
            api.list_bill_credits(CW, params={"payment_id": payment["id"]}))
        assert len(credits) == 1
        credit = credits[0]
        assert credit["status"] == "APPLIED"
        assert credit["applied_to_arrearage_cents"] == 20000
        assert credit["applied_to_current_cents"] == 0

    def test_remit_clears_arrearage_and_flips_reconnection_eligible(self, api):
        """PRD §3.7: "If, after this application, the account's `arrearage_cents` has
        reached 0 and the account is disconnected (`is_disconnected` true), the
        account's `reconnection_eligible` is set to true — the household has cleared its
        arrears and may be reconnected."

        Design: Difficulty/transitive_cascade/payment_remit_billcredit_reconnection_chain
        """
        ctx, pledge, payment = _arrearage_pledge_payment(api)
        remit(api, payment["id"], ctx["vendor_id"])
        account = validate_success(api.get_utility_account(ctx["account_id"], CW))
        assert account["arrearage_cents"] == 0
        assert account["current_balance_cents"] == 30000
        assert account["lifetime_credited_cents"] == 20000
        assert account["reconnection_eligible"] is True
        paid = validate_success(api.get_pledge(pledge["id"], CW))
        assert paid["status"] == "PAID"


class TestAccountLedgerConservationOnReturn:
    def test_return_restores_account_buckets(self, api):
        """PRD §3.7: "Returning moves the payment from `REMITTED` to `RETURNED` and
        fully compensates the ledger: the associated bill credit moves from `APPLIED` to
        `REVERSED`, the account's `arrearage_cents` is increased back by
        `applied_to_arrearage_cents`, its `current_balance_cents` is increased back by
        `applied_to_current_cents`, and its `lifetime_credited_cents` is decreased by
        `credit_amount_cents`, restoring the account conservation invariant."

        Design: Difficulty/compensating_invariant/account_ledger_conservation_payment_return
        """
        ctx, pledge, payment = _arrearage_pledge_payment(api)
        remit(api, payment["id"], ctx["vendor_id"])
        api.return_payment(payment["id"], make_vendoragent_headers(ctx["vendor_id"]))
        account = validate_success(api.get_utility_account(ctx["account_id"], CW))
        assert account["arrearage_cents"] == 20000
        assert account["current_balance_cents"] == 30000
        assert account["lifetime_credited_cents"] == 0
        assert_account_conservation(account)

    def test_return_reverses_bill_credit_and_clears_reconnection(self, api):
        """PRD §3.7: "If after the reversal the account's `arrearage_cents` is again
        greater than 0, its `reconnection_eligible` is set back to false."

        Design: Difficulty/compensating_invariant/account_ledger_conservation_payment_return
        """
        ctx, pledge, payment = _arrearage_pledge_payment(api)
        remit(api, payment["id"], ctx["vendor_id"])
        returned = validate_success(
            api.return_payment(payment["id"], make_vendoragent_headers(ctx["vendor_id"])))
        assert returned["status"] == "RETURNED"
        credits, _meta = validate_paginated(
            api.list_bill_credits(CW, params={"payment_id": payment["id"]}))
        assert credits[0]["status"] == "REVERSED"
        account = validate_success(api.get_utility_account(ctx["account_id"], CW))
        assert account["reconnection_eligible"] is False


def test_return_non_remitted_payment_rejected(api):
    """PRD §3.7: "A vendor agent may return a remitted payment, which requires the
    payment be in `REMITTED` status, or the return is rejected with
    `ERR_PAYMENT_NOT_REMITTED`."

    Design: Corner/validations/return_non_remitted_payment_returns_error
    """
    ctx = setup_approved_application(api)
    pledge = validate_success(create_pledge_on(api, ctx, pledged_amount_cents=30000), expected_status=201)
    payment = create_initiated_payment(api, pledge["id"], 30000)
    resp = api.return_payment(payment["id"], make_vendoragent_headers(ctx["vendor_id"]))
    validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_REMITTED.value)
    after = validate_success(api.get_payment(payment["id"], CW))
    assert after["status"] == "INITIATED"
