"""Charge endpoints + fork-join state machine (PRD §3.5, §3.7)."""
from flask import Blueprint, request

import errors
import response
from db import db, iso_millis
from middleware import require_auth, require_role
from services import serialize
from services.common import (touch, get_body, require_enum, require_int,
                             parse_pagination, paginate)
from services.lookups import (get_pledge, get_charge, get_creator, get_patron,
                              require_creator_owner)
from services.ledger import (create_charge, settle_succeeded, settle_failed,
                            refund_charge)

bp = Blueprint("charges", __name__)

CHARGE_KINDS = {"INITIAL_PRORATION", "CYCLE_RENEWAL", "UPGRADE_PRORATION",
                "PER_CREATION", "WIN_BACK"}
OUTCOMES = {"SUCCEEDED", "FAILED"}


@bp.post("/charges")
def create_charge_endpoint():
    ctx = require_auth()
    require_role(ctx, {"PlatformAdmin"})
    body = get_body()

    pledge_id = body.get("pledge_id")
    if pledge_id is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: pledge_id")
    pledge = get_pledge(pledge_id)
    charge_kind = require_enum(body, "charge_kind", CHARGE_KINDS)
    gross_amount_cents = require_int(body, "gross_amount_cents", minimum=0)

    creator = get_creator(pledge["creator_id"])
    patron = get_patron(pledge["patron_id"])
    anchor = _parse_iso(pledge["cycle_anchor_date"]) or db.now()
    rec = create_charge(pledge, creator, patron, charge_kind, gross_amount_cents, anchor)
    return response.success(serialize.charge(rec), status=201)


def _parse_iso(s):
    from datetime import datetime, timezone
    if s is None:
        return None
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@bp.get("/charges")
def list_charges():
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron", "PlatformAdmin"})
    limit, offset = parse_pagination()
    items = list(db.charges.values())
    for key in ("pledge_id", "creator_id", "status", "cycle_anchor_date", "swept_into_payout_id"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if str(c.get(key)) == val]
    page, total = paginate(items, limit, offset)
    return response.list_success([serialize.charge(r) for r in page], limit, offset, total)


@bp.get("/charges/<charge_id>")
def get_one_charge(charge_id):
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron", "PlatformAdmin"})
    rec = get_charge(charge_id)
    return response.success(serialize.charge(rec))


@bp.post("/charges/<charge_id>/settle")
def settle_charge(charge_id):
    ctx = require_auth()
    require_role(ctx, {"PlatformAdmin"})
    charge = get_charge(charge_id)
    body = get_body()
    outcome = require_enum(body, "outcome", OUTCOMES)

    # State: only a PENDING charge can be settled (PRD §3.5).
    if charge["status"] != "PENDING":
        errors.fail(errors.ERR_CHARGE_NOT_PENDING, "Charge is not PENDING")

    pledge = db.pledges.get(charge["pledge_id"])
    creator = db.creators.get(charge["creator_id"])
    patron = db.patrons.get(pledge["patron_id"]) if pledge else None

    if outcome == "SUCCEEDED":
        settle_succeeded(charge, pledge, creator, patron)
    else:
        settle_failed(charge, pledge, creator, patron)

    return response.success(serialize.charge(charge))


@bp.post("/charges/<charge_id>/refund")
def refund_charge_endpoint(charge_id):
    ctx = require_auth()
    require_role(ctx, {"Creator"})
    charge = get_charge(charge_id)
    require_creator_owner(ctx, charge["creator_id"])

    # State: only a SUCCEEDED charge can be refunded (PRD §3.5).
    if charge["status"] != "SUCCEEDED":
        errors.fail(errors.ERR_CHARGE_NOT_REFUNDABLE, "Charge is not SUCCEEDED")
    # A swept charge cannot be refunded (PRD §3.5).
    if charge.get("swept_into_payout_id") is not None:
        errors.fail(errors.ERR_CHARGE_ALREADY_SWEPT, "Charge already swept into a payout")

    pledge = db.pledges.get(charge["pledge_id"])
    creator = db.creators.get(charge["creator_id"])
    patron = db.patrons.get(pledge["patron_id"]) if pledge else None

    refund_charge(charge, pledge, creator, patron)
    return response.success(serialize.charge(charge))
