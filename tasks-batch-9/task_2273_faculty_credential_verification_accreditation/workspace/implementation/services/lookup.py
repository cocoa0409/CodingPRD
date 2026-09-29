"""Existence resolution (rungs 5 and 6) and common relational lookups."""

import db
from constants import INACTIVE_ASSIGNMENT_STATUSES
from db import store
from errors import ApiError

_NOT_FOUND = {
    "disciplines": "ERR_DISCIPLINE_NOT_FOUND",
    "programs": "ERR_PROGRAM_NOT_FOUND",
    "terms": "ERR_TERM_NOT_FOUND",
    "faculty_members": "ERR_FACULTY_NOT_FOUND",
    "credential_records": "ERR_CREDENTIAL_RECORD_NOT_FOUND",
    "credential_evaluations": "ERR_EVALUATION_NOT_FOUND",
    "course_sections": "ERR_SECTION_NOT_FOUND",
    "course_assignments": "ERR_ASSIGNMENT_NOT_FOUND",
    "justifications": "ERR_JUSTIFICATION_NOT_FOUND",
    "rosters": "ERR_ROSTER_NOT_FOUND",
    "contracts": "ERR_CONTRACT_NOT_FOUND",
    "pd_records": "ERR_PD_RECORD_NOT_FOUND",
    "reviews": "ERR_REVIEW_NOT_FOUND",
}


def get(collection_name, row_id):
    collection = getattr(store, collection_name)
    if not isinstance(row_id, str) or row_id not in collection:
        raise ApiError(_NOT_FOUND[collection_name])
    return collection[row_id]


def maybe(collection_name, row_id):
    collection = getattr(store, collection_name)
    if not isinstance(row_id, str):
        return None
    return collection.get(row_id)


def discipline(row_id):
    return get("disciplines", row_id)


def program(row_id):
    return get("programs", row_id)


def term(row_id):
    return get("terms", row_id)


def faculty(row_id):
    return get("faculty_members", row_id)


def credential(row_id):
    return get("credential_records", row_id)


def evaluation(row_id):
    return get("credential_evaluations", row_id)


def section(row_id):
    return get("course_sections", row_id)


def assignment(row_id):
    return get("course_assignments", row_id)


def justification(row_id):
    return get("justifications", row_id)


def roster(row_id):
    return get("rosters", row_id)


def contract(row_id):
    return get("contracts", row_id)


def pd_record(row_id):
    return get("pd_records", row_id)


def review(row_id):
    return get("reviews", row_id)


# ------------------------------------------------------------- relations
def credentials_of(faculty_id):
    return [r for r in db.ordered(store.credential_records)
            if r["faculty_member_id"] == faculty_id]


def evaluations_of(credential_record_id):
    return [e for e in db.ordered(store.credential_evaluations)
            if e["credential_record_id"] == credential_record_id]


def has_completed_equivalent_evaluation(credential_record_id):
    for ev in evaluations_of(credential_record_id):
        if ev["status"] == "COMPLETED" and ev.get("equivalency_verdict") == "EQUIVALENT":
            return True
    return False


def assignments_of_faculty(faculty_id):
    return [a for a in db.ordered(store.course_assignments)
            if a["faculty_member_id"] == faculty_id]


def assignments_of_section(section_id):
    return [a for a in db.ordered(store.course_assignments)
            if a["course_section_id"] == section_id]


def active_assignments_of_faculty(faculty_id):
    return [a for a in assignments_of_faculty(faculty_id)
            if a["status"] not in INACTIVE_ASSIGNMENT_STATUSES]


def included_assignments(program_id, term_id):
    """Assignments counted for a (program, term) pair: active rows only."""
    out = []
    for a in db.ordered(store.course_assignments):
        if a["status"] in INACTIVE_ASSIGNMENT_STATUSES:
            continue
        sec = store.course_sections.get(a["course_section_id"])
        if not sec:
            continue
        if sec["program_id"] == program_id and sec["term_id"] == term_id:
            out.append(a)
    return out


def rosters_for(program_id, term_id):
    return [r for r in db.ordered(store.rosters)
            if r["program_id"] == program_id and r["term_id"] == term_id]


def generated_roster(program_id, term_id):
    for r in rosters_for(program_id, term_id):
        if r["status"] == "GENERATED":
            return r
    return None


def certified_roster(program_id, term_id):
    for r in rosters_for(program_id, term_id):
        if r["status"] == "CERTIFIED":
            return r
    return None


def anchor_roster_for_term(program_id, term_id):
    """Roster of (program, term) in GENERATED or CERTIFIED, greatest created_at."""
    candidates = [r for r in rosters_for(program_id, term_id)
                  if r["status"] in ("GENERATED", "CERTIFIED")]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r["_seq"])


def anchor_roster_for_program(program_id):
    """The program's roster in GENERATED or CERTIFIED with greatest created_at."""
    candidates = [r for r in db.ordered(store.rosters)
                  if r["program_id"] == program_id
                  and r["status"] in ("GENERATED", "CERTIFIED")]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r["_seq"])


def justifications_of_assignment(assignment_id):
    return [j for j in db.ordered(store.justifications)
            if j["course_assignment_id"] == assignment_id]


def approved_justification(assignment_id):
    for j in justifications_of_assignment(assignment_id):
        if j["status"] == "APPROVED":
            return j
    return None


def contracts_of_faculty(faculty_id):
    return [c for c in db.ordered(store.contracts)
            if c["faculty_member_id"] == faculty_id]


def pd_records_of(faculty_id):
    return [p for p in db.ordered(store.pd_records)
            if p["faculty_member_id"] == faculty_id]


def reviews_of_program(program_id):
    return [r for r in db.ordered(store.reviews) if r["program_id"] == program_id]
