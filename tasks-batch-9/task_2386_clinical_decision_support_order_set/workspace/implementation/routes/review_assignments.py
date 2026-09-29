"""Reviewer assignment, vote casting, quorum evaluation and withdrawal (PRD §3.4)."""
from flask import Blueprint, request

import const
import validate
from common import base_record, now, touch
from db import db
from errors import ApiError
from middleware import (authenticate, caller_id, check_freeze, check_read_freeze,
                        get_alert, get_assignment, get_clinician, get_order_set)
from response import created, ok, paginate
from services import calc, domain

bp = Blueprint("review_assignments", __name__)


def _target_class(assignment):
    return "order_set" if assignment.get("order_set_id") else "alert"


# ------------------------------------------------------------------ create
@bp.post("/cds/review-assignments")
def create_assignment():
    authenticate(("CommitteeChair",))
    data = validate.body()

    # body foreign keys in declared input order
    reviewer = None
    if isinstance(data.get("reviewer_id"), str):
        reviewer = get_clinician(data["reviewer_id"])
    order_set = None
    if isinstance(data.get("order_set_id"), str):
        order_set = get_order_set(data["order_set_id"])
    alert = None
    if isinstance(data.get("alert_id"), str):
        alert = get_alert(data["alert_id"])

    reviewer_id = validate.string(data, "reviewer_id", required=True)
    review_kind = validate.enum(data, "review_kind", const.REVIEW_KINDS, required=True)
    order_set_id = validate.string(data, "order_set_id")
    alert_id = validate.string(data, "alert_id")
    due_at = validate.instant(data, "due_at")

    if (order_set_id is None) == (alert_id is None):
        raise ApiError(
            "ERR_INVALID_REQUEST", "Exactly one of order_set_id or alert_id must be supplied"
        )
    if reviewer is None:
        reviewer = get_clinician(reviewer_id)

    if reviewer["employment_status"] != "ACTIVE":
        raise ApiError("ERR_CLINICIAN_NOT_ACTIVE", "Reviewer is not ACTIVE")

    check_freeze("order_set" if order_set is not None else "alert")

    # segregation of duties (PRD §2.10)
    if order_set is not None:
        if order_set["built_by_clinician_id"] == reviewer_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", "The builder may not review their own order set")
        other_kind = "SPECIALTY_APPROVAL" if review_kind == "PEER_REVIEW" else "PEER_REVIEW"
        for existing in domain.assignments_of_order_set(order_set["id"]):
            if (existing["reviewer_id"] == reviewer_id
                    and existing["review_kind"] == other_kind
                    and existing["state"] in ("ASSIGNED", "CAST")):
                raise ApiError(
                    "ERR_SEGREGATION_OF_DUTIES",
                    "A reviewer may not hold both review stages on one order set",
                )
    else:
        if alert["designed_by_clinician_id"] == reviewer_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", "The designer may not review their own alert")

    # self review (PRD §2.10)
    artifact = order_set if order_set is not None else alert
    content_request = db.content_requests.get(artifact["content_request_id"])
    if content_request is not None and content_request["clinical_sponsor_id"] == reviewer_id:
        raise ApiError(
            "ERR_SELF_REVIEW_FORBIDDEN", "The sponsor may not review artifacts from their request"
        )
    if order_set is not None and order_set["pharmacy_signoff_by_clinician_id"] == reviewer_id:
        raise ApiError(
            "ERR_SELF_REVIEW_FORBIDDEN", "The pharmacy signer may not review this order set"
        )

    # hard-stop justification (PRD §3.4)
    if alert is not None and alert["severity_tier"] == "TIER_1_HARD_STOP":
        if not (alert.get("hard_stop_justification") or "").strip():
            raise ApiError(
                "ERR_TIER1_JUSTIFICATION_REQUIRED",
                "A TIER_1_HARD_STOP alert requires a hard_stop_justification before review",
            )

    # duplicate assignment
    siblings = (domain.assignments_of_order_set(order_set["id"]) if order_set is not None
                else domain.assignments_of_alert(alert["id"]))
    for existing in siblings:
        if (existing["reviewer_id"] == reviewer_id
                and existing["review_kind"] == review_kind
                and existing["state"] in ("ASSIGNED", "CAST")):
            raise ApiError(
                "ERR_DUPLICATE_REVIEW_ASSIGNMENT",
                "Reviewer already holds this assignment on the artifact",
            )

    # workload pricing
    if order_set is not None:
        risk_snapshot = order_set["risk_class"]
        minutes = calc.assignment_minutes(review_kind, risk_snapshot)
    else:
        risk_snapshot = domain.alert_risk_class(alert)
        minutes = calc.assignment_minutes(review_kind, risk_snapshot, alert["severity_tier"])

    if reviewer["review_workload_assigned_minutes"] + minutes > reviewer["review_workload_capacity_minutes"]:
        raise ApiError("ERR_REVIEWER_CAPACITY_EXCEEDED", "Reviewer capacity would be exceeded")

    assignment = base_record()
    assignment.update({
        "order_set_id": order_set["id"] if order_set is not None else None,
        "alert_id": alert["id"] if alert is not None else None,
        "reviewer_id": reviewer_id,
        "due_at": due_at,
        "review_kind": review_kind,
        "state": "ASSIGNED",
        "estimated_minutes": minutes,
        "risk_class_snapshot": risk_snapshot,
        "vote": None,
        "comment": None,
        "evidence_concern": False,
        "cast_at": None,
        "withdrawal_reason": None,
        "void_reason": None,
    })
    db.review_assignments[assignment["id"]] = assignment

    domain.debit_workload(reviewer, minutes)

    if alert is not None and alert["review_state"] == "DRAFT":
        alert["review_state"] = "SPECIALTY_APPROVAL"
        alert["required_approval_votes"] = const.ALERT_REQUIRED_VOTES[alert["severity_tier"]]
        touch(alert)

    return created(assignment)


# ------------------------------------------------------------------ reads
@bp.get("/cds/review-assignments")
def list_assignments():
    authenticate(const.ANY_ROLE)
    records = list(db.review_assignments.values())
    for field in ("order_set_id", "alert_id", "reviewer_id", "review_kind", "state", "vote"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    concern = validate.query_bool("evidence_concern")
    if concern is not None:
        records = [r for r in records if r["evidence_concern"] is concern]
    return paginate(records)


@bp.get("/cds/review-assignments/<cid>")
def read_assignment(cid):
    authenticate(const.ANY_ROLE)
    assignment = get_assignment(cid)
    check_read_freeze(_target_class(assignment))
    return ok(assignment)


# ------------------------------------------------------------------ cast
def _peer_stage_counts(order_set_id, review_kind):
    cast = [
        a for a in domain.assignments_of_order_set(order_set_id)
        if a["review_kind"] == review_kind and a["state"] == "CAST"
    ]
    return cast


def _evaluate_order_set_stage(order_set, review_kind):
    """Quorum evaluation steps 1-7 (PRD §3.4)."""
    risk_class = domain.order_set_risk_class(order_set)
    order_set["risk_class"] = risk_class
    cast = _peer_stage_counts(order_set["id"], review_kind)
    concern_count = len([a for a in cast if a["evidence_concern"] is True])
    needed = calc.required_votes(risk_class, concern_count)
    prefix = "peer" if review_kind == "PEER_REVIEW" else "specialty"
    order_set[prefix + "_required_votes"] = needed
    approve = len([a for a in cast if a["vote"] == "APPROVE"])
    reject = len([a for a in cast if a["vote"] == "REJECT"])
    return calc.quorum_met(risk_class, len(cast), approve, reject, needed)


def _return_order_set_to_draft(order_set, triggering_id, restage_alerts):
    order_set["review_state"] = "DRAFT"
    order_set["revision_round"] += 1
    domain.void_other_assignments(
        domain.assignments_of_order_set(order_set["id"]), triggering_id, "ARTIFACT_RETURNED_TO_DRAFT"
    )
    if restage_alerts:
        domain.restage_linked_alerts(order_set)
    domain.recompute_order_set_counters(order_set)


@bp.post("/cds/review-assignments/<cid>/cast")
def cast_vote(cid):
    authenticate(("PeerReviewer", "SpecialtyApprover"))
    assignment = get_assignment(cid)

    if assignment["reviewer_id"] != caller_id():
        raise ApiError("ERR_ROLE_IDENTITY_MISMATCH", "Only the named reviewer may cast this vote")

    data = validate.body()
    vote = validate.enum(data, "vote", const.VOTES, required=True)
    comment = validate.string(data, "comment")
    evidence_concern = validate.boolean(data, "evidence_concern", default=False)

    if assignment["state"] != "ASSIGNED":
        raise ApiError("ERR_ASSIGNMENT_NOT_ASSIGNED", "Assignment is no longer outstanding")

    order_set = db.order_sets.get(assignment["order_set_id"]) if assignment["order_set_id"] else None
    alert = db.alerts.get(assignment["alert_id"]) if assignment["alert_id"] else None

    # the review stage must match the target artifact's current review state
    if order_set is not None:
        if order_set["review_state"] != assignment["review_kind"]:
            raise ApiError(
                "ERR_ORDER_SET_NOT_DRAFT",
                "Order set is not in the %s stage" % assignment["review_kind"],
            )
    else:
        if alert["review_state"] != "SPECIALTY_APPROVAL":
            raise ApiError("ERR_ALERT_NOT_APPROVED", "Alert is not in its approval stage")

    reviewer = db.clinicians.get(assignment["reviewer_id"])
    if reviewer is not None and reviewer["employment_status"] != "ACTIVE":
        raise ApiError("ERR_CLINICIAN_NOT_ACTIVE", "Reviewer is not ACTIVE")

    check_freeze("order_set" if order_set is not None else "alert")

    assignment["state"] = "CAST"
    assignment["vote"] = vote
    assignment["comment"] = comment
    assignment["evidence_concern"] = evidence_concern
    assignment["cast_at"] = now()
    touch(assignment)

    if order_set is not None:
        domain.recompute_order_set_counters(order_set)
        if assignment["review_kind"] == "PEER_REVIEW":
            if vote == "REJECT":
                _return_order_set_to_draft(order_set, assignment["id"], restage_alerts=False)
            elif _evaluate_order_set_stage(order_set, "PEER_REVIEW"):
                order_set["review_state"] = "SPECIALTY_APPROVAL"
                _evaluate_order_set_stage(order_set, "SPECIALTY_APPROVAL")
        else:
            if vote in ("REVISE", "REJECT"):
                _return_order_set_to_draft(order_set, assignment["id"], restage_alerts=True)
            elif _evaluate_order_set_stage(order_set, "SPECIALTY_APPROVAL"):
                order_set["review_state"] = "APPROVED"
                order_set["_deciding_specialty_reviewer_id"] = assignment["reviewer_id"]
        touch(order_set)
    else:
        domain.recompute_alert_counters(alert)
        if vote in ("REVISE", "REJECT"):
            alert["review_state"] = "DRAFT"
            domain.void_other_assignments(
                domain.assignments_of_alert(alert["id"]), assignment["id"],
                "ARTIFACT_RETURNED_TO_DRAFT",
            )
            domain.recompute_alert_counters(alert)
        else:
            needed = const.ALERT_REQUIRED_VOTES[alert["severity_tier"]]
            alert["required_approval_votes"] = needed
            cast = [a for a in domain.assignments_of_alert(alert["id"]) if a["state"] == "CAST"]
            approve = len([a for a in cast if a["vote"] == "APPROVE"])
            reject = len([a for a in cast if a["vote"] == "REJECT"])
            if calc.alert_quorum_met(len(cast), approve, reject, needed):
                alert["review_state"] = "APPROVED"
                alert["_deciding_reviewer_id"] = assignment["reviewer_id"]
        touch(alert)

    return ok(assignment)


# ------------------------------------------------------------------ withdraw
@bp.post("/cds/review-assignments/<cid>/withdraw")
def withdraw(cid):
    authenticate(("CommitteeChair",))
    assignment = get_assignment(cid)
    data = validate.body()
    reason = validate.string(data, "withdrawal_reason", required=True)

    if assignment["state"] != "ASSIGNED":
        raise ApiError("ERR_ASSIGNMENT_NOT_ASSIGNED", "Only an outstanding assignment may be withdrawn")

    check_freeze(_target_class(assignment))

    domain.credit_workload(assignment)
    assignment["state"] = "WITHDRAWN"
    assignment["withdrawal_reason"] = reason
    touch(assignment)
    return ok(assignment)
