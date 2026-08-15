"""BranchOffice endpoints (PRD 3.1)."""
from flask import Blueprint, request

from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public
from util import add_months, today
from validate import get_body, opt_int, req_str

bp = Blueprint("branches", __name__)

DEFAULT_CYCLE_MONTHS = 12


@bp.post("/branches")
def create_branch():
    authorized(["FirmAdmin"])
    body = get_body()
    name = req_str(body, "name")
    region = req_str(body, "region")
    cycle = opt_int(body, "inspection_cycle_months", default=DEFAULT_CYCLE_MONTHS,
                    positive=True)
    rec = new_record("branches", {
        "name": name,
        "region": region,
        "inspection_cycle_months": cycle,
        "open_findings_count": 0,
        "high_severity_open_count": 0,
        "sd_rep_count": 0,
        "posture": "NORMAL",
        "risk_score": 0,
        "next_inspection_due_date": add_months(today(), cycle).isoformat(),
    })
    return success_object(public(rec), status=201)


@bp.get("/branches")
def list_branches():
    return list_response("branches", filters={"region": request.args.get("region")})


@bp.get("/branches/<rid>")
def get_branch(rid):
    return get_one("branches", rid)
