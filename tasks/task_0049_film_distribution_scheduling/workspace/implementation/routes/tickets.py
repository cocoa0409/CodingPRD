"""Ticket endpoints: purchase, refund, exchange."""

from datetime import timedelta

from flask import Blueprint

from db import db, new_id
from clock import now_iso, now_dt
from middleware import (
    require_roles,
    get_auth,
    parse_json_body,
    require_fields,
    require_int,
    require_str,
)
from response import success_object
from errors import (
    ERR_NOT_FOUND,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_FILM_NOT_RELEASED,
    ERR_SHOWTIME_NOT_ON_SALE,
    ERR_PRESALE_ANOMALY_DETECTED,
    ERR_PRESALE_NOT_OPEN,
    ERR_SEAT_CAPACITY_EXCEEDED,
    ERR_PER_BUYER_LIMIT_EXCEEDED,
    ERR_TICKET_NOT_REFUNDABLE,
    ERR_EXCHANGE_TARGET_INVALID,
    ERR_BAD_REQUEST,
    raise_error,
)
from datetime_utils import parse_iso8601
from services.audit import append_audit
from services.calculations import (
    ROLLING_WINDOW_THRESHOLD,
    CUMULATIVE_THRESHOLD,
    WINDOW_MINUTES,
    PER_BUYER_HARD_CAP,
)
from services.cascade import append_reversal_for_individual_ticket
from services.showtime_aggregates import recompute_showtime_aggregates
from services.sweep import lazy_sale_open
from services.version_check import check_version, check_idempotent_action

bp = Blueprint("tickets", __name__)


def _serialize(t):
    return dict(t)


def _count_buyer_valid_tickets(showtime_id, buyer_external_id):
    return sum(
        1 for t in db.tickets.values()
        if t["showtime_id"] == showtime_id
        and t["buyer_external_id"] == buyer_external_id
        and t["status"] == "VALID"
    )


def _count_buyer_valid_rolling(showtime_id, buyer_external_id):
    now = now_dt()
    cutoff = now - timedelta(minutes=WINDOW_MINUTES)
    count = 0
    for t in db.tickets.values():
        if t["showtime_id"] != showtime_id:
            continue
        if t["buyer_external_id"] != buyer_external_id:
            continue
        if t["status"] != "VALID":
            continue
        purchased_at = parse_iso8601(t["purchased_at"], "purchased_at")
        if cutoff <= purchased_at <= now:
            count += 1
    return count


@bp.route("/showtimes/<showtime_id>/tickets", methods=["POST"])
@require_roles({"TicketingPlatform"})
def purchase_ticket(showtime_id):
    role, user_id = get_auth()
    # Path existence
    showtime = db.showtimes.get(showtime_id)
    if not showtime:
        raise_error(ERR_NOT_FOUND, "showtime not found")
    body = parse_json_body()
    require_fields(body, ["buyer_external_id", "paid_amount_cents"])
    buyer_external_id = require_str(body.get("buyer_external_id"), "buyer_external_id")
    paid_amount_cents = require_int(body.get("paid_amount_cents"), "paid_amount_cents", min_v=0)
    promo_code = body.get("promo_code")
    if promo_code is not None and not isinstance(promo_code, str):
        raise_error(ERR_BAD_REQUEST, "promo_code must be string")

    # Lazy presale open
    lazy_sale_open(showtime)

    # State checks
    film = db.films.get(showtime["film_id"])
    if film and film.get("status") != "RELEASED":
        # ERR_FILM_NOT_RELEASED (priority 6) — only relevant when sale would otherwise open
        # Special: if sale_status is PRESALE and presale_opens_at has not yet been reached,
        # return ERR_PRESALE_NOT_OPEN. But §3.5 says: "If the film is not yet RELEASED when
        # the clock crosses presale_opens_at, the transition is suppressed and any ticket
        # purchase attempt fails with ERR_FILM_NOT_RELEASED."
        # PRESALE before presale_opens_at -> ERR_PRESALE_NOT_OPEN; check that first.
        presale_opens = parse_iso8601(showtime["presale_opens_at"], "presale_opens_at")
        if now_dt() < presale_opens:
            raise_error(ERR_PRESALE_NOT_OPEN, "presale not open")
        # Otherwise the film is not released
        raise_error(ERR_FILM_NOT_RELEASED, "film not released")

    # presale_opens_at gating (for released film whose presale hasn't opened)
    presale_opens = parse_iso8601(showtime["presale_opens_at"], "presale_opens_at")
    if showtime["sale_status"] == "PRESALE" and now_dt() < presale_opens:
        raise_error(ERR_PRESALE_NOT_OPEN, "presale not open")

    # Sale status must be ON_SALE
    if showtime["sale_status"] != "ON_SALE":
        # CLOSED -> ERR_SHOWTIME_NOT_ON_SALE
        raise_error(ERR_SHOWTIME_NOT_ON_SALE, "showtime not on sale")

    # Priority 8: anomaly check (BEFORE per-buyer cap and seat capacity? Per priority order:
    # priority 8 is anomaly, priority 14 is seat capacity, priority 15 is per-buyer cap.
    # Spec also clarifies anomaly trumps per-buyer cap explicitly.
    rolling = _count_buyer_valid_rolling(showtime_id, buyer_external_id) + 1
    cumulative = _count_buyer_valid_tickets(showtime_id, buyer_external_id) + 1
    anomaly_triggered = False
    triggering_rule = None
    triggering_count = 0
    if rolling >= ROLLING_WINDOW_THRESHOLD:
        anomaly_triggered = True
        triggering_rule = "ROLLING_WINDOW"
        triggering_count = rolling
    elif cumulative >= CUMULATIVE_THRESHOLD:
        anomaly_triggered = True
        triggering_rule = "CUMULATIVE"
        triggering_count = cumulative

    if anomaly_triggered:
        # Set anomaly_flag and append AnomalyAlert; do not persist ticket
        showtime["anomaly_flag"] = True
        showtime["updated_at"] = now_iso()
        showtime["version"] = showtime.get("version", 1) + 1
        alert_id = new_id()
        alert = {
            "id": alert_id,
            "showtime_id": showtime_id,
            "buyer_external_id": buyer_external_id,
            "rule": triggering_rule,
            "triggering_count": triggering_count,
            "created_at": now_iso(),
        }
        db.anomaly_alerts[alert_id] = alert
        raise_error(ERR_PRESALE_ANOMALY_DETECTED, "presale anomaly detected")

    # Priority 14: seat capacity
    screen = db.screens.get(showtime["screen_id"])
    if not screen:
        raise_error(ERR_NOT_FOUND, "screen not found")
    valid_count = sum(1 for t in db.tickets.values() if t["showtime_id"] == showtime_id and t["status"] == "VALID")
    if valid_count + 1 > screen["seat_capacity"]:
        raise_error(ERR_SEAT_CAPACITY_EXCEEDED, "seat capacity exceeded")

    # Priority 15: per-buyer hard cap
    buyer_valid = _count_buyer_valid_tickets(showtime_id, buyer_external_id)
    if buyer_valid + 1 > PER_BUYER_HARD_CAP:
        raise_error(ERR_PER_BUYER_LIMIT_EXCEEDED, "per-buyer hard cap exceeded")

    # Create ticket
    now = now_iso()
    ticket = {
        "id": new_id(),
        "showtime_id": showtime_id,
        "buyer_external_id": buyer_external_id,
        "paid_amount_cents": paid_amount_cents,
        "promo_code": promo_code,
        "status": "VALID",
        "exchanged_to_showtime_id": None,
        "purchased_at": now,
        "refunded_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.tickets[ticket["id"]] = ticket

    # Recompute aggregates
    recompute_showtime_aggregates(showtime)
    showtime["updated_at"] = now_iso()
    showtime["version"] = showtime.get("version", 1) + 1

    return success_object(_serialize(ticket), http_status=201)


@bp.route("/tickets/<ticket_id>", methods=["GET"])
@require_roles({"PlatformAdmin", "TicketingPlatform", "CinemaOps", "FinanceOps", "Auditor"})
def get_ticket(ticket_id):
    t = db.tickets.get(ticket_id)
    if not t:
        raise_error(ERR_NOT_FOUND, "ticket not found")
    return success_object(_serialize(t))


@bp.route("/tickets/<ticket_id>/refund", methods=["POST"])
@require_roles({"TicketingPlatform", "CinemaOps"})
def refund_ticket(ticket_id):
    role, user_id = get_auth()
    ticket = db.tickets.get(ticket_id)
    if not ticket:
        raise_error(ERR_NOT_FOUND, "ticket not found")
    body = parse_json_body()
    requested_version = body.get("version")
    if requested_version is not None and (isinstance(requested_version, bool) or not isinstance(requested_version, int)):
        raise_error(ERR_BAD_REQUEST, "version must be integer")

    # State (priority 5): only VALID -> refundable, otherwise ERR_TICKET_NOT_REFUNDABLE
    if ticket["status"] in ("REFUNDED", "EXCHANGED"):
        check_idempotent_action(ticket["version"], requested_version, ticket["status"] == "REFUNDED")
        raise_error(ERR_TICKET_NOT_REFUNDABLE, "ticket not refundable")

    showtime = db.showtimes.get(ticket["showtime_id"])
    # PRD §3.8 explicitly contemplates a refund against a ticket whose
    # parent showtime is already COMPLETED and whose POSTING Settlement
    # is POSTED -- the result is a compensating REVERSAL row. Therefore
    # COMPLETED on its own is NOT past the refund grace window.

    check_version(ticket["version"], requested_version)

    # Apply
    ticket["status"] = "REFUNDED"
    ticket["refunded_at"] = now_iso()
    ticket["updated_at"] = now_iso()
    ticket["version"] = ticket["version"] + 1

    if showtime:
        recompute_showtime_aggregates(showtime)
        showtime["updated_at"] = now_iso()
        showtime["version"] = showtime.get("version", 1) + 1

    append_reversal_for_individual_ticket(ticket)

    append_audit(role, user_id, "TICKET_REFUND", "Ticket", ticket["id"], {"status": "REFUNDED"})
    return success_object(_serialize(ticket))


@bp.route("/tickets/<ticket_id>/exchange", methods=["POST"])
@require_roles({"TicketingPlatform", "CinemaOps"})
def exchange_ticket(ticket_id):
    role, user_id = get_auth()
    ticket = db.tickets.get(ticket_id)
    if not ticket:
        raise_error(ERR_NOT_FOUND, "ticket not found")
    body = parse_json_body()
    require_fields(body, ["exchanged_to_showtime_id"])
    exchanged_to_showtime_id = require_str(body.get("exchanged_to_showtime_id"), "exchanged_to_showtime_id")
    requested_version = body.get("version")
    if requested_version is not None and (isinstance(requested_version, bool) or not isinstance(requested_version, int)):
        raise_error(ERR_BAD_REQUEST, "version must be integer")

    if ticket["status"] in ("REFUNDED", "EXCHANGED"):
        check_idempotent_action(ticket["version"], requested_version, ticket["status"] == "EXCHANGED")
        raise_error(ERR_TICKET_NOT_REFUNDABLE, "ticket not refundable")

    # FK existence for destination
    dest = db.showtimes.get(exchanged_to_showtime_id)
    if not dest:
        raise_error(ERR_REFERENCED_ENTITY_NOT_FOUND, "destination showtime not found")

    src_showtime = db.showtimes.get(ticket["showtime_id"])
    if src_showtime and src_showtime["lifecycle_status"] == "COMPLETED":
        raise_error(ERR_TICKET_NOT_REFUNDABLE, "showtime already completed")

    # Exchange target compatibility (state + format/price)
    if dest["lifecycle_status"] != "SCHEDULED" or dest["sale_status"] not in ("PRESALE", "ON_SALE"):
        raise_error(ERR_EXCHANGE_TARGET_INVALID, "exchange target invalid state")
    # Format/price compatibility — same per-seat price as original ticket
    if dest["ticket_price_cents"] != ticket["paid_amount_cents"]:
        # paid_amount may differ from list price due to promo; spec says format/price compatible.
        # Use ticket_price_cents of the source showtime vs destination.
        src_price = src_showtime["ticket_price_cents"] if src_showtime else None
        if src_price is not None and src_price != dest["ticket_price_cents"]:
            raise_error(ERR_EXCHANGE_TARGET_INVALID, "exchange target price mismatch")
    # Format compatibility: source film format vs destination film format
    if src_showtime:
        src_film = db.films.get(src_showtime["film_id"])
        dest_film = db.films.get(dest["film_id"])
        if src_film and dest_film and src_film["format"] != dest_film["format"]:
            raise_error(ERR_EXCHANGE_TARGET_INVALID, "exchange target format mismatch")

    check_version(ticket["version"], requested_version)

    # Apply
    ticket["status"] = "EXCHANGED"
    ticket["exchanged_to_showtime_id"] = exchanged_to_showtime_id
    ticket["refunded_at"] = now_iso()
    ticket["updated_at"] = now_iso()
    ticket["version"] = ticket["version"] + 1

    # Create new child ticket on destination
    new_ticket_id = new_id()
    child = {
        "id": new_ticket_id,
        "showtime_id": exchanged_to_showtime_id,
        "buyer_external_id": ticket["buyer_external_id"],
        "paid_amount_cents": ticket["paid_amount_cents"],
        "promo_code": ticket.get("promo_code"),
        "status": "VALID",
        "exchanged_to_showtime_id": None,
        "purchased_at": now_iso(),
        "refunded_at": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.tickets[new_ticket_id] = child

    # Recompute aggregates for both showtimes
    if src_showtime:
        recompute_showtime_aggregates(src_showtime)
        src_showtime["updated_at"] = now_iso()
        src_showtime["version"] = src_showtime.get("version", 1) + 1
    recompute_showtime_aggregates(dest)
    dest["updated_at"] = now_iso()
    dest["version"] = dest.get("version", 1) + 1

    append_reversal_for_individual_ticket(ticket)

    append_audit(role, user_id, "TICKET_EXCHANGE", "Ticket", ticket["id"], {"status": "EXCHANGED", "to": exchanged_to_showtime_id})
    return success_object(_serialize(ticket))
