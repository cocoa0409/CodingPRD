"""Interest accrual, stop-payment orders, ownership, and APY-tier matching
(PRD §3.3, §3.9–§3.11).

Covers queue-A difficulty instances for the single-truncation interest formula, the
half-open interest-period overlap geometry, the closed-band duplicate-stop geometry, and
the Application-depends-on-ApyTier dependency, plus queue-B corner instances for interest
precision, POD/last-primary owner rules, and stop-expiry validation.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    make_account_holder_headers,
    make_officer_headers,
    set_clock,
    create_apy_tier,
    create_customer,
    create_submitted_application,
    open_account,
    open_account_with_deposit,
    place_stop_payment,
)
from test_helpers.factories import (
    interest_posting_payload,
    stop_payment_payload,
    owner_payload,
)


def _holder(customer):
    return make_account_holder_headers(customer["id"])


# ===========================================================================
# Queue A — combinatorial_formula / interest_accrual_truncate_after_full_product
# ===========================================================================
def test_interest_single_truncation_after_full_product(api):
    """PRD §3.11: "The raw interest is that period-start balance multiplied by the tier's
    `annual_rate_bps`, divided by ten thousand to convert basis points to a fraction,
    multiplied by the number of days, and divided by 365 for the day-count basis".
    PRD §3.11: "The full multiplication and division are carried out first, and only then
    is the result truncated toward zero to whole cents in a single step to yield
    `posted_interest_cents`; there is no intermediate per-day rounding."

    Ledger 1000000, 450 bps, 31 days -> 1000000*450/10000*31/365 = 3821.9..., floor 3821;
    the INTEREST credit lifts ledger to 1003821 and resets accrued to 0.

    Design: Difficulty/combinatorial_formula/interest_accrual_truncate_after_full_product
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="HY1", product_type="SAVINGS", annual_rate_bps=450)
    cust, account = open_account_with_deposit(
        deposit_cents=1000000, product_type="SAVINGS", requested_apy_tier_code="HY1",
        customer_overrides={"tax_id_last4": "1010"},
    )
    posting = validate_success(
        api.post_interest(
            account["id"], interest_posting_payload("2026-01-01", "2026-02-01"),
            make_officer_headers("officer-1"),
        ),
        201,
    )
    assert posting["posted_interest_cents"] == 3821

    acct_after = validate_success(api.get_account(account["id"], make_officer_headers()), 200)
    assert acct_after["ledger_balance_cents"] == 1003821
    assert acct_after["accrued_interest_cents"] == 0


def test_interest_posting_records_resolved_tier_and_credit(api):
    """PRD §3.11: "Posting creates an `INTEREST` credit transaction for
    `posted_interest_cents`, resets the account's `accrued_interest_cents` to zero, and
    records the resulting `InterestPosting` with its `account_id`, the period bounds, the
    computed `posted_interest_cents`, and the `applied_apy_tier_code` resolved at posting
    time."
    PRD §3.11: "the system resolves the `ApyTier` whose `code` equals the account's
    `apy_tier_code`".

    The posting records applied_apy_tier_code HY1 and an INTEREST credit transaction of
    3821 cents is posted to the account.

    Design: Difficulty/combinatorial_formula/interest_accrual_truncate_after_full_product
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="HY1", product_type="SAVINGS", annual_rate_bps=450)
    cust, account = open_account_with_deposit(
        deposit_cents=1000000, product_type="SAVINGS", requested_apy_tier_code="HY1",
        customer_overrides={"tax_id_last4": "1011"},
    )
    posting = validate_success(
        api.post_interest(
            account["id"], interest_posting_payload("2026-01-01", "2026-02-01"),
            make_officer_headers("officer-1"),
        ),
        201,
    )
    assert posting["applied_apy_tier_code"] == "HY1"
    assert posting["posted_interest_cents"] == 3821

    txns = validate_success(
        api.list_account_transactions(
            account["id"], make_officer_headers(), params={"limit": 100}
        ),
        200,
    )
    interest_txns = [t for t in txns if t["txn_type"] == "INTEREST"]
    assert len(interest_txns) == 1
    assert interest_txns[0]["direction"] == "CREDIT"
    assert interest_txns[0]["amount_cents"] == 3821


# ===========================================================================
# Queue B — calculations / interest_truncates_subdollar_to_zero
# ===========================================================================
def test_interest_truncates_subdollar_to_zero(api):
    """PRD §3.11: "only then is the result truncated toward zero to whole cents in a
    single step to yield `posted_interest_cents`".

    Ledger 100, 100 bps, 1 day -> 100*100/10000*1/365 = 0.0027, floor 0; ledger
    unchanged at 100.

    Design: Corner/calculations/interest_truncates_subdollar_to_zero
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="LOW", product_type="SAVINGS", annual_rate_bps=100)
    cust, account = open_account_with_deposit(
        deposit_cents=100, product_type="SAVINGS", requested_apy_tier_code="LOW",
        customer_overrides={"tax_id_last4": "1919"},
    )
    posting = validate_success(
        api.post_interest(
            account["id"], interest_posting_payload("2026-01-01", "2026-01-02"),
            make_officer_headers("officer-1"),
        ),
        201,
    )
    assert posting["posted_interest_cents"] == 0
    acct_after = validate_success(api.get_account(account["id"], make_officer_headers()), 200)
    assert acct_after["ledger_balance_cents"] == 100


# ===========================================================================
# Queue A — resource_temporal_overlap / interest_period_halfopen_overlap_rejected_adjacent_ok
# ===========================================================================
def test_adjacent_interest_period_accepted_overlap_rejected(api):
    """PRD §3.11: "The new period must not overlap any existing interest posting interval
    for the same account; because the interval is half-open, adjacency is allowed — a new
    period whose start equals a prior period's end does not overlap and is accepted — but
    any genuine overlap is rejected with `ERR_INTEREST_PERIOD_OVERLAP`."

    With [2026-01-01, 2026-02-01) posted: the adjacent [2026-02-01, 2026-03-01) is
    accepted (201); the overlapping [2026-01-15, 2026-02-15) is rejected; exactly 2
    postings remain.

    Design: Difficulty/resource_temporal_overlap/interest_period_halfopen_overlap_rejected_adjacent_ok
    """
    set_clock("2026-03-01T00:00:00Z")
    create_apy_tier(code="HY1", product_type="SAVINGS", annual_rate_bps=450)
    cust, account = open_account_with_deposit(
        deposit_cents=1000000, product_type="SAVINGS", requested_apy_tier_code="HY1",
        customer_overrides={"tax_id_last4": "1313"},
    )
    validate_success(
        api.post_interest(
            account["id"], interest_posting_payload("2026-01-01", "2026-02-01"),
            make_officer_headers("officer-1"),
        ),
        201,
    )
    # Adjacent period: start == prior end -> accepted.
    validate_success(
        api.post_interest(
            account["id"], interest_posting_payload("2026-02-01", "2026-03-01"),
            make_officer_headers("officer-1"),
        ),
        201,
    )
    # Overlapping period -> rejected.
    res = api.post_interest(
        account["id"], interest_posting_payload("2026-01-15", "2026-02-15"),
        make_officer_headers("officer-1"),
    )
    validate_error(res, "ERR_INTEREST_PERIOD_OVERLAP", expected_status=409)

    postings = validate_success(
        api.list_interest_postings(account["id"], make_officer_headers()), 200
    )
    assert len(postings) == 2, f"exactly 2 postings expected, got {len(postings)}"


def test_overlapping_interest_period_rejected_only(api):
    """PRD §3.11: "any genuine overlap is rejected with `ERR_INTEREST_PERIOD_OVERLAP`."

    A period nested inside an existing one is a genuine overlap and is rejected.

    Design: Difficulty/resource_temporal_overlap/interest_period_halfopen_overlap_rejected_adjacent_ok
    """
    set_clock("2026-03-01T00:00:00Z")
    create_apy_tier(code="HY1", product_type="SAVINGS", annual_rate_bps=450)
    cust, account = open_account_with_deposit(
        deposit_cents=1000000, product_type="SAVINGS", requested_apy_tier_code="HY1",
        customer_overrides={"tax_id_last4": "1314"},
    )
    validate_success(
        api.post_interest(
            account["id"], interest_posting_payload("2026-01-01", "2026-02-01"),
            make_officer_headers("officer-1"),
        ),
        201,
    )
    res = api.post_interest(
        account["id"], interest_posting_payload("2026-01-10", "2026-01-20"),
        make_officer_headers("officer-1"),
    )
    validate_error(res, "ERR_INTEREST_PERIOD_OVERLAP", expected_status=409)


# ===========================================================================
# Queue A — resource_temporal_overlap / duplicate_active_stop_payment_amount_band_rejected
# ===========================================================================
def test_duplicate_active_stop_payment_rejected(api):
    """PRD §3.10: "At most one `ACTIVE` stop-payment order may cover a given
    `check_number` on an account — because every active stop covers the closed amount
    band from one cent up to its `max_amount_cents`, two active stops on the same check
    necessarily overlap in coverage — so a second active stop on the same check is
    rejected with `ERR_DUPLICATE_STOP_PAYMENT`."

    A second ACTIVE stop on check 9001 (even with a smaller max) is rejected; exactly one
    ACTIVE stop remains.

    Design: Difficulty/resource_temporal_overlap/duplicate_active_stop_payment_amount_band_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account(customer_overrides={"tax_id_last4": "1414"})
    holder = _holder(cust)
    place_stop_payment(account["id"], cust["id"], check_number="9001",
                       max_amount_cents=8000, expires_on="2026-12-31")
    res = api.create_stop_payment(
        account["id"], stop_payment_payload("9001", 3000, "2026-12-31"), holder
    )
    validate_error(res, "ERR_DUPLICATE_STOP_PAYMENT", expected_status=409)

    stops = validate_success(
        api.list_stop_payments(account["id"], holder, params={"status": "ACTIVE"}), 200
    )
    active_9001 = [s for s in stops if s["check_number"] == "9001" and s["status"] == "ACTIVE"]
    assert len(active_9001) == 1


def test_second_stop_different_check_allowed(api):
    """PRD §3.10: "At most one `ACTIVE` stop-payment order may cover a given
    `check_number` on an account".

    The constraint is per-check_number: a stop on a *different* check (9002) is accepted
    alongside the first.

    Design: Difficulty/resource_temporal_overlap/duplicate_active_stop_payment_amount_band_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account(customer_overrides={"tax_id_last4": "1415"})
    holder = _holder(cust)
    place_stop_payment(account["id"], cust["id"], check_number="9001",
                       max_amount_cents=8000, expires_on="2026-12-31")
    second = validate_success(
        api.create_stop_payment(
            account["id"], stop_payment_payload("9002", 3000, "2026-12-31"), holder
        ),
        201,
    )
    assert second["status"] == "ACTIVE"
    assert second["check_number"] == "9002"


# ===========================================================================
# Queue A — cross_entity_state_dependency / approve_requires_matching_apy_tier_product
# ===========================================================================
def test_approve_rejects_product_type_tier_mismatch(api):
    """PRD §3.3: "Beyond segregation of duties, approval requires that the
    `kyc_risk_score` be strictly below 70 — a score of 70 or higher is rejected with
    `ERR_KYC_RISK_TOO_HIGH` — and that the application's `requested_apy_tier_code` resolve
    to an `ApyTier` whose `product_type` equals the application's `product_type`, failing
    which the request is rejected with `ERR_APY_TIER_NOT_FOUND`."

    Only a SAVINGS tier HYS exists; a SUBMITTED CHECKING application requesting HYS is
    rejected ERR_APY_TIER_NOT_FOUND at approve and stays SUBMITTED.

    Design: Difficulty/cross_entity_state_dependency/approve_requires_matching_apy_tier_product
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="HYS", product_type="SAVINGS", annual_rate_bps=300)
    cust = create_customer(legal_name="Mismatch Owner", tax_id_last4="9090")
    app = create_submitted_application(
        cust["id"], product_type="CHECKING", requested_apy_tier_code="HYS",
        submitted_by="teller-1",
    )
    res = api.approve_application(app["id"], make_officer_headers("officer-1"))
    validate_error(res, "ERR_APY_TIER_NOT_FOUND", expected_status=404)

    app_after = validate_success(api.get_application(app["id"], make_officer_headers()), 200)
    assert app_after["status"] == "SUBMITTED"


def test_approve_succeeds_with_matching_product_tier(api):
    """PRD §3.3: "Beyond segregation of duties, approval requires that the
    `kyc_risk_score` be strictly below 70 — a score of 70 or higher is rejected with
    `ERR_KYC_RISK_TOO_HIGH` — and that the application's `requested_apy_tier_code` resolve
    to an `ApyTier` whose `product_type` equals the application's `product_type`, failing
    which the request is rejected with `ERR_APY_TIER_NOT_FOUND`."

    The positive leg of the same dependency: a SAVINGS application requesting a SAVINGS
    tier approves and opens a SAVINGS account.

    Design: Difficulty/cross_entity_state_dependency/approve_requires_matching_apy_tier_product
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="HYS", product_type="SAVINGS", annual_rate_bps=300)
    cust = create_customer(legal_name="Match Owner", tax_id_last4="9091")
    app = create_submitted_application(
        cust["id"], product_type="SAVINGS", requested_apy_tier_code="HYS",
        submitted_by="teller-1",
    )
    approved = validate_success(
        api.approve_application(app["id"], make_officer_headers("officer-1")), 200
    )
    account = validate_success(
        api.get_account(approved["opened_account_id"], make_officer_headers()), 200
    )
    assert account["product_type"] == "SAVINGS"
    assert account["apy_tier_code"] == "HYS"


# ===========================================================================
# Queue B — validations / pod_already_designated_rejected
# ===========================================================================
def test_pod_already_designated_rejected(api):
    """PRD §3.9: "An account may carry at most one active `POD_BENEFICIARY` owner; an
    attempt to add a second active POD beneficiary is rejected with
    `ERR_POD_ALREADY_DESIGNATED`."

    Design: Corner/validations/pod_already_designated_rejected
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account(customer_overrides={
        "legal_name": "Primary Owner", "tax_id_last4": "2626",
    })
    pod1 = create_customer(legal_name="POD One", tax_id_last4="2727")
    pod2 = create_customer(legal_name="POD Two", tax_id_last4="2828")
    holder = _holder(cust)
    validate_success(
        api.add_owner(account["id"], owner_payload(pod1["id"], "POD_BENEFICIARY"), holder), 201
    )
    res = api.add_owner(account["id"], owner_payload(pod2["id"], "POD_BENEFICIARY"), holder)
    validate_error(res, "ERR_POD_ALREADY_DESIGNATED", expected_status=409)


# ===========================================================================
# Queue B — validations / cannot_remove_last_primary_owner
# ===========================================================================
def test_cannot_remove_last_primary_owner(api):
    """PRD §3.9: "an account must always retain at least one active `PRIMARY` owner;
    deactivating an owner that is the last active `PRIMARY` is rejected with
    `ERR_LAST_PRIMARY_OWNER`."

    Design: Corner/validations/cannot_remove_last_primary_owner
    """
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account(customer_overrides={
        "legal_name": "Sole Primary", "tax_id_last4": "2929",
    })
    holder = _holder(cust)
    owners = validate_success(api.list_owners(account["id"], holder), 200)
    primary = [o for o in owners if o["ownership_role"] == "PRIMARY"][0]
    res = api.delete_owner(account["id"], primary["id"], holder)
    validate_error(res, "ERR_LAST_PRIMARY_OWNER", expected_status=409)


# ===========================================================================
# Queue B — validations / stop_payment_expiry_in_past_rejected
# ===========================================================================
def test_stop_payment_expiry_not_future_rejected(api):
    """PRD §3.10: "The `expires_on` date is exclusive: the order is already dead on that
    date, so it must be strictly after the current ledger clock date, or the placement
    is rejected with `ERR_STOP_EXPIRY_IN_PAST`."

    expires_on equal to the current ledger date (2026-01-01) is not strictly future.

    Design: Corner/validations/stop_payment_expiry_in_past_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    create_apy_tier(code="CHK_STD", product_type="CHECKING")
    cust, account = open_account(customer_overrides={"tax_id_last4": "2424"})
    holder = _holder(cust)
    res = api.create_stop_payment(
        account["id"], stop_payment_payload("3001", 5000, "2026-01-01"), holder
    )
    validate_error(res, "ERR_STOP_EXPIRY_IN_PAST", expected_status=422)
