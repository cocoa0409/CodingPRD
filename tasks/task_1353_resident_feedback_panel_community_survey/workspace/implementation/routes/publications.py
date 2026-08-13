from flask import Blueprint, g, request

from core import (ERR_INVALID_REQUEST, ApiError, body, db, list_response,
                  new_resource, ok, opt_int, req_str, require_roles, touch)
from serializers import ser_publication

bp = Blueprint("publications", __name__)


def get_publication_or_404(publication_id):
    p = db.publications.get(publication_id)
    if p is None:
        raise ApiError("ERR_PUBLICATION_NOT_FOUND", 404, "Publication not found")
    return p


@bp.post("/feedback-panel/publications")
@require_roles("DataAnalyst")
def create_publication():
    data = body()
    wave_id = req_str(data, "wave_id")
    weight_snapshot_id = req_str(data, "weight_snapshot_id")
    wave = db.waves.get(wave_id)
    if wave is None:
        raise ApiError("ERR_WAVE_NOT_FOUND", 404, "Survey wave not found")
    snap = db.snapshots.get(weight_snapshot_id)
    if snap is None:
        raise ApiError("ERR_SNAPSHOT_NOT_FOUND", 404, "Weight snapshot not found")
    title = req_str(data, "title")
    k_threshold = opt_int(data, "k_threshold", 5)
    if snap["wave_id"] != wave_id:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "weight_snapshot_id does not belong to wave_id")
    groups = {}
    for r in db.responses.values():
        if r["wave_id"] == wave_id and r["status"] == "ACCEPTED":
            cid = db.panelists[r["panelist_id"]]["home_cell_id"]
            groups[cid] = groups.get(cid, 0) + 1
    breakdown = []
    for cid in sorted(groups):
        n = groups[cid]
        breakdown.append({
            "cell_id": cid,
            "n_respondents": n,
            "weighted_share": snap["weighted_cell_shares"].get(cid, 0.0),
            "suppressed": 0 < n < k_threshold,
        })
    pub = new_resource()
    pub.update({
        "wave_id": wave_id,
        "weight_snapshot_id": weight_snapshot_id,
        "title": title,
        "k_threshold": k_threshold,
        "breakdown_cells": breakdown,
        "status": "DRAFT",
    })
    db.publications[pub["id"]] = pub
    return ok(ser_publication(pub), 201)


@bp.get("/feedback-panel/publications")
@require_roles("DataAnalyst", "PrivacyOfficer", "DepartmentLiaison")
def list_publications():
    items = list(db.publications.values())
    wave_id = request.args.get("wave_id")
    if wave_id is not None:
        items = [p for p in items if p["wave_id"] == wave_id]
    weight_snapshot_id = request.args.get("weight_snapshot_id")
    if weight_snapshot_id is not None:
        items = [p for p in items if p["weight_snapshot_id"] == weight_snapshot_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response(items, ser_publication)


@bp.get("/feedback-panel/publications/<publication_id>")
@require_roles("DataAnalyst", "PrivacyOfficer", "DepartmentLiaison")
def get_publication(publication_id):
    return ok(ser_publication(get_publication_or_404(publication_id)))


@bp.post("/feedback-panel/publications/<publication_id>/publish")
@require_roles("PrivacyOfficer")
def publish(publication_id):
    pub = get_publication_or_404(publication_id)
    if pub["status"] != "DRAFT":
        raise ApiError("ERR_PUBLICATION_NOT_PUBLISHED", 409,
                       "Publish requires publication status DRAFT")
    snap = db.snapshots[pub["weight_snapshot_id"]]
    if snap["status"] != "FINALIZED":
        raise ApiError("ERR_SNAPSHOT_NOT_FINALIZED", 409,
                       "Publish requires the pinned snapshot to be FINALIZED")
    wave = db.waves[pub["wave_id"]]
    if wave["status"] != "WEIGHTED":
        raise ApiError("ERR_WAVE_NOT_WEIGHTED", 409,
                       "Publish requires wave status WEIGHTED")
    if g.user_id == snap["finalized_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "The publisher must differ from the snapshot finalizer")
    for b in pub["breakdown_cells"]:
        if 0 < b["n_respondents"] < pub["k_threshold"]:
            raise ApiError("ERR_K_ANONYMITY_VIOLATION", 422,
                           "A breakdown cell has fewer than k_threshold respondents")
    pub["status"] = "PUBLISHED"
    touch(pub)
    wave["status"] = "PUBLISHED"
    touch(wave)
    return ok(ser_publication(pub))


@bp.post("/feedback-panel/publications/<publication_id>/retract")
@require_roles("PrivacyOfficer")
def retract(publication_id):
    pub = get_publication_or_404(publication_id)
    if pub["status"] != "PUBLISHED":
        raise ApiError("ERR_PUBLICATION_NOT_PUBLISHED", 409,
                       "Retract requires publication status PUBLISHED")
    pub["status"] = "RETRACTED"
    touch(pub)
    for c in db.commitments.values():
        if c["publication_id"] == pub["id"] and c["status"] in ("COMMITTED", "IN_PROGRESS"):
            c["status"] = "SUSPENDED"
            touch(c)
    return ok(ser_publication(pub))
