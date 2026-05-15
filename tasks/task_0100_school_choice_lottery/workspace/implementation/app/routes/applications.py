"""Application endpoints — CRUD + submit / accept / decline / withdraw."""
from datetime import timedelta

from flask import Blueprint, g, jsonify, request

from ..auth import require_auth
from ..calculations import (MAX_CHOICES_PER_STUDENT, OFFER_RESPONSE_HOURS,
                            WITHDRAW_GRACE_DAYS, classify_priority_category,
                            compute_lottery_weight)
from ..clock import clock_now_dt, format_iso, parse_iso
from ..errors import APIError
from ..occ import check_version
from ..responses import list_response, success_response
from ..services.family import (recompute_head_household_application_id,
                               set_anchor_if_unset)
from ..services.lookups import (fk_program, fk_student, get_application_or_404,
                                get_family_or_404)
from ..services.sweeps import recompute_seats, waitlist_backfill
from ..store import get_lock, get_store, stamp_create, stamp_update
from ..validators import (get_json_body, paginate, parse_pagination,
                          require_integer, require_string)


bp = Blueprint("applications", __name__, url_prefix="/enrollment/applications")


VALID_APP_STATUS = {"DRAFT", "SUBMITTED", "OFFERED", "ACCEPTED",
                    "DECLINED", "WAITLISTED", "EXPIRED", "WITHDRAWN"}


def _serialize(a: dict) -> dict:
    return {
        "id": a["id"],
        "student_id": a["student_id"],
        "program_id": a["program_id"],
        "choice_rank": a["choice_rank"],
        "status": a["status"],
        "priority_category": a.get("priority_category"),
        "lottery_weight": a.get("lottery_weight"),
        "lottery_score": a.get("lottery_score"),
        "waitlist_position": a.get("waitlist_position"),
        "offer_expires_at": a.get("offer_expires_at"),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def _student_owner_check(student):
    """For FamilyUser, ownership check based on student.family_id."""
    if g.user_role == "FamilyUser" and g.user_id != student["family_id"]:
        raise APIError("ERR_FORBIDDEN", "FamilyUser may only act on their own family's students")


def _student_active_apps(student_id: str) -> list:
    return [a for a in get_store().applications.values()
            if a["student_id"] == student_id and a["status"] in ("DRAFT", "SUBMITTED")]


def _anchor_district_id(family: dict):
    """Return the district_id of the family's anchor application's program-school, else None."""
    anchor_id = family.get("head_household_application_id")
    if anchor_id is None:
        return None
    store = get_store()
    anchor_app = store.applications.get(anchor_id)
    if anchor_app is None:
        return None
    program = store.programs.get(anchor_app["program_id"])
    if program is None:
        return None
    school = store.schools.get(program["school_id"])
    if school is None:
        return None
    return school["district_id"]


# ---------------------------------------------------------------------------
# Create / List / Read
# ---------------------------------------------------------------------------

@bp.route("", methods=["POST"])
@require_auth("FamilyUser")
def create_application():
    body = get_json_body()
    student_id = require_string(body, "student_id")
    program_id = require_string(body, "program_id")
    choice_rank = require_integer(body, "choice_rank", minimum=1, maximum=5)

    with get_lock():
        student = fk_student(student_id)
        program = fk_program(program_id)
        _student_owner_check(student)

        # ERR_GRADE_MISMATCH
        if student["grade_level_next_year"] != program["grade_level"]:
            raise APIError("ERR_GRADE_MISMATCH",
                           "student grade_level_next_year != program.grade_level")

        # ERR_DUPLICATE_CHOICE_RANK across DRAFT/SUBMITTED
        for a in get_store().applications.values():
            if (a["student_id"] == student_id
                    and a["status"] in ("DRAFT", "SUBMITTED")
                    and a["choice_rank"] == choice_rank):
                raise APIError("ERR_DUPLICATE_CHOICE_RANK",
                               "another DRAFT/SUBMITTED application by this student already uses this choice_rank")

        # ERR_TOO_MANY_CHOICES
        if len(_student_active_apps(student_id)) >= MAX_CHOICES_PER_STUDENT:
            raise APIError("ERR_TOO_MANY_CHOICES",
                           f"student already has {MAX_CHOICES_PER_STUDENT} active applications")

        record = {
            "student_id": student_id,
            "program_id": program_id,
            "choice_rank": choice_rank,
            "status": "DRAFT",
            "priority_category": None,
            "lottery_weight": None,
            "lottery_score": None,
            "waitlist_position": None,
            "offer_expires_at": None,
        }
        stamp_create(record)
        get_store().applications[record["id"]] = record
        resp, code = success_response(_serialize(record), status=201, response_type="object")
    return jsonify(resp), code


@bp.route("", methods=["GET"])
@require_auth("FamilyUser", "DistrictAdmin", "SystemOperator")
def list_applications():
    limit, offset = parse_pagination()
    student_id = request.args.get("student_id")
    program_id = request.args.get("program_id")
    status_filter = request.args.get("status")
    family_id = request.args.get("family_id")

    if status_filter is not None and status_filter not in VALID_APP_STATUS:
        raise APIError("ERR_VALIDATION", "invalid status filter")

    store = get_store()
    items = []
    for a in store.applications.values():
        if student_id is not None and a["student_id"] != student_id:
            continue
        if program_id is not None and a["program_id"] != program_id:
            continue
        if status_filter is not None and a["status"] != status_filter:
            continue
        if family_id is not None:
            s = store.students.get(a["student_id"])
            if s is None or s["family_id"] != family_id:
                continue
        # FamilyUser may only see their own family's applications
        if g.user_role == "FamilyUser":
            s = store.students.get(a["student_id"])
            if s is None or s["family_id"] != g.user_id:
                continue
        items.append(a)
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, total = paginate(items, limit, offset)
    resp, code = list_response([_serialize(x) for x in page], total, limit, offset)
    return jsonify(resp), code


@bp.route("/<application_id>", methods=["GET"])
@require_auth("FamilyUser", "DistrictAdmin", "SystemOperator")
def get_application(application_id):
    rec = get_application_or_404(application_id)
    if g.user_role == "FamilyUser":
        student = get_store().students.get(rec["student_id"])
        if student is None or student["family_id"] != g.user_id:
            raise APIError("ERR_FORBIDDEN", "FamilyUser may only read their own family's applications")
    resp, code = success_response(_serialize(rec), status=200, response_type="object")
    return jsonify(resp), code


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

@bp.route("/<application_id>/submit", methods=["POST"])
@require_auth("FamilyUser")
def submit_application(application_id):
    body = get_json_body()
    with get_lock():
        app = get_application_or_404(application_id)
        store = get_store()
        student = store.students[app["student_id"]]
        _student_owner_check(student)
        check_version(app, body)

        program = store.programs[app["program_id"]]
        # PRD §3.4: "Submission requires the program's window_status to be
        # OPEN; outside of that window the request is rejected with
        # ERR_REGISTRATION_WINDOW_CLOSED." This error is keyed to the window
        # condition, so we evaluate it before the generic DRAFT precondition;
        # otherwise the §2.10 auto-WITHDRAWN cascade would mask it.
        if program["window_status"] != "OPEN":
            raise APIError("ERR_REGISTRATION_WINDOW_CLOSED",
                           f"program window_status is {program['window_status']}; submit requires OPEN")

        if app["status"] != "DRAFT":
            raise APIError("ERR_INVALID_STATE_FOR_TRANSITION",
                           f"submit requires DRAFT; current status is {app['status']}")

        # Grade re-check
        if student["grade_level_next_year"] != program["grade_level"]:
            raise APIError("ERR_GRADE_MISMATCH",
                           "student grade_level_next_year != program.grade_level")

        # Duplicate choice_rank re-check across DRAFT/SUBMITTED (other than self)
        for a in store.applications.values():
            if a["id"] == app["id"]:
                continue
            if (a["student_id"] == student["id"]
                    and a["status"] in ("DRAFT", "SUBMITTED")
                    and a["choice_rank"] == app["choice_rank"]):
                raise APIError("ERR_DUPLICATE_CHOICE_RANK",
                               "another DRAFT/SUBMITTED application uses this choice_rank")

        # Too many choices re-check (self counts as DRAFT; transition will keep it active)
        active_others = [a for a in store.applications.values()
                         if a["student_id"] == student["id"]
                         and a["id"] != app["id"]
                         and a["status"] in ("DRAFT", "SUBMITTED")]
        if len(active_others) >= MAX_CHOICES_PER_STUDENT:
            raise APIError("ERR_TOO_MANY_CHOICES",
                           f"student already has {MAX_CHOICES_PER_STUDENT} active applications")

        family = store.families[student["family_id"]]
        school = store.schools[program["school_id"]]
        district = store.districts[school["district_id"]]

        crosses = (school["district_id"] != family["residency_district_id"])
        if crosses:
            # Need an APPROVED TransferRequest linked to this application
            ok = False
            for tr in store.transfer_requests.values():
                if (tr["application_id"] == app["id"]
                        and tr["target_district_id"] == school["district_id"]
                        and tr["status"] == "APPROVED"):
                    ok = True
                    break
            if not ok:
                raise APIError("ERR_TRANSFER_NOT_APPROVED",
                               "cross-district application requires an APPROVED TransferRequest")

        # Compute priority_category and lottery_weight
        anchor_district = _anchor_district_id(family)
        category = classify_priority_category(family, program, school, district, anchor_district)
        weight = compute_lottery_weight(category, family, district, app["choice_rank"])

        app["status"] = "SUBMITTED"
        app["priority_category"] = category
        app["lottery_weight"] = weight
        stamp_update(app)

        resp, code = success_response(_serialize(app), status=200, response_type="object")
    return jsonify(resp), code


# ---------------------------------------------------------------------------
# Accept
# ---------------------------------------------------------------------------

@bp.route("/<application_id>/accept", methods=["POST"])
@require_auth("FamilyUser")
def accept_application(application_id):
    body = get_json_body()
    with get_lock():
        app = get_application_or_404(application_id)
        store = get_store()
        student = store.students[app["student_id"]]
        _student_owner_check(student)
        check_version(app, body)

        # PRD §2.11 concurrency rule (first-writer-wins on Application.status
        # keyed by student_id): if another ACCEPTED application by this same
        # student already exists, the loser of the race sees
        # ERR_STUDENT_ALREADY_ACCEPTED, even though the winner's cascade has
        # by now flipped this losing app from OFFERED to WITHDRAWN. So this
        # check must run BEFORE the generic OFFERED-status precondition.
        for a in store.applications.values():
            if (a["student_id"] == student["id"]
                    and a["id"] != app["id"]
                    and a["status"] == "ACCEPTED"):
                raise APIError("ERR_STUDENT_ALREADY_ACCEPTED",
                               "student already has an ACCEPTED application")

        if app["status"] != "OFFERED":
            raise APIError("ERR_INVALID_STATE_FOR_TRANSITION",
                           f"accept requires OFFERED; current status is {app['status']}")

        # offer expiry temporal check (priority 14)
        if app.get("offer_expires_at"):
            exp_dt = parse_iso(app["offer_expires_at"])
            if clock_now_dt() >= exp_dt:
                raise APIError("ERR_OFFER_EXPIRED",
                               "offer_expires_at has passed")

        # Seat availability: this application is already counted as OFFERED, so transitioning
        # to ACCEPTED does not change the (OFFERED + ACCEPTED) total. No new seat needed.

        program = store.programs[app["program_id"]]
        app["status"] = "ACCEPTED"
        app["offer_expires_at"] = None
        stamp_update(app)

        # Recompute counters
        recompute_seats(program)

        # Set sibling anchor if unset
        family = store.families[student["family_id"]]
        set_anchor_if_unset(family["id"], app["id"])

        # Cascade: every OTHER OFFERED application by the same student -> WITHDRAWN,
        # and run waitlist_backfill on each such program.
        other_offered = [a for a in store.applications.values()
                         if a["student_id"] == student["id"]
                         and a["id"] != app["id"]
                         and a["status"] == "OFFERED"]
        other_offered.sort(key=lambda a: (a["created_at"], a["id"]))
        for other in other_offered:
            other["status"] = "WITHDRAWN"
            other["offer_expires_at"] = None
            stamp_update(other)
            other_program = store.programs[other["program_id"]]
            recompute_seats(other_program)
            waitlist_backfill(other_program["id"], triggered_by_app_id=other["id"])

        resp, code = success_response(_serialize(app), status=200, response_type="object")
    return jsonify(resp), code


# ---------------------------------------------------------------------------
# Decline
# ---------------------------------------------------------------------------

@bp.route("/<application_id>/decline", methods=["POST"])
@require_auth("FamilyUser")
def decline_application(application_id):
    body = get_json_body()
    with get_lock():
        app = get_application_or_404(application_id)
        store = get_store()
        student = store.students[app["student_id"]]
        _student_owner_check(student)
        check_version(app, body)

        if app["status"] != "OFFERED":
            raise APIError("ERR_INVALID_STATE_FOR_TRANSITION",
                           f"decline requires OFFERED; current status is {app['status']}")

        if app.get("offer_expires_at"):
            exp_dt = parse_iso(app["offer_expires_at"])
            if clock_now_dt() >= exp_dt:
                raise APIError("ERR_OFFER_EXPIRED",
                               "offer_expires_at has passed")

        program = store.programs[app["program_id"]]
        app["status"] = "DECLINED"
        app["offer_expires_at"] = None
        stamp_update(app)
        recompute_seats(program)
        waitlist_backfill(program["id"], triggered_by_app_id=app["id"])

        resp, code = success_response(_serialize(app), status=200, response_type="object")
    return jsonify(resp), code


# ---------------------------------------------------------------------------
# Withdraw (from ACCEPTED)
# ---------------------------------------------------------------------------

@bp.route("/<application_id>/withdraw", methods=["POST"])
@require_auth("FamilyUser")
def withdraw_application(application_id):
    body = get_json_body()
    with get_lock():
        app = get_application_or_404(application_id)
        store = get_store()
        student = store.students[app["student_id"]]
        _student_owner_check(student)
        check_version(app, body)

        if app["status"] != "ACCEPTED":
            raise APIError("ERR_INVALID_STATE_FOR_TRANSITION",
                           f"withdraw requires ACCEPTED; current status is {app['status']}")

        program = store.programs[app["program_id"]]
        # Find LotteryRun for this program
        lr = next((r for r in store.lottery_runs.values() if r["program_id"] == program["id"]), None)
        if lr is None:
            raise APIError("ERR_INVALID_STATE_FOR_TRANSITION",
                           "no LotteryRun found for program; cannot evaluate withdraw grace")
        drawn_at = parse_iso(lr["drawn_at"])
        if clock_now_dt() >= drawn_at + timedelta(days=WITHDRAW_GRACE_DAYS):
            raise APIError("ERR_WITHDRAW_GRACE_PASSED",
                           "withdraw grace window has passed")

        family = store.families[student["family_id"]]
        was_anchor = (family.get("head_household_application_id") == app["id"])

        app["status"] = "WITHDRAWN"
        stamp_update(app)
        recompute_seats(program)

        if was_anchor:
            recompute_head_household_application_id(family["id"])

        waitlist_backfill(program["id"], triggered_by_app_id=app["id"])

        resp, code = success_response(_serialize(app), status=200, response_type="object")
    return jsonify(resp), code
