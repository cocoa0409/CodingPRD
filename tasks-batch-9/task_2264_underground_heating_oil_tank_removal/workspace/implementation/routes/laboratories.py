"""Laboratory registration and read."""

from flask import Blueprint

from db import create
from middleware import authenticate, body, opt_bool, opt_int, req_str, resolve
from response import entity_response

bp = Blueprint("laboratories", __name__)


@bp.post("/laboratories")
def create_laboratory():
    authenticate(("ComplianceOfficer",))
    payload = body()
    lab_name = req_str(payload, "lab_name")
    accredited = opt_bool(payload, "accredited", True)
    turnaround = opt_int(payload, "committed_turnaround_hours", 72, exclusive_min=0)
    holding = opt_int(payload, "holding_time_hours", 336, exclusive_min=0)
    concurrency = opt_int(payload, "max_concurrent_analyses", 2, minimum=1)
    lab = create("laboratories", {
        "lab_name": lab_name,
        "accredited": accredited,
        "committed_turnaround_hours": turnaround,
        "holding_time_hours": holding,
        "max_concurrent_analyses": concurrency,
    })
    return entity_response(lab, 201)


@bp.get("/laboratories/<laboratory_id>")
def read_laboratory(laboratory_id):
    authenticate(("ProjectCoordinator", "FieldTechnician", "LabAnalyst",
                  "ComplianceOfficer"))
    return entity_response(resolve("laboratories", laboratory_id))
