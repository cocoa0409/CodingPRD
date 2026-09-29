"""Gate reviews: convening, balloting, the four-way close and conditions
settlement (PRD §3.6)."""

from flask import Blueprint

import clock
import db
import errors as E
import middleware as M
import response as R
import validation as V
from routes import common
from services import core

bp = Blueprint("gate_reviews", __name__)


def _gate_of(review):
    return db.stage_gates.get(review["gate_id"])


def _project_of(review):
    return db.projects.get(review["project_id"])


# ---------------------------------------------------------------------------
# scheduling and reads
# ---------------------------------------------------------------------------
@bp.post("/innovation-projects/<project_id>/gate-reviews")
def create_gate_review(project_id):
    M.authenticate("GateChair")
    project = common.project(project_id)
    data = V.body()
    gate_id = V.id_field(data, "gate_id")
    scheduled_raw, scheduled_dt = V.datetime_field(data, "scheduled_at")
    gate = common.stage_gate(gate_id)

    if project["dev_status"] not in ("IDEA", "SCREENED", "PILOT_QUALIFIED",
                                    "LAUNCH_READY"):
        E.fail(E.ERR_PROJECT_INVALID_STATE,
               "dev_status %s does not admit a gate review."
               % project["dev_status"])

    row = core.new_row(db.gate_reviews, {
        "project_id": project["id"],
        "gate_id": gate["id"],
        "scheduled_at": scheduled_raw,
        "status": "SCHEDULED",
        "decision": None,
        "chair_user_id": None,
        "deliverable_completeness_pct": core.ZERO2,
        "readiness_index": core.ZERO2,
        "vote_count": 0,
        "conditions": None,
        "conditions_due_at": None,
        "closed_at": None,
    })
    row["_dt_scheduled_at"] = scheduled_dt
    row["_dt_conditions_due_at"] = None
    return R.object_response(row, 201)


@bp.get("/gate-reviews")
def list_gate_reviews():
    M.reader()
    rows = M.apply_filters(db.rows(db.gate_reviews), {
        "project_id": "project_id",
        "gate_id": "gate_id",
        "status": "status",
    })
    rows = M.order(rows)
    page, limit, offset, total = M.page(rows)
    return R.list_response(page, limit, offset, total)


@bp.get("/gate-reviews/<gate_review_id>")
def read_gate_review(gate_review_id):
    M.reader()
    return R.object_response(common.gate_review(gate_review_id))


# ---------------------------------------------------------------------------
# opening the session
# ---------------------------------------------------------------------------
@bp.post("/gate-reviews/<gate_review_id>/open")
def open_gate_review(gate_review_id):
    M.authenticate("GateChair")
    review = common.gate_review(gate_review_id)
    gate = _gate_of(review)
    project = _project_of(review)

    if review["status"] != "SCHEDULED":
        E.fail(E.ERR_GATE_REVIEW_INVALID_STATE,
               "Only a SCHEDULED review may be opened; this one is %s."
               % review["status"])
    if project["dev_status"] != gate["stage_from"]:
        E.fail(E.ERR_PROJECT_INVALID_STATE,
               "dev_status %s does not match the gate's stage_from %s."
               % (project["dev_status"], gate["stage_from"]))

    if gate["gate_number"] != project["next_gate_number"]:
        E.fail(E.ERR_GATE_SEQUENCE_VIOLATION,
               "Gate %d is not the project's next gate (%d)."
               % (gate["gate_number"], project["next_gate_number"]))
    for other in db.children(db.gate_reviews, "project_id", project["id"]):
        if other["id"] != review["id"] and other["status"] == "IN_SESSION":
            E.fail(E.ERR_GATE_REVIEW_ALREADY_IN_SESSION,
                   "Another review of this project is already IN_SESSION.")
    if project["open_gate_conditions"]:
        E.fail(E.ERR_GATE_CONDITIONS_OPEN,
               "Unresolved conditions from an earlier conditional pass block "
               "this gate.")

    completeness = core.completeness_for(project["id"], gate)
    readiness = core.readiness_index_for(project, gate, completeness)
    core.apply(review, {
        "status": "IN_SESSION",
        "deliverable_completeness_pct": completeness,
        "readiness_index": readiness,
    })
    return R.object_response(review, 200)


# ---------------------------------------------------------------------------
# balloting
# ---------------------------------------------------------------------------
@bp.post("/gate-reviews/<gate_review_id>/votes")
def cast_vote(gate_review_id):
    user_id = M.authenticate("FunctionalReviewer", "RegulatoryApprover")
    review = common.gate_review(gate_review_id)
    data = V.body()
    function = V.enum_field(data, "function", V.FUNCTIONS)
    vote = V.enum_field(data, "vote", V.VOTES)
    rationale = V.string_field(data, "rationale", required=False, max_len=1000)

    if review["status"] != "IN_SESSION":
        E.fail(E.ERR_GATE_REVIEW_INVALID_STATE,
               "A review must be IN_SESSION to take ballots; this one is %s."
               % review["status"])

    project = _project_of(review)
    if project is not None and project["owner_user_id"] == user_id:
        E.fail(E.ERR_OWNER_CANNOT_VOTE,
               "The project owner may not vote on its own gate.")

    for ballot in core.review_votes(review["id"]):
        if ballot["function"] == function:
            E.fail(E.ERR_DUPLICATE_FUNCTION_VOTE,
                   "Seat %s has already voted on this review." % function)

    row = core.new_row(db.gate_votes, {
        "gate_review_id": review["id"],
        "function": function,
        "vote": vote,
        "voter_user_id": user_id,
        "rationale": rationale,
    }, common=False)

    core.apply(review, {"vote_count": review["vote_count"] + 1})
    return R.object_response(row, 201)


@bp.get("/gate-reviews/<gate_review_id>/votes")
def list_votes(gate_review_id):
    M.reader()
    review = common.gate_review(gate_review_id)
    rows = M.order(core.review_votes(review["id"]))
    page, limit, offset, total = M.page(rows)
    return R.list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# closing
# ---------------------------------------------------------------------------
def _derive_decision(ballots, gate):
    values = [b["vote"] for b in ballots]
    rejects = [b for b in ballots if b["vote"] == "REJECT"]
    if rejects:
        veto = set(gate["veto_functions"] or ())
        if any(b["function"] in veto for b in rejects):
            return "KILLED"
        return "RECYCLED"
    if "APPROVE_WITH_CONDITIONS" in values:
        return "CONDITIONAL_PASS"
    return "PASSED"


def _advance(project, gate, conditional):
    changes = {
        "dev_status": gate["stage_to"],
        "next_gate_number": gate["gate_number"] + 1,
    }
    if conditional:
        changes["open_gate_conditions"] = True
    core.apply(project, changes)

    case = core.authoritative_case(project["id"])
    if case is not None and case["status"] == "COMPUTED":
        core.apply(case, {"status": "LOCKED"})

    core.create_next_checklist(project)
    if gate["stage_to"] == "LAUNCH_READY":
        core.recompute_launch_readiness(project)


@bp.post("/gate-reviews/<gate_review_id>/close")
def close_gate_review(gate_review_id):
    user_id = M.authenticate("GateChair")
    review = common.gate_review(gate_review_id)
    data = V.body()
    conditions = V.string_field(data, "conditions", required=False, max_len=2000)
    due_raw, due_dt = V.datetime_field(data, "conditions_due_at", required=False)

    if review["status"] != "IN_SESSION":
        E.fail(E.ERR_GATE_REVIEW_INVALID_STATE,
               "Only an IN_SESSION review may be closed; this one is %s."
               % review["status"])

    gate = _gate_of(review)
    project = _project_of(review)
    ballots = core.review_votes(review["id"])

    if any(b["voter_user_id"] == user_id for b in ballots):
        E.fail(E.ERR_CHAIR_CANNOT_VOTE_AND_CLOSE,
               "A chair who voted on this review may not close it.")
    if review["vote_count"] < gate["quorum_size"]:
        E.fail(E.ERR_QUORUM_NOT_MET,
               "%d ballots are below the quorum of %d."
               % (review["vote_count"], gate["quorum_size"]))

    decision = _derive_decision(ballots, gate)
    closed_at = clock.current_raw()

    if decision in ("PASSED", "CONDITIONAL_PASS"):
        if decision == "CONDITIONAL_PASS":
            if conditions is None or conditions.strip() == "":
                E.fail(E.ERR_INVALID_REQUEST,
                       "A conditional pass requires a non-empty 'conditions'.")
            if due_dt is None:
                E.fail(E.ERR_INVALID_REQUEST,
                       "A conditional pass requires 'conditions_due_at'.")
            if due_dt <= clock.current_dt():
                E.fail(E.ERR_INVALID_REQUEST,
                       "'conditions_due_at' must be after the current instant.")

        completeness = core.completeness_for(project["id"], gate)
        readiness = core.readiness_index_for(project, gate, completeness)

        if completeness != core.HUNDRED:
            E.fail(E.ERR_DELIVERABLE_CHECKLIST_INCOMPLETE,
                   "The gate checklist stands at %s%%." % completeness)
        if readiness < gate["readiness_floor_index"]:
            E.fail(E.ERR_GATE_READINESS_BELOW_FLOOR,
                   "Readiness index %s is below the floor %s."
                   % (readiness, gate["readiness_floor_index"]))
        case = core.authoritative_case(project["id"])
        if core.hurdles_cleared(case, gate) != 3:
            E.fail(E.ERR_BUSINESS_CASE_HURDLE_NOT_MET,
                   "The authoritative business case does not clear all three "
                   "financial hurdles.")

        changes = {
            "status": decision,
            "decision": decision,
            "chair_user_id": user_id,
            "closed_at": closed_at,
            "deliverable_completeness_pct": completeness,
            "readiness_index": readiness,
        }
        if decision == "CONDITIONAL_PASS":
            changes["conditions"] = conditions
            changes["conditions_due_at"] = due_raw
        core.apply(review, changes)
        review["_dt_closed_at"] = clock.current_dt()
        if decision == "CONDITIONAL_PASS":
            review["_dt_conditions_due_at"] = due_dt
        _advance(project, gate, decision == "CONDITIONAL_PASS")

    else:
        core.apply(review, {
            "status": decision,
            "decision": decision,
            "chair_user_id": user_id,
            "closed_at": closed_at,
        })
        review["_dt_closed_at"] = clock.current_dt()
        if decision == "RECYCLED":
            core.step_back(project, gate)
        else:
            core.apply(project, {"dev_status": "KILLED"})
            core.kill_cascade(project, review["id"])

    return R.object_response(review, 200)


# ---------------------------------------------------------------------------
# settling conditions
# ---------------------------------------------------------------------------
@bp.post("/gate-reviews/<gate_review_id>/clear-conditions")
def clear_conditions(gate_review_id):
    M.authenticate("GateChair")
    review = common.gate_review(gate_review_id)
    data = V.body()
    V.string_field(data, "resolution_note", max_len=2000)

    if review["status"] != "CONDITIONAL_PASS":
        E.fail(E.ERR_GATE_REVIEW_INVALID_STATE,
               "Only a CONDITIONAL_PASS review has conditions to clear; this "
               "one is %s." % review["status"])

    due = core.dt_of(review, "conditions_due_at")
    if due is not None and clock.current_dt() > due:
        E.fail(E.ERR_CONDITIONS_DUE_PASSED,
               "The conditions deadline has already passed.")

    gate = _gate_of(review)
    project = _project_of(review)
    completeness = core.completeness_for(project["id"], gate)
    if completeness != core.HUNDRED:
        E.fail(E.ERR_DELIVERABLE_CHECKLIST_INCOMPLETE,
               "The gate checklist stands at %s%%." % completeness)

    core.apply(review, {"status": "PASSED", "decision": "PASSED"})
    core.apply(project, {"open_gate_conditions": False})
    return R.object_response(review, 200)


@bp.post("/gate-reviews/<gate_review_id>/expire-conditions")
def expire_conditions(gate_review_id):
    M.authenticate("PortfolioAdmin")
    review = common.gate_review(gate_review_id)

    if review["status"] != "CONDITIONAL_PASS":
        E.fail(E.ERR_GATE_REVIEW_INVALID_STATE,
               "Only a CONDITIONAL_PASS review may have its conditions "
               "expired; this one is %s." % review["status"])

    due = core.dt_of(review, "conditions_due_at")
    if due is None or clock.current_dt() <= due:
        E.fail(E.ERR_CONDITIONS_NOT_DUE,
               "The conditions deadline has not yet passed.")

    gate = _gate_of(review)
    project = _project_of(review)
    core.apply(review, {"status": "RECYCLED", "decision": "RECYCLED"})
    core.step_back(project, gate, {"open_gate_conditions": False})
    return R.object_response(review, 200)
