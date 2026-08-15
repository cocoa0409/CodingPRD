"""Deposit endpoints."""
from flask import Blueprint, request

from db import store, clock, new_id, now_iso, _parse_iso
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER, ERR_DEPOSIT_DEADLINE_PASSED,
    ERR_DEPOSIT_AMOUNT_MISMATCH, ERR_CYCLE_PHASE_MISMATCH, ERR_CAPACITY_FULL,
    ERR_FORBIDDEN,
)
from middleware import require_roles, get_auth
from response import success_object, success_list
from services.derived import recompute_program, recompute_cycle, recompute_melt_risk
from services.serializers import serialize_deposit, touch

bp = Blueprint("deposits", __name__, url_prefix="/enrollment/deposits")


@bp.route("", methods=["POST"])
def create_deposit():
    user_id, role = require_roles("Applicant")
    body = request.get_json(silent=True) or {}
    application_id = body.get("application_id")
    amount_cents = body.get("amount_cents")

    if application_id is None or application_id not in store.applications:
        raise ApiError(ERR_NOT_FOUND, 404, "application_id not found")
    app = store.applications[application_id]

    # Applicant ownership
    if user_id != app["applicant_id"]:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Not resource owner")

    if amount_cents is None or not isinstance(amount_cents, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, "amount_cents required as integer")

    # State gate
    if app["status"] != "ADMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Application status {app['status']} does not permit deposit")

    program = store.programs.get(app["program_id"])
    cycle = store.cycles.get(app["cycle_id"])

    # Clock gate
    now = clock.now()
    deadline = _parse_iso(cycle["deposit_deadline_at"]) if cycle else None
    if deadline and now > deadline:
        raise ApiError(ERR_DEPOSIT_DEADLINE_PASSED, 409,
                       "Deposit deadline has passed")

    # Amount match
    if amount_cents != program["deposit_amount_cents"]:
        raise ApiError(ERR_DEPOSIT_AMOUNT_MISMATCH, 422,
                       "amount_cents != program.deposit_amount_cents")

    # Cycle phase
    if cycle["status"] != "DECISIONS_RELEASED":
        raise ApiError(ERR_CYCLE_PHASE_MISMATCH, 409,
                       f"Cycle status {cycle['status']} does not permit deposits")

    # Capacity
    recompute_program(program)
    if program["deposited_count"] + program["enrolled_count"] >= program["capacity_seats"]:
        raise ApiError(ERR_CAPACITY_FULL, 409, "Program capacity reached")

    now_iso_str = now_iso()
    deposit = {
        "id": new_id(),
        "application_id": application_id,
        "amount_cents": amount_cents,
        "paid_at": now_iso_str,
        "refund_amount_cents": None,
        "status": "PAID",
        "created_at": now_iso_str,
        "updated_at": now_iso_str,
        "version": 1,
    }
    store.deposits[deposit["id"]] = deposit

    # Application ADMITTED -> DEPOSITED
    app["status"] = "DEPOSITED"
    touch(app)

    recompute_program(program)
    touch(program)
    if cycle:
        recompute_cycle(cycle)
    recompute_melt_risk(app)

    return success_object(serialize_deposit(deposit), status=201)


@bp.route("/<depositId>", methods=["GET"])
def get_deposit(depositId):
    user_id, role = get_auth()
    if role not in ("SystemAdmin", "EnrollmentManager", "AdmissionsOfficer",
                    "FinancialAidOfficer", "Applicant"):
        raise ApiError(ERR_FORBIDDEN, 403, "Role not permitted")
    d = store.deposits.get(depositId)
    if not d:
        raise ApiError(ERR_NOT_FOUND, 404, "Deposit not found")
    if role == "Applicant":
        app = store.applications.get(d["application_id"])
        if not app or user_id != app["applicant_id"]:
            raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Not resource owner")
    return success_object(serialize_deposit(d))


@bp.route("", methods=["GET"])
def list_deposits():
    require_roles("SystemAdmin", "EnrollmentManager", "AdmissionsOfficer", "FinancialAidOfficer")
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    items = list(store.deposits.values())
    if application_id:
        items = [d for d in items if d["application_id"] == application_id]
    if status:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_deposit(d) for d in page], limit, offset, total)
