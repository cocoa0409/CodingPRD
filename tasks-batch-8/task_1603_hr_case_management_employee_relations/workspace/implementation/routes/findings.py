"""Findings, recommended actions, substantiation, calibration (PRD §3.5)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_UNAUTHORIZED, ERR_SEGREGATION_OF_DUTIES,
    ERR_INVESTIGATOR_CONFLICT, ERR_DOCUMENTATION_STANDARD,
    ERR_INSUFFICIENT_CREDIBILITY,
)
from middleware import authorize, require_investigator
from response import success_object
from services import calculations as calc
from services.core import (
    new_record, touch, require_path, list_response, serialize_finding,
    serialize_action, check_case_not_held, touch_case_manifest,
    interviews_of, evidence_of, assessments_of,
)
from util import CLOCK
from validate import Payload

bp = Blueprint("findings", __name__)

READ_ROLES = {"ERManager", "Investigator", "LegalCounsel"}
SUBSTANTIATION_OUTCOMES = {"SUBSTANTIATED", "UNSUBSTANTIATED", "INCONCLUSIVE"}
ACTION_TYPES = {"NO_ACTION", "COACHING", "WRITTEN_WARNING", "FINAL_WARNING",
                "SUSPENSION", "DEMOTION", "TERMINATION", "POLICY_CHANGE"}


@bp.post("/er/cases/<cid>/findings")
def create_finding(cid):
    caller = authorize({"Investigator"})
    case = require_path("cases", cid)
    p = Payload(request.get_json(silent=True))
    rationale_text = p.get_str("rationale_text", required=True)

    # priority 6 — the finding draft IS the INVESTIGATING -> FINDINGS_DRAFT
    # transition, gated on real groundwork
    if case["status"] != "INVESTIGATING":
        raise_error(ERR_INVALID_STATE,
                    f"cannot draft a finding while the case is "
                    f"{case['status']}")
    if not any(iv["status"] == "COMPLETED" for iv in interviews_of(cid)):
        raise_error(ERR_INVALID_STATE,
                    "at least one COMPLETED interview is required before "
                    "drafting a finding")
    if not any(ev["status"] == "ADMITTED" for ev in evidence_of(cid)):
        raise_error(ERR_INVALID_STATE,
                    "at least one ADMITTED evidence item is required before "
                    "drafting a finding")
    # priority 7
    check_case_not_held(case)
    # ownership — only the case's assigned investigator drafts the finding
    inv = require_investigator(caller)
    if inv["id"] != case["assigned_investigator_id"]:
        raise_error(ERR_UNAUTHORIZED,
                    "only the case's assigned investigator may draft the "
                    "finding")

    # priority 24
    p.raise_if_errors()

    rec = new_record()
    rec.update({
        "case_id": cid,
        "author_investigator_id": inv["id"],
        "substantiation_status": "DRAFT",
        "approval_status": "PENDING_REVIEW",
        "rationale_text": rationale_text,
        "calibration_score": None,
        "calibrated_by_ids": [],
        "_approved_at": None,
    })
    db["findings"][rec["id"]] = rec
    case["status"] = "FINDINGS_DRAFT"
    touch(case)
    touch_case_manifest(cid)
    return success_object(serialize_finding(rec), status=201)


@bp.get("/er/cases/<cid>/findings")
def list_case_findings(cid):
    authorize(READ_ROLES)
    require_path("cases", cid)
    items = [f for f in db["findings"].values() if f["case_id"] == cid]
    return list_response(items, serialize_finding)


@bp.get("/er/findings/<fid>")
def get_finding(fid):
    authorize(READ_ROLES)
    rec = require_path("findings", fid)
    return success_object(serialize_finding(rec))


@bp.get("/er/findings")
def list_findings():
    authorize(READ_ROLES)
    items = list(db["findings"].values())
    for field in ("author_investigator_id", "substantiation_status",
                  "approval_status"):
        v = request.args.get(field)
        if v is not None:
            items = [f for f in items if f.get(field) == v]
    return list_response(items, serialize_finding)


@bp.patch("/er/findings/<fid>")
def patch_finding(fid):
    caller = authorize({"Investigator"})
    finding = require_path("findings", fid)
    p = Payload(request.get_json(silent=True))
    rationale_text = p.get_str("rationale_text", required=True)

    # priority 6 — editable only while substantiation is DRAFT
    if finding["substantiation_status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE,
                    "rationale_text is editable only while the finding is in "
                    "DRAFT")
    # priority 7
    case = db["cases"][finding["case_id"]]
    check_case_not_held(case)
    # ownership — the author edits
    require_investigator(caller)
    if caller.user_id != finding["author_investigator_id"]:
        raise_error(ERR_UNAUTHORIZED,
                    "only the finding's author may edit the rationale")

    # priority 24
    p.raise_if_errors()

    finding["rationale_text"] = rationale_text
    touch(finding)
    return success_object(serialize_finding(finding))


@bp.post("/er/findings/<fid>/substantiate")
def substantiate_finding(fid):
    caller = authorize({"Investigator"})
    finding = require_path("findings", fid)
    p = Payload(request.get_json(silent=True))
    outcome = p.get_enum("outcome", SUBSTANTIATION_OUTCOMES, required=True)

    # priority 6
    if finding["substantiation_status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE,
                    "substantiation outcome may be set only from DRAFT")
    # priority 7
    case = db["cases"][finding["case_id"]]
    check_case_not_held(case)
    # ownership — substantiation is the author's call
    require_investigator(caller)
    if caller.user_id != finding["author_investigator_id"]:
        raise_error(ERR_UNAUTHORIZED,
                    "only the finding's author may substantiate it")
    # priority 16 — rationale standard is consulted before any credibility
    # question (PRD §3.5)
    if len(finding["rationale_text"] or "") < 100:
        raise_error(ERR_DOCUMENTATION_STANDARD,
                    "rationale_text must be at least 100 characters before "
                    "substantiation")
    # priority 17 — credibility-consistency gate on the ACTIVE variant scores
    if outcome == "SUBSTANTIATED":
        assessments = assessments_of(finding["case_id"])
        if all(calc.active_score(a) < 0.50 for a in assessments):
            raise_error(ERR_INSUFFICIENT_CREDIBILITY,
                        "SUBSTANTIATED is inconsistent with the case's active "
                        "credibility scores (all below 0.50)")
    # priority 24
    p.raise_if_errors()

    finding["substantiation_status"] = outcome
    touch(finding)
    return success_object(serialize_finding(finding))


@bp.post("/er/findings/<fid>/actions")
def propose_action(fid):
    caller = authorize({"Investigator"})
    finding = require_path("findings", fid)
    p = Payload(request.get_json(silent=True))
    action_type = p.get_enum("action_type", ACTION_TYPES, required=True)
    severity_points = p.get_int("severity_points", required=True,
                                minimum=0, maximum=100)
    justification = p.get_str("justification", required=True)

    # priority 6 — actions are proposed while the finding is in review
    if finding["approval_status"] not in ("PENDING_REVIEW", "REJECTED"):
        raise_error(ERR_INVALID_STATE,
                    f"cannot propose actions while the finding's approval "
                    f"status is {finding['approval_status']}")
    # priority 7
    case = db["cases"][finding["case_id"]]
    check_case_not_held(case)
    # ownership — actions are proposed by the author
    require_investigator(caller)
    if caller.user_id != finding["author_investigator_id"]:
        raise_error(ERR_UNAUTHORIZED,
                    "only the finding's author may propose actions")
    # priority 16 — documentation standard
    if justification is not None and len(justification) < 30:
        raise_error(ERR_DOCUMENTATION_STANDARD,
                    "justification must be at least 30 characters")
    # priority 24
    p.raise_if_errors()

    rec = new_record()
    rec.update({
        "finding_id": fid,
        "action_type": action_type,
        "severity_points": severity_points,
        "justification": justification,
        "status": "PROPOSED",
    })
    db["recommended_actions"][rec["id"]] = rec
    return success_object(serialize_action(rec), status=201)


@bp.get("/er/findings/<fid>/actions")
def list_finding_actions(fid):
    authorize(READ_ROLES)
    require_path("findings", fid)
    items = calc.actions_of(fid)
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response(items, serialize_action)


@bp.post("/er/recommended-actions/<aid>/withdraw")
def withdraw_action(aid):
    caller = authorize({"Investigator"})
    action = require_path("recommended_actions", aid)
    finding = db["findings"][action["finding_id"]]

    # priority 6
    if action["status"] != "PROPOSED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot withdraw an action in status {action['status']}")
    if finding["approval_status"] not in ("PENDING_REVIEW", "REJECTED"):
        raise_error(ERR_INVALID_STATE,
                    "actions may be withdrawn only while the finding is in "
                    "PENDING_REVIEW or REJECTED")
    # priority 7
    case = db["cases"][finding["case_id"]]
    check_case_not_held(case)
    # ownership — the author withdraws
    require_investigator(caller)
    if caller.user_id != finding["author_investigator_id"]:
        raise_error(ERR_UNAUTHORIZED,
                    "only the finding's author may withdraw its actions")

    action["status"] = "WITHDRAWN"
    touch(action)
    return success_object(serialize_action(action))


@bp.post("/er/findings/<fid>/submit-for-calibration")
def submit_for_calibration(fid):
    caller = authorize({"Investigator"})
    finding = require_path("findings", fid)

    # priority 6
    if finding["approval_status"] != "PENDING_REVIEW":
        raise_error(ERR_INVALID_STATE,
                    f"cannot submit for calibration from approval status "
                    f"{finding['approval_status']}")
    if finding["substantiation_status"] == "DRAFT":
        raise_error(ERR_INVALID_STATE,
                    "substantiation must leave DRAFT before calibration")
    if not any(a["status"] == "PROPOSED" for a in calc.actions_of(fid)):
        raise_error(ERR_INVALID_STATE,
                    "at least one PROPOSED recommended action is required "
                    "for calibration")
    # priority 7
    case = db["cases"][finding["case_id"]]
    check_case_not_held(case)
    # ownership — the author alone submits
    require_investigator(caller)
    if caller.user_id != finding["author_investigator_id"]:
        raise_error(ERR_UNAUTHORIZED,
                    "only the finding's author may submit it for calibration")
    # priority 16 — rationale standard
    if len(finding["rationale_text"] or "") < 100:
        raise_error(ERR_DOCUMENTATION_STANDARD,
                    "rationale_text must be at least 100 characters before "
                    "calibration")

    finding["approval_status"] = "CALIBRATED"
    touch(finding)
    case["status"] = "CALIBRATION"
    touch(case)
    return success_object(serialize_finding(finding))


@bp.post("/er/findings/<fid>/approve")
def approve_finding(fid):
    caller = authorize({"Investigator"})
    finding = require_path("findings", fid)

    # priority 6
    if finding["approval_status"] != "CALIBRATED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot approve a finding in approval status "
                    f"{finding['approval_status']}")
    # priority 7
    case = db["cases"][finding["case_id"]]
    check_case_not_held(case)
    # priority 8 — segregation of duties: the author may not vote
    voter = require_investigator(caller)
    if voter["id"] == finding["author_investigator_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "the finding's author may not cast a calibration vote")
    # priority 9 — conflict screen on the voter
    conflicts = voter["conflicted_employee_ids"]
    if case["subject_employee_id"] in conflicts or (
            case["reporter_employee_id"] is not None
            and case["reporter_employee_id"] in conflicts):
        raise_error(ERR_INVESTIGATOR_CONFLICT,
                    "the voting investigator is conflicted against the case "
                    "subject or reporter")

    # record the vote; every accepted vote advances the case version
    finding["calibrated_by_ids"] = finding["calibrated_by_ids"] + [voter["id"]]
    touch(finding)
    touch(case)

    # quorum: 2 distinct investigators, neither the author
    distinct_voters = {v for v in finding["calibrated_by_ids"]
                       if v != finding["author_investigator_id"]}
    if len(distinct_voters) >= 2:
        finding["approval_status"] = "APPROVED"
        finding["_approved_at"] = CLOCK.now()
        finding["calibration_score"] = calc.action_calibration(finding, case)
        winner = calc.calibration_winner(finding)
        for action in calc.actions_of(fid):
            if action["status"] != "PROPOSED":
                continue
            if winner is not None and action["id"] == winner["id"]:
                action["status"] = "ACCEPTED"
            else:
                action["status"] = "SUPERSEDED"
            touch(action)
        case["status"] = "PENDING_CLOSURE"
        touch(case)
    return success_object(serialize_finding(finding))


@bp.post("/er/findings/<fid>/reject")
def reject_finding(fid):
    caller = authorize({"Investigator"})
    finding = require_path("findings", fid)
    p = Payload(request.get_json(silent=True))
    rejection_reason = p.get_str("rejection_reason", required=True)

    # priority 6
    if finding["approval_status"] != "CALIBRATED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot reject a finding in approval status "
                    f"{finding['approval_status']}")
    # priority 7
    case = db["cases"][finding["case_id"]]
    check_case_not_held(case)
    # priority 8 — the author may not reject their own finding
    rejector = require_investigator(caller)
    if rejector["id"] == finding["author_investigator_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "the finding's author may not reject it")
    # priority 16 — documentation standard
    if rejection_reason is not None and len(rejection_reason) < 20:
        raise_error(ERR_DOCUMENTATION_STANDARD,
                    "rejection_reason must be at least 20 characters")
    # priority 24
    p.raise_if_errors()

    # revision loop: REJECTED is immediately restored to PENDING_REVIEW with
    # substantiation returned to DRAFT and the calibration pool cleared
    finding["approval_status"] = "PENDING_REVIEW"
    finding["substantiation_status"] = "DRAFT"
    finding["calibrated_by_ids"] = []
    touch(finding)
    case["status"] = "FINDINGS_DRAFT"
    touch(case)
    return success_object(serialize_finding(finding))
