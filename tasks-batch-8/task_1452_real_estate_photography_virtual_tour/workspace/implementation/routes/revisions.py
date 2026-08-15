"""RevisionRequest endpoints."""

from flask import Blueprint, request

from db import store
from errors import ApiError, invalid_request, not_found, forbidden
import errors
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from serializers import revision_json
from services.calculations import (
    paid_revision_fee_cents, FREE_REVISION_ROUNDS, REVISION_HARD_CAP,
)
from services.domain import touch, sweep_clock
from timeutil import new_id, iso_now_ms, now_dt

bp = Blueprint("revisions", __name__)


def _get_booking_or_404(booking_id):
    b = store.bookings.get(booking_id)
    if not b:
        raise not_found("ShootBooking not found")
    return b


def _get_revision_under_booking(booking_id, revision_id):
    b = _get_booking_or_404(booking_id)
    r = store.revisions.get(revision_id)
    if not r or r["booking_id"] != b["id"]:
        raise not_found("RevisionRequest not found")
    return b, r


# Global ops list
@bp.route("/revisions", methods=["GET"])
def global_list_revisions():
    require_roles("Coordinator", "OpsAdmin")
    sweep_clock()
    limit, offset = parse_pagination(request.args)
    items = sorted(store.revisions.values(), key=lambda r: r["created_at"])
    for f in ("booking_id", "bundle_id", "state"):
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if r.get(f) == v]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([revision_json(r) for r in page], limit, offset, total)


@bp.route("/revisions/<revisionId>", methods=["GET"])
def global_get_revision(revisionId):
    require_roles("Coordinator", "OpsAdmin")
    sweep_clock()
    r = store.revisions.get(revisionId)
    if not r:
        raise not_found("RevisionRequest not found")
    return success_object(revision_json(r))


# Nested
@bp.route("/shoot-bookings/<booking_id>/revisions", methods=["POST"])
def create_revision(booking_id):
    user_id, _ = require_roles("ClientAgent")
    b = _get_booking_or_404(booking_id)
    data = request.get_json(silent=True) or {}
    for f in ("bundle_id", "notes"):
        if f not in data:
            raise invalid_request(f"Missing required field: {f}")
    if b["state"] != "DELIVERED":
        raise ApiError(errors.ERR_BOOKING_NOT_DELIVERED, 409,
                       "revision requires booking DELIVERED")
    if b["client_agent_id"] != user_id:
        raise forbidden("Only the owning ClientAgent may open revisions")
    bundle = store.asset_bundles.get(data["bundle_id"])
    if not bundle or bundle["booking_id"] != b["id"]:
        raise not_found("AssetBundle not found")
    # Revision window (strictly before)
    if b["revision_window_closes_utc"] is not None and not (now_dt() < b["revision_window_closes_utc"]):
        raise ApiError(errors.ERR_REVISION_WINDOW_CLOSED, 422,
                       "Revision window closed")
    if b["revisions_used"] >= REVISION_HARD_CAP:
        raise ApiError(errors.ERR_REVISION_LIMIT_REACHED, 409,
                       "Revision limit 4 reached")
    market = store.markets.get(b["market_id"])
    is_free = b["revisions_used"] < FREE_REVISION_ROUNDS
    fee = 0 if is_free else paid_revision_fee_cents(market)
    r = {
        "id": new_id(),
        "booking_id": b["id"],
        "bundle_id": bundle["id"],
        "notes": data["notes"],
        "state": "OPEN",
        "is_free": is_free,
        "fee_cents": fee,
        "created_at": iso_now_ms(),
        "updated_at": iso_now_ms(),
        "version": 1,
    }
    store.revisions[r["id"]] = r
    b["revisions_used"] += 1
    b["state"] = "REVISION_REQUESTED"
    touch(b)
    return success_object(revision_json(r), http_status=201)


@bp.route("/shoot-bookings/<booking_id>/revisions", methods=["GET"])
def list_revisions(booking_id):
    require_roles("ClientAgent", "Photographer", "Coordinator", "OpsAdmin")
    sweep_clock()
    b = _get_booking_or_404(booking_id)
    limit, offset = parse_pagination(request.args)
    items = sorted(
        (r for r in store.revisions.values() if r["booking_id"] == b["id"]),
        key=lambda x: x["created_at"],
    )
    state = request.args.get("state")
    if state is not None:
        items = [r for r in items if r["state"] == state]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([revision_json(r) for r in page], limit, offset, total)


@bp.route("/shoot-bookings/<booking_id>/revisions/<revisionId>", methods=["GET"])
def get_revision(booking_id, revisionId):
    require_roles("ClientAgent", "Photographer", "Coordinator", "OpsAdmin")
    sweep_clock()
    _, r = _get_revision_under_booking(booking_id, revisionId)
    return success_object(revision_json(r))


@bp.route("/shoot-bookings/<booking_id>/revisions/<revisionId>/claim", methods=["POST"])
def claim_revision(booking_id, revisionId):
    user_id, _ = require_roles("Photographer")
    b, r = _get_revision_under_booking(booking_id, revisionId)
    if r["state"] != "OPEN":
        raise ApiError(errors.ERR_REVISION_NOT_OPEN, 409, "claim requires OPEN")
    if b.get("assigned_photographer_id") != user_id:
        raise forbidden("Only the assigned Photographer may claim")
    r["state"] = "IN_PROGRESS"
    touch(r)
    return success_object(revision_json(r))


@bp.route("/shoot-bookings/<booking_id>/revisions/<revisionId>/dismiss", methods=["POST"])
def dismiss_revision(booking_id, revisionId):
    require_roles("OpsAdmin")
    b, r = _get_revision_under_booking(booking_id, revisionId)
    if r["state"] != "OPEN":
        raise ApiError(errors.ERR_REVISION_NOT_OPEN, 409, "dismiss requires OPEN")
    r["state"] = "REJECTED_EXHAUSTED"
    touch(r)
    return success_object(revision_json(r))
