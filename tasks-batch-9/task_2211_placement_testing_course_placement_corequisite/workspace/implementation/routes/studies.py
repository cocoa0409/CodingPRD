"""Cut-score validation studies: proposal, runs and the director's decision."""

from flask import Blueprint

from constants import (
    DI_MIN_INDEX,
    RULE_SUBJECTS,
    STUDY_STATES,
    VALIDATION_MIN_SUCCESS_RATE,
)
from db import base_row, db, sort_rows, touch
from errors import fail
from middleware import authenticate
from response import created, ok
from routes.common import eq, filter_rows, find, listing
from services import calc, cascades, serialize
from validators import Field, parse_body, parse_query

bp = Blueprint("studies", __name__)

READERS = ("AssessmentStaff", "AssessmentDirector")

CREATE_SPEC = {
    "subject_area": Field("enum", required=True, values=RULE_SUBJECTS),
    "candidate_rule_id": Field("id", required=True),
    "window_start_at": Field("datetime", required=True),
    "window_end_at": Field("datetime", required=True),
}

LIST_SPEC = {
    "subject_area": Field("enum", values=RULE_SUBJECTS),
    "candidate_rule_id": Field("id"),
    "state": Field("enum", values=STUDY_STATES),
}

DECIDE_SPEC = {
    "decision": Field("enum", required=True, values=("APPROVE", "REJECT")),
    "decision_note": Field("str", required=True),
}


@bp.post("/validation-studies")
def create_study():
    user_id, _role = authenticate(("AssessmentStaff",))
    body = parse_body(CREATE_SPEC)

    if not (body["window_end_at"] > body["window_start_at"]):
        fail("ERR_INVALID_REQUEST", "window_end_at must be strictly after window_start_at")

    rule = find("rules", body["candidate_rule_id"])

    if rule["subject_area"] != body["subject_area"]:
        fail("ERR_INVALID_REQUEST", "subject_area disagrees with the candidate rule")
    if rule["status"] != "DRAFT":
        fail("ERR_CANDIDATE_RULE_NOT_DRAFT", "the candidate rule is not in status DRAFT")

    for other in sort_rows(list(db.studies.values())):
        if other["candidate_rule_id"] == rule["id"] and other["state"] in ("DRAFT", "COMPLETED"):
            other["state"] = "WITHDRAWN"
            other["decision_note"] = "superseded by a newer study"
            touch(other)

    row = base_row()
    row.update({
        "subject_area": body["subject_area"],
        "candidate_rule_id": rule["id"],
        "window_start_at": body["window_start_at"],
        "window_end_at": body["window_end_at"],
        "strict_cohort_size": 0,
        "strict_success_count": 0,
        "strict_success_rate": None,
        "inclusive_cohort_size": 0,
        "inclusive_success_count": 0,
        "inclusive_success_rate": None,
        "disproportionate_impact_index": None,
        "reference_group_key": None,
        "run_count": 0,
        "proposed_by_user_id": user_id,
        "decided_by_user_id": None,
        "decision_note": None,
        "state": "DRAFT",
    })
    db.studies[row["id"]] = row
    return created(serialize.study(row))


@bp.get("/validation-studies/<study_id>")
def get_study(study_id):
    authenticate(READERS)
    parse_query({}, paginated=False)
    row = find("studies", study_id)
    return ok(serialize.study(row))


@bp.get("/validation-studies")
def list_studies():
    authenticate(READERS)
    query = parse_query(LIST_SPEC)
    rows = filter_rows(list(db.studies.values()), query, {
        "subject_area": eq("subject_area"),
        "candidate_rule_id": eq("candidate_rule_id"),
        "state": eq("state"),
    })
    return listing(rows, query, serialize.study)


@bp.post("/validation-studies/<study_id>/run")
def run(study_id):
    authenticate(("AssessmentStaff",))
    parse_body({})
    row = find("studies", study_id)

    if row["state"] not in ("DRAFT", "COMPLETED"):
        fail("ERR_INVALID_STATE", "only a DRAFT or COMPLETED study may be run")

    rule = db.rules.get(row["candidate_rule_id"])
    if rule is None or rule["status"] != "DRAFT":
        fail("ERR_CANDIDATE_RULE_NOT_DRAFT", "the candidate rule is no longer in status DRAFT")

    if row["window_end_at"] > db.clock:
        fail("ERR_STUDY_WINDOW_OPEN", "the observation window is still open")

    metrics = calc.study_metrics(row)
    if metrics["strict_cohort_size"] == 0:
        fail("ERR_STUDY_COHORT_EMPTY", "the strict cohort is empty")

    row.update(metrics)
    row["run_count"] = row["run_count"] + 1
    row["state"] = "COMPLETED"
    touch(row)
    return ok(serialize.study(row))


@bp.post("/validation-studies/<study_id>/decide")
def decide(study_id):
    user_id, _role = authenticate(("AssessmentDirector",))
    body = parse_body(DECIDE_SPEC)
    row = find("studies", study_id)

    if row["state"] != "COMPLETED":
        fail("ERR_INVALID_STATE", "only a COMPLETED study may be decided")

    decision = body["decision"]
    rule = db.rules.get(row["candidate_rule_id"])
    if decision == "APPROVE":
        if rule is None or rule["status"] != "DRAFT":
            fail("ERR_CANDIDATE_RULE_NOT_DRAFT", "the candidate rule is no longer in status DRAFT")

    if user_id == row["proposed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the proposer may not decide their own study")

    if decision == "APPROVE":
        rate = row["strict_success_rate"]
        if rate is None or rate < VALIDATION_MIN_SUCCESS_RATE:
            fail("ERR_VALIDATION_RATE_TOO_LOW", "the strict success rate is below the floor")
        index = row["disproportionate_impact_index"]
        if index is None or index < DI_MIN_INDEX:
            fail("ERR_DISPROPORTIONATE_IMPACT", "the disproportionate impact index is below the floor")

    row["decided_by_user_id"] = user_id
    row["decision_note"] = body["decision_note"]
    row["state"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    touch(row)

    if decision == "APPROVE":
        cascades.activate_rule(rule)
    return ok(serialize.study(row))
