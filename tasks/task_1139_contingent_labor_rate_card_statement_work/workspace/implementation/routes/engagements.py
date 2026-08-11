from datetime import timedelta

from flask import Blueprint, request

from db import clock_now, fmt_ts, stamp_new, store, today_str, touch
from envelope import ok, ok_list
from errors import (
    ERR_INVALID_STATE,
    ERR_MISCLASSIFICATION_RISK,
    ERR_NO_ELIGIBLE_SUPPLIER,
    ERR_NOT_FOUND,
    ERR_STALE_ENGAGEMENT_VERSION,
    raise_err,
)
from security import ALL_READ, require_roles
from services import (
    RESPONSE_WINDOW_DAYS,
    misclassification_risk,
    select_suppliers,
    worker_offboard_cascade,
)
from validators import (
    apply_filters,
    get_body,
    opt_bool,
    opt_int,
    opt_str,
    paginate,
    req_enum,
    req_int,
    req_str,
)
import serializers

bp = Blueprint("engagements", __name__)

ENGAGEMENT_TYPES = {"REQUISITION", "SOW"}
PAYMENT_BASIS = {"HOURLY", "FIXED"}
SUPERVISION_LEVELS = {"DAILY", "MILESTONE"}
DECISIONS = {"APPROVE", "REWORK"}


def _get_engagement(engagement_id):
    eng = store.engagements.get(engagement_id)
    if eng is None:
        raise_err(ERR_NOT_FOUND, f"Engagement {engagement_id} not found.")
    return eng


@bp.post("/v1/engagements")
def create_engagement():
    require_roles("HiringManager")
    body = get_body()
    rec = {
        "title": req_str(body, "title"),
        "engagement_type": req_enum(body, "engagement_type", ENGAGEMENT_TYPES),
        "role_code": req_str(body, "role_code"),
        "skill_code": req_str(body, "skill_code"),
        "geo_code": req_str(body, "geo_code"),
        "payment_basis": req_enum(body, "payment_basis", PAYMENT_BASIS),
        "supervision_level": req_enum(body, "supervision_level", SUPERVISION_LEVELS),
        "duration_months": req_int(body, "duration_months"),
        "budget_cents": req_int(body, "budget_cents"),
        "prorata_conversion": opt_bool(body, "prorata_conversion", False),
        "status": "DRAFT",
        "misclassification_risk": None,
        "classification_note": None,
        "awarded_supplier_id": None,
        "committed_spend_cents": 0,
        "budget_audit_raised": False,
    }
    stamp_new(rec)
    store.engagements[rec["id"]] = rec
    return ok(serializers.engagement(rec), 201)


@bp.get("/v1/engagements")
def list_engagements():
    require_roles(*ALL_READ)
    filters = {
        "status": request.args.get("status"),
        "engagement_type": request.args.get("engagement_type"),
        "awarded_supplier_id": request.args.get("awarded_supplier_id"),
    }
    records = apply_filters(list(store.engagements.values()), filters)
    page, total, limit, offset = paginate(records, serializers.engagement)
    return ok_list(page, total, limit, offset)


@bp.get("/v1/engagements/<engagement_id>")
def get_engagement(engagement_id):
    require_roles(*ALL_READ)
    return ok(serializers.engagement(_get_engagement(engagement_id)))


@bp.post("/v1/engagements/<engagement_id>/submit-review")
def submit_review(engagement_id):
    require_roles("HiringManager")
    eng = _get_engagement(engagement_id)
    if eng["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT engagement can be submitted for review.")
    eng["misclassification_risk"] = misclassification_risk(eng)
    eng["status"] = "IN_REVIEW"
    touch(eng)
    return ok(serializers.engagement(eng))


@bp.post("/v1/engagements/<engagement_id>/classification-decision")
def classification_decision(engagement_id):
    require_roles("ProgramAdmin")
    body = get_body()
    decision = req_enum(body, "decision", DECISIONS)
    rationale = opt_str(body, "risk_override_rationale")
    note = opt_str(body, "note")
    eng = _get_engagement(engagement_id)
    if eng["status"] != "IN_REVIEW":
        raise_err(ERR_INVALID_STATE, "Only an IN_REVIEW engagement accepts a classification decision.")
    if decision == "REWORK":
        eng["status"] = "DRAFT"
        eng["classification_note"] = note
    else:  # APPROVE
        if eng["misclassification_risk"] == "HIGH" and not rationale:
            raise_err(
                ERR_MISCLASSIFICATION_RISK,
                "Approving a HIGH-risk engagement requires risk_override_rationale.",
            )
        eng["status"] = "OPEN"
        if rationale:
            eng["classification_note"] = rationale
    touch(eng)
    return ok(serializers.engagement(eng))


@bp.post("/v1/engagements/<engagement_id>/distribute")
def distribute(engagement_id):
    require_roles("ProgramAdmin")
    eng = _get_engagement(engagement_id)
    if eng["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Only an OPEN engagement can be distributed.")
    pool = select_suppliers()
    if not pool:
        raise_err(ERR_NO_ELIGIBLE_SUPPLIER, "No eligible supplier for distribution.")
    now = clock_now()
    offers = []
    for sup in pool:
        rec = {
            "engagement_id": eng["id"],
            "supplier_id": sup["id"],
            "status": "OFFERED",
            "offered_at": fmt_ts(now),
            "response_due_at": fmt_ts(now + timedelta(days=RESPONSE_WINDOW_DAYS)),
            "responded_at": None,
        }
        stamp_new(rec)
        store.offers[rec["id"]] = rec
        sup["offers_made_count"] += 1
        sup["open_offers_count"] += 1
        touch(sup)
        offers.append(rec)
    eng["status"] = "FILLING"
    touch(eng)
    return ok_list(
        [serializers.offer(o) for o in offers], len(offers), len(offers), 0, status=201
    )


@bp.post("/v1/engagements/<engagement_id>/amendments")
def amend_engagement(engagement_id):
    require_roles("HiringManager")
    body = get_body()
    expected = req_int(body, "expected_engagement_version")
    budget = opt_int(body, "budget_cents")
    duration = opt_int(body, "duration_months")
    title = opt_str(body, "title")
    eng = _get_engagement(engagement_id)
    if eng["status"] == "CLOSED":
        raise_err(ERR_INVALID_STATE, "A CLOSED engagement cannot be amended.")
    if expected != eng["version"]:
        raise_err(
            ERR_STALE_ENGAGEMENT_VERSION,
            "expected_engagement_version does not match the engagement's current version.",
        )
    if budget is not None:
        eng["budget_cents"] = budget
    if duration is not None:
        eng["duration_months"] = duration
    if title is not None:
        eng["title"] = title
    touch(eng)
    return ok(serializers.engagement(eng))


@bp.post("/v1/engagements/<engagement_id>/close")
def close_engagement(engagement_id):
    require_roles("HiringManager")
    eng = _get_engagement(engagement_id)
    if eng["status"] not in ("OPEN", "FILLING", "ACTIVE"):
        raise_err(ERR_INVALID_STATE, "Only an OPEN, FILLING or ACTIVE engagement can be closed.")
    # Withdraw all OFFERED / ACCEPTED offers; OFFERED ones decrement the slot counter.
    for o in store.offers.values():
        if o["engagement_id"] == eng["id"] and o["status"] in ("OFFERED", "ACCEPTED"):
            was_offered = o["status"] == "OFFERED"
            o["status"] = "WITHDRAWN"
            touch(o)
            if was_offered:
                sup = store.suppliers.get(o["supplier_id"])
                if sup is not None:
                    sup["open_offers_count"] -= 1
                    touch(sup)
    # Terminate booked assignments and cascade workers to OFFBOARDING.
    if eng["status"] in ("FILLING", "ACTIVE"):
        target = ("PENDING",) if eng["status"] == "FILLING" else ("PENDING", "ACTIVE")
        for a in store.assignments.values():
            if a["engagement_id"] == eng["id"] and a["status"] in target:
                a["status"] = "TERMINATED"
                a["termination_reason"] = "ENGAGEMENT_CLOSED"
                a["actual_end_date"] = today_str()
                touch(a)
                worker = store.workers.get(a["worker_id"])
                if worker is not None:
                    worker_offboard_cascade(worker)
    eng["status"] = "CLOSED"
    touch(eng)
    return ok(serializers.engagement(eng))
