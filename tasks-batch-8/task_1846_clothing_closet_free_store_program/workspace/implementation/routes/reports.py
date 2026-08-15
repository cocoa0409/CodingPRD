"""Impact and inventory turnover report (PRD 3.9).

Trailing 28-day half-open window (now-28d, now]; an event exactly 28 days
before the present is excluded.
"""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
from db import store
from errors import bad_request
from middleware import require_roles
from response import ok
from routes.items import get_zone_or_404
from util import quantize, round_half_up_int

bp = Blueprint("reports", __name__)

WINDOW_DAYS = 28


@bp.get("/closet/reports/impact")
@require_roles("ProgramAdmin", "VolunteerLead")
def impact_report():
    zone_id = request.args.get("zone_id")
    if zone_id is None:
        raise bad_request("Missing required query parameter: zone_id")
    zone = get_zone_or_404(zone_id)

    now = db.now()
    window_start = now - timedelta(days=WINDOW_DAYS)

    def in_window(dt):
        return dt is not None and window_start < dt <= now

    window_distributed = sum(
        1 for i in store.items.values()
        if i["distributed_from_zone_id"] == zone_id and in_window(i["distributed_at"])
    )
    window_stocked = sum(
        1 for i in store.items.values()
        if in_window(i["stocked_at"])
        and (
            i["storage_zone_id"] == zone_id
            or i["distributed_from_zone_id"] == zone_id
        )
    )
    current_stock = zone["current_stock"]
    stock_at_window_start = current_stock + window_distributed - window_stocked

    denom_current = max(1, current_stock)
    avg_mean = round_half_up_int(
        (Decimal(stock_at_window_start) + Decimal(current_stock)) / 2
    )
    denom_average = max(1, avg_mean)
    # Both ratios at four decimal places, rounded half up (PRD 2.9).
    turnover_current = float(
        quantize(Decimal(window_distributed) / Decimal(denom_current), "0.0001")
    )
    turnover_average = float(
        quantize(Decimal(window_distributed) / Decimal(denom_average), "0.0001")
    )

    items_distributed_total = sum(
        1 for i in store.items.values() if i["status"] == "DISTRIBUTED"
    )
    unique_clients_served = len(
        {v["client_id"] for v in store.visits.values() if v["status"] == "CHECKED_OUT"}
    )
    recycled_items_total = sum(
        1 for i in store.items.values() if i["status"] == "RECYCLED"
    )
    provisional_total = sum(
        b["provisional_credit_cents"]
        for b in store.recycling.values()
        if b["provisional_credit_cents"] is not None
    )
    final_total = sum(
        b["final_credit_cents"]
        for b in store.recycling.values()
        if b["final_credit_cents"] is not None
    )

    return ok({
        "zone_id": zone_id,
        "current_stock": current_stock,
        "window_distributed": window_distributed,
        "window_stocked": window_stocked,
        "stock_at_window_start": stock_at_window_start,
        "turnover_current_basis": turnover_current,
        "turnover_average_basis": turnover_average,
        "items_distributed_total": items_distributed_total,
        "unique_clients_served": unique_clients_served,
        "recycled_items_total": recycled_items_total,
        "recycling_provisional_credit_cents_total": provisional_total,
        "recycling_final_credit_cents_total": final_total,
    })
