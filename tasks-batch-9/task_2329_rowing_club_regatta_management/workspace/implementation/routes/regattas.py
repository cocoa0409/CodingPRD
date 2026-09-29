"""The regatta calendar and its lifecycle."""
from flask import Blueprint

import auth
import calc
import cascade
import clock
import db
import derive
import helpers
import response
import validate

bp = Blueprint("regattas", __name__)

OPEN_PROTEST_STATUSES = ("FILED", "UNDER_JURY_REVIEW", "REMANDED")


@bp.post("/regattas")
@auth.require("ClubAdmin")
def create_regatta():
    data = validate.body()
    name = validate.string(data, "name")
    host_club = validate.string(data, "host_club")
    venue_kind = validate.enum(data, "venue_kind", calc.VENUE_KINDS)
    race_date, race_raw = validate.datetime_field(data, "race_date_at")
    deadline, deadline_raw = validate.datetime_field(data, "entry_deadline_at")
    scratch, scratch_raw = validate.datetime_field(data, "scratch_deadline_at")
    weigh_open, weigh_open_raw = validate.datetime_field(data, "weigh_in_opens_at")
    weigh_close, weigh_close_raw = validate.datetime_field(data, "weigh_in_closes_at")
    late_allowed = validate.boolean(data, "late_entry_allowed", required=False, default=False)

    regatta = db.base_record()
    regatta["name"] = name
    regatta["host_club"] = host_club
    regatta["venue_kind"] = venue_kind
    db.set_dt(regatta, "race_date_at", race_date, race_raw)
    db.set_dt(regatta, "entry_deadline_at", deadline, deadline_raw)
    db.set_dt(regatta, "scratch_deadline_at", scratch, scratch_raw)
    db.set_dt(regatta, "weigh_in_opens_at", weigh_open, weigh_open_raw)
    db.set_dt(regatta, "weigh_in_closes_at", weigh_close, weigh_close_raw)
    regatta["late_entry_allowed"] = late_allowed
    regatta["net_fee_cents"] = 0
    regatta["deposit_held_cents"] = 0
    regatta["status"] = "OPEN_FOR_ENTRY"
    db.regattas[regatta["id"]] = regatta
    return response.created(derive.regatta_out(regatta))


@bp.get("/regattas/<ident>")
@auth.require("ClubAdmin", "Coach", "RaceOfficial", "JuryChair", "EquipmentManager", "Member")
def get_regatta(ident):
    regatta = helpers.load("regatta", ident)
    return response.ok(derive.regatta_out(regatta))


@bp.get("/regattas")
@auth.require("ClubAdmin", "Coach", "RaceOfficial", "Member")
def list_regattas():
    wanted = response.filters("status", "venue_kind")
    rows = db.ordered(db.regattas, lambda r: response.matches(r, wanted))
    return response.paginate(rows, derive.regatta_out)


def _cancel_regatta(regatta, void_lanes):
    for entry in db.ordered(db.entries, lambda e: e["regatta_id"] == regatta["id"]
                            and e["status"] in ("DRAFT",) + cascade.LIVE_ENTRY_STATUSES):
        cascade.scratch_entry(entry, entry["total_fee_cents"],
                              release_rack_units=False, void_lanes=False)
    if not void_lanes:
        return
    heat_ids = [h["id"] for h in db.heats.values() if h["regatta_id"] == regatta["id"]]
    for lane in db.ordered(db.lanes, lambda l: l["heat_id"] in heat_ids
                           and l["lane_status"] in ("PENDING", "PROVISIONAL")):
        cascade.void_lane(lane)


@bp.post("/regattas/<ident>/status-transitions")
@auth.require("ClubAdmin")
def regatta_status_transition(ident):
    regatta = helpers.load("regatta", ident)
    data = validate.body()
    to_status = validate.enum(data, "to_status", calc.REGATTA_STATUSES)

    helpers.not_terminal("regatta", regatta)

    now = clock.now()
    current = regatta["status"]
    if to_status == "ENTRIES_CLOSED" and current == "OPEN_FOR_ENTRY":
        if now < db.dt(regatta, "entry_deadline_at"):
            helpers.invalid_transition("The entry deadline has not been reached yet.")
        regatta["status"] = "ENTRIES_CLOSED"
        db.touch(regatta)
    elif to_status == "OPEN_FOR_ENTRY" and current == "ENTRIES_CLOSED":
        if not regatta["late_entry_allowed"]:
            helpers.invalid_transition("This regatta does not permit late entries.")
        if now >= db.dt(regatta, "race_date_at"):
            helpers.invalid_transition("Racing has already started.")
        regatta["status"] = "OPEN_FOR_ENTRY"
        db.touch(regatta)
    elif to_status == "RACING" and current == "ENTRIES_CLOSED":
        if now < db.dt(regatta, "race_date_at"):
            helpers.invalid_transition("The race date has not been reached yet.")
        if regatta["venue_kind"] == "AWAY":
            for load in db.trailers.values():
                if load["regatta_id"] != regatta["id"]:
                    continue
                if load["status"] not in ("DEPARTED", "ARRIVED"):
                    helpers.invalid_transition(
                        "Trailer load %s has not departed yet." % load["id"])
        regatta["status"] = "RACING"
        db.touch(regatta)
    elif to_status == "COMPLETE" and current == "RACING":
        heat_ids = []
        for heat in db.heats.values():
            if heat["regatta_id"] != regatta["id"]:
                continue
            if heat["status"] != "RESULTS_OFFICIAL":
                helpers.invalid_transition(
                    "Heat %s is not yet RESULTS_OFFICIAL." % heat["id"])
            heat_ids.append(heat["id"])
        for protest in db.protests.values():
            if protest["heat_id"] in heat_ids and protest["status"] in OPEN_PROTEST_STATUSES:
                helpers.invalid_transition(
                    "Protest %s is still unresolved." % protest["id"])
        regatta["status"] = "COMPLETE"
        db.touch(regatta)
    elif to_status == "CANCELLED" and current in ("OPEN_FOR_ENTRY", "ENTRIES_CLOSED", "RACING"):
        if current == "RACING":
            for heat in db.heats.values():
                if heat["regatta_id"] == regatta["id"] and heat["status"] == "RESULTS_OFFICIAL":
                    helpers.invalid_transition(
                        "Heat %s already has official results." % heat["id"])
        regatta["status"] = "CANCELLED"
        db.touch(regatta)
        _cancel_regatta(regatta, void_lanes=(current == "RACING"))
    else:
        helpers.invalid_transition(
            "%s -> %s is not a declared regatta transition." % (current, to_status))
    return response.ok(derive.regatta_out(regatta))
