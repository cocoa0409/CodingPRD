"""Composite setup helpers for CDI program test scenarios.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints — the server is restarted before each test, so each test starts
against an empty database. Setup calls use get_success_data() so failures
surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_cdi_program_payload,
    create_cdi_query_payload,
    create_cdi_review_payload,
    create_escalation_policy_payload,
    create_patient_case_payload,
    create_provider_payload,
    create_query_response_payload,
)
from .test_users import TEST_USERS, make_provider_headers

MANAGER = TEST_USERS["cdi_manager_headers"]
SPECIALIST = TEST_USERS["cdi_specialist_headers"]
CODER = TEST_USERS["him_coder_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]
SYSADMIN = TEST_USERS["system_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def create_program(**overrides):
    """Create a CDIProgram. Returns program dict."""
    return get_success_data(
        api_client.create_cdi_program(create_cdi_program_payload(**overrides), MANAGER)
    )


def create_policy(program_id, **overrides):
    """Create an EscalationPolicy under a program. Returns policy dict."""
    return get_success_data(
        api_client.create_escalation_policy(
            create_escalation_policy_payload(program_id, **overrides), MANAGER
        )
    )


def create_provider(program_id, **overrides):
    """Register a Provider under a program. Returns provider dict."""
    return get_success_data(
        api_client.create_provider(create_provider_payload(program_id, **overrides), MANAGER)
    )


def create_case(program_id, provider_id, **overrides):
    """Register a PatientCase. Returns case dict."""
    return get_success_data(
        api_client.create_patient_case(
            create_patient_case_payload(program_id, provider_id, **overrides), CODER
        )
    )


def advance_clock(program_id, by_periods):
    """Advance a program's logical clock. Returns updated program dict."""
    return get_success_data(api_client.advance_clock(program_id, by_periods, MANAGER))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — program + policy + provider (+ case)
# ---------------------------------------------------------------------------

def setup_program_with_policy(response_due_periods=1, escalation_stage_periods=1,
                              max_escalation_stage=1, **program_overrides):
    """Program + one default EscalationPolicy. Returns (program, policy)."""
    program = create_program(**program_overrides)
    policy = create_policy(
        program["id"],
        response_due_periods=response_due_periods,
        escalation_stage_periods=escalation_stage_periods,
        max_escalation_stage=max_escalation_stage,
        is_default=True,
    )
    return program, policy


def setup_program_policy_provider(response_due_periods=1, escalation_stage_periods=1,
                                  max_escalation_stage=1, **program_overrides):
    """Program + default policy + one provider. Returns (program, policy, provider)."""
    program, policy = setup_program_with_policy(
        response_due_periods=response_due_periods,
        escalation_stage_periods=escalation_stage_periods,
        max_escalation_stage=max_escalation_stage,
        **program_overrides,
    )
    provider = create_provider(program["id"])
    return program, policy, provider


def setup_basic_scenario(discharge_period=5, initial_drg_weight=1.0, initial_drg_code="DRG-A",
                         response_due_periods=1, escalation_stage_periods=1,
                         max_escalation_stage=1):
    """Program + policy + provider + one case. Returns dict of all four."""
    program, policy, provider = setup_program_policy_provider(
        response_due_periods=response_due_periods,
        escalation_stage_periods=escalation_stage_periods,
        max_escalation_stage=max_escalation_stage,
    )
    case = create_case(
        program["id"], provider["id"],
        discharge_period=discharge_period,
        initial_drg_code=initial_drg_code,
        initial_drg_weight=initial_drg_weight,
    )
    return {"program": program, "policy": policy, "provider": provider, "case": case}


# ---------------------------------------------------------------------------
# Tier 3: review / query lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_review(case_id):
    """Open a DRAFT review on a case. Returns review dict."""
    return get_success_data(
        api_client.create_cdi_review(create_cdi_review_payload(case_id), SPECIALIST)
    )


def activate_review(review_id):
    """Activate a DRAFT review. Returns updated review dict."""
    return get_success_data(api_client.activate_cdi_review(review_id, SPECIALIST))


def create_and_activate_review(case_id):
    """Create a review on the case and activate it. Returns ACTIVE review dict."""
    review = create_review(case_id)
    return activate_review(review["id"])


def create_query(review_id, provider_id, policy_id, **overrides):
    """Create a DRAFT query. Returns query dict."""
    return get_success_data(
        api_client.create_cdi_query(
            create_cdi_query_payload(review_id, provider_id, policy_id, **overrides), SPECIALIST
        )
    )


def send_query(query_id, expected_query_version):
    """Send a DRAFT query (OCC). Returns updated query dict."""
    return get_success_data(
        api_client.send_cdi_query(
            query_id, {"expected_query_version": expected_query_version}, SPECIALIST
        )
    )


def setup_sent_query(proposed_drg_weight=2.0, proposed_soi=2, proposed_rom=2,
                     proposed_drg_code="DRG-B", discharge_period=10,
                     initial_drg_weight=1.0, initial_drg_code="DRG-A",
                     response_due_periods=5, escalation_stage_periods=5,
                     max_escalation_stage=1, query_text=None, clinical_indicators=None):
    """Full chain: program + policy + provider + case + ACTIVE review + SENT query.

    Returns dict with program, policy, provider, case, review, query.
    """
    scenario = setup_basic_scenario(
        discharge_period=discharge_period,
        initial_drg_weight=initial_drg_weight,
        initial_drg_code=initial_drg_code,
        response_due_periods=response_due_periods,
        escalation_stage_periods=escalation_stage_periods,
        max_escalation_stage=max_escalation_stage,
    )
    review = create_and_activate_review(scenario["case"]["id"])
    query_overrides = {}
    if query_text is not None:
        query_overrides["query_text"] = query_text
    if clinical_indicators is not None:
        query_overrides["clinical_indicators"] = clinical_indicators
    query = create_query(
        review["id"], scenario["provider"]["id"], scenario["policy"]["id"],
        proposed_drg_weight=proposed_drg_weight,
        proposed_soi=proposed_soi,
        proposed_rom=proposed_rom,
        proposed_drg_code=proposed_drg_code,
        **query_overrides,
    )
    query = send_query(query["id"], query["version"])
    scenario["review"] = review
    scenario["query"] = query
    return scenario


def respond_to_query(query_id, provider_id, response_type="AGREE", response_text="ok"):
    """Record a provider response. The responder identity IS the Provider.id."""
    headers = make_provider_headers(provider_id)
    return get_success_data(
        api_client.create_query_response(
            query_id,
            create_query_response_payload(response_type=response_type, response_text=response_text),
            headers,
        )
    )


def setup_agreed_case(proposed_drg_weight=2.0, proposed_soi=2, proposed_rom=2,
                      proposed_drg_code="DRG-B", discharge_period=10,
                      initial_drg_weight=1.0, initial_drg_code="DRG-A",
                      response_due_periods=10, escalation_stage_periods=10,
                      max_escalation_stage=1):
    """Sent query + AGREE response. Case working_* now equals the proposal.

    Returns scenario dict including the QueryResponse under 'response'.
    """
    scenario = setup_sent_query(
        proposed_drg_weight=proposed_drg_weight,
        proposed_soi=proposed_soi,
        proposed_rom=proposed_rom,
        proposed_drg_code=proposed_drg_code,
        discharge_period=discharge_period,
        initial_drg_weight=initial_drg_weight,
        initial_drg_code=initial_drg_code,
        response_due_periods=response_due_periods,
        escalation_stage_periods=escalation_stage_periods,
        max_escalation_stage=max_escalation_stage,
    )
    response = respond_to_query(
        scenario["query"]["id"], scenario["provider"]["id"], response_type="AGREE"
    )
    scenario["response"] = response
    return scenario


def close_review(review_id, closed_reason="OPPORTUNITY_CAPTURED"):
    """Close a review with a fresh OCC token. Returns updated review dict."""
    current = get_success_data(api_client.get_cdi_review(review_id, SPECIALIST))
    return get_success_data(
        api_client.close_cdi_review(
            review_id,
            {"closed_reason": closed_reason, "expected_review_version": current["version"]},
            SPECIALIST,
        )
    )


def get_case(case_id):
    return get_success_data(api_client.get_patient_case(case_id, CODER))


def finalize_case(case_id, coder_drg_code=None, coder_drg_weight=None):
    """Finalize a case's coding with a fresh OCC token. Defaults coder DRG to
    the case's current working values (match path). Returns updated case dict."""
    current = get_case(case_id)
    payload = {
        "coder_drg_code": coder_drg_code if coder_drg_code is not None else current["working_drg_code"],
        "coder_drg_weight": coder_drg_weight if coder_drg_weight is not None else current["working_drg_weight"],
        "expected_case_version": current["version"],
    }
    return get_success_data(api_client.finalize_coding(case_id, payload, CODER))


def setup_finalized_case(discharge_period=1, initial_drg_weight=1.0, initial_drg_code="DRG-A",
                         advance_to=None):
    """Program + provider + case, clock advanced past discharge, case FINAL_CODED
    (coder DRG matches working DRG). Returns scenario dict."""
    program = create_program()
    provider = create_provider(program["id"])
    case = create_case(
        program["id"], provider["id"],
        discharge_period=discharge_period,
        initial_drg_code=initial_drg_code,
        initial_drg_weight=initial_drg_weight,
    )
    if advance_to is None:
        advance_to = discharge_period
    if advance_to > 0:
        advance_clock(program["id"], advance_to)
    case = finalize_case(case["id"])
    return {"program": program, "provider": provider, "case": case}


# ---------------------------------------------------------------------------
# Tier 4: threshold / accumulation targeting
# ---------------------------------------------------------------------------

def drive_education_score(provider_id, source_query_id, points_to_deduct,
                          pattern_tag="LEADING_LANGUAGE"):
    """Record manual education events totalling points_to_deduct against a
    provider. Splits into events of at most 25 points (the per-event maximum)."""
    remaining = points_to_deduct
    while remaining > 0:
        chunk = min(remaining, 25)
        get_success_data(
            api_client.create_provider_education_event(
                {
                    "provider_id": provider_id,
                    "pattern_tag": pattern_tag,
                    "points_deducted": chunk,
                    "source_query_id": source_query_id,
                    "note": f"manual deduction {chunk}",
                },
                MANAGER,
            )
        )
        remaining -= chunk
    return get_success_data(api_client.get_provider(provider_id, MANAGER))


# ---------------------------------------------------------------------------
# Tier 5: reconciliation scenarios
# ---------------------------------------------------------------------------

def setup_mismatched_finalize(proposed_drg_code="DRG-B", proposed_drg_weight=2.0,
                              coder_drg_code="DRG-A", coder_drg_weight=1.0,
                              discharge_period=1, initial_drg_weight=1.0,
                              initial_drg_code="DRG-A"):
    """AGREE-moved case, review closed, clock past discharge, then finalize with a
    coder DRG that mismatches the working DRG -> ERR_DRG_MISMATCH response plus an
    OPEN ReconciliationEvent. Returns scenario dict with 'mismatch_error' (raw
    response) and 'reconciliation' (the created event)."""
    scenario = setup_agreed_case(
        proposed_drg_weight=proposed_drg_weight,
        proposed_drg_code=proposed_drg_code,
        discharge_period=discharge_period,
        initial_drg_weight=initial_drg_weight,
        initial_drg_code=initial_drg_code,
    )
    close_review(scenario["review"]["id"])
    advance_clock(scenario["program"]["id"], discharge_period + 1)
    current = get_case(scenario["case"]["id"])
    mismatch_response = api_client.finalize_coding(
        scenario["case"]["id"],
        {
            "coder_drg_code": coder_drg_code,
            "coder_drg_weight": coder_drg_weight,
            "expected_case_version": current["version"],
        },
        CODER,
    )
    scenario["mismatch_error"] = mismatch_response
    events, _meta = None, None
    from prd_bench_local_runner.testing import validate_paginated
    events, _meta = validate_paginated(
        api_client.list_case_reconciliations(scenario["case"]["id"], MANAGER)
    )
    scenario["reconciliation"] = events[0] if events else None
    return scenario
