"""Routes: contamination tickets, chipping runs, mulch events/claims,
volunteers, volunteer shifts, diversion reports, logical clock."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from domain import (
    adjudicate_upheld,
    allocation_key,
    common_new,
    claim_json,
    compute_yield,
    derive_tier,
    diversion_rollup,
    event_json,
    expire_event_claims,
    get_or_404,
    mark_no_show,
    notify,
    promotion_sweep,
    release_claim_allocation,
    recompute_strikes,
    report_json,
    resolve_overturned,
    run_json,
    shift_json,
    site_stockpile_cy,
    sorted_asc,
    ticket_json,
    touch,
    try_allocate,
    volunteer_json,
)
from http_util import (
    ApiError,
    auth,
    body,
    forbidden,
    occ_field,
    ok,
    paged,
    req_field,
    v_bool,
    v_dec,
    v_dt,
    v_enum,
    v_int,
    v_str,
)
from state import (
    DB,
    MATERIAL_CLASSES,
    MIN_CLAIM_CY,
    SHIFT_ROLES,
    SIZE_CLASSES,
    TICKET_CATEGORIES,
    clock_now,
    fmt_dt,
    new_id,
    parse_dt,
    set_clock,
)

bp = Blueprint("ops", __name__)

TICKET_STATUSES = ("OPEN", "UPHELD", "DISMISSED", "APPEALED", "UPHELD_FINAL", "OVERTURNED")
RUN_STATUSES = ("SCHEDULED", "COMPLETED", "CANCELLED")
EVENT_STATUSES = ("SCHEDULED", "OPEN", "CLOSED")
CLAIM_STATUSES = ("CONFIRMED", "WAITLISTED", "FULFILLED", "CANCELLED", "EXPIRED")
VOLUNTEER_STATUSES = ("APPLIED", "APPROVED", "SUSPENDED")
SHIFT_STATUSES = ("SIGNED_UP", "COMPLETED", "NO_SHOW", "CANCELLED")
REPORT_STATUSES = ("DRAFT", "PUBLISHED", "SUPERSEDED")


# ===========================================================================
# Contamination tickets
# ===========================================================================
@bp.post("/contamination-tickets")
def create_ticket():
    uid, role = auth(["ProgramAdmin", "SiteSupervisor", "Volunteer"])
    data = body()
    program_id = v_str(req_field(data, "program_id"), "program_id")
    category = v_enum(req_field(data, "category"), "category", TICKET_CATEGORIES)
    notes = data.get("notes")
    if notes is not None:
        v_str(notes, "notes")
    booking_id = data.get("booking_id")
    site_id = data.get("site_id")

    program = get_or_404("programs", program_id)
    booking = None
    site = None
    if booking_id is not None:
        booking = get_or_404("bookings", booking_id)
    if site_id is not None:
        site = get_or_404("sites", site_id)

    # Referential coherence (priority 8): exactly one source, in-program.
    if (booking_id is None) == (site_id is None):
        raise ApiError(
            "ERR_TICKET_SOURCE_INVALID",
            422,
            "Ticket must reference exactly one of booking_id or site_id",
        )
    if booking is not None:
        zone = DB["zones"].get(booking["zone_id"])
        if zone is None or zone["program_id"] != program_id:
            raise ApiError(
                "ERR_TICKET_SOURCE_INVALID",
                422,
                "Ticket source must belong to the given program",
            )
    else:
        if site["program_id"] != program_id:
            raise ApiError(
                "ERR_TICKET_SOURCE_INVALID",
                422,
                "Ticket source must belong to the given program",
            )

    # Business constraints (priority 10)
    if booking is not None and booking["status"] not in ("CONFIRMED", "SERVICED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "A booking-linked ticket requires the booking to be CONFIRMED or SERVICED",
        )
    for t in DB["tickets"].values():
        if t["status"] != "OPEN":
            continue
        if booking_id is not None and t["booking_id"] == booking_id:
            raise ApiError(
                "ERR_DUPLICATE_TICKET",
                409,
                "An OPEN ticket already exists for this booking",
            )
        if site_id is not None and t["site_id"] == site_id:
            raise ApiError(
                "ERR_DUPLICATE_TICKET", 409, "An OPEN ticket already exists for this site"
            )

    t = {
        "id": new_id(),
        "program_id": program_id,
        "booking_id": booking_id,
        "site_id": site_id,
        "category": category,
        "notes": notes,
        "reporter_user_id": uid,
        "reporter_role": role,
        "status": "OPEN",
        "adjudicated_by": None,
        "adjudicated_at": None,
        "appeal_deadline": None,
        "resolved_by": None,
    }
    common_new(t)
    DB["tickets"][t["id"]] = t
    touch(program)  # open_ticket_count incremented; posture recomputed
    return ok(ticket_json(t), status=201)


@bp.get("/contamination-tickets")
def list_tickets():
    auth(["ProgramAdmin", "SiteSupervisor"])
    program_id = request.args.get("program_id")
    booking_id = request.args.get("booking_id")
    site_id = request.args.get("site_id")
    status = request.args.get("status")
    items = list(DB["tickets"].values())
    if program_id is not None:
        items = [t for t in items if t["program_id"] == program_id]
    if booking_id is not None:
        items = [t for t in items if t["booking_id"] == booking_id]
    if site_id is not None:
        items = [t for t in items if t["site_id"] == site_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return paged([ticket_json(t) for t in sorted_asc(items)])


@bp.get("/contamination-tickets/<tid>")
def get_ticket(tid):
    auth(["ProgramAdmin", "SiteSupervisor", "Resident", "Volunteer"])
    return ok(ticket_json(get_or_404("tickets", tid)))


@bp.post("/contamination-tickets/<tid>/adjudicate")
def adjudicate_ticket(tid):
    uid, role = auth(["ProgramAdmin", "SiteSupervisor"])
    t = get_or_404("tickets", tid)
    data = body()
    verdict = v_enum(req_field(data, "verdict"), "verdict", ("UPHELD", "DISMISSED"))
    if t["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only an OPEN ticket can be adjudicated"
        )
    # Segregation of duties (binds ProgramAdmin too): adjudicator != reporter
    if uid == t["reporter_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "The adjudicator must differ from the ticket's reporter",
        )
    if verdict == "UPHELD":
        adjudicate_upheld(t, uid)
    else:
        program = DB["programs"][t["program_id"]]
        t["status"] = "DISMISSED"
        t["adjudicated_by"] = uid
        t["adjudicated_at"] = clock_now()
        touch(t)
        touch(program)  # open_ticket_count decremented; posture recomputed
    return ok(ticket_json(t))


@bp.post("/contamination-tickets/<tid>/appeal")
def appeal_ticket(tid):
    uid, role = auth(["Resident"])
    t = get_or_404("tickets", tid)
    # Ownership (priority 3): the ticket's household only.
    if t["booking_id"] is not None:
        booking = DB["bookings"].get(t["booking_id"])
        if booking is not None and booking["household_id"] != uid:
            forbidden("Resident may appeal only their own household's tickets")
    if t["status"] != "UPHELD":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an UPHELD ticket can be appealed")
    if t["booking_id"] is None:
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Site-linked tickets cannot be appealed"
        )
    if clock_now() > t["appeal_deadline"]:
        raise ApiError(
            "ERR_APPEAL_WINDOW_EXPIRED",
            422,
            "Appeal window (adjudicated_at + 72h, inclusive) has expired",
        )
    t["status"] = "APPEALED"
    touch(t)
    return ok(ticket_json(t))


@bp.post("/contamination-tickets/<tid>/resolve-appeal")
def resolve_ticket_appeal(tid):
    uid, role = auth(["ProgramAdmin"])
    t = get_or_404("tickets", tid)
    data = body()
    resolution = v_enum(
        req_field(data, "resolution"), "resolution", ("UPHELD_FINAL", "OVERTURNED")
    )
    if t["status"] != "APPEALED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only an APPEALED ticket can be resolved"
        )
    # Segregation of duties: resolver != original adjudicator
    if uid == t["adjudicated_by"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "The appeal resolver must differ from the original adjudicator",
        )
    if resolution == "UPHELD_FINAL":
        t["status"] = "UPHELD_FINAL"
        t["resolved_by"] = uid
        touch(t)
    else:
        resolve_overturned(t, uid)
    return ok(ticket_json(t))


# ===========================================================================
# Chipping runs
# ===========================================================================
@bp.post("/chipping-runs")
def create_run():
    auth(["ProgramAdmin"])
    data = body()
    program_id = v_str(req_field(data, "program_id"), "program_id")
    site_id = v_str(req_field(data, "site_id"), "site_id")
    scheduled_start = v_dt(req_field(data, "scheduled_start"), "scheduled_start")
    scheduled_end = v_dt(req_field(data, "scheduled_end"), "scheduled_end")
    material_class = v_enum(req_field(data, "material_class"), "material_class", MATERIAL_CLASSES)
    program = get_or_404("programs", program_id)
    site = get_or_404("sites", site_id)
    if site["program_id"] != program_id:
        raise ApiError("ERR_VALIDATION", 400, "site does not belong to the given program")
    # Processing window: [window_start, window_end + 14 days]
    window_lo = program["window_start"]
    window_hi = program["window_end"] + timedelta(days=14)
    if not (window_lo <= scheduled_start <= window_hi):
        raise ApiError(
            "ERR_RUN_WINDOW_INVALID", 422, "scheduled_start is outside the processing window"
        )
    if not (window_lo <= scheduled_end <= window_hi):
        raise ApiError(
            "ERR_RUN_WINDOW_INVALID", 422, "scheduled_end is outside the processing window"
        )
    if not (scheduled_end > scheduled_start):
        raise ApiError(
            "ERR_RUN_WINDOW_INVALID", 422, "scheduled_end must be later than scheduled_start"
        )
    # Overlap + 2h buffer against non-cancelled runs at the same site
    buffer = timedelta(hours=2)
    for other in DB["runs"].values():
        if other["site_id"] != site_id or other["status"] == "CANCELLED":
            continue
        if scheduled_start < other["scheduled_end"] + buffer and other[
            "scheduled_start"
        ] < scheduled_end + buffer:
            raise ApiError(
                "ERR_RUN_OVERLAP",
                409,
                "Chipping runs at one site must not overlap and must keep a 2h buffer",
            )
    r = {
        "id": new_id(),
        "program_id": program_id,
        "site_id": site_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "material_class": material_class,
        "status": "SCHEDULED",
        "input_cy": None,
        "measured_input_tons": None,
        "contaminated_input_tons": Decimal("0"),
        "theoretical_output_cy": None,
        "measured_output_cy": None,
        "variance_pct": None,
        "yield_review_confirmed": False,
    }
    common_new(r)
    DB["runs"][r["id"]] = r
    return ok(run_json(r), status=201)


@bp.get("/chipping-runs")
def list_runs():
    auth(["ProgramAdmin", "SiteSupervisor", "HaulerPartner"])
    program_id = request.args.get("program_id")
    site_id = request.args.get("site_id")
    status = request.args.get("status")
    items = list(DB["runs"].values())
    if program_id is not None:
        items = [r for r in items if r["program_id"] == program_id]
    if site_id is not None:
        items = [r for r in items if r["site_id"] == site_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paged([run_json(r) for r in sorted_asc(items)])


@bp.get("/chipping-runs/<rid>")
def get_run(rid):
    auth(["ProgramAdmin", "SiteSupervisor", "HaulerPartner"])
    return ok(run_json(get_or_404("runs", rid)))


@bp.post("/chipping-runs/<rid>/complete")
def complete_run(rid):
    auth(["ProgramAdmin", "HaulerPartner"])
    r = get_or_404("runs", rid)
    data = body()
    input_cy = v_dec(req_field(data, "input_cy"), "input_cy", lo=Decimal("0"))
    measured_input = v_dec(req_field(data, "measured_input_tons"), "measured_input_tons")
    contaminated = Decimal("0")
    if data.get("contaminated_input_tons") is not None:
        contaminated = v_dec(data["contaminated_input_tons"], "contaminated_input_tons")
    measured_output = v_dec(req_field(data, "measured_output_cy"), "measured_output_cy")
    review_confirmed = False
    if data.get("yield_review_confirmed") is not None:
        review_confirmed = v_bool(data["yield_review_confirmed"], "yield_review_confirmed")
    # Value validation (malformed -> ERR_VALIDATION 400)
    if measured_input <= 0:
        raise ApiError("ERR_VALIDATION", 400, "measured_input_tons must be greater than zero")
    if measured_output < 0:
        raise ApiError("ERR_VALIDATION", 400, "measured_output_cy must be non-negative")
    if contaminated < 0 or contaminated > measured_input:
        raise ApiError(
            "ERR_VALIDATION", 400, "contaminated_input_tons may not exceed measured_input_tons"
        )

    if r["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a SCHEDULED run can be completed")

    site = DB["sites"][r["site_id"]]
    program = DB["programs"][r["program_id"]]

    if clock_now() < r["scheduled_start"]:
        raise ApiError(
            "ERR_RUN_WINDOW_INVALID", 422, "Run cannot complete before its scheduled_start"
        )

    theoretical, raw_variance, variance_pct = compute_yield(
        r["material_class"], measured_input, contaminated, measured_output
    )
    if raw_variance > Decimal("0.08") and not review_confirmed:
        raise ApiError(
            "ERR_YIELD_VARIANCE_REVIEW_REQUIRED",
            422,
            "Yield variance above 8%% requires yield_review_confirmed=true",
        )

    # Capacity check (priority 11): input may not exceed the current stockpile
    if input_cy > site_stockpile_cy(r["site_id"]):
        raise ApiError(
            "ERR_RUN_INPUT_EXCEEDS_STOCKPILE",
            422,
            "input_cy may not exceed the site's current stockpile",
        )

    # Commit: store scale data, draw the stockpile, credit the pool, sweep
    r["status"] = "COMPLETED"
    r["input_cy"] = input_cy
    r["measured_input_tons"] = measured_input
    r["contaminated_input_tons"] = contaminated
    r["measured_output_cy"] = measured_output
    r["theoretical_output_cy"] = theoretical
    r["variance_pct"] = variance_pct
    r["yield_review_confirmed"] = review_confirmed
    touch(r)
    touch(site)  # stockpile_cy drawn down (derived)
    program["mulch_produced_cy"] += measured_output
    touch(program)  # pool credit + any promotions below (one bump)
    promotion_sweep(program)
    return ok(run_json(r))


@bp.post("/chipping-runs/<rid>/cancel")
def cancel_run(rid):
    auth(["ProgramAdmin"])
    r = get_or_404("runs", rid)
    if r["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a SCHEDULED run can be cancelled")
    r["status"] = "CANCELLED"
    touch(r)
    return ok(run_json(r))


# ===========================================================================
# Mulch events
# ===========================================================================
@bp.post("/mulch-events")
def create_event():
    auth(["ProgramAdmin"])
    data = body()
    program_id = v_str(req_field(data, "program_id"), "program_id")
    name = v_str(req_field(data, "name"), "name")
    claim_open_at = v_dt(req_field(data, "claim_open_at"), "claim_open_at")
    claim_close_at = v_dt(req_field(data, "claim_close_at"), "claim_close_at")
    pickup_start = v_dt(req_field(data, "pickup_start"), "pickup_start")
    pickup_end = v_dt(req_field(data, "pickup_end"), "pickup_end")
    cap = Decimal("2.0")
    if data.get("per_household_cap_cy") is not None:
        cap = v_dec(data["per_household_cap_cy"], "per_household_cap_cy", lo=Decimal("0.01"))
    get_or_404("programs", program_id)
    if not (claim_close_at > claim_open_at):
        raise ApiError(
            "ERR_VALIDATION", 400, "claim_close_at must be later than claim_open_at"
        )
    if not (pickup_start >= claim_close_at):
        raise ApiError(
            "ERR_VALIDATION", 400, "pickup_start must be no earlier than claim_close_at"
        )
    if not (pickup_end > pickup_start):
        raise ApiError("ERR_VALIDATION", 400, "pickup_end must be later than pickup_start")
    e = {
        "id": new_id(),
        "program_id": program_id,
        "name": name,
        "claim_open_at": claim_open_at,
        "claim_close_at": claim_close_at,
        "pickup_start": pickup_start,
        "pickup_end": pickup_end,
        "per_household_cap_cy": cap,
        "status": "SCHEDULED",
    }
    common_new(e)
    DB["events"][e["id"]] = e
    return ok(event_json(e), status=201)


@bp.get("/mulch-events")
def list_events():
    auth(["ProgramAdmin", "SiteSupervisor", "Resident", "Volunteer"])
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = list(DB["events"].values())
    if program_id is not None:
        items = [e for e in items if e["program_id"] == program_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return paged([event_json(e) for e in sorted_asc(items)])


@bp.get("/mulch-events/<eid>")
def get_event(eid):
    auth(["ProgramAdmin", "SiteSupervisor", "Resident", "Volunteer"])
    return ok(event_json(get_or_404("events", eid)))


@bp.patch("/mulch-events/<eid>")
def patch_event(eid):
    auth(["ProgramAdmin"])
    e = get_or_404("events", eid)
    data = body()
    new_status = v_enum(req_field(data, "status"), "status", EVENT_STATUSES)
    declared = {("SCHEDULED", "OPEN"), ("OPEN", "CLOSED")}
    if (e["status"], new_status) not in declared:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Event status transition %s -> %s is not declared" % (e["status"], new_status),
        )
    program = DB["programs"][e["program_id"]]
    if new_status == "OPEN":
        if program["status"] != "ACTIVE":
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Event can open only while its program is ACTIVE",
            )
        e["status"] = "OPEN"
        notify(
            e["program_id"],
            "MULCH_EVENT_OPENED",
            message="Mulch event %s is open for claims." % e["name"],
        )
    else:  # CLOSED
        e["status"] = "CLOSED"
        released = expire_event_claims(e)
        promoted = promotion_sweep(program)
        if released or promoted:
            touch(program)  # tier allocation counters changed
    touch(e)
    return ok(event_json(e))


# ===========================================================================
# Mulch claims
# ===========================================================================
@bp.post("/mulch-claims")
def create_claim():
    uid, role = auth(["Resident", "ProgramAdmin"])
    data = body()
    event_id = req_field(data, "event_id")
    household_id = req_field(data, "household_id")
    requested = v_dec(req_field(data, "requested_cy"), "requested_cy")

    # Ownership (priority 3)
    if role == "Resident" and household_id != uid:
        forbidden("Resident may claim only for their own household")

    event = get_or_404("events", event_id)
    household = get_or_404("households", household_id)

    # Referential coherence (priority 8): household and event share a program
    if household["program_id"] != event["program_id"]:
        raise ApiError(
            "ERR_VALIDATION", 400, "household and event must belong to the same program"
        )

    # Temporal gate (priority 9): claim window inclusive of both ends
    now = clock_now()
    if not (event["claim_open_at"] <= now <= event["claim_close_at"]):
        raise ApiError(
            "ERR_CLAIM_WINDOW_INVALID",
            422,
            "Claim must be created within [claim_open_at, claim_close_at]",
        )

    # Business constraints (priority 10)
    if event["status"] != "OPEN":
        raise ApiError("ERR_EVENT_NOT_OPEN", 409, "Claims require an OPEN event")
    for c in DB["claims"].values():
        if (
            c["event_id"] == event_id
            and c["household_id"] == household_id
            and c["status"] in ("CONFIRMED", "WAITLISTED")
        ):
            raise ApiError(
                "ERR_DUPLICATE_CLAIM",
                409,
                "Household already has an active claim on this event",
            )

    # Capacity band (priority 11)
    if requested < MIN_CLAIM_CY or requested > event["per_household_cap_cy"]:
        raise ApiError(
            "ERR_CLAIM_CAP_EXCEEDED",
            422,
            "requested_cy must be at least 0.5 and at most the event's per_household_cap_cy",
        )

    program = DB["programs"][event["program_id"]]
    tier = derive_tier(household)
    allocated, status = try_allocate(program, event, tier, requested)
    c = {
        "id": new_id(),
        "event_id": event_id,
        "household_id": household_id,
        "requested_cy": requested,
        "tier": tier,
        "allocated_cy": allocated,
        "status": status,
    }
    common_new(c)
    DB["claims"][c["id"]] = c
    if status == "CONFIRMED":
        program[allocation_key(tier)] += allocated
        touch(program)  # tier allocation counter changed
    return ok(claim_json(c), status=201)


@bp.get("/mulch-claims")
def list_claims():
    auth(["ProgramAdmin", "SiteSupervisor"])
    event_id = request.args.get("event_id")
    household_id = request.args.get("household_id")
    status = request.args.get("status")
    items = list(DB["claims"].values())
    if event_id is not None:
        items = [c for c in items if c["event_id"] == event_id]
    if household_id is not None:
        items = [c for c in items if c["household_id"] == household_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paged([claim_json(c) for c in sorted_asc(items)])


@bp.get("/mulch-claims/<cid>")
def get_claim(cid):
    auth(["ProgramAdmin", "SiteSupervisor", "Resident"])
    return ok(claim_json(get_or_404("claims", cid)))


@bp.patch("/mulch-claims/<cid>")
def patch_claim(cid):
    uid, role = auth(["Resident", "SiteSupervisor", "ProgramAdmin"])
    data = body()
    new_status = v_enum(req_field(data, "status"), "status", CLAIM_STATUSES)
    # Per-transition role split (priority 2)
    if new_status == "FULFILLED" and role not in ("SiteSupervisor", "ProgramAdmin"):
        forbidden("Only SiteSupervisor or ProgramAdmin may mark a claim FULFILLED")
    if new_status == "CANCELLED" and role not in ("Resident", "ProgramAdmin"):
        forbidden("Only the owning Resident or ProgramAdmin may cancel a claim")
    c = get_or_404("claims", cid)
    # Ownership (priority 3) for the Resident cancellation path
    if role == "Resident" and new_status == "CANCELLED" and c["household_id"] != uid:
        forbidden("Resident may cancel only their own household's claims")
    # State legality (priority 5)
    declared = {("CONFIRMED", "FULFILLED"), ("CONFIRMED", "CANCELLED"), ("WAITLISTED", "CANCELLED")}
    if (c["status"], new_status) not in declared:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Claim transition %s -> %s is not declared" % (c["status"], new_status),
        )
    event = DB["events"][c["event_id"]]
    if new_status == "FULFILLED":
        now = clock_now()
        if not (event["pickup_start"] <= now <= event["pickup_end"]):
            raise ApiError(
                "ERR_PICKUP_WINDOW_CLOSED",
                422,
                "Fulfillment is valid only within [pickup_start, pickup_end]",
            )
        c["status"] = "FULFILLED"
        touch(c)
    else:  # CANCELLED
        was_confirmed = c["status"] == "CONFIRMED"
        program = DB["programs"][event["program_id"]]
        c["status"] = "CANCELLED"
        touch(c)
        if was_confirmed:
            release_claim_allocation(program, c)
            promotion_sweep(program)
            touch(program)  # release + any promotions (one bump)
    return ok(claim_json(c))


# ===========================================================================
# Volunteers
# ===========================================================================
@bp.post("/volunteers")
def create_volunteer():
    auth(["Anonymous", "ProgramAdmin"])
    data = body()
    program_id = v_str(req_field(data, "program_id"), "program_id")
    full_name = v_str(req_field(data, "full_name"), "full_name")
    email = v_str(req_field(data, "email"), "email")
    program = get_or_404("programs", program_id)
    if program["status"] == "CLOSED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Volunteer registration is refused once the program is CLOSED",
        )
    v = {
        "id": new_id(),
        "program_id": program_id,
        "full_name": full_name,
        "email": email,
        "status": "APPLIED",
        "no_show_count": 0,
    }
    common_new(v)
    DB["volunteers"][v["id"]] = v
    return ok(volunteer_json(v), status=201)


@bp.get("/volunteers")
def list_volunteers():
    auth(["ProgramAdmin", "SiteSupervisor"])
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = list(DB["volunteers"].values())
    if program_id is not None:
        items = [v for v in items if v["program_id"] == program_id]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    return paged([volunteer_json(v) for v in sorted_asc(items)])


@bp.get("/volunteers/<vid>")
def get_volunteer(vid):
    auth(["ProgramAdmin", "SiteSupervisor", "Volunteer"])
    return ok(volunteer_json(get_or_404("volunteers", vid)))


@bp.patch("/volunteers/<vid>")
def patch_volunteer(vid):
    auth(["ProgramAdmin"])
    v = get_or_404("volunteers", vid)
    data = body()
    new_status = v_enum(req_field(data, "status"), "status", VOLUNTEER_STATUSES)
    declared = {
        ("APPLIED", "APPROVED"),
        ("APPROVED", "SUSPENDED"),
        ("SUSPENDED", "APPROVED"),
    }
    if (v["status"], new_status) not in declared:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Volunteer transition %s -> %s is not declared" % (v["status"], new_status),
        )
    v["status"] = new_status
    touch(v)
    return ok(volunteer_json(v))


# ===========================================================================
# Volunteer shifts
# ===========================================================================
@bp.post("/volunteer-shifts")
def create_shift():
    uid, role = auth(["Volunteer", "ProgramAdmin"])
    data = body()
    volunteer_id = req_field(data, "volunteer_id")
    site_id = req_field(data, "site_id")
    start_at = v_dt(req_field(data, "start_at"), "start_at")
    end_at = v_dt(req_field(data, "end_at"), "end_at")
    shift_role = v_enum(req_field(data, "shift_role"), "shift_role", SHIFT_ROLES)

    # Ownership (priority 3)
    if role == "Volunteer" and volunteer_id != uid:
        forbidden("Volunteer may sign up only for themselves")

    if not (end_at > start_at):
        raise ApiError("ERR_VALIDATION", 400, "end_at must be later than start_at")

    volunteer = get_or_404("volunteers", volunteer_id)
    site = get_or_404("sites", site_id)

    # Referential coherence (priority 8)
    if volunteer["program_id"] != site["program_id"]:
        raise ApiError(
            "ERR_VALIDATION", 400, "volunteer and site must belong to the same program"
        )
    program = DB["programs"][volunteer["program_id"]]
    if not (program["window_start"] <= start_at and end_at <= program["window_end"]):
        raise ApiError(
            "ERR_VALIDATION", 400, "Shift must lie inside the program window"
        )

    # Business constraints (priority 10)
    if volunteer["status"] != "APPROVED":
        raise ApiError(
            "ERR_VOLUNTEER_NOT_APPROVED",
            409,
            "Shift signup requires an APPROVED volunteer",
        )
    # Personal overlap: half-open [start_at, end_at) against SIGNED_UP/COMPLETED
    for s in DB["shifts"].values():
        if (
            s["volunteer_id"] == volunteer_id
            and s["status"] in ("SIGNED_UP", "COMPLETED")
            and start_at < s["end_at"]
            and s["start_at"] < end_at
        ):
            raise ApiError(
                "ERR_SHIFT_OVERLAP",
                409,
                "Volunteer already has a shift overlapping this interval",
            )

    # Capacity (priority 11): site / calendar date / role occupancy
    occupancy = 0
    for s in DB["shifts"].values():
        if (
            s["site_id"] == site_id
            and s["status"] in ("SIGNED_UP", "COMPLETED")
            and s["shift_role"] == shift_role
            and s["start_at"].date() == start_at.date()
        ):
            occupancy += 1
    if occupancy >= site["volunteer_slots_per_role"]:
        raise ApiError(
            "ERR_SHIFT_CAPACITY_FULL",
            422,
            "Site/date/role occupancy has reached volunteer_slots_per_role",
        )

    s = {
        "id": new_id(),
        "volunteer_id": volunteer_id,
        "site_id": site_id,
        "start_at": start_at,
        "end_at": end_at,
        "shift_role": shift_role,
        "status": "SIGNED_UP",
    }
    common_new(s)
    DB["shifts"][s["id"]] = s
    return ok(shift_json(s), status=201)


@bp.get("/volunteer-shifts")
def list_shifts():
    auth(["ProgramAdmin", "SiteSupervisor", "Volunteer"])
    volunteer_id = request.args.get("volunteer_id")
    site_id = request.args.get("site_id")
    status = request.args.get("status")
    items = list(DB["shifts"].values())
    if volunteer_id is not None:
        items = [s for s in items if s["volunteer_id"] == volunteer_id]
    if site_id is not None:
        items = [s for s in items if s["site_id"] == site_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return paged([shift_json(s) for s in sorted_asc(items)])


@bp.get("/volunteer-shifts/<sid>")
def get_shift(sid):
    auth(["ProgramAdmin", "SiteSupervisor", "Volunteer"])
    return ok(shift_json(get_or_404("shifts", sid)))


@bp.patch("/volunteer-shifts/<sid>")
def patch_shift(sid):
    uid, role = auth(["Volunteer", "SiteSupervisor", "ProgramAdmin"])
    data = body()
    new_status = v_enum(req_field(data, "status"), "status", SHIFT_STATUSES)
    # Per-transition role split (priority 2)
    if new_status == "CANCELLED" and role not in ("Volunteer", "ProgramAdmin"):
        forbidden("Only the owning Volunteer or ProgramAdmin may cancel a shift")
    if new_status in ("COMPLETED", "NO_SHOW") and role not in ("SiteSupervisor", "ProgramAdmin"):
        forbidden("Only SiteSupervisor or ProgramAdmin may mark shift outcomes")
    s = get_or_404("shifts", sid)
    # Ownership (priority 3) for the Volunteer cancellation path
    if role == "Volunteer" and new_status == "CANCELLED" and s["volunteer_id"] != uid:
        forbidden("Volunteer may cancel only their own shifts")
    if s["status"] != "SIGNED_UP":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Only a SIGNED_UP shift can transition (requested %s)" % new_status,
        )
    now = clock_now()
    if new_status == "CANCELLED":
        # 24h cutoff (inclusive boundary); ProgramAdmin is exempt.
        if role != "ProgramAdmin" and now > s["start_at"] - timedelta(hours=24):
            raise ApiError(
                "ERR_SHIFT_CUTOFF_PASSED",
                422,
                "Volunteer cancellation requires now <= start_at - 24h",
            )
        s["status"] = "CANCELLED"  # site-date-role occupancy decremented (derived)
        touch(s)
    elif new_status == "COMPLETED":
        if now < s["end_at"]:
            raise ApiError(
                "ERR_SHIFT_CUTOFF_PASSED",
                422,
                "Shift outcomes require now >= end_at",
            )
        s["status"] = "COMPLETED"
        touch(s)
    elif new_status == "NO_SHOW":
        if now < s["end_at"]:
            raise ApiError(
                "ERR_SHIFT_CUTOFF_PASSED",
                422,
                "Shift outcomes require now >= end_at",
            )
        mark_no_show(s)
    else:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Shift transition %s -> %s is not declared" % (s["status"], new_status),
        )
    return ok(shift_json(s))


# ===========================================================================
# Diversion reports
# ===========================================================================
@bp.post("/diversion-reports")
def create_report():
    auth(["ProgramAdmin"])
    data = body()
    program_id = v_str(req_field(data, "program_id"), "program_id")
    program = get_or_404("programs", program_id)
    # OCC (priority 6): guarded on the program's version
    occ_field(data, "expected_program_version", program["version"])
    roll = diversion_rollup(program)
    r = {
        "id": new_id(),
        "program_id": program_id,
        "period_start": program["window_start"],
        "period_end": program["window_end"],
        "status": "DRAFT",
        "collected_tons": roll["collected_tons"],
        "diverted_tons": roll["diverted_tons"],
        "disposed_tons": roll["disposed_tons"],
        "diversion_rate": roll["diversion_rate"],
        "grade": roll["grade"],
        "below_target": roll["below_target"],
        "published_at": None,
    }
    common_new(r)
    DB["reports"][r["id"]] = r
    # Supersede any currently PUBLISHED report of the program
    for other in DB["reports"].values():
        if other["id"] != r["id"] and other["program_id"] == program_id and other["status"] == "PUBLISHED":
            other["status"] = "SUPERSEDED"
            touch(other)
    touch(program)  # creating a report increments the program version
    return ok(report_json(r), status=201)


@bp.get("/diversion-reports")
def list_reports():
    auth(["ProgramAdmin", "SiteSupervisor", "HaulerPartner"])
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = list(DB["reports"].values())
    if program_id is not None:
        items = [r for r in items if r["program_id"] == program_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paged([report_json(r) for r in sorted_asc(items)])


@bp.get("/diversion-reports/<rid>")
def get_report(rid):
    auth(["ProgramAdmin", "SiteSupervisor", "HaulerPartner"])
    return ok(report_json(get_or_404("reports", rid)))


@bp.patch("/diversion-reports/<rid>")
def patch_report(rid):
    auth(["ProgramAdmin"])
    r = get_or_404("reports", rid)
    data = body()
    new_status = v_enum(req_field(data, "status"), "status", REPORT_STATUSES)
    if (r["status"], new_status) != ("DRAFT", "PUBLISHED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Report transition %s -> %s is not declared" % (r["status"], new_status),
        )
    program = DB["programs"][r["program_id"]]
    if clock_now() <= program["window_end"]:
        raise ApiError(
            "ERR_REPORT_NOT_PUBLISHABLE",
            409,
            "Report can be published only after the program window ends",
        )
    if any(
        run["program_id"] == r["program_id"] and run["status"] == "SCHEDULED"
        for run in DB["runs"].values()
    ):
        raise ApiError(
            "ERR_REPORT_NOT_PUBLISHABLE",
            409,
            "Report cannot publish while chipping runs remain SCHEDULED",
        )
    r["status"] = "PUBLISHED"
    r["published_at"] = clock_now()
    touch(r)
    return ok(report_json(r))


# ===========================================================================
# Test-driving logical clock (PRD 2.4)
# ===========================================================================
@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth(["ProgramAdmin"])
    data = body()
    to = v_dt(req_field(data, "to_iso8601"), "to_iso8601")
    set_clock(to)
    return ok({"current_utc": fmt_dt(clock_now())})
