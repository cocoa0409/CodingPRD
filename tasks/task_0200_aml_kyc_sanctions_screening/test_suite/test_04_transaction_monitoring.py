"""Transaction monitoring: CTR boundary, day-bucket windowing, account gating."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_customer_payload, create_legal_entity_payload, create_account_payload,
    create_transaction_payload, create_risk_assessment_payload,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx

CO = TEST_USERS["compliance_officer_headers"]
SF = TEST_USERS["system_feed_headers"]


# ==========================================================================
# Queue A — boundary_precision_check (CTR strict > boundary)
# ==========================================================================
def test_ctr_strict_gt_boundary(api):
    """PRD §3.6: "for a `CASH_IN`, take the same-UTC-day cash-in window total
    after this amount is added; if that post-addition total is strictly greater
    than 1,000,000 cents (that is, strictly above 10,000 dollars), the rule
    `CTR_THRESHOLD` fires — a window total of exactly 1,000,000 cents does not
    fire, because the boundary is strict."
    PRD §3.6: "the structuring rule: a `CASH_IN` whose own `amount_cents` is at
    least 900,000 and at most 1,000,000 cents — the just-under-threshold band,
    inclusive at both ends — fires `STRUCTURING`."

    1,000,000 exactly does NOT fire CTR (falls to STRUCTURING); 1,000,001 fires CTR.

    Design: Difficulty/boundary_precision_check/ctr_threshold_strict_gt_boundary_on_transactions
    """
    cust = fx.create_legal_entity(legal_name="Bnd Co")
    acct_eq = fx.create_account(cust["id"], account_ref="AC-BND-EQ")
    acct_gt = fx.create_account(cust["id"], account_ref="AC-BND-GT")
    eq = validate_success(api.post_transaction(
        acct_eq["id"], create_transaction_payload(direction="CASH_IN", amount_cents=1000000,
                                                  posted_at="2026-06-03T08:00:00Z", counterparty_country="US"), SF), 201)
    gt = validate_success(api.post_transaction(
        acct_gt["id"], create_transaction_payload(direction="CASH_IN", amount_cents=1000001,
                                                  posted_at="2026-06-03T08:00:00Z", counterparty_country="US"), SF), 201)
    assert eq["triggered_rule"] == "STRUCTURING"
    assert gt["triggered_rule"] == "CTR_THRESHOLD"


def test_ctr_cumulative_window_crosses_strict_boundary(api):
    """PRD §3.6: "for a `CASH_IN`, take the same-UTC-day cash-in window total
    after this amount is added; if that post-addition total is strictly greater
    than 1,000,000 cents (that is, strictly above 10,000 dollars), the rule
    `CTR_THRESHOLD` fires — a window total of exactly 1,000,000 cents does not
    fire, because the boundary is strict."

    Accumulation facet of the same strict-> boundary: 500,000 + 500,001 on the
    same UTC day makes the window 1,000,001 (> 1,000,000) and the SECOND cash-in
    fires CTR, while a prior window of exactly 1,000,000 would not have.

    Design: Difficulty/boundary_precision_check/ctr_threshold_strict_gt_boundary_on_transactions
    """
    cust = fx.create_legal_entity(legal_name="Cum Co")
    acct = fx.create_account(cust["id"], account_ref="AC-CUM-1")
    t1 = validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=500000,
                                               posted_at="2026-06-03T08:00:00Z", counterparty_country="US"), SF), 201)
    t2 = validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=500001,
                                               posted_at="2026-06-03T12:00:00Z", counterparty_country="US"), SF), 201)
    assert t1["triggered_rule"] is None        # window 500,000, below band and below CTR
    assert t2["triggered_rule"] == "CTR_THRESHOLD"  # window 1,000,001 > 1,000,000


def test_enqueue_empty_window_returns_review_empty(api):
    """PRD §3.10: "Enqueue requires at least one in-window account: if the window
    contains no qualifying account, the review stays `PLANNED` and the request is
    rejected with `ERR_REVIEW_EMPTY`."

    Design: Difficulty/boundary_precision_check/enqueue_empty_window_zero_accounts_on_lookback
    """
    review = fx.create_lookback_review(
        reason="empty window probe", window_start="2030-01-01T00:00:00Z",
        window_end="2030-01-08T00:00:00Z")
    validate_error(api.enqueue_lookback_review(review["id"], CO), ApiErrorId.ERR_REVIEW_EMPTY.value)
    after = validate_success(api.get_lookback_review(review["id"], CO))
    assert after["status"] == "PLANNED"


def test_enqueue_empty_when_only_txn_at_window_end(api):
    """PRD §3.10: "a transaction posted exactly at `window_start` is in-window,
    while one posted exactly at `window_end` is not."
    PRD §3.10: "Enqueue requires at least one in-window account: if the window
    contains no qualifying account, the review stays `PLANNED` and the request is
    rejected with `ERR_REVIEW_EMPTY`."

    The only candidate transaction sits exactly at window_end (excluded), so the
    qualifying set is empty -> ERR_REVIEW_EMPTY and the review stays PLANNED. This
    exercises the zero-count edge via boundary exclusion rather than a far-future
    window.

    Design: Difficulty/boundary_precision_check/enqueue_empty_window_zero_accounts_on_lookback
    """
    cust = fx.create_legal_entity(legal_name="EndOnly Co")
    acct = fx.create_account(cust["id"], account_ref="AC-ENDONLY-1")
    validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=5000,
                                               posted_at="2026-06-08T00:00:00Z", counterparty_country="US"), SF), 201)
    review = fx.create_lookback_review(
        reason="end-only probe", window_start="2026-06-01T00:00:00Z",
        window_end="2026-06-08T00:00:00Z")
    validate_error(api.enqueue_lookback_review(review["id"], CO), ApiErrorId.ERR_REVIEW_EMPTY.value)
    after = validate_success(api.get_lookback_review(review["id"], CO))
    assert after["status"] == "PLANNED"


# ==========================================================================
# Queue A — resource_temporal_overlap (CTR window day-bucket reset)
# ==========================================================================
def test_ctr_window_resets_at_utc_midnight(api):
    """PRD §3.6: "the relevant window is the calendar-day bucket of `posted_at` in
    UTC, spanning from midnight up to but not including the next midnight, and
    when a transaction's `posted_at` falls on a new UTC day the aggregate resets
    to zero before this transaction is folded in."

    600,000 on day 1 (23:00) then 600,000 on day 2 (01:00): each is alone in its
    own day-bucket, so neither tips a 1,000,000 window, and the day-2 aggregate is
    only 600,000.

    Design: Difficulty/resource_temporal_overlap/ctr_window_calendar_day_bucket_resets_at_utc_midnight
    """
    cust = fx.create_legal_entity(legal_name="Win Co")
    acct = fx.create_account(cust["id"], account_ref="AC-WIN-1")
    day1 = validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=600000,
                                               posted_at="2026-06-06T23:00:00Z", counterparty_country="US"), SF), 201)
    day2 = validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=600000,
                                               posted_at="2026-06-07T01:00:00Z", counterparty_country="US"), SF), 201)
    assert day1["triggered_rule"] is None
    assert day2["triggered_rule"] is None
    acct_after = validate_success(api.get_account(acct["id"], CO))
    assert acct_after["aggregate_cash_in_cents"] == 600000


def test_ctr_window_accumulates_within_same_day(api):
    """PRD §3.6: "the relevant window is the calendar-day bucket of `posted_at` in
    UTC, spanning from midnight up to but not including the next midnight, and
    when a transaction's `posted_at` falls on a new UTC day the aggregate resets
    to zero before this transaction is folded in."
    PRD §3.6: "for a `CASH_IN`, take the same-UTC-day cash-in window total after
    this amount is added; if that post-addition total is strictly greater than
    1,000,000 cents (that is, strictly above 10,000 dollars), the rule
    `CTR_THRESHOLD` fires — a window total of exactly 1,000,000 cents does not
    fire, because the boundary is strict."

    The same-day positive control for the day-bucket: two 600,000 cash-ins on the
    SAME UTC day accumulate to 1,200,000 (> 1,000,000), so the second fires CTR —
    the bucket does NOT reset between same-day transactions.

    Design: Difficulty/resource_temporal_overlap/ctr_window_calendar_day_bucket_resets_at_utc_midnight
    """
    cust = fx.create_legal_entity(legal_name="SameDay Co")
    acct = fx.create_account(cust["id"], account_ref="AC-SAMEDAY-1")
    t1 = validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=600000,
                                               posted_at="2026-06-06T08:00:00Z", counterparty_country="US"), SF), 201)
    t2 = validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=600000,
                                               posted_at="2026-06-06T20:00:00Z", counterparty_country="US"), SF), 201)
    assert t1["triggered_rule"] is None
    assert t2["triggered_rule"] == "CTR_THRESHOLD"
    acct_after = validate_success(api.get_account(acct["id"], CO))
    assert acct_after["aggregate_cash_in_cents"] == 1200000


# ==========================================================================
# Queue A — cross_entity_state_dependency (transaction blocked by account status)
# ==========================================================================
def test_transaction_blocked_by_offboarded_account(api):
    """PRD §3.1: "as a cascade, every account whose `monitoring_status` is not
    already `FROZEN` has its `monitoring_status` set to `FROZEN` and its
    `kyc_status` set to `KYC_BLOCKED`."
    PRD §3.6: "A transaction may not be posted to an account whose `kyc_status`
    is `KYC_BLOCKED` or whose `monitoring_status` is `FROZEN`; such a post is
    rejected with `ERR_ACCOUNT_NOT_TRANSACTABLE`."

    An OFFBOARDED customer's account is KYC_BLOCKED + FROZEN -> posting rejected.

    Design: Difficulty/cross_entity_state_dependency/transaction_blocked_by_account_status_pair_transaction_account
    """
    customer = validate_success(api.create_customer(
        create_customer_payload(legal_name="Off Co", date_of_birth="1988-08-08"), CO), 201)
    cid = customer["id"]
    acct = validate_success(api.create_account(cid, create_account_payload(account_ref="AC-OFF-1"), CO), 201)
    ra = validate_success(api.create_risk_assessment(
        cid, create_risk_assessment_payload(variant="PROVISIONAL", geography_factor=1,
                                            product_factor=1, pep_factor=1, adverse_media_factor=1), CO), 201)
    validate_success(api.apply_rating(
        cid, {"risk_assessment_id": ra["id"], "expected_customer_version": customer["version"]}, CO))
    validate_success(api.clear_screening(cid, CO))
    validate_success(api.approve_customer(cid, CO))
    offb = validate_success(api.offboard_customer(cid, CO))
    assert offb["cdd_status"] == "OFFBOARDED"
    acct_after = validate_success(api.get_account(acct["id"], CO))
    assert acct_after["kyc_status"] == "KYC_BLOCKED" and acct_after["monitoring_status"] == "FROZEN"
    validate_error(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=5000,
                                               posted_at="2026-06-05T08:00:00Z", counterparty_country="US"), SF),
        ApiErrorId.ERR_ACCOUNT_NOT_TRANSACTABLE.value)


def test_transaction_blocked_by_rejected_account(api):
    """PRD §3.1: "If the applied band is `PROHIBITED`, the customer is immediately
    driven to the terminal `REJECTED` state and, as a cascade, every account of
    that customer whose `monitoring_status` is not already `FROZEN` has its
    `kyc_status` set to `KYC_BLOCKED` and its `monitoring_status` set to
    `FROZEN`."
    PRD §3.6: "A transaction may not be posted to an account whose `kyc_status`
    is `KYC_BLOCKED` or whose `monitoring_status` is `FROZEN`; such a post is
    rejected with `ERR_ACCOUNT_NOT_TRANSACTABLE`."

    A distinct route into the same Transaction->Account dependency: the account is
    locked by a PROHIBITED/REJECTED owner rather than an OFFBOARDED one.

    Design: Difficulty/cross_entity_state_dependency/transaction_blocked_by_account_status_pair_transaction_account
    """
    customer = validate_success(api.create_customer(
        create_customer_payload(legal_name="Rej Co", date_of_birth="1962-02-02"), CO), 201)
    cid = customer["id"]
    acct = validate_success(api.create_account(cid, create_account_payload(account_ref="AC-REJ-1"), CO), 201)
    ra = validate_success(api.create_risk_assessment(
        cid, create_risk_assessment_payload(variant="PROVISIONAL", geography_factor=5,
                                            product_factor=5, pep_factor=5, adverse_media_factor=5), CO), 201)
    rated = validate_success(api.apply_rating(
        cid, {"risk_assessment_id": ra["id"], "expected_customer_version": customer["version"]}, CO))
    assert rated["cdd_status"] == "REJECTED"
    acct_after = validate_success(api.get_account(acct["id"], CO))
    assert acct_after["kyc_status"] == "KYC_BLOCKED"
    validate_error(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=5000,
                                               posted_at="2026-06-05T08:00:00Z", counterparty_country="US"), SF),
        ApiErrorId.ERR_ACCOUNT_NOT_TRANSACTABLE.value)


# ==========================================================================
# Queue B — transaction / account corner instances
# ==========================================================================
def test_transaction_immutable_no_version_field(api):
    """PRD §2.4: "A `Transaction` and an `AuditEvent` are immutable append-only
    records: each carries only `id` and `created_at`, and neither carries
    `updated_at` nor `version`."

    Design: Corner/entities/transaction_immutable_no_version_field
    """
    cust = fx.create_legal_entity(legal_name="Imm Co", incorporation_date="2018-08-08")
    acct = fx.create_account(cust["id"], account_ref="AC-IMM-1")
    txn = validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=5000,
                                               posted_at="2026-06-11T08:00:00Z", counterparty_country="US"), SF), 201)
    assert "id" in txn and "created_at" in txn
    assert "version" not in txn
    assert "updated_at" not in txn


def test_account_parallel_dimensions_independent(api):
    """PRD §3.6: "an account in `ACTIVE` moves to `UNDER_INVESTIGATION` when an
    alert is created against it".
    PRD §3.6: "The KYC dimension is driven entirely by the owning customer's
    lifecycle. When the customer reaches `APPROVED`, accounts in `PENDING_KYC`
    cascade to `KYC_OK`."

    Firing an alert on a not-yet-approved customer's account moves
    monitoring_status to UNDER_INVESTIGATION while kyc_status stays PENDING_KYC.

    Design: Corner/state_machines/account_parallel_dimensions_independent
    """
    cust = fx.create_legal_entity(legal_name="Par Co", incorporation_date="2003-03-03")
    acct = fx.create_account(cust["id"], account_ref="AC-PAR-1")
    validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=950000,
                                               posted_at="2026-06-15T08:00:00Z", counterparty_country="US"), SF), 201)
    acct_after = validate_success(api.get_account(acct["id"], CO))
    assert acct_after["monitoring_status"] == "UNDER_INVESTIGATION"
    assert acct_after["kyc_status"] == "PENDING_KYC"


def test_duplicate_account_ref_returns_409(api):
    """PRD §3.6: "The `account_ref` must be unique across all accounts; a
    duplicate is rejected with `ERR_DUPLICATE_ACCOUNT_REF`."

    Design: Corner/validations/duplicate_account_ref_returns_409
    """
    cust = fx.create_legal_entity(legal_name="Dup Co", incorporation_date="1998-08-08")
    validate_success(api.create_account(cust["id"], create_account_payload(account_ref="AC-DUP-1"), CO), 201)
    validate_error(api.create_account(
        cust["id"], create_account_payload(account_ref="AC-DUP-1", opening_balance_cents=100), CO),
        ApiErrorId.ERR_DUPLICATE_ACCOUNT_REF.value)


def test_account_not_transactable_when_frozen(api):
    """PRD §3.6: "a `ComplianceOfficer` may freeze an account that is
    `UNDER_INVESTIGATION`, moving its `monitoring_status` to `FROZEN`".
    PRD §3.6: "A transaction may not be posted to an account whose `kyc_status`
    is `KYC_BLOCKED` or whose `monitoring_status` is `FROZEN`; such a post is
    rejected with `ERR_ACCOUNT_NOT_TRANSACTABLE`."

    Design: Corner/validations/account_not_transactable_when_frozen
    """
    cust = fx.create_legal_entity(legal_name="Frz Co", incorporation_date="1995-05-05")
    acct = fx.create_account(cust["id"], account_ref="AC-FRZ-1")
    validate_success(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=950000,
                                               posted_at="2026-06-20T08:00:00Z", counterparty_country="US"), SF), 201)
    frozen = validate_success(api.freeze_account(acct["id"], CO))
    assert frozen["monitoring_status"] == "FROZEN"
    validate_error(api.post_transaction(
        acct["id"], create_transaction_payload(direction="CASH_IN", amount_cents=5000,
                                               posted_at="2026-06-20T10:00:00Z", counterparty_country="US"), SF),
        ApiErrorId.ERR_ACCOUNT_NOT_TRANSACTABLE.value)
