"""Equipment unit (fleet) endpoints."""
from flask import Blueprint

from core import (
    LOGISTICS_READERS,
    ROLE_MANAGER,
    ROLE_THERAPIST,
    ApiError,
    add_days,
    authenticate,
    base_row,
    db,
    enum_filter,
    now,
    paginate,
    pagination,
    respond,
    sorted_rows,
    str_filter,
    today,
    touch,
)
from domain import get_branch, get_equipment_unit
from serial import equipment_unit_out
from validate import Field, validate

bp = Blueprint("equipment_units", __name__)

EQUIPMENT_CLASSES = (
    "STATIONARY_CONCENTRATOR",
    "PORTABLE_CONCENTRATOR",
    "LIQUID_RESERVOIR",
    "LIQUID_PORTABLE",
    "COMPRESSED_CYLINDER",
)
UNIT_STATUSES = ("IN_STOCK", "RESERVED", "DEPLOYED", "IN_QUARANTINE", "RETIRED")
LIQUID_CLASSES = ("LIQUID_RESERVOIR", "LIQUID_PORTABLE")

CREATE_FIELDS = [
    Field("branch_id", "string", required=True, min_len=1),
    Field("serial_number", "string", required=True, min_len=1, max_len=40),
    Field("model_code", "string", required=True, min_len=1, max_len=40),
    Field("equipment_class", "enum", required=True, enum=EQUIPMENT_CLASSES),
    Field("max_continuous_lpm", "number", required=True, minimum="0.5", maximum="15.0"),
    Field("max_pulse_setting", "integer", default=0, minimum=0, maximum=9),
    Field("pm_interval_days", "integer", default=365, minimum=30, maximum=1095),
    Field("next_pm_due_date", "date", required=True),
    Field("replaces_unit_id", "string", nullable=True, default=None, min_len=1),
]


@bp.post("/equipment-units")
def create_unit():
    authenticate((ROLE_MANAGER,))
    data = validate(CREATE_FIELDS)
    branch = get_branch(data["branch_id"])
    replaces = None
    if data["replaces_unit_id"] is not None:
        replaces = get_equipment_unit(data["replaces_unit_id"])
    for existing in db.equipment_units.values():
        if existing["serial_number"] == data["serial_number"]:
            raise ApiError("ERR_DUPLICATE_SERIAL_NUMBER")
    if replaces is not None and replaces["status"] not in (
        "IN_QUARANTINE",
        "RETIRED",
    ):
        raise ApiError("ERR_REPLACED_UNIT_NOT_REPLACEABLE")
    if data["equipment_class"] in LIQUID_CLASSES and not branch[
        "liquid_oxygen_certified"
    ]:
        raise ApiError("ERR_BRANCH_NOT_LIQUID_CERTIFIED")
    row = base_row()
    row.update(
        {
            "branch_id": branch["id"],
            "serial_number": data["serial_number"],
            "model_code": data["model_code"],
            "equipment_class": data["equipment_class"],
            "max_continuous_lpm": data["max_continuous_lpm"],
            "max_pulse_setting": data["max_pulse_setting"],
            "pm_interval_days": data["pm_interval_days"],
            "next_pm_due_date": data["next_pm_due_date"],
            "status": "IN_STOCK",
            "replaces_unit_id": replaces["id"] if replaces is not None else None,
            "recall_remediated_at": None,
            "quarantine_reason": "NONE",
        }
    )
    db.equipment_units[row["id"]] = row
    return respond(equipment_unit_out(row), 201)


@bp.get("/equipment-units")
def list_units():
    authenticate(LOGISTICS_READERS)
    branch_id = str_filter("branch_id")
    replaces_id = str_filter("replaces_unit_id")
    model_code = str_filter("model_code")
    equipment_class = enum_filter("equipment_class", EQUIPMENT_CLASSES)
    status = enum_filter("status", UNIT_STATUSES)
    limit, offset = pagination()
    rows = sorted_rows(db.equipment_units.values())
    if branch_id is not None:
        rows = [r for r in rows if r["branch_id"] == branch_id]
    if replaces_id is not None:
        rows = [r for r in rows if r["replaces_unit_id"] == replaces_id]
    if model_code is not None:
        rows = [r for r in rows if r["model_code"] == model_code]
    if equipment_class is not None:
        rows = [r for r in rows if r["equipment_class"] == equipment_class]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, equipment_unit_out)


@bp.get("/equipment-units/<unit_id>")
def read_unit(unit_id):
    authenticate(LOGISTICS_READERS)
    return respond(equipment_unit_out(get_equipment_unit(unit_id)))


@bp.post("/equipment-units/<unit_id>/service")
def service_unit(unit_id):
    """IN_QUARANTINE -> IN_STOCK; restamps PM and records recall remediation."""
    authenticate((ROLE_THERAPIST,))
    unit = get_equipment_unit(unit_id)
    if unit["status"] != "IN_QUARANTINE":
        raise ApiError("ERR_INVALID_STATE")
    unit["next_pm_due_date"] = add_days(today(), unit["pm_interval_days"]).isoformat()
    unit["quarantine_reason"] = "NONE"
    unit["status"] = "IN_STOCK"
    for notice in sorted_rows(db.recall_notices.values()):
        if notice["model_code"] == unit["model_code"] and notice["status"] in (
            "OPEN",
            "IN_REMEDIATION",
        ):
            unit["recall_remediated_at"] = now()
            break
    touch(unit)
    return respond(equipment_unit_out(unit))


@bp.post("/equipment-units/<unit_id>/retire")
def retire_unit(unit_id):
    authenticate((ROLE_MANAGER,))
    unit = get_equipment_unit(unit_id)
    if unit["status"] not in ("IN_QUARANTINE", "IN_STOCK"):
        raise ApiError("ERR_INVALID_STATE")
    unit["status"] = "RETIRED"
    touch(unit)
    return respond(equipment_unit_out(unit))
