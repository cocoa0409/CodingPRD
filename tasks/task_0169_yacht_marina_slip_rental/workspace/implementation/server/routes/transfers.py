"""Slip transfer request routes."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import iso_format, parse_iso
from ..common import bump, get_json_body, require_fields, stamp_new
from ..errors import ApiError
from ..marina_helpers import (
    assert_size_match,
    enforce_boater_owns,
    get_marina,
    get_reservation,
    get_slip,
    get_transfer_request,
    get_vessel,
    reservation_overlaps_slip,
)
from ..pricing import forward_looking_total
from ..response import respond
from ..serializers import transfer_view
from ..store import store


bp = Blueprint("transfers", __name__, url_prefix="/marinas")


@bp.post("/<marina_id>/transfer-requests")
@require_auth("Boater")
def create_transfer(marina_id: str):
    body = get_json_body()
    require_fields(body, "reservation_id", "desired_slip_id")
    with store.lock:
        get_marina(marina_id)
        res = get_reservation(marina_id, body["reservation_id"])
        enforce_boater_owns(res["boater_id"])
        get_slip(marina_id, body["desired_slip_id"])
        if res.get("status") not in ("APPROVED", "CHECKED_IN"):
            raise ApiError("ERR_INVALID_STATE", "Source reservation must be APPROVED or CHECKED_IN")
        tr = {
            "marina_id": marina_id,
            "reservation_id": res["id"],
            "desired_slip_id": body["desired_slip_id"],
            "status": "REQUESTED",
            "offer_expires_at": None,
        }
        stamp_new(tr)
        store.transfer_requests[tr["id"]] = tr
    return respond(transfer_view(tr), 201)


@bp.post("/<marina_id>/transfer-requests/<request_id>/offer")
@require_auth("DockMaster")
def offer_transfer(marina_id: str, request_id: str):
    with store.lock:
        marina = get_marina(marina_id)
        tr = get_transfer_request(marina_id, request_id)
        if tr.get("status") != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE", "Transfer request is not REQUESTED")
        slip = get_slip(marina_id, tr["desired_slip_id"])
        if slip.get("status") != "AVAILABLE":
            raise ApiError("ERR_INVALID_STATE", "Desired slip is not AVAILABLE")
        res = get_reservation(marina_id, tr["reservation_id"])
        vessel = get_vessel(marina_id, res["vessel_id"])

        # Size-match
        assert_size_match(slip, vessel)

        # Overlap on desired slip for remaining term [current_date, check_out_date)
        current = parse_iso(marina["current_date"])
        try:
            res_check_in = parse_iso(res["check_in_date"])
        except (KeyError, ValueError):
            raise ApiError("ERR_BAD_REQUEST", "Reservation has invalid check_in_date")
        try:
            check_out = parse_iso(res["check_out_date"])
        except (KeyError, ValueError):
            raise ApiError("ERR_BAD_REQUEST", "Reservation has invalid check_out_date")
        # Remaining window — clamp start to current_date but never before check_in_date
        remaining_start = current if current > res_check_in else res_check_in
        if reservation_overlaps_slip(slip["id"], remaining_start, check_out):
            raise ApiError("ERR_SLIP_OCCUPIED", "Desired slip occupied during remaining term")

        tr["status"] = "OFFERED"
        tr["offer_expires_at"] = iso_format(current + timedelta(hours=24))
        bump(tr)
        return respond(transfer_view(tr), 200)


@bp.post("/<marina_id>/transfer-requests/<request_id>/decline")
@require_auth("Boater")
def decline_transfer(marina_id: str, request_id: str):
    with store.lock:
        get_marina(marina_id)
        tr = get_transfer_request(marina_id, request_id)
        res = get_reservation(marina_id, tr["reservation_id"])
        enforce_boater_owns(res["boater_id"])
        if tr.get("status") != "OFFERED":
            raise ApiError("ERR_INVALID_STATE", "Transfer request is not OFFERED")
        tr["status"] = "DECLINED"
        bump(tr)
        return respond(transfer_view(tr), 200)


@bp.post("/<marina_id>/transfer-requests/<request_id>/requeue")
@require_auth("Boater")
def requeue_transfer(marina_id: str, request_id: str):
    with store.lock:
        get_marina(marina_id)
        tr = get_transfer_request(marina_id, request_id)
        res = get_reservation(marina_id, tr["reservation_id"])
        enforce_boater_owns(res["boater_id"])
        if tr.get("status") != "DECLINED":
            raise ApiError("ERR_INVALID_STATE", "Transfer request is not DECLINED")
        if res.get("status") not in ("APPROVED", "CHECKED_IN"):
            raise ApiError("ERR_INVALID_STATE", "Source reservation no longer active")
        tr["status"] = "REQUESTED"
        bump(tr)
        return respond(transfer_view(tr), 200)


@bp.post("/<marina_id>/transfer-requests/<request_id>/accept")
@require_auth("Boater")
def accept_transfer(marina_id: str, request_id: str):
    with store.lock:
        marina = get_marina(marina_id)
        tr = get_transfer_request(marina_id, request_id)
        res = get_reservation(marina_id, tr["reservation_id"])
        enforce_boater_owns(res["boater_id"])
        if tr.get("status") != "OFFERED":
            raise ApiError("ERR_INVALID_STATE", "Transfer request is not OFFERED")
        current = parse_iso(marina["current_date"])
        try:
            offer_exp = parse_iso(tr["offer_expires_at"]) if tr.get("offer_expires_at") else None
        except ValueError:
            offer_exp = None
        if offer_exp is None or current >= offer_exp:
            raise ApiError("ERR_INVALID_STATE", "Offer has expired")
        desired_slip = get_slip(marina_id, tr["desired_slip_id"])
        if desired_slip.get("status") != "AVAILABLE":
            raise ApiError("ERR_INVALID_STATE", "Desired slip is not AVAILABLE")

        vessel = get_vessel(marina_id, res["vessel_id"])
        check_in = parse_iso(res["check_in_date"])
        check_out = parse_iso(res["check_out_date"])

        # Update reservation's slip + recompute estimated total
        res["slip_id"] = desired_slip["id"]
        res["estimated_total_cents"] = forward_looking_total(
            base_daily_rate_cents=int(marina["base_daily_rate_cents"]),
            loa_feet=vessel["loa_feet"],
            flat_daily_charge_cents=int(desired_slip["flat_daily_charge_cents"]),
            liveaboard=bool(res.get("liveaboard")),
            check_in_date=check_in,
            check_out_date=check_out,
        )
        bump(res)

        tr["status"] = "ACCEPTED"
        bump(tr)
        return respond(transfer_view(tr), 200)
