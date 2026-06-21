"""Assignment routes: create (OCC + supersede), get, accept, decline, sub-lists.
PRD §3.5, §3.9, §3.12."""
from datetime import datetime, timezone
from flask import Blueprint, request

from db import db, common_fields, touch
from errors import err
from middleware import get_user_context, require_role
from response import success_object
from serializers import assignment_out, payout_ledger_out, qa_report_out
from services import calc
from services.helpers import (get_json_body, require_fields, paginate_and_respond,
                              append_ledger_entry)
from services.lookups import (get_assignment, get_job, get_project, get_linguist,
                              active_translator_assignment, active_reviewer_assignment,
                              assignments_of_job)

bp = Blueprint("assignments", __name__)

ROLES = {"TRANSLATOR", "REVIEWER"}
NON_TERMINAL = {"OFFERED", "ACCEPTED", "IN_PROGRESS"}


def _parse_dt(s, field):
    if not isinstance(s, str):
        raise err("ERR_INVALID_REQUEST", "%s must be an ISO 8601 string" % field)
    try:
        v = s
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "%s must be a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _linguist_qualified(linguist, source_locale, target_locale):
    for p in linguist["qualified_pairs"]:
        if (p.get("source_locale") == source_locale
                and p.get("target_locale") == target_locale):
            return True
    return False


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intervals: touching at endpoints does NOT overlap."""
    return a_start < b_end and b_start < a_end


def _shared_utc_days(start, end):
    """Set of UTC calendar dates the half-open window [start, end) touches."""
    days = set()
    d = start.date()
    last = end.date()
    # If window is empty at the boundary, include start date only.
    cur = d
    while cur <= last:
        # half-open: a window ending exactly at midnight of `last` does not occupy
        # that final day. But to be safe and simple, include all dates from start
        # date through end date; exclude end date if end is exactly midnight and > start date.
        days.add(cur)
        cur = cur.fromordinal(cur.toordinal() + 1)
    # Remove the end date if the window ends exactly at 00:00:00 of that date
    # (half-open: that instant is not occupied) and the window spans >0 into prior day.
    if end.time() == datetime.min.time() and end.date() > start.date():
        days.discard(end.date())
    return days


# ---------------------------------------------------------------------------
# Create assignment (OCC on job.version, supersede, segregation, window, qual)
# ---------------------------------------------------------------------------
@bp.route("/assignments", methods=["POST"])
def create_assignment():
    _uid, role = get_user_context()
    require_role(role, {"ProjectManager"})
    body = get_json_body()
    require_fields(body, ["job_id", "linguist_id", "role",
                          "window_start", "window_end", "expected_job_version"])

    new_role = body["role"]
    if new_role not in ROLES:
        raise err("ERR_INVALID_REQUEST", "role must be TRANSLATOR or REVIEWER")
    expected_version = body["expected_job_version"]
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise err("ERR_INVALID_REQUEST", "expected_job_version must be an integer")

    # existence: job before linguist (left-to-right / path then body FK order)
    job = get_job(body["job_id"])
    linguist = get_linguist(body["linguist_id"])

    ws = _parse_dt(body["window_start"], "window_start")
    we = _parse_dt(body["window_end"], "window_end")
    if not (we > ws):
        raise err("ERR_INVALID_REQUEST", "window_end must be after window_start")

    project = db.projects.get(job["project_id"])

    # priority 6: segregation (REVIEWER cannot be the job's active translator)
    if new_role == "REVIEWER":
        translator = active_translator_assignment(job["id"])
        if translator is not None and translator["linguist_id"] == linguist["id"]:
            raise err("ERR_SEGREGATION_VIOLATION",
                      "Reviewer cannot be the job's active translator")

    # priority 7: qualification + active
    if (linguist["status"] != "ACTIVE"
            or not _linguist_qualified(linguist,
                                       project["source_locale"], project["target_locale"])):
        raise err("ERR_LINGUIST_NOT_QUALIFIED",
                  "Linguist is not qualified/active for this locale pair")

    # priority 10: OCC stale job version
    if expected_version != job["version"]:
        raise err("ERR_STALE_VERSION", "expected_job_version does not match job version")

    # priority 12 (business tier): REVIEWER window must not overlap active translator window
    if new_role == "REVIEWER":
        translator = active_translator_assignment(job["id"])
        if translator is not None:
            tws = _parse_dt(translator["window_start"], "window_start")
            twe = _parse_dt(translator["window_end"], "window_end")
            if _intervals_overlap(ws, we, tws, twe):
                raise err("ERR_WINDOW_OVERLAP",
                          "Reviewer window overlaps the active translator window")

    # Side effect: supersede any prior non-terminal assignment of the same role
    for a in assignments_of_job(job["id"]):
        if a["role"] == new_role and a["status"] in NON_TERMINAL:
            _supersede(a)

    a = common_fields()
    a.update({
        "job_id": job["id"],
        "linguist_id": linguist["id"],
        "role": new_role,
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "payout_cents": 0,
        "payout_finalized": False,
        "expected_job_version": expected_version,
        "status": "OFFERED",
    })
    db.assignments[a["id"]] = a

    # increments job.version by 1
    touch(job)

    return success_object(assignment_out(a), 201)


def _supersede(assignment):
    """Move a non-terminal assignment to SUPERSEDED; revert commitment if accepted/in-progress."""
    if assignment["status"] in ("ACCEPTED", "IN_PROGRESS"):
        linguist = db.linguists.get(assignment["linguist_id"])
        if linguist is not None:
            append_ledger_entry(linguist, assignment["id"], "REVERSAL",
                                -assignment["payout_cents"], "superseded by replacement")
    assignment["status"] = "SUPERSEDED"
    touch(assignment)


@bp.route("/assignments/<aid>", methods=["GET"])
def get_assignment_route(aid):
    uid, role = get_user_context()
    require_role(role, {"ProjectManager", "Translator", "Reviewer"})
    a = get_assignment(aid)
    if role in ("Translator", "Reviewer") and uid != a["linguist_id"]:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Linguist may only read its own assignment")
    return success_object(assignment_out(a), 200)


# ---------------------------------------------------------------------------
# Accept (OFFERED -> ACCEPTED) PRD §3.5
# ---------------------------------------------------------------------------
@bp.route("/assignments/<aid>/accept", methods=["POST"])
def accept_assignment(aid):
    uid, role = get_user_context()
    require_role(role, {"Translator", "Reviewer"})
    a = get_assignment(aid)
    if uid != a["linguist_id"]:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Linguist may only accept its own assignment")
    if a["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "Assignment must be OFFERED to accept")

    linguist = db.linguists.get(a["linguist_id"])
    if linguist["status"] != "ACTIVE":
        raise err("ERR_LINGUIST_INACTIVE", "Inactive linguist cannot accept assignments")

    job = db.jobs.get(a["job_id"])
    project = db.projects.get(job["project_id"])
    if project["status"] not in ("APPROVED", "IN_PRODUCTION"):
        raise err("ERR_PROJECT_NOT_APPROVED", "Project must be APPROVED or IN_PRODUCTION")

    # compute the provisional payout for this assignment's job (TRANSLATOR metered;
    # reviewer carries 0).
    if a["role"] == "TRANSLATOR":
        this_weighted = float(calc.job_weighted_words(job, "quoted"))
        payout = calc.linguist_payout_provisional(
            job, project["pinned_linguist_rate_cents_per_word"])
    else:
        this_weighted = float(calc.job_weighted_words(job, "quoted"))
        payout = 0

    # priority 9: throughput capacity check (per shared UTC day)
    _check_throughput(linguist, a, this_weighted)

    # accept
    a["status"] = "ACCEPTED"
    a["payout_cents"] = payout
    touch(a)

    # ledger COMMIT (+payout) and reconcile committed_payout_cents
    append_ledger_entry(linguist, a["id"], "COMMIT", payout, "assignment accepted")

    # IN_PROGRESS automatic
    a["status"] = "IN_PROGRESS"
    touch(a)

    # TRANSLATOR: drive job PENDING->TRANSLATING and project APPROVED->IN_PRODUCTION
    if a["role"] == "TRANSLATOR":
        if job["status"] == "PENDING":
            job["status"] = "TRANSLATING"
            touch(job)  # increments version
        if project["status"] == "APPROVED":
            project["status"] = "IN_PRODUCTION"
            touch(project)

    return success_object(assignment_out(a), 200)


def _weighted_words_for_assignment(assignment):
    job = db.jobs.get(assignment["job_id"])
    if job is None:
        return 0.0
    return float(calc.job_weighted_words(job, "quoted"))


def _window_days_for_assignment(assignment):
    ws = _parse_dt(assignment["window_start"], "window_start")
    we = _parse_dt(assignment["window_end"], "window_end")
    return _shared_utc_days(ws, we), ws, we


def _check_throughput(linguist, new_assignment, new_weighted):
    """Sum existing committed weighted words across overlapping ACCEPTED/IN_PROGRESS
    windows that share a UTC day with the new window; reject if any shared day exceeds cap."""
    cap = linguist["daily_throughput_words"]
    new_days, nws, nwe = _window_days_for_assignment(new_assignment)

    # For each UTC day touched by the new window, sum the weighted words of the
    # linguist's other active assignments whose window touches that same day.
    existing = [a for a in db.assignments.values()
                if a["linguist_id"] == linguist["id"]
                and a["id"] != new_assignment["id"]
                and a["status"] in ("ACCEPTED", "IN_PROGRESS")]

    for day in new_days:
        committed = 0.0
        for a in existing:
            a_days, _aws, _awe = _window_days_for_assignment(a)
            if day in a_days:
                committed += _weighted_words_for_assignment(a)
        if committed + new_weighted > cap:
            raise err("ERR_THROUGHPUT_EXCEEDED",
                      "Accepting would exceed the linguist's daily throughput cap")


# ---------------------------------------------------------------------------
# Decline (OFFERED -> DECLINED) PRD §3.5
# ---------------------------------------------------------------------------
@bp.route("/assignments/<aid>/decline", methods=["POST"])
def decline_assignment(aid):
    uid, role = get_user_context()
    require_role(role, {"Translator", "Reviewer"})
    a = get_assignment(aid)
    if uid != a["linguist_id"]:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Linguist may only decline its own assignment")
    if a["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "Assignment must be OFFERED to decline")
    a["status"] = "DECLINED"
    touch(a)
    return success_object(assignment_out(a), 200)


# ---------------------------------------------------------------------------
# Assignment sub-lists
# ---------------------------------------------------------------------------
@bp.route("/assignments/<aid>/payout-ledger", methods=["GET"])
def list_assignment_ledger(aid):
    uid, role = get_user_context()
    require_role(role, {"ProjectManager", "Translator", "Reviewer"})
    a = get_assignment(aid)
    if role in ("Translator", "Reviewer") and uid != a["linguist_id"]:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Linguist may only read its own assignment ledger")
    items = [e for e in db.payout_ledger.values() if e["assignment_id"] == aid]
    return paginate_and_respond(items, payout_ledger_out)


@bp.route("/assignments/<aid>/qa-reports", methods=["GET"])
def list_assignment_qa_reports(aid):
    uid, role = get_user_context()
    require_role(role, {"ProjectManager", "Reviewer"})
    a = get_assignment(aid)
    if role == "Reviewer" and uid != a["linguist_id"]:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Reviewer may only read its own assignment QA reports")
    items = [q for q in db.qa_reports.values() if q["reviewer_assignment_id"] == aid]
    return paginate_and_respond(items, qa_report_out)
