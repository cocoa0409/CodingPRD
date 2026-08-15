"""Retrofit projects: proposal, approval, install, commission, accept."""

from flask import Blueprint, request

from auth import require_roles, check_ownership
from envelope import ok_object, ok_list
from errors import invalid_request, invalid_state, not_found, unprocessable, ERR_SEQUENCE_COMPRESSOR_INVALID
import store
from store import new_resource, touch
from util import body_or_empty, parse_pagination, public, req_int, req_list_of_str, req_str, sort_and_page

bp = Blueprint("retrofits", __name__)

ALL_ROLES = ["DealerAdmin", "EnergyEngineer", "ServiceTech", "ContractManager", "FacilityManager"]


def _get_or_404(project_id):
    proj = store.retrofit_projects.get(project_id)
    if proj is None:
        raise not_found("RetrofitProject not found")
    return proj


def _validate_sequence(facility_id, sequence_ids, require_in_service):
    for cid in sequence_ids:
        comp = store.compressors.get(cid)
        if comp is None or comp["facility_id"] != facility_id:
            raise unprocessable(
                ERR_SEQUENCE_COMPRESSOR_INVALID,
                "sequence_compressor_ids entry missing or foreign to facility",
            )
        if require_in_service and comp["status"] != "IN_SERVICE":
            raise unprocessable(
                ERR_SEQUENCE_COMPRESSOR_INVALID,
                "sequence_compressor_ids entry must be IN_SERVICE at approve time",
            )


@bp.route("/retrofit-projects", methods=["POST"])
def create_project():
    require_roles(["EnergyEngineer"])
    body = body_or_empty()
    facility_id = req_str(body, "facility_id")
    baseline_psi = req_int(body, "baseline_pressure_psi")
    target_psi = req_int(body, "target_pressure_psi")
    sequence_ids = req_list_of_str(body, "sequence_compressor_ids")
    cost = req_int(body, "project_cost_cents")

    if target_psi >= baseline_psi:
        raise invalid_request("target_pressure_psi must be strictly below baseline_pressure_psi")

    if store.facilities.get(facility_id) is None:
        raise not_found("Facility not found")

    _validate_sequence(facility_id, sequence_ids, require_in_service=False)

    proj = new_resource()
    proj.update(
        {
            "facility_id": facility_id,
            "baseline_pressure_psi": baseline_psi,
            "target_pressure_psi": target_psi,
            "sequence_compressor_ids": list(sequence_ids),
            "project_cost_cents": cost,
            "accepted_date": None,
            "status": "PROPOSED",
        }
    )
    store.retrofit_projects[proj["id"]] = proj
    return ok_object(public(proj), 201)


@bp.route("/retrofit-projects", methods=["GET"])
def list_projects():
    require_roles(ALL_ROLES)
    items = list(store.retrofit_projects.values())
    facility_id = request.args.get("facility_id")
    status = request.args.get("status")
    if facility_id is not None:
        items = [p for p in items if p["facility_id"] == facility_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    limit, offset = parse_pagination()
    page, total = sort_and_page(items, limit, offset)
    return ok_list([public(p) for p in page], limit, offset, total)


@bp.route("/retrofit-projects/<retrofitProjectId>", methods=["GET"])
def get_project(retrofitProjectId):
    user_id, role = require_roles(ALL_ROLES)
    proj = _get_or_404(retrofitProjectId)
    check_ownership(user_id, role, proj["facility_id"])
    return ok_object(public(proj), 200)


@bp.route("/retrofit-projects/<retrofitProjectId>/approve", methods=["POST"])
def approve(retrofitProjectId):
    user_id, role = require_roles(["FacilityManager"])
    proj = _get_or_404(retrofitProjectId)
    check_ownership(user_id, role, proj["facility_id"])
    if proj["status"] != "PROPOSED":
        raise invalid_state("RetrofitProject must be PROPOSED to approve")
    _validate_sequence(proj["facility_id"], proj["sequence_compressor_ids"], require_in_service=True)
    proj["status"] = "APPROVED"
    touch(proj)
    return ok_object(public(proj), 200)


@bp.route("/retrofit-projects/<retrofitProjectId>/mark-installed", methods=["POST"])
def mark_installed(retrofitProjectId):
    require_roles(["ServiceTech"])
    proj = _get_or_404(retrofitProjectId)
    if proj["status"] != "APPROVED":
        raise invalid_state("RetrofitProject must be APPROVED to mark installed")
    proj["status"] = "INSTALLED"
    touch(proj)
    return ok_object(public(proj), 200)


@bp.route("/retrofit-projects/<retrofitProjectId>/commission", methods=["POST"])
def commission(retrofitProjectId):
    require_roles(["ServiceTech"])
    proj = _get_or_404(retrofitProjectId)
    if proj["status"] != "INSTALLED":
        raise invalid_state("RetrofitProject must be INSTALLED to commission")
    proj["status"] = "COMMISSIONED"
    touch(proj)
    return ok_object(public(proj), 200)


@bp.route("/retrofit-projects/<retrofitProjectId>/accept", methods=["POST"])
def accept(retrofitProjectId):
    user_id, role = require_roles(["FacilityManager"])
    proj = _get_or_404(retrofitProjectId)
    check_ownership(user_id, role, proj["facility_id"])
    if proj["status"] != "COMMISSIONED":
        raise invalid_state("RetrofitProject must be COMMISSIONED to accept")
    proj["status"] = "ACCEPTED"
    proj["accepted_date"] = store.clock_today().isoformat()
    touch(proj)
    return ok_object(public(proj), 200)
