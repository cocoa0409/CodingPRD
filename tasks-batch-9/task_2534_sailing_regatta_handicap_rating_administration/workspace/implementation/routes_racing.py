"""Races, the start line, the recall loop, results and race scoring."""
from datetime import timedelta

from flask import Blueprint

import calc
import services
import store
from errors import fail
from pipeline import Ctx, F, list_read, must, no_body, ok, ok_row, validate
from util import fmt_dt, parse_dt

bp = Blueprint("racing", __name__)

READ_ROLES = ["ClubAdmin", "RegattaChair", "Measurer", "RaceOfficer", "JuryChair", "Competitor"]

COURSE_CODES = ("WINDWARD_LEEWARD", "TRIANGLE", "DISTANCE_COASTAL")
PRESTART_MINUTES = 5
PRESTART_GAP_MINUTES = 3

FINISH_STATUSES = ("FINISHED", "DNF", "DNS", "RET", "OCS", "DSQ", "DNC", "RDG")
CREATABLE_FINISH_STATUSES = ("FINISHED", "DNF", "DNS", "RET", "DNC")


def _prestart(race_or_dt):
    """The closed prestart occupancy window [start - 5 min, start]."""
    if isinstance(race_or_dt, dict):
        start = parse_dt(race_or_dt["scheduled_start_utc"])
    else:
        start = race_or_dt
    return start - timedelta(minutes=PRESTART_MINUTES), start


# --------------------------------------------------------------------------
# Race
# --------------------------------------------------------------------------


@bp.post("/regatta-ops/races")
def race_create():
    ctx = Ctx(["RegattaChair", "RaceOfficer"])
    data = validate(
        ctx,
        [
            F("regatta_id", "string"),
            F("race_number", "integer", ge=1, le=20),
            F("course_code", "enum", enum=COURSE_CODES),
            F("course_distance_nm", "number", gt=0, le=300),
            F("scheduled_start_utc", "datetime"),
        ],
    )
    regatta = must("regattas", data["regatta_id"])
    # step 32
    for other in store.find("races", regatta_id=regatta["id"]):
        if int(other["race_number"]) == int(data["race_number"]):
            fail("ERR_DUPLICATE_RECORD", "race_number is already scheduled for this regatta")
    # step 33: closed windows may not overlap and consecutive windows need a 3-minute gap
    new_open, new_close = _prestart(parse_dt(data["scheduled_start_utc"]))
    gap = timedelta(minutes=PRESTART_GAP_MINUTES)
    for other in store.find("races", regatta_id=regatta["id"]):
        if other.get("start_status") == "ABANDONED":
            continue
        other_open, other_close = _prestart(other)
        if new_open <= other_close and other_open <= new_close:
            fail("ERR_START_LINE_WINDOW_CONFLICT", "the prestart window overlaps another race")
        if new_open > other_close and (new_open - other_close) < gap:
            fail("ERR_START_LINE_WINDOW_CONFLICT", "consecutive prestart windows need a 3-minute gap")
        if other_open > new_close and (other_open - new_close) < gap:
            fail("ERR_START_LINE_WINDOW_CONFLICT", "consecutive prestart windows need a 3-minute gap")
    blocked = "DIVISION_UNDER_MINIMUM" if services.under_min_division_exists(regatta) else None
    row = store.insert(
        "races",
        {
            "regatta_id": regatta["id"],
            "race_number": data["race_number"],
            "course_code": data["course_code"],
            "course_distance_nm": data["course_distance_nm"],
            "scheduled_start_utc": data["scheduled_start_utc"],
            "actual_start_utc": None,
            "start_status": "PENDING",
            "scoring_status": "NOT_SCORED",
            "general_recall_count": 0,
            "black_flag_active": False,
            "staffing_ready": False,
            "staffed_position_codes": [],
            "start_blocked_reason": blocked,
            "points_pool_total": 0,
            "results_closed_utc": None,
            "rescore_count": 0,
            "abandon_reason_code": None,
        },
    )
    # both computed staffing fields are seeded at creation, without a version bump
    ready, staffed, _missing, _ws, _we = calc.race_staffing_readiness(row)
    row["staffing_ready"] = ready
    row["staffed_position_codes"] = staffed
    return ok_row(row, 201)


@bp.post("/regatta-ops/races/<rid>/start-sequence")
def race_start_sequence(rid):
    ctx = Ctx(["RaceOfficer"])
    no_body(ctx)
    race = must("races", rid)
    # step 11
    if race["start_status"] not in ("PENDING", "GENERAL_RECALLED"):
        fail("ERR_INVALID_STATE", "the sequence starts only from PENDING or GENERAL_RECALLED")
    regatta = store.get("regattas", race["regatta_id"])
    # step 12
    if regatta["status"] != "RACING":
        fail("ERR_REGATTA_PHASE_INVALID", "the regatta is not RACING")
    # step 14
    if race.get("start_blocked_reason") is not None:
        fail("ERR_RACE_START_BLOCKED", "the race is blocked: %s" % race["start_blocked_reason"])
    # step 15
    newest_si = None
    for doc in store.find("race_documents", regatta_id=regatta["id"], doc_type="SI", status="PUBLISHED"):
        if newest_si is None or int(doc["revision"]) > int(newest_si["revision"]):
            newest_si = doc
    if newest_si is None or store.D(newest_si, "effective_utc") > store.now():
        fail("ERR_SAILING_INSTRUCTIONS_NOT_EFFECTIVE", "the newest SI revision is not yet in force")
    # step 20
    ready, staffed, _missing, _ws, _we = calc.race_staffing_readiness(race)
    if not ready:
        fail("ERR_STAFFING_INCOMPLETE", "the race committee is not fully on station")
    # the recall counters are deliberately left alone, so a third attempt stays under black flag
    store.apply_changes(
        race,
        {
            "start_status": "SEQUENCE_STARTED",
            "staffing_ready": ready,
            "staffed_position_codes": staffed,
        },
    )
    return ok_row(race)


def _open_results_window(race):
    """First result opens scoring; every later one re-stamps results_closed_utc."""
    changes = {"results_closed_utc": fmt_dt(store.now())}
    if race["scoring_status"] == "NOT_SCORED":
        changes["scoring_status"] = "PROVISIONAL"
    store.apply_changes(race, changes)


@bp.post("/regatta-ops/races/<rid>/recall")
def race_recall(rid):
    ctx = Ctx(["RaceOfficer"])
    data = validate(
        ctx,
        [
            F("recall_type", "enum", enum=("INDIVIDUAL", "GENERAL")),
            F("entry_id", "string", required=False),
            F("signal_utc", "datetime"),
            F("reason_code", "string", nonblank=True),
        ],
    )
    race = must("races", rid)
    entry = None
    if data["entry_id"] is not None:
        entry = must("entries", data["entry_id"])
    # step 11
    if race["start_status"] != "SEQUENCE_STARTED":
        fail("ERR_INVALID_STATE", "a recall is signalled only from SEQUENCE_STARTED")
    # step 17
    if entry is not None and entry.get("registration_status") == "WITHDRAWN":
        fail("ERR_ENTRY_WITHDRAWN", "the named entry has withdrawn")
    # step 23
    if entry is not None and entry["regatta_id"] != race["regatta_id"]:
        fail("ERR_CROSS_REGATTA_REFERENCE", "the entry belongs to another regatta")
    # step 45
    if entry is not None and entry.get("registration_status") != "ACCEPTED":
        fail("ERR_ENTRY_NOT_ACCEPTED", "the named entry is not ACCEPTED")
    # step 46
    if data["recall_type"] == "INDIVIDUAL" and entry is None:
        fail("ERR_RECALL_PAYLOAD_INVALID", "entry_id is required for an INDIVIDUAL recall")
    if data["recall_type"] == "GENERAL" and entry is not None:
        fail("ERR_RECALL_PAYLOAD_INVALID", "entry_id must be null for a GENERAL recall")
    window_open, _window_close = _prestart(race)
    if parse_dt(data["signal_utc"]) < window_open:
        fail("ERR_RECALL_PAYLOAD_INVALID", "signal_utc precedes the opening of the prestart window")

    # the flag as it stood at signal time, captured before any increment
    black_flag_applied = bool(race.get("black_flag_active"))
    if data["recall_type"] == "GENERAL":
        count = int(race["general_recall_count"]) + 1
        store.apply_changes(
            race,
            {
                "start_status": "GENERAL_RECALLED",
                "general_recall_count": count,
                "black_flag_active": bool(race.get("black_flag_active")) or count >= 2,
            },
        )
        resulting = "GENERAL_RECALLED"
    else:
        resulting = "SEQUENCE_STARTED"
        if black_flag_applied:
            store.insert(
                "race_results",
                {
                    "race_id": race["id"],
                    "entry_id": entry["id"],
                    "finish_status": "OCS",
                    "elapsed_seconds": None,
                    "penalty_percent": 0,
                    "corrected_seconds": None,
                    "place": None,
                    "points": 0,
                    "discardable": False,
                    "voided": False,
                },
            )
            _open_results_window(race)
    event = store.insert(
        "recall_events",
        {
            "race_id": race["id"],
            "recall_type": data["recall_type"],
            "entry_id": None if entry is None else entry["id"],
            "recorded_by_member_id": ctx.user_id,
            "signal_utc": data["signal_utc"],
            "reason_code": data["reason_code"],
            "resulting_start_status": resulting,
            "black_flag_applied": black_flag_applied,
        },
        versioned=False,
    )
    return ok_row(event, 201)


@bp.post("/regatta-ops/races/<rid>/start")
def race_start(rid):
    ctx = Ctx(["RaceOfficer"])
    data = validate(ctx, [F("actual_start_utc", "datetime")])
    race = must("races", rid)
    # step 11
    if race["start_status"] != "SEQUENCE_STARTED":
        fail("ERR_INVALID_STATE", "the start is recorded only from SEQUENCE_STARTED")
    # step 50
    window_open, _window_close = _prestart(race)
    if parse_dt(data["actual_start_utc"]) < window_open:
        fail("ERR_START_TIME_INVALID", "actual_start_utc precedes the prestart window")
    store.apply_changes(
        race, {"start_status": "STARTED", "actual_start_utc": data["actual_start_utc"]}
    )
    return ok_row(race)


@bp.post("/regatta-ops/races/<rid>/abandon")
def race_abandon(rid):
    ctx = Ctx(["RaceOfficer"])
    data = validate(ctx, [F("reason_code", "string", nonblank=True)])
    race = must("races", rid)
    # step 11
    if race["start_status"] not in ("SEQUENCE_STARTED", "STARTED"):
        fail("ERR_INVALID_STATE", "only a sequenced or started race may be abandoned")
    regatta = store.get("regattas", race["regatta_id"])
    # hop 1: terminal on the start dimension, and the only way out of FINAL
    store.apply_changes(
        race,
        {
            "start_status": "ABANDONED",
            "abandon_reason_code": data["reason_code"],
            "scoring_status": "NOT_SCORED",
            "points_pool_total": 0,
        },
    )
    # hop 2
    for result in store.find("race_results", race_id=race["id"]):
        store.apply_changes(
            result, {"voided": True, "points": 0, "place": None, "corrected_seconds": None}
        )
    # hop 3: every series total loses exactly the points this race had awarded
    services.refresh_series(regatta)
    services.refresh_final_race_count(regatta)
    return ok_row(race)


@bp.post("/regatta-ops/races/<rid>/score")
def race_score(rid):
    ctx = Ctx(["RaceOfficer"])
    no_body(ctx)
    race = must("races", rid)
    # step 11
    if race["scoring_status"] != "PROVISIONAL":
        fail("ERR_INVALID_STATE", "scoring closes only from PROVISIONAL")
    if race["start_status"] != "STARTED":
        fail("ERR_INVALID_STATE", "the race is not STARTED")
    regatta = store.get("regattas", race["regatta_id"])
    # step 12
    if regatta["status"] != "RACING":
        fail("ERR_REGATTA_PHASE_INVALID", "the regatta is not RACING")
    # step 49
    for division in store.find("divisions", regatta_id=regatta["id"]):
        if int(division.get("accepted_entry_count") or 0) >= 1 and division["status"] != "CONFIRMED":
            fail("ERR_DIVISION_NOT_CONFIRMED", "a division holding accepted entries is not CONFIRMED")
    # hop 1: the did-not-compete rows nobody enters by hand
    scored = set()
    for result in store.find("race_results", race_id=race["id"]):
        scored.add(result["entry_id"])
    for entry in store.find("entries", regatta_id=regatta["id"], registration_status="ACCEPTED"):
        if entry["id"] in scored:
            continue
        store.insert(
            "race_results",
            {
                "race_id": race["id"],
                "entry_id": entry["id"],
                "finish_status": "DNC",
                "elapsed_seconds": None,
                "penalty_percent": 0,
                "corrected_seconds": None,
                "place": None,
                "points": 0,
                "discardable": True,
                "voided": False,
            },
        )
    store.apply_changes(race, {"scoring_status": "FINAL"})
    # hop 2
    calc.race_points_and_places(race)
    # hop 3
    services.refresh_series(regatta)
    # hop 4
    services.refresh_final_race_count(regatta)
    services.maybe_score_regatta(regatta)
    return ok_row(race)


@bp.get("/regatta-ops/races/<rid>")
def race_read(rid):
    Ctx(READ_ROLES)
    return ok_row(must("races", rid))


@bp.get("/regatta-ops/races")
def race_list():
    Ctx(READ_ROLES)
    return list_read("races", ["regatta_id", "start_status", "scoring_status", "course_code"])


@bp.get("/regatta-ops/races/<rid>/staffing")
def race_staffing(rid):
    Ctx(["ClubAdmin", "RegattaChair", "RaceOfficer"])
    race = must("races", rid)
    ready, staffed, missing, window_start, window_end = calc.race_staffing_readiness(race)
    return ok(
        {
            "race_id": race["id"],
            "staffing_ready": ready,
            "staffed_position_codes": staffed,
            "missing_position_codes": missing,
            "coverage_window_start_utc": fmt_dt(window_start),
            "coverage_window_end_utc": fmt_dt(window_end),
        }
    )


# --------------------------------------------------------------------------
# RaceResult
# --------------------------------------------------------------------------


@bp.post("/regatta-ops/race-results")
def result_create():
    ctx = Ctx(["RaceOfficer"])
    data = validate(
        ctx,
        [
            F("race_id", "string"),
            F("entry_id", "string"),
            F("finish_status", "enum", enum=FINISH_STATUSES),
            F("elapsed_seconds", "number", required=False, defer=True),
            F("penalty_percent", "number", required=False, default=0, one_of=(0, 20, 30, 40)),
        ],
    )
    race = must("races", data["race_id"])
    entry = must("entries", data["entry_id"])
    # step 11
    if race["start_status"] != "STARTED":
        fail("ERR_INVALID_STATE", "results are recorded only while the race is STARTED")
    regatta = store.get("regattas", race["regatta_id"])
    # step 12
    if regatta["status"] != "RACING":
        fail("ERR_REGATTA_PHASE_INVALID", "the regatta is not RACING")
    # step 17
    if entry.get("registration_status") == "WITHDRAWN":
        fail("ERR_ENTRY_WITHDRAWN", "the named entry has withdrawn")
    # step 23
    if entry["regatta_id"] != race["regatta_id"]:
        fail("ERR_CROSS_REGATTA_REFERENCE", "the entry belongs to another regatta")
    # step 32
    for other in store.find("race_results", race_id=race["id"], entry_id=entry["id"]):
        fail("ERR_DUPLICATE_RECORD", "this entry already holds a result in this race")
    # step 44
    status = data["finish_status"]
    if status not in CREATABLE_FINISH_STATUSES:
        fail("ERR_RESULT_PAYLOAD_INVALID", "%s is minted by the server, never supplied" % status)
    elapsed = data["elapsed_seconds"]
    if status == "FINISHED":
        if elapsed is None:
            fail("ERR_RESULT_PAYLOAD_INVALID", "elapsed_seconds is required for FINISHED")
    elif elapsed is not None:
        fail("ERR_RESULT_PAYLOAD_INVALID", "elapsed_seconds is forbidden for %s" % status)
    if elapsed is not None and not (float(elapsed) > 0 and float(elapsed) <= 604800):
        fail("ERR_RESULT_PAYLOAD_INVALID", "elapsed_seconds is outside its declared range")
    # step 45
    if entry.get("registration_status") != "ACCEPTED":
        fail("ERR_ENTRY_NOT_ACCEPTED", "the named entry is not ACCEPTED")
    row = store.insert(
        "race_results",
        {
            "race_id": race["id"],
            "entry_id": entry["id"],
            "finish_status": status,
            "elapsed_seconds": elapsed,
            "penalty_percent": data["penalty_percent"],
            "corrected_seconds": None,
            "place": None,
            "points": 0,
            "discardable": True,
            "voided": False,
        },
    )
    # the corrected time is computed the moment a finisher is recorded
    row["corrected_seconds"] = calc.result_corrected_seconds(row, race, regatta)
    _open_results_window(race)
    return ok_row(row, 201)


@bp.get("/regatta-ops/race-results/<rid>")
def result_read(rid):
    Ctx(READ_ROLES)
    return ok_row(must("race_results", rid))


@bp.get("/regatta-ops/race-results")
def result_list():
    Ctx(READ_ROLES)
    return list_read("race_results", ["race_id", "entry_id", "finish_status", "voided"])


# --------------------------------------------------------------------------
# RecallEvent (append-only, no version)
# --------------------------------------------------------------------------


@bp.get("/regatta-ops/recall-events/<rid>")
def recall_read(rid):
    Ctx(["ClubAdmin", "RegattaChair", "RaceOfficer", "JuryChair", "Competitor"])
    return ok_row(must("recall_events", rid))


@bp.get("/regatta-ops/recall-events")
def recall_list():
    Ctx(["ClubAdmin", "RegattaChair", "RaceOfficer", "JuryChair", "Competitor"])
    return list_read("recall_events", ["race_id", "entry_id", "recorded_by_member_id", "recall_type"])
