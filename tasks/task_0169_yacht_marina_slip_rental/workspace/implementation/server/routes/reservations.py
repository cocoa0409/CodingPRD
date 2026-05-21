"""Reservation routes — create, get, list, approve/check-in/check-out/cancel."""
from __future__ import annotations

from flask import Blueprint, g, request

from ..auth import require_auth
from ..clock import iso_format, parse_iso
from ..common import (
    bump,
    get_json_body,
    paginate,
    parse_pagination,
    require_fields,
    stamp_new,
)
from ..errors import ApiError
from ..marina_helpers import (
    assert_size_match,
    enforce_boater_owns,
    get_boater,
    get_marina,
    get_policy,
    get_reservation,
    get_slip,
    get_vessel,
    parse_required_iso,
    recompute_liveaboard_count,
    reservation_overlaps_slip,
)
from ..pricing import (
    chronological_total,
    forward_looking_total,
    settlement_for_readings,
    whole_day_nights,
)
from ..response import respond
from ..serializers import reservation_view, settlement_view
from ..store import gen_id, store


bp = Blueprint("reservations", __name__, url_prefix="/marinas")


VALID_STATUSES = {"DRAFT", "APPROVED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED", "EXPIRED"}


@bp.post("/<marina_id>/reservations")
@require_auth("Boater", "DockMaster")
def create_reservation(marina_id: str):
    body = get_json_body()
    require_fields(
        body,
        "boater_id",
        "vessel_id",
        "slip_id",
        "check_in_date",
        "check_out_date",
        "insurance_policy_id",
    )
    check_in = parse_required_iso(body, "check_in_date")
    check_out = parse_required_iso(body, "check_out_date")
    if not (check_out > check_in):
        raise ApiError("ERR_INVALID_DATE_RANGE", "check_out_date must be strictly after check_in_date")
    liveaboard = bool(body.get("liveaboard", False))

    with store.lock:
        get_marina(marina_id)
        boater = get_boater(marina_id, body["boater_id"])
        enforce_boater_owns(boater["id"])
        vessel = get_vessel(marina_id, body["vessel_id"])
        slip = get_slip(marina_id, body["slip_id"])
        policy = get_policy(marina_id, body["insurance_policy_id"])

        # Vessel must belong to the named boater
        if vessel.get("boater_id") != boater["id"]:
            raise ApiError("ERR_NOT_FOUND", "Vessel does not belong to the named boater")
        # Policy must belong to the boater
        if policy.get("boater_id") != boater["id"]:
            raise ApiError("ERR_NOT_FOUND", "Policy does not belong to the named boater")

        nights = whole_day_nights(check_in, check_out)
        reservation = {
            "marina_id": marina_id,
            "boater_id": boater["id"],
            "vessel_id": vessel["id"],
            "slip_id": slip["id"],
            "check_in_date": iso_format(check_in),
            "check_out_date": iso_format(check_out),
            "liveaboard": liveaboard,
            "insurance_policy_id": policy["id"],
            "status": "DRAFT",
            "estimated_total_cents": None,
            "final_total_cents": None,
            "nights": nights,
        }
        stamp_new(reservation)
        store.reservations[reservation["id"]] = reservation
    return respond(reservation_view(reservation), 201)


@bp.get("/<marina_id>/reservations/<reservation_id>")
@require_auth("DockMaster", "BillingClerk", "Boater")
def fetch_reservation(marina_id: str, reservation_id: str):
    with store.lock:
        get_marina(marina_id)
        res = get_reservation(marina_id, reservation_id)
        if g.user_role == "Boater":
            enforce_boater_owns(res["boater_id"])
        return respond(reservation_view(res), 200)


@bp.get("/<marina_id>/reservations")
@require_auth("DockMaster", "BillingClerk")
def list_reservations(marina_id: str):
    with store.lock:
        get_marina(marina_id)
        limit, offset = parse_pagination()
        status_filter = request.args.get("status")
        slip_id = request.args.get("slip_id")
        boater_id = request.args.get("boater_id")
        items = [
            r
            for r in store.reservations.values()
            if r.get("marina_id") == marina_id
            and (status_filter is None or r.get("status") == status_filter)
            and (slip_id is None or r.get("slip_id") == slip_id)
            and (boater_id is None or r.get("boater_id") == boater_id)
        ]
        items.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))
        sliced, meta = paginate(items, limit, offset)
        return respond([reservation_view(r) for r in sliced], 200, list_meta=meta)


def _check_policy_covers(policy: dict, check_in, check_out) -> bool:
    if policy.get("status") != "ACTIVE":
        return False
    try:
        eff = parse_iso(policy["effective_date"])
        exp = parse_iso(policy["expiration_date"])
    except (KeyError, ValueError):
        return False
    return eff <= check_in and exp >= check_out


@bp.post("/<marina_id>/reservations/<reservation_id>/approve")
@require_auth("DockMaster")
def approve_reservation(marina_id: str, reservation_id: str):
    with store.lock:
        marina = get_marina(marina_id)
        res = get_reservation(marina_id, reservation_id)

        # State precondition (priority 4)
        if res.get("status") != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Reservation is not in DRAFT")

        vessel = get_vessel(marina_id, res["vessel_id"])
        slip = get_slip(marina_id, res["slip_id"])

        # Slip must be currently AVAILABLE (size-match still happens before
        # this PRD says: slip status must be AVAILABLE; if MAINTENANCE/RETIRED,
        # treat as size-match failures? PRD §3.4 says "The slip must also be
        # currently AVAILABLE" between size match and overlap. We'll model that
        # as ERR_INVALID_STATE since "state precondition" covers it.
        if slip.get("status") != "AVAILABLE":
            raise ApiError("ERR_INVALID_STATE", "Slip is not AVAILABLE")

        # Priority 5/6/7: size-match (raise the first failure)
        assert_size_match(slip, vessel)

        check_in = parse_iso(res["check_in_date"])
        check_out = parse_iso(res["check_out_date"])

        # Priority 8: insurance coverage
        policy = store.policies.get(res.get("insurance_policy_id"))
        if policy is None or policy.get("marina_id") != marina_id:
            raise ApiError("ERR_INSURANCE_LAPSED", "Insurance policy not found for this marina")
        if not _check_policy_covers(policy, check_in, check_out):
            raise ApiError("ERR_INSURANCE_LAPSED", "Insurance policy does not cover term")

        # Priority 9: liveaboard policy
        if res.get("liveaboard"):
            if not slip.get("liveaboard_allowed"):
                raise ApiError(
                    "ERR_LIVEABOARD_POLICY_VIOLATION",
                    "Slip does not permit liveaboard reservations",
                )
            if vessel.get("holding_tank_gallons") is None:
                raise ApiError(
                    "ERR_LIVEABOARD_POLICY_VIOLATION",
                    "Vessel missing holding_tank_gallons",
                )

            # Priority 10: liveaboard quota
            if int(marina.get("liveaboard_active_count", 0)) >= int(
                marina.get("liveaboard_quota", 0)
            ):
                raise ApiError(
                    "ERR_LIVEABOARD_QUOTA_EXCEEDED",
                    "Marina liveaboard quota would be exceeded",
                )

        # Priority 11: slip occupancy / overlap
        if reservation_overlaps_slip(slip["id"], check_in, check_out):
            raise ApiError("ERR_SLIP_OCCUPIED", "Another reservation overlaps this slip term")

        # Success — compute forward-looking total
        res["estimated_total_cents"] = forward_looking_total(
            base_daily_rate_cents=int(marina["base_daily_rate_cents"]),
            loa_feet=vessel["loa_feet"],
            flat_daily_charge_cents=int(slip["flat_daily_charge_cents"]),
            liveaboard=bool(res.get("liveaboard")),
            check_in_date=check_in,
            check_out_date=check_out,
        )
        res["status"] = "APPROVED"
        bump(res)

        if res.get("liveaboard"):
            recompute_liveaboard_count(marina)
            bump(marina)

        return respond(reservation_view(res), 200)


@bp.post("/<marina_id>/reservations/<reservation_id>/check-in")
@require_auth("DockMaster")
def check_in_reservation(marina_id: str, reservation_id: str):
    with store.lock:
        marina = get_marina(marina_id)
        res = get_reservation(marina_id, reservation_id)
        if res.get("status") != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", "Reservation is not APPROVED")
        current = parse_iso(marina["current_date"])
        check_in = parse_iso(res["check_in_date"])
        if current < check_in:
            raise ApiError("ERR_INVALID_STATE", "Marina clock has not reached check_in_date")
        res["status"] = "CHECKED_IN"
        bump(res)
        return respond(reservation_view(res), 200)


@bp.post("/<marina_id>/reservations/<reservation_id>/check-out")
@require_auth("DockMaster")
def check_out_reservation(marina_id: str, reservation_id: str):
    with store.lock:
        marina = get_marina(marina_id)
        res = get_reservation(marina_id, reservation_id)
        if res.get("status") != "CHECKED_IN":
            raise ApiError("ERR_INVALID_STATE", "Reservation is not CHECKED_IN")
        current = parse_iso(marina["current_date"])
        check_in = parse_iso(res["check_in_date"])
        check_out = parse_iso(res["check_out_date"])
        if current < check_in:
            raise ApiError("ERR_INVALID_STATE", "Marina clock has not reached check_in_date")

        # Block check-out if any SCHEDULED pump-out references this reservation
        for p in store.pump_out_jobs.values():
            if p.get("reservation_id") == res["id"] and p.get("status") == "SCHEDULED":
                raise ApiError(
                    "ERR_HAS_DEPENDENCIES",
                    "A SCHEDULED pump-out job still references this reservation",
                )

        vessel = get_vessel(marina_id, res["vessel_id"])
        slip = get_slip(marina_id, res["slip_id"])

        res["final_total_cents"] = chronological_total(
            base_daily_rate_cents=int(marina["base_daily_rate_cents"]),
            loa_feet=vessel["loa_feet"],
            flat_daily_charge_cents=int(slip["flat_daily_charge_cents"]),
            liveaboard=bool(res.get("liveaboard")),
            check_in_date=check_in,
            check_out_date=check_out,
        )
        res["status"] = "CHECKED_OUT"
        bump(res)

        # If liveaboard: run the utility settlement over [check_in_date, current_date)
        if res.get("liveaboard"):
            readings = [
                r
                for r in store.utility_readings.values()
                if r.get("reservation_id") == res["id"] and not r.get("applied_in_settlement")
            ]
            # Filter by read_at in [check_in_date, current_date) and sort
            in_window = []
            for r in readings:
                try:
                    read_at = parse_iso(r["read_at"])
                except (KeyError, ValueError):
                    continue
                if check_in <= read_at < current:
                    in_window.append((read_at, r["id"], r))
            in_window.sort(key=lambda t: (t[0], t[1]))
            ordered_readings = [t[2] for t in in_window]

            agg = settlement_for_readings(
                readings=ordered_readings,
                liveaboard=True,
            )
            settlement = {
                "reservation_id": res["id"],
                "window_start": iso_format(check_in),
                "window_end": iso_format(current),
                "kwh_total": agg["kwh_total"],
                "water_gallons_total": agg["water_gallons_total"],
                "sewage_charge_cents": agg["sewage_charge_cents"],
                "total_cents": agg["total_cents"],
            }
            stamp_new(settlement)
            store.utility_settlements[settlement["id"]] = settlement

            for reading in ordered_readings:
                reading["applied_in_settlement"] = True

            recompute_liveaboard_count(marina)
            bump(marina)

        return respond(reservation_view(res), 200)


@bp.post("/<marina_id>/reservations/<reservation_id>/cancel")
@require_auth("Boater", "DockMaster")
def cancel_reservation(marina_id: str, reservation_id: str):
    with store.lock:
        marina = get_marina(marina_id)
        res = get_reservation(marina_id, reservation_id)
        if g.user_role == "Boater":
            enforce_boater_owns(res["boater_id"])
        if res.get("status") not in ("DRAFT", "APPROVED"):
            raise ApiError("ERR_INVALID_STATE", "Reservation is not in a cancellable state")
        was_approved_liveaboard = res.get("status") == "APPROVED" and res.get("liveaboard")
        if res.get("status") == "APPROVED":
            for p in store.pump_out_jobs.values():
                if p.get("reservation_id") == res["id"] and p.get("status") == "SCHEDULED":
                    raise ApiError(
                        "ERR_HAS_DEPENDENCIES",
                        "A SCHEDULED pump-out job still references this reservation",
                    )
        res["status"] = "CANCELLED"
        bump(res)
        if was_approved_liveaboard:
            recompute_liveaboard_count(marina)
            bump(marina)
        return respond(reservation_view(res), 200)
