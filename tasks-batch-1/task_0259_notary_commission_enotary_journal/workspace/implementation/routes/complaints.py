"""Complaint routes: investigation, risk, bond settlement (PRD §3.8)."""
from flask import Blueprint, request, g

from db import store, new_common_fields, touch
from domain import (
    find_complaint, find_notary, audit, recompute_risk_score, auto_suspend_notary,
    settle_against_bond, COMPLAINT_CATEGORIES, RISK_SUSPEND_THRESHOLD,
)
from errors import err
from middleware import endpoint
from response import success, list_response
from serialize import view, view_list
from validation import (
    get_body, require_str, require_int, require_enum, non_negative_cents,
    parse_pagination, paginate,
)

bp = Blueprint("complaints", __name__)


@bp.post("/complaints")
@endpoint(("CommissionAuthority",))
def file_complaint():
    body = get_body()
    notary_id = require_str(body, "notary_id")
    category = require_enum(body, "category", COMPLAINT_CATEGORIES)
    claim = require_int(body, "claim_amount_cents", default=0)

    find_notary(notary_id)
    non_negative_cents(claim, "claim_amount_cents")

    rec = dict(new_common_fields())
    rec.update({
        "notary_id": notary_id,
        "filed_by_user_id": g.get("user_id"),
        "category": category,
        "claim_amount_cents": claim,
        "status": "FILED",
        "settled_claim_cents": 0,
    })
    store.complaints[rec["id"]] = rec
    return success(view(rec), status=201)


@bp.get("/complaints/<complaint_id>")
@endpoint(("CommissionAuthority", "Notary"))
def get_complaint(complaint_id):
    return success(view(find_complaint(complaint_id)))


@bp.get("/complaints")
@endpoint(("CommissionAuthority", "Notary"))
def list_complaints():
    limit, offset = parse_pagination()
    recs = list(store.complaints.values())
    nid = request.args.get("notary_id")
    category = request.args.get("category")
    status = request.args.get("status")
    if nid is not None:
        recs = [r for r in recs if r["notary_id"] == nid]
    if category is not None:
        recs = [r for r in recs if r["category"] == category]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, total = paginate(recs, limit, offset)
    return list_response(view_list(page), limit, offset, total)


@bp.post("/complaints/<complaint_id>/open-review")
@endpoint(("CommissionAuthority",))
def open_review(complaint_id):
    complaint = find_complaint(complaint_id)
    if complaint["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Complaint is not FILED")
    # Segregation of duties: acting operator must not be the subject notary
    # (PRD §3.8). X-User-ID compared against the subject notary's id.
    if g.get("user_id") == complaint["notary_id"]:
        raise err("ERR_SEGREGATION_VIOLATION", "Cannot adjudicate own complaint")
    complaint["status"] = "UNDER_REVIEW"
    touch(complaint)
    audit(complaint["notary_id"], "COMPLAINT", complaint_id, "COMPLAINT_OPENED",
          "COMMISSION_AUTHORITY", "Complaint review opened")
    return success(view(complaint))


@bp.post("/complaints/<complaint_id>/request-info")
@endpoint(("CommissionAuthority",))
def request_info(complaint_id):
    complaint = find_complaint(complaint_id)
    if complaint["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Complaint is not UNDER_REVIEW")
    complaint["status"] = "INFO_REQUESTED"
    touch(complaint)
    return success(view(complaint))


@bp.post("/complaints/<complaint_id>/resume-review")
@endpoint(("CommissionAuthority",))
def resume_review(complaint_id):
    complaint = find_complaint(complaint_id)
    if complaint["status"] != "INFO_REQUESTED":
        raise err("ERR_INVALID_STATE", "Complaint is not INFO_REQUESTED")
    complaint["status"] = "UNDER_REVIEW"
    touch(complaint)
    audit(complaint["notary_id"], "COMPLAINT", complaint_id, "COMPLAINT_RESUMED",
          "COMMISSION_AUTHORITY", "Complaint review resumed")
    return success(view(complaint))


@bp.post("/complaints/<complaint_id>/substantiate")
@endpoint(("CommissionAuthority",))
def substantiate(complaint_id):
    complaint = find_complaint(complaint_id)
    if complaint["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Complaint is not UNDER_REVIEW")
    complaint["status"] = "SUBSTANTIATED"
    touch(complaint)
    notary = store.notaries.get(complaint["notary_id"])
    if notary is not None:
        recompute_risk_score(notary)
        touch(notary)
        # Auto-suspend cascade if risk crosses threshold and notary is ACTIVE.
        if notary["risk_score"] >= RISK_SUSPEND_THRESHOLD and notary["status"] == "ACTIVE":
            auto_suspend_notary(notary, actor_role="SYSTEM")
    audit(complaint["notary_id"], "COMPLAINT", complaint_id, "COMPLAINT_SUBSTANTIATED",
          "COMMISSION_AUTHORITY", "Complaint substantiated")
    return success(view(complaint))


@bp.post("/complaints/<complaint_id>/dismiss")
@endpoint(("CommissionAuthority",))
def dismiss(complaint_id):
    complaint = find_complaint(complaint_id)
    if complaint["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Complaint is not UNDER_REVIEW")
    complaint["status"] = "DISMISSED"
    touch(complaint)
    audit(complaint["notary_id"], "COMPLAINT", complaint_id, "COMPLAINT_DISMISSED",
          "COMMISSION_AUTHORITY", "Complaint dismissed")
    return success(view(complaint))


@bp.post("/complaints/<complaint_id>/settle")
@endpoint(("CommissionAuthority",))
def settle(complaint_id):
    complaint = find_complaint(complaint_id)
    if complaint["status"] != "SUBSTANTIATED":
        raise err("ERR_INVALID_STATE", "Complaint is not SUBSTANTIATED")
    notary = store.notaries.get(complaint["notary_id"])
    bond = store.bonds.get(notary.get("bond_id")) if notary else None
    if bond is None or bond["status"] != "ACTIVE":
        raise err("ERR_BOND_NOT_ACTIVE", "Subject notary's bond is not ACTIVE")
    if complaint["claim_amount_cents"] <= 0:
        raise err("ERR_NO_CLAIM_AMOUNT", "Complaint has no claim amount")

    complaint["status"] = "SETTLED"
    touch(complaint)
    # Draw against the bond; may exhaust -> auto-suspend (three-deep cascade).
    settle_against_bond(complaint, bond)
    # Settlement keeps the complaint in the risk SUB set; recompute (no weight
    # change but keeps semantics aligned with PRD §3.8 final_after_settle).
    if notary is not None:
        recompute_risk_score(notary)
        touch(notary)
    audit(complaint["notary_id"], "COMPLAINT", complaint_id, "COMPLAINT_SETTLED",
          "COMMISSION_AUTHORITY", "Complaint settled")
    return success(view(complaint))
