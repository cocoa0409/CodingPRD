"""Application routes — create, read, patch, and all state actions."""

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import fail
from helpers import (get_json_body, require_str, require_int, opt_int,
                     require_enum, require_list, parse_dt, paginate,
                     sort_by_created, get_or_404)
from middleware import require_roles
from response import success_object, success_list
from services import calc, workflow

bp = Blueprint("applications", __name__)

CATEGORIES = ("ARTIST_ALLEY", "DEALER", "PUBLISHER", "STUDIO", "NONPROFIT")
KINDS = ("BOOTH_10X10", "BOOTH_10X20", "CORNER_BOOTH", "ENDCAP",
         "FEATURED_ISLAND", "ARTIST_TABLE", "NONPROFIT_TABLE")
TERMINAL = ("JURIED_REJECTED", "DECLINED", "WITHDRAWN", "CANCELLED")


def application_view(a):
    keys = (
        "id", "exhibitor_id", "convention_id", "category", "channel",
        "requested_space_kinds", "requested_space_count",
        "estimated_daily_sales_cents", "conflicted_juror_user_ids",
        "status", "permit_status", "permit_number", "permit_expires_at",
        "submitted_at", "decided_at", "jury_composite_score",
        "provisional_quote_cents", "final_invoice_cents", "deposit_cents",
        "amount_paid_cents", "badge_fees_cents", "balance_due_cents",
        "refund_cents", "included_badges", "purchased_extra_badges",
        "tax_estimate_cents", "cancellation_reason",
        "created_at", "updated_at", "version",
    )
    return {k: a.get(k) for k in keys}


def _check_exhibitor_owns(user_id, application):
    if application["exhibitor_id"] != user_id:
        fail("ERR_FORBIDDEN_OWNERSHIP",
             "Exhibitor role targets a resource owned by another exhibitor")


# ---------------------------------------------------------------------------
# POST /applications
# ---------------------------------------------------------------------------
@bp.route("/applications", methods=["POST"])
def create_application():
    user_id, _ = require_roles("Exhibitor")
    body = get_json_body()
    convention_id = require_str(body, "convention_id")
    category = require_enum(body, "category", CATEGORIES)
    channel = require_enum(body, "channel", ("RENEWAL", "OPEN"))
    kinds = require_list(body, "requested_space_kinds")
    for k in kinds:
        if k not in KINDS:
            fail("ERR_INVALID_REQUEST", f"unknown space kind {k}")
    if len(kinds) == 0:
        fail("ERR_INVALID_REQUEST", "requested_space_kinds must be non-empty")
    count = require_int(body, "requested_space_count", minimum=1)
    est_sales = require_int(body, "estimated_daily_sales_cents", minimum=0)
    conflicted = body.get("conflicted_juror_user_ids", [])
    if not isinstance(conflicted, list) or any(not isinstance(x, str) for x in conflicted):
        fail("ERR_INVALID_REQUEST", "conflicted_juror_user_ids must be an array of strings")

    # existence
    conv = db.conventions.get(convention_id)
    if conv is None:
        fail("ERR_NOT_FOUND", "convention_id does not exist")
    exhibitor = db.exhibitors.get(user_id)
    if exhibitor is None:
        fail("ERR_NOT_FOUND", "exhibitor does not exist")

    # referential: category must equal exhibitor category
    if category != exhibitor["category"]:
        fail("ERR_CATEGORY_MISMATCH",
             "Application category differs from the exhibitor's registered category")

    permit_status = "PENDING" if conv["tax_permit_required"] else "NOT_REQUIRED"
    a = {
        "id": db.new_id(),
        "exhibitor_id": user_id,
        "convention_id": convention_id,
        "category": category,
        "channel": channel,
        "requested_space_kinds": list(kinds),
        "requested_space_count": count,
        "estimated_daily_sales_cents": est_sales,
        "conflicted_juror_user_ids": list(conflicted),
        "status": "DRAFT",
        "permit_status": permit_status,
        "permit_number": None,
        "permit_expires_at": None,
        "submitted_at": None,
        "decided_at": None,
        "jury_composite_score": None,
        "provisional_quote_cents": None,
        "final_invoice_cents": None,
        "deposit_cents": None,
        "amount_paid_cents": 0,
        "badge_fees_cents": 0,
        "balance_due_cents": 0,
        "refund_cents": None,
        "included_badges": 0,
        "purchased_extra_badges": 0,
        "tax_estimate_cents": None,
        "cancellation_reason": None,
    }
    db.stamp_created(a)
    db.applications[a["id"]] = a
    return success_object(application_view(a), 201)


@bp.route("/applications", methods=["GET"])
def list_applications():
    user_id, role = require_roles("ShowDirector", "OperationsStaff", "JuryMember", "Exhibitor")
    items = list(db.applications.values())
    if role == "Exhibitor":
        items = [a for a in items if a["exhibitor_id"] == user_id]
    else:
        ex = request.args.get("exhibitor_id")
        if ex is not None:
            items = [a for a in items if a["exhibitor_id"] == ex]
    for f in ("convention_id", "status", "category"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a[f] == v]
    items = sort_by_created(items)
    limit, offset, total, page = paginate(items)
    return success_list([application_view(a) for a in page], limit, offset, total)


@bp.route("/applications/<applicationId>", methods=["GET"])
def get_application(applicationId):
    user_id, role = require_roles("ShowDirector", "OperationsStaff", "JuryMember", "Exhibitor")
    a = get_or_404(db.applications, applicationId)
    if role == "Exhibitor":
        _check_exhibitor_owns(user_id, a)
    return success_object(application_view(a), 200)


@bp.route("/applications/<applicationId>", methods=["PATCH"])
def patch_application(applicationId):
    user_id, role = require_roles("Exhibitor")
    a = get_or_404(db.applications, applicationId)
    _check_exhibitor_owns(user_id, a)
    body = get_json_body()
    expected = body.get("expected_application_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        fail("ERR_INVALID_REQUEST", "expected_application_version is required")
    # state precondition (DRAFT or NEEDS_REVISION) — priority 5 with OCC
    if a["status"] not in ("DRAFT", "NEEDS_REVISION"):
        fail("ERR_INVALID_TRANSITION",
             "Application may only be revised while DRAFT or NEEDS_REVISION")
    if expected != a["version"]:
        fail("ERR_STALE_APPLICATION_VERSION",
             "expected_application_version does not match the application's current version")

    if "requested_space_kinds" in body and body["requested_space_kinds"] is not None:
        kinds = require_list(body, "requested_space_kinds")
        for k in kinds:
            if k not in KINDS:
                fail("ERR_INVALID_REQUEST", f"unknown space kind {k}")
        if len(kinds) == 0:
            fail("ERR_INVALID_REQUEST", "requested_space_kinds must be non-empty")
        a["requested_space_kinds"] = list(kinds)
    count = opt_int(body, "requested_space_count", minimum=1)
    if count is not None:
        a["requested_space_count"] = count
    est = opt_int(body, "estimated_daily_sales_cents", minimum=0)
    if est is not None:
        a["estimated_daily_sales_cents"] = est
    if "conflicted_juror_user_ids" in body and body["conflicted_juror_user_ids"] is not None:
        c = body["conflicted_juror_user_ids"]
        if not isinstance(c, list) or any(not isinstance(x, str) for x in c):
            fail("ERR_INVALID_REQUEST", "conflicted_juror_user_ids must be an array of strings")
        a["conflicted_juror_user_ids"] = list(c)
    if "channel" in body and body["channel"] is not None:
        a["channel"] = require_enum(body, "channel", ("RENEWAL", "OPEN"))
    db.touch(a)
    return success_object(application_view(a), 200)


# ---------------------------------------------------------------------------
# Submit / resubmit
# ---------------------------------------------------------------------------
def _submit_checks(a, conv, exhibitor, is_revision_resubmit):
    now = db.now_dt()
    phase = conv["phase"]
    if is_revision_resubmit and phase == "JURY_REVIEW":
        # window checks waived; quota/duplicate checks still apply
        pass
    else:
        if phase != "APPLICATIONS_OPEN":
            fail("ERR_INVALID_TRANSITION",
                 "Submission requires phase APPLICATIONS_OPEN")
        close = db._parse_iso(conv["application_close_at"])
        if a["channel"] == "RENEWAL":
            if not (exhibitor["prior_years_completed"] >= 1 and exhibitor["standing"] == "GOOD"):
                fail("ERR_RENEWAL_NOT_ELIGIBLE",
                     "RENEWAL requires prior_years_completed >= 1 and GOOD standing")
            if not (db._parse_iso(conv["renewal_open_at"]) <= now < close):
                fail("ERR_APPLICATION_WINDOW_CLOSED",
                     "Outside the renewal submission window")
        else:
            if not (db._parse_iso(conv["application_open_at"]) <= now < close):
                fail("ERR_APPLICATION_WINDOW_CLOSED",
                     "Outside the open submission window")
    # quota row must exist
    quota = workflow.quota_for(a["convention_id"], a["category"])
    if quota is None:
        fail("ERR_CATEGORY_NOT_OFFERED",
             "No CategoryQuota row exists for this category in this convention")
    # duplicate live application
    for other in db.applications.values():
        if other["id"] == a["id"]:
            continue
        if other["exhibitor_id"] == a["exhibitor_id"] \
                and other["convention_id"] == a["convention_id"] \
                and other["status"] not in ("WITHDRAWN", "JURIED_REJECTED", "DECLINED", "CANCELLED"):
            fail("ERR_DUPLICATE_APPLICATION",
                 "Exhibitor already has a live application in this convention")


@bp.route("/applications/<applicationId>/submit", methods=["POST"])
def submit_application(applicationId):
    user_id, role = require_roles("Exhibitor")
    a = get_or_404(db.applications, applicationId)
    _check_exhibitor_owns(user_id, a)
    if a["status"] not in ("DRAFT", "NEEDS_REVISION"):
        fail("ERR_INVALID_TRANSITION",
             "Only DRAFT or NEEDS_REVISION applications may be submitted")
    conv = db.conventions[a["convention_id"]]
    exhibitor = db.exhibitors[a["exhibitor_id"]]
    is_revision_resubmit = (a["status"] == "NEEDS_REVISION")
    _submit_checks(a, conv, exhibitor, is_revision_resubmit)

    a["submitted_at"] = db.now_iso()
    a["provisional_quote_cents"] = calc.provisional_quote(a, conv)
    a["tax_estimate_cents"] = calc.sales_tax_estimate(a, conv)
    a["status"] = "SUBMITTED"
    db.touch(a)
    return success_object(application_view(a), 200)


@bp.route("/applications/<applicationId>/withdraw", methods=["POST"])
def withdraw_application(applicationId):
    user_id, role = require_roles("Exhibitor")
    a = get_or_404(db.applications, applicationId)
    _check_exhibitor_owns(user_id, a)
    if a["status"] not in ("DRAFT", "SUBMITTED", "UNDER_REVIEW",
                           "NEEDS_REVISION", "JURIED_WAITLISTED"):
        fail("ERR_INVALID_TRANSITION",
             "Withdrawal allowed only from DRAFT/SUBMITTED/UNDER_REVIEW/NEEDS_REVISION/JURIED_WAITLISTED")
    was_waitlisted = a["status"] == "JURIED_WAITLISTED"
    a["status"] = "WITHDRAWN"
    db.touch(a)
    if was_waitlisted:
        quota = workflow.quota_for(a["convention_id"], a["category"])
        if quota is not None and quota["waitlisted_count"] > 0:
            quota["waitlisted_count"] -= 1
            db.touch(quota)
    workflow.moot_neighbor_requests(a["exhibitor_id"])
    return success_object(application_view(a), 200)


@bp.route("/applications/<applicationId>/request-revision", methods=["POST"])
def request_revision(applicationId):
    require_roles("ShowDirector")
    a = get_or_404(db.applications, applicationId)
    if a["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_TRANSITION",
             "request-revision requires UNDER_REVIEW")
    a["status"] = "NEEDS_REVISION"
    db.touch(a)
    return success_object(application_view(a), 200)


@bp.route("/applications/<applicationId>/decide", methods=["POST"])
def decide_application(applicationId):
    require_roles("ShowDirector")
    a = get_or_404(db.applications, applicationId)
    body = get_json_body()
    decision = require_enum(body, "decision", ("ACCEPTED", "WAITLISTED", "REJECTED"))
    if a["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_TRANSITION", "decide requires UNDER_REVIEW")
    # quorum
    if calc.distinct_juror_count(a["id"]) < calc.QUORUM:
        fail("ERR_JURY_QUORUM_NOT_MET",
             "Fewer than 3 distinct-juror scores")
    composite = a.get("jury_composite_score")
    quota = workflow.quota_for(a["convention_id"], a["category"])
    from decimal import Decimal
    comp_d = Decimal(str(composite)) if composite is not None else None
    if decision == "ACCEPTED":
        if comp_d is None or comp_d < calc.ACCEPT_THRESHOLD:
            fail("ERR_SCORE_BELOW_THRESHOLD",
                 "ACCEPTED requires jury_composite_score >= 70.00")
        if quota is not None and quota["accepted_count"] >= quota["max_accepted"]:
            fail("ERR_CATEGORY_QUOTA_FULL",
                 "accepted_count has reached max_accepted")
        a["status"] = "JURIED_ACCEPTED"
        a["decided_at"] = db.now_iso()
        db.touch(a)
        if quota is not None:
            quota["accepted_count"] += 1
            db.touch(quota)
    elif decision == "WAITLISTED":
        if comp_d is None or comp_d < calc.WAITLIST_THRESHOLD:
            fail("ERR_SCORE_BELOW_THRESHOLD",
                 "WAITLISTED requires jury_composite_score >= 50.00")
        if quota is not None and quota["waitlisted_count"] >= quota["max_waitlisted"]:
            fail("ERR_WAITLIST_FULL",
                 "waitlisted_count has reached max_waitlisted")
        a["status"] = "JURIED_WAITLISTED"
        a["decided_at"] = db.now_iso()
        db.touch(a)
        if quota is not None:
            quota["waitlisted_count"] += 1
            db.touch(quota)
    else:  # REJECTED
        a["status"] = "JURIED_REJECTED"
        a["decided_at"] = db.now_iso()
        db.touch(a)
        workflow.moot_neighbor_requests(a["exhibitor_id"])
    return success_object(application_view(a), 200)


# ---------------------------------------------------------------------------
# accept-offer / decline / cancel / badge-extras
# ---------------------------------------------------------------------------
@bp.route("/applications/<applicationId>/accept-offer", methods=["POST"])
def accept_offer(applicationId):
    user_id, role = require_roles("Exhibitor")
    a = get_or_404(db.applications, applicationId)
    _check_exhibitor_owns(user_id, a)
    body = get_json_body()
    deposit_in = require_int(body, "deposit_cents", minimum=0)
    # priority 5: state
    if a["status"] != "JURIED_ACCEPTED":
        fail("ERR_INVALID_TRANSITION", "accept-offer requires JURIED_ACCEPTED")
    conv = db.conventions[a["convention_id"]]
    exhibitor = db.exhibitors[a["exhibitor_id"]]
    # at least one TENTATIVE placement must exist — state gate (ERR_INVALID_TRANSITION)
    tentative = [p for p in db.placements.values()
                 if p["application_id"] == a["id"] and p["status"] == "TENTATIVE"]
    if not tentative:
        fail("ERR_INVALID_TRANSITION",
             "accept-offer requires at least one TENTATIVE placement")
    # priority 6: temporal — offer expiry window
    now = db.now_dt()
    decided = db._parse_iso(a["decided_at"])
    if now > decided + timedelta(days=conv["deposit_window_days"]):
        fail("ERR_OFFER_EXPIRED", "Offer acceptance window has passed")
    # priority 7: compliance — standing then permit
    if exhibitor["standing"] not in ("GOOD", "PROBATION"):
        fail("ERR_EXHIBITOR_SUSPENDED",
             "Exhibitor standing must be GOOD or PROBATION")
    if conv["tax_permit_required"] and a["permit_status"] not in ("VERIFIED", "EXEMPT"):
        fail("ERR_PERMIT_NOT_VERIFIED",
             "permit_status must be VERIFIED or EXEMPT")
    # priority 10: money — deposit exact match
    invoice = calc.final_invoice(a, conv)
    deposit = calc.deposit_for(invoice)
    if deposit_in != deposit:
        fail("ERR_DEPOSIT_MISMATCH",
             "deposit_cents differs from the computed deposit")

    a["final_invoice_cents"] = invoice
    a["deposit_cents"] = deposit
    a["amount_paid_cents"] = deposit
    calc.recompute_balance_due(a)
    a["status"] = "CONTRACTED"
    db.touch(a)
    return success_object(application_view(a), 200)


@bp.route("/applications/<applicationId>/decline", methods=["POST"])
def decline_offer(applicationId):
    user_id, role = require_roles("Exhibitor")
    a = get_or_404(db.applications, applicationId)
    _check_exhibitor_owns(user_id, a)
    if a["status"] != "JURIED_ACCEPTED":
        fail("ERR_INVALID_TRANSITION", "decline requires JURIED_ACCEPTED")
    workflow.decline_application(a)
    return success_object(application_view(a), 200)


@bp.route("/applications/<applicationId>/cancel", methods=["POST"])
def cancel_application(applicationId):
    user_id, role = require_roles("Exhibitor", "ShowDirector")
    a = get_or_404(db.applications, applicationId)
    if role == "Exhibitor":
        _check_exhibitor_owns(user_id, a)
    if a["status"] not in ("CONTRACTED", "PLACED"):
        fail("ERR_INVALID_TRANSITION", "cancel requires CONTRACTED or PLACED")
    reason = "DIRECTOR" if role == "ShowDirector" else "EXHIBITOR"
    workflow.cancel_application(a, reason)
    return success_object(application_view(a), 200)


@bp.route("/applications/<applicationId>/badge-extras", methods=["POST"])
def badge_extras(applicationId):
    user_id, role = require_roles("Exhibitor")
    a = get_or_404(db.applications, applicationId)
    _check_exhibitor_owns(user_id, a)
    body = get_json_body()
    qty = require_int(body, "quantity", minimum=1)
    if a["status"] != "PLACED":
        fail("ERR_INVALID_TRANSITION", "badge-extras requires PLACED")
    if a["purchased_extra_badges"] + qty > a["included_badges"]:
        fail("ERR_BADGE_EXTRA_LIMIT",
             "purchased_extra_badges may not exceed included_badges")
    a["purchased_extra_badges"] += qty
    a["badge_fees_cents"] += qty * calc.EXTRA_BADGE_FEE_CENTS
    calc.recompute_balance_due(a)
    db.touch(a)
    return success_object(application_view(a), 200)


# ---------------------------------------------------------------------------
# Permit dimension
# ---------------------------------------------------------------------------
@bp.route("/applications/<applicationId>/submit-permit", methods=["POST"])
def submit_permit(applicationId):
    user_id, role = require_roles("Exhibitor")
    a = get_or_404(db.applications, applicationId)
    _check_exhibitor_owns(user_id, a)
    body = get_json_body()
    permit_number = require_str(body, "permit_number")
    expires = parse_dt(body, "permit_expires_at")
    if a["permit_status"] not in ("PENDING", "REJECTED"):
        fail("ERR_INVALID_TRANSITION",
             "submit-permit requires permit_status PENDING or REJECTED")
    a["permit_number"] = permit_number
    a["permit_expires_at"] = db._fmt_iso(expires)
    a["permit_status"] = "SUBMITTED"
    db.touch(a)
    return success_object(application_view(a), 200)


@bp.route("/applications/<applicationId>/verify-permit", methods=["POST"])
def verify_permit(applicationId):
    require_roles("ShowDirector")
    a = get_or_404(db.applications, applicationId)
    if a["permit_status"] != "SUBMITTED":
        fail("ERR_INVALID_TRANSITION", "verify-permit requires SUBMITTED")
    a["permit_status"] = "VERIFIED"
    db.touch(a)
    return success_object(application_view(a), 200)


@bp.route("/applications/<applicationId>/reject-permit", methods=["POST"])
def reject_permit(applicationId):
    require_roles("ShowDirector")
    a = get_or_404(db.applications, applicationId)
    if a["permit_status"] != "SUBMITTED":
        fail("ERR_INVALID_TRANSITION", "reject-permit requires SUBMITTED")
    a["permit_status"] = "REJECTED"
    db.touch(a)
    return success_object(application_view(a), 200)


@bp.route("/applications/<applicationId>/claim-exemption", methods=["POST"])
def claim_exemption(applicationId):
    user_id, role = require_roles("Exhibitor")
    a = get_or_404(db.applications, applicationId)
    _check_exhibitor_owns(user_id, a)
    if a["permit_status"] != "PENDING":
        fail("ERR_INVALID_TRANSITION", "claim-exemption requires PENDING")
    exhibitor = db.exhibitors[a["exhibitor_id"]]
    if exhibitor["category"] != "NONPROFIT":
        fail("ERR_EXEMPTION_NOT_ALLOWED",
             "Only NONPROFIT exhibitors may claim exemption")
    a["permit_status"] = "EXEMPT"
    db.touch(a)
    return success_object(application_view(a), 200)
