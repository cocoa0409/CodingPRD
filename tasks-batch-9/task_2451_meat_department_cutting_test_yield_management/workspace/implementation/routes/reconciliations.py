"""Period shrink reconciliation: draft, post, dispute, redraft (PRD §3.9)."""

from flask import Blueprint

import errors
import middleware as mw
import validation as v
from calc import rhu
from db import db, make, mark, sort_rows
from errors import ApiError
from response import list_response, object_response
from services import reconciliation as recon

bp = Blueprint("reconciliations", __name__)

BASES = ("YIELD_MODEL", "PHYSICAL_COUNT")

RECON_ACTION_ROLES = {
    "POST": (mw.MEAT_MANAGER,),
    "DISPUTE": (mw.PRICING_ANALYST,),
    "REDRAFT": (mw.PRICING_ANALYST,),
}

DECLARED_TRANSITIONS = {
    "POST": ("DRAFT",),
    "DISPUTE": ("POSTED",),
    "REDRAFT": ("DISPUTED",),
}


@bp.route("/meat-ops/shrink-reconciliations", methods=["POST"])
def create_reconciliation():
    mw.authenticate((mw.PRICING_ANALYST,))
    payload = v.body()

    department_id = v.field_id(payload, "department_id", required=True)
    start_raw, _ = v.field_date(payload, "period_start_date", required=True)
    end_raw, _ = v.field_date(payload, "period_end_date", required=True)
    if end_raw < start_raw:
        v.bad("'period_end_date' must not be earlier than 'period_start_date'")
    basis = v.field_enum(payload, "basis", BASES, required=True)

    department = v.resolve("department", department_id)

    row = make("ShrinkReconciliation", {
        "department_id": department_id,
        "period_start_date": start_raw,
        "period_end_date": end_raw,
        "basis": basis,
        "expected_salable_lb": rhu(0, 2),
        "physical_salable_lb": rhu(0, 2),
        "variance_lb": rhu(0, 2),
        "variance_pct": rhu(0, 4),
        "within_tolerance": False,
        "markdown_dollars_cents": 0,
        "shrink_dollars_cents": 0,
        "override_reason": None,
        "dispute_reason": None,
        "posted_by_user_id": None,
        "status": "DRAFT",
    })
    recon.compute_figures(row, department)
    db.shrink_reconciliations[row["id"]] = row
    return object_response(row, 201)


@bp.route("/meat-ops/shrink-reconciliations/<row_id>", methods=["GET"])
def get_reconciliation(row_id):
    mw.authenticate(mw.RECONCILIATION_READERS)
    return object_response(v.resolve("shrink_reconciliation", row_id))


@bp.route("/meat-ops/departments/<department_id>/shrink-reconciliations",
          methods=["GET"])
def list_department_reconciliations(department_id):
    mw.authenticate(mw.RECONCILIATION_READERS)
    v.resolve("department", department_id)
    limit, offset = v.pagination()
    basis = v.query_filter("basis")
    status = v.query_filter("status")
    rows = []
    for row in db.shrink_reconciliations.values():
        if row["department_id"] != department_id:
            continue
        if basis is not None and row["basis"] != basis:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return list_response(sort_rows(rows), limit, offset)


@bp.route("/meat-ops/shrink-reconciliations/<row_id>/transitions", methods=["POST"])
def reconciliation_transition(row_id):
    user_id, role = mw.authenticate((mw.MEAT_MANAGER, mw.PRICING_ANALYST))
    row = v.resolve("shrink_reconciliation", row_id)
    payload = v.body()

    action = v.field_enum(payload, "action", tuple(RECON_ACTION_ROLES), required=True)
    override_reason = v.field_str(payload, "override_reason", min_len=1, max_len=280)
    dispute_reason = v.field_str(payload, "dispute_reason",
                                required=(action == "DISPUTE"),
                                min_len=1, max_len=280)

    mw.check_action_role(role, action, RECON_ACTION_ROLES)

    if row["status"] not in DECLARED_TRANSITIONS[action]:
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "%s is not a declared transition out of %s"
                       % (action, row["status"]))

    department = db.departments[row["department_id"]]

    if action == "POST":
        suspended = [plan for plan
                     in recon.plans_in_period(row["department_id"],
                                              row["period_start_date"],
                                              row["period_end_date"],
                                              ("SUSPENDED",))]
        if suspended:
            raise ApiError(errors.ERR_PERIOD_HAS_SUSPENDED_PLAN, 422,
                           "A case plan inside the period is SUSPENDED")
        if not row["within_tolerance"] and override_reason is None:
            raise ApiError(errors.ERR_SHRINK_EXCEEDS_TOLERANCE, 422,
                           "An out-of-tolerance reconciliation needs an "
                           "override_reason")
        if override_reason is not None:
            row["override_reason"] = override_reason
        row["posted_by_user_id"] = user_id
        row["status"] = "POSTED"
        mark(row)
        recon.close_reconciled_purchases(row)

    elif action == "DISPUTE":
        row["dispute_reason"] = dispute_reason
        row["status"] = "DISPUTED"
        mark(row)

    else:                                          # REDRAFT
        row["posted_by_user_id"] = None
        row["status"] = "DRAFT"
        recon.compute_figures(row, department)
        mark(row)

    return object_response(row)
