"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. All setup calls use the lenient validator so a
failed precondition surfaces as a clear "Setup step failed" error.

All roles are opaque-identified (PRD §2.1), so the shared header constants are
canonical; no per-entity identity threading is required.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .constants import TS
from .factories import (
    create_appeal_payload,
    create_charge_statement_payload,
    create_claim_payload,
    create_determination_payload,
    create_employer_payload,
    create_evidence_payload,
    create_hearing_payload,
    create_model_payload,
    create_response_payload,
    create_separation_payload,
    create_state_rule_payload,
    create_tpa_engagement_payload,
    create_witness_payload,
    post_line_item_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["claims_analyst_headers"]
TPA_AGENT = TEST_USERS["tpa_agent_headers"]
LIAISON = TEST_USERS["agency_liaison_headers"]
AUDITOR = TEST_USERS["charge_auditor_headers"]
RATER = TEST_USERS["rating_analyst_headers"]
TPA_MANAGER = TEST_USERS["tpa_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def set_clock(iso=TS["CLOCK_START"]):
    """Advance the logical clock (PRD §2.5). Returns the reported current_utc."""
    return get_success_data(api_client.set_clock(iso, ADMIN))


def create_state_rule(state_code="XX", response_window_days=10,
                      window_basis="CALENDAR", appeal_window_days=30,
                      protest_window_days=30, weekend_shift="NONE"):
    payload = create_state_rule_payload(
        state_code, response_window_days, window_basis,
        appeal_window_days, protest_window_days, weekend_shift)
    return get_success_data(api_client.create_state_rule(payload, ADMIN))


def create_employer(legal_name="Acme Widgets", merit_rating_method="RESERVE_RATIO",
                    taxable_payroll_cents=1_000_000_000,
                    reserve_balance_cents=None, fein=None):
    payload = create_employer_payload(
        legal_name=legal_name, fein=fein, merit_rating_method=merit_rating_method,
        taxable_payroll_cents=taxable_payroll_cents,
        reserve_balance_cents=reserve_balance_cents)
    return get_success_data(api_client.create_employer(payload, ADMIN))


def create_tpa_engagement(employer_id, tpa_name="ClaimShield Partners",
                          authority_scope="FULL",
                          effective_from=TS["ENGAGEMENT_FROM"],
                          effective_to=TS["ENGAGEMENT_TO"]):
    payload = create_tpa_engagement_payload(
        employer_id, tpa_name, authority_scope, effective_from, effective_to)
    return get_success_data(api_client.create_tpa_engagement(payload, TPA_MANAGER))


def create_separation(employer_id, separation_reason="LAYOFF",
                      claimant_name="Pat Claimant", ssn_last4="1111",
                      last_day_worked=TS["LAST_DAY_WORKED"]):
    payload = create_separation_payload(
        employer_id, claimant_name, ssn_last4, last_day_worked, separation_reason)
    return get_success_data(api_client.create_separation(payload, ANALYST))


def create_claim(employer_id, separation_id, state_code="XX",
                 state_claim_number=None, notice_received_at=TS["NOTICE"],
                 max_benefit_cents=1_000_000, weekly_benefit_amount_cents=40_000):
    payload = create_claim_payload(
        employer_id, separation_id, state_code, state_claim_number,
        notice_received_at, weekly_benefit_amount_cents=weekly_benefit_amount_cents,
        max_benefit_cents=max_benefit_cents)
    return get_success_data(api_client.create_claim(payload, ANALYST))


def get_claim(claim_id):
    return get_success_data(api_client.get_claim(claim_id, ANALYST))


def get_employer(employer_id):
    return get_success_data(api_client.get_employer(employer_id, ADMIN))


def get_response(response_id):
    return get_success_data(api_client.get_response(response_id, ANALYST))


def get_hearing(hearing_id):
    return get_success_data(api_client.get_hearing(hearing_id, ANALYST))


def get_witness(hearing_id, witness_id):
    data, _meta = None, None
    resp = api_client.list_hearing_witnesses(hearing_id, ANALYST)
    items = get_success_data(resp)
    for w in items:
        if w["id"] == witness_id:
            data = w
    assert data is not None, f"Witness {witness_id} not found on hearing {hearing_id}"
    return data


def get_statement(statement_id):
    return get_success_data(api_client.get_charge_statement(statement_id, AUDITOR))


def get_line_item(line_item_id):
    return get_success_data(api_client.get_line_item(line_item_id, AUDITOR))


def get_protest(protest_id):
    return get_success_data(api_client.get_protest(protest_id, AUDITOR))


def get_appeal(appeal_id):
    return get_success_data(api_client.get_appeal(appeal_id, ANALYST))


def get_determination(determination_id):
    return get_success_data(api_client.get_determination(determination_id, LIAISON))


def get_engagement(engagement_id):
    return get_success_data(api_client.get_tpa_engagement(engagement_id, TPA_MANAGER))


def get_model(model_id):
    return get_success_data(api_client.get_model(model_id, RATER))


def get_separation(separation_id):
    return get_success_data(api_client.get_separation(separation_id, ANALYST))


# ---------------------------------------------------------------------------
# Tier 2: response drafting, evidence, submission
# ---------------------------------------------------------------------------

def draft_response(claim_id, response_type="PROTEST",
                   separation_reason_code="LAYOFF", narrative="Documented.",
                   filed_by_tpa_id=None, amendment_of=None, as_tpa=False):
    payload = create_response_payload(
        response_type, separation_reason_code, narrative,
        filed_by_tpa_id=filed_by_tpa_id, amendment_of=amendment_of)
    headers = TPA_AGENT if as_tpa else ANALYST
    return get_success_data(api_client.create_response(claim_id, payload, headers))


def attach_evidence(claim_id, response_id=None,
                    doc_category="FINAL_INCIDENT_REPORT",
                    doc_date=TS["DOC_PRE_NOTICE"], authenticated=True,
                    as_tpa=False):
    """Attach one evidence document; with the defaults (an authenticated final
    incident report dated before the notice) the referenced draft scores 40."""
    payload = create_evidence_payload(doc_category, doc_date, authenticated,
                                      response_id=response_id)
    headers = TPA_AGENT if as_tpa else ANALYST
    return get_success_data(api_client.attach_evidence(claim_id, payload, headers))


def submit_response(claim_id, response_id, headers=None):
    """Read the claim's current version, then submit with that OCC token."""
    headers = headers or ANALYST
    version = get_success_data(api_client.get_claim(claim_id, headers))["version"]
    return get_success_data(
        api_client.submit_response(claim_id, response_id, version, headers))


def create_claim_with_complete_draft(employer_id, separation_id,
                                     state_code="XX", notice_received_at=TS["NOTICE"],
                                     separation_reason_code="LAYOFF",
                                     response_type="PROTEST",
                                     max_benefit_cents=1_000_000,
                                     filed_by_tpa_id=None, as_tpa=False):
    """Claim + one draft response + one authenticated incident report (score 40).
    Returns (claim, response)."""
    claim = create_claim(employer_id, separation_id, state_code=state_code,
                         notice_received_at=notice_received_at,
                         max_benefit_cents=max_benefit_cents)
    response = draft_response(claim["id"], response_type=response_type,
                              separation_reason_code=separation_reason_code,
                              filed_by_tpa_id=filed_by_tpa_id, as_tpa=as_tpa)
    attach_evidence(claim["id"], response["id"], as_tpa=as_tpa)
    return claim, response


def submit_complete_response(employer_id, separation_id, state_code="XX",
                             notice_received_at=TS["NOTICE"],
                             separation_reason_code="LAYOFF", response_type="PROTEST",
                             filed_by_tpa_id=None, as_tpa=False):
    """Claim + complete draft + submit. Returns (claim, submitted_response)."""
    claim, response = create_claim_with_complete_draft(
        employer_id, separation_id, state_code=state_code,
        notice_received_at=notice_received_at,
        separation_reason_code=separation_reason_code, response_type=response_type,
        filed_by_tpa_id=filed_by_tpa_id, as_tpa=as_tpa)
    submitted = submit_response(
        claim["id"], response["id"], headers=TPA_AGENT if as_tpa else ANALYST)
    return get_claim(claim["id"]), submitted


# ---------------------------------------------------------------------------
# Tier 3: adjudication lifecycle (ack -> determination -> appeal -> hearing)
# ---------------------------------------------------------------------------

def ack_claim(claim_id):
    """Simulate the state agency acknowledging a submitted response."""
    return get_success_data(api_client.claim_adjudication_ack(claim_id, ADMIN))


def determine_claim(claim_id, outcome="ALLOWED", mailed_at=TS["MAILED"]):
    payload = create_determination_payload(outcome, mailed_at)
    return get_success_data(api_client.create_determination(claim_id, payload, LIAISON))


def setup_under_adjudication_claim(employer_kwargs=None, separation_reason="LAYOFF",
                                   state_code="XX", notice_received_at=TS["NOTICE"]):
    """Employer -> separation -> claim -> complete draft -> on-time submit ->
    agency ack. Claim is UNDER_ADJUDICATION, awaiting a determination."""
    employer = create_employer(**(employer_kwargs or {}))
    separation = create_separation(employer["id"], separation_reason=separation_reason)
    claim, response = submit_complete_response(
        employer["id"], separation["id"], state_code=state_code,
        notice_received_at=notice_received_at,
        separation_reason_code=separation_reason)
    ack_claim(claim["id"])
    return {
        "employer": get_employer(employer["id"]),
        "separation": get_separation(separation["id"]),
        "claim": get_claim(claim["id"]),
        "response": get_response(response["id"]),
    }


def setup_determined_claim(employer_kwargs=None, outcome="ALLOWED",
                           mailed_at=TS["MAILED"], separation_reason="LAYOFF",
                           state_code="XX", notice_received_at=TS["NOTICE"]):
    """Full chain: employer -> separation -> claim -> draft -> evidence ->
    submit (on time) -> agency ack -> determination. Returns a context dict."""
    ctx = setup_under_adjudication_claim(
        employer_kwargs=employer_kwargs, separation_reason=separation_reason,
        state_code=state_code, notice_received_at=notice_received_at)
    determination = determine_claim(ctx["claim"]["id"], outcome=outcome,
                                    mailed_at=mailed_at)
    return {
        "employer": get_employer(ctx["employer"]["id"]),
        "separation": get_separation(ctx["separation"]["id"]),
        "claim": get_claim(ctx["claim"]["id"]),
        "response": ctx["response"],
        "determination": determination,
    }


def appeal_determination(determination_id, appellant="EMPLOYER",
                         grounds="The determination misapplied the facts.",
                         as_liaison=False):
    payload = create_appeal_payload(appellant, grounds)
    headers = LIAISON if as_liaison else ANALYST
    return get_success_data(api_client.file_appeal(determination_id, payload, headers))


def setup_appealed_claim(**kwargs):
    """Determined claim + an employer appeal (claim HEARING_PENDING)."""
    ctx = setup_determined_claim(**kwargs)
    appeal = appeal_determination(ctx["determination"]["id"])
    ctx["appeal"] = appeal
    ctx["claim"] = get_claim(ctx["claim"]["id"])
    ctx["determination"] = get_determination(ctx["determination"]["id"])
    return ctx


def schedule_hearing(appeal_id, claim_id,
                     scheduled_start="2026-08-20T14:00:00Z",
                     scheduled_end="2026-08-20T15:00:00Z",
                     referee_id="ref-1", location="Room 1"):
    payload = create_hearing_payload(claim_id, scheduled_start, scheduled_end,
                                     referee_id, location)
    return get_success_data(api_client.schedule_hearing(appeal_id, payload, ANALYST))


def add_witness(hearing_id, full_name="Witness One",
                witness_role="DIRECT_SUPERVISOR",
                availability_start="2026-08-20T13:00:00Z",
                availability_end="2026-08-20T16:00:00Z"):
    payload = create_witness_payload(full_name, witness_role,
                                     availability_start, availability_end)
    return get_success_data(api_client.add_witness(hearing_id, payload, ANALYST))


def prep_witness_once(hearing_id, witness_id):
    return get_success_data(api_client.prep_witness(hearing_id, witness_id, ANALYST))


def prep_witness_to_ready(hearing_id, witness_id):
    """Three preparation steps: UNPREPARED -> BRIEFED -> EXHIBITS_REVIEWED -> READY."""
    witness = None
    for _ in range(3):
        witness = prep_witness_once(hearing_id, witness_id)
    return witness


def setup_docketed_hearing(referee_id="ref-1", start="2026-08-20T14:00:00Z",
                           end="2026-08-20T15:00:00Z", **kwargs):
    """Appealed claim + scheduled hearing (appeal DOCKETED, hearing SCHEDULED)."""
    ctx = setup_appealed_claim(**kwargs)
    hearing = schedule_hearing(ctx["appeal"]["id"], ctx["claim"]["id"],
                               scheduled_start=start, scheduled_end=end,
                               referee_id=referee_id)
    ctx["hearing"] = hearing
    ctx["appeal"] = get_appeal(ctx["appeal"]["id"])
    return ctx


def setup_heard_appeal(referee_id="ref-1", **kwargs):
    """Full chain through a held hearing: appeal HEARD, hearing HELD."""
    ctx = setup_docketed_hearing(referee_id=referee_id, **kwargs)
    witness = add_witness(ctx["hearing"]["id"])
    prep_witness_to_ready(ctx["hearing"]["id"], witness["id"])
    held = get_success_data(api_client.hold_hearing(ctx["hearing"]["id"], LIAISON))
    ctx["witness"] = get_witness(ctx["hearing"]["id"], witness["id"])
    ctx["hearing"] = held
    ctx["appeal"] = get_appeal(ctx["appeal"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: charge statements, line items, protests
# ---------------------------------------------------------------------------

def create_statement(employer_id, state_code="XX", quarter=TS["QUARTER"],
                     issued_at=TS["STMT_ISSUED"]):
    payload = create_charge_statement_payload(employer_id, state_code, quarter,
                                              issued_at)
    return get_success_data(api_client.create_charge_statement(payload, LIAISON))


def post_line(statement_id, claim_id, amount_cents, benefit_weeks=2,
              erroneous_reason=None):
    payload = post_line_item_payload(claim_id, amount_cents, benefit_weeks,
                                     erroneous_reason)
    return get_success_data(api_client.post_line_item(statement_id, payload, LIAISON))


def file_protest(line_id, statement_id, protest_basis="WRONG_EMPLOYER"):
    """Read the statement's current version, then file the protest (OCC)."""
    version = get_statement(statement_id)["version"]
    return get_success_data(
        api_client.file_protest(line_id, protest_basis, version, AUDITOR))


def setup_statement_with_line(amount_cents=400_000, erroneous_reason="WRONG_EMPLOYER",
                              employer_kwargs=None, max_benefit_cents=1_000_000):
    """Employer + separation + claim + statement + one posted line.
    Returns a context dict."""
    employer = create_employer(**(employer_kwargs or {}))
    separation = create_separation(employer["id"])
    claim = create_claim(employer["id"], separation["id"],
                         max_benefit_cents=max_benefit_cents)
    statement = create_statement(employer["id"])
    line = post_line(statement["id"], claim["id"], amount_cents,
                     erroneous_reason=erroneous_reason)
    return {
        "employer": get_employer(employer["id"]),
        "separation": separation,
        "claim": get_claim(claim["id"]),
        "statement": get_statement(statement["id"]),
        "line": line,
    }


def review_protest(protest_id):
    return get_success_data(api_client.review_protest(protest_id, LIAISON))


def sustain_protest(protest_id):
    return get_success_data(api_client.sustain_protest(protest_id, LIAISON))


# ---------------------------------------------------------------------------
# Tier 5: rating models
# ---------------------------------------------------------------------------

def create_model(employer_id, model_year=2027, variant="RESERVE_RATIO",
                 kind="OFFICIAL"):
    payload = create_model_payload(model_year, variant, kind)
    return get_success_data(api_client.create_model(employer_id, payload, RATER))


def finalize_model(employer_id, model_id):
    """Read the employer's current version, then finalize with that OCC token."""
    version = get_employer(employer_id)["version"]
    return get_success_data(
        api_client.finalize_model(employer_id, model_id, version, RATER))


# ---------------------------------------------------------------------------
# Tier 6: late-response strike accumulation
# ---------------------------------------------------------------------------

def file_late_response(employer_id, separation_id, state_code="XX",
                       notice_received_at=TS["NOTICE"], filed_by_tpa_id=None,
                       as_tpa=False, response_type="NO_PROTEST"):
    """Draft a complete response for a claim whose deadline has already passed
    (the caller moves the clock first), then submit it late.
    Returns the submitted response payload."""
    claim = create_claim(employer_id, separation_id, state_code=state_code,
                         notice_received_at=notice_received_at)
    response = draft_response(claim["id"], response_type=response_type,
                              separation_reason_code="LAYOFF",
                              narrative="Late acknowledgment.",
                              filed_by_tpa_id=filed_by_tpa_id, as_tpa=as_tpa)
    attach_evidence(claim["id"], response["id"], as_tpa=as_tpa)
    return submit_response(claim["id"], response["id"],
                           headers=TPA_AGENT if as_tpa else ANALYST)


def setup_employer_with_late_strikes(strike_count, response_window_days=5,
                                     legal_name="StrikeCo",
                                     reserve_balance_cents=None):
    """Employer with exactly `strike_count` late responses.

    State XX uses a short CALENDAR window; each claim is drafted with evidence
    while the clock is at the start, then submitted after the clock moves past
    its computed due date. Returns the refreshed employer.
    """
    set_clock(TS["CLOCK_START"])
    create_state_rule("XX", response_window_days=response_window_days,
                      window_basis="CALENDAR", weekend_shift="NONE")
    employer = create_employer(legal_name=legal_name,
                               reserve_balance_cents=reserve_balance_cents)
    separations = [
        create_separation(employer["id"], claimant_name=f"Worker {i}",
                          ssn_last4=f"{4000 + i:04d}")
        for i in range(strike_count)
    ]
    for i, sep in enumerate(separations):
        if i == 0:
            # First claim is created before the clock moves; the rest are
            # created after, with their notice date already in the past.
            claim = create_claim(employer["id"], sep["id"])
            response = draft_response(claim["id"], response_type="NO_PROTEST",
                                      narrative="Late.")
            attach_evidence(claim["id"], response["id"])
            set_clock(TS["LATE_CLOCK"])
            submit_response(claim["id"], response["id"])
        else:
            file_late_response(employer["id"], sep["id"])
    return get_employer(employer["id"])
