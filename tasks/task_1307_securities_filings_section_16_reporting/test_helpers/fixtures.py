"""Composite setup helpers for the Section 16 filings domain.

Every helper builds preconditions from scratch via PRD-declared endpoints and
uses get_success_data() so setup failures surface as clear "Setup failed"
errors. ReportingInsider is entity-backed (PRD §2.1): plan calls thread the
owning ReportingPerson.id through make_reporting_insider_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_issuer_payload, create_reporting_person_payload,
    create_transaction_payload, create_filing_payload,
    create_trading_plan_payload, create_blackout_window_payload,
    create_beneficial_holder_payload, create_position_change_payload,
    create_annual_sweep_payload, create_filing_agent_authorization_payload,
)
from .test_users import (
    make_compliance_officer_headers, make_filing_coordinator_headers,
    make_filing_agent_headers, make_equity_plan_admin_headers,
    make_reporting_insider_headers,
)

CO = TEST_DEFAULTS["COMPLIANCE_OFFICER_ID"]
COORD = TEST_DEFAULTS["FILING_COORDINATOR_ID"]
AGENT = TEST_DEFAULTS["FILING_AGENT_ID"]
EPA = TEST_DEFAULTS["EQUITY_PLAN_ADMIN_ID"]
CCC = TEST_DEFAULTS["EDGAR_CCC"]


def _setup_fail(step: str, resp):
    raise AssertionError(f"Setup failed at {step}: {resp.status_code} {resp.text}")


def _ok(step: str, resp):
    if resp.status_code >= 300:
        _setup_fail(step, resp)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation and clock control
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Set the server logical clock (ComplianceOfficer only, PRD §2.5)."""
    return _ok("set_clock", api_client.set_clock(
        {"to_iso8601": to_iso8601}, make_compliance_officer_headers(CO)))


def create_issuer(**overrides):
    """Register an issuer (ComplianceOfficer)."""
    return _ok("create_issuer", api_client.create_issuer(
        create_issuer_payload(**overrides), make_compliance_officer_headers(CO)))


def create_reporting_person(issuer_id, **overrides):
    """Create a proposed insider (born PROPOSED)."""
    return _ok("create_reporting_person", api_client.create_reporting_person(
        create_reporting_person_payload(issuer_id=issuer_id, **overrides),
        make_compliance_officer_headers(CO)))


def person_action(person_id, action):
    """Drive the designation lifecycle (DESIGNATE / EXIT / REINSTATE)."""
    return _ok(f"person_action:{action}", api_client.person_transition(
        person_id, {"action": action}, make_compliance_officer_headers(CO)))


def get_person(person_id):
    return _ok("get_person", api_client.get_reporting_person(
        person_id, make_compliance_officer_headers(CO)))


def get_filing(filing_id):
    return _ok("get_filing", api_client.get_filing(
        filing_id, make_compliance_officer_headers(CO)))


def get_transaction(transaction_id):
    return _ok("get_transaction", api_client.get_transaction(
        transaction_id, make_compliance_officer_headers(CO)))


def get_holder(holder_id):
    return _ok("get_holder", api_client.get_beneficial_holder(
        holder_id, make_compliance_officer_headers(CO)))


def get_plan(plan_id):
    return _ok("get_plan", api_client.get_trading_plan(
        plan_id, make_compliance_officer_headers(CO)))


def find_filings(**params):
    """List filings with filters; returns the full data list (limit 100)."""
    params.setdefault("limit", 100)
    return _ok("find_filings", api_client.list_filings(
        make_compliance_officer_headers(CO), params=params))


def find_draft_form(person_id, form_type):
    """Return the single DRAFT filing of the given form type for the person."""
    filings = find_filings(reporting_person_id=person_id, form_type=form_type,
                           status="DRAFT")
    assert len(filings) == 1, (
        f"Expected exactly one DRAFT {form_type} for person {person_id}, "
        f"got {len(filings)}")
    return filings[0]


# ---------------------------------------------------------------------------
# Tier 2: designation lifecycle and transaction intake
# ---------------------------------------------------------------------------

def create_active_person(issuer_id, designate_at=None, **overrides):
    """Create a person and DESIGNATE them ACTIVE. Optionally sets the clock
    first so designation_date lands on a chosen logical date."""
    if designate_at is not None:
        set_clock(designate_at)
    person = create_reporting_person(issuer_id, **overrides)
    return person_action(person["id"], "DESIGNATE")


def ingest_transaction(person_id, ingester_id=EPA, ingester_role="EquityPlanAdmin",
                       **overrides):
    """Ingest a transaction (born INGESTED) via the feed or manual channel."""
    if ingester_role == "EquityPlanAdmin":
        headers = make_equity_plan_admin_headers(ingester_id)
    else:
        headers = make_filing_coordinator_headers(ingester_id)
    return _ok("ingest_transaction", api_client.create_transaction(
        create_transaction_payload(reporting_person_id=person_id, **overrides),
        headers))


def confirm_transaction(transaction_id, confirmer_id=CO):
    """Confirm an INGESTED transaction (four-eyes: confirmer != ingester)."""
    return _ok("confirm_transaction", api_client.confirm_transaction(
        transaction_id, make_compliance_officer_headers(confirmer_id)))


def void_transaction(transaction_id, confirmer_id=CO, reason=None):
    payload = {} if reason is None else {"reason": reason}
    return _ok("void_transaction", api_client.void_transaction(
        transaction_id, payload, make_compliance_officer_headers(confirmer_id)))


# ---------------------------------------------------------------------------
# Tier 3: filing pipeline (ready -> submit -> EDGAR disposition)
# ---------------------------------------------------------------------------

def authorize_filing_agent(issuer_id, agent_user_id=AGENT):
    """Create an ACTIVE filing-agent authorization for (issuer, agent)."""
    return _ok("authorize_filing_agent",
               api_client.create_filing_agent_authorization(
                   create_filing_agent_authorization_payload(
                       issuer_id=issuer_id, agent_user_id=agent_user_id),
                   make_compliance_officer_headers(CO)))


def ready_filing(filing_id, coordinator_id=COORD):
    return _ok("ready_filing", api_client.ready_filing(
        filing_id, make_filing_coordinator_headers(coordinator_id)))


def submit_filing(filing_id, edgar_ccc=CCC, agent_id=AGENT):
    return _ok("submit_filing", api_client.submit_filing(
        filing_id, {"edgar_ccc": edgar_ccc}, make_filing_agent_headers(agent_id)))


def record_edgar_acceptance(filing_id, accession_number=None, agent_id=AGENT):
    payload = {"outcome": "ACCEPTED",
               "accession_number": accession_number or TEST_DEFAULTS["ACCESSION_NUMBER"]}
    return _ok("record_edgar_acceptance", api_client.record_edgar_result(
        filing_id, payload, make_filing_agent_headers(agent_id)))


def record_edgar_rejection(filing_id, rejection_reason="bad tag", agent_id=AGENT):
    return _ok("record_edgar_rejection", api_client.record_edgar_result(
        filing_id, {"outcome": "REJECTED", "rejection_reason": rejection_reason},
        make_filing_agent_headers(agent_id)))


def setup_person_with_confirmed_transaction(
        issuer_overrides=None, person_overrides=None, txn_overrides=None,
        designate_at=None, confirm_clock=None, authorize_agent=True):
    """Issuer + ACTIVE person + one confirmed transaction + its auto Form 4 DRAFT.

    Returns dict(issuer, person, txn, form4).
    """
    issuer = create_issuer(**(issuer_overrides or {}))
    if authorize_agent:
        authorize_filing_agent(issuer["id"])
    person = create_active_person(issuer["id"], designate_at=designate_at,
                                  **(person_overrides or {}))
    txn = ingest_transaction(person["id"], **(txn_overrides or {}))
    if confirm_clock is not None:
        set_clock(confirm_clock)
    txn = confirm_transaction(txn["id"])
    form4 = find_draft_form(person["id"], "FORM_4")
    return {"issuer": issuer, "person": person, "txn": txn, "form4": form4}


def setup_ready_auto_form4(**kwargs):
    """Confirmed transaction whose auto Form 4 has been moved to READY."""
    scenario = setup_person_with_confirmed_transaction(**kwargs)
    scenario["form4"] = ready_filing(scenario["form4"]["id"])
    return scenario


def setup_accepted_auto_form4(submit_clock=None, accept_clock=None,
                              accession_number=None, **kwargs):
    """Confirmed transaction whose auto Form 4 has gone
    DRAFT -> READY -> SUBMITTED -> ACCEPTED."""
    scenario = setup_ready_auto_form4(**kwargs)
    if submit_clock is not None:
        set_clock(submit_clock)
    submit_filing(scenario["form4"]["id"])
    if accept_clock is not None:
        set_clock(accept_clock)
    scenario["form4"] = record_edgar_acceptance(
        scenario["form4"]["id"], accession_number=accession_number)
    return scenario


# ---------------------------------------------------------------------------
# Tier 4: trading plans (10b5-1)
# ---------------------------------------------------------------------------

def create_trading_plan(person_id, **overrides):
    """Draft a plan as the owning insider (X-User-ID == reporting_person_id)."""
    return _ok("create_trading_plan", api_client.create_trading_plan(
        create_trading_plan_payload(reporting_person_id=person_id, **overrides),
        make_reporting_insider_headers(person_id)))


def plan_action(plan_id, action, person_id=None):
    """Drive a plan transition. Officer actions (APPROVE / REJECT / ACTIVATE /
    SUSPEND / REINSTATE / TERMINATE) default to ComplianceOfficer; insider
    actions (SUBMIT_ADOPTION, insider TERMINATE) pass person_id."""
    if person_id is not None:
        headers = make_reporting_insider_headers(person_id)
    else:
        headers = make_compliance_officer_headers(CO)
    return _ok(f"plan_action:{action}", api_client.plan_transition(
        plan_id, {"action": action}, headers))


def setup_adopted_plan(issuer_id, person_id, approve_at=None,
                       first_trade_date="2026-09-01", expiration_date="2027-03-01",
                       plan_name="Plan A"):
    """Plan walked DRAFT -> PENDING_APPROVAL -> ADOPTED."""
    if approve_at is not None:
        set_clock(approve_at)
    plan = create_trading_plan(person_id, plan_name=plan_name,
                               first_trade_date=first_trade_date,
                               expiration_date=expiration_date)
    plan_action(plan["id"], "SUBMIT_ADOPTION", person_id=person_id)
    return plan_action(plan["id"], "APPROVE")


def setup_active_plan(issuer_id, person_id, approve_at, activate_at, **window):
    """Plan walked through to ACTIVE (clock must reach cooling_off_end_date)."""
    plan = setup_adopted_plan(issuer_id, person_id, approve_at=approve_at, **window)
    set_clock(activate_at)
    return plan_action(plan["id"], "ACTIVATE")


# ---------------------------------------------------------------------------
# Tier 5: beneficial ownership and sweeps
# ---------------------------------------------------------------------------

def create_beneficial_holder(issuer_id, **overrides):
    """Start monitoring a beneficial owner (born MONITORING)."""
    return _ok("create_beneficial_holder", api_client.create_beneficial_holder(
        create_beneficial_holder_payload(issuer_id=issuer_id, **overrides),
        make_compliance_officer_headers(CO)))


def post_position_change(holder_id, shares_delta, derivative_shares_delta=0,
                         effective_date="2026-08-01", note=None):
    payload = create_position_change_payload(
        shares_delta=shares_delta, derivative_shares_delta=derivative_shares_delta,
        effective_date=effective_date)
    if note is not None:
        payload["note"] = note
    return _ok("post_position_change", api_client.post_position_change(
        holder_id, payload, make_compliance_officer_headers(CO)))


def create_annual_sweep(issuer_id, fiscal_year=2026):
    """Open an annual sweep (born OPEN)."""
    return _ok("create_annual_sweep", api_client.create_annual_sweep(
        create_annual_sweep_payload(issuer_id=issuer_id, fiscal_year=fiscal_year),
        make_compliance_officer_headers(CO)))


def create_blackout_window(issuer_id, start_date, end_date, reason=None):
    payload = create_blackout_window_payload(
        issuer_id=issuer_id, start_date=start_date, end_date=end_date)
    if reason is not None:
        payload["reason"] = reason
    return _ok("create_blackout_window", api_client.create_blackout_window(
        payload, make_compliance_officer_headers(CO)))
