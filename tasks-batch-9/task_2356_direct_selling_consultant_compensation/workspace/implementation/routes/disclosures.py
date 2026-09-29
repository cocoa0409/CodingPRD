"""Income disclosure statements: population bases, distribution metrics, publication."""

from flask import Blueprint

from common import (
    clock_str,
    new_row,
    opt_str,
    pagination,
    paginate,
    q_enum,
    q_str,
    raw_body,
    req_enum,
    req_int,
    req_str,
    touch,
)
from db import db
from errors import ApiError
from middleware import actor_id, auth
from response import created, ok, ok_list
from services.disclosure import metrics, population_earnings
from services.genealogy import by_created
from services.lookup import fetch

bp = Blueprint("disclosures", __name__)

DISCLOSURE_STATUSES = ("DRAFT", "LEGAL_REVIEW", "PUBLISHED", "SUPERSEDED")
POPULATION_BASES = ("ALL_ENROLLED", "PAID_ONLY")

READ_ROLES = [
    "Consultant",
    "CommissionAnalyst",
    "FinanceController",
    "LegalReviewer",
    "PlatformAdmin",
]


def _context(run):
    period = db.periods.get(run["qualification_period_id"])
    plan = db.plans.get(period["compensation_plan_id"]) if period else None
    return period, plan


def _recompute(disclosure, run):
    period, plan = _context(run)
    earnings = population_earnings(run, plan, period, disclosure["population_basis"])
    disclosure.update(metrics(earnings))


@bp.post("/income-disclosure-statements")
def create_disclosure():
    auth(["CommissionAnalyst"])
    body = raw_body()
    commission_run_id = req_str(body, "commission_run_id", min_len=1)
    population_basis = req_enum(body, "population_basis", POPULATION_BASES)
    expected_version = req_int(body, "expected_commission_run_version", minimum=0)

    run = fetch("run", commission_run_id)

    if expected_version != int(run["version"]):
        raise ApiError("ERR_STALE_RUN_VERSION")
    if run["status"] != "PAID":
        raise ApiError("ERR_RUN_NOT_PAID")

    period, plan = _context(run)
    earnings = population_earnings(run, plan, period, population_basis)
    if not earnings:
        raise ApiError("ERR_DISCLOSURE_POPULATION_EMPTY")

    row = new_row()
    row.update(
        {
            "commission_run_id": run["id"],
            "period_code": run["period_code"],
            "population_basis": population_basis,
            "status": "DRAFT",
            "revision_number": 0,
            "submitted_by_user_id": None,
            "legal_reviewer_user_id": None,
            "published_at": None,
            "superseded_by_id": None,
            "supersede_reason": None,
            "revision_note": None,
        }
    )
    row.update(metrics(earnings))
    db.disclosures[row["id"]] = row

    touch(run)
    return created(row)


@bp.get("/income-disclosure-statements")
def list_disclosures():
    auth(READ_ROLES)
    limit, offset = pagination()
    filters = {
        "commission_run_id": q_str("commission_run_id"),
        "superseded_by_id": q_str("superseded_by_id"),
        "period_code": q_str("period_code"),
        "population_basis": q_enum("population_basis", POPULATION_BASES),
        "status": q_enum("status", DISCLOSURE_STATUSES),
    }
    rows = by_created(list(db.disclosures.values()))
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/income-disclosure-statements/<statement_id>")
def read_disclosure(statement_id):
    auth(READ_ROLES)
    return ok(fetch("disclosure", statement_id))


@bp.post("/income-disclosure-statements/<statement_id>/submit-legal-review")
def submit_legal_review(statement_id):
    auth(["CommissionAnalyst"])
    disclosure = fetch("disclosure", statement_id)
    if disclosure["status"] != "DRAFT":
        raise ApiError("ERR_DISCLOSURE_NOT_DRAFT")

    disclosure["status"] = "LEGAL_REVIEW"
    disclosure["submitted_by_user_id"] = actor_id()
    touch(disclosure)
    return ok(disclosure)


@bp.post("/income-disclosure-statements/<statement_id>/legal-decision")
def legal_decision(statement_id):
    auth(["LegalReviewer"])
    body = raw_body()
    decision = req_enum(body, "decision", ("PUBLISH", "REQUEST_REVISION"))
    revision_note = opt_str(body, "revision_note")

    disclosure = fetch("disclosure", statement_id)
    if (
        disclosure["submitted_by_user_id"] is not None
        and actor_id() == disclosure["submitted_by_user_id"]
    ):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    run = db.runs.get(disclosure["commission_run_id"])
    if run is None or run["status"] != "PAID":
        raise ApiError("ERR_RUN_NOT_PAID")
    if disclosure["status"] != "LEGAL_REVIEW":
        raise ApiError("ERR_DISCLOSURE_NOT_IN_REVIEW")
    if decision == "REQUEST_REVISION" and revision_note is None:
        raise ApiError("ERR_REVISION_NOTE_REQUIRED")

    if decision == "PUBLISH":
        disclosure["status"] = "PUBLISHED"
        disclosure["published_at"] = clock_str()
        disclosure["legal_reviewer_user_id"] = actor_id()
        touch(disclosure)
        for other in by_created(list(db.disclosures.values())):
            if other["id"] == disclosure["id"]:
                continue
            if other["commission_run_id"] != run["id"] or other["status"] != "PUBLISHED":
                continue
            other["status"] = "SUPERSEDED"
            other["supersede_reason"] = "NEWER_PUBLICATION"
            other["superseded_by_id"] = disclosure["id"]
            touch(other)
    else:
        disclosure["status"] = "DRAFT"
        disclosure["revision_number"] = int(disclosure["revision_number"]) + 1
        disclosure["revision_note"] = revision_note
        disclosure["submitted_by_user_id"] = None
        _recompute(disclosure, run)
        touch(disclosure)

    return ok(disclosure)
