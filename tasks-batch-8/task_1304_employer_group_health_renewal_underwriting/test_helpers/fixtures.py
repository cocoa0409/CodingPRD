"""Composite setup helpers.

Each fixture builds preconditions from scratch via PRD-declared endpoints —
the test harness restarts the server before every test, so nothing carries over.

Common economics used throughout:
  group 500 / enrolled 400 / claims 24 months, total_paid 38400000,
  enrollment_months 9600, no large claims
    -> experience_rate_cents 5338, credibility_factor 1.0
  current_premium_annual 24000000 (current PEPM 5000, 15% cap ceiling 5750)
    -> blended 5338 uncapped; annual premium on reference plan 25622400
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_broker_payload,
    create_case_payload,
    create_census_payload,
    create_claims_payload,
    create_plan_design_payload,
    create_quote_payload,
    create_counter_payload,
    create_respond_payload,
    create_stop_loss_payload,
    create_enrollment_change_payload,
)
from .test_users import (
    TEST_USERS,
    make_broker_headers,
    make_underwriter_headers,
    make_senior_underwriter_headers,
)

UW = TEST_USERS["underwriter_headers"]
SU = TEST_USERS["senior_underwriter_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation and early case states
# ---------------------------------------------------------------------------

def create_broker(**overrides):
    """Register a broker; returns the broker dict (status ACTIVE)."""
    resp = api_client.create_broker(create_broker_payload(**overrides), UW)
    return get_success_data(resp)


def create_case(broker_id, **overrides):
    """Create an underwriting case (INTAKE). Returns the case dict."""
    resp = api_client.create_case(create_case_payload(broker_id, **overrides), UW)
    return get_success_data(resp)


def create_case_in_census_pending(broker_id, **overrides):
    """Case walked INTAKE -> CENSUS_PENDING."""
    case = create_case(broker_id, **overrides)
    resp = api_client.submit_for_census(case["id"], UW)
    return get_success_data(resp)


def create_case_in_census_received(broker_id, census_overrides=None, **case_overrides):
    """Case walked to CENSUS_RECEIVED via a validated census snapshot.

    Returns (case, census).
    """
    case = create_case_in_census_pending(broker_id, **case_overrides)
    c_over = dict(census_overrides or {})
    if "total_employees" not in c_over:
        c_over["total_employees"] = case["group_size"]
    resp = api_client.create_census_snapshot(
        case["id"], create_census_payload(**c_over), UW
    )
    census = get_success_data(resp)
    resp = api_client.validate_census(census["id"], UW)
    census = get_success_data(resp)
    case = get_success_data(api_client.get_case(case["id"], UW))
    return case, census


def create_case_in_claims_pending(broker_id, **kwargs):
    """Case walked to CLAIMS_PENDING. Returns (case, census)."""
    case, census = create_case_in_census_received(broker_id, **kwargs)
    resp = api_client.request_claims(case["id"], UW)
    case = get_success_data(resp)
    return case, census


# ---------------------------------------------------------------------------
# Tier 2: claims pipeline
# ---------------------------------------------------------------------------

def add_claims_record(case_id, **overrides):
    """Create a claims experience record (PENDING) on the case."""
    resp = api_client.create_claims_experience(
        case_id, create_claims_payload(**overrides), UW
    )
    return get_success_data(resp)


def submit_claims_record(claims_id, submitter_headers=None):
    """PENDING -> SUBMITTED as the given underwriter (defaults to uw-001)."""
    hdrs = submitter_headers or make_underwriter_headers("uw-001")
    resp = api_client.submit_claims(claims_id, hdrs)
    return get_success_data(resp)


def review_claims_record(claims_id, reviewer_headers=None):
    """SUBMITTED -> REVIEWED as a senior underwriter other than the submitter."""
    hdrs = reviewer_headers or make_senior_underwriter_headers("su-001")
    resp = api_client.review_claims(claims_id, hdrs)
    return get_success_data(resp)


def create_case_in_rating(broker_id, claims_overrides=None, **case_overrides):
    """Case walked to RATING_IN_PROGRESS via a reviewed 24-month claims record.

    Returns (case, claims).
    """
    case, _census = create_case_in_claims_pending(broker_id, **case_overrides)
    claims = add_claims_record(case["id"], **(claims_overrides or {}))
    submit_claims_record(claims["id"])
    review_claims_record(claims["id"])
    case = get_success_data(api_client.get_case(case["id"], UW))
    return case, claims


# ---------------------------------------------------------------------------
# Tier 3: plan designs and quotes
# ---------------------------------------------------------------------------

def add_modeled_plan(case_id, **overrides):
    """Create a plan design and model it (DRAFT -> MODELED)."""
    resp = api_client.create_plan_design(
        case_id, create_plan_design_payload(**overrides), UW
    )
    plan = get_success_data(resp)
    resp = api_client.model_plan(plan["id"], UW)
    return get_success_data(resp)


def create_draft_quote(case_id, plan_id, **overrides):
    """Create a quote (DRAFT) with a fresh expected_case_version."""
    case = get_success_data(api_client.get_case(case_id, UW))
    payload = create_quote_payload(
        plan_id, expected_case_version=case["version"], **overrides
    )
    resp = api_client.create_quote(case_id, payload, UW)
    return get_success_data(resp)


def create_proposed_quote(case_id, plan_id, **overrides):
    """Create a quote and propose it (DRAFT -> PROPOSED)."""
    quote = create_draft_quote(case_id, plan_id, **overrides)
    resp = api_client.propose_quote(quote["id"], UW)
    return get_success_data(resp)


def setup_case_with_proposed_quote(quote_funding_type="FULLY_INSURED",
                                   case_funding_type="FULLY_INSURED",
                                   **case_overrides):
    """Full pipeline to case QUOTED with one PROPOSED quote on a MODELED
    reference plan. Returns (broker, case, plan, quote)."""
    broker = create_broker()
    case, _claims = create_case_in_rating(
        broker["id"], funding_type=case_funding_type, **case_overrides
    )
    plan = add_modeled_plan(case["id"])
    quote = create_proposed_quote(
        case["id"], plan["id"], funding_type=quote_funding_type
    )
    case = get_success_data(api_client.get_case(case["id"], UW))
    return broker, case, plan, quote


def setup_case_with_countered_quote(**case_overrides):
    """Case NEGOTIATING with the quote COUNTERED after one broker counter.
    Returns (broker, case, plan, quote, round)."""
    broker, case, plan, quote = setup_case_with_proposed_quote(**case_overrides)
    broker_headers = make_broker_headers(broker["id"])
    resp = api_client.counter_quote(
        quote["id"], create_counter_payload(), broker_headers
    )
    quote = get_success_data(resp)
    rounds = get_success_data(api_client.list_negotiation_rounds(quote["id"], UW))
    round_row = rounds[0]
    case = get_success_data(api_client.get_case(case["id"], UW))
    return broker, case, plan, quote, round_row


# ---------------------------------------------------------------------------
# Tier 5: acceptance / terminal states
# ---------------------------------------------------------------------------

def setup_approved_case(commission_pct=0.04, funding_type="FULLY_INSURED",
                        **case_overrides):
    """Full pipeline through broker acceptance: case APPROVED, quote ACCEPTED,
    plan SELECTED, one CommissionDisclosure minted.

    Returns (broker, case, plan, quote, disclosure).
    """
    broker = create_broker(commission_pct=commission_pct)
    case, _claims = create_case_in_rating(broker["id"], **case_overrides)
    plan = add_modeled_plan(case["id"])
    quote = create_proposed_quote(case["id"], plan["id"], funding_type=funding_type)
    broker_headers = make_broker_headers(broker["id"])
    resp = api_client.accept_quote(quote["id"], broker_headers)
    quote = get_success_data(resp)
    case = get_success_data(api_client.get_case(case["id"], UW))
    disclosures = get_success_data(
        api_client.list_commission_disclosures(case["id"], UW)
    )
    disclosure = disclosures[0]
    return broker, case, plan, quote, disclosure


def add_enrollment_event(case_id, quote_id, headers=None, **overrides):
    """Report an enrollment change event (REPORTED)."""
    resp = api_client.create_enrollment_change(
        case_id, create_enrollment_change_payload(quote_id, **overrides),
        headers or UW,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Stop-loss helpers
# ---------------------------------------------------------------------------

def add_stop_loss_quote(quote_id, **overrides):
    """Create a stop-loss quote (DRAFT) under a quote."""
    resp = api_client.create_stop_loss_quote(
        quote_id, create_stop_loss_payload(**overrides), UW
    )
    return get_success_data(resp)


def setup_level_funded_case_with_quote(**case_overrides):
    """Level-funded case walked to QUOTED with one LEVEL_FUNDED PROPOSED quote
    on a MODELED reference plan. Returns (broker, case, plan, quote)."""
    broker = create_broker()
    case, _claims = create_case_in_rating(
        broker["id"], funding_type="LEVEL_FUNDED", **case_overrides
    )
    plan = add_modeled_plan(case["id"])
    quote = create_proposed_quote(case["id"], plan["id"], funding_type="LEVEL_FUNDED")
    case = get_success_data(api_client.get_case(case["id"], UW))
    return broker, case, plan, quote


def setup_level_funded_quote_with_stop_loss(quote_overrides=None, **slq_overrides):
    """Case QUOTED with a LEVEL_FUNDED PROPOSED quote and a stop-loss already
    QUOTED. Returns (broker, case, plan, quote, slq)."""
    broker, case, plan, quote = setup_level_funded_case_with_quote()
    slq = add_stop_loss_quote(quote["id"], **slq_overrides)
    resp = api_client.quote_stop_loss(slq["id"], UW)
    slq = get_success_data(resp)
    return broker, case, plan, quote, slq
