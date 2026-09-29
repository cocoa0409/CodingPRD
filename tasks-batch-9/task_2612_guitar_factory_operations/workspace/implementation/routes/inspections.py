"""Playability setup inspection rounds (PRD 3.8)."""

from flask import Blueprint

import auth
import calc
import domain
import validate as v
from constants import (INSPECTION_STATUSES, MAX_REWORK_ROUNDS,
                       PASS_SCORE_MAX, VERDICTS)
from envelope import object_response, paginate
from errors import ApiError
from serialize import inspection_view
from store import INSPECTIONS, ORDERS, new_record, touch

bp = Blueprint("inspections", __name__)

OPEN_STATUSES = ("OPEN", "MEASURED")


def _round(inspection_id):
    return v.fetch(INSPECTIONS, inspection_id, "ERR_SETUP_INSPECTION_NOT_FOUND")


@bp.post("/build-orders/<build_order_id>/setup-inspections")
def open_round(build_order_id):
    user_id, _role = auth.require(auth.LUTHIER)
    order = v.fetch(ORDERS, build_order_id, "ERR_BUILD_ORDER_NOT_FOUND")
    if order["build_stage"] not in ("SETUP", "INSPECTION"):
        raise ApiError("ERR_BUILD_STAGE_INVALID",
                       "an inspection round opens from SETUP or INSPECTION")
    existing = [r for r in INSPECTIONS.values()
                if r["build_order_id"] == order["id"]]
    if any(r["status"] in OPEN_STATUSES for r in existing):
        raise ApiError("ERR_INSPECTION_ROUND_OPEN",
                       "a round on this order is still in progress")
    if order["rework_round_count"] >= MAX_REWORK_ROUNDS:
        raise ApiError("ERR_MAX_REWORK_EXCEEDED",
                       "the rework loop has run its three permitted times")
    rec = new_record(INSPECTIONS, {
        "build_order_id": order["id"],
        "round_number": len(existing) + 1,
        "action_mm_treble": None,
        "action_mm_bass": None,
        "relief_mm": None,
        "intonation_cents_max": None,
        "deviation_score": None,
        "verdict": "PENDING",
        "performed_by_user_id": user_id,
        "inspector_user_id": None,
        "status": "OPEN",
    })
    order["build_stage"] = "INSPECTION"
    touch(order)
    return object_response(inspection_view(rec), 201)


@bp.get("/setup-inspections/<inspection_id>")
def read_round(inspection_id):
    auth.require_staff()
    return object_response(inspection_view(_round(inspection_id)))


@bp.get("/setup-inspections")
def list_rounds():
    auth.require_staff()
    rows = v.apply_filters(list(INSPECTIONS.values()), [
        ("build_order_id", v.filter_value("build_order_id")),
        ("status", v.filter_enum("status", INSPECTION_STATUSES)),
        ("verdict", v.filter_enum("verdict", VERDICTS)),
    ])
    rows.sort(key=lambda r: (r["round_number"], r["created_at"], r["_seq"]))
    return paginate(rows, inspection_view)


@bp.post("/setup-inspections/<inspection_id>/measure")
def measure(inspection_id):
    user_id, _role = auth.require(auth.LUTHIER)
    rec = _round(inspection_id)
    if rec["status"] != "OPEN":
        raise ApiError("ERR_INSPECTION_STATE_INVALID",
                       "only an OPEN round accepts measurements")
    if user_id != rec["performed_by_user_id"]:
        raise ApiError("ERR_MEASUREMENT_OWNER_MISMATCH",
                       "only the luthier who opened the round may measure it")
    body = v.body()
    treble = v.get_dec(body, "action_mm_treble", minimum="0.50",
                       maximum="5.00", scale=2)
    bass = v.get_dec(body, "action_mm_bass", minimum="0.50", maximum="6.00",
                     scale=2)
    relief = v.get_dec(body, "relief_mm", minimum="0.00", maximum="1.00",
                       scale=2)
    intonation = v.get_dec(body, "intonation_cents_max", minimum="0.0",
                           maximum="50.0", scale=1)
    rec["action_mm_treble"] = treble
    rec["action_mm_bass"] = bass
    rec["relief_mm"] = relief
    rec["intonation_cents_max"] = intonation
    rec["deviation_score"] = calc.deviation_score(treble, bass, relief,
                                                  intonation)
    rec["status"] = "MEASURED"
    touch(rec)
    return object_response(inspection_view(rec))


@bp.post("/setup-inspections/<inspection_id>/sign")
def sign(inspection_id):
    user_id, _role = auth.require(auth.QUALITY_INSPECTOR)
    rec = _round(inspection_id)
    if rec["status"] != "MEASURED":
        raise ApiError("ERR_INSPECTION_STATE_INVALID",
                       "only a MEASURED round may be signed")
    if user_id == rec["performed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the signing inspector may not be the setup luthier")
    order = ORDERS.get(rec["build_order_id"])
    if rec["deviation_score"] <= PASS_SCORE_MAX:
        rec["status"] = "SIGNED"
        rec["verdict"] = "PASS"
        rec["inspector_user_id"] = user_id
        touch(rec)
    else:
        rec["status"] = "FAILED"
        rec["verdict"] = "FAIL"
        touch(rec)
        if order is not None:
            domain.inspection_fail_cascade(order)
    return object_response(inspection_view(rec))
