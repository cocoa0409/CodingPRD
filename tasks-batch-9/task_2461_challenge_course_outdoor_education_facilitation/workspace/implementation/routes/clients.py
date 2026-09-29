"""Group clients, their funds ledger, and the booking lifecycle."""
from flask import Blueprint, g

from db import store, base_row, touch, clock_date, by_created_at
from errors import ApiError, invalid
from middleware import authorize
from response import object_response, created_response, list_response, pagination, paginate
from validation import body, req_str, req_enum, req_int, req_date
from services import constants as C
from services import derive, serialize, cascade, money
from services.lookup import get_course, get_group_client, get_booking, apply_filters

bp = Blueprint("clients", __name__)
PREFIX = "/challenge-course"


# ------------------------------------------------------------------ group clients

@bp.post(PREFIX + "/group-clients")
def create_group_client():
    authorize(["ProgramDirector"])
    payload = body()

    client_name = req_str(payload, "client_name")
    org_type = req_enum(payload, "org_type", C.ORG_TYPES)
    tier = req_enum(payload, "tier", C.TIERS, required=False, default="STANDARD")

    row = base_row()
    row.update({
        "client_name": client_name,
        "org_type": org_type,
        "tier": tier,
        "payments_received_cents": 0,
        "credit_balance_cents": 0,
    })
    store.group_clients[row["id"]] = row
    return created_response(serialize.group_client(row))


@bp.get(PREFIX + "/group-clients/<group_client_id>")
def read_group_client(group_client_id):
    authorize(["ProgramDirector", "GroupCoordinator"])
    row = get_group_client(group_client_id)
    return object_response(serialize.group_client(row))


@bp.post(PREFIX + "/group-clients/<group_client_id>/payments")
def post_payment(group_client_id):
    authorize(["ProgramDirector"])
    payload = body()
    amount_cents = req_int(payload, "amount_cents", minimum=1)
    req_str(payload, "reference")

    client = get_group_client(group_client_id)
    client["payments_received_cents"] = client["payments_received_cents"] + amount_cents
    client["credit_balance_cents"] = client["credit_balance_cents"] + amount_cents
    touch(client)
    return object_response(serialize.group_client(client))


# ----------------------------------------------------------------------- bookings

@bp.post(PREFIX + "/bookings")
def create_booking():
    authorize(["ProgramDirector", "GroupCoordinator"])
    payload = body()

    course_id = req_str(payload, "course_id")
    group_client_id = req_str(payload, "group_client_id")
    program_date = req_date(payload, "program_date")
    expected_participant_count = req_int(payload, "expected_participant_count", minimum=1)

    course = get_course(course_id)
    client = get_group_client(group_client_id)

    # Step 34 — the program date must clear the minimum lead time.
    if (program_date - clock_date()).days < C.MIN_LEAD_DAYS:
        raise ApiError("ERR_PROGRAM_DATE_IN_PAST")

    row = base_row()
    row.update({
        "course_id": course["id"],
        "group_client_id": client["id"],
        "program_date": program_date,
        "expected_participant_count": expected_participant_count,
        "status": "DRAFT",
        "billable_head_count": 0,
        "required_chaperone_count": 0,
        "raw_subtotal_cents": 0,
        "high_element_surcharge_cents": 0,
        "quoted_total_cents": 0,
        "deposit_required_cents": 0,
        "deposit_allocated_cents": 0,
        "cancellation_fee_cents": 0,
        "retained_cents": 0,
        "refund_cents": 0,
        "cancellation_variant": "NONE",
        "notice_days_at_cancel": None,
        "quote_index": 0,
    })
    store.bookings[row["id"]] = row
    return created_response(serialize.booking(row))


@bp.get(PREFIX + "/bookings/<booking_id>")
def read_booking(booking_id):
    authorize(["ProgramDirector", "SafetyOfficer", "Facilitator", "GroupCoordinator"])
    row = get_booking(booking_id)
    return object_response(serialize.booking(row))


@bp.get(PREFIX + "/bookings")
def list_bookings():
    authorize(["ProgramDirector", "SafetyOfficer", "GroupCoordinator"])
    limit, offset = pagination()
    rows = by_created_at(list(store.bookings.values()))
    rows = apply_filters(rows, {
        "course_id": ("str", "course_id"),
        "group_client_id": ("str", "group_client_id"),
        "status": ("str", "status"),
        "roster_status": ("str", "roster_status"),
        "program_date": ("date", "program_date"),
    }, accessors={"roster_status": derive.roster_status})
    window, total = paginate(rows, limit, offset)
    return list_response([serialize.booking(r) for r in window], limit, offset, total)


@bp.post(PREFIX + "/bookings/<booking_id>/quote")
def quote_booking(booking_id):
    authorize(["ProgramDirector"])
    payload = body()
    expected_version = req_int(payload, "expected_booking_version", minimum=0)

    booking = get_booking(booking_id)

    # Step 8 — optimistic concurrency.
    if booking["version"] != expected_version:
        raise ApiError("ERR_STALE_BOOKING_VERSION")

    # Step 9 — only a draft or an already-quoted booking may be (re-)priced.
    if booking["status"] not in ("DRAFT", "QUOTED"):
        raise ApiError("ERR_BOOKING_NOT_QUOTABLE")

    if derive.block_count(booking["id"]) < 1:
        raise invalid("A booking must carry at least one program block to be quoted.")

    money.run_quote(booking)
    return object_response(serialize.booking(booking))


@bp.post(PREFIX + "/bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    authorize(["GroupCoordinator"])
    body()

    booking = get_booking(booking_id)

    # Step 7 — only the booking's own coordinator may confirm it.
    if booking["group_client_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # Step 9.
    if booking["status"] != "QUOTED":
        raise ApiError("ERR_BOOKING_NOT_CONFIRMABLE")

    blocks = derive.blocks_of_booking(booking["id"])

    # Step 13 — professional inspection currency of every rigged element.
    for block in blocks:
        if not block["element_id"]:
            continue
        element = store.elements.get(block["element_id"])
        if element is None:
            continue
        due = element["next_professional_inspection_due_on"]
        if due is None or due < booking["program_date"]:
            raise ApiError("ERR_INSPECTION_OVERDUE")

    # Step 15 — site rescue readiness.
    course = store.courses.get(booking["course_id"])
    if course is None or not derive.rescue_readiness_ok(course):
        raise ApiError("ERR_RESCUE_READINESS_UNMET")

    # Step 19 — the whole roster must be screened.
    if derive.roster_status(booking) != "READY":
        raise ApiError("ERR_PARTICIPANT_SCREENING_INCOMPLETE")

    # Step 29 — the program must close on a debrief.
    if not blocks or blocks[-1]["phase"] != "DEBRIEF":
        raise ApiError("ERR_DEBRIEF_BLOCK_MISSING")

    # Step 31 — chaperone coverage.
    chaperones = len([p for p in derive.participants_of_booking(booking["id"]) if p["is_chaperone"]])
    if chaperones < booking["required_chaperone_count"]:
        raise ApiError("ERR_CHAPERONE_SHORTFALL")

    # Step 37 — client funds.
    client = store.group_clients.get(booking["group_client_id"])
    deposit = booking["deposit_required_cents"]
    if client is None or client["credit_balance_cents"] < deposit:
        raise ApiError("ERR_INSUFFICIENT_CLIENT_CREDIT")

    booking["status"] = "CONFIRMED"
    booking["deposit_allocated_cents"] = deposit
    touch(booking)

    client["credit_balance_cents"] = client["credit_balance_cents"] - deposit
    touch(client)

    return object_response(serialize.booking(booking))


@bp.post(PREFIX + "/bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    authorize(["GroupCoordinator", "ProgramDirector"])
    payload = body()
    req_str(payload, "reason")

    booking = get_booking(booking_id)

    # Step 7 — a coordinator may only cancel its own group's booking.
    if g.role == "GroupCoordinator" and booking["group_client_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # Step 9.
    if booking["status"] in C.TERMINAL_BOOKING_STATUSES:
        raise ApiError("ERR_BOOKING_ALREADY_TERMINAL")

    client = money.settle_cancellation(booking)
    touch(booking)
    cascade.abandon_open_blocks(booking)
    if client is not None:
        touch(client)

    return object_response(serialize.booking(booking))
