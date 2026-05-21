"""OverageSettlement routes (§3.6)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g

from ..auth import require_auth
from ..calculations import compute_overage
from ..clock import now, parse_iso
from ..common import as_int, bump, get_json_body, require_fields, stamp_new
from ..constants import DISPUTE_WINDOW_DAYS
from ..errors import ApiError
from ..response import respond
from ..serializers import settlement_view
from ..store import store


bp = Blueprint("overage_settlements", __name__, url_prefix="/overage-settlements")


@bp.post("")
@require_auth("FleetManager")
def create_settlement():
    body = get_json_body()
    require_fields(body, "lease_agreement_id", "period_year", "period_month")
    lease_id = body["lease_agreement_id"]
    period_year = as_int(body["period_year"], "period_year", min_value=2000, max_value=2099)
    period_month = as_int(body["period_month"], "period_month", min_value=1, max_value=12)

    with store.lock:
        la = store.lease_agreements.get(lease_id)
        if la is None:
            raise ApiError("ERR_NOT_FOUND", "Lease not found")
        # Duplicate-period check
        for s in store.overage_settlements.values():
            if (
                s.get("lease_agreement_id") == lease_id
                and int(s.get("period_year") or 0) == period_year
                and int(s.get("period_month") or 0) == period_month
            ):
                raise ApiError(
                    "ERR_DUPLICATE_SETTLEMENT_PERIOD",
                    "A settlement already exists for this lease/year/month",
                )

        v = store.vehicles.get(la["vehicle_id"])
        if v is None:
            raise ApiError("ERR_NOT_FOUND", "Vehicle not found")

        prov_miles, prov_balance = compute_overage(la, v, period_year, period_month, "provisional", now())
        settlement = {
            "lease_agreement_id": lease_id,
            "period_year": period_year,
            "period_month": period_month,
            "provisional_overage_miles": prov_miles,
            "final_overage_miles": 0,
            "provisional_balance_cents": prov_balance,
            "balance_cents": 0,
            "settlement_status": "DRAFT",
        }
        stamp_new(settlement)
        store.overage_settlements[settlement["id"]] = settlement
    return respond(settlement_view(settlement), 201)


@bp.get("/<settlement_id>")
@require_auth("FleetManager", "TaxAdmin", "Lessee")
def get_settlement(settlement_id: str):
    with store.lock:
        s = store.overage_settlements.get(settlement_id)
        if s is None:
            raise ApiError("ERR_NOT_FOUND", "OverageSettlement not found")
        # Ownership check for Lessee
        if g.user_role == "Lessee":
            la = store.lease_agreements.get(s["lease_agreement_id"])
            if la is None or la.get("lessee_id") != g.user_id:
                raise ApiError("ERR_FORBIDDEN", "Lessee may only read their own settlements")

        # Read-through provisional recompute (PRD §3.6: provisional variant used while in DRAFT)
        if s.get("settlement_status") == "DRAFT":
            la = store.lease_agreements.get(s["lease_agreement_id"])
            v = store.vehicles.get(la["vehicle_id"]) if la is not None else None
            if la is not None and v is not None:
                prov_miles, prov_balance = compute_overage(
                    la, v, int(s["period_year"]), int(s["period_month"]), "provisional", now()
                )
                s["provisional_overage_miles"] = prov_miles
                s["provisional_balance_cents"] = prov_balance
        return respond(settlement_view(s), 200)


@bp.post("/<settlement_id>/finalize")
@require_auth("FleetManager")
def finalize_settlement(settlement_id: str):
    with store.lock:
        s = store.overage_settlements.get(settlement_id)
        if s is None:
            raise ApiError("ERR_NOT_FOUND", "OverageSettlement not found")
        if s.get("settlement_status") != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Settlement is not DRAFT")
        la = store.lease_agreements.get(s["lease_agreement_id"])
        if la is None:
            raise ApiError("ERR_NOT_FOUND", "Lease not found")
        if la.get("lease_state") not in ("ACTIVE", "IN_RETURN"):
            raise ApiError("ERR_INVALID_STATE", "Lease must be ACTIVE or IN_RETURN")
        v = store.vehicles.get(la["vehicle_id"])
        if v is None:
            raise ApiError("ERR_NOT_FOUND", "Vehicle not found")

        final_miles, final_balance = compute_overage(
            la, v, int(s["period_year"]), int(s["period_month"]), "final", now()
        )
        s["final_overage_miles"] = final_miles
        s["balance_cents"] = final_balance
        s["settlement_status"] = "FINAL"
        bump(s)

        la["cumulative_overage_miles"] = int(la.get("cumulative_overage_miles", 0)) + final_miles
        bump(la)
    return respond(settlement_view(s), 200)


@bp.post("/<settlement_id>/mark-paid")
@require_auth("FleetManager")
def mark_paid(settlement_id: str):
    with store.lock:
        s = store.overage_settlements.get(settlement_id)
        if s is None:
            raise ApiError("ERR_NOT_FOUND", "OverageSettlement not found")
        if s.get("settlement_status") != "FINAL":
            raise ApiError("ERR_INVALID_STATE", "Settlement is not FINAL")

        s["settlement_status"] = "PAID"
        bump(s)
        la = store.lease_agreements.get(s["lease_agreement_id"])
        if la is not None:
            lessee = store.lessees.get(la["lessee_id"])
            if lessee is not None:
                lessee["outstanding_balance_cents"] = (
                    int(lessee.get("outstanding_balance_cents", 0)) - int(s.get("balance_cents", 0))
                )
                bump(lessee)
    return respond(settlement_view(s), 200)


@bp.post("/<settlement_id>/dispute")
@require_auth("Lessee")
def dispute(settlement_id: str):
    with store.lock:
        s = store.overage_settlements.get(settlement_id)
        if s is None:
            raise ApiError("ERR_NOT_FOUND", "OverageSettlement not found")
        la = store.lease_agreements.get(s["lease_agreement_id"])
        if la is None:
            raise ApiError("ERR_NOT_FOUND", "Lease not found")
        # Priority 4 — ownership: X-User-ID must equal lessee_id
        if la.get("lessee_id") != g.user_id:
            raise ApiError("ERR_FORBIDDEN", "Lessee does not own this settlement")
        if s.get("settlement_status") != "FINAL":
            raise ApiError("ERR_INVALID_STATE", "Settlement is not FINAL")
        if la.get("lease_state") not in ("ACTIVE", "IN_RETURN"):
            raise ApiError("ERR_INVALID_STATE", "Lease must be ACTIVE or IN_RETURN")

        created_at = parse_iso(s["created_at"])
        window_end = created_at + timedelta(days=DISPUTE_WINDOW_DAYS)
        if now() > window_end:
            raise ApiError("ERR_DISPUTE_WINDOW_CLOSED", "Dispute window has closed")

        s["settlement_status"] = "DISPUTED"
        bump(s)
    return respond(settlement_view(s), 200)
