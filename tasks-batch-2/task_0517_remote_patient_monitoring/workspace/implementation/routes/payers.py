"""Payer endpoints (PRD §3.1)."""
from flask import Blueprint

import errors
import serializers
import validation as V
from common import get_json_body, parse_pagination, sort_by_created, paginate
from db import db, stamp_create
from middleware import require_roles
from response import object_response, array_response

bp = Blueprint("payers", __name__)

PAYER_TYPES = {"MEDICARE", "MEDICARE_ADVANTAGE", "COMMERCIAL"}


@bp.post("/payers")
@require_roles("BillingSpecialist")
def create_payer():
    body = get_json_body()
    name = V.require_string(body, "name")
    payer_type = V.require_enum(body, "payer_type", PAYER_TYPES)
    rate_99453 = V.require_int(body, "rate_99453_cents", minimum=0)
    rate_99454 = V.require_int(body, "rate_99454_cents", minimum=0)
    rate_99457 = V.require_int(body, "rate_99457_cents", minimum=0)
    requires_active_consent = V.optional_bool(body, "requires_active_consent", True)
    timely_filing_days = V.optional_int(body, "timely_filing_days", 90, minimum=1)

    rec = {
        "name": name,
        "payer_type": payer_type,
        "rate_99453_cents": rate_99453,
        "rate_99454_cents": rate_99454,
        "rate_99457_cents": rate_99457,
        "requires_active_consent": requires_active_consent,
        "timely_filing_days": timely_filing_days,
    }
    stamp_create(rec)
    db.payers[rec["id"]] = rec
    return object_response(serializers.payer(rec), 201)


@bp.get("/payers/<pid>")
@require_roles("BillingSpecialist", "CareCoordinator")
def get_payer(pid):
    rec = db.payers.get(pid)
    if rec is None:
        raise errors.not_found("Payer not found.")
    return object_response(serializers.payer(rec))


@bp.get("/payers")
@require_roles("BillingSpecialist", "CareCoordinator")
def list_payers():
    limit, offset = parse_pagination()
    records = sort_by_created(list(db.payers.values()))
    page, total = paginate(records, limit, offset)
    return array_response([serializers.payer(r) for r in page],
                          limit, offset, total)
