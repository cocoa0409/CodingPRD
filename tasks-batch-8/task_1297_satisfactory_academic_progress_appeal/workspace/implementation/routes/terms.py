"""Term endpoints: create, read, close-grading, evaluate."""

from datetime import date

from flask import Blueprint

import errors
from db import _new_id, now, store
from middleware import authenticate, get_body, require_roles
from response import success
from serializers import pub_term
from services import audit
from services.pipeline import run_term_evaluation

bp = Blueprint("terms", __name__)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _parse_date(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@bp.post("/sap/terms")
def create_term():
    authenticate()
    require_roles("Registrar")
    body = get_body()

    # Term date exclusivity (15) is evaluated before body well-formedness (22).
    start = _parse_date(body.get("start_date"))
    end = _parse_date(body.get("end_date"))
    if start is not None and end is not None:
        for t in store.terms.values():
            ex_start = _parse_date(t["start_date"])
            ex_end = _parse_date(t["end_date"])
            if ex_start is None or ex_end is None:
                continue
            # Closed-interval semantics: touching endpoints count as overlap.
            if start <= ex_end and ex_start <= end:
                errors.fail(errors.ERR_TERM_DATE_OVERLAP,
                            "Term date range intersects an existing term")

    code = body.get("code")
    if not isinstance(code, str):
        errors.fail(errors.ERR_INVALID_REQUEST, "code is required")
    seq = body.get("seq")
    if not _is_int(seq):
        errors.fail(errors.ERR_INVALID_REQUEST, "seq must be an integer")
    if start is None or end is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "start_date and end_date must be ISO dates")
    if start > end:
        errors.fail(errors.ERR_INVALID_REQUEST, "start_date must be on or before end_date")

    ts = now()
    row = {
        "id": _new_id(),
        "code": code,
        "seq": seq,
        "start_date": body["start_date"],
        "end_date": body["end_date"],
        "status": "OPEN",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.terms[row["id"]] = row
    audit.record("TERM_CREATED", "Term", row["id"], None, None, pub_term(row))
    return success(pub_term(row), status=201)


@bp.get("/sap/terms/<tid>")
def get_term(tid):
    authenticate()
    require_roles("Student", "Registrar", "AidOfficer", "CommitteeMember", "Auditor", "AidAdministrator")
    row = store.terms.get(tid)
    if row is None:
        errors.fail(errors.ERR_NOT_FOUND, "Term %s does not exist" % tid)
    return success(pub_term(row))


@bp.post("/sap/terms/<tid>/close-grading")
def close_grading(tid):
    authenticate()
    require_roles("Registrar")
    term = store.terms.get(tid)
    if term is None:
        errors.fail(errors.ERR_NOT_FOUND, "Term %s does not exist" % tid)
    if term["status"] != "OPEN":
        errors.fail(errors.ERR_INVALID_STATE,
                    "Grading can only be closed from OPEN")
    for e in store.enrollments.values():
        if e["term_id"] == tid and e["status"] == "IN_PROGRESS":
            errors.fail(errors.ERR_ENROLLMENTS_PENDING,
                        "In-progress enrollments remain in this term")
    before = pub_term(term)
    term["status"] = "GRADING_CLOSED"
    term["updated_at"] = now()
    term["version"] += 1
    audit.record("TERM_GRADING_CLOSED", "Term", term["id"], None, before, pub_term(term))
    return success(pub_term(term))


@bp.post("/sap/terms/<tid>/evaluate")
def evaluate_term(tid):
    authenticate()
    require_roles("AidOfficer")
    term = store.terms.get(tid)
    if term is None:
        errors.fail(errors.ERR_NOT_FOUND, "Term %s does not exist" % tid)
    # From-state validity (EVALUATED is terminal) precedes the readiness check.
    if term["status"] == "EVALUATED":
        errors.fail(errors.ERR_INVALID_STATE, "Term has already been evaluated")
    if term["status"] != "GRADING_CLOSED":
        errors.fail(errors.ERR_TERM_NOT_READY,
                    "Term must be grading-closed before evaluation")
    summary = run_term_evaluation(term)
    return success(summary)
