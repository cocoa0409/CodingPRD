"""Composite setup helpers.

These encapsulate the multi-step preambles that most tests share (create +
open a program, register + verify a consumer, file + document + submit a claim,
push it to UNDER_REVIEW, approve it and produce a payout). Because the test
harness restarts the server before every test, each helper builds all of its
preconditions from scratch using only PRD-declared endpoints.

All helpers use the lenient get_success_data() so a setup failure surfaces as a
clear "Setup failed" rather than a confusing downstream assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_program_payload, create_consumer_payload, create_claim_payload,
    create_document_payload, unique_email,
)
from .test_users import (
    TEST_USERS, make_consumer_headers, make_reviewer_headers,
    REVIEWER_USER_ID,
)
from .constants import CLOCK_IN_WINDOW, BENEFIT_START, BENEFIT_END

PM = TEST_USERS["program_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
REVIEWER = TEST_USERS["claim_reviewer_headers"]
ANON = TEST_USERS["anonymous_headers"]


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(api=api_client, to_iso8601=CLOCK_IN_WINDOW):
    """Move the logical clock (PlatformAdmin only)."""
    return get_success_data(api.set_clock(to_iso8601, ADMIN))


# --------------------------------------------------------------------------
# Programs
# --------------------------------------------------------------------------
def create_program(api=api_client, **overrides) -> dict:
    """Create a DRAFT program."""
    payload = create_program_payload(**overrides)
    return get_success_data(api.create_program(payload, PM))


def open_program(api=api_client, program_id=None) -> dict:
    return get_success_data(api.open_program(program_id, PM))


def create_open_program(api=api_client, **overrides) -> dict:
    """Create a program then open it. Returns the OPEN program (version fresh)."""
    prog = create_program(api, **overrides)
    return open_program(api, prog["id"])


def program_version(api=api_client, program_id=None) -> int:
    return get_success_data(api.get_program(program_id, PM))["version"]


# --------------------------------------------------------------------------
# Consumers
# --------------------------------------------------------------------------
def register_consumer(api=api_client, email=None, full_name="Test Consumer") -> dict:
    payload = create_consumer_payload(email=email or unique_email(), full_name=full_name)
    return get_success_data(api.create_consumer(payload, ANON))


def verify_consumer(api=api_client, consumer_id=None) -> dict:
    return get_success_data(api.verify_consumer(consumer_id, ADMIN))


def register_verified_consumer(api=api_client, email=None, full_name="Test Consumer") -> dict:
    c = register_consumer(api, email=email, full_name=full_name)
    verify_consumer(api, c["id"])
    # Return the refreshed consumer (VERIFIED, scores recomputed).
    return get_success_data(api.get_consumer(c["id"], ADMIN))


# --------------------------------------------------------------------------
# Claims / documents
# --------------------------------------------------------------------------
def create_claim(api=api_client, consumer=None, program_id=None,
                 claimed_amount_cents=25000,
                 benefit_period_start=BENEFIT_START,
                 benefit_period_end=BENEFIT_END,
                 match_id=None) -> dict:
    """File a DRAFT claim as its owning consumer (ownership-gated call)."""
    headers = make_consumer_headers(consumer["id"])
    extra = {}
    if match_id is not None:
        extra["match_id"] = match_id
    payload = create_claim_payload(
        consumer["id"], program_id,
        claimed_amount_cents=claimed_amount_cents,
        benefit_period_start=benefit_period_start,
        benefit_period_end=benefit_period_end,
        **extra,
    )
    return get_success_data(api.create_claim(payload, headers))


def add_document(api=api_client, claim=None, consumer=None,
                 doc_type="RECEIPT", file_ref="receipt-ref") -> dict:
    headers = make_consumer_headers(consumer["id"])
    payload = create_document_payload(doc_type=doc_type, file_ref=file_ref)
    return get_success_data(api.upload_document(claim["id"], payload, headers))


def submit_claim(api=api_client, claim=None, consumer=None) -> dict:
    headers = make_consumer_headers(consumer["id"])
    return get_success_data(api.submit_claim(claim["id"], headers))


def verify_document(api=api_client, document_id=None) -> dict:
    return get_success_data(api.verify_document(document_id, REVIEWER))


def start_review(api=api_client, claim_id=None) -> dict:
    return get_success_data(api.start_review(claim_id, REVIEWER))


def approve_claim(api=api_client, claim_id=None, program_id=None,
                  expected_program_version=None) -> dict:
    """Approve as ClaimReviewer, fetching the live program version if not given."""
    if expected_program_version is None:
        expected_program_version = program_version(api, program_id)
    return get_success_data(
        api.approve_claim(claim_id, expected_program_version, REVIEWER))


def get_claim(api=api_client, claim_id=None, headers=None) -> dict:
    return get_success_data(api.get_claim(claim_id, headers or ADMIN))


def first_payout(api=api_client, claim_id=None) -> dict:
    data = get_success_data(api.list_payouts(claim_id, ADMIN))
    assert data, f"expected a payout on claim {claim_id}"
    return data[0]


# --------------------------------------------------------------------------
# Composite scenarios
# --------------------------------------------------------------------------
def setup_claim_under_review(api=api_client, program_overrides=None,
                             claimed_amount_cents=25000,
                             verify_doc=True,
                             consumer_verified=True,
                             benefit_period_start=BENEFIT_START,
                             benefit_period_end=BENEFIT_END,
                             set_clock_first=True) -> dict:
    """Build one claim in UNDER_REVIEW.

    Steps: clock -> create+open program -> register (verified) consumer ->
    file claim -> upload document -> submit -> (verify document) -> start-review.

    Returns dict(program, program_version, consumer, claim, document).
    program_version is the program's version captured just after open (before
    any approval), suitable as expected_program_version for a first approval.
    """
    if set_clock_first:
        set_clock(api)
    program = create_open_program(api, **(program_overrides or {}))
    pver = program["version"]
    if consumer_verified:
        consumer = register_verified_consumer(api)
    else:
        consumer = register_consumer(api)
    claim = create_claim(api, consumer, program["id"],
                         claimed_amount_cents=claimed_amount_cents,
                         benefit_period_start=benefit_period_start,
                         benefit_period_end=benefit_period_end)
    document = add_document(api, claim, consumer)
    submit_claim(api, claim, consumer)
    if verify_doc:
        verify_document(api, document["id"])
    start_review(api, claim["id"])
    claim = get_claim(api, claim["id"])
    return {
        "program": program,
        "program_version": pver,
        "consumer": consumer,
        "claim": claim,
        "document": document,
    }


def setup_approved_fixed_claim(api=api_client, program_overrides=None,
                               claimed_amount_cents=25000) -> dict:
    """A FIXED claim carried through APPROVED with its Payout in INITIATED.

    Returns dict(program, consumer, claim, payout).
    """
    ctx = setup_claim_under_review(
        api, program_overrides=program_overrides,
        claimed_amount_cents=claimed_amount_cents)
    approve_claim(api, ctx["claim"]["id"], ctx["program"]["id"],
                  ctx["program_version"])
    claim = get_claim(api, ctx["claim"]["id"])
    payout = first_payout(api, claim["id"])
    return {
        "program": ctx["program"],
        "consumer": ctx["consumer"],
        "claim": claim,
        "payout": payout,
    }


def setup_cleared_payout(api=api_client, program_overrides=None) -> dict:
    """A FIXED claim approved and its Payout CLEARED.

    Returns dict(program, consumer, claim, payout).
    """
    ctx = setup_approved_fixed_claim(api, program_overrides=program_overrides)
    get_success_data(api.clear_payout(ctx["payout"]["id"], ADMIN))
    payout = first_payout(api, ctx["claim"]["id"])
    return {
        "program": ctx["program"],
        "consumer": ctx["consumer"],
        "claim": ctx["claim"],
        "payout": payout,
    }


def setup_claim_with_open_flag(api=api_client, reason="SUSPICIOUS_DOCS",
                               consumer_verified=True) -> dict:
    """A DRAFT claim carrying one OPEN fraud flag raised by fraud-1.

    Returns dict(program, consumer, claim, flag).
    """
    set_clock(api)
    program = create_open_program(api)
    consumer = (register_verified_consumer(api) if consumer_verified
                else register_consumer(api))
    claim = create_claim(api, consumer, program["id"], claimed_amount_cents=25000)
    flag = get_success_data(api.raise_fraud_flag(
        claim["id"], {"reason": reason}, TEST_USERS["fraud_analyst_1_headers"]))
    return {"program": program, "consumer": consumer, "claim": claim, "flag": flag}
