"""Race day: heats, lane seeding, results, officialization and progression."""
from datetime import timedelta

from flask import Blueprint

import auth
import calc
import clock
import db
import derive
import helpers
import response
import validate
from errors import fail

bp = Blueprint("race", __name__)

OPEN_PROTEST_STATUSES = ("FILED", "UNDER_JURY_REVIEW", "REMANDED")
PROTEST_WINDOW = timedelta(minutes=calc.PROTEST_WINDOW_MINUTES)


def _lane_sort_key(lane):
    return (lane["elapsed_seconds"], lane["_created_at"], lane["_seq"])


def _seed_lanes(heat, entry_ids):
    """Create one PENDING lane per crew, awarding the club preference order."""
    numbers = derive.preference_lanes(heat["lane_count"])
    existing = {}
    for lane in derive.heat_lanes(heat["id"]):
        if lane["lane_status"] == "PENDING":
            existing.setdefault(lane["regatta_entry_id"], lane)
    created = 0
    for index, entry_id in enumerate(entry_ids):
        if index >= len(numbers):
            break
        number = numbers[index]
        held = existing.pop(entry_id, None)
        if held is None:
            lane = db.base_record()
            lane["heat_id"] = heat["id"]
            lane["regatta_entry_id"] = entry_id
            lane["lane_number"] = number
            lane["elapsed_seconds"] = None
            lane["place"] = None
            lane["advanced"] = False
            lane["lane_status"] = "PENDING"
            db.lanes[lane["id"]] = lane
            created += 1
        elif held["lane_number"] != number:
            held["lane_number"] = number
            db.touch(held)
    return created


def _run_advancement(heat):
    """calculations.heat_advancement_selection, in the three pinned steps."""
    target_id = heat.get("advances_to_heat_id")
    target = db.heats.get(target_id) if target_id else None
    if target is None:
        return

    sources = [h for h in db.heats.values()
               if h.get("advances_to_heat_id") == target["id"]
               and h["status"] == "RESULTS_OFFICIAL"]
    sources.sort(key=lambda h: (db.dt(h, "scheduled_start_at"), h["_created_at"], h["_seq"]))

    # Step one: the automatic qualifiers, source heat by source heat.
    automatic = []
    per_source = {}
    for source in sources:
        official = [l for l in derive.heat_lanes(source["id"])
                    if l["lane_status"] == "OFFICIAL" and l["elapsed_seconds"] is not None]
        official.sort(key=_lane_sort_key)
        per_source[source["id"]] = official
        automatic.extend(official[:source["advance_count"]])

    # Step two: the fastest-loser fill.
    auto_ids = {l["id"] for l in automatic}
    losers = []
    for source in sources:
        losers.extend(l for l in per_source[source["id"]] if l["id"] not in auto_ids)
    losers.sort(key=_lane_sort_key)
    remaining = target["lane_count"] - len(automatic)
    fill = losers[:remaining] if remaining > 0 else []

    selected = automatic + fill
    for lane in selected:
        if not lane["advanced"]:
            lane["advanced"] = True
            db.touch(lane)

    # Step three: seed the target heat with the advancing crews.
    selected.sort(key=_lane_sort_key)
    created = _seed_lanes(target, [l["regatta_entry_id"] for l in selected])
    if selected and target["status"] == "SCHEDULED":
        target["status"] = "LANES_ASSIGNED"
        db.touch(target)
    elif created:
        db.touch(target)


# --------------------------------------------------------------------------- #
# Heats                                                                       #
# --------------------------------------------------------------------------- #
@bp.post("/heats")
@auth.require("RaceOfficial")
def create_heat():
    data = validate.body()
    helpers.check_fk("regatta", data, "regatta_id")
    helpers.check_fk("heat", data, "advances_to_heat_id")
    regatta_id = validate.string(data, "regatta_id")
    event_code = validate.string(data, "event_code")
    round_kind = validate.enum(data, "round_kind", calc.ROUND_KINDS)
    start, start_raw = validate.datetime_field(data, "scheduled_start_at")
    lane_count = validate.integer(data, "lane_count", minimum=1, maximum=8)
    advance_count = validate.integer(data, "advance_count", required=False, default=0,
                                     minimum=0, maximum=8)
    advances_to = validate.string(data, "advances_to_heat_id", required=False,
                                  default=None, nullable=True)

    regatta = db.regattas[regatta_id]
    helpers.not_terminal("regatta", regatta)

    if advances_to is not None:
        downstream = db.heats[advances_to]
        if downstream["regatta_id"] != regatta_id:
            fail("ERR_HEAT_NOT_IN_REGATTA",
                 "Heat %s belongs to another regatta." % advances_to)
        if calc.ROUND_ORDER[downstream["round_kind"]] <= calc.ROUND_ORDER[round_kind]:
            fail("ERR_HEAT_NOT_IN_REGATTA",
                 "A %s round cannot feed a %s round."
                 % (round_kind, downstream["round_kind"]))

    heat = db.base_record()
    heat["regatta_id"] = regatta_id
    heat["advances_to_heat_id"] = advances_to
    heat["event_code"] = event_code
    heat["round_kind"] = round_kind
    db.set_dt(heat, "scheduled_start_at", start, start_raw)
    heat["lane_count"] = lane_count
    heat["advance_count"] = advance_count
    heat["occupied_lane_count"] = 0
    heat["free_lane_count"] = lane_count
    db.set_dt(heat, "protest_window_closes_at", None)
    heat["status"] = "SCHEDULED"
    db.heats[heat["id"]] = heat
    return response.created(derive.heat_out(heat))


@bp.get("/heats/<ident>")
@auth.require("ClubAdmin", "Coach", "RaceOfficial", "JuryChair", "Member")
def get_heat(ident):
    heat = helpers.load("heat", ident)
    return response.ok(derive.heat_out(heat))


@bp.get("/heats")
@auth.require("ClubAdmin", "Coach", "RaceOfficial", "JuryChair", "Member")
def list_heats():
    wanted = response.filters("regatta_id", "advances_to_heat_id", "event_code",
                              "round_kind", "status")
    rows = db.ordered(db.heats, lambda h: response.matches(h, wanted))
    return response.paginate(rows, derive.heat_out)


@bp.post("/heats/<ident>/assign-lanes")
@auth.require("RaceOfficial")
def assign_lanes(ident):
    heat = helpers.load("heat", ident)
    data = validate.body()
    validate.string(data, "note", required=False, nullable=True)

    helpers.not_terminal("heat", heat)

    regatta = db.regattas[heat["regatta_id"]]
    if regatta["status"] != "RACING":
        fail("ERR_REGATTA_NOT_RACING",
             "Regatta %s is %s, not RACING." % (regatta["id"], regatta["status"]))

    candidates = db.ordered(db.entries, lambda e: e["regatta_id"] == heat["regatta_id"]
                            and e["event_code"] == heat["event_code"]
                            and e["status"] == "CONFIRMED")
    if not candidates:
        fail("ERR_NO_ELIGIBLE_ENTRIES",
             "No CONFIRMED entry matches event %s." % heat["event_code"])
    candidates.sort(key=lambda e: (e["seed_time_seconds"], e["_created_at"], e["_seq"]))

    numbers = derive.preference_lanes(heat["lane_count"])
    if len(candidates) > len(numbers):
        fail("ERR_LANE_CAPACITY_EXCEEDED",
             "%d crews cannot be seeded into %d lanes." % (len(candidates), len(numbers)))

    if heat["status"] != "SCHEDULED":
        helpers.invalid_transition(
            "Only a SCHEDULED heat may be seeded; this one is %s." % heat["status"])

    _seed_lanes(heat, [e["id"] for e in candidates])
    heat["status"] = "LANES_ASSIGNED"
    db.touch(heat)
    return response.ok(derive.heat_out(heat))


@bp.post("/heats/<ident>/results")
@auth.require("RaceOfficial")
def post_results(ident):
    heat = helpers.load("heat", ident)
    data = validate.body()

    # Rung 4: any lane the payload names must exist.
    raw_results = data.get("lane_results")
    if isinstance(raw_results, list):
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            for key in ("race_lane_id", "lane_id", "id"):
                value = item.get(key)
                if isinstance(value, str) and value not in db.lanes:
                    fail("ERR_LANE_NOT_FOUND", "No lane with id %s." % value)

    results = validate.object_array(data, "lane_results")
    by_lane_id = {}
    by_number = {}
    for item in results:
        elapsed = validate.number(item, "elapsed_seconds", one_dp=True)
        lane_id = None
        for key in ("race_lane_id", "lane_id", "id"):
            if item.get(key) is not None:
                lane_id = validate.string(item, key)
                break
        if lane_id is not None:
            by_lane_id[lane_id] = elapsed
        elif item.get("lane_number") is not None:
            by_number[validate.integer(item, "lane_number", minimum=1, maximum=8)] = elapsed
        else:
            fail("ERR_INVALID_REQUEST",
                 "Each lane result must name race_lane_id or lane_number.")

    helpers.not_terminal("heat", heat)
    if heat["status"] != "LANES_ASSIGNED":
        fail("ERR_HEAT_NOT_ASSIGNED",
             "Heat %s is %s, not LANES_ASSIGNED." % (heat["id"], heat["status"]))

    pending = [l for l in derive.heat_lanes(heat["id"]) if l["lane_status"] == "PENDING"]
    for lane in pending:
        if lane["id"] not in by_lane_id and lane["lane_number"] not in by_number:
            fail("ERR_INVALID_REQUEST",
                 "lane_results is missing an elapsed_seconds value for lane %s."
                 % lane["id"])

    for lane in pending:
        elapsed = by_lane_id.get(lane["id"])
        if elapsed is None:
            elapsed = by_number.get(lane["lane_number"])
        lane["elapsed_seconds"] = elapsed
        lane["lane_status"] = "PROVISIONAL"
        db.touch(lane)
    for lane in derive.recompute_places(heat["id"]):
        db.touch(lane)

    now = clock.now()
    db.set_dt(heat, "protest_window_closes_at", now + PROTEST_WINDOW)
    heat["status"] = "RESULTS_PROVISIONAL"
    db.touch(heat)
    return response.ok(derive.heat_out(heat))


@bp.post("/heats/<ident>/officialize")
@auth.require("RaceOfficial")
def officialize_heat(ident):
    heat = helpers.load("heat", ident)
    data = validate.body()
    validate.string(data, "note", required=False, nullable=True)

    helpers.not_terminal("heat", heat)
    if heat["status"] != "RESULTS_PROVISIONAL":
        fail("ERR_HEAT_NOT_PROVISIONAL",
             "Heat %s is %s, not RESULTS_PROVISIONAL." % (heat["id"], heat["status"]))

    closes = db.dt(heat, "protest_window_closes_at")
    if closes is None or clock.now() < closes:
        fail("ERR_PROTEST_WINDOW_OPEN",
             "The protest window on heat %s has not closed yet." % heat["id"])

    for protest in db.protests.values():
        if protest["heat_id"] == heat["id"] and protest["status"] in OPEN_PROTEST_STATUSES:
            helpers.invalid_transition(
                "Protest %s is still unresolved." % protest["id"])

    lanes = derive.heat_lanes(heat["id"])
    for lane in lanes:
        if lane["lane_status"] == "PROVISIONAL":
            lane["lane_status"] = "OFFICIAL"
            db.touch(lane)

    heat["status"] = "RESULTS_OFFICIAL"
    db.touch(heat)

    _run_advancement(heat)

    for lane in lanes:
        if lane["lane_status"] not in ("OFFICIAL", "DISQUALIFIED"):
            continue
        entry = db.entries.get(lane["regatta_entry_id"])
        if entry is not None and entry["status"] == "CONFIRMED":
            entry["status"] = "RACED"
            db.touch(entry)
    return response.ok(derive.heat_out(heat))


# --------------------------------------------------------------------------- #
# Race lanes                                                                  #
# --------------------------------------------------------------------------- #
@bp.get("/race-lanes/<ident>")
@auth.require("ClubAdmin", "Coach", "RaceOfficial", "JuryChair", "Member")
def get_lane(ident):
    lane = helpers.load("lane", ident)
    return response.ok(derive.lane_out(lane))


@bp.get("/race-lanes")
@auth.require("ClubAdmin", "Coach", "RaceOfficial", "JuryChair", "Member")
def list_lanes():
    wanted = response.filters("heat_id", "regatta_entry_id", "lane_status", "advanced")
    rows = db.ordered(db.lanes, lambda l: response.matches(l, wanted))
    return response.paginate(rows, derive.lane_out)
