"""Array circuits, storage bins and hardware units (PRD 3.4, 3.5, 3.9)."""

import calc
import errors as E
import services
from errors import ApiError
from flask import Blueprint
from db import db, new_row, touch
from middleware import endpoint
from response import ok_row
from routes.helpers import (
    CONDITION_GRADES,
    HANDLING_STATUSES,
    UNIT_TYPES,
    check_frozen,
    check_restricted,
    get_bin,
    get_circuit,
    get_project,
    get_unit,
    invalid_state,
    paged,
    resolve_fk,
)
from validation import (
    bool_field,
    enum_field,
    enum_query,
    get_body,
    int_field,
    num_field,
    str_field,
    str_list_field,
    str_query,
)

bp = Blueprint("field", __name__)

READ_ROLES = (
    "ProjectCoordinator",
    "SolarContractor",
    "RoofingContractor",
    "SolarOwner",
    "SystemOwner",
)
READ_ROLES_WITH_AHJ = READ_ROLES + ("AHJInspector",)
DISPOSITIONS = ("RETAIN", "SCRAP")


# --------------------------------------------------------------------------
# ArrayCircuit
# --------------------------------------------------------------------------
@bp.route("/reroof/projects/<project_id>/array-circuits", methods=["POST"])
@endpoint("ProjectCoordinator")
def create_circuit(project_id):
    project = get_project(project_id)
    body = get_body()
    circuit_label = str_field(body, "circuit_label", required=True)
    module_count = int_field(body, "module_count", required=True, minimum=1)
    dc_kw = num_field(body, "dc_kw", required=True, exclusive_min=0)

    for existing in services.project_circuits(project["id"]):
        if existing["circuit_label"] == circuit_label:
            raise ApiError(
                E.ERR_DUPLICATE_CIRCUIT_LABEL,
                "circuit_label must be unique within the project",
                409,
            )

    circuit = new_row(
        {
            "project_id": project["id"],
            "circuit_label": circuit_label,
            "module_count": module_count,
            "dc_kw": dc_kw,
            "status": "ENERGIZED",
            "interlock_verified": False,
            "isolation_note": None,
            "isolated_at": None,
            "reenergized_at": None,
        }
    )
    db.circuits[circuit["id"]] = circuit
    return ok_row(circuit, 201)


@bp.route("/reroof/array-circuits/<circuit_id>", methods=["GET"])
@endpoint(*READ_ROLES_WITH_AHJ)
def read_circuit(circuit_id):
    return ok_row(get_circuit(circuit_id))


@bp.route("/reroof/projects/<project_id>/array-circuits", methods=["GET"])
@endpoint(*READ_ROLES)
def list_project_circuits(project_id):
    project = get_project(project_id)
    return paged(services.project_circuits(project["id"]))


@bp.route("/reroof/array-circuits/<circuit_id>/energization", methods=["POST"])
@endpoint("SolarContractor")
def energization(circuit_id):
    circuit = get_circuit(circuit_id)
    project = db.projects.get(circuit["project_id"])
    body = get_body()
    action = enum_field(body, "action", ("DE_ENERGIZE", "RE_ENERGIZE"), required=True)
    interlock_verified = bool_field(body, "interlock_verified", required=True)
    isolation_note = str_field(body, "isolation_note", required=False, default=None)

    snapshot = services.project_snapshot(project)

    if action == "DE_ENERGIZE":
        # Priority 8
        if circuit["status"] == "ENERGIZED":
            if project["phase"] != "AUTHORIZED":
                raise invalid_state(
                    "project phase must be AUTHORIZED to de-energize, not %s"
                    % project["phase"]
                )
        elif circuit["status"] == "ISOLATION_PENDING":
            if not interlock_verified:
                raise invalid_state(
                    "an ISOLATION_PENDING circuit requires a verified interlock"
                )
        else:
            raise invalid_state(
                "cannot de-energize a circuit in %s" % circuit["status"]
            )
        # Priority 10
        check_frozen(project)

        if isolation_note is not None:
            circuit["isolation_note"] = isolation_note
        if interlock_verified:
            circuit["status"] = "ISOLATED"
            circuit["interlock_verified"] = True
            circuit["isolated_at"] = db.now()
            touch(circuit)
            services.rollup_project(project)
            services.evaluate_deenergized(project)
        else:
            circuit["status"] = "ISOLATION_PENDING"
            circuit["interlock_verified"] = False
            touch(circuit)
    else:
        # Priority 8
        if circuit["status"] != "ISOLATED":
            raise invalid_state(
                "cannot re-energize a circuit in %s" % circuit["status"]
            )
        if project["phase"] != "REINSTALL":
            raise invalid_state(
                "project phase must be REINSTALL to re-energize, not %s"
                % project["phase"]
            )
        # Priorities 10 and 11
        check_frozen(project)
        check_restricted(project)
        # Priority 14
        for unit in services.circuit_units(circuit["id"]):
            if unit["handling_status"] == "SCRAPPED":
                continue
            if unit["handling_status"] != "REINSTALLED":
                raise ApiError(
                    E.ERR_CIRCUIT_UNITS_NOT_REINSTALLED,
                    "every non-scrapped unit on the circuit must be REINSTALLED",
                    409,
                )

        if isolation_note is not None:
            circuit["isolation_note"] = isolation_note
        circuit["status"] = "ENERGIZED"
        circuit["reenergized_at"] = db.now()
        touch(circuit)
        services.rollup_project(project)
        services.evaluate_commissioned(project)

    services.commit_project(project, snapshot)
    return ok_row(circuit)


# --------------------------------------------------------------------------
# StorageBin
# --------------------------------------------------------------------------
@bp.route("/reroof/projects/<project_id>/storage-bins", methods=["POST"])
@endpoint("ProjectCoordinator")
def create_bin(project_id):
    project = get_project(project_id)
    body = get_body()
    bin_label = str_field(body, "bin_label", required=True)
    capacity_slots = int_field(body, "capacity_slots", required=True, minimum=1)
    climate_controlled = bool_field(
        body, "climate_controlled", required=False, default=False
    )
    accepts_unit_types = str_list_field(
        body, "accepts_unit_types", UNIT_TYPES, required=False, default=None
    )
    if accepts_unit_types is None:
        accepts_unit_types = list(UNIT_TYPES)

    for existing in services.project_bins(project["id"]):
        if existing["bin_label"] == bin_label:
            raise ApiError(
                E.ERR_DUPLICATE_BIN_LABEL,
                "bin_label must be unique within the project",
                409,
            )

    storage_bin = new_row(
        {
            "project_id": project["id"],
            "bin_label": bin_label,
            "capacity_slots": capacity_slots,
            "climate_controlled": climate_controlled,
            "accepts_unit_types": accepts_unit_types,
            "occupied_slots": 0,
        }
    )
    db.bins[storage_bin["id"]] = storage_bin
    return ok_row(storage_bin, 201)


@bp.route("/reroof/storage-bins/<bin_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_bin(bin_id):
    return ok_row(get_bin(bin_id))


@bp.route("/reroof/projects/<project_id>/storage-bins", methods=["GET"])
@endpoint("ProjectCoordinator", "SolarContractor")
def list_project_bins(project_id):
    project = get_project(project_id)
    return paged(services.project_bins(project["id"]))


# --------------------------------------------------------------------------
# HardwareUnit
# --------------------------------------------------------------------------
@bp.route("/reroof/projects/<project_id>/hardware-units", methods=["POST"])
@endpoint("SolarContractor")
def create_unit(project_id):
    project = get_project(project_id)
    body = get_body()
    circuit = resolve_fk(body, "array_circuit_id", get_circuit)
    array_circuit_id = str_field(body, "array_circuit_id", required=True)
    unit_type = enum_field(body, "unit_type", UNIT_TYPES, required=True)
    manufacturer = str_field(body, "manufacturer", required=True)
    model_code = str_field(body, "model_code", required=True)
    serial_number = str_field(body, "serial_number", required=True)
    rated_watts = int_field(body, "rated_watts", required=True, minimum=1)

    # Priority 15
    if circuit["project_id"] != project["id"]:
        raise ApiError(
            E.ERR_CROSS_PROJECT_REFERENCE,
            "array_circuit_id belongs to a different project",
            422,
        )
    # Priority 25
    for existing in services.project_units(project["id"]):
        if existing["serial_number"] == serial_number:
            raise ApiError(
                E.ERR_DUPLICATE_SERIAL,
                "serial_number must be unique within the project",
                409,
            )

    snapshot = services.project_snapshot(project)
    unit = new_row(
        {
            "project_id": project["id"],
            "array_circuit_id": array_circuit_id,
            "unit_type": unit_type,
            "manufacturer": manufacturer,
            "model_code": model_code,
            "serial_number": serial_number,
            "rated_watts": rated_watts,
            "handling_status": "ON_ROOF",
            "condition_grade": "UNINSPECTED",
            "disposition": None,
            "damage_note": None,
            "storage_bin_id": None,
            "storage_position": None,
            "storage_label": None,
            "warranty_variant": None,
            "warranty_preserved": None,
            "warranty_risk_points": 0,
            "off_roof_days": None,
            "removed_at": None,
            "stored_at": None,
            "reinstalled_at": None,
        }
    )
    db.units[unit["id"]] = unit
    services.rollup_project(project)
    services.commit_project(project, snapshot)
    return ok_row(unit, 201)


@bp.route("/reroof/hardware-units/<unit_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_unit(unit_id):
    return ok_row(get_unit(unit_id))


@bp.route("/reroof/hardware-units", methods=["GET"])
@endpoint(*READ_ROLES)
def list_units():
    project_id = str_query("project_id")
    array_circuit_id = str_query("array_circuit_id")
    storage_bin_id = str_query("storage_bin_id")
    handling_status = enum_query("handling_status", HANDLING_STATUSES)
    condition_grade = enum_query("condition_grade", CONDITION_GRADES)

    rows = []
    for unit in db.units.values():
        if project_id is not None and unit["project_id"] != project_id:
            continue
        if array_circuit_id is not None and unit["array_circuit_id"] != array_circuit_id:
            continue
        if storage_bin_id is not None and unit["storage_bin_id"] != storage_bin_id:
            continue
        if handling_status is not None and unit["handling_status"] != handling_status:
            continue
        if condition_grade is not None and unit["condition_grade"] != condition_grade:
            continue
        rows.append(unit)
    return paged(rows)


@bp.route("/reroof/hardware-units/<unit_id>/removal", methods=["POST"])
@endpoint("SolarContractor")
def remove_unit(unit_id):
    unit = get_unit(unit_id)
    project = db.projects.get(unit["project_id"])
    circuit = db.circuits.get(unit["array_circuit_id"])
    get_body()

    # Priority 8
    if unit["handling_status"] != "ON_ROOF":
        raise invalid_state(
            "cannot remove a unit in %s" % unit["handling_status"]
        )
    # Priority 9
    if circuit is None or circuit["status"] != "ISOLATED":
        raise ApiError(
            E.ERR_CIRCUIT_NOT_ISOLATED,
            "the unit's circuit must be ISOLATED before removal",
            409,
        )
    # Priority 10
    check_frozen(project)

    snapshot = services.project_snapshot(project)
    unit["handling_status"] = "REMOVED"
    unit["removed_at"] = db.now()
    unit["warranty_variant"] = (
        "MANUFACTURER_STRICT"
        if project["warranty_notice_status"] == "FILED"
        else "INSTALLER_LENIENT"
    )
    touch(unit)
    services.rollup_project(project)
    services.commit_project(project, snapshot)
    return ok_row(unit)


@bp.route("/reroof/hardware-units/<unit_id>/storage", methods=["POST"])
@endpoint("SolarContractor")
def store_unit(unit_id):
    unit = get_unit(unit_id)
    project = db.projects.get(unit["project_id"])
    body = get_body()
    storage_bin = resolve_fk(body, "storage_bin_id", get_bin)
    storage_bin_id = str_field(body, "storage_bin_id", required=True)
    storage_position = int_field(
        body, "storage_position", required=False, default=None, minimum=1
    )

    # Priority 8
    if unit["handling_status"] != "REMOVED":
        raise invalid_state("cannot store a unit in %s" % unit["handling_status"])
    # Priority 10
    check_frozen(project)
    # Priority 15
    if storage_bin["project_id"] != unit["project_id"]:
        raise ApiError(
            E.ERR_CROSS_PROJECT_REFERENCE,
            "storage_bin_id belongs to a different project than the unit",
            422,
        )
    # Priority 24
    if unit["unit_type"] not in storage_bin["accepts_unit_types"]:
        raise ApiError(
            E.ERR_BIN_UNIT_TYPE_REJECTED,
            "bin does not accept units of type %s" % unit["unit_type"],
            422,
        )
    # Priority 29
    if storage_bin["occupied_slots"] >= storage_bin["capacity_slots"]:
        raise ApiError(
            E.ERR_BIN_CAPACITY_EXCEEDED, "storage bin is at capacity", 409
        )

    snapshot = services.project_snapshot(project)
    position = (
        storage_position
        if storage_position is not None
        else storage_bin["occupied_slots"] + 1
    )
    unit["storage_bin_id"] = storage_bin_id
    unit["storage_position"] = position
    unit["storage_label"] = "%s-%s" % (storage_bin["bin_label"], position)
    unit["handling_status"] = "STORED"
    unit["stored_at"] = db.now()
    touch(unit)
    services.recompute_bin_occupancy(storage_bin)
    services.rollup_project(project)
    services.evaluate_deck_work(project)
    services.commit_project(project, snapshot)
    return ok_row(unit)


@bp.route("/reroof/hardware-units/<unit_id>/condition-grade", methods=["POST"])
@endpoint("SolarContractor")
def grade_unit(unit_id):
    unit = get_unit(unit_id)
    project = db.projects.get(unit["project_id"])
    body = get_body()
    condition_grade = enum_field(
        body, "condition_grade", ("SERVICEABLE", "DAMAGED"), required=True
    )
    disposition = enum_field(body, "disposition", DISPOSITIONS, required=True)
    damage_note = str_field(body, "damage_note", required=False, default=None)

    # Priority 8
    if unit["handling_status"] not in ("REMOVED", "STORED"):
        raise invalid_state(
            "cannot grade a unit in %s" % unit["handling_status"]
        )
    current = unit["condition_grade"]
    if condition_grade == "SERVICEABLE":
        if disposition != "RETAIN":
            raise invalid_state("grading SERVICEABLE requires a RETAIN disposition")
        if current != "UNINSPECTED":
            raise invalid_state(
                "cannot grade SERVICEABLE from condition %s" % current
            )
    else:
        if disposition == "RETAIN":
            if current not in ("UNINSPECTED", "SERVICEABLE"):
                raise invalid_state(
                    "cannot grade DAMAGED from condition %s" % current
                )
        else:
            if current not in ("UNINSPECTED", "SERVICEABLE", "DAMAGED"):
                raise invalid_state(
                    "cannot scrap a unit whose condition is %s" % current
                )

    snapshot = services.project_snapshot(project)
    was_stored = unit["handling_status"] == "STORED"
    unit["condition_grade"] = condition_grade
    unit["disposition"] = disposition
    if damage_note is not None:
        unit["damage_note"] = damage_note
    if condition_grade == "DAMAGED" and disposition == "SCRAP":
        unit["handling_status"] = "SCRAPPED"
    touch(unit)

    if unit["handling_status"] == "SCRAPPED" and was_stored:
        services.recompute_bin_occupancy(db.bins.get(unit["storage_bin_id"]))
    services.rollup_project(project)
    services.evaluate_deck_work(project)
    services.commit_project(project, snapshot)
    return ok_row(unit)


@bp.route("/reroof/hardware-units/<unit_id>/reinstall", methods=["POST"])
@endpoint("SolarContractor")
def reinstall_unit(unit_id):
    unit = get_unit(unit_id)
    project = db.projects.get(unit["project_id"])
    circuit = db.circuits.get(unit["array_circuit_id"])
    get_body()

    # Priority 8
    if unit["handling_status"] != "STORED":
        raise invalid_state(
            "cannot reinstall a unit in %s" % unit["handling_status"]
        )
    if project["phase"] != "REINSTALL":
        raise invalid_state(
            "project phase must be REINSTALL to reinstall, not %s" % project["phase"]
        )
    # Priority 9
    if circuit is None or circuit["status"] != "ISOLATED":
        raise ApiError(
            E.ERR_CIRCUIT_NOT_ISOLATED,
            "the unit's circuit must still be ISOLATED to reinstall",
            409,
        )
    # Priorities 10 and 11
    check_frozen(project)
    check_restricted(project)
    # Priority 12
    if not (
        project["ownership_model"] == "HOST_OWNED"
        or project["warranty_notice_status"] == "FILED"
    ):
        raise ApiError(
            E.ERR_WARRANTY_NOTICE_MISSING,
            "the manufacturer warranty notice must be FILED before reinstall",
            409,
        )
    # Priority 13
    if unit["condition_grade"] not in ("SERVICEABLE", "REPLACED"):
        raise ApiError(
            E.ERR_UNIT_NOT_SERVICEABLE,
            "unit condition_grade must be SERVICEABLE or REPLACED to reinstall",
            409,
        )

    snapshot = services.project_snapshot(project)
    now = db.now()
    unit["handling_status"] = "REINSTALLED"
    unit["reinstalled_at"] = now
    off_roof_days = 0
    if unit["removed_at"] is not None:
        off_roof_days = (now.date() - unit["removed_at"].date()).days
    unit["off_roof_days"] = off_roof_days
    preserved, points = calc.unit_warranty_preservation(
        unit, db.bins.get(unit["storage_bin_id"]), off_roof_days
    )
    unit["warranty_preserved"] = preserved
    unit["warranty_risk_points"] = points
    touch(unit)

    services.recompute_bin_occupancy(db.bins.get(unit["storage_bin_id"]))
    services.rollup_project(project)
    services.evaluate_commissioned(project)
    services.commit_project(project, snapshot)
    return ok_row(unit)
