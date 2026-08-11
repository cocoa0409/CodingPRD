"""Standing ride series endpoints (recurring weekly rides)."""

from flask import request

from core import (
    db, get_caller, require_role, get_body, ok, parse_pagination, paginate,
    field_str, field_int, field_enum, field_date, stamp_new, touch, sort_created,
    today, ApiError, err_not_found, err_forbidden, family_member_of,
    check_family_active,
)
from domain import (
    ser_standing_ride, active_rate_card, next_occurrence, generate_occurrences,
    system_cancel_ride, billing_hold_active, WEEKDAY_MAP,
)

KINDS = {"GROCERY", "APPOINTMENT", "COMPANION_OUTING"}
SERIES_EVENTS = {"PAUSE", "RESUME", "END"}


def _series_or_404(sid):
    series = db.standing_rides.get(sid)
    if series is None:
        raise err_not_found("Standing ride not found")
    return series


def _booking_gates(caller, body, client_id, booked_by_id):
    """Shared booking pipeline for rides and standing rides (stages 4-13).

    Returns (client, service_class). Raises appropriate ApiErrors.
    """
    # 4. ownership
    if caller.role == "Client":
        if caller.user_id != client_id:
            raise err_forbidden("Client may only book for themselves")
    elif caller.role == "FamilyMember":
        member = family_member_of(caller)
        if member is None:
            raise err_forbidden("Family member not recognized")
        if member["client_id"] != client_id:
            raise err_forbidden("Family member may only book for their own client")
    # 5. family tier
    if caller.role == "FamilyMember":
        member = check_family_active(caller)
        if member["access_level"] not in ("BOOK_FOR_CLIENT", "BILLING_PAYER"):
            from core import err_family_access
            raise err_family_access(
                "Family member access tier does not permit booking"
            )
    # 6. existence
    client = db.clients.get(client_id)
    if client is None:
        raise err_not_found("Client not found")
    if booked_by_id is not None and booked_by_id not in db.family_members:
        raise err_not_found("booked_by_family_member_id not found")
    # 7. client-active gate
    if client["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CLIENT_SUSPENDED", 409,
            "Client is not ACTIVE",
        )
    # 12. referential: family booker must belong to this client
    if booked_by_id is not None:
        member = db.family_members[booked_by_id]
        if member["client_id"] != client_id:
            raise ApiError(
                "ERR_FAMILY_CLIENT_MISMATCH", 409,
                "booked_by_family_member_id belongs to a different client",
            )
    service_class = "WAV" if client["mobility_aid"] == "POWER_WHEELCHAIR" else "STANDARD"
    return client, service_class


def register(app):

    @app.route("/standing-rides", methods=["POST"])
    def create_standing_ride():
        body = get_body()
        client_id = field_str(body, "client_id", required=True)
        weekday = field_enum(body, "weekday", set(WEEKDAY_MAP.keys()), required=True)
        tod = field_int(
            body, "pickup_time_of_day_minutes", required=True, minimum=0, maximum=1439
        )
        kind = field_enum(body, "kind", KINDS, required=True)
        est_dur = field_int(body, "estimated_duration_minutes", required=True, minimum=0)
        est_miles = field_int(body, "estimated_distance_miles", required=True, minimum=0)
        origin_zone = field_str(body, "origin_zone", required=True)
        starts_on = field_date(body, "starts_on", required=True)
        ends_on = field_date(body, "ends_on", required=True)
        booked_by = field_str(body, "booked_by_family_member_id")
        caller = get_caller()
        require_role(caller, {"Coordinator", "Client", "FamilyMember"})
        client, service_class = _booking_gates(caller, body, client_id, booked_by)
        # 10. temporal window
        if ends_on < starts_on:
            raise ApiError(
                "ERR_STANDING_WINDOW_INVALID", 422,
                "ends_on must not be earlier than starts_on",
            )
        # 13. fiscal gates
        series_probe = {
            "weekday": weekday,
            "starts_on": starts_on,
            "ends_on": ends_on,
        }
        gate_date = next_occurrence(series_probe) or starts_on
        if active_rate_card(service_class, gate_date) is None:
            raise ApiError(
                "ERR_RATE_CARD_NOT_ACTIVE", 409,
                "No ACTIVE rate card covers the derived service class",
            )
        if billing_hold_active(client):
            raise ApiError(
                "ERR_BILLING_HOLD", 402,
                "Client overdue receivables are at or above the billing hold limit",
            )
        series = {
            "client_id": client_id,
            "booked_by_family_member_id": booked_by,
            "weekday": weekday,
            "pickup_time_of_day_minutes": tod,
            "kind": kind,
            "estimated_duration_minutes": est_dur,
            "estimated_distance_miles": est_miles,
            "origin_zone": origin_zone,
            "starts_on": starts_on,
            "ends_on": ends_on,
            "status": "ACTIVE",
        }
        stamp_new(series)
        db.standing_rides[series["id"]] = series
        generate_occurrences(series, actor_role=caller.role, actor_user_id=caller.user_id)
        return ok(ser_standing_ride(series), status=201)

    @app.route("/standing-rides/<sid>", methods=["GET"])
    def get_standing_ride(sid):
        caller = get_caller()
        require_role(caller, {"Coordinator", "BillingAdmin", "Client", "FamilyMember"})
        series = _series_or_404(sid)
        if caller.role == "Client":
            if series["client_id"] != caller.user_id:
                raise err_forbidden("Client may only access their own series")
        elif caller.role == "FamilyMember":
            member = family_member_of(caller)
            if member is None or member["status"] != "ACTIVE":
                raise err_forbidden("Family membership not active")
            if member["client_id"] != series["client_id"]:
                raise err_forbidden("Family member may only access their own client")
        return ok(ser_standing_ride(series))

    @app.route("/standing-rides", methods=["GET"])
    def list_standing_rides():
        caller = get_caller()
        require_role(caller, {"Coordinator", "BillingAdmin"})
        limit, offset = parse_pagination()
        items = sort_created(db.standing_rides.values())
        client_id = request.args.get("client_id")
        booked_by = request.args.get("booked_by_family_member_id")
        status = request.args.get("status")
        if client_id is not None:
            items = [s for s in items if s["client_id"] == client_id]
        if booked_by is not None:
            items = [s for s in items if s["booked_by_family_member_id"] == booked_by]
        if status is not None:
            items = [s for s in items if s["status"] == status]
        page, meta = paginate(items, limit, offset)
        return ok(
            [ser_standing_ride(s) for s in page], response_type="array", pagination=meta
        )

    @app.route("/standing-rides/<sid>", methods=["PUT"])
    def put_standing_ride(sid):
        body = get_body()
        expected_version = field_int(body, "expected_standing_ride_version", required=True)
        weekday = field_enum(body, "weekday", set(WEEKDAY_MAP.keys()))
        tod = field_int(body, "pickup_time_of_day_minutes", minimum=0, maximum=1439)
        kind = field_enum(body, "kind", KINDS)
        est_dur = field_int(body, "estimated_duration_minutes", minimum=0)
        est_miles = field_int(body, "estimated_distance_miles", minimum=0)
        origin_zone = field_str(body, "origin_zone")
        starts_on = field_date(body, "starts_on")
        ends_on = field_date(body, "ends_on")
        caller = get_caller()
        require_role(caller, {"Coordinator"})
        series = _series_or_404(sid)
        if series["status"] == "ENDED":
            raise ApiError(
                "ERR_STANDING_STATUS_INVALID", 409,
                "An ENDED series cannot be edited",
            )
        if expected_version != series["version"]:
            raise ApiError(
                "ERR_STALE_VERSION", 412,
                "expected_standing_ride_version does not match the current version",
            )
        new_starts = starts_on if starts_on is not None else series["starts_on"]
        new_ends = ends_on if ends_on is not None else series["ends_on"]
        if new_ends < new_starts:
            raise ApiError(
                "ERR_STANDING_WINDOW_INVALID", 422,
                "ends_on must not be earlier than starts_on",
            )
        if weekday is not None:
            series["weekday"] = weekday
        if tod is not None:
            series["pickup_time_of_day_minutes"] = tod
        if kind is not None:
            series["kind"] = kind
        if est_dur is not None:
            series["estimated_duration_minutes"] = est_dur
        if est_miles is not None:
            series["estimated_distance_miles"] = est_miles
        if origin_zone is not None:
            series["origin_zone"] = origin_zone
        if starts_on is not None:
            series["starts_on"] = starts_on
        if ends_on is not None:
            series["ends_on"] = ends_on
        touch(series)
        # delete generated SCHEDULED rides with pickup date after today
        t = today()
        doomed = [
            r
            for r in db.rides.values()
            if r["standing_ride_id"] == sid
            and r["status"] == "SCHEDULED"
            and r["scheduled_pickup_at"].date() > t
        ]
        for r in doomed:
            del db.rides[r["id"]]
            for ev_id in [
                eid for eid, e in db.ride_events.items() if e["ride_id"] == r["id"]
            ]:
                del db.ride_events[ev_id]
        if series["status"] == "ACTIVE":
            generate_occurrences(
                series, actor_role=caller.role, actor_user_id=caller.user_id
            )
        return ok(ser_standing_ride(series))

    @app.route("/standing-rides/<sid>/status-events", methods=["POST"])
    def standing_status_event(sid):
        body = get_body()
        event_type = field_enum(body, "event_type", SERIES_EVENTS, required=True)
        caller = get_caller()
        require_role(caller, {"Coordinator", "Client"})
        series = _series_or_404(sid)
        if caller.role == "Client" and series["client_id"] != caller.user_id:
            raise err_forbidden("Client may only manage their own series")
        status = series["status"]

        def state_invalid():
            return ApiError(
                "ERR_STANDING_STATUS_INVALID", 409,
                f"Event {event_type} not permitted from series status {status}",
            )

        t = today()
        if event_type == "PAUSE":
            if status != "ACTIVE":
                raise state_invalid()
            series["status"] = "PAUSED"
            touch(series)
            for ride in list(db.rides.values()):
                if (
                    ride["standing_ride_id"] == sid
                    and ride["status"] == "SCHEDULED"
                    and ride["scheduled_pickup_at"].date() > t
                ):
                    system_cancel_ride(ride, "SERIES_PAUSED")
        elif event_type == "RESUME":
            if status != "PAUSED":
                raise state_invalid()
            series["status"] = "ACTIVE"
            touch(series)
            generate_occurrences(
                series, actor_role=caller.role, actor_user_id=caller.user_id
            )
        elif event_type == "END":
            if status not in ("ACTIVE", "PAUSED"):
                raise state_invalid()
            series["status"] = "ENDED"
            touch(series)
            for ride in list(db.rides.values()):
                if ride["standing_ride_id"] == sid and ride["status"] == "SCHEDULED":
                    system_cancel_ride(ride, "SERIES_ENDED")
        return ok(ser_standing_ride(series))
