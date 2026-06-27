"""Autopay enrollment/drafting, bureau-sweep reporting & idempotency, and the
score-dashboard dual variant."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_bureau_report, assert_bureaus_are_three, assert_score_snapshot,
    make_loan_servicer_headers, make_compliance_officer_headers, make_borrower_headers,
    make_platform_admin_headers,
    setup_funded_loan, post_payment, loan_version,
    create_verified_account, issue_disclosure, acknowledge_disclosure,
    create_pending_loan, fund_loan, create_card, post_deposit, card_version,
    set_clock, run_autopay, run_bureau_sweep,
)


# =========================================================================
# Corner / entities + endpoints: autopay defaults and patch
# =========================================================================

def test_autopay_default_funding_wallet_false(api):
    """PRD §3.11: "an optional `funding_wallet` flag (defaulting to false)."
    PRD §3.11: "A new enrollment has `status` of `ACTIVE`."

    Design: Corner/entities/autopay_default_funding_wallet_false
    """
    acct, _disc, loan = setup_funded_loan(state_code="CA", apr_bps=0, principal_cents=60000)
    data = validate_success(
        api.create_autopay(
            {"loan_id": loan["id"], "day_of_month": 5}, make_borrower_headers(acct["id"])
        ),
        expected_status=201,
    )
    assert data["funding_wallet"] is False
    assert data["status"] == "ACTIVE"


def test_autopay_patch_pause_status(api):
    """PRD §3.11: "The enrollment can later be paused, resumed, or cancelled by patching its `status` among `ACTIVE`, `PAUSED`, and `CANCELLED`."

    Design: Corner/endpoints/autopay_patch_pause_status
    """
    acct, _disc, loan = setup_funded_loan(state_code="CA", apr_bps=0, principal_cents=60000)
    enr = validate_success(
        api.create_autopay(
            {"loan_id": loan["id"], "day_of_month": 5}, make_borrower_headers(acct["id"])
        ),
        expected_status=201,
    )
    data = validate_success(
        api.patch_autopay(enr["id"], {"status": "PAUSED"}, make_borrower_headers(acct["id"]))
    )
    assert data["status"] == "PAUSED"


# =========================================================================
# Corner / validations: wallet-funded autopay insufficiency
# =========================================================================

def test_wallet_funded_autopay_insufficient_wallet(api):
    """PRD §3.11: "When `funding_wallet` is true and the account's `wallet_cents` does not cover the draft amount, the draft is rejected with `ERR_INSUFFICIENT_WALLET` (HTTP 409) — autopay never overdrafts the wallet."

    Design: Corner/validations/wallet_funded_autopay_insufficient_wallet
    """
    acct, _disc, loan = setup_funded_loan(
        state_code="CA", apr_bps=0, principal_cents=60000, funded_at="2026-02-01T00:00:00Z",
    )
    validate_success(
        api.create_autopay(
            {"loan_id": loan["id"], "day_of_month": 5, "funding_wallet": True},
            make_borrower_headers(acct["id"]),
        ),
        expected_status=201,
    )
    set_clock("2026-03-05T00:00:00Z")
    run_autopay()
    pays, meta = validate_paginated(
        api.list_loan_payments(loan["id"], make_borrower_headers(acct["id"]), params={"source": "AUTOPAY"})
    )
    assert meta["total_count"] == 0
    refetched = validate_success(api.get_loan(loan["id"], make_borrower_headers(acct["id"])))
    assert refetched["principal_paid_cents"] == 0


# =========================================================================
# Difficulty / resource_temporal_overlap: autopay half-open window idempotency
# =========================================================================

def test_autopay_half_open_window_no_double_draft(api):
    """PRD §3.11: "The sweep is **idempotent within a billing cycle**: an installment already drafted within the half-open monthly window from the cycle start up to (but not including) one month later is skipped and never double-drafted; when the current installment was already drafted in that window, no payment is created."

    Design: Difficulty/resource_temporal_overlap/autopay_half_open_monthly_window_no_double_draft
    """
    acct, _disc, loan = setup_funded_loan(
        state_code="CA", apr_bps=0, principal_cents=60000, funded_at="2026-02-01T00:00:00Z",
    )
    validate_success(
        api.create_autopay(
            {"loan_id": loan["id"], "day_of_month": 5, "funding_wallet": False},
            make_borrower_headers(acct["id"]),
        ),
        expected_status=201,
    )
    set_clock("2026-03-05T00:00:00Z")
    run_autopay()
    run_autopay()  # second run in the same window must be a no-op
    pays, meta = validate_paginated(
        api.list_loan_payments(loan["id"], make_borrower_headers(acct["id"]), params={"source": "AUTOPAY"})
    )
    assert meta["total_count"] == 1
    refetched = validate_success(api.get_loan(loan["id"], make_borrower_headers(acct["id"])))
    assert refetched["principal_paid_cents"] == 5000


# =========================================================================
# Difficulty / resource_temporal_overlap: bureau calendar bucket idempotency
# =========================================================================

def test_bureau_inclusive_calendar_bucket_one_report(api):
    """PRD §3.12: "At most one report exists per combination of `loan_id`, `tradeline_kind`, and `cycle_label` calendar-month bucket: re-running the sweep in the same YYYY-MM bucket creates no additional rows and skips emission where a row already exists."

    Design: Difficulty/resource_temporal_overlap/bureau_inclusive_calendar_bucket_one_report
    """
    acct, _disc, loan = setup_funded_loan(
        state_code="CA", apr_bps=0, principal_cents=60000, funded_at="2026-02-01T00:00:00Z",
    )
    set_clock("2026-03-20T00:00:00Z")
    run_bureau_sweep()
    run_bureau_sweep()  # same 2026-03 bucket -> no additional LOAN row
    reports, meta = validate_paginated(
        api.list_loan_bureau_reports(loan["id"], make_borrower_headers(acct["id"]),
                                     params={"cycle_label": "2026-03"})
    )
    assert meta["total_count"] == 1


# =========================================================================
# Corner / entities + endpoints: bureau report immutability, score snapshots
# =========================================================================

def test_bureau_report_immutable_no_version_field(api):
    """PRD §2.4: "Two resources are append-only audit records and carry **only** `id` and `created_at` — they have neither `updated_at` nor `version`: the `BureauReport` and the `ScoreSnapshot`."
    PRD §3.12: "a `bureaus` array that is always the three bureaus `EQUIFAX`, `EXPERIAN`, and `TRANSUNION`."

    Design: Corner/entities/bureau_report_immutable_no_version_field
    """
    acct, _disc, loan = setup_funded_loan(
        state_code="CA", apr_bps=0, principal_cents=60000, funded_at="2026-02-01T00:00:00Z",
    )
    set_clock("2026-03-20T00:00:00Z")
    run_bureau_sweep()
    reports, _meta = validate_paginated(
        api.list_loan_bureau_reports(loan["id"], make_borrower_headers(acct["id"]),
                                     params={"cycle_label": "2026-03"})
    )
    assert len(reports) >= 1
    for r in reports:
        assert_bureau_report(r)
        assert r["tradeline_kind"] == "LOAN"
        assert_bureaus_are_three(r)


def test_score_snapshots_history_list(api):
    """PRD §3.12: "the system persists one `ScoreSnapshot` per account per cycle, recording its `account_id`, the `cycle_label`, the model `simulated_score`, and the `score_delta` from the prior snapshot."
    PRD §3.12: "The `score_delta` is `simulated_score` minus the prior snapshot's `simulated_score`, or 0 if there is no prior snapshot."

    Design: Corner/endpoints/score_snapshots_history_list
    """
    acct, _disc, loan = setup_funded_loan(
        state_code="CA", apr_bps=0, principal_cents=60000, funded_at="2026-02-01T00:00:00Z",
    )
    set_clock("2026-03-20T00:00:00Z")
    run_bureau_sweep()
    snaps, meta = validate_paginated(
        api.list_score_snapshots(acct["id"], make_borrower_headers(acct["id"]))
    )
    assert meta["total_count"] == 1
    assert_score_snapshot(snaps[0])
    assert snaps[0]["score_delta"] == 0
    assert snaps[0]["cycle_label"] == "2026-03"


# =========================================================================
# Difficulty / dual_variant_calc: score optimistic vs realized
# =========================================================================

def test_score_optimistic_vs_realized(api):
    """PRD §3.12: "A read of an account's score returns the **realized** score by default — counting only the marks actually present in the persisted `BureauReport` rows, making no assumption about the in-flight cycle — and persists nothing on read."
    PRD §3.12: "When the read supplies a `projection` of `optimistic`, the **optimistic projection** variant instead assumes the in-flight (current) cycle is reported on-time: it adds exactly one more on-time mark and zero late marks for the in-flight cycle before scoring"
    PRD §3.12: "Start from a base of 580. Add a payment-history component: 6 points for each on-time installment reported, minus 40 points for each late mark reported."

    Design: Difficulty/dual_variant_calc/score_optimistic_vs_realized
    """
    set_clock("2026-01-15T00:00:00Z")
    acct = create_verified_account(state_code="CA")
    ldisc = issue_disclosure(acct["id"], product_kind="LOAN", apr_bps=0)
    cdisc = issue_disclosure(acct["id"], product_kind="SECURED_CARD", apr_bps=0)
    acknowledge_disclosure(ldisc["id"], acct["id"])
    acknowledge_disclosure(cdisc["id"], acct["id"])

    loan = create_pending_loan(acct["id"], ldisc["id"], principal_cents=60000, term_months=12)
    loan = fund_loan(loan["id"])

    # Secured card: deposit 50000, activate (balance 0 -> utilization 0 -> 120 util pts).
    card = create_card(acct["id"], cdisc["id"])
    post_deposit(card["id"], acct["id"], 50000, card["version"])
    validate_success(api.activate_card(card["id"], {}, make_borrower_headers(acct["id"])))

    # Three monthly on-time cycles (pay each, then sweep) at 01-15, 02-15, 03-15.
    post_payment(loan["id"], acct["id"], 5000, loan_version(loan["id"], acct["id"]))
    run_bureau_sweep()
    set_clock("2026-02-15T00:00:00Z")
    post_payment(loan["id"], acct["id"], 5000, loan_version(loan["id"], acct["id"]))
    run_bureau_sweep()
    set_clock("2026-03-15T00:00:00Z")
    post_payment(loan["id"], acct["id"], 5000, loan_version(loan["id"], acct["id"]))
    run_bureau_sweep()

    optimistic = validate_success(
        api.get_score(acct["id"], make_borrower_headers(acct["id"]), params={"projection": "optimistic"})
    )
    realized = validate_success(api.get_score(acct["id"], make_borrower_headers(acct["id"])))
    # realized: base 580 + payment_history 18 (3 on-time * 6) + util 120 + age 4 (2 months * 2).
    assert realized["simulated_score"] == 722
    # optimistic adds one on-time mark: payment_history 24.
    assert optimistic["simulated_score"] == 728
    assert optimistic["simulated_score"] - realized["simulated_score"] == 6
