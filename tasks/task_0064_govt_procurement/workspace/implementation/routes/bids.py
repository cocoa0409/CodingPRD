"""Bid + Committee + Award routes."""

from flask import Blueprint, request

from common import get_json_body, get_pagination, slice_page
from middleware import require_roles
from response import paginated, success
from services import bid as svc
from services import project as proj_svc


bp = Blueprint("bids", __name__, url_prefix="/procurement")


@bp.post("/projects/<pid>/bids")
@require_roles("Supplier")
def submit_bid(pid):
    body = get_json_body()
    bid = svc.submit_bid(pid, body)
    return success(bid, 201)


@bp.post("/bids/<bid_id>/withdraw")
@require_roles("Supplier")
def withdraw_bid(bid_id):
    return success(svc.withdraw_bid(bid_id), 200)


@bp.post("/bids/<bid_id>/record-evaluation")
@require_roles("EvaluationExpert")
def record_eval(bid_id):
    body = get_json_body()
    return success(svc.record_evaluation(bid_id, body), 200)


@bp.get("/projects/<pid>/bids")
@require_roles("ProcurementOfficer", "Regulator", "Supplier", "EvaluationExpert")
def list_bids(pid):
    from db import db

    proj_svc.get_project_or_404(pid)
    limit, offset = get_pagination()
    status_f = request.args.get("bid_status")
    items = [b for b in db.bids.values() if b["project_id"] == pid]
    if status_f:
        items = [b for b in items if b["bid_status"] == status_f]
    items.sort(key=lambda b: b["created_at"])
    page, total = slice_page(items, limit, offset)
    return paginated(page, limit, offset, total, 200)


@bp.post("/projects/<pid>/form-committee")
@require_roles("ProcurementOfficer")
def form_committee(pid):
    body = get_json_body()
    c = svc.form_committee(pid, body)
    return success(c, 201)


@bp.post("/committees/<cid>/finalize")
@require_roles("ProcurementOfficer")
def finalize_committee(cid):
    return success(svc.finalize_committee(cid), 200)


@bp.post("/projects/<pid>/open-bid-ceremony")
@require_roles("ProcurementOfficer")
def open_ceremony(pid):
    return success(svc.open_bid_ceremony(pid), 200)


@bp.post("/projects/<pid>/decide-award")
@require_roles("ProcurementOfficer")
def decide_award(pid):
    return success(svc.decide_award(pid), 201)


@bp.post("/awards/<aid>/publish")
@require_roles("ProcurementOfficer")
def publish_award(aid):
    return success(svc.publish_award(aid), 200)
