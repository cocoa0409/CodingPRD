"""Bid specifications, their immutable clause book and the compliance matrix.

PRD §3.2, §3.3 and §3.4 — including Cascade B, which starts at the release of a
revision that names a predecessor.
"""

from flask import Blueprint

import calc
import find
import services
import validate
from db import db, new_row, touch
from errors import ApiError
from middleware import ALL_ROLES, BODY_ENGINEER, PURCHASING_OFFICER, acting_user_id, authorize
from response import created, listing, ok

bp = Blueprint("specs", __name__)

CLAUSE_CATEGORIES = (
    "CHASSIS",
    "PUMP",
    "AERIAL",
    "PATIENT_COMPARTMENT",
    "ELECTRICAL",
    "PAINT",
)
COMPLIANCE_RESPONSES = ("COMPLY", "EXCEPTION", "ALTERNATE")
OPERATOR_DISPOSITIONS = ("ACCEPTED", "REJECTED")


# ==========================================================================
# Bid specifications
# ==========================================================================


@bp.post("/specifications")
@authorize(PURCHASING_OFFICER)
def draft_specification():
    data = validate.body()
    program_id = validate.req_ref(data, "program_id")
    title = validate.req_str(data, "title", 1, 160)
    supersedes_spec_id = validate.opt_ref(data, "supersedes_spec_id")

    find.program(program_id)
    revision_number = 1
    if supersedes_spec_id is not None:
        predecessor = find.specification(supersedes_spec_id)
        revision_number = int(predecessor["revision_number"]) + 1

    row = new_row(
        {
            "program_id": program_id,
            "supersedes_spec_id": supersedes_spec_id,
            "title": title,
            "revision_number": revision_number,
            "authored_by_user_id": acting_user_id(),
            "released_by_user_id": None,
            "status": "DRAFT",
            "clause_count": 0,
            "mandatory_clause_count": 0,
            "compliance_score_strict": calc.rhu2(0),
            "compliance_score_provisional": calc.rhu2(0),
            "restrictive_clause_ratio_pct": calc.rhu2(0),
            "released_at": None,
        }
    )
    db.specifications[row["id"]] = row
    return created(row)


@bp.get("/specifications")
@authorize(*ALL_ROLES)
def list_specifications():
    limit, offset = validate.pagination()
    program_id = validate.query_filter("program_id")
    supersedes_spec_id = validate.query_filter("supersedes_spec_id")
    status = validate.query_filter("status")
    rows = list(db.specifications.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if supersedes_spec_id is not None:
        rows = [r for r in rows if r["supersedes_spec_id"] == supersedes_spec_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows, limit, offset)


@bp.get("/specifications/<specification_id>")
@authorize(*ALL_ROLES)
def read_specification(specification_id):
    return ok(find.specification(specification_id))


@bp.post("/specifications/<specification_id>/submit-review")
@authorize(PURCHASING_OFFICER)
def submit_specification_for_review(specification_id):
    spec = find.specification(specification_id)
    if spec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_SPEC_STATE")
    services.recompute_spec_counts(spec)
    if int(spec["clause_count"]) < 1:
        raise ApiError("ERR_SPEC_HAS_NO_CLAUSES")
    spec["status"] = "UNDER_REVIEW"
    services.recompute_spec_scores(spec)
    services.recompute_spec_ratio(spec)
    touch(spec)
    return ok(spec)


@bp.post("/specifications/<specification_id>/rework")
@authorize(PURCHASING_OFFICER)
def rework_specification(specification_id):
    spec = find.specification(specification_id)
    if spec["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_SPEC_STATE")
    spec["status"] = "DRAFT"
    spec["revision_number"] = int(spec["revision_number"]) + 1
    touch(spec)
    return ok(spec)


@bp.post("/specifications/<specification_id>/release")
@authorize(PURCHASING_OFFICER)
def release_specification(specification_id):
    spec = find.specification(specification_id)
    if spec["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_SPEC_STATE")

    predecessor = None
    if spec["supersedes_spec_id"]:
        predecessor = db.specifications.get(spec["supersedes_spec_id"])
        # Rung 28 sits above rung 29: the program mismatch is reported first.
        if predecessor is not None and predecessor["program_id"] != spec["program_id"]:
            raise ApiError("ERR_SPEC_PROGRAM_MISMATCH")
        if predecessor is None or predecessor["status"] != "RELEASED":
            raise ApiError("ERR_PREDECESSOR_NOT_RELEASED")

    # Rung 33 — a second officer has to release what the first one authored.
    if acting_user_id() == spec["authored_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if int(spec["clause_count"]) < 1:
        raise ApiError("ERR_SPEC_HAS_NO_CLAUSES")
    if calc.dec(spec["restrictive_clause_ratio_pct"]) > calc.RESTRICTIVE_RATIO_MAX_PCT:
        raise ApiError("ERR_RESTRICTIVE_CLAUSE_RATIO_EXCEEDED")
    if calc.dec(spec["compliance_score_strict"]) < calc.RELEASE_MIN_STRICT_SCORE:
        raise ApiError("ERR_SPEC_COMPLIANCE_BELOW_THRESHOLD")

    spec["status"] = "RELEASED"
    spec["released_at"] = services.clock_raw()
    spec["released_by_user_id"] = acting_user_id()
    touch(spec)

    if predecessor is not None:
        services.supersede_predecessor(predecessor)

    return ok(spec)


# ==========================================================================
# Specification clauses — immutable, so no `updated_at` and no `version`
# ==========================================================================


@bp.post("/specifications/<specification_id>/clauses")
@authorize(PURCHASING_OFFICER)
def append_clause(specification_id):
    data = validate.body()
    clause_code = validate.req_str(data, "clause_code", 1, 24)
    category = validate.req_enum(data, "category", CLAUSE_CATEGORIES)
    requirement_text = validate.req_str(data, "requirement_text", 1, 500)
    mandatory = validate.opt_bool(data, "mandatory", True)
    is_restrictive = validate.opt_bool(data, "is_restrictive", False)

    spec = find.specification(specification_id)
    if spec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_SPEC_STATE")
    for existing in calc.spec_clauses(spec["id"]):
        if existing["clause_code"] == clause_code:
            raise ApiError("ERR_DUPLICATE_CLAUSE_CODE")

    row = new_row(
        {
            "specification_id": spec["id"],
            "clause_code": clause_code,
            "category": category,
            "requirement_text": requirement_text,
            "mandatory": mandatory,
            "is_restrictive": is_restrictive,
        },
        versioned=False,
    )
    db.clauses[row["id"]] = row
    services.recompute_spec_all(spec)
    return created(row)


@bp.get("/clauses")
@authorize(*ALL_ROLES)
def list_clauses():
    limit, offset = validate.pagination()
    specification_id = validate.query_filter("specification_id")
    category = validate.query_filter("category")
    rows = list(db.clauses.values())
    if specification_id is not None:
        rows = [r for r in rows if r["specification_id"] == specification_id]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    return listing(rows, limit, offset)


@bp.get("/clauses/<clause_id>")
@authorize(*ALL_ROLES)
def read_clause(clause_id):
    return ok(find.clause(clause_id))


# ==========================================================================
# The compliance matrix
# ==========================================================================


@bp.post("/compliance-entries")
@authorize(BODY_ENGINEER)
def file_compliance_entry():
    data = validate.body()
    specification_id = validate.req_ref(data, "specification_id")
    clause_id = validate.req_ref(data, "clause_id")
    response = validate.req_enum(data, "response", COMPLIANCE_RESPONSES)
    exception_text = validate.opt_str(data, "exception_text", 1, None)

    spec = find.specification(specification_id)
    clause = find.clause(clause_id)

    if spec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_SPEC_STATE")

    # Rung 43 — at most one entry per pair, and the clause must be the spec's own.
    if clause["specification_id"] != spec["id"]:
        raise ApiError("ERR_DUPLICATE_COMPLIANCE_ENTRY")
    for existing in calc.spec_entries(spec["id"]):
        if existing["clause_id"] == clause["id"]:
            raise ApiError("ERR_DUPLICATE_COMPLIANCE_ENTRY")

    row = new_row(
        {
            "specification_id": spec["id"],
            "clause_id": clause["id"],
            "response": response,
            "exception_text": exception_text,
            "disposition": "PENDING",
            "disposition_note": None,
            "responded_by_user_id": acting_user_id(),
        }
    )
    db.compliance_entries[row["id"]] = row
    services.recompute_spec_scores(spec)
    touch(spec)
    return created(row)


@bp.get("/compliance-entries")
@authorize(*ALL_ROLES)
def list_compliance_entries():
    limit, offset = validate.pagination()
    specification_id = validate.query_filter("specification_id")
    clause_id = validate.query_filter("clause_id")
    disposition = validate.query_filter("disposition")
    rows = list(db.compliance_entries.values())
    if specification_id is not None:
        rows = [r for r in rows if r["specification_id"] == specification_id]
    if clause_id is not None:
        rows = [r for r in rows if r["clause_id"] == clause_id]
    if disposition is not None:
        rows = [r for r in rows if r["disposition"] == disposition]
    return listing(rows, limit, offset)


@bp.get("/compliance-entries/<compliance_entry_id>")
@authorize(*ALL_ROLES)
def read_compliance_entry(compliance_entry_id):
    return ok(find.compliance_entry(compliance_entry_id))


@bp.post("/compliance-entries/<compliance_entry_id>/dispose")
@authorize(PURCHASING_OFFICER)
def dispose_compliance_entry(compliance_entry_id):
    data = validate.body()
    disposition = validate.req_enum(data, "disposition", OPERATOR_DISPOSITIONS)
    disposition_note = validate.opt_str(data, "disposition_note", 1, None)

    entry = find.compliance_entry(compliance_entry_id)
    spec = db.specifications.get(entry["specification_id"])
    if entry["disposition"] != "PENDING" or spec is None or spec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_ENTRY_STATE")

    entry["disposition"] = disposition
    entry["disposition_note"] = disposition_note
    touch(entry)
    services.recompute_spec_scores(spec)
    touch(spec)
    return ok(entry)
