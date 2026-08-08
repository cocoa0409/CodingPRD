"""Hearing routes and court-calendar capacity checks."""

from flask import g, request

import envelope
import services
import store
from common import (authorize, check_case_ownership, get_body, lookup, owns_case,
                    pagination_params, paginate, require_dt, require_enum,
                    require_str)
from errors import ApiError

HEARING_READ_ROLES = {"Clerk", "Landlord", "Tenant", "Mediator", "Judge"}
HEARING_TYPES = {"INITIAL", "TRIAL", "ENFORCEMENT"}
HEARING_STATUSES = {"SCHEDULED", "HELD", "CONTINUED", "CANCELLED"}


def _check_calendar(court, new_start, new_end, exclude_id=None):
    for h2 in store.db["hearings"].values():
        if h2["court_id"] != court["id"] or h2["status"] != "SCHEDULED":
            continue
        if exclude_id is not None and h2["id"] == exclude_id:
            continue
        if new_start < h2["scheduled_end"] and h2["scheduled_start"] < new_end:
            raise ApiError("ERR_HEARING_CONFLICT", "Interval overlaps a scheduled hearing")
    day = new_start.date()
    day_count = 0
    for h2 in store.db["hearings"].values():
        if h2["court_id"] != court["id"] or h2["status"] != "SCHEDULED":
            continue
        if h2["scheduled_start"].date() == day:
            day_count += 1
    if day_count >= court["hearing_daily_capacity"]:
        raise ApiError("ERR_CALENDAR_FULL", "Court is at daily capacity for that date")


def register(app):
    @app.route("/hearings", methods=["POST"])
    def create_hearing():
        authorize({"Clerk"})
        body = get_body()
        case_id = require_str(body, "case_id")
        court_id = require_str(body, "court_id")
        hearing_type = require_enum(body, "hearing_type", HEARING_TYPES)
        start = require_dt(body, "scheduled_start")
        end = require_dt(body, "scheduled_end")
        if not (start < end):
            raise ApiError("ERR_VALIDATION", "scheduled_start must be before scheduled_end")
        lookup("cases", case_id)
        court = lookup("courts", court_id)
        _check_calendar(court, start, end)
        h = services.new_entity("hearings", versioned=True)
        h["case_id"] = case_id
        h["court_id"] = court_id
        h["hearing_type"] = hearing_type
        h["scheduled_start"] = start
        h["scheduled_end"] = end
        h["continuance_count"] = 0
        h["continued_from_id"] = None
        h["status"] = "SCHEDULED"
        court["hearings_scheduled_count"] += 1
        services.touch(court)
        return envelope.created(h)

    @app.route("/hearings/<hearing_id>", methods=["GET"])
    def get_hearing(hearing_id):
        authorize(HEARING_READ_ROLES)
        h = lookup("hearings", hearing_id)
        check_case_ownership(store.db["cases"].get(h["case_id"], {}))
        return envelope.success(h)

    @app.route("/hearings", methods=["GET"])
    def list_hearings():
        authorize(HEARING_READ_ROLES)
        limit, offset = pagination_params()
        args = request.args
        items = []
        for h in store.db["hearings"].values():
            case = store.db["cases"].get(h["case_id"])
            if case is not None and not owns_case(case):
                continue
            if args.get("case_id") and h["case_id"] != args.get("case_id"):
                continue
            if args.get("court_id") and h["court_id"] != args.get("court_id"):
                continue
            if args.get("status") and h["status"] != args.get("status"):
                continue
            if args.get("continued_from_id") and h.get("continued_from_id") != args.get("continued_from_id"):
                continue
            items.append(h)
        page, total = paginate(items, limit, offset)
        return envelope.listing(page, limit, offset, total)

    @app.route("/hearings/<hearing_id>/transition", methods=["POST"])
    def transition_hearing(hearing_id):
        authorize({"Clerk", "Judge"})
        h = lookup("hearings", hearing_id)
        body = get_body()
        to = require_str(body, "to_status")
        if to not in HEARING_STATUSES:
            raise ApiError("ERR_VALIDATION", "Unknown to_status: %s" % to)
        court = store.db["courts"].get(h["court_id"])
        case = store.db["cases"].get(h["case_id"])

        if to == "HELD":
            if g.role != "Judge":
                raise ApiError("ERR_UNAUTHORIZED", "Only a judge may hold a hearing")
            if h["status"] != "SCHEDULED":
                raise ApiError("ERR_INVALID_STATE", "Hearing not SCHEDULED")
            if case is None or case["status"] != "IN_LITIGATION":
                raise ApiError("ERR_CASE_NOT_IN_LITIGATION", "Case is not IN_LITIGATION")
            if store.now() < h["scheduled_start"]:
                raise ApiError("ERR_INVALID_STATE", "Hearing cannot be held before its start")
            h["status"] = "HELD"
            services.touch(h)
            if court is not None:
                court["hearings_scheduled_count"] -= 1
                services.touch(court)
        elif to == "CANCELLED":
            if g.role != "Clerk":
                raise ApiError("ERR_UNAUTHORIZED", "Only a clerk may cancel a hearing")
            if h["status"] != "SCHEDULED":
                raise ApiError("ERR_INVALID_STATE", "Hearing not SCHEDULED")
            h["status"] = "CANCELLED"
            services.touch(h)
            if court is not None:
                court["hearings_scheduled_count"] -= 1
                services.touch(court)
        elif to == "CONTINUED":
            if h["status"] != "SCHEDULED":
                raise ApiError("ERR_INVALID_STATE", "Hearing not SCHEDULED")
            new_start = require_dt(body, "new_start")
            new_end = require_dt(body, "new_end")
            if not (new_start < new_end):
                raise ApiError("ERR_INVALID_INTERVAL", "new_start must be before new_end")
            _check_calendar(court, new_start, new_end, exclude_id=h["id"])
            # predecessor leaves SCHEDULED
            h["status"] = "CONTINUED"
            services.touch(h)
            if court is not None:
                court["hearings_scheduled_count"] -= 1
            # successor
            successor = services.new_entity("hearings", versioned=True)
            successor["case_id"] = h["case_id"]
            successor["court_id"] = h["court_id"]
            successor["hearing_type"] = h["hearing_type"]
            successor["scheduled_start"] = new_start
            successor["scheduled_end"] = new_end
            successor["continuance_count"] = h["continuance_count"] + 1
            successor["continued_from_id"] = h["id"]
            successor["status"] = "SCHEDULED"
            if court is not None:
                court["hearings_scheduled_count"] += 1
                services.touch(court)
            # transition response is the path resource (predecessor, now CONTINUED);
            # the successor is discoverable via GET /hearings?continued_from_id=<id>.
            return envelope.success(h)
        else:
            raise ApiError("ERR_INVALID_STATE", "Illegal hearing transition to %s" % to)
        return envelope.success(h)
