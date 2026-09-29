"""Construction draw administration and the disbursement waterfall
(PRD section 3.7)."""

from flask import Blueprint

import auth
import calc
import envelope
import resolve
import serializers
import shapes
import store
from auth import INSTITUTION_REP, LOAN_SERVICER, READ_ALL
from errors import ApiError
from routes.loans import DRAW_PHASE

bp = Blueprint("draws", __name__)

PROJECT_PHASES = ("SITE_WORK", "FOUNDATION", "SHELL", "SANCTUARY_FITOUT",
                  "SCHOOL_FITOUT", "FINAL")


@bp.route("/draw-requests", methods=["POST"])
def create_draw():
    ctx = auth.authenticate((LOAN_SERVICER, INSTITUTION_REP))
    b = shapes.body()
    loan = resolve.loan(b.get("loan_id"))
    auth.scope(ctx, auth.owner_of_loan(loan))
    if loan is None:
        shapes.req_id_field(b, "loan_id")
    phase = shapes.req_enum(b, "project_phase", PROJECT_PHASES)
    amount = shapes.req_int(b, "requested_amount_cents", exclusive_minimum=0)
    percent = shapes.req_ratio(b, "percent_complete", gt=0, le=1)
    # ladder 20
    if loan["servicing_status"] not in DRAW_PHASE:
        raise ApiError("ERR_LOAN_NOT_IN_DRAW_PHASE")
    # ladder 49
    if amount > calc.free_commitment(loan):
        raise ApiError("ERR_DRAW_EXCEEDS_COMMITMENT")

    row = store.base_record()
    row.update({
        "loan_id": loan["id"],
        "project_phase": phase,
        "requested_amount_cents": amount,
        "percent_complete": percent,
        "approved_amount_cents": None,
        "retainage_cents": None,
        "interest_reserve_applied_cents": None,
        "inspection_fee_cents": None,
        "net_disbursed_cents": None,
        "completion_pct_at_disbursement": None,
        "status": "SUBMITTED",
        "inspector_note": None,
        "void_reason": None,
        "disbursement_date": None,
        "reinstatement_note": None,
    })
    store.draw_requests[row["id"]] = row
    store.mark_created(row)
    return envelope.created(serializers.draw_request(row))


@bp.route("/draw-requests/<draw_request_id>", methods=["GET"])
def get_draw(draw_request_id):
    ctx = auth.authenticate(READ_ALL)
    row = resolve.draw_request(draw_request_id)
    auth.scope(ctx, auth.owner_of_draw(row))
    return envelope.ok(serializers.draw_request(row))


@bp.route("/draw-requests", methods=["GET"])
def list_draws():
    auth.authenticate(READ_ALL)
    rows = envelope.filter_rows(list(store.draw_requests.values()),
                                {"loan_id": "loan_id",
                                 "status": "status",
                                 "project_phase": "project_phase"})
    return envelope.listing(envelope.sort_created_asc(rows),
                            serializers.draw_request)


@bp.route("/draw-requests/<draw_request_id>/approve", methods=["POST"])
def approve_draw(draw_request_id):
    auth.authenticate((LOAN_SERVICER,))
    draw = resolve.draw_request(draw_request_id)
    b = shapes.body()
    approved = shapes.req_int(b, "approved_amount_cents", minimum=0)
    note = shapes.req_str(b, "inspector_note")
    if approved > draw["requested_amount_cents"]:
        shapes.bad("approved_amount_cents",
                   "may not exceed requested_amount_cents")
    loan = store.loans[draw["loan_id"]]
    # ladder 20
    if loan["servicing_status"] not in DRAW_PHASE:
        raise ApiError("ERR_LOAN_NOT_IN_DRAW_PHASE")
    # ladder 21
    if draw["status"] != "SUBMITTED":
        raise ApiError("ERR_DRAW_INVALID_STATE")
    # ladder 49
    if approved > calc.free_commitment(loan):
        raise ApiError("ERR_DRAW_EXCEEDS_COMMITMENT")

    draw["approved_amount_cents"] = approved
    draw["inspector_note"] = note
    draw["status"] = "APPROVED"
    loan["reserved_draw_cents"] += approved
    store.touch(draw)
    store.touch(loan)
    return envelope.ok(serializers.draw_request(draw))


@bp.route("/draw-requests/<draw_request_id>/disburse", methods=["POST"])
def disburse_draw(draw_request_id):
    auth.authenticate((LOAN_SERVICER,))
    draw = resolve.draw_request(draw_request_id)
    b = shapes.body()
    date_raw, _date_dt = shapes.opt_dt(b, "disbursement_date")
    loan = store.loans[draw["loan_id"]]
    # ladder 20
    if loan["servicing_status"] not in DRAW_PHASE:
        raise ApiError("ERR_LOAN_NOT_IN_DRAW_PHASE")
    # ladder 21
    if draw["status"] != "APPROVED":
        raise ApiError("ERR_DRAW_INVALID_STATE")
    # ladder 45
    for covenant in store.children(store.covenants, "loan_id", loan["id"]):
        if covenant["status"] not in ("COMPLIANT", "WAIVED"):
            raise ApiError("ERR_DRAW_BLOCKED_BY_COVENANT_BREACH")

    approved = draw["approved_amount_cents"]
    result = calc.waterfall(loan, approved)
    # ladder 50
    if result["net_disbursed_cents"] <= 0:
        raise ApiError("ERR_DRAW_NET_NONPOSITIVE")

    first_disbursement = loan["disbursed_principal_cents"] == 0
    draw.update(result)
    draw["status"] = "DISBURSED"
    draw["disbursement_date"] = date_raw
    loan["reserved_draw_cents"] -= approved
    loan["disbursed_principal_cents"] += approved
    loan["undrawn_commitment_cents"] -= approved
    loan["outstanding_principal_cents"] += approved
    loan["retainage_held_cents"] += result["retainage_cents"]
    loan["interest_reserve_shortfall_cents"] -= \
        result["interest_reserve_applied_cents"]
    if first_disbursement and loan["servicing_status"] == "PENDING_FIRST_DRAW":
        loan["servicing_status"] = "CONSTRUCTION_DRAW"
    store.touch(draw)
    store.touch(loan)
    return envelope.ok(serializers.draw_request(draw))


@bp.route("/draw-requests/<draw_request_id>/reject", methods=["POST"])
def reject_draw(draw_request_id):
    auth.authenticate((LOAN_SERVICER,))
    draw = resolve.draw_request(draw_request_id)
    b = shapes.body()
    note = shapes.req_str(b, "inspector_note")
    # ladder 21
    if draw["status"] != "SUBMITTED":
        raise ApiError("ERR_DRAW_INVALID_STATE")
    draw["inspector_note"] = note
    draw["status"] = "REJECTED"
    store.touch(draw)
    return envelope.ok(serializers.draw_request(draw))


@bp.route("/draw-requests/<draw_request_id>/void", methods=["POST"])
def void_draw(draw_request_id):
    auth.authenticate((LOAN_SERVICER,))
    draw = resolve.draw_request(draw_request_id)
    b = shapes.body()
    reason = shapes.req_str(b, "void_reason")
    loan = store.loans[draw["loan_id"]]
    # ladder 20
    if loan["servicing_status"] not in DRAW_PHASE:
        raise ApiError("ERR_LOAN_NOT_IN_DRAW_PHASE")
    # ladder 21
    if draw["status"] != "DISBURSED":
        raise ApiError("ERR_DRAW_INVALID_STATE")

    approved = draw["approved_amount_cents"]
    loan["disbursed_principal_cents"] -= approved
    loan["undrawn_commitment_cents"] += approved
    loan["retainage_held_cents"] -= draw["retainage_cents"]
    loan["interest_reserve_shortfall_cents"] += \
        draw["interest_reserve_applied_cents"]
    loan["outstanding_principal_cents"] -= approved
    draw["void_reason"] = reason
    draw["status"] = "VOIDED"
    if loan["disbursed_principal_cents"] == 0 and \
            loan["servicing_status"] == "CONSTRUCTION_DRAW":
        loan["servicing_status"] = "PENDING_FIRST_DRAW"
    store.touch(draw)
    store.touch(loan)
    return envelope.ok(serializers.draw_request(draw))


@bp.route("/draw-requests/<draw_request_id>/reinstate", methods=["POST"])
def reinstate_draw(draw_request_id):
    auth.authenticate((LOAN_SERVICER,))
    draw = resolve.draw_request(draw_request_id)
    b = shapes.body()
    note = shapes.req_str(b, "reinstatement_note")
    loan = store.loans[draw["loan_id"]]
    # ladder 21 — the from-state, and the posture the revert arm requires
    if draw["status"] != "SUSPENDED":
        raise ApiError("ERR_DRAW_INVALID_STATE")
    if loan["risk_posture"] not in ("OPEN", "WATCH"):
        raise ApiError("ERR_DRAW_INVALID_STATE")
    # ladder 49
    approved = draw["approved_amount_cents"]
    if approved > calc.free_commitment(loan):
        raise ApiError("ERR_DRAW_EXCEEDS_COMMITMENT")

    draw["status"] = "APPROVED"
    draw["reinstatement_note"] = note
    loan["reserved_draw_cents"] += approved
    store.touch(draw)
    store.touch(loan)
    return envelope.ok(serializers.draw_request(draw))
