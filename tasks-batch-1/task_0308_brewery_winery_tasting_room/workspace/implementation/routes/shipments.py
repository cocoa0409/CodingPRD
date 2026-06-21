"""Shipment routes (PRD §3.7, §3.8). Scheduling reservation + release gates."""
from datetime import timedelta

from flask import Blueprint, request

import constants as C
import calculations as calc
from db import db, common_fields, touch
from clock import now as clock_now
from errors import (
    err, ERR_INVALID_STATE, ERR_NOT_RESOURCE_OWNER, ERR_RELEASE_NOT_OPEN,
    ERR_RELEASE_WINDOW_CLOSED, ERR_PER_MEMBER_CAP_EXCEEDED, ERR_INSUFFICIENT_INVENTORY,
)
from middleware import authenticate, authorize
from response import success
from serialize import public
from domain import (
    recompute_release_available, recompute_winery_loyalty_liability, is_of_age,
)
from ledger_service import append_ledger
from validate import (
    get_json_body, require_str, require_positive_int, require_enum,
    get_or_404, resolve_winery_fk, resolve_fk,
)
from pagination import paginate, sorted_by_creation
from util import parse_datetime

bp = Blueprint("shipments", __name__)


def _product_for_release(release):
    return db.products.get(release["product_id"])


def _new_shipment(winery_id, membership_id, release_id, requested_bottles,
                  ship_to_state_code, subtotal, discount, total):
    s = common_fields()
    s.update({
        "membership_id": membership_id,
        "winery_id": winery_id,
        "release_id": release_id,
        "requested_bottles": requested_bottles,
        "subtotal_cents": subtotal,
        "discount_cents": discount,
        "total_cents": total,
        "loyalty_points_earned": 0,
        "ship_to_state_code": ship_to_state_code,
        "hold_reason": "NONE",
        "status": "SCHEDULED",
    })
    return s


@bp.route("/shipments", methods=["POST"])
def create_shipment():
    _, role = authenticate()
    authorize(role, ["ClubManager"])
    body = get_json_body()
    winery_id = require_str(body, "winery_id")
    membership_id = require_str(body, "membership_id")
    release_id = require_str(body, "release_id")
    requested_bottles = require_positive_int(body, "requested_bottles")
    with db.lock:
        winery = resolve_winery_fk(winery_id)
        membership = resolve_fk(db.memberships, membership_id, winery_id)
        release = resolve_fk(db.releases, release_id, winery_id)
        member = db.members.get(membership["member_id"])
        product = _product_for_release(release)

        # business_temporal/constraint gates, in PRD §2.9 priority order
        # release must be OPEN
        if release["status"] != "OPEN":
            raise err(ERR_RELEASE_NOT_OPEN, "Release is not OPEN")
        # per-member allocation cap (priority 11) before release window (priority 12)
        existing = 0
        for sh in db.shipments.values():
            if (sh["release_id"] == release_id
                    and sh["membership_id"] == membership_id
                    and sh["status"] in ("SCHEDULED", "HELD", "RELEASED", "DELIVERED")):
                existing += sh["requested_bottles"]
        if existing + requested_bottles > release["per_member_cap"]:
            raise err(ERR_PER_MEMBER_CAP_EXCEEDED, "Per-member allocation cap exceeded")
        # release window: now in [opens_at, closes_at)
        now = clock_now()
        opens_at = parse_datetime(release["opens_at"], "opens_at")
        closes_at = parse_datetime(release["closes_at"], "closes_at")
        if not (opens_at <= now < closes_at):
            raise err(ERR_RELEASE_WINDOW_CLOSED, "Release window is closed")
        # inventory sufficiency on the release
        if release["available_bottles"] < requested_bottles:
            raise err(ERR_INSUFFICIENT_INVENTORY, "Insufficient release inventory")

        # pricing
        subtotal, discount, total = calc.shipment_pricing(
            requested_bottles, product["list_price_cents"], membership["tier"]
        )
        ship_to_state = member["ship_to_state_code"]

        s = _new_shipment(winery_id, membership_id, release_id, requested_bottles,
                          ship_to_state, subtotal, discount, total)
        db.shipments[s["id"]] = s

        # reserve inventory on the release
        release["reserved_bottles"] = release["reserved_bottles"] + requested_bottles
        recompute_release_available(release)
        touch(release)

        return success(public(s), status=201)


@bp.route("/shipments", methods=["GET"])
def list_shipments():
    user_id, role = authenticate()
    authorize(role, ["ClubManager", "Member", "ComplianceOfficer"])
    with db.lock:
        items = list(db.shipments.values())
        membership_id = request.args.get("membership_id")
        release_id = request.args.get("release_id")
        winery_id = request.args.get("winery_id")
        status = request.args.get("status")
        ship_to_state = request.args.get("ship_to_state_code")
        if membership_id is not None:
            items = [s for s in items if s["membership_id"] == membership_id]
        if release_id is not None:
            items = [s for s in items if s["release_id"] == release_id]
        if winery_id is not None:
            items = [s for s in items if s["winery_id"] == winery_id]
        if status is not None:
            items = [s for s in items if s["status"] == status]
        if ship_to_state is not None:
            items = [s for s in items if s["ship_to_state_code"] == ship_to_state]
        # Member self-service: read only own shipments (by owning membership's member)
        if role == "Member":
            items = [s for s in items if _shipment_member_id(s) == user_id]
        items = sorted_by_creation(items)
        page, pg = paginate(items)
        return success([public(s) for s in page], pagination=pg)


def _shipment_member_id(shipment):
    ms = db.memberships.get(shipment["membership_id"])
    return ms["member_id"] if ms else None


@bp.route("/shipments/<shipment_id>", methods=["GET"])
def get_shipment(shipment_id):
    user_id, role = authenticate()
    authorize(role, ["ClubManager", "Member"])
    with db.lock:
        s = get_or_404(db.shipments, shipment_id)
        if role == "Member" and _shipment_member_id(s) != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, "Member may only read its own shipment")
        return success(public(s))


def _evaluate_gates(shipment):
    """Return the first failing gate's hold reason, or None if all gates pass.
    Priority order: WINERY_SUSPENDED, AGE, STATE_LIMIT, BILLING (PRD §3.7)."""
    winery = db.wineries.get(shipment["winery_id"])
    membership = db.memberships.get(shipment["membership_id"])
    member = db.members.get(membership["member_id"]) if membership else None
    release = db.releases.get(shipment["release_id"])
    product = db.products.get(release["product_id"]) if release else None

    if winery is None or winery["status"] != "ACTIVE":
        return "WINERY_SUSPENDED"
    if member is None or not is_of_age(member["date_of_birth"]):
        return "AGE"
    # state shipping limit
    this_cases = calc.shipment_cases(shipment["requested_bottles"], product["bottle_volume_ml"])
    prior_cases = _prior_cases(member, shipment["ship_to_state_code"])
    if calc.state_limit_exceeded(prior_cases, this_cases, shipment["ship_to_state_code"]):
        return "STATE_LIMIT"
    if membership["billing_status"] != "CURRENT":
        return "BILLING"
    return None


def _prior_cases(member, state_code):
    """Sum cases shipped by this member to this state, RELEASED/DELIVERED, in the
    trailing 365 days ending at the current clock (PRD §3.8)."""
    now = clock_now()
    window_start = now - timedelta(days=365)
    total = 0.0
    for sh in db.shipments.values():
        if sh["status"] not in ("RELEASED", "DELIVERED"):
            continue
        if sh["ship_to_state_code"] != state_code:
            continue
        ms = db.memberships.get(sh["membership_id"])
        if ms is None or ms["member_id"] != member["id"]:
            continue
        created = parse_datetime(sh["created_at"], "created_at")
        if not (window_start <= created <= now):
            continue
        prod = None
        rel = db.releases.get(sh["release_id"])
        if rel is not None:
            prod = db.products.get(rel["product_id"])
        if prod is None:
            continue
        total += calc.shipment_cases(sh["requested_bottles"], prod["bottle_volume_ml"])
    return total


def _commit_release(shipment):
    """Shared RELEASED side effects (PRD §3.7)."""
    release = db.releases.get(shipment["release_id"])
    product = db.products.get(release["product_id"])
    membership = db.memberships.get(shipment["membership_id"])
    winery = db.wineries.get(shipment["winery_id"])
    qty = shipment["requested_bottles"]

    # release reserved -> committed
    release["reserved_bottles"] = release["reserved_bottles"] - qty
    release["committed_bottles"] = release["committed_bottles"] + qty
    recompute_release_available(release)
    touch(release)

    # product inventory removed
    product["on_hand_bottles"] = product["on_hand_bottles"] - qty
    product["allocated_bottles"] = product["allocated_bottles"] - qty
    product["free_bottles"] = product["on_hand_bottles"] - product["allocated_bottles"]
    touch(product)

    # loyalty earned on net spend
    earned = calc.loyalty_earned(shipment["total_cents"], membership["tier"])
    shipment["loyalty_points_earned"] = earned
    membership["loyalty_points"] = membership["loyalty_points"] + earned
    membership["lifetime_bottles_shipped"] = membership["lifetime_bottles_shipped"] + qty
    touch(membership)
    recompute_winery_loyalty_liability(winery)
    touch(winery)

    # ledger entry
    append_ledger(winery["id"], "SHIPMENT_RELEASE", "SHIPMENT", shipment["id"],
                  0, 0, f"Shipment {shipment['id']} released ({qty} bottles)")


@bp.route("/shipments/<shipment_id>/transitions", methods=["POST"])
def transition_shipment(shipment_id):
    _, role = authenticate()
    authorize(role, ["ClubManager"])
    with db.lock:
        s = get_or_404(db.shipments, shipment_id)
        body = get_json_body()
        action = require_enum(body, "action", {"RELEASE", "HOLD", "DELIVER", "CANCEL"})

        if action == "RELEASE":
            return _do_release(s)
        elif action == "HOLD":
            return _do_hold(s)
        elif action == "DELIVER":
            if s["status"] != "RELEASED":
                raise err(ERR_INVALID_STATE, "Shipment is not RELEASED")
            s["status"] = "DELIVERED"
            touch(s)
            return success(public(s))
        else:  # CANCEL
            if s["status"] not in ("SCHEDULED", "HELD"):
                raise err(ERR_INVALID_STATE, "Shipment cannot be cancelled from its current state")
            release = db.releases.get(s["release_id"])
            if release is not None:
                release["reserved_bottles"] = release["reserved_bottles"] - s["requested_bottles"]
                recompute_release_available(release)
                touch(release)
            s["status"] = "CANCELLED"
            touch(s)
            return success(public(s))


def _do_release(s):
    if s["status"] not in ("SCHEDULED", "HELD"):
        raise err(ERR_INVALID_STATE, "Shipment is not SCHEDULED or HELD")
    # release must still be OPEN (PRD §3.7) -> ERR_RELEASE_NOT_OPEN otherwise
    release = db.releases.get(s["release_id"])
    if release is None or release["status"] != "OPEN":
        raise err(ERR_RELEASE_NOT_OPEN, "Drawn release is not OPEN")

    hold_reason = _evaluate_gates(s)
    if hold_reason is None:
        # all gates pass -> RELEASED
        s["hold_reason"] = "NONE"
        s["status"] = "RELEASED"
        touch(s)
        _commit_release(s)
        return success(public(s))
    else:
        # divert to HELD
        s["hold_reason"] = hold_reason
        s["status"] = "HELD"
        touch(s)
        if hold_reason == "AGE":
            append_ledger(s["winery_id"], "AGE_REJECTION", "SHIPMENT", s["id"],
                          0, 0, f"Shipment {s['id']} held: age rejection")
        elif hold_reason == "STATE_LIMIT":
            append_ledger(s["winery_id"], "STATE_LIMIT_REJECTION", "SHIPMENT", s["id"],
                          0, 0, f"Shipment {s['id']} held: state shipping limit")
        return success(public(s))


def _do_hold(s):
    # explicit HOLD action: only from SCHEDULED
    if s["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Shipment is not SCHEDULED")
    hold_reason = _evaluate_gates(s)
    if hold_reason is None:
        # No gate failing — there is nothing to hold on; treat as invalid state.
        raise err(ERR_INVALID_STATE, "No compliance gate is failing")
    s["hold_reason"] = hold_reason
    s["status"] = "HELD"
    touch(s)
    if hold_reason == "AGE":
        append_ledger(s["winery_id"], "AGE_REJECTION", "SHIPMENT", s["id"],
                      0, 0, f"Shipment {s['id']} held: age rejection")
    elif hold_reason == "STATE_LIMIT":
        append_ledger(s["winery_id"], "STATE_LIMIT_REJECTION", "SHIPMENT", s["id"],
                      0, 0, f"Shipment {s['id']} held: state shipping limit")
    return success(public(s))
