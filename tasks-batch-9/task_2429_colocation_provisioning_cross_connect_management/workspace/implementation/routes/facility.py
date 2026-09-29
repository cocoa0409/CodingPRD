"""Floor rows and cabinet space (PRD §3.2 and §3.3)."""

from flask import Blueprint

import refs
from auth import authorize
from errors import ApiError
from response import created, ok, ok_list, paginate, pagination, serialize
from rollups import (
    cabinets_of_contract,
    circuits_of_cabinet,
    recompute_contract,
    recompute_row,
)
from store import (
    CABINET_STATUSES,
    COMMIT_CABINET_STATUSES,
    FOOTPRINT_TYPES,
    base_row,
    store,
    touch,
)
from validate import (
    json_body,
    opt_bool,
    opt_enum,
    opt_int,
    opt_number,
    qfilter,
    req_enum,
    req_int,
    req_number,
    req_string,
)

bp = Blueprint("facility", __name__)

ROW_READ_ROLES = ("FacilityManager", "ProvisioningEngineer", "BillingOperator")
CABINET_READ_ROLES = ("FacilityManager", "ProvisioningEngineer", "BillingOperator", "CustomerAdmin")
ACCEPTING_POSTURES = ("OPEN", "COOLING_CONSTRAINED")

CABINET_TRANSITIONS = {
    ("AVAILABLE", "RESERVED"),
    ("RESERVED", "AVAILABLE"),
    ("RESERVED", "INSTALLED"),
}


# --------------------------------------------------------------------------
# Floor rows
# --------------------------------------------------------------------------

@bp.route("/rows", methods=["POST"])
def create_row():
    authorize("FacilityManager")
    body = json_body()
    hall_code = req_string(body, "hall_code")
    row_code = req_string(body, "row_code")
    cabinet_slot_count = req_int(body, "cabinet_slot_count", minimum=1)
    design_density = req_number(body, "design_density_kw_per_cabinet", exclusive_minimum=0)
    max_row_power = req_number(body, "max_row_power_kw", exclusive_minimum=0)
    cooling_capacity = req_number(body, "cooling_capacity_kw", exclusive_minimum=0)
    escort_slot_count = opt_int(body, "escort_slot_count", 1, minimum=0)
    decommission_flag = opt_bool(body, "decommission_flag", False)

    for existing in store.rows.values():
        if existing["hall_code"] == hall_code and existing["row_code"] == row_code:
            raise ApiError("ERR_INVALID_REQUEST", "row_code must be unique within the hall")

    row = base_row()
    row.update(
        {
            "hall_code": hall_code,
            "row_code": row_code,
            "cabinet_slot_count": cabinet_slot_count,
            "design_density_kw_per_cabinet": design_density,
            "max_row_power_kw": max_row_power,
            "cooling_capacity_kw": cooling_capacity,
            "escort_slot_count": escort_slot_count,
            "decommission_flag": decommission_flag,
            "occupied_slot_count": 0,
            "energized_cabinet_count": 0,
            "allocated_power_kw": 0.0,
            "cooling_load_kw": 0.0,
            "density_ceiling_kw": 0.0,
            "effective_ceiling_kw": 0.0,
            "measured_peak_kw": 0.0,
            "stranded_nameplate_kw": 0.0,
            "stranded_measured_kw": 0.0,
            "row_status": "OPEN",
        }
    )
    store.rows[row["id"]] = row
    recompute_row(row)
    return created(serialize(row))


@bp.route("/rows/<row_id>", methods=["PATCH"])
def patch_row(row_id):
    authorize("FacilityManager")
    row = refs.path_row(refs.ROW, row_id)
    body = json_body()
    cooling_capacity = opt_number(body, "cooling_capacity_kw", None, exclusive_minimum=0)
    max_row_power = opt_number(body, "max_row_power_kw", None, exclusive_minimum=0)
    design_density = opt_number(body, "design_density_kw_per_cabinet", None, exclusive_minimum=0)
    escort_slot_count = opt_int(body, "escort_slot_count", None, minimum=0)
    decommission_flag = opt_bool(body, "decommission_flag", None)

    if cooling_capacity is not None:
        row["cooling_capacity_kw"] = cooling_capacity
    if max_row_power is not None:
        row["max_row_power_kw"] = max_row_power
    if design_density is not None:
        row["design_density_kw_per_cabinet"] = design_density
    if escort_slot_count is not None:
        row["escort_slot_count"] = escort_slot_count
    if decommission_flag is not None:
        row["decommission_flag"] = decommission_flag

    # Re-limiting always increments the row's version, even when the recomputed
    # capacity picture happens to be unchanged.
    recompute_row(row, force=True)
    return ok(serialize(row))


@bp.route("/rows/<row_id>", methods=["GET"])
def get_row(row_id):
    authorize(*ROW_READ_ROLES)
    row = refs.path_row(refs.ROW, row_id)
    return ok(serialize(row))


@bp.route("/rows", methods=["GET"])
def list_rows():
    authorize(*ROW_READ_ROLES)
    limit, offset = pagination()
    rows = qfilter(list(store.rows.values()), "hall_code", "row_status")
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


# --------------------------------------------------------------------------
# Cabinets
# --------------------------------------------------------------------------

@bp.route("/cabinets", methods=["POST"])
def create_cabinet():
    authorize("FacilityManager", "ProvisioningEngineer")
    body = json_body()
    row = refs.body_fk(body, "row_id", refs.ROW)

    row_id = req_string(body, "row_id")
    cabinet_code = req_string(body, "cabinet_code")
    rated_power_kw = req_number(body, "rated_power_kw", exclusive_minimum=0)
    footprint_type = opt_enum(body, "footprint_type", FOOTPRINT_TYPES, "CABINET")
    u_height = opt_int(body, "u_height", 42, minimum=1)

    for existing in store.cabinets.values():
        if existing["row_id"] == row_id and existing["cabinet_code"] == cabinet_code:
            raise ApiError("ERR_INVALID_REQUEST", "cabinet_code must be unique within the row")

    if row["row_status"] not in ACCEPTING_POSTURES:
        raise ApiError(
            "ERR_ROW_NOT_ACCEPTING_SPACE",
            "row posture %s does not accept new space" % row["row_status"],
        )

    cabinet = base_row()
    cabinet.update(
        {
            "row_id": row_id,
            "contract_id": None,
            "cabinet_code": cabinet_code,
            "footprint_type": footprint_type,
            "rated_power_kw": rated_power_kw,
            "u_height": u_height,
            "status": "AVAILABLE",
            "allocated_power_kw": 0.0,
            "cooling_load_kw": 0.0,
            "energized_primary_circuit_count": 0,
        }
    )
    store.cabinets[cabinet["id"]] = cabinet
    # An AVAILABLE cabinet occupies no slot, so the row picture is recomputed
    # but does not move.
    recompute_row(row)
    return created(serialize(cabinet))


@bp.route("/cabinets/<cabinet_id>/state", methods=["POST"])
def cabinet_state(cabinet_id):
    authorize("FacilityManager", "ProvisioningEngineer")
    cabinet = refs.path_row(refs.CABINET, cabinet_id)
    body = json_body()
    body_contract = refs.body_fk(body, "contract_id", refs.CONTRACT)
    to_state = req_enum(body, "to_state", CABINET_STATUSES)

    current = cabinet["status"]
    if (current, to_state) not in CABINET_TRANSITIONS:
        raise ApiError(
            "ERR_INVALID_STATE",
            "cabinet cannot move from %s to %s" % (current, to_state),
        )

    row = store.rows.get(cabinet["row_id"])

    if to_state == "RESERVED":
        contract_id = req_string(body, "contract_id")
        contract = body_contract
        if contract["status"] not in ("PENDING_ACTIVATION", "ACTIVE"):
            raise ApiError(
                "ERR_CONTRACT_NOT_ACTIVE",
                "reserving space requires a PENDING_ACTIVATION or ACTIVE contract",
            )
        if row["row_status"] not in ACCEPTING_POSTURES:
            raise ApiError(
                "ERR_ROW_NOT_ACCEPTING_SPACE",
                "row posture %s does not accept new space" % row["row_status"],
            )
        committed = [
            c for c in cabinets_of_contract(contract_id) if c["status"] in COMMIT_CABINET_STATUSES
        ]
        if len(committed) + 1 > contract["committed_cabinet_count"]:
            raise ApiError(
                "ERR_CABINET_COMMIT_EXCEEDED",
                "the contract's committed cabinet count is a hard cap",
            )
        cabinet["contract_id"] = contract_id
        cabinet["status"] = "RESERVED"
        touch(cabinet)
        recompute_row(row, force=True)
        recompute_contract(contract)

    elif to_state == "INSTALLED":
        contract = store.contracts.get(cabinet.get("contract_id"))
        if contract is None or contract["status"] != "ACTIVE":
            raise ApiError("ERR_CONTRACT_NOT_ACTIVE", "installation requires an ACTIVE contract")
        if row["row_status"] not in ACCEPTING_POSTURES:
            raise ApiError(
                "ERR_ROW_NOT_ACCEPTING_SPACE",
                "row posture %s does not accept new space" % row["row_status"],
            )
        cabinet["status"] = "INSTALLED"
        touch(cabinet)
        recompute_row(row)

    else:  # RESERVED -> AVAILABLE, the exact inverse of a reservation
        committed = [
            c
            for c in circuits_of_cabinet(cabinet_id)
            if c["status"] in ("APPROVED", "ENERGIZED")
        ]
        if committed:
            raise ApiError(
                "ERR_INVALID_STATE",
                "release is refused while the cabinet still carries committed power",
            )
        contract = store.contracts.get(cabinet.get("contract_id"))
        cabinet["contract_id"] = None
        cabinet["status"] = "AVAILABLE"
        touch(cabinet)
        recompute_row(row, force=True)
        recompute_contract(contract)

    return ok(serialize(cabinet))


@bp.route("/cabinets/<cabinet_id>", methods=["GET"])
def get_cabinet(cabinet_id):
    actor = authorize(*CABINET_READ_ROLES)
    cabinet = refs.path_row(refs.CABINET, cabinet_id)
    actor.scope_cabinet(cabinet)
    return ok(serialize(cabinet))


@bp.route("/cabinets", methods=["GET"])
def list_cabinets():
    actor = authorize(*CABINET_READ_ROLES)
    actor.require_customer()
    actor.scope_query(("contract", "contract_id"))
    limit, offset = pagination()
    rows = qfilter(
        list(store.cabinets.values()), "row_id", "contract_id", "status", "footprint_type"
    )
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)
