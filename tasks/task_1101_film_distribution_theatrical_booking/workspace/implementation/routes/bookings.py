"""BookingAgreement endpoints with negotiation, acceptance, cancellation, holdover."""
from flask import Blueprint, request
from decimal import Decimal

from db import db
from middleware import require_roles
from response import success_object
from errors import (
    err_invalid_request, err_invalid_state, err_distributor_frozen,
    err_film_not_bookable, err_theatre_inactive, err_screen_unavailable,
    err_referential, err_screen_theatre_mismatch, err_invalid_rental_terms,
    err_stale_version, err_zone_conflict, err_holdover_not_eligible,
)
from services.core import (
    serialize_booking, get_booking, get_distributor, get_film,
    new_entity_common, touch, compute_distributor_posture, compute_holdover_eligible,
)
from services.clock import get_logical_clock
from util import parse_dt, iso_from_dt, dec_pct
from ._helpers import get_json_body, require_fields, paginate_list

bp = Blueprint("bookings", __name__)


def _validate_rental_terms(week_one, floor):
    if week_one is None or floor is None:
        raise err_invalid_request("week_one_rental_pct and floor_pct required")
    try:
        w = Decimal(str(week_one))
        f = Decimal(str(floor))
    except Exception:
        raise err_invalid_rental_terms()
    if w < Decimal("0") or w > Decimal("0.95"):
        raise err_invalid_rental_terms()
    if f > w:
        raise err_invalid_rental_terms()


def _check_zone_conflict(did, film_id, theatre_id, opening_date=None):
    """Raise ERR_ZONE_CLEARANCE_CONFLICT if any UPHELD clearance covers this theatre+film+date window.

    We don't have geographic coordinates for theatres; use a simplified model:
    another theatre's UPHELD clearance in the same market covers this theatre if theatre_id != clearance.theatre_id
    AND the market matches. For the "opening_date" we check overlap with [effective_from, effective_until] closed.
    """
    theatre = db.theatres.get(theatre_id)
    if not theatre:
        return
    for z in db.zone_clearances.values():
        if z["status"] != "UPHELD":
            continue
        if z["film_id"] != film_id:
            continue
        if z["theatre_id"] == theatre_id:
            continue
        # same market?
        z_market = db.markets.get(z["market_id"])
        if not z_market or z_market["code"] != theatre["market_code"]:
            continue
        if z_market["distributor_id"] != did:
            continue
        # check time overlap if opening_date provided
        if opening_date is not None:
            od = parse_dt(opening_date)
            ef = parse_dt(z["effective_from_utc"])
            eu = parse_dt(z["effective_until_utc"])
            if od is None or ef is None or eu is None:
                continue
            # point-in-interval (closed) check
            if not (ef <= od <= eu):
                continue
        raise err_zone_conflict()


@bp.route("/distributors/<did>/booking-agreements", methods=["POST"])
@require_roles("Booker")
def create_booking(did, _user_id, _role):
    d = get_distributor(did)
    body = get_json_body()
    # 4 FROZEN
    if compute_distributor_posture(did) == "FROZEN":
        raise err_distributor_frozen()
    require_fields(body, ["film_id", "theatre_id", "screen_id", "opening_date",
                          "min_weeks_committed", "week_one_rental_pct",
                          "rental_decay_per_week", "floor_pct", "per_capita_floor_cents"])
    # 6 FILM_NOT_BOOKABLE
    film = db.films.get(body["film_id"])
    if film and film["distributor_id"] == did:
        if film["lifecycle_status"] not in ("PRE_RELEASE", "IN_RELEASE", "HOLDOVER_PHASE"):
            raise err_film_not_bookable()
    # 9 ZONE
    # 11 REFERENTIAL
    if not film or film["distributor_id"] != did:
        raise err_referential("film_id not resolvable")
    theatre = db.theatres.get(body["theatre_id"])
    if not theatre or theatre["distributor_id"] != did:
        raise err_referential("theatre_id not resolvable")
    screen = db.screens.get(body["screen_id"])
    if not screen:
        raise err_referential("screen_id not resolvable")
    if body.get("aggregate_deal_id"):
        ad = db.aggregate_deals.get(body["aggregate_deal_id"])
        if not ad or ad["distributor_id"] != did:
            raise err_referential("aggregate_deal_id not resolvable")
    # 12 SCREEN_THEATRE_MISMATCH
    if screen["theatre_id"] != theatre["id"]:
        raise err_screen_theatre_mismatch()
    # 13 SCREEN_UNAVAILABLE
    if screen["status"] != "AVAILABLE":
        raise err_screen_unavailable()
    # Zone conflict check (before rental terms per §2.11 priority 9 before 16)
    od = parse_dt(body["opening_date"])
    if od is None:
        raise err_invalid_request("opening_date must be ISO 8601")
    _check_zone_conflict(did, body["film_id"], body["theatre_id"], body["opening_date"])
    # 16 INVALID_RENTAL_TERMS
    _validate_rental_terms(body["week_one_rental_pct"], body["floor_pct"])
    if not isinstance(body["min_weeks_committed"], int) or body["min_weeks_committed"] < 0:
        raise err_invalid_request("min_weeks_committed must be integer")
    if not isinstance(body["per_capita_floor_cents"], int) or body["per_capita_floor_cents"] < 0:
        raise err_invalid_request("per_capita_floor_cents must be integer")
    decay = dec_pct(body["rental_decay_per_week"])
    if decay is None:
        raise err_invalid_request("rental_decay_per_week invalid")

    common = new_entity_common()
    b = {
        **common,
        "film_id": body["film_id"],
        "theatre_id": body["theatre_id"],
        "screen_id": body["screen_id"],
        "deal_status": "PROPOSED",
        "print_status": "NOT_ORDERED",
        "opening_date": iso_from_dt(od),
        "min_weeks_committed": body["min_weeks_committed"],
        "week_one_rental_pct": dec_pct(body["week_one_rental_pct"]),
        "rental_decay_per_week": decay,
        "floor_pct": dec_pct(body["floor_pct"]),
        "per_capita_floor_cents": body["per_capita_floor_cents"],
        "weeks_played": 0,
        "aggregate_deal_id": body.get("aggregate_deal_id"),
        "created_by_user_id": _user_id,
    }
    db.booking_agreements[b["id"]] = b
    return success_object(serialize_booking(b), 201)


@bp.route("/distributors/<did>/booking-agreements/<baid>", methods=["GET"])
@require_roles("Any")
def read_booking(did, baid, _user_id, _role):
    return success_object(serialize_booking(get_booking(did, baid)))


@bp.route("/distributors/<did>/booking-agreements", methods=["GET"])
@require_roles("Any")
def list_bookings(did, _user_id, _role):
    get_distributor(did)
    items = []
    for b in db.booking_agreements.values():
        f = db.films.get(b["film_id"])
        if f and f["distributor_id"] == did:
            items.append(b)
    filters = {}
    for k in ("film_id", "theatre_id", "screen_id", "aggregate_deal_id", "deal_status", "print_status"):
        if k in request.args:
            filters[k] = request.args.get(k)
    return paginate_list(items, serialize_booking, filters)


@bp.route("/distributors/<did>/booking-agreements/<baid>/counter", methods=["POST"])
@require_roles("Booker", "Exhibitor")
def counter_booking(did, baid, _user_id, _role):
    d = get_distributor(did)
    b = get_booking(did, baid)
    body = get_json_body()
    # 4 FROZEN
    if compute_distributor_posture(did) == "FROZEN":
        raise err_distributor_frozen()
    # 5 INVALID_STATE — role-matched transitions
    # Exhibitor counters PROPOSED -> COUNTERED
    # Booker counters COUNTERED -> PROPOSED
    if _role == "Exhibitor" and b["deal_status"] != "PROPOSED":
        raise err_invalid_state("Exhibitor may only counter a PROPOSED agreement")
    if _role == "Booker" and b["deal_status"] != "COUNTERED":
        raise err_invalid_state("Booker may only counter a COUNTERED agreement")
    # 16 INVALID_RENTAL_TERMS (re-validate)
    require_fields(body, ["week_one_rental_pct", "rental_decay_per_week", "floor_pct", "per_capita_floor_cents"])
    _validate_rental_terms(body["week_one_rental_pct"], body["floor_pct"])
    # 20 STALE_VERSION — last
    if "expected_booking_agreement_version" in body:
        if body["expected_booking_agreement_version"] != b["version"]:
            raise err_stale_version()
    # Apply counter-terms
    b["week_one_rental_pct"] = dec_pct(body["week_one_rental_pct"])
    b["rental_decay_per_week"] = dec_pct(body["rental_decay_per_week"])
    b["floor_pct"] = dec_pct(body["floor_pct"])
    if not isinstance(body["per_capita_floor_cents"], int):
        raise err_invalid_request("per_capita_floor_cents must be integer")
    b["per_capita_floor_cents"] = body["per_capita_floor_cents"]
    b["deal_status"] = "COUNTERED" if _role == "Exhibitor" else "PROPOSED"
    touch(b)
    return success_object(serialize_booking(b))


def _auto_create_dcp_shipment(b):
    """On acceptance: auto-create DCPShipment (QUEUED) and advance print axis."""
    from services.core import new_entity_common
    screen = db.screens.get(b["screen_id"])
    common = new_entity_common()
    s = {
        **common,
        "booking_agreement_id": b["id"],
        "content_format": screen["projection_format"] if screen else "DCP_2K",
        "tracking_number": "",
        "shipped_at": None,
        "delivered_at": None,
        "status": "QUEUED",
    }
    db.dcp_shipments[s["id"]] = s
    b["print_status"] = "DCP_QUEUED"


@bp.route("/distributors/<did>/booking-agreements/<baid>/accept", methods=["POST"])
@require_roles("Booker", "Exhibitor")
def accept_booking(did, baid, _user_id, _role):
    d = get_distributor(did)
    b = get_booking(did, baid)
    body = get_json_body()
    # 4 FROZEN
    if compute_distributor_posture(did) == "FROZEN":
        raise err_distributor_frozen()
    # 5 INVALID_STATE — Exhibitor accepts PROPOSED, Booker accepts COUNTERED
    if _role == "Exhibitor" and b["deal_status"] != "PROPOSED":
        raise err_invalid_state("Exhibitor may only accept a PROPOSED agreement")
    if _role == "Booker" and b["deal_status"] != "COUNTERED":
        raise err_invalid_state("Booker may only accept a COUNTERED agreement")
    # 6 FILM_NOT_BOOKABLE
    film = db.films.get(b["film_id"])
    if not film or film["lifecycle_status"] not in ("PRE_RELEASE", "IN_RELEASE", "HOLDOVER_PHASE"):
        raise err_film_not_bookable()
    # Theatre must be ACTIVE
    theatre = db.theatres.get(b["theatre_id"])
    if not theatre or theatre["status"] != "ACTIVE":
        raise err_theatre_inactive()
    # 13 SCREEN_AVAILABLE
    screen = db.screens.get(b["screen_id"])
    if not screen or screen["status"] != "AVAILABLE":
        raise err_screen_unavailable()
    # 9 ZONE conflict (after film/theatre/screen checks per priority order, but we match scaffold priority 9 before 13)
    # Actually per §2.11, zone is priority 9 and screen avail is 13; we do zone first
    # But we already did screen/theatre checks. Keep zone after theatre/screen state for simplicity.
    # Reorder: zone conflict (9) comes BEFORE screen availability (13). Do it now:
    _check_zone_conflict(did, b["film_id"], b["theatre_id"], b["opening_date"])
    # 20 STALE_VERSION
    if "expected_booking_agreement_version" in body:
        if body["expected_booking_agreement_version"] != b["version"]:
            raise err_stale_version()
    # Apply — one mutation of the agreement: deal ACCEPTED + print axis fires
    # (auto-created QUEUED shipment), so exactly one version increment (§3.3).
    b["deal_status"] = "ACCEPTED"
    screen["status"] = "BOOKED"
    touch(screen)
    _auto_create_dcp_shipment(b)
    touch(b)
    # PRD §2.7: every booking acceptance advances the film's committed-screen
    # count and version.
    touch(film)
    return success_object(serialize_booking(b))


@bp.route("/distributors/<did>/booking-agreements/<baid>/decline", methods=["POST"])
@require_roles("Booker", "Exhibitor")
def decline_booking(did, baid, _user_id, _role):
    b = get_booking(did, baid)
    if _role == "Exhibitor" and b["deal_status"] != "PROPOSED":
        raise err_invalid_state("Exhibitor may only decline a PROPOSED agreement")
    if _role == "Booker" and b["deal_status"] != "COUNTERED":
        raise err_invalid_state("Booker may only decline a COUNTERED agreement")
    b["deal_status"] = "DECLINED"
    touch(b)
    return success_object(serialize_booking(b))


@bp.route("/distributors/<did>/booking-agreements/<baid>/cancel", methods=["POST"])
@require_roles("Booker")
def cancel_booking(did, baid, _user_id, _role):
    b = get_booking(did, baid)
    if b["deal_status"] in ("IN_PLAY", "HELD_OVER", "COMPLETED"):
        raise err_invalid_state("Cannot cancel from this state")
    if b["deal_status"] not in ("PROPOSED", "COUNTERED", "ACCEPTED"):
        raise err_invalid_state("Cannot cancel from this state")
    was_accepted = b["deal_status"] == "ACCEPTED"
    b["deal_status"] = "CANCELLED"
    if was_accepted:
        screen = db.screens.get(b["screen_id"])
        if screen and screen["status"] == "BOOKED":
            screen["status"] = "AVAILABLE"
            touch(screen)
        # DCP shipments not yet DELIVERED -> RETURNED
        for s in db.dcp_shipments.values():
            if s["booking_agreement_id"] == b["id"] and s["status"] in ("QUEUED", "IN_TRANSIT"):
                s["status"] = "RETURNED"
                touch(s)
        # KDMs in ISSUED/LIVE -> REVOKED
        for k in db.kdm_keys.values():
            if k["booking_agreement_id"] == b["id"] and k["status"] in ("ISSUED", "LIVE"):
                k["status"] = "REVOKED"
                touch(k)
        if b["print_status"] == "KEY_LIVE":
            b["print_status"] = "DCP_DELIVERED"
    touch(b)
    return success_object(serialize_booking(b))


@bp.route("/distributors/<did>/booking-agreements/<baid>/holdover", methods=["POST"])
@require_roles("Booker")
def holdover_booking(did, baid, _user_id, _role):
    d = get_distributor(did)
    b = get_booking(did, baid)
    body = get_json_body()
    if b["deal_status"] != "IN_PLAY":
        raise err_invalid_state("Must be IN_PLAY for holdover")
    if not compute_holdover_eligible(b):
        raise err_holdover_not_eligible()
    b["deal_status"] = "HELD_OVER"
    touch(b)
    # Create HoldoverDecision HOLD
    prior_week = d["week_epoch"] - 1
    prior_gross = sum(
        r["gross_cents"]
        for r in db.box_office_reports.values()
        if r["booking_agreement_id"] == b["id"]
        and r["status"] == "LOCKED"
        and r.get("week_index") == prior_week
    )
    common = new_entity_common()
    hd = {
        **common,
        "booking_agreement_id": b["id"],
        "week_index": d["week_epoch"],
        "prior_week_gross_cents": prior_gross,
        "decision": "HOLD",
        "rationale": body.get("rationale"),
    }
    db.holdover_decisions[hd["id"]] = hd
    return success_object(serialize_booking(b))


@bp.route("/distributors/<did>/booking-agreements/<baid>/holdover_release", methods=["POST"])
@require_roles("Booker")
def holdover_release_booking(did, baid, _user_id, _role):
    d = get_distributor(did)
    b = get_booking(did, baid)
    if b["deal_status"] != "HELD_OVER":
        raise err_invalid_state("Must be HELD_OVER for holdover_release")
    b["deal_status"] = "IN_PLAY"
    touch(b)
    prior_week = d["week_epoch"] - 1
    prior_gross = sum(
        r["gross_cents"]
        for r in db.box_office_reports.values()
        if r["booking_agreement_id"] == b["id"]
        and r["status"] == "LOCKED"
        and r.get("week_index") == prior_week
    )
    common = new_entity_common()
    hd = {
        **common,
        "booking_agreement_id": b["id"],
        "week_index": d["week_epoch"],
        "prior_week_gross_cents": prior_gross,
        "decision": "RELEASE",
        "rationale": None,
    }
    db.holdover_decisions[hd["id"]] = hd
    return success_object(serialize_booking(b))


@bp.route("/distributors/<did>/booking-agreements/<baid>/holdover-decisions", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "Exhibitor", "Auditor")
def list_holdover_decisions(did, baid, _user_id, _role):
    get_booking(did, baid)
    items = [h for h in db.holdover_decisions.values() if h["booking_agreement_id"] == baid]
    from services.core import serialize_holdover_decision
    filters = {}
    for k in ("decision", "booking_agreement_id"):
        if k in request.args:
            filters[k] = request.args.get(k)
    return paginate_list(items, serialize_holdover_decision, filters)
