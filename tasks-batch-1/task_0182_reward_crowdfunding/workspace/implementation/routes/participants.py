"""Creator and Backer registration + reads, plus the test-driving clock."""
from flask import Blueprint

from db import db
from errors import err, ERR_NOT_FOUND
from middleware import require_role
from response import success
from services import domain
from util import get_json_body, require_str, parse_dt

bp = Blueprint("participants", __name__)


# ---- Creator ----
@bp.route("/creators", methods=["POST"])
def create_creator():
    require_role(["PlatformAdmin"])
    body = get_json_body()
    display_name = require_str(body, "display_name")
    payout_currency = require_str(body, "payout_currency")
    rec = {
        "display_name": display_name,
        "payout_currency": payout_currency,
    }
    domain._stamp_new(rec, versioned=True)
    db.creators[rec["id"]] = rec
    return success(domain.serialize(rec), status=201)


@bp.route("/creators/<creator_id>", methods=["GET"])
def get_creator(creator_id):
    require_role(["PlatformAdmin", "Creator", "Backer"])
    rec = db.creators.get(creator_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Creator not found")
    return success(domain.serialize(rec), status=200)


# ---- Backer ----
@bp.route("/backers", methods=["POST"])
def create_backer():
    require_role(["PlatformAdmin"])
    body = get_json_body()
    email = require_str(body, "email")
    display_name = require_str(body, "display_name")
    rec = {
        "email": email,
        "display_name": display_name,
        "lifetime_authorized_cents": 0,
        "lifetime_captured_cents": 0,
        "declined_auth_count": 0,
        "reliability_score": 100.0,
    }
    domain._stamp_new(rec, versioned=True)
    db.backers[rec["id"]] = rec
    return success(domain.serialize(rec), status=201)


@bp.route("/backers/<backer_id>", methods=["GET"])
def get_backer(backer_id):
    require_role(["PlatformAdmin", "Creator", "Backer"])
    rec = db.backers.get(backer_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Backer not found")
    return success(domain.serialize(rec), status=200)


# ---- Clock (test-driving) ----
from errors import ERR_INVALID_REQUEST  # noqa: E402


def _require_now_utc(body):
    raw = body.get("now_utc")
    dt = parse_dt(raw)
    if dt is None:
        raise err(ERR_INVALID_REQUEST, "now_utc must be an ISO 8601 UTC timestamp")
    # Store canonical ISO string with ms precision.
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@bp.route("/_clock/set", methods=["POST"])
def clock_set():
    require_role(["PlatformAdmin"])
    body = get_json_body()
    db.clock = _require_now_utc(body)
    return success({}, status=200)


@bp.route("/_clock/advance", methods=["POST"])
def clock_advance():
    require_role(["PlatformAdmin"])
    body = get_json_body()
    new_clock = _require_now_utc(body)
    db.clock = new_clock
    new_dt = parse_dt(new_clock)
    # Auto-close any LIVE campaign whose deadline_utc <= new clock.
    due = []
    for c in db.campaigns.values():
        if c["status"] == "LIVE":
            deadline = parse_dt(c["deadline_utc"])
            if deadline is not None and deadline <= new_dt:
                due.append(c)
    # Settle in deterministic order (created_at, _seq).
    due.sort(key=lambda c: (c["created_at"], c["_seq"]))
    for c in due:
        domain.settle_campaign(c)
    return success({}, status=200)
