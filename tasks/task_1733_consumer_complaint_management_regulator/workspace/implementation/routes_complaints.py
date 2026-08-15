"""Complaint intake, lifecycle actions, and audit trail (PRD §3.2-§3.5)."""
from datetime import timedelta

from flask import g, request, Blueprint

import services as svc
from db import store
from errors import (
    ApiError,
    ERR_CATEGORY_RETIRED,
    ERR_ESCALATION_OPEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
    ERR_PRODUCT_FROZEN,
    ERR_QA_PASS_REQUIRED,
    ERR_RCA_REQUIRED,
    ERR_REFERRAL_OPEN,
    ERR_RETENTION_EXPIRED,
    ERR_SOD_SELF_REVIEW,
    ERR_STALE_VERSION,
    ERR_TEMPLATE_MISMATCH,
    ERR_TEMPLATE_NOT_ACTIVE,
)
from middleware import (
    ALL_ROLES,
    get_body,
    opt_int,
    opt_str,
    pagination_params,
    req_int,
    req_nonempty_str,
    req_str,
    require_roles,
)
from response import ok, ok_list
from timeutil import add_years, iso

bp = Blueprint("complaints", __name__)

INTAKE_ROLES = ("IntakeSpecialist", "CaseHandler")
HANDLER = ("CaseHandler",)
EVENT_READERS = ("ComplaintManager", "CaseHandler", "QAReviewer", "RemediationApprover", "ExecutiveReviewer", "Auditor")
REOPEN_WITHDRAW = ("CaseHandler", "ComplaintManager")
NON_TERMINAL = ("INTAKE", "TRIAGED", "INVESTIGATING", "RESPONSE_DRAFTED", "RESPONSE_QA")


def _set_terminal(complaint):
    """Terminal side effects shared by resolve and withdraw."""
    complaint.resolved_at = store.now()
    complaint.retention_purge_at = add_years(complaint.resolved_at, svc.RETENTION_YEARS)


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------

@bp.post("/complaints")
@require_roles(*INTAKE_ROLES)
def create_complaint():
    body = get_body()
    # Existence (priority 3): business codes in the body resolve to live records.
    ch_code = body.get("channel_code")
    pr_code = body.get("product_code")
    cat_code = body.get("category_code")
    if isinstance(ch_code, str):
        svc.channel_by_code(ch_code)
    if isinstance(pr_code, str):
        svc.product_by_code(pr_code)
    if isinstance(cat_code, str):
        svc.category_by_code(cat_code)
    # Request shape (priority 4).
    complainant_ref = req_str(body, "complainant_ref")
    channel_code = req_str(body, "channel_code")
    product_code = req_str(body, "product_code")
    category_code = req_str(body, "category_code")
    narrative = req_str(body, "narrative")
    claimed = opt_int(body, "claimed_loss_cents", 0, minimum=0)
    portal_ref = opt_str(body, "portal_ref", None)
    channel = store.channel_by_code[channel_code]
    product = store.product_by_code[product_code]
    category = store.category_by_code[category_code]
    # Business rules: posture gate (5) before taxonomy retirement (9).
    if product.posture == "FROZEN":
        raise ApiError(ERR_PRODUCT_FROZEN, "Product posture is FROZEN; complaint intake is rejected.", 409)
    if category.retired:
        raise ApiError(ERR_CATEGORY_RETIRED, "Retired taxonomy categories cannot be assigned at intake.", 409)
    now = store.now()
    c = svc.fresh_rec(
        complainant_ref=complainant_ref,
        channel_code=channel_code,
        product_code=product_code,
        category_code=category_code,
        received_at=now,
        narrative=narrative,
        claimed_loss_cents=claimed,
        status="INTAKE",
        response_text=None,
        response_template_key=None,
        resolved_at=None,
        approved_restitution_cents=0,
        paid_restitution_cents=0,
        timeliness_score=None,
        owner_user_id=g.user_id,
        retention_purge_at=None,
    )
    store.complaints[c.id] = c
    svc.append_event(c.id, "CREATED", {"status": "INTAKE"})
    # Atomic regulator-portal referral (referral_auto_creation calculation).
    if channel.is_regulator_portal:
        ref = svc.fresh_rec(
            complaint_id=c.id,
            portal_ref=portal_ref if portal_ref is not None else f"AUTO-{c.id}",
            received_via_portal_at=c.received_at,
            response_due_at=c.received_at + timedelta(days=svc.REFERRAL_RESPONSE_DAYS),
            submitted_at=None,
            timeliness="PENDING",
            status="OPEN",
            response_text=None,
        )
        store.referrals[ref.id] = ref
        svc.append_event(c.id, "REFERRAL_FILED", {"referral_id": ref.id, "portal_ref": ref.portal_ref})
    svc.recompute_posture(product)
    return ok(svc.ser_complaint(c), 201)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@bp.get("/complaints/<complaintId>")
@require_roles(*ALL_ROLES)
def get_complaint(complaintId):
    return ok(svc.ser_complaint(svc.get_complaint(complaintId)), 200)


@bp.get("/complaints")
@require_roles(*ALL_ROLES)
def list_complaints():
    limit, offset = pagination_params()
    recs = list(store.complaints.values())
    for param in ("status", "product_code", "channel_code", "category_code"):
        v = request.args.get(param)
        if v is not None:
            recs = [c for c in recs if getattr(c, param) == v]
    items, total = svc.paged(recs, svc.ser_complaint, limit, offset)
    return ok_list(items, total, limit, offset)


@bp.get("/complaints/<cid>/events")
@require_roles(*EVENT_READERS)
def list_events(cid):
    svc.get_complaint(cid)
    limit, offset = pagination_params()
    recs = [e for e in store.events.values() if e.complaint_id == cid]
    # Audit trail order: event_at ASC, created_at ASC (creation sequence tiebreak).
    ordered = sorted(recs, key=lambda e: (e.event_at, e.created_at, e._seq))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([svc.ser_event(e) for e in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Lifecycle actions
# ---------------------------------------------------------------------------

@bp.post("/complaints/<complaintId>/triage")
@require_roles(*HANDLER)
def triage(complaintId):
    c = svc.get_complaint(complaintId)
    if c.status != "INTAKE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, f"Complaint status is {c.status}; triage requires INTAKE.", 409)
    category = store.category_by_code.get(c.category_code)
    if category is not None and category.retired:
        raise ApiError(ERR_CATEGORY_RETIRED, "Cannot triage: the complaint's taxonomy category is retired.", 409)
    old = c.status
    c.status = "TRIAGED"
    svc.touch(c)
    svc.append_event(c.id, "STATUS_CHANGED", {"old_status": old, "new_status": "TRIAGED"})
    svc.recompute_posture(store.product_by_code[c.product_code])
    return ok(svc.ser_complaint(c), 200)


@bp.post("/complaints/<complaintId>/start_investigation")
@require_roles(*HANDLER)
def start_investigation(complaintId):
    c = svc.get_complaint(complaintId)
    if c.status not in ("TRIAGED", "REOPENED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            f"Complaint status is {c.status}; start_investigation requires TRIAGED or REOPENED.",
            409,
        )
    old = c.status
    c.status = "INVESTIGATING"
    svc.touch(c)
    svc.append_event(c.id, "STATUS_CHANGED", {"old_status": old, "new_status": "INVESTIGATING"})
    svc.recompute_posture(store.product_by_code[c.product_code])
    return ok(svc.ser_complaint(c), 200)


@bp.post("/complaints/<complaintId>/taxonomy_recodes")
@require_roles(*HANDLER)
def taxonomy_recode(complaintId):
    c = svc.get_complaint(complaintId)
    body = get_body()
    # Existence: the target category code must resolve (priority 3).
    ncc = body.get("new_category_code")
    if isinstance(ncc, str):
        svc.category_by_code(ncc)
    # Request shape (priority 4).
    new_category_code = req_str(body, "new_category_code")
    expected = req_int(body, "expected_complaint_version")
    category = store.category_by_code[new_category_code]
    # Business: retired target (9) before OCC staleness (19, always last).
    if category.retired:
        raise ApiError(ERR_CATEGORY_RETIRED, "Retired taxonomy categories cannot be assigned.", 409)
    if expected != c.version:
        raise ApiError(ERR_STALE_VERSION, "expected_complaint_version does not match the complaint's current version.", 412)
    old = c.category_code
    c.category_code = new_category_code
    svc.touch(c)
    svc.append_event(c.id, "TAXONOMY_RECODED", {"old_category_code": old, "new_category_code": new_category_code})
    return ok(svc.ser_complaint(c), 200)


@bp.post("/complaints/<complaintId>/draft_response")
@require_roles(*HANDLER)
def draft_response(complaintId):
    c = svc.get_complaint(complaintId)
    body = get_body()
    # Existence: a named template key must resolve (priority 3).
    key = body.get("response_template_key")
    if isinstance(key, str):
        svc.template_by_key(key)
    response_text = req_str(body, "response_text")
    template_key = opt_str(body, "response_template_key", None)
    # State (8).
    if c.status != "INVESTIGATING":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, f"Complaint status is {c.status}; draft_response requires INVESTIGATING.", 409)
    # Template activeness and channel/category match (10).
    if template_key is not None:
        t = store.template_by_key[template_key]
        if t.status != "ACTIVE":
            raise ApiError(ERR_TEMPLATE_NOT_ACTIVE, "response_template_key references a template that is not ACTIVE.", 409)
        if t.channel_code != c.channel_code or t.category_code != c.category_code:
            raise ApiError(ERR_TEMPLATE_MISMATCH, "Template channel_code/category_code do not match the complaint's.", 409)
    # Composite gate (15): a COMPLETED RCA must exist.
    has_completed_rca = any(
        r.complaint_id == c.id and r.status == "COMPLETED" for r in store.rcas.values()
    )
    if not has_completed_rca:
        raise ApiError(ERR_RCA_REQUIRED, "draft_response requires a COMPLETED RootCauseAnalysis.", 409)
    c.status = "RESPONSE_DRAFTED"
    c.response_text = response_text
    c.response_template_key = template_key
    svc.touch(c)
    svc.append_event(c.id, "RESPONSE_DRAFTED", {"response_template_key": template_key})
    svc.recompute_posture(store.product_by_code[c.product_code])
    return ok(svc.ser_complaint(c), 200)


@bp.post("/complaints/<complaintId>/submit_for_qa")
@require_roles(*HANDLER)
def submit_for_qa(complaintId):
    c = svc.get_complaint(complaintId)
    if c.status != "RESPONSE_DRAFTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, f"Complaint status is {c.status}; submit_for_qa requires RESPONSE_DRAFTED.", 409)
    old = c.status
    c.status = "RESPONSE_QA"
    svc.touch(c)
    svc.append_event(c.id, "STATUS_CHANGED", {"old_status": old, "new_status": "RESPONSE_QA"})
    svc.recompute_posture(store.product_by_code[c.product_code])
    return ok(svc.ser_complaint(c), 200)


@bp.post("/complaints/<complaintId>/qa_fail")
@require_roles("QAReviewer")
def qa_fail(complaintId):
    c = svc.get_complaint(complaintId)
    # Segregation of duties (6) surfaces before the state check (8).
    if g.user_id == c.owner_user_id:
        raise ApiError(ERR_SOD_SELF_REVIEW, "A reviewer may not fail a complaint they own.", 409)
    if c.status != "RESPONSE_QA":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, f"Complaint status is {c.status}; qa_fail requires RESPONSE_QA.", 409)
    review = next(
        (r for r in store.reviews.values()
         if r.complaint_id == c.id and r.status == "OPEN" and r.reviewer_user_id == g.user_id),
        None,
    )
    if review is None:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "The acting reviewer holds no OPEN QualityReview for this complaint.", 409)
    # Complete the acting reviewer's OPEN review with FAIL in the same call.
    review.outcome = "FAIL"
    review.status = "COMPLETED"
    svc.touch(review)
    c.status = "INVESTIGATING"
    svc.touch(c)
    svc.append_event(c.id, "QA_FAILED", {"review_id": review.id, "outcome": "FAIL"})
    svc.recompute_timeliness_score(c)
    svc.recompute_posture(store.product_by_code[c.product_code])
    return ok(svc.ser_complaint(c), 200)


@bp.post("/complaints/<complaintId>/resolve")
@require_roles(*HANDLER)
def resolve(complaintId):
    c = svc.get_complaint(complaintId)
    if c.status != "RESPONSE_QA":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, f"Complaint status is {c.status}; resolve requires RESPONSE_QA.", 409)
    # Composite gates (15): QA pass first, then open-escalation (PRD §3.5 order).
    has_pass = any(
        r.complaint_id == c.id and r.status == "COMPLETED" and r.outcome == "PASS"
        for r in store.reviews.values()
    )
    if not has_pass:
        raise ApiError(ERR_QA_PASS_REQUIRED, "resolve requires a COMPLETED QualityReview with outcome PASS.", 409)
    has_open_esc = any(
        e.complaint_id == c.id and e.status in ("RAISED", "ACKNOWLEDGED")
        for e in store.escalations.values()
    )
    if has_open_esc:
        raise ApiError(ERR_ESCALATION_OPEN, "resolve is blocked while an EscalationCase is RAISED or ACKNOWLEDGED.", 409)
    old = c.status
    c.status = "RESOLVED"
    _set_terminal(c)
    svc.touch(c)
    svc.append_event(c.id, "STATUS_CHANGED", {"old_status": old, "new_status": "RESOLVED"})
    svc.recompute_posture(store.product_by_code[c.product_code])
    return ok(svc.ser_complaint(c), 200)


@bp.post("/complaints/<complaintId>/reopen")
@require_roles(*REOPEN_WITHDRAW)
def reopen(complaintId):
    c = svc.get_complaint(complaintId)
    if c.status != "RESOLVED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, f"Complaint status is {c.status}; reopen requires RESOLVED.", 409)
    if c.retention_purge_at is not None and store.now() >= c.retention_purge_at:
        raise ApiError(ERR_RETENTION_EXPIRED, "The retention window has elapsed; reopen is refused.", 409)
    c.status = "REOPENED"
    c.resolved_at = None
    c.retention_purge_at = None
    svc.touch(c)
    svc.append_event(c.id, "REOPENED", {"old_status": "RESOLVED", "new_status": "REOPENED"})
    svc.recompute_posture(store.product_by_code[c.product_code])
    return ok(svc.ser_complaint(c), 200)


@bp.post("/complaints/<complaintId>/withdraw")
@require_roles(*REOPEN_WITHDRAW)
def withdraw(complaintId):
    c = svc.get_complaint(complaintId)
    if c.status not in NON_TERMINAL:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, f"Complaint status is {c.status}; withdraw requires a non-terminal status.", 409)
    for r in store.referrals.values():
        if r.complaint_id == c.id and r.status in ("OPEN", "REOPENED_BY_REGULATOR"):
            raise ApiError(ERR_REFERRAL_OPEN, "withdraw is blocked while a referral is OPEN or REOPENED_BY_REGULATOR.", 409)
    old = c.status
    c.status = "WITHDRAWN"
    _set_terminal(c)
    svc.touch(c)
    svc.append_event(c.id, "WITHDRAWN", {"old_status": old, "new_status": "WITHDRAWN"})
    svc.recompute_posture(store.product_by_code[c.product_code])
    return ok(svc.ser_complaint(c), 200)
