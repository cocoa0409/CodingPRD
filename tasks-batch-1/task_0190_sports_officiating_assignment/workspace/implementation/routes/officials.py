"""Official endpoints (PRD §3.1, §3.12).

POST   /officials                     register + create SeasonLedger row
GET    /officials
GET    /officials/{id}
PATCH  /officials/{id}                 OCC on expected_official_version
GET    /officials/{id}/eligibility     recompute postseason breakdown
GET    /officials/{id}/assignments
GET    /officials/{id}/ledger
"""
from flask import Blueprint, request

import db
import lookup
import serialize
from errors import err, ERR_STALE_OFFICIAL_VERSION, ERR_INVALID_REQUEST
from middleware import get_user_context, require_role
from pagination import get_pagination, paginate
from response import object_response, array_response
from services import validate, derive

bp = Blueprint("officials", __name__)

RANKS = {"ROOKIE", "CERTIFIED", "SENIOR", "MASTER"}
STATUSES = {"ACTIVE", "SUSPENDED"}
READ_ROLES = {"LeagueAdmin", "Assignor", "Official", "Evaluator"}


@bp.route("/officials", methods=["POST"])
def create_official():
    _, role = get_user_context()
    require_role(role, {"LeagueAdmin"})
    data = validate.body()
    league_id = validate.require_str(data, "league_id")
    full_name = validate.require_str(data, "full_name")
    rank = validate.enum(data, "rank", RANKS, required=False, default="ROOKIE")
    home_lat = validate.number(data, "home_lat")
    home_lon = validate.number(data, "home_lon")
    max_travel = validate.number(data, "max_travel_miles", required=False,
                                 default=50)
    with db.lock:
        league = lookup.league(league_id)
        rec = {
            "league_id": league_id,
            "full_name": full_name,
            "rank": rank,
            "home_lat": home_lat,
            "home_lon": home_lon,
            "max_travel_miles": max_travel,
            "status": "ACTIVE",
            "games_worked_count": 0,
            "noshow_count": 0,
            "penalty_points": 0,
            "mean_rating": None,
            "reliability_score": 100,
            "postseason_eligible": False,
        }
        db.stamp_create(rec)
        db.officials[rec["id"]] = rec
        # Create the official's SeasonLedger row (one per official per league).
        ledger = {
            "league_id": league_id,
            "official_id": rec["id"],
            "penalty_points": 0,
            "total_pay_accrued_cents": 0,
            "total_mileage_accrued_cents": 0,
        }
        db.stamp_create(ledger)
        db.season_ledgers[ledger["id"]] = ledger
    return object_response(serialize.official(rec), 201)


@bp.route("/officials", methods=["GET"])
def list_officials():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    league_id = request.args.get("league_id")
    with db.lock:
        rows = list(db.officials.values())
        if league_id is not None:
            rows = [o for o in rows if o["league_id"] == league_id]
        page, total = paginate(rows, limit, offset)
        items = [serialize.official(r) for r in page]
    return array_response(items, limit, offset, total)


@bp.route("/officials/<official_id>", methods=["GET"])
def get_official(official_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    with db.lock:
        rec = lookup.official(official_id)
        return object_response(serialize.official(rec))


@bp.route("/officials/<official_id>", methods=["PATCH"])
def update_official(official_id):
    _, role = get_user_context()
    require_role(role, {"LeagueAdmin"})
    data = validate.body()
    with db.lock:
        rec = lookup.official(official_id)
        # OCC (priority 16) before input validity (priority 17).
        if "expected_official_version" not in data or data["expected_official_version"] is None:
            err(ERR_INVALID_REQUEST, "expected_official_version is required")
        expected = data["expected_official_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            err(ERR_INVALID_REQUEST, "expected_official_version must be an integer")
        if expected != rec["version"]:
            err(ERR_STALE_OFFICIAL_VERSION, "official version mismatch")
        rank = validate.enum(data, "rank", RANKS, required=False, default=None)
        status = validate.enum(data, "status", STATUSES, required=False, default=None)
        max_travel = validate.number(data, "max_travel_miles", required=False,
                                     default=None)
        if rank is not None:
            rec["rank"] = rank
        if status is not None:
            rec["status"] = status
        if max_travel is not None:
            rec["max_travel_miles"] = max_travel
        db.touch(rec)
        # Status change can affect derived eligibility; refresh derived fields.
        derive.recompute_official_derived(rec)
        return object_response(serialize.official(rec))


@bp.route("/officials/<official_id>/eligibility", methods=["GET"])
def official_eligibility(official_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    with db.lock:
        rec = lookup.official(official_id)
        # Read-time recompute (PRD §3.12). Persist refreshed derived fields.
        derive.recompute_official_derived(rec)
        return object_response(serialize.official(rec))


@bp.route("/officials/<official_id>/assignments", methods=["GET"])
def official_assignments(official_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    with db.lock:
        lookup.official(official_id)
        rows = [a for a in db.assignments.values() if a["official_id"] == official_id]
        page, total = paginate(rows, limit, offset)
        items = [serialize.assignment(r) for r in page]
    return array_response(items, limit, offset, total)


@bp.route("/officials/<official_id>/ledger", methods=["GET"])
def official_ledger(official_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    with db.lock:
        lookup.official(official_id)
        rows = [l for l in db.season_ledgers.values() if l["official_id"] == official_id]
        page, total = paginate(rows, limit, offset)
        items = [serialize.ledger(r) for r in page]
    return array_response(items, limit, offset, total)
