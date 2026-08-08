"""Violation read + abatement routes — PRD §3.4."""

from flask import Blueprint

import config
import domain
import serialize
import store
import validate as V
from auth import authenticate, require_owns_establishment
from envelope import array_response, send, watch
from errors import ApiError

bp = Blueprint("violations", __name__)

READ_ROLES = ["HealthOfficer", "Inspector", "RecordsClerk", "EstablishmentOperator"]


def _establishment_of(violation):
    inspection = store.inspections.get(violation["inspection_id"])
    if inspection is None:
        return None, None
    return inspection, store.establishments.get(inspection["establishment_id"])


@bp.get("/body-art/violations/<violation_id>")
def read_violation(violation_id):
    authenticate(READ_ROLES)
    rec = V.get_violation(violation_id)
    return send(lambda: serialize.violation(rec), 200)


@bp.get("/body-art/violations")
def list_violations():
    authenticate(READ_ROLES)
    limit, offset = V.pagination()
    inspection_id = V.filter_string("inspection_id")
    status = V.filter_enum("status", config.VIOLATION_STATUSES)
    severity = V.filter_enum("severity", config.VIOLATION_SEVERITIES)

    rows = store.sorted_rows(store.violations)
    if inspection_id is not None:
        rows = [r for r in rows if r["inspection_id"] == inspection_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    page, total = V.paginate(rows, limit, offset)
    return array_response([serialize.violation(r) for r in page], limit, offset, total)


@bp.post("/body-art/violations/<violation_id>/correction")
def submit_correction(violation_id):
    caller = authenticate(["EstablishmentOperator"])
    rec = V.get_violation(violation_id)
    data = V.body()
    correction_note = V.req_string(data, "correction_note", 1)

    inspection, est = _establishment_of(rec)
    owner_id = inspection["establishment_id"] if inspection is not None else None
    require_owns_establishment(caller, owner_id)

    if rec["status"] != "ISSUED":
        raise ApiError("ERR_VIOLATION_STATE_INVALID")

    watch(rec)
    rec["status"] = "CORRECTION_SUBMITTED"
    rec["correction_note"] = correction_note
    rec["correction_submitted_at"] = store.now()
    return send(lambda: serialize.violation(rec), 200)


@bp.post("/body-art/violations/<violation_id>/correction-decision")
def decide_correction(violation_id):
    authenticate(["Inspector"])
    rec = V.get_violation(violation_id)
    data = V.body()
    decision = V.req_enum(data, "decision", config.CORRECTION_DECISIONS)

    if rec["status"] != "CORRECTION_SUBMITTED":
        raise ApiError("ERR_VIOLATION_STATE_INVALID")

    _inspection, est = _establishment_of(rec)
    watch(rec)

    if decision == "VERIFY":
        rec["status"] = "VERIFIED"
        if est is not None:
            domain.recompute_counters(est)
            domain.recompute_risk_and_posture(est)
    else:
        if store.now() < rec["abatement_due_at"]:
            rec["status"] = "ISSUED"
            rec["correction_note"] = None
            rec["correction_submitted_at"] = None
        else:
            rec["status"] = "ESCALATED"
            if est is not None:
                domain.recompute_risk_and_posture(est)
    return send(lambda: serialize.violation(rec), 200)
