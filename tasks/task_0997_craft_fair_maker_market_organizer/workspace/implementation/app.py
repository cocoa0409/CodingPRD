"""Craft-Fair & Maker-Market Organizer API — Flask entry point and routes."""
import os
import threading

from flask import Flask

from core import (
    ApiError, store, auth, require, body, ok, ok_list, err_response,
    stamp, stamp_light, touch, by_created, pub, get_or_404, apply_filters,
    parse_dt, fmt_ts, invalid, req_str, req_int, req_enum, req_dt, req_pct,
    posture_gate, select_booth, booth_occupied, approved_count_for_category,
    category_cap_for, event_zones, event_booths, event_applications,
    event_assignments, event_settlements, event_tickets, event_attendance,
    event_sales, event_slots, assignment_for_application, charges_for_assignment,
    booth_of, zone_of_booth, event_of_assignment, booth_fee_final,
    settlement_gross_quote, commission_quote, commission_final,
    outstanding_booth_fee, mint_charge, create_assignment_with_provisional,
    waitlist_promotion_scan, forfeit_assignment, auto_close_event_applications,
    weather_severe_cascade, cancel_event_cascade,
    serialize_event, serialize_zone, serialize_booth, serialize_vendor,
    serialize_application, serialize_jury_score, serialize_assignment,
    serialize_charge, serialize_slot, serialize_ticket, serialize_attendance,
    serialize_sale, serialize_settlement,
    PRE_LIVE_POSTURES, TERMINAL_POSTURES, WEATHER_FLAGS, ZONE_EXPOSURES,
    CATEGORIES, TIERS, SLOT_KINDS, BAYS, TICKET_KINDS, DECIDE_OUTCOMES,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

# Serialize requests: the store is a plain in-memory dict and several writes are
# multi-step (selector + grant + charge minting), so concurrent requests must
# interleave at request granularity, not bytecode granularity.
_REQUEST_LOCK = threading.RLock()


@app.before_request
def _acquire_store_lock():
    _REQUEST_LOCK.acquire()


@app.teardown_request
def _release_store_lock(exc):
    _REQUEST_LOCK.release()


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_response(e)


@app.errorhandler(404)
def handle_404(e):
    return err_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found."))


@app.errorhandler(405)
def handle_405(e):
    return err_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found."))


@app.errorhandler(Exception)
def handle_unexpected(e):
    # Never leak a bare 500 HTML page; respond in the error envelope.
    return err_response(ApiError("ERR_INVALID_INPUT", 400, "Unexpected error: %s" % e))


def get_event_or_404(event_id):
    return get_or_404("events", event_id, "MakerEvent")


def get_event_scoped(table, rid, event, fk, label):
    """Existence check left-to-right: event first (caller did), then the child,
    then that the child belongs to the event."""
    rec = get_or_404(table, rid, label)
    if rec.get(fk) != event["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "%s not found in event: %s" % (label, rid))
    return rec


def get_application_in_event(event, app_id):
    return get_event_scoped("applications", app_id, event, "maker_event_id", "VendorApplication")


def get_assignment_in_event(event, assignment_id):
    asg = get_or_404("assignments", assignment_id, "BoothAssignment")
    app_rec = store.applications.get(asg["vendor_application_id"])
    if app_rec is None or app_rec["maker_event_id"] != event["id"]:
        raise ApiError("ERR_NOT_FOUND", 404,
                       "BoothAssignment not found in event: %s" % assignment_id)
    return asg


def get_settlement_in_event(event, settlement_id):
    st = get_or_404("settlements", settlement_id, "Settlement")
    asg = store.assignments.get(st["booth_assignment_id"])
    app_rec = store.applications.get(asg["vendor_application_id"]) if asg else None
    if app_rec is None or app_rec["maker_event_id"] != event["id"]:
        raise ApiError("ERR_NOT_FOUND", 404,
                       "Settlement not found in event: %s" % settlement_id)
    return st


def get_ticket_in_event(event, ticket_id):
    return get_event_scoped("tickets", ticket_id, event, "maker_event_id", "Ticket")


def get_attendance_in_event(event, attendance_id):
    return get_event_scoped("attendance", attendance_id, event, "maker_event_id", "Attendance")


def application_vendor_id(app_rec):
    return app_rec["vendor_profile_id"]


def assignment_vendor_id(asg):
    app_rec = store.applications.get(asg["vendor_application_id"])
    return app_rec["vendor_profile_id"] if app_rec else None


# ===========================================================================
# Clock (test-driving)
# ===========================================================================


@app.post("/_clock/set_current_utc")
def set_clock():
    _, role = auth()
    require(role, "PlatformAdmin")
    data = body()
    dt = parse_dt(data.get("to_iso8601"))
    if dt is None:
        invalid("Field 'to_iso8601' must be an ISO 8601 datetime string.")
    store.clock = dt
    # Note: no eager sweeps here. The application window is enforced at submit
    # time (ERR_APPLICATION_WINDOW_CLOSED) and the payment deadline at pay time
    # (ERR_PAYMENT_WINDOW_EXPIRED); the manual close-applications endpoint must
    # remain callable after the clock passes the window end.
    return ok({"now_iso8601": fmt_ts(store.clock)})


# ===========================================================================
# MakerEvent
# ===========================================================================


@app.post("/maker-events")
def create_event():
    uid, role = auth()
    require(role, "EventCoordinator")
    data = body()
    name = req_str(data, "name")
    opens = req_dt(data, "opens_at")
    closes = req_dt(data, "closes_at")
    capacity = req_int(data, "venue_capacity")
    win_start = req_dt(data, "application_window_start")
    win_end = req_dt(data, "application_window_end")
    quorum = req_int(data, "jury_quorum")
    pct_std = req_pct(data, "commission_pct_standard")
    pct_anchor = req_pct(data, "commission_pct_anchor")
    weather = data.get("weather_flag") or "CLEAR"
    if weather not in WEATHER_FLAGS:
        invalid("Field 'weather_flag' must be one of CLEAR, ADVISORY, SEVERE.")

    rec = {
        "name": name,
        "opens_at": fmt_ts(opens),
        "closes_at": fmt_ts(closes),
        "venue_capacity": capacity,
        "posture": "PLANNING",
        "weather_flag": weather,
        "application_window_start": fmt_ts(win_start),
        "application_window_end": fmt_ts(win_end),
        "jury_quorum": quorum,
        "_created_by": uid,
        "_opens": opens,
        "_closes": closes,
        "_win_start": win_start,
        "_win_end": win_end,
    }
    # Persist commission pcts as plain numbers (int when whole, float otherwise)
    rec["commission_pct_standard"] = int(pct_std) if pct_std == pct_std.to_integral_value() else float(pct_std)
    rec["commission_pct_anchor"] = int(pct_anchor) if pct_anchor == pct_anchor.to_integral_value() else float(pct_anchor)
    stamp(rec)
    store.events[rec["id"]] = rec
    return ok(serialize_event(rec), 201)


@app.get("/maker-events")
def list_events():
    auth()
    recs = [serialize_event(e) for e in by_created(store.events.values())]
    return ok_list(recs)


@app.get("/maker-events/<event_id>")
def get_event(event_id):
    auth()
    ev = get_event_or_404(event_id)
    return ok(serialize_event(ev))


def _event_action(event_id, allowed_from, fn):
    uid, role = auth()
    require(role, "EventCoordinator")
    ev = get_event_or_404(event_id)
    if ev["posture"] not in allowed_from:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "MakerEvent posture %s does not have this transition." % ev["posture"])
    fn(ev, uid)
    return ok(serialize_event(ev))


@app.post("/maker-events/<event_id>/open-applications")
def open_applications(event_id):
    def do(ev, uid):
        if store.clock < ev["_win_start"]:
            raise ApiError("ERR_APPLICATION_WINDOW_CLOSED", 409,
                           "Logical clock has not reached application_window_start.")
        if ev["jury_quorum"] < 2:
            invalid("jury_quorum must be at least 2 to open applications.")
        ev["posture"] = "APPLICATION_OPEN"
        touch(ev)
    return _event_action(event_id, ("PLANNING",), do)


@app.post("/maker-events/<event_id>/close-applications")
def close_applications(event_id):
    def do(ev, uid):
        auto_close_event_applications(ev)
    return _event_action(event_id, ("APPLICATION_OPEN",), do)


@app.post("/maker-events/<event_id>/begin-scheduling")
def begin_scheduling(event_id):
    def do(ev, uid):
        apps = event_applications(ev["id"])
        # Unresolved = still in the pre-review pipeline (DRAFT/SUBMITTED). Note:
        # in JURY_REVIEW posture the close sweep has already moved every DRAFT
        # to WITHDRAWN and every SUBMITTED to IN_REVIEW, so this only fires for
        # applications created but never routed through the window.
        unresolved = [a for a in apps if a["status"] in ("DRAFT", "SUBMITTED")]
        if unresolved:
            raise ApiError("ERR_UNRESOLVED_APPLICATIONS", 409,
                           "Some applications are still unresolved.")
        for a in apps:
            if a["status"] == "APPROVED" and a["jury_score_count"] < ev["jury_quorum"]:
                raise ApiError("ERR_UNRESOLVED_APPLICATIONS", 409,
                               "An APPROVED application has not met jury quorum.")
        # Materialize waitlist ranks per category: jury_score_total DESC,
        # created_at ASC, vendor_profile_id ASC.
        for cat in CATEGORIES:
            waitlisted = [a for a in apps
                          if a["status"] == "WAITLISTED" and a["requested_category"] == cat]
            waitlisted.sort(key=lambda a: (-a["jury_score_total"], a["created_at"], a["_seq"],
                                           a["vendor_profile_id"]))
            for i, a in enumerate(waitlisted, start=1):
                a["waitlist_rank"] = i
                touch(a)
        ev["posture"] = "SCHEDULING"
        touch(ev)
    return _event_action(event_id, ("JURY_REVIEW",), do)


@app.post("/maker-events/<event_id>/go-live")
def go_live(event_id):
    def do(ev, uid):
        asgs = event_assignments(ev["id"])
        if not any(x["status"] == "ACTIVE" for x in asgs):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "At least one ACTIVE BoothAssignment is required to go live.")
        for x in asgs:
            if x["status"] == "PENDING_PAYMENT":
                due = parse_dt(x["payment_due_at"])
                if due is not None and due <= store.clock:
                    raise ApiError("ERR_PAYMENT_WINDOW_EXPIRED", 409,
                                   "A PENDING_PAYMENT assignment has passed its payment deadline.")
        ev["posture"] = "LIVE"
        touch(ev)
    return _event_action(event_id, ("SCHEDULING",), do)


@app.post("/maker-events/<event_id>/end-event")
def end_event(event_id):
    def do(ev, uid):
        if store.clock < ev["_closes"]:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Logical clock has not reached closes_at.")
        for a in event_attendance(ev["id"]):
            if a["exited_at"] is None:
                raise ApiError("ERR_UNRESOLVED_ATTENDANCE", 409,
                               "Some attendees are still on site.")
        for x in event_assignments(ev["id"]):
            if x["status"] == "ACTIVE":
                st = {
                    "booth_assignment_id": x["id"],
                    "status": "PENDING",
                    "gross_sales_cents": 0,
                    "commission_cents": 0,
                    "net_payout_cents": 0,
                    "approved_by_user_id": None,
                }
                stamp(st)
                store.settlements[st["id"]] = st
        ev["posture"] = "SETTLEMENT"
        touch(ev)
    return _event_action(event_id, ("LIVE",), do)


@app.post("/maker-events/<event_id>/close-event")
def close_event(event_id):
    def do(ev, uid):
        for s in event_settlements(ev["id"]):
            if s["status"] in ("PENDING", "COMPUTED", "DISPUTED"):
                raise ApiError("ERR_UNRESOLVED_SETTLEMENTS", 409,
                               "Some settlements are not APPROVED or PAID.")
        ev["posture"] = "CLOSED"
        touch(ev)
    return _event_action(event_id, ("SETTLEMENT",), do)


@app.post("/maker-events/<event_id>/cancel")
def cancel_event(event_id):
    def do(ev, uid):
        cancel_event_cascade(ev)
    return _event_action(event_id, PRE_LIVE_POSTURES + ("WEATHER_HOLD",), do)


@app.post("/maker-events/<event_id>/weather")
def set_weather(event_id):
    uid, role = auth()
    require(role, "EventCoordinator")
    ev = get_event_or_404(event_id)
    data = body()
    flag = req_enum(data, "weather_flag", WEATHER_FLAGS)
    if flag == "SEVERE" and ev["posture"] == "LIVE":
        ev["weather_flag"] = "SEVERE"
        weather_severe_cascade(ev)
    elif flag == "CLEAR" and ev["posture"] == "WEATHER_HOLD":
        if store.clock >= ev["_closes"]:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Cannot return to LIVE after closes_at.")
        ev["weather_flag"] = "CLEAR"
        ev["posture"] = "LIVE"
        touch(ev)
    else:
        ev["weather_flag"] = flag
        touch(ev)
    return ok(serialize_event(ev))


# ===========================================================================
# BoothZone & Booth
# ===========================================================================


@app.post("/maker-events/<event_id>/booth-zones")
def create_zone(event_id):
    _, role = auth()
    require(role, "EventCoordinator")
    ev = get_event_or_404(event_id)
    posture_gate(ev, PRE_LIVE_POSTURES)
    data = body()
    rec = {
        "maker_event_id": ev["id"],
        "label": req_str(data, "label"),
        "weather_exposure": req_enum(data, "weather_exposure", ZONE_EXPOSURES),
        "category": req_enum(data, "category", CATEGORIES),
        "category_cap": req_int(data, "category_cap"),
    }
    stamp(rec)
    store.zones[rec["id"]] = rec
    return ok(serialize_zone(rec), 201)


@app.get("/maker-events/<event_id>/booth-zones")
def list_zones(event_id):
    auth()
    ev = get_event_or_404(event_id)
    recs = [serialize_zone(z) for z in by_created(event_zones(ev["id"]))]
    return ok_list(recs)


@app.get("/booth-zones/<zone_id>")
def get_zone(zone_id):
    auth()
    z = get_or_404("zones", zone_id, "BoothZone")
    return ok(serialize_zone(z))


@app.get("/booth-zones")
def list_zones_filtered():
    auth()
    recs = [serialize_zone(z) for z in by_created(store.zones.values())]
    recs = apply_filters(recs, {"maker_event_id": "maker_event_id"})
    return ok_list(recs)


@app.post("/maker-events/<event_id>/booth-zones/<zone_id>/booths")
def create_booth(event_id, zone_id):
    _, role = auth()
    require(role, "EventCoordinator")
    ev = get_event_or_404(event_id)
    zone = get_event_scoped("zones", zone_id, ev, "maker_event_id", "BoothZone")
    posture_gate(ev, PRE_LIVE_POSTURES)
    data = body()
    tier = req_enum(data, "tier", TIERS)
    footprint = req_int(data, "footprint_sqm")
    if tier == "ANCHOR" and footprint < 20:
        raise ApiError("ERR_BOOTH_CONSTRAINT_VIOLATION", 422,
                       "ANCHOR booths must be at least 20 sqm.")
    rec = {
        "booth_zone_id": zone["id"],
        "code": req_str(data, "code"),
        "tier": tier,
        "footprint_sqm": footprint,
        "price_cents": req_int(data, "price_cents"),
        "assigned_application_id": None,
    }
    stamp(rec)
    store.booths[rec["id"]] = rec
    return ok(serialize_booth(rec), 201)


def booth_with_occupancy(b):
    d = serialize_booth(b)
    d["occupied"] = booth_occupied(b["id"])
    return d


@app.get("/maker-events/<event_id>/booth-zones/<zone_id>/booths")
def list_booths(event_id, zone_id):
    auth()
    ev = get_event_or_404(event_id)
    zone = get_event_scoped("zones", zone_id, ev, "maker_event_id", "BoothZone")
    recs = [booth_with_occupancy(b) for b in by_created(
        [b for b in store.booths.values() if b["booth_zone_id"] == zone["id"]])]
    recs = apply_filters(recs, {"tier": "tier", "occupied": "occupied"})
    return ok_list(recs)


@app.get("/booths/<booth_id>")
def get_booth(booth_id):
    auth()
    b = get_or_404("booths", booth_id, "Booth")
    return ok(booth_with_occupancy(b))


@app.get("/booths")
def list_booths_filtered():
    auth()
    recs = [booth_with_occupancy(b) for b in by_created(list(store.booths.values()))]
    recs = apply_filters(recs, {
        "booth_zone_id": "booth_zone_id",
        "assigned_application_id": "assigned_application_id",
    })
    return ok_list(recs)


# ===========================================================================
# VendorProfile
# ===========================================================================


@app.post("/vendor-profiles")
def create_vendor():
    _, role = auth()
    require(role, "PlatformAdmin")
    data = body()
    name = req_str(data, "display_name")
    email = req_str(data, "contact_email")
    region = req_str(data, "home_region")
    for v in store.vendors.values():
        if v["contact_email"] == email:
            raise ApiError("ERR_EMAIL_TAKEN", 409,
                           "contact_email already in use: %s" % email)
    rec = {
        "display_name": name,
        "contact_email": email,
        "home_region": region,
        "status": "ACTIVE",
    }
    stamp(rec)
    store.vendors[rec["id"]] = rec
    return ok(serialize_vendor(rec), 201)


@app.get("/vendor-profiles/<vendor_id>")
def get_vendor(vendor_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Vendor", "PlatformAdmin")
    v = get_or_404("vendors", vendor_id, "VendorProfile")
    return ok(serialize_vendor(v))


@app.post("/vendor-profiles/<vendor_id>/suspend")
def suspend_vendor(vendor_id):
    _, role = auth()
    require(role, "PlatformAdmin")
    v = get_or_404("vendors", vendor_id, "VendorProfile")
    v["status"] = "SUSPENDED"
    touch(v)
    return ok(serialize_vendor(v))


@app.get("/vendor-profiles/<vendor_id>/applications")
def list_vendor_applications(vendor_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Vendor", "PlatformAdmin")
    v = get_or_404("vendors", vendor_id, "VendorProfile")
    recs = [serialize_application(a) for a in by_created(
        [a for a in store.applications.values() if a["vendor_profile_id"] == v["id"]])]
    return ok_list(recs)


# ===========================================================================
# VendorApplication
# ===========================================================================


@app.post("/maker-events/<event_id>/applications")
def create_application(event_id):
    uid, role = auth()
    require(role, "Vendor")
    ev = get_event_or_404(event_id)
    posture_gate(ev, ("PLANNING", "APPLICATION_OPEN"))
    data = body()
    vendor_id = req_str(data, "vendor_profile_id")
    vendor = get_or_404("vendors", vendor_id, "VendorProfile")
    if vendor_id != uid:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Vendors may only file applications for their own profile.")
    category = req_enum(data, "requested_category", CATEGORIES)
    tier = req_enum(data, "requested_tier", TIERS)
    rec = {
        "maker_event_id": ev["id"],
        "vendor_profile_id": vendor["id"],
        "requested_category": category,
        "requested_tier": tier,
        "status": "DRAFT",
        "jury_score_total": 0,
        "jury_score_count": 0,
        "waitlist_rank": None,
    }
    stamp(rec)
    store.applications[rec["id"]] = rec
    return ok(serialize_application(rec), 201)


@app.get("/maker-events/<event_id>/applications")
def list_applications(event_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Juror", "Vendor", "PlatformAdmin")
    ev = get_event_or_404(event_id)
    recs = [serialize_application(a) for a in by_created(event_applications(ev["id"]))]
    recs = apply_filters(recs, {
        "status": "status",
        "requested_category": "requested_category",
        "vendor_profile_id": "vendor_profile_id",
    })
    return ok_list(recs)


@app.get("/maker-events/<event_id>/applications/<app_id>")
def get_application(event_id, app_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Juror", "Vendor", "PlatformAdmin")
    ev = get_event_or_404(event_id)
    app_rec = get_application_in_event(ev, app_id)
    return ok(serialize_application(app_rec))


@app.get("/applications/<app_id>")
def get_application_canonical(app_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Juror", "Vendor", "PlatformAdmin")
    app_rec = get_or_404("applications", app_id, "VendorApplication")
    return ok(serialize_application(app_rec))


@app.get("/applications")
def list_applications_filtered():
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Juror", "Vendor", "PlatformAdmin")
    recs = [serialize_application(a) for a in by_created(store.applications.values())]
    recs = apply_filters(recs, {
        "maker_event_id": "maker_event_id",
        "vendor_profile_id": "vendor_profile_id",
        "status": "status",
        "requested_category": "requested_category",
    })
    return ok_list(recs)


@app.post("/maker-events/<event_id>/applications/<app_id>/submit")
def submit_application(event_id, app_id):
    uid, role = auth()
    require(role, "Vendor")
    ev = get_event_or_404(event_id)
    app_rec = get_application_in_event(ev, app_id)
    posture_gate(ev, ("APPLICATION_OPEN",))
    if app_rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Application status %s cannot be submitted." % app_rec["status"])
    if app_rec["vendor_profile_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Only the owning vendor may submit this application.")
    vendor = store.vendors.get(app_rec["vendor_profile_id"])
    if vendor is not None and vendor["status"] == "SUSPENDED":
        raise ApiError("ERR_VENDOR_SUSPENDED", 409, "Vendor is suspended.")
    if not (ev["_win_start"] <= store.clock < ev["_win_end"]):
        raise ApiError("ERR_APPLICATION_WINDOW_CLOSED", 409,
                       "Outside the application intake window.")
    cat = app_rec["requested_category"]
    if approved_count_for_category(ev["id"], cat) >= category_cap_for(ev["id"], cat):
        raise ApiError("ERR_CATEGORY_CAP_EXCEEDED", 409,
                       "Category cap exhausted for %s." % cat)
    app_rec["status"] = "SUBMITTED"
    touch(app_rec)
    return ok(serialize_application(app_rec))


@app.post("/maker-events/<event_id>/applications/<app_id>/withdraw")
def withdraw_application(event_id, app_id):
    uid, role = auth()
    require(role, "Vendor")
    ev = get_event_or_404(event_id)
    app_rec = get_application_in_event(ev, app_id)
    if app_rec["status"] not in ("DRAFT", "SUBMITTED", "IN_REVIEW", "WAITLISTED", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Application status %s cannot be withdrawn." % app_rec["status"])
    if app_rec["vendor_profile_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Only the owning vendor may withdraw this application.")
    was_approved = app_rec["status"] == "APPROVED"
    app_rec["status"] = "WITHDRAWN"
    app_rec["waitlist_rank"] = None
    touch(app_rec)
    if was_approved:
        asg = assignment_for_application(app_rec["id"])
        if asg is not None and asg["status"] in ("PENDING_PAYMENT", "ACTIVE"):
            forfeit_assignment(asg, event=ev)
    return ok(serialize_application(app_rec))


@app.post("/maker-events/<event_id>/applications/<app_id>/decide")
def decide_application(event_id, app_id):
    _, role = auth()
    require(role, "EventCoordinator")
    ev = get_event_or_404(event_id)
    app_rec = get_application_in_event(ev, app_id)
    posture_gate(ev, ("JURY_REVIEW",))
    if app_rec["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Application status %s cannot be decided." % app_rec["status"])
    data = body()
    outcome = req_enum(data, "outcome", DECIDE_OUTCOMES)
    expected = data.get("expected_event_version")
    if isinstance(expected, str) and expected.isdigit():
        expected = int(expected)
    if isinstance(expected, bool) or (expected is not None and not isinstance(expected, int)):
        invalid("Field 'expected_event_version' must be an integer.")
    if app_rec["jury_score_count"] < ev["jury_quorum"]:
        raise ApiError("ERR_JURY_QUORUM_NOT_MET", 409,
                       "Fewer than jury_quorum distinct juror scores present.")

    chosen = None
    if outcome == "APPROVE":
        cat = app_rec["requested_category"]
        tier = app_rec["requested_tier"]
        # Priority 8: booth constraint — some booth must match (category, tier)
        matching = [b for b in event_booths(ev["id"])
                    if (zone_of_booth(b) is not None
                        and zone_of_booth(b)["category"] == cat
                        and b["tier"] == tier)]
        if not matching:
            raise ApiError("ERR_BOOTH_CONSTRAINT_VIOLATION", 422,
                           "No booth matches the requested category and tier.")
        # Priority 9: category cap
        if approved_count_for_category(ev["id"], cat) >= category_cap_for(ev["id"], cat):
            raise ApiError("ERR_CATEGORY_CAP_EXCEEDED", 409,
                           "Approving would exceed the category cap for %s." % cat)
        # Priority 14: occupancy — selector over unoccupied matching booths
        chosen = select_booth(ev, cat, tier)
        if chosen is None:
            raise ApiError("ERR_BOOTH_DOUBLE_BOOKED", 409,
                           "Every booth matching the requested category and tier is occupied.")
    if expected != ev["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_event_version does not match the current event version.")

    if outcome == "APPROVE":
        app_rec["status"] = "APPROVED"
        touch(app_rec)
        create_assignment_with_provisional(ev, app_rec, chosen)
    elif outcome == "WAITLIST":
        app_rec["status"] = "WAITLISTED"
        app_rec["waitlist_rank"] = None
        touch(app_rec)
    else:  # REJECT
        app_rec["status"] = "REJECTED"
        touch(app_rec)
    touch(ev)  # every decision advances the event version
    return ok(serialize_application(app_rec))


@app.post("/maker-events/<event_id>/applications/<app_id>/revoke")
def revoke_application(event_id, app_id):
    _, role = auth()
    require(role, "EventCoordinator")
    ev = get_event_or_404(event_id)
    app_rec = get_application_in_event(ev, app_id)
    posture_gate(ev, ("JURY_REVIEW", "SCHEDULING"))
    if app_rec["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an APPROVED application can be revoked.")
    app_rec["status"] = "CANCELLED"
    touch(app_rec)
    asg = assignment_for_application(app_rec["id"])
    if asg is not None and asg["status"] in ("PENDING_PAYMENT", "ACTIVE"):
        forfeit_assignment(asg, event=ev)
    else:
        waitlist_promotion_scan(ev, category=app_rec["requested_category"])
    return ok(serialize_application(app_rec))


# ===========================================================================
# JuryScore
# ===========================================================================


@app.post("/maker-events/<event_id>/applications/<app_id>/jury-scores")
def create_jury_score(event_id, app_id):
    uid, role = auth()
    require(role, "Juror")
    ev = get_event_or_404(event_id)
    app_rec = get_application_in_event(ev, app_id)
    posture_gate(ev, ("JURY_REVIEW",))
    data = body()
    craftsmanship = req_int(data, "craftsmanship")
    originality = req_int(data, "originality")
    presentation = req_int(data, "booth_presentation")
    for field, v in (("craftsmanship", craftsmanship), ("originality", originality),
                     ("booth_presentation", presentation)):
        if v < 0 or v > 10:
            invalid("Field '%s' must be between 0 and 10." % field)
    if uid == app_rec["vendor_profile_id"] or uid == ev["_created_by"]:
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "Juror must differ from the applicant and the event creator.")
    for s in store.jury_scores.values():
        if s["vendor_application_id"] == app_rec["id"] and s["juror_user_id"] == uid:
            raise ApiError("ERR_JURY_DUPLICATE", 409,
                           "This juror has already scored this application.")
    rec = {
        "vendor_application_id": app_rec["id"],
        "juror_user_id": uid,
        "craftsmanship": craftsmanship,
        "originality": originality,
        "booth_presentation": presentation,
        "total": craftsmanship + originality + presentation,
    }
    stamp_light(rec)
    store.jury_scores[rec["id"]] = rec
    app_rec["jury_score_total"] += rec["total"]
    app_rec["jury_score_count"] += 1
    touch(app_rec)
    return ok(serialize_jury_score(rec), 201)


@app.get("/maker-events/<event_id>/applications/<app_id>/jury-scores")
def list_jury_scores(event_id, app_id):
    _, role = auth()
    require(role, "EventCoordinator", "Juror", "Treasurer", "PlatformAdmin")
    ev = get_event_or_404(event_id)
    app_rec = get_application_in_event(ev, app_id)
    recs = [serialize_jury_score(s) for s in by_created(
        [s for s in store.jury_scores.values() if s["vendor_application_id"] == app_rec["id"]])]
    return ok_list(recs)


@app.get("/jury-scores")
def list_jury_scores_filtered():
    _, role = auth()
    require(role, "EventCoordinator", "Juror", "Treasurer", "PlatformAdmin")
    recs = [serialize_jury_score(s) for s in by_created(store.jury_scores.values())]
    recs = apply_filters(recs, {"vendor_application_id": "vendor_application_id"})
    return ok_list(recs)


@app.get("/jury-scores/<score_id>")
def get_jury_score(score_id):
    _, role = auth()
    require(role, "EventCoordinator", "Juror", "Treasurer", "PlatformAdmin")
    s = get_or_404("jury_scores", score_id, "JuryScore")
    return ok(serialize_jury_score(s))


# ===========================================================================
# BoothAssignment & BoothFeeCharge
# ===========================================================================


@app.get("/maker-events/<event_id>/assignments")
def list_assignments(event_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Vendor", "PlatformAdmin")
    ev = get_event_or_404(event_id)
    recs = [serialize_assignment(x) for x in by_created(event_assignments(ev["id"]))]
    recs = apply_filters(recs, {
        "status": "status",
        "booth_id": "booth_id",
        "vendor_application_id": "vendor_application_id",
    })
    return ok_list(recs)


@app.get("/maker-events/<event_id>/assignments/<assignment_id>")
def get_assignment(event_id, assignment_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Vendor", "PlatformAdmin")
    ev = get_event_or_404(event_id)
    asg = get_assignment_in_event(ev, assignment_id)
    return ok(serialize_assignment(asg))


@app.get("/booth-assignments/<assignment_id>")
def get_assignment_canonical(assignment_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Vendor", "PlatformAdmin")
    asg = get_or_404("assignments", assignment_id, "BoothAssignment")
    return ok(serialize_assignment(asg))


@app.get("/booth-assignments")
def list_assignments_filtered():
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Vendor", "PlatformAdmin")
    recs = [serialize_assignment(x) for x in by_created(store.assignments.values())]
    recs = apply_filters(recs, {
        "booth_id": "booth_id",
        "vendor_application_id": "vendor_application_id",
        "status": "status",
    })
    return ok_list(recs)


@app.post("/maker-events/<event_id>/assignments/<assignment_id>/pay")
def pay_assignment(event_id, assignment_id):
    uid, role = auth()
    require(role, "Vendor")
    ev = get_event_or_404(event_id)
    asg = get_assignment_in_event(ev, assignment_id)
    posture_gate(ev, ("SCHEDULING", "LIVE", "WEATHER_HOLD"))
    if asg["status"] != "PENDING_PAYMENT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Assignment status %s cannot be paid." % asg["status"])
    if assignment_vendor_id(asg) != uid:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Only the owning vendor may pay for this assignment.")
    vendor = store.vendors.get(assignment_vendor_id(asg))
    if vendor is not None and vendor["status"] == "SUSPENDED":
        raise ApiError("ERR_VENDOR_SUSPENDED", 409, "Vendor is suspended.")
    due = parse_dt(asg["payment_due_at"])
    if due is not None and store.clock > due:
        raise ApiError("ERR_PAYMENT_WINDOW_EXPIRED", 409,
                       "The payment window has expired.")
    if booth_occupied(asg["booth_id"], exclude_assignment_id=asg["id"]):
        raise ApiError("ERR_BOOTH_DOUBLE_BOOKED", 409,
                       "Another assignment already occupies this booth.")
    booth = booth_of(asg)
    mint_charge(asg["id"], "FINAL", booth_fee_final(booth), "sum_then_round")
    asg["status"] = "ACTIVE"
    touch(asg)
    if booth is not None:
        booth["assigned_application_id"] = asg["vendor_application_id"]
        touch(booth)
    return ok(serialize_assignment(asg))


@app.post("/maker-events/<event_id>/assignments/<assignment_id>/forfeit")
def forfeit_assignment_endpoint(event_id, assignment_id):
    uid, role = auth()
    require(role, "Vendor", "EventCoordinator")
    ev = get_event_or_404(event_id)
    if ev["posture"] in TERMINAL_POSTURES:
        posture_gate(ev, ())
    asg = get_assignment_in_event(ev, assignment_id)
    if asg["status"] not in ("PENDING_PAYMENT", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Assignment status %s cannot be forfeited." % asg["status"])
    if role == "Vendor" and assignment_vendor_id(asg) != uid:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Only the owning vendor may forfeit this assignment.")
    forfeit_assignment(asg, event=ev)
    return ok(serialize_assignment(asg))


@app.post("/maker-events/<event_id>/assignments/<assignment_id>/release")
def release_assignment(event_id, assignment_id):
    _, role = auth()
    require(role, "EventCoordinator")
    ev = get_event_or_404(event_id)
    asg = get_assignment_in_event(ev, assignment_id)
    posture_gate(ev, ("SCHEDULING",))
    if asg["status"] != "PENDING_PAYMENT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PENDING_PAYMENT assignment can be released.")
    asg["status"] = "RELEASED"
    touch(asg)
    booth = booth_of(asg)
    if booth is not None and booth.get("assigned_application_id") == asg["vendor_application_id"]:
        booth["assigned_application_id"] = None
        touch(booth)
    app_rec = store.applications.get(asg["vendor_application_id"])
    waitlist_promotion_scan(ev, category=app_rec["requested_category"] if app_rec else None)
    return ok(serialize_assignment(asg))


@app.post("/maker-events/<event_id>/assignments/<assignment_id>/confirm")
def confirm_assignment(event_id, assignment_id):
    uid, role = auth()
    require(role, "Vendor")
    ev = get_event_or_404(event_id)
    asg = get_assignment_in_event(ev, assignment_id)
    posture_gate(ev, ("SCHEDULING", "LIVE", "WEATHER_HOLD"))
    app_rec = store.applications.get(asg["vendor_application_id"])
    if app_rec is None or app_rec["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Application is not in APPROVED state.")
    if app_rec["vendor_profile_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Only the owning vendor may confirm this application.")
    if asg["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Assignment must be ACTIVE before confirmation.")
    vendor = store.vendors.get(app_rec["vendor_profile_id"])
    if vendor is not None and vendor["status"] == "SUSPENDED":
        raise ApiError("ERR_VENDOR_SUSPENDED", 409, "Vendor is suspended.")
    app_rec["status"] = "CONFIRMED"
    touch(app_rec)
    return ok(serialize_application(app_rec))


@app.get("/maker-events/<event_id>/assignments/<assignment_id>/charges")
def list_charges(event_id, assignment_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Vendor", "PlatformAdmin")
    ev = get_event_or_404(event_id)
    asg = get_assignment_in_event(ev, assignment_id)
    recs = [serialize_charge(c) for c in charges_for_assignment(asg["id"])]
    return ok_list(recs)


@app.get("/booth-fee-charges")
def list_charges_filtered():
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Vendor", "PlatformAdmin")
    recs = [serialize_charge(c) for c in by_created(store.charges.values())]
    recs = apply_filters(recs, {"booth_assignment_id": "booth_assignment_id"})
    return ok_list(recs)


@app.get("/booth-fee-charges/<charge_id>")
def get_charge(charge_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Vendor", "PlatformAdmin")
    c = get_or_404("charges", charge_id, "BoothFeeCharge")
    return ok(serialize_charge(c))


# ===========================================================================
# LoadInSlot
# ===========================================================================


@app.post("/maker-events/<event_id>/load-in-slots")
def create_slot(event_id):
    uid, role = auth()
    require(role, "Vendor", "EventCoordinator")
    ev = get_event_or_404(event_id)
    posture_gate(ev, ("SCHEDULING", "LIVE", "WEATHER_HOLD"))
    data = body()
    asg = get_or_404("assignments", req_str(data, "booth_assignment_id"), "BoothAssignment")
    app_rec = store.applications.get(asg["vendor_application_id"])
    if app_rec is None or app_rec["maker_event_id"] != ev["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "BoothAssignment not found in event.")
    if role == "Vendor" and app_rec["vendor_profile_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Vendors may only reserve slots for their own assignments.")
    kind = req_enum(data, "kind", SLOT_KINDS)
    starts = req_dt(data, "starts_at")
    ends = req_dt(data, "ends_at")
    bay = req_enum(data, "bay", BAYS)
    if not (starts < ends):
        invalid("starts_at must be strictly before ends_at.")
    for s in event_slots(ev["id"]):
        if s["bay"] != bay or s["kind"] != kind:
            continue
        if starts < s["_ends"] and s["_starts"] < ends:
            raise ApiError("ERR_SLOT_OVERLAP", 409,
                           "Slot conflicts with an existing reservation on bay %s." % bay)
    rec = {
        "maker_event_id": ev["id"],
        "booth_assignment_id": asg["id"],
        "kind": kind,
        "starts_at": fmt_ts(starts),
        "ends_at": fmt_ts(ends),
        "bay": bay,
        "_starts": starts,
        "_ends": ends,
    }
    stamp(rec)
    store.slots[rec["id"]] = rec
    return ok(serialize_slot(rec), 201)


@app.get("/maker-events/<event_id>/load-in-slots")
def list_slots(event_id):
    _, role = auth()
    require(role, "EventCoordinator", "Vendor", "PlatformAdmin")
    ev = get_event_or_404(event_id)
    recs = [serialize_slot(s) for s in by_created(event_slots(ev["id"]))]
    recs = apply_filters(recs, {
        "bay": "bay", "kind": "kind", "booth_assignment_id": "booth_assignment_id",
    })
    return ok_list(recs)


@app.get("/load-in-slots/<slot_id>")
def get_slot(slot_id):
    _, role = auth()
    require(role, "EventCoordinator", "Vendor", "PlatformAdmin")
    s = get_or_404("slots", slot_id, "LoadInSlot")
    return ok(serialize_slot(s))


@app.get("/load-in-slots")
def list_slots_filtered():
    _, role = auth()
    require(role, "EventCoordinator", "Vendor", "PlatformAdmin")
    recs = [serialize_slot(s) for s in by_created(store.slots.values())]
    recs = apply_filters(recs, {
        "maker_event_id": "maker_event_id", "booth_assignment_id": "booth_assignment_id",
    })
    return ok_list(recs)


# ===========================================================================
# Ticket & Attendance
# ===========================================================================


@app.post("/maker-events/<event_id>/tickets")
def create_ticket(event_id):
    _, role = auth()
    require(role, "EventCoordinator", "PlatformAdmin")
    ev = get_event_or_404(event_id)
    posture_gate(ev, ("PLANNING", "APPLICATION_OPEN", "JURY_REVIEW", "SCHEDULING",
                      "LIVE", "WEATHER_HOLD", "SETTLEMENT"))
    data = body()
    rec = {
        "maker_event_id": ev["id"],
        "purchaser_email": req_str(data, "purchaser_email"),
        "kind": req_enum(data, "kind", TICKET_KINDS),
        "price_cents": req_int(data, "price_cents"),
        "state": "ISSUED",
        "redeemed_at": None,
    }
    stamp(rec)
    store.tickets[rec["id"]] = rec
    return ok(serialize_ticket(rec), 201)


@app.get("/maker-events/<event_id>/tickets")
def list_tickets(event_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "GateAgent", "PlatformAdmin")
    ev = get_event_or_404(event_id)
    recs = [serialize_ticket(t) for t in by_created(event_tickets(ev["id"]))]
    recs = apply_filters(recs, {"state": "state", "kind": "kind"})
    return ok_list(recs)


@app.get("/maker-events/<event_id>/tickets/<ticket_id>")
def get_ticket(event_id, ticket_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "GateAgent", "PlatformAdmin")
    ev = get_event_or_404(event_id)
    t = get_ticket_in_event(ev, ticket_id)
    return ok(serialize_ticket(t))


@app.get("/tickets/<ticket_id>")
def get_ticket_canonical(ticket_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "GateAgent", "PlatformAdmin")
    t = get_or_404("tickets", ticket_id, "Ticket")
    return ok(serialize_ticket(t))


@app.get("/tickets")
def list_tickets_filtered():
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "GateAgent", "PlatformAdmin")
    recs = [serialize_ticket(t) for t in by_created(store.tickets.values())]
    recs = apply_filters(recs, {"maker_event_id": "maker_event_id"})
    return ok_list(recs)


def effective_occupancy(event_id):
    onsite = 0
    vip_onsite = 0
    for a in event_attendance(event_id):
        if a["exited_at"] is not None:
            continue
        onsite += 1
        t = store.tickets.get(a["ticket_id"])
        if t is not None and t["kind"] == "VIP":
            vip_onsite += 1
    return onsite + vip_onsite


@app.post("/maker-events/<event_id>/tickets/<ticket_id>/redeem")
def redeem_ticket(event_id, ticket_id):
    _, role = auth()
    require(role, "GateAgent")
    ev = get_event_or_404(event_id)
    t = get_ticket_in_event(ev, ticket_id)
    posture_gate(ev, ("LIVE",))
    if t["state"] != "ISSUED" or ev["weather_flag"] == "SEVERE":
        raise ApiError("ERR_TICKET_NOT_REDEEMABLE", 409,
                       "Ticket is not redeemable at this time.")
    if effective_occupancy(ev["id"]) >= ev["venue_capacity"]:
        raise ApiError("ERR_VENUE_AT_CAPACITY", 409,
                       "Venue is at capacity.")
    t["state"] = "REDEEMED"
    t["redeemed_at"] = fmt_ts(store.clock)
    touch(t)
    att = {
        "maker_event_id": ev["id"],
        "ticket_id": t["id"],
        "entered_at": fmt_ts(store.clock),
        "exited_at": None,
    }
    stamp_light(att)
    store.attendance[att["id"]] = att
    return ok(serialize_ticket(t))


@app.post("/maker-events/<event_id>/tickets/<ticket_id>/refund")
def refund_ticket(event_id, ticket_id):
    _, role = auth()
    require(role, "EventCoordinator")
    ev = get_event_or_404(event_id)
    t = get_ticket_in_event(ev, ticket_id)
    data = body()
    reason = data.get("reason")
    allowed = False
    if t["state"] == "ISSUED":
        if ev["posture"] in ("PLANNING", "APPLICATION_OPEN", "JURY_REVIEW",
                             "SCHEDULING", "WEATHER_HOLD") or reason == "EVENT_CANCELLED":
            allowed = True
    elif t["state"] == "REDEEMED":
        att = None
        for a in event_attendance(ev["id"]):
            if a["ticket_id"] == t["id"]:
                att = a
        if att is not None and att["exited_at"] is not None and reason == "EVENT_CANCELLED":
            allowed = True
    if not allowed:
        raise ApiError("ERR_TICKET_NOT_REFUNDABLE", 409,
                       "Ticket state and reason do not permit refund.")
    t["state"] = "REFUNDED"
    touch(t)
    return ok(serialize_ticket(t))


@app.get("/maker-events/<event_id>/attendance")
def list_attendance(event_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "GateAgent", "PlatformAdmin")
    ev = get_event_or_404(event_id)
    recs = [serialize_attendance(a) for a in by_created(event_attendance(ev["id"]))]
    recs = apply_filters(recs, {"ticket_id": "ticket_id"})
    on_site = request_arg_bool("on_site")
    if on_site is not None:
        if on_site:
            recs = [r for r in recs if r["exited_at"] is None]
        else:
            recs = [r for r in recs if r["exited_at"] is not None]
    return ok_list(recs)


def request_arg_bool(name):
    from flask import request as flask_request
    v = flask_request.args.get(name)
    if v is None:
        return None
    return v.lower() in ("true", "1", "yes")


@app.get("/attendance/<attendance_id>")
def get_attendance(attendance_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "GateAgent", "PlatformAdmin")
    a = get_or_404("attendance", attendance_id, "Attendance")
    return ok(serialize_attendance(a))


@app.get("/attendance")
def list_attendance_filtered():
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "GateAgent", "PlatformAdmin")
    recs = [serialize_attendance(a) for a in by_created(store.attendance.values())]
    recs = apply_filters(recs, {"maker_event_id": "maker_event_id", "ticket_id": "ticket_id"})
    return ok_list(recs)


@app.post("/maker-events/<event_id>/attendance/<attendance_id>/exit")
def exit_attendance(event_id, attendance_id):
    _, role = auth()
    require(role, "GateAgent")
    ev = get_event_or_404(event_id)
    a = get_attendance_in_event(ev, attendance_id)
    if a["exited_at"] is not None:
        raise ApiError("ERR_INVALID_STATE", 409, "Attendance row already has an exit scan.")
    a["exited_at"] = fmt_ts(store.clock)
    return ok(serialize_attendance(a))


# ===========================================================================
# SalesLedgerEntry
# ===========================================================================


@app.post("/maker-events/<event_id>/sales-ledger")
def create_sale(event_id):
    uid, role = auth()
    require(role, "Vendor")
    ev = get_event_or_404(event_id)
    posture_gate(ev, ("LIVE", "WEATHER_HOLD"))
    data = body()
    asg = get_or_404("assignments", req_str(data, "booth_assignment_id"), "BoothAssignment")
    app_rec = store.applications.get(asg["vendor_application_id"])
    if app_rec is None or app_rec["maker_event_id"] != ev["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "BoothAssignment not found in event.")
    if app_rec["vendor_profile_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Vendors may only post ledger entries for their own assignments.")
    gross = req_int(data, "gross_cents")
    rev_of = data.get("reversal_of_entry_id")
    if rev_of is not None:
        orig = get_or_404("sales", rev_of, "SalesLedgerEntry")
        if orig["booth_assignment_id"] != asg["id"]:
            raise ApiError("ERR_INVALID_INPUT", 400,
                           "reversal_of_entry_id must reference an entry of the same assignment.")
        if gross >= 0:
            raise ApiError("ERR_INVALID_INPUT", 400,
                           "A compensation row must carry a negative gross_cents.")
    rec = {
        "maker_event_id": ev["id"],
        "booth_assignment_id": asg["id"],
        "gross_cents": gross,
        "recorded_at": fmt_ts(store.clock),
        "reversal_of_entry_id": rev_of,
    }
    stamp_light(rec)
    store.sales[rec["id"]] = rec
    return ok(serialize_sale(rec), 201)


@app.get("/maker-events/<event_id>/sales-ledger")
def list_sales(event_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Vendor", "PlatformAdmin")
    ev = get_event_or_404(event_id)
    recs = [serialize_sale(s) for s in by_created(event_sales(ev["id"]))]
    recs = apply_filters(recs, {"booth_assignment_id": "booth_assignment_id"})
    return ok_list(recs)


@app.get("/sales-ledger-entries/<entry_id>")
def get_sale(entry_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Vendor", "PlatformAdmin")
    s = get_or_404("sales", entry_id, "SalesLedgerEntry")
    return ok(serialize_sale(s))


@app.get("/sales-ledger-entries")
def list_sales_filtered():
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Vendor", "PlatformAdmin")
    recs = [serialize_sale(s) for s in by_created(store.sales.values())]
    recs = apply_filters(recs, {
        "maker_event_id": "maker_event_id",
        "booth_assignment_id": "booth_assignment_id",
        "reversal_of_entry_id": "reversal_of_entry_id",
    })
    return ok_list(recs)


# ===========================================================================
# Settlement
# ===========================================================================


@app.get("/maker-events/<event_id>/settlements")
def list_settlements(event_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Vendor", "PlatformAdmin")
    ev = get_event_or_404(event_id)
    recs = [serialize_settlement(s) for s in by_created(event_settlements(ev["id"]))]
    recs = apply_filters(recs, {"status": "status", "booth_assignment_id": "booth_assignment_id"})
    return ok_list(recs)


@app.get("/maker-events/<event_id>/settlements/<settlement_id>")
def get_settlement(event_id, settlement_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Vendor", "PlatformAdmin")
    ev = get_event_or_404(event_id)
    st = get_settlement_in_event(ev, settlement_id)
    return ok(serialize_settlement(st))


@app.get("/settlements/<settlement_id>")
def get_settlement_canonical(settlement_id):
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Vendor", "PlatformAdmin")
    st = get_or_404("settlements", settlement_id, "Settlement")
    return ok(serialize_settlement(st))


@app.get("/settlements")
def list_settlements_filtered():
    _, role = auth()
    require(role, "EventCoordinator", "Treasurer", "Vendor", "PlatformAdmin")
    recs = [serialize_settlement(s) for s in by_created(store.settlements.values())]
    recs = apply_filters(recs, {"booth_assignment_id": "booth_assignment_id", "status": "status"})
    return ok_list(recs)


def compute_settlement_fields(st):
    asg = store.assignments.get(st["booth_assignment_id"])
    st["gross_sales_cents"] = settlement_gross_quote(st["booth_assignment_id"])
    st["commission_cents"] = commission_quote(st["booth_assignment_id"])
    outstanding = outstanding_booth_fee(asg) if asg is not None else 0
    st["net_payout_cents"] = st["gross_sales_cents"] - st["commission_cents"] - outstanding


@app.post("/maker-events/<event_id>/settlements/<settlement_id>/compute")
def compute_settlement(event_id, settlement_id):
    _, role = auth()
    require(role, "Treasurer")
    ev = get_event_or_404(event_id)
    st = get_settlement_in_event(ev, settlement_id)
    posture_gate(ev, ("SETTLEMENT",))
    if st["status"] not in ("PENDING", "DISPUTED"):
        raise ApiError("ERR_SETTLEMENT_NOT_COMPUTABLE", 409,
                       "Settlement status %s cannot be computed." % st["status"])
    compute_settlement_fields(st)
    st["status"] = "COMPUTED"
    touch(st)
    return ok(serialize_settlement(st))


@app.post("/maker-events/<event_id>/settlements/<settlement_id>/approve")
def approve_settlement(event_id, settlement_id):
    uid, role = auth()
    require(role, "Treasurer")
    ev = get_event_or_404(event_id)
    st = get_settlement_in_event(ev, settlement_id)
    if st["status"] != "COMPUTED":
        raise ApiError("ERR_SETTLEMENT_NOT_APPROVABLE", 409,
                       "Settlement status %s cannot be approved." % st["status"])
    if uid == ev["_created_by"]:
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "Settlement approver must differ from the event creator.")
    data = body()
    expected = data.get("expected_settlement_version")
    if isinstance(expected, str) and expected.isdigit():
        expected = int(expected)
    if isinstance(expected, bool) or (expected is not None and not isinstance(expected, int)):
        invalid("Field 'expected_settlement_version' must be an integer.")
    if expected != st["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_settlement_version does not match the current settlement version.")
    st["approved_by_user_id"] = uid
    st["status"] = "APPROVED"
    touch(st)
    return ok(serialize_settlement(st))


@app.post("/maker-events/<event_id>/settlements/<settlement_id>/dispute")
def dispute_settlement(event_id, settlement_id):
    uid, role = auth()
    require(role, "Vendor")
    ev = get_event_or_404(event_id)
    st = get_settlement_in_event(ev, settlement_id)
    if st["status"] != "COMPUTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Settlement status %s cannot be disputed." % st["status"])
    asg = store.assignments.get(st["booth_assignment_id"])
    if assignment_vendor_id(asg) != uid:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Only the vendor behind this settlement may dispute it.")
    st["status"] = "DISPUTED"
    touch(st)
    return ok(serialize_settlement(st))


@app.post("/maker-events/<event_id>/settlements/<settlement_id>/mark-paid")
def mark_paid_settlement(event_id, settlement_id):
    _, role = auth()
    require(role, "Treasurer")
    ev = get_event_or_404(event_id)
    st = get_settlement_in_event(ev, settlement_id)
    if st["status"] != "APPROVED":
        raise ApiError("ERR_SETTLEMENT_NOT_PAYABLE", 409,
                       "Settlement status %s cannot be marked paid." % st["status"])
    st["commission_cents"] = commission_final(st["booth_assignment_id"])
    st["status"] = "PAID"
    touch(st)
    return ok(serialize_settlement(st))


@app.post("/maker-events/<event_id>/settlements/<settlement_id>/cancel")
def cancel_settlement(event_id, settlement_id):
    _, role = auth()
    require(role, "Treasurer")
    ev = get_event_or_404(event_id)
    st = get_settlement_in_event(ev, settlement_id)
    if st["status"] not in ("PENDING", "COMPUTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Settlement status %s cannot be cancelled." % st["status"])
    st["status"] = "CANCELLED"
    touch(st)
    return ok(serialize_settlement(st))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
