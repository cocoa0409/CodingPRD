"""Show endpoints (PRD §3.2, §3.5, §3.6)."""

from flask import Blueprint, request

from clock import now_iso_ms, parse_iso
from db import DB
from errors import (
    ERR_TOUR_NOT_FOUND,
    ERR_SHOW_NOT_FOUND,
    ERR_INVALID_SHOW_STATE,
    ERR_TOUR_NOT_ACTIVE,
    ERR_UNRESOLVED_SESSIONS,
    ERR_VENUE_DATE_CONFLICT,
    ERR_CLOSEOUT_INCOMPLETE,
    ERR_INSUFFICIENT_ALLOCATION,
    ERR_VALIDATION,
    err,
)
from middleware import (
    require_role,
    require_auth,
    get_json_body,
    require_string,
    require_int,
    require_enum,
    base_fields,
    touch,
    paginate,
    new_id,
)
from response import success_object, success_list
from services import core
from services.core import (
    validate_size_curve,
    validate_commission_config,
    calendar_date_of,
    royalty_snapshot_from_tour,
)
from services.serializers import show_view

bp = Blueprint("shows", __name__)


def get_show_or_404(show_id):
    s = DB.shows.get(show_id)
    if s is None:
        raise err(ERR_SHOW_NOT_FOUND, 404, "No Show with the given id")
    return s


@bp.post("/merch/shows")
def create_show():
    require_role("TourManager")
    body = get_json_body()
    tour_id = body.get("tour_id")

    # Existence of the body FK (priority 3) precedes remaining shape checks.
    if tour_id is None:
        raise err(ERR_VALIDATION, 400, "Missing required field: tour_id")
    if tour_id not in DB.tours:
        raise err(ERR_TOUR_NOT_FOUND, 404, "No Tour with the given id")

    city = require_string(body, "city", required=True)
    venue_name = require_string(body, "venue_name", required=True)
    show_date = require_string(body, "show_date", required=True)
    commission_mode = require_enum(body, "commission_mode", ("FLAT", "TIERED"), required=True)

    try:
        parsed_date = parse_iso(show_date)
    except (ValueError, TypeError):
        raise err(ERR_VALIDATION, 400, "show_date must be an ISO 8601 datetime")

    size_curve = body.get("size_curve")
    if size_curve is not None:
        size_curve = validate_size_curve(size_curve)

    flat_bps, tiers = validate_commission_config(body, commission_mode)

    # Venue calendar capacity: one non-CANCELLED show per venue per calendar date.
    for other in DB.shows.values():
        if other["status"] == "CANCELLED":
            continue
        if other["venue_name"] == venue_name and calendar_date_of(other) == parsed_date.date():
            raise err(ERR_VENUE_DATE_CONFLICT, 409,
                      "Another non-CANCELLED show occupies this venue on this date")

    show = {
        **base_fields(),
        "tour_id": tour_id,
        "city": city,
        "venue_name": venue_name,
        "show_date": show_date,
        "commission_mode": commission_mode,
        "flat_commission_bps": flat_bps,
        "commission_tiers": tiers,
        "size_curve": size_curve,
        "status": "SCHEDULED",
        "settlement_id": None,
        "closeout_credit_cents": None,
    }
    DB.shows[show["id"]] = show
    return success_object(show_view(show), status=201)


@bp.get("/merch/shows")
def list_shows():
    require_auth()
    tour_id = request.args.get("tour_id")
    settlement_id = request.args.get("settlement_id")
    items = list(DB.shows.values())
    if tour_id is not None:
        items = [s for s in items if s["tour_id"] == tour_id]
    if settlement_id is not None:
        items = [s for s in items if s.get("settlement_id") == settlement_id]
    items.sort(key=lambda s: s["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([show_view(s) for s in page], limit, offset, total)


@bp.get("/merch/shows/<show_id>")
def get_show(show_id):
    require_auth()
    return success_object(show_view(get_show_or_404(show_id)))


@bp.post("/merch/shows/<show_id>/open")
def open_show(show_id):
    require_role("TourManager")
    show = get_show_or_404(show_id)
    if show["status"] != "SCHEDULED":
        raise err(ERR_INVALID_SHOW_STATE, 409, "Only a SCHEDULED show can be opened")
    tour = DB.tours[show["tour_id"]]
    if tour["status"] != "ACTIVE":
        raise err(ERR_TOUR_NOT_ACTIVE, 409, "Opening a show requires an ACTIVE tour")
    show["status"] = "OPEN"
    touch(show)
    return success_object(show_view(show))


@bp.post("/merch/shows/<show_id>/begin-reconciliation")
def begin_reconciliation(show_id):
    require_role("TourManager")
    show = get_show_or_404(show_id)
    if show["status"] != "OPEN":
        raise err(ERR_INVALID_SHOW_STATE, 409, "Only an OPEN show can begin reconciliation")
    for s in core.sessions_of_show(show_id):
        if s["status"] not in ("COUNTED_OUT", "VERIFIED"):
            raise err(ERR_UNRESOLVED_SESSIONS, 409,
                      "Every session must be COUNTED_OUT or VERIFIED")

    prov_gross, prov_commission = core.compute_provisional_figures(show)
    tour = DB.tours[show["tour_id"]]
    settlement = {
        **base_fields(),
        "show_id": show_id,
        "status": "PROVISIONAL",
        "provisional_gross_cents": prov_gross,
        "venue_commission_provisional_cents": prov_commission,
        "final_gross_cents": None,
        "venue_commission_final_cents": None,
        "net_to_tour_cents": None,
        "artist_royalty_cents": None,
        "licensing_cents": None,
        "company_share_cents": None,
        **royalty_snapshot_from_tour(tour),
        "reconciled_by_user_id": None,
        "dispute_reason": None,
    }
    DB.settlements[settlement["id"]] = settlement
    show["settlement_id"] = settlement["id"]
    show["status"] = "RECONCILING"
    touch(show)
    return success_object(show_view(show))


@bp.post("/merch/shows/<show_id>/cancel")
def cancel_show(show_id):
    require_role("TourManager")
    show = get_show_or_404(show_id)
    if show["status"] != "SCHEDULED":
        raise err(ERR_INVALID_SHOW_STATE, 409,
                  "Only a SCHEDULED show can be cancelled (pre-doors only)")
    show["status"] = "CANCELLED"
    touch(show)
    return success_object(show_view(show))


@bp.post("/merch/shows/<show_id>/close-out")
def close_out_show(show_id):
    require_role("TourManager")
    show = get_show_or_404(show_id)
    body = get_json_body()

    # Body FK existence (priority 3) precedes the state gate.
    lines = body.get("lines")
    if not isinstance(lines, list):
        raise err(ERR_VALIDATION, 400, "lines must be a list")
    for line in lines:
        if not isinstance(line, dict):
            raise err(ERR_VALIDATION, 400, "Each close-out line must be an object")
        alloc_id = line.get("allocation_id")
        if alloc_id is None or alloc_id not in DB.allocations:
            from errors import ERR_ALLOCATION_NOT_FOUND
            raise err(ERR_ALLOCATION_NOT_FOUND, 404, "No Allocation with the given id")

    if show["status"] != "SETTLED":
        raise err(ERR_INVALID_SHOW_STATE, 409, "Close-out requires a SETTLED show")

    # Every allocation with quantity_on_hand > 0 must appear exactly once.
    show_allocs = [a for a in DB.allocations.values() if a["show_id"] == show_id]
    with_on_hand = {a["id"]: a for a in show_allocs if core.allocation_on_hand(a) > 0}

    seen = set()
    parsed_lines = []
    for line in lines:
        alloc = DB.allocations[line["allocation_id"]]
        action = line.get("action")
        qty = line.get("quantity")
        if alloc["show_id"] != show_id:
            raise err(ERR_VALIDATION, 400, "Close-out line allocation does not belong to this show")
        if action not in ("RETURN", "LIQUIDATE"):
            raise err(ERR_VALIDATION, 400, "action must be RETURN or LIQUIDATE")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 0:
            raise err(ERR_VALIDATION, 400, "quantity must be a non-negative integer")
        parsed_lines.append((alloc, action, qty))
        seen.add(alloc["id"])

    missing = [aid for aid in with_on_hand if aid not in seen]
    if missing:
        raise err(ERR_CLOSEOUT_INCOMPLETE, 409,
                  "Every allocation with quantity_on_hand > 0 must appear in lines")

    actual_proceeds = require_int(body, "actual_proceeds_cents", ge=0, required=True)
    handling_fee = require_int(body, "handling_fee_cents", ge=0, required=True)
    if handling_fee > actual_proceeds:
        raise err(ERR_VALIDATION, 400, "handling_fee_cents may not exceed actual_proceeds_cents")

    # Aggregate per-allocation return/liquidate and check sufficiency.
    per_alloc = {}
    for alloc, action, qty in parsed_lines:
        agg = per_alloc.setdefault(alloc["id"], {"alloc": alloc, "RETURN": 0, "LIQUIDATE": 0})
        agg[action] += qty
    for aid, agg in per_alloc.items():
        alloc = agg["alloc"]
        on_hand = core.allocation_on_hand(alloc)
        if agg["RETURN"] + agg["LIQUIDATE"] > on_hand:
            raise err(ERR_INSUFFICIENT_ALLOCATION, 409,
                      "RETURN + LIQUIDATE exceeds quantity_on_hand")

    # Apply.
    for aid, agg in per_alloc.items():
        alloc = agg["alloc"]
        on_hand = core.allocation_on_hand(alloc)
        alloc["quantity_returned"] = agg["RETURN"]
        alloc["quantity_liquidated"] = agg["LIQUIDATE"]
        alloc["quantity_shrunk"] = on_hand - agg["RETURN"] - agg["LIQUIDATE"]
        touch(alloc)

    show["closeout_credit_cents"] = actual_proceeds - handling_fee
    show["status"] = "CLOSED"
    touch(show)

    # Auto-close the tour when this was its last non-terminal show.
    tour = DB.tours[show["tour_id"]]
    if tour["status"] == "ACTIVE":
        remaining = [
            s for s in DB.shows.values()
            if s["tour_id"] == tour["id"] and s["status"] not in ("CLOSED", "CANCELLED")
        ]
        if not remaining:
            tour["status"] = "CLOSED"
            touch(tour)

    return success_object(show_view(show))
