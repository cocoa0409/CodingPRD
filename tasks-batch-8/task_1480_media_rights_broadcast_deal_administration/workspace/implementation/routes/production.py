import db
from errors import raise_error
from flask import Blueprint, request
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from serializers import serialize
from services import calculations as calc
from services.clock import now, parse_iso
from util import (apply_filters, get_json_body, get_pagination, paginate,
                  req_datetime, req_int, req_string, sorted_by_created,
                  stamp_new, touch)

bp = Blueprint("production", __name__)


def _get_deal_or_404(deal_id):
    d = db.deals.get(deal_id)
    if d is None:
        raise_error("ERR_DEAL_NOT_FOUND")
    return d


def _get_obligation_scoped(deal_id, obligation_id):
    _get_deal_or_404(deal_id)
    o = db.production_obligations.get(obligation_id)
    if o is None or o["deal_id"] != deal_id:
        raise_error("ERR_OBLIGATION_NOT_FOUND")
    return o


def _get_event_scoped(deal_id, event_id):
    _get_deal_or_404(deal_id)
    e = db.broadcast_events.get(event_id)
    if e is None or e["deal_id"] != deal_id:
        raise_error("ERR_EVENT_NOT_FOUND")
    return e


def _get_measurement_scoped(deal_id, measurement_id):
    _get_deal_or_404(deal_id)
    m = db.audience_measurements.get(measurement_id)
    if m is None or m["deal_id"] != deal_id:
        raise_error("ERR_MEASUREMENT_NOT_FOUND")
    return m


def _season_end_for(deal, season_index):
    asset = db.rights_assets.get(deal["asset_id"])
    if asset is None:
        return deal.get("term_end")
    # Season n spans [season_start + (n-1) years, season_start + n years) approximated
    # against the asset's season bounds for season 1, extended yearly thereafter.
    from datetime import timedelta
    season_length = asset["season_end_date"] - asset["season_start_date"]
    return asset["season_end_date"] + season_length * (season_index - 1)


# --- Production obligations -------------------------------------------------

@bp.route("/deals/<dealId>/production-obligations", methods=["POST"])
def create_obligation(dealId):
    require_roles({"ProductionAuditor"})
    deal = _get_deal_or_404(dealId)
    body = get_json_body()
    season_index = req_int(body, "season_index", minimum=1)
    bid = db.bids.get(deal["winning_bid_id"])
    games_required = bid["production_commitment_games"] if bid else 0
    obligation = {
        "deal_id": dealId,
        "season_index": season_index,
        "games_required": games_required,
        "games_delivered": 0,
        "shortfall_games": 0,
        "make_good_credit_cents": 0,
        "credit_settled_cents": 0,
        "status": "TRACKING",
    }
    stamp_new(obligation)
    db.production_obligations[obligation["id"]] = obligation
    return success_object(serialize(obligation), status_code=201)


@bp.route("/deals/<dealId>/production-obligations", methods=["GET"])
def list_obligations(dealId):
    require_roles(ALL_ROLES)
    _get_deal_or_404(dealId)
    limit, offset = get_pagination()
    items = [o for o in db.production_obligations.values() if o["deal_id"] == dealId]
    items = sorted_by_created(items)
    items = apply_filters(items, [
        ("status", request.args.get("status")),
        ("season_index", request.args.get("season_index")),
        ("deal_id", request.args.get("deal_id")),
    ])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(o) for o in page], limit, offset, total)


@bp.route("/deals/<dealId>/production-obligations/<obligationId>", methods=["GET"])
def get_obligation(dealId, obligationId):
    require_roles(ALL_ROLES)
    return success_object(serialize(_get_obligation_scoped(dealId, obligationId)))


@bp.route("/production-obligations", methods=["GET"])
def list_obligations_flat():
    require_roles(ALL_ROLES)
    limit, offset = get_pagination()
    items = sorted_by_created(list(db.production_obligations.values()))
    items = apply_filters(items, [
        ("deal_id", request.args.get("deal_id")),
        ("status", request.args.get("status")),
        ("season_index", request.args.get("season_index")),
    ])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(o) for o in page], limit, offset, total)


@bp.route("/production-obligations/<obligationId>", methods=["GET"])
def get_obligation_flat(obligationId):
    require_roles(ALL_ROLES)
    o = db.production_obligations.get(obligationId)
    if o is None:
        raise_error("ERR_OBLIGATION_NOT_FOUND")
    return success_object(serialize(o))


@bp.route("/deals/<dealId>/production-obligations/<obligationId>/declare-shortfall", methods=["POST"])
def declare_shortfall(dealId, obligationId):
    require_roles({"ProductionAuditor"})
    o = _get_obligation_scoped(dealId, obligationId)
    deal = db.deals[dealId]
    if o["status"] != "TRACKING":
        raise_error("ERR_INVALID_REQUEST", "Declare-shortfall requires obligation TRACKING")
    season_end = _season_end_for(deal, o["season_index"])
    if season_end is not None and now() <= season_end:
        raise_error("ERR_NO_SHORTFALL", "Season has not closed yet")
    if o["games_delivered"] >= o["games_required"]:
        raise_error("ERR_NO_SHORTFALL")
    o["shortfall_games"] = o["games_required"] - o["games_delivered"]
    o["make_good_credit_cents"] = calc.make_good_credit(deal, o)
    o["status"] = "SHORTFALL_DECLARED"
    o["shortfall_declared_at"] = now()
    touch(o)
    deal["accrued_make_good_credit_cents"] = deal.get("accrued_make_good_credit_cents", 0) + o["make_good_credit_cents"]
    touch(deal)
    calc.refresh_posture(deal)
    return success_object(serialize(o))


@bp.route("/deals/<dealId>/production-obligations/<obligationId>/apply-remedy", methods=["POST"])
def apply_remedy(dealId, obligationId):
    require_roles({"ProductionAuditor"})
    o = _get_obligation_scoped(dealId, obligationId)
    deal = db.deals[dealId]
    if o["status"] != "SHORTFALL_DECLARED":
        raise_error("ERR_INVALID_REQUEST", "Apply-remedy requires obligation SHORTFALL_DECLARED")
    if o["credit_settled_cents"] != o["make_good_credit_cents"]:
        raise_error("ERR_INVALID_REQUEST", "Apply-remedy requires credit fully offset")
    o["status"] = "REMEDIED"
    touch(o)
    deal["accrued_make_good_credit_cents"] = deal.get("accrued_make_good_credit_cents", 0) - o["make_good_credit_cents"]
    touch(deal)
    calc.refresh_posture(deal)
    return success_object(serialize(o))


@bp.route("/deals/<dealId>/production-obligations/<obligationId>/forgive-credit", methods=["POST"])
def forgive_credit(dealId, obligationId):
    require_roles({"RightsManager"})
    o = _get_obligation_scoped(dealId, obligationId)
    deal = db.deals[dealId]
    if o["status"] != "SHORTFALL_DECLARED":
        raise_error("ERR_INVALID_REQUEST", "Forgive-credit requires obligation SHORTFALL_DECLARED")
    if o["credit_settled_cents"] != 0:
        raise_error("ERR_INVALID_REQUEST", "Forgive-credit requires credit_settled_cents == 0")
    credit = o["make_good_credit_cents"]
    o["make_good_credit_cents"] = 0
    o["status"] = "CREDITED"
    touch(o)
    deal["accrued_make_good_credit_cents"] = deal.get("accrued_make_good_credit_cents", 0) - credit
    touch(deal)
    calc.refresh_posture(deal)
    return success_object(serialize(o))


# --- Broadcast events --------------------------------------------------------

@bp.route("/deals/<dealId>/broadcast-events", methods=["POST"])
def create_event(dealId):
    require_roles({"ProductionAuditor"})
    _get_deal_or_404(dealId)
    body = get_json_body()
    obligation_id = body.get("obligation_id")
    if not isinstance(obligation_id, str) or obligation_id not in db.production_obligations:
        raise_error("ERR_OBLIGATION_NOT_FOUND")
    obligation = db.production_obligations[obligation_id]
    if obligation["deal_id"] != dealId:
        raise_error("ERR_OBLIGATION_NOT_FOUND")
    event_code = req_string(body, "event_code")
    scheduled_kickoff = req_datetime(body, "scheduled_kickoff_utc", parse_iso)
    event = {
        "deal_id": dealId,
        "obligation_id": obligation_id,
        "event_code": event_code,
        "scheduled_kickoff_utc": scheduled_kickoff,
        "actual_air_start_utc": None,
        "status": "SCHEDULED",
    }
    stamp_new(event)
    db.broadcast_events[event["id"]] = event
    return success_object(serialize(event), status_code=201)


@bp.route("/deals/<dealId>/broadcast-events", methods=["GET"])
def list_events(dealId):
    require_roles(ALL_ROLES)
    _get_deal_or_404(dealId)
    limit, offset = get_pagination()
    items = [e for e in db.broadcast_events.values() if e["deal_id"] == dealId]
    items = sorted_by_created(items)
    items = apply_filters(items, [
        ("status", request.args.get("status")),
        ("obligation_id", request.args.get("obligation_id")),
        ("deal_id", request.args.get("deal_id")),
    ])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(e) for e in page], limit, offset, total)


@bp.route("/deals/<dealId>/broadcast-events/<eventId>", methods=["GET"])
def get_event(dealId, eventId):
    require_roles(ALL_ROLES)
    return success_object(serialize(_get_event_scoped(dealId, eventId)))


@bp.route("/broadcast-events", methods=["GET"])
def list_events_flat():
    require_roles(ALL_ROLES)
    limit, offset = get_pagination()
    items = sorted_by_created(list(db.broadcast_events.values()))
    items = apply_filters(items, [
        ("deal_id", request.args.get("deal_id")),
        ("obligation_id", request.args.get("obligation_id")),
        ("status", request.args.get("status")),
    ])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(e) for e in page], limit, offset, total)


@bp.route("/broadcast-events/<eventId>", methods=["GET"])
def get_event_flat(eventId):
    require_roles(ALL_ROLES)
    e = db.broadcast_events.get(eventId)
    if e is None:
        raise_error("ERR_EVENT_NOT_FOUND")
    return success_object(serialize(e))


@bp.route("/deals/<dealId>/broadcast-events/<eventId>/mark-delivered", methods=["POST"])
def mark_delivered(dealId, eventId):
    require_roles({"ProductionAuditor"})
    e = _get_event_scoped(dealId, eventId)
    body = get_json_body()
    if e["status"] != "SCHEDULED":
        raise_error("ERR_INVALID_REQUEST", "Mark-delivered requires event SCHEDULED")
    obligation = db.production_obligations.get(e["obligation_id"])
    if obligation is None:
        raise_error("ERR_OBLIGATION_NOT_FOUND")
    if obligation["status"] != "TRACKING":
        raise_error("ERR_OBLIGATION_NOT_TRACKING")
    actual_air_start = req_datetime(body, "actual_air_start_utc", parse_iso)
    e["actual_air_start_utc"] = actual_air_start
    e["status"] = "DELIVERED"
    touch(e)
    obligation["games_delivered"] += 1
    if obligation["games_delivered"] == obligation["games_required"] and obligation["status"] == "TRACKING":
        obligation["status"] = "MET"
    touch(obligation)
    deal = db.deals.get(dealId)
    if deal is not None:
        calc.refresh_posture(deal)
    return success_object(serialize(e))


@bp.route("/deals/<dealId>/broadcast-events/<eventId>/mark-no-show", methods=["POST"])
def mark_no_show(dealId, eventId):
    require_roles({"ProductionAuditor"})
    e = _get_event_scoped(dealId, eventId)
    if e["status"] != "SCHEDULED":
        raise_error("ERR_INVALID_REQUEST", "Mark-no-show requires event SCHEDULED")
    from datetime import timedelta
    if now() <= e["scheduled_kickoff_utc"] + timedelta(hours=calc.NO_SHOW_GRACE_HOURS):
        raise_error("ERR_INVALID_REQUEST", "No-show grace period has not elapsed")
    e["status"] = "NO_SHOW"
    touch(e)
    return success_object(serialize(e))


@bp.route("/deals/<dealId>/broadcast-events/<eventId>/cancel-by-league", methods=["POST"])
def cancel_by_league(dealId, eventId):
    require_roles({"RightsManager"})
    e = _get_event_scoped(dealId, eventId)
    if e["status"] != "SCHEDULED":
        raise_error("ERR_INVALID_REQUEST", "Cancel-by-league requires event SCHEDULED")
    e["status"] = "CANCELLED_BY_LEAGUE"
    touch(e)
    obligation = db.production_obligations.get(e["obligation_id"])
    if obligation is not None:
        obligation["games_required"] = max(0, obligation["games_required"] - 1)
        touch(obligation)
    return success_object(serialize(e))


@bp.route("/deals/<dealId>/broadcast-events/<eventId>/cancel-by-broadcaster", methods=["POST"])
def cancel_by_broadcaster(dealId, eventId):
    require_roles({"ProductionAuditor"})
    e = _get_event_scoped(dealId, eventId)
    if e["status"] != "SCHEDULED":
        raise_error("ERR_INVALID_REQUEST", "Cancel-by-broadcaster requires event SCHEDULED")
    e["status"] = "CANCELLED_BY_BROADCASTER"
    touch(e)
    return success_object(serialize(e))


# --- Audience measurements ---------------------------------------------------

MEASUREMENT_SOURCES = {"PANEL", "CENSUS", "HYBRID"}


@bp.route("/deals/<dealId>/audience-measurements", methods=["POST"])
def create_measurement(dealId):
    require_roles({"ProductionAuditor"})
    _get_deal_or_404(dealId)
    body = get_json_body()
    broadcast_event_id = body.get("broadcast_event_id")
    if not isinstance(broadcast_event_id, str) or broadcast_event_id not in db.broadcast_events:
        raise_error("ERR_EVENT_NOT_FOUND")
    event = db.broadcast_events[broadcast_event_id]
    if event["deal_id"] != dealId:
        raise_error("ERR_EVENT_NOT_FOUND")
    reporting_period_end = req_datetime(body, "reporting_period_end", parse_iso)
    rating_bp = req_int(body, "rating_basis_points", minimum=0)
    if rating_bp > 20000:
        raise_error("ERR_INVALID_REQUEST", "rating_basis_points must be <= 20000")
    source = body.get("source")
    if source not in MEASUREMENT_SOURCES:
        raise_error("ERR_INVALID_REQUEST", f"source must be one of {sorted(MEASUREMENT_SOURCES)}")
    m = {
        "deal_id": dealId,
        "broadcast_event_id": broadcast_event_id,
        "reporting_period_end": reporting_period_end,
        "rating_basis_points": rating_bp,
        "source": source,
        "status": "PROVISIONAL",
    }
    stamp_new(m)
    db.audience_measurements[m["id"]] = m
    return success_object(serialize(m), status_code=201)


@bp.route("/deals/<dealId>/audience-measurements", methods=["GET"])
def list_measurements(dealId):
    require_roles(ALL_ROLES)
    _get_deal_or_404(dealId)
    limit, offset = get_pagination()
    items = [m for m in db.audience_measurements.values() if m["deal_id"] == dealId]
    items = sorted_by_created(items)
    items = apply_filters(items, [
        ("status", request.args.get("status")),
        ("broadcast_event_id", request.args.get("broadcast_event_id")),
        ("deal_id", request.args.get("deal_id")),
    ])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(m) for m in page], limit, offset, total)


@bp.route("/deals/<dealId>/audience-measurements/<measurementId>", methods=["GET"])
def get_measurement(dealId, measurementId):
    require_roles(ALL_ROLES)
    return success_object(serialize(_get_measurement_scoped(dealId, measurementId)))


@bp.route("/audience-measurements", methods=["GET"])
def list_measurements_flat():
    require_roles(ALL_ROLES)
    limit, offset = get_pagination()
    items = sorted_by_created(list(db.audience_measurements.values()))
    items = apply_filters(items, [
        ("deal_id", request.args.get("deal_id")),
        ("broadcast_event_id", request.args.get("broadcast_event_id")),
        ("status", request.args.get("status")),
    ])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(m) for m in page], limit, offset, total)


@bp.route("/audience-measurements/<measurementId>", methods=["GET"])
def get_measurement_flat(measurementId):
    require_roles(ALL_ROLES)
    m = db.audience_measurements.get(measurementId)
    if m is None:
        raise_error("ERR_MEASUREMENT_NOT_FOUND")
    return success_object(serialize(m))


@bp.route("/deals/<dealId>/audience-measurements/<measurementId>/confirm", methods=["POST"])
def confirm_measurement(dealId, measurementId):
    require_roles({"ProductionAuditor"})
    m = _get_measurement_scoped(dealId, measurementId)
    if m["status"] not in ("PROVISIONAL", "DISPUTED"):
        raise_error("ERR_INVALID_REQUEST", "Confirm requires measurement PROVISIONAL or DISPUTED")
    event = db.broadcast_events.get(m["broadcast_event_id"])
    if event is None or event["status"] != "DELIVERED":
        raise_error("ERR_EVENT_NOT_DELIVERED")
    m["status"] = "CONFIRMED"
    touch(m)
    deal = db.deals.get(dealId)
    if deal is not None:
        deal["cumulative_rating_basis_points"] = deal.get("cumulative_rating_basis_points", 0) + m["rating_basis_points"]
        touch(deal)
        calc.refresh_posture(deal)
    return success_object(serialize(m))


@bp.route("/deals/<dealId>/audience-measurements/<measurementId>/dispute", methods=["POST"])
def dispute_measurement(dealId, measurementId):
    require_roles({"BidCoordinator"})
    m = _get_measurement_scoped(dealId, measurementId)
    if m["status"] != "PROVISIONAL":
        raise_error("ERR_INVALID_REQUEST", "Dispute requires measurement PROVISIONAL")
    m["status"] = "DISPUTED"
    touch(m)
    return success_object(serialize(m))


@bp.route("/deals/<dealId>/audience-measurements/<measurementId>/exclude", methods=["POST"])
def exclude_measurement(dealId, measurementId):
    require_roles({"ComplianceOfficer"})
    m = _get_measurement_scoped(dealId, measurementId)
    if m["status"] != "DISPUTED":
        raise_error("ERR_INVALID_REQUEST", "Exclude requires measurement DISPUTED")
    m["status"] = "EXCLUDED"
    touch(m)
    return success_object(serialize(m))
