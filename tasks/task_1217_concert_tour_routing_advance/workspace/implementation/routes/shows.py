"""Show endpoints (PRD 3.3-3.7): create/list/get, confirm, advance,
mark-performed, cancel, ticket feed, day sheet, plus flat fetch/search."""
from datetime import datetime, time as dtime, timezone

from flask import Blueprint, request

from db import store, clock, new_entity, touch
from errors import ApiError
from middleware import (
    authenticate, READ_ROLES, ROLE_TOUR_MANAGER, ROLE_PROMOTER, get_body,
    v_str, v_int, v_date, v_dt, parse_date, fmt_dt,
)
from response import success_object, list_response
from services import (
    SECTION_FIELDS, PROJECTION_SET, CANCELLABLE_SHOW_STATES,
    show_json, packet_json, resolve_tour, resolve_show,
    packet_for_show, compute_daysheet_issued, packet_sections_complete,
    on_sale_lead_satisfied, confirm_lead_satisfied, radius_conflicts,
    recompute_show_projection, recompute_tour_financials,
    recompute_tour_posture,
)

bp = Blueprint("shows", __name__)

TM_ONLY = frozenset({ROLE_TOUR_MANAGER})


@bp.post("/tours/<tourId>/shows")
def create_show(tourId):
    authenticate(TM_ONLY)
    t = resolve_tour(tourId)
    b = get_body()
    market_id = v_str(b, "market_id")
    venue_id = v_str(b, "venue_id")
    show_date = v_date(b, "show_date")
    on_sale_dt = v_dt(b, "on_sale_at")
    avg_ticket_price_cents = v_int(b, "avg_ticket_price_cents", minv=0)
    market = store["markets"].get(market_id)
    if market is None or market["tour_id"] != t["id"]:
        raise ApiError(
            "ERR_REFERENTIAL_INTEGRITY",
            422,
            "market_id does not resolve within the same tour",
        )
    venue = store["venues"].get(venue_id)
    if venue is None or venue["tour_id"] != t["id"]:
        raise ApiError(
            "ERR_REFERENTIAL_INTEGRITY",
            422,
            "venue_id does not resolve within the same tour",
        )
    # Venue availability at create (PRD 3.3): date inside the tour window and
    # listed in available_dates. The booked_dates exclusion is a confirm-time
    # gate only (PRD 3.4).
    in_window = (
        parse_date(t["window_start_date"]) <= show_date <= parse_date(t["window_end_date"])
    )
    if (
        not in_window
        or show_date.isoformat() not in venue["available_dates"]
    ):
        raise ApiError(
            "ERR_VENUE_UNAVAILABLE",
            409,
            "show_date not in venue.available_dates or already booked",
        )
    # On-sale lead: gap from on_sale_at to the show date (UTC midnight) must
    # be no less than 14 days; exactly 14 days is allowed (PRD 3.3).
    if not on_sale_lead_satisfied(show_date, on_sale_dt):
        raise ApiError(
            "ERR_ON_SALE_LEAD_VIOLATED",
            409,
            "show_date - on_sale_at < MIN_ON_SALE_LEAD_DAYS",
        )
    s = new_entity()
    s.update(
        {
            "tour_id": t["id"],
            "market_id": market_id,
            "venue_id": venue_id,
            "show_date": show_date.isoformat(),
            "on_sale_at": fmt_dt(on_sale_dt),
            "capacity": 0,  # frozen snapshot taken at first hold acceptance
            "tickets_sold": 0,
            "gross_potential_cents": 0,
            "avg_ticket_price_cents": avg_ticket_price_cents,
            "projected_gross_cents": 0,
            "projected_cost_cents": 0,
            "status": "HOLD_REQUESTED",
        }
    )
    store["shows"][s["id"]] = s
    # AdvancePacket auto-created alongside, all three sections PENDING.
    p = new_entity()
    p.update(
        {
            "show_id": s["id"],
            "tech_rider_status": "PENDING",
            "hospitality_status": "PENDING",
            "immigration_status": "PENDING",
            "packet_revision": 0,
        }
    )
    store["packets"][p["id"]] = p
    return success_object(show_json(s), 201)


@bp.get("/tours/<tourId>/shows")
def list_shows(tourId):
    authenticate(READ_ROLES)
    t = resolve_tour(tourId)
    market_id = request.args.get("market_id")
    venue_id = request.args.get("venue_id")
    status = request.args.get("status")
    items = [s for s in store["shows"].values() if s["tour_id"] == t["id"]]
    if market_id is not None:
        items = [s for s in items if s["market_id"] == market_id]
    if venue_id is not None:
        items = [s for s in items if s["venue_id"] == venue_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response(items, show_json)


@bp.get("/tours/<tourId>/shows/<showId>")
def get_show(tourId, showId):
    authenticate(READ_ROLES)
    t = resolve_tour(tourId)
    return success_object(show_json(resolve_show(t, showId)))


@bp.post("/tours/<tourId>/shows/<showId>/confirm")
def confirm_show(tourId, showId):
    authenticate(TM_ONLY)
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    b = get_body()
    # OCC gate (PRD 2.8): expected_tour_version is non-optional.
    expected_tour_version = v_int(b, "expected_tour_version")
    if expected_tour_version != t["version"]:
        raise ApiError(
            "ERR_STALE_TOUR_VERSION",
            412,
            "expected_tour_version does not match Tour.version",
        )
    if s["status"] != "HOLD_PLACED":
        raise ApiError("ERR_INVALID_STATE", 409, "confirm requires Show.status == HOLD_PLACED")
    if t["posture"] != "OPEN":
        raise ApiError(
            "ERR_POSTURE_NOT_OPEN", 409, "Operation requires Tour.posture == OPEN"
        )
    venue = store["venues"][s["venue_id"]]
    if (
        s["show_date"] not in venue["available_dates"]
        or s["show_date"] in venue["booked_dates"]
    ):
        raise ApiError(
            "ERR_VENUE_UNAVAILABLE",
            409,
            "show_date not in venue.available_dates or already booked",
        )
    if not confirm_lead_satisfied(parse_date(s["show_date"])):
        raise ApiError(
            "ERR_ON_SALE_LEAD_VIOLATED",
            409,
            "show_date - on_sale_at < MIN_ON_SALE_LEAD_DAYS",
        )
    # Radius-clause sweep: a CRITICAL conflict rejects the confirmation;
    # STANDARD conflicts open ComplianceHolds and let it proceed (PRD 3.4).
    conflicts = radius_conflicts(t, s)
    if any(sev == "CRITICAL" for _, sev in conflicts):
        raise ApiError(
            "ERR_RADIUS_CONFLICT",
            409,
            "Radius-clause sweep produced a CRITICAL conflict",
        )
    s["status"] = "CONFIRMED"
    venue["booked_dates"].append(s["show_date"])
    touch(venue)
    for other, _sev in conflicts:
        h = new_entity()
        h.update(
            {
                "tour_id": t["id"],
                "hold_kind": "RADIUS_CONFLICT",
                "severity": "STANDARD",
                "related_show_id": s["id"],
                "reason": f"Radius conflict with show {other['id']}",
                "status": "ACTIVE",
            }
        )
        store["compliance_holds"][h["id"]] = h
    recompute_tour_posture(t)
    recompute_show_projection(s)
    touch(s)
    recompute_tour_financials(t)
    # A successful confirmation increments the tour's version by one.
    touch(t)
    return success_object(show_json(s))


@bp.post("/tours/<tourId>/shows/<showId>/advance")
def advance_show(tourId, showId):
    authenticate(TM_ONLY)
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    if s["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "advance requires Show.status == CONFIRMED")
    if t["posture"] == "FROZEN":
        raise ApiError(
            "ERR_POSTURE_FROZEN", 409, "Operation blocked because Tour.posture == FROZEN"
        )
    p = packet_for_show(s["id"])
    if p is None or not packet_sections_complete(p):
        raise ApiError(
            "ERR_ADVANCE_INCOMPLETE",
            409,
            "Advance packet has a section not APPROVED (or immigration NOT_REQUIRED)",
        )
    s["status"] = "ADVANCED"
    recompute_show_projection(s)
    touch(s)
    # daysheet_issued flips to true on advance (derived); the packet changed.
    touch(p)
    if recompute_tour_financials(t):
        touch(t)
    return success_object(show_json(s))


@bp.post("/tours/<tourId>/shows/<showId>/mark-performed")
def mark_performed(tourId, showId):
    authenticate(TM_ONLY)
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    if s["status"] != "ADVANCED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "mark-performed requires Show.status == ADVANCED"
        )
    # Allowed once the logical clock reaches the end of the show date in UTC.
    end_of_day = datetime.combine(
        parse_date(s["show_date"]), dtime(23, 59, 59, 999000), tzinfo=timezone.utc
    )
    if clock["now"] < end_of_day:
        raise ApiError(
            "ERR_SHOW_NOT_YET",
            409,
            "Cannot mark performed before show_date end-of-day UTC",
        )
    s["status"] = "PERFORMED"
    recompute_show_projection(s)
    touch(s)
    # Spawn Settlement in DRAFT.
    st = new_entity()
    st.update(
        {
            "show_id": s["id"],
            "box_office_gross_cents": 0,
            "taxes_cents": 0,
            "facility_fees_cents": 0,
            "promoter_expenses_cents": 0,
            "artist_share_cents": 0,
            "variance_cents": 0,
            "variance_flag": "NONE",
            "status": "DRAFT",
            "_submitted_by": None,
        }
    )
    store["settlements"][st["id"]] = st
    if recompute_tour_financials(t):
        touch(t)
    return success_object(show_json(s))


@bp.post("/tours/<tourId>/shows/<showId>/cancel")
def cancel_show(tourId, showId):
    authenticate(TM_ONLY)
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    if s["status"] not in CANCELLABLE_SHOW_STATES:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "cancel requires Show.status in {HOLD_REQUESTED, HOLD_PLACED, CONFIRMED}",
        )
    was = s["status"]
    s["status"] = "CANCELLED"
    if was == "CONFIRMED":
        venue = store["venues"][s["venue_id"]]
        if s["show_date"] in venue["booked_dates"]:
            venue["booked_dates"].remove(s["show_date"])
            touch(venue)
    # Cascade: an ACCEPTED promoter hold becomes WITHDRAWN.
    for h in store["holds"].values():
        if h["show_id"] == s["id"] and h["status"] == "ACCEPTED":
            h["status"] = "WITHDRAWN"
            touch(h)
    # Cascade: reset every advance-packet section back to PENDING.
    p = packet_for_show(s["id"])
    if p is not None:
        changed_sections = 0
        for field in SECTION_FIELDS.values():
            if p[field] != "PENDING":
                p[field] = "PENDING"
                changed_sections += 1
        if changed_sections:
            p["packet_revision"] += changed_sections
            touch(p)
    s["projected_gross_cents"] = 0
    s["projected_cost_cents"] = 0
    touch(s)
    tour_dirty = recompute_tour_posture(t)
    if recompute_tour_financials(t):
        tour_dirty = True
    if tour_dirty:
        touch(t)
    return success_object(show_json(s))


@bp.patch("/tours/<tourId>/shows/<showId>/tickets")
def update_tickets(tourId, showId):
    authenticate(frozenset({ROLE_PROMOTER}))
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    b = get_body()
    tickets_sold = v_int(b, "tickets_sold", minv=0)
    s["tickets_sold"] = tickets_sold
    # The projection only depends on actual sales once the logical clock has
    # reached on_sale_at (PRD 3.6); before that, recompute is a no-op.
    recompute_show_projection(s)
    touch(s)
    if recompute_tour_financials(t):
        touch(t)
    return success_object(show_json(s))


@bp.get("/tours/<tourId>/shows/<showId>/day-sheet")
def day_sheet(tourId, showId):
    authenticate(READ_ROLES)
    t = resolve_tour(tourId)
    s = resolve_show(t, showId)
    p = packet_for_show(s["id"])
    budget_total = sum(
        bl["estimated_cents"]
        for bl in store["budget_lines"].values()
        if bl["show_id"] == s["id"] and bl["is_committed"]
    )
    return success_object(
        {
            "show_id": s["id"],
            "daysheet_issued": compute_daysheet_issued(p, s) if p is not None else False,
            "packet_revision": p["packet_revision"] if p is not None else 0,
            "budget_total_cents": budget_total,
        }
    )


# --- Flat fetch / flat search (PRD 2.9) ---

@bp.get("/tours/shows/<showId>")
def flat_get_show(showId):
    authenticate(READ_ROLES)
    s = store["shows"].get(showId)
    if s is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Show not found")
    return success_object(show_json(s))


@bp.get("/tours/shows")
def flat_search_shows():
    authenticate(READ_ROLES)
    tour_id = request.args.get("tour_id")
    market_id = request.args.get("market_id")
    venue_id = request.args.get("venue_id")
    items = list(store["shows"].values())
    if tour_id is not None:
        items = [s for s in items if s["tour_id"] == tour_id]
    if market_id is not None:
        items = [s for s in items if s["market_id"] == market_id]
    if venue_id is not None:
        items = [s for s in items if s["venue_id"] == venue_id]
    return list_response(items, show_json)
