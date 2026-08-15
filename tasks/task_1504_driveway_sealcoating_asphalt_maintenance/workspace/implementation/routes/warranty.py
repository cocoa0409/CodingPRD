"""WarrantyRecord + WarrantyClaim endpoints."""

from flask import Blueprint, request

from clock import now_iso_ms
from db import DB
from middleware import (
    require_role, get_json_body, require_fields, check_unknown_fields,
    require_enum, base_fields, paginate, err, touch,
)
from response import success_object, success_list
from errors import (
    ERR_WARRANTY_RECORD_NOT_FOUND, ERR_WARRANTY_CLAIM_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER, ERR_WARRANTY_NOT_ACTIVE, ERR_WARRANTY_EXPIRED,
    ERR_CLAIM_NOT_OPEN, ERR_SEGREGATION_OF_DUTIES,
)
from services import check_warranty_active

bp = Blueprint("warranty", __name__)


def serialize_record(r):
    return {
        "id": r["id"],
        "work_order_id": r["work_order_id"],
        "property_id": r["property_id"],
        "warranty_months": r["warranty_months"],
        "started_on": r["started_on"],
        "expires_on": r["expires_on"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_claim(c):
    return {
        "id": c["id"],
        "warranty_record_id": c["warranty_record_id"],
        "claim_type": c["claim_type"],
        "description": c["description"],
        "investigated_by": c["investigated_by"],
        "repair_work_order_id": c["repair_work_order_id"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


# ---- records ----

@bp.get("/api/warranty-records")
def list_records():
    user_id, role = require_role("OfficeAdmin", "Dispatcher", "Customer")
    items = list(DB.warranty_records.values())
    if role == "Customer":
        own_props = {p["id"] for p in DB.properties.values() if p["customer_id"] == user_id}
        items = [r for r in items if r["property_id"] in own_props]
    wo_filter = request.args.get("work_order_id")
    prop_filter = request.args.get("property_id")
    status_filter = request.args.get("status")
    if wo_filter:
        items = [r for r in items if r["work_order_id"] == wo_filter]
    if prop_filter:
        items = [r for r in items if r["property_id"] == prop_filter]
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]
    items.sort(key=lambda r: r["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_record(r) for r in page], limit, offset, total)


@bp.get("/api/warranty-records/<recordId>")
def get_record(recordId):
    user_id, role = require_role("OfficeAdmin", "Dispatcher", "Customer")
    r = DB.warranty_records.get(recordId)
    if r is None:
        raise err(ERR_WARRANTY_RECORD_NOT_FOUND, 404, "Warranty record id does not exist")
    if role == "Customer":
        prop = DB.properties.get(r["property_id"])
        if prop is None or prop["customer_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, 403,
                      "Customer acting on a resource owned by a different customer")
    return success_object(serialize_record(r))


# ---- claims ----

@bp.post("/api/warranty-claims")
def create_claim():
    user_id, role = require_role("Customer")
    body = get_json_body()
    check_unknown_fields(body, {"warranty_record_id", "claim_type", "description"})
    require_fields(body, ["warranty_record_id", "claim_type", "description"])
    rec = DB.warranty_records.get(body["warranty_record_id"])
    if rec is None:
        raise err(ERR_WARRANTY_RECORD_NOT_FOUND, 404, "Warranty record id does not exist")
    # Ownership
    prop = DB.properties.get(rec["property_id"])
    if prop is None or prop["customer_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, 403,
                  "Customer acting on a resource owned by a different customer")
    # State: ACTIVE + not expired (lazy flip)
    if rec["status"] != "ACTIVE":
        # Could be CLAIM_OPEN/EXPIRED/EXHAUSTED. If ACTIVE-but-past-expiry, the lazy flip
        # fires below via check_warranty_active.
        if rec["status"] == "ACTIVE":
            pass  # unreachable but explicit
        else:
            # Check if it should lazily flip to EXPIRED first
            if rec["status"] != "EXPIRED":
                raise err(ERR_WARRANTY_NOT_ACTIVE, 409,
                          "Claim requires WarrantyRecord in ACTIVE")
            else:
                raise err(ERR_WARRANTY_NOT_ACTIVE, 409,
                          "Claim requires WarrantyRecord in ACTIVE")
    check_warranty_active(rec)
    claim_type = require_enum(body, "claim_type", {"CRACK_RECURRENCE", "PEELING", "FADE"})
    c = base_fields()
    c.update({
        "warranty_record_id": rec["id"],
        "claim_type": claim_type,
        "description": body["description"],
        "investigated_by": None,
        "repair_work_order_id": None,
        "status": "OPEN",
    })
    DB.warranty_claims[c["id"]] = c
    rec["status"] = "CLAIM_OPEN"
    touch(rec)
    return success_object(serialize_claim(c), status=201)


@bp.get("/api/warranty-claims")
def list_claims():
    user_id, role = require_role("OfficeAdmin", "Dispatcher", "Customer")
    items = list(DB.warranty_claims.values())
    if role == "Customer":
        own_props = {p["id"] for p in DB.properties.values() if p["customer_id"] == user_id}
        own_recs = {r["id"] for r in DB.warranty_records.values() if r["property_id"] in own_props}
        items = [c for c in items if c["warranty_record_id"] in own_recs]
    rec_filter = request.args.get("warranty_record_id")
    status_filter = request.args.get("status")
    if rec_filter:
        items = [c for c in items if c["warranty_record_id"] == rec_filter]
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]
    items.sort(key=lambda c: c["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_claim(c) for c in page], limit, offset, total)


@bp.get("/api/warranty-claims/<claimId>")
def get_claim(claimId):
    user_id, role = require_role("OfficeAdmin", "Dispatcher", "Customer")
    c = DB.warranty_claims.get(claimId)
    if c is None:
        raise err(ERR_WARRANTY_CLAIM_NOT_FOUND, 404, "Warranty claim id does not exist")
    if role == "Customer":
        rec = DB.warranty_records.get(c["warranty_record_id"])
        prop = DB.properties.get(rec["property_id"]) if rec else None
        if prop is None or prop["customer_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, 403,
                      "Customer acting on a resource owned by a different customer")
    return success_object(serialize_claim(c))


@bp.post("/api/warranty-claims/<claimId>/investigate")
def investigate_claim(claimId):
    user_id, role = require_role("OfficeAdmin")
    c = DB.warranty_claims.get(claimId)
    if c is None:
        raise err(ERR_WARRANTY_CLAIM_NOT_FOUND, 404, "Warranty claim id does not exist")
    if c["status"] != "OPEN":
        raise err(ERR_CLAIM_NOT_OPEN, 409,
                  "investigate requires OPEN; approve/deny require INVESTIGATING")
    c["status"] = "INVESTIGATING"
    c["investigated_by"] = user_id
    touch(c)
    return success_object(serialize_claim(c))


def _adjudicate(claimId, action):
    """Common path for approve/deny."""
    user_id, role = require_role("OfficeAdmin")
    c = DB.warranty_claims.get(claimId)
    if c is None:
        raise err(ERR_WARRANTY_CLAIM_NOT_FOUND, 404, "Warranty claim id does not exist")
    if c["status"] != "INVESTIGATING":
        raise err(ERR_CLAIM_NOT_OPEN, 409,
                  "investigate requires OPEN; approve/deny require INVESTIGATING")
    if c["investigated_by"] == user_id:
        raise err(ERR_SEGREGATION_OF_DUTIES, 403,
                  "Approver/denier must differ from the claim's investigator")
    return c


@bp.post("/api/warranty-claims/<claimId>/approve")
def approve_claim(claimId):
    c = _adjudicate(claimId, "approve")
    # Create warranty-repair WorkOrder
    rec = DB.warranty_records.get(c["warranty_record_id"])
    orig_wo = DB.work_orders.get(rec["work_order_id"]) if rec else None
    wo = base_fields()
    wo.update({
        "property_id": orig_wo["property_id"] if orig_wo else None,
        "quote_id": None,
        "warranty_claim_id": c["id"],
        "route_sheet_id": None,
        "material_lot_id": None,
        "include_crack_fill": orig_wo["include_crack_fill"] if orig_wo else False,
        "include_patch": orig_wo["include_patch"] if orig_wo else False,
        "include_seal": orig_wo["include_seal"] if orig_wo else False,
        "include_striping": False,
        "coats": 1,
        "material_grade": orig_wo["material_grade"] if orig_wo else "STANDARD",
        "quoted_area_sqft": orig_wo["actual_area_sqft"] if orig_wo else 0,
        "quoted_total_cents": 0,
        "scheduled_date": None,
        "window_start_hour": None,
        "window_end_hour": None,
        "drive_minutes_est": None,
        "vehicles_to_move": None,
        "reserved_gallons": 0,
        "execution_status": "PENDING",
        "billing_status": "UNINVOICED",
        "striping_status": "NOT_REQUIRED",
        "stall_count": None,
        "ada_stalls_required": None,
        "stripe_linear_ft_computed": None,
        "actual_area_sqft": None,
        "actual_crack_ft": None,
        "actual_pothole_area_sqft": None,
        "actual_stripe_ft": None,
        "gallons_used": None,
        "started_at": None,
        "finished_at": None,
        "cure_until": None,
        "completed_at": None,
    })
    DB.work_orders[wo["id"]] = wo
    c["status"] = "APPROVED"
    c["repair_work_order_id"] = wo["id"]
    touch(c)
    return success_object(serialize_claim(c))


@bp.post("/api/warranty-claims/<claimId>/deny")
def deny_claim(claimId):
    c = _adjudicate(claimId, "deny")
    c["status"] = "DENIED"
    touch(c)
    rec = DB.warranty_records.get(c["warranty_record_id"])
    if rec is not None and rec["status"] == "CLAIM_OPEN":
        rec["status"] = "ACTIVE"
        touch(rec)
    return success_object(serialize_claim(c))
