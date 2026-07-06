"""Payments driving invoices to PAID, fiscal/lock error gates, ownership, and archive.

Difficulty queue A: invoice PAID terminal branch. Corner queue B: credit-limit gate;
suspended-account gate; over-payment; paid-invoice void lock; cross-account ownership;
archive-search pagination.
"""
from prd_bench_local_runner.testing import (
    validate_success, validate_error, validate_paginated,
)
from test_helpers import (
    ApiErrorId,
    make_advertiser_headers, compliance_officer_headers,
    create_draft_notice, submit_notice, get_notice,
    provision_reference, setup_affidavit_issued, setup_invoice_paid,
    payment_payload,
)


# ===========================================================================
# Difficulty rule 3 — invoice PAID terminal branch
# ===========================================================================

class TestInvoicePaidTerminal:
    def test_full_payment_moves_invoice_to_paid(self, api):
        """PRD §3.7: "when the accumulated `amount_paid_cents` reaches or exceeds the
        invoice's `total_cents`, the invoice advances from `ISSUED` to `PAID`."

        Design: Difficulty/non_linear_state_machine/invoice_branching_paid_terminal
        """
        ref = setup_affidavit_issued(api, line_count_actual=2)  # invoice ISSUED total 4100
        headers = make_advertiser_headers(ref["account"]["id"])
        validate_success(
            api.create_payment(payment_payload(ref["invoice"]["id"], 4100), headers), 201)
        inv = validate_success(api.get_invoice(ref["invoice"]["id"], headers), 200)
        assert inv["status"] == "PAID", inv["status"]

    def test_full_payment_records_amount_and_clears_outstanding(self, api):
        """PRD §3.7: "Every payment recomputes the account's `outstanding_balance_cents`,
        lowering it by the payment amount."

        Design: Difficulty/non_linear_state_machine/invoice_branching_paid_terminal
        """
        ref = setup_affidavit_issued(api, line_count_actual=2)
        headers = make_advertiser_headers(ref["account"]["id"])
        api.create_payment(payment_payload(ref["invoice"]["id"], 4100), headers)
        inv = validate_success(api.get_invoice(ref["invoice"]["id"], headers), 200)
        assert inv["amount_paid_cents"] == 4100, inv["amount_paid_cents"]
        acct = validate_success(api.get_account(ref["account"]["id"], headers), 200)
        assert acct["outstanding_balance_cents"] == 0, acct["outstanding_balance_cents"]


# ===========================================================================
# Corner queue B — fiscal / lock / ownership gates
# ===========================================================================

def test_submit_credit_limit_exceeded(api):
    """PRD §3.2: "the account's current `committed_balance_cents` plus the notice's
    `estimated_cost_cents` must be at most the account's `credit_limit_cents`, and if
    that sum would exceed the limit the submit is rejected with
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

    Design: Corner/errors/submit_credit_limit_exceeded
    """
    ref = provision_reference(api, account_overrides={"name": "Thin Wallet",
                                                      "account_type": "INDIVIDUAL",
                                                      "credit_limit_cents": 1000})
    notice = create_draft_notice(api, ref["account"], ref["newspaper"])  # estimated 1600
    resp = api.submit_notice(notice["id"], make_advertiser_headers(ref["account"]["id"]))
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, expected_status=402)
    after = get_notice(api, notice["id"], ref["account"])
    assert after["status"] == "DRAFT", after["status"]


def test_submit_account_suspended(api):
    """PRD §3.2: "The owning account must be `ACTIVE`; a submit attempted against a
    `SUSPENDED` account is rejected with `ERR_ACCOUNT_SUSPENDED` (HTTP 409)."

    Design: Corner/errors/submit_account_suspended
    """
    ref = provision_reference(api, account_overrides={"name": "Frozen Firm",
                                                      "status": "SUSPENDED"})
    notice = create_draft_notice(api, ref["account"], ref["newspaper"])
    resp = api.submit_notice(notice["id"], make_advertiser_headers(ref["account"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED, expected_status=409)


def test_payment_exceeds_balance_rejected(api):
    """PRD §3.7: "The amount must be strictly greater than 0 and at most the invoice's
    remaining balance — its `total_cents` minus the already-paid `amount_paid_cents`; an
    amount that is 0 or negative, or that exceeds the remaining balance, is rejected with
    `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422)."

    Design: Corner/errors/payment_exceeds_balance_rejected
    """
    ref = setup_affidavit_issued(api, line_count_actual=2)  # invoice ISSUED total 4100
    headers = make_advertiser_headers(ref["account"]["id"])
    resp = api.create_payment(payment_payload(ref["invoice"]["id"], 5000), headers)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE, expected_status=422)
    inv = validate_success(api.get_invoice(ref["invoice"]["id"], headers), 200)
    assert inv["status"] == "ISSUED", inv["status"]


def test_void_affidavit_blocked_when_invoice_paid(api):
    """PRD §3.7: "Voiding is refused if the notice's invoice has already been paid: when
    that invoice is in `PAID` status the void is rejected with `ERR_INVOICE_PAID_LOCK`
    (HTTP 409), because a settled bill cannot be unwound."

    Design: Corner/errors/void_affidavit_blocked_when_invoice_paid
    """
    ref = setup_invoice_paid(api, line_count_actual=2)  # invoice PAID (4100)
    resp = api.void_affidavit(ref["affidavit"]["id"], {"reason": "too late"},
                             compliance_officer_headers())
    validate_error(resp, ApiErrorId.ERR_INVOICE_PAID_LOCK, expected_status=409)
    aff = validate_success(
        api.get_affidavit(ref["affidavit"]["id"], compliance_officer_headers()), 200)
    assert aff["status"] == "ISSUED", aff["status"]


def test_advertiser_cannot_submit_other_accounts_notice(api):
    """PRD §2.1: "an advertiser may act only on notices, proofs, insertions, invoices,
    and payments whose `account_id` chain resolves to its own account."

    Design: Corner/rbac/advertiser_cannot_submit_other_accounts_notice
    """
    ref = provision_reference(api, account_overrides={"name": "Firm A"})
    from test_helpers import create_account
    account_b = create_account(api, name="Firm B")
    notice = create_draft_notice(api, ref["account"], ref["newspaper"])  # owned by A
    resp = api.submit_notice(notice["id"], make_advertiser_headers(account_b["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
    after = get_notice(api, notice["id"], ref["account"])
    assert after["status"] == "DRAFT", after["status"]


def test_notices_archive_search_pagination(api):
    """PRD §2.3: "Every list response echoes `limit` and `offset` in `meta` alongside
    `total_count` (the total number of matching records ignoring pagination) and
    `has_more` (true when unread records remain beyond the current window)."

    Design: Corner/endpoints/notices_archive_search_pagination
    """
    ref = provision_reference(api)
    create_draft_notice(api, ref["account"], ref["newspaper"], title="Estate One")
    create_draft_notice(api, ref["account"], ref["newspaper"], title="Estate Two")
    headers = make_advertiser_headers(ref["account"]["id"])
    data, meta = validate_paginated(
        api.list_notices(headers, params={"account_id": ref["account"]["id"],
                                          "limit": 1, "offset": 0}))
    assert len(data) == 1, f"expected 1 row with limit=1, got {len(data)}"
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is True, meta["has_more"]
