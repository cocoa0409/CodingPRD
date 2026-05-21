"""Dispute routes."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import parse_iso
from ..common import bump, check_occ, get_json_body, require_fields, stamp_new
from ..errors import ApiError
from ..fare_logic import increment_period, refund_split
from ..response import respond
from ..serializers import dispute_view
from ..store import store


bp = Blueprint("disputes", __name__, url_prefix="/transit/disputes")


@bp.post("")
@require_auth("Rider")
def create_dispute():
    body = get_json_body()
    require_fields(body, "trip_id")
    trip_id = body["trip_id"]

    with store.lock:
        trip = store.trips.get(trip_id)
        if trip is None:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Trip not found")
        card = store.cards.get(trip["card_id"])
        if card is None or card["rider_id"] != g.user_id:
            raise ApiError("ERR_FORBIDDEN", "Trip does not belong to this rider")
        if trip.get("fare_status") != "PROVISIONAL":
            raise ApiError("ERR_INVALID_STATE", "Trip fare_status is not PROVISIONAL")

        dispute = {
            "trip_id": trip_id,
            "rider_id": g.user_id,
            "status": "OPEN",
            "refund_amount_cents": None,
        }
        stamp_new(dispute)
        store.disputes[dispute["id"]] = dispute
        trip["fare_status"] = "DISPUTED"
        bump(trip)
    return respond(dispute_view(dispute), 201)


@bp.post("/<dispute_id>/claim")
@require_auth("AgencyOfficer")
def claim(dispute_id: str):
    body = get_json_body()
    with store.lock:
        d = store.disputes.get(dispute_id)
        if d is None:
            raise ApiError("ERR_NOT_FOUND", "Dispute not found")
        if d["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Dispute is not OPEN")
        check_occ(d, body.get("version"))
        d["status"] = "INVESTIGATING"
        bump(d)
    return respond(dispute_view(d), 200)


@bp.post("/<dispute_id>/request-evidence")
@require_auth("AgencyOfficer")
def request_evidence(dispute_id: str):
    body = get_json_body()
    with store.lock:
        d = store.disputes.get(dispute_id)
        if d is None:
            raise ApiError("ERR_NOT_FOUND", "Dispute not found")
        if d["status"] != "INVESTIGATING":
            raise ApiError("ERR_INVALID_STATE", "Dispute is not INVESTIGATING")
        check_occ(d, body.get("version"))
        d["status"] = "OPEN"
        bump(d)
    return respond(dispute_view(d), 200)


@bp.post("/<dispute_id>/resolve")
@require_auth("AgencyOfficer")
def resolve(dispute_id: str):
    body = get_json_body()
    require_fields(body, "decision")
    decision = body["decision"]
    if decision not in ("REFUND", "REJECT"):
        raise ApiError("ERR_VALIDATION", "decision must be REFUND or REJECT")
    with store.lock:
        d = store.disputes.get(dispute_id)
        if d is None:
            raise ApiError("ERR_NOT_FOUND", "Dispute not found")
        if d["status"] != "INVESTIGATING":
            raise ApiError("ERR_INVALID_STATE", "Dispute is not INVESTIGATING")
        check_occ(d, body.get("version"))

        trip = store.trips.get(d["trip_id"])
        if trip is None:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Trip not found")
        provisional = int(trip.get("provisional_fare_cents") or 0)
        paid_from_fsa = int(trip.get("paid_from_fsa_cents") or 0)

        if decision == "REFUND":
            d["status"] = "RESOLVED_REFUNDED"
            d["refund_amount_cents"] = provisional
            # Trip: DISPUTED -> SETTLED with 0
            trip["fare_status"] = "SETTLED"
            trip["settled_fare_cents"] = 0
            bump(trip)
            # Refund split: FSA share (rounded) + wallet (absorbs drift)
            refund_to_fsa, refund_to_wallet = refund_split(provisional, 0, paid_from_fsa)
            card = store.cards.get(trip["card_id"])
            account = None
            rider = store.riders.get(card["rider_id"]) if card else None
            if rider and rider.get("employer_id"):
                for acc in store.fsa_accounts.values():
                    if acc.get("rider_id") == rider["id"]:
                        account = acc
                        break
            if account is not None and refund_to_fsa > 0:
                account["balance_cents"] = int(account["balance_cents"]) + refund_to_fsa
                bump(account)
            elif refund_to_fsa > 0:
                # No account to receive — push the share to wallet
                refund_to_wallet += refund_to_fsa
            if card is not None and refund_to_wallet > 0:
                card["wallet_balance_cents"] = int(card["wallet_balance_cents"]) + refund_to_wallet
                bump(card)
            # Decrement both daily and weekly cap-period accumulators by provisional
            for period in list(store.cap_periods.values()):
                if period["card_id"] != trip["card_id"]:
                    continue
                ws = parse_iso(period["window_start"])
                we = parse_iso(period["window_end"])
                tap_at = parse_iso(trip["tap_in_at"])
                if ws <= tap_at < we:
                    increment_period(period, -provisional)
        else:
            d["status"] = "RESOLVED_REJECTED"
            d["refund_amount_cents"] = 0
            trip["fare_status"] = "SETTLED"
            trip["settled_fare_cents"] = provisional
            bump(trip)
        bump(d)
    return respond(dispute_view(d), 200)
