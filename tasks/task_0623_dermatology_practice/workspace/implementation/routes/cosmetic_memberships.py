"""CosmeticMembership wallet lifecycle (PRD 3.6)."""
from flask import Blueprint, request

import db
import errors
import helpers
import response
import services
from middleware import require

bp = Blueprint("cosmetic_memberships", __name__)

TIERS = {"SILVER", "GOLD"}


@bp.post("/cosmetic-memberships")
@require("BillingSpecialist", "FrontDesk")
def create_membership():
    data = helpers.body()
    patient_id = helpers.require_str(data, "patient_id")
    tier = helpers.require_enum(data, "tier", TIERS)
    purchased = helpers.require_int(data, "purchased_unit_cents")
    if purchased < 0:
        raise errors.invalid_request("purchased_unit_cents must be >= 0")
    helpers.get_or_404(db.patients, patient_id, "patient")
    row = {
        "patient_id": patient_id,
        "tier": tier,
        "purchased_unit_cents": purchased,
        "unit_balance_cents": 0,
        "status": "PENDING",
    }
    db.stamp_new(row)
    db.cosmetic_memberships[row["id"]] = row
    return response.created(row)


@bp.get("/cosmetic-memberships/<mid>")
@require("BillingSpecialist", "FrontDesk", "PracticeAdmin")
def get_membership(mid):
    row = helpers.get_or_404(db.cosmetic_memberships, mid, "membership")
    return response.ok(row)


@bp.get("/cosmetic-memberships")
@require("BillingSpecialist", "FrontDesk", "PracticeAdmin")
def list_memberships():
    rows = list(db.cosmetic_memberships.values())
    pid = request.args.get("patient_id")
    if pid is not None:
        rows = [m for m in rows if m["patient_id"] == pid]
    page, limit, offset, total = helpers.paginate(rows)
    return response.listing(page, limit, offset, total)


@bp.post("/cosmetic-memberships/<mid>/activate")
@require("BillingSpecialist")
def activate(mid):
    m = helpers.get_or_404(db.cosmetic_memberships, mid, "membership")
    if m["status"] != "PENDING":
        raise errors.bad_state("ERR_MEMBERSHIP_BAD_STATE")
    m["status"] = "ACTIVE"
    m["unit_balance_cents"] = services.membership_wallet_grant(m)
    db.touch(m)
    return response.ok(m)


@bp.post("/cosmetic-memberships/<mid>/cancel")
@require("BillingSpecialist")
def cancel(mid):
    m = helpers.get_or_404(db.cosmetic_memberships, mid, "membership")
    if m["status"] not in ("PENDING", "ACTIVE"):
        raise errors.bad_state("ERR_MEMBERSHIP_BAD_STATE")
    was_active = m["status"] == "ACTIVE"
    m["status"] = "CANCELLED"
    if was_active:
        m["unit_balance_cents"] = 0  # forfeit remaining wallet
    db.touch(m)
    return response.ok(m)
