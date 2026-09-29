"""Regatta entries, lineup declaration, submission, weigh-ins and scratches."""
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
from errors import fail

bp = Blueprint("entries", __name__)


# --------------------------------------------------------------------------- #
# Entries                                                                     #
# --------------------------------------------------------------------------- #
@bp.post("/regatta-entries")
@auth.require("Coach")
def create_entry():
    data = validate.body()
    helpers.check_fk("regatta", data, "regatta_id")
    helpers.check_fk("shell", data, "shell_id")
    regatta_id = validate.string(data, "regatta_id")
    shell_id = validate.string(data, "shell_id")
    event_code = validate.string(data, "event_code")
    boat_class = validate.enum(data, "boat_class", calc.BOAT_CLASSES)
    seed_time = validate.number(data, "seed_time_seconds", one_dp=True)

    regatta = db.regattas[regatta_id]
    shell = db.shells[shell_id]
    helpers.not_terminal("regatta", regatta)
    helpers.not_terminal("shell", shell)

    if regatta["status"] != "OPEN_FOR_ENTRY":
        fail("ERR_REGATTA_ENTRIES_CLOSED",
             "Regatta %s is %s." % (regatta["id"], regatta["status"]))
    if boat_class != shell["boat_class"]:
        fail("ERR_BOAT_CLASS_MISMATCH",
             "Hull %s races %s, not %s." % (shell["id"], shell["boat_class"], boat_class))

    entry = db.base_record()
    entry["regatta_id"] = regatta_id
    entry["shell_id"] = shell_id
    entry["trailer_load_id"] = None
    entry["event_code"] = event_code
    entry["boat_class"] = boat_class
    entry["seed_time_seconds"] = seed_time
    db.set_dt(entry, "submitted_at", None)
    entry["base_fee_cents"] = 0
    entry["transport_levy_cents"] = 0
    entry["late_fee_cents"] = 0
    entry["total_fee_cents"] = 0
    entry["refund_cents"] = None
    entry["rack_tier"] = None
    entry["rack_position"] = None
    entry["status"] = "DRAFT"
    db.entries[entry["id"]] = entry
    return response.created(derive.entry_out(entry))


@bp.get("/regatta-entries/<ident>")
@auth.require("ClubAdmin", "Coach", "RaceOfficial", "EquipmentManager", "JuryChair")
def get_entry(ident):
    entry = helpers.load("entry", ident)
    return response.ok(derive.entry_out(entry))


@bp.get("/regatta-entries")
@auth.require("ClubAdmin", "Coach", "RaceOfficial", "EquipmentManager")
def list_entries():
    wanted = response.filters("regatta_id", "shell_id", "trailer_load_id",
                              "event_code", "status")
    rows = db.ordered(db.entries, lambda e: response.matches(e, wanted))
    return response.paginate(rows, derive.entry_out)


@bp.post("/regatta-entries/<ident>/lineup")
@auth.require("Coach")
def declare_lineup(ident):
    entry = helpers.load("entry", ident)
    data = validate.body()

    # Rung 4: seated member existence, before payload shape.
    raw_seats = data.get("seats")
    if isinstance(raw_seats, list):
        for item in raw_seats:
            if isinstance(item, dict):
                value = item.get("member_id")
                if isinstance(value, str) and value not in db.members:
                    fail("ERR_MEMBER_NOT_FOUND", "No member with id %s." % value)

    expected = validate.integer(data, "expected_regatta_entry_version")
    seat_specs = validate.object_array(data, "seats")
    seats = []
    for item in seat_specs:
        seats.append({
            "member_id": validate.string(item, "member_id"),
            "seat_number": validate.integer(item, "seat_number", minimum=0, maximum=8),
            "seat_role": validate.enum(item, "seat_role", calc.SEAT_ROLES),
        })

    # Rung 6: optimistic concurrency on the entry.
    if expected != entry["version"]:
        fail("ERR_STALE_ENTRY_VERSION",
             "Entry %s is at version %d, not %d." % (entry["id"], entry["version"], expected))

    helpers.not_terminal("entry", entry)

    # Rung 21.
    for spec in seats:
        helpers.member_active(db.members[spec["member_id"]], "seated member")

    # Rung 28: swim tests.
    for spec in seats:
        member = db.members[spec["member_id"]]
        if not derive.swim_test_valid(member):
            fail("ERR_SWIM_TEST_MISSING",
                 "Member %s has no current swim test." % member["id"])

    # Rung 29: coxswain certification.
    for spec in seats:
        if spec["seat_role"] != "COXSWAIN":
            continue
        member = db.members[spec["member_id"]]
        if not derive.coxswain_cert_valid(member):
            fail("ERR_COXSWAIN_CERT_EXPIRED",
                 "Member %s has no current coxswain certification." % member["id"])

    # Rung 34: hull tier restriction.
    shell = db.shells.get(entry["shell_id"])
    if shell is not None and shell["tier_restriction"] == "COMPETITIVE_ONLY":
        for spec in seats:
            if db.members[spec["member_id"]]["tier"] != "COMPETITIVE":
                fail("ERR_TIER_NOT_PERMITTED_FOR_HULL",
                     "Hull %s seats COMPETITIVE members only." % shell["id"])

    # Rung 41: the declared seats must fill the class exactly.
    boat_class = entry["boat_class"]
    expected_count = calc.CLASS_SEAT_COUNT[boat_class]
    cox_seats = [s for s in seats if s["seat_role"] == "COXSWAIN"]
    if len(seats) != expected_count:
        fail("ERR_SEAT_COUNT_MISMATCH",
             "A %s needs exactly %d seats, %d declared." % (boat_class, expected_count, len(seats)))
    if boat_class in calc.CLASSES_WITH_COXSWAIN:
        if len(cox_seats) != 1 or cox_seats[0]["seat_number"] != 0:
            fail("ERR_SEAT_COUNT_MISMATCH",
                 "A %s needs exactly one COXSWAIN seat at seat_number 0." % boat_class)
    elif cox_seats:
        fail("ERR_SEAT_COUNT_MISMATCH",
             "A %s carries no coxswain seat." % boat_class)

    # Rung 42: no member seated twice.
    seen = set()
    for spec in seats:
        if spec["member_id"] in seen:
            fail("ERR_DUPLICATE_SEAT_MEMBER",
                 "Member %s is seated twice." % spec["member_id"])
        seen.add(spec["member_id"])

    if entry["status"] not in ("DRAFT", "LINEUP_DECLARED"):
        helpers.invalid_transition(
            "A lineup may only be declared on a DRAFT or LINEUP_DECLARED entry; "
            "this one is %s." % entry["status"])

    # Wholesale replacement of the previously declared seats.
    for old in derive.entry_seats(entry["id"]):
        db.seats.pop(old["id"], None)

    for spec in seats:
        member = db.members[spec["member_id"]]
        seat = db.base_record()
        seat["regatta_entry_id"] = entry["id"]
        seat["member_id"] = spec["member_id"]
        seat["seat_number"] = spec["seat_number"]
        seat["seat_role"] = spec["seat_role"]
        seat["weighed_kg"] = None
        seat["weighed_by_user_id"] = None
        seat["deadweight_kg"] = None
        seat["weigh_in_status"] = "NOT_REQUIRED"
        seat["eligibility_status"] = derive.seat_eligibility(member, spec["seat_role"])
        db.seats[seat["id"]] = seat

    entry["status"] = "LINEUP_DECLARED"
    db.touch(entry)
    return response.ok(derive.entry_out(entry))


@bp.post("/regatta-entries/<ident>/submit")
@auth.require("Coach")
def submit_entry(ident):
    entry = helpers.load("entry", ident)
    data = validate.body()
    validate.string(data, "note", required=False, nullable=True)

    helpers.not_terminal("entry", entry)

    regatta = db.regattas[entry["regatta_id"]]
    if regatta["status"] != "OPEN_FOR_ENTRY":
        fail("ERR_REGATTA_ENTRIES_CLOSED",
             "Regatta %s is %s." % (regatta["id"], regatta["status"]))
    if entry["status"] != "LINEUP_DECLARED":
        fail("ERR_ENTRY_NOT_DECLARED",
             "Entry %s is %s, not LINEUP_DECLARED." % (entry["id"], entry["status"]))

    conservative = derive.condition_indices(entry["shell_id"])[0]
    if conservative < calc.MIN_CONDITION_INDEX_TO_SUBMIT:
        fail("ERR_SHELL_CONDITION_TOO_LOW",
             "Hull %s sits at condition index %d." % (entry["shell_id"], conservative))

    seats = derive.entry_seats(entry["id"])
    for seat in seats:
        if seat["eligibility_status"] == "BLOCKED_DUES":
            fail("ERR_SEAT_MEMBER_DELINQUENT",
                 "Seated member %s carries an unpaid dues balance." % seat["member_id"])
    for seat in seats:
        if seat["eligibility_status"] != "ELIGIBLE":
            helpers.invalid_transition(
                "Seat %s is %s." % (seat["id"], seat["eligibility_status"]))

    now = clock.now()
    base, levy, late, total = derive.entry_fee(entry, regatta, now)
    db.set_dt(entry, "submitted_at", now)
    entry["base_fee_cents"] = base
    entry["transport_levy_cents"] = levy
    entry["late_fee_cents"] = late
    entry["total_fee_cents"] = total
    entry["status"] = "SUBMITTED"
    db.touch(entry)
    for seat in seats:
        if seat["seat_role"] == "COXSWAIN" and seat["weigh_in_status"] == "NOT_REQUIRED":
            seat["weigh_in_status"] = "PENDING"
            db.touch(seat)
    db.touch(regatta)
    return response.ok(derive.entry_out(entry))


@bp.post("/regatta-entries/<ident>/confirm")
@auth.require("RaceOfficial")
def confirm_entry(ident):
    entry = helpers.load("entry", ident)
    data = validate.body()
    validate.string(data, "note", required=False, nullable=True)

    helpers.not_terminal("entry", entry)
    if entry["status"] != "SUBMITTED":
        fail("ERR_ENTRY_NOT_SUBMITTED",
             "Entry %s is %s, not SUBMITTED." % (entry["id"], entry["status"]))

    seats = derive.entry_seats(entry["id"])
    for seat in seats:
        if seat["seat_role"] == "COXSWAIN" and seat["weigh_in_status"] != "PASSED":
            fail("ERR_WEIGH_IN_NOT_PASSED",
                 "Coxswain seat %s has not passed its weigh-in." % seat["id"])

    regatta = db.regattas[entry["regatta_id"]]
    if regatta["venue_kind"] == "AWAY":
        load = db.trailers.get(entry.get("trailer_load_id")) if entry.get("trailer_load_id") else None
        if entry.get("rack_tier") is None or load is None or \
                load["status"] not in ("SEALED", "DEPARTED", "ARRIVED"):
            fail("ERR_ENTRY_NOT_RACKED",
                 "Entry %s is not racked on a sealed trailer." % entry["id"])

    for seat in seats:
        if seat["eligibility_status"] != "ELIGIBLE":
            helpers.invalid_transition(
                "Seat %s is %s." % (seat["id"], seat["eligibility_status"]))

    entry["status"] = "CONFIRMED"
    db.touch(entry)
    return response.ok(derive.entry_out(entry))


@bp.post("/regatta-entries/<ident>/scratch")
@auth.require("Coach", "ClubAdmin")
def scratch_entry_route(ident):
    entry = helpers.load("entry", ident)
    data = validate.body()
    validate.string(data, "reason")

    helpers.not_terminal("entry", entry)

    regatta = db.regattas[entry["regatta_id"]]
    if entry["status"] in ("DRAFT", "LINEUP_DECLARED"):
        cascade.scratch_entry(entry, 0, release_rack_units=False, void_lanes=False,
                              touch_regatta=False)
    else:
        refund = derive.scratch_refund(entry, regatta)
        cascade.scratch_entry(entry, refund,
                              release_rack_units=True,
                              void_lanes=(entry["status"] == "CONFIRMED"))
    return response.ok(derive.entry_out(entry))


# --------------------------------------------------------------------------- #
# Lineup seats                                                                #
# --------------------------------------------------------------------------- #
@bp.get("/lineup-seats/<ident>")
@auth.require("ClubAdmin", "Coach", "RaceOfficial", "Member")
def get_seat(ident):
    seat = helpers.load("seat", ident)
    return response.ok(derive.seat_out(seat))


@bp.get("/lineup-seats")
@auth.require("ClubAdmin", "Coach", "RaceOfficial", "Member")
def list_seats():
    wanted = response.filters("regatta_entry_id", "member_id", "seat_role",
                              "weigh_in_status", "eligibility_status")
    rows = db.ordered(db.seats, lambda s: response.matches(s, wanted))
    return response.paginate(rows, derive.seat_out)


@bp.post("/lineup-seats/<ident>/weigh-in")
@auth.require("RaceOfficial")
def record_weigh_in(ident):
    seat = helpers.load("seat", ident)
    data = validate.body()
    weighed = validate.number(data, "weighed_kg", one_dp=True)

    entry = db.entries.get(seat["regatta_entry_id"])
    if entry is not None:
        helpers.not_terminal("entry", entry)

    if auth.actor_id() == seat["member_id"]:
        fail("ERR_SELF_WEIGH_IN_FORBIDDEN",
             "A coxswain may not record their own weigh-in.")

    regatta = db.regattas.get(entry["regatta_id"]) if entry is not None else None
    if regatta is not None:
        now = clock.now()
        opens = db.dt(regatta, "weigh_in_opens_at")
        closes = db.dt(regatta, "weigh_in_closes_at")
        if opens is not None and now < opens:
            fail("ERR_WEIGH_IN_WINDOW_CLOSED", "The weigh-in window has not opened yet.")
        if closes is not None and now >= closes:
            fail("ERR_WEIGH_IN_WINDOW_CLOSED", "The weigh-in window has closed.")

    deadweight = derive.coxswain_deadweight(weighed, seat["seat_role"])
    total = deadweight
    for other in derive.entry_seats(seat["regatta_entry_id"]):
        if other["id"] == seat["id"]:
            continue
        if other["weigh_in_status"] in ("PASSED", "FAILED") and other["deadweight_kg"] is not None:
            total += other["deadweight_kg"]

    seat["weighed_kg"] = weighed
    seat["weighed_by_user_id"] = auth.actor_id()
    seat["deadweight_kg"] = deadweight
    seat["weigh_in_status"] = "FAILED" if total > calc.MAX_ENTRY_DEADWEIGHT_KG else "PASSED"
    db.touch(seat)

    if entry is not None:
        cascade.apply_entry_demotion(entry)
    return response.ok(derive.seat_out(seat))
