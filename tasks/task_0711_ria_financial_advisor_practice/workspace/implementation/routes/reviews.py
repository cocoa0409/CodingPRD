"""Review endpoints & cadence calendar (PRD §3.8)."""

from datetime import date, timedelta

from flask import Blueprint, request

from db import db, _iso_ms
from errors import err
from middleware import authenticate, authorize
from response import created, ok, list_ok
from services.common import stamp_new, touch
from services.lookup import get_or_404, ref_or_422
from util import body, require_str, require_iso_date, opt_pos_int, pagination, paginate

bp = Blueprint("reviews", __name__)

READ_ROLES = {"Advisor", "ComplianceOfficer", "BillingAdmin"}


def _is_overdue(r):
    """Lazy recompute: true when clock date > scheduled_for and status SCHEDULED."""
    if r["status"] != "SCHEDULED":
        return False
    return db.clock_date() > date.fromisoformat(r["scheduled_for"])


def serialize(r):
    return {
        "id": r["id"],
        "household_id": r["household_id"],
        "cadence_days": r["cadence_days"],
        "scheduled_for": r["scheduled_for"],
        "completed_at": r["completed_at"],
        "next_due_date": r["next_due_date"],
        "is_overdue": _is_overdue(r),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.route("/reviews", methods=["POST"])
def create():
    _, role = authenticate()
    authorize(role, {"Advisor"})
    data = body()
    household_id = require_str(data, "household_id")
    scheduled_for = require_iso_date(data, "scheduled_for")
    cadence_days = opt_pos_int(data, "cadence_days", 365)
    ref_or_422(db.households, household_id, "household_id")
    # review-date collision (priority 10): two SCHEDULED reviews for same
    # household may not share the same scheduled_for.
    new_date = date.fromisoformat(scheduled_for)
    existing_scheduled = [
        x for x in db.reviews.values()
        if x["household_id"] == household_id and x["status"] == "SCHEDULED"
    ]
    for x in existing_scheduled:
        if x["scheduled_for"] == scheduled_for:
            raise err("ERR_REVIEW_DATE_COLLISION",
                      "Two scheduled reviews may not share a date")
    r = {
        "household_id": household_id,
        "cadence_days": cadence_days,
        "scheduled_for": scheduled_for,
        "completed_at": None,
        "next_due_date": None,
        "status": "SCHEDULED",
    }
    stamp_new(r)
    db.reviews[r["id"]] = r
    # supersede earlier SCHEDULED reviews whose scheduled_for is before this one
    for x in existing_scheduled:
        if date.fromisoformat(x["scheduled_for"]) < new_date:
            x["status"] = "MISSED"
            touch(x)
    return created(serialize(r))


@bp.route("/reviews/<rid>", methods=["GET"])
def read(rid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    r = get_or_404(db.reviews, rid)
    return ok(serialize(r))


@bp.route("/reviews", methods=["GET"])
def list_():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = pagination()
    household_id = request.args.get("household_id")
    items = list(db.reviews.values())
    if household_id is not None:
        items = [x for x in items if x["household_id"] == household_id]
    items = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    page = paginate(items, limit, offset)
    return list_ok([serialize(x) for x in page], limit, offset, len(items))


@bp.route("/reviews/<rid>/complete", methods=["POST"])
def complete(rid):
    _, role = authenticate()
    authorize(role, {"Advisor"})
    r = get_or_404(db.reviews, rid)
    if r["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "COMPLETE requires SCHEDULED")
    household = db.households.get(r["household_id"])
    if household is None or household["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Owning household must be ACTIVE")
    completed_dt = db.clock_now()
    r["completed_at"] = _iso_ms(completed_dt)
    next_due = completed_dt.date() + timedelta(days=r["cadence_days"])
    r["next_due_date"] = next_due.isoformat()
    r["status"] = "COMPLETED"
    touch(r)
    return ok(serialize(r))
