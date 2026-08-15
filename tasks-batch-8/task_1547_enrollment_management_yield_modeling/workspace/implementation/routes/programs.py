"""Program endpoints."""
from flask import Blueprint, request

from db import store, new_id, now_iso
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_TARGET_EXCEEDS_CAPACITY,
    ERR_BUDGET_BELOW_COMMITTED, ERR_STALE_VERSION,
)
from middleware import require_roles
from response import success_object, success_list
from services.derived import recompute_program
from services.serializers import serialize_program, touch

bp = Blueprint("programs", __name__, url_prefix="/enrollment/programs")


def _get_program_or_404(pid):
    p = store.programs.get(pid)
    if not p:
        raise ApiError(ERR_NOT_FOUND, 404, "Program not found")
    return p


@bp.route("", methods=["POST"])
def create_program():
    require_roles("EnrollmentManager")
    body = request.get_json(silent=True) or {}
    cycle_id = body.get("cycle_id")
    name = body.get("name")
    capacity = body.get("capacity_seats")
    target = body.get("target_enrollment")
    tuition = body.get("tuition_cents")
    budget = body.get("scholarship_budget_cents")
    deposit_amt = body.get("deposit_amount_cents")
    auto_wl = body.get("auto_waitlist_activation", False)

    if cycle_id is None or cycle_id not in store.cycles:
        raise ApiError(ERR_NOT_FOUND, 404, "cycle_id not found")
    for v, n in [(name, "name"), (capacity, "capacity_seats"),
                 (target, "target_enrollment"), (tuition, "tuition_cents"),
                 (budget, "scholarship_budget_cents"),
                 (deposit_amt, "deposit_amount_cents")]:
        if v is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{n} required")
    if not isinstance(target, int) or not isinstance(capacity, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, "target/capacity must be integers")
    if target > capacity:
        raise ApiError(ERR_TARGET_EXCEEDS_CAPACITY, 422,
                       "target_enrollment exceeds capacity_seats")

    now = now_iso()
    program = {
        "id": new_id(),
        "cycle_id": cycle_id,
        "name": name,
        "capacity_seats": capacity,
        "target_enrollment": target,
        "tuition_cents": tuition,
        "scholarship_budget_cents": budget,
        "deposit_amount_cents": deposit_amt,
        "auto_waitlist_activation": bool(auto_wl),
        "admitted_count": 0,
        "deposited_count": 0,
        "enrolled_count": 0,
        "seats_open": capacity,
        "scholarship_committed_cents": 0,
        "scholarship_available_cents": budget,
        "intake_posture": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    recompute_program(program)
    store.programs[program["id"]] = program
    return success_object(serialize_program(program), status=201)


@bp.route("/<programId>", methods=["GET"])
def get_program(programId):
    require_roles("SystemAdmin", "EnrollmentManager", "AdmissionsOfficer", "FinancialAidOfficer")
    p = _get_program_or_404(programId)
    recompute_program(p)
    return success_object(serialize_program(p))


@bp.route("", methods=["GET"])
def list_programs():
    require_roles("SystemAdmin", "EnrollmentManager", "AdmissionsOfficer", "FinancialAidOfficer")
    cycle_id = request.args.get("cycle_id")
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    items = [p for p in store.programs.values()]
    if cycle_id:
        items = [p for p in items if p["cycle_id"] == cycle_id]
    for p in items:
        recompute_program(p)
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_program(p) for p in page], limit, offset, total)


@bp.route("/<programId>", methods=["PATCH"])
def patch_program(programId):
    require_roles("EnrollmentManager")
    p = _get_program_or_404(programId)
    body = request.get_json(silent=True) or {}

    expected = body.get("expected_program_version")
    if expected is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_program_version required")
    if expected != p["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       f"expected_program_version {expected} != current {p['version']}")

    new_capacity = body.get("capacity_seats", p["capacity_seats"])
    new_target = body.get("target_enrollment", p["target_enrollment"])
    new_budget = body.get("scholarship_budget_cents", p["scholarship_budget_cents"])
    new_auto = body.get("auto_waitlist_activation", p["auto_waitlist_activation"])

    # Compute committed from current state
    recompute_program(p)
    if new_target > new_capacity:
        raise ApiError(ERR_TARGET_EXCEEDS_CAPACITY, 422,
                       "target_enrollment exceeds capacity_seats")
    if new_budget < p["scholarship_committed_cents"]:
        raise ApiError(ERR_BUDGET_BELOW_COMMITTED, 409,
                       "scholarship_budget_cents below committed")

    p["capacity_seats"] = new_capacity
    p["target_enrollment"] = new_target
    p["scholarship_budget_cents"] = new_budget
    p["auto_waitlist_activation"] = bool(new_auto)
    recompute_program(p)
    touch(p)
    return success_object(serialize_program(p))
