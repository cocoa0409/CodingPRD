"""Insurance certificate (COI) endpoints (PRD §3.10)."""
from flask import Blueprint, request

import errors
import serializers
from clock import now as clock_now
from db import db, stamp_create, touch
from helpers import (parse_body, require_fields, require_int, parse_dt,
                     paginate, sort_by_created)
from middleware import get_identity, require_roles
from response import success

bp = Blueprint("insurance", __name__)


def get_coi_or_404(coi_id):
    c = db.insurance_certificates.get(coi_id)
    if c is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Insurance certificate not found")
    return c


@bp.post("/insurance-certificates")
def create_coi():
    user_id, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron"})
    body = parse_body()
    require_fields(body, ["patron_id", "coverage_amount_cents", "effective_date", "expiry_date"])

    patron = db.patrons.get(body["patron_id"])
    if patron is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Patron not found")

    # Ownership: a Patron may only create a COI for themselves.
    if role == "Patron" and body["patron_id"] != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER,
                         "Patron may only upload a certificate for themselves")

    coverage = require_int(body, "coverage_amount_cents", minimum=0)
    effective = parse_dt(body["effective_date"], "effective_date")
    expiry = parse_dt(body["expiry_date"], "expiry_date")

    status = "ACTIVE"
    if expiry <= clock_now():
        status = "EXPIRED"

    rec = {
        "patron_id": body["patron_id"],
        "coverage_amount_cents": coverage,
        "effective_date": effective,
        "expiry_date": expiry,
        "status": status,
    }
    stamp_create(rec)
    db.insurance_certificates[rec["id"]] = rec
    return success(serializers.insurance_certificate(rec), status=201)


@bp.get("/insurance-certificates/<coi_id>")
def get_coi(coi_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron"})
    c = get_coi_or_404(coi_id)
    return success(serializers.insurance_certificate(c))


@bp.get("/insurance-certificates")
def list_cois():
    _, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron"})
    items = list(db.insurance_certificates.values())
    patron_id = request.args.get("patron_id")
    if patron_id:
        items = [c for c in items if c["patron_id"] == patron_id]
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items, request.args)
    return success([serializers.insurance_certificate(c) for c in page], pagination=meta)


@bp.post("/insurance-certificates/<coi_id>/revoke")
def revoke_coi(coi_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator"})
    c = get_coi_or_404(coi_id)
    if c["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Only an ACTIVE certificate can be revoked")
    c["status"] = "REVOKED"
    touch(c)
    return success(serializers.insurance_certificate(c))
