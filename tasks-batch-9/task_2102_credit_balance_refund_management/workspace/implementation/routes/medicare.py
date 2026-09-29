"""Medicare 60-day repayment obligations (PRD 3.11)."""
from flask import Blueprint, request

import auth
import clock
import db
import derive
import response
import validation as v
from errors import ApiError

bp = Blueprint("medicare", __name__)


@bp.get("/medicare-obligations")
@auth.require(*auth.ALL_ROLES)
def list_obligations():
    rows = db.ordered(list(db.medicare_obligations.values()))
    for name in ("credit_balance_id", "payer_id", "state"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    return response.page(rows, derive.medicare_obligation)


@bp.get("/medicare-obligations/<obligation_id>")
@auth.require(*auth.ALL_ROLES)
def read_obligation(obligation_id):
    return response.ok(derive.medicare_obligation(v.must_exist("obligation", obligation_id)))


@bp.post("/medicare-obligations/<obligation_id>/report")
@auth.require(auth.COMPLIANCE_OFFICER)
def report_obligation(obligation_id):
    ob = v.must_exist("obligation", obligation_id)    # rank 3
    data = v.body()
    report_reference = v.req_str(data, "report_reference")   # rank 6
    if ob["state"] not in ("OPEN", "LATE"):                  # rank 13
        raise ApiError("ERR_OBLIGATION_INVALID_STATE")

    derive.refresh_obligation(ob)
    ob["report_reference"] = report_reference
    ob["reported_at"] = clock.now()
    # Destination is decided by lateness recomputed against the logical clock at
    # report time: day 60 is compliant, day 61 is one day late.
    if ob["days_late"] == 0:
        ob["state"] = "REPORTED"
        ob["penalty_cents"] = 0
    else:
        ob["state"] = "REPORTED_LATE"
    db.touch(ob)
    return response.ok(derive.medicare_obligation(ob))
