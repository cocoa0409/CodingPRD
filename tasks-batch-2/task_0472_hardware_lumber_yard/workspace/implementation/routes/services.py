"""ServiceStation + ServiceTicket endpoints (PRD 3.8)."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import db
import errors
import helpers
import serialize
import validate
from auth import authenticate, require_roles
from response import ok, created, ok_list

bp = Blueprint("services", __name__)

TICKET_TERMINAL = {"COMPLETED", "CANCELLED"}
SERVICE_TYPES = {"KEY_CUT", "PAINT_MIX", "PROPANE_EXCHANGE"}


# ---------------------------------------------------------------- Stations ---

@bp.route("/service-stations", methods=["POST"])
def create_station():
    caller = authenticate()
    require_roles(caller, {"InventoryManager"})
    data = validate.body()
    name = validate.require_str(data, "name")
    buffer_minutes = validate.opt_int(data, "buffer_minutes", default=0, minimum=0)
    with db.lock:
        rec = db.new_record({
            "name": name,
            "buffer_minutes": buffer_minutes,
            "status": "ACTIVE",
        })
        db.service_stations[rec["id"]] = rec
        return created(serialize.service_station(rec))


@bp.route("/service-stations/<rid>", methods=["GET"])
def get_station(rid):
    caller = authenticate()
    require_roles(caller, {"InventoryManager", "SalesAssociate"})
    with db.lock:
        rec = helpers.get_or_404(db.service_stations, rid)
        return ok(serialize.service_station(rec))


@bp.route("/service-stations/<rid>/set-offline", methods=["POST"])
def set_offline(rid):
    caller = authenticate()
    require_roles(caller, {"InventoryManager"})
    data = validate.body()
    with db.lock:
        rec = helpers.get_or_404(db.service_stations, rid)
        offline = validate.require_bool(data, "offline")
        rec["status"] = "OFFLINE" if offline else "ACTIVE"
        db.touch(rec)
        return ok(serialize.service_station(rec))


# ----------------------------------------------------------------- Tickets ---

def _non_terminal_tickets(station_id):
    return [
        t for t in db.service_tickets.values()
        if t["service_station_id"] == station_id and t["status"] not in TICKET_TERMINAL
    ]


def _intervals_overlap(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


@bp.route("/service-tickets", methods=["POST"])
def book_ticket():
    caller = authenticate()
    require_roles(caller, {"SalesAssociate"})
    data = validate.body()
    station_id = validate.require_str(data, "service_station_id")
    account_id = validate.opt_str(data, "contractor_account_id", default=None)
    service_type = validate.require_enum(data, "service_type", SERVICE_TYPES)
    cylinder_certified = validate.opt_bool(data, "cylinder_certified", default=False)
    scheduled_start = validate.parse_datetime(data, "scheduled_start", required=True)
    scheduled_end = validate.parse_datetime(data, "scheduled_end", required=True)
    if not (scheduled_end > scheduled_start):
        raise errors.invalid_request("scheduled_end must be strictly after scheduled_start")
    with db.lock:
        station = helpers.get_or_404(db.service_stations, station_id)
        if account_id is not None:
            helpers.get_or_404(db.contractor_accounts, account_id)
        # priority 16: buffer-expanded overlap on the station
        buffer = timedelta(minutes=station["buffer_minutes"])
        req_start = scheduled_start - buffer
        req_end = scheduled_end + buffer
        for t in _non_terminal_tickets(station_id):
            if _intervals_overlap(req_start, req_end, t["scheduled_start"], t["scheduled_end"]):
                raise errors.ApiError(errors.ERR_STATION_BOOKING_CONFLICT, 409,
                                      "window conflicts with an existing ticket")
        rec = db.new_record({
            "service_station_id": station_id,
            "contractor_account_id": account_id,
            "service_type": service_type,
            "cylinder_certified": cylinder_certified,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "fee_cents": 0,
            "status": "BOOKED",
        })
        db.service_tickets[rec["id"]] = rec
        return created(serialize.service_ticket(rec))


@bp.route("/service-tickets/<rid>", methods=["GET"])
def get_ticket(rid):
    caller = authenticate()
    require_roles(caller, {"SalesAssociate", "Contractor"})
    with db.lock:
        rec = helpers.get_or_404(db.service_tickets, rid)
        if caller.is_contractor and rec["contractor_account_id"] != caller.user_id:
            raise errors.unauthorized()
        return ok(serialize.service_ticket(rec))


@bp.route("/service-tickets", methods=["GET"])
def list_tickets():
    caller = authenticate()
    require_roles(caller, {"SalesAssociate", "Contractor"})
    limit, offset = validate.pagination()
    station_id = request.args.get("service_station_id")
    account_id = request.args.get("contractor_account_id")
    with db.lock:
        items = list(db.service_tickets.values())
        if caller.is_contractor:
            items = [t for t in items if t["contractor_account_id"] == caller.user_id]
        if station_id is not None:
            items = [t for t in items if t["service_station_id"] == station_id]
        if account_id is not None:
            items = [t for t in items if t["contractor_account_id"] == account_id]
        items = helpers.sorted_by_creation(items)
        page, total = helpers.paginate(items, limit, offset)
        return ok_list([serialize.service_ticket(t) for t in page], limit, offset, total)


@bp.route("/service-tickets/<rid>/start", methods=["POST"])
def start_ticket(rid):
    caller = authenticate()
    require_roles(caller, {"SalesAssociate"})
    with db.lock:
        ticket = helpers.get_or_404(db.service_tickets, rid)
        if ticket["status"] != "BOOKED":
            raise errors.invalid_state("start is only defined from BOOKED")
        station = db.service_stations.get(ticket["service_station_id"])
        # priority 9: station offline
        if station is None or station["status"] != "ACTIVE":
            raise errors.ApiError(errors.ERR_STATION_OFFLINE, 409,
                                  "station is OFFLINE")
        # priority 11: propane safety
        if ticket["service_type"] == "PROPANE_EXCHANGE" and not ticket["cylinder_certified"]:
            raise errors.ApiError(errors.ERR_CYLINDER_NOT_CERTIFIED, 409,
                                  "propane cylinder not certified")
        ticket["fee_cents"] = calc.service_fee(ticket["service_type"])
        ticket["status"] = "IN_PROGRESS"
        db.touch(ticket)
        return ok(serialize.service_ticket(ticket))


@bp.route("/service-tickets/<rid>/complete", methods=["POST"])
def complete_ticket(rid):
    caller = authenticate()
    require_roles(caller, {"SalesAssociate"})
    with db.lock:
        ticket = helpers.get_or_404(db.service_tickets, rid)
        if ticket["status"] != "IN_PROGRESS":
            raise errors.invalid_state("complete is only defined from IN_PROGRESS")
        ticket["status"] = "COMPLETED"
        db.touch(ticket)
        return ok(serialize.service_ticket(ticket))


@bp.route("/service-tickets/<rid>/cancel", methods=["POST"])
def cancel_ticket(rid):
    caller = authenticate()
    require_roles(caller, {"SalesAssociate"})
    with db.lock:
        ticket = helpers.get_or_404(db.service_tickets, rid)
        if ticket["status"] != "BOOKED":
            raise errors.invalid_state("only a BOOKED ticket can be cancelled")
        ticket["status"] = "CANCELLED"
        db.touch(ticket)
        return ok(serialize.service_ticket(ticket))
