"""Showtime endpoints (PRD §3.2, §3.8, §3.9): scheduling + seat-map materialize,
open/repricing/cancel/close transitions, and reverse-reachability list reads.
"""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import errors as E
from middleware import (
    authenticate, authorize, current_role, current_user_id,
    CINEMA_MANAGER, BOX_OFFICE_AGENT, MEMBER, DISTRIBUTOR,
)
import response
from services import common as C
from services import domain as D
from routes._helpers import get_or_404

bp = Blueprint("showtimes", __name__)

VALID_PROFILES = {"STANDARD", "MATINEE", "PEAK"}
VALID_RENTAL_BASIS = {"BOX_OFFICE", "RENTAL"}


# ============================================================================
# Schedule a showtime (materializes the seat map)
# ============================================================================
@bp.route("/auditoriums/<aud_id>/showtimes", methods=["POST"])
def schedule_showtime(aud_id):
    role = authenticate()
    authorize(role, {CINEMA_MANAGER})

    # Existence (priority 4): auditorium then film FK.
    aud = get_or_404(db.auditoriums, aud_id, "Auditorium")

    body = C.get_body()
    C.require_fields(body, ["film_id", "starts_at", "pricing_profile", "base_price_cents"])
    film_id = C.require_str(body, "film_id")
    starts_raw = C.require_str(body, "starts_at")
    starts_at = C.parse_iso(starts_raw)
    profile = body.get("pricing_profile")
    if profile not in VALID_PROFILES:
        raise E.invalid_request("pricing_profile must be one of STANDARD|MATINEE|PEAK")
    base_price = C.require_int(body, "base_price_cents")
    if base_price < 0:
        raise E.invalid_request("base_price_cents must be >= 0")

    rental_basis = body.get("rental_basis", "BOX_OFFICE")
    if rental_basis is None:
        rental_basis = "BOX_OFFICE"
    if rental_basis not in VALID_RENTAL_BASIS:
        raise E.invalid_request("rental_basis must be BOX_OFFICE or RENTAL")

    fee = body.get("private_rental_fee_cents", 0)
    if fee is None:
        fee = 0
    if not C.is_int(fee) or fee < 0:
        raise E.invalid_request("private_rental_fee_cents must be an integer >= 0")

    film = get_or_404(db.films, film_id, "Film")

    # ---- business band (PRD §2.7 fixed order) ----
    # priority 7: matinee window
    if profile == "MATINEE" and starts_at.hour >= D.MATINEE_CUTOFF_HOUR:
        raise E.APIError(E.ERR_MATINEE_WINDOW_VIOLATION, 422,
                         "MATINEE requires local start hour < 17")

    # compute ends_at = starts_at + runtime + trailer pad
    ends_at = starts_at + timedelta(minutes=film["runtime_minutes"] + D.TRAILER_PAD_MINUTES)

    # priority 8: auditorium double-booking (interval + turnaround buffer)
    turnaround = aud["turnaround_minutes"]
    new_end_with_buffer = ends_at + timedelta(minutes=turnaround)
    for other in db.showtimes.values():
        if other["auditorium_id"] != aud_id:
            continue
        if other["status"] == "CANCELLED":
            continue
        o_start = C.parse_iso(other["starts_at"])
        o_end = C.parse_iso(other["ends_at"])
        o_end_buf = o_end + timedelta(minutes=turnaround)
        # Overlap of [starts_at, ends_at+buffer) with [o_start, o_end+buffer).
        if starts_at < o_end_buf and o_start < new_end_with_buffer:
            raise E.APIError(E.ERR_AUDITORIUM_DOUBLE_BOOKED, 409,
                             "Showtime overlaps an existing screening (incl. turnaround)")

    # priority 9: rental-fee invariant
    if rental_basis == "RENTAL":
        if fee <= 0:
            raise E.APIError(E.ERR_RENTAL_FEE_INVALID, 422,
                             "RENTAL showtime requires private_rental_fee_cents > 0")
    else:  # BOX_OFFICE
        if fee != 0:
            raise E.APIError(E.ERR_RENTAL_FEE_INVALID, 422,
                             "BOX_OFFICE showtime requires private_rental_fee_cents == 0")

    st = C.new_common_fields()
    st.update({
        "auditorium_id": aud_id,
        "film_id": film_id,
        "starts_at": starts_raw,
        "ends_at": ends_at.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ends_at.microsecond // 1000:03d}Z",
        "pricing_profile": profile,
        "base_price_cents": base_price,
        "status": "SCHEDULED",
        "rental_basis": rental_basis,
        "private_rental_fee_cents": fee,
    })
    db.showtimes[st["id"]] = st

    # Materialize the seat map: one Seat per physical seat.
    for i in range(aud["seat_count"]):
        seat = C.new_lean_fields()
        seat.update({
            "showtime_id": st["id"],
            "row_label": "A",
            "seat_number": i + 1,
            "seat_class": "STANDARD",
            "occupancy": "FREE",
        })
        db.seats[seat["id"]] = seat

    return response.ok_object(C.serialize(D.project_showtime(st)), 201)


# ============================================================================
# Reads
# ============================================================================
@bp.route("/auditoriums/<aud_id>/showtimes", methods=["GET"])
def list_auditorium_showtimes(aud_id):
    role = authenticate()
    authorize(role, {CINEMA_MANAGER, BOX_OFFICE_AGENT})
    get_or_404(db.auditoriums, aud_id, "Auditorium")
    limit, offset = C.parse_pagination()
    status = request.args.get("status")
    items = [s for s in db.showtimes.values() if s["auditorium_id"] == aud_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    data = [C.serialize(D.project_showtime(s)) for s in page]
    return response.ok_array(data, limit, offset, total, 200)


@bp.route("/showtimes/<st_id>", methods=["GET"])
def get_showtime(st_id):
    role = authenticate()
    authorize(role, {CINEMA_MANAGER, BOX_OFFICE_AGENT, MEMBER})
    st = get_or_404(db.showtimes, st_id, "Showtime")
    # Lazily expire past-TTL HELD orders before computing counts.
    D.expire_showtime_holds(st_id)
    return response.ok_object(C.serialize(D.project_showtime(st)), 200)


@bp.route("/showtimes", methods=["GET"])
def list_showtimes():
    role = authenticate()
    authorize(role, {CINEMA_MANAGER, BOX_OFFICE_AGENT, DISTRIBUTOR})
    limit, offset = C.parse_pagination()
    film_id = request.args.get("film_id")
    status = request.args.get("status")
    items = list(db.showtimes.values())
    # Distributor scope: only showtimes of the distributor's own films.
    if current_role() == DISTRIBUTOR:
        own_films = {f["id"] for f in db.films.values() if f["distributor_id"] == current_user_id()}
        items = [s for s in items if s["film_id"] in own_films]
    if film_id is not None:
        items = [s for s in items if s["film_id"] == film_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    data = [C.serialize(D.project_showtime(s)) for s in page]
    return response.ok_array(data, limit, offset, total, 200)


@bp.route("/showtimes/<st_id>/seats", methods=["GET"])
def list_seats(st_id):
    role = authenticate()
    authorize(role, {CINEMA_MANAGER, BOX_OFFICE_AGENT, MEMBER})
    get_or_404(db.showtimes, st_id, "Showtime")
    D.expire_showtime_holds(st_id)
    limit, offset = C.parse_pagination()
    occupancy = request.args.get("occupancy")
    seats = [s for s in db.seats.values() if s["showtime_id"] == st_id]
    projected = [D.project_seat(s) for s in seats]
    if occupancy is not None:
        projected = [s for s in projected if s["occupancy"] == occupancy]
    projected = C.order_by_created(projected)
    page, total = C.paginate(projected, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)


@bp.route("/showtimes/<st_id>/orders", methods=["GET"])
def list_showtime_orders(st_id):
    role = authenticate()
    authorize(role, {CINEMA_MANAGER, BOX_OFFICE_AGENT})
    get_or_404(db.showtimes, st_id, "Showtime")
    D.expire_showtime_holds(st_id)
    limit, offset = C.parse_pagination()
    status = request.args.get("status")
    items = [o for o in db.orders.values() if o["showtime_id"] == st_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)


@bp.route("/showtimes/<st_id>/settlement", methods=["GET"])
def get_showtime_settlement(st_id):
    role = authenticate()
    authorize(role, {CINEMA_MANAGER, DISTRIBUTOR})
    get_or_404(db.showtimes, st_id, "Showtime")
    limit, offset = C.parse_pagination()
    items = [s for s in db.settlements.values() if s["showtime_id"] == st_id]
    if current_role() == DISTRIBUTOR:
        items = [s for s in items if s["distributor_id"] == current_user_id()]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)


# ============================================================================
# Transitions
# ============================================================================
@bp.route("/showtimes/<st_id>/open", methods=["POST"])
def open_showtime(st_id):
    role = authenticate()
    authorize(role, {CINEMA_MANAGER})
    st = get_or_404(db.showtimes, st_id, "Showtime")
    if st["status"] != "SCHEDULED":
        raise E.invalid_state("Showtime must be SCHEDULED to open")
    film = db.films.get(st["film_id"])
    if film is None or film["status"] not in ("BOOKING", "RUNNING"):
        raise E.invalid_state("Film must be BOOKING or RUNNING to open a showtime")
    if st["rental_basis"] == "RENTAL" and st["private_rental_fee_cents"] <= 0:
        raise E.APIError(E.ERR_RENTAL_FEE_INVALID, 422,
                         "RENTAL showtime requires private_rental_fee_cents > 0")
    st["status"] = "ON_SALE"
    # Film BOOKING -> RUNNING bubble-up.
    if film["status"] == "BOOKING":
        film["status"] = "RUNNING"
        C.touch(film)
    C.touch(st)
    return response.ok_object(C.serialize(D.project_showtime(st)), 200)


@bp.route("/showtimes/<st_id>/pricing", methods=["PATCH"])
def reprice_showtime(st_id):
    role = authenticate()
    authorize(role, {CINEMA_MANAGER})
    st = get_or_404(db.showtimes, st_id, "Showtime")
    if st["status"] not in ("SCHEDULED", "ON_SALE"):
        raise E.invalid_state("Showtime must be SCHEDULED or ON_SALE to re-price")
    body = C.get_body()
    new_profile = body.get("pricing_profile")
    new_base = body.get("base_price_cents")
    if new_profile is None and new_base is None:
        raise E.invalid_request("Must supply pricing_profile and/or base_price_cents")
    if new_profile is not None:
        if new_profile not in VALID_PROFILES:
            raise E.invalid_request("pricing_profile must be one of STANDARD|MATINEE|PEAK")
        if new_profile == "MATINEE":
            starts_at = C.parse_iso(st["starts_at"])
            if starts_at.hour >= D.MATINEE_CUTOFF_HOUR:
                raise E.APIError(E.ERR_MATINEE_WINDOW_VIOLATION, 422,
                                 "MATINEE requires local start hour < 17")
        st["pricing_profile"] = new_profile
    if new_base is not None:
        if not C.is_int(new_base) or new_base < 0:
            raise E.invalid_request("base_price_cents must be an integer >= 0")
        st["base_price_cents"] = new_base
    C.touch(st)
    return response.ok_object(C.serialize(D.project_showtime(st)), 200)


@bp.route("/showtimes/<st_id>/cancel", methods=["POST"])
def cancel_showtime(st_id):
    role = authenticate()
    authorize(role, {CINEMA_MANAGER})
    st = get_or_404(db.showtimes, st_id, "Showtime")

    # priority 5: state
    if st["status"] not in ("SCHEDULED", "ON_SALE"):
        raise E.invalid_state("Showtime must be SCHEDULED or ON_SALE to cancel")

    # priority 6: OCC
    body = C.get_body()
    C.require_fields(body, ["expected_showtime_version"])
    expected = body.get("expected_showtime_version")
    if not C.is_int(expected):
        raise E.invalid_request("expected_showtime_version must be an integer")
    if expected != st["version"]:
        raise E.APIError(E.ERR_STALE_SHOWTIME_VERSION, 412,
                         "expected_showtime_version does not match current version")

    started_on_sale = st["status"] == "ON_SALE"
    st["status"] = "CANCELLED"

    if started_on_sale:
        # Refund every PAID order in full (each its own cascade), cancel HELD.
        for order in list(db.orders.values()):
            if order["showtime_id"] != st_id:
                continue
            if order["status"] == "PAID":
                D.refund_paid_order(order, "ORIGINAL", from_cascade=True)
            elif order["status"] == "HELD":
                order["status"] = "CANCELLED"
                D._void_tickets_and_free_seats(order)
                C.touch(order)
    # Free any remaining seats (SCHEDULED case: pre-created seat map).
    for seat in db.seats.values():
        if seat["showtime_id"] == st_id:
            seat["occupancy"] = "FREE"

    C.touch(st)
    return response.ok_object(C.serialize(D.project_showtime(st)), 200)


@bp.route("/showtimes/<st_id>/close", methods=["POST"])
def close_showtime(st_id):
    role = authenticate()
    authorize(role, {CINEMA_MANAGER})
    st = get_or_404(db.showtimes, st_id, "Showtime")
    if st["status"] != "ON_SALE":
        raise E.invalid_state("Showtime must be ON_SALE to close")

    # Lazily expire any past-TTL HELD orders before the no-HELD check.
    D.expire_showtime_holds(st_id)

    # priority 18: close readiness — current >= ends_at AND no HELD order remains.
    now = clock.now()
    ends_at = C.parse_iso(st["ends_at"])
    if now < ends_at:
        raise E.APIError(E.ERR_SHOWTIME_NOT_OVER, 409, "Showtime is not over yet")
    for order in db.orders.values():
        if order["showtime_id"] == st_id and order["status"] == "HELD":
            raise E.APIError(E.ERR_SHOWTIME_NOT_OVER, 409, "A HELD order remains on the showtime")

    st["status"] = "CLOSED"
    _create_settlement(st)
    C.touch(st)
    return response.ok_object(C.serialize(D.project_showtime(st)), 200)


def _create_settlement(st: dict) -> None:
    """Compute the distributor split and persist exactly one Settlement (PRD §3.9)."""
    from decimal import Decimal

    film = db.films[st["film_id"]]
    distributor_id = film["distributor_id"]
    distributor = db.distributors[distributor_id]

    if st["rental_basis"] == "BOX_OFFICE":
        gross = D.current_gross_receipts(st["id"])
        week_index = _week_index(st, film)
        applied_pct = _select_split_term(film["split_schedule"], week_index)
        sliding_share = C.round_half_up(Decimal(gross) * Decimal(str(applied_pct)))
        distributor_share = max(sliding_share, distributor["minimum_guarantee_cents"])
        house_share = gross - distributor_share
    else:  # RENTAL
        gross = st["private_rental_fee_cents"]
        applied_pct = float(D.RENTAL_HOUSE_DISTRIBUTOR_PCT)
        distributor_share = C.round_half_up(Decimal(gross) * D.RENTAL_HOUSE_DISTRIBUTOR_PCT)
        house_share = gross - distributor_share

    settlement = C.new_common_fields()
    settlement.update({
        "showtime_id": st["id"],
        "film_id": film["id"],
        "distributor_id": distributor_id,
        "gross_receipts_cents": gross,
        "applied_distributor_pct": applied_pct,
        "distributor_share_cents": distributor_share,
        "house_share_cents": house_share,
    })
    db.settlements[settlement["id"]] = settlement


def _week_index(st: dict, film: dict) -> int:
    release_dt = film.get("_release_dt") or C.parse_iso(film["release_date"])
    starts_at = C.parse_iso(st["starts_at"])
    delta = starts_at - release_dt
    weeks = delta.total_seconds() / (7 * 24 * 3600)
    import math
    return max(0, math.floor(weeks))


def _select_split_term(schedule: list, week_index: int):
    """Pick the distributor_pct of the term with the greatest week_index <= week_index."""
    best = None
    for term in schedule:
        wi = term["week_index"]
        if wi <= week_index and (best is None or wi > best["week_index"]):
            best = term
    if best is None:
        # Guaranteed week_index 0 entry exists; fall back to it defensively.
        best = min(schedule, key=lambda t: t["week_index"])
    return best["distributor_pct"]
