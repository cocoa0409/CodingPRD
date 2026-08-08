"""GET /reports/facility-adherence -- the facility medication-adherence index."""

from flask import Blueprint, request

import calc
from envelope import ok
from errors import ApiError
from ladder import Ctx

bp = Blueprint("reports", __name__)


@bp.get("/reports/facility-adherence")
def facility_adherence():
    ctx = Ctx(roles=("HealthServicesAdmin",))

    def facility_required():
        value = request.args.get("facility_code")
        if value is None or value == "":
            raise ApiError("ERR_VALIDATION", "facility_code is required")
    ctx.at(8, facility_required, sub=0)
    ctx.run()

    facility_code = request.args["facility_code"]
    order_count, index = calc.facility_adherence_index(facility_code)
    return ok({
        "facility_code": facility_code,
        "order_count": order_count,
        "adherence_index": index,
    })
