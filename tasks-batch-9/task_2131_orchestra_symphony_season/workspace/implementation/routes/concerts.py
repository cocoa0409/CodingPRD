"""Concerts: creation, the three status dimensions, cancellation, substitution,
settlement and the read-only price quote."""

from flask import Blueprint, request

from calc import single_ticket_price
from db import db
from domain import (base_fields, contracts_of_concert, created_key,
                    engagements_of_service, inventory_element,
                    recompute_fulfilled, recompute_inventory,
                    recompute_readiness, season_of_concert, serialize,
                    service_schedule_key, services_of_concert, touch,
                    unlock_programming)
from errors import raise_err
from middleware import endpoint
from response import ok, ok_list
from validate import (body, check_body_fks, paginate, req_dt,
                      req_int, req_str)

bp = Blueprint("concerts", __name__)


def get_concert_or_404(concert_id):
    concert = db.concerts.get(concert_id)
    if concert is None:
        raise_err("ERR_CONCERT_NOT_FOUND")
    return concert


def _snapshot_inventory(venue_id):
    sections = [s for s in db.sections.values() if s["venue_id"] == venue_id]
    sections.sort(key=created_key)
    inventory = []
    for section in sections:
        inventory.append({
            "seat_section_id": section["id"],
            "capacity": section["capacity"],
            "held_count": 0,
            "sold_count": 0,
            "available_count": section["capacity"],
            "fill_bp": 0,
            "demand_band": "LOW",
        })
    return inventory


@bp.route("/orchestra/concerts", methods=["POST"])
@endpoint(["ArtisticAdmin"])
def create_concert():
    data = body()
    check_body_fks(data, ["season_id", "venue_id"])          # rung 4
    season = db.seasons.get(data.get("season_id"))
    if season is None:
        req_str(data, "season_id")
        raise_err("ERR_SEASON_NOT_FOUND")
    venue = db.venues.get(data.get("venue_id"))
    if venue is None:
        req_str(data, "venue_id")
        raise_err("ERR_VENUE_NOT_FOUND")

    title = req_str(data, "title")
    start = req_dt(data, "performance_start_utc")
    end = req_dt(data, "performance_end_utc")
    program_minutes = req_int(data, "program_minutes", minv=1)

    concert = base_fields()
    concert.update({
        "season_id": season["id"],
        "venue_id": venue["id"],
        "title": title,
        "performance_start_utc": data["performance_start_utc"],
        "performance_end_utc": data["performance_end_utc"],
        "program_minutes": program_minutes,
        "programming_status": "DRAFT",
        "sale_status": "UNANNOUNCED",
        "performance_status": "SCHEDULED",
        "readiness_posture": "READY",
        "section_inventory": _snapshot_inventory(venue["id"]),
        "seats_held_count": 0,
        "seats_sold_count": 0,
        "substitution_count": 0,
        "gross_ticket_revenue_cents": 0,
        "_perf_start_dt": start,
        "_perf_end_dt": end,
    })
    db.concerts[concert["id"]] = concert
    return ok(serialize(concert), 201)


@bp.route("/orchestra/concerts/<concert_id>", methods=["GET"])
@endpoint(["ArtisticAdmin", "OrchestraManager", "BoxOfficeAgent", "Patron"])
def read_concert(concert_id):
    return ok(serialize(get_concert_or_404(concert_id)))


@bp.route("/orchestra/concerts", methods=["GET"])
@endpoint(["ArtisticAdmin", "OrchestraManager", "BoxOfficeAgent", "Patron"])
def list_concerts():
    season_id = request.args.get("season_id")
    venue_id = request.args.get("venue_id")
    sale_status = request.args.get("sale_status")
    records = []
    for concert in db.concerts.values():
        if season_id is not None and concert["season_id"] != season_id:
            continue
        if venue_id is not None and concert["venue_id"] != venue_id:
            continue
        if sale_status is not None and concert["sale_status"] != sale_status:
            continue
        records.append(concert)
    items, limit, offset, total = paginate(records, serialize)
    return ok_list(items, limit, offset, total)


@bp.route("/orchestra/concerts/<concert_id>/program", methods=["POST"])
@endpoint(["ArtisticAdmin"])
def program_concert(concert_id):
    concert = get_concert_or_404(concert_id)
    if concert["programming_status"] != "DRAFT":           # rung 7
        raise_err("ERR_CONCERT_NOT_DRAFT")
    season = season_of_concert(concert)
    if season is None or season["status"] != "PLANNING":   # rung 8
        raise_err("ERR_INVALID_SEASON_TRANSITION")

    with touch(concert):
        concert["programming_status"] = "PROGRAMMED"
        recompute_readiness(concert)
    with touch(season):
        season["concerts_programmed_count"] += 1
    return ok(serialize(concert))


@bp.route("/orchestra/concerts/<concert_id>/cancel", methods=["POST"])
@endpoint(["ArtisticAdmin"])
def cancel_concert(concert_id):
    concert = get_concert_or_404(concert_id)
    data = body()
    req_str(data, "reason")                                # rung 6
    if concert["performance_status"] != "SCHEDULED":       # rung 7
        raise_err("ERR_CONCERT_ALREADY_CANCELLED")
    season = season_of_concert(concert)
    if season is not None and season["status"] == "CLOSED":  # rung 8
        raise_err("ERR_INVALID_SEASON_TRANSITION")

    with touch(concert):
        concert["performance_status"] = "CANCELLED"
        concert["sale_status"] = "SALES_CLOSED"
    if season is not None:
        with touch(season):
            season["concerts_cancelled_count"] += 1

    _cascade_personnel(concert)
    _cascade_box_office(concert)

    # open guest contracts are withdrawn; signed ones are left alone
    for contract in sorted(contracts_of_concert(concert["id"]), key=created_key):
        if contract["status"] in ("OFFERED", "COUNTERED"):
            with touch(contract):
                contract["status"] = "WITHDRAWN"

    # affected packages recompute their fulfilment roll-up (price is untouched)
    for package in sorted(db.packages.values(), key=created_key):
        if concert["id"] in package["concert_ids"]:
            with touch(package):
                recompute_fulfilled(package)

    # programming_status and readiness_posture are deliberately left as they were
    return ok(serialize(concert))


def _cascade_personnel(concert):
    services = [s for s in services_of_concert(concert["id"])
                if s["status"] in ("DRAFT", "PUBLISHED")]
    for service in sorted(services, key=service_schedule_key):
        with touch(service):
            service["status"] = "CANCELLED"
        for engagement in sorted(engagements_of_service(service["id"]), key=created_key):
            if engagement["status"] != "CONFIRMED":
                continue
            with touch(engagement):
                engagement["status"] = "VOIDED"
            if engagement["provisional_pay_cents"] is None:
                continue
            musician = db.musicians.get(engagement["musician_id"])
            if musician is None:
                continue
            with touch(musician):
                musician["services_charged_ytd"] -= 1
                musician["ytd_earnings_cents"] -= engagement["provisional_pay_cents"]


def _cascade_box_office(concert):
    orders = [o for o in db.orders.values() if o["concert_id"] == concert["id"]]
    for order in sorted(orders, key=created_key):
        if order["status"] == "HELD":
            with touch(order):
                order["status"] = "EXPIRED"
        elif order["status"] == "PAID":
            with touch(order):
                order["status"] = "REFUNDED"
            patron = db.patrons.get(order["patron_id"])
            if patron is not None:
                with touch(patron):
                    patron["credit_balance_cents"] += order["amount_paid_cents"]
    with touch(concert):
        recompute_inventory(concert)


@bp.route("/orchestra/concerts/<concert_id>/substitute", methods=["POST"])
@endpoint(["ArtisticAdmin"])
def substitute_artist(concert_id):
    concert = get_concert_or_404(concert_id)
    data = body()
    check_body_fks(data, ["contract_id"])                  # rung 4
    contract = db.contracts.get(data.get("contract_id"))
    if contract is None:
        req_str(data, "contract_id")
        raise_err("ERR_CONTRACT_NOT_FOUND")
    if contract["concert_id"] != concert["id"]:
        raise_err("ERR_CONTRACT_NOT_FOUND")

    replacement_name = req_str(data, "replacement_artist_name")   # rung 6
    replacement_fee = req_int(data, "replacement_fee_cents", minv=0)

    if contract["status"] not in ("OFFERED", "COUNTERED", "SIGNED"):  # rung 7
        raise_err("ERR_CONTRACT_NOT_NEGOTIABLE")

    with touch(contract):
        contract["status"] = "WITHDRAWN"

    replacement = base_fields()
    replacement.update({
        "concert_id": concert["id"],
        "artist_name": replacement_name,
        "role_type": contract["role_type"],
        "offered_fee_cents": replacement_fee,
        "countered_fee_cents": None,
        "agreed_fee_cents": None,
        "negotiation_round": 1,
        "status": "OFFERED",
    })
    db.contracts[replacement["id"]] = replacement

    with touch(concert):
        concert["substitution_count"] += 1
        unlock_programming(concert)
        recompute_readiness(concert)

    return ok(serialize(replacement), 201)


@bp.route("/orchestra/concerts/<concert_id>/settle", methods=["POST"])
@endpoint(["ArtisticAdmin"])
def settle_concert(concert_id):
    concert = get_concert_or_404(concert_id)
    if concert["performance_status"] != "SCHEDULED":
        raise_err("ERR_CONCERT_NOT_SETTLEABLE")
    season = season_of_concert(concert)
    if season is None or season["status"] != "IN_PROGRESS":
        raise_err("ERR_CONCERT_NOT_SETTLEABLE")
    for service in services_of_concert(concert["id"]):
        if service["status"] == "PUBLISHED":
            raise_err("ERR_CONCERT_NOT_SETTLEABLE")

    revenue = 0
    for order in db.orders.values():
        if order["concert_id"] == concert["id"] and order["status"] == "PAID":
            revenue += order["amount_paid_cents"]

    with touch(concert):
        concert["performance_status"] = "PERFORMED"
        concert["sale_status"] = "SALES_CLOSED"
        concert["gross_ticket_revenue_cents"] = revenue
    return ok(serialize(concert))


@bp.route("/orchestra/concerts/<concert_id>/price-quote", methods=["GET"])
@endpoint(["BoxOfficeAgent", "Patron"])
def price_quote(concert_id):
    concert = get_concert_or_404(concert_id)               # rung 3

    args = {k: v for k, v in request.args.items() if v != ""}
    # rung 4 -- body/query referential integrity in the canonical order
    if "seat_section_id" in args and args["seat_section_id"] not in db.sections:
        raise_err("ERR_SECTION_NOT_FOUND")
    if "patron_id" in args and args["patron_id"] not in db.patrons:
        raise_err("ERR_PATRON_NOT_FOUND")

    section_id = args.get("seat_section_id")
    if not section_id:
        raise_err("ERR_INVALID_REQUEST", "Field 'seat_section_id' is required.")
    section = db.sections[section_id]

    seat_count = 1
    if "seat_count" in args:
        try:
            seat_count = int(args["seat_count"])
        except (TypeError, ValueError):
            raise_err("ERR_INVALID_REQUEST", "Field 'seat_count' must be an integer.")
        if seat_count < 1:
            raise_err("ERR_INVALID_REQUEST", "Field 'seat_count' must be >= 1.")

    patron = db.patrons.get(args["patron_id"]) if "patron_id" in args else None
    donor_level = patron["donor_level"] if patron is not None else "NONE"

    season = season_of_concert(concert)
    element = inventory_element(concert, section_id)
    if element is None:
        held, sold, capacity = 0, 0, section["capacity"]
    else:
        held, sold, capacity = element["held_count"], element["sold_count"], element["capacity"]

    unit, band, fill_bp, donor_bp, amount_due = single_ticket_price(
        season["base_ticket_price_cents"], section["price_multiplier_bp"],
        held, sold, capacity, donor_level, seat_count)

    return ok({
        "unit_price_cents": unit,
        "demand_band": band,
        "fill_bp": fill_bp,
        "donor_discount_bp": donor_bp,
        "seat_count": seat_count,
        "amount_due_cents": amount_due,
    })
