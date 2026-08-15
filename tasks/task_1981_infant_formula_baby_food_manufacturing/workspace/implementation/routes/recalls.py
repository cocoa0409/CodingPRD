"""RecallCampaign and RecallScope endpoints."""
from decimal import Decimal

from flask import Blueprint, request

from db import store, now, new_id
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_INVALID_RANGE, ERR_RECALL_SCOPE_EMPTY,
                    ERR_RECOVERY_THRESHOLD_NOT_MET)
from middleware import authorized
from response import ok, paginate
from services import (ser_recall, ser_scope, get_or_404, stamp_new, touch,
                      compute_recovery_pct, RECALL_REASONS, RECALL_CLASSES,
                      WITHDRAWAL_LEVELS)
from util import get_body, require_fields, check_enum, to_decimal, q2

bp = Blueprint("recalls", __name__)

RECALL_READ = ("QA_MANAGER", "REGULATORY_AFFAIRS", "QUALITY_ANALYST", "SUPPLY_CHAIN_PLANNER")

RECOVERY_FLOORS = {"CLASS_I": Decimal("90.00"),
                   "CLASS_II": Decimal("80.00"),
                   "CLASS_III": Decimal("70.00")}


def _campaign_scopes(recall_id):
    return [s for s in store.scopes.values() if s["recall_id"] == recall_id]


def _overall_recovery(scopes):
    total_shipped = sum(s["quantity_shipped_kg"] for s in scopes)
    total_recovered = sum(s["quantity_recovered_kg"] for s in scopes)
    if total_shipped == 0:
        return Decimal("100.00")
    return q2((total_recovered / total_shipped) * Decimal(100))


# ------------------------------------------------------------------ campaigns
@bp.post("/recall-campaigns")
@authorized("QA_MANAGER")
def create_recall(_user_id=None, _role=None):
    body = get_body()
    require_fields(body, ["reason", "recall_class", "scope_description"])
    reason = check_enum(body["reason"], RECALL_REASONS, "reason")
    rclass = check_enum(body["recall_class"], RECALL_CLASSES, "recall_class")
    rec = stamp_new({
        "id": new_id(),
        "recall_ref": store.next_ref("R"),
        "reason": reason,
        "recall_class": rclass,
        "scope_description": body["scope_description"],
        "status": "INITIATED",
        "initiated_by": _user_id,
        "initiated_at": now(),
        "completed_at": None,
        "effectiveness_checks": None,
    })
    store.recalls[rec["id"]] = rec
    return ok(ser_recall(rec), 201)


@bp.get("/recall-campaigns")
@authorized(*RECALL_READ)
def list_recalls(_user_id=None, _role=None):
    records = list(store.recalls.values())
    for param, field in (("status", "status"), ("recall_class", "recall_class")):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[field] == v]
    return paginate(records, ser_recall)


@bp.get("/recall-campaigns/<rid>")
@authorized(*RECALL_READ)
def get_recall(rid, _user_id=None, _role=None):
    return ok(ser_recall(get_or_404(store.recalls, rid, "RecallCampaign")))


@bp.post("/recall-campaigns/<rid>/notify")
@authorized("REGULATORY_AFFAIRS")
def notify_recall(rid, _user_id=None, _role=None):
    rec = get_or_404(store.recalls, rid, "RecallCampaign")
    if rec["status"] != "INITIATED":
        raise err(ERR_INVALID_STATE,
                  "RecallCampaign in status %s cannot be notified" % rec["status"])
    scopes = _campaign_scopes(rec["id"])
    if not scopes:
        raise err(ERR_RECALL_SCOPE_EMPTY,
                  "Recall campaign must have at least one scope entry before notification")
    if not all(s["status"] == "PENDING" for s in scopes):
        raise err(ERR_INVALID_STATE,
                  "All scope entries must be PENDING before notification")
    rec["status"] = "NOTIFIED"
    touch(rec)
    for s in scopes:
        s["status"] = "NOTIFIED"
        touch(s)
    return ok(ser_recall(rec))


@bp.post("/recall-campaigns/<rid>/begin-recovery")
@authorized("SUPPLY_CHAIN_PLANNER")
def begin_recovery(rid, _user_id=None, _role=None):
    rec = get_or_404(store.recalls, rid, "RecallCampaign")
    if rec["status"] != "NOTIFIED":
        raise err(ERR_INVALID_STATE,
                  "RecallCampaign in status %s cannot begin recovery" % rec["status"])
    rec["status"] = "IN_PROGRESS"
    touch(rec)
    for s in _campaign_scopes(rec["id"]):
        if s["status"] == "NOTIFIED":
            s["status"] = "IN_PROGRESS"
            touch(s)
    return ok(ser_recall(rec))


@bp.post("/recall-campaigns/<rid>/start-effectiveness-check")
@authorized("QUALITY_ANALYST")
def start_effectiveness(rid, _user_id=None, _role=None):
    rec = get_or_404(store.recalls, rid, "RecallCampaign")
    if rec["status"] != "IN_PROGRESS":
        raise err(ERR_INVALID_STATE,
                  "RecallCampaign in status %s cannot start effectiveness check"
                  % rec["status"])
    scopes = _campaign_scopes(rec["id"])
    if not scopes or not all(s["status"] in ("RECOVERED", "VERIFIED") for s in scopes):
        raise err(ERR_INVALID_STATE,
                  "All scope entries must be RECOVERED or VERIFIED")
    rec["status"] = "EFFECTIVENESS_CHECK"
    rec["effectiveness_checks"] = [{
        "check_date": __import__("util").fmt_dt(now()),
        "consignee_count": len(scopes),
        "response_count": sum(1 for s in scopes if s["quantity_recovered_kg"] > 0),
        "recovery_pct": float(_overall_recovery(scopes)),
    }]
    touch(rec)
    return ok(ser_recall(rec))


@bp.post("/recall-campaigns/<rid>/complete")
@authorized("QA_MANAGER")
def complete_recall(rid, _user_id=None, _role=None):
    rec = get_or_404(store.recalls, rid, "RecallCampaign")
    if rec["status"] != "EFFECTIVENESS_CHECK":
        raise err(ERR_INVALID_STATE,
                  "RecallCampaign in status %s cannot be completed" % rec["status"])
    scopes = _campaign_scopes(rec["id"])
    if not scopes or not all(s["status"] == "VERIFIED" for s in scopes):
        raise err(ERR_INVALID_STATE,
                  "All scope entries must be VERIFIED before completion")
    overall = _overall_recovery(scopes)
    floor = RECOVERY_FLOORS[rec["recall_class"]]
    if overall < floor:
        raise err(ERR_RECOVERY_THRESHOLD_NOT_MET,
                  "Overall recovery_pct %s is below the %s threshold for %s"
                  % (overall, floor, rec["recall_class"]))
    rec["status"] = "COMPLETED"
    rec["completed_at"] = now()
    touch(rec)
    return ok(ser_recall(rec))


@bp.post("/recall-campaigns/<rid>/terminate")
@authorized("QA_MANAGER")
def terminate_recall(rid, _user_id=None, _role=None):
    rec = get_or_404(store.recalls, rid, "RecallCampaign")
    if rec["status"] != "INITIATED":
        raise err(ERR_INVALID_STATE,
                  "RecallCampaign in status %s cannot be terminated" % rec["status"])
    body = get_body()
    require_fields(body, ["termination_reason"])
    rec["status"] = "TERMINATED"
    touch(rec)
    batch_ids = set()
    for s in _campaign_scopes(rec["id"]):
        s["status"] = "VERIFIED"
        touch(s)
        batch_ids.add(s["batch_id"])
    for bid in batch_ids:
        batch = store.batches.get(bid)
        if batch is not None and batch["status"] == "RECALLED":
            batch["status"] = "RELEASED"
            touch(batch)
    return ok(ser_recall(rec))


# ------------------------------------------------------------------ scopes
@bp.post("/recall-campaigns/<rid>/scopes")
@authorized("QA_MANAGER")
def create_scope(rid, _user_id=None, _role=None):
    rec = get_or_404(store.recalls, rid, "RecallCampaign")
    body = get_body()
    batch = None
    if body.get("batch_id") is not None:
        batch = get_or_404(store.batches, body["batch_id"], "ProductionBatch")
    if rec["status"] in ("COMPLETED", "TERMINATED"):
        raise err(ERR_INVALID_STATE,
                  "RecallCampaign in status %s cannot accept scope entries" % rec["status"])
    require_fields(body, ["batch_id", "withdrawal_level", "quantity_shipped_kg"])
    level = check_enum(body["withdrawal_level"], WITHDRAWAL_LEVELS, "withdrawal_level")
    shipped = to_decimal(body["quantity_shipped_kg"], "quantity_shipped_kg")
    if shipped < 0:
        raise err(ERR_INVALID_RANGE, "quantity_shipped_kg must be non-negative")
    shipped = shipped.quantize(Decimal("0.001"))
    if batch["status"] != "RELEASED":
        raise err(ERR_INVALID_STATE,
                  "ProductionBatch in status %s cannot be added to recall scope"
                  % batch["status"])
    scope = stamp_new({
        "id": new_id(),
        "recall_id": rec["id"],
        "batch_id": batch["id"],
        "withdrawal_level": level,
        "status": "PENDING",
        "quantity_shipped_kg": shipped,
        "quantity_recovered_kg": Decimal("0"),
        "recovery_pct": Decimal("100.00") if shipped == 0 else Decimal("0.00"),
    })
    store.scopes[scope["id"]] = scope
    # cascade: RELEASED -> RECALLED
    batch["status"] = "RECALLED"
    touch(batch)
    return ok(ser_scope(scope), 201)


@bp.get("/recall-campaigns/<rid>/scopes")
@authorized(*RECALL_READ)
def list_campaign_scopes(rid, _user_id=None, _role=None):
    get_or_404(store.recalls, rid, "RecallCampaign")
    return paginate(_campaign_scopes(rid), ser_scope)


@bp.get("/recall-scopes")
@authorized(*RECALL_READ)
def list_scopes(_user_id=None, _role=None):
    records = list(store.scopes.values())
    for param, field in (("recall_id", "recall_id"), ("batch_id", "batch_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            records = [s for s in records if s[field] == v]
    return paginate(records, ser_scope)


@bp.get("/recall-scopes/<sid>")
@authorized(*RECALL_READ)
def get_scope(sid, _user_id=None, _role=None):
    return ok(ser_scope(get_or_404(store.scopes, sid, "RecallScope")))


@bp.post("/recall-scopes/<sid>/record-recovery")
@authorized("SUPPLY_CHAIN_PLANNER")
def record_recovery(sid, _user_id=None, _role=None):
    scope = get_or_404(store.scopes, sid, "RecallScope")
    if scope["status"] != "IN_PROGRESS":
        raise err(ERR_INVALID_STATE,
                  "RecallScope in status %s cannot record recovery" % scope["status"])
    body = get_body()
    require_fields(body, ["recovered_kg"])
    amount = to_decimal(body["recovered_kg"], "recovered_kg")
    if amount <= 0:
        raise err(ERR_INVALID_RANGE, "recovered_kg must be greater than 0")
    scope["quantity_recovered_kg"] += amount.quantize(Decimal("0.001"))
    scope["recovery_pct"] = compute_recovery_pct(scope)
    if scope["quantity_recovered_kg"] >= scope["quantity_shipped_kg"]:
        scope["status"] = "RECOVERED"
    touch(scope)
    return ok(ser_scope(scope))


@bp.post("/recall-scopes/<sid>/verify")
@authorized("QUALITY_ANALYST")
def verify_scope(sid, _user_id=None, _role=None):
    scope = get_or_404(store.scopes, sid, "RecallScope")
    if scope["status"] not in ("IN_PROGRESS", "RECOVERED"):
        raise err(ERR_INVALID_STATE,
                  "RecallScope in status %s cannot be verified" % scope["status"])
    scope["status"] = "VERIFIED"
    touch(scope)
    return ok(ser_scope(scope))
