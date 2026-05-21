"""IFTAQuarter routes (§3.9)."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..calculations import compute_ifta, quarter_end_date, quarter_window
from ..clock import now, parse_iso
from ..common import as_int, bump, get_json_body, require_fields, stamp_new
from ..errors import ApiError
from ..response import respond
from ..serializers import ifta_view
from ..store import store


bp = Blueprint("ifta_quarters", __name__)


@bp.post("/lessees/<lessee_id>/ifta-quarters")
@require_auth("TaxAdmin")
def open_quarter(lessee_id: str):
    body = get_json_body()
    require_fields(body, "year", "quarter")
    year = as_int(body["year"], "year", min_value=2000, max_value=2099)
    quarter = as_int(body["quarter"], "quarter", min_value=1, max_value=4)

    with store.lock:
        if lessee_id not in store.lessees:
            raise ApiError("ERR_NOT_FOUND", "Lessee not found")
        q = {
            "lessee_id": lessee_id,
            "year": year,
            "quarter": quarter,
            "filing_status": "OPEN",
            "total_taxable_gallons": 0,
            "total_tax_cents": 0,
        }
        stamp_new(q)
        store.ifta_quarters[q["id"]] = q
    return respond(ifta_view(q), 201)


@bp.get("/ifta-quarters/<quarter_id>")
@require_auth("FleetManager", "TaxAdmin")
def get_quarter(quarter_id: str):
    with store.lock:
        q = store.ifta_quarters.get(quarter_id)
        if q is None:
            raise ApiError("ERR_NOT_FOUND", "IFTAQuarter not found")
        return respond(ifta_view(q), 200)


@bp.post("/ifta-quarters/<quarter_id>/prepare")
@require_auth("TaxAdmin")
def prepare_quarter(quarter_id: str):
    with store.lock:
        q = store.ifta_quarters.get(quarter_id)
        if q is None:
            raise ApiError("ERR_NOT_FOUND", "IFTAQuarter not found")
        if q.get("filing_status") != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Quarter is not OPEN")
        # Temporal gate: now() must be >= quarter_end_date
        if now() < quarter_end_date(int(q["year"]), int(q["quarter"])):
            raise ApiError("ERR_QUARTER_NOT_READY", "Quarter has not ended yet")

        lessee = store.lessees.get(q["lessee_id"])
        if lessee is None:
            raise ApiError("ERR_NOT_FOUND", "Lessee not found")
        total_gallons, total_tax = compute_ifta(lessee, int(q["year"]), int(q["quarter"]))
        q["total_taxable_gallons"] = total_gallons
        q["total_tax_cents"] = total_tax
        q["filing_status"] = "READY"
        bump(q)
    return respond(ifta_view(q), 200)


@bp.post("/ifta-quarters/<quarter_id>/file")
@require_auth("TaxAdmin")
def file_quarter(quarter_id: str):
    with store.lock:
        q = store.ifta_quarters.get(quarter_id)
        if q is None:
            raise ApiError("ERR_NOT_FOUND", "IFTAQuarter not found")
        if q.get("filing_status") != "READY":
            raise ApiError("ERR_INVALID_STATE", "Quarter is not READY")

        w_start, w_end = quarter_window(int(q["year"]), int(q["quarter"]))
        lessee_id = q["lessee_id"]
        # Identify the lessee's leases/cards
        lease_ids = {la["id"] for la in store.lease_agreements.values() if la.get("lessee_id") == lessee_id}
        card_ids = {c["id"] for c in store.fuel_cards.values() if c.get("lease_agreement_id") in lease_ids}

        q["filing_status"] = "CLOSED"
        bump(q)

        for t in store.fuel_card_transactions.values():
            if t.get("fuel_card_id") not in card_ids:
                continue
            if t.get("txn_status") != "POSTED":
                continue
            if not t.get("ifta_eligible"):
                continue
            ts = parse_iso(t["posted_at"])
            if w_start <= ts <= w_end:
                t["txn_status"] = "IFTA_INCLUDED"
    return respond(ifta_view(q), 200)
