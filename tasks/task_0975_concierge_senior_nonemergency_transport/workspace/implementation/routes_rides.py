"""Ride booking, cancellation, dispatch, execution events, and ride log."""

from datetime import timedelta

from flask import request

from core import (
    db, get_caller, require_role, get_body, ok, parse_pagination, paginate,
    field_str, field_int, field_enum, field_datetime, stamp_new, touch,
    sort_created, now, today, ApiError, err_not_found, err_forbidden,
    err_invalid, family_member_of, check_family_active, err_family_access,
)
from domain import (
    ser_ride, ser_ride_event, ser_assignment, active_rate_card, compute_fare,
    cancellation_fee, append_event, offered_assignment_for_ride,
    accepted_assignment_for_ride, expire_offered_assignments_for_ride,
    release_accepted_assignment_for_ride, select_driver, posture_complete,
    driver_current_load, driver_has_overlap, billing_hold_active,
    suspend_client_cascade, OFFER_TIMEOUT_MINUTES, NO_SHOW_WAIT_MINUTES,
    NO_SHOW_STRIKE_LIMIT,
)
from routes_standing import _booking_gates, KINDS

EXECUTION_EVENTS = {
    "EN_ROUTE", "ARRIVED", "WAIT_STARTED", "WAIT_ENDED",
    "SERVICE_STARTED", "COMPLETE", "NO_SHOW",
}
CANCELLABLE_STATUSES = {"SCHEDULED", "DISPATCHING", "ASSIGNED", "EN_ROUTE", "ARRIVED"}


def _ride_or_404(rid):
    ride = db.rides.get(rid)
    if ride is None:
        raise err_not_found("Ride not found")
    return ride


def _client_scoped_ride_access(caller, ride):
    """Ownership for read endpoints on a loaded ride (revoked members fail here)."""
    if caller.role == "Client":
        if ride["client_id"] != caller.user_id:
            raise err_forbidden("Client may only access their own rides")
    elif caller.role == "FamilyMember":
        member = family_member_of(caller)
        if member is None or member["status"] != "ACTIVE":
            raise err_forbidden("Family membership not active")
        if member["client_id"] != ride["client_id"]:
            raise err_forbidden("Family member may only access their own client's rides")


def _client_match_ownership(caller, client_id):
    """Stage-4 ownership only (client match). Membership-status failures are
    left for the stage-5 tier check (ERR_FAMILY_ACCESS_INSUFFICIENT)."""
    if caller.role == "Client":
        if caller.user_id != client_id:
            raise err_forbidden("Client may only act on their own resources")
    elif caller.role == "FamilyMember":
        member = family_member_of(caller)
        if member is None:
            raise err_forbidden("Family member not recognized")
        if member["client_id"] != client_id:
            raise err_forbidden("Family member may only act on their own client's resources")


def register(app):

    @app.route("/rides", methods=["POST"])
    def create_ride():
        body = get_body()
        client_id = field_str(body, "client_id", required=True)
        kind = field_enum(body, "kind", KINDS, required=True)
        pickup = field_datetime(body, "scheduled_pickup_at", required=True)
        est_dur = field_int(body, "estimated_duration_minutes", required=True, minimum=0)
        est_miles = field_int(body, "estimated_distance_miles", required=True, minimum=0)
        origin_zone = field_str(body, "origin_zone", required=True)
        booked_by = field_str(body, "booked_by_family_member_id")
        linked_return = field_str(body, "linked_return_ride_id")
        caller = get_caller()
        require_role(caller, {"Client", "FamilyMember", "Coordinator"})
        client, service_class = _booking_gates(caller, body, client_id, booked_by)
        # 6. existence: linked_return_ride_id
        linked = None
        if linked_return is not None:
            linked = db.rides.get(linked_return)
            if linked is None:
                raise err_not_found("linked_return_ride_id not found")
        # 12. referential: return-leg link
        if linked is not None:
            if (
                linked["client_id"] != client_id
                or linked["kind"] != "APPOINTMENT"
                or linked["status"] != "SCHEDULED"
                or linked["linked_return_ride_id"] is not None
            ):
                raise ApiError(
                    "ERR_RETURN_LINK_MISMATCH", 409,
                    "linked_return_ride_id must target a SCHEDULED APPOINTMENT ride "
                    "of the same client with no return link of its own",
                )
        # 12. referential: family booker belongs to this client
        if booked_by is not None:
            member = db.family_members[booked_by]
            if member["client_id"] != client_id:
                raise ApiError(
                    "ERR_FAMILY_CLIENT_MISMATCH", 409,
                    "booked_by_family_member_id belongs to a different client",
                )
        # 13. fiscal gates
        card = active_rate_card(service_class, pickup.date())
        if card is None:
            raise ApiError(
                "ERR_RATE_CARD_NOT_ACTIVE", 409,
                "No ACTIVE rate card covers the derived service class at pickup",
            )
        if billing_hold_active(client):
            raise ApiError(
                "ERR_BILLING_HOLD", 402,
                "Client overdue receivables are at or above the billing hold limit",
            )
        requires_wav = client["mobility_aid"] == "POWER_WHEELCHAIR"
        ride = {
            "client_id": client_id,
            "standing_ride_id": None,
            "booked_by_family_member_id": booked_by,
            "linked_return_ride_id": linked_return,
            "kind": kind,
            "origin_zone": origin_zone,
            "scheduled_pickup_at": pickup,
            "estimated_duration_minutes": est_dur,
            "estimated_distance_miles": est_miles,
            "requires_wav": requires_wav,
            "service_class": service_class,
            "assist_level": client["assist_level_default"],
            "status": "SCHEDULED",
            "dispatch_round": 0,
            "excluded_driver_ids": [],
            "assigned_driver_id": None,
            "en_route_at": None,
            "arrived_at": None,
            "wait_minutes": 0,
            "service_minutes": None,
            "actual_distance_miles": None,
            "quoted_fare_cents": None,
            "final_fare_cents": None,
            "cancellation_fee_cents": 0,
            "cancel_reason": None,
            "cancelled_by_role": None,
            "no_show_fee_cents": 0,
            "_open_wait_started_at": None,
            "_service_started_at": None,
            "_rate_card_id": card["id"],
        }
        fare, _min_adj, _bw = compute_fare(card, est_dur, est_miles, 0, pickup, service_class)
        ride["quoted_fare_cents"] = fare
        stamp_new(ride)
        db.rides[ride["id"]] = ride
        append_event(ride, "CREATED", caller.role, caller.user_id)
        return ok(ser_ride(ride), status=201)

    @app.route("/rides/<rid>", methods=["GET"])
    def get_ride(rid):
        caller = get_caller()
        require_role(
            caller, {"Client", "FamilyMember", "Coordinator", "Driver", "BillingAdmin"}
        )
        ride = _ride_or_404(rid)
        if caller.role == "Driver":
            if ride["assigned_driver_id"] != caller.user_id:
                raise err_forbidden("Driver may only access their own rides")
        else:
            _client_scoped_ride_access(caller, ride)
        return ok(ser_ride(ride))

    @app.route("/rides", methods=["GET"])
    def list_rides():
        caller = get_caller()
        require_role(
            caller, {"Client", "FamilyMember", "Coordinator", "Driver", "BillingAdmin"}
        )
        limit, offset = parse_pagination()
        items = sort_created(db.rides.values())
        if caller.role == "Client":
            items = [r for r in items if r["client_id"] == caller.user_id]
        elif caller.role == "FamilyMember":
            member = family_member_of(caller)
            if member is None or member["status"] != "ACTIVE":
                raise err_forbidden("Family membership not active")
            items = [r for r in items if r["client_id"] == member["client_id"]]
        elif caller.role == "Driver":
            items = [r for r in items if r["assigned_driver_id"] == caller.user_id]
        for param in (
            "client_id", "assigned_driver_id", "standing_ride_id",
            "booked_by_family_member_id", "linked_return_ride_id", "status",
        ):
            val = request.args.get(param)
            if val is not None:
                items = [r for r in items if r.get(param) == val]
        page, meta = paginate(items, limit, offset)
        return ok([ser_ride(r) for r in page], response_type="array", pagination=meta)

    @app.route("/rides/<rid>/cancel", methods=["POST"])
    def cancel_ride(rid):
        body = get_body()
        cancel_note = field_str(body, "cancel_note")
        caller = get_caller()
        require_role(caller, {"Client", "FamilyMember", "Coordinator"})
        ride = _ride_or_404(rid)
        if caller.role in ("Client", "FamilyMember"):
            _client_match_ownership(caller, ride["client_id"])
        if caller.role == "FamilyMember":
            member = check_family_active(caller)
            if member["access_level"] not in ("BOOK_FOR_CLIENT", "BILLING_PAYER"):
                raise err_family_access(
                    "Family member access tier does not permit cancellation"
                )
        if ride["status"] not in CANCELLABLE_STATUSES:
            raise ApiError(
                "ERR_RIDE_NOT_CANCELLABLE", 409,
                f"Ride cannot be cancelled from status {ride['status']}",
            )
        # tiered fee against the pickup's rate card
        from billing import ride_rate_card
        card = ride_rate_card(ride)
        fee = cancellation_fee(card, ride["scheduled_pickup_at"]) if card else 0
        prior_status = ride["status"]
        if prior_status == "DISPATCHING":
            expire_offered_assignments_for_ride(ride)
        elif prior_status in ("ASSIGNED", "EN_ROUTE", "ARRIVED"):
            release_accepted_assignment_for_ride(ride, "RIDE_CANCELLED")
        ride["status"] = "CANCELLED"
        ride["cancel_reason"] = "CUSTOMER"
        ride["cancellation_fee_cents"] = fee
        ride["cancelled_by_role"] = caller.role
        touch(ride)
        append_event(ride, "CANCELLED", caller.role, caller.user_id, note=cancel_note)
        return ok(ser_ride(ride))

    @app.route("/rides/<rid>/dispatch", methods=["POST"])
    def dispatch_ride(rid):
        get_body()
        caller = get_caller()
        require_role(caller, {"Coordinator"})
        ride = _ride_or_404(rid)
        if ride["status"] not in ("SCHEDULED", "DISPATCHING"):
            raise ApiError(
                "ERR_RIDE_NOT_DISPATCHABLE", 409,
                f"Ride cannot be dispatched from status {ride['status']}",
            )
        if offered_assignment_for_ride(ride) is not None:
            raise ApiError(
                "ERR_DUPLICATE_OFFER", 409,
                "An OFFERED assignment is still live for this ride",
            )
        ride["status"] = "DISPATCHING"
        ride["dispatch_round"] += 1
        driver = select_driver(ride)
        if driver is None:
            touch(ride)
            return ok(None)
        offer_time = now()
        assignment = {
            "ride_id": ride["id"],
            "driver_id": driver["id"],
            "round": ride["dispatch_round"],
            "status": "OFFERED",
            "offered_at": offer_time,
            "offer_expires_at": offer_time + timedelta(minutes=OFFER_TIMEOUT_MINUTES),
            "responded_at": None,
            "decline_reason": None,
            "release_reason": None,
            "matched_by": "COORDINATOR",
            "matched_by_user_id": caller.user_id,
        }
        stamp_new(assignment)
        db.assignments[assignment["id"]] = assignment
        touch(ride)
        append_event(ride, "DISPATCHED", caller.role, caller.user_id)
        append_event(ride, "OFFERED", caller.role, caller.user_id)
        return ok(ser_assignment(assignment))

    @app.route("/rides/<rid>/execution-events", methods=["POST"])
    def execution_event(rid):
        body = get_body()
        event_type = field_enum(body, "event_type", EXECUTION_EVENTS, required=True)
        note = field_str(body, "note")
        actual_miles = field_int(body, "actual_distance_miles", minimum=0)
        if event_type == "COMPLETE" and actual_miles is None:
            raise err_invalid("actual_distance_miles is required for COMPLETE")
        caller = get_caller()
        require_role(caller, {"Driver"})
        ride = _ride_or_404(rid)
        if ride["assigned_driver_id"] != caller.user_id:
            raise err_forbidden("Only the assigned driver may append execution events")
        status = ride["status"]

        def invalid():
            return ApiError(
                "ERR_EXECUTION_EVENT_INVALID", 409,
                f"Event {event_type} not permitted from ride status {status}",
            )

        open_wait = ride["_open_wait_started_at"] is not None
        now_ts = now()

        if event_type == "EN_ROUTE":
            if status != "ASSIGNED":
                raise invalid()
            ride["status"] = "EN_ROUTE"
            ride["en_route_at"] = now_ts
            touch(ride)
            append_event(ride, "EN_ROUTE", "Driver", caller.user_id, note=note)
        elif event_type == "ARRIVED":
            if status != "EN_ROUTE":
                raise invalid()
            ride["status"] = "ARRIVED"
            ride["arrived_at"] = now_ts
            touch(ride)
            append_event(ride, "ARRIVED", "Driver", caller.user_id, note=note)
        elif event_type == "WAIT_STARTED":
            if status not in ("ARRIVED", "IN_SERVICE") or open_wait:
                raise invalid()
            ride["_open_wait_started_at"] = now_ts
            append_event(ride, "WAIT_STARTED", "Driver", caller.user_id, note=note)
        elif event_type == "WAIT_ENDED":
            if status not in ("ARRIVED", "IN_SERVICE") or not open_wait:
                raise invalid()
            delta = now_ts - ride["_open_wait_started_at"]
            ride["wait_minutes"] += max(0, int(delta.total_seconds() // 60))
            ride["_open_wait_started_at"] = None
            touch(ride)
            append_event(ride, "WAIT_ENDED", "Driver", caller.user_id, note=note)
        elif event_type == "SERVICE_STARTED":
            if status != "ARRIVED" or open_wait:
                raise invalid()
            ride["status"] = "IN_SERVICE"
            ride["_service_started_at"] = now_ts
            touch(ride)
            append_event(ride, "SERVICE_STARTED", "Driver", caller.user_id, note=note)
        elif event_type == "COMPLETE":
            if status != "IN_SERVICE" or open_wait:
                raise invalid()
            started = ride["_service_started_at"]
            ride["service_minutes"] = max(
                0, int((now_ts - started).total_seconds() // 60)
            )
            ride["actual_distance_miles"] = actual_miles
            from billing import ride_rate_card
            card = ride_rate_card(ride)
            if card is not None:
                ride["_rate_card_id"] = card["id"]
                fare, _min_adj, _bw = compute_fare(
                    card, ride["service_minutes"], actual_miles,
                    ride["wait_minutes"], ride["scheduled_pickup_at"],
                    ride["service_class"],
                )
                ride["final_fare_cents"] = fare
            ride["status"] = "COMPLETED"
            touch(ride)
            append_event(ride, "COMPLETED", "Driver", caller.user_id, note=note)
        elif event_type == "NO_SHOW":
            if status != "ARRIVED":
                raise invalid()
            if now_ts < ride["arrived_at"] + timedelta(minutes=NO_SHOW_WAIT_MINUTES):
                raise ApiError(
                    "ERR_NO_SHOW_TOO_EARLY", 409,
                    "No-show grace period has not elapsed",
                )
            from billing import ride_rate_card
            card = ride_rate_card(ride)
            ride["no_show_fee_cents"] = card["minimum_charge_cents"] if card else 0
            ride["status"] = "NO_SHOW"
            touch(ride)
            append_event(ride, "NO_SHOW_RECORDED", "Driver", caller.user_id, note=note)
            client = db.clients.get(ride["client_id"])
            if client is not None:
                client["no_show_count"] += 1
                touch(client)
                if (
                    client["no_show_count"] >= NO_SHOW_STRIKE_LIMIT
                    and client["status"] == "ACTIVE"
                ):
                    client["status"] = "SUSPENDED"
                    touch(client)
                    suspend_client_cascade(client)
        return ok(ser_ride(ride))

    @app.route("/rides/<rid>/events", methods=["GET"])
    def ride_events(rid):
        caller = get_caller()
        require_role(caller, {"Client", "FamilyMember", "Coordinator", "BillingAdmin"})
        ride = _ride_or_404(rid)
        member = None
        if caller.role in ("Client", "FamilyMember"):
            _client_scoped_ride_access(caller, ride)
            if caller.role == "FamilyMember":
                member = family_member_of(caller)
        limit, offset = parse_pagination()
        events = [
            e for e in db.ride_events.values() if e["ride_id"] == rid
        ]
        if member is not None and not member["notify_on_ride_events"]:
            events = []
        events.sort(key=lambda e: (e["occurred_at"], e["created_at"], e["_seq"]))
        page, meta = paginate(events, limit, offset)
        return ok(
            [ser_ride_event(e) for e in page], response_type="array", pagination=meta
        )
