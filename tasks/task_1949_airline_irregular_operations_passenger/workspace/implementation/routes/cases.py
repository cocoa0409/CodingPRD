"""Reaccommodation case + option endpoints: reads, generate-options, commit, escalate."""

from flask import Blueprint, request

import errors
from db import db
from middleware import (
    authenticate,
    booking_of_case,
    booking_of_option,
    check_booking_ownership,
    require_role,
)
from response import success_list, success_object
from serializers import serialize_case, serialize_option
from services.core import touch
from services.selector import commit_option, generate_options, _cabin_inventory
from validators import get_json_body, get_json_body_optional, pagination_params, req_bool, req_string

bp = Blueprint("cases", __name__)

CASE_READ_ROLES = ["ReaccommodationAgent", "OpsController", "DutyManager", "Passenger"]
CASE_STATUSES = {"QUEUED", "OFFERED", "COMMITTED", "EXPIRED", "ESCALATED", "VOIDED"}
OPTION_STATUSES = {"PROPOSED", "ACCEPTED", "REJECTED", "EXPIRED"}


def _get_case_or_404(cid):
    c = db.reaccommodation_cases.get(cid)
    if c is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "ReaccommodationCase not found")
    return c


@bp.get("/irops/reaccommodation-cases/<cid>")
def get_case(cid):
    caller = authenticate()
    require_role(caller, CASE_READ_ROLES)
    c = _get_case_or_404(cid)
    if caller.is_passenger:
        b = booking_of_case(c)
        if b is not None:
            check_booking_ownership(caller, b)
    return success_object(serialize_case(c), 200)


@bp.get("/irops/reaccommodation-cases")
def list_cases():
    caller = authenticate()
    require_role(caller, CASE_READ_ROLES)
    booking_id = request.args.get("booking_id")
    event_id = request.args.get("disruption_event_id")
    case_status = request.args.get("case_status")
    if case_status is not None and case_status not in CASE_STATUSES:
        errors.raise_error(errors.ERR_INVALID_ENUM,
                           "case_status value %r outside declared enum domain" % case_status)
    committed_option_id = request.args.get("committed_option_id")
    limit, offset = pagination_params()
    items = list(db.reaccommodation_cases.values())
    if caller.is_passenger:
        items = [c for c in items
                 if db.bookings.get(c["booking_id"]) is not None
                 and db.bookings[c["booking_id"]]["passenger_id"] == caller.user_id]
    if booking_id is not None:
        items = [c for c in items if c["booking_id"] == booking_id]
    if event_id is not None:
        items = [c for c in items if c["disruption_event_id"] == event_id]
    if case_status is not None:
        items = [c for c in items if c["case_status"] == case_status]
    if committed_option_id is not None:
        items = [c for c in items if c["committed_option_id"] == committed_option_id]

    def sort_key(c):
        b = db.bookings.get(c["booking_id"])
        b_created = b["created_at"] if b is not None else c["created_at"]
        return (-c["priority_score"], b_created)

    items.sort(key=sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_case(c) for c in page], limit, offset, total)


@bp.post("/irops/reaccommodation-cases/<cid>/generate-options")
def generate(cid):
    caller = authenticate()
    require_role(caller, ["ReaccommodationAgent", "Passenger"])
    body = get_json_body_optional()
    include_interline = body.get("include_interline", False)
    if not isinstance(include_interline, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "include_interline must be a boolean")
    c = _get_case_or_404(cid)
    if caller.is_passenger:
        b = booking_of_case(c)
        if b is not None:
            check_booking_ownership(caller, b)
    if c["case_status"] not in ("QUEUED", "ESCALATED"):
        errors.raise_error(errors.ERR_CASE_NOT_COMMITTABLE,
                           "generate-options requires QUEUED or ESCALATED")
    generate_options(c, include_interline)
    return success_object(serialize_case(c), 200)


@bp.get("/irops/reaccommodation-cases/<cid>/options")
def list_case_options(cid):
    caller = authenticate()
    require_role(caller, CASE_READ_ROLES)
    c = _get_case_or_404(cid)
    if caller.is_passenger:
        b = booking_of_case(c)
        if b is not None:
            check_booking_ownership(caller, b)
    limit, offset = pagination_params()
    items = [o for o in db.reaccommodation_options.values() if o["case_id"] == cid]
    items.sort(key=lambda o: (o["rank_score"], o["created_at"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_option(o) for o in page], limit, offset, total)


@bp.get("/irops/reaccommodation-options/<oid>")
def get_option(oid):
    caller = authenticate()
    require_role(caller, CASE_READ_ROLES)
    o = db.reaccommodation_options.get(oid)
    if o is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "ReaccommodationOption not found")
    if caller.is_passenger:
        b = booking_of_option(o)
        if b is not None:
            check_booking_ownership(caller, b)
    return success_object(serialize_option(o), 200)


@bp.get("/irops/reaccommodation-options")
def list_options():
    caller = authenticate()
    require_role(caller, CASE_READ_ROLES)
    case_id = request.args.get("case_id")
    agreement_id = request.args.get("interline_agreement_id")
    option_status = request.args.get("option_status")
    if option_status is not None and option_status not in OPTION_STATUSES:
        errors.raise_error(errors.ERR_INVALID_ENUM,
                           "option_status value %r outside declared enum domain" % option_status)
    limit, offset = pagination_params()
    items = sorted(db.reaccommodation_options.values(), key=lambda o: o["created_at"])
    if caller.is_passenger:
        def owned(o):
            b = booking_of_option(o)
            return b is not None and b["passenger_id"] == caller.user_id
        items = [o for o in items if owned(o)]
    if case_id is not None:
        items = [o for o in items if o["case_id"] == case_id]
    if agreement_id is not None:
        items = [o for o in items if o["interline_agreement_id"] == agreement_id]
    if option_status is not None:
        items = [o for o in items if o["option_status"] == option_status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_option(o) for o in page], limit, offset, total)


@bp.post("/irops/reaccommodation-cases/<cid>/commit")
def commit(cid):
    caller = authenticate()
    require_role(caller, ["ReaccommodationAgent", "Passenger"])
    body = get_json_body()
    option_id = body.get("option_id")
    if option_id is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "option_id is required")
    if not isinstance(option_id, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "option_id must be a string")
    expected_version = body.get("expected_case_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "expected_case_version is required and must be an integer")
    c = _get_case_or_404(cid)
    if caller.is_passenger:
        b = booking_of_case(c)
        if b is not None:
            check_booking_ownership(caller, b)
    option = db.reaccommodation_options.get(option_id)
    if option is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "ReaccommodationOption not found")
    # OCC first
    if expected_version != c["version"]:
        errors.raise_error(errors.ERR_STALE_VERSION,
                           "expected_case_version does not match current case version")
    # case must be OFFERED
    if c["case_status"] != "OFFERED":
        errors.raise_error(errors.ERR_CASE_NOT_COMMITTABLE,
                           "commit requires case_status OFFERED")
    # option must be PROPOSED and belong to this case, legs still schedulable
    if option["case_id"] != c["id"] or option["option_status"] != "PROPOSED":
        errors.raise_error(errors.ERR_OPTION_NOT_PROPOSED,
                           "Option is not PROPOSED for this case")
    legs_ok = True
    for leg in option["legs"]:
        f = db.flights.get(leg["flight_id"])
        if f is None or f["flight_status"] not in ("SCHEDULED", "DELAYED"):
            legs_ok = False
            break
    if not legs_ok:
        option["option_status"] = "EXPIRED"
        touch(option)
        errors.raise_error(errors.ERR_OPTION_NOT_PROPOSED,
                           "A leg flight has left SCHEDULED/DELAYED; option expired")
    # seats
    booking = db.bookings.get(c["booking_id"])
    party = booking["party_size"] if booking else 1
    for leg in option["legs"]:
        ci = _cabin_inventory(leg["flight_id"], leg["cabin"])
        if option["is_interline"]:
            agreement = db.interline_agreements.get(option["interline_agreement_id"])
            committed = ci["interline_seats_committed"] if ci else 0
            quota = agreement["seats_quota_per_flight"] if agreement else 0
            if committed + party > quota:
                errors.raise_error(errors.ERR_SEATS_INSUFFICIENT,
                                   "Interline quota exhausted")
        else:
            avail = (ci["capacity"] - ci["seats_sold"] - ci["interline_seats_committed"]) if ci else 0
            if avail < party:
                errors.raise_error(errors.ERR_SEATS_INSUFFICIENT,
                                   "seats_available < party_size on a required cabin")
    # interline agreement must be ACTIVE
    if option["is_interline"]:
        agreement = db.interline_agreements.get(option["interline_agreement_id"])
        if agreement is None or agreement["agreement_status"] != "ACTIVE":
            errors.raise_error(errors.ERR_INTERLINE_AGREEMENT_INACTIVE,
                               "Interline agreement is not ACTIVE")
    commit_option(c, option)
    return success_object(serialize_case(c), 200)


@bp.post("/irops/reaccommodation-cases/<cid>/escalate")
def escalate(cid):
    caller = authenticate()
    require_role(caller, ["ReaccommodationAgent"])
    get_json_body_optional()
    c = _get_case_or_404(cid)
    if c["case_status"] not in ("QUEUED", "OFFERED"):
        errors.raise_error(errors.ERR_CASE_NOT_COMMITTABLE,
                           "escalate requires QUEUED or OFFERED")
    c["case_status"] = "ESCALATED"
    touch(c)
    return success_object(serialize_case(c), 200)
