"""Season lifecycle: creation, reads, advances and the ops-run checkpoint."""

from flask import Blueprint

from db import db, now
from domain import (agreement_for_season, base_fields, concerts_of_season,
                    created_key, recompute_patron_score, recompute_readiness,
                    refresh_concerts, serialize, touch)
from errors import raise_err
from middleware import endpoint
from response import ok
from validate import body, check_body_fks, req_dt, req_enum, req_int, req_str, opt_int

bp = Blueprint("seasons", __name__)

SEASON_STATUSES = ("PLANNING", "RENEWAL_WINDOW", "SINGLE_ON_SALE", "IN_PROGRESS", "CLOSED")
SUCCESSOR = {
    "PLANNING": "RENEWAL_WINDOW",
    "RENEWAL_WINDOW": "SINGLE_ON_SALE",
    "SINGLE_ON_SALE": "IN_PROGRESS",
    "IN_PROGRESS": "CLOSED",
}


def get_season_or_404(season_id):
    season = db.seasons.get(season_id)
    if season is None:
        raise_err("ERR_SEASON_NOT_FOUND")
    return season


@bp.route("/orchestra/seasons", methods=["POST"])
@endpoint(["ArtisticAdmin"])
def create_season():
    data = body()
    check_body_fks(data, [])
    name = req_str(data, "name")
    fiscal_year = req_int(data, "fiscal_year")
    deadline = req_dt(data, "renewal_deadline_utc")
    base_price = req_int(data, "base_ticket_price_cents", minv=1)
    loyalty = opt_int(data, "loyalty_discount_bp", 500, minv=0, maxv=2000)

    season = base_fields()
    season.update({
        "name": name,
        "fiscal_year": fiscal_year,
        "renewal_deadline_utc": data["renewal_deadline_utc"],
        "base_ticket_price_cents": base_price,
        "loyalty_discount_bp": loyalty,
        "status": "PLANNING",
        "ops_run_index": 0,
        "concerts_programmed_count": 0,
        "concerts_cancelled_count": 0,
        "program_book_revenue_cents": 0,
        "_renewal_deadline_dt": deadline,
    })
    db.seasons[season["id"]] = season
    return ok(serialize(season), 201)


@bp.route("/orchestra/seasons/<season_id>", methods=["GET"])
@endpoint(["ArtisticAdmin", "OrchestraManager", "BoxOfficeAgent", "AdvertisingSales"])
def read_season(season_id):
    return ok(serialize(get_season_or_404(season_id)))


@bp.route("/orchestra/seasons/<season_id>/advance", methods=["POST"])
@endpoint(["ArtisticAdmin"])
def advance_season(season_id):
    season = get_season_or_404(season_id)          # rung 3
    data = body()
    target = req_enum(data, "target_status", SEASON_STATUSES)   # rung 6

    # rung 8 -- cross-entity state gates
    current = season["status"]
    if SUCCESSOR.get(current) != target:
        raise_err("ERR_INVALID_SEASON_TRANSITION")

    if target == "RENEWAL_WINDOW":
        if agreement_for_season(season["id"]) is None:
            raise_err("ERR_UNION_AGREEMENT_MISSING")
        if season["concerts_programmed_count"] < 1:
            raise_err("ERR_NO_PROGRAMMED_CONCERTS")
        _advance_to_renewal_window(season)
    elif target == "SINGLE_ON_SALE":
        if now() < season["_renewal_deadline_dt"]:
            raise_err("ERR_INVALID_SEASON_TRANSITION")
        _advance_to_single_on_sale(season)
    elif target == "IN_PROGRESS":
        with touch(season):
            season["status"] = "IN_PROGRESS"
    else:  # CLOSED
        for concert in concerts_of_season(season["id"]):
            if concert["performance_status"] not in ("PERFORMED", "CANCELLED"):
                raise_err("ERR_INVALID_SEASON_TRANSITION")
        _advance_to_closed(season)

    return ok(serialize(season))


def _advance_to_renewal_window(season):
    with touch(season):
        season["status"] = "RENEWAL_WINDOW"
    concerts = concerts_of_season(season["id"])
    concerts.sort(key=lambda c: (c["_perf_start_dt"], c["created_at"], c["_seq"]))
    for concert in concerts:
        if (concert["programming_status"] in ("PROGRAMMED", "LOCKED")
                and concert["sale_status"] == "UNANNOUNCED"):
            with touch(concert):
                concert["sale_status"] = "RENEWAL_ONLY"


def _advance_to_single_on_sale(season):
    with touch(season):
        season["status"] = "SINGLE_ON_SALE"

    concerts = sorted(concerts_of_season(season["id"]), key=created_key)
    # hop 1a -- concerts open to the public
    for concert in concerts:
        if concert["sale_status"] == "RENEWAL_ONLY":
            with touch(concert):
                concert["sale_status"] = "PUBLIC_ONSALE"

    # hop 1b -- unpaid packages lapse, in ascending created_at order
    touched = set()
    packages = [p for p in db.packages.values()
                if p["season_id"] == season["id"] and p["status"] == "PENDING_PAYMENT"]
    for package in sorted(packages, key=created_key):
        with touch(package):
            package["status"] = "LAPSED"
        touched.update(package["concert_ids"])

    # hops 2 and 3 -- released seats, refreshed counters
    refresh_concerts(touched)

    # every concert of the season recomputes its readiness posture
    for concert in concerts:
        with touch(concert):
            recompute_readiness(concert)


def _advance_to_closed(season):
    with touch(season):
        season["status"] = "CLOSED"
    for concert in concerts_of_season(season["id"]):
        with touch(concert):
            concert["sale_status"] = "SALES_CLOSED"
    for package in db.packages.values():
        if package["season_id"] == season["id"] and package["status"] == "ACTIVE":
            with touch(package):
                package["status"] = "EXPIRED"


@bp.route("/orchestra/seasons/<season_id>/run-ops", methods=["POST"])
@endpoint(["ArtisticAdmin", "BoxOfficeAgent"])
def run_ops(season_id):
    season = get_season_or_404(season_id)
    if season["status"] == "CLOSED":
        raise_err("ERR_INVALID_SEASON_TRANSITION")

    with touch(season):
        season["ops_run_index"] += 1
    epoch = season["ops_run_index"]

    concert_ids = set(c["id"] for c in concerts_of_season(season["id"]))
    touched = set()

    # hop 1 -- stale holds expire, in ascending created_at order
    stale = [o for o in db.orders.values()
             if o["concert_id"] in concert_ids and o["status"] == "HELD"
             and o["hold_expires_at_ops_run"] <= epoch]
    for order in sorted(stale, key=created_key):
        with touch(order):
            order["status"] = "EXPIRED"
        touched.add(order["concert_id"])

    # unpaid packages past the renewal deadline lapse
    if now() > season["_renewal_deadline_dt"]:
        pending = [p for p in db.packages.values()
                   if p["season_id"] == season["id"] and p["status"] == "PENDING_PAYMENT"]
        for package in sorted(pending, key=created_key):
            with touch(package):
                package["status"] = "LAPSED"
            touched.update(package["concert_ids"])

    # hops 2 and 3
    refresh_concerts(touched)

    # every patron holding a package in this season refreshes their score
    patron_ids = set(p["patron_id"] for p in db.packages.values()
                     if p["season_id"] == season["id"])
    for patron_id in sorted(patron_ids):
        patron = db.patrons.get(patron_id)
        if patron is None:
            continue
        with touch(patron):
            recompute_patron_score(patron)

    return ok(serialize(season))
