"""Composite setup helpers for the Research Funding API.

Fixtures encapsulate multi-step preambles so tests focus on assertions, not plumbing.

Identity-threading rule (PRD §2.1):
- Per PRD §2.1, X-User-ID is opaque for all roles. BUT: owner-gated operations
  (project submit, begin-closing, pi-approve, rework, audit submit/resubmit)
  compare X-User-ID to Project.principal_investigator_id (the value passed in
  the project create payload). Fixtures that create a project pass DEFAULT_PI_ID
  as principal_investigator_id, so make_principal_investigator_headers(pi_id=DEFAULT_PI_ID)
  works for any operation gated on that project's owner. Tests that need a
  different PI identity must propagate the chosen pi id consistently from
  create to all owner-gated calls.

All fixtures use get_success_data() (lenient) so setup failures yield clear
"Setup failed" errors, not assertion noise.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client, ApiClient
from .factories import (
    create_project_payload,
    create_budget_item_payload,
    create_peer_review_payload,
    create_budget_adjustment_payload,
    create_reimbursement_payload,
    create_compliance_rule_payload,
    create_closing_audit_payload,
    create_allocation_run_payload,
    line_change,
    deliverable,
    audit_finding,
    attachment,
    reject_payload,
)
from .test_users import (
    DEFAULT_PI_ID,
    TEST_USERS,
    make_principal_investigator_headers,
    make_dept_approver_headers,
    make_finance_officer_headers,
    make_research_admin_headers,
    make_audit_officer_headers,
    make_peer_reviewer_headers,
    make_test_driver_headers,
)


# Convenient handles
PI_HEADERS = TEST_USERS["pi_headers"]
DEPT_HEADERS = TEST_USERS["dept_headers"]
DEPT_HEADERS_ALT = TEST_USERS["dept_headers_alt"]
FINANCE_HEADERS = TEST_USERS["finance_headers"]
FINANCE_HEADERS_ALT = TEST_USERS["finance_headers_alt"]
ADMIN_HEADERS = TEST_USERS["research_admin_headers"]
AUDIT_HEADERS = TEST_USERS["audit_officer_headers"]
TEST_DRIVER_HEADERS = TEST_USERS["test_driver_headers"]


# --- Time helpers --------------------------------------------------------------

def _server_clock_now(api: ApiClient) -> datetime:
    """Read the server's logical clock via api_request_timestamp meta on a
    cheap GET. Falls back to wall clock if the response is malformed."""
    resp = api.list_projects(ADMIN_HEADERS, params={"limit": 1, "offset": 0})
    try:
        body = resp.json()
        ts = body.get("meta", {}).get("api_request_timestamp")
        if ts:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        pass
    return datetime.now(timezone.utc)


def _epoch(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def future_dates(api: ApiClient, *, start_offset_days: int = 1, duration_days: int = 365) -> Tuple[int, int]:
    """Return (planned_start_date, planned_end_date) as Unix epoch seconds, both in the future
    relative to the server's logical clock."""
    now = _server_clock_now(api)
    start = now + timedelta(days=start_offset_days)
    end = start + timedelta(days=duration_days)
    return _epoch(start), _epoch(end)


def now_epoch(api: ApiClient) -> int:
    """Return the server's logical-clock 'now' as Unix epoch seconds."""
    return _epoch(_server_clock_now(api))


def advance_clock_to(api: ApiClient, target: datetime) -> None:
    """Advance the server's logical clock to a target datetime via the test-only endpoint."""
    headers = make_test_driver_headers()
    resp = api.advance_clock(_iso_z(target), headers)
    get_success_data(resp)


def advance_clock_by_days(api: ApiClient, days: int) -> None:
    """Advance the server's logical clock forward by N days from its current value."""
    now = _server_clock_now(api)
    advance_clock_to(api, now + timedelta(days=days))


# --- Tier 1: state progression — project lifecycle ----------------------------

def create_draft_project(api: ApiClient = api_client, *,
                          pi_id: str = DEFAULT_PI_ID,
                          funding_source: str = "NATIONAL",
                          start_offset_days: int = 1,
                          duration_days: int = 365,
                          requested_amount: float = 100000.00,
                          **overrides) -> Dict[str, Any]:
    """Create a Project in DRAFT status. Pi headers are derived from pi_id.

    If `planned_start_date` and/or `planned_end_date` are passed in overrides,
    they take precedence over the values derived from start_offset_days/duration_days.
    """
    start_epoch, end_epoch = future_dates(api,
                                           start_offset_days=start_offset_days,
                                           duration_days=duration_days)
    # Allow callers to override the dates explicitly.
    start_epoch = overrides.pop("planned_start_date", start_epoch)
    end_epoch = overrides.pop("planned_end_date", end_epoch)
    payload = create_project_payload(
        principal_investigator_id=pi_id,
        funding_source=funding_source,
        planned_start_date=start_epoch,
        planned_end_date=end_epoch,
        requested_amount=requested_amount,
        **overrides,
    )
    headers = make_principal_investigator_headers(pi_id)
    resp = api.create_project(payload, headers)
    return get_success_data(resp)


def add_budget_item(api: ApiClient, project: Dict[str, Any], *,
                     category: str, requested_amount: float,
                     pi_id: Optional[str] = None) -> Dict[str, Any]:
    """Append a BudgetItem under a DRAFT project."""
    if pi_id is None:
        pi_id = project["principal_investigator_id"]
    headers = make_principal_investigator_headers(pi_id)
    payload = create_budget_item_payload(category=category, requested_amount=requested_amount)
    resp = api.create_budget_item(project["id"], payload, headers)
    return get_success_data(resp)


def submit_project(api: ApiClient, project: Dict[str, Any]) -> Dict[str, Any]:
    headers = make_principal_investigator_headers(project["principal_investigator_id"])
    resp = api.submit_project(project["id"], headers)
    return get_success_data(resp)


def append_peer_review(api: ApiClient, project_id: str, *,
                        recommendation: str = "APPROVE",
                        reviewer_id: Optional[str] = None,
                        score: int = 80) -> Dict[str, Any]:
    """Append one peer review for a project (the project must be UNDER_REVIEW)."""
    if reviewer_id is None:
        reviewer_id = f"peer-reviewer-{uuid.uuid4().hex[:6]}"
    headers = make_peer_reviewer_headers(reviewer_id)
    payload = create_peer_review_payload(reviewer_id=reviewer_id,
                                          recommendation=recommendation,
                                          score=score)
    resp = api.create_peer_review(project_id, payload, headers)
    return get_success_data(resp)


def add_three_approving_reviews(api: ApiClient, project_id: str) -> List[Dict[str, Any]]:
    """Add three APPROVE peer reviews — sufficient to satisfy approve preconditions."""
    return [append_peer_review(api, project_id, recommendation="APPROVE",
                                reviewer_id=f"reviewer-{i}-{uuid.uuid4().hex[:4]}")
            for i in range(3)]


def approve_project(api: ApiClient, project_id: str) -> Dict[str, Any]:
    """Approve a project as ResearchAdmin (no peer-review work; caller must have set
    up reviews via add_three_approving_reviews first)."""
    resp = api.approve_project(project_id, ADMIN_HEADERS)
    return get_success_data(resp)


def activate_project(api: ApiClient, project_id: str) -> Dict[str, Any]:
    """Activate a project as ResearchAdmin. Caller must ensure now() >= planned_start_date
    (use advance_clock_to)."""
    resp = api.activate_project(project_id, ADMIN_HEADERS)
    return get_success_data(resp)


def create_and_approve_project(api: ApiClient = api_client, *,
                                pi_id: str = DEFAULT_PI_ID,
                                funding_source: str = "NATIONAL",
                                budget_items: Optional[List[Tuple[str, float]]] = None,
                                start_offset_days: int = 1,
                                duration_days: int = 365,
                                ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Create a project, attach budget items, submit it, append 3 approving peer reviews,
    and approve it (status=APPROVED, project_code minted, BudgetItems APPROVED).

    Returns (project, budget_items).
    """
    if budget_items is None:
        budget_items = [("MATERIALS", 1000.00)]
    project = create_draft_project(api, pi_id=pi_id, funding_source=funding_source,
                                    start_offset_days=start_offset_days,
                                    duration_days=duration_days)
    items = [add_budget_item(api, project,
                              category=cat, requested_amount=amt,
                              pi_id=pi_id) for (cat, amt) in budget_items]
    submit_project(api, project)
    add_three_approving_reviews(api, project["id"])
    project = approve_project(api, project["id"])
    # Re-read budget items so we have the APPROVED rows with approved_amount set.
    items = _list_budget_items(api, project["id"])
    return project, items


def create_and_activate_project(api: ApiClient = api_client, *,
                                 pi_id: str = DEFAULT_PI_ID,
                                 funding_source: str = "NATIONAL",
                                 budget_items: Optional[List[Tuple[str, float]]] = None,
                                 start_offset_days: int = 1,
                                 duration_days: int = 365,
                                 ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Create a project, approve it, advance the clock past planned_start_date, and activate it.

    Returns (project, budget_items).
    """
    project, items = create_and_approve_project(api,
                                                  pi_id=pi_id,
                                                  funding_source=funding_source,
                                                  budget_items=budget_items,
                                                  start_offset_days=start_offset_days,
                                                  duration_days=duration_days)
    # Activation requires now() >= planned_start_date.
    target = datetime.fromtimestamp(project["planned_start_date"] + 60, tz=timezone.utc)
    advance_clock_to(api, target)
    project = activate_project(api, project["id"])
    # Refresh items in case anything cascades on activation.
    items = _list_budget_items(api, project["id"])
    return project, items


def _list_budget_items(api: ApiClient, project_id: str) -> List[Dict[str, Any]]:
    resp = api.list_budget_items(project_id, ADMIN_HEADERS, params={"limit": 100, "offset": 0})
    body = get_success_data(resp)
    # Could be either a list (data is array) or a dict with embedded list — we only feed this
    # function inside fixtures, so assume body is the raw list.
    if isinstance(body, list):
        return body
    if isinstance(body, dict) and "items" in body:
        return body["items"]
    # Fallback: re-parse from raw response
    raw = api.list_budget_items(project_id, ADMIN_HEADERS, params={"limit": 100, "offset": 0}).json()
    data = raw.get("data", [])
    return data if isinstance(data, list) else []


def list_audit_logs(api: ApiClient, *,
                     subject_type: Optional[str] = None,
                     subject_id: Optional[str] = None,
                     limit: int = 100) -> List[Dict[str, Any]]:
    """Read audit-log rows, optionally filtered. Uses AuditOfficer headers."""
    params: Dict[str, Any] = {"limit": limit, "offset": 0}
    if subject_type is not None:
        params["subject_type"] = subject_type
    if subject_id is not None:
        params["subject_id"] = subject_id
    raw = api.list_audit_logs(AUDIT_HEADERS, params=params).json()
    data = raw.get("data", [])
    return data if isinstance(data, list) else []


# --- Tier 2: entity hierarchy -------------------------------------------------

def setup_active_project_with_budget(api: ApiClient = api_client, *,
                                      pi_id: str = DEFAULT_PI_ID,
                                      funding_source: str = "NATIONAL",
                                      categories: Optional[List[Tuple[str, float]]] = None,
                                      ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Common scenario: create + approve + activate a project with one or more
    APPROVED budget items. Returns (project, budget_items)."""
    if categories is None:
        categories = [("MATERIALS", 2000.00)]
    return create_and_activate_project(api, pi_id=pi_id, funding_source=funding_source,
                                        budget_items=categories)


# --- Tier 3: reimbursement lifecycle shortcuts --------------------------------

def create_reimbursement(api: ApiClient, *, project: Dict[str, Any],
                          budget_item: Dict[str, Any],
                          amount: float = 100.00,
                          invoice_number: Optional[str] = None,
                          invoice_authenticated: bool = True,
                          attachments: Optional[List[Dict[str, str]]] = None,
                          vendor_id: Optional[str] = None,
                          invoice_date: Optional[int] = None,
                          expense_category: Optional[str] = None,
                          ) -> Dict[str, Any]:
    """Create a Reimbursement DRAFT.

    invoice_date defaults to halfway between planned_start_date and now(); set
    invoice_authenticated=False or attachments=[] to deliberately exercise rejection paths.
    """
    pi_id = project["principal_investigator_id"]
    headers = make_principal_investigator_headers(pi_id)
    if invoice_date is None:
        # Pick a date inside [planned_start_date, now()]
        invoice_date = max(project["planned_start_date"], now_epoch(api) - 60)
    if expense_category is None:
        expense_category = budget_item["category"]
    payload = create_reimbursement_payload(
        project_id=project["id"],
        budget_item_id=budget_item["id"],
        expense_category=expense_category,
        amount=amount,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        invoice_authenticated=invoice_authenticated,
        attachments=attachments,
        vendor_id=vendor_id,
    )
    resp = api.create_reimbursement(payload, headers)
    return get_success_data(resp)


def submit_reimbursement(api: ApiClient, reimbursement: Dict[str, Any],
                          *, pi_id: Optional[str] = None) -> Dict[str, Any]:
    if pi_id is None:
        # Look up the project to find the pi_id.
        project = _get_project(api, reimbursement["project_id"])
        pi_id = project["principal_investigator_id"]
    headers = make_principal_investigator_headers(pi_id)
    resp = api.submit_reimbursement(reimbursement["id"], headers)
    return get_success_data(resp)


def pi_approve_reimbursement(api: ApiClient, reimbursement: Dict[str, Any],
                              *, pi_id: Optional[str] = None) -> Dict[str, Any]:
    if pi_id is None:
        project = _get_project(api, reimbursement["project_id"])
        pi_id = project["principal_investigator_id"]
    headers = make_principal_investigator_headers(pi_id)
    resp = api.pi_approve_reimbursement(reimbursement["id"], headers)
    return get_success_data(resp)


def dept_approve_reimbursement(api: ApiClient, reimbursement: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.dept_approve_reimbursement(reimbursement["id"], DEPT_HEADERS)
    return get_success_data(resp)


def finance_approve_reimbursement(api: ApiClient, reimbursement: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.finance_approve_reimbursement(reimbursement["id"], FINANCE_HEADERS)
    return get_success_data(resp)


def mark_paid_reimbursement(api: ApiClient, reimbursement: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.mark_paid_reimbursement(reimbursement["id"], FINANCE_HEADERS)
    return get_success_data(resp)


def _get_project(api: ApiClient, project_id: str) -> Dict[str, Any]:
    resp = api.get_project(project_id, ADMIN_HEADERS)
    return get_success_data(resp)


def get_reimbursement(api: ApiClient, reimbursement_id: str) -> Dict[str, Any]:
    resp = api.get_reimbursement(reimbursement_id, ADMIN_HEADERS)
    return get_success_data(resp)


def get_budget_item(api: ApiClient, budget_item_id: str) -> Dict[str, Any]:
    resp = api.get_budget_item(budget_item_id, ADMIN_HEADERS)
    return get_success_data(resp)


def get_project(api: ApiClient, project_id: str) -> Dict[str, Any]:
    return _get_project(api, project_id)


def get_audit(api: ApiClient, audit_id: str) -> Dict[str, Any]:
    resp = api.get_closing_audit(audit_id, ADMIN_HEADERS)
    return get_success_data(resp)


def create_and_pay_reimbursement(api: ApiClient, *, project: Dict[str, Any],
                                  budget_item: Dict[str, Any],
                                  amount: float,
                                  invoice_number: Optional[str] = None,
                                  vendor_id: Optional[str] = None,
                                  ) -> Dict[str, Any]:
    """Walk a reimbursement through DRAFT → SUBMITTED → UNDER_REVIEW → APPROVED → PAID.

    Use to create historical paid spending for execution-rate / indirect-cost tests.
    """
    r = create_reimbursement(api, project=project, budget_item=budget_item,
                              amount=amount, invoice_number=invoice_number,
                              vendor_id=vendor_id)
    submit_reimbursement(api, r)
    pi_approve_reimbursement(api, r)
    dept_approve_reimbursement(api, r)
    finance_approve_reimbursement(api, r)
    return mark_paid_reimbursement(api, r)


def create_and_approve_reimbursement(api: ApiClient, *, project: Dict[str, Any],
                                      budget_item: Dict[str, Any], amount: float,
                                      invoice_number: Optional[str] = None,
                                      vendor_id: Optional[str] = None,
                                      ) -> Dict[str, Any]:
    """Walk a reimbursement through DRAFT → ... → APPROVED (not PAID)."""
    r = create_reimbursement(api, project=project, budget_item=budget_item,
                              amount=amount, invoice_number=invoice_number,
                              vendor_id=vendor_id)
    submit_reimbursement(api, r)
    pi_approve_reimbursement(api, r)
    dept_approve_reimbursement(api, r)
    return finance_approve_reimbursement(api, r)


def create_and_submit_reimbursement(api: ApiClient, *, project: Dict[str, Any],
                                     budget_item: Dict[str, Any],
                                     amount: float,
                                     invoice_number: Optional[str] = None,
                                     vendor_id: Optional[str] = None,
                                     ) -> Dict[str, Any]:
    """Walk a reimbursement through DRAFT → SUBMITTED only."""
    r = create_reimbursement(api, project=project, budget_item=budget_item,
                              amount=amount, invoice_number=invoice_number,
                              vendor_id=vendor_id)
    return submit_reimbursement(api, r)


# --- Tier 4: budget-adjustment lifecycle -------------------------------------

def create_zero_sum_adjustment(api: ApiClient, *, project: Dict[str, Any],
                                lines: List[Tuple[str, float]],
                                justification: Optional[str] = None,
                                pi_id: Optional[str] = None) -> Dict[str, Any]:
    """Create a BudgetAdjustment DRAFT with the supplied (budget_item_id, delta) lines."""
    if pi_id is None:
        pi_id = project["principal_investigator_id"]
    headers = make_principal_investigator_headers(pi_id)
    line_changes = [line_change(bid, delta) for (bid, delta) in lines]
    payload = create_budget_adjustment_payload(
        project_id=project["id"],
        line_changes=line_changes,
        justification=justification or
            "Reallocating funds between budget categories for unforeseen experimental needs.",
    )
    resp = api.create_budget_adjustment(payload, headers)
    return get_success_data(resp)


def submit_adjustment(api: ApiClient, adjustment: Dict[str, Any], *, pi_id: Optional[str] = None) -> Dict[str, Any]:
    if pi_id is None:
        project = _get_project(api, adjustment["project_id"])
        pi_id = project["principal_investigator_id"]
    headers = make_principal_investigator_headers(pi_id)
    resp = api.submit_budget_adjustment(adjustment["id"], headers)
    return get_success_data(resp)


def dept_approve_adjustment(api: ApiClient, adjustment: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.dept_approve_budget_adjustment(adjustment["id"], DEPT_HEADERS)
    return get_success_data(resp)


def finance_approve_adjustment(api: ApiClient, adjustment: Dict[str, Any]) -> Dict[str, Any]:
    resp = api.finance_approve_budget_adjustment(adjustment["id"], FINANCE_HEADERS)
    return get_success_data(resp)


def submit_and_dept_approve_adjustment(api: ApiClient, adjustment: Dict[str, Any]) -> Dict[str, Any]:
    submit_adjustment(api, adjustment)
    return dept_approve_adjustment(api, adjustment)


# --- Tier 5: closing-audit / finalization ------------------------------------

def begin_closing(api: ApiClient, project: Dict[str, Any], *, pi_id: Optional[str] = None) -> Dict[str, Any]:
    if pi_id is None:
        pi_id = project["principal_investigator_id"]
    headers = make_principal_investigator_headers(pi_id)
    resp = api.begin_closing(project["id"], headers)
    return get_success_data(resp)


def create_closing_audit(api: ApiClient, *, project: Dict[str, Any],
                          residual_fund_action: str = "RETURN",
                          deliverables: Optional[List[Dict[str, str]]] = None,
                          audit_findings: Optional[List[Dict[str, Any]]] = None,
                          pi_id: Optional[str] = None) -> Dict[str, Any]:
    if pi_id is None:
        pi_id = project["principal_investigator_id"]
    headers = make_principal_investigator_headers(pi_id)
    payload = create_closing_audit_payload(
        project_id=project["id"],
        residual_fund_action=residual_fund_action,
        deliverables=deliverables,
        audit_findings=audit_findings,
    )
    resp = api.create_closing_audit(payload, headers)
    return get_success_data(resp)


def submit_closing_audit(api: ApiClient, audit: Dict[str, Any], *, project: Optional[Dict[str, Any]] = None,
                          pi_id: Optional[str] = None) -> Dict[str, Any]:
    if pi_id is None:
        if project is not None:
            pi_id = project["principal_investigator_id"]
        else:
            project = _get_project(api, audit["project_id"])
            pi_id = project["principal_investigator_id"]
    headers = make_principal_investigator_headers(pi_id)
    resp = api.submit_closing_audit(audit["id"], headers)
    return get_success_data(resp)


def setup_project_in_closing(api: ApiClient = api_client, *,
                              pi_id: str = DEFAULT_PI_ID,
                              funding_source: str = "NATIONAL",
                              total_budget_amount: float = 1000.00,
                              paid_amount: float = 0.00,
                              category: str = "MATERIALS",
                              ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Create + approve + activate a project, optionally pay one reimbursement, then begin-closing.

    Returns (project, budget_items). The project ends in CLOSING state with no open reimbursements.
    """
    project, items = setup_active_project_with_budget(
        api,
        pi_id=pi_id,
        funding_source=funding_source,
        categories=[(category, total_budget_amount)],
    )
    if paid_amount > 0:
        create_and_pay_reimbursement(api,
                                      project=project,
                                      budget_item=items[0],
                                      amount=paid_amount)
    project = begin_closing(api, project, pi_id=pi_id)
    items = _list_budget_items(api, project["id"])
    return project, items


# --- Compliance rule helpers --------------------------------------------------

def create_compliance_rule(api: ApiClient, *,
                            rule_code: str,
                            applies_to_funding_source: str = "ALL",
                            applies_to_category: str = "ALL",
                            parameters: Optional[Dict[str, Any]] = None,
                            severity: str = "WARN",
                            active: bool = True) -> Dict[str, Any]:
    payload = create_compliance_rule_payload(
        rule_code=rule_code,
        applies_to_funding_source=applies_to_funding_source,
        applies_to_category=applies_to_category,
        parameters=parameters,
        severity=severity,
        active=active,
    )
    resp = api.create_compliance_rule(payload, ADMIN_HEADERS)
    return get_success_data(resp)


# --- Difficulty-design composite fixtures ------------------------------------

def setup_two_projects_with_paid_materials(api: ApiClient = api_client) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Setup for the indirect_cost_periodic vs closing_cascade difficulty instance.

    Two ACTIVE projects (both NATIONAL by default for predictable rate; one over the
    1M threshold to exercise the threshold-tier reduction), each with one PAID
    reimbursement under MATERIALS so DIRECT_COST base is non-zero. The caller can
    further configure per project.
    """
    p1, items1 = setup_active_project_with_budget(
        api,
        pi_id="pi-multi-1",
        funding_source="NATIONAL",
        categories=[("MATERIALS", 800000.00)],
    )
    create_and_pay_reimbursement(api, project=p1, budget_item=items1[0], amount=300.00)
    p2, items2 = setup_active_project_with_budget(
        api,
        pi_id="pi-multi-2",
        funding_source="PROVINCIAL",
        categories=[("MATERIALS", 600000.00)],
    )
    create_and_pay_reimbursement(api, project=p2, budget_item=items2[0], amount=200.00)
    return get_project(api, p1["id"]), get_project(api, p2["id"])


def setup_project_for_execution_rate(api: ApiClient = api_client) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """Setup for the execution_rate_chronological_vs_forward difficulty instance.

    Builds a project with:
      - Approved budget total 2000 in MATERIALS
      - One PAID reimbursement of 1000 (numerator under chronological)
      - One APPROVED-but-not-PAID reimbursement of 500 (numerator under forward only)
    Then begin-closing. Returns (project, items, approved_reimb).
    """
    project, items = setup_active_project_with_budget(
        api,
        pi_id="pi-exec-rate",
        funding_source="NATIONAL",
        categories=[("MATERIALS", 2000.00)],
    )
    item = items[0]
    create_and_pay_reimbursement(api, project=project, budget_item=item, amount=1000.00,
                                  invoice_number=f"INV-PAID-{uuid.uuid4().hex[:6]}")
    approved_r = create_and_approve_reimbursement(api, project=project, budget_item=item,
                                                    amount=500.00,
                                                    invoice_number=f"INV-APPR-{uuid.uuid4().hex[:6]}")
    project = begin_closing(api, project)
    return get_project(api, project["id"]), _list_budget_items(api, project["id"]), approved_r


def setup_project_with_two_budget_items_and_versions(api: ApiClient = api_client,
                                                        *, item_a_amount: float = 1000.00,
                                                        item_b_amount: float = 500.00,
                                                        ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Setup for the version-pin difficulty instance.

    Active project with TWO BudgetItems (A, B). Returns (project, item_A, item_B)."""
    project, items = setup_active_project_with_budget(
        api,
        pi_id=f"pi-versions-{uuid.uuid4().hex[:4]}",
        funding_source="NATIONAL",
        categories=[("MATERIALS", item_a_amount), ("EQUIPMENT", item_b_amount)],
    )
    a, b = items[0], items[1]
    return project, a, b


def add_two_pending_reviews(api: ApiClient, project_id: str) -> List[Dict[str, Any]]:
    """Add exactly two APPROVE peer reviews — used to test the empty-set boundary
    (count == 2 < 3 should yield ERR_INSUFFICIENT_REVIEWS at approve)."""
    return [append_peer_review(api, project_id, recommendation="APPROVE",
                                reviewer_id=f"reviewer-{i}-{uuid.uuid4().hex[:4]}")
            for i in range(2)]


def setup_project_in_under_review(api: ApiClient = api_client, *,
                                    pi_id: str = DEFAULT_PI_ID,
                                    funding_source: str = "NATIONAL",
                                    budget_items: Optional[List[Tuple[str, float]]] = None,
                                    n_reviews: int = 0,
                                    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Create a project, attach budget items, submit it. Optionally append n APPROVE
    peer reviews. Returns (project, items) — the project is in UNDER_REVIEW."""
    if budget_items is None:
        budget_items = [("MATERIALS", 1000.00)]
    project = create_draft_project(api, pi_id=pi_id, funding_source=funding_source)
    items = [add_budget_item(api, project, category=cat, requested_amount=amt, pi_id=pi_id)
             for (cat, amt) in budget_items]
    project = submit_project(api, project)
    for i in range(n_reviews):
        append_peer_review(api, project["id"], recommendation="APPROVE",
                            reviewer_id=f"r-{uuid.uuid4().hex[:6]}")
    return project, items


def reject_reimbursement_cycle(api: ApiClient, reimbursement_id: str) -> Dict[str, Any]:
    """Submit → pi-approve → dept-approve → reject. Used to bump rework_count by 1."""
    r = get_reimbursement(api, reimbursement_id)
    submit_reimbursement(api, r)
    r = get_reimbursement(api, reimbursement_id)
    pi_approve_reimbursement(api, r)
    r = get_reimbursement(api, reimbursement_id)
    dept_approve_reimbursement(api, r)
    resp = api.reject_reimbursement(reimbursement_id,
                                     reject_payload(rejection_reason=f"cycle ${uuid.uuid4().hex[:4]}"),
                                     DEPT_HEADERS)
    return get_success_data(resp)
