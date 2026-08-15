"""Settlements: reads, dispute workflow, payment (PRD 3.6/3.8)."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    raise_err, ERR_LOAD_NOT_FOUND, ERR_SETTLEMENT_NOT_FOUND,
    ERR_SETTLEMENT_NOT_PENDING, ERR_SETTLEMENT_NOT_DISPUTED,
    ERR_SETTLEMENT_NOT_COUNTERED, ERR_SETTLEMENT_NOT_PAYABLE,
    ERR_UNRESOLVED_DISPUTE, ERR_STALE_VERSION, ERR_DISPUTE_WINDOW_CLOSED,
    ERR_DISPUTE_WINDOW_OPEN, ERR_OPEN_CRITICAL_INCIDENT,
)
from middleware import require_role
from response import success
from util import get_body, v_int, v_str, paginate

bp = Blueprint("settlements", __name__)


def settlement_or_404(sid):
    st = db.store["settlements"].get(sid)
    if st is None:
        raise_err(ERR_SETTLEMENT_NOT_FOUND)
    return st


@bp.get("/haul/loads/<lid>/settlement")
def get_load_settlement(lid):
    if db.store["loads"].get(lid) is None:
        raise_err(ERR_LOAD_NOT_FOUND)
    st = svc.get_settlement_for_load(lid)
    data = [svc.settlement_json(st)] if st is not None else []
    meta = {"limit": 10, "offset": 0, "total_count": len(data), "has_more": False}
    return success(data, response_type="array", pagination=meta)


@bp.get("/haul/settlements")
def list_settlements():
    items = sorted(db.store["settlements"].values(), key=lambda s: s["seq"])
    st_f = request.args.get("status")
    if st_f is not None:
        items = [s for s in items if s["status"] == st_f]
    page, meta = paginate([svc.settlement_json(s) for s in items])
    return success(page, response_type="array", pagination=meta)


@bp.get("/haul/settlements/<sid>")
def get_settlement(sid):
    return success(svc.settlement_json(settlement_or_404(sid)))


@bp.post("/haul/settlements/<sid>/dispute")
def dispute(sid):
    require_role("ConsigneeAgent")
    body = get_body()
    weight = v_int(body, "disputed_weight_lb", min_value=1)
    st = settlement_or_404(sid)
    if st["status"] != "PENDING":
        raise_err(ERR_SETTLEMENT_NOT_PENDING, "dispute requires PENDING")
    if db.now() > st["dispute_deadline_at"]:
        raise_err(ERR_DISPUTE_WINDOW_CLOSED, "dispute window has closed")
    st["disputed_weight_lb"] = weight
    st["status"] = "DISPUTED"
    svc.touch(st)
    return success(svc.settlement_json(st))


@bp.post("/haul/settlements/<sid>/accept-original")
def accept_original(sid):
    require_role("ConsigneeAgent")
    st = settlement_or_404(sid)
    if st["status"] != "DISPUTED":
        raise_err(ERR_SETTLEMENT_NOT_DISPUTED, "accept-original requires DISPUTED")
    ld = db.store["loads"].get(st["load_id"])
    st["effective_delivered_weight_lb"] = st["delivered_weight_lb"]
    svc.apply_weight_basis(st, ld, st["delivered_weight_lb"])
    st["dispute_adjustment_cents"] = 0
    st["status"] = "RESOLVED"
    svc.touch(st)
    return success(svc.settlement_json(st))


@bp.post("/haul/settlements/<sid>/counter")
def counter(sid):
    require_role("Dispatcher")
    body = get_body()
    weight = v_int(body, "counter_weight_lb", min_value=1)
    expected = v_int(body, "expected_settlement_version")
    st = settlement_or_404(sid)
    if st["status"] not in ("DISPUTED", "COUNTERED"):
        raise_err(ERR_SETTLEMENT_NOT_DISPUTED, "counter requires DISPUTED or COUNTERED")
    if expected != st["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_settlement_version does not match settlement version")
    st["counter_weight_lb"] = weight
    st["status"] = "COUNTERED"
    svc.touch(st)
    return success(svc.settlement_json(st))


@bp.post("/haul/settlements/<sid>/redispute")
def redispute(sid):
    require_role("ConsigneeAgent")
    body = get_body()
    weight = v_int(body, "disputed_weight_lb", required=False, min_value=1)
    st = settlement_or_404(sid)
    if st["status"] != "COUNTERED":
        raise_err(ERR_SETTLEMENT_NOT_COUNTERED, "redispute requires COUNTERED")
    if db.now() > st["dispute_deadline_at"]:
        raise_err(ERR_DISPUTE_WINDOW_CLOSED, "dispute window has closed")
    if weight is not None:
        st["disputed_weight_lb"] = weight
    st["status"] = "DISPUTED"
    svc.touch(st)
    return success(svc.settlement_json(st))


@bp.post("/haul/settlements/<sid>/accept-counter")
def accept_counter(sid):
    require_role("ConsigneeAgent")
    st = settlement_or_404(sid)
    if st["status"] != "COUNTERED":
        raise_err(ERR_SETTLEMENT_NOT_COUNTERED, "accept-counter requires COUNTERED")
    ld = db.store["loads"].get(st["load_id"])
    # adjustment = penalty on the delivered-weight basis - penalty on counter basis
    _, _, _, penalty_delivered = svc.shrink_fields(ld, st["delivered_weight_lb"])
    _, _, _, penalty_counter = svc.shrink_fields(ld, st["counter_weight_lb"])
    st["dispute_adjustment_cents"] = penalty_delivered - penalty_counter
    st["effective_delivered_weight_lb"] = st["counter_weight_lb"]
    svc.apply_weight_basis(st, ld, st["counter_weight_lb"])
    st["status"] = "RESOLVED"
    svc.touch(st)
    return success(svc.settlement_json(st))


@bp.post("/haul/settlements/<sid>/pay")
def pay(sid):
    require_role("CarrierAdmin")
    st = settlement_or_404(sid)
    if st["status"] in ("PRELIMINARY", "PAID"):
        raise_err(ERR_SETTLEMENT_NOT_PAYABLE, "pay requires PENDING or RESOLVED")
    if st["status"] in ("DISPUTED", "COUNTERED"):
        raise_err(ERR_UNRESOLVED_DISPUTE, "settlement has an unresolved dispute")
    for inc in db.store["incidents"].values():
        if (inc["load_id"] == st["load_id"] and inc["severity"] == "CRITICAL"
                and inc["status"] in ("REPORTED", "UNDER_REVIEW")):
            raise_err(ERR_OPEN_CRITICAL_INCIDENT,
                      "an open CRITICAL incident blocks payment")
    if st["status"] == "PENDING" and db.now() <= st["dispute_deadline_at"]:
        raise_err(ERR_DISPUTE_WINDOW_OPEN,
                  "paying from PENDING requires the dispute window to have run out")
    st["paid_at"] = db.now()
    st["status"] = "PAID"
    svc.touch(st)
    return success(svc.settlement_json(st))
