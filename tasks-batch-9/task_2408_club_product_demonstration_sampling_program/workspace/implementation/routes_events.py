"""Demo events, the two-dimensional booking machine, assignments and reservations."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import domain as dm
import validation as v
from envelope import ok, ok_array, paginate
from errors import fail
from store import by_seq, db, iso, iso_now, new_row, now, touch

bp = Blueprint("events", __name__)

BOOKING_ACTIONS = ("SUBMIT", "REJECT", "APPROVE", "REVOKE_APPROVAL", "CLOSE_OUT", "CANCEL")

BOOKING_ACTION_ROLES = {
    "SUBMIT": ("Manufacturer", "ProgramAdmin"),
    "CANCEL": ("Manufacturer", "ClubOperations", "ProgramAdmin"),
    "REJECT": ("ClubOperations", "ProgramAdmin"),
    "APPROVE": ("ClubOperations", "ProgramAdmin"),
    "REVOKE_APPROVAL": ("ClubOperations", "ProgramAdmin"),
    "CLOSE_OUT": ("ClubOperations", "ProgramAdmin"),
}

BOOKING_FROM_STATES = {
    "SUBMIT": ("DRAFT",),
    "REJECT": ("SUBMITTED",),
    "APPROVE": ("SUBMITTED",),
    "REVOKE_APPROVAL": ("CONFIRMED",),
    "CLOSE_OUT": ("CONFIRMED",),
    "CANCEL": ("DRAFT", "SUBMITTED", "CONFIRMED"),
}

ASSIGNMENT_ACTIONS = ("CONFIRM", "CHECK_IN", "CHECK_OUT", "NO_SHOW", "RELEASE")

ASSIGNMENT_ACTION_ROLES = {
    "CONFIRM": ("Demonstrator", "ProgramAdmin"),
    "CHECK_IN": ("Demonstrator", "ProgramAdmin"),
    "CHECK_OUT": ("Demonstrator", "ProgramAdmin"),
    "NO_SHOW": ("StaffingCoordinator", "ProgramAdmin"),
    "RELEASE": ("StaffingCoordinator", "ProgramAdmin"),
}

ASSIGNMENT_FROM_STATES = {
    "CONFIRM": ("ASSIGNED",),
    "CHECK_IN": ("CONFIRMED",),
    "CHECK_OUT": ("CHECKED_IN",),
    "NO_SHOW": ("ASSIGNED", "CONFIRMED"),
    "RELEASE": ("ASSIGNED", "CONFIRMED"),
}


def _read_action(body, legal, roles_by_action, caller):
    """Rung 3 before rung 4: an illegal member defers to ERR_VALIDATION."""
    action = body.get("action")
    if not isinstance(action, str) or action not in legal:
        return None
    v.require_role(caller, roles_by_action[action])
    return action


# ===========================================================================
# DemoEvent
# ===========================================================================
@bp.post("/demo-events")
def create_demo_event():
    caller = v.guard(("ProgramAdmin", "Manufacturer"))
    body = v.json_body()
    manufacturer_id = v.req_string(body, "manufacturer_id")
    club_id = v.req_string(body, "club_id")
    product_id = v.req_string(body, "product_id")
    event_date = v.req_date(body, "event_date")
    day_part = v.req_enum(body, "day_part", calc.DAY_PARTS)
    requested = v.req_int(body, "requested_sample_cases", minimum=1, maximum=40)
    attribution = v.opt_int(body, "attribution_window_days", default=14, minimum=3, maximum=28)
    addons = v.opt_addon_services(body, "addon_services", default=[])

    man = dm.resolve(db.manufacturers, manufacturer_id, "ERR_MANUFACTURER_NOT_FOUND")
    club = dm.resolve(db.clubs, club_id, "ERR_CLUB_NOT_FOUND")
    product = dm.resolve(db.products, product_id, "ERR_PRODUCT_NOT_FOUND")
    v.check_ownership(caller, manufacturer_id=man["id"])

    if product["manufacturer_id"] != man["id"]:
        fail(
            "ERR_PRODUCT_MANUFACTURER_MISMATCH",
            "the product belongs to another manufacturer.",
        )
    if man["account_status"] == "SUSPENDED":
        fail("ERR_MANUFACTURER_SUSPENDED", "the manufacturer account is suspended.")

    row = new_row(
        manufacturer_id=man["id"],
        club_id=club["id"],
        product_id=product["id"],
        event_date=event_date.isoformat(),
        day_part=day_part,
        event_type="FOOD_SAMPLING" if product["requires_food_handling"] else "NON_FOOD_DEMO",
        requested_sample_cases=requested,
        allocated_sample_cases=0,
        pool_cases_used=0,
        reserve_cases_used=0,
        addon_services=addons,
        attribution_window_days=attribution,
        booking_status="DRAFT",
        staffing_status="UNSTAFFED",
        settlement_status="UNBILLED",
        event_window_start_utc=None,
        event_window_end_utc=None,
        required_support_count=0,
        no_show_recovery_open=False,
        cancellation_reason=None,
        submitted_at=None,
        approved_at=None,
    )
    dm.write_event_window(row)
    db.demo_events[row["id"]] = row
    return ok(dm.pub(row), 201)


@bp.get("/demo-events/<eid>")
def get_demo_event(eid):
    v.guard(
        (
            "ProgramAdmin",
            "ClubOperations",
            "Manufacturer",
            "StaffingCoordinator",
            "Demonstrator",
        )
    )
    row = dm.resolve(db.demo_events, eid, "ERR_DEMO_EVENT_NOT_FOUND")
    return ok(dm.pub(row))


@bp.get("/demo-events")
def list_demo_events():
    v.guard(
        (
            "ProgramAdmin",
            "ClubOperations",
            "Manufacturer",
            "StaffingCoordinator",
            "Demonstrator",
        )
    )
    limit, offset = v.pagination()
    rows = by_seq(list(db.demo_events.values()))
    for field in ("manufacturer_id", "club_id", "product_id"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    event_date = request.args.get("event_date")
    if event_date is not None:
        if calc.parse_date(event_date) is None:
            fail("ERR_VALIDATION", "event_date must be a YYYY-MM-DD date.")
        rows = [r for r in rows if r["event_date"] == event_date]
    booking_status = v.query_enum("booking_status", calc.BOOKING_STATUSES)
    if booking_status is not None:
        rows = [r for r in rows if r["booking_status"] == booking_status]
    staffing_status = v.query_enum("staffing_status", calc.STAFFING_STATUSES)
    if staffing_status is not None:
        rows = [r for r in rows if r["staffing_status"] == staffing_status]
    page, total = paginate(rows, limit, offset)
    return ok_array([dm.pub(r) for r in page], limit, offset, total)


@bp.patch("/demo-events/<eid>")
def patch_demo_event(eid):
    caller = v.guard(("ProgramAdmin", "Manufacturer"))
    body = v.json_body()
    event_date = v.opt_date(body, "event_date")
    day_part = v.opt_enum(body, "day_part", calc.DAY_PARTS)
    requested = v.opt_int(body, "requested_sample_cases", minimum=1, maximum=40)
    attribution = v.opt_int(body, "attribution_window_days", minimum=3, maximum=28)
    addons = v.opt_addon_services(body, "addon_services")
    row = dm.resolve(db.demo_events, eid, "ERR_DEMO_EVENT_NOT_FOUND")
    v.check_ownership(caller, manufacturer_id=row["manufacturer_id"])
    if row["booking_status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "only a DRAFT booking may be revised.")

    if event_date is not None:
        row["event_date"] = event_date.isoformat()
    if day_part is not None:
        row["day_part"] = day_part
    if requested is not None:
        row["requested_sample_cases"] = requested
    if attribution is not None:
        row["attribution_window_days"] = attribution
    if addons is not None:
        row["addon_services"] = addons
    if event_date is not None or day_part is not None:
        dm.write_event_window(row)
    touch(row)
    return ok(dm.pub(row))


@bp.post("/demo-events/<eid>/transitions")
def transition_demo_event(eid):
    caller = v.guard(("ProgramAdmin", "ClubOperations", "Manufacturer"))
    body = v.json_body()
    action = _read_action(body, BOOKING_ACTIONS, BOOKING_ACTION_ROLES, caller)
    if action is None:
        fail("ERR_VALIDATION", "action must be one of %s." % (list(BOOKING_ACTIONS),))
    v.opt_string(body, "reason")

    event = dm.resolve(db.demo_events, eid, "ERR_DEMO_EVENT_NOT_FOUND")
    state = event["booking_status"]

    # CANCEL from DRAFT or SUBMITTED is a manufacturer-side action only.
    if action == "CANCEL" and state in ("DRAFT", "SUBMITTED") and caller.role == "ClubOperations":
        fail("ERR_ROLE_NOT_PERMITTED", "ClubOperations may only cancel a CONFIRMED booking.")

    v.check_ownership(
        caller, manufacturer_id=event["manufacturer_id"], club_id=event["club_id"]
    )

    if state not in BOOKING_FROM_STATES[action]:
        fail("ERR_INVALID_STATE", "%s is not legal from booking_status %s." % (action, state))

    club = db.clubs[event["club_id"]]
    product = db.products[event["product_id"]]
    man = db.manufacturers[event["manufacturer_id"]]
    is_food = event["event_type"] == "FOOD_SAMPLING"

    if action == "REVOKE_APPROVAL":
        if event["staffing_status"] not in dm.RECOMPUTABLE_COVERAGE:
            fail("ERR_INVALID_STATE", "the staffing dimension has moved past coverage.")
        if any(
            s["shipment_status"] in calc.RECEIVED_SHIPMENT_STATUSES
            for s in dm.event_shipments(event["id"])
        ):
            fail("ERR_INVALID_STATE", "samples have already been received for this event.")

    if action == "CLOSE_OUT":
        if event["staffing_status"] != "EXECUTED":
            fail("ERR_EVENT_NOT_EXECUTED", "the event has not been executed.")
        for a in dm.event_assignments(event["id"]):
            if a["assignment_status"] in calc.HELD_ASSIGNMENT_STATUSES:
                fail("ERR_EVENT_NOT_EXECUTED", "an assignment is still open.")

    if action == "APPROVE" and is_food:
        if calc.parse_date(club["health_permit_expires_on"]) < calc.parse_date(
            event["event_date"]
        ):
            fail("ERR_CLUB_HEALTH_PERMIT_EXPIRED", "the club health permit has expired.")

    if action in ("SUBMIT", "APPROVE"):
        if product["manufacturer_id"] != event["manufacturer_id"]:
            fail(
                "ERR_PRODUCT_MANUFACTURER_MISMATCH",
                "the product belongs to another manufacturer.",
            )

    if action == "SUBMIT":
        clock_date = db.clock.date()
        event_day = calc.parse_date(event["event_date"])
        if event_day < clock_date + timedelta(days=calc.MIN_BOOKING_LEAD_DAYS):
            fail("ERR_BOOKING_LEAD_TIME_TOO_SHORT", "the booking lead time is too short.")
        if event_day > clock_date + timedelta(days=calc.MAX_BOOKING_HORIZON_DAYS):
            fail("ERR_BOOKING_HORIZON_EXCEEDED", "the booking horizon is exceeded.")

    if action == "APPROVE":
        if club["club_status"] == "CLOSED" or (
            club["club_status"] == "RESTRICTED" and is_food
        ):
            fail("ERR_CLUB_NOT_OPEN", "the host club is not accepting this approval.")
        scope = [
            e
            for e in db.demo_events.values()
            if e["club_id"] == event["club_id"]
            and e["event_date"] == event["event_date"]
            and e["booking_status"] in calc.LIVE_BOOKING_STATUSES
        ]
        if len(scope) >= club["daily_event_capacity"]:
            fail("ERR_CLUB_DAY_CAPACITY_FULL", "the club-day calendar is full.")
        if is_food:
            food_count = sum(1 for e in scope if e["event_type"] == "FOOD_SAMPLING")
            if food_count >= club["food_station_count"]:
                fail("ERR_FOOD_STATION_UNAVAILABLE", "no food sampling station is free.")
        category_count = 0
        for e in scope:
            other = db.products.get(e["product_id"])
            if other is not None and other["category"] == product["category"]:
                category_count += 1
        if category_count >= calc.MAX_EVENTS_PER_CATEGORY_PER_DAY:
            fail("ERR_CATEGORY_CALENDAR_CONFLICT", "the category calendar is full.")

    if man["account_status"] == "SUSPENDED":
        fail("ERR_MANUFACTURER_SUSPENDED", "the manufacturer account is suspended.")

    if action in ("SUBMIT", "APPROVE") and man["account_status"] != "ACTIVE":
        fail("ERR_MANUFACTURER_ON_CREDIT_HOLD", "the manufacturer account is on hold.")

    from_pool = from_reserve = 0
    if action == "APPROVE":
        from_pool, from_reserve = dm.allocation_waterfall(event, product, man)
        allocated = from_pool + from_reserve
        if allocated == 0:
            fail("ERR_SAMPLE_POOL_EXHAUSTED", "the club-week sample pool is exhausted.")
        if is_food and allocated < calc.MIN_CASES_FOR_FOOD_SAMPLING:
            fail(
                "ERR_SAMPLE_ALLOCATION_BELOW_MINIMUM",
                "a food sampling event needs at least %d cases."
                % calc.MIN_CASES_FOR_FOOD_SAMPLING,
            )

    if action == "CLOSE_OUT" and is_food:
        if dm.received_cases(event["id"]) < 1:
            fail("ERR_SAMPLES_NOT_RECEIVED", "no sample cases have been received.")

    # ---- side effects ------------------------------------------------------
    if action == "SUBMIT":
        event["booking_status"] = "SUBMITTED"
        event["submitted_at"] = iso_now()
        touch(event)

    elif action == "REJECT":
        event["booking_status"] = "DRAFT"
        event["submitted_at"] = None
        touch(event)

    elif action == "APPROVE":
        event["pool_cases_used"] = from_pool
        event["reserve_cases_used"] = from_reserve
        event["allocated_sample_cases"] = from_pool + from_reserve
        dm.sync_required_support(event)
        dm.recompute_coverage(event)
        event["approved_at"] = iso_now()
        event["booking_status"] = "CONFIRMED"
        touch(event)

    elif action == "REVOKE_APPROVAL":
        event["pool_cases_used"] = 0
        event["reserve_cases_used"] = 0
        event["allocated_sample_cases"] = 0
        dm.sync_required_support(event)
        dm.release_event_assignments(event)
        dm.release_event_reservations(event)
        dm.recompute_coverage(event)
        event["approved_at"] = None
        event["booking_status"] = "SUBMITTED"
        touch(event)

    elif action == "CLOSE_OUT":
        event["booking_status"] = "COMPLETED"
        event["staffing_status"] = "CLOSED_OUT"
        dm.release_event_reservations(event)
        event["no_show_recovery_open"] = False
        touch(event)

    else:  # CANCEL
        if state == "CONFIRMED":
            reason = (
                "CLUB_CANCELLED"
                if caller.role == "ClubOperations"
                else "MANUFACTURER_CANCELLED_LATE"
            )
            dm.cancel_confirmed_event(event, reason)
        else:
            event["cancellation_reason"] = "MANUFACTURER_CANCELLED_EARLY"
            event["booking_status"] = "CANCELLED"
            dm.freeze_coverage_on_cancel(event)
            dm.recompute_settlement(event)
            touch(event)

    return ok(dm.pub(event))


# ===========================================================================
# EventAssignment
# ===========================================================================
@bp.post("/demo-events/<eid>/assignments")
def create_assignment(eid):
    v.guard(("ProgramAdmin", "StaffingCoordinator"))
    body = v.json_body()
    demonstrator_id = v.req_string(body, "demonstrator_id")
    role = v.req_enum(body, "role", calc.ASSIGNMENT_ROLES)
    travel_authorized = v.opt_bool(body, "travel_authorized", default=False)
    replaces_assignment_id = v.opt_string(body, "replaces_assignment_id")

    event = dm.resolve(db.demo_events, eid, "ERR_DEMO_EVENT_NOT_FOUND")
    dem = dm.resolve(db.demonstrators, demonstrator_id, "ERR_DEMONSTRATOR_NOT_FOUND")
    if replaces_assignment_id is not None:
        dm.resolve(db.assignments, replaces_assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")

    if event["booking_status"] != "CONFIRMED":
        fail("ERR_INVALID_STATE", "assignments require a CONFIRMED booking.")

    if dem["employment_status"] != "ACTIVE":
        fail("ERR_DEMONSTRATOR_NOT_ACTIVE", "the demonstrator is not active.")

    product = db.products[event["product_id"]]
    if event["event_type"] == "FOOD_SAMPLING":
        if not dm.holds_valid_cert(dem["id"], "FOOD_HANDLER", event["event_date"]):
            fail("ERR_FOOD_CERT_INVALID", "a valid FOOD_HANDLER certificate is required.")
    if product["requires_heat_equipment"]:
        if not dm.holds_valid_cert(dem["id"], "HEAT_EQUIPMENT", event["event_date"]):
            fail("ERR_SPECIALTY_CERT_MISSING", "a valid HEAT_EQUIPMENT certificate is required.")
    if product["allergen_flag"]:
        if not dm.holds_valid_cert(dem["id"], "ALLERGEN_AWARENESS", event["event_date"]):
            fail(
                "ERR_SPECIALTY_CERT_MISSING",
                "a valid ALLERGEN_AWARENESS certificate is required.",
            )

    if dem["home_club_id"] != event["club_id"] and not travel_authorized:
        fail("ERR_DEMONSTRATOR_CLUB_MISMATCH", "the demonstrator is rostered elsewhere.")

    window_start = calc.parse_instant(event["event_window_start_utc"])
    window_end = calc.parse_instant(event["event_window_end_utc"])
    new_start, new_end = calc.shift_window(window_start, window_end)

    existing = dm.demonstrator_assignments(dem["id"])
    for other in existing:
        if other["assignment_status"] not in calc.HELD_ASSIGNMENT_STATUSES:
            continue
        old_start = calc.parse_instant(other["scheduled_start_utc"])
        old_end = calc.parse_instant(other["scheduled_end_utc"])
        if new_start <= old_end and old_start <= new_end:
            fail("ERR_DEMONSTRATOR_DOUBLE_BOOKED", "the demonstrator is already booked.")

    event_day = calc.parse_date(event["event_date"])
    week_start = calc.week_monday(event_day)
    week_end = week_start + timedelta(days=7)
    same_day = 0
    same_week = 0
    for other in existing:
        if other["assignment_status"] not in calc.CAP_ASSIGNMENT_STATUSES:
            continue
        other_event = db.demo_events.get(other["demo_event_id"])
        if other_event is None:
            continue
        other_day = calc.parse_date(other_event["event_date"])
        if other_day == event_day:
            same_day += 1
        if week_start <= other_day < week_end:
            same_week += 1
    if same_day >= calc.MAX_ASSIGNMENTS_PER_DEMONSTRATOR_PER_DAY:
        fail("ERR_DEMONSTRATOR_DAILY_CAP_EXCEEDED", "the daily assignment cap is reached.")
    if same_week >= dem["max_weekly_events"]:
        fail("ERR_DEMONSTRATOR_WEEKLY_CAP_EXCEEDED", "the weekly assignment cap is reached.")

    if role == "LEAD":
        for other in dm.event_assignments(event["id"]):
            if other["role"] == "LEAD" and other["assignment_status"] in calc.CAP_ASSIGNMENT_STATUSES:
                fail("ERR_LEAD_ALREADY_ASSIGNED", "the event already holds a LEAD.")

    row = new_row(
        demo_event_id=event["id"],
        demonstrator_id=dem["id"],
        replaces_assignment_id=replaces_assignment_id,
        role=role,
        travel_authorized=travel_authorized,
        assignment_status="ASSIGNED",
        scheduled_start_utc=iso(new_start),
        scheduled_end_utc=iso(new_end),
        check_in_at=None,
        check_out_at=None,
        hours_worked=0.00,
        billable_hours=0.00,
        late_check_in=False,
    )
    db.assignments[row["id"]] = row
    dm.coverage_after_insert(event)
    return ok(dm.pub(row), 201)


@bp.get("/event-assignments/<aid>")
def get_assignment(aid):
    v.guard(("ProgramAdmin", "StaffingCoordinator", "Demonstrator", "ClubOperations"))
    row = dm.resolve(db.assignments, aid, "ERR_ASSIGNMENT_NOT_FOUND")
    return ok(dm.pub(row))


@bp.get("/event-assignments")
def list_assignments():
    v.guard(("ProgramAdmin", "StaffingCoordinator", "Demonstrator", "ClubOperations"))
    limit, offset = v.pagination()
    rows = by_seq(list(db.assignments.values()))
    for field in ("demo_event_id", "demonstrator_id", "replaces_assignment_id"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    status = v.query_enum("assignment_status", calc.ASSIGNMENT_STATUSES)
    if status is not None:
        rows = [r for r in rows if r["assignment_status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_array([dm.pub(r) for r in page], limit, offset, total)


@bp.post("/event-assignments/<aid>/transitions")
def transition_assignment(aid):
    caller = v.guard(("ProgramAdmin", "StaffingCoordinator", "Demonstrator"))
    body = v.json_body()
    action = _read_action(body, ASSIGNMENT_ACTIONS, ASSIGNMENT_ACTION_ROLES, caller)
    if action is None:
        fail("ERR_VALIDATION", "action must be one of %s." % (list(ASSIGNMENT_ACTIONS),))
    occurred_raw = body.get("occurred_at_utc")
    occurred_at = v.opt_instant(body, "occurred_at_utc")
    v.opt_string(body, "note")

    assignment = dm.resolve(db.assignments, aid, "ERR_ASSIGNMENT_NOT_FOUND")
    v.check_ownership(caller, demonstrator_id=assignment["demonstrator_id"])

    state = assignment["assignment_status"]
    if state not in ASSIGNMENT_FROM_STATES[action]:
        fail("ERR_INVALID_STATE", "%s is not legal from assignment_status %s." % (action, state))

    event = db.demo_events.get(assignment["demo_event_id"])
    if action in ("CONFIRM", "CHECK_IN"):
        if event is None or event["booking_status"] != "CONFIRMED":
            fail("ERR_INVALID_STATE", "the event booking is not CONFIRMED.")

    if action == "CHECK_IN" and event is not None and event["event_type"] == "FOOD_SAMPLING":
        active = [
            r
            for r in dm.event_reservations(event["id"])
            if r["reservation_status"] == "ACTIVE"
        ]
        if not active:
            fail("ERR_EQUIPMENT_NOT_SANITIZED", "no equipment unit is in use for this event.")
        for res in active:
            unit = db.equipment_units.get(res["equipment_unit_id"])
            if unit is None or unit["sanitation_status"] != "IN_USE":
                fail("ERR_EQUIPMENT_NOT_SANITIZED", "the reserved unit is not in use.")

    instant = occurred_at if occurred_at is not None else now()
    stamp = occurred_raw if occurred_at is not None else iso_now()

    if action in ("CHECK_IN", "CHECK_OUT"):
        if instant > now():
            fail("ERR_CHECK_IN_WINDOW_INVALID", "the instant is in the future.")
    if action == "CHECK_IN":
        start = calc.parse_instant(assignment["scheduled_start_utc"])
        end = calc.parse_instant(assignment["scheduled_end_utc"])
        earliest = start - timedelta(minutes=calc.CHECK_IN_EARLY_MINUTES)
        if instant < earliest or instant > end:
            fail("ERR_CHECK_IN_WINDOW_INVALID", "the check-in instant is outside the window.")
    if action == "CHECK_OUT":
        check_in = calc.parse_instant(assignment.get("check_in_at"))
        if check_in is None or instant <= check_in:
            fail("ERR_CHECK_IN_WINDOW_INVALID", "the check-out instant must follow check-in.")
    if action == "NO_SHOW":
        start = calc.parse_instant(assignment["scheduled_start_utc"])
        if now() < start + timedelta(minutes=calc.NO_SHOW_GRACE_MINUTES):
            fail("ERR_NO_SHOW_TOO_EARLY", "the no-show grace period has not elapsed.")

    dem = db.demonstrators.get(assignment["demonstrator_id"])

    if action == "CONFIRM":
        assignment["assignment_status"] = "CONFIRMED"
        touch(assignment)

    elif action == "CHECK_IN":
        assignment["assignment_status"] = "CHECKED_IN"
        assignment["check_in_at"] = stamp
        assignment["late_check_in"] = dm.compute_late_check_in(assignment)
        touch(assignment)
        if (
            assignment["role"] == "LEAD"
            and event is not None
            and event["staffing_status"] == "FULLY_STAFFED"
        ):
            event["staffing_status"] = "EXECUTED"
            touch(event)

    elif action == "CHECK_OUT":
        assignment["assignment_status"] = "COMPLETED"
        assignment["check_out_at"] = stamp
        dm.apply_attendance_figures(assignment)
        touch(assignment)
        if dem is not None:
            dm.recompute_demonstrator_metrics(dem)
            touch(dem)

    elif action == "RELEASE":
        assignment["assignment_status"] = "RELEASED"
        touch(assignment)
        if dem is not None:
            dm.recompute_demonstrator_metrics(dem)
            touch(dem)
        if event is not None and dm.downgrade_coverage(event, False):
            touch(event)

    else:  # NO_SHOW
        assignment["assignment_status"] = "NO_SHOW"
        touch(assignment)
        went_on_leave = False
        if dem is not None:
            dm.recompute_demonstrator_metrics(dem)
            if (
                dem["no_show_strike_count"] >= calc.NO_SHOW_STRIKE_LIMIT
                and dem["employment_status"] == "ACTIVE"
            ):
                dem["employment_status"] = "ON_LEAVE"
                went_on_leave = True
            touch(dem)
        if went_on_leave:
            clock_date = db.clock.date()
            for other in dm.demonstrator_assignments(dem["id"]):
                if other["id"] == assignment["id"]:
                    continue
                if other["assignment_status"] not in ("ASSIGNED", "CONFIRMED"):
                    continue
                other_event = db.demo_events.get(other["demo_event_id"])
                if other_event is None:
                    continue
                if calc.parse_date(other_event["event_date"]) < clock_date:
                    continue
                other["assignment_status"] = "RELEASED"
                touch(other)
                if dm.downgrade_coverage(other_event, False):
                    touch(other_event)
        if event is not None:
            if dm.downgrade_coverage(event, True):
                touch(event)
            dm.create_cancellation_credit(event, "DEMONSTRATOR_NO_SHOW")

    return ok(dm.pub(assignment))


# ===========================================================================
# EquipmentReservation
# ===========================================================================
@bp.post("/equipment-reservations")
def create_reservation():
    caller = v.guard(("ProgramAdmin", "ClubOperations", "StaffingCoordinator"))
    body = v.json_body()
    equipment_unit_id = v.req_string(body, "equipment_unit_id")
    demo_event_id = v.req_string(body, "demo_event_id")
    start_raw = v.req_present(body, "window_start_utc")
    window_start = calc.parse_instant(start_raw)
    if window_start is None:
        fail("ERR_VALIDATION", "window_start_utc must be an ISO 8601 UTC instant.")
    end_raw = v.req_present(body, "window_end_utc")
    window_end = calc.parse_instant(end_raw)
    if window_end is None:
        fail("ERR_VALIDATION", "window_end_utc must be an ISO 8601 UTC instant.")
    if window_end <= window_start:
        fail("ERR_VALIDATION", "window_end_utc must be later than window_start_utc.")

    unit = dm.resolve(db.equipment_units, equipment_unit_id, "ERR_RESOURCE_NOT_FOUND")
    event = dm.resolve(db.demo_events, demo_event_id, "ERR_DEMO_EVENT_NOT_FOUND")
    v.check_ownership(caller, club_id=event["club_id"])

    if unit["club_id"] != event["club_id"]:
        fail("ERR_EQUIPMENT_CLUB_MISMATCH", "the unit belongs to another club.")

    event_start = calc.parse_instant(event["event_window_start_utc"])
    event_end = calc.parse_instant(event["event_window_end_utc"])
    latest_start = event_start - timedelta(minutes=calc.SETUP_LEAD_MINUTES)
    if window_start > latest_start or window_end < event_end:
        fail(
            "ERR_RESERVATION_WINDOW_INSUFFICIENT",
            "the window must cover setup through the end of the event.",
        )

    buffer_delta = timedelta(minutes=calc.SANITATION_BUFFER_MINUTES)
    for other in db.reservations.values():
        if other["equipment_unit_id"] != unit["id"]:
            continue
        if other["reservation_status"] not in ("HELD", "ACTIVE"):
            continue
        old_start = calc.parse_instant(other["window_start_utc"])
        old_end = calc.parse_instant(other["window_end_utc"])
        if window_start < old_end + buffer_delta and old_start < window_end + buffer_delta:
            fail("ERR_EQUIPMENT_WINDOW_CONFLICT", "the unit is already reserved nearby.")

    row = new_row(
        equipment_unit_id=unit["id"],
        demo_event_id=event["id"],
        window_start_utc=start_raw,
        window_end_utc=end_raw,
        buffer_minutes=calc.SANITATION_BUFFER_MINUTES,
        reservation_status="HELD",
    )
    db.reservations[row["id"]] = row
    return ok(dm.pub(row), 201)


@bp.get("/equipment-reservations/<rid>")
def get_reservation(rid):
    v.guard(("ProgramAdmin", "ClubOperations", "StaffingCoordinator"))
    row = dm.resolve(db.reservations, rid, "ERR_RESOURCE_NOT_FOUND")
    return ok(dm.pub(row))


@bp.get("/equipment-reservations")
def list_reservations():
    v.guard(("ProgramAdmin", "ClubOperations", "StaffingCoordinator"))
    limit, offset = v.pagination()
    rows = by_seq(list(db.reservations.values()))
    for field in ("equipment_unit_id", "demo_event_id"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    status = v.query_enum("reservation_status", calc.RESERVATION_STATUSES)
    if status is not None:
        rows = [r for r in rows if r["reservation_status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_array([dm.pub(r) for r in page], limit, offset, total)


@bp.post("/equipment-reservations/<rid>/transitions")
def transition_reservation(rid):
    caller = v.guard(("ProgramAdmin", "ClubOperations"))
    body = v.json_body()
    action = v.req_enum(body, "action", ("ACTIVATE", "RELEASE"))
    res = dm.resolve(db.reservations, rid, "ERR_RESOURCE_NOT_FOUND")
    event = db.demo_events.get(res["demo_event_id"])
    v.check_ownership(caller, club_id=event["club_id"] if event else None)

    state = res["reservation_status"]
    legal = ("HELD",) if action == "ACTIVATE" else ("HELD", "ACTIVE")
    if state not in legal:
        fail("ERR_INVALID_STATE", "%s is not legal from reservation_status %s." % (action, state))

    unit = db.equipment_units.get(res["equipment_unit_id"])

    if action == "ACTIVATE":
        if event is None or event["booking_status"] != "CONFIRMED":
            fail("ERR_INVALID_STATE", "the event booking is not CONFIRMED.")
        window_start = calc.parse_instant(res["window_start_utc"])
        window_end = calc.parse_instant(res["window_end_utc"])
        earliest = window_start - timedelta(minutes=calc.ACTIVATION_EARLY_MINUTES)
        if now() < earliest or now() > window_end:
            fail("ERR_INVALID_STATE", "the activation window is not open.")
        if unit is None or unit["sanitation_status"] != "SANITIZED":
            fail("ERR_EQUIPMENT_NOT_SANITIZED", "the unit is not sanitized.")
        res["reservation_status"] = "ACTIVE"
        touch(res)
        unit["sanitation_status"] = "IN_USE"
        touch(unit)
    else:
        was_active = state == "ACTIVE"
        res["reservation_status"] = "RELEASED"
        touch(res)
        if was_active and unit is not None:
            unit["sanitation_status"] = "SOILED"
            touch(unit)

    return ok(dm.pub(res))
