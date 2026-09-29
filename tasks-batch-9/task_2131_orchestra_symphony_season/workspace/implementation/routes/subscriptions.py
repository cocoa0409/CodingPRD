"""Subscription packages: building, paying and the renewal chain."""

from flask import Blueprint, request

from calc import loyalty_discount_bp, round_half_up, subscription_price
from db import db, now
from domain import (available_seats, base_fields, force_bump,
                    recompute_fulfilled, recompute_patron_score,
                    refresh_concerts, serialize, touch)
from errors import raise_err
from middleware import endpoint, own
from response import ok, ok_list
from validate import (body, check_body_fks, opt_int, paginate, present,
                      req_int, req_list, req_str)

bp = Blueprint("subscriptions", __name__)


def get_package_or_404(subscription_id):
    package = db.packages.get(subscription_id)
    if package is None:
        raise_err("ERR_SUBSCRIPTION_NOT_FOUND")
    return package


def _check_membership(concert_ids, season_id):
    """Rung 19 -- package membership."""
    if not isinstance(concert_ids, list) or len(concert_ids) == 0:
        raise_err("ERR_PACKAGE_CONCERT_MISMATCH")
    if len(set(concert_ids)) != len(concert_ids):
        raise_err("ERR_PACKAGE_CONCERT_MISMATCH")
    for concert_id in concert_ids:
        concert = db.concerts.get(concert_id)
        if concert is None:
            raise_err("ERR_PACKAGE_CONCERT_MISMATCH")
        if concert["season_id"] != season_id:
            raise_err("ERR_PACKAGE_CONCERT_MISMATCH")
        if concert["programming_status"] not in ("PROGRAMMED", "LOCKED"):
            raise_err("ERR_PACKAGE_CONCERT_MISMATCH")


def _check_seat_availability(concert_ids, seat_section_id, seat_count):
    """Rung 22 -- seat availability on every affected concert."""
    for concert_id in concert_ids:
        concert = db.concerts.get(concert_id)
        if concert is None or available_seats(concert, seat_section_id) < seat_count:
            raise_err("ERR_INSUFFICIENT_SEATS")


def _ordered_concert_ids(concert_ids):
    """Ascending performance_start_utc, ties broken by ascending created_at."""
    concerts = [db.concerts[cid] for cid in concert_ids if cid in db.concerts]
    concerts.sort(key=lambda c: (c["_perf_start_dt"], c["created_at"], c["_seq"]))
    return [c["id"] for c in concerts]


@bp.route("/orchestra/subscriptions", methods=["POST"])
@endpoint(["BoxOfficeAgent", "Patron"])
def create_subscription():
    data = body()
    check_body_fks(data, ["season_id", "seat_section_id", "patron_id", "concert_ids"])

    if present(data, "patron_id"):                            # rung 5
        own(data["patron_id"], "Patron")

    patron_id = req_str(data, "patron_id")                    # rung 6
    season_id = req_str(data, "season_id")
    seat_section_id = req_str(data, "seat_section_id")
    seat_count = req_int(data, "seat_count", minv=1)
    concert_ids = req_list(data, "concert_ids")

    patron = db.patrons[patron_id]
    season = db.seasons[season_id]
    section = db.sections[seat_section_id]

    if season["status"] not in ("RENEWAL_WINDOW", "SINGLE_ON_SALE"):   # rung 8
        raise_err("ERR_INVALID_SEASON_TRANSITION")

    if section["donor_priority_rank"] <= 2 and patron["donor_level"] not in (
            "BENEFACTOR", "LAUREATE"):                        # rung 17
        raise_err("ERR_DONOR_BENEFIT_REQUIRED")

    _check_membership(concert_ids, season_id)                 # rung 19

    for concert_id in concert_ids:                            # rung 20
        concert = db.concerts[concert_id]
        if concert["venue_id"] != section["venue_id"]:
            raise_err("ERR_SEAT_SECTION_VENUE_MISMATCH")

    _check_seat_availability(concert_ids, seat_section_id, seat_count)   # rung 22

    locked_unit = round_half_up(
        season["base_ticket_price_cents"] * section["price_multiplier_bp"], 10000)
    price = subscription_price(locked_unit, seat_count, len(concert_ids))

    package = base_fields()
    package.update({
        "patron_id": patron_id,
        "season_id": season_id,
        "seat_section_id": seat_section_id,
        "prior_package_id": None,
        "seat_count": seat_count,
        "concert_ids": list(concert_ids),
        "package_type": "NEW",
        "status": "PENDING_PAYMENT",
        "locked_unit_price_cents": locked_unit,
        "price_cents": price,
        "fulfilled_concert_count": 0,
    })
    recompute_fulfilled(package)
    db.packages[package["id"]] = package

    refresh_concerts(concert_ids)
    return ok(serialize(package), 201)


@bp.route("/orchestra/subscriptions/<subscription_id>", methods=["GET"])
@endpoint(["ArtisticAdmin", "BoxOfficeAgent", "Patron"])
def read_subscription(subscription_id):
    return ok(serialize(get_package_or_404(subscription_id)))


@bp.route("/orchestra/subscriptions", methods=["GET"])
@endpoint(["ArtisticAdmin", "BoxOfficeAgent", "Patron"])
def list_subscriptions():
    filters = {
        "patron_id": request.args.get("patron_id"),
        "season_id": request.args.get("season_id"),
        "seat_section_id": request.args.get("seat_section_id"),
        "prior_package_id": request.args.get("prior_package_id"),
        "status": request.args.get("status"),
    }
    records = []
    for package in db.packages.values():
        if any(value is not None and package[key] != value
               for key, value in filters.items()):
            continue
        records.append(package)
    items, limit, offset, total = paginate(records, serialize)
    return ok_list(items, limit, offset, total)


@bp.route("/orchestra/subscriptions/<subscription_id>/pay", methods=["POST"])
@endpoint(["BoxOfficeAgent", "Patron"])
def pay_subscription(subscription_id):
    package = get_package_or_404(subscription_id)             # rung 3
    own(package["patron_id"], "Patron")                       # rung 5
    if package["status"] != "PENDING_PAYMENT":                # rung 7
        raise_err("ERR_SUBSCRIPTION_NOT_PENDING")

    with touch(package):
        package["status"] = "ACTIVE"

    refresh_concerts(package["concert_ids"])

    patron = db.patrons.get(package["patron_id"])
    if patron is not None:
        with touch(patron):
            patron["lifetime_cash_in_cents"] += package["price_cents"]
            if package["package_type"] == "NEW":
                patron["consecutive_renewal_years"] = 1
            else:
                patron["consecutive_renewal_years"] += 1
            recompute_patron_score(patron)

    return ok(serialize(package))


@bp.route("/orchestra/subscriptions/<subscription_id>/renew", methods=["POST"])
@endpoint(["BoxOfficeAgent", "Patron"])
def renew_subscription(subscription_id):
    prior = get_package_or_404(subscription_id)               # rung 3
    data = body()
    check_body_fks(data, ["season_id", "concert_ids"])        # rung 4
    own(prior["patron_id"], "Patron")                         # rung 5

    season_id = req_str(data, "season_id")                    # rung 6
    concert_ids = req_list(data, "concert_ids")
    expected_version = req_int(data, "expected_package_version")
    seat_count = opt_int(data, "seat_count", prior["seat_count"], minv=1)

    if prior["status"] != "ACTIVE":                           # rung 7
        raise_err("ERR_SUBSCRIPTION_NOT_ACTIVE")

    target_season = db.seasons[season_id]
    if target_season["status"] != "RENEWAL_WINDOW":           # rung 8
        raise_err("ERR_RENEWAL_WINDOW_CLOSED")

    if expected_version != prior["version"]:                  # rung 9
        raise_err("ERR_STALE_PACKAGE_VERSION")

    # rung 18 -- the priority score is freshly recomputed and persisted here
    patron = db.patrons.get(prior["patron_id"])
    section = db.sections.get(prior["seat_section_id"])
    if patron is not None:
        with touch(patron):
            recompute_patron_score(patron)
    score = patron["renewal_priority_score"] if patron is not None else 0
    threshold = section["min_renewal_priority_score"] if section is not None else 0
    if score < threshold:
        raise_err("ERR_RENEWAL_PRIORITY_INSUFFICIENT")

    _check_membership(concert_ids, season_id)                 # rung 19

    if now() > target_season["_renewal_deadline_dt"]:         # rung 21
        raise_err("ERR_RENEWAL_DEADLINE_PASSED")

    _check_seat_availability(concert_ids, prior["seat_section_id"], seat_count)  # rung 22

    locked_unit = prior["locked_unit_price_cents"]
    loyalty_bp = loyalty_discount_bp(target_season["loyalty_discount_bp"],
                                     patron["consecutive_renewal_years"] if patron else 0)
    price = subscription_price(locked_unit, seat_count, len(concert_ids), loyalty_bp)

    package = base_fields()
    package.update({
        "patron_id": prior["patron_id"],
        "season_id": season_id,
        "seat_section_id": prior["seat_section_id"],
        "prior_package_id": prior["id"],
        "seat_count": seat_count,
        "concert_ids": list(concert_ids),
        "package_type": "RENEWAL",
        "status": "PENDING_PAYMENT",
        "locked_unit_price_cents": locked_unit,
        "price_cents": price,
        "fulfilled_concert_count": 0,
    })
    recompute_fulfilled(package)
    db.packages[package["id"]] = package

    refresh_concerts(concert_ids)
    force_bump(prior)

    return ok(serialize(package), 201)
