"""AdequacyEvaluation endpoints incl. finalize and penalty-summary."""

from flask import Blueprint

import db
import errors
import helpers
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.finalize import finalize_evaluation

bp = Blueprint("evaluations", __name__)

EVAL_STATUSES = {"OPEN", "FINALIZED"}


@bp.route("/network/evaluations", methods=["POST"])
@require_roles("NetworkManager")
def create_evaluation(user_id, role):
    body = helpers.get_body()
    measurement_period = helpers.req_str(body, "measurement_period")
    period_start_date = helpers.req_str(body, "period_start_date")
    period_end_date = helpers.req_str(body, "period_end_date")
    ps = helpers.parse_date(period_start_date, "period_start_date")
    pe = helpers.parse_date(period_end_date, "period_end_date")
    if pe < ps:
        raise errors.err_invalid("period_end_date must be >= period_start_date")
    for e in db.evaluations.values():
        if e["status"] == "OPEN":
            raise errors.err_evaluation_already_open()
    rec = {
        "measurement_period": measurement_period,
        "period_start_date": period_start_date, "period_end_date": period_end_date,
        "status": "OPEN", "total_penalty_cents": 0, "finalized_at": None,
        "deficiency_penalties_cents": 0, "error_penalties_cents": 0,
        "late_correction_penalties_cents": 0, "accrual_events": [],
    }
    helpers.stamp_new(rec)
    db.evaluations[rec["id"]] = rec
    return success_object(helpers.ser_evaluation(rec), 201)


@bp.route("/network/evaluations", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_evaluations(user_id, role):
    limit, offset = helpers.get_pagination()
    status = helpers.query_enum("status", EVAL_STATUSES)
    items = list(db.evaluations.values())
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, total = helpers.paginate(items, limit, offset)
    return success_list([helpers.ser_evaluation(e) for e in page], limit, offset, total)


@bp.route("/network/evaluations/<eid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_evaluation(user_id, role, eid):
    rec = db.evaluations.get(eid)
    if rec is None:
        raise errors.err_evaluation_not_found()
    return success_object(helpers.ser_evaluation(rec))


@bp.route("/network/evaluations/<eid>/finalize", methods=["POST"])
@require_roles("NetworkManager")
def finalize(user_id, role, eid):
    rec = db.evaluations.get(eid)
    if rec is None:
        raise errors.err_evaluation_not_found()
    if rec["status"] != "OPEN":
        raise errors.err_evaluation_invalid_state()
    ps = helpers.parse_date(rec["period_start_date"], "period_start_date")
    pe = helpers.parse_date(rec["period_end_date"], "period_end_date")
    for p in db.probes.values():
        if p["status"] != "SCHEDULED":
            continue
        rd = helpers.parse_date(p["requested_date"], "requested_date")
        if ps <= rd <= pe:
            raise errors.err_unrecorded_probes()
    finalize_evaluation(rec)
    return success_object(helpers.ser_evaluation(rec))


@bp.route("/network/evaluations/<eid>/penalty-summary", methods=["GET"])
@require_roles("NetworkManager", "ComplianceOfficer", "Regulator")
def penalty_summary(user_id, role, eid):
    rec = db.evaluations.get(eid)
    if rec is None:
        raise errors.err_evaluation_not_found()
    rows = []
    for ev in rec.get("accrual_events", []):
        d = db.deficiencies.get(ev["deficiency_id"])
        rows.append({
            "kind": "DEFICIENCY_ACCRUAL",
            "deficiency_id": ev["deficiency_id"],
            "region_id": d["region_id"] if d else None,
            "specialty": d["specialty"] if d else None,
            "amount_cents": ev["accrual_cents"],
        })
    data = {
        "deficiency_penalties_cents": rec.get("deficiency_penalties_cents", 0),
        "error_penalties_cents": rec.get("error_penalties_cents", 0),
        "late_correction_penalties_cents": rec.get("late_correction_penalties_cents", 0),
        "total_penalty_cents": rec["total_penalty_cents"],
        "rows": rows,
    }
    return success_object(data)
