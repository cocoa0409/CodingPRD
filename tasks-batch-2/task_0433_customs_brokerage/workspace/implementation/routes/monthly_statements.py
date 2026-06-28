"""Monthly statement endpoints (PRD §3.8)."""
from flask import Blueprint

from db import db
from errors import err
from helpers import (
    get_body, require_str, stamp_create, bump_version, lookup, list_response,
    validate_period_month,
)
from middleware import require_roles
from response import object_response
from serializers import statement_view

bp = Blueprint("monthly_statements", __name__)


@bp.post("/monthly-statements")
@require_roles("AccountAdmin")
def create_statement():
    body = get_body()
    importer_id = body.get("importer_id")
    if not isinstance(importer_id, str) or importer_id == "":
        raise err("ERR_VALIDATION", "importer_id is required.")
    period_month = require_str(body, "period_month")

    # existence (404).
    lookup(db.importers, importer_id)

    # format (priority 12) before period overlap (priority 19).
    validate_period_month(period_month)

    # A second OPEN statement for the same importer + month overlaps.
    for s in db.monthly_statements.values():
        if (
            s["importer_id"] == importer_id
            and s["period_month"] == period_month
            and s["status"] == "OPEN"
        ):
            raise err("ERR_STATEMENT_PERIOD_OVERLAP", "An OPEN statement for this importer/month exists.")

    rec = {
        "importer_id": importer_id,
        "period_month": period_month,
        "statement_total_cents": 0,
        "entry_count": 0,
        "status": "OPEN",
    }
    stamp_create(rec)
    db.monthly_statements[rec["id"]] = rec
    return object_response(statement_view(rec), status=201)


@bp.get("/monthly-statements/<id>")
@require_roles("AccountAdmin", "ImporterUser", "LicensedBroker", "CBPOfficer")
def get_statement(id):
    return object_response(statement_view(lookup(db.monthly_statements, id)))


@bp.get("/monthly-statements")
@require_roles("AccountAdmin", "ImporterUser", "LicensedBroker", "CBPOfficer")
def list_statements():
    return list_response(
        db.monthly_statements.values(), statement_view,
        filters=[("importer_id", "importer_id")],
    )


@bp.post("/monthly-statements/<id>/settle")
@require_roles("AccountAdmin")
def settle_statement(id):
    statement = lookup(db.monthly_statements, id)
    if statement["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Statement is not OPEN.")
    # Every entry on this statement must be LIQUIDATED.
    scheduled = [e for e in db.entries.values() if e.get("statement_id") == statement["id"]]
    if any(e["status"] != "LIQUIDATED" for e in scheduled):
        raise err("ERR_INVALID_STATE", "Not all entries on the statement are LIQUIDATED.")
    statement["status"] = "SETTLED"
    bump_version(statement)
    return object_response(statement_view(statement))
