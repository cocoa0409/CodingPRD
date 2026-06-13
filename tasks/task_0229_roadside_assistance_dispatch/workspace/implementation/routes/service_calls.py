"""ServiceCall, DispatchOffer, candidate-ranking routes (PRD §3.5-§3.9)."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import errors
import serializers
import validation
from listing import sort_and_window
from middleware import authenticate, require_roles
from response import object_response, array_response
from services import geo, pricing

bp = Blueprint("service_calls", __name__)

VALID_SERVICE_TYPES = validation.SERVICE_TYPES
MAX_DISPATCH_ATTEMPTS = 3


# --------------------------------------------------------------------------
# Creation + read
# --------------------------------------------------------------------------

@bp.route("/service-calls", methods=["POST"])
def create_call():
    ident = authenticate()
    require_roles(ident, {"Member", "DispatchOperator"})
    body = validation.get_body()

    validation.require_present(body, ["member_id", "service_type", "breakdown_lat", "breakdown_lng"])

    member_id = body["member_id"]
    if not isinstance(member_id, str):
        raise errors.invalid_request("member_id must be a string.")
    member = db.members.get(member_id)
    if member is None:
        raise errors.not_found("Member not found.")

    # ownership: a member may only open its own calls.
    if ident.is_member and ident.user_id != member_id:
        raise errors.not_resource_owner("A member may only open its own service calls.")

    service_type = body["service_type"]
    validation.require_enum(service_type, VALID_SERVICE_TYPES, "service_type")
    validation.require_lat(body["breakdown_lat"], "breakdown_lat")
    validation.require_lng(body["breakdown_lng"], "breakdown_lng")

    dropoff_lat = body.get("dropoff_lat")
    dropoff_lng = body.get("dropoff_lng")
    if service_type == "TOW":
        if dropoff_lat is None or dropoff_lng is None:
            raise errors.invalid_request("TOW requires dropoff_lat and dropoff_lng.")
        validation.require_lat(dropoff_lat, "dropoff_lat")
        validation.require_lng(dropoff_lng, "dropoff_lng")
    else:
        # dropoff ignored for non-tow; validate if present and well-typed only.
        if dropoff_lat is not None:
            validation.require_lat(dropoff_lat, "dropoff_lat")
        if dropoff_lng is not None:
            validation.require_lng(dropoff_lng, "dropoff_lng")

    # business: member must be ACTIVE (after existence/ownership/state gates).
    if member["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_MEMBERSHIP_NOT_ACTIVE, 409,
                              "Member must be ACTIVE to open a service call.")

    plan = db.membership_plans[member["plan_id"]]

    if service_type == "TOW":
        tow_distance = geo.haversine_miles(
            body["breakdown_lat"], body["breakdown_lng"], dropoff_lat, dropoff_lng)
    else:
        tow_distance = 0

    estimated = pricing.service_cost_cents(plan, service_type, tow_distance)

    record = {
        "member_id": member_id,
        "service_type": service_type,
        "breakdown_lat": body["breakdown_lat"],
        "breakdown_lng": body["breakdown_lng"],
        "dropoff_lat": dropoff_lat,
        "dropoff_lng": dropoff_lng,
        "status": "DISPATCHING",
        "assigned_provider_id": None,
        "tow_distance_miles": tow_distance,
        "estimated_cost_cents": estimated,
        "final_cost_cents": 0,
        "member_out_of_pocket_cents": 0,
        "final_towed_miles": 0,
        "dispatch_attempts": 0,
    }
    db.stamp_create(record)
    db.service_calls[record["id"]] = record
    return object_response(serializers.service_call(record), 201)


@bp.route("/service-calls/<call_id>", methods=["GET"])
def get_call(call_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator", "Member", "ServiceProvider"})
    call = db.service_calls.get(call_id)
    if call is None:
        raise errors.not_found("Service call not found.")
    if ident.is_member and ident.user_id != call["member_id"]:
        raise errors.not_resource_owner("A member may only fetch its own service calls.")
    if ident.is_provider and ident.user_id != call.get("assigned_provider_id"):
        raise errors.not_resource_owner("A provider may only fetch its assigned calls.")
    return object_response(serializers.service_call(call), 200)


@bp.route("/service-calls", methods=["GET"])
def list_calls():
    ident = authenticate()
    require_roles(ident, {"DispatchOperator", "Member"})
    limit, offset = validation.parse_pagination()
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    records = list(db.service_calls.values())
    if ident.is_member:
        records = [c for c in records if c["member_id"] == ident.user_id]
    if member_id is not None:
        records = [c for c in records if c["member_id"] == member_id]
    if status is not None:
        records = [c for c in records if c["status"] == status]
    page, total = sort_and_window(records, limit, offset)
    return array_response([serializers.service_call(c) for c in page],
                          limit, offset, total, 200)


# --------------------------------------------------------------------------
# Dispatch candidates (computed read)
# --------------------------------------------------------------------------

@bp.route("/service-calls/<call_id>/dispatch-candidates", methods=["GET"])
def dispatch_candidates(call_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator"})
    call = db.service_calls.get(call_id)
    if call is None:
        raise errors.not_found("Service call not found.")
    limit, offset = validation.parse_pagination()

    now = clock.now()
    service_type = call["service_type"]
    candidates = []
    for p in db.service_providers.values():
        if p["status"] != "AVAILABLE":
            continue
        if service_type not in p["capabilities"]:
            continue
        dist = geo.haversine_miles(
            p["current_lat"], p["current_lng"],
            call["breakdown_lat"], call["breakdown_lng"])
        if dist > geo.MAX_DISPATCH_RADIUS_MILES:
            continue
        # at least one SCHEDULED shift whose half-open window contains now
        in_shift = False
        for s in db.provider_shifts.values():
            if s["provider_id"] != p["id"] or s["status"] != "SCHEDULED":
                continue
            ss = validation.parse_datetime(s["shift_start"], "shift_start")
            se = validation.parse_datetime(s["shift_end"], "shift_end")
            if ss <= now < se:
                in_shift = True
                break
        if not in_shift:
            continue
        candidates.append((p, dist))

    is_tow = service_type == "TOW"

    def sort_key(item):
        p, dist = item
        caps_len = len(p["capabilities"]) if is_tow else 0
        return (
            -float(p["rating"]),          # rating DESC
            dist,                          # offer_distance_miles ASC
            caps_len,                      # (TOW only) capabilities length ASC
            p["created_at"],               # created_at ASC
            p["id"],                       # stable
        )

    ranked = sorted(candidates, key=sort_key)
    providers = [p for p, _ in ranked]
    total = len(providers)
    page = providers[offset:offset + limit]
    return array_response([serializers.service_provider(p) for p in page],
                          limit, offset, total, 200)


# --------------------------------------------------------------------------
# Offers
# --------------------------------------------------------------------------

@bp.route("/service-calls/<call_id>/offers", methods=["POST"])
def create_offer(call_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator"})
    call = db.service_calls.get(call_id)
    if call is None:
        raise errors.not_found("Service call not found.")

    body = validation.get_body()
    validation.require_present(body, ["provider_id", "expected_service_call_version"])

    provider_id = body["provider_id"]
    if not isinstance(provider_id, str):
        raise errors.invalid_request("provider_id must be a string.")
    provider = db.service_providers.get(provider_id)
    if provider is None:
        raise errors.not_found("Provider not found.")

    expected_version = body["expected_service_call_version"]
    if not validation.is_int(expected_version):
        raise errors.invalid_request("expected_service_call_version must be an integer.")

    # state: call must be DISPATCHING
    if call["status"] != "DISPATCHING":
        raise errors.invalid_state("Offers may only be dispatched on a DISPATCHING call.")

    # Business rules in pinned precedence (PRD §3.7):
    # capability -> provider availability -> outstanding offer -> attempts cap -> version
    if call["service_type"] not in provider["capabilities"]:
        raise errors.ApiError(errors.ERR_CAPABILITY_MISMATCH, 409,
                              "Provider cannot perform the requested service type.")

    if provider["status"] != "AVAILABLE":
        raise errors.ApiError(errors.ERR_PROVIDER_UNAVAILABLE, 409,
                              "Provider is not AVAILABLE.")

    has_live = any(o["service_call_id"] == call_id and o["status"] == "OFFERED"
                   for o in db.dispatch_offers.values())
    if has_live:
        raise errors.ApiError(errors.ERR_OFFER_ALREADY_OUTSTANDING, 409,
                              "A live offer already exists on this call.")

    if call["dispatch_attempts"] >= MAX_DISPATCH_ATTEMPTS:
        raise errors.ApiError(errors.ERR_DISPATCH_LIMIT_REACHED, 409,
                              "Re-offer budget exhausted.")

    if expected_version != call["version"]:
        raise errors.ApiError(errors.ERR_STALE_CALL_VERSION, 412,
                              "expected_service_call_version does not match the live version.")

    offer_distance = geo.haversine_miles(
        provider["current_lat"], provider["current_lng"],
        call["breakdown_lat"], call["breakdown_lng"])
    eta = geo.eta_minutes(offer_distance)

    offer = {
        "service_call_id": call_id,
        "provider_id": provider_id,
        "status": "OFFERED",
        "eta_minutes": eta,
        "offer_distance_miles": offer_distance,
    }
    db.stamp_create(offer)
    db.dispatch_offers[offer["id"]] = offer

    call["dispatch_attempts"] += 1
    db.touch(call)
    return object_response(serializers.dispatch_offer(offer), 201)


@bp.route("/service-calls/<call_id>/offers", methods=["GET"])
def list_offers(call_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator", "Member", "ServiceProvider"})
    call = db.service_calls.get(call_id)
    if call is None:
        raise errors.not_found("Service call not found.")
    limit, offset = validation.parse_pagination()
    status = request.args.get("status")
    records = [o for o in db.dispatch_offers.values() if o["service_call_id"] == call_id]
    if status is not None:
        records = [o for o in records if o["status"] == status]
    page, total = sort_and_window(records, limit, offset)
    return array_response([serializers.dispatch_offer(o) for o in page],
                          limit, offset, total, 200)


@bp.route("/service-calls/<call_id>/bay-reservations", methods=["GET"])
def list_call_reservations(call_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator", "Member"})
    call = db.service_calls.get(call_id)
    if call is None:
        raise errors.not_found("Service call not found.")
    if ident.is_member and ident.user_id != call["member_id"]:
        raise errors.not_resource_owner("A member may only list its own call's reservations.")
    limit, offset = validation.parse_pagination()
    status = request.args.get("status")
    records = [r for r in db.bay_reservations.values() if r["service_call_id"] == call_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = sort_and_window(records, limit, offset)
    return array_response([serializers.bay_reservation(r) for r in page],
                          limit, offset, total, 200)


@bp.route("/service-calls/<call_id>/offers/<offer_id>/accept", methods=["POST"])
def accept_offer(call_id, offer_id):
    ident = authenticate()
    require_roles(ident, {"ServiceProvider"})
    call = db.service_calls.get(call_id)
    if call is None:
        raise errors.not_found("Service call not found.")
    offer = db.dispatch_offers.get(offer_id)
    if offer is None or offer["service_call_id"] != call_id:
        raise errors.not_found("Offer not found.")
    # ownership: acting provider must be the offer's provider
    if ident.user_id != offer["provider_id"]:
        raise errors.not_resource_owner("Only the offered provider may accept.")
    # state: offer OFFERED and parent call DISPATCHING
    if offer["status"] != "OFFERED" or call["status"] != "DISPATCHING":
        raise errors.invalid_state("Offer is not in an acceptable state.")

    provider = db.service_providers.get(offer["provider_id"])
    if provider is None:
        raise errors.not_found("Provider not found.")
    if provider["status"] != "AVAILABLE":
        raise errors.ApiError(errors.ERR_PROVIDER_UNAVAILABLE, 409,
                              "Provider is not AVAILABLE.")

    # CASCADE: offer -> ACCEPTED ; call -> ASSIGNED ; provider -> ON_JOB
    offer["status"] = "ACCEPTED"
    db.touch(offer)

    call["status"] = "ASSIGNED"
    call["assigned_provider_id"] = provider["id"]
    db.touch(call)

    provider["status"] = "ON_JOB"
    provider["active_call_id"] = call_id
    db.touch(provider)

    return object_response(serializers.dispatch_offer(offer), 200)


@bp.route("/service-calls/<call_id>/offers/<offer_id>/decline", methods=["POST"])
def decline_offer(call_id, offer_id):
    ident = authenticate()
    require_roles(ident, {"ServiceProvider"})
    call = db.service_calls.get(call_id)
    if call is None:
        raise errors.not_found("Service call not found.")
    offer = db.dispatch_offers.get(offer_id)
    if offer is None or offer["service_call_id"] != call_id:
        raise errors.not_found("Offer not found.")
    if ident.user_id != offer["provider_id"]:
        raise errors.not_resource_owner("Only the offered provider may decline.")
    if offer["status"] != "OFFERED":
        raise errors.invalid_state("Only an OFFERED offer may be declined.")
    offer["status"] = "DECLINED"
    db.touch(offer)
    # call remains DISPATCHING; provider untouched
    return object_response(serializers.dispatch_offer(offer), 200)


@bp.route("/service-calls/<call_id>/offers/<offer_id>/expire", methods=["POST"])
def expire_offer(call_id, offer_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator"})
    call = db.service_calls.get(call_id)
    if call is None:
        raise errors.not_found("Service call not found.")
    offer = db.dispatch_offers.get(offer_id)
    if offer is None or offer["service_call_id"] != call_id:
        raise errors.not_found("Offer not found.")
    if offer["status"] != "OFFERED":
        raise errors.invalid_state("Only an OFFERED offer may be expired.")
    offer["status"] = "EXPIRED"
    db.touch(offer)
    # call remains DISPATCHING; provider untouched
    return object_response(serializers.dispatch_offer(offer), 200)


# --------------------------------------------------------------------------
# Lifecycle: start / complete / abandon / cancel
# --------------------------------------------------------------------------

@bp.route("/service-calls/<call_id>/start", methods=["POST"])
def start_call(call_id):
    ident = authenticate()
    require_roles(ident, {"ServiceProvider"})
    call = db.service_calls.get(call_id)
    if call is None:
        raise errors.not_found("Service call not found.")
    if ident.user_id != call.get("assigned_provider_id"):
        raise errors.not_resource_owner("Only the assigned provider may start travel.")
    if call["status"] != "ASSIGNED":
        raise errors.invalid_state("start is only allowed from ASSIGNED.")
    call["status"] = "EN_ROUTE"
    db.touch(call)
    return object_response(serializers.service_call(call), 200)


@bp.route("/service-calls/<call_id>/complete", methods=["POST"])
def complete_call(call_id):
    ident = authenticate()
    require_roles(ident, {"ServiceProvider"})
    call = db.service_calls.get(call_id)
    if call is None:
        raise errors.not_found("Service call not found.")
    if ident.user_id != call.get("assigned_provider_id"):
        raise errors.not_resource_owner("Only the assigned provider may complete the job.")
    if call["status"] != "EN_ROUTE":
        raise errors.invalid_state("complete is only allowed from EN_ROUTE.")

    body = validation.get_body()
    final_towed = body.get("final_towed_miles")
    if final_towed is None:
        miles = call["tow_distance_miles"]
    else:
        if not validation.is_number(final_towed) or final_towed < 0:
            raise errors.invalid_request("final_towed_miles must be a number >= 0.")
        miles = final_towed

    member = db.members[call["member_id"]]
    plan = db.membership_plans[member["plan_id"]]

    # Annual-period rollover BEFORE reading the quota gate.
    now = clock.now()
    period_start = validation.parse_datetime(member["annual_period_start"], "annual_period_start")
    if now >= period_start + timedelta(days=365):
        member["annual_period_start"] = clock.iso(period_start + timedelta(days=365))
        member["services_used_this_year"] = 0
        db.touch(member)

    # Quota gate.
    if member["services_used_this_year"] >= plan["annual_service_limit"]:
        raise errors.ApiError(errors.ERR_ANNUAL_LIMIT_EXCEEDED, 409,
                              "Annual service limit reached.")

    # Cost reconciliation.
    final_cost = pricing.service_cost_cents(plan, call["service_type"], miles)
    call["final_towed_miles"] = miles
    call["final_cost_cents"] = final_cost
    call["member_out_of_pocket_cents"] = final_cost
    call["status"] = "COMPLETED"
    db.touch(call)

    member["services_used_this_year"] += 1
    member["outstanding_balance_cents"] += final_cost
    db.touch(member)

    provider = db.service_providers.get(call["assigned_provider_id"])
    if provider is not None:
        provider["status"] = "AVAILABLE"
        provider["active_call_id"] = None
        db.touch(provider)

    return object_response(serializers.service_call(call), 200)


@bp.route("/service-calls/<call_id>/abandon", methods=["POST"])
def abandon_call(call_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator"})
    call = db.service_calls.get(call_id)
    if call is None:
        raise errors.not_found("Service call not found.")
    if call["status"] != "DISPATCHING":
        raise errors.invalid_state("abandon is only allowed from DISPATCHING.")
    has_live = any(o["service_call_id"] == call_id and o["status"] == "OFFERED"
                   for o in db.dispatch_offers.values())
    if has_live:
        raise errors.invalid_state("Cannot abandon while a live offer is outstanding.")
    if call["dispatch_attempts"] < 1:
        raise errors.invalid_state("Cannot abandon before at least one dispatch attempt.")
    call["status"] = "UNFULFILLED"
    db.touch(call)
    return object_response(serializers.service_call(call), 200)


@bp.route("/service-calls/<call_id>/cancel", methods=["POST"])
def cancel_call(call_id):
    ident = authenticate()
    require_roles(ident, {"Member"})
    call = db.service_calls.get(call_id)
    if call is None:
        raise errors.not_found("Service call not found.")
    if ident.user_id != call["member_id"]:
        raise errors.not_resource_owner("A member may only cancel its own call.")
    if call["status"] not in ("DISPATCHING", "ASSIGNED"):
        raise errors.invalid_state("cancel is only allowed from DISPATCHING or ASSIGNED.")

    if call["status"] == "DISPATCHING":
        call["status"] = "CANCELLED"
        # conditional cascade: live offer -> EXPIRED
        for o in db.dispatch_offers.values():
            if o["service_call_id"] == call_id and o["status"] == "OFFERED":
                o["status"] = "EXPIRED"
                db.touch(o)
        db.touch(call)
    else:  # ASSIGNED
        provider_id = call["assigned_provider_id"]
        call["status"] = "CANCELLED"
        call["assigned_provider_id"] = None
        db.touch(call)
        provider = db.service_providers.get(provider_id)
        if provider is not None:
            provider["status"] = "AVAILABLE"
            provider["active_call_id"] = None
            db.touch(provider)

    return object_response(serializers.service_call(call), 200)
