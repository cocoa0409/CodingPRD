from flask import Blueprint, request

import services as svc
from errors import ApiError, err_invalid_request, err_unauthorized
from middleware import (
    auth,
    get_body,
    require,
    optional,
    optional_enum,
    lookup,
    lookup_fk,
    parse_pagination,
    paginate,
)
from response import ok_object, ok_list

bp = Blueprint("yards", __name__)

AGGRESSION_FLAGS = {"NONE", "CAUTION", "AGGRESSIVE"}


def _check_yard_ranges(size, pets):
    if size is not None and not (1 <= size <= 200000):
        raise err_invalid_request("yard_size_sqft must be between 1 and 200000")
    if pets is not None and not (0 <= pets <= 20):
        raise err_invalid_request("pet_count must be between 0 and 20")


def _recompute_active_subscriptions(yard):
    """Cascade: any ACTIVE subscription on this yard recomputes its fee snapshot."""
    for sub in svc.subscriptions.values():
        if sub["yard_id"] == yard["id"] and sub["status"] == "ACTIVE":
            plan = svc.plans.get(sub["plan_id"])
            if plan is not None:
                sub["monthly_fee_cents_snapshot"] = svc.monthly_fee(plan, yard)
                svc.bump(sub)


@bp.post("/api/yards")
def create_yard():
    uid, role = auth("OperationsManager", "Customer")
    data = get_body()
    customer_id = require(data, "customer_id", str)
    address_line1 = require(data, "address_line1", str)
    city = require(data, "city", str)
    state_code = require(data, "state_code", str)
    postal_code = require(data, "postal_code", str)
    yard_size_sqft = require(data, "yard_size_sqft", int)
    pet_count = require(data, "pet_count", int)
    service_region_code = require(data, "service_region_code", str)
    is_multi = optional(data, "is_multifamily_common_area", bool, False)
    hoa_code = optional(data, "hoa_account_code", str)
    _check_yard_ranges(yard_size_sqft, pet_count)
    lookup_fk(svc.customers, customer_id, "Customer")
    if role == "Customer" and customer_id != uid:
        raise err_unauthorized("Customers may only create yards for themselves")
    if is_multi and not hoa_code:
        raise ApiError("ERR_HOA_CODE_REQUIRED", 422,
                       "hoa_account_code is required when is_multifamily_common_area is true")
    rec = svc.new_record()
    rec.update(
        {
            "customer_id": customer_id,
            "address_line1": address_line1,
            "city": city,
            "state_code": state_code,
            "postal_code": postal_code,
            "yard_size_sqft": yard_size_sqft,
            "pet_count": pet_count,
            "is_multifamily_common_area": is_multi,
            "hoa_account_code": hoa_code,
            "service_region_code": service_region_code,
        }
    )
    svc.yards[rec["id"]] = rec
    _recompute_active_subscriptions(rec)
    return ok_object(svc.ser_yard(rec), status=201)


@bp.get("/api/yards/<yid>")
def get_yard(yid):
    uid, role = auth("OperationsManager", "Customer", "Technician")
    rec = lookup(svc.yards, yid, "Yard")
    if role == "Customer" and rec["customer_id"] != uid:
        raise err_unauthorized("Customers may only access their own yards")
    return ok_object(svc.ser_yard(rec))


@bp.get("/api/yards")
def list_yards():
    uid, role = auth("OperationsManager", "Customer", "Technician")
    limit, offset = parse_pagination()
    records = list(svc.yards.values())
    customer_id = request.args.get("customer_id")
    if role == "Customer":
        if customer_id is not None and customer_id != uid:
            raise err_unauthorized("Customers may only list their own yards")
        records = [y for y in records if y["customer_id"] == uid]
    elif customer_id is not None:
        records = [y for y in records if y["customer_id"] == customer_id]
    region = request.args.get("service_region_code")
    if region is not None:
        records = [y for y in records if y["service_region_code"] == region]
    page, total = paginate(records, limit, offset)
    return ok_list([svc.ser_yard(y) for y in page], total, limit, offset)


@bp.put("/api/yards/<yid>")
def update_yard(yid):
    uid, role = auth("OperationsManager", "Customer")
    rec = lookup(svc.yards, yid, "Yard")
    if role == "Customer" and rec["customer_id"] != uid:
        raise err_unauthorized("Customers may only update their own yards")
    data = get_body()
    size = optional(data, "yard_size_sqft", int)
    pets = optional(data, "pet_count", int)
    is_multi = optional(data, "is_multifamily_common_area", bool)
    hoa_code = optional(data, "hoa_account_code", str)
    region = optional(data, "service_region_code", str)
    _check_yard_ranges(size, pets)
    new_multi = rec["is_multifamily_common_area"] if is_multi is None else is_multi
    new_hoa = rec["hoa_account_code"] if hoa_code is None else hoa_code
    if new_multi and not new_hoa:
        raise ApiError("ERR_HOA_CODE_REQUIRED", 422,
                       "hoa_account_code is required when is_multifamily_common_area is true")
    if size is not None:
        rec["yard_size_sqft"] = size
    if pets is not None:
        rec["pet_count"] = pets
    if is_multi is not None:
        rec["is_multifamily_common_area"] = is_multi
    if hoa_code is not None:
        rec["hoa_account_code"] = hoa_code
    if region is not None:
        rec["service_region_code"] = region
    svc.bump(rec)
    _recompute_active_subscriptions(rec)
    return ok_object(svc.ser_yard(rec))


# --------------------------- PropertyAccessProfile ---------------------------

@bp.post("/api/yards/<yid>/access-profile")
def create_access_profile(yid):
    uid, role = auth("OperationsManager", "Customer")
    yard = lookup(svc.yards, yid, "Yard")
    if role == "Customer" and yard["customer_id"] != uid:
        raise err_unauthorized("Customers may only manage their own yards")
    data = get_body()
    gate_code = require(data, "gate_access_code", str)
    gate_instructions = require(data, "gate_instructions", str)
    pet_on_premises = require(data, "pet_on_premises", bool)
    flag = optional_enum(data, "pet_aggression_flag", AGGRESSION_FLAGS, "NONE")
    if svc.access_profile_of_yard(yard["id"]) is not None:
        raise err_invalid_request("Yard already has a PropertyAccessProfile")
    rec = svc.new_record()
    rec.update(
        {
            "yard_id": yard["id"],
            "gate_access_code": gate_code,
            "gate_instructions": gate_instructions,
            "pet_on_premises": pet_on_premises,
            "pet_aggression_flag": flag,
            "access_status": "VERIFICATION_PENDING",
            "suspension_reason": None,
        }
    )
    svc.access_profiles[rec["id"]] = rec
    return ok_object(svc.ser_access_profile(rec), status=201)


@bp.get("/api/yards/<yid>/access-profile")
def get_yard_access_profile(yid):
    uid, role = auth("OperationsManager", "Customer", "Technician")
    yard = lookup(svc.yards, yid, "Yard")
    if role == "Customer" and yard["customer_id"] != uid:
        raise err_unauthorized("Customers may only access their own yards")
    limit, offset = parse_pagination()
    profile = svc.access_profile_of_yard(yard["id"])
    records = [profile] if profile is not None else []
    page, total = paginate(records, limit, offset)
    return ok_list([svc.ser_access_profile(p) for p in page], total, limit, offset)


@bp.get("/api/property-access-profiles")
def list_access_profiles():
    uid, role = auth("OperationsManager", "Customer", "Technician")
    limit, offset = parse_pagination()
    records = list(svc.access_profiles.values())
    yard_id = request.args.get("yard_id")
    if yard_id is not None:
        records = [p for p in records if p["yard_id"] == yard_id]
    if role == "Customer":
        own_yards = {y["id"] for y in svc.yards.values() if y["customer_id"] == uid}
        records = [p for p in records if p["yard_id"] in own_yards]
    page, total = paginate(records, limit, offset)
    return ok_list([svc.ser_access_profile(p) for p in page], total, limit, offset)


@bp.post("/api/property-access-profiles/<pid>/verify")
def verify_access_profile(pid):
    auth("OperationsManager")
    rec = lookup(svc.access_profiles, pid, "PropertyAccessProfile")
    if rec["access_status"] not in ("VERIFICATION_PENDING", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "verify is only valid from VERIFICATION_PENDING or SUSPENDED")
    if not rec["gate_access_code"]:
        raise ApiError("ERR_GATE_CODE_REQUIRED", 422,
                       "gate_access_code must be non-empty to verify")
    rec["access_status"] = "VERIFIED"
    rec["suspension_reason"] = None
    svc.bump(rec)
    return ok_object(svc.ser_access_profile(rec))


@bp.post("/api/property-access-profiles/<pid>/suspend")
def suspend_access_profile(pid):
    auth("OperationsManager")
    rec = lookup(svc.access_profiles, pid, "PropertyAccessProfile")
    data = get_body()
    reason = require(data, "reason", str)
    if rec["access_status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "suspend is only valid from VERIFIED")
    rec["access_status"] = "SUSPENDED"
    rec["suspension_reason"] = reason
    svc.bump(rec)
    return ok_object(svc.ser_access_profile(rec))


@bp.post("/api/property-access-profiles/<pid>/require-reverification")
def require_reverification(pid):
    auth("OperationsManager")
    rec = lookup(svc.access_profiles, pid, "PropertyAccessProfile")
    if rec["access_status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "require-reverification is only valid from VERIFIED")
    rec["access_status"] = "VERIFICATION_PENDING"
    svc.bump(rec)
    return ok_object(svc.ser_access_profile(rec))
