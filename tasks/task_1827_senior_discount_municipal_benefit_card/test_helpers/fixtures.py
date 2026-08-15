"""Composite setup helpers for multi-step test prerequisites.

The interesting claims in this program require the system to be in a state that
takes 5-20 API calls to reach (an approved application, a live card, a merchant
with an offer, a history of purchases, a filed claim). These helpers encapsulate
those chains so tests can focus on assertions. All helpers use the lenient
get_success_data() validator so setup failures surface as clear
"Setup step failed" errors.

Identity threading: Cardholder and MerchantOperator are entity-backed roles
(PRD §2.1), so ownership-gated calls always use make_cardholder_headers /
make_merchant_operator_headers with the real entity id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK, TEST_DEFAULTS
from .factories import (
    create_application_payload,
    create_document_payload,
    create_merchant_payload,
    create_offer_payload,
    create_program_fund_payload,
    create_usage_transaction_payload,
)
from .test_users import (
    TEST_USERS,
    make_cardholder_headers,
    make_merchant_operator_headers,
)

# Shared opaque-identity headers. The ProgramAdministrator (admin-1) who
# approves is always a different user id from the EligibilitySpecialist
# (spec-1) who reviews, so segregation of duties holds by construction.
ADMIN_HEADERS = TEST_USERS["program_administrator_headers"]     # X-User-ID: admin-1
SPEC_HEADERS = TEST_USERS["eligibility_specialist_headers"]     # X-User-ID: spec-1
FRAUD1_HEADERS = TEST_USERS["fraud_analyst_headers"]            # X-User-ID: fraud-1
APPLICANT_HEADERS = TEST_USERS["applicant_headers"]

DOCUMENT_TYPES = ("PROOF_OF_AGE", "PROOF_OF_INCOME", "PROOF_OF_RESIDENCY")
DOCUMENT_REFS = {"PROOF_OF_AGE": "DOC-AGE", "PROOF_OF_INCOME": "DOC-INC",
                 "PROOF_OF_RESIDENCY": "DOC-RES"}


# ─── Clock ─────────────────────────────────────────────

def set_clock(to_iso8601=DEFAULT_CLOCK):
    """Pin the logical clock (PRD §2.4). Returns the clock payload."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN_HEADERS))


# ─── Applications and documents ────────────────────────

def submit_initial_application(full_name="Test Senior",
                               date_of_birth=TEST_DEFAULTS["DATE_OF_BIRTH"],
                               annual_income_cents=TEST_DEFAULTS["ANNUAL_INCOME_CENTS"],
                               residency_address=TEST_DEFAULTS["RESIDENCY_ADDRESS"],
                               applicant_headers=None):
    """Submit an INITIAL application as an Applicant. Returns the application."""
    return get_success_data(api_client.create_application(
        create_application_payload(
            kind="INITIAL", applicant_full_name=full_name,
            date_of_birth=date_of_birth, annual_income_cents=annual_income_cents,
            residency_address=residency_address),
        applicant_headers or APPLICANT_HEADERS))


def start_review(application_id, specialist_headers=None):
    return get_success_data(
        api_client.start_review(application_id, specialist_headers or SPEC_HEADERS))


def upload_document(application_id, document_type, reference=None,
                    uploader_headers=None):
    return get_success_data(api_client.add_document(
        application_id,
        create_document_payload(document_type, reference or DOCUMENT_REFS[document_type]),
        uploader_headers or APPLICANT_HEADERS))


def verify_document(application_id, document_id, specialist_headers=None):
    return get_success_data(api_client.review_document(
        application_id, document_id, "VERIFIED", specialist_headers or SPEC_HEADERS))


def upload_and_verify_document(application_id, document_type, reference=None,
                               uploader_headers=None, specialist_headers=None):
    doc = upload_document(application_id, document_type, reference, uploader_headers)
    verify_document(application_id, doc["id"], specialist_headers)
    return doc


def onboard_cardholder(full_name="Test Senior",
                       date_of_birth=TEST_DEFAULTS["DATE_OF_BIRTH"],
                       annual_income_cents=TEST_DEFAULTS["ANNUAL_INCOME_CENTS"],
                       residency_address=TEST_DEFAULTS["RESIDENCY_ADDRESS"],
                       specialist_headers=None, admin_headers=None,
                       applicant_headers=None):
    """Full INITIAL enrollment: submit -> start-review -> three verified
    documents -> approve. Returns dict(application, cardholder, card)."""
    spec_h = specialist_headers or SPEC_HEADERS
    admin_h = admin_headers or ADMIN_HEADERS
    app_h = applicant_headers or APPLICANT_HEADERS
    app = submit_initial_application(full_name, date_of_birth,
                                     annual_income_cents, residency_address, app_h)
    start_review(app["id"], spec_h)
    for doc_type in DOCUMENT_TYPES:
        upload_and_verify_document(app["id"], doc_type, uploader_headers=app_h,
                                   specialist_headers=spec_h)
    approved = get_success_data(api_client.approve_application(app["id"], admin_h))
    cardholder_id = approved["cardholder_id"]
    cardholder = get_success_data(api_client.get_cardholder(cardholder_id, admin_h))
    cards = get_success_data(api_client.list_cards(cardholder_id, admin_h))
    return {"application": approved, "cardholder": cardholder, "card": cards[0]}


def submit_and_approve_recertification(cardholder_id,
                                       annual_income_cents=1500000,
                                       full_name="Test Senior",
                                       date_of_birth=TEST_DEFAULTS["DATE_OF_BIRTH"],
                                       residency_address=TEST_DEFAULTS["RESIDENCY_ADDRESS"],
                                       specialist_headers=None, admin_headers=None):
    """File a RECERTIFICATION application as the cardholder and drive it to
    APPROVED. Returns the approved application."""
    spec_h = specialist_headers or SPEC_HEADERS
    admin_h = admin_headers or ADMIN_HEADERS
    ch_h = make_cardholder_headers(cardholder_id)
    app = get_success_data(api_client.create_application(
        create_application_payload(
            kind="RECERTIFICATION", applicant_full_name=full_name,
            date_of_birth=date_of_birth, annual_income_cents=annual_income_cents,
            residency_address=residency_address, cardholder_id=cardholder_id),
        ch_h))
    start_review(app["id"], spec_h)
    for doc_type in DOCUMENT_TYPES:
        upload_and_verify_document(app["id"], doc_type, reference="RC-" + doc_type,
                                   uploader_headers=ch_h, specialist_headers=spec_h)
    return get_success_data(api_client.approve_application(app["id"], admin_h))


def read_cardholder(cardholder_id, headers=None):
    return get_success_data(
        api_client.get_cardholder(cardholder_id, headers or ADMIN_HEADERS))


def read_cards(cardholder_id, headers=None):
    return get_success_data(
        api_client.list_cards(cardholder_id, headers or ADMIN_HEADERS))


# ─── Merchants and offers ──────────────────────────────

def create_merchant(name="Test Merchant",
                    reimbursement_rate_pct=TEST_DEFAULTS["MERCHANT_RATE_PCT"],
                    monthly_reimbursement_cap_cents=TEST_DEFAULTS["MERCHANT_MONTHLY_CAP_CENTS"]):
    return get_success_data(api_client.create_merchant(
        create_merchant_payload(name, reimbursement_rate_pct,
                                monthly_reimbursement_cap_cents),
        ADMIN_HEADERS))


def create_offer(merchant_id, category="GROCERY",
                 discount_pct=TEST_DEFAULTS["OFFER_DISCOUNT_PCT"],
                 max_discount_cents=TEST_DEFAULTS["OFFER_MAX_DISCOUNT_CENTS"],
                 valid_from=TEST_DEFAULTS["OFFER_VALID_FROM"],
                 valid_until=TEST_DEFAULTS["OFFER_VALID_UNTIL"]):
    return get_success_data(api_client.create_offer(
        merchant_id,
        create_offer_payload(category, discount_pct, max_discount_cents,
                             valid_from, valid_until),
        make_merchant_operator_headers(merchant_id)))


def setup_merchant_with_offer(merchant_overrides=None, offer_overrides=None):
    """Enroll a merchant and publish one offer. Returns (merchant, offer)."""
    merchant = create_merchant(**(merchant_overrides or {}))
    offer = create_offer(merchant["id"], **(offer_overrides or {}))
    return merchant, offer


# ─── Usage transactions and fraud ──────────────────────

def post_transactions(card_id, merchant_id, count=1, purchase_amount_cents=100,
                      category="GROCERY"):
    """Post N purchases at the current clock. Returns the created transactions."""
    headers = make_merchant_operator_headers(merchant_id)
    transactions = []
    for _ in range(count):
        transactions.append(get_success_data(api_client.create_usage_transaction(
            create_usage_transaction_payload(card_id, merchant_id, category,
                                             purchase_amount_cents),
            headers)))
    return transactions


def flag_transactions(transaction_ids, analyst_headers=None, reason="fraud pattern"):
    headers = analyst_headers or FRAUD1_HEADERS
    return [get_success_data(api_client.flag_transaction(tid, reason, headers))
            for tid in transaction_ids]


def setup_posted_transactions(count, purchase_amount_cents=100,
                              clock="2026-08-10T10:00:00Z",
                              cardholder_overrides=None, merchant_overrides=None,
                              offer_overrides=None):
    """Onboard a cardholder, enroll a merchant with one offer, optionally pin the
    clock, then post N purchases. Returns the scenario dict."""
    onboard = onboard_cardholder(**(cardholder_overrides or {}))
    merchant, offer = setup_merchant_with_offer(merchant_overrides, offer_overrides)
    if clock is not None:
        set_clock(clock)
    transactions = post_transactions(onboard["card"]["id"], merchant["id"], count,
                                     purchase_amount_cents)
    return {"cardholder": onboard["cardholder"], "card": onboard["card"],
            "merchant": merchant, "offer": offer, "transactions": transactions}


def setup_suspended_cardholder():
    """Onboard + three posted transactions + three manual flags by fraud-1.

    Ends with the cardholder SUSPENDED (pre_suspension_status ACTIVE),
    the card SUSPENDED, and fraud_flag_count == 3 (PRD §3.7 threshold cascade).
    """
    scenario = setup_posted_transactions(3, 100)
    flag_transactions([t["id"] for t in scenario["transactions"]],
                      reason="fraud pattern")
    scenario["cardholder"] = read_cardholder(scenario["cardholder"]["id"])
    return scenario


# ─── Funds and reimbursement claims ────────────────────

def create_program_fund(fiscal_year=TEST_DEFAULTS["FUND_FISCAL_YEAR"],
                        allocated_cents=TEST_DEFAULTS["FUND_ALLOCATED_CENTS"]):
    return get_success_data(api_client.create_program_fund(
        create_program_fund_payload(fiscal_year, allocated_cents), ADMIN_HEADERS))


def file_claim(merchant_id, period_month):
    """File a reimbursement claim as the merchant's own operator."""
    return get_success_data(api_client.create_reimbursement_claim(
        merchant_id, period_month, make_merchant_operator_headers(merchant_id)))


def list_claims(merchant_id, params=None):
    return get_success_data(api_client.list_reimbursement_claims(
        merchant_id, make_merchant_operator_headers(merchant_id), params=params))


def setup_submitted_claim(purchase_amount_cents=1000, transaction_count=1,
                          period_month="2026-08",
                          transaction_clock="2026-08-05T10:00:00Z",
                          claim_clock="2026-09-01T00:00:00Z",
                          merchant_overrides=None, offer_overrides=None,
                          fund_allocated_cents=None):
    """Onboard + merchant/offer (+ optional fund) + transactions in one month +
    clock into the next month + a filed claim for the period.

    Returns dict(cardholder, card, merchant, offer, fund, transactions, claim).
    """
    onboard = onboard_cardholder()
    merchant, offer = setup_merchant_with_offer(merchant_overrides, offer_overrides)
    fund = (create_program_fund(allocated_cents=fund_allocated_cents)
            if fund_allocated_cents is not None else None)
    set_clock(transaction_clock)
    transactions = post_transactions(onboard["card"]["id"], merchant["id"],
                                     transaction_count, purchase_amount_cents)
    set_clock(claim_clock)
    claim = file_claim(merchant["id"], period_month)
    return {"cardholder": onboard["cardholder"], "card": onboard["card"],
            "merchant": merchant, "offer": offer, "fund": fund,
            "transactions": transactions, "claim": claim}
