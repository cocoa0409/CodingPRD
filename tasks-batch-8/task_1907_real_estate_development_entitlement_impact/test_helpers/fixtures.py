"""Composite setup helpers.

Every test runs against a fresh, empty database (the runner restarts the
server before each test), so each helper builds its own preconditions from
PRD-declared endpoints only.  Setup calls use the lenient `get_success_data`
validator so a broken precondition surfaces as a clear "Setup step failed"
rather than a confusing assertion deep in a test.

Identity threading: Applicant / StaffReviewer / DecisionAuthority are
entity-backed roles (PRD 2.1), so every ownership- or authorship-gated call
uses headers built from the actual registry row's id.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import CLOCK_DEFAULT_ISO, V1_RATES
from .factories import (
    create_applicant_payload,
    create_application_payload,
    create_condition_payload,
    create_decision_authority_payload,
    create_development_agreement_payload,
    create_fee_schedule_payload,
    create_hearing_payload,
    create_outreach_event_payload,
    create_project_payload,
    create_review_comment_payload,
    create_staff_reviewer_payload,
    file_appeal_payload,
    file_petition_payload,
    record_payment_payload,
    render_decision_payload,
    request_permit_payload,
    resolve_appeal_payload,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_decision_authority_headers,
    make_staff_reviewer_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 0 — primitive steps
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str = CLOCK_DEFAULT_ISO) -> Dict[str, Any]:
    """Set the logical clock (PlatformAdmin only, PRD 2.8)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_and_adopt_fee_schedule(
    label: str = "FY2026 Adopted",
    effective_date: str = CLOCK_DEFAULT_ISO,
    rates: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a fee schedule and adopt it (DRAFT -> ADOPTED, PRD 3.1)."""
    payload = create_fee_schedule_payload(
        schedule_label=label, effective_date=effective_date, **(rates or {})
    )
    schedule = get_success_data(api_client.create_fee_schedule(payload, ADMIN))
    return get_success_data(api_client.adopt_fee_schedule(schedule["id"], ADMIN))


def register_applicant(**overrides) -> Dict[str, Any]:
    """Register an applicant; the returned row's id is the Applicant identity."""
    return get_success_data(
        api_client.create_applicant(create_applicant_payload(**overrides), ADMIN)
    )


def register_reviewer(disciplines: Optional[List[str]] = None, **overrides) -> Dict[str, Any]:
    """Register a staff reviewer (default discipline PLANNING)."""
    payload = create_staff_reviewer_payload(
        disciplines=disciplines or ["PLANNING"], **overrides
    )
    return get_success_data(api_client.create_staff_reviewer(payload, ADMIN))


def register_authority(body: str = "CITY_COUNCIL", **overrides) -> Dict[str, Any]:
    """Register a decision authority (default body CITY_COUNCIL)."""
    payload = create_decision_authority_payload(body=body, **overrides)
    return get_success_data(api_client.create_decision_authority(payload, ADMIN))


def create_project_for(applicant: Dict[str, Any], **overrides) -> Dict[str, Any]:
    """Create a project owned by `applicant`, called with that applicant's
    identity so ownership checks thread correctly."""
    headers = make_applicant_headers(applicant["id"])
    payload = create_project_payload(applicant["id"], **overrides)
    return get_success_data(api_client.create_project(payload, headers))


def create_application_for(
    project: Dict[str, Any], applicant: Dict[str, Any], **overrides
) -> Dict[str, Any]:
    """Create a DRAFT application carrying the project's current version under
    the optimistic-concurrency rule (PRD 2.7)."""
    headers = make_applicant_headers(applicant["id"])
    payload = create_application_payload(
        project["id"], expected_project_version=project["version"], **overrides
    )
    return get_success_data(api_client.create_application(payload, headers))


def submit_application(application: Dict[str, Any], applicant: Dict[str, Any]) -> Dict[str, Any]:
    headers = make_applicant_headers(applicant["id"])
    return get_success_data(api_client.submit_application(application["id"], headers))


def get_application(app_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_application(app_id, headers or ADMIN))


def list_application_assessments(
    app_id: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict] = None,
) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(
        api_client.list_assessments(app_id, headers or ADMIN, params=params)
    )
    return data


def get_single_assessment(
    app_id: str,
    headers: Optional[Dict[str, str]] = None,
    variant: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the application's single assessment of the given variant."""
    params = {"variant": variant} if variant else None
    rows = list_application_assessments(app_id, headers, params=params)
    assert len(rows) == 1, f"Expected exactly one assessment, got {len(rows)}"
    return rows[0]


def pay_assessment(
    assessment_id: str,
    applicant: Dict[str, Any],
    amount: float,
    paid_at: str = "2026-08-02T00:00:00Z",
) -> Dict[str, Any]:
    headers = make_applicant_headers(applicant["id"])
    payload = record_payment_payload(amount=amount, paid_at=paid_at)
    return get_success_data(api_client.record_payment(assessment_id, payload, headers))


# ---------------------------------------------------------------------------
# Tier 1 — state progression for EntitlementApplication
# ---------------------------------------------------------------------------


def setup_submitted_application(
    project_overrides: Optional[Dict[str, Any]] = None,
    application_overrides: Optional[Dict[str, Any]] = None,
    rates: Optional[Dict[str, Any]] = None,
    schedule_label: str = "V1",
    with_reviewer: bool = False,
    with_authority: bool = False,
    reviewer_disciplines: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Clock at the default instant + ADOPTED schedule + applicant + project +
    DRAFT application + submitted.  Returns a context dict."""
    set_clock(CLOCK_DEFAULT_ISO)
    schedule = create_and_adopt_fee_schedule(label=schedule_label, rates=rates)
    applicant = register_applicant()
    project = create_project_for(applicant, **(project_overrides or {}))
    application = create_application_for(
        project, applicant, **(application_overrides or {})
    )
    application = submit_application(application, applicant)
    ctx: Dict[str, Any] = {
        "schedule": schedule,
        "applicant": applicant,
        "applicant_headers": make_applicant_headers(applicant["id"]),
        "project": project,
        "application": application,
    }
    if with_reviewer:
        reviewer = register_reviewer(disciplines=reviewer_disciplines)
        ctx["reviewer"] = reviewer
        ctx["reviewer_headers"] = make_staff_reviewer_headers(reviewer["id"])
    if with_authority:
        authority = register_authority()
        ctx["authority"] = authority
        ctx["authority_headers"] = make_decision_authority_headers(authority["id"])
    return ctx


def setup_under_review_application(
    reviewer_disciplines: Optional[List[str]] = None, **kwargs
) -> Dict[str, Any]:
    """Submitted application moved to UNDER_REVIEW by a registered reviewer."""
    kwargs["with_reviewer"] = True
    ctx = setup_submitted_application(
        reviewer_disciplines=reviewer_disciplines or ["PLANNING"], **kwargs
    )
    app = get_success_data(
        api_client.open_review(ctx["application"]["id"], ctx["reviewer_headers"])
    )
    ctx["application"] = app
    return ctx


def setup_decision_pending_application(**kwargs) -> Dict[str, Any]:
    """Application advanced to DECISION_PENDING (no hearings, posture LOW)."""
    ctx = setup_under_review_application(**kwargs)
    app = get_success_data(
        api_client.advance_to_decision(ctx["application"]["id"], ctx["reviewer_headers"])
    )
    ctx["application"] = app
    return ctx


def render_decision_now(
    ctx: Dict[str, Any],
    decision: str = "APPROVE",
    authority: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Render a decision with a fresh OCC read of the application version."""
    authority = authority or ctx.get("authority")
    if authority is None:
        authority = register_authority()
        ctx["authority"] = authority
        ctx["authority_headers"] = make_decision_authority_headers(authority["id"])
    auth_headers = make_decision_authority_headers(authority["id"])
    app_id = ctx["application"]["id"]
    current = get_application(app_id, auth_headers)
    payload = render_decision_payload(
        decided_by=authority["id"],
        expected_application_version=current["version"],
        decision=decision,
    )
    rendered = get_success_data(api_client.render_decision(app_id, payload, auth_headers))
    ctx["decision"] = rendered
    ctx["application"] = get_application(app_id, auth_headers)
    return rendered


def setup_approved_application(**kwargs) -> Dict[str, Any]:
    """Full lifecycle through APPROVED: submitted -> under review ->
    decision pending -> APPROVE rendered (decision RENDERED)."""
    kwargs["with_authority"] = True
    ctx = setup_decision_pending_application(**kwargs)
    render_decision_now(ctx, decision="APPROVE")
    return ctx


# ---------------------------------------------------------------------------
# Tier 2 — decision finality via the appeal path
# ---------------------------------------------------------------------------


def file_in_window_appeal(
    ctx: Dict[str, Any],
    grounds: str = "Procedural error",
    filed_at: Optional[str] = None,
) -> Dict[str, Any]:
    """File an appeal whose filed_at is the decision's effective date — always
    inside the appeal window no matter its length (PRD 3.9: only a filed_at on
    or after the appeal_deadline is refused)."""
    decision = ctx.get("decision") or {}
    effective = filed_at or decision.get("decision_effective_date") or "2026-08-01T00:00:00Z"
    payload = file_appeal_payload(filed_at=effective, grounds=grounds)
    appeal = get_success_data(
        api_client.file_appeal(ctx["application"]["id"], payload, ADMIN)
    )
    ctx["appeal"] = appeal
    return appeal


def resolve_appeal_now(ctx: Dict[str, Any], ruling: str = "UPHELD") -> Dict[str, Any]:
    authority = ctx["authority"]
    auth_headers = make_decision_authority_headers(authority["id"])
    resolved = get_success_data(
        api_client.resolve_appeal(ctx["appeal"]["id"], resolve_appeal_payload(ruling), auth_headers)
    )
    ctx["appeal"] = resolved
    return resolved


def finalize_decision_via_appeal(ctx: Dict[str, Any], ruling: str = "UPHELD") -> Dict[str, Any]:
    """Drive the rendered decision to FINAL (ruling UPHELD) or remand
    (ruling REVERSED) through the appeal path, without depending on the
    appeal-window length."""
    file_in_window_appeal(ctx)
    return resolve_appeal_now(ctx, ruling=ruling)


# ---------------------------------------------------------------------------
# Tier 3 — fees settled and permits
# ---------------------------------------------------------------------------


def pay_final_assessment_in_full(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Pay the FINAL assessment's full net_total (on time relative to its
    due date, the decision's effective date)."""
    final = get_single_assessment(
        ctx["application"]["id"], ctx["reviewer_headers"], variant="FINAL"
    )
    paid_at = ctx.get("decision", {}).get(
        "decision_effective_date", "2026-08-01T00:00:00Z"
    )
    pay_assessment(final["id"], ctx["applicant"], final["net_total"], paid_at=paid_at)
    return get_success_data(
        api_client.get_assessment(final["id"], ctx["reviewer_headers"])
    )


def setup_approved_with_fees_paid(**kwargs) -> Dict[str, Any]:
    """Approved application whose decision is FINAL (appeal UPHELD) and whose
    FINAL assessment is PAID — every permit-issuance precondition green."""
    ctx = setup_approved_application(**kwargs)
    finalize_decision_via_appeal(ctx, ruling="UPHELD")
    ctx["final_assessment"] = pay_final_assessment_in_full(ctx)
    return ctx


def request_permit(
    ctx: Dict[str, Any], permit_type: str = "GRADING"
) -> Dict[str, Any]:
    headers = make_applicant_headers(ctx["applicant"]["id"])
    return get_success_data(
        api_client.request_permit_sequence(
            ctx["application"]["id"],
            request_permit_payload(permit_type=permit_type),
            headers,
        )
    )


def issue_permit_now(ctx: Dict[str, Any], seq_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.issue_permit(seq_id, ctx["reviewer_headers"]))


# ---------------------------------------------------------------------------
# Tier 4 — hearings, outreach, conditions
# ---------------------------------------------------------------------------


def schedule_hearing(
    ctx: Dict[str, Any],
    hearing_date: str = "2026-08-25T00:00:00Z",
    notice_posted_date: str = "2026-08-01T00:00:00Z",
    hearing_body: str = "PLANNING_COMMISSION",
) -> Dict[str, Any]:
    payload = create_hearing_payload(
        hearing_date=hearing_date,
        notice_posted_date=notice_posted_date,
        hearing_body=hearing_body,
    )
    return get_success_data(
        api_client.create_hearing(ctx["application"]["id"], payload, ctx["reviewer_headers"])
    )


def record_outreach(
    ctx: Dict[str, Any], disposition: str, event_date: str, attendee_count: int = 10
) -> Dict[str, Any]:
    payload = create_outreach_event_payload(
        event_date=event_date, disposition=disposition, attendee_count=attendee_count
    )
    return get_success_data(
        api_client.create_outreach_event(
            ctx["application"]["id"], payload, ctx["reviewer_headers"]
        )
    )


def post_comment(
    ctx: Dict[str, Any],
    severity: str = "INFO",
    discipline: Optional[str] = None,
    comment_text: str = "Review comment",
    revises_comment_id: Optional[str] = None,
) -> Dict[str, Any]:
    reviewer = ctx["reviewer"]
    payload = create_review_comment_payload(
        reviewer["id"],
        discipline=discipline or reviewer["disciplines"][0],
        comment_text=comment_text,
        severity=severity,
    )
    if revises_comment_id is not None:
        payload["revises_comment_id"] = revises_comment_id
    return get_success_data(
        api_client.create_review_comment(
            ctx["application"]["id"], payload, ctx["reviewer_headers"]
        )
    )


def add_condition(
    ctx: Dict[str, Any],
    condition_text: str = "Pay impact fees prior to permit issuance",
    category: str = "FEE",
    required_before: str = "PERMIT_ISSUANCE",
) -> Dict[str, Any]:
    auth_headers = make_decision_authority_headers(ctx["authority"]["id"])
    payload = create_condition_payload(
        condition_text=condition_text, category=category, required_before=required_before
    )
    return get_success_data(
        api_client.create_condition(ctx["application"]["id"], payload, auth_headers)
    )


# ---------------------------------------------------------------------------
# Tier 5 — development agreements, petitions, vesting
# ---------------------------------------------------------------------------


def draft_and_adopt_da(
    ctx: Dict[str, Any],
    agreement_number: str = "ORD-0001",
    adoption_date: str = "2026-08-05T00:00:00Z",
    vesting_term_years: int = 5,
    registered_voters: int = 12500,
) -> Dict[str, Any]:
    """Draft a development agreement on the (approved) application and adopt
    it: DRAFT -> ADOPTED with vesting_status PENDING_REFERENDUM (PRD 3.8)."""
    auth_headers = make_decision_authority_headers(ctx["authority"]["id"])
    payload = create_development_agreement_payload(
        agreement_number=agreement_number,
        adoption_date=adoption_date,
        vesting_term_years=vesting_term_years,
        registered_voters=registered_voters,
    )
    da = get_success_data(
        api_client.create_development_agreement(
            ctx["application"]["id"], payload, auth_headers
        )
    )
    da = get_success_data(api_client.adopt_development_agreement(da["id"], auth_headers))
    ctx["da"] = da
    return da


def file_petition_now(
    ctx: Dict[str, Any],
    da: Dict[str, Any],
    valid_signature_count: int,
    filed_at: Optional[str] = None,
) -> Dict[str, Any]:
    """File a referendum petition.  Default filed_at equals the agreement's
    adoption_date so the filing is inside the referendum window regardless of
    the window's length (PRD 3.8)."""
    payload = file_petition_payload(
        filed_at=filed_at or da["adoption_date"],
        valid_signature_count=valid_signature_count,
    )
    return get_success_data(
        api_client.file_referendum_petition(da["id"], payload, ADMIN)
    )


def certify_petition_now(ctx: Dict[str, Any], petition_id: str) -> Dict[str, Any]:
    auth_headers = make_decision_authority_headers(ctx["authority"]["id"])
    return get_success_data(api_client.certify_referendum_petition(petition_id, auth_headers))


def finalize_vesting_now(ctx: Dict[str, Any], da_id: str) -> Dict[str, Any]:
    auth_headers = make_decision_authority_headers(ctx["authority"]["id"])
    return get_success_data(api_client.finalize_vesting(da_id, auth_headers))
