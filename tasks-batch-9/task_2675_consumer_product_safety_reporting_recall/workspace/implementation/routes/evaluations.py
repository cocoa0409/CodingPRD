"""Reportability evaluation and the internal escalation clock (PRD 3.3)."""

from flask import Blueprint

import auth
import calc
import lookups
import responses
import shapes
import store
from errors import raise_error

bp = Blueprint("evaluations", __name__)

STANDARD_BASES = ("DEFECT", "UNREASONABLE_RISK", "NONCOMPLIANCE",
                  "VOLUNTARY_STANDARD_FAILURE")
EVALUATION_STATUSES = ("OPEN", "IN_REVIEW", "REPORTABLE", "NOT_REPORTABLE")
DETERMINATIONS = ("REPORTABLE", "NOT_REPORTABLE")
LIVE_EVALUATION_STATUSES = ("OPEN", "IN_REVIEW", "REPORTABLE")

READ_ROLES = ("ProgramAdmin", "ComplianceOfficer", "SafetyDirector",
              "PenaltyCounsel")


@bp.route("/reportability-evaluations/<evaluation_id>", methods=["GET"])
def get_evaluation(evaluation_id):
    auth.authorize(*READ_ROLES)
    return responses.object_response(lookups.find("evaluation", evaluation_id))


@bp.route("/reportability-evaluations", methods=["GET"])
def list_evaluations():
    auth.authorize(*READ_ROLES)
    limit, offset = shapes.pagination()
    hazard_pattern_id = shapes.q_str("hazard_pattern_id")
    product_model_id = shapes.q_str("product_model_id")
    status = shapes.q_enum("status", EVALUATION_STATUSES)
    standard_basis = shapes.q_enum("standard_basis", STANDARD_BASES)
    escalation_breached = shapes.q_bool("escalation_breached")

    def keep(row):
        if hazard_pattern_id is not None and row["hazard_pattern_id"] != hazard_pattern_id:
            return False
        if product_model_id is not None and row["product_model_id"] != product_model_id:
            return False
        if status is not None and row["status"] != status:
            return False
        if standard_basis is not None and row["standard_basis"] != standard_basis:
            return False
        if (escalation_breached is not None
                and row["escalation_breached"] != escalation_breached):
            return False
        return True

    return responses.list_response(
        store.ordered(store.evaluations, keep), limit, offset)


@bp.route("/reportability-evaluations", methods=["POST"])
def create_evaluation():
    auth.authorize("ComplianceOfficer", "SafetyDirector")
    data = shapes.body()
    hazard_pattern_id = shapes._req(data, "hazard_pattern_id")
    standard_basis = shapes.req_enum(data, "standard_basis", STANDARD_BASES)

    pattern = lookups.find("hazard_pattern", hazard_pattern_id)
    if pattern["pattern_status"] != "CONFIRMED":
        raise_error("ERR_PATTERN_STATE_INVALID")

    for existing in store.evaluations.values():
        if (existing["hazard_pattern_id"] == hazard_pattern_id
                and existing["status"] in LIVE_EVALUATION_STATUSES):
            raise_error("ERR_DUPLICATE_DOCKET_ENTRY")

    opened_at = store.now_logical()
    due_at = opened_at + store.hours(calc.escalation_window_hours(pattern))
    row = store.new_row(
        hazard_pattern_id=hazard_pattern_id,
        product_model_id=pattern["product_model_id"],
        standard_basis=standard_basis,
        status="OPEN",
        opened_at=opened_at,
        internal_escalation_due_at=due_at,
        escalation_breached=False,
        review_started_at=None,
        determined_at=None,
        report_due_at=None,
        defect_score=None,
        risk_score=None,
        determination_note=None,
    )
    store.evaluations[row["id"]] = row
    return responses.created(row)


@bp.route("/reportability-evaluations/<evaluation_id>/begin-review",
          methods=["POST"])
def begin_review(evaluation_id):
    auth.authorize("ComplianceOfficer", "SafetyDirector")
    evaluation = lookups.find("evaluation", evaluation_id)
    shapes.body()

    if evaluation["status"] != "OPEN":
        raise_error("ERR_EVALUATION_STATE_INVALID")

    started = store.now_logical()
    evaluation["status"] = "IN_REVIEW"
    evaluation["review_started_at"] = started
    # Strictly later than the deadline is a breach; exactly on it is on time.
    evaluation["escalation_breached"] = started > evaluation["internal_escalation_due_at"]
    store.touch(evaluation)
    return responses.object_response(evaluation)


def _score_supports_reportable(standard_basis, defect_score, risk_score):
    if standard_basis == "DEFECT":
        return defect_score >= 5
    if standard_basis == "UNREASONABLE_RISK":
        return risk_score >= 5
    return (defect_score + risk_score) >= 8


@bp.route("/reportability-evaluations/<evaluation_id>/determine",
          methods=["POST"])
def determine(evaluation_id):
    auth.authorize("ComplianceOfficer", "SafetyDirector")
    evaluation = lookups.find("evaluation", evaluation_id)
    data = shapes.body()
    determination = shapes.req_enum(data, "determination", DETERMINATIONS)
    defect_score = shapes.req_int(data, "defect_score", minimum=0, maximum=10)
    risk_score = shapes.req_int(data, "risk_score", minimum=0, maximum=10)
    determination_note = shapes.req_str(data, "determination_note", 1, 2000)

    if evaluation["status"] != "IN_REVIEW":
        raise_error("ERR_EVALUATION_STATE_INVALID")

    supported = _score_supports_reportable(
        evaluation["standard_basis"], defect_score, risk_score)
    if determination == "REPORTABLE":
        if not supported:
            raise_error("ERR_DETERMINATION_UNSUPPORTED")
    else:
        if supported:
            raise_error("ERR_DETERMINATION_UNSUPPORTED")

    determined_at = store.now_logical()
    evaluation["defect_score"] = defect_score
    evaluation["risk_score"] = risk_score
    evaluation["determination_note"] = determination_note
    evaluation["determined_at"] = determined_at
    evaluation["status"] = determination

    model = lookups.maybe("product_model", evaluation["product_model_id"])

    if determination == "REPORTABLE":
        evaluation["report_due_at"] = determined_at + store.hours(240)
        store.touch(evaluation)

        def clustered(row):
            return (row["hazard_pattern_id"] == evaluation["hazard_pattern_id"]
                    and row["status"] == "CLUSTERED")

        flipped = 0
        for row in store.ordered(store.incidents, clustered):
            row["status"] = "ESCALATED"
            row["escalation_deadline_at"] = determined_at + store.hours(120)
            store.touch(row)
            flipped += 1

        if model is not None:
            model["open_escalation_count"] = model["open_escalation_count"] + flipped
            model["hazard_posture"] = "FROZEN"
            store.touch(model)
    else:
        store.touch(evaluation)
        if model is not None:
            model["hazard_posture"] = "MONITORED"
            store.touch(model)

    return responses.object_response(evaluation)
