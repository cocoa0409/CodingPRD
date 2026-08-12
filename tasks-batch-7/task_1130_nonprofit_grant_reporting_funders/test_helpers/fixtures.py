"""Composite setup helpers.

Every fixture builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server). Setup calls use
the lenient get_success_data() validator so a setup failure surfaces as a clear
"Setup failed" error rather than a confusing assertion deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_audit_engagement_payload,
    create_audit_finding_payload,
    create_budget_line_payload,
    create_expense_payload,
    create_funder_payload,
    create_fund_payload,
    create_grant_payload,
    create_match_contribution_payload,
    create_modification_request_payload,
    report_edit_payload,
)
from .test_users import TEST_USERS, make_funder_headers

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
FINANCE = TEST_USERS["finance_headers"]
DIRECTOR = TEST_USERS["director_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at step '{step}': HTTP {resp.status_code} — {resp.text}"
    )


def _ok(step, resp):
    data = get_success_data(resp)
    if data is None:
        _fail(step, resp)
    return data


# ---------------------------------------------------------------------------
# Tier 1: base entities
# ---------------------------------------------------------------------------

def create_funder(funder_type="FOUNDATION", **overrides):
    payload = create_funder_payload(funder_type=funder_type, **overrides)
    resp = api_client.create_funder(payload, ADMIN)
    return _ok("create_funder", resp)


def create_grant(funder_id, **overrides):
    payload = create_grant_payload(funder_id, **overrides)
    resp = api_client.create_grant(payload, OFFICER)
    return _ok("create_grant", resp)


def add_budget_line(grant_id, **overrides):
    resp = api_client.create_budget_line(
        grant_id, create_budget_line_payload(**overrides), OFFICER
    )
    return _ok("add_budget_line", resp)


def add_fund(grant_id, **overrides):
    resp = api_client.create_fund(grant_id, create_fund_payload(**overrides), FINANCE)
    return _ok("add_fund", resp)


def activate_grant(grant_id):
    resp = api_client.activate_grant(grant_id, DIRECTOR)
    return _ok("activate_grant", resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return _ok("set_clock", resp)


def get_grant(grant_id):
    resp = api_client.get_grant(grant_id, OFFICER)
    return _ok("get_grant", resp)


def list_reports(grant_id, params=None):
    resp = api_client.list_reports(grant_id, OFFICER, params=params)
    return _ok("list_reports", resp)


# ---------------------------------------------------------------------------
# Tier 2: grant hierarchies
# ---------------------------------------------------------------------------

def setup_draft_grant(lines=None, **grant_overrides):
    """Funder + DRAFT grant with the given budget lines (default one PERSONNEL
    line of 100000000) and one UNRESTRICTED fund covering the award.

    Returns dict(funder, grant, lines, fund).
    """
    funder = create_funder(**grant_overrides.pop("funder_overrides", {}))
    grant = create_grant(funder["id"], **grant_overrides)
    line_specs = lines if lines is not None else [
        {"category": "PERSONNEL", "budgeted_cents": 100_000_000}
    ]
    lines_out = [add_budget_line(grant["id"], **spec) for spec in line_specs]
    fund = add_fund(
        grant["id"], allocated_cents=grant_overrides.get(
            "award_amount_cents", 100_000_000
        )
    )
    return {"funder": funder, "grant": grant, "lines": lines_out, "fund": fund}


def setup_active_grant(lines=None, extra_funds=None, **grant_overrides):
    """DRAFT grant hierarchy + activation. Returns
    dict(funder, grant, lines, fund, extra_funds, reports) with the full
    report calendar. `extra_funds` is an optional list of fund payload
    overrides to create (as additional funds) BEFORE activation, since PRD
    §3.1 forbids fund creation after the grant leaves DRAFT. Lines are
    re-fetched post-activation so `ctx["lines"]` reflects the computed
    `period_budgets_cents` from PRD §3.2."""
    ctx = setup_draft_grant(lines=lines, **grant_overrides)
    gid = ctx["grant"]["id"]
    extras = [add_fund(gid, **spec) for spec in (extra_funds or [])]
    ctx["extra_funds"] = extras
    ctx["grant"] = activate_grant(gid)
    # Re-fetch budget lines: activation computes period_budgets_cents per
    # PRD §3.2, so the snapshot from creation time is stale.
    refreshed_resp = api_client.list_budget_lines(gid, OFFICER)
    refreshed = _ok("list_budget_lines_post_activation", refreshed_resp)
    by_id = {l["id"]: l for l in refreshed}
    ctx["lines"] = [by_id[l["id"]] for l in ctx["lines"]]
    ctx["reports"] = list_reports(gid)
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: expenses, posting, allocation
# ---------------------------------------------------------------------------

def create_expense(grant_id, created_by=OFFICER, **overrides):
    resp = api_client.create_expense(
        grant_id, create_expense_payload(**overrides), created_by
    )
    return _ok("create_expense", resp)


def post_expense(expense_id, posted_by=FINANCE):
    resp = api_client.post_expense(expense_id, posted_by)
    return _ok("post_expense", resp)


def create_posted_expense(grant_id, created_by=OFFICER, posted_by=FINANCE,
                          **overrides):
    expense = create_expense(grant_id, created_by=created_by, **overrides)
    return post_expense(expense["id"], posted_by=posted_by)


def allocate(expense_id, budget_line_id, fund_id, amount_cents, allocated_by=OFFICER):
    resp = api_client.create_allocation(
        expense_id,
        {
            "budget_line_id": budget_line_id,
            "fund_id": fund_id,
            "amount_cents": amount_cents,
        },
        allocated_by,
    )
    return _ok("create_allocation", resp)


def create_posted_allocated_expense(grant_id, budget_line_id, fund_id, amount_cents,
                                    expense_date="2026-06-20"):
    """POSTED expense of amount_cents fully allocated to the given line/fund."""
    expense = create_posted_expense(
        grant_id, expense_date=expense_date, amount_cents=amount_cents
    )
    allocation = allocate(expense["id"], budget_line_id, fund_id, amount_cents)
    return expense, allocation


# ---------------------------------------------------------------------------
# Tier 3b: report lifecycle
# ---------------------------------------------------------------------------

def start_report(report_id):
    resp = api_client.start_report(report_id, OFFICER)
    return _ok("start_report", resp)


def edit_report(report_id, **overrides):
    resp = api_client.update_report(report_id, report_edit_payload(**overrides), OFFICER)
    return _ok("edit_report", resp)


def submit_report(report_id):
    resp = api_client.submit_report(report_id, OFFICER)
    return _ok("submit_report", resp)


def start_review(report_id, funder_id):
    resp = api_client.start_review_report(report_id, make_funder_headers(funder_id))
    return _ok("start_review", resp)


def accept_report(report_id, funder_id):
    resp = api_client.accept_report(report_id, make_funder_headers(funder_id))
    return _ok("accept_report", resp)


def return_report(report_id, funder_id, reason="needs detail"):
    resp = api_client.return_report(
        report_id, {"returned_reason": reason}, make_funder_headers(funder_id)
    )
    return _ok("return_report", resp)


def revise_report(report_id):
    resp = api_client.revise_report(report_id, OFFICER)
    return _ok("revise_report", resp)


def walk_report_to_accepted(report_id, funder_id):
    """DRAFT (already edited) -> SUBMITTED -> UNDER_REVIEW -> ACCEPTED."""
    submit_report(report_id)
    start_review(report_id, funder_id)
    return accept_report(report_id, funder_id)


# ---------------------------------------------------------------------------
# Tier 4: audit engagements, findings, suspension
# ---------------------------------------------------------------------------

def create_engagement(grant_id, **overrides):
    resp = api_client.create_audit_engagement(
        grant_id, create_audit_engagement_payload(**overrides), DIRECTOR
    )
    return _ok("create_engagement", resp)


def advance_engagement(engagement_id, steps=1):
    engagement = None
    for _ in range(steps):
        resp = api_client.advance_audit_engagement(engagement_id, AUDITOR)
        engagement = _ok("advance_engagement", resp)
    return engagement


def create_engagement_in_conducted(grant_id, **overrides):
    """Engagement advanced SCHEDULED -> PREPARATION -> READY -> CONDUCTED."""
    engagement = create_engagement(grant_id, **overrides)
    return advance_engagement(engagement["id"], steps=3)


def file_finding(engagement_id, severity="OBSERVATION", description="finding"):
    resp = api_client.create_audit_finding(
        engagement_id,
        create_audit_finding_payload(severity=severity, description=description),
        AUDITOR,
    )
    return _ok("file_finding", resp)


def suspend_grant_with_material_weakness(grant_id, **engagement_overrides):
    """Drive an ACTIVE grant into SUSPENDED by filing a MATERIAL_WEAKNESS on a
    CONDUCTED engagement. Returns (engagement, finding)."""
    engagement = create_engagement_in_conducted(grant_id, **engagement_overrides)
    finding = file_finding(
        engagement["id"], severity="MATERIAL_WEAKNESS", description="mw"
    )
    return engagement, finding


def resolve_finding(finding_id, response_text="fixed"):
    """OPEN -> RESPONSE_SUBMITTED -> RESOLVED."""
    resp = api_client.respond_audit_finding(finding_id, {"response_text": response_text}, OFFICER)
    _ok("respond_finding", resp)
    resp = api_client.resolve_audit_finding(finding_id, AUDITOR)
    return _ok("resolve_finding", resp)


# ---------------------------------------------------------------------------
# Tier 5: match contributions, modification requests, renewal
# ---------------------------------------------------------------------------

def create_match_contribution(grant_id, **overrides):
    resp = api_client.create_match_contribution(
        grant_id, create_match_contribution_payload(**overrides), OFFICER
    )
    return _ok("create_match_contribution", resp)


def document_contribution(contribution_id, documented_by=OFFICER):
    resp = api_client.document_match_contribution(
        contribution_id, {"documentation_ref": "doc-ref"}, documented_by
    )
    return _ok("document_contribution", resp)


def verify_contribution(contribution_id, verified_by=FINANCE):
    resp = api_client.verify_match_contribution(contribution_id, verified_by)
    return _ok("verify_contribution", resp)


def create_modification_request(grant_id, **overrides):
    resp = api_client.create_modification_request(
        grant_id, create_modification_request_payload(**overrides), OFFICER
    )
    return _ok("create_modification_request", resp)


def submit_modification_request(request_id):
    resp = api_client.submit_modification_request(request_id, DIRECTOR)
    return _ok("submit_modification_request", resp)


def create_submitted_modification(grant_id, **overrides):
    request = create_modification_request(grant_id, **overrides)
    submit_modification_request(request["id"])
    return request


def create_renewal_application(grant_id):
    resp = api_client.create_renewal_application(grant_id, OFFICER)
    return _ok("create_renewal_application", resp)


# ---------------------------------------------------------------------------
# Tier 6: report-period activity helpers
# ---------------------------------------------------------------------------

def post_activity_in_period(grant_id, budget_line_id, fund_id, amount_cents,
                            expense_date):
    """Record + post + fully allocate one expense. Returns the allocation."""
    expense, allocation = create_posted_allocated_expense(
        grant_id, budget_line_id, fund_id, amount_cents, expense_date=expense_date
    )
    return allocation


def accept_period_report(ctx, report, amount_cents=None, expense_date=None,
                         line=None):
    """Drive a SCHEDULED report to ACCEPTED, optionally posting one fully
    allocated expense against `line` (default ctx['lines'][0]) first."""
    if amount_cents is not None:
        line = line or ctx["lines"][0]
        post_activity_in_period(
            ctx["grant"]["id"], line["id"], ctx["fund"]["id"],
            amount_cents, expense_date or report["period_start"][:10],
        )
    start_report(report["id"])
    edit_report(report["id"])
    return walk_report_to_accepted(report["id"], ctx["funder"]["id"])
