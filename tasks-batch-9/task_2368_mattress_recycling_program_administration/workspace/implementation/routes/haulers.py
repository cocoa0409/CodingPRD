"""Contract haulers."""

from flask import Blueprint, request

import response
from db import db
from middleware import ADMIN, AUDITOR, HAULER, SITE_OPERATOR, auth, get_hauler, get_program
from util import (F, apply_filters, base_record, pagination, paginate, public,
                  sort_records, validate_body)

bp = Blueprint("haulers", __name__)

READ_ROLES = [ADMIN, AUDITOR, HAULER, SITE_OPERATOR]


@bp.post("/haulers")
def create_hauler():
    auth([ADMIN])
    body = validate_body([
        F("state_program_id", "string"),
        F("company_name", "string"),
        F("service_regions", "array", min_items=1),
        F("per_unit_rate_cents", "int", minimum=0),
        F("per_km_rate_cents", "int", minimum=0),
        F("max_route_payment_cents", "int", minimum=1),
        F("max_concurrent_routes", "int", required=False, minimum=1),
    ])
    program = get_program(body["state_program_id"])
    rec = base_record()
    rec.update({
        "state_program_id": program["id"],
        "company_name": body["company_name"],
        "service_regions": list(body["service_regions"]),
        "per_unit_rate_cents": body["per_unit_rate_cents"],
        "per_km_rate_cents": body["per_km_rate_cents"],
        "max_route_payment_cents": body["max_route_payment_cents"],
        "max_concurrent_routes": body.get("max_concurrent_routes", 2),
        "active_route_count": 0,
        "total_paid_cents": 0,
    })
    db.haulers[rec["id"]] = rec
    return response.obj(public(rec), 201)


@bp.get("/haulers/<hauler_id>")
def read_hauler(hauler_id):
    auth(READ_ROLES)
    return response.obj(public(get_hauler(hauler_id)))


@bp.get("/haulers")
def list_haulers():
    auth(READ_ROLES)
    limit, offset = pagination()
    records = sort_records(list(db.haulers.values()))
    records = apply_filters(records, [("state_program_id", "state_program_id")])
    region = request.args.get("region_code")
    if region:
        records = [r for r in records if region in r["service_regions"]]
    window, total = paginate(records, limit, offset)
    return response.arr([public(r) for r in window], limit, offset, total)
