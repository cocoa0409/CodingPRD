"""Code titles, supplement cycles, submissions and conflict resolution."""
from flask import Blueprint, g

import calc
import domain
from core import (ROLE_CODIFICATION, STAFF_ROLES, ApiError, authorize,
                  body_dict, db, fetch, fk, invalid, listing, new_record,
                  now_date, occ, ok, opt_enum, ok_list, q, req_date, req_enum,
                  req_int, req_str, sort_records, touch)

bp = Blueprint("codification", __name__)

ACTIONS = ("ADD", "AMEND", "REPEAL")
BASES = ("LATER_ADOPTION_WINS", "SPECIFIC_OVER_GENERAL", "MANUAL_OVERRIDE")


# ------------------------------------------------------------ code titles
@bp.route("/clerk/code-titles", methods=["POST"])
def create_code_title():
    authorize((ROLE_CODIFICATION,))
    body = body_dict()
    title_number = req_int(body, "title_number", minimum=1)
    name = req_str(body, "name")
    status = opt_enum(body, "status", ("ACTIVE", "RESERVED"), default="ACTIVE")
    for existing in db.code_titles.values():
        if existing["title_number"] == title_number:
            raise ApiError("ERR_DUPLICATE_CODE_TITLE", 422)
    title = new_record()
    title.update({
        "title_number": title_number,
        "name": name,
        "section_refs": [],
        "current_supplement_number": 0,
        "status": status,
    })
    db.code_titles[title["id"]] = title
    return ok(title, 201)


@bp.route("/clerk/code-titles/<title_id>", methods=["GET"])
def get_code_title(title_id):
    authorize(STAFF_ROLES)
    return ok(fetch(db.code_titles, title_id, "ERR_CODE_TITLE_NOT_FOUND"))


@bp.route("/clerk/code-titles", methods=["GET"])
def list_code_titles():
    authorize(STAFF_ROLES)
    return listing(list(db.code_titles.values()), {"status": q("status")})


# -------------------------------------------------------- supplement cycles
@bp.route("/clerk/code-titles/<title_id>/supplement-cycles", methods=["POST"])
def create_cycle(title_id):
    authorize((ROLE_CODIFICATION,))
    title = fetch(db.code_titles, title_id, "ERR_CODE_TITLE_NOT_FOUND")
    body = body_dict()
    supplement_number = req_int(body, "supplement_number", minimum=1)
    open_on = req_date(body, "window_open_on")
    close_on = req_date(body, "window_close_on")
    siblings = domain.cycles_of(title["id"])
    for sibling in siblings:
        if sibling["supplement_number"] == supplement_number:
            raise ApiError("ERR_DUPLICATE_SUPPLEMENT_NUMBER", 422)
    if close_on < open_on:
        raise ApiError("ERR_SUPPLEMENT_WINDOW_CONFLICT", 409)
    for sibling in siblings:
        if sibling["status"] not in ("OPEN", "LOCKED"):
            continue
        # "overlap OR abut": a window opening the day after another closes collides
        if (open_on - sibling["window_close_on"]).days <= 1 and \
                (sibling["window_open_on"] - close_on).days <= 1:
            raise ApiError("ERR_SUPPLEMENT_WINDOW_CONFLICT", 409)
    cycle = new_record()
    cycle.update({
        "code_title_id": title["id"],
        "supplement_number": supplement_number,
        "window_open_on": open_on,
        "window_close_on": close_on,
        "status": "OPEN",
        "submission_count": 0,
        "client_submission_count": 0,
        "conflict_count": 0,
        "certified_on": None,
    })
    db.cycles[cycle["id"]] = cycle
    return ok(cycle, 201)


@bp.route("/clerk/code-titles/<title_id>/supplement-cycles", methods=["GET"])
def list_cycles_of_title(title_id):
    authorize(STAFF_ROLES)
    fetch(db.code_titles, title_id, "ERR_CODE_TITLE_NOT_FOUND")
    return listing(domain.cycles_of(title_id))


@bp.route("/clerk/supplement-cycles/<cycle_id>", methods=["GET"])
def get_cycle(cycle_id):
    authorize(STAFF_ROLES)
    return ok(fetch(db.cycles, cycle_id, "ERR_CYCLE_NOT_FOUND"))


@bp.route("/clerk/supplement-cycles", methods=["GET"])
def list_cycles():
    authorize(STAFF_ROLES)
    return listing(list(db.cycles.values()),
                   {"code_title_id": q("code_title_id"), "status": q("status")})


@bp.route("/clerk/supplement-cycles/<cycle_id>/lock", methods=["POST"])
def lock_cycle(cycle_id):
    authorize((ROLE_CODIFICATION,))
    cycle = fetch(db.cycles, cycle_id, "ERR_CYCLE_NOT_FOUND")
    submissions = domain.submissions_of(cycle["id"])
    live = [s for s in submissions if s["status"] != "WITHDRAWN"]
    if cycle["status"] != "OPEN" or not live:
        raise ApiError("ERR_CYCLE_NOT_OPEN", 409)
    cycle["status"] = "LOCKED"
    touch(cycle)
    for submission in submissions:
        if submission["status"] == "PENDING":
            submission["status"] = "IN_REVIEW"
            touch(submission)
    domain.recompute_cycle_counters(cycle)
    return ok(cycle)


@bp.route("/clerk/supplement-cycles/<cycle_id>/certify", methods=["POST"])
def certify_cycle(cycle_id):
    authorize((ROLE_CODIFICATION,))
    cycle = fetch(db.cycles, cycle_id, "ERR_CYCLE_NOT_FOUND")
    body = body_dict()
    certified_on = req_date(body, "certified_on")
    if cycle["status"] != "LOCKED":
        raise ApiError("ERR_CYCLE_NOT_LOCKED", 409)
    submissions = domain.submissions_of(cycle["id"])
    if cycle["conflict_count"] != 0 or any(
            s["status"] == "CONFLICT_HELD" for s in submissions):
        raise ApiError("ERR_UNRESOLVED_CONFLICTS", 409)
    if any(s["status"] in ("PENDING", "IN_REVIEW") for s in submissions):
        raise ApiError("ERR_CYCLE_HAS_OPEN_SUBMISSIONS", 409)
    for submission in submissions:
        if submission["resolved_by_user_id"] == g.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403)
    cycle["status"] = "CERTIFIED"
    cycle["certified_on"] = certified_on
    touch(cycle)
    title = db.code_titles.get(cycle["code_title_id"])
    accepted = [s for s in submissions if s["status"] == "ACCEPTED"]
    if title is not None:
        refs = list(title["section_refs"])
        for submission in accepted:
            ref = submission["code_section_ref"]
            if submission["action"] == "ADD":
                refs.append(ref)
            elif submission["action"] == "REPEAL" and ref in refs:
                refs.remove(ref)
        title["section_refs"] = refs
        title["current_supplement_number"] = cycle["supplement_number"]
        touch(title)
    for submission in accepted:
        instrument = db.instruments.get(submission["instrument_id"])
        if instrument is None:
            continue
        domain.apply_effective_date(instrument)
        if instrument["status"] == "PUBLISHED":
            instrument["status"] = "EFFECTIVE"
            touch(instrument)
    return ok(cycle)


# --------------------------------------------------- codification submissions
@bp.route("/clerk/codification-submissions", methods=["POST"])
def create_submission():
    authorize((ROLE_CODIFICATION,))
    body = body_dict()
    cycle = fk(body, "cycle_id", db.cycles, "ERR_CYCLE_NOT_FOUND")
    instrument = fk(body, "instrument_id", db.instruments, "ERR_INSTRUMENT_NOT_FOUND")
    code_section_ref = req_str(body, "code_section_ref")
    action = req_enum(body, "action", ACTIONS)
    if cycle is None:
        raise invalid("Field 'cycle_id' is required.")
    if instrument is None:
        raise invalid("Field 'instrument_id' is required.")
    title = db.code_titles.get(cycle["code_title_id"])
    occ(body, "expected_code_title_version", title, "ERR_STALE_CODE_TITLE_VERSION")
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN", 409)
    live_client = [s for s in domain.submissions_of(cycle["id"])
                   if s["origin"] == "CLIENT" and s["status"] != "WITHDRAWN"]
    superseded = domain.supersede_target(cycle["id"], instrument["id"], code_section_ref)
    effective_client_count = len(live_client)
    if superseded is not None and superseded["origin"] == "CLIENT":
        effective_client_count -= 1
    if effective_client_count >= calc.MAX_CLIENT_SUBMISSIONS_PER_CYCLE:
        raise ApiError("ERR_CYCLE_SUBMISSION_CAPACITY", 422)
    today = now_date()
    if not (cycle["window_open_on"] <= today <= cycle["window_close_on"]):
        raise ApiError("ERR_OUTSIDE_SUBMISSION_WINDOW", 409)
    if (instrument["code_section_ref"] != code_section_ref
            or instrument["code_title_id"] != cycle["code_title_id"]):
        raise ApiError("ERR_CODE_SECTION_UNKNOWN", 422)
    submission = domain.new_submission(cycle, instrument, code_section_ref,
                                       action, "CLIENT")
    touch(title)
    return ok(submission, 201)


@bp.route("/clerk/codification-submissions/<submission_id>", methods=["GET"])
def get_submission(submission_id):
    authorize(STAFF_ROLES)
    return ok(fetch(db.submissions, submission_id, "ERR_SUBMISSION_NOT_FOUND"))


@bp.route("/clerk/codification-submissions", methods=["GET"])
def list_submissions():
    authorize(STAFF_ROLES)
    return listing(list(db.submissions.values()), {
        "cycle_id": q("cycle_id"),
        "instrument_id": q("instrument_id"),
        "conflict_with_submission_id": q("conflict_with_submission_id"),
        "status": q("status"),
    })


@bp.route("/clerk/codification-submissions/<submission_id>/decide",
          methods=["POST"])
def decide_submission(submission_id):
    authorize((ROLE_CODIFICATION,))
    submission = fetch(db.submissions, submission_id, "ERR_SUBMISSION_NOT_FOUND")
    body = body_dict()
    decision = req_enum(body, "decision", ("ACCEPT", "REJECT"))
    if submission["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_SUBMISSION_STATE", 409)
    cycle = db.cycles.get(submission["cycle_id"])
    if cycle is None or cycle["status"] != "LOCKED":
        raise ApiError("ERR_CYCLE_NOT_LOCKED", 409)
    submission["status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    touch(submission)
    domain.recompute_cycle_counters(cycle)
    return ok(submission)


@bp.route("/clerk/codification-submissions/<submission_id>/resolve-conflict",
          methods=["POST"])
def resolve_conflict(submission_id):
    authorize((ROLE_CODIFICATION,))
    submission = fetch(db.submissions, submission_id, "ERR_SUBMISSION_NOT_FOUND")
    body = body_dict()
    winning = fk(body, "winning_submission_id", db.submissions,
                 "ERR_SUBMISSION_NOT_FOUND")
    basis = req_enum(body, "resolution_basis", BASES)
    if basis == "MANUAL_OVERRIDE" and winning is None:
        raise invalid("winning_submission_id is required under MANUAL_OVERRIDE.")
    if submission["status"] != "CONFLICT_HELD":
        raise ApiError("ERR_INVALID_SUBMISSION_STATE", 409)
    cycle = db.cycles.get(submission["cycle_id"])
    if cycle is None or cycle["status"] != "LOCKED":
        raise ApiError("ERR_CYCLE_NOT_LOCKED", 409)
    partner = db.submissions.get(submission["conflict_with_submission_id"])
    if partner is None:
        raise ApiError("ERR_INVALID_SUBMISSION_STATE", 409)
    pair = [submission, partner]
    if basis == "MANUAL_OVERRIDE":
        if winning["id"] not in (submission["id"], partner["id"]):
            raise invalid("winning_submission_id must name one of the two conflict "
                          "partners.")
        winner = winning
        loser = partner if winning["id"] == submission["id"] else submission
    else:
        winner, loser = calc.supplement_conflict_precedence(
            basis, pair, lambda s: db.instruments.get(s["instrument_id"]))
    for row, status in ((winner, "ACCEPTED"), (loser, "REJECTED")):
        row["status"] = status
        row["conflict_with_submission_id"] = None
        row["resolution_basis"] = basis
        row["resolved_by_user_id"] = g.user_id
        touch(row)
    domain.recompute_cycle_counters(cycle)
    return ok(submission)
