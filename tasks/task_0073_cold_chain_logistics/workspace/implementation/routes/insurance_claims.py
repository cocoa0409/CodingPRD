"""Insurance claim endpoints."""

from flask import Blueprint, request

from clock import clock
from db import db, new_id
from errors import err
from middleware import require_roles
from response import object_response
from serializers import insurance_claim as ser_ic
from validators import require_dict, require_int, require_str


bp = Blueprint("insurance_claims", __name__)


def _bump(row):
    row["updated_at"] = clock.now_iso()
    row["version"] = row.get("version", 0) + 1


@bp.post("/insurance-claims")
@require_roles("CARRIER")
def report_claim():
    body = require_dict(request.get_json(silent=True) or {})
    task_id = require_str(body.get("task_id"), field="task_id", min_len=1)
    decision_id = require_str(body.get("decision_id"), field="decision_id", min_len=1)
    if not db.tasks.exists(task_id):
        err("ERR_REFERENCE_NOT_FOUND", "task_id not found.")
    if not db.decisions.exists(decision_id):
        err("ERR_REFERENCE_NOT_FOUND", "decision_id not found.")
    task = db.tasks.get(task_id)
    decision = db.decisions.get(decision_id)
    if decision["task_id"] != task_id:
        err("ERR_REFERENCE_NOT_FOUND", "decision does not belong to task.")
    if decision["status"] != "FINALIZED":
        err("ERR_DECISION_NOT_FINALIZED", "Decision is not FINALIZED.")
    requested = body.get("requested_amount_cents")
    require_int(requested, field="requested_amount_cents", min_val=0)
    vehicle = db.vehicles.get(task.get("vehicle_id"))
    if vehicle is None:
        err("ERR_INVALID_STATE", "Task has no vehicle.")
    if requested > vehicle["insured_cap_cents"]:
        err("ERR_INSURANCE_CAP_EXCEEDED", "requested_amount_cents exceeds insured_cap_cents.")
    now_iso = clock.now_iso()
    row = {
        "id": new_id(),
        "task_id": task_id,
        "decision_id": decision_id,
        "requested_amount_cents": int(requested),
        "assessed_amount_cents": 0,
        "payout_amount_cents": 0,
        "subrogation_recovered_cents": 0,
        "status": "REPORTED",
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.claims.put(row)
    return object_response(ser_ic(row), status_code=201)


@bp.post("/insurance-claims/<claim_id>/prepare-evidence")
@require_roles("CARRIER")
def prepare_evidence(claim_id):
    row = db.claims.get(claim_id)
    if row is None:
        err("ERR_NOT_FOUND", "InsuranceClaim not found.")
    if row["status"] != "REPORTED":
        err("ERR_INVALID_STATE", "Claim must be REPORTED to prepare evidence.")
    row["status"] = "EVIDENCE_PREP"
    _bump(row)
    return object_response(ser_ic(row))


@bp.post("/insurance-claims/<claim_id>/assess")
@require_roles("INSURANCE_ADJUSTER")
def assess_claim(claim_id):
    with db.global_lock:
        row = db.claims.get(claim_id)
        if row is None:
            err("ERR_NOT_FOUND", "InsuranceClaim not found.")
        if row["status"] not in {"EVIDENCE_PREP", "NEGOTIATING"}:
            err("ERR_INVALID_STATE", "Claim must be EVIDENCE_PREP or NEGOTIATING to assess.")
        body = require_dict(request.get_json(silent=True) or {})
        assessed = body.get("assessed_amount_cents")
        if (not isinstance(assessed, int) or isinstance(assessed, bool)
                or assessed < 0 or assessed > row["requested_amount_cents"]):
            err("ERR_AMOUNT_INVALID", "assessed_amount_cents out of range.")
        row["assessed_amount_cents"] = int(assessed)
        row["status"] = "ASSESSMENT"
        _bump(row)
    return object_response(ser_ic(row))


@bp.post("/insurance-claims/<claim_id>/negotiate")
@require_roles("CARRIER", "INSURANCE_ADJUSTER")
def negotiate_claim(claim_id):
    row = db.claims.get(claim_id)
    if row is None:
        err("ERR_NOT_FOUND", "InsuranceClaim not found.")
    if row["status"] != "ASSESSMENT":
        err("ERR_INVALID_STATE", "Claim must be ASSESSMENT to negotiate.")
    row["status"] = "NEGOTIATING"
    _bump(row)
    return object_response(ser_ic(row))


@bp.post("/insurance-claims/<claim_id>/pay")
@require_roles("INSURANCE_ADJUSTER")
def pay_claim(claim_id):
    with db.global_lock:
        row = db.claims.get(claim_id)
        if row is None:
            err("ERR_NOT_FOUND", "InsuranceClaim not found.")
        if row["status"] != "ASSESSMENT":
            err("ERR_INVALID_STATE", "Claim must be ASSESSMENT to pay.")
        if row["assessed_amount_cents"] <= 0:
            err("ERR_INVALID_STATE", "assessed_amount_cents must be > 0 to pay.")
        row["payout_amount_cents"] = row["assessed_amount_cents"]
        row["status"] = "PAID_OUT"
        _bump(row)
    return object_response(ser_ic(row))


@bp.post("/insurance-claims/<claim_id>/reject")
@require_roles("INSURANCE_ADJUSTER")
def reject_claim(claim_id):
    with db.global_lock:
        row = db.claims.get(claim_id)
        if row is None:
            err("ERR_NOT_FOUND", "InsuranceClaim not found.")
        if row["status"] != "ASSESSMENT":
            err("ERR_INVALID_STATE", "Claim must be ASSESSMENT to reject.")
        body = require_dict(request.get_json(silent=True) or {})
        require_str(body.get("reason"), field="reason", min_len=1, max_len=500)
        row["payout_amount_cents"] = 0
        row["status"] = "REJECTED"
        _bump(row)
    return object_response(ser_ic(row))


@bp.post("/insurance-claims/<claim_id>/subrogate")
@require_roles("INSURANCE_ADJUSTER")
def subrogate(claim_id):
    with db.global_lock:
        row = db.claims.get(claim_id)
        if row is None:
            err("ERR_NOT_FOUND", "InsuranceClaim not found.")
        if row["status"] != "PAID_OUT":
            err("ERR_INVALID_STATE", "Claim must be PAID_OUT to subrogate.")
        body = require_dict(request.get_json(silent=True) or {})
        amount = body.get("subrogation_recovered_cents")
        if (not isinstance(amount, int) or isinstance(amount, bool)
                or amount < 0 or amount > row["payout_amount_cents"]):
            err("ERR_AMOUNT_INVALID", "subrogation_recovered_cents out of range.")
        row["subrogation_recovered_cents"] = int(amount)
        row["payout_amount_cents"] = max(0, row["payout_amount_cents"] - int(amount))
        row["status"] = "SUBROGATION"
        _bump(row)
    return object_response(ser_ic(row))


@bp.post("/insurance-claims/<claim_id>/close")
@require_roles("INSURANCE_ADJUSTER")
def close_claim(claim_id):
    with db.global_lock:
        row = db.claims.get(claim_id)
        if row is None:
            err("ERR_NOT_FOUND", "InsuranceClaim not found.")
        if row["status"] not in {"SUBROGATION", "PAID_OUT"}:
            err("ERR_INVALID_STATE", "Claim must be SUBROGATION or PAID_OUT to close.")
        row["status"] = "CLOSED"
        _bump(row)
    return object_response(ser_ic(row))


@bp.get("/insurance-claims/<claim_id>")
@require_roles("CARRIER", "COMPLIANCE_OFFICER", "INSURANCE_ADJUSTER")
def get_claim(claim_id):
    row = db.claims.get(claim_id)
    if row is None:
        err("ERR_NOT_FOUND", "InsuranceClaim not found.")
    return object_response(ser_ic(row))
