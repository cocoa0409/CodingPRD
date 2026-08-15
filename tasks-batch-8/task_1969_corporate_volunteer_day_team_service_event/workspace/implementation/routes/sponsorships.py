"""Sponsorship endpoints: pledge, commit, settle, withdraw."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_err,
    ERR_SPONSORSHIP_NOT_FOUND,
    ERR_EVENT_NOT_FOUND,
    ERR_INVALID_SPONSORSHIP_TRANSITION,
    ERR_EVENT_STATE_FORBIDS_WRITE,
)
from middleware import authenticate, body
from response import success_object, success_list
from services import calc
from services.core import mint, bump, refresh_event, ser_sponsorship, sort_entities
from validate import req_string, req_int, req_enum, check_range

bp = Blueprint("sponsorships", __name__)

FC = ["FinanceController"]
MATCH_TYPES = ("FLAT", "PER_CHECK_IN", "PER_VERIFIED_HOUR")


def load_sponsorship(sid):
    sp = db.sponsorships.get(sid)
    if sp is None:
        raise_err(ERR_SPONSORSHIP_NOT_FOUND, "sponsorship not found")
    return sp


@bp.post("/sponsorships")
def create_sponsorship():
    authenticate(FC)
    data = body()
    event_id = req_string(data, "event_id")
    sponsor_name = req_string(data, "sponsor_name")
    match_type = req_enum(data, "match_type", MATCH_TYPES)
    rate = req_int(data, "rate_cents")
    cap = req_int(data, "pledge_cap_cents")
    ev = db.events.get(event_id)
    if ev is None:
        raise_err(ERR_EVENT_NOT_FOUND, "service event not found")
    check_range(rate >= 1, "rate_cents must be >= 1")
    check_range(cap >= 1, "pledge_cap_cents must be >= 1")
    sp = mint()
    sp.update(
        {
            "event_id": ev["id"],
            "sponsor_name": sponsor_name,
            "match_type": match_type,
            "rate_cents": rate,
            "pledge_cap_cents": cap,
            "status": "PLEDGED",
            "provisional_amount_cents": 0,
            "settled_amount_cents": None,
        }
    )
    db.sponsorships[sp["id"]] = sp
    return success_object(ser_sponsorship(sp), 201)


@bp.get("/sponsorships")
def list_sponsorships():
    authenticate(["Any"])
    items = list(db.sponsorships.values())
    for param in ("event_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [s for s in items if str(s.get(param)) == val]
    return success_list([ser_sponsorship(s) for s in sort_entities(items)])


@bp.get("/sponsorships/<sponsorshipId>")
def get_sponsorship(sponsorshipId):
    authenticate(["Any"])
    return success_object(ser_sponsorship(load_sponsorship(sponsorshipId)))


@bp.post("/sponsorships/<sponsorshipId>/commit")
def commit_sponsorship(sponsorshipId):
    authenticate(FC)
    sp = load_sponsorship(sponsorshipId)
    if sp["status"] != "PLEDGED":
        raise_err(ERR_INVALID_SPONSORSHIP_TRANSITION, "only a PLEDGED sponsorship can be committed")
    sp["status"] = "COMMITTED"
    # bring the current forward-looking estimate into the credit
    sp["provisional_amount_cents"] = calc.provisional_amount(sp)
    bump(sp)
    ev = db.events.get(sp["event_id"])
    if ev is not None:
        refresh_event(ev)
    return success_object(ser_sponsorship(sp))


@bp.post("/sponsorships/<sponsorshipId>/settle")
def settle_sponsorship(sponsorshipId):
    authenticate(FC)
    sp = load_sponsorship(sponsorshipId)
    if sp["status"] != "COMMITTED":
        raise_err(ERR_INVALID_SPONSORSHIP_TRANSITION, "only a COMMITTED sponsorship can be settled")
    ev = db.events.get(sp["event_id"])
    if ev is None or ev["status"] not in ("COMPLETED", "CLOSED"):
        raise_err(ERR_EVENT_STATE_FORBIDS_WRITE, "event must be COMPLETED or CLOSED to settle")
    sp["settled_amount_cents"] = calc.settled_amount(sp)
    sp["status"] = "SETTLED"
    bump(sp)
    refresh_event(ev)
    return success_object(ser_sponsorship(sp))


@bp.post("/sponsorships/<sponsorshipId>/withdraw")
def withdraw_sponsorship(sponsorshipId):
    authenticate(FC)
    sp = load_sponsorship(sponsorshipId)
    if sp["status"] not in ("PLEDGED", "COMMITTED"):
        raise_err(ERR_INVALID_SPONSORSHIP_TRANSITION, "sponsorship cannot be withdrawn from its current status")
    sp["status"] = "WITHDRAWN"
    bump(sp)
    ev = db.events.get(sp["event_id"])
    if ev is not None:
        refresh_event(ev)
    return success_object(ser_sponsorship(sp))
