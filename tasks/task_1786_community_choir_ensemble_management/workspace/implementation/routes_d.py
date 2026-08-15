"""Routes: venues, concerts, venue bookings, program pieces, guest contracts."""

import store
from domain import (
    CONCERT_ACTIONS, SERVICE_KINDS, cancel_linked_contract, concert_cancel_cascade,
    compute_performance_eligible, gate_season, quote_fee, cancellation_fee,
    sync_concert_duration, treasury_credit, treasury_debit,
)
from errors import ApiError
from routes_common import apply_filters, many, one, route
from serializers import (
    booking_view, concert_view, contract_view, piece_view, venue_view,
)
from store import all_of, new_row, touch
from timeutil import add_hours, clock, parse_instant
from validate import check_body, check_enum, get_or_404, resolve_ids

ALL_ROLES = ("President", "Treasurer", "ChoirDirector", "Librarian", "Member")
CONCERT_WRITE_POSTURES = ("REHEARSING", "CONCERT_LOCK")


def validate_service_lines(lines):
    if not isinstance(lines, list):
        raise ApiError("ERR_INVALID_REQUEST", "service_lines must be an array")
    for line in lines:
        if not isinstance(line, dict):
            raise ApiError("ERR_INVALID_REQUEST", "each service line must be an object")
        for key in line:
            if key not in ("kind", "units", "rate_cents"):
                raise ApiError("ERR_INVALID_REQUEST", "unknown field on service line: %s" % key)
        for req in ("kind", "units", "rate_cents"):
            if req not in line or line[req] is None:
                raise ApiError("ERR_INVALID_REQUEST", "service line requires %s" % req)
        check_enum(line, "kind", SERVICE_KINDS)
        if not isinstance(line["units"], (int, float)) or isinstance(line["units"], bool):
            raise ApiError("ERR_INVALID_REQUEST", "service line units must be a number")
        if not isinstance(line["rate_cents"], int) or isinstance(line["rate_cents"], bool):
            raise ApiError("ERR_INVALID_REQUEST", "service line rate_cents must be an integer")


# ------------------------------------------------------------------- venues
@route("POST", "/v1/venues", roles=["President"], code=201)
def create_venue(ctx):
    body = check_body(ctx["body"], {"name": ("string", True), "capacity": ("int", True)})
    venue = new_row(store.venues, name=body["name"], capacity=body["capacity"], status="ACTIVE")
    return one(venue_view, venue, 201)


@route("GET", "/v1/venues/{rid}", roles=ALL_ROLES)
def get_venue(ctx):
    return one(venue_view, get_or_404(store.venues, ctx["path"]["rid"]))


@route("GET", "/v1/venues", roles=ALL_ROLES)
def list_venues(ctx):
    rows = apply_filters(all_of(store.venues), {"status": ctx["args"].get("status")})
    return many(venue_view, rows, ctx["args"])


@route("POST", "/v1/venues/{rid}/archive", roles=["President"])
def archive_venue(ctx):
    venue = get_or_404(store.venues, ctx["path"]["rid"])
    check_body(ctx["body"], {})
    if venue["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "only an ACTIVE venue can be archived")
    venue["status"] = "ARCHIVED"
    touch(venue)
    return one(venue_view, venue)


# ------------------------------------------------------------------ concerts
@route("POST", "/v1/concerts", roles=["ChoirDirector"], code=201)
def create_concert(ctx):
    ids = resolve_ids(ctx["body"], (store.seasons, "season_id"))
    body = check_body(ctx["body"], {
        "season_id": ("string", True),
        "title": ("string", True),
        "expected_attendance": ("int", True),
    })
    season = ids.get("season_id") or get_or_404(store.seasons, body["season_id"])
    gate_season(season, CONCERT_WRITE_POSTURES)
    concert = new_row(
        store.concerts,
        season_id=season["id"],
        title=body["title"],
        expected_attendance=body["expected_attendance"],
        status="PLANNING",
        program_duration_seconds=0,
    )
    return one(concert_view, concert, 201)


@route("GET", "/v1/concerts/{rid}", roles=ALL_ROLES)
def get_concert(ctx):
    return one(concert_view, get_or_404(store.concerts, ctx["path"]["rid"]))


@route("GET", "/v1/concerts", roles=ALL_ROLES)
def list_concerts(ctx):
    rows = apply_filters(all_of(store.concerts), {
        "season_id": ctx["args"].get("season_id"),
        "status": ctx["args"].get("status"),
    })
    return many(concert_view, rows, ctx["args"])


def _confirmed_booking(concert_id):
    return next(
        (b for b in store.venue_bookings.values()
         if b["concert_id"] == concert_id and b["status"] == "CONFIRMED"),
        None,
    )


def _non_void_pieces(concert_id):
    return [
        p for p in store.program_pieces.values()
        if p["concert_id"] == concert_id and p["status"] != "VOID"
    ]


@route("POST", "/v1/concerts/{rid}/transition", roles=["ChoirDirector"])
def concert_transition(ctx):
    concert = get_or_404(store.concerts, ctx["path"]["rid"])
    body = check_body(ctx["body"], {"action": ("string", True)})
    check_enum(body, "action", CONCERT_ACTIONS)
    gate_season(store.seasons[concert["season_id"]], CONCERT_WRITE_POSTURES)
    action = body["action"]

    if action == "LOCK_PROGRAM":
        booking = _confirmed_booking(concert["id"])
        if booking is None:
            if concert["status"] == "PLANNING":
                raise ApiError("ERR_BOOKING_NOT_CONFIRMED", "LOCK_PROGRAM requires a CONFIRMED booking")
            raise ApiError("ERR_INVALID_STATE", "LOCK_PROGRAM is not legal from %s" % concert["status"])
        if concert["status"] != "VENUE_BOOKED":
            raise ApiError("ERR_INVALID_STATE", "LOCK_PROGRAM is not legal from %s" % concert["status"])
        pieces = _non_void_pieces(concert["id"])
        if not pieces or any(p["status"] != "CONFIRMED" for p in pieces):
            raise ApiError("ERR_NO_CONFIRMED_PIECES", "program needs at least one piece, all CONFIRMED")
        sync_concert_duration(concert)
        window = (booking["_end_dt"] - booking["_start_dt"]).total_seconds()
        if concert["program_duration_seconds"] > window - 900:
            raise ApiError("ERR_PROGRAM_TOO_LONG", "program exceeds the booking window minus 900s")
        concert["status"] = "PROGRAM_LOCKED"
        touch(concert)
        return one(concert_view, concert)

    if action == "MARK_READY":
        if concert["status"] != "PROGRAM_LOCKED":
            raise ApiError("ERR_INVALID_STATE", "MARK_READY is not legal from %s" % concert["status"])
        for p in _non_void_pieces(concert["id"]):
            if p["status"] == "CONFIRMED" and p.get("guest_contract_id"):
                contract = store.guest_contracts.get(p["guest_contract_id"])
                if contract is None or contract["status"] != "PAID":
                    raise ApiError("ERR_CONTRACT_UNPAID", "a linked contract is not PAID")
        concert["status"] = "READY"
        touch(concert)
        return one(concert_view, concert)

    if action == "PERFORM":
        if concert["status"] != "READY":
            raise ApiError("ERR_INVALID_STATE", "PERFORM is not legal from %s" % concert["status"])
        booking = _confirmed_booking(concert["id"])
        if booking is None or clock.now < booking["_start_dt"]:
            raise ApiError("ERR_CONCERT_TOO_EARLY", "the booking start_at has not been reached")
        concert["status"] = "PERFORMED"
        touch(concert)
        return one(concert_view, concert)

    # CANCEL
    if concert["status"] not in ("PLANNING", "VENUE_BOOKED", "PROGRAM_LOCKED", "READY"):
        raise ApiError("ERR_INVALID_STATE", "CANCEL is not legal from %s" % concert["status"])
    if concert["status"] == "READY":
        for p in _non_void_pieces(concert["id"]):
            if p.get("guest_contract_id"):
                contract = store.guest_contracts.get(p["guest_contract_id"])
                if contract is not None and contract["status"] == "PAID":
                    raise ApiError(
                        "ERR_INVALID_STATE",
                        "a READY concert with a linked PAID contract cannot be cancelled",
                    )
    concert_cancel_cascade(concert)
    return one(concert_view, concert)


# ------------------------------------------------------------- venue bookings
@route("POST", "/v1/venue-bookings", roles=["ChoirDirector"], code=201)
def create_booking(ctx):
    ids = resolve_ids(ctx["body"], (store.concerts, "concert_id"), (store.venues, "venue_id"))
    body = check_body(ctx["body"], {
        "concert_id": ("string", True),
        "venue_id": ("string", True),
        "start_at": ("datetime", True),
        "end_at": ("datetime", True),
        "deposit_cents": ("int", True),
    })
    concert = ids.get("concert_id") or get_or_404(store.concerts, body["concert_id"])
    venue = ids.get("venue_id") or get_or_404(store.venues, body["venue_id"])
    gate_season(store.seasons[concert["season_id"]], CONCERT_WRITE_POSTURES)
    if venue["status"] != "ACTIVE":
        raise ApiError("ERR_VENUE_ARCHIVED", "the venue is ARCHIVED")
    start_dt = parse_instant(body["start_at"])
    end_dt = parse_instant(body["end_at"])
    for other in store.venue_bookings.values():
        if other["venue_id"] != venue["id"] or other["status"] not in ("REQUESTED", "CONFIRMED"):
            continue
        if start_dt < other["_end_dt"] and other["_start_dt"] < end_dt:
            raise ApiError("ERR_VENUE_OVERLAP", "the interval intersects an existing booking")
    if concert["expected_attendance"] > venue["capacity"]:
        raise ApiError("ERR_VENUE_CAPACITY_EXCEEDED", "expected_attendance exceeds the venue capacity")
    if start_dt < add_hours(clock.now, 72):
        raise ApiError("ERR_BOOKING_LEAD_TIME", "start_at must be at least 72 hours in the future")
    booking = new_row(
        store.venue_bookings,
        concert_id=concert["id"],
        venue_id=venue["id"],
        start_at=body["start_at"],
        end_at=body["end_at"],
        deposit_cents=body["deposit_cents"],
        status="REQUESTED",
    )
    booking["_start_dt"] = start_dt
    booking["_end_dt"] = end_dt
    return one(booking_view, booking, 201)


@route("GET", "/v1/venue-bookings/{rid}", roles=ALL_ROLES)
def get_booking(ctx):
    return one(booking_view, get_or_404(store.venue_bookings, ctx["path"]["rid"]))


@route("GET", "/v1/venue-bookings", roles=ALL_ROLES)
def list_bookings(ctx):
    rows = apply_filters(all_of(store.venue_bookings), {
        "concert_id": ctx["args"].get("concert_id"),
        "venue_id": ctx["args"].get("venue_id"),
        "status": ctx["args"].get("status"),
    })
    return many(booking_view, rows, ctx["args"])


def _booking_write(ctx, roles_posture=True):
    booking = get_or_404(store.venue_bookings, ctx["path"]["rid"])
    check_body(ctx["body"], {})
    concert = store.concerts[booking["concert_id"]]
    gate_season(store.seasons[concert["season_id"]], CONCERT_WRITE_POSTURES)
    return booking, concert


@route("POST", "/v1/venue-bookings/{rid}/confirm", roles=["Treasurer"])
def confirm_booking(ctx):
    booking, concert = _booking_write(ctx)
    if booking["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "only a REQUESTED booking can be confirmed")
    season = store.seasons[concert["season_id"]]
    treasury_debit(season, booking["deposit_cents"], check=True)
    booking["status"] = "CONFIRMED"
    touch(booking)
    if concert["status"] == "PLANNING":
        concert["status"] = "VENUE_BOOKED"
        touch(concert)
    return one(booking_view, booking)


@route("POST", "/v1/venue-bookings/{rid}/decline", roles=["ChoirDirector"])
def decline_booking(ctx):
    booking, concert = _booking_write(ctx)
    if booking["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "only a REQUESTED booking can be declined")
    booking["status"] = "DECLINED"
    touch(booking)
    return one(booking_view, booking)


@route("POST", "/v1/venue-bookings/{rid}/release", roles=["ChoirDirector"])
def release_booking(ctx):
    booking, concert = _booking_write(ctx)
    if booking["status"] == "REQUESTED":
        booking["status"] = "CANCELLED"
        touch(booking)
        return one(booking_view, booking)
    if booking["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "only REQUESTED or CONFIRMED bookings can be released")
    if concert["status"] == "PERFORMED":
        raise ApiError("ERR_INVALID_STATE", "a performed concert's booking cannot be released")
    season = store.seasons[concert["season_id"]]
    treasury_credit(season, booking["deposit_cents"])
    booking["status"] = "RELEASED"
    touch(booking)
    if concert["status"] == "VENUE_BOOKED":
        concert["status"] = "PLANNING"
        touch(concert)
    return one(booking_view, booking)


# ------------------------------------------------------------- program pieces
@route("POST", "/v1/program-pieces", roles=["ChoirDirector"], code=201)
def create_piece(ctx):
    raw = ctx["body"]
    concert = resolve_ids(raw, (store.concerts, "concert_id")).get("concert_id")
    if isinstance(raw, dict) and isinstance(raw.get("featured_member_ids"), list):
        for mid in raw["featured_member_ids"]:
            get_or_404(store.members, mid)
    resolve_ids(raw, (store.guest_contracts, "guest_contract_id"))
    body = check_body(raw, {
        "concert_id": ("string", True),
        "title": ("string", True),
        "duration_seconds": ("int", True),
        "sequence_no": ("int", True),
        "featured_member_ids": ("array", False),
        "guest_contract_id": ("string", False),
    })
    if concert is None:
        concert = get_or_404(store.concerts, body["concert_id"])
    featured = body.get("featured_member_ids") or []
    for mid in featured:
        if not isinstance(mid, str):
            raise ApiError("ERR_INVALID_REQUEST", "featured_member_ids must be strings")
    gate_season(store.seasons[concert["season_id"]], CONCERT_WRITE_POSTURES)
    if any(
        p["concert_id"] == concert["id"] and p["status"] != "VOID" and p["sequence_no"] == body["sequence_no"]
        for p in store.program_pieces.values()
    ):
        raise ApiError("ERR_PROGRAM_SEQUENCE_CONFLICT", "sequence_no already used by a non-VOID piece")
    piece = new_row(
        store.program_pieces,
        concert_id=concert["id"],
        title=body["title"],
        duration_seconds=body["duration_seconds"],
        sequence_no=body["sequence_no"],
        featured_member_ids=featured,
        guest_contract_id=body.get("guest_contract_id"),
        status="DRAFT",
    )
    return one(piece_view, piece, 201)


@route("GET", "/v1/program-pieces/{rid}", roles=ALL_ROLES)
def get_piece(ctx):
    return one(piece_view, get_or_404(store.program_pieces, ctx["path"]["rid"]))


@route("GET", "/v1/program-pieces", roles=ALL_ROLES)
def list_pieces(ctx):
    rows = apply_filters(all_of(store.program_pieces), {
        "concert_id": ctx["args"].get("concert_id"),
        "guest_contract_id": ctx["args"].get("guest_contract_id"),
        "status": ctx["args"].get("status"),
    })
    return many(piece_view, rows, ctx["args"])


@route("PATCH", "/v1/program-pieces/{rid}", roles=["ChoirDirector"])
def patch_piece(ctx):
    piece = get_or_404(store.program_pieces, ctx["path"]["rid"])
    raw = ctx["body"]
    if isinstance(raw, dict) and isinstance(raw.get("featured_member_ids"), list):
        for mid in raw["featured_member_ids"]:
            get_or_404(store.members, mid)
    resolve_ids(raw, (store.guest_contracts, "guest_contract_id"))
    body = check_body(raw, {
        "title": ("string", False),
        "duration_seconds": ("int", False),
        "sequence_no": ("int", False),
        "featured_member_ids": ("array", False),
        "guest_contract_id": ("string", False),
    })
    if body.get("featured_member_ids") is not None:
        for mid in body["featured_member_ids"]:
            if not isinstance(mid, str):
                raise ApiError("ERR_INVALID_REQUEST", "featured_member_ids must be strings")
    concert = store.concerts[piece["concert_id"]]
    gate_season(store.seasons[concert["season_id"]], CONCERT_WRITE_POSTURES)
    if piece["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "only a DRAFT piece can be updated")
    if "sequence_no" in body and any(
        p["concert_id"] == piece["concert_id"] and p["id"] != piece["id"]
        and p["status"] != "VOID" and p["sequence_no"] == body["sequence_no"]
        for p in store.program_pieces.values()
    ):
        raise ApiError("ERR_PROGRAM_SEQUENCE_CONFLICT", "sequence_no already used by a non-VOID piece")
    for field in ("title", "duration_seconds", "sequence_no", "featured_member_ids", "guest_contract_id"):
        if field in body:
            piece[field] = body[field]
    touch(piece)
    return one(piece_view, piece)


@route("POST", "/v1/program-pieces/{rid}/confirm", roles=["ChoirDirector"])
def confirm_piece(ctx):
    piece = get_or_404(store.program_pieces, ctx["path"]["rid"])
    check_body(ctx["body"], {})
    concert = store.concerts[piece["concert_id"]]
    gate_season(store.seasons[concert["season_id"]], CONCERT_WRITE_POSTURES)
    if concert["status"] not in ("PLANNING", "VENUE_BOOKED"):
        raise ApiError("ERR_INVALID_STATE", "the concert is not in PLANNING or VENUE_BOOKED")
    if piece["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "only a DRAFT piece can be confirmed")
    for mid in piece["featured_member_ids"]:
        member = store.members[mid]
        if not compute_performance_eligible(member):
            raise ApiError("ERR_MEMBER_NOT_ELIGIBLE", "a featured member is not performance_eligible")
    if piece.get("guest_contract_id"):
        contract = store.guest_contracts[piece["guest_contract_id"]]
        if contract["status"] not in ("ACCEPTED", "APPROVED", "PAID"):
            raise ApiError("ERR_CONTRACT_NOT_ACCEPTED", "the linked contract is not ACCEPTED/APPROVED/PAID")
    piece["status"] = "CONFIRMED"
    touch(piece)
    sync_concert_duration(concert)
    return one(piece_view, piece)


@route("POST", "/v1/program-pieces/{rid}/void", roles=["ChoirDirector"])
def void_piece(ctx):
    piece = get_or_404(store.program_pieces, ctx["path"]["rid"])
    check_body(ctx["body"], {})
    concert = store.concerts[piece["concert_id"]]
    season = store.seasons[concert["season_id"]]
    gate_season(season, CONCERT_WRITE_POSTURES)
    if piece["status"] not in ("DRAFT", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", "the piece is already VOID")
    if piece["status"] == "CONFIRMED" and concert["status"] not in ("PLANNING", "VENUE_BOOKED"):
        raise ApiError("ERR_INVALID_STATE", "a CONFIRMED piece cannot be voided once the program is locked")
    piece["status"] = "VOID"
    touch(piece)
    if piece.get("guest_contract_id"):
        contract = store.guest_contracts.get(piece["guest_contract_id"])
        if contract is not None:
            cancel_linked_contract(contract, season, check=True)
    sync_concert_duration(concert)
    return one(piece_view, piece)


# ------------------------------------------------------------ guest contracts
@route("POST", "/v1/guest-contracts", roles=["ChoirDirector"], code=201)
def create_contract(ctx):
    # tier 4: body ids left to right in input order (season_id, then concert_id)
    ids = resolve_ids(ctx["body"], (store.seasons, "season_id"), (store.concerts, "concert_id"))
    body = check_body(ctx["body"], {
        "season_id": ("string", True),
        "musician_name": ("string", True),
        "service_lines": ("array", True),
        "travel_stipend_cents": ("int", False),
        "concert_id": ("string", False),
    })
    season = ids.get("season_id") or get_or_404(store.seasons, body["season_id"])
    validate_service_lines(body["service_lines"])
    gate_season(season, None)
    stipend = body.get("travel_stipend_cents", 0)
    contract = new_row(
        store.guest_contracts,
        season_id=season["id"],
        concert_id=body.get("concert_id"),
        musician_name=body["musician_name"],
        service_lines=body["service_lines"],
        travel_stipend_cents=stipend,
        quoted_fee_cents=quote_fee(body["service_lines"], stipend),
        cancellation_fee_cents=0,
        counter_count=0,
        status="DRAFT",
        approved_by_user_id=None,
        paid_by_user_id=None,
    )
    return one(contract_view, contract, 201)


@route("GET", "/v1/guest-contracts/{rid}", roles=ALL_ROLES)
def get_contract(ctx):
    return one(contract_view, get_or_404(store.guest_contracts, ctx["path"]["rid"]))


@route("GET", "/v1/guest-contracts", roles=ALL_ROLES)
def list_contracts(ctx):
    rows = apply_filters(all_of(store.guest_contracts), {
        "season_id": ctx["args"].get("season_id"),
        "concert_id": ctx["args"].get("concert_id"),
        "status": ctx["args"].get("status"),
    })
    return many(contract_view, rows, ctx["args"])


def _contract_write(ctx):
    contract = get_or_404(store.guest_contracts, ctx["path"]["rid"])
    gate_season(store.seasons[contract["season_id"]], None)
    return contract


@route("POST", "/v1/guest-contracts/{rid}/offer", roles=["ChoirDirector"])
def offer_contract(ctx):
    contract = _contract_write(ctx)
    body = check_body(ctx["body"], {
        "service_lines": ("array", False),
        "travel_stipend_cents": ("int", False),
    })
    if body.get("service_lines") is not None:
        validate_service_lines(body["service_lines"])
        contract["service_lines"] = body["service_lines"]
    if body.get("travel_stipend_cents") is not None:
        contract["travel_stipend_cents"] = body["travel_stipend_cents"]
    if contract["status"] not in ("DRAFT", "COUNTERED"):
        raise ApiError("ERR_INVALID_STATE", "offer is not legal from %s" % contract["status"])
    contract["quoted_fee_cents"] = quote_fee(contract["service_lines"], contract["travel_stipend_cents"])
    contract["status"] = "OFFERED"
    touch(contract)
    return one(contract_view, contract)


@route("POST", "/v1/guest-contracts/{rid}/counter", roles=["ChoirDirector"])
def counter_contract(ctx):
    contract = _contract_write(ctx)
    body = check_body(ctx["body"], {
        "expected_guest_contract_version": ("int", True),
        "service_lines": ("array", False),
        "travel_stipend_cents": ("int", False),
    })
    if body.get("service_lines") is not None:
        validate_service_lines(body["service_lines"])
    if body["expected_guest_contract_version"] != contract["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_guest_contract_version does not match the contract version")
    if contract["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", "counter is not legal from %s" % contract["status"])
    if body.get("service_lines") is not None:
        contract["service_lines"] = body["service_lines"]
    if body.get("travel_stipend_cents") is not None:
        contract["travel_stipend_cents"] = body["travel_stipend_cents"]
    contract["counter_count"] += 1
    contract["quoted_fee_cents"] = quote_fee(contract["service_lines"], contract["travel_stipend_cents"])
    contract["status"] = "COUNTERED"
    touch(contract)
    return one(contract_view, contract)


@route("POST", "/v1/guest-contracts/{rid}/accept", roles=["ChoirDirector"])
def accept_contract(ctx):
    contract = _contract_write(ctx)
    check_body(ctx["body"], {})
    if contract["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", "accept is not legal from %s" % contract["status"])
    contract["status"] = "ACCEPTED"
    touch(contract)
    return one(contract_view, contract)


@route("POST", "/v1/guest-contracts/{rid}/decline", roles=["ChoirDirector"])
def decline_contract(ctx):
    contract = _contract_write(ctx)
    check_body(ctx["body"], {})
    if contract["status"] not in ("OFFERED", "COUNTERED"):
        raise ApiError("ERR_INVALID_STATE", "decline is not legal from %s" % contract["status"])
    contract["status"] = "DECLINED"
    touch(contract)
    return one(contract_view, contract)


@route("POST", "/v1/guest-contracts/{rid}/approve", roles=["President"])
def approve_contract(ctx):
    contract = _contract_write(ctx)
    check_body(ctx["body"], {})
    if contract["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", "approve is not legal from %s" % contract["status"])
    contract["status"] = "APPROVED"
    contract["approved_by_user_id"] = ctx["uid"]
    touch(contract)
    return one(contract_view, contract)


@route("POST", "/v1/guest-contracts/{rid}/pay", roles=["Treasurer"])
def pay_contract(ctx):
    contract = _contract_write(ctx)
    check_body(ctx["body"], {})
    if contract["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "pay is not legal from %s" % contract["status"])
    if ctx["uid"] == contract["approved_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "the payer must differ from the approver")
    season = store.seasons[contract["season_id"]]
    treasury_debit(season, contract["quoted_fee_cents"], check=True)
    contract["status"] = "PAID"
    contract["paid_by_user_id"] = ctx["uid"]
    touch(contract)
    return one(contract_view, contract)


@route("POST", "/v1/guest-contracts/{rid}/cancel", roles=["ChoirDirector"])
def cancel_contract(ctx):
    contract = _contract_write(ctx)
    check_body(ctx["body"], {})
    if contract["status"] in ("DRAFT", "OFFERED", "COUNTERED"):
        contract["status"] = "CANCELLED"
        touch(contract)
        return one(contract_view, contract)
    if contract["status"] in ("ACCEPTED", "APPROVED"):
        fee = cancellation_fee(contract["quoted_fee_cents"])
        season = store.seasons[contract["season_id"]]
        treasury_debit(season, fee, check=True)
        contract["cancellation_fee_cents"] = fee
        contract["status"] = "CANCELLED"
        touch(contract)
        return one(contract_view, contract)
    raise ApiError("ERR_INVALID_STATE", "cancel is not legal from %s" % contract["status"])
