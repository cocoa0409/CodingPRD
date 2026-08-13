"""Routes: programs, sites, zones, households, bookings, intake events."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from domain import (
    close_site_cascade,
    common_new,
    append_only_new,
    booking_json,
    diversion_rollup,
    get_or_404,
    household_json,
    intake_json,
    notification_json,
    notify,
    ops_run,
    program_json,
    program_posture,
    site_json,
    site_stockpile_cy,
    sorted_asc,
    sorted_desc,
    ticket_json,
    touch,
    zone_json,
    zone_reserved_trees,
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
    v_dec,
    v_dt,
    v_enum,
    v_int,
    v_str,
)
from state import (
    CLASS_CY,
    DB,
    EST_TONS,
    POSTURE_TICKET_THRESHOLD,
    SIZE_CLASSES,
    SOURCE_TYPES,
    clock_now,
    dec,
    new_id,
    num_out,
    r2,
    r3,
)

bp = Blueprint("core", __name__)

READ_ALL = ["ProgramAdmin", "SiteSupervisor", "HaulerPartner", "Resident", "Volunteer"]

PROGRAM_STATUSES = ("DRAFT", "PUBLISHED", "ACTIVE", "CLOSED")
SITE_STATUSES = ("PLANNED", "OPEN", "SUSPENDED", "CLOSING", "CLOSED")
ZONE_STATUSES = ("ACTIVE", "SUSPENDED")
BOOKING_STATUSES = ("CONFIRMED", "SERVICED", "MISSED", "CANCELLED", "REJECTED_CONTAMINATED")


def _program_of_zone(zone):
    return DB["programs"].get(zone["program_id"])


# ===========================================================================
# Programs
# ===========================================================================
@bp.post("/programs")
def create_program():
    auth(["ProgramAdmin"])
    data = body()
    name = v_str(req_field(data, "name"), "name")
    season_label = v_str(req_field(data, "season_label"), "season_label")
    window_start = v_dt(req_field(data, "window_start"), "window_start")
    window_end = v_dt(req_field(data, "window_end"), "window_end")
    if "target_diversion_rate" in data and data["target_diversion_rate"] is not None:
        target = v_dec(data["target_diversion_rate"], "target_diversion_rate",
                       lo=Decimal("0"), hi=Decimal("1"))
    else:
        target = Decimal("0.9")
    if window_end < window_start + timedelta(days=7):
        raise ApiError(
            "ERR_VALIDATION", 400, "window_end must be at least 7 days after window_start"
        )
    p = {
        "id": new_id(),
        "name": name,
        "season_label": season_label,
        "window_start": window_start,
        "window_end": window_end,
        "target_diversion_rate": target,
        "status": "DRAFT",
        "mulch_produced_cy": Decimal("0"),
        "mulch_allocated_participant_cy": Decimal("0"),
        "mulch_allocated_general_cy": Decimal("0"),
    }
    common_new(p)
    DB["programs"][p["id"]] = p
    return ok(program_json(p), status=201)


@bp.get("/programs")
def list_programs():
    auth(READ_ALL)
    status = request.args.get("status")
    items = list(DB["programs"].values())
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paged([program_json(p) for p in sorted_asc(items)])


@bp.get("/programs/<pid>")
def get_program(pid):
    auth(READ_ALL)
    return ok(program_json(get_or_404("programs", pid)))


@bp.patch("/programs/<pid>")
def patch_program(pid):
    auth(["ProgramAdmin"])
    p = get_or_404("programs", pid)
    data = body()

    # Structural field validation (malformed -> 400)
    new_status = data.get("status")
    if new_status is not None:
        v_enum(new_status, "status", PROGRAM_STATUSES)
    edit_fields = ("name", "window_start", "window_end", "target_diversion_rate")
    wants_edit = any(f in data and data[f] is not None for f in edit_fields)
    name = v_str(data["name"], "name") if data.get("name") is not None else None
    ws = v_dt(data["window_start"], "window_start") if data.get("window_start") is not None else None
    we = v_dt(data["window_end"], "window_end") if data.get("window_end") is not None else None
    tdr = None
    if data.get("target_diversion_rate") is not None:
        tdr = v_dec(data["target_diversion_rate"], "target_diversion_rate",
                    lo=Decimal("0"), hi=Decimal("1"))

    # State legality (priority 5): field edits are DRAFT-only; transitions must
    # be declared in the Program state machine.
    if wants_edit and p["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Program fields are editable only in DRAFT")
    declared = {("DRAFT", "PUBLISHED"), ("PUBLISHED", "ACTIVE"), ("ACTIVE", "CLOSED")}
    if new_status is not None and (p["status"], new_status) not in declared:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Program status transition %s -> %s is not declared" % (p["status"], new_status),
        )

    # OCC (priority 6)
    occ_field(data, "expected_program_version", p["version"])

    # Apply candidate edits and validate the resulting window
    new_ws = ws if ws is not None else p["window_start"]
    new_we = we if we is not None else p["window_end"]
    if (ws is not None or we is not None) and new_we < new_ws + timedelta(days=7):
        raise ApiError(
            "ERR_VALIDATION", 400, "window_end must be at least 7 days after window_start"
        )

    # Transition preconditions
    if new_status == "PUBLISHED":
        has_zone = any(z["program_id"] == pid for z in DB["zones"].values())
        has_site = any(s["program_id"] == pid for s in DB["sites"].values())
        if not has_zone or not has_site:
            raise ApiError(
                "ERR_VALIDATION",
                400,
                "Publishing requires at least one service zone and one drop-off site",
            )
        if new_we < new_ws + timedelta(days=7):
            raise ApiError(
                "ERR_VALIDATION", 400, "window_end must be at least 7 days after window_start"
            )
    elif new_status == "ACTIVE":
        if clock_now() < p["window_start"]:
            raise ApiError(
                "ERR_OUTSIDE_COLLECTION_WINDOW",
                422,
                "Program cannot be activated before window_start",
            )
    elif new_status == "CLOSED":
        if _program_close_blocked(pid):
            raise ApiError(
                "ERR_PROGRAM_HAS_OPEN_ITEMS",
                409,
                "Program close blocked: open items remain",
            )

    # Commit
    if name is not None:
        p["name"] = name
    if ws is not None:
        p["window_start"] = ws
    if we is not None:
        p["window_end"] = we
    if tdr is not None:
        p["target_diversion_rate"] = tdr
    if new_status is not None:
        p["status"] = new_status
        if new_status == "PUBLISHED":
            notify(
                pid,
                "PROGRAM_PUBLISHED",
                message="Program %s (%s) has been published." % (p["name"], p["season_label"]),
            )
    touch(p)
    return ok(program_json(p))


def _program_close_blocked(pid):
    if any(
        s["program_id"] == pid and s["status"] != "CLOSED" for s in DB["sites"].values()
    ):
        return True
    if not any(
        r["program_id"] == pid and r["status"] == "PUBLISHED" for r in DB["reports"].values()
    ):
        return True
    for b in DB["bookings"].values():
        z = DB["zones"].get(b["zone_id"])
        if z and z["program_id"] == pid and b["status"] in ("CONFIRMED", "MISSED"):
            return True
    if any(
        t["program_id"] == pid and t["status"] in ("OPEN", "APPEALED")
        for t in DB["tickets"].values()
    ):
        return True
    if any(e["program_id"] == pid and e["status"] != "CLOSED" for e in DB["events"].values()):
        return True
    return False


@bp.post("/programs/<pid>/ops-run")
def program_ops_run(pid):
    auth(["ProgramAdmin"])
    p = get_or_404("programs", pid)
    ops_run(p)
    return ok(program_json(p))


@bp.get("/programs/<pid>/diversion-summary")
def program_diversion_summary(pid):
    auth(["ProgramAdmin", "SiteSupervisor", "HaulerPartner"])
    p = get_or_404("programs", pid)
    roll = diversion_rollup(p)
    return ok(
        {
            "collected_tons": num_out(roll["collected_tons"]),
            "diverted_tons": num_out(roll["diverted_tons"]),
            "disposed_tons": num_out(roll["disposed_tons"]),
            "diversion_rate": num_out(roll["diversion_rate"]),
            "grade": roll["grade"],
            "below_target": roll["below_target"],
        }
    )


@bp.get("/programs/<pid>/notifications")
def program_notifications(pid):
    auth(["ProgramAdmin", "SiteSupervisor"])
    get_or_404("programs", pid)
    kind = request.args.get("kind")
    household_id = request.args.get("household_id")
    items = [n for n in DB["notifications"].values() if n["program_id"] == pid]
    if kind is not None:
        items = [n for n in items if n["kind"] == kind]
    if household_id is not None:
        items = [n for n in items if n["household_id"] == household_id]
    return paged([notification_json(n) for n in sorted_desc(items)])


# ===========================================================================
# Drop-off sites
# ===========================================================================
@bp.post("/sites")
def create_site():
    auth(["ProgramAdmin"])
    data = body()
    program_id = v_str(req_field(data, "program_id"), "program_id")
    name = v_str(req_field(data, "name"), "name")
    address = v_str(req_field(data, "address"), "address")
    capacity = v_dec(req_field(data, "capacity_cy"), "capacity_cy", lo=Decimal("0.01"))
    open_date = v_dt(req_field(data, "open_date"), "open_date")
    close_date = v_dt(req_field(data, "close_date"), "close_date")
    if data.get("volunteer_slots_per_role") is not None:
        slots = v_int(data["volunteer_slots_per_role"], "volunteer_slots_per_role", lo=1)
    else:
        slots = 3
    program = get_or_404("programs", program_id)
    if not (program["window_start"] <= open_date <= program["window_end"]):
        raise ApiError("ERR_VALIDATION", 400, "open_date must lie within the program window")
    if not (program["window_start"] <= close_date <= program["window_end"]):
        raise ApiError("ERR_VALIDATION", 400, "close_date must lie within the program window")
    if open_date > close_date:
        raise ApiError("ERR_VALIDATION", 400, "open_date must be no later than close_date")
    if program["status"] == "CLOSED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Program must be DRAFT, PUBLISHED or ACTIVE to add a site"
        )
    s = {
        "id": new_id(),
        "program_id": program_id,
        "name": name,
        "address": address,
        "capacity_cy": capacity,
        "open_date": open_date,
        "close_date": close_date,
        "volunteer_slots_per_role": slots,
        "status": "PLANNED",
    }
    common_new(s)
    DB["sites"][s["id"]] = s
    return ok(site_json(s), status=201)


@bp.get("/sites")
def list_sites():
    auth(READ_ALL)
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = list(DB["sites"].values())
    if program_id is not None:
        items = [s for s in items if s["program_id"] == program_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return paged([site_json(s) for s in sorted_asc(items)])


@bp.get("/sites/<sid>")
def get_site(sid):
    auth(READ_ALL)
    return ok(site_json(get_or_404("sites", sid)))


@bp.patch("/sites/<sid>")
def patch_site(sid):
    auth(["ProgramAdmin", "SiteSupervisor"])
    s = get_or_404("sites", sid)
    data = body()

    new_status = data.get("status")
    if new_status is not None:
        v_enum(new_status, "status", SITE_STATUSES)
    capacity = None
    if data.get("capacity_cy") is not None:
        capacity = v_dec(data["capacity_cy"], "capacity_cy", lo=Decimal("0.01"))
    open_date = v_dt(data["open_date"], "open_date") if data.get("open_date") is not None else None
    close_date = v_dt(data["close_date"], "close_date") if data.get("close_date") is not None else None
    slots = None
    if data.get("volunteer_slots_per_role") is not None:
        slots = v_int(data["volunteer_slots_per_role"], "volunteer_slots_per_role", lo=1)

    # State legality (priority 5)
    declared = {
        ("PLANNED", "OPEN"),
        ("OPEN", "SUSPENDED"),
        ("SUSPENDED", "OPEN"),
        ("OPEN", "CLOSING"),
        ("SUSPENDED", "CLOSING"),
        ("CLOSING", "CLOSED"),
    }
    if new_status is not None and (s["status"], new_status) not in declared:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Site status transition %s -> %s is not declared" % (s["status"], new_status),
        )

    # OCC (priority 6)
    occ_field(data, "expected_site_version", s["version"])

    program = DB["programs"][s["program_id"]]
    # Date edits must stay inside the program window and ordered
    new_open = open_date if open_date is not None else s["open_date"]
    new_close = close_date if close_date is not None else s["close_date"]
    if open_date is not None or close_date is not None:
        if not (program["window_start"] <= new_open <= program["window_end"]):
            raise ApiError("ERR_VALIDATION", 400, "open_date must lie within the program window")
        if not (program["window_start"] <= new_close <= program["window_end"]):
            raise ApiError("ERR_VALIDATION", 400, "close_date must lie within the program window")
        if new_open > new_close:
            raise ApiError("ERR_VALIDATION", 400, "open_date must be no later than close_date")

    now = clock_now()
    # Transition preconditions
    if new_status == "OPEN":
        if s["status"] == "PLANNED":
            if program["status"] != "ACTIVE":
                raise ApiError(
                    "ERR_INVALID_STATE", 409, "Site can open only while its program is ACTIVE"
                )
            if not (new_open <= now <= new_close):
                raise ApiError(
                    "ERR_OUTSIDE_COLLECTION_WINDOW",
                    422,
                    "Site can open only between open_date and close_date inclusive",
                )
        elif s["status"] == "SUSPENDED":
            if now > new_close:
                raise ApiError(
                    "ERR_OUTSIDE_COLLECTION_WINDOW",
                    422,
                    "Site cannot reopen after its close_date",
                )
    elif new_status == "CLOSED":
        if site_stockpile_cy(sid) != 0:
            raise ApiError(
                "ERR_SITE_NOT_CLOSABLE", 409, "Site stockpile must be exactly zero to close"
            )
        if any(
            t["site_id"] == sid and t["status"] in ("OPEN", "APPEALED")
            for t in DB["tickets"].values()
        ):
            raise ApiError(
                "ERR_SITE_NOT_CLOSABLE",
                409,
                "Site has open or appealed contamination tickets",
            )

    # Capacity check runs last (priority 11)
    if capacity is not None and capacity < site_stockpile_cy(sid):
        raise ApiError(
            "ERR_CAPACITY_BELOW_STOCKPILE",
            422,
            "capacity_cy cannot be lowered below the current stockpile",
        )

    # Commit
    if capacity is not None:
        s["capacity_cy"] = capacity
    if open_date is not None:
        s["open_date"] = open_date
    if close_date is not None:
        s["close_date"] = close_date
    if slots is not None:
        s["volunteer_slots_per_role"] = slots
    if new_status is not None:
        if new_status == "CLOSING":
            close_site_cascade(s)
        else:
            s["status"] = new_status
    touch(s)
    return ok(site_json(s))


# ===========================================================================
# Service zones
# ===========================================================================
@bp.post("/zones")
def create_zone():
    auth(["ProgramAdmin"])
    data = body()
    program_id = v_str(req_field(data, "program_id"), "program_id")
    zone_code = v_str(req_field(data, "zone_code"), "zone_code")
    collection_date = v_dt(req_field(data, "collection_date"), "collection_date")
    capacity = v_int(req_field(data, "daily_tree_capacity"), "daily_tree_capacity", lo=1)
    program = get_or_404("programs", program_id)
    if not (program["window_start"] <= collection_date <= program["window_end"]):
        raise ApiError(
            "ERR_VALIDATION", 400, "collection_date must lie within the program window"
        )
    if any(
        z["program_id"] == program_id and z["zone_code"] == zone_code
        for z in DB["zones"].values()
    ):
        raise ApiError("ERR_VALIDATION", 400, "zone_code must be unique within the program")
    if program["status"] == "CLOSED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Program must be DRAFT, PUBLISHED or ACTIVE to add a zone"
        )
    z = {
        "id": new_id(),
        "program_id": program_id,
        "zone_code": zone_code,
        "collection_date": collection_date,
        "daily_tree_capacity": capacity,
        "status": "ACTIVE",
    }
    common_new(z)
    DB["zones"][z["id"]] = z
    return ok(zone_json(z), status=201)


@bp.get("/zones")
def list_zones():
    auth(READ_ALL)
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = list(DB["zones"].values())
    if program_id is not None:
        items = [z for z in items if z["program_id"] == program_id]
    if status is not None:
        items = [z for z in items if z["status"] == status]
    return paged([zone_json(z) for z in sorted_asc(items)])


@bp.get("/zones/<zid>")
def get_zone(zid):
    auth(READ_ALL)
    return ok(zone_json(get_or_404("zones", zid)))


@bp.patch("/zones/<zid>")
def patch_zone(zid):
    auth(["ProgramAdmin"])
    z = get_or_404("zones", zid)
    data = body()

    new_status = data.get("status")
    if new_status is not None:
        v_enum(new_status, "status", ZONE_STATUSES)
    new_date = None
    if data.get("collection_date") is not None:
        new_date = v_dt(data["collection_date"], "collection_date")
    new_cap = None
    if data.get("daily_tree_capacity") is not None:
        new_cap = v_int(data["daily_tree_capacity"], "daily_tree_capacity", lo=1)

    # State legality (priority 5)
    declared = {("ACTIVE", "SUSPENDED"), ("SUSPENDED", "ACTIVE")}
    if new_status is not None and (z["status"], new_status) not in declared:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Zone status transition %s -> %s is not declared" % (z["status"], new_status),
        )

    # OCC (priority 6)
    occ_field(data, "expected_zone_version", z["version"])

    now = clock_now()
    program = DB["programs"][z["program_id"]]
    date_change = new_date is not None and new_date != z["collection_date"]
    if date_change:
        # Lead time: makeup-day move (current date already passed) or at least
        # 48h ahead of the current collection date (inclusive boundary).
        cur = z["collection_date"]
        if not (cur < now or now <= cur - timedelta(hours=48)):
            raise ApiError(
                "ERR_NOTIFICATION_LEAD_TIME",
                422,
                "collection_date change requires a makeup-day move or 48h lead time",
            )
        if not (program["window_start"] <= new_date <= program["window_end"]):
            raise ApiError(
                "ERR_OUTSIDE_COLLECTION_WINDOW",
                422,
                "New collection_date must lie within the program window",
            )
        if not (new_date > now):
            raise ApiError(
                "ERR_OUTSIDE_COLLECTION_WINDOW",
                422,
                "New collection_date must be in the future",
            )

    # Capacity check runs last (priority 11)
    if new_cap is not None and new_cap < zone_reserved_trees(zid):
        raise ApiError(
            "ERR_ROUTE_CAPACITY_EXCEEDED",
            422,
            "daily_tree_capacity cannot be reduced below reserved_trees",
        )

    # Commit
    if new_cap is not None:
        z["daily_tree_capacity"] = new_cap
    if new_status is not None:
        z["status"] = new_status
    if date_change:
        z["collection_date"] = new_date
        affected_households = []
        for b in DB["bookings"].values():
            if b["zone_id"] == zid and b["status"] == "CONFIRMED":
                b["service_date"] = new_date
                touch(b)
                if b["household_id"] not in affected_households:
                    affected_households.append(b["household_id"])
        for hid in affected_households:
            notify(
                z["program_id"],
                "ZONE_RESCHEDULED",
                household_id=hid,
                zone_id=zid,
                message="Collection date for zone %s has been rescheduled." % z["zone_code"],
            )
    touch(z)
    return ok(zone_json(z))


# ===========================================================================
# Households
# ===========================================================================
@bp.post("/households")
def create_household():
    auth(["Anonymous", "ProgramAdmin"])
    data = body()
    program_id = v_str(req_field(data, "program_id"), "program_id")
    zone_id = v_str(req_field(data, "zone_id"), "zone_id")
    address = v_str(req_field(data, "address"), "address")
    contact_email = v_str(req_field(data, "contact_email"), "contact_email")
    program = get_or_404("programs", program_id)
    zone = get_or_404("zones", zone_id)
    if zone["program_id"] != program_id:
        raise ApiError("ERR_VALIDATION", 400, "zone does not belong to the given program")
    if program["status"] == "CLOSED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Household registration is refused once the program is CLOSED"
        )
    h = {
        "id": new_id(),
        "program_id": program_id,
        "zone_id": zone_id,
        "address": address,
        "contact_email": contact_email,
        "strike_count": 0,
        "curbside_eligible": True,
    }
    common_new(h)
    DB["households"][h["id"]] = h
    return ok(household_json(h), status=201)


@bp.get("/households")
def list_households():
    auth(["ProgramAdmin", "SiteSupervisor"])
    program_id = request.args.get("program_id")
    zone_id = request.args.get("zone_id")
    eligible_raw = request.args.get("curbside_eligible")
    items = list(DB["households"].values())
    if program_id is not None:
        items = [h for h in items if h["program_id"] == program_id]
    if zone_id is not None:
        items = [h for h in items if h["zone_id"] == zone_id]
    if eligible_raw is not None:
        if eligible_raw.lower() == "true":
            items = [h for h in items if h["curbside_eligible"] is True]
        elif eligible_raw.lower() == "false":
            items = [h for h in items if h["curbside_eligible"] is False]
        else:
            items = []
    return paged([household_json(h) for h in sorted_asc(items)])


@bp.get("/households/<hid>")
def get_household(hid):
    auth(["ProgramAdmin", "SiteSupervisor", "Resident"])
    return ok(household_json(get_or_404("households", hid)))


# ===========================================================================
# Curbside bookings
# ===========================================================================
@bp.post("/bookings")
def create_booking():
    uid, role = auth(["Resident", "ProgramAdmin"])
    data = body()
    household_id = req_field(data, "household_id")
    zone_id = req_field(data, "zone_id")
    tree_count = v_int(req_field(data, "tree_count"), "tree_count", lo=1, hi=5)
    size_class = v_enum(req_field(data, "size_class"), "size_class", SIZE_CLASSES)

    # Ownership (priority 3): Resident acts on their own household only.
    if role == "Resident" and household_id != uid:
        forbidden("Resident may book only for their own household")

    household = get_or_404("households", household_id)
    zone = get_or_404("zones", zone_id)

    # Compliance (priority 7): prep attestation must be true.
    if data.get("prep_attestation") is not True:
        raise ApiError(
            "ERR_PREP_ATTESTATION_REQUIRED",
            422,
            "prep_attestation must be true: trees must be free of stands, decorations, tinsel, flocking",
        )

    # Referential coherence (priority 8)
    if zone_id != household["zone_id"]:
        raise ApiError("ERR_ZONE_MISMATCH", 422, "booking.zone_id must equal household.zone_id")

    # Business constraints (priority 10)
    program = _program_of_zone(zone)
    if program_posture(program["id"]) == "RESTRICTED":
        raise ApiError(
            "ERR_PROGRAM_RESTRICTED",
            409,
            "Program posture is RESTRICTED; new bookings are blocked",
        )
    if zone["status"] != "ACTIVE":
        raise ApiError("ERR_ZONE_SUSPENDED", 409, "Zone is suspended; new bookings rejected")
    if not household["curbside_eligible"]:
        raise ApiError(
            "ERR_HOUSEHOLD_BARRED", 403, "Household is barred from curbside service"
        )

    # Capacity (priority 11)
    reserved = zone_reserved_trees(zone_id)
    if reserved + tree_count > zone["daily_tree_capacity"]:
        raise ApiError(
            "ERR_ROUTE_CAPACITY_EXCEEDED", 422, "Route tree capacity exceeded"
        )

    b = {
        "id": new_id(),
        "household_id": household_id,
        "zone_id": zone_id,
        "tree_count": tree_count,
        "size_class": size_class,
        "prep_attestation": True,
        "status": "CONFIRMED",
        "service_date": zone["collection_date"],
        "actual_tons": None,
        "estimated_tons": r3(dec(tree_count) * EST_TONS[size_class]),
    }
    common_new(b)
    DB["bookings"][b["id"]] = b
    touch(zone)  # reserved_trees / projections recomputed
    return ok(booking_json(b), status=201)


@bp.get("/bookings")
def list_bookings():
    auth(["ProgramAdmin", "SiteSupervisor"])
    household_id = request.args.get("household_id")
    zone_id = request.args.get("zone_id")
    status = request.args.get("status")
    items = list(DB["bookings"].values())
    if household_id is not None:
        items = [b for b in items if b["household_id"] == household_id]
    if zone_id is not None:
        items = [b for b in items if b["zone_id"] == zone_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return paged([booking_json(b) for b in sorted_asc(items)])


@bp.get("/bookings/<bid>")
def get_booking(bid):
    auth(["ProgramAdmin", "SiteSupervisor", "Resident"])
    return ok(booking_json(get_or_404("bookings", bid)))


def _own_booking_or_admin(role, uid, booking):
    if role == "Resident" and booking["household_id"] != uid:
        forbidden("Resident may act only on their own household's bookings")


@bp.post("/bookings/<bid>/cancel")
def cancel_booking(bid):
    uid, role = auth(["Resident", "ProgramAdmin"])
    b = get_or_404("bookings", bid)
    _own_booking_or_admin(role, uid, b)
    if b["status"] not in ("CONFIRMED", "MISSED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Only a CONFIRMED or MISSED booking can be cancelled",
        )
    was_confirmed = b["status"] == "CONFIRMED"
    b["status"] = "CANCELLED"
    touch(b)
    if was_confirmed:
        touch(DB["zones"][b["zone_id"]])  # reserved capacity released
    return ok(booking_json(b))


@bp.post("/bookings/<bid>/reschedule")
def reschedule_booking(bid):
    uid, role = auth(["Resident", "ProgramAdmin"])
    b = get_or_404("bookings", bid)
    _own_booking_or_admin(role, uid, b)
    data = body()
    new_service_date = v_dt(req_field(data, "new_service_date"), "new_service_date")
    if b["status"] != "MISSED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a MISSED booking can be rescheduled"
        )
    zone = DB["zones"][b["zone_id"]]
    household = DB["households"][b["household_id"]]
    if new_service_date != zone["collection_date"]:
        raise ApiError(
            "ERR_BOOKING_DATE_MISMATCH",
            422,
            "new_service_date must equal the zone's current collection_date",
        )
    if not (zone["collection_date"] > clock_now()):
        raise ApiError(
            "ERR_OUTSIDE_COLLECTION_WINDOW",
            422,
            "The zone's collection_date must still lie in the future",
        )
    if zone["status"] != "ACTIVE":
        raise ApiError("ERR_ZONE_SUSPENDED", 409, "Zone is suspended; reschedule rejected")
    if not household["curbside_eligible"]:
        raise ApiError(
            "ERR_HOUSEHOLD_BARRED", 403, "Household is barred from curbside service"
        )
    reserved = zone_reserved_trees(b["zone_id"])
    if reserved + b["tree_count"] > zone["daily_tree_capacity"]:
        raise ApiError("ERR_ROUTE_CAPACITY_EXCEEDED", 422, "Route tree capacity exceeded")
    b["status"] = "CONFIRMED"
    b["service_date"] = new_service_date
    touch(b)
    touch(zone)  # reserved capacity re-added
    return ok(booking_json(b))


@bp.post("/bookings/<bid>/record-outcome")
def record_booking_outcome(bid):
    auth(["SiteSupervisor", "ProgramAdmin"])
    b = get_or_404("bookings", bid)
    data = body()
    outcome = v_enum(req_field(data, "outcome"), "outcome", ("SERVICED", "MISSED"))
    actual_tons = None
    if data.get("actual_tons") is not None:
        actual_tons = v_dec(data["actual_tons"], "actual_tons", lo=Decimal("0"))
    if b["status"] != "CONFIRMED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Outcomes can be recorded only for CONFIRMED bookings",
        )
    zone = DB["zones"][b["zone_id"]]
    if outcome == "SERVICED":
        b["status"] = "SERVICED"
        b["actual_tons"] = actual_tons
    else:
        b["status"] = "MISSED"  # reserved capacity released (derived)
    touch(b)
    touch(zone)  # reserved_trees / collected_tons_actual recomputed
    return ok(booking_json(b))


# ===========================================================================
# Intake events
# ===========================================================================
@bp.post("/intake-events")
def create_intake_event():
    auth(["SiteSupervisor", "ProgramAdmin"])
    data = body()
    site_id = v_str(req_field(data, "site_id"), "site_id")
    source_type = v_enum(req_field(data, "source_type"), "source_type", SOURCE_TYPES)
    tree_count = v_int(req_field(data, "tree_count"), "tree_count", lo=1)
    size_class = v_enum(req_field(data, "size_class"), "size_class", SIZE_CLASSES)
    contaminated = Decimal("0")
    if data.get("contaminated_cy") is not None:
        contaminated = v_dec(data["contaminated_cy"], "contaminated_cy", lo=Decimal("0"))
    weighed_tons = None
    if data.get("weighed_tons") is not None:
        weighed_tons = v_dec(data["weighed_tons"], "weighed_tons", lo=Decimal("0"))

    # Volume arithmetic (fixed): gross -> contaminated cap -> net
    gross = r2(dec(tree_count) * CLASS_CY[size_class])
    if contaminated > gross:
        raise ApiError(
            "ERR_VALIDATION", 400, "contaminated_cy may not exceed gross_volume_cy"
        )
    net = r2(gross - contaminated)

    site = get_or_404("sites", site_id)
    program = DB["programs"][site["program_id"]]

    # Temporal gate (priority 9): recorded within the collection window
    now = clock_now()
    if not (program["window_start"] <= now <= program["window_end"]):
        raise ApiError(
            "ERR_OUTSIDE_COLLECTION_WINDOW",
            422,
            "Intake must be recorded within the program collection window",
        )

    # Business constraints (priority 10)
    if site["status"] != "OPEN":
        raise ApiError("ERR_SITE_NOT_OPEN", 409, "Intake requires the site to be OPEN")
    if program_posture(program["id"]) == "RESTRICTED":
        raise ApiError(
            "ERR_PROGRAM_RESTRICTED",
            409,
            "Program posture is RESTRICTED; new intake events are blocked",
        )

    # Capacity (priority 11)
    if site_stockpile_cy(site_id) + net > site["capacity_cy"]:
        raise ApiError(
            "ERR_SITE_CAPACITY_EXCEEDED", 422, "Site stockpile capacity exceeded"
        )

    estimated_tons = r3(dec(tree_count) * EST_TONS[size_class])
    e = {
        "id": new_id(),
        "site_id": site_id,
        "source_type": source_type,
        "tree_count": tree_count,
        "size_class": size_class,
        "contaminated_cy": contaminated,
        "gross_volume_cy": gross,
        "net_volume_cy": net,
        "weighed_tons": weighed_tons,
        "estimated_tons": estimated_tons,
        "report_tons": weighed_tons if weighed_tons is not None else estimated_tons,
        "recorded_at": now,
        "status": "RECORDED",
        "void_reason": None,
    }
    append_only_new(e)
    DB["intake_events"][e["id"]] = e
    touch(site)  # stockpile_cy recomputed
    return ok(intake_json(e), status=201)


@bp.get("/intake-events")
def list_intake_events():
    auth(["ProgramAdmin", "SiteSupervisor", "HaulerPartner"])
    site_id = request.args.get("site_id")
    status = request.args.get("status")
    items = list(DB["intake_events"].values())
    if site_id is not None:
        items = [e for e in items if e["site_id"] == site_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return paged([intake_json(e) for e in sorted_asc(items)])


@bp.get("/intake-events/<eid>")
def get_intake_event(eid):
    auth(["ProgramAdmin", "SiteSupervisor", "HaulerPartner"])
    return ok(intake_json(get_or_404("intake_events", eid)))


@bp.post("/intake-events/<eid>/void")
def void_intake_event(eid):
    auth(["SiteSupervisor", "ProgramAdmin"])
    e = get_or_404("intake_events", eid)
    data = body()
    reason = v_str(req_field(data, "reason"), "reason")
    if e["status"] != "RECORDED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a RECORDED intake event can be voided"
        )
    e["status"] = "VOIDED"
    e["void_reason"] = reason
    # stockpile_cy -= net_volume_cy (compensating; derived on read)
    touch(DB["sites"][e["site_id"]])
    return ok(intake_json(e))
