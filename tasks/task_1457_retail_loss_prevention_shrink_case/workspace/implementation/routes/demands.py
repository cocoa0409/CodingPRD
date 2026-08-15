"""Civil demand endpoints (PRD §3.6)."""

from datetime import timedelta

from flask import Blueprint, request

from db import db, clock_now, fmt_iso, parse_iso
from middleware import get_auth, require_role, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.validate import (
    body, req_string, req_int, opt_int, req_enum, get_or_404,
)
from services.entities import make_civil_demand, pub, touch
from services.calculations import (
    compute_demand_amounts, demand_outstanding, recompute_case_restitution_status,
)
from errors import (
    err403, err409, err412,
    ERR_INVALID_STATE_TRANSITION, ERR_NOT_CASE_ASSIGNEE,
    ERR_STALE_CASE_VERSION, ERR_SOD_DEMAND_ISSUER, ERR_DEMAND_WINDOW_CLOSED,
    ERR_BASIS_NOT_ALLOWED, ERR_WRITE_OFF_CAP_EXCEEDED,
)

bp = Blueprint("demands", __name__)


@bp.route("/civil-demands", methods=["POST"])
def create_demand():
    user_id, role = get_auth()
    require_role(role, {"LPAnalyst"})
    data = body()
    case_id = req_string(data, "case_id")
    basis = req_enum(data, "basis", ["STATUTORY", "ACTUAL_LOSS"])
    expected_case_version = req_int(data, "expected_case_version")
    priors_offense_count = opt_int(data, "priors_offense_count", default=0, minimum=0)
    recovery_cost_cents = opt_int(data, "recovery_cost_cents", default=0, minimum=0)

    case = get_or_404(db.cases, case_id, "case")
    # ownership (priority 3): assignee only
    if case.get("assigned_analyst_id") != user_id:
        raise err403(ERR_NOT_CASE_ASSIGNEE,
                     "Actor is not the case's assigned analyst")
    # cross-entity state gate (priority 7)
    if case["status"] not in ("INTERVIEWED", "ADJUDICATING"):
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Demand drafting requires case INTERVIEWED or ADJUDICATING")
    # OCC (priority 8)
    if expected_case_version != case["version"]:
        raise err412(ERR_STALE_CASE_VERSION,
                     "expected_case_version does not match the case's current "
                     "version")
    # fiscal (priority 12): STATUTORY forbidden on EMPLOYEE-subject cases
    if basis == "STATUTORY" and case["subject_type"] == "EMPLOYEE":
        raise err409(ERR_BASIS_NOT_ALLOWED,
                     "STATUTORY basis is not allowed on EMPLOYEE-subject cases")

    # supersede any existing DRAFT
    for d in db.civil_demands.values():
        if d["case_id"] == case_id and d["status"] == "DRAFT":
            d["status"] = "CANCELLED"
            touch(d)

    demand = make_civil_demand(case_id, basis, priors_offense_count,
                               recovery_cost_cents, user_id)
    db.civil_demands[demand["id"]] = demand

    # drafting bumps the case version (OCC anchor)
    touch(case)
    return success_object(pub(demand), status=201)


@bp.route("/civil-demands", methods=["GET"])
def list_demands():
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    case_id = _q("case_id")
    status = _q("status")
    basis = _q("basis")
    items = sorted(db.civil_demands.values(),
                   key=lambda d: (d["created_at"], d["id"]))
    if case_id is not None:
        items = [d for d in items if d["case_id"] == case_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    if basis is not None:
        items = [d for d in items if d["basis"] == basis]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([pub(d) for d in page], limit, offset, total)


@bp.route("/civil-demands/<demand_id>", methods=["GET"])
def get_demand(demand_id):
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    demand = get_or_404(db.civil_demands, demand_id, "civil demand")
    return success_object(pub(demand))


@bp.route("/civil-demands/<demand_id>/issue", methods=["POST"])
def issue_demand(demand_id):
    user_id, role = get_auth()
    require_role(role, {"LPManager"})
    demand = get_or_404(db.civil_demands, demand_id, "civil demand")
    case = db.cases.get(demand["case_id"])
    if demand["status"] != "DRAFT":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Demand must be DRAFT to issue")
    if case is None or case["status"] not in ("INTERVIEWED", "ADJUDICATING"):
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Case must be INTERVIEWED or ADJUDICATING")
    # SoD (priority 9)
    if demand["created_by"] == user_id:
        raise err409(ERR_SOD_DEMAND_ISSUER,
                     "Demand issuer must differ from the drafting analyst")
    # temporal (priority 10): within adjudicated_at + 60d when adjudicated
    if case.get("adjudicated_at"):
        if clock_now() > parse_iso(case["adjudicated_at"]) + timedelta(days=60):
            raise err409(ERR_DEMAND_WINDOW_CLOSED,
                         "More than 60 days have passed since adjudication")

    merch = case["total_loss_cents"]
    if case["subject_type"] == "EMPLOYEE" and case.get("employee_id"):
        emp = db.employees[case["employee_id"]]
        priors = emp["prior_substantiated_count"]
    else:
        priors = demand["priors_offense_count"]
    penalty, amount_due = compute_demand_amounts(
        demand["basis"], merch, priors, demand["recovery_cost_cents"])
    demand["merchandise_loss_cents"] = merch
    demand["statutory_penalty_cents"] = penalty
    demand["amount_due_cents"] = amount_due
    demand["outstanding_cents"] = demand_outstanding(demand)
    demand["issued_at"] = fmt_iso(clock_now())
    demand["status"] = "ISSUED"
    touch(demand)

    recompute_case_restitution_status(case)
    if demand["outstanding_cents"] > 0:
        case["restitution_status"] = "OUTSTANDING"
    touch(case)
    return success_object(pub(demand))


@bp.route("/civil-demands/<demand_id>/write-off", methods=["POST"])
def write_off_demand(demand_id):
    user_id, role = get_auth()
    require_role(role, {"LPManager"})
    demand = get_or_404(db.civil_demands, demand_id, "civil demand")
    if demand["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Demand must be ISSUED or PARTIALLY_PAID to write off")
    if demand["outstanding_cents"] > 50000:
        raise err409(ERR_WRITE_OFF_CAP_EXCEEDED,
                     "outstanding_cents exceeds the 50000 write-off cap")
    demand["status"] = "WRITTEN_OFF"
    touch(demand)
    case = db.cases.get(demand["case_id"])
    if case is not None:
        recompute_case_restitution_status(case)
        touch(case)
    return success_object(pub(demand))


@bp.route("/civil-demands/<demand_id>/cancel", methods=["POST"])
def cancel_demand(demand_id):
    user_id, role = get_auth()
    require_role(role, {"LPManager"})
    demand = get_or_404(db.civil_demands, demand_id, "civil demand")
    if demand["status"] != "DRAFT":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Demand must be DRAFT to cancel")
    demand["status"] = "CANCELLED"
    touch(demand)
    return success_object(pub(demand))


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None
