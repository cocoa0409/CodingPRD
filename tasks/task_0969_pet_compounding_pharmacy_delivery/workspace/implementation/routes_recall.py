from flask import Blueprint, request

import db
from errors import ApiError
from middleware import auth, body, require_ownership
from response import success, paged
from services import (get_or_404, covered_lots, activate_recall_cascade)
from util import new_resource, touch, req, as_str, as_enum, now_iso

bp = Blueprint("recall", __name__)

RECALL_READ = ("Pharmacist", "ComplianceOfficer", "PharmacyAdmin")
TASK_READ = ("Owner", "ComplianceOfficer", "PharmacyAdmin")


def _filter(items, names):
    out = []
    for it in items:
        ok = True
        for n in names:
            v = request.args.get(n)
            if v is not None and str(it.get(n)) != v:
                ok = False
                break
        if ok:
            out.append(it)
    return out


# ---- Recalls ----

@bp.route("/recalls", methods=["POST"])
def create_recall():
    auth("ComplianceOfficer")
    d = body()
    scope = as_enum(req(d, "scope"), "scope", {"LOT", "CATALOG_ITEM"})
    lot_id = d.get("lot_id")
    drug_id = d.get("drug_catalog_item_id")
    if lot_id is not None:
        get_or_404(db.lots, lot_id, "lot")
    if drug_id is not None:
        get_or_404(db.drug_catalog_items, drug_id, "drug catalog item")
    if scope == "LOT" and lot_id is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "lot_id is required for LOT scope", 400)
    if scope == "CATALOG_ITEM" and drug_id is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "drug_catalog_item_id is required for CATALOG_ITEM scope", 400)
    reason = as_str(req(d, "reason"), "reason")
    severity = as_enum(req(d, "severity"), "severity",
                       {"CLASS_I", "CLASS_II", "CLASS_III"})
    r = new_resource({
        "scope": scope,
        "lot_id": lot_id if scope == "LOT" else None,
        "drug_catalog_item_id": drug_id if scope == "CATALOG_ITEM" else None,
        "reason": reason, "severity": severity,
        "status": "DRAFT", "activated_at": None,
    })
    db.recalls[r["id"]] = r
    return success(r, 201)


@bp.route("/recalls/<rid>", methods=["GET"])
def get_recall(rid):
    auth("Owner", "Pharmacist", "ComplianceOfficer", "PharmacyAdmin")
    return success(get_or_404(db.recalls, rid, "recall"))


@bp.route("/recalls", methods=["GET"])
def list_recalls():
    auth(*RECALL_READ)
    return paged(_filter(list(db.recalls.values()),
                         ["lot_id", "drug_catalog_item_id", "status"]))


@bp.route("/recalls/<rid>/activate", methods=["POST"])
def activate_recall(rid):
    auth("ComplianceOfficer")
    r = get_or_404(db.recalls, rid, "recall")
    if r["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "recall is not DRAFT", 409)
    r["status"] = "ACTIVE"
    r["activated_at"] = now_iso()
    activate_recall_cascade(r)
    touch(r)
    return success(r)


@bp.route("/recalls/<rid>/complete", methods=["POST"])
def complete_recall(rid):
    auth("ComplianceOfficer")
    r = get_or_404(db.recalls, rid, "recall")
    if r["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "recall is not ACTIVE", 409)
    for t in db.recall_tasks.values():
        if t["recall_id"] == r["id"] and t["status"] not in ("NOTIFIED",
                                                             "ACKNOWLEDGED"):
            raise ApiError("ERR_INVALID_STATE",
                           "every recall task must be NOTIFIED or ACKNOWLEDGED "
                           "before completion", 409)
    for lot in covered_lots(r):
        if lot["status"] == "QUARANTINED" and lot.get("recall_id") == r["id"]:
            lot["status"] = "RECALLED"
            touch(lot)
    r["status"] = "COMPLETED"
    touch(r)
    return success(r)


@bp.route("/recalls/<rid>/tasks", methods=["GET"])
def list_recall_tasks(rid):
    auth(*TASK_READ)
    get_or_404(db.recalls, rid, "recall")
    return paged([t for t in db.recall_tasks.values() if t["recall_id"] == rid])


# ---- Recall tasks ----

@bp.route("/recall-tasks", methods=["GET"])
def list_tasks():
    auth(*TASK_READ)
    return paged(_filter(list(db.recall_tasks.values()),
                         ["recall_id", "compound_order_id", "owner_id", "status"]))


@bp.route("/recall-tasks/<rid>", methods=["GET"])
def get_task(rid):
    auth(*TASK_READ)
    return success(get_or_404(db.recall_tasks, rid, "recall task"))


@bp.route("/recall-tasks/<rid>/mark-notified", methods=["POST"])
def mark_notified(rid):
    auth("ComplianceOfficer")
    t = get_or_404(db.recall_tasks, rid, "recall task")
    if t["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "task is not PENDING", 409)
    t["status"] = "NOTIFIED"
    touch(t)
    return success(t)


@bp.route("/recall-tasks/<rid>/mark-failed", methods=["POST"])
def mark_failed(rid):
    auth("ComplianceOfficer")
    t = get_or_404(db.recall_tasks, rid, "recall task")
    if t["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "task is not PENDING", 409)
    t["status"] = "FAILED"
    touch(t)
    return success(t)


@bp.route("/recall-tasks/<rid>/acknowledge", methods=["POST"])
def acknowledge(rid):
    _, user_id = auth("Owner")
    t = get_or_404(db.recall_tasks, rid, "recall task")
    require_ownership(user_id, t["owner_id"])
    if t["status"] != "NOTIFIED":
        raise ApiError("ERR_INVALID_STATE", "task is not NOTIFIED", 409)
    t["status"] = "ACKNOWLEDGED"
    touch(t)
    return success(t)
