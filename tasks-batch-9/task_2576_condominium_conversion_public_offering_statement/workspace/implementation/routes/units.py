"""Unit reads, boundary adjustments and the withdrawal / reinstatement pair."""

from flask import Blueprint

import envelope
import serializers
import store
import validation as v
from errors import ApiError
from services import cascades, projects as project_service
from routes.declaration import UNIT_INPUTS

bp = Blueprint("units", __name__)

READ_ROLES = ["ConverterSponsor", "StateRegulator", "LenderUnderwriter",
              "EscrowAgent", "PlatformAdmin", "Purchaser", "TenantOccupant"]
PATCH_ROLES = ["ConverterSponsor", "LicensedEngineer"]
WITHDRAW_ROLES = ["ConverterSponsor"]


@bp.get("/units")
def list_units():
    v.authorize(READ_ROLES)
    limit, offset = v.pagination()
    records = [
        u for u in store.ordered(store.units.values())
        if v.matches(
            u,
            conversion_project_id=v.filter_value("conversion_project_id"),
            declaration_package_id=v.filter_value("declaration_package_id"),
            declaration_status=v.filter_value("declaration_status"),
            sale_status=v.filter_value("sale_status"))]
    window, page = envelope.paginate(records, limit, offset)
    return envelope.array_response(serializers.dump_all(window), 200, page)


@bp.get("/units/<unit_id>")
def get_unit(unit_id):
    v.authorize(READ_ROLES)
    unit = v.get_unit(unit_id)
    return envelope.object_response(serializers.dump(unit), 200)


@bp.patch("/units/<unit_id>")
def patch_unit(unit_id):
    v.authorize(PATCH_ROLES)
    unit = v.get_unit(unit_id)
    package = v.get_package(unit["declaration_package_id"])
    project = v.get_project(unit["conversion_project_id"])
    body = v.parse([dict(spec, required=False) for spec in UNIT_INPUTS])
    v.gate_not_frozen(project)
    v.require_state(unit, "sale_status", ("UNSOLD",))
    basis_changed = ("base_percentage_interest_bp" in body
                     and body["base_percentage_interest_bp"]
                     != unit["base_percentage_interest_bp"])
    for name, value in body.items():
        unit[name] = value
    if basis_changed and package["allocated_bp_total"] == 0:
        # No reallocation sweep has written this package yet, so the effective
        # interest still tracks the declared basis it was seeded from.
        unit["percentage_interest_bp"] = unit["base_percentage_interest_bp"]
    store.touch(unit)
    if basis_changed:
        # The declared economic basis moved beneath a certified plat.
        cascades.revert_plat(package)
    project_service.sync(project)
    return envelope.object_response(serializers.dump(unit), 200)


@bp.post("/units/<unit_id>/withdraw")
def withdraw_unit(unit_id):
    v.authorize(WITHDRAW_ROLES)
    unit = v.get_unit(unit_id)
    package = v.get_package(unit["declaration_package_id"])
    project = v.get_project(unit["conversion_project_id"])
    body = v.parse([v.field("withdrawal_reason", "string", required=False,
                            max_len=500)])
    v.gate_not_frozen(project)
    v.require_state(unit, "declaration_status", ("INCLUDED",))
    survivors = [u for u in store.package_units(package["id"])
                 if u["declaration_status"] == "INCLUDED"
                 and u["id"] != unit["id"]]
    if not survivors:
        raise ApiError("ERR_LAST_INCLUDED_UNIT")
    cascades.withdraw_unit(unit, package, project,
                           body.get("withdrawal_reason"))
    return envelope.object_response(serializers.dump(unit), 200)


@bp.post("/units/<unit_id>/reinstate")
def reinstate_unit(unit_id):
    v.authorize(WITHDRAW_ROLES)
    unit = v.get_unit(unit_id)
    package = v.get_package(unit["declaration_package_id"])
    project = v.get_project(unit["conversion_project_id"])
    v.gate_not_frozen(project)
    v.require_state(unit, "declaration_status", ("WITHDRAWN",))
    cascades.reinstate_unit(unit, package, project)
    return envelope.object_response(serializers.dump(unit), 200)
