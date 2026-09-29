from flask import Blueprint

from db import db
from errors import fail
from middleware import endpoint, body
from response import created, ok
from routes.common import get_facility, get_interconnect, paged_list, resolve_refs
from services import derive

bp = Blueprint("interconnects", __name__)

READ_ROLES = ["PlatformAdmin", "ProjectOperator", "PipelineScheduler",
              "ProgramAdministrator", "FinanceController"]


@bp.post("/interconnect-agreements")
@endpoint(["PipelineScheduler"])
def create_interconnect():
    b = body()
    (facility,) = resolve_refs(b, (("facility_id", get_facility),))
    row = db.new_row({
        "facility_id": facility["id"],
        "pipeline_operator_name": b.string("pipeline_operator_name"),
        "max_h2s_ppm": b.number("max_h2s_ppm", 1, gt=0),
        "max_moisture_lb_per_mmscf": b.number("max_moisture_lb_per_mmscf", 1, gt=0),
        "max_co2_pct": b.number("max_co2_pct", 1, gt=0),
        "min_hhv_btu_per_scf": b.number("min_hhv_btu_per_scf", 2, gt=0),
        "max_hourly_injection_mmbtu": b.number("max_hourly_injection_mmbtu", 3, gt=0),
        "ramp_buffer_minutes": b.integer("ramp_buffer_minutes", ge=0),
        "nomination_lead_hours": b.integer("nomination_lead_hours", ge=0),
        "status": "ACTIVE",
        "curtailment_count": 0,
    })
    db.interconnects[row["id"]] = row
    return created(derive.ser_interconnect(row))


@bp.get("/interconnect-agreements")
@endpoint(READ_ROLES)
def list_interconnects():
    return paged_list(db.interconnects, derive.ser_interconnect,
                      ("facility_id", "status"))


@bp.get("/interconnect-agreements/<interconnect_id>")
@endpoint(READ_ROLES)
def read_interconnect(interconnect_id):
    return ok(derive.ser_interconnect(get_interconnect(interconnect_id)))


@bp.post("/interconnect-agreements/<interconnect_id>/status-change")
@endpoint(["PipelineScheduler"])
def status_change_interconnect(interconnect_id):
    interconnect = get_interconnect(interconnect_id)
    b = body()
    action = b.enum("action", ("REINSTATE", "TERMINATE"))
    b.string("reason", required=False)

    if action == "REINSTATE":
        if interconnect["status"] != "SUSPENDED":
            fail("ERR_INVALID_STATE",
                 "Only a SUSPENDED interconnection agreement may be reinstated.")
        interconnect["status"] = "ACTIVE"
        interconnect["curtailment_count"] = 0
    else:
        if interconnect["status"] not in ("ACTIVE", "SUSPENDED"):
            fail("ERR_INVALID_STATE",
                 "Only an ACTIVE or SUSPENDED agreement may be terminated.")
        if interconnect["status"] == "ACTIVE":
            for nom in db.nominations.values():
                if nom["interconnect_id"] == interconnect["id"] and \
                        nom["status"] in ("NOMINATED", "CONFIRMED"):
                    fail("ERR_INVALID_STATE",
                         "Live schedule commitments remain on this agreement.")
        interconnect["status"] = "TERMINATED"
    db.touch(interconnect)
    return ok(derive.ser_interconnect(interconnect))
