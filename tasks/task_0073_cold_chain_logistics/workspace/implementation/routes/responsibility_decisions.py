"""Responsibility decision endpoints."""

from decimal import Decimal

from flask import Blueprint, request

from clock import clock
from db import db, new_id
from errors import err
from middleware import require_roles, auth_context
from response import object_response
from serializers import responsibility_decision as ser_rd
from services import audit
from services.responsibility import attach_advisory
from services.precision import round_half_up_2
from validators import (
    require_dict,
    require_enum,
    require_number,
    require_str,
)


bp = Blueprint("responsibility_decisions", __name__)


SPLIT_METHODS = {"DURATION_WEIGHTED", "SEVERITY_WEIGHTED"}
PARTY_ROLES = {"SHIPPER", "CARRIER", "CONSIGNEE"}


def _bump(row):
    row["updated_at"] = clock.now_iso()
    row["version"] = row.get("version", 0) + 1


def _validate_pct_sum(shipper, carrier, consignee):
    s = (round_half_up_2(shipper) + round_half_up_2(carrier) + round_half_up_2(consignee))
    if s != Decimal("1.00"):
        err("ERR_PCT_SUM_INVALID", "Party percentages must sum to 1.00.")


def _decision_for_task(task_id: str):
    for d in db.decisions.all():
        if d["task_id"] == task_id:
            return d
    return None


@bp.post("/responsibility-decisions")
@require_roles("COMPLIANCE_OFFICER")
def create_decision():
    body = require_dict(request.get_json(silent=True) or {})
    task_id = require_str(body.get("task_id"), field="task_id", min_len=1)
    assessment_id = require_str(body.get("assessment_id"), field="assessment_id", min_len=1)
    if not db.tasks.exists(task_id):
        err("ERR_REFERENCE_NOT_FOUND", "task_id not found.")
    if not db.assessments.exists(assessment_id):
        err("ERR_REFERENCE_NOT_FOUND", "assessment_id not found.")
    assessment = db.assessments.get(assessment_id)
    if assessment["task_id"] != task_id:
        err("ERR_REFERENCE_NOT_FOUND", "assessment_id does not belong to task_id.")
    if assessment["status"] != "FINALIZED":
        err("ERR_INVALID_STATE", "assessment must be FINALIZED.")

    if _decision_for_task(task_id) is not None:
        err("ERR_INVALID_STATE", "ResponsibilityDecision already exists for this task.")

    shipper_pct = body.get("shipper_pct")
    carrier_pct = body.get("carrier_pct")
    consignee_pct = body.get("consignee_pct")
    require_number(shipper_pct, field="shipper_pct", min_val=0.00, max_val=1.00)
    require_number(carrier_pct, field="carrier_pct", min_val=0.00, max_val=1.00)
    require_number(consignee_pct, field="consignee_pct", min_val=0.00, max_val=1.00)
    split_method = require_enum(body.get("split_method"), SPLIT_METHODS, field="split_method")

    _validate_pct_sum(shipper_pct, carrier_pct, consignee_pct)

    user_id, role = auth_context()
    now_iso = clock.now_iso()
    row = {
        "id": new_id(),
        "task_id": task_id,
        "assessment_id": assessment_id,
        "shipper_pct": float(round_half_up_2(shipper_pct)),
        "carrier_pct": float(round_half_up_2(carrier_pct)),
        "consignee_pct": float(round_half_up_2(consignee_pct)),
        "attributed_quantity": 0,
        "split_method": split_method,
        "status": "DRAFT",
        "mediator_id": None,
        "finalizing_role": None,
        "advisory_split": None,
        "_acceptors": [],  # list of X-User-IDs that have accepted in current UNDER_REVIEW round
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    attach_advisory(row)
    db.decisions.put(row)
    audit.log("RESPONSIBILITY_DECISION", row["id"], "DRAFTED", role, user_id)
    return object_response(ser_rd(row), status_code=201)


@bp.patch("/responsibility-decisions/<decision_id>")
@require_roles("COMPLIANCE_OFFICER")
def patch_decision(decision_id):
    row = db.decisions.get(decision_id)
    if row is None:
        err("ERR_NOT_FOUND", "ResponsibilityDecision not found.")

    body = require_dict(request.get_json(silent=True) or {})

    # OCC first
    if "version" in body:
        if body["version"] != row["version"]:
            err("ERR_VERSION_CONFLICT", "version mismatch.")

    # State eligibility: DRAFT or MEDIATION (which cycles back to DRAFT)
    if row["status"] not in {"DRAFT", "MEDIATION"}:
        err("ERR_INVALID_STATE", "Decision must be DRAFT or MEDIATION to patch.")

    candidate = dict(row)
    if "shipper_pct" in body:
        require_number(body["shipper_pct"], field="shipper_pct", min_val=0.00, max_val=1.00)
        candidate["shipper_pct"] = float(round_half_up_2(body["shipper_pct"]))
    if "carrier_pct" in body:
        require_number(body["carrier_pct"], field="carrier_pct", min_val=0.00, max_val=1.00)
        candidate["carrier_pct"] = float(round_half_up_2(body["carrier_pct"]))
    if "consignee_pct" in body:
        require_number(body["consignee_pct"], field="consignee_pct", min_val=0.00, max_val=1.00)
        candidate["consignee_pct"] = float(round_half_up_2(body["consignee_pct"]))
    if "split_method" in body:
        candidate["split_method"] = require_enum(
            body["split_method"], SPLIT_METHODS, field="split_method"
        )

    _validate_pct_sum(
        candidate["shipper_pct"], candidate["carrier_pct"], candidate["consignee_pct"]
    )

    cycling = row["status"] == "MEDIATION"

    for k, v in candidate.items():
        row[k] = v

    # Always recompute advisory on PATCH per the PRD
    attach_advisory(row)

    if cycling:
        row["status"] = "DRAFT"
        row["_acceptors"] = []
        user_id, role = auth_context()
        audit.log("RESPONSIBILITY_DECISION", row["id"], "DRAFTED", role, user_id)

    _bump(row)
    return object_response(ser_rd(row))


@bp.post("/responsibility-decisions/<decision_id>/submit")
@require_roles("COMPLIANCE_OFFICER")
def submit_decision(decision_id):
    row = db.decisions.get(decision_id)
    if row is None:
        err("ERR_NOT_FOUND", "ResponsibilityDecision not found.")
    if row["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Decision must be DRAFT to submit.")
    row["status"] = "UNDER_REVIEW"
    row["_acceptors"] = []
    _bump(row)
    user_id, role = auth_context()
    audit.log("RESPONSIBILITY_DECISION", row["id"], "UNDER_REVIEW", role, user_id)
    return object_response(ser_rd(row))


@bp.post("/responsibility-decisions/<decision_id>/accept")
@require_roles("SHIPPER", "CARRIER", "CONSIGNEE")
def accept_decision(decision_id):
    with db.global_lock:
        row = db.decisions.get(decision_id)
        if row is None:
            err("ERR_NOT_FOUND", "ResponsibilityDecision not found.")
        if row["status"] != "UNDER_REVIEW":
            err("ERR_INVALID_STATE", "Decision must be UNDER_REVIEW to accept.")
        user_id, role = auth_context()
        task = db.tasks.get(row["task_id"])
        if task is None:
            err("ERR_INVALID_STATE", "Parent task missing.")
        # Verify the actor is actually the party of their role on this task
        # The role corresponds to one of shipper/carrier/consignee on the task
        # We need to track acceptance per X-User-ID. Per the PRD, "the server tracks
        # acceptance per X-User-ID" and the goal is to ensure all three parties have
        # accepted. We accept any of the three role kinds that map to a known
        # party-id on the task.
        expected_party_ids = {
            "SHIPPER": task.get("shipper_id"),
            "CARRIER": task.get("carrier_id"),
            "CONSIGNEE": task.get("consignee_id"),
        }
        target_id = expected_party_ids.get(role)
        if target_id is None or user_id != target_id:
            err("ERR_FORBIDDEN", "Caller is not the role's party on this task.")
        # Track acceptance by party role
        acceptors = set(row.get("_acceptors", []))
        acceptors.add(role)
        row["_acceptors"] = list(acceptors)
        # When all three parties have accepted -> ACCEPTED
        if acceptors == PARTY_ROLES:
            row["status"] = "ACCEPTED"
            audit.log(
                "RESPONSIBILITY_DECISION", row["id"], "ACCEPTED", role, user_id
            )
        _bump(row)
    return object_response(ser_rd(row))


@bp.post("/responsibility-decisions/<decision_id>/dispute")
@require_roles("SHIPPER", "CARRIER", "CONSIGNEE")
def dispute_decision(decision_id):
    row = db.decisions.get(decision_id)
    if row is None:
        err("ERR_NOT_FOUND", "ResponsibilityDecision not found.")
    if row["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", "Decision must be UNDER_REVIEW to dispute.")
    body = require_dict(request.get_json(silent=True) or {})
    require_str(body.get("reason"), field="reason", min_len=1, max_len=500)
    user_id, role = auth_context()
    task = db.tasks.get(row["task_id"])
    expected_party_ids = {
        "SHIPPER": task.get("shipper_id"),
        "CARRIER": task.get("carrier_id"),
        "CONSIGNEE": task.get("consignee_id"),
    }
    target_id = expected_party_ids.get(role)
    if target_id is None or user_id != target_id:
        err("ERR_FORBIDDEN", "Caller is not the role's party on this task.")
    row["status"] = "DISPUTED"
    row["_acceptors"] = []
    _bump(row)
    audit.log("RESPONSIBILITY_DECISION", row["id"], "DISPUTED", role, user_id)
    return object_response(ser_rd(row))


@bp.post("/responsibility-decisions/<decision_id>/mediate")
@require_roles("COMPLIANCE_OFFICER")
def mediate_decision(decision_id):
    row = db.decisions.get(decision_id)
    if row is None:
        err("ERR_NOT_FOUND", "ResponsibilityDecision not found.")
    if row["status"] != "DISPUTED":
        err("ERR_INVALID_STATE", "Decision must be DISPUTED to mediate.")
    user_id, role = auth_context()
    row["status"] = "MEDIATION"
    row["mediator_id"] = user_id
    _bump(row)
    audit.log("RESPONSIBILITY_DECISION", row["id"], "MEDIATED", role, user_id)
    return object_response(ser_rd(row))


@bp.post("/responsibility-decisions/<decision_id>/finalize")
@require_roles("COMPLIANCE_OFFICER")
def finalize_decision(decision_id):
    with db.global_lock:
        row = db.decisions.get(decision_id)
        if row is None:
            err("ERR_NOT_FOUND", "ResponsibilityDecision not found.")
        if row["status"] != "ACCEPTED":
            err("ERR_INVALID_STATE", "Decision must be ACCEPTED to finalize.")
        user_id, role = auth_context()
        task = db.tasks.get(row["task_id"])
        if task is None:
            err("ERR_INVALID_STATE", "Parent task missing.")
        if user_id in (task.get("shipper_id"), task.get("carrier_id"), task.get("consignee_id")):
            err("ERR_SEGREGATION_VIOLATION", "Finalizer cannot be a named party.")
        assessment = db.assessments.get(row["assessment_id"])
        row["status"] = "FINALIZED"
        row["finalizing_role"] = "COMPLIANCE_OFFICER"
        row["attributed_quantity"] = int(assessment["damaged_quantity"])
        _bump(row)
        audit.log("RESPONSIBILITY_DECISION", row["id"], "FINALIZED", role, user_id)
    return object_response(ser_rd(row))


@bp.get("/responsibility-decisions/<decision_id>")
@require_roles("SHIPPER", "CARRIER", "CONSIGNEE", "COMPLIANCE_OFFICER", "INSURANCE_ADJUSTER")
def get_decision(decision_id):
    row = db.decisions.get(decision_id)
    if row is None:
        err("ERR_NOT_FOUND", "ResponsibilityDecision not found.")
    return object_response(ser_rd(row))
