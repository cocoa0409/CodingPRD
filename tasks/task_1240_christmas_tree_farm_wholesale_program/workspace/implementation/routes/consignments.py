"""Consignment endpoints: create, read, list, deliver, report-return,
settle, dispute (PRD 3.7)."""
from flask import Blueprint, request

from authz import require_role
from db import store
from errors import (insufficient_standing, invalid_state, malformed,
                    posture_forbids, return_exceeds_delivered)
from helpers import (body, get_or_404, is_num, new_record, paginate,
                     req_field, req_int, req_num, req_str, touch)
from respond import success
from serialize import consignment_out
from services import (buckets_of_lot, check_lot_depleted, final_settlement,
                      lot_of_bucket, provisional_settlement)

bp = Blueprint("consignments", __name__)


def _season_of_consignment(cons):
    return store.seasons[cons["season_id"]]


@bp.post("/api/consignments")
def create_consignment():
    require_role("FarmManager")
    data = body()
    # Existence of body FK references, left to right (priority 4).
    season_id = req_field(data, "season_id")
    if isinstance(season_id, str):
        get_or_404(store.seasons, season_id, "season_id does not exist")
    bucket_id = req_field(data, "bucket_id")
    if isinstance(bucket_id, str):
        get_or_404(store.stand_buckets, bucket_id, "bucket_id does not exist")
    # Well-formedness (priority 5).
    season_id = req_str(data, "season_id")
    bucket_id = req_str(data, "bucket_id")
    lot_name = req_str(data, "lot_name")
    quantity = req_int(data, "quantity", minimum=1)
    unit_price_cents = req_int(data, "unit_price_cents", minimum=0)
    max_return_pct = req_num(data, "max_return_pct")
    if not (0 <= max_return_pct <= 1):
        raise malformed("Field max_return_pct must be between 0 and 1 inclusive")
    # Posture (priority 7): consignment creation requires BOOKING or HARVEST.
    if store.seasons[season_id]["posture"] not in ("BOOKING", "HARVEST"):
        raise posture_forbids("Consignment creation requires BOOKING or HARVEST")
    rec = new_record({
        "season_id": season_id,
        "bucket_id": bucket_id,
        "lot_name": lot_name,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "max_return_pct": max_return_pct,
        "delivered_count": None,
        "returned_count": 0,
        "provisional_settlement_cents": None,
        "final_settlement_cents": None,
        "status": "DRAFT",
    })
    store.consignments[rec["id"]] = rec
    return success(consignment_out(rec), status=201)


@bp.get("/api/consignments/<cid>")
def get_consignment(cid):
    require_role("Owner", "FarmManager")
    return success(consignment_out(get_or_404(store.consignments, cid)))


@bp.get("/api/consignments")
def list_consignments():
    require_role("Owner", "FarmManager")
    items = sorted(store.consignments.values(), key=lambda c: c["_seq"])
    season_id = request.args.get("season_id")
    bucket_id = request.args.get("bucket_id")
    if season_id is not None:
        items = [c for c in items if c["season_id"] == season_id]
    if bucket_id is not None:
        items = [c for c in items if c["bucket_id"] == bucket_id]
    page, meta = paginate(items)
    return success([consignment_out(c) for c in page], response_type="array",
                   pagination=meta)


@bp.post("/api/consignments/<cid>/deliver")
def deliver_consignment(cid):
    require_role("FarmManager")
    cons = get_or_404(store.consignments, cid)
    data = body()
    delivered = req_int(data, "delivered_count", minimum=1)
    # State (priority 6): only a DRAFT consignment can be delivered.
    if cons["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT consignment can be delivered")
    # Posture (priority 7): delivery requires HARVEST or SHIPPING.
    if _season_of_consignment(cons)["posture"] not in ("HARVEST", "SHIPPING"):
        raise posture_forbids("Delivery requires HARVEST or SHIPPING posture")
    bucket = store.stand_buckets[cons["bucket_id"]]
    # Constraint (priority 21): delivered_count <= bucket available_count.
    if delivered > bucket["standing_count"] - bucket["reserved_count"]:
        raise insufficient_standing("delivered_count exceeds available_count")
    bucket["standing_count"] -= delivered
    bucket["consigned_cumulative"] += delivered
    touch(bucket)
    cons["delivered_count"] = delivered
    cons["provisional_settlement_cents"] = provisional_settlement(
        delivered, cons["unit_price_cents"], cons["max_return_pct"])
    cons["status"] = "DELIVERED"
    touch(cons)
    check_lot_depleted(lot_of_bucket(bucket))
    return success(consignment_out(cons))


@bp.post("/api/consignments/<cid>/report-return")
def report_return(cid):
    require_role("FarmManager")
    cons = get_or_404(store.consignments, cid)
    data = body()
    returned = req_int(data, "returned_count", minimum=0)
    # State (priority 6): reports are accepted from DELIVERED (first report)
    # or DISPUTED (re-report after dispute).
    if cons["status"] not in ("DELIVERED", "DISPUTED"):
        raise invalid_state("Returns can be reported only from DELIVERED or DISPUTED")
    # Posture (priority 7): DELIVERED reports in SHIPPING or SETTLEMENT;
    # DISPUTED re-reports only in SETTLEMENT.
    posture = _season_of_consignment(cons)["posture"]
    if cons["status"] == "DELIVERED" and posture not in ("SHIPPING", "SETTLEMENT"):
        raise posture_forbids("Return reports require SHIPPING or SETTLEMENT")
    if cons["status"] == "DISPUTED" and posture != "SETTLEMENT":
        raise posture_forbids("Re-reports after dispute require SETTLEMENT")
    # Constraint (priority 28): returned_count <= delivered_count.
    if returned > cons["delivered_count"]:
        raise return_exceeds_delivered("returned_count exceeds delivered_count")
    cons["returned_count"] = returned
    cons["status"] = "SETTLING"
    touch(cons)
    return success(consignment_out(cons))


@bp.post("/api/consignments/<cid>/settle")
def settle_consignment(cid):
    require_role("FarmManager")
    cons = get_or_404(store.consignments, cid)
    if cons["status"] != "SETTLING":
        raise invalid_state("Only a SETTLING consignment can be settled")
    if _season_of_consignment(cons)["posture"] != "SETTLEMENT":
        raise posture_forbids("Settlement requires SETTLEMENT posture")
    cons["final_settlement_cents"] = final_settlement(
        cons["delivered_count"], cons["returned_count"], cons["unit_price_cents"])
    cons["status"] = "SETTLED"
    touch(cons)
    return success(consignment_out(cons))


@bp.post("/api/consignments/<cid>/dispute")
def dispute_consignment(cid):
    require_role("FarmManager")
    cons = get_or_404(store.consignments, cid)
    if cons["status"] != "SETTLING":
        raise invalid_state("Only a SETTLING consignment can be disputed")
    if _season_of_consignment(cons)["posture"] != "SETTLEMENT":
        raise posture_forbids("Dispute requires SETTLEMENT posture")
    cons["status"] = "DISPUTED"
    touch(cons)
    return success(consignment_out(cons))
