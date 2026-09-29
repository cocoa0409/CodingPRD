"""Information sharing agreements."""
import datetime

from flask import Blueprint, g, request

import auth
import calc
import envelope
import serialize
import store
import validate as V
from auth import endpoint
from errors import ApiError

bp = Blueprint("isa", __name__)


@bp.post("/plan-admin/information-sharing-agreements")
@endpoint(["PlanSponsorAdmin"])
def create_isa():
    body = V.body_of(request)
    plan_id = V.req_str(body, "plan_id")
    vendor_id = V.req_str(body, "vendor_id")
    effective_from = V.req_date(body, "effective_from")
    effective_through = V.req_date(body, "effective_through")
    if effective_through < effective_from:
        raise V.bad("effective_through must fall on or after effective_from.")
    shares = {key: V.opt_bool(body, key, True) for key in
              ("shares_loan_data", "shares_hardship_data", "shares_contribution_data")}

    plan = auth.plan(plan_id)                      # rung 5
    auth.vendor(vendor_id)                         # rung 5
    auth.own_plan(plan)                            # rung 6
    if plan["status"] not in ("ACTIVE", "FROZEN"):  # rung 10
        raise ApiError("ERR_PLAN_NOT_ACTIVE", "The governing plan is %s." % plan["status"])

    gap = datetime.timedelta(days=calc.ISA_MINIMUM_GAP_DAYS)
    for other in store.isas_for(plan_id, vendor_id):    # rung 32
        if other["status"] == "TERMINATED":
            continue
        other_from = calc.parse_iso_date(other["effective_from"])
        other_through = calc.parse_iso_date(other["effective_through"])
        if effective_from <= other_through + gap and other_from <= effective_through + gap:
            raise ApiError("ERR_ISA_INTERVAL_OVERLAP",
                           "Agreements for this plan and vendor must be separated by at "
                           "least one clear day.")

    row = store.common_fields()
    row.update({
        "plan_id": plan_id,
        "vendor_id": vendor_id,
        "status": "PENDING",
        "effective_from": effective_from.isoformat(),
        "effective_through": effective_through.isoformat(),
        "data_current_through_date": None,
    })
    row.update(shares)
    store.isas[row["id"]] = row
    return envelope.created(serialize.isa(row))


@bp.get("/plan-admin/information-sharing-agreements/<row_id>")
@endpoint(auth.ALL_ROLES)
def get_isa(row_id):
    return envelope.ok(serialize.isa(auth.isa(row_id)))


@bp.get("/plan-admin/information-sharing-agreements")
@endpoint(auth.ALL_ROLES)
def list_isas():
    args = request.args
    limit, offset = V.pagination(args)
    plan_id = args.get("plan_id")
    vendor_id = args.get("vendor_id")
    status = V.query_enum(args, "status", calc.ISA_STATUSES)
    items = store.rows(store.isas)
    if plan_id:
        items = [a for a in items if a["plan_id"] == plan_id]
    if vendor_id:
        items = [a for a in items if a["vendor_id"] == vendor_id]
    if status:
        items = [a for a in items if a["status"] == status]
    page, total = envelope.paginate(items, limit, offset)
    return envelope.listing([serialize.isa(a) for a in page], limit, offset, total)


ISA_TRANSITIONS = {
    ("PENDING", "ACTIVE"),
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "TERMINATED"),
    ("SUSPENDED", "TERMINATED"),
    ("PENDING", "TERMINATED"),
}


@bp.post("/plan-admin/information-sharing-agreements/<row_id>/status")
@endpoint(["PlanSponsorAdmin"])
def isa_status(row_id):
    body = V.body_of(request)
    to_status = V.req_enum(body, "to_status", calc.ISA_STATUSES)
    agreement = auth.isa(row_id)
    auth.own_isa(agreement)
    if (agreement["status"], to_status) not in ISA_TRANSITIONS:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Agreement cannot move from %s to %s." % (agreement["status"], to_status))
    if agreement["status"] == "PENDING" and to_status == "ACTIVE":
        plan = store.plans.get(agreement["plan_id"])
        if not plan or plan["status"] not in ("ACTIVE", "FROZEN"):
            raise ApiError("ERR_PLAN_NOT_ACTIVE",
                           "The governing plan is not ACTIVE or FROZEN.")
    agreement["status"] = to_status
    store.touch(agreement)
    return envelope.ok(serialize.isa(agreement))


@bp.post("/plan-admin/information-sharing-agreements/<row_id>/data-feed")
@endpoint(["VendorRepresentative"])
def isa_data_feed(row_id):
    body = V.body_of(request)
    through = V.req_date(body, "data_current_through_date")
    agreement = auth.isa(row_id)
    auth.own_isa(agreement)
    if agreement["status"] == "TERMINATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A terminated agreement cannot receive a data feed.")
    if through > store.today():                      # rung 29
        raise ApiError("ERR_DATE_IN_FUTURE", "data_current_through_date is in the future.")
    agreement["data_current_through_date"] = through.isoformat()
    if agreement["status"] == "SUSPENDED":
        agreement["status"] = "ACTIVE"
    store.touch(agreement)
    return envelope.ok(serialize.isa(agreement))
