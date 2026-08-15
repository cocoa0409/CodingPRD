"""Compressor registry: CRUD + run-hours + state transitions + decommission."""

from flask import Blueprint, request

from auth import require_roles, check_ownership
from domain import decommission_cascade, recompute_facility_chain
from envelope import ok_object, ok_list
from errors import conflict, invalid_state, not_found, unprocessable, ERR_DUPLICATE_ASSET_TAG, ERR_RUN_HOURS_REGRESSION
import store
from store import new_resource, touch
from util import body_or_empty, opt_int, parse_pagination, public, req_int, req_str, sort_and_page

bp = Blueprint("compressors", __name__)

ALL_ROLES = ["DealerAdmin", "EnergyEngineer", "ServiceTech", "ContractManager", "FacilityManager"]


def _get_or_404(compressor_id):
    comp = store.compressors.get(compressor_id)
    if comp is None:
        raise not_found("Compressor not found")
    return comp


@bp.route("/compressors", methods=["POST"])
def create_compressor():
    require_roles(["DealerAdmin", "ServiceTech"])
    body = body_or_empty()
    facility_id = req_str(body, "facility_id")
    asset_tag = req_str(body, "asset_tag")
    rated_kw = req_int(body, "rated_kw")
    rated_cfm = req_int(body, "rated_cfm")
    run_hours = opt_int(body, "run_hours_total", 0)

    fac = store.facilities.get(facility_id)
    if fac is None:
        raise not_found("Facility not found")

    # asset_tag unique per facility among non-DECOMMISSIONED compressors
    if any(
        c["facility_id"] == facility_id and c["asset_tag"] == asset_tag and c["status"] != "DECOMMISSIONED"
        for c in store.compressors.values()
    ):
        raise conflict(ERR_DUPLICATE_ASSET_TAG, "asset_tag already in use at this facility")

    comp = new_resource()
    comp.update(
        {
            "facility_id": facility_id,
            "asset_tag": asset_tag,
            "rated_kw": rated_kw,
            "rated_cfm": rated_cfm,
            "run_hours_total": run_hours,
            "status": "IN_SERVICE",
        }
    )
    store.compressors[comp["id"]] = comp
    recompute_facility_chain(facility_id)
    return ok_object(public(comp), 201)


@bp.route("/compressors", methods=["GET"])
def list_compressors():
    require_roles(ALL_ROLES)
    items = list(store.compressors.values())
    facility_id = request.args.get("facility_id")
    status = request.args.get("status")
    if facility_id is not None:
        items = [c for c in items if c["facility_id"] == facility_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    limit, offset = parse_pagination()
    page, total = sort_and_page(items, limit, offset)
    return ok_list([public(c) for c in page], limit, offset, total)


@bp.route("/compressors/<compressorId>", methods=["GET"])
def get_compressor(compressorId):
    user_id, role = require_roles(ALL_ROLES)
    comp = _get_or_404(compressorId)
    check_ownership(user_id, role, comp["facility_id"])
    return ok_object(public(comp), 200)


@bp.route("/compressors/<compressorId>/log-run-hours", methods=["POST"])
def log_run_hours(compressorId):
    require_roles(["ServiceTech"])
    comp = _get_or_404(compressorId)
    body = body_or_empty()
    run_hours = req_int(body, "run_hours_total")
    if run_hours < comp["run_hours_total"]:
        raise unprocessable(ERR_RUN_HOURS_REGRESSION, "run_hours_total may not decrease")
    if run_hours != comp["run_hours_total"]:
        comp["run_hours_total"] = run_hours
        touch(comp)
    recompute_facility_chain(comp["facility_id"])
    return ok_object(public(comp), 200)


@bp.route("/compressors/<compressorId>/mark-down", methods=["POST"])
def mark_down(compressorId):
    require_roles(["ServiceTech"])
    comp = _get_or_404(compressorId)
    if comp["status"] != "IN_SERVICE":
        raise invalid_state("Compressor must be IN_SERVICE to mark down")
    fac = store.facilities.get(comp["facility_id"])
    if fac is not None and fac["status"] == "OFFBOARDED":
        raise invalid_state("Facility is OFFBOARDED")
    comp["status"] = "DOWN"
    touch(comp)
    recompute_facility_chain(comp["facility_id"])
    return ok_object(public(comp), 200)


@bp.route("/compressors/<compressorId>/return-to-service", methods=["POST"])
def return_to_service(compressorId):
    require_roles(["ServiceTech"])
    comp = _get_or_404(compressorId)
    if comp["status"] != "DOWN":
        raise invalid_state("Compressor must be DOWN to return to service")
    comp["status"] = "IN_SERVICE"
    touch(comp)
    recompute_facility_chain(comp["facility_id"])
    return ok_object(public(comp), 200)


@bp.route("/compressors/<compressorId>/decommission", methods=["POST"])
def decommission(compressorId):
    require_roles(["DealerAdmin", "ContractManager"])
    comp = _get_or_404(compressorId)
    if comp["status"] not in ("IN_SERVICE", "DOWN"):
        raise invalid_state("Compressor must be IN_SERVICE or DOWN to decommission")
    comp["status"] = "DECOMMISSIONED"
    touch(comp)
    decommission_cascade(comp)
    return ok_object(public(comp), 200)
