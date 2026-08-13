from decimal import Decimal

from flask import Blueprint, request

from core import (ERR_INVALID_REQUEST, ApiError, body, db, list_response,
                  new_resource, now, ok, parse_dt, req_int, req_num, req_str,
                  require_roles, touch)
from logic import (STRIKE_LIMIT, WAVE_TERMINAL, cell_touch, compute_streak,
                   final_response_rate, projected_response_rate,
                   representativeness_score)
from routes.instruments import certified_locale_set
from serializers import ser_wave

bp = Blueprint("waves", __name__)


def get_wave_or_404(wave_id):
    w = db.waves.get(wave_id)
    if w is None:
        raise ApiError("ERR_WAVE_NOT_FOUND", 404, "Survey wave not found")
    return w


@bp.post("/feedback-panel/survey-waves")
@require_roles("PanelManager")
def create_wave():
    data = body()
    wave_code = req_str(data, "wave_code")
    instrument_id = req_str(data, "instrument_id")
    instrument = db.instruments.get(instrument_id)
    if instrument is None:
        raise ApiError("ERR_INSTRUMENT_NOT_FOUND", 404, "Instrument not found")
    opens_at = parse_dt(data.get("opens_at"), "opens_at")
    closes_at = parse_dt(data.get("closes_at"), "closes_at")
    if closes_at <= opens_at:
        raise ApiError(ERR_INVALID_REQUEST, 400, "closes_at must be strictly later than opens_at")
    rate = req_num(data, "min_response_rate")
    rate_d = Decimal(str(rate))
    if rate_d <= 0 or rate_d > 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "min_response_rate must be in (0, 1]")
    pool_total = req_int(data, "incentive_pool_total_cents", min_value=0)
    base_incentive = req_int(data, "base_incentive_cents", min_value=0)
    for w in db.waves.values():
        if w["wave_code"] == wave_code:
            raise ApiError(ERR_INVALID_REQUEST, 400, "wave_code already exists")
    w = new_resource()
    w.update({
        "wave_code": wave_code,
        "instrument_id": instrument_id,
        "opens_at": opens_at,
        "closes_at": closes_at,
        "min_response_rate": rate,
        "incentive_pool_total_cents": pool_total,
        "base_incentive_cents": base_incentive,
        "incentive_pool_available_cents": pool_total,
        "incentive_pool_reserved_cents": 0,
        "incentive_pool_paid_cents": 0,
        "invited_count": 0,
        "completed_count": 0,
        "status": "DRAFT",
    })
    db.waves[w["id"]] = w
    return ok(ser_wave(w), 201)


@bp.get("/feedback-panel/survey-waves")
@require_roles("PanelManager", "DataAnalyst")
def list_waves():
    items = list(db.waves.values())
    instrument_id = request.args.get("instrument_id")
    if instrument_id is not None:
        items = [w for w in items if w["instrument_id"] == instrument_id]
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    return list_response(items, ser_wave)


@bp.get("/feedback-panel/survey-waves/<wave_id>")
@require_roles("PanelManager", "DataAnalyst", "PrivacyOfficer", "IncentiveClerk")
def get_wave(wave_id):
    return ok(ser_wave(get_wave_or_404(wave_id)))


@bp.post("/feedback-panel/survey-waves/<wave_id>/arm")
@require_roles("PanelManager")
def arm(wave_id):
    w = get_wave_or_404(wave_id)
    if w["status"] in WAVE_TERMINAL:
        raise ApiError("ERR_WAVE_ALREADY_TERMINAL", 409, "Wave is terminal")
    if w["status"] != "DRAFT":
        raise ApiError("ERR_WAVE_INVALID_STATE", 409, "Arm requires wave status DRAFT")
    inst = db.instruments[w["instrument_id"]]
    if inst["status"] != "LOCKED":
        raise ApiError("ERR_INSTRUMENT_NOT_LOCKED", 409,
                       "Wave arm requires instrument status LOCKED")
    certified = certified_locale_set(inst)
    for loc in inst["required_locales"]:
        if loc not in certified:
            raise ApiError("ERR_TRANSLATION_NOT_CERTIFIED", 409,
                           "Locale %s lacks a CERTIFIED translation at the current revision" % loc)
    if now() > w["opens_at"]:
        raise ApiError("ERR_WAVE_WINDOW_NOT_OPEN", 409,
                       "The current time is past opens_at")
    w["status"] = "ARMED"
    touch(w)
    return ok(ser_wave(w))


@bp.post("/feedback-panel/survey-waves/<wave_id>/open-fielding")
@require_roles("PanelManager")
def open_fielding(wave_id):
    w = get_wave_or_404(wave_id)
    if w["status"] in WAVE_TERMINAL:
        raise ApiError("ERR_WAVE_ALREADY_TERMINAL", 409, "Wave is terminal")
    if w["status"] != "ARMED":
        raise ApiError("ERR_WAVE_NOT_ARMED", 409,
                       "Open-fielding requires wave status ARMED")
    if not (w["opens_at"] <= now() <= w["closes_at"]):
        raise ApiError("ERR_WAVE_WINDOW_NOT_OPEN", 409,
                       "The current time is outside the fielding window")
    w["status"] = "FIELDING"
    touch(w)
    return ok(ser_wave(w))


@bp.post("/feedback-panel/survey-waves/<wave_id>/close")
@require_roles("PanelManager")
def close(wave_id):
    w = get_wave_or_404(wave_id)
    if w["status"] in WAVE_TERMINAL:
        raise ApiError("ERR_WAVE_ALREADY_TERMINAL", 409, "Wave is terminal")
    if w["status"] != "FIELDING":
        raise ApiError("ERR_WAVE_NOT_FIELDING", 409, "Close requires wave status FIELDING")
    gate = now() > w["closes_at"]
    if not gate and w["invited_count"] > 0:
        rate = Decimal(w["completed_count"]) / Decimal(w["invited_count"])
        if rate >= Decimal(str(w["min_response_rate"])):
            gate = True
    if not gate:
        raise ApiError("ERR_MIN_RESPONSE_NOT_MET", 409,
                       "Early close requires completed/invited >= min_response_rate")
    # Cascade hop 1: expire every SENT invitation of the wave.
    sent = [i for i in db.invitations.values()
            if i["wave_id"] == w["id"] and i["status"] == "SENT"]
    sent.sort(key=lambda i: i["_seq"])
    affected = {}
    for inv in sent:
        inv["status"] = "EXPIRED"
        touch(inv)
        p = db.panelists[inv["panelist_id"]]
        affected[p["id"]] = p
        cell = db.cells.get(p["home_cell_id"])
        if cell is not None:
            cell["reserved_count"] -= 1
            cell_touch(cell)
    # Cascade hops 2-3: recompute streaks, lapse panelists at the strike limit.
    for pid in sorted(affected):
        p = affected[pid]
        streak = compute_streak(p)
        if p["status"] == "ACTIVE" and streak >= STRIKE_LIMIT:
            p["status"] = "LAPSED"
            p["lapsed_at"] = now()
            p["missed_streak"] = 0
            touch(p)
        elif streak != p["missed_streak"]:
            p["missed_streak"] = streak
            touch(p)
    w["status"] = "CLOSED"
    touch(w)
    return ok(ser_wave(w))


@bp.post("/feedback-panel/survey-waves/<wave_id>/cancel")
@require_roles("PanelManager")
def cancel(wave_id):
    w = get_wave_or_404(wave_id)
    if w["status"] in WAVE_TERMINAL:
        raise ApiError("ERR_WAVE_ALREADY_TERMINAL", 409, "Wave is terminal")
    if w["status"] not in ("DRAFT", "ARMED"):
        raise ApiError("ERR_WAVE_INVALID_STATE", 409,
                       "Cancel requires wave status DRAFT or ARMED")
    w["status"] = "CANCELLED"
    touch(w)
    return ok(ser_wave(w))


@bp.get("/feedback-panel/survey-waves/<wave_id>/analysis")
@require_roles("DataAnalyst")
def analysis(wave_id):
    w = get_wave_or_404(wave_id)
    return ok({
        "projected_response_rate": projected_response_rate(w),
        "final_response_rate": final_response_rate(w),
        "representativeness_score": representativeness_score(),
    })
