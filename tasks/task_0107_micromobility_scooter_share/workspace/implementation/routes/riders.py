"""Rider endpoints: registration, wallet, plan changes, lifecycle (PRD §3.2).

POST /api/riders                          — Anonymous
GET  /api/riders/{id}                      — PlatformAdmin, Rider
GET  /api/riders                           — PlatformAdmin
POST /api/riders/{id}/topup                — Rider, PlatformAdmin
POST /api/riders/{id}/change-plan          — Rider, PlatformAdmin (OCC on rider)
POST /api/riders/{id}/suspend              — PlatformAdmin
POST /api/riders/{id}/reinstate            — PlatformAdmin
GET  /api/riders/{id}/wallet-transactions  — PlatformAdmin, Rider
"""
from flask import Blueprint, request

import errors
from db import db, stamp_new, touch
from middleware import authenticate, require_role, require_rider_owner
from response import success
from services.wallet import create_txn
from util import (
    get_json_body, require_fields, require_int, require_string,
    public, parse_pagination, paginate,
)

bp = Blueprint("riders", __name__)


@bp.post("/api/riders")
def create_rider():
    # Self-registration is the Anonymous role's only capability (PRD §2.1, §3.2).
    role, user_id = authenticate()
    require_role(role, {"Anonymous"})

    body = get_json_body()
    require_fields(body, ["email", "full_name", "plan_id"])
    require_string(body["email"], "email")
    require_string(body["full_name"], "full_name")
    require_string(body["plan_id"], "plan_id")

    # Uniqueness of email across riders (PRD §3.2).
    for r in db.riders.values():
        if r["email"] == body["email"]:
            raise errors.invalid_request(f"email {body['email']} already exists")

    # plan_id is a body foreign key -> ERR_REFERENCE_NOT_FOUND when dangling.
    if body["plan_id"] not in db.plans:
        raise errors.reference_not_found("plan_id does not reference a plan")

    rider = {
        "email": body["email"],
        "full_name": body["full_name"],
        "plan_id": body["plan_id"],
        "wallet_balance_cents": 0,
        "outstanding_fine_cents": 0,
        "status": "ACTIVE",
    }
    stamp_new(rider)
    db.riders[rider["id"]] = rider
    return success(public(rider), status=201)


@bp.get("/api/riders/<rider_id>")
def get_rider(rider_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Rider"})
    rider = _require_rider(rider_id)
    require_rider_owner(role, user_id, rider["id"])
    return success(public(rider))


@bp.get("/api/riders")
def list_riders():
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})
    limit, offset = parse_pagination()

    rows = list(db.riders.values())
    plan_id = request.args.get("plan_id")
    if plan_id is not None:
        rows = [r for r in rows if r["plan_id"] == plan_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page, pagination = paginate(rows, limit, offset)
    return success(page, is_array=True, pagination=pagination)


@bp.post("/api/riders/<rider_id>/topup")
def topup(rider_id):
    role, user_id = authenticate()
    require_role(role, {"Rider", "PlatformAdmin"})
    rider = _require_rider(rider_id)
    require_rider_owner(role, user_id, rider["id"])

    body = get_json_body()
    require_fields(body, ["amount_cents"])
    require_int(body["amount_cents"], "amount_cents", minimum=0)

    txn = create_txn(rider["id"], "TOPUP", body["amount_cents"])
    rider["wallet_balance_cents"] += body["amount_cents"]
    touch(rider)
    # Endpoint returns the created WalletTransaction with 201.
    return success(public(txn), status=201)


@bp.post("/api/riders/<rider_id>/change-plan")
def change_plan(rider_id):
    role, user_id = authenticate()
    require_role(role, {"Rider", "PlatformAdmin"})
    rider = _require_rider(rider_id)
    require_rider_owner(role, user_id, rider["id"])

    body = get_json_body()
    # Existence/reference (priority 5) precedes state, business, and OCC (PRD §2.8).
    require_fields(body, ["plan_id", "expected_rider_version"])
    require_string(body["plan_id"], "plan_id")
    new_plan = db.plans.get(body["plan_id"])
    if new_plan is None:
        raise errors.reference_not_found("plan_id does not reference a plan")

    # OCC on the rider (PRD §2.7). Field shape checked before comparison.
    require_int(body["expected_rider_version"], "expected_rider_version")

    # Business rule (priority 12): LOW_INCOME requires an APPROVED application.
    if new_plan["code"] == "LOW_INCOME":
        has_approved = any(
            a["rider_id"] == rider["id"] and a["status"] == "APPROVED"
            for a in db.low_income_applications.values()
        )
        if not has_approved:
            raise errors.ApiError(
                errors.ERR_NO_APPROVED_APPLICATION, 422,
                "Switching to LOW_INCOME requires an APPROVED application",
            )

    if body["expected_rider_version"] != rider["version"]:
        raise errors.ApiError(
            errors.ERR_STALE_RIDER_VERSION, 412,
            "expected_rider_version does not match the rider's current version",
        )

    rider["plan_id"] = new_plan["id"]
    touch(rider)
    return success(public(rider))


@bp.post("/api/riders/<rider_id>/suspend")
def suspend(rider_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})
    rider = _require_rider(rider_id)
    if rider["status"] != "ACTIVE":
        raise errors.invalid_state("Rider is not ACTIVE")
    rider["status"] = "SUSPENDED"
    touch(rider)
    return success(public(rider))


@bp.post("/api/riders/<rider_id>/reinstate")
def reinstate(rider_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})
    rider = _require_rider(rider_id)
    if rider["status"] != "SUSPENDED":
        raise errors.invalid_state("Rider is not SUSPENDED")
    if rider["outstanding_fine_cents"] != 0:
        raise errors.ApiError(
            errors.ERR_OUTSTANDING_FINES, 422,
            "Rider has outstanding fines and cannot be reinstated",
        )
    rider["status"] = "ACTIVE"
    touch(rider)
    return success(public(rider))


@bp.get("/api/riders/<rider_id>/wallet-transactions")
def list_wallet_transactions(rider_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Rider"})
    rider = _require_rider(rider_id)
    require_rider_owner(role, user_id, rider["id"])
    limit, offset = parse_pagination()

    rows = [t for t in db.wallet_transactions.values() if t["rider_id"] == rider["id"]]
    page, pagination = paginate(rows, limit, offset)
    return success(page, is_array=True, pagination=pagination)


def _require_rider(rider_id):
    rider = db.riders.get(rider_id)
    if rider is None:
        raise errors.not_found("Rider not found")
    return rider
