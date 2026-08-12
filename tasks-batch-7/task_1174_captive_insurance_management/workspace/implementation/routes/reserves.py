"""ActuarialReserve routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from clock import fmt_ts, now_iso, parse_ts
from errors import ApiError
from middleware import require_roles
from response import ok, paginate
from services import constants as C
from services.audit import log
from services.core import (
    body,
    compute_reserve_estimates,
    get_captive,
    get_program,
    get_reserve,
    opt_num,
    parse_dt_field,
    recompute_captive_ledger,
    req_enum,
    stamp_new,
    touch,
)

bp = Blueprint("reserves", __name__)

READ_ROLES = ("CaptiveManager", "Underwriter", "Actuary")


def _chain(captiveId, programId):
    captive = get_captive(captiveId)
    program = get_program(captive, programId)
    return captive, program


@bp.post("/api/captives/<captiveId>/programs/<programId>/reserves")
def create_reserve(captiveId, programId):
    user_id, role = require_roles("Actuary")
    captive, program = _chain(captiveId, programId)
    data = body()
    reserve_type = req_enum(data, "reserve_type", C.RESERVE_TYPES)
    method = req_enum(data, "actuarial_method", C.ACTUARIAL_METHODS)
    valuation = parse_dt_field(data, "valuation_date")
    confidence = opt_num(data, "confidence_level_pct", C.CONFIDENCE_LEVEL_DEFAULT)
    if confidence < C.CONFIDENCE_LEVEL_MIN or confidence > C.CONFIDENCE_LEVEL_MAX:
        raise ApiError("ERR_INVALID_REQUEST",
                       "confidence_level_pct must be between 50 and 95")

    reserve = stamp_new()
    reserve.update({
        "program_id": programId,
        "captive_id": captiveId,
        "reserve_type": reserve_type,
        "actuarial_method": method,
        "valuation_date": fmt_ts(valuation),
        "central_estimate_cents": 0,
        "low_estimate_cents": 0,
        "high_estimate_cents": 0,
        "carried_reserve_cents": 0,
        "confidence_level_pct": confidence,
        "development_factor": 0.0,
        "certified_by": None,
        "certification_date": None,
        "status": "PRELIMINARY",
        "created_by": user_id,
    })
    compute_reserve_estimates(captive, program, reserve)
    db.reserves[reserve["id"]] = reserve

    # Supersede any prior CERTIFIED reserve for the same program + type with an
    # earlier valuation date.
    superseded = False
    for other in db.reserves.values():
        if other["id"] == reserve["id"]:
            continue
        if (other["program_id"] == programId
                and other["reserve_type"] == reserve_type
                and other["status"] == "CERTIFIED"):
            other_date = parse_ts(other.get("valuation_date"))
            if other_date is not None and other_date < valuation:
                other["status"] = "SUPERSEDED"
                touch(other)
                superseded = True
    if superseded:
        recompute_captive_ledger(captive)

    log(captiveId, "CALCULATION_RUN", "ActuarialReserve", reserve["id"], role,
        user_id, "Actuarial reserve created PRELIMINARY; estimates computed",
        None, "PRELIMINARY")
    return ok(reserve, 201)


@bp.get("/api/captives/<captiveId>/programs/<programId>/reserves")
def list_reserves(captiveId, programId):
    require_roles(*READ_ROLES)
    _chain(captiveId, programId)
    items = [r for r in db.reserves.values() if r["program_id"] == programId]
    type_filter = request.args.get("reserve_type")
    if type_filter:
        items = [r for r in items if r["reserve_type"] == type_filter]
    status_filter = request.args.get("status")
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]
    items.sort(key=lambda e: e["created_at"])
    page, meta = paginate(items, request.args)
    return ok(page, 200, meta)


@bp.get("/api/captives/<captiveId>/programs/<programId>/reserves/<reserveId>")
def get_reserve_route(captiveId, programId, reserveId):
    require_roles(*READ_ROLES)
    _, program = _chain(captiveId, programId)
    return ok(get_reserve(program, reserveId), 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/reserves/<reserveId>/review")
def review_reserve(captiveId, programId, reserveId):
    user_id, role = require_roles("Actuary")
    captive, program = _chain(captiveId, programId)
    reserve = get_reserve(program, reserveId)
    if reserve["status"] != "PRELIMINARY":
        raise ApiError("ERR_RESERVE_NOT_PRELIMINARY",
                       "Actuarial reserve must be in PRELIMINARY state")
    prev = reserve["status"]
    compute_reserve_estimates(captive, program, reserve)
    reserve["status"] = "REVIEWED"
    touch(reserve)
    log(captiveId, "CALCULATION_RUN", "ActuarialReserve", reserveId, role,
        user_id, "Reserve reviewed; estimates recomputed", prev, "REVIEWED")
    return ok(reserve, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/reserves/<reserveId>/certify")
def certify_reserve(captiveId, programId, reserveId):
    user_id, role = require_roles("Actuary")
    captive, program = _chain(captiveId, programId)
    reserve = get_reserve(program, reserveId)
    if reserve["status"] != "REVIEWED":
        raise ApiError("ERR_RESERVE_NOT_REVIEWED",
                       "Actuarial reserve must be in REVIEWED state")
    if reserve.get("created_by") == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Same user cannot perform both creation and certification of the same reserve")
    data = body()
    carried = data.get("carried_reserve_cents")
    if carried is None or isinstance(carried, bool) or not isinstance(carried, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST",
                       "carried_reserve_cents is required and must be a number")
    carried = int(carried)
    if carried < int(reserve["low_estimate_cents"]) or carried > int(
            reserve["high_estimate_cents"]):
        raise ApiError("ERR_RESERVE_OUT_OF_RANGE",
                       "Carried reserve is outside actuarial range (below low estimate or above high estimate)")
    prev = reserve["status"]
    reserve["carried_reserve_cents"] = carried
    reserve["certified_by"] = user_id
    reserve["certification_date"] = now_iso()
    reserve["status"] = "CERTIFIED"
    touch(reserve)
    recompute_captive_ledger(captive)
    log(captiveId, "CERTIFICATION", "ActuarialReserve", reserveId, role,
        user_id, f"Reserve certified; carried reserve {carried} cents", prev,
        "CERTIFIED")
    return ok(reserve, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/reserves/<reserveId>/file")
def file_reserve(captiveId, programId, reserveId):
    user_id, role = require_roles("CaptiveManager")
    captive, program = _chain(captiveId, programId)
    reserve = get_reserve(program, reserveId)
    if reserve["status"] != "CERTIFIED":
        raise ApiError("ERR_RESERVE_NOT_CERTIFIED",
                       "Actuarial reserve must be in CERTIFIED state")
    prev = reserve["status"]
    reserve["status"] = "FILED"
    touch(reserve)
    recompute_captive_ledger(captive)
    # Update the same-year annual statement's liabilities, if one exists.
    vdt = parse_ts(reserve.get("valuation_date"))
    if vdt is not None:
        for stmt in db.statements.values():
            if stmt["captive_id"] == captiveId and int(
                    stmt["statement_year"]) == vdt.year:
                from services.core import compute_statement_fields
                compute_statement_fields(captive, stmt)
                touch(stmt)
    log(captiveId, "FILING_SUBMITTED", "ActuarialReserve", reserveId, role,
        user_id, "Reserve filed with regulator", prev, "FILED")
    return ok(reserve, 200)
