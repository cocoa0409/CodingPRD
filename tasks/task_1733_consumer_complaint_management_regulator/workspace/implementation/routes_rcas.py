"""Root-cause analysis routes (PRD §3.4)."""
from datetime import timedelta

from flask import request, Blueprint

import services as svc
from db import store
from errors import (
    ApiError,
    ERR_INVALID_STATE_TRANSITION,
    ERR_RCA_DEADLINE_PASSED,
)
from middleware import get_body, pagination_params, req_enum, req_str, require_roles
from response import ok, ok_list

bp = Blueprint("rcas", __name__)

RCA_READERS = ("ComplaintManager", "CaseHandler", "QAReviewer", "ExecutiveReviewer", "Auditor")
VERDICTS = ("SUBSTANTIATED", "NOT_SUBSTANTIATED", "INCONCLUSIVE")


@bp.post("/complaints/<cid>/rcas")
@require_roles("CaseHandler")
def create_rca(cid):
    complaint = svc.get_complaint(cid)
    body = get_body()
    # Existence: linked_product_code must resolve.
    lpc = body.get("linked_product_code")
    if isinstance(lpc, str):
        svc.product_by_code(lpc)
    verdict = req_enum(body, "verdict", VERDICTS)
    linked_product_code = req_str(body, "linked_product_code")
    process_step = req_str(body, "process_step")
    # Creating a fresh RCA supersedes any prior DRAFT of the same complaint.
    for prior in store.rcas.values():
        if prior.complaint_id == complaint.id and prior.status == "DRAFT":
            prior.status = "SUPERSEDED"
            svc.touch(prior)
    r = svc.fresh_rec(
        complaint_id=complaint.id,
        verdict=verdict,
        linked_product_code=linked_product_code,
        process_step=process_step,
        completed_at=None,
        status="DRAFT",
    )
    store.rcas[r.id] = r
    return ok(svc.ser_rca(r), 201)


@bp.get("/complaints/<cid>/rcas")
@require_roles(*RCA_READERS)
def list_complaint_rcas(cid):
    svc.get_complaint(cid)
    limit, offset = pagination_params()
    recs = [r for r in store.rcas.values() if r.complaint_id == cid]
    items, total = svc.paged(recs, svc.ser_rca, limit, offset)
    return ok_list(items, total, limit, offset)


@bp.get("/rcas")
@require_roles(*RCA_READERS)
def list_rcas():
    limit, offset = pagination_params()
    recs = list(store.rcas.values())
    complaint_id = request.args.get("complaint_id")
    if complaint_id is not None:
        recs = [r for r in recs if r.complaint_id == complaint_id]
    linked = request.args.get("linked_product_code")
    if linked is not None:
        recs = [r for r in recs if r.linked_product_code == linked]
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r.status == status]
    items, total = svc.paged(recs, svc.ser_rca, limit, offset)
    return ok_list(items, total, limit, offset)


@bp.get("/rcas/<rcaId>")
@require_roles(*RCA_READERS)
def get_rca(rcaId):
    return ok(svc.ser_rca(svc.get_rca(rcaId)), 200)


@bp.post("/rcas/<rcaId>/complete")
@require_roles("CaseHandler")
def complete_rca(rcaId):
    r = svc.get_rca(rcaId)
    if r.status != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, f"RCA status is {r.status}; complete requires DRAFT.", 409)
    complaint = svc.get_complaint(r.complaint_id)
    # Inclusive boundary: completion exactly at received_at + 30 days succeeds.
    deadline = complaint.received_at + timedelta(days=svc.RCA_DEADLINE_DAYS)
    if store.now() > deadline:
        raise ApiError(ERR_RCA_DEADLINE_PASSED, "The 30-day RCA completion deadline has passed.", 409)
    r.status = "COMPLETED"
    r.completed_at = store.now()
    svc.touch(r)
    if r.verdict == "SUBSTANTIATED":
        # Cascade hop 2: refresh the attributed product's aggregates and posture.
        linked = store.product_by_code.get(r.linked_product_code)
        if linked is not None:
            svc.recompute_posture(linked)
    return ok(svc.ser_rca(r), 200)
