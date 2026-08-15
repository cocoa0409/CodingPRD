"""Route resource endpoints."""
from flask import Blueprint, request

import db
from envelope import success_list, success_object
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_DUPLICATE_ROUTE_CODE,
    ERR_INVALID_STATE,
    ERR_INVALID_TIME_RANGE,
    raise_err,
)
from middleware import authenticate, get_or_404, require_roles
from validation import (
    get_body,
    opt_bool,
    paginate,
    pagination_params,
    req_int,
    req_minute,
    req_str,
)

bp = Blueprint("routes", __name__)

READ_ROLES = {"SystemAdmin", "DistrictAdmin", "ContractorOps", "FinanceClerk", "Driver"}


def check_transition(rec, allowed_from):
    if rec["status"] == "ARCHIVED":
        raise_err(ERR_ALREADY_TERMINAL, "Route is ARCHIVED (terminal)")
    if rec["status"] not in allowed_from:
        raise_err(
            ERR_INVALID_STATE,
            "Route in state %s cannot perform this transition" % rec["status"],
        )


@bp.route("/busops/routes", methods=["POST"])
def create_route():
    body = get_body()
    contract_id = req_str(body, "contract_id")
    route_code = req_str(body, "route_code")
    school_site = req_str(body, "school_site")
    am_start = req_minute(body, "am_start_minute")
    am_end = req_int(body, "am_end_minute", minimum=0, maximum=1439)
    student_count = req_int(body, "student_count", minimum=0)
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    contract = get_or_404("contracts", contract_id, "Contract")
    # temporal: strictly positive duration
    if am_end <= am_start:
        raise_err(
            ERR_INVALID_TIME_RANGE, "am_end_minute must be strictly after am_start_minute"
        )
    # constraint: unique route code within contract among non-archived routes
    for r in db.all_of("routes"):
        if (
            r["contract_id"] == contract_id
            and r["route_code"] == route_code
            and r["status"] != "ARCHIVED"
        ):
            raise_err(
                ERR_DUPLICATE_ROUTE_CODE,
                "route_code already exists on the contract",
            )
    # fiscal: contract must be ACTIVE
    if contract["status"] != "ACTIVE":
        raise_err(ERR_CONTRACT_NOT_ACTIVE, "Route creation requires contract ACTIVE")

    rec = {
        "id": db.new_id(),
        "contract_id": contract_id,
        "route_code": route_code,
        "school_site": school_site,
        "am_start_minute": am_start,
        "am_end_minute": am_end,
        "student_count": student_count,
        "status": "ACTIVE",
    }
    db.stamp_new(rec)
    db.STORES["routes"][rec["id"]] = rec
    return success_object(db.public(rec), status=201)


@bp.route("/busops/routes", methods=["GET"])
def list_routes():
    limit, offset = pagination_params()
    actor = authenticate()
    require_roles(actor, READ_ROLES)
    items = list(db.all_of("routes"))
    contract_id = request.args.get("contract_id")
    status = request.args.get("status")
    if contract_id is not None:
        items = [r for r in items if r["contract_id"] == contract_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, info = paginate(items, limit, offset)
    return success_list(page, info)


@bp.route("/busops/routes/<rid>", methods=["GET"])
def get_route(rid):
    actor = authenticate()
    require_roles(actor, READ_ROLES)
    rec = get_or_404("routes", rid, "Route")
    return success_object(db.public(rec))


@bp.route("/busops/routes/<rid>/deactivate", methods=["POST"])
def deactivate_route(rid):
    body = get_body()
    archive = opt_bool(body, "archive", default=False)
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    rec = get_or_404("routes", rid, "Route")
    if archive:
        check_transition(rec, ("SUSPENDED",))
        today = db.clock_date().isoformat()
        for a in db.all_of("assignments"):
            if a["route_id"] != rec["id"]:
                continue
            if a["status"] not in ("PLANNED", "CONFIRMED", "EN_ROUTE"):
                continue
            day = db.day_of_assignment(a)
            if day is not None and day["service_date"] >= today:
                raise_err(
                    ERR_INVALID_STATE,
                    "Route has future assignments and cannot be archived",
                )
        rec["status"] = "ARCHIVED"
    else:
        check_transition(rec, ("ACTIVE",))
        rec["status"] = "SUSPENDED"
    db.touch(rec)
    return success_object(db.public(rec))


@bp.route("/busops/routes/<rid>/reactivate", methods=["POST"])
def reactivate_route(rid):
    get_body()
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    rec = get_or_404("routes", rid, "Route")
    check_transition(rec, ("SUSPENDED",))
    contract = db.find("contracts", rec["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise_err(
            ERR_CONTRACT_NOT_ACTIVE, "Reactivation requires contract status=ACTIVE"
        )
    rec["status"] = "ACTIVE"
    db.touch(rec)
    return success_object(db.public(rec))
