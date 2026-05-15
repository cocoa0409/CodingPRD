"""Program endpoints + lottery draw."""
from flask import Blueprint, g, jsonify, request

from ..auth import require_auth
from ..clock import parse_iso
from ..errors import APIError
from ..occ import check_version
from ..responses import list_response, success_response
from ..services.lookups import (fk_school, get_program_or_404,
                                get_school_or_404)
from ..services.lottery import run_lottery_draw
from ..services.sweeps import recompute_seats
from ..store import get_lock, get_store, stamp_create, stamp_update
from ..validators import (get_json_body, optional_field, paginate,
                          parse_pagination, require_integer, require_string)


bp = Blueprint("programs", __name__, url_prefix="/enrollment/programs")

VALID_WINDOW_STATUS = {"SCHEDULED", "OPEN", "CLOSED", "LOTTERY_DRAWN", "BACKFILL"}


def _serialize(p: dict) -> dict:
    return {
        "id": p["id"],
        "school_id": p["school_id"],
        "grade_level": p["grade_level"],
        "academic_year": p["academic_year"],
        "seats_total": p["seats_total"],
        "seats_offered": p["seats_offered"],
        "seats_accepted": p["seats_accepted"],
        "registration_open_at": p["registration_open_at"],
        "registration_close_at": p["registration_close_at"],
        "lottery_seed": p.get("lottery_seed"),
        "window_status": p["window_status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.route("", methods=["POST"])
@require_auth("DistrictAdmin")
def create_program():
    body = get_json_body()
    school_id = require_string(body, "school_id")
    grade_level = require_integer(body, "grade_level", minimum=0, maximum=12)
    academic_year = require_integer(body, "academic_year", minimum=2025)
    # PRD §3.1: seats_total must be a positive integer; non-positive at
    # creation triggers ERR_SEATS_BELOW_COMMITTED (same rule that fires when a
    # reduction drops seats_total below seats_accepted).
    seats_total = require_integer(body, "seats_total")
    if seats_total <= 0:
        raise APIError("ERR_SEATS_BELOW_COMMITTED",
                       "seats_total must be a positive integer")
    open_at = require_string(body, "registration_open_at")
    close_at = require_string(body, "registration_close_at")
    lottery_seed = optional_field(body, "lottery_seed", None)

    open_dt = parse_iso(open_at)
    close_dt = parse_iso(close_at)
    if not (close_dt > open_dt):
        raise APIError("ERR_VALIDATION", "registration_close_at must be strictly after registration_open_at")

    if lottery_seed is not None:
        if not isinstance(lottery_seed, str) or not (1 <= len(lottery_seed) <= 64):
            raise APIError("ERR_VALIDATION", "lottery_seed must be a string of 1-64 chars")

    with get_lock():
        school = fk_school(school_id)
        # DistrictAdmin ownership: school must belong to the admin's district
        if g.user_id != school["district_id"]:
            raise APIError("ERR_FORBIDDEN", "DistrictAdmin may only create programs in their own district's schools")
        # ERR_GRADE_NOT_OFFERED
        if grade_level not in school["grade_levels_offered"]:
            raise APIError("ERR_GRADE_NOT_OFFERED",
                           f"grade_level {grade_level} not in school.grade_levels_offered")
        record = {
            "school_id": school_id,
            "grade_level": grade_level,
            "academic_year": academic_year,
            "seats_total": seats_total,
            "seats_offered": 0,
            "seats_accepted": 0,
            "registration_open_at": open_at,
            "registration_close_at": close_at,
            "lottery_seed": lottery_seed,
            "window_status": "SCHEDULED",
        }
        stamp_create(record)
        get_store().programs[record["id"]] = record
        resp, status = success_response(_serialize(record), status=201, response_type="object")
    return jsonify(resp), status


@bp.route("", methods=["GET"])
@require_auth("SystemOperator", "DistrictAdmin", "FamilyUser")
def list_programs():
    limit, offset = parse_pagination()
    school_id = request.args.get("school_id")
    district_id = request.args.get("district_id")
    window_status = request.args.get("window_status")
    grade_level_s = request.args.get("grade_level")
    if window_status is not None and window_status not in VALID_WINDOW_STATUS:
        raise APIError("ERR_VALIDATION", "invalid window_status filter")
    grade_level = None
    if grade_level_s is not None:
        try:
            grade_level = int(grade_level_s)
        except ValueError:
            raise APIError("ERR_VALIDATION", "grade_level must be an integer")

    store = get_store()
    out = []
    for p in store.programs.values():
        if school_id is not None and p["school_id"] != school_id:
            continue
        if district_id is not None:
            s = store.schools.get(p["school_id"])
            if s is None or s["district_id"] != district_id:
                continue
        if window_status is not None and p["window_status"] != window_status:
            continue
        if grade_level is not None and p["grade_level"] != grade_level:
            continue
        out.append(p)
    out.sort(key=lambda p: (p["created_at"], p["id"]))
    page, total = paginate(out, limit, offset)
    resp, status = list_response([_serialize(x) for x in page], total, limit, offset)
    return jsonify(resp), status


@bp.route("/<program_id>", methods=["GET"])
@require_auth("SystemOperator", "DistrictAdmin", "FamilyUser")
def get_program(program_id):
    rec = get_program_or_404(program_id)
    resp, status = success_response(_serialize(rec), status=200, response_type="object")
    return jsonify(resp), status


@bp.route("/<program_id>", methods=["PATCH"])
@require_auth("DistrictAdmin")
def patch_program(program_id):
    body = get_json_body()
    with get_lock():
        rec = get_program_or_404(program_id)
        # Ownership
        school = get_store().schools.get(rec["school_id"])
        if school is None or g.user_id != school["district_id"]:
            raise APIError("ERR_FORBIDDEN", "DistrictAdmin may only update programs in their own district")
        check_version(rec, body)

        if rec["window_status"] not in ("SCHEDULED", "OPEN", "CLOSED"):
            raise APIError("ERR_INVALID_STATE_FOR_TRANSITION",
                           "program may only be updated while window_status is SCHEDULED/OPEN/CLOSED")

        new_seats = None
        if "seats_total" in body and body["seats_total"] is not None:
            new_seats = require_integer(body, "seats_total")
            # PRD §3.1: a reduction below committed (or a non-positive integer)
            # raises ERR_SEATS_BELOW_COMMITTED.
            if new_seats <= 0 or new_seats < rec["seats_accepted"]:
                raise APIError("ERR_SEATS_BELOW_COMMITTED",
                               "seats_total cannot drop below seats_accepted")

        new_seed = None
        if "lottery_seed" in body and body["lottery_seed"] is not None:
            seed = body["lottery_seed"]
            if not isinstance(seed, str) or not (1 <= len(seed) <= 64):
                raise APIError("ERR_VALIDATION", "lottery_seed must be a string of 1-64 chars")
            new_seed = seed

        new_close = None
        if "registration_close_at" in body and body["registration_close_at"] is not None:
            close_s = body["registration_close_at"]
            if not isinstance(close_s, str):
                raise APIError("ERR_VALIDATION", "registration_close_at must be a string")
            close_dt = parse_iso(close_s)
            open_dt = parse_iso(rec["registration_open_at"])
            if not (close_dt > open_dt):
                raise APIError("ERR_VALIDATION", "registration_close_at must be strictly after registration_open_at")
            new_close = close_s

        if new_seats is not None:
            rec["seats_total"] = new_seats
        if new_seed is not None:
            rec["lottery_seed"] = new_seed
        if new_close is not None:
            rec["registration_close_at"] = new_close
        stamp_update(rec)
        resp, status = success_response(_serialize(rec), status=200, response_type="object")
    return jsonify(resp), status


@bp.route("/<program_id>/lottery/draw", methods=["POST"])
@require_auth("DistrictAdmin")
def lottery_draw(program_id):
    with get_lock():
        rec = get_program_or_404(program_id)
        school = get_store().schools.get(rec["school_id"])
        if school is None or g.user_id != school["district_id"]:
            raise APIError("ERR_FORBIDDEN", "only the owning district may run a program's lottery")

        # Priority 8 vs 10: SCHEDULED/OPEN -> ERR_LOTTERY_NOT_READY,
        # LOTTERY_DRAWN/BACKFILL -> ERR_LOTTERY_ALREADY_DRAWN
        status = rec["window_status"]
        if status in ("SCHEDULED", "OPEN"):
            raise APIError("ERR_LOTTERY_NOT_READY",
                           f"program is in {status}; lottery requires CLOSED")
        if status in ("LOTTERY_DRAWN", "BACKFILL"):
            raise APIError("ERR_LOTTERY_ALREADY_DRAWN",
                           f"program already in {status}")
        if status != "CLOSED":
            raise APIError("ERR_LOTTERY_NOT_READY",
                           f"program is in {status}; lottery requires CLOSED")

        if not rec.get("lottery_seed"):
            raise APIError("ERR_LOTTERY_SEED_MISSING", "lottery_seed is required to draw")

        # At least one SUBMITTED application
        store = get_store()
        has_submitted = any(a for a in store.applications.values()
                            if a["program_id"] == rec["id"] and a["status"] == "SUBMITTED")
        if not has_submitted:
            raise APIError("ERR_INVALID_STATE_FOR_TRANSITION",
                           "no SUBMITTED applications to draw")

        lr = run_lottery_draw(rec)

        # Serialize the lottery run
        out = {
            "id": lr["id"],
            "program_id": lr["program_id"],
            "seed_used": lr["seed_used"],
            "drawn_at": lr["drawn_at"],
            "applications_ranked": lr["applications_ranked"],
            "offers_issued_count": lr["offers_issued_count"],
            "created_at": lr["created_at"],
        }
        resp, code = success_response(out, status=200, response_type="object")
    return jsonify(resp), code


@bp.route("/<program_id>/waitlist-events", methods=["GET"])
@require_auth("DistrictAdmin", "SystemOperator")
def list_waitlist_events(program_id):
    limit, offset = parse_pagination()
    get_program_or_404(program_id)
    items = [w for w in get_store().waitlist_events.values() if w["program_id"] == program_id]
    items.sort(key=lambda w: (w["occurred_at"], w["id"]))
    page, total = paginate(items, limit, offset)
    out = [{
        "id": w["id"],
        "program_id": w["program_id"],
        "triggered_by_application_id": w["triggered_by_application_id"],
        "promoted_application_id": w["promoted_application_id"],
        "occurred_at": w["occurred_at"],
        "created_at": w["created_at"],
    } for w in page]
    resp, code = list_response(out, total, limit, offset)
    return jsonify(resp), code
