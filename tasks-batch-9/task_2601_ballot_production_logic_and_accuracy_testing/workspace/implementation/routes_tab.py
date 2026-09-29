"""Tabulator units, logic-and-accuracy sessions and the logical clock."""

from datetime import timedelta

from flask import Blueprint

import auth
import calc
import derive
import envelope
import guards
import serial
import store
import util
import validate
from errors import fail

bp = Blueprint("tab", __name__)

PROGRAM_STATUSES = ("UNPROGRAMMED", "PROGRAMMED", "LA_PASSED", "LA_FAILED")
CUSTODY_STATUSES = ("IN_VAULT", "DEPLOYED", "RETURNED", "SEALED_RETENTION")
SESSION_STATUSES = ("SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED")


# ---------------------------------------------------------------------------
# Tabulator units
# ---------------------------------------------------------------------------

@bp.post("/elections/<election_id>/tabulator-units")
def create_unit(election_id):
    auth.require(auth.VOTING_SYSTEM_TECHNICIAN)
    body = validate.body()
    asset_tag = validate.req_str(body, "asset_tag")
    firmware_version = validate.opt_str(body, "firmware_version")
    election = guards.find("elections", election_id)
    guards.require_phase(election, ("SETUP", "CONTESTS_CERTIFIED", "STYLES_LOCKED"))
    row = store.insert("tabulator_units", {
        "election_id": election_id,
        "precinct_id": None,
        "programmed_style_id": None,
        "asset_tag": asset_tag,
        "firmware_version": firmware_version,
        "program_status": "UNPROGRAMMED",
        "custody_status": "IN_VAULT",
        "seal_number": None,
        "programmed_by_user_id": None,
        "la_session_count": 0,
        "retention_until": None,
    })
    return envelope.created(serial.unit(row))


@bp.get("/tabulator-units/<unit_id>")
def read_unit(unit_id):
    auth.require_any()
    row = guards.find("tabulator_units", unit_id)
    return envelope.ok(serial.unit(row))


@bp.get("/tabulator-units")
def list_units():
    auth.require_any()
    limit, offset = validate.pagination()
    election_id = validate.query_str("election_id")
    precinct_id = validate.query_str("precinct_id")
    programmed_style_id = validate.query_str("programmed_style_id")
    program_status = validate.query_enum("program_status", PROGRAM_STATUSES)
    custody_status = validate.query_enum("custody_status", CUSTODY_STATUSES)
    rows = store.all_rows("tabulator_units")
    if election_id:
        rows = [r for r in rows if r["election_id"] == election_id]
    if precinct_id:
        rows = [r for r in rows if r["precinct_id"] == precinct_id]
    if programmed_style_id:
        rows = [r for r in rows if r["programmed_style_id"] == programmed_style_id]
    if program_status:
        rows = [r for r in rows if r["program_status"] == program_status]
    if custody_status:
        rows = [r for r in rows if r["custody_status"] == custody_status]
    rows.sort(key=lambda r: (r["asset_tag"], r["created_at"], r["_seq"]))
    page, total = validate.paginate(rows, limit, offset)
    return envelope.ok_list([serial.unit(r) for r in page], limit, offset, total)


@bp.post("/tabulator-units/<unit_id>/program")
def program_unit(unit_id):
    role, user = auth.require(auth.VOTING_SYSTEM_TECHNICIAN)
    body = validate.body()
    style_id = validate.req_str(body, "style_id")
    firmware_version = validate.req_str(body, "firmware_version")
    unit = guards.find("tabulator_units", unit_id)
    election = store.get("elections", unit["election_id"])
    style = store.get("ballot_styles", style_id)
    if style is None or style["election_id"] != unit["election_id"]:
        fail("ERR_BALLOT_STYLE_NOT_FOUND", "Ballot style does not exist.")
    guards.require_phase(election, ("STYLES_LOCKED",))
    if style["status"] != "LOCKED":
        fail("ERR_STYLE_STATE_INVALID",
             "Ballot style state %s does not permit programming." % style["status"])
    if (unit["program_status"] not in ("UNPROGRAMMED", "LA_FAILED")
            or unit["custody_status"] != "IN_VAULT"):
        fail("ERR_UNIT_STATE_INVALID",
             "Tabulator state %s/%s does not permit programming."
             % (unit["program_status"], unit["custody_status"]))
    unit["programmed_style_id"] = style_id
    unit["firmware_version"] = firmware_version
    unit["programmed_by_user_id"] = user
    unit["program_status"] = "PROGRAMMED"
    store.touch(unit)
    return envelope.ok(serial.unit(unit))


@bp.post("/tabulator-units/<unit_id>/deploy")
def deploy_unit(unit_id):
    role, user = auth.require(auth.WAREHOUSE_CUSTODIAN)
    body = validate.body()
    precinct_id = validate.req_str(body, "precinct_id")
    seal_number = validate.req_str(body, "seal_number")
    unit = guards.find("tabulator_units", unit_id)
    election = store.get("elections", unit["election_id"])
    precinct = store.get("precincts", precinct_id)
    if precinct is None or precinct["election_id"] != unit["election_id"]:
        fail("ERR_PRECINCT_NOT_FOUND", "Precinct does not exist.")
    guards.require_phase(election, ("STYLES_LOCKED",))
    if unit["program_status"] != "LA_PASSED" or unit["custody_status"] != "IN_VAULT":
        fail("ERR_UNIT_STATE_INVALID",
             "Tabulator state %s/%s does not permit deployment."
             % (unit["program_status"], unit["custody_status"]))
    if not any(l["custody_state"] == "ISSUED"
               for l in store.lots_of_precinct(precinct_id)):
        fail("ERR_LOT_STATE_INVALID",
             "No ballot lot has been issued to this precinct.")
    if unit["programmed_style_id"] != precinct["assigned_style_id"]:
        fail("ERR_UNIT_STYLE_MISMATCH",
             "The unit is programmed for another ballot style.")
    if derive.seal_in_use(unit["election_id"], seal_number, exclude_unit_id=unit["id"]):
        fail("ERR_SEAL_NUMBER_DUPLICATE",
             "Seal number '%s' is already in use in this election." % seal_number)
    unit["custody_status"] = "DEPLOYED"
    unit["precinct_id"] = precinct_id
    unit["seal_number"] = seal_number
    store.touch(unit)
    derive.append_custody(unit["election_id"], "TABULATOR_UNIT", unit["id"],
                          "SEAL_APPLIED", "IN_VAULT", "DEPLOYED", seal_number,
                          role, user)
    derive.recompute_open_seals(election)
    derive.recompute_precinct(precinct)
    derive.recompute_readiness(election)
    return envelope.ok(serial.unit(unit))


@bp.post("/tabulator-units/<unit_id>/break-seal")
def break_seal(unit_id):
    role, user = auth.require(auth.WAREHOUSE_CUSTODIAN)
    body = validate.body()
    validate.req_str(body, "reason")
    unit = guards.find("tabulator_units", unit_id)
    election = store.get("elections", unit["election_id"])
    guards.require_phase(election, ("STYLES_LOCKED", "DEPLOYED"))
    if unit["custody_status"] != "DEPLOYED":
        fail("ERR_UNIT_STATE_INVALID",
             "Tabulator custody state %s does not permit breaking a seal."
             % unit["custody_status"])
    precinct = store.get("precincts", unit["precinct_id"])
    broken_seal = unit["seal_number"]
    unit["custody_status"] = "IN_VAULT"
    unit["seal_number"] = None
    unit["precinct_id"] = None
    store.touch(unit)
    derive.append_custody(unit["election_id"], "TABULATOR_UNIT", unit["id"],
                          "SEAL_BROKEN", "DEPLOYED", "IN_VAULT", broken_seal,
                          role, user)
    derive.recompute_open_seals(election)
    if precinct is not None:
        derive.recompute_precinct(precinct)
    derive.recompute_readiness(election)
    return envelope.ok(serial.unit(unit))


@bp.post("/tabulator-units/<unit_id>/seal-retention")
def seal_retention(unit_id):
    role, user = auth.require(auth.WAREHOUSE_CUSTODIAN)
    body = validate.body()
    seal_number = validate.req_str(body, "seal_number")
    retention_days = validate.req_int(body, "retention_days", minimum=1)
    unit = guards.find("tabulator_units", unit_id)
    election = store.get("elections", unit["election_id"])
    if unit["custody_status"] != "RETURNED":
        fail("ERR_UNIT_STATE_INVALID",
             "Tabulator custody state %s does not permit a retention seal."
             % unit["custody_status"])
    if election is None or election["status"] != "RECONCILED":
        fail("ERR_RETENTION_BEFORE_RECONCILIATION",
             "The election has not been reconciled.")
    if derive.seal_in_use(unit["election_id"], seal_number, exclude_unit_id=unit["id"]):
        fail("ERR_SEAL_NUMBER_DUPLICATE",
             "Seal number '%s' is already in use in this election." % seal_number)
    anchor = util.parse_ts(election["election_date"])
    unit["custody_status"] = "SEALED_RETENTION"
    unit["seal_number"] = seal_number
    unit["retention_until"] = util.fmt_ts(anchor + timedelta(days=retention_days))
    store.touch(unit)
    derive.append_custody(unit["election_id"], "TABULATOR_UNIT", unit["id"],
                          "RETENTION_SEAL", "RETURNED", "SEALED_RETENTION",
                          seal_number, role, user)
    derive.recompute_open_seals(election)
    return envelope.ok(serial.unit(unit))


# ---------------------------------------------------------------------------
# Logic & accuracy sessions
# ---------------------------------------------------------------------------

def _buffered(session):
    start = util.parse_ts(session["scheduled_start"])
    end = util.parse_ts(session["scheduled_end"])
    return (start - timedelta(minutes=calc.SETUP_BUFFER_MINUTES),
            end + timedelta(minutes=calc.SETUP_BUFFER_MINUTES))


@bp.post("/la-test-sessions")
def create_session():
    auth.require(auth.VOTING_SYSTEM_TECHNICIAN)
    body = validate.body()
    tabulator_id = validate.req_str(body, "tabulator_id")
    deck_id = validate.req_str(body, "deck_id")
    session_type = validate.req_enum(body, "session_type", calc.SESSION_TYPES)
    scheduled_start = validate.req_ts(body, "scheduled_start")
    scheduled_end = validate.req_ts(body, "scheduled_end")
    notice_posted_at = validate.req_ts(body, "public_notice_posted_at")
    if scheduled_end <= scheduled_start:
        fail("ERR_INVALID_REQUEST", "scheduled_end must be strictly after scheduled_start.")
    unit = store.get("tabulator_units", tabulator_id)
    if unit is None:
        fail("ERR_TABULATOR_NOT_FOUND", "Tabulator unit does not exist.")
    deck = store.get("test_decks", deck_id)
    deck_election = store.election_of_deck(deck) if deck is not None else None
    if deck is None or deck_election is None or deck_election["id"] != unit["election_id"]:
        fail("ERR_TEST_DECK_NOT_FOUND", "Test deck does not exist.")
    election = store.get("elections", unit["election_id"])
    guards.require_phase(election, ("STYLES_LOCKED", "DEPLOYED", "POLLS_CLOSED"))
    if unit["program_status"] not in ("PROGRAMMED", "LA_PASSED"):
        fail("ERR_UNIT_STATE_INVALID",
             "Tabulator program state %s has nothing to test." % unit["program_status"])
    if deck["status"] != "DRAFT":
        fail("ERR_DECK_STATE_INVALID",
             "Test deck state %s cannot be scheduled." % deck["status"])
    lo = scheduled_start - timedelta(minutes=calc.SETUP_BUFFER_MINUTES)
    hi = scheduled_end + timedelta(minutes=calc.SETUP_BUFFER_MINUTES)
    for other in store.sessions_of_unit(tabulator_id):
        other_lo, other_hi = _buffered(other)
        if lo <= other_hi and other_lo <= hi:
            fail("ERR_UNIT_TEST_WINDOW_CONFLICT",
                 "The tabulator already hosts a session across this window.")
    row = store.insert("la_sessions", {
        "tabulator_id": tabulator_id,
        "deck_id": deck_id,
        "session_type": session_type,
        "scheduled_start": util.fmt_ts(scheduled_start),
        "scheduled_end": util.fmt_ts(scheduled_end),
        "public_notice_posted_at": util.fmt_ts(notice_posted_at),
        "status": "SCHEDULED",
        "notice_lead_minutes": util.floor_minutes(scheduled_start, notice_posted_at),
        "observer_count": 0,
        "observer_names": [],
        "reported_marks": [],
        "reported_blank_count": None,
        "reported_overvote_count": None,
        "discrepancy_count": None,
        "conducted_by_user_id": None,
        "started_at": None,
        "completed_at": None,
    })
    return envelope.created(serial.session(row))


@bp.get("/la-test-sessions/<session_id>")
def read_session(session_id):
    auth.require_any()
    row = guards.find("la_sessions", session_id)
    return envelope.ok(serial.session(row))


@bp.get("/la-test-sessions")
def list_sessions():
    auth.require_any()
    limit, offset = validate.pagination()
    tabulator_id = validate.query_str("tabulator_id")
    deck_id = validate.query_str("deck_id")
    status = validate.query_enum("status", SESSION_STATUSES)
    session_type = validate.query_enum("session_type", calc.SESSION_TYPES)
    rows = store.all_rows("la_sessions")
    if tabulator_id:
        rows = [r for r in rows if r["tabulator_id"] == tabulator_id]
    if deck_id:
        rows = [r for r in rows if r["deck_id"] == deck_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if session_type:
        rows = [r for r in rows if r["session_type"] == session_type]
    rows.sort(key=store.order_key)
    page, total = validate.paginate(rows, limit, offset)
    return envelope.ok_list([serial.session(r) for r in page], limit, offset, total)


@bp.post("/la-test-sessions/<session_id>/observers")
def add_observer(session_id):
    auth.require(auth.VOTING_SYSTEM_TECHNICIAN, auth.PUBLIC_OBSERVER)
    body = validate.body()
    observer_name = validate.req_str(body, "observer_name")
    session = guards.find("la_sessions", session_id)
    if session["status"] != "SCHEDULED":
        fail("ERR_SESSION_STATE_INVALID",
             "Session state %s does not accept observers." % session["status"])
    session["observer_names"] = list(session["observer_names"]) + [observer_name]
    session["observer_count"] = len(session["observer_names"])
    store.touch(session)
    return envelope.ok(serial.session(session))


@bp.post("/la-test-sessions/<session_id>/start")
def start_session(session_id):
    role, user = auth.require(auth.VOTING_SYSTEM_TECHNICIAN)
    session = guards.find("la_sessions", session_id)
    unit = store.get("tabulator_units", session["tabulator_id"])
    deck = store.get("test_decks", session["deck_id"])
    if session["status"] != "SCHEDULED":
        fail("ERR_SESSION_STATE_INVALID",
             "Session state %s cannot be started." % session["status"])
    if unit is None or unit["program_status"] not in ("PROGRAMMED", "LA_PASSED"):
        fail("ERR_UNIT_STATE_INVALID",
             "Tabulator program state does not permit a test.")
    if deck is None or deck["status"] != "DRAFT":
        fail("ERR_DECK_STATE_INVALID", "The test deck is no longer usable.")
    if user is not None and user == unit["programmed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The technician who programmed the unit may not conduct its test.")
    election = store.get("elections", unit["election_id"])
    required_lead = (election["la_notice_hours"] or 0) * 60
    if (session["notice_lead_minutes"] or 0) < required_lead:
        fail("ERR_PUBLIC_NOTICE_TOO_LATE",
             "Public notice lead of %s minutes is below the required %d."
             % (session["notice_lead_minutes"], required_lead))
    start = util.parse_ts(session["scheduled_start"])
    end = util.parse_ts(session["scheduled_end"])
    now = util.now()
    if now < start - timedelta(minutes=calc.SESSION_EARLY_START_MINUTES) or now > end:
        fail("ERR_OUTSIDE_TEST_WINDOW",
             "The logical clock is outside the session admission window.")
    minimum = (calc.MIN_PUBLIC_OBSERVERS if session["session_type"] == "PRE_ELECTION_PUBLIC"
               else calc.MIN_AUDIT_OBSERVERS)
    if (session["observer_count"] or 0) < minimum:
        fail("ERR_INSUFFICIENT_OBSERVERS",
             "%d observers are required for a %s session."
             % (minimum, session["session_type"]))
    session["status"] = "IN_PROGRESS"
    session["started_at"] = util.now_str()
    session["conducted_by_user_id"] = user
    store.touch(session)
    store.setf(deck, status="SEALED")
    return envelope.ok(serial.session(session))


@bp.post("/la-test-sessions/<session_id>/record-results")
def record_results(session_id):
    role, user = auth.require(auth.VOTING_SYSTEM_TECHNICIAN)
    body = validate.body()
    reported_marks = validate.req_marks(body, "reported_marks", min_mark_count=0)
    reported_blank_count = validate.req_int(body, "reported_blank_count", minimum=0)
    reported_overvote_count = validate.req_int(body, "reported_overvote_count", minimum=0)
    session = guards.find("la_sessions", session_id)
    if session["status"] != "IN_PROGRESS":
        fail("ERR_SESSION_STATE_INVALID",
             "Session state %s cannot record results." % session["status"])
    if user != session["conducted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "Results are recorded by the technician who conducted the test.")
    unit = store.get("tabulator_units", session["tabulator_id"])
    deck = store.get("test_decks", session["deck_id"])
    election = store.get("elections", unit["election_id"])
    total = calc.discrepancy(deck, reported_marks, reported_blank_count,
                             reported_overvote_count)
    session["reported_marks"] = reported_marks
    session["reported_blank_count"] = reported_blank_count
    session["reported_overvote_count"] = reported_overvote_count
    session["discrepancy_count"] = total
    session["completed_at"] = util.now_str()
    session["status"] = "PASSED" if total == 0 else "FAILED"
    store.touch(session)
    if total == 0:
        if deck["status"] == "SEALED":
            store.setf(deck, status="CONSUMED")
        changes = {"program_status": "LA_PASSED",
                   "la_session_count": len(store.sessions_of_unit(unit["id"]))}
        store.setf(unit, **changes)
        precinct = store.get("precincts", unit["precinct_id"])
        if precinct is not None:
            derive.recompute_precinct(precinct)
        derive.recompute_readiness(election)
    else:
        derive.cascade_la_failure(session, unit, deck, election, role, user)
    return envelope.ok(serial.session(session))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    body = validate.body()
    moment = validate.req_ts(body, "now")
    util.set_now(moment)
    return envelope.ok({"now": util.now_str()})
