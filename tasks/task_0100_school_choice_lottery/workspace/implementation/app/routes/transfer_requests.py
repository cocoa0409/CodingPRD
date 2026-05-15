"""TransferRequest endpoints — create / list / approve / deny / revoke."""
from flask import Blueprint, g, jsonify, request

from ..auth import require_auth
from ..errors import APIError
from ..occ import check_version
from ..responses import list_response, success_response
from ..services.family import recompute_head_household_application_id
from ..services.lookups import (fk_application, fk_district,
                                get_transfer_request_or_404)
from ..services.sweeps import (recompute_seats, recompute_waitlist_positions,
                               waitlist_backfill)
from ..store import get_lock, get_store, stamp_create, stamp_update
from ..validators import (get_json_body, paginate, parse_pagination,
                          require_string)


bp = Blueprint("transfer_requests", __name__, url_prefix="/enrollment/transfer-requests")


VALID_TR_STATUS = {"PENDING", "APPROVED", "DENIED", "REVOKED"}


def _serialize(t: dict) -> dict:
    return {
        "id": t["id"],
        "application_id": t["application_id"],
        "target_district_id": t["target_district_id"],
        "status": t["status"],
        "capacity_units_held": t["capacity_units_held"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def _district_capacity(target_district_id: str) -> int:
    """Sum (seats_total - seats_accepted) over MAGNET/CHARTER programs in the target
    district whose window_status is in the allowed set.
    """
    allowed_status = {"SCHEDULED", "OPEN", "CLOSED", "LOTTERY_DRAWN", "BACKFILL"}
    store = get_store()
    total = 0
    for p in store.programs.values():
        school = store.schools.get(p["school_id"])
        if school is None or school["district_id"] != target_district_id:
            continue
        if school["school_type"] not in ("MAGNET", "CHARTER"):
            continue
        if p["window_status"] not in allowed_status:
            continue
        total += int(p["seats_total"]) - int(p["seats_accepted"])
    return total


@bp.route("", methods=["POST"])
@require_auth("FamilyUser")
def create_transfer_request():
    body = get_json_body()
    application_id = require_string(body, "application_id")
    target_district_id = require_string(body, "target_district_id")

    with get_lock():
        app = fk_application(application_id)
        district = fk_district(target_district_id)

        store = get_store()
        student = store.students.get(app["student_id"])
        if student is None or student["family_id"] != g.user_id:
            raise APIError("ERR_FORBIDDEN",
                           "FamilyUser may only create transfer requests for their own family's applications")
        program = store.programs.get(app["program_id"])
        if program is None:
            raise APIError("ERR_FK_NOT_FOUND", "linked program does not exist")
        school = store.schools.get(program["school_id"])
        if school is None or school["district_id"] != target_district_id:
            raise APIError("ERR_VALIDATION",
                           "target_district_id must equal program.school.district_id")

        record = {
            "application_id": application_id,
            "target_district_id": target_district_id,
            "status": "PENDING",
            "capacity_units_held": 0,
        }
        stamp_create(record)
        store.transfer_requests[record["id"]] = record
        resp, code = success_response(_serialize(record), status=201, response_type="object")
    return jsonify(resp), code


@bp.route("", methods=["GET"])
@require_auth("FamilyUser", "DistrictAdmin", "SystemOperator")
def list_transfer_requests():
    limit, offset = parse_pagination()
    target_district_id = request.args.get("target_district_id")
    status_filter = request.args.get("status")
    application_id = request.args.get("application_id")
    if status_filter is not None and status_filter not in VALID_TR_STATUS:
        raise APIError("ERR_VALIDATION", "invalid status filter")

    store = get_store()
    items = []
    for t in store.transfer_requests.values():
        if target_district_id is not None and t["target_district_id"] != target_district_id:
            continue
        if status_filter is not None and t["status"] != status_filter:
            continue
        if application_id is not None and t["application_id"] != application_id:
            continue
        if g.user_role == "FamilyUser":
            app = store.applications.get(t["application_id"])
            if app is None:
                continue
            student = store.students.get(app["student_id"])
            if student is None or student["family_id"] != g.user_id:
                continue
        items.append(t)
    items.sort(key=lambda t: (t["created_at"], t["id"]))
    page, total = paginate(items, limit, offset)
    resp, code = list_response([_serialize(x) for x in page], total, limit, offset)
    return jsonify(resp), code


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------

@bp.route("/<tr_id>/approve", methods=["POST"])
@require_auth("DistrictAdmin")
def approve_transfer_request(tr_id):
    body = get_json_body()
    with get_lock():
        tr = get_transfer_request_or_404(tr_id)
        if g.user_id != tr["target_district_id"]:
            raise APIError("ERR_FORBIDDEN",
                           "DistrictAdmin may only act on transfer requests targeting their own district")
        check_version(tr, body)

        if tr["status"] != "PENDING":
            raise APIError("ERR_INVALID_STATE_FOR_TRANSITION",
                           f"approve requires PENDING; current status is {tr['status']}")

        store = get_store()
        district = store.districts[tr["target_district_id"]]
        if not district["accepts_inter_district_transfers"]:
            raise APIError("ERR_DISTRICT_NO_TRANSFERS",
                           "target district does not accept inter-district transfers")

        # Capacity calculation
        capacity = _district_capacity(tr["target_district_id"])
        held = sum(1 for t in store.transfer_requests.values()
                   if t["target_district_id"] == tr["target_district_id"]
                   and t["status"] == "APPROVED")
        if held + 1 > capacity:
            raise APIError("ERR_DISTRICT_CAPACITY_EXCEEDED",
                           "approving would exceed inter-district capacity")

        tr["status"] = "APPROVED"
        tr["capacity_units_held"] = 1
        stamp_update(tr)
        resp, code = success_response(_serialize(tr), status=200, response_type="object")
    return jsonify(resp), code


# ---------------------------------------------------------------------------
# Deny
# ---------------------------------------------------------------------------

@bp.route("/<tr_id>/deny", methods=["POST"])
@require_auth("DistrictAdmin")
def deny_transfer_request(tr_id):
    body = get_json_body()
    with get_lock():
        tr = get_transfer_request_or_404(tr_id)
        if g.user_id != tr["target_district_id"]:
            raise APIError("ERR_FORBIDDEN",
                           "DistrictAdmin may only act on transfer requests targeting their own district")
        check_version(tr, body)

        if tr["status"] != "PENDING":
            raise APIError("ERR_INVALID_STATE_FOR_TRANSITION",
                           f"deny requires PENDING; current status is {tr['status']}")

        tr["status"] = "DENIED"
        tr["capacity_units_held"] = 0
        stamp_update(tr)
        resp, code = success_response(_serialize(tr), status=200, response_type="object")
    return jsonify(resp), code


# ---------------------------------------------------------------------------
# Revoke
# ---------------------------------------------------------------------------

@bp.route("/<tr_id>/revoke", methods=["POST"])
@require_auth("DistrictAdmin")
def revoke_transfer_request(tr_id):
    body = get_json_body()
    with get_lock():
        tr = get_transfer_request_or_404(tr_id)
        if g.user_id != tr["target_district_id"]:
            raise APIError("ERR_FORBIDDEN",
                           "DistrictAdmin may only act on transfer requests targeting their own district")
        check_version(tr, body)

        if tr["status"] != "APPROVED":
            raise APIError("ERR_INVALID_STATE_FOR_TRANSITION",
                           f"revoke requires APPROVED; current status is {tr['status']}")

        store = get_store()
        app = store.applications.get(tr["application_id"])
        if app is None:
            raise APIError("ERR_INVALID_STATE_FOR_TRANSITION",
                           "linked application no longer exists")
        if app["status"] not in ("DRAFT", "SUBMITTED", "WAITLISTED"):
            raise APIError("ERR_INVALID_STATE_FOR_TRANSITION",
                           f"linked application must be in DRAFT/SUBMITTED/WAITLISTED; current {app['status']}")

        tr["status"] = "REVOKED"
        tr["capacity_units_held"] = 0
        stamp_update(tr)

        # Cascade application
        if app["status"] in ("SUBMITTED", "WAITLISTED"):
            was_waitlisted = (app["status"] == "WAITLISTED")
            app["status"] = "WITHDRAWN"
            app["waitlist_position"] = None
            stamp_update(app)
            program = store.programs[app["program_id"]]
            recompute_seats(program)
            if was_waitlisted:
                # Renumber the remaining waitlist positions; no seat was offered, so no backfill promotion.
                recompute_waitlist_positions(program["id"])

        resp, code = success_response(_serialize(tr), status=200, response_type="object")
    return jsonify(resp), code
