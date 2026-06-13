"""Facility endpoints (PRD §3.2)."""
from flask import Blueprint, request

import errors
import serializers
from db import db, stamp_create, touch
from helpers import (parse_body, require_fields, require_int, require_number,
                     require_enum, paginate, sort_by_created)
from middleware import get_identity, require_roles
from response import success

bp = Blueprint("facilities", __name__)


def get_facility_or_404(facility_id):
    f = db.facilities.get(facility_id)
    if f is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Facility not found")
    return f


@bp.post("/facilities")
def create_facility():
    _, role = get_identity()
    require_roles(role, {"RecCoordinator"})
    body = parse_body()
    require_fields(body, ["name", "facility_type", "hourly_rate_cents",
                          "resident_discount_pct", "prime_multiplier",
                          "prime_start_hour", "prime_end_hour"])
    if not isinstance(body["name"], str):
        raise errors.err(errors.ERR_VALIDATION, "name must be a string")
    require_enum(body, "facility_type", {"FIELD", "COURT", "POOL", "PAVILION"})
    require_int(body, "hourly_rate_cents", minimum=0)

    disc = require_number(body, "resident_discount_pct")
    if not (0 <= disc < 1):
        raise errors.err(errors.ERR_VALIDATION, "resident_discount_pct must be >= 0 and < 1")
    require_number(body, "prime_multiplier")

    prime_start = require_int(body, "prime_start_hour", minimum=0, maximum=23)
    prime_end = require_int(body, "prime_end_hour")
    if not (prime_start < prime_end <= 24):
        raise errors.err(errors.ERR_VALIDATION, "prime_end_hour must be > prime_start_hour and <= 24")

    buffer_minutes = 0
    if "buffer_minutes" in body and body["buffer_minutes"] is not None:
        buffer_minutes = require_int(body, "buffer_minutes", minimum=0)
    deposit_cents = 0
    if "deposit_cents" in body and body["deposit_cents"] is not None:
        deposit_cents = require_int(body, "deposit_cents", minimum=0)
    requires_coi = False
    if "requires_coi" in body and body["requires_coi"] is not None:
        if not isinstance(body["requires_coi"], bool):
            raise errors.err(errors.ERR_VALIDATION, "requires_coi must be boolean")
        requires_coi = body["requires_coi"]
    min_coi = 0
    if "min_coi_coverage_cents" in body and body["min_coi_coverage_cents"] is not None:
        min_coi = require_int(body, "min_coi_coverage_cents", minimum=0)

    rec = {
        "name": body["name"],
        "facility_type": body["facility_type"],
        "status": "OPEN",
        "hourly_rate_cents": body["hourly_rate_cents"],
        "resident_discount_pct": disc,
        "prime_multiplier": body["prime_multiplier"],
        "prime_start_hour": prime_start,
        "prime_end_hour": prime_end,
        "buffer_minutes": buffer_minutes,
        "deposit_cents": deposit_cents,
        "requires_coi": requires_coi,
        "min_coi_coverage_cents": min_coi,
        "granted_permit_count": 0,
    }
    stamp_create(rec)
    db.facilities[rec["id"]] = rec
    return success(serializers.facility(rec), status=201)


@bp.get("/facilities/<facility_id>")
def get_facility(facility_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron", "FinanceClerk"})
    f = get_facility_or_404(facility_id)
    return success(serializers.facility(f))


@bp.patch("/facilities/<facility_id>")
def update_facility(facility_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator"})
    f = get_facility_or_404(facility_id)
    body = parse_body()

    # OCC guard for the reconfigure edit (PRD §2.6 / §3.2).
    require_fields(body, ["expected_facility_version"])
    expected = body["expected_facility_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.err(errors.ERR_VALIDATION, "expected_facility_version must be an integer")
    if expected != f["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "expected_facility_version does not match")

    if "status" in body and body["status"] is not None:
        require_enum(body, "status", {"OPEN", "CLOSED"})
        f["status"] = body["status"]
    if "buffer_minutes" in body and body["buffer_minutes"] is not None:
        f["buffer_minutes"] = require_int(body, "buffer_minutes", minimum=0)
    if "deposit_cents" in body and body["deposit_cents"] is not None:
        f["deposit_cents"] = require_int(body, "deposit_cents", minimum=0)
    if "requires_coi" in body and body["requires_coi"] is not None:
        if not isinstance(body["requires_coi"], bool):
            raise errors.err(errors.ERR_VALIDATION, "requires_coi must be boolean")
        f["requires_coi"] = body["requires_coi"]
    if "min_coi_coverage_cents" in body and body["min_coi_coverage_cents"] is not None:
        f["min_coi_coverage_cents"] = require_int(body, "min_coi_coverage_cents", minimum=0)

    touch(f)
    return success(serializers.facility(f))


@bp.get("/facilities/<facility_id>/permits")
def list_facility_permits(facility_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron", "FinanceClerk"})
    get_facility_or_404(facility_id)
    items = [p for p in db.permits.values() if p["facility_id"] == facility_id]
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items, request.args)
    return success([serializers.permit(p) for p in page], pagination=meta)
