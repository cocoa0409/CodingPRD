"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database and the logical clock at exactly 2026-08-01T00:00:00Z per PRD
§2.10). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors.

OCC threading: filing creation and laser creation are OCC-guarded on the
contract version (PRD §2.8). Activation, renewal, laser creation, and
filing creation all bump the contract version, so helpers always re-GET
the contract immediately before an OCC-guarded call.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    adjudicate_claim_payload,
    approve_filing_payload,
    create_audit_payload,
    create_claim_payload,
    create_contract_payload,
    create_filing_payload,
    create_forecast_payload,
    create_lasered_term_payload,
    create_member_payload,
    create_plan_payload,
    create_reimbursement_payload,
    dispute_filing_payload,
    pay_claim_payload,
    renew_contract_payload,
    resolve_audit_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_stop_loss_analyst_headers

ADMIN = TEST_USERS["plan_administrator_headers"]
EXAMINER = TEST_USERS["claims_examiner_headers"]
ANALYST = TEST_USERS["stop_loss_analyst_headers"]
REVIEWER = TEST_USERS["carrier_reviewer_headers"]
ACCOUNTANT = TEST_USERS["plan_accountant_headers"]
AUDITOR = TEST_USERS["carrier_auditor_headers"]

# X-User-ID of the shared analyst constant; fixtures that submit filings
# record this as the filing's submitting operator (PRD §2.11).
ANALYST_USER_ID = "test-analyst-1"


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at {step}: {exc}")


# ---------------------------------------------------------------------------
# Tier 1 — single-entity creation and state progression
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """PlanAdministrator moves the logical clock (PRD §2.10)."""
    resp = api_client.set_clock(set_clock_payload(to_iso8601), ADMIN)
    return _ok("set_clock", resp)


def create_plan(plan_name="Acme Health Plan", sponsor_tax_id="12-3456789"):
    """Create a plan (born ACTIVE). Returns the plan dict."""
    resp = api_client.create_plan(
        create_plan_payload(plan_name=plan_name, sponsor_tax_id=sponsor_tax_id),
        ADMIN)
    return _ok("create_plan", resp)


def create_contract(plan_id, **overrides):
    """Draft a contract (born DRAFT). Returns the contract dict."""
    resp = api_client.create_contract(
        create_contract_payload(plan_id, **overrides), ADMIN)
    return _ok("create_contract", resp)


def get_contract(contract_id):
    resp = api_client.get_contract(contract_id, ADMIN)
    return _ok("get_contract", resp)


def get_contract_version(contract_id):
    """Current contract version for OCC-guarded writes (PRD §2.8)."""
    return get_contract(contract_id)["version"]


def activate_contract(contract_id):
    """DRAFT -> IN_FORCE; materializes the accumulation rows."""
    resp = api_client.activate_contract(contract_id, ADMIN)
    return _ok("activate_contract", resp)


def renew_contract(contract_id, new_policy_year_start, new_policy_year_end,
                   **overrides):
    """EXPIRED -> RENEWED; returns the successor DRAFT contract (201)."""
    resp = api_client.renew_contract(
        contract_id,
        renew_contract_payload(new_policy_year_start, new_policy_year_end,
                               **overrides),
        ADMIN)
    return _ok("renew_contract", resp)


def create_member(plan_id, member_external_id="M001", **overrides):
    """Enroll a member (born ACTIVE, notice_status NONE)."""
    resp = api_client.create_member(
        create_member_payload(plan_id, member_external_id, **overrides), ADMIN)
    return _ok("create_member", resp)


def get_member(member_id):
    resp = api_client.get_member(member_id, ADMIN)
    return _ok("get_member", resp)


def file_notice(member_id):
    """NOTICE_PENDING -> NOTICE_FILED (PlanAdministrator)."""
    resp = api_client.file_notice(member_id, ADMIN)
    return _ok("file_notice", resp)


# ---------------------------------------------------------------------------
# Tier 2 — lasers and claims
# ---------------------------------------------------------------------------

def create_laser(contract_id, member_id, lasered_specific_deductible_cents,
                 effective_from, effective_to):
    """Create a lasered term with a fresh OCC version. Returns the term."""
    version = get_contract_version(contract_id)
    resp = api_client.create_lasered_term(
        create_lasered_term_payload(
            contract_id, member_id, lasered_specific_deductible_cents,
            effective_from, effective_to, version),
        ADMIN)
    return _ok("create_laser", resp)


def create_claim(plan_id, member_id, service_date="2026-02-01T00:00:00Z",
                 billed_amount_cents=15_000_000, claim_type="MEDICAL"):
    """Submit a claim (born SUBMITTED). Returns the claim dict."""
    resp = api_client.create_claim(
        create_claim_payload(
            plan_id, member_id, service_date=service_date,
            billed_amount_cents=billed_amount_cents, claim_type=claim_type),
        EXAMINER)
    return _ok("create_claim", resp)


def adjudicate_claim(claim_id, allowed_amount_cents):
    resp = api_client.adjudicate_claim(
        claim_id, adjudicate_claim_payload(allowed_amount_cents), EXAMINER)
    return _ok("adjudicate_claim", resp)


def pay_claim(claim_id, paid_amount_cents, paid_date="2026-02-02T00:00:00Z"):
    resp = api_client.pay_claim(
        claim_id, pay_claim_payload(paid_amount_cents, paid_date), EXAMINER)
    return _ok("pay_claim", resp)


def get_claim(claim_id):
    resp = api_client.get_claim(claim_id, ADMIN)
    return _ok("get_claim", resp)


def get_reimbursement(reimbursement_id):
    resp = api_client.get_reimbursement(reimbursement_id, ADMIN)
    return _ok("get_reimbursement", resp)


def get_audit(audit_id):
    resp = api_client.get_audit(audit_id, ADMIN)
    return _ok("get_audit", resp)


def create_and_pay_claim(plan_id, member_id, amount_cents,
                         service_date="2026-02-01T00:00:00Z",
                         paid_date="2026-02-02T00:00:00Z"):
    """Create -> adjudicate (allowed == billed) -> pay. Returns PAID claim."""
    claim = create_claim(plan_id, member_id, service_date=service_date,
                         billed_amount_cents=amount_cents)
    adjudicate_claim(claim["id"], amount_cents)
    return pay_claim(claim["id"], amount_cents, paid_date)


# ---------------------------------------------------------------------------
# Tier 3 — accumulation ledger reads
# ---------------------------------------------------------------------------

def list_accumulations():
    """All accumulation rows (filtering done client-side)."""
    resp = api_client.list_accumulations(ADMIN, params={"limit": 100})
    return validate_paginated(resp)[0]


def get_specific_row(contract_id, member_id):
    """The one SPECIFIC accumulation row for (contract, member)."""
    matches = [r for r in list_accumulations()
               if r["contract_id"] == contract_id
               and r["member_id"] == member_id and r["scope"] == "SPECIFIC"]
    assert len(matches) == 1, (
        f"Expected exactly one SPECIFIC row for ({contract_id}, {member_id}), "
        f"got {len(matches)}")
    return matches[0]


def get_aggregate_row(contract_id):
    """The one AGGREGATE accumulation row for the contract (member_id null)."""
    matches = [r for r in list_accumulations()
               if r["contract_id"] == contract_id and r["scope"] == "AGGREGATE"]
    assert len(matches) == 1, (
        f"Expected exactly one AGGREGATE row for {contract_id}, "
        f"got {len(matches)}")
    return matches[0]


# ---------------------------------------------------------------------------
# Tier 4 — filings and the carrier-review lifecycle
# ---------------------------------------------------------------------------

def create_filing(contract_id, claim_ids, filing_scope="SPECIFIC",
                  member_id=None, analyst_headers=None):
    """Create a DRAFT filing with a fresh OCC version. Returns the filing."""
    version = get_contract_version(contract_id)
    overrides = {}
    if member_id is not None:
        overrides["member_id"] = member_id
    resp = api_client.create_filing(
        create_filing_payload(contract_id, filing_scope, claim_ids, version,
                              **overrides),
        analyst_headers or ANALYST)
    return _ok("create_filing", resp)


def get_filing(filing_id):
    resp = api_client.get_filing(filing_id, ADMIN)
    return _ok("get_filing", resp)


def submit_filing(filing_id, analyst_headers=None):
    resp = api_client.submit_filing(filing_id, analyst_headers or ANALYST)
    return _ok("submit_filing", resp)


def begin_review(filing_id):
    resp = api_client.begin_review(filing_id, REVIEWER)
    return _ok("begin_review", resp)


def dispute_filing(filing_id, disputed_line_item_ids):
    resp = api_client.dispute_filing(
        filing_id, dispute_filing_payload(disputed_line_item_ids), REVIEWER)
    return _ok("dispute_filing", resp)


def approve_filing(filing_id, approved_amount_cents):
    resp = api_client.approve_filing(
        filing_id, approve_filing_payload(approved_amount_cents), REVIEWER)
    return _ok("approve_filing", resp)


def list_line_items(filing_id):
    resp = api_client.list_filing_line_items(filing_id, ADMIN)
    return validate_paginated(resp)[0]


def setup_plan_contract_member(plan_name="Acme Health Plan",
                               member_external_id="M001",
                               **contract_overrides):
    """Plan + DRAFT contract + member + activation. Returns ctx dict."""
    plan = create_plan(plan_name)
    contract = create_contract(plan["id"], **contract_overrides)
    member = create_member(plan["id"], member_external_id)
    contract = activate_contract(contract["id"])
    return {"plan": plan, "contract": contract, "member": member}


def setup_paid_claim_scenario(plan_name="Acme Health Plan", claim_cents=15_000_000,
                              service_date="2026-02-01T00:00:00Z",
                              paid_date="2026-02-02T00:00:00Z",
                              file_the_notice=True, **contract_overrides):
    """Plan + IN_FORCE contract + member + one PAID claim.

    A paid claim above the fifty-percent threshold arms the notice
    obligation; pass file_the_notice=True (default) to record the notice.
    Returns ctx dict with plan/contract/member/claim.
    """
    ctx = setup_plan_contract_member(plan_name=plan_name, **contract_overrides)
    claim = create_and_pay_claim(
        ctx["plan"]["id"], ctx["member"]["id"], claim_cents,
        service_date=service_date, paid_date=paid_date)
    ctx["claim"] = claim
    if file_the_notice:
        file_notice(ctx["member"]["id"])
    return ctx


def setup_draft_filing(plan_name="Acme Health Plan", claim_cents=15_000_000,
                       analyst_user_id=None, **contract_overrides):
    """Paid-claim scenario + notice filed + DRAFT specific filing.

    Returns ctx dict extended with the filing. When analyst_user_id is given,
    the filing is created (and later submitted) under that operator id so
    segregation-of-duties tests can control the submitter identity.
    """
    ctx = setup_paid_claim_scenario(plan_name=plan_name, claim_cents=claim_cents,
                                    **contract_overrides)
    headers = (make_stop_loss_analyst_headers(analyst_user_id)
               if analyst_user_id else None)
    filing = create_filing(ctx["contract"]["id"], [ctx["claim"]["id"]],
                           filing_scope="SPECIFIC",
                           member_id=ctx["member"]["id"],
                           analyst_headers=headers)
    ctx["filing"] = filing
    ctx["analyst_headers"] = headers or ANALYST
    return ctx


def setup_under_review_filing(plan_name="Acme Health Plan", claim_cents=15_000_000,
                              analyst_user_id=None, **contract_overrides):
    """DRAFT filing -> SUBMITTED -> UNDER_REVIEW. Returns ctx dict."""
    ctx = setup_draft_filing(plan_name=plan_name, claim_cents=claim_cents,
                             analyst_user_id=analyst_user_id,
                             **contract_overrides)
    ctx["filing"] = submit_filing(ctx["filing"]["id"],
                                  analyst_headers=ctx["analyst_headers"])
    ctx["filing"] = begin_review(ctx["filing"]["id"])
    return ctx


def setup_approved_filing(plan_name="Acme Health Plan", claim_cents=15_000_000,
                          approved_amount_cents=5_000_000, analyst_user_id=None,
                          **contract_overrides):
    """UNDER_REVIEW filing -> APPROVED at approved_amount_cents."""
    ctx = setup_under_review_filing(plan_name=plan_name, claim_cents=claim_cents,
                                    analyst_user_id=analyst_user_id,
                                    **contract_overrides)
    ctx["filing"] = approve_filing(ctx["filing"]["id"], approved_amount_cents)
    return ctx


def setup_paid_filing(plan_name="Acme Health Plan", claim_cents=15_000_000,
                      approved_amount_cents=5_000_000, analyst_user_id=None,
                      **contract_overrides):
    """APPROVED filing + matching reimbursement recorded and posted -> PAID.

    Returns ctx dict extended with the reimbursement.
    """
    ctx = setup_approved_filing(
        plan_name=plan_name, claim_cents=claim_cents,
        approved_amount_cents=approved_amount_cents,
        analyst_user_id=analyst_user_id, **contract_overrides)
    resp = api_client.create_reimbursement(
        create_reimbursement_payload(ctx["filing"]["id"], approved_amount_cents),
        ACCOUNTANT)
    reimbursement = _ok("create_reimbursement", resp)
    resp = api_client.post_reimbursement(reimbursement["id"], ACCOUNTANT)
    reimbursement = _ok("post_reimbursement", resp)
    ctx["reimbursement"] = reimbursement
    ctx["filing"] = get_filing(ctx["filing"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 5 — audits and forecasts
# ---------------------------------------------------------------------------

def setup_audit(plan_name="Acme Health Plan", claim_cents=15_000_000,
                approved_amount_cents=5_000_000, analyst_user_id=None,
                through_paid=True, **contract_overrides):
    """Filing (PAID by default) + audit OPENED. Returns ctx with the audit."""
    if through_paid:
        ctx = setup_paid_filing(
            plan_name=plan_name, claim_cents=claim_cents,
            approved_amount_cents=approved_amount_cents,
            analyst_user_id=analyst_user_id, **contract_overrides)
    else:
        ctx = setup_under_review_filing(
            plan_name=plan_name, claim_cents=claim_cents,
            analyst_user_id=analyst_user_id, **contract_overrides)
    resp = api_client.create_audit(
        create_audit_payload(ctx["filing"]["id"]), AUDITOR)
    ctx["audit"] = _ok("create_audit", resp)
    return ctx


def setup_audit_findings_issued(**kwargs):
    """Audit OPENED -> FINDINGS_ISSUED. Returns ctx with the audit."""
    ctx = setup_audit(**kwargs)
    resp = api_client.issue_findings(ctx["audit"]["id"], AUDITOR)
    ctx["audit"] = _ok("issue_findings", resp)
    return ctx


def resolve_audit(audit_id, adjustment_cents, admin_headers):
    resp = api_client.resolve_audit(
        audit_id, resolve_audit_payload(adjustment_cents), admin_headers)
    return _ok("resolve_audit", resp)


def compute_forecast(plan_id, forecast_basis="PURE_EXPERIENCE",
                     next_year_specific_deductible_cents=10_000_000):
    resp = api_client.create_forecast(
        create_forecast_payload(
            plan_id, forecast_basis,
            next_year_specific_deductible_cents=next_year_specific_deductible_cents),
        ADMIN)
    return _ok("create_forecast", resp)
