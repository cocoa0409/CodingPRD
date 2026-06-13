"""RentalAssistancePeriod endpoints — PRD §3.11."""
from flask import Blueprint

from db import STORE, to_iso, parse_iso
from errors import ApiError
from middleware import get_auth, require_roles
from response import success
from services.common import lookup, list_response
from services.models import base_entity, touch, serialize
from services.validation import require_body, req_str, req_datetime

bp = Blueprint("rental_periods", __name__)

ALL_ROLES = ["ProgramAdmin", "Caseworker", "Inspector"]


@bp.route("/disaster-relief/rental-periods", methods=["POST"])
def create_period():
    _uid, role = get_auth()
    require_roles(role, ["Caseworker", "ProgramAdmin"])
    body = require_body()
    ihp_case_id = req_str(body, "ihp_case_id")
    with STORE.lock:
        case = lookup("ihp_cases", ihp_case_id)

        # Funding case must be AWARD_APPROVED or DISBURSING (priority 5)
        if case["status"] not in ("AWARD_APPROVED", "DISBURSING"):
            raise ApiError("ERR_CASE_NOT_FUNDABLE_FOR_RENTAL")

        period_start = req_datetime(body, "period_start")
        period_end = req_datetime(body, "period_end")
        if period_end <= period_start:
            raise ApiError("ERR_INVALID_REQUEST", "period_end must be after period_start.")

        applicant_id = case["applicant_id"]

        # Overlap (priority 9.5): half-open, no buffer, same applicant, ACTIVE only
        for other in STORE.rental_periods.values():
            if other["applicant_id"] != applicant_id:
                continue
            if other["status"] != "ACTIVE":
                continue
            o_start = parse_iso(other["period_start"])
            o_end = parse_iso(other["period_end"])
            if period_start < o_end and o_start < period_end:
                raise ApiError("ERR_RENTAL_PERIOD_OVERLAP")

        p = base_entity()
        p.update({
            "ihp_case_id": ihp_case_id,
            "applicant_id": applicant_id,
            "period_start": to_iso(period_start),
            "period_end": to_iso(period_end),
            "status": "ACTIVE",
        })
        STORE.rental_periods[p["id"]] = p
        return success(serialize(p), status=201)


@bp.route("/disaster-relief/rental-periods", methods=["GET"])
def list_periods():
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        data, pg = list_response(
            STORE.rental_periods.values(),
            {"ihp_case_id": "ihp_case_id", "applicant_id": "applicant_id", "status": "status"},
        )
    return success(data, pagination=pg)


@bp.route("/disaster-relief/rental-periods/<pid>", methods=["GET"])
def get_period(pid):
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        p = lookup("rental_periods", pid)
        return success(serialize(p))


@bp.route("/disaster-relief/rental-periods/<pid>/close", methods=["POST"])
def close_period(pid):
    _uid, role = get_auth()
    require_roles(role, ["Caseworker", "ProgramAdmin"])
    with STORE.lock:
        p = lookup("rental_periods", pid)
        if p["status"] != "ACTIVE":
            raise ApiError("ERR_RENTAL_PERIOD_NOT_ACTIVE")
        p["status"] = "CLOSED"
        touch(p)
        return success(serialize(p))
