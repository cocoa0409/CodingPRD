"""LeaseAgreement routes: draft / read / activate / begin-return / finalize-return (§3.2, §3.8)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g

from ..auth import require_auth
from ..calculations import compute_overage
from ..clock import iso_format, now, parse_iso
from ..common import (
    as_bool,
    as_int,
    bump,
    get_json_body,
    require_fields,
    stamp_new,
)
from ..constants import SUSPEND_THRESHOLD_CENTS
from ..errors import ApiError
from ..response import respond
from ..serializers import lease_view
from ..store import store


bp = Blueprint("lease_agreements", __name__, url_prefix="/lease-agreements")


# Helper: lease month diff (capped at 60 months)
def _within_60_months(start_dt, end_dt) -> bool:
    delta = end_dt - start_dt
    # 60 months ≈ 60 * 30.5 days ≈ 1830 days. Use calendar-month approximation more carefully:
    # months count = (end.year-start.year)*12 + (end.month-start.month), with day adjustment.
    years = end_dt.year - start_dt.year
    months = end_dt.month - start_dt.month
    total = years * 12 + months
    if end_dt.day < start_dt.day:
        total -= 1
    return total <= 60 and total >= 0


@bp.post("")
@require_auth("FleetManager")
def create_lease():
    body = get_json_body()
    require_fields(
        body,
        "lessee_id",
        "vehicle_id",
        "term_start_date",
        "term_end_date",
        "monthly_mileage_allowance",
        "overage_rate_cents_per_mile",
    )
    lessee_id = body["lessee_id"]
    vehicle_id = body["vehicle_id"]
    try:
        ts = parse_iso(body["term_start_date"])
        te = parse_iso(body["term_end_date"])
    except ValueError as exc:
        raise ApiError("ERR_VALIDATION", str(exc))
    if not (te > ts):
        raise ApiError("ERR_VALIDATION", "term_end_date must be after term_start_date")
    if not _within_60_months(ts, te):
        raise ApiError("ERR_VALIDATION", "term span must not exceed 60 months")

    allowance = as_int(body["monthly_mileage_allowance"], "monthly_mileage_allowance", min_value=1000, max_value=15000)
    rate = as_int(body["overage_rate_cents_per_mile"], "overage_rate_cents_per_mile", min_value=5, max_value=100)
    tiered = body.get("tiered_overage_enabled", False) or False
    if isinstance(tiered, bool):
        pass
    else:
        raise ApiError("ERR_VALIDATION", "tiered_overage_enabled must be boolean")

    with store.lock:
        if lessee_id not in store.lessees:
            raise ApiError("ERR_NOT_FOUND", "Lessee not found")
        if vehicle_id not in store.vehicles:
            raise ApiError("ERR_NOT_FOUND", "Vehicle not found")

        lease = {
            "lessee_id": lessee_id,
            "vehicle_id": vehicle_id,
            "term_start_date": iso_format(ts),
            "term_end_date": iso_format(te),
            "monthly_mileage_allowance": allowance,
            "overage_rate_cents_per_mile": rate,
            "tiered_overage_enabled": tiered,
            "lease_state": "DRAFT",
            "cumulative_overage_miles": 0,
            "collision_open_count": 0,
        }
        stamp_new(lease)
        store.lease_agreements[lease["id"]] = lease
    return respond(lease_view(lease), 201)


@bp.get("/<lease_id>")
@require_auth("FleetManager", "TaxAdmin", "ClaimAdjuster", "VendorOps", "Lessee")
def get_lease(lease_id: str):
    with store.lock:
        la = store.lease_agreements.get(lease_id)
        if la is None:
            raise ApiError("ERR_NOT_FOUND", "Lease not found")
        if g.user_role == "Lessee" and la.get("lessee_id") != g.user_id:
            raise ApiError("ERR_FORBIDDEN", "Lessee may only read their own leases")
        return respond(lease_view(la), 200)


@bp.post("/<lease_id>/activate")
@require_auth("FleetManager")
def activate_lease(lease_id: str):
    with store.lock:
        la = store.lease_agreements.get(lease_id)
        if la is None:
            raise ApiError("ERR_NOT_FOUND", "Lease not found")
        if la["lease_state"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Lease is not DRAFT")
        v = store.vehicles.get(la["vehicle_id"])
        if v is None:
            raise ApiError("ERR_NOT_FOUND", "Vehicle not found")
        if v["vehicle_status"] != "AVAILABLE" or v.get("current_lease_id") is not None:
            raise ApiError("ERR_VEHICLE_ALREADY_ALLOCATED", "Vehicle is not AVAILABLE")
        lessee = store.lessees.get(la["lessee_id"])
        if lessee is None:
            raise ApiError("ERR_NOT_FOUND", "Lessee not found")
        if lessee["account_status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Lessee is not ACTIVE")
        if int(lessee["outstanding_balance_cents"]) >= SUSPEND_THRESHOLD_CENTS:
            raise ApiError("ERR_INVALID_STATE", "Lessee balance at/above suspend threshold")

        # Commit transitions
        la["lease_state"] = "ACTIVE"
        bump(la)
        v["vehicle_status"] = "ALLOCATED"
        v["current_lease_id"] = la["id"]
        v["odometer_current_miles"] = int(v.get("odometer_baseline_miles", 0))
        bump(v)
    return respond(lease_view(la), 200)


@bp.post("/<lease_id>/begin-return")
@require_auth("FleetManager")
def begin_return(lease_id: str):
    with store.lock:
        la = store.lease_agreements.get(lease_id)
        if la is None:
            raise ApiError("ERR_NOT_FOUND", "Lease not found")
        if la["lease_state"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Lease is not ACTIVE")
        if int(la.get("collision_open_count", 0)) > 0:
            raise ApiError("ERR_OPEN_COLLISION_BLOCKS_RETURN", "Open collision claims block return")

        # Commit transition
        la["lease_state"] = "IN_RETURN"
        bump(la)
        v = store.vehicles.get(la["vehicle_id"])
        if v is not None:
            v["vehicle_status"] = "IN_SHOP"
            bump(v)

        # Synthesise a final-month DRAFT OverageSettlement for the current month
        now_dt = now()
        year = now_dt.year
        month = now_dt.month
        # Skip if a settlement for the same (lease, year, month) already exists
        already = any(
            s.get("lease_agreement_id") == la["id"]
            and int(s.get("period_year") or 0) == year
            and int(s.get("period_month") or 0) == month
            for s in store.overage_settlements.values()
        )
        if not already and v is not None:
            prov_miles, prov_balance = compute_overage(la, v, year, month, "provisional", now_dt)
            settlement = {
                "lease_agreement_id": la["id"],
                "period_year": year,
                "period_month": month,
                "provisional_overage_miles": prov_miles,
                "final_overage_miles": 0,
                "provisional_balance_cents": prov_balance,
                "balance_cents": 0,
                "settlement_status": "DRAFT",
            }
            stamp_new(settlement)
            store.overage_settlements[settlement["id"]] = settlement
    return respond(lease_view(la), 200)


@bp.post("/<lease_id>/finalize-return")
@require_auth("FleetManager")
def finalize_return(lease_id: str):
    with store.lock:
        la = store.lease_agreements.get(lease_id)
        if la is None:
            raise ApiError("ERR_NOT_FOUND", "Lease not found")
        if la["lease_state"] != "IN_RETURN":
            raise ApiError("ERR_INVALID_STATE", "Lease is not IN_RETURN")

        v = store.vehicles.get(la["vehicle_id"])
        # No open maintenance tickets on the vehicle
        if v is not None:
            for t in store.maintenance_tickets.values():
                if t.get("vehicle_id") != v["id"]:
                    continue
                if t.get("ticket_status") not in ("CLOSED", "CANCELLED"):
                    raise ApiError(
                        "ERR_VEHICLE_NOT_RETURNABLE",
                        "Open or in-shop maintenance tickets block return",
                    )

        # Every settlement must be PAID, DISPUTED, or FINAL with balance_cents == 0
        for s in store.overage_settlements.values():
            if s.get("lease_agreement_id") != la["id"]:
                continue
            status = s.get("settlement_status")
            if status in ("PAID", "DISPUTED"):
                continue
            if status == "FINAL" and int(s.get("balance_cents") or 0) == 0:
                continue
            raise ApiError("ERR_VEHICLE_NOT_RETURNABLE", "Unsettled overage rows remain")

        # Commit transition
        la["lease_state"] = "CLOSED"
        bump(la)
        if v is not None:
            v["vehicle_status"] = "AVAILABLE"
            v["current_lease_id"] = None
            bump(v)
        for card in store.fuel_cards.values():
            if card.get("lease_agreement_id") != la["id"]:
                continue
            if card.get("card_status") == "CLOSED":
                continue
            card["card_status"] = "CLOSED"
            bump(card)
    return respond(lease_view(la), 200)
