"""Precincts, ballot styles and test decks."""

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

bp = Blueprint("styles", __name__)


# ---------------------------------------------------------------------------
# Precincts
# ---------------------------------------------------------------------------

@bp.post("/elections/<election_id>/precincts")
def create_precinct(election_id):
    auth.require(auth.ELECTIONS_DIRECTOR, auth.BALLOT_COORDINATOR)
    body = validate.body()
    precinct_code = validate.req_str(body, "precinct_code")
    district_codes = validate.req_str_set(body, "district_codes")
    registered_voter_count = validate.req_int(body, "registered_voter_count", minimum=0)
    polling_place = validate.req_str(body, "polling_place")
    election = guards.find("elections", election_id)
    guards.require_phase(election, ("SETUP", "CONTESTS_CERTIFIED"))
    row = store.insert("precincts", {
        "election_id": election_id,
        "precinct_code": precinct_code,
        "district_codes": district_codes,
        "registered_voter_count": registered_voter_count,
        "polling_place": polling_place,
        "assigned_style_id": None,
        "required_ballot_quantity": calc.required_ballot_quantity(registered_voter_count),
        "ballots_received": 0,
        "deployment_status": "NOT_READY",
    })
    derive.recompute_readiness(election)
    return envelope.created(serial.precinct(row))


@bp.get("/precincts/<precinct_id>")
def read_precinct(precinct_id):
    auth.require_any()
    row = guards.find("precincts", precinct_id)
    return envelope.ok(serial.precinct(row))


@bp.get("/precincts")
def list_precincts():
    auth.require_any()
    limit, offset = validate.pagination()
    election_id = validate.query_str("election_id")
    assigned_style_id = validate.query_str("assigned_style_id")
    deployment_status = validate.query_enum("deployment_status", ("READY", "NOT_READY"))
    rows = store.all_rows("precincts")
    if election_id:
        rows = [r for r in rows if r["election_id"] == election_id]
    if assigned_style_id:
        rows = [r for r in rows if r["assigned_style_id"] == assigned_style_id]
    if deployment_status:
        rows = [r for r in rows if r["deployment_status"] == deployment_status]
    rows.sort(key=lambda r: (r["precinct_code"], r["created_at"], r["_seq"]))
    page, total = validate.paginate(rows, limit, offset)
    return envelope.ok_list([serial.precinct(r) for r in page], limit, offset, total)


@bp.post("/precincts/<precinct_id>/assign-style")
def assign_style(precinct_id):
    auth.require(auth.BALLOT_COORDINATOR)
    body = validate.body()
    style_id = validate.req_str(body, "style_id")
    precinct = guards.find("precincts", precinct_id)
    election = store.get("elections", precinct["election_id"])
    style = store.get("ballot_styles", style_id)
    if style is None or style["election_id"] != precinct["election_id"]:
        fail("ERR_BALLOT_STYLE_NOT_FOUND", "Ballot style does not exist.")
    guards.require_phase(election, ("CONTESTS_CERTIFIED", "STYLES_LOCKED"))
    if style["status"] not in ("APPROVED", "LOCKED"):
        fail("ERR_STYLE_STATE_INVALID",
             "Ballot style state %s does not permit assignment." % style["status"])
    previous_id = precinct["assigned_style_id"]
    store.setf(precinct, assigned_style_id=style_id)
    if previous_id and previous_id != style_id:
        previous = store.get("ballot_styles", previous_id)
        if previous is not None:
            derive.recompute_style_precinct_count(previous)
    derive.recompute_style_precinct_count(style)
    derive.recompute_precinct(precinct)
    derive.recompute_readiness(election)
    return envelope.ok(serial.precinct(precinct))


# ---------------------------------------------------------------------------
# Ballot styles
# ---------------------------------------------------------------------------

@bp.post("/elections/<election_id>/ballot-styles")
def create_style(election_id):
    role, user = auth.require(auth.BALLOT_COORDINATOR)
    body = validate.body()
    style_code = validate.req_str(body, "style_code")
    district_codes = validate.req_str_set(body, "district_codes")
    language_set = validate.req_str_set(body, "language_set", must_contain=("EN",))
    required_formats = validate.req_str_set(body, "required_formats",
                                           allowed=calc.BALLOT_FORMATS,
                                           must_contain=("PAPER_STANDARD",))
    supersedes_style_id = validate.opt_str(body, "supersedes_style_id")
    election = guards.find("elections", election_id)
    superseded = None
    if supersedes_style_id is not None:
        superseded = store.get("ballot_styles", supersedes_style_id)
        if superseded is None or superseded["election_id"] != election_id:
            fail("ERR_BALLOT_STYLE_NOT_FOUND", "Ballot style does not exist.")
    guards.require_phase(election, ("SETUP", "CONTESTS_CERTIFIED"))
    row = store.insert("ballot_styles", {
        "election_id": election_id,
        "style_code": style_code,
        "district_codes": district_codes,
        "language_set": language_set,
        "required_formats": required_formats,
        "supersedes_style_id": supersedes_style_id,
        "revision": 1,
        "status": "DRAFT",
        "proof_cycle_count": 0,
        "proof_requested_by_user_id": None,
        "proof_decided_by_user_id": None,
        "translated_languages": [],
        "certified_formats": [],
        "rotation_seed_index": 0,
        "contest_count": 0,
        "precinct_count": 0,
    })
    row["contest_count"] = derive.style_contest_count(row)
    if superseded is not None:
        derive.cascade_style_superseded(superseded, row, role, user)
    derive.recompute_rotation_seeds(election_id)
    derive.sync_election(election)
    return envelope.created(serial.style(row))


@bp.get("/ballot-styles/<style_id>")
def read_style(style_id):
    auth.require_any()
    row = guards.find("ballot_styles", style_id)
    return envelope.ok(serial.style(row))


@bp.get("/ballot-styles")
def list_styles():
    auth.require_any()
    limit, offset = validate.pagination()
    election_id = validate.query_str("election_id")
    supersedes_style_id = validate.query_str("supersedes_style_id")
    status = validate.query_enum("status", ("DRAFT", "PROOFING", "PROOF_REJECTED",
                                           "APPROVED", "LOCKED", "SUPERSEDED"))
    rows = store.all_rows("ballot_styles")
    if election_id:
        rows = [r for r in rows if r["election_id"] == election_id]
    if supersedes_style_id:
        rows = [r for r in rows if r["supersedes_style_id"] == supersedes_style_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=store.order_key)
    page, total = validate.paginate(rows, limit, offset)
    return envelope.ok_list([serial.style(r) for r in page], limit, offset, total)


@bp.get("/ballot-styles/<style_id>/layout")
def read_layout(style_id):
    auth.require_any()
    basis = validate.query_enum("basis", calc.LAYOUT_BASES, "CERTIFIED_BASIS")
    style = guards.find("ballot_styles", style_id)
    election = store.election_of_style(style)
    codes = set(style["district_codes"])
    printed = [c for c in store.contests_of(election["id"])
               if c["status"] == "CERTIFIED" and c["district_code"] in codes]
    printed.sort(key=lambda c: (c["ballot_order_index"] is None,
                                c["ballot_order_index"] if c["ballot_order_index"] is not None else 0,
                                calc.contest_sort_key(c)))
    contests = []
    candidate_count = 0
    for contest in printed:
        entries, offset, modulus = calc.contest_layout(election, contest, style, basis)
        candidate_count += len(entries)
        contests.append({
            "contest_id": contest["id"],
            "title": contest["title"],
            "contest_type": contest["contest_type"],
            "district_code": contest["district_code"],
            "ballot_order_index": contest["ballot_order_index"],
            "seats_open": contest["seats_open"],
            "rotation_required": contest["rotation_required"],
            "rotation_offset": offset,
            "rotation_modulus": modulus,
            "candidates": entries,
        })
    return envelope.ok({
        "style_id": style["id"],
        "style_code": style["style_code"],
        "revision": style["revision"],
        "basis": basis,
        "rotation_policy": election["rotation_policy"],
        "rotation_seed_index": style["rotation_seed_index"],
        "contest_count": style["contest_count"],
        "candidate_count": candidate_count,
        "contests": contests,
    })


@bp.post("/ballot-styles/<style_id>/language-certifications")
def language_certifications(style_id):
    auth.require(auth.LANGUAGE_ACCESS_COORDINATOR)
    body = validate.body()
    translated_languages = validate.req_str_set(body, "translated_languages")
    certified_formats = validate.req_str_set(body, "certified_formats",
                                             allowed=calc.BALLOT_FORMATS)
    style = guards.find("ballot_styles", style_id)
    election = store.election_of_style(style)
    guards.require_phase(election, ("SETUP", "CONTESTS_CERTIFIED"))
    if style["status"] not in ("DRAFT", "PROOF_REJECTED"):
        fail("ERR_STYLE_STATE_INVALID",
             "Ballot style state %s does not permit certification." % style["status"])
    style["translated_languages"] = translated_languages
    style["certified_formats"] = certified_formats
    store.touch(style)
    return envelope.ok(serial.style(style))


@bp.post("/ballot-styles/<style_id>/request-proof")
def request_proof(style_id):
    role, user = auth.require(auth.BALLOT_COORDINATOR)
    style = guards.find("ballot_styles", style_id)
    election = store.election_of_style(style)
    allowed = ("CONTESTS_CERTIFIED", "STYLES_LOCKED") if style["status"] == "PROOF_REJECTED" \
        else ("CONTESTS_CERTIFIED",)
    guards.require_phase(election, allowed)
    if style["status"] not in ("DRAFT", "PROOF_REJECTED"):
        fail("ERR_STYLE_STATE_INVALID",
             "Ballot style state %s does not permit a proof request." % style["status"])
    if (style["contest_count"] or 0) < 1:
        fail("ERR_STYLE_STATE_INVALID", "Ballot style prints no certified contest.")
    translated = set(style["translated_languages"])
    certified = set(style["certified_formats"])
    if not set(style["language_set"]).issubset(translated) \
            or not set(style["required_formats"]).issubset(certified):
        fail("ERR_LANGUAGE_COVERAGE_INCOMPLETE",
             "Style is missing translations or alternative formats.")
    was_rejected = style["status"] == "PROOF_REJECTED"
    style["status"] = "PROOFING"
    style["proof_cycle_count"] = (style["proof_cycle_count"] or 0) + 1
    style["proof_requested_by_user_id"] = user
    style["proof_decided_by_user_id"] = None
    if was_rejected:
        style["revision"] = (style["revision"] or 1) + 1
    store.touch(style)
    return envelope.ok(serial.style(style))


@bp.post("/ballot-styles/<style_id>/proof-decision")
def proof_decision(style_id):
    role, user = auth.require(auth.ELECTIONS_DIRECTOR, auth.BALLOT_COORDINATOR)
    body = validate.body()
    decision = validate.req_enum(body, "decision", ("APPROVE", "REJECT"))
    validate.opt_str(body, "decision_note")
    style = guards.find("ballot_styles", style_id)
    election = store.election_of_style(style)
    if style["status"] != "PROOFING":
        fail("ERR_STYLE_STATE_INVALID",
             "Ballot style state %s does not permit a proof decision." % style["status"])
    guards.require_phase(election, ("CONTESTS_CERTIFIED",))
    if user is not None and user == style["proof_requested_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "This action must be performed by a different user.")
    style["proof_decided_by_user_id"] = user
    if decision == "APPROVE":
        style["status"] = "APPROVED"
        store.touch(style)
    else:
        style["status"] = "PROOF_REJECTED"
        style["translated_languages"] = []
        style["certified_formats"] = []
        store.touch(style)
        derive.void_decks_of_style(style)
    return envelope.ok(serial.style(style))


# ---------------------------------------------------------------------------
# Test decks
# ---------------------------------------------------------------------------

@bp.post("/ballot-styles/<style_id>/test-decks")
def create_test_deck(style_id):
    role, user = auth.require(auth.VOTING_SYSTEM_TECHNICIAN, auth.BALLOT_COORDINATOR)
    body = validate.body()
    deck_code = validate.req_str(body, "deck_code")
    ballot_count = validate.req_int(body, "ballot_count")
    blank_count = validate.req_int(body, "blank_count", minimum=0)
    overvote_count = validate.req_int(body, "overvote_count", minimum=0)
    expected_marks = validate.req_marks(body, "expected_marks", min_mark_count=1)
    style = guards.find("ballot_styles", style_id)
    election = store.election_of_style(style)
    guards.require_phase(election, ("CONTESTS_CERTIFIED", "STYLES_LOCKED"))
    if style["status"] not in ("APPROVED", "LOCKED"):
        fail("ERR_STYLE_STATE_INVALID",
             "Ballot style state %s does not permit deck construction." % style["status"])
    if ballot_count < 1:
        fail("ERR_EMPTY_TEST_DECK", "A test deck must contain at least one ballot.")
    codes = set(style["district_codes"])
    for mark in expected_marks:
        contest = store.get("contests", mark["contest_id"])
        if (contest is None or contest["election_id"] != election["id"]
                or contest["status"] != "CERTIFIED"
                or contest["district_code"] not in codes):
            fail("ERR_DECK_MARK_OFF_STYLE",
                 "Expected mark references a contest that is not printed on this style.")
        candidate = store.get("candidates", mark["candidate_id"])
        if (candidate is None or candidate["contest_id"] != contest["id"]
                or candidate["status"] != "CERTIFIED"):
            fail("ERR_DECK_MARK_OFF_STYLE",
                 "Expected mark references a candidate that is not printed on this style.")
    expected_total_marks = sum(m["mark_count"] for m in expected_marks)
    capacity = ballot_count * calc.LINES_PER_FACE
    if expected_total_marks > capacity:
        fail("ERR_DECK_MARKS_EXCEED_CAPACITY",
             "%d expected marks exceed the %d mark capacity of %d ballots."
             % (expected_total_marks, capacity, ballot_count))
    row = store.insert("test_decks", {
        "style_id": style_id,
        "deck_code": deck_code,
        "ballot_count": ballot_count,
        "blank_count": blank_count,
        "overvote_count": overvote_count,
        "expected_marks": expected_marks,
        "expected_total_marks": expected_total_marks,
        "status": "DRAFT",
        "created_by_user_id": user,
    })
    return envelope.created(serial.deck(row))


@bp.get("/ballot-styles/<style_id>/test-decks")
def list_test_decks(style_id):
    auth.require_any()
    limit, offset = validate.pagination()
    status = validate.query_enum("status", ("DRAFT", "SEALED", "CONSUMED", "VOIDED"))
    guards.find("ballot_styles", style_id)
    rows = store.decks_of_style(style_id)
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=store.order_key)
    page, total = validate.paginate(rows, limit, offset)
    return envelope.ok_list([serial.deck(r) for r in page], limit, offset, total)
