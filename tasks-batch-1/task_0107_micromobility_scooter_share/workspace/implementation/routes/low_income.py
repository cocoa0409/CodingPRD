"""LowIncomeApplication endpoints (PRD §3.2).

POST /api/low-income-applications              — Rider
GET  /api/low-income-applications/{id}          — PlatformAdmin, Rider
GET  /api/low-income-applications               — PlatformAdmin
POST /api/low-income-applications/{id}/approve  — PlatformAdmin
POST /api/low-income-applications/{id}/reject   — PlatformAdmin
"""
from flask import Blueprint, request

import constants
import errors
from db import db, stamp_new, touch
from middleware import authenticate, require_role, require_rider_owner
from response import success
from util import (
    get_json_body, require_fields, require_int, require_string,
    public, parse_pagination, paginate,
)

bp = Blueprint("low_income", __name__)


@bp.post("/api/low-income-applications")
def create_application():
    role, user_id = authenticate()
    require_role(role, {"Rider"})

    body = get_json_body()
    require_fields(body, ["rider_id", "household_size", "annual_income_cents"])
    require_string(body["rider_id"], "rider_id")

    # Ownership: a Rider submits only on their own behalf (PRD §2.1). Checked
    # against the body rider_id after the reference is confirmed to exist.
    rider = db.riders.get(body["rider_id"])
    if rider is None:
        raise errors.reference_not_found("rider_id does not reference a rider")
    require_rider_owner(role, user_id, rider["id"])

    require_int(body["household_size"], "household_size", minimum=1)
    require_int(body["annual_income_cents"], "annual_income_cents", minimum=0)

    app_rec = {
        "rider_id": body["rider_id"],
        "household_size": body["household_size"],
        "annual_income_cents": body["annual_income_cents"],
        "status": "SUBMITTED",
    }
    stamp_new(app_rec)
    db.low_income_applications[app_rec["id"]] = app_rec
    return success(public(app_rec), status=201)


@bp.get("/api/low-income-applications/<app_id>")
def get_application(app_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Rider"})
    app_rec = _require_app(app_id)
    require_rider_owner(role, user_id, app_rec["rider_id"])
    return success(public(app_rec))


@bp.get("/api/low-income-applications")
def list_applications():
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})
    limit, offset = parse_pagination()

    rows = list(db.low_income_applications.values())
    rider_id = request.args.get("rider_id")
    if rider_id is not None:
        rows = [r for r in rows if r["rider_id"] == rider_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page, pagination = paginate(rows, limit, offset)
    return success(page, is_array=True, pagination=pagination)


@bp.post("/api/low-income-applications/<app_id>/approve")
def approve(app_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})
    app_rec = _require_app(app_id)
    if app_rec["status"] != "SUBMITTED":
        raise errors.invalid_state("Application is not SUBMITTED")
    # Income-ceiling check (PRD §3.2): annual_income <= 3,000,000 * household_size.
    ceiling = constants.INCOME_CEILING_PER_PERSON_CENTS * app_rec["household_size"]
    if app_rec["annual_income_cents"] > ceiling:
        raise errors.invalid_state("Declared income exceeds the low-income ceiling")
    app_rec["status"] = "APPROVED"
    touch(app_rec)
    return success(public(app_rec))


@bp.post("/api/low-income-applications/<app_id>/reject")
def reject(app_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})
    app_rec = _require_app(app_id)
    if app_rec["status"] != "SUBMITTED":
        raise errors.invalid_state("Application is not SUBMITTED")
    app_rec["status"] = "REJECTED"
    touch(app_rec)
    return success(public(app_rec))


def _require_app(app_id):
    app_rec = db.low_income_applications.get(app_id)
    if app_rec is None:
        raise errors.not_found("Low-income application not found")
    return app_rec
