"""Placement rules: drafting, activation and retirement."""

from decimal import Decimal

from flask import Blueprint

from constants import EL_STATUSES, MEASURE_TYPES, PATHWAYS, RULE_STATUSES, RULE_SUBJECTS
from db import base_row, db
from errors import fail
from middleware import authenticate
from response import created, ok
from routes.common import eq, filter_rows, find, listing
from services import cascades, serialize
from validators import Field, parse_body, parse_query

bp = Blueprint("rules", __name__)

READERS = ("AssessmentDirector", "AssessmentStaff", "Registrar")

GPA = Field("dec", places=2, minimum=Decimal("0.00"), maximum=Decimal("4.50"), nullable=True)
SCORE = Field("int", minimum=0, maximum=1000, nullable=True)

CREATE_SPEC = {
    "subject_area": Field("enum", required=True, values=RULE_SUBJECTS),
    "measure_type": Field("enum", required=True, values=MEASURE_TYPES),
    "target_course_id": Field("id", required=True),
    "coreq_course_id": Field("id", nullable=True),
    "coreq_required": Field("bool"),
    "priority_rank": Field("int", required=True, minimum=1, maximum=999),
    "min_hs_gpa": GPA,
    "max_hs_gpa": GPA,
    "min_score": SCORE,
    "max_score": SCORE,
    "required_el_status": Field("enum", values=EL_STATUSES, nullable=True),
    "required_self_guided_pathway": Field("enum", values=PATHWAYS, nullable=True),
    "effective_from": Field("datetime", required=True),
    "effective_to": Field("datetime", nullable=True),
    "version_label": Field("str", required=True),
}

LIST_SPEC = {
    "subject_area": Field("enum", values=RULE_SUBJECTS),
    "measure_type": Field("enum", values=MEASURE_TYPES),
    "status": Field("enum", values=RULE_STATUSES),
    "target_course_id": Field("id"),
    "coreq_course_id": Field("id"),
    "required_el_status": Field("enum", values=EL_STATUSES),
}


@bp.post("/placement-rules")
def create_rule():
    authenticate(("AssessmentDirector",))
    body = parse_body(CREATE_SPEC)

    min_gpa = body.get("min_hs_gpa")
    max_gpa = body.get("max_hs_gpa")
    if min_gpa is not None and max_gpa is not None and not (min_gpa < max_gpa):
        fail("ERR_INVALID_REQUEST", "min_hs_gpa must be strictly below max_hs_gpa")
    min_score = body.get("min_score")
    max_score = body.get("max_score")
    if min_score is not None and max_score is not None and not (min_score <= max_score):
        fail("ERR_INVALID_REQUEST", "min_score must not exceed max_score")

    target = find("courses", body["target_course_id"])
    coreq = None
    if body.get("coreq_course_id") is not None:
        coreq = find("courses", body["coreq_course_id"])

    row = base_row()
    row.update({
        "subject_area": body["subject_area"],
        "measure_type": body["measure_type"],
        "target_course_id": target["id"],
        "coreq_course_id": coreq["id"] if coreq else None,
        "coreq_required": body.get("coreq_required", False),
        "priority_rank": body["priority_rank"],
        "min_hs_gpa": min_gpa,
        "max_hs_gpa": max_gpa,
        "min_score": min_score,
        "max_score": max_score,
        "required_el_status": body.get("required_el_status"),
        "required_self_guided_pathway": body.get("required_self_guided_pathway"),
        "effective_from": body["effective_from"],
        "effective_to": body.get("effective_to"),
        "version_label": body["version_label"],
        "status": "DRAFT",
        "activated_at": None,
    })
    db.rules[row["id"]] = row
    return created(serialize.rule(row))


@bp.get("/placement-rules/<rule_id>")
def get_rule(rule_id):
    authenticate(READERS)
    parse_query({}, paginated=False)
    row = find("rules", rule_id)
    return ok(serialize.rule(row))


@bp.get("/placement-rules")
def list_rules():
    authenticate(READERS)
    query = parse_query(LIST_SPEC)
    rows = filter_rows(list(db.rules.values()), query, {
        "subject_area": eq("subject_area"),
        "measure_type": eq("measure_type"),
        "status": eq("status"),
        "target_course_id": eq("target_course_id"),
        "coreq_course_id": eq("coreq_course_id"),
        "required_el_status": eq("required_el_status"),
    })
    return listing(rows, query, serialize.rule)


def measure_complete(rule):
    kind = rule["measure_type"]
    if kind == "TRANSCRIPT_GPA":
        return rule["min_hs_gpa"] is not None or rule["max_hs_gpa"] is not None
    if kind == "TEST_SCORE":
        return rule["min_score"] is not None or rule["max_score"] is not None
    return rule["required_self_guided_pathway"] is not None


def coreq_valid(rule):
    if not rule["coreq_required"]:
        return True
    if rule["coreq_course_id"] is None:
        return False
    support = db.courses.get(rule["coreq_course_id"])
    if support is None or support["status"] != "ACTIVE" or not support["is_support_course"]:
        return False
    for edge in db.requisites.values():
        if (
            edge["status"] == "ACTIVE"
            and edge["requisite_type"] == "COREQUISITE"
            and edge["course_id"] == rule["target_course_id"]
            and edge["requisite_course_id"] == support["id"]
        ):
            return True
    return False


@bp.post("/placement-rules/<rule_id>/activate")
def activate_rule(rule_id):
    authenticate(("AssessmentDirector",))
    parse_body({})
    row = find("rules", rule_id)

    if row["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "only a DRAFT rule may be activated")

    target = db.courses.get(row["target_course_id"])
    if target is None or target["status"] != "ACTIVE":
        fail("ERR_COURSE_RETIRED", "target_course_id names a retired course")
    if row["coreq_course_id"] is not None:
        support = db.courses.get(row["coreq_course_id"])
        if support is None or support["status"] != "ACTIVE":
            fail("ERR_COURSE_RETIRED", "coreq_course_id names a retired course")

    if not coreq_valid(row):
        fail("ERR_COREQ_COURSE_INVALID", "the required corequisite support course is not valid")
    if not measure_complete(row):
        fail("ERR_RULE_MEASURE_INCOMPLETE", "the rule's measure bounds are not specified")

    cascades.activate_rule(row)
    return ok(serialize.rule(row))


@bp.post("/placement-rules/<rule_id>/retire")
def retire_rule(rule_id):
    authenticate(("AssessmentDirector",))
    parse_body({})
    row = find("rules", rule_id)
    if row["status"] not in ("DRAFT", "ACTIVE", "SUPERSEDED"):
        fail("ERR_INVALID_STATE", "only a DRAFT, ACTIVE or SUPERSEDED rule may be retired")
    cascades.retire_rule(row, withdraw_studies=True)
    return ok(serialize.rule(row))
