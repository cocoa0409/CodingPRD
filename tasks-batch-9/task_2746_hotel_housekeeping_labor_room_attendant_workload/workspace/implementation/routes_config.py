"""Standing up the property, its inventory and its people -- PRD 3.1.

Properties, room types, rooms and attendants.
"""

from decimal import Decimal

from flask import Blueprint, request

import derive
from auth import FRONT_DESK_AGENT, HOUSEKEEPING_DIRECTOR, authenticate
from envelope import created, filtered, ok, paginate
from errors import ApiError
from serialize import attendant_out, property_out, room_out, room_type_out
from store import STORE, base_record, touch
from timeutil import format_iso_date
from validate import read_body, vbool, vdate, venum, vint, vstr, vdec, has_key

bp = Blueprint("config", __name__)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

@bp.post("/housekeeping/properties")
def create_property():
    authenticate((HOUSEKEEPING_DIRECTOR,))
    body = read_body()
    row = base_record(STORE)
    row.update({
        "name": vstr(body, "name", 1, 120),
        "ordinance_profile": venum(
            body, "ordinance_profile", derive.ORDINANCE_PROFILES, required=False, default="NONE"
        ),
        "credit_minute_value": vint(body, "credit_minute_value", 5, 120, required=False, default=30),
        "standard_shift_minutes": vint(
            body, "standard_shift_minutes", 60, 720, required=False, default=480
        ),
        "pre_post_shift_minutes": vint(
            body, "pre_post_shift_minutes", 0, 240, required=False, default=45
        ),
        "min_daily_paid_minutes": vint(
            body, "min_daily_paid_minutes", 0, 480, required=False, default=240
        ),
        "max_daily_credits": vdec(
            body, "max_daily_credits", "0.25", "40.00", 2, required=False, default=Decimal("16.00")
        ),
        "max_daily_square_feet": vint(
            body, "max_daily_square_feet", 100, 20000, required=False, default=2200
        ),
        "laundry_sla_minutes": vint(
            body, "laundry_sla_minutes", 30, 1440, required=False, default=240
        ),
        "laundry_capacity_sets": vint(
            body, "laundry_capacity_sets", 1, 10000, required=False, default=300
        ),
        "reclean_threshold_score": vdec(
            body, "reclean_threshold_score", "0.0", "100.0", 1,
            required=False, default=Decimal("85.0"),
        ),
        "inspection_sample_rate": vdec(
            body, "inspection_sample_rate", "0.00", "1.00", 2,
            required=False, default=Decimal("0.20"),
        ),
        "probation_sample_rate": vdec(
            body, "probation_sample_rate", "0.00", "1.00", 2,
            required=False, default=Decimal("0.50"),
        ),
        "rest_buffer_minutes": vint(body, "rest_buffer_minutes", 0, 120, required=False, default=10),
    })
    STORE.properties[row["id"]] = row
    return created(property_out(STORE, row))


@bp.get("/housekeeping/properties/<pid>")
def read_property(pid):
    authenticate(None)
    row = derive.get_property(STORE, pid)
    return ok(property_out(STORE, row))


# ---------------------------------------------------------------------------
# Room types
# ---------------------------------------------------------------------------

@bp.post("/housekeeping/room-types")
def create_room_type():
    authenticate((HOUSEKEEPING_DIRECTOR,))
    body = read_body()
    property_id = vstr(body, "property_id", 1, None)
    code = vstr(body, "code", 1, 24, upper=True)
    square_feet = vint(body, "square_feet", 50, 5000)
    checkout_credits = vdec(body, "checkout_credits", "0.25", "10.00", 2)
    stayover_credits = vdec(body, "stayover_credits", "0.25", "10.00", 2)
    deep_clean_credits = vdec(body, "deep_clean_credits", "0.25", "10.00", 2)
    linen_sets_per_room = vint(body, "linen_sets_per_room", 0, 40, required=False, default=2)

    prop = derive.get_property(STORE, property_id)

    for existing in derive.room_types_of_property(STORE, prop["id"]):
        if existing["code"] == code:
            raise ApiError(
                "ERR_ROOM_TYPE_CODE_DUPLICATE",
                "Room type code %s already exists for this property." % code,
            )

    row = base_record(STORE)
    row.update({
        "property_id": prop["id"],
        "code": code,
        "square_feet": square_feet,
        "checkout_credits": checkout_credits,
        "stayover_credits": stayover_credits,
        "deep_clean_credits": deep_clean_credits,
        "linen_sets_per_room": linen_sets_per_room,
    })
    STORE.room_types[row["id"]] = row

    # PRD 3.1: defining a room type immediately recomputes par_required_sets and
    # shortage_status on every linen line of the property.
    derive.recompute_all_linen_of_property(STORE, prop["id"])
    return created(room_type_out(STORE, row))


@bp.get("/housekeeping/room-types/<tid>")
def read_room_type(tid):
    authenticate(None)
    row = derive.get_room_type(STORE, tid)
    return ok(room_type_out(STORE, row))


@bp.get("/housekeeping/room-types")
def list_room_types():
    authenticate(None)
    rows = filtered(
        list(STORE.room_types.values()),
        request.args,
        {"property_id": ("property_id", None), "code": ("code", None)},
    )
    return paginate(rows, request.args, lambda r: room_type_out(STORE, r))


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------

@bp.post("/housekeeping/rooms")
def create_room():
    authenticate((HOUSEKEEPING_DIRECTOR,))
    body = read_body()
    property_id = vstr(body, "property_id", 1, None)
    room_type_id = vstr(body, "room_type_id", 1, None)
    room_number = vstr(body, "room_number", 1, 12)
    floor = vint(body, "floor", None, None, required=False, default=1)
    service_program = venum(
        body, "service_program", derive.SERVICE_PROGRAMS, required=False, default="DAILY"
    )
    occupancy_state = venum(
        body, "occupancy_state", derive.OCCUPANCY_STATES, required=False, default="VACANT"
    )
    last_serviced = vdate(body, "last_serviced_business_date", required=False, default=None)
    last_deep_cleaned = vdate(body, "last_deep_cleaned_business_date", required=False, default=None)

    prop = derive.get_property(STORE, property_id)
    room_type = derive.get_room_type(STORE, room_type_id)
    if room_type["property_id"] != prop["id"]:
        raise ApiError(
            "ERR_PROPERTY_SCOPE_MISMATCH",
            "Room type %s does not belong to property %s." % (room_type["id"], prop["id"]),
        )

    for existing in derive.rooms_of_property(STORE, prop["id"]):
        if existing["room_number"] == room_number:
            raise ApiError(
                "ERR_ROOM_NUMBER_DUPLICATE",
                "Room number %s already exists for this property." % room_number,
            )

    row = base_record(STORE)
    row.update({
        "property_id": prop["id"],
        "room_type_id": room_type["id"],
        "room_number": room_number,
        "floor": floor,
        "service_program": service_program,
        "occupancy_state": occupancy_state,
        # PRD 3.1: cleanliness_status starts at DIRTY and is thereafter driven by the
        # system rather than commanded, except through the explicit operator correction.
        "cleanliness_status": "DIRTY",
        "last_serviced_business_date": last_serviced,
        "last_deep_cleaned_business_date": last_deep_cleaned,
    })
    STORE.rooms[row["id"]] = row

    # Adding a room moves the property's linen par level.
    derive.recompute_all_linen_of_property(STORE, prop["id"])
    return created(room_out(STORE, row))


@bp.get("/housekeeping/rooms/<rid>")
def read_room(rid):
    authenticate(None)
    row = derive.get_room(STORE, rid)
    return ok(room_out(STORE, row))


@bp.get("/housekeeping/rooms")
def list_rooms():
    authenticate(None)
    rows = filtered(
        list(STORE.rooms.values()),
        request.args,
        {
            "property_id": ("property_id", None),
            "room_type_id": ("room_type_id", None),
            "service_program": ("service_program", None),
            "cleanliness_status": ("cleanliness_status", None),
        },
    )
    return paginate(rows, request.args, lambda r: room_out(STORE, r))


@bp.patch("/housekeeping/rooms/<rid>")
def patch_room(rid):
    authenticate((HOUSEKEEPING_DIRECTOR, FRONT_DESK_AGENT))
    body = read_body()
    occupancy_state = venum(
        body, "occupancy_state", derive.OCCUPANCY_STATES, required=False, default=None
    )
    service_program = venum(
        body, "service_program", derive.SERVICE_PROGRAMS, required=False, default=None
    )
    cleanliness_status = venum(
        body, "cleanliness_status", derive.CLEANLINESS_STATUSES, required=False, default=None
    )
    seen_serviced = has_key(body, "last_serviced_business_date")
    seen_deep = has_key(body, "last_deep_cleaned_business_date")
    last_serviced = vdate(
        body, "last_serviced_business_date", required=False, default=None, nullable=True
    )
    last_deep_cleaned = vdate(
        body, "last_deep_cleaned_business_date", required=False, default=None, nullable=True
    )

    room = derive.get_room(STORE, rid)

    # PRD 3.1: a room being cleaned right now cannot be pulled out from under the
    # attendant.
    if cleanliness_status == "OUT_OF_ORDER" and room["cleanliness_status"] == "IN_SERVICE":
        raise ApiError(
            "ERR_ROOM_ALREADY_IN_SERVICE",
            "Room %s is IN_SERVICE and cannot be taken out of order." % room["id"],
        )

    if occupancy_state is not None:
        room["occupancy_state"] = occupancy_state
        # Setting DUE_OUT returns a serviced room to the head of the cleaning loop.
        if occupancy_state == "DUE_OUT" and room["cleanliness_status"] in (
            "CLEAN", "INSPECTED_PASS",
        ):
            room["cleanliness_status"] = "DIRTY"
    if service_program is not None:
        room["service_program"] = service_program
    if cleanliness_status is not None:
        room["cleanliness_status"] = cleanliness_status
    if seen_serviced:
        room["last_serviced_business_date"] = last_serviced
    if seen_deep:
        room["last_deep_cleaned_business_date"] = last_deep_cleaned

    touch(STORE, room)
    return ok(room_out(STORE, room))


# ---------------------------------------------------------------------------
# Attendants
# ---------------------------------------------------------------------------

@bp.post("/housekeeping/attendants")
def create_attendant():
    authenticate((HOUSEKEEPING_DIRECTOR,))
    body = read_body()
    property_id = vstr(body, "property_id", 1, None)
    employee_code = vstr(body, "employee_code", 1, 24)
    full_name = vstr(body, "full_name", 1, 120)
    seniority_date = vdate(body, "seniority_date")
    hourly_rate_cents = vint(body, "hourly_rate_cents", 100, 20000)
    can_inspect = vbool(body, "can_inspect", required=False, default=False)
    restricted_duty = vbool(body, "restricted_duty", required=False, default=False)
    status = venum(body, "status", derive.ATTENDANT_STATUSES, required=False, default="ACTIVE")

    prop = derive.get_property(STORE, property_id)

    for existing in STORE.attendants.values():
        if existing["property_id"] == prop["id"] and existing["employee_code"] == employee_code:
            raise ApiError(
                "ERR_EMPLOYEE_CODE_DUPLICATE",
                "Employee code %s already exists for this property." % employee_code,
            )

    row = base_record(STORE)
    row.update({
        "property_id": prop["id"],
        "employee_code": employee_code,
        "full_name": full_name,
        "seniority_date": seniority_date,
        "hourly_rate_cents": hourly_rate_cents,
        "can_inspect": can_inspect,
        "restricted_duty": restricted_duty,
        "status": status,
        "quality_probation": False,
        "lifetime_fail_count": 0,
    })
    STORE.attendants[row["id"]] = row
    return created(attendant_out(STORE, row))


@bp.get("/housekeeping/attendants/<aid>")
def read_attendant(aid):
    authenticate(None)
    row = derive.get_attendant(STORE, aid)
    return ok(attendant_out(STORE, row))


@bp.get("/housekeeping/attendants")
def list_attendants():
    authenticate(None)
    rows = filtered(
        list(STORE.attendants.values()),
        request.args,
        {"property_id": ("property_id", None), "status": ("status", None)},
    )
    return paginate(rows, request.args, lambda r: attendant_out(STORE, r))


@bp.patch("/housekeeping/attendants/<aid>")
def patch_attendant(aid):
    authenticate((HOUSEKEEPING_DIRECTOR,))
    body = read_body()
    restricted_duty = vbool(body, "restricted_duty", required=False, default=None)
    can_inspect = vbool(body, "can_inspect", required=False, default=None)
    status = venum(body, "status", derive.ATTENDANT_STATUSES, required=False, default=None)

    attendant = derive.get_attendant(STORE, aid)

    restricted_changed = restricted_duty is not None and restricted_duty != attendant["restricted_duty"]
    if restricted_duty is not None:
        attendant["restricted_duty"] = restricted_duty
    if can_inspect is not None:
        attendant["can_inspect"] = can_inspect
    if status is not None:
        attendant["status"] = status
    touch(STORE, attendant)

    if restricted_changed:
        # PRD 3.1: flipping restricted_duty re-derives effective_credit_cap,
        # compliance_state and required_inspection_samples on every one of that
        # attendant's rosters whose status is not CLOSED.  This is one of the two
        # routes by which a roster can land in BREACH_BLOCKED.
        rosters = [
            r for r in STORE.rosters.values()
            if r["attendant_id"] == attendant["id"] and r["status"] != "CLOSED"
        ]
        for roster in sorted(rosters, key=lambda r: (r["created_at"], r["_seq"])):
            derive.cascade_roster(STORE, roster)

    return ok(attendant_out(STORE, attendant))
