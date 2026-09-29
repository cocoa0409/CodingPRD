"""Placement determinations: the selector, the placement axis and the evidence axis."""

from flask import Blueprint

from constants import DETERMINATION_MEASURES, EVIDENCE_STATES, PLACEMENT_STATES, RULE_SUBJECTS
from db import base_row, db, sort_rows, touch
from errors import fail
from middleware import authenticate
from response import created, ok
from routes.common import eq, filter_rows, find, listing
from services import calc, cascades, serialize
from validators import Field, parse_body, parse_query

bp = Blueprint("determinations", __name__)

READERS = ("AssessmentStaff", "AssessmentDirector", "Registrar", "Instructor", "Student")

CREATE_SPEC = {
    "student_id": Field("id", required=True),
    "subject_area": Field("enum", required=True, values=RULE_SUBJECTS),
    "expected_student_version": Field("int", required=True),
}

LIST_SPEC = {
    "student_id": Field("id"),
    "subject_area": Field("enum", values=RULE_SUBJECTS),
    "applied_rule_id": Field("id"),
    "placed_course_id": Field("id"),
    "coreq_course_id": Field("id"),
    "source_attempt_id": Field("id"),
    "superseded_by_id": Field("id"),
    "placement_state": Field("enum", values=PLACEMENT_STATES),
    "evidence_state": Field("enum", values=EVIDENCE_STATES),
    "measure_type_used": Field("enum", values=DETERMINATION_MEASURES),
}

EVIDENCE_SPEC = {
    "target_evidence_state": Field("enum", required=True, values=EVIDENCE_STATES),
    "note": Field("str", nullable=True),
}


@bp.post("/placement-determinations")
def create_determination():
    user_id, _role = authenticate(("AssessmentStaff",))
    body = parse_body(CREATE_SPEC)

    student = find("students", body["student_id"])
    if body["expected_student_version"] != student["version"]:
        fail("ERR_STALE_STUDENT_VERSION", "expected_student_version does not match")

    subject = body["subject_area"]
    rule, cited = calc.select_rule(student, subject)
    if rule is None:
        fail("ERR_NO_PLACEMENT_RULE_MATCH", "no ACTIVE placement rule matches the student")

    if student["el_status"] == "EL_ACTIVE" and subject in ("ENGLISH", "ESL"):
        if rule["required_el_status"] != "EL_ACTIVE":
            fail("ERR_EL_PATHWAY_VIOLATION", "the winning rule is not an EL pathway rule")

    bundle = calc.confidence_bundle(student, subject)

    row = base_row()
    row.update({
        "student_id": student["id"],
        "subject_area": subject,
        "measure_type_used": rule["measure_type"],
        "applied_rule_id": rule["id"],
        "placed_course_id": rule["target_course_id"],
        "coreq_course_id": rule["coreq_course_id"] if rule["coreq_required"] else None,
        "source_attempt_id": cited["id"] if cited is not None else None,
        "superseded_by_id": None,
        "base_confidence_score": bundle["base_confidence_score"],
        "staleness_penalty": bundle["staleness_penalty"],
        "confidence_score": bundle["confidence_score"],
        "validity_days": bundle["validity_days"],
        "expires_at": bundle["expires_at"],
        "determined_by_user_id": user_id,
        "determined_at": bundle["determined_at"],
        "placement_state": "PROVISIONAL",
        "evidence_state": bundle["evidence_state"],
    })
    db.determinations[row["id"]] = row

    for other in sort_rows(list(db.determinations.values())):
        if other["id"] == row["id"]:
            continue
        if other["student_id"] != student["id"] or other["subject_area"] != subject:
            continue
        if other["placement_state"] in ("PROVISIONAL", "FINAL"):
            other["placement_state"] = "SUPERSEDED"
            other["superseded_by_id"] = row["id"]
            touch(other)

    touch(student)
    return created(serialize.determination(row))


@bp.get("/placement-determinations/<determination_id>")
def get_determination(determination_id):
    authenticate(READERS)
    parse_query({}, paginated=False)
    row = find("determinations", determination_id)
    return ok(serialize.determination(row))


@bp.get("/placement-determinations")
def list_determinations():
    authenticate(READERS)
    query = parse_query(LIST_SPEC)
    rows = filter_rows(list(db.determinations.values()), query, {
        "student_id": eq("student_id"),
        "subject_area": eq("subject_area"),
        "applied_rule_id": eq("applied_rule_id"),
        "placed_course_id": eq("placed_course_id"),
        "coreq_course_id": eq("coreq_course_id"),
        "source_attempt_id": eq("source_attempt_id"),
        "superseded_by_id": eq("superseded_by_id"),
        "placement_state": eq("placement_state"),
        "evidence_state": eq("evidence_state"),
        "measure_type_used": eq("measure_type_used"),
    })
    return listing(rows, query, serialize.determination)


@bp.post("/placement-determinations/<determination_id>/finalize")
def finalize(determination_id):
    authenticate(("AssessmentStaff",))
    parse_body({})
    row = find("determinations", determination_id)

    if row["placement_state"] == "SUPERSEDED":
        fail("ERR_DETERMINATION_SUPERSEDED", "the determination has been superseded")
    if row["placement_state"] != "PROVISIONAL":
        fail("ERR_INVALID_STATE", "only a PROVISIONAL determination may be finalized")
    if row["evidence_state"] != "VERIFIED":
        fail("ERR_EVIDENCE_NOT_VERIFIED", "evidence_state must be VERIFIED")
    if not (db.clock < row["expires_at"]):
        fail("ERR_PLACEMENT_EXPIRED", "the placement has lapsed")

    row["placement_state"] = "FINAL"
    touch(row)
    student = db.students.get(row["student_id"])
    if student is not None:
        touch(student)
    return ok(serialize.determination(row))


@bp.post("/placement-determinations/<determination_id>/evidence")
def evidence(determination_id):
    authenticate(("AssessmentStaff",))
    body = parse_body(EVIDENCE_SPEC)
    row = find("determinations", determination_id)

    if row["placement_state"] == "SUPERSEDED":
        fail("ERR_DETERMINATION_SUPERSEDED", "the determination has been superseded")

    target = body["target_evidence_state"]
    current = row["evidence_state"]
    allowed = {
        "VERIFIED": ("UNVERIFIED", "DISPUTED"),
        "DISPUTED": ("UNVERIFIED", "VERIFIED"),
    }
    if target not in allowed or current not in allowed[target]:
        fail("ERR_INVALID_STATE", "%s -> %s is not a declared transition" % (current, target))

    student = db.students.get(row["student_id"])

    if target == "VERIFIED":
        if current == "UNVERIFIED":
            transcript_ok = student is not None and student["hs_transcript_status"] == "VERIFIED"
            scored_ok = any(
                a["student_id"] == row["student_id"]
                and a["state"] == "SCORED"
                and a["subject_area"] == row["subject_area"]
                for a in db.attempts.values()
            )
            if not (transcript_ok or scored_ok):
                fail("ERR_NO_VERIFIABLE_EVIDENCE", "no verifiable evidence stands behind the placement")
        else:
            voided = db.attempts.get(row["source_attempt_id"]) if row["source_attempt_id"] else None
            floor = voided["created_at"] if voided is not None else None
            fresh = any(
                a["student_id"] == row["student_id"]
                and a["state"] == "SCORED"
                and a["subject_area"] == row["subject_area"]
                and (floor is None or a["created_at"] > floor)
                for a in db.attempts.values()
            )
            if not fresh:
                fail("ERR_NO_VERIFIABLE_EVIDENCE", "fresh evidence is required to clear a dispute")

    row["evidence_state"] = target
    touch(row)

    if target == "DISPUTED":
        ctx = cascades.new_ctx()
        cascades.dispute_registration_cascade(row, ctx)
        cascades.settle(ctx)

    # PRD 3.6: an evidence move "recomputes the student's `advising_hold` and
    # increments the determination's `version` by one" -- advising_hold is a
    # derived read, so the student row itself is not mutated here.
    return ok(serialize.determination(row))
