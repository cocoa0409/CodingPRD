"""Portfolios, evidence artifacts and self-reported coverage."""
from flask import Blueprint, request

from db import (artifacts_of_portfolio, db, new_row, order_rows,
                outcomes_of_course, portfolio_of_claim)
from errors import ApiError
from middleware import (ROLE_ASSESSOR, ROLE_COORDINATOR, ROLE_REVIEWER,
                        ROLE_STUDENT, authenticate, enforce_student_scope,
                        find_or_404, scoped_artifact, scoped_portfolio)
from response import created, no_content, ok, ok_list, read_pagination
from serializers import artifact_out, portfolio_out
from services.coverage import portfolio_provisional_coverage
from util import (MIN_PROVISIONAL_COVERAGE_BP, as_enum, as_id, as_str,
                  json_body, present, put_dt, require, touch)

bp = Blueprint("portfolios", __name__)

READ_ROLES = [ROLE_COORDINATOR, ROLE_ASSESSOR, ROLE_REVIEWER, ROLE_STUDENT]
EDITABLE_STATUSES = ("DRAFT", "REVISION_REQUESTED")
ARTIFACT_TYPES = ["WORK_PRODUCT", "EMPLOYER_LETTER", "TRAINING_CERTIFICATE",
                  "LICENSE", "MILITARY_RECORD", "SUPERVISOR_EVALUATION"]
ALIGNMENTS = ["PRIMARY", "SUPPORTING"]


def _course_of_portfolio(portfolio):
    claim = db.claims.get(portfolio["claim_id"])
    if claim is None:
        return None, None
    return claim, db.courses.get(claim["course_id"])


def _refresh_coverage(portfolio):
    claim, course = _course_of_portfolio(portfolio)
    if course is not None:
        portfolio["provisional_coverage_bp"] = portfolio_provisional_coverage(portfolio, course)
    return claim, course


# ---------------------------------------------------------------- portfolios
@bp.post("/portfolios")
def create_portfolio():
    authenticate([ROLE_STUDENT])
    body = json_body()
    claim = None
    if present(body, "claim_id") and isinstance(body["claim_id"], str):
        claim = db.claims.get(body["claim_id"])
        if claim is None:
            raise ApiError("ERR_CLAIM_NOT_FOUND")
    as_id(require(body, "claim_id"), "claim_id")
    narrative = None
    if present(body, "narrative"):
        narrative = as_str(body["narrative"], "narrative", 1)
    # rung 9c
    if claim["source_type"] != "PORTFOLIO":
        raise ApiError("ERR_PORTFOLIO_NOT_ALLOWED_FOR_SOURCE")
    if portfolio_of_claim(claim["id"]) is not None:
        raise ApiError("ERR_PORTFOLIO_ALREADY_EXISTS")

    portfolio = new_row("Portfolio")
    portfolio["claim_id"] = claim["id"]
    portfolio["narrative"] = narrative
    portfolio["status"] = "DRAFT"
    portfolio["artifact_count"] = 0
    portfolio["provisional_coverage_bp"] = None
    portfolio["verified_coverage_bp"] = None
    portfolio["revision_round"] = 0
    put_dt(portfolio, "submitted_at", None)
    db.portfolios[portfolio["id"]] = portfolio
    return created(portfolio_out(portfolio))


@bp.get("/portfolios/<portfolio_id>")
def read_portfolio(portfolio_id):
    ctx = authenticate(READ_ROLES)
    portfolio = scoped_portfolio(ctx, portfolio_id)
    return ok(portfolio_out(portfolio))


@bp.get("/portfolios")
def list_portfolios():
    authenticate(READ_ROLES)
    limit, offset = read_pagination()
    rows = list(db.portfolios.values())
    for name in ("claim_id", "status"):
        wanted = request.args.get(name)
        if wanted is not None and wanted != "":
            rows = [r for r in rows if r.get(name) == wanted]
    rows = order_rows(rows, [(lambda r: r["created_at"], False)])
    return ok_list(rows, portfolio_out, limit, offset)


@bp.post("/portfolios/<portfolio_id>/submit")
def submit_portfolio(portfolio_id):
    ctx = authenticate([ROLE_STUDENT])
    portfolio = scoped_portfolio(ctx, portfolio_id)
    # rung 16
    if portfolio["status"] not in EDITABLE_STATUSES:
        raise ApiError("ERR_PORTFOLIO_NOT_SUBMITTABLE")
    # rung 34
    if portfolio["artifact_count"] < 1:
        raise ApiError("ERR_PORTFOLIO_NO_ARTIFACTS")
    claim, course = _refresh_coverage(portfolio)
    # rung 35
    if (portfolio["provisional_coverage_bp"] or 0) < MIN_PROVISIONAL_COVERAGE_BP:
        raise ApiError("ERR_INSUFFICIENT_OUTCOME_COVERAGE")

    portfolio["status"] = "SUBMITTED"
    put_dt(portfolio, "submitted_at", db.clock)
    touch(portfolio)
    if claim is not None:
        claim["provisional_coverage_bp"] = portfolio["provisional_coverage_bp"]
        touch(claim)
    return ok(portfolio_out(portfolio))


# ---------------------------------------------------------------- artifacts
def _validate_mappings(value, course):
    if not isinstance(value, list) or len(value) < 1 or len(value) > 12:
        raise ApiError("ERR_INVALID_REQUEST", "outcome_mappings must hold between 1 and 12 entries")
    seen = set()
    mappings = []
    for entry in value:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "each outcome_mapping must be an object")
        outcome_id = as_id(entry.get("learning_outcome_id"), "learning_outcome_id")
        alignment = as_enum(entry.get("alignment"), "alignment", ALIGNMENTS)
        if outcome_id in seen:
            raise ApiError("ERR_INVALID_REQUEST", "outcome_mappings must not repeat a learning_outcome_id")
        seen.add(outcome_id)
        mappings.append({"learning_outcome_id": outcome_id, "alignment": alignment})
    # rung 23
    allowed = set(o["id"] for o in outcomes_of_course(course["id"])) if course is not None else set()
    for mapping in mappings:
        if mapping["learning_outcome_id"] not in allowed:
            raise ApiError("ERR_OUTCOME_NOT_IN_COURSE")
    return mappings


@bp.post("/portfolios/<portfolio_id>/artifacts")
def add_artifact(portfolio_id):
    ctx = authenticate([ROLE_STUDENT])
    portfolio = scoped_portfolio(ctx, portfolio_id)
    body = json_body()
    artifact_type = as_enum(require(body, "artifact_type"), "artifact_type", ARTIFACT_TYPES)
    title = as_str(require(body, "title"), "title", 1)
    evidence_uri = as_str(require(body, "evidence_uri"), "evidence_uri", 1)
    raw_mappings = require(body, "outcome_mappings")
    description = None
    if present(body, "description"):
        description = as_str(body["description"], "description", 1)
    # rung 16
    if portfolio["status"] not in EDITABLE_STATUSES:
        raise ApiError("ERR_PORTFOLIO_NOT_EDITABLE")
    claim, course = _course_of_portfolio(portfolio)
    mappings = _validate_mappings(raw_mappings, course)

    artifact = new_row("Artifact", extra_lean=True)
    artifact["portfolio_id"] = portfolio["id"]
    artifact["artifact_type"] = artifact_type
    artifact["title"] = title
    artifact["description"] = description
    artifact["evidence_uri"] = evidence_uri
    artifact["outcome_mappings"] = mappings
    db.artifacts[artifact["id"]] = artifact

    portfolio["artifact_count"] += 1
    _refresh_coverage(portfolio)
    touch(portfolio)
    return created(artifact_out(artifact))


@bp.delete("/portfolios/<portfolio_id>/artifacts/<artifact_id>")
def delete_artifact(portfolio_id, artifact_id):
    ctx = authenticate([ROLE_STUDENT])
    portfolio = scoped_portfolio(ctx, portfolio_id)
    artifact = db.artifacts.get(artifact_id)
    if artifact is None or artifact["portfolio_id"] != portfolio["id"]:
        raise ApiError("ERR_ARTIFACT_NOT_FOUND")
    # rung 16
    if portfolio["status"] not in EDITABLE_STATUSES:
        raise ApiError("ERR_PORTFOLIO_NOT_EDITABLE")

    del db.artifacts[artifact_id]
    portfolio["artifact_count"] = max(0, portfolio["artifact_count"] - 1)
    _refresh_coverage(portfolio)
    touch(portfolio)
    return no_content()


@bp.get("/artifacts/<artifact_id>")
def read_artifact(artifact_id):
    ctx = authenticate(READ_ROLES)
    artifact = scoped_artifact(ctx, artifact_id)
    return ok(artifact_out(artifact))


@bp.get("/artifacts")
def list_artifacts():
    authenticate(READ_ROLES)
    limit, offset = read_pagination()
    rows = list(db.artifacts.values())
    for name in ("portfolio_id", "artifact_type"):
        wanted = request.args.get(name)
        if wanted is not None and wanted != "":
            rows = [r for r in rows if r.get(name) == wanted]
    rows = order_rows(rows, [(lambda r: r["created_at"], False)])
    return ok_list(rows, artifact_out, limit, offset)
