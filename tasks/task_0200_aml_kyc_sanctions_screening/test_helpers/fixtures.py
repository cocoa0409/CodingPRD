"""Composite setup helpers.

These encapsulate the multi-step API sequences that most interesting test claims
require to reach a specific state. They use get_success_data() (lenient) internally
so that a broken precondition surfaces as a clear "Setup failed" rather than a
confusing assertion deep in a test.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints — the test harness restarts the server (empty DB) before each test.

All five roles are opaque (PRD §2.1), so headers are shared constants from
test_users.TEST_USERS.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_headers
from .factories import (
    create_customer_payload, create_legal_entity_payload,
    create_risk_assessment_payload, create_account_payload,
    create_transaction_payload, create_screening_hit_payload,
    create_lookback_review_payload,
)

CO = TEST_USERS["compliance_officer_headers"]
AN = TEST_USERS["analyst_headers"]
QR = TEST_USERS["quality_reviewer_headers"]
SF = TEST_USERS["system_feed_headers"]
PA = TEST_USERS["platform_admin_headers"]


# --------------------------------------------------------------------------
# Clock control
# --------------------------------------------------------------------------
def set_clock(iso8601: str):
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, PA))


# --------------------------------------------------------------------------
# Tier 1: Customer creation + lifecycle progression
# --------------------------------------------------------------------------
def create_customer(**overrides) -> dict:
    """A NEW INDIVIDUAL customer."""
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), CO))


def create_legal_entity(**overrides) -> dict:
    """A NEW LEGAL_ENTITY customer."""
    return get_success_data(api_client.create_customer(create_legal_entity_payload(**overrides), CO))


def create_account(customer_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_account(customer_id, create_account_payload(**overrides), CO))


def create_and_rate_customer(factors=None, *, legal_entity=False, **cust_overrides) -> dict:
    """Create a customer, create a PROVISIONAL assessment, apply it.

    Returns the customer dict as returned by apply-rating (RISK_RATED, with
    risk_rating/risk_score set). `factors` is a dict of the four *_factor inputs;
    defaults to all-1 (LOW).
    """
    factors = factors or {}
    cust = create_legal_entity(**cust_overrides) if legal_entity else create_customer(**cust_overrides)
    ra = get_success_data(api_client.create_risk_assessment(
        cust["id"], create_risk_assessment_payload(variant="PROVISIONAL", **factors), CO))
    rated = get_success_data(api_client.apply_rating(
        cust["id"], {"risk_assessment_id": ra["id"], "expected_customer_version": cust["version"]}, CO))
    return rated


def create_approved_customer(factors=None, *, legal_entity=False, **cust_overrides) -> dict:
    """Drive a customer all the way to APPROVED (LOW by default).

    Path: create -> rate -> clear-screening -> approve. Only valid for a band
    whose edd_required is false (i.e. not HIGH and no open hits). Returns the
    APPROVED customer dict.
    """
    rated = create_and_rate_customer(factors=factors, legal_entity=legal_entity, **cust_overrides)
    cid = rated["id"]
    get_success_data(api_client.clear_screening(cid, CO))
    return get_success_data(api_client.approve_customer(cid, CO))


def create_screening_hit(customer_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_screening_hit(
        customer_id, create_screening_hit_payload(**overrides), CO))


def confirm_hit(hit_id: str) -> dict:
    """Walk a PENDING hit ESCALATE -> CONFIRM. Returns the CONFIRMED hit."""
    get_success_data(api_client.disposition_hit(hit_id, {"decision": "ESCALATE"}, CO))
    return get_success_data(api_client.disposition_hit(hit_id, {"decision": "CONFIRM"}, CO))


# --------------------------------------------------------------------------
# Tier 2 / 4: Account + transaction -> alert
# --------------------------------------------------------------------------
def post_transaction(account_id: str, **overrides) -> dict:
    return get_success_data(api_client.post_transaction(
        account_id, create_transaction_payload(**overrides), SF))


def setup_account_with_alert(rule="STRUCTURING", *, legal_entity=True,
                             factors=None, rate=False, approve=False,
                             **cust_overrides):
    """Create a customer + account, then fire one alert of the requested rule.

    rule:
      STRUCTURING -> a single CASH_IN of 950,000 (in the struct band).
      CTR_THRESHOLD -> a single CASH_IN of 1,000,001 (strictly over the limit).
      HIGH_RISK_GEO -> a small CASH_IN from IR.

    If `rate` is true the customer is rated with `factors` first (so the alert's
    severity reflects the owning customer's risk_rating). If `approve` is true the
    customer is driven all the way to APPROVED before the transaction posts.

    Returns (customer, account, alert).
    """
    if approve:
        cust = create_approved_customer(factors=factors, legal_entity=legal_entity, **cust_overrides)
        acct = create_account(cust["id"], account_ref=_ref())
        # cascade may have moved kyc to KYC_OK; account opened post-approve stays PENDING_KYC,
        # which is still transactable.
    elif rate:
        cust = create_and_rate_customer(factors=factors, legal_entity=legal_entity, **cust_overrides)
        acct = create_account(cust["id"], account_ref=_ref())
    else:
        cust = create_legal_entity(**cust_overrides) if legal_entity else create_customer(**cust_overrides)
        acct = create_account(cust["id"], account_ref=_ref())

    if rule == "STRUCTURING":
        post_transaction(acct["id"], direction="CASH_IN", amount_cents=950000, counterparty_country="US")
    elif rule == "CTR_THRESHOLD":
        post_transaction(acct["id"], direction="CASH_IN", amount_cents=1000001, counterparty_country="US")
    elif rule == "HIGH_RISK_GEO":
        post_transaction(acct["id"], direction="CASH_IN", amount_cents=5000, counterparty_country="IR")
    else:
        raise ValueError(f"unsupported rule {rule}")

    alerts, _ = _list(api_client.list_account_alerts(acct["id"], AN))
    alert = alerts[0]
    return cust, acct, alert


# --------------------------------------------------------------------------
# Tier 3: Case + linked alert
# --------------------------------------------------------------------------
def open_case(customer_id: str, user_id="an-1") -> dict:
    return get_success_data(api_client.create_case(
        {"customer_id": customer_id}, make_headers(user_id, "Analyst")))


def setup_case_with_linked_alert(rule="STRUCTURING", *, factors=None, rate=False,
                                 approve=False, analyst_user_id="an-1"):
    """Customer + account fires `rule`; open a case; link the alert (auto-advances
    TRIAGE -> INVESTIGATING). Returns (customer, account, alert, case)."""
    cust, acct, alert = setup_account_with_alert(
        rule=rule, factors=factors, rate=rate, approve=approve)
    case = open_case(cust["id"], user_id=analyst_user_id)
    linked = get_success_data(api_client.link_alert(
        case["id"],
        {"alert_id": alert["id"], "expected_case_version": case["version"]},
        make_headers(analyst_user_id, "Analyst")))
    return cust, acct, alert, linked


# --------------------------------------------------------------------------
# Tier 5: Full filing lifecycle
# --------------------------------------------------------------------------
def setup_sar_recommended_case(*, analyst_user_id="an-1"):
    """Customer + STRUCTURING alert linked into an INVESTIGATING case, then
    RECOMMEND_SAR. Returns (customer, account, alert, case)."""
    cust, acct, alert, case = setup_case_with_linked_alert(
        rule="STRUCTURING", analyst_user_id=analyst_user_id)
    case = get_success_data(api_client.disposition_case(
        case["id"], {"decision": "RECOMMEND_SAR"}, make_headers(analyst_user_id, "Analyst")))
    return cust, acct, alert, case


def setup_ctr_required_case(*, analyst_user_id="an-1"):
    """Customer + CTR_THRESHOLD alert linked into an INVESTIGATING case, then
    REQUIRE_CTR. Returns (customer, account, alert, case)."""
    cust, acct, alert, case = setup_case_with_linked_alert(
        rule="CTR_THRESHOLD", analyst_user_id=analyst_user_id)
    case = get_success_data(api_client.disposition_case(
        case["id"], {"decision": "REQUIRE_CTR"}, make_headers(analyst_user_id, "Analyst")))
    return cust, acct, alert, case


def create_draft_sar_filing(*, analyst_user_id="an-1"):
    """Through to a DRAFT SAR filing on a SAR_RECOMMENDED case.
    Returns (case, filing)."""
    cust, acct, alert, case = setup_sar_recommended_case(analyst_user_id=analyst_user_id)
    filing = get_success_data(api_client.create_filing(
        case["id"], {"filing_type": "SAR"}, make_headers(analyst_user_id, "Analyst")))
    return case, filing


def create_submitted_sar_filing(*, analyst_user_id="an-1", reviewer_user_id="qr-1"):
    """DRAFT SAR -> approve (by reviewer) -> submit. Returns (case, filing)."""
    case, filing = create_draft_sar_filing(analyst_user_id=analyst_user_id)
    rev = make_headers(reviewer_user_id, "QualityReviewer")
    get_success_data(api_client.approve_filing(filing["id"], rev))
    submitted = get_success_data(api_client.submit_filing(filing["id"], rev))
    return case, submitted


# --------------------------------------------------------------------------
# Lookback review
# --------------------------------------------------------------------------
def create_lookback_review(**overrides) -> dict:
    return get_success_data(api_client.create_lookback_review(
        create_lookback_review_payload(**overrides), CO))


def setup_in_progress_lookback(*, window_start="2026-06-01T00:00:00Z",
                               window_end="2026-06-08T00:00:00Z",
                               txn_posted_at="2026-06-05T12:00:00Z",
                               clock=None):
    """A LookbackReview enqueued to IN_PROGRESS with exactly one QUEUED item over
    one ACTIVE account that had an in-window transaction. Returns
    (customer, account, review, item)."""
    if clock:
        set_clock(clock)
    cust = create_legal_entity()
    acct = create_account(cust["id"], account_ref=_ref())
    post_transaction(acct["id"], direction="CASH_IN", amount_cents=5000,
                     posted_at=txn_posted_at, counterparty_country="US")
    review = create_lookback_review(window_start=window_start, window_end=window_end)
    review = get_success_data(api_client.enqueue_lookback_review(review["id"], CO))
    items, _ = _list(api_client.list_lookback_items(review["id"], AN))
    return cust, acct, review, items[0]


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------
_ref_counter = {"n": 0}


def _ref() -> str:
    """Unique account_ref within a single test run."""
    _ref_counter["n"] += 1
    return f"AC-FX-{_ref_counter['n']}"


def _list(response):
    """Return (data_list, meta) from a list endpoint response, lenient."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})
