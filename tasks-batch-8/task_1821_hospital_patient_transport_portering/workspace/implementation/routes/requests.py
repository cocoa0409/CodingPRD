"""Transport request routes: creation, reads, close (cancel/supersede),
dispatch offers, offer respond, trip events, and delay records."""

from flask import Blueprint, request

from db import store, now
from errors import ApiError
from middleware import require_roles, forbidden
from response import ok, ok_list, public, public_list, sort_created, paginate
from services import (
    PRIORITIES, REQUIRED_EQUIPMENT, ISOLATION_PRECAUTIONS, CAUSE_CODES,
    ACTIVE_REQUEST_STATUSES, TERMINAL_REQUEST_STATUSES,
    TARGET_RESPONSE_MINUTES, PATIENT_MIN_SEPARATION_SECONDS,
    CONGESTION_SURCHARGE_PER_TRIP, CONGESTION_CAP,
    stamp_new, touch, travel_estimate, transporter_eligible, eligible_pool,
    select_asset, make_offer, release_offer_asset, pending_offer_for_request,
    auto_dispatch_eval, eval_posture, delay_record_exists, make_delay_record,
)
from util import (
    get_body, req_string, req_enum, opt_enum, opt_bool, opt_string, opt_datetime,
    parse_datetime, fmt, floor_minutes,
)

bp = Blueprint("requests", __name__)


def _not_found(what):
    raise ApiError("ERR_NOT_FOUND", 404, "{} not found".format(what))


def _get_request(request_id):
    r = store.requests.get(request_id)
    if r is None:
        _not_found("transport request")
    return r


def _filters(recs, params):
    out = list(recs)
    for param in params:
        v = request.args.get(param)
        if v is not None:
            out = [r for r in out if r.get(param) is not None and str(r.get(param)) == v]
    return out


# ---------------------------------------------------------------------------
# Create / read requests
# ---------------------------------------------------------------------------

@bp.post("/transport/requests")
def create_request():
    uid, role = require_roles("RequestingClinician")
    data = get_body()
    patient_ref = req_string(data, "patient_ref")
    origin = req_string(data, "origin_location_id")
    dest = req_string(data, "destination_location_id")
    priority = req_enum(data, "priority", PRIORITIES)
    required_equipment = req_enum(data, "required_equipment", REQUIRED_EQUIPMENT)
    oxygen = opt_bool(data, "oxygen_required", False)
    isolation = opt_enum(data, "isolation_precaution", ISOLATION_PRECAUTIONS, "NONE")
    spt = opt_datetime(data, "scheduled_pickup_time")
    deadline = opt_datetime(data, "appointment_deadline")

    # Tier 4: existence of referenced locations.
    if origin not in store.locations:
        _not_found("origin location")
    if dest not in store.locations:
        _not_found("destination location")

    # Tier 9: business temporal guards.
    n = now()
    if spt is not None and spt < n:
        raise ApiError("ERR_SCHEDULE_IN_PAST", 422, "scheduled_pickup_time is in the past")
    if deadline is not None and deadline < n:
        raise ApiError("ERR_SCHEDULE_IN_PAST", 422, "appointment_deadline is in the past")
    if spt is not None:
        for r in store.requests.values():
            if r["patient_ref"] != patient_ref or r["status"] in TERMINAL_REQUEST_STATUSES:
                continue
            if not r["scheduled_pickup_time"]:
                continue
            other = parse_datetime(r["scheduled_pickup_time"], "scheduled_pickup_time")
            if abs((spt - other).total_seconds()) < PATIENT_MIN_SEPARATION_SECONDS:
                raise ApiError("ERR_PATIENT_SCHEDULE_CONFLICT", 409,
                               "another non-terminal request for this patient is scheduled within 75 minutes")

    # Tier 10: duplicate active request.
    for r in store.requests.values():
        if (r["patient_ref"] == patient_ref
                and r["destination_location_id"] == dest
                and r["status"] in ACTIVE_REQUEST_STATUSES):
            raise ApiError("ERR_DUPLICATE_ACTIVE_REQUEST", 409,
                           "an active request already exists for this patient and destination")

    rec = stamp_new({
        "patient_ref": patient_ref,
        "origin_location_id": origin,
        "destination_location_id": dest,
        "priority": priority,
        "required_equipment": required_equipment,
        "oxygen_required": oxygen,
        "isolation_precaution": isolation,
        "scheduled_pickup_time": fmt(spt) if spt is not None else None,
        "appointment_deadline": fmt(deadline) if deadline is not None else None,
        "requested_by": uid,
        "status": "QUEUED",
        "sla_posture": "ON_TRACK",
        "escalation_count": 0,
        "decline_count": 0,
        "release_count": 0,
        "offer_seq_count": 0,
        "excluded_transporter_ids": [],
        "assigned_transporter_id": None,
        "assigned_equipment_id": None,
        "duplicate_of_id": None,
        "committed_eta_minutes": None,
        "response_minutes": None,
        "at_pickup_at": None,
        "picked_up_at": None,
        "completed_at": None,
        "closed_at": None,
        "cancel_reason": None,
    })
    store.requests[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/transport/requests")
def list_requests():
    require_roles("RequestingClinician", "TransportDispatcher", "TransportSupervisor", "Transporter")
    recs = _filters(sort_created(store.requests.values()), [
        "status", "priority", "sla_posture", "origin_location_id",
        "destination_location_id", "assigned_transporter_id",
        "assigned_equipment_id", "duplicate_of_id",
    ])
    page, meta = paginate(recs)
    return ok_list(public_list(page), meta)


@bp.get("/transport/requests/<request_id>")
def get_request(request_id):
    require_roles("RequestingClinician", "TransportDispatcher", "TransportSupervisor", "Transporter")
    return ok(public(_get_request(request_id)))


# ---------------------------------------------------------------------------
# Close (CANCEL / SUPERSEDE)
# ---------------------------------------------------------------------------

@bp.post("/transport/requests/<request_id>/close")
def close_request(request_id):
    uid, role = require_roles("RequestingClinician", "TransportDispatcher", "TransportSupervisor")
    data = get_body()
    action = req_enum(data, "action", {"CANCEL", "SUPERSEDE"})
    dup_id = data.get("duplicate_of_id")
    reason = opt_string(data, "reason")
    if action == "SUPERSEDE":
        if not isinstance(dup_id, str) or not dup_id:
            raise ApiError("ERR_VALIDATION", 400, "duplicate_of_id is required for SUPERSEDE")
        if role != "TransportDispatcher":
            forbidden("supersede-as-duplicate is dispatcher-only")

    r = _get_request(request_id)
    target = None
    if action == "SUPERSEDE":
        target = store.requests.get(dup_id)
        if target is None:
            _not_found("duplicate target request")

    # Ownership (tier 2, entity-dependent): clinicians cancel only their own.
    if role == "RequestingClinician" and r["requested_by"] != uid:
        forbidden("clinicians may cancel only their own requests")

    # Tier 6: entity state.
    if r["status"] in TERMINAL_REQUEST_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "request is already in a terminal state")
    if action == "CANCEL":
        if r["status"] == "IN_TRANSIT":
            raise ApiError("ERR_INVALID_REQUEST_STATE", 409, "cannot cancel a request that is IN_TRANSIT")
        if role == "RequestingClinician" and r["status"] != "QUEUED":
            forbidden("clinicians may cancel only while the request is QUEUED")
    else:
        if r["status"] != "QUEUED":
            raise ApiError("ERR_INVALID_REQUEST_STATE", 409, "only a QUEUED request can be superseded")
        # Tier 8: supersede target must qualify.
        if (target["id"] == r["id"] or target["status"] != "QUEUED"
                or target["patient_ref"] != r["patient_ref"]):
            raise ApiError("ERR_NOT_DUPLICATE", 409,
                           "duplicate target must be a different QUEUED request for the same patient")

    freed_asset = None
    po = pending_offer_for_request(r["id"])
    if po is not None:
        po["status"] = "SUPERSEDED"
        touch(po)
        freed_asset = release_offer_asset(po)

    if action == "CANCEL":
        if r["status"] in ("ASSIGNED", "AT_PICKUP"):
            # The assigned asset was never IN_USE: release without cleaning.
            if r["assigned_equipment_id"]:
                a = store.equipment_assets.get(r["assigned_equipment_id"])
                if a is not None and a["status"] == "RESERVED":
                    a["status"] = "AVAILABLE"
                    touch(a)
                    freed_asset = a
            r["assigned_transporter_id"] = None
        r["status"] = "CANCELLED"
        r["cancel_reason"] = reason
    else:
        r["duplicate_of_id"] = dup_id
        r["status"] = "SUPERSEDED"
        if reason is not None:
            r["cancel_reason"] = reason

    r["closed_at"] = fmt(now())
    touch(r)
    if freed_asset is not None:
        auto_dispatch_eval(freed_asset)
    return ok(public(r))


# ---------------------------------------------------------------------------
# Dispatch offers
# ---------------------------------------------------------------------------

@bp.post("/transport/requests/<request_id>/offers")
def create_offer(request_id):
    uid, role = require_roles("TransportDispatcher")
    data = get_body()
    erv = data.get("expected_request_version")
    if erv is None or isinstance(erv, bool) or not isinstance(erv, int):
        raise ApiError("ERR_VALIDATION", 400, "expected_request_version is required and must be an integer")
    tid = data.get("transporter_id")
    if tid is not None and not isinstance(tid, str):
        raise ApiError("ERR_VALIDATION", 400, "transporter_id must be a string")

    r = _get_request(request_id)
    t = None
    if tid is not None:
        t = store.transporters.get(tid)
        if t is None:
            _not_found("transporter")

    # Tier 5: optimistic concurrency — outranks the state tier.
    if erv != r["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_request_version does not match the request version")

    # Tier 6: state.
    if r["status"] != "QUEUED":
        raise ApiError("ERR_INVALID_REQUEST_STATE", 409, "offers can only be created on a QUEUED request")

    if t is not None:
        # Tier 7: isolation safety gate (manual selection only).
        if r["isolation_precaution"] != "NONE" and not t["isolation_certified"]:
            raise ApiError("ERR_ISOLATION_CAPABILITY_MISMATCH", 422,
                           "transporter is not isolation certified")
        # Tier 10: remaining eligibility.
        if not transporter_eligible(t, r, check_isolation=False):
            raise ApiError("ERR_TRANSPORTER_INELIGIBLE", 422, "transporter is not eligible for this request")
        est = travel_estimate(t, r)  # raises ERR_NO_TRAVEL_EDGE
    else:
        pool = eligible_pool(r)
        if not pool:
            raise ApiError("ERR_NO_ELIGIBLE_TRANSPORTER", 422, "no eligible transporter available")
        t = pool[0]
        est = travel_estimate(t, r)  # raises ERR_NO_TRAVEL_EDGE (loaded leg)

    # Equipment availability counts the asset that superseding the current
    # PENDING offer is about to release (it is re-selectable by the new offer).
    po = pending_offer_for_request(r["id"])
    asset = None
    if r["required_equipment"] != "PORTER_ONLY":
        extra = None
        if po is not None and po.get("_reserved_asset_id"):
            pa = store.equipment_assets.get(po["_reserved_asset_id"])
            if (pa is not None and pa["status"] == "RESERVED"
                    and pa["equipment_type"] == r["required_equipment"]):
                extra = pa
        asset = select_asset(r["required_equipment"], extra=extra)
        if asset is None:
            raise ApiError("ERR_NO_AVAILABLE_EQUIPMENT", 422,
                           "no AVAILABLE equipment asset of the required type")

    # Supersede any existing PENDING offer; its asset returns to AVAILABLE and
    # deliberately NO auto-dispatch eval runs on this path.
    if po is not None:
        po["status"] = "SUPERSEDED"
        touch(po)
        release_offer_asset(po)

    offer = make_offer(r, t, asset)
    offer["estimated_travel_minutes"] = est
    return ok(public(offer), 201)


@bp.get("/transport/requests/<request_id>/offers")
def list_request_offers(request_id):
    require_roles("TransportDispatcher", "TransportSupervisor")
    r = _get_request(request_id)
    recs = [o for o in store.offers.values() if o["transport_request_id"] == r["id"]]
    recs = _filters(sort_created(recs), ["status"])
    page, meta = paginate(recs)
    return ok_list(public_list(page), meta)


@bp.post("/transport/dispatch-offers/<offer_id>/respond")
def respond_offer(offer_id):
    uid, role = require_roles("Transporter")
    data = get_body()
    decision = req_enum(data, "decision", {"ACCEPT", "DECLINE"})
    o = store.offers.get(offer_id)
    if o is None:
        _not_found("dispatch offer")
    # Ownership (tier 2): only the addressed transporter may respond.
    if o["transporter_id"] != uid:
        forbidden("only the addressed transporter may respond to this offer")
    if o["status"] != "PENDING":
        raise ApiError("ERR_INVALID_OFFER_STATE", 409, "offer is not PENDING")
    r = store.requests[o["transport_request_id"]]

    if decision == "ACCEPT":
        if r["status"] != "QUEUED":
            raise ApiError("ERR_INVALID_REQUEST_STATE", 409, "request is no longer QUEUED")
        t = store.transporters.get(uid)
        if t is None or t["status"] != "ON_SHIFT":
            raise ApiError("ERR_INVALID_TRANSPORTER_STATE", 409, "transporter is not ON_SHIFT")
        o["status"] = "ACCEPTED"
        o["responded_at"] = fmt(now())
        touch(o)
        in_transit = sum(1 for x in store.requests.values() if x["status"] == "IN_TRANSIT")
        r["assigned_transporter_id"] = uid
        r["committed_eta_minutes"] = (o["estimated_travel_minutes"]
                                      + CONGESTION_SURCHARGE_PER_TRIP * min(in_transit, CONGESTION_CAP))
        r["status"] = "ASSIGNED"
        touch(r)
    else:
        o["status"] = "DECLINED"
        o["responded_at"] = fmt(now())
        touch(o)
        r["decline_count"] += 1
        if uid not in r["excluded_transporter_ids"]:
            r["excluded_transporter_ids"].append(uid)
        touch(r)
        freed = release_offer_asset(o)
        if freed is not None:
            auto_dispatch_eval(freed)
    return ok(public(o))


# ---------------------------------------------------------------------------
# Trip events
# ---------------------------------------------------------------------------

@bp.post("/transport/requests/<request_id>/trip-events")
def trip_event(request_id):
    uid, role = require_roles("Transporter", "TransportDispatcher")
    data = get_body()
    event = req_enum(data, "event", {"ARRIVE_PICKUP", "PICKUP", "COMPLETE", "RELEASE"})
    cause = data.get("cause_code")
    if cause is not None and cause not in CAUSE_CODES:
        raise ApiError("ERR_VALIDATION", 400, "invalid cause_code")

    r = _get_request(request_id)

    # Ownership (tier 2): trip events belong to the assigned transporter,
    # except that a dispatcher may force a release.
    if event == "RELEASE":
        if role == "Transporter" and r["assigned_transporter_id"] != uid:
            forbidden("only the assigned transporter or a dispatcher may release the trip")
    else:
        if role != "Transporter" or r["assigned_transporter_id"] != uid:
            forbidden("only the assigned transporter may post this trip event")

    # Tier 6: state.
    if r["status"] in TERMINAL_REQUEST_STATUSES:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "request is already in a terminal state")
    required_state = {"ARRIVE_PICKUP": "ASSIGNED", "PICKUP": "AT_PICKUP",
                      "COMPLETE": "IN_TRANSIT", "RELEASE": "ASSIGNED"}[event]
    if r["status"] != required_state:
        raise ApiError("ERR_INVALID_REQUEST_STATE", 409,
                       "event {} is not allowed from status {}".format(event, r["status"]))

    n = now()
    if event == "ARRIVE_PICKUP":
        r["at_pickup_at"] = fmt(n)
        r["response_minutes"] = floor_minutes(n - parse_datetime(r["created_at"], "created_at"))
        # Final freeze of the SLA posture.
        target = TARGET_RESPONSE_MINUTES[r["priority"]]
        r["sla_posture"] = eval_posture(r["response_minutes"], target)
        r["status"] = "AT_PICKUP"
        touch(r)

    elif event == "PICKUP":
        asset = None
        if r["assigned_equipment_id"]:
            asset = store.equipment_assets.get(r["assigned_equipment_id"])
            if asset is None or asset["status"] != "RESERVED":
                raise ApiError("ERR_INVALID_ASSET_STATE", 409, "assigned asset is not RESERVED")
        r["picked_up_at"] = fmt(n)
        r["status"] = "IN_TRANSIT"
        if asset is not None:
            asset["status"] = "IN_USE"
            touch(asset)
        touch(r)

    elif event == "COMPLETE":
        assigned_tid = r["assigned_transporter_id"]
        r["completed_at"] = fmt(n)
        r["assigned_transporter_id"] = None
        r["status"] = "COMPLETED"
        if assigned_tid:
            t = store.transporters.get(assigned_tid)
            if t is not None:
                t["current_location_id"] = r["destination_location_id"]
                touch(t)
        asset = None
        if r["assigned_equipment_id"]:
            asset = store.equipment_assets.get(r["assigned_equipment_id"])
        if asset is not None:
            asset["status"] = "AWAITING_CLEANING"
            asset["current_location_id"] = r["destination_location_id"]
            if r["isolation_precaution"] != "NONE":
                asset["isolation_contaminated"] = True
            touch(asset)
            task = stamp_new({
                "equipment_asset_id": asset["id"],
                "transport_request_id": r["id"],
                "task_type": "DEEP" if r["isolation_precaution"] != "NONE" else "STANDARD",
                "status": "PENDING",
                "started_at": None,
                "finished_at": None,
                "verified_at": None,
                "performed_by": None,
                "verified_by": None,
                "rework_count": 0,
            })
            store.cleaning_tasks[task["id"]] = task
        # Delay records.
        if r["appointment_deadline"]:
            deadline = parse_datetime(r["appointment_deadline"], "appointment_deadline")
            if n > deadline and not delay_record_exists(r["id"], "APPOINTMENT_LATE"):
                make_delay_record(r, "APPOINTMENT_LATE", floor_minutes(n - deadline),
                                  cause if cause is not None else "OTHER", "COMPLETION")
        if r["response_minutes"] is not None:
            target = TARGET_RESPONSE_MINUTES[r["priority"]]
            if r["response_minutes"] > target and not delay_record_exists(r["id"], "SLA_BREACH"):
                make_delay_record(r, "SLA_BREACH", r["response_minutes"] - target,
                                  "SYSTEM", "COMPLETION")
        touch(r)

    else:  # RELEASE
        holder = r["assigned_transporter_id"]
        r["assigned_transporter_id"] = None
        r["release_count"] += 1
        if holder and holder not in r["excluded_transporter_ids"]:
            r["excluded_transporter_ids"].append(holder)
        r["status"] = "QUEUED"
        freed = None
        if r["assigned_equipment_id"]:
            a = store.equipment_assets.get(r["assigned_equipment_id"])
            if a is not None and a["status"] == "RESERVED":
                a["status"] = "AVAILABLE"
                touch(a)
                freed = a
        touch(r)
        if freed is not None:
            auto_dispatch_eval(freed)

    return ok(public(r))


# ---------------------------------------------------------------------------
# Delay records
# ---------------------------------------------------------------------------

@bp.get("/transport/requests/<request_id>/delay-records")
def list_delay_records(request_id):
    require_roles("TransportDispatcher", "TransportSupervisor")
    r = _get_request(request_id)
    recs = [d for d in store.delay_records.values() if d["transport_request_id"] == r["id"]]
    recs = sort_created(recs)
    page, meta = paginate(recs)
    return ok_list(public_list(page), meta)
