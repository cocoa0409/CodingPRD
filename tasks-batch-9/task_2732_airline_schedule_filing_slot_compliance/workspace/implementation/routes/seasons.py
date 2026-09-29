"""The season calendar: creation, one-step transitions and the slot audit."""
from flask import Blueprint

import cascades
import db
import reqval as rv
from db import mark, store
from errors import ApiError
from middleware import authenticate
from response import ok, written, written_raw
from routes.common import READ_ROLES, list_response, read_one
from util import dt_of, fmt_dt

bp = Blueprint("seasons", __name__)

ADMIN = ("SystemAdmin",)
NEXT_STATUS = {"DRAFT": "OPEN", "OPEN": "CLOSED", "CLOSED": "ARCHIVED", "ARCHIVED": None}
AUDIT_THRESHOLD = 80.00


@bp.post("/seasons")
def create_season():
    authenticate(ADMIN)
    payload = rv.body()
    code = rv.req_str(payload, "season_code", 2, 4)
    start = rv.req_dt(payload, "start_date")
    end = rv.req_dt(payload, "end_date")
    return_deadline = rv.req_dt(payload, "slot_return_deadline_utc")
    window_close = rv.req_dt(payload, "filing_change_window_close_utc")
    if dt_of(end) <= dt_of(start):
        rv.bad("end_date must be strictly later than start_date.")
    if dt_of(return_deadline) >= dt_of(start):
        rv.bad("slot_return_deadline_utc must fall strictly before start_date.")
    if dt_of(window_close) >= dt_of(start):
        rv.bad("filing_change_window_close_utc must fall strictly before start_date.")
    if dt_of(return_deadline) > dt_of(window_close):
        rv.bad("slot_return_deadline_utc must be at or before filing_change_window_close_utc.")
    for row in store.values("seasons"):
        if row["season_code"] == code:
            rv.bad("A season with that season_code already exists.")
    row = store.insert("seasons", {
        "season_code": code,
        "start_date": start,
        "end_date": end,
        "slot_return_deadline_utc": return_deadline,
        "filing_change_window_close_utc": window_close,
        "status": "DRAFT",
        "slot_audit_completed_at_utc": None,
        "audit_reference": None,
        "held_series_count": 0,
    })
    return written(row, 201)


@bp.get("/seasons/<season_id>")
def get_season(season_id):
    return ok(read_one("seasons", season_id))


@bp.get("/seasons")
def list_seasons():
    authenticate(READ_ROLES)
    return list_response("seasons", [
        ("status", rv.q_enum("status", "season_status")),
        ("season_code", rv.q_str("season_code")),
    ])


@bp.post("/seasons/<season_id>/transition")
def transition_season(season_id):
    authenticate(ADMIN)
    season = store.require("seasons", season_id)
    payload = rv.body()
    target = rv.req_enum(payload, "to_status", "season_status")
    if target != NEXT_STATUS[season["status"]]:
        raise ApiError("ERR_SEASON_STATE_INVALID")
    if target == "ARCHIVED" and season["slot_audit_completed_at_utc"] is None:
        raise ApiError("ERR_SEASON_AUDIT_PENDING")
    season["status"] = target
    mark(season)
    if target == "ARCHIVED":
        _archive_holdings(season)
    return written(season)


def _archive_holdings(season):
    """Grandfather rights carry forward; everything else in HELD expires."""
    for holding in store.values("slot_holdings"):
        if holding["season_id"] != season["id"] or holding["holding_status"] != "HELD":
            continue
        if holding["retains_historic_precedence"]:
            holding["historic_precedence"] = True
        else:
            holding["holding_status"] = "EXPIRED"
            holding["historic_precedence"] = False
        mark(holding)


@bp.post("/seasons/<season_id>/slot-audit")
def slot_audit(season_id):
    authenticate(("SlotCoordinator",))
    season = store.require("seasons", season_id)
    payload = rv.body()
    reference = rv.req_str(payload, "audit_reference", 1, 120)
    if season["status"] != "CLOSED":
        raise ApiError("ERR_SEASON_STATE_INVALID")
    if season["slot_audit_completed_at_utc"] is not None:
        raise ApiError("ERR_SLOT_AUDIT_ALREADY_RUN")

    audited = [
        holding for holding in store.values("slot_holdings")
        if holding["season_id"] == season_id and holding["holding_status"] == "HELD"
    ]
    audited_ids = [holding["id"] for holding in audited]
    retained = 0
    lost = 0
    for holding in audited:
        if float(holding["utilization_pct"] or 0.0) >= AUDIT_THRESHOLD:
            holding["retains_historic_precedence"] = True
            mark(holding)
            retained += 1
        else:
            cascades.lose_holding(holding)
            lost += 1

    season["slot_audit_completed_at_utc"] = fmt_dt(db.now())
    season["audit_reference"] = reference
    mark(season)

    summary = {
        "audited_count": len(audited),
        "retained_count": retained,
        "lost_count": lost,
        "audit_reference": reference,
        "audited_slot_holding_ids": audited_ids,
    }
    return written_raw(lambda: summary)
