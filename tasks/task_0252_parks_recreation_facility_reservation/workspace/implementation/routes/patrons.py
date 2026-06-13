"""Patron endpoints (PRD §3.1)."""
from flask import Blueprint, request

import errors
import serializers
from db import db, stamp_create, touch
from helpers import parse_body, require_fields, require_enum, paginate, sort_by_created
from middleware import get_identity, require_roles
from response import success
from services import calculations as calc

bp = Blueprint("patrons", __name__)


@bp.post("/patrons")
def create_patron():
    _, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron"})
    body = parse_body()
    require_fields(body, ["full_name", "email", "residency"])
    if not isinstance(body["full_name"], str) or not isinstance(body["email"], str):
        raise errors.err(errors.ERR_VALIDATION, "full_name and email must be strings")
    require_enum(body, "residency", {"RESIDENT", "NON_RESIDENT"})

    # email unique across patrons
    for p in db.patrons.values():
        if p["email"] == body["email"]:
            raise errors.err(errors.ERR_VALIDATION, "email must be unique across patrons")

    rec = {
        "full_name": body["full_name"],
        "email": body["email"],
        "residency": body["residency"],
        "residency_verified": False,
        "standing": "GOOD",
        "no_show_strikes": 0,
        "wallet_credit_cents": 0,
    }
    stamp_create(rec)
    db.patrons[rec["id"]] = rec
    return success(serializers.patron(rec), status=201)


def _get_patron_or_404(patron_id):
    p = db.patrons.get(patron_id)
    if p is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Patron not found")
    return p


@bp.get("/patrons/<patron_id>")
def get_patron(patron_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron", "FinanceClerk"})
    p = _get_patron_or_404(patron_id)
    return success(serializers.patron(p))


@bp.post("/patrons/<patron_id>/verify-residency")
def verify_residency(patron_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator"})
    p = _get_patron_or_404(patron_id)
    p["residency_verified"] = True
    touch(p)
    return success(serializers.patron(p))


@bp.get("/patrons/<patron_id>/permits")
def list_patron_permits(patron_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron", "FinanceClerk"})
    _get_patron_or_404(patron_id)
    items = [p for p in db.permits.values() if p["patron_id"] == patron_id]
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items, request.args)
    return success([serializers.permit(p) for p in page], pagination=meta)


@bp.get("/patrons/<patron_id>/insurance-certificates")
def list_patron_cois(patron_id):
    _, role = get_identity()
    require_roles(role, {"RecCoordinator", "Patron"})
    _get_patron_or_404(patron_id)
    items = [c for c in db.insurance_certificates.values() if c["patron_id"] == patron_id]
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items, request.args)
    return success([serializers.insurance_certificate(c) for c in page], pagination=meta)
