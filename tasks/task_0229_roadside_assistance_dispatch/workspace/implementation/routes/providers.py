"""ServiceProvider and ProviderShift routes (PRD §3.3)."""
from flask import Blueprint, request

import db
import errors
import serializers
import validation
from listing import sort_and_window
from middleware import authenticate, require_roles
from response import object_response, array_response

bp = Blueprint("providers", __name__)

VALID_SERVICE_TYPES = validation.SERVICE_TYPES


# ---- ServiceProvider ----

@bp.route("/service-providers", methods=["POST"])
def create_provider():
    ident = authenticate()
    require_roles(ident, {"DispatchOperator"})
    body = validation.get_body()

    validation.require_present(body, [
        "company_name", "current_lat", "current_lng", "capabilities", "rating",
    ])
    validation.require_str(body["company_name"], "company_name")
    validation.require_lat(body["current_lat"], "current_lat")
    validation.require_lng(body["current_lng"], "current_lng")

    caps = body["capabilities"]
    if (not isinstance(caps, list) or len(caps) == 0
            or any(c not in VALID_SERVICE_TYPES for c in caps)):
        raise errors.invalid_request(
            "capabilities must be a non-empty subset of service types.")

    rating = body["rating"]
    if not validation.is_number(rating) or rating < 0.0 or rating > 5.0:
        raise errors.invalid_request("rating must be a number in 0.0..5.0.")

    record = {
        "company_name": body["company_name"],
        "status": "AVAILABLE",
        "current_lat": body["current_lat"],
        "current_lng": body["current_lng"],
        "capabilities": list(caps),
        "rating": rating,
        "active_call_id": None,
    }
    db.stamp_create(record)
    db.service_providers[record["id"]] = record
    return object_response(serializers.service_provider(record), 201)


@bp.route("/service-providers/<provider_id>", methods=["GET"])
def get_provider(provider_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator", "ServiceProvider"})
    p = db.service_providers.get(provider_id)
    if p is None:
        raise errors.not_found("Provider not found.")
    if ident.is_provider and ident.user_id != provider_id:
        raise errors.not_resource_owner("A provider may only fetch its own record.")
    return object_response(serializers.service_provider(p), 200)


@bp.route("/service-providers", methods=["GET"])
def list_providers():
    ident = authenticate()
    require_roles(ident, {"DispatchOperator", "ServiceProvider"})
    limit, offset = validation.parse_pagination()
    status = request.args.get("status")
    records = list(db.service_providers.values())
    if status is not None:
        records = [p for p in records if p["status"] == status]
    page, total = sort_and_window(records, limit, offset)
    return array_response([serializers.service_provider(p) for p in page],
                          limit, offset, total, 200)


@bp.route("/service-providers/<provider_id>/go-offline", methods=["POST"])
def go_offline(provider_id):
    ident = authenticate()
    require_roles(ident, {"ServiceProvider"})
    p = db.service_providers.get(provider_id)
    if p is None:
        raise errors.not_found("Provider not found.")
    if ident.user_id != provider_id:
        raise errors.not_resource_owner("A provider may only act on its own record.")
    if p["status"] != "AVAILABLE":
        raise errors.invalid_state("go-offline is only allowed from AVAILABLE.")
    p["status"] = "OFFLINE"
    db.touch(p)
    return object_response(serializers.service_provider(p), 200)


@bp.route("/service-providers/<provider_id>/go-online", methods=["POST"])
def go_online(provider_id):
    ident = authenticate()
    require_roles(ident, {"ServiceProvider"})
    p = db.service_providers.get(provider_id)
    if p is None:
        raise errors.not_found("Provider not found.")
    if ident.user_id != provider_id:
        raise errors.not_resource_owner("A provider may only act on its own record.")
    if p["status"] != "OFFLINE":
        raise errors.invalid_state("go-online is only allowed from OFFLINE.")
    p["status"] = "AVAILABLE"
    db.touch(p)
    return object_response(serializers.service_provider(p), 200)


@bp.route("/service-providers/<provider_id>/offers", methods=["GET"])
def list_provider_offers(provider_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator", "ServiceProvider"})
    p = db.service_providers.get(provider_id)
    if p is None:
        raise errors.not_found("Provider not found.")
    if ident.is_provider and ident.user_id != provider_id:
        raise errors.not_resource_owner("A provider may only list its own offers.")
    limit, offset = validation.parse_pagination()
    status = request.args.get("status")
    records = [o for o in db.dispatch_offers.values() if o["provider_id"] == provider_id]
    if status is not None:
        records = [o for o in records if o["status"] == status]
    page, total = sort_and_window(records, limit, offset)
    return array_response([serializers.dispatch_offer(o) for o in page],
                          limit, offset, total, 200)


# ---- ProviderShift ----

@bp.route("/service-providers/<provider_id>/shifts", methods=["POST"])
def create_shift(provider_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator", "ServiceProvider"})
    p = db.service_providers.get(provider_id)
    if p is None:
        raise errors.not_found("Provider not found.")
    if ident.is_provider and ident.user_id != provider_id:
        raise errors.not_resource_owner("A provider may only schedule its own shifts.")

    body = validation.get_body()
    validation.require_present(body, ["shift_start", "shift_end"])
    shift_start = validation.parse_datetime(body["shift_start"], "shift_start")
    shift_end = validation.parse_datetime(body["shift_end"], "shift_end")
    if shift_end <= shift_start:
        raise errors.invalid_request("shift_end must be strictly after shift_start.")

    # Overlap check against SCHEDULED shifts for the same provider (half-open).
    for s in db.provider_shifts.values():
        if s["provider_id"] != provider_id or s["status"] != "SCHEDULED":
            continue
        es = validation.parse_datetime(s["shift_start"], "shift_start")
        ee = validation.parse_datetime(s["shift_end"], "shift_end")
        # Positive-measure overlap of [start,end): start < ee and es < end.
        if shift_start < ee and es < shift_end:
            raise errors.ApiError(errors.ERR_SHIFT_OVERLAP, 409,
                                  "New shift overlaps an existing SCHEDULED shift.")

    record = {
        "provider_id": provider_id,
        "shift_start": body["shift_start"],
        "shift_end": body["shift_end"],
        "status": "SCHEDULED",
    }
    db.stamp_create(record)
    db.provider_shifts[record["id"]] = record
    return object_response(serializers.provider_shift(record), 201)


@bp.route("/service-providers/<provider_id>/shifts", methods=["GET"])
def list_shifts(provider_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator", "ServiceProvider"})
    p = db.service_providers.get(provider_id)
    if p is None:
        raise errors.not_found("Provider not found.")
    if ident.is_provider and ident.user_id != provider_id:
        raise errors.not_resource_owner("A provider may only list its own shifts.")
    limit, offset = validation.parse_pagination()
    status = request.args.get("status")
    records = [s for s in db.provider_shifts.values() if s["provider_id"] == provider_id]
    if status is not None:
        records = [s for s in records if s["status"] == status]
    page, total = sort_and_window(records, limit, offset)
    return array_response([serializers.provider_shift(s) for s in page],
                          limit, offset, total, 200)


@bp.route("/service-providers/<provider_id>/shifts/<shift_id>/cancel", methods=["POST"])
def cancel_shift(provider_id, shift_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator", "ServiceProvider"})
    p = db.service_providers.get(provider_id)
    if p is None:
        raise errors.not_found("Provider not found.")
    s = db.provider_shifts.get(shift_id)
    if s is None or s["provider_id"] != provider_id:
        raise errors.not_found("Shift not found.")
    if ident.is_provider and ident.user_id != provider_id:
        raise errors.not_resource_owner("A provider may only cancel its own shifts.")
    if s["status"] != "SCHEDULED":
        raise errors.invalid_state("Only a SCHEDULED shift may be cancelled.")
    s["status"] = "CANCELLED"
    db.touch(s)
    return object_response(serializers.provider_shift(s), 200)
