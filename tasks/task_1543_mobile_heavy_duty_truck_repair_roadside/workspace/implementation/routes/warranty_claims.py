"""WarrantyClaim endpoints: file, submit, decide, appeal, settle."""
from decimal import Decimal

from flask import Blueprint, request

from db import store, new_record, touch
from errors import (ApiError, err_not_found, err_invalid_state,
                    err_validation)
from middleware import auth
from response import success
from serializers import serialize
from services.cascades import wall_now
from services.pricing import warranty_retail_value, service_dispatch
from routes.service_calls import get_call_or_404, ensure_not_cancelled
from util import Field, validate_body, parse_pagination, paginate, rhu

bp = Blueprint("warranty_claims", __name__)

CLAIM_TYPES = {"OEM_BASE", "OEM_POWERTRAIN", "EXTENDED_SERVICE_CONTRACT"}
READ_ROLES = ["OpsAdmin", "Dispatcher", "Technician", "WarrantyAdministrator",
              "BillingClerk"]
LIST_ROLES = ["OpsAdmin", "WarrantyAdministrator", "BillingClerk"]


def _get_claim(claim_id):
    c = store.warranty_claims.get(claim_id)
    if c is None:
        raise err_not_found("WarrantyClaim not found")
    return c


@bp.route("/roadside/service-calls/<serviceCallId>/warranty-claims",
          methods=["POST"])
def create_claim(serviceCallId):
    uid, role = auth(["Technician", "WarrantyAdministrator"])
    call = get_call_or_404(serviceCallId)
    vals = validate_body(request.get_json(silent=True), [
        Field("claim_type", "enum", required=True, enum=CLAIM_TYPES),
        Field("oem_labor_hours", "number", required=True, min_val=0),
        Field("oem_labor_rate_cents", "int", required=True, min_val=0),
        Field("parts_at_cost_cents", "int", required=True, min_val=0),
    ])
    ensure_not_cancelled(call)
    if call["status"] != "REPAIR_COMPLETED":
        raise err_invalid_state("Claim filing requires REPAIR_COMPLETED")
    vehicle = store.vehicles.get(call["vehicle_id"])
    ctype = vals["claim_type"]
    if ctype in ("OEM_BASE", "OEM_POWERTRAIN"):
        expires = vehicle.get("oem_warranty_expires_at") if vehicle else None
        miles_limit = (vehicle.get("oem_warranty_miles_limit")
                       if vehicle else None)
        completion_miles = call.get("completion_odometer_miles")
        ok = (expires is not None and miles_limit is not None
              and call["received_at"] < expires
              and completion_miles is not None
              and completion_miles <= miles_limit)
        if not ok:
            raise ApiError("ERR_WARRANTY_WINDOW_EXPIRED",
                           "OEM claim filed outside the time/mileage coverage "
                           "window", 409)
    elif ctype == "EXTENDED_SERVICE_CONTRACT":
        if not (vehicle and vehicle.get("extended_warranty")):
            raise ApiError("ERR_WARRANTY_NOT_APPLICABLE",
                           "Extended-contract claim on a vehicle without "
                           "extended_warranty", 409)
    for inv in store.invoices.values():
        if (inv["service_call_id"] == call["id"]
                and inv["issue_status"] != "VOID"):
            raise ApiError("ERR_INVOICE_EXISTS",
                           "A non-VOID invoice already exists for the call", 409)
    if role == "Technician":
        filed_by = uid
    else:
        disp = service_dispatch(call)
        filed_by = disp["technician_id"] if disp else None
    oem_value = (rhu(Decimal(str(vals["oem_labor_hours"]))
                     * vals["oem_labor_rate_cents"])
                 + vals["parts_at_cost_cents"])
    rec = new_record()
    now = wall_now()
    rec.update({
        "_created": now, "_updated": now,
        "service_call_id": call["id"],
        "vehicle_id": call["vehicle_id"],
        "claim_type": ctype,
        "filed_by_technician_id": filed_by,
        "oem_labor_hours": vals["oem_labor_hours"],
        "oem_labor_rate_cents": vals["oem_labor_rate_cents"],
        "parts_at_cost_cents": vals["parts_at_cost_cents"],
        "oem_value_cents": oem_value,
        "retail_value_cents": None,
        "recovered_cents": None,
        "status": "DRAFT",
        "denial_reason": None,
        "appeal_count": 0,
        "decided_by": None,
        "settled_amount_cents": None,
    })
    store.warranty_claims[rec["id"]] = rec
    return success(serialize("claim", rec), status=201)


@bp.route("/roadside/warranty-claims/<claimId>", methods=["GET"])
def get_claim(claimId):
    auth(READ_ROLES)
    return success(serialize("claim", _get_claim(claimId)))


@bp.route("/roadside/warranty-claims", methods=["GET"])
def list_claims():
    auth(LIST_ROLES)
    limit, offset = parse_pagination(request.args)
    call_f = request.args.get("service_call_id")
    veh_f = request.args.get("vehicle_id")
    filer_f = request.args.get("filed_by_technician_id")
    status_f = request.args.get("status")
    items = sorted(store.warranty_claims.values(), key=lambda r: r["_seq"])
    if call_f is not None:
        items = [c for c in items if c["service_call_id"] == call_f]
    if veh_f is not None:
        items = [c for c in items if c["vehicle_id"] == veh_f]
    if filer_f is not None:
        items = [c for c in items if c["filed_by_technician_id"] == filer_f]
    if status_f is not None:
        items = [c for c in items if c["status"] == status_f]
    page, total, has_more = paginate(items, limit, offset)
    return success([serialize("claim", c) for c in page],
                   response_type="array",
                   pagination={"limit": limit, "offset": offset,
                               "total_count": total, "has_more": has_more})


@bp.route("/roadside/warranty-claims/<claimId>/submit", methods=["POST"])
def submit(claimId):
    auth(["WarrantyAdministrator"])
    claim = _get_claim(claimId)
    validate_body(request.get_json(silent=True), [])
    if claim["status"] != "DRAFT":
        raise err_invalid_state("Submit requires status DRAFT")
    call = store.service_calls.get(claim["service_call_id"])
    retail = warranty_retail_value(claim, call)
    claim["retail_value_cents"] = retail
    claim["recovered_cents"] = min(claim["oem_value_cents"], retail)
    claim["status"] = "SUBMITTED"
    touch(claim, wall_now())
    return success(serialize("claim", claim))


@bp.route("/roadside/warranty-claims/<claimId>/decide", methods=["POST"])
def decide(claimId):
    uid, role = auth(["WarrantyAdministrator"])
    claim = _get_claim(claimId)
    vals = validate_body(request.get_json(silent=True), [
        Field("decision", "enum", required=True, enum={"APPROVED", "DENIED"}),
        Field("denial_reason", "string"),
    ])
    if claim["status"] not in ("SUBMITTED", "APPEALED"):
        raise err_invalid_state("Decide requires status SUBMITTED or APPEALED")
    if vals["decision"] == "DENIED":
        if not vals.get("denial_reason"):
            raise err_validation("denial_reason is required when DENIED")
        claim["status"] = "DENIED"
        claim["denial_reason"] = vals["denial_reason"]
    else:
        claim["status"] = "APPROVED"
    claim["decided_by"] = uid
    touch(claim, wall_now())
    return success(serialize("claim", claim))


@bp.route("/roadside/warranty-claims/<claimId>/appeal", methods=["POST"])
def appeal(claimId):
    auth(["Dispatcher", "OpsAdmin"])
    claim = _get_claim(claimId)
    validate_body(request.get_json(silent=True), [])
    if claim["status"] != "DENIED":
        raise err_invalid_state("Appeal requires status DENIED")
    if claim["appeal_count"] >= 2:
        raise ApiError("ERR_APPEAL_LIMIT_REACHED",
                       "Appeal attempted with appeal_count == 2", 409)
    claim["appeal_count"] += 1
    claim["status"] = "APPEALED"
    touch(claim, wall_now())
    return success(serialize("claim", claim))


@bp.route("/roadside/warranty-claims/<claimId>/settle", methods=["POST"])
def settle(claimId):
    auth(["WarrantyAdministrator"])
    claim = _get_claim(claimId)
    vals = validate_body(request.get_json(silent=True), [
        Field("settled_amount_cents", "int", required=True, min_val=0),
    ])
    if claim["status"] != "APPROVED":
        raise err_invalid_state("Settle requires status APPROVED")
    if vals["settled_amount_cents"] != claim["recovered_cents"]:
        raise err_validation("settled_amount_cents must equal recovered_cents")
    claim["settled_amount_cents"] = vals["settled_amount_cents"]
    claim["status"] = "SETTLED"
    touch(claim, wall_now())
    return success(serialize("claim", claim))
