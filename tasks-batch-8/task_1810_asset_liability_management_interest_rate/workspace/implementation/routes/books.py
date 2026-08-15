"""AlmBook and Position endpoints (PRD 3.1)."""

import store
from envelope import list_response, object_response
from errors import ApiError
from serializers import book_json, position_json
from services import (
    active_positions,
    positions_of_book,
    recompute_book_totals,
    stamp_new,
    touch,
)
from validate import opt_bool, opt_int, req_enum, req_int, req_num, req_str

from routes.common import READ_ROLES, endpoint, get_or_404

CATEGORIES = ("LOAN", "SECURITY", "DEPOSIT", "BORROWING")
DEPOSIT_SEGMENTS = ("RETAIL_NONMATURITY", "BUSINESS_NONMATURITY", "TIME")


@endpoint("POST", "/books", roles=["TreasuryAnalyst"])
def create_book(ctx):
    body = ctx.body
    # Rung 4: body shape.
    name = req_str(body, "name")
    base_curve = req_int(body, "base_curve_rate_bps")
    min_hedged = opt_int(body, "min_hedged_notional_cents", min_v=0, default=0)
    book = {
        "name": name,
        "base_curve_rate_bps": base_curve,
        "min_hedged_notional_cents": min_hedged,
        "status": "DRAFT",
        "total_assets_cents": 0,
        "total_liabilities_cents": 0,
        "hedged_notional_cents": 0,
    }
    stamp_new(book)
    store.books[book["id"]] = book
    return object_response(book_json(book), 201)


@endpoint("GET", "/books/<book_id>", roles=READ_ROLES)
def get_book(ctx):
    book = get_or_404(store.books, ctx.param("book_id"))
    return object_response(book_json(book))


@endpoint("POST", "/books/<book_id>/activate", roles=["TreasuryAnalyst"])
def activate_book(ctx):
    book = get_or_404(store.books, ctx.param("book_id"))
    # Rung 6: state-transition legality, then activation completeness.
    if book["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    active = active_positions(book["id"])
    has_asset = any(p["category"] in ("LOAN", "SECURITY") for p in active)
    has_liability = any(p["category"] in ("DEPOSIT", "BORROWING") for p in active)
    if not (has_asset and has_liability):
        raise ApiError("ERR_BOOK_ACTIVATION_INCOMPLETE")
    book["status"] = "ACTIVE"
    touch(book)  # activation increments the book version by one
    return object_response(book_json(book))


@endpoint("POST", "/books/<book_id>/positions", roles=["TreasuryAnalyst"])
def create_position(ctx):
    book = get_or_404(store.books, ctx.param("book_id"))
    body = ctx.body
    # Rung 4: generic shape first, then the deposit-segment conditional.
    category = req_enum(body, "category", CATEGORIES)
    balance = req_int(body, "balance_cents", min_v=1)
    rate = req_int(body, "rate_bps", min_v=0)
    runoff = req_num(body, "scheduled_runoff_pct", min_v=0, max_v=100)
    prepay = opt_bool(body, "is_prepayment_eligible", default=False)
    duration = req_num(body, "duration_years", min_v=0)
    segment = body.get("deposit_segment")
    if category == "DEPOSIT":
        if segment is None:
            raise ApiError("ERR_DEPOSIT_SEGMENT_REQUIRED")
        if segment not in DEPOSIT_SEGMENTS:
            raise ApiError("ERR_INVALID_REQUEST")
    else:
        segment = None
    position = {
        "book_id": book["id"],
        "category": category,
        "deposit_segment": segment,
        "balance_cents": balance,
        "rate_bps": rate,
        "scheduled_runoff_pct": runoff,
        "is_prepayment_eligible": prepay,
        "duration_years": duration,
        "status": "ACTIVE",
    }
    stamp_new(position)
    store.positions[position["id"]] = position
    recompute_book_totals(book)
    touch(book)  # position creation increments the book version
    return object_response(position_json(position), 201)


@endpoint("GET", "/books/<book_id>/positions", roles=READ_ROLES)
def list_positions(ctx):
    book = get_or_404(store.books, ctx.param("book_id"))
    rows = positions_of_book(book["id"])
    category = ctx.args.get("category")
    if category is not None:
        rows = [p for p in rows if p["category"] == category]
    status = ctx.args.get("status")
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    return list_response(rows, ctx.args, position_json)


@endpoint("GET", "/positions/<position_id>", roles=READ_ROLES)
def get_position(ctx):
    position = get_or_404(store.positions, ctx.param("position_id"))
    return object_response(position_json(position))


@endpoint("PATCH", "/positions/<position_id>", roles=["TreasuryAnalyst"])
def patch_position(ctx):
    position = get_or_404(store.positions, ctx.param("position_id"))
    body = ctx.body
    # Rung 4: OCC field is non-optional; optional economics validated if present.
    expected = req_int(body, "expected_book_version")
    if "balance_cents" in body and body["balance_cents"] is not None:
        req_int(body, "balance_cents", min_v=1)
    if "rate_bps" in body and body["rate_bps"] is not None:
        req_int(body, "rate_bps", min_v=0)
    if "scheduled_runoff_pct" in body and body["scheduled_runoff_pct"] is not None:
        req_num(body, "scheduled_runoff_pct", min_v=0, max_v=100)
    if "is_prepayment_eligible" in body and body["is_prepayment_eligible"] is not None:
        from validate import req_bool
        req_bool(body, "is_prepayment_eligible")
    if "duration_years" in body and body["duration_years"] is not None:
        req_num(body, "duration_years", min_v=0)
    # Rung 5: optimistic concurrency against the parent book.
    book = get_or_404(store.books, position["book_id"])
    if expected != book["version"]:
        raise ApiError("ERR_STALE_VERSION")
    for field in (
        "balance_cents", "rate_bps", "scheduled_runoff_pct",
        "is_prepayment_eligible", "duration_years",
    ):
        if field in body and body[field] is not None:
            position[field] = body[field]
    touch(position)
    recompute_book_totals(book)
    touch(book)  # position patching increments the book version
    return object_response(position_json(position))


@endpoint("POST", "/positions/<position_id>/retire", roles=["TreasuryAnalyst"])
def retire_position(ctx):
    position = get_or_404(store.positions, ctx.param("position_id"))
    # Rung 6: only an ACTIVE position can retire.
    if position["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    # Rung 11: blocked while a PROPOSED/DESIGNATED/ACTIVE hedge references it.
    for hedge in store.hedges.values():
        if (
            hedge["position_id"] == position["id"]
            and hedge["status"] in ("PROPOSED", "DESIGNATED", "ACTIVE")
        ):
            raise ApiError("ERR_POSITION_HAS_ACTIVE_HEDGE")
    position["status"] = "RETIRED"
    touch(position)
    book = get_or_404(store.books, position["book_id"])
    recompute_book_totals(book)
    touch(book)  # position retirement increments the book version
    return object_response(position_json(position))
