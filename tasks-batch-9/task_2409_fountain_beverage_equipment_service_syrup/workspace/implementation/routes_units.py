"""Dispenser units: placement, the service dimension and confirmed returns
(PRD 3.3)."""

from flask import Blueprint

from cascade import confirm_return_cascade
from core import (
    CALIBRATION_STATUSES,
    UNIT_STATUSES,
    body,
    db,
    endpoint,
    f_dt,
    f_str,
    fail,
    get_agreement,
    get_outlet,
    get_unit,
    new_id,
    ok,
    ok_list,
    pagination,
    paginate,
    q_str,
    require,
    sort_rows,
    stamp_new,
    touch,
)
from serialize import ser_unit

bp = Blueprint("units", __name__)


# ---------------------------------------------------------------------------
# POST /fountain-network/dispenser-units
# ---------------------------------------------------------------------------
@bp.post("/dispenser-units")
@endpoint(["NetworkAdmin"])
def create_unit():
    payload = body()
    # rung 3
    outlet_id = f_str(payload, "outlet_id", required=True)
    agreement_id = f_str(payload, "agreement_id", required=True)
    serial_number = f_str(payload, "serial_number", required=True)
    model_code = f_str(payload, "model_code", required=True)
    installed_raw, installed_dt = f_dt(payload, "installed_at", required=True)
    # rung 5 - declared body-reference order: outlet_id then agreement_id
    outlet = get_outlet(outlet_id)
    agreement = get_agreement(agreement_id)
    # rung 18
    require(
        agreement["outlet_id"] == outlet["id"],
        "ERR_OUTLET_AGREEMENT_MISMATCH",
        "The submitted outlet_id does not match the agreement's outlet.",
    )
    # rung 30
    for row in db.units.values():
        if row["serial_number"] == serial_number:
            fail("ERR_DUPLICATE_SERIAL_NUMBER", "Serial number %s already exists." % serial_number)

    unit = {
        "id": new_id(),
        "outlet_id": outlet["id"],
        "agreement_id": agreement["id"],
        "serial_number": serial_number,
        "model_code": model_code,
        "installed_at": installed_raw,
        "_installed_at": installed_dt,
        "status": "IN_SERVICE",
        "calibration_status": "UNVERIFIED",
        "lifetime_dispensed_gallons": 0,
        "gallons_at_last_filter_change": 0,
        "brix_ratio_last_measured": None,
        "_total_ounces": 0,
    }
    stamp_new(unit)
    db.units[unit["id"]] = unit
    return ok(ser_unit(unit), 201)


# ---------------------------------------------------------------------------
# GET /fountain-network/dispenser-units/{id}
# ---------------------------------------------------------------------------
@bp.get("/dispenser-units/<uid>")
@endpoint(["NetworkAdmin", "SupplyPlanner", "ServiceTechnician", "ComplianceOfficer", "OutletManager"])
def read_unit(uid):
    return ok(ser_unit(get_unit(uid)))


# ---------------------------------------------------------------------------
# GET /fountain-network/dispenser-units
# ---------------------------------------------------------------------------
@bp.get("/dispenser-units")
@endpoint(["NetworkAdmin", "SupplyPlanner", "ServiceTechnician", "ComplianceOfficer"])
def list_units():
    limit, offset = pagination()
    outlet_id = q_str("outlet_id")
    agreement_id = q_str("agreement_id")
    status = q_str("status", enum=UNIT_STATUSES)
    calibration_status = q_str("calibration_status", enum=CALIBRATION_STATUSES)
    rows = list(db.units.values())
    if outlet_id is not None:
        rows = [r for r in rows if r["outlet_id"] == outlet_id]
    if agreement_id is not None:
        rows = [r for r in rows if r["agreement_id"] == agreement_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if calibration_status is not None:
        rows = [r for r in rows if r["calibration_status"] == calibration_status]
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([ser_unit(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# POST /fountain-network/dispenser-units/{id}/service-hold
# ---------------------------------------------------------------------------
@bp.post("/dispenser-units/<uid>/service-hold")
@endpoint(["ServiceTechnician"])
def unit_service_hold(uid):
    payload = body()
    # rung 3
    action = f_str(payload, "action", required=True, enum=("PLACE", "RELEASE"))
    # rung 4
    unit = get_unit(uid)

    if action == "PLACE":
        # rung 9
        require(
            unit["status"] == "IN_SERVICE",
            "ERR_INVALID_STATE_TRANSITION",
            "Only an IN_SERVICE unit can be placed on service hold.",
        )
        unit["status"] = "SERVICE_HOLD"
    else:
        # rung 9
        require(
            unit["status"] == "SERVICE_HOLD",
            "ERR_INVALID_STATE_TRANSITION",
            "Only a unit on SERVICE_HOLD can be released.",
        )
        # rung 15
        overdue_sanitation = any(
            t["dispenser_unit_id"] == unit["id"]
            and t["task_type"] == "SANITATION"
            and t["status"] == "OVERDUE"
            for t in db.tasks.values()
        )
        require(
            not overdue_sanitation,
            "ERR_SANITATION_OVERDUE",
            "A SANITATION task of this unit is OVERDUE.",
        )
        unit["status"] = "IN_SERVICE"
    touch(unit)
    return ok(ser_unit(unit))


# ---------------------------------------------------------------------------
# POST /fountain-network/dispenser-units/{id}/confirm-return
# ---------------------------------------------------------------------------
@bp.post("/dispenser-units/<uid>/confirm-return")
@endpoint(["NetworkAdmin"])
def unit_confirm_return(uid):
    # rung 4
    unit = get_unit(uid)
    # rung 9
    require(
        unit["status"] == "RECALL_STAGED",
        "ERR_INVALID_STATE_TRANSITION",
        "Only a RECALL_STAGED unit can be confirmed returned.",
    )
    unit["status"] = "RETURNED"
    touch(unit)
    confirm_return_cascade(unit)
    return ok(ser_unit(unit))
