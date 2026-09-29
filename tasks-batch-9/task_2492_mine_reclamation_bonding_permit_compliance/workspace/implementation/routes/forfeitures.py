"""Forfeiture, state-conducted reclamation and the four-link cascade (PRD 3.7)."""

from flask import Blueprint

import calculations as calc
import constants as C
import engine
import serialization as ser
from db import D, ZERO, base_row, days, db, money, now
from engine import bump
from errors import ApiError
from response import created_response, object_response
from routes._shared import (
    collection_filtered,
    require_permit_operator,
    require_permit_status,
    require_state,
)
from validation import (
    authorize,
    enum_field,
    get_body,
    lookup,
    number_field,
    resolve,
    str_field,
)

bp = Blueprint("forfeitures", __name__)

LIST_FILTERS = [
    ("permit_id", "permit_id", None),
    ("status", "status", C.PROCEEDING_STATUSES),
]


@bp.post("/mining/forfeiture-proceedings")
def create_proceeding():
    authorize([C.ROLE_PROGRAM_DIRECTOR])
    body = get_body()
    permit_id = str_field(body, "permit_id")
    initiation_reason = enum_field(body, "initiation_reason", C.INITIATION_REASONS)

    permit = resolve(db.permits, permit_id, "ERR_PERMIT_NOT_FOUND")

    # Band 10 — the permit's state, then the one-proceeding-per-permit rule.
    require_permit_status(permit, C.PERMIT_STATUSES_FORFEITURE)
    if engine.has_proceeding(permit["id"]):
        raise ApiError(
            "ERR_PERMIT_HAS_OPEN_PROCEEDING",
            "A forfeiture proceeding already exists for this permit.",
        )

    row = base_row()
    row.update(
        {
            "permit_id": permit_id,
            "initiation_reason": initiation_reason,
            "status": "INITIATED",
            "contest_note": None,
            "contest_deadline": row["created_at"] + days(C.CONTEST_WINDOW_DAYS),
            "forfeited_bond_amount": ZERO,
            "state_reclamation_cost_estimate": ZERO,
            "actual_cost_incurred": ZERO,
            "completion_pct": ZERO,
            "deficiency_amount": ZERO,
            "surplus_amount": ZERO,
            "finalized_at": None,
            "completed_at": None,
        }
    )
    db.proceedings[row["id"]] = row

    # The posture lands in FORFEITURE_PENDING, the highest band.
    engine.recompute_posture(permit)
    bump(permit)

    return created_response(ser.proceeding_out(row))


@bp.get("/mining/forfeiture-proceedings/<proceeding_id>")
def get_proceeding(proceeding_id):
    authorize(C.ROLES_OP_STAFF_PUBLIC)
    row = lookup(db.proceedings, proceeding_id, "ERR_PROCEEDING_NOT_FOUND")
    return object_response(ser.proceeding_out(row))


@bp.get("/mining/forfeiture-proceedings")
def list_proceedings():
    authorize(C.ROLES_OP_STAFF_PUBLIC)
    return collection_filtered(db.proceedings.values(), LIST_FILTERS, ser.proceeding_out)


@bp.post("/mining/forfeiture-proceedings/<proceeding_id>/contest")
def contest(proceeding_id):
    user_id, role = authorize([C.ROLE_OPERATOR])
    body = get_body()
    contest_note = str_field(body, "contest_note")

    row = lookup(db.proceedings, proceeding_id, "ERR_PROCEEDING_NOT_FOUND")
    permit = db.permits[row["permit_id"]]

    # Band 6, band 9, then band 12.
    require_permit_operator(role, user_id, permit)
    require_state(row, "status", ["INITIATED"], "ERR_PROCEEDING_STATE_INVALID")
    if now() > row["contest_deadline"]:
        raise ApiError(
            "ERR_CONTEST_WINDOW_CLOSED",
            "The window for contesting this proceeding has closed.",
        )

    row["status"] = "CONTESTED"
    row["contest_note"] = contest_note
    bump(row)
    return object_response(ser.proceeding_out(row))


@bp.post("/mining/forfeiture-proceedings/<proceeding_id>/finalize")
def finalize(proceeding_id):
    authorize([C.ROLE_PROGRAM_DIRECTOR])
    body = get_body()
    state_estimate = number_field(body, "state_reclamation_cost_estimate", ge=0)

    row = lookup(db.proceedings, proceeding_id, "ERR_PROCEEDING_NOT_FOUND")
    permit = db.permits[row["permit_id"]]

    # Band 9, then band 12 — the boundary instant belongs to the operator.
    require_state(row, "status", ["INITIATED", "CONTESTED"], "ERR_PROCEEDING_STATE_INVALID")
    if not now() > row["contest_deadline"]:
        raise ApiError(
            "ERR_CONTEST_WINDOW_OPEN",
            "The contest window is still open; the proceeding cannot yet be finalised.",
        )

    # The forfeited figure is observed before the permit transition zeroes it.
    forfeited = money(permit["bond_held_amount"])
    deficiency, surplus = calc.forfeiture_finalization_settlement(state_estimate, forfeited)

    # Link 1 — the proceeding's own transition.
    row["status"] = "FINAL"
    row["finalized_at"] = now()
    row["state_reclamation_cost_estimate"] = money(state_estimate)
    row["forfeited_bond_amount"] = forfeited
    row["deficiency_amount"] = deficiency
    row["surplus_amount"] = surplus
    bump(row)

    # Links 2, 3 and 4.
    engine.forfeiture_cascade(permit)

    return object_response(ser.proceeding_out(row))


@bp.post("/mining/forfeiture-proceedings/<proceeding_id>/record-state-reclamation")
def record_state_reclamation(proceeding_id):
    authorize([C.ROLE_PROGRAM_DIRECTOR])
    body = get_body()
    actual_cost = number_field(body, "actual_cost_incurred", ge=0)
    completion_pct = number_field(body, "completion_pct", ge=0, le=100)

    row = lookup(db.proceedings, proceeding_id, "ERR_PROCEEDING_NOT_FOUND")

    # Band 9 — progress is only recorded against a finalised proceeding.
    require_state(row, "status", ["FINAL"], "ERR_PROCEEDING_STATE_INVALID")

    row["actual_cost_incurred"] = money(actual_cost)
    row["completion_pct"] = completion_pct

    if D(completion_pct) == 100:
        deficiency, surplus = calc.forfeiture_completion_settlement(
            actual_cost, row["forfeited_bond_amount"]
        )
        row["deficiency_amount"] = deficiency
        row["surplus_amount"] = surplus
        row["status"] = "COMPLETED"
        row["completed_at"] = now()
        bump(row)

        permit = db.permits[row["permit_id"]]
        operator = db.operators.get(permit["operator_id"])
        if operator is not None and surplus > 0:
            operator["refund_due_amount"] = money(
                D(operator["refund_due_amount"]) + surplus
            )
            bump(operator)
        if deficiency > 0:
            engine.reclassify_site_as_legacy(permit, row)
    else:
        bump(row)

    return object_response(ser.proceeding_out(row))
