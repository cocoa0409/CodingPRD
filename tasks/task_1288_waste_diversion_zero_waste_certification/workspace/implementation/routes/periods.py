"""ScorecardPeriod endpoints, including the close sweep."""

from flask import Blueprint

from db import base_record, parse_iso_dt, store, touch
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_PERIOD_ALREADY_OPEN,
    ERR_PERIOD_HAS_PENDING_TICKETS,
    ERR_PERIOD_OVERLAP,
    ERR_WINDOW_INVALID,
    not_found,
)
from middleware import (
    no_input,
    ALL_ROLES,
    authenticate,
    check_unknown,
    f_date,
    f_str,
    get_body,
)
from response import success_list, success_object
from services.calc import (
    add_months,
    audit_adjusted_settlement,
    compute_live_period,
    cost_avoidance,
    dec,
)
from services.lifecycle import pub_period, rederive_tier
from util import PERIOD_STATUSES, apply_filters, paginate, sort_items

bp = Blueprint("periods", __name__)


@bp.route("/scorecard_periods", methods=["POST"])
def create_period():
    authenticate(["CertificationOfficer"])
    b = get_body()
    check_unknown(b, ["site_id", "period_start", "period_end"])
    site_id = f_str(b, "site_id")
    ps = f_date(b, "period_start")
    pe = f_date(b, "period_end")

    if site_id not in store.sites:
        raise not_found("Site not found")

    # Overlap layer: the single-open-period guard fires BEFORE overlap.
    for p in store.periods.values():
        if p["site_id"] == site_id and p["status"] == "OPEN":
            raise ApiError(ERR_PERIOD_ALREADY_OPEN, 409,
                           "The site already has an OPEN scorecard period")
    for p in store.periods.values():
        if (p["site_id"] == site_id
                and p["period_start"] < pe and ps < p["period_end"]):
            raise ApiError(ERR_PERIOD_OVERLAP, 409,
                           "Another period overlaps this half-open window")

    # Window validity (half-open: start strictly before end).
    if ps >= pe:
        raise ApiError(ERR_WINDOW_INVALID, 422,
                       "period_start must be earlier than period_end")

    rec = base_record({
        "site_id": site_id,
        "period_start": ps,
        "period_end": pe,
        "status": "OPEN",
        # Frozen slots used once CLOSED; OPEN reads compute live.
        "total_waste_lbs_validated": 0,
        "diverted_lbs_validated": 0,
        "diversion_rate_certified_pct": 0.0,
        "total_waste_lbs_provisional": 0,
        "diverted_lbs_provisional": 0,
        "diversion_rate_provisional_pct": 0.0,
        "rebate_estimate_cents": 0,
        "rebate_settled_cents": None,
        "cost_avoided_cents": None,
        "contamination_event_count": 0,
    })
    store.periods[rec["id"]] = rec
    return success_object(pub_period(rec), 201)


@bp.route("/scorecard_periods/<period_id>", methods=["GET"])
def get_period(period_id):
    authenticate(ALL_ROLES)
    rec = store.periods.get(period_id)
    if rec is None:
        raise not_found("Scorecard period not found")
    return success_object(pub_period(rec))


@bp.route("/scorecard_periods", methods=["GET"])
def list_periods():
    authenticate(ALL_ROLES)
    items = apply_filters(store.periods.values(), [
        ("site_id", "site_id", None),
        ("status", "status", PERIOD_STATUSES),
    ])
    page, meta = paginate(sort_items(items))
    return success_list([pub_period(p) for p in page], meta)


def _goal_achieved(goal, frozen):
    """Evaluate one ACTIVE goal against the period's frozen certified metrics."""
    target = dec(goal["target_value"])
    if goal["metric"] == "DIVERSION_RATE":
        return dec(frozen["diversion_rate_certified_pct"]) >= target
    if goal["metric"] == "COST_AVOIDANCE":
        return dec(frozen["cost_avoided_cents"]) >= target
    # CONTAMINATION_EVENTS: achieved when the count is at most the target.
    return dec(frozen["contamination_event_count"]) <= target


@bp.route("/scorecard_periods/<period_id>/close", methods=["POST"])
def close_period(period_id):
    authenticate(["CertificationOfficer"])
    no_input(get_body())
    p = store.periods.get(period_id)
    if p is None:
        raise not_found("Scorecard period not found")
    if p["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Period is not OPEN")

    site_id = p["site_id"]
    ws, we = p["period_start"], p["period_end"]

    # Close requires zero in-window PENDING tickets.
    for t in store.tickets.values():
        if (t["site_id"] == site_id and t["validation_status"] == "PENDING"
                and ws <= t["ticket_date"] < we):
            raise ApiError(ERR_PERIOD_HAS_PENDING_TICKETS, 409,
                           "PENDING tickets remain inside the period window")

    site = store.sites[site_id]

    # Freeze: certified/provisional totals, rates, rebate estimate, and the
    # contamination event count; then settle rebates and compute cost avoidance.
    frozen = compute_live_period(store, p)
    p["total_waste_lbs_validated"] = frozen["total_waste_lbs_validated"]
    p["diverted_lbs_validated"] = frozen["diverted_lbs_validated"]
    p["diversion_rate_certified_pct"] = frozen["diversion_rate_certified_pct"]
    p["total_waste_lbs_provisional"] = frozen["total_waste_lbs_provisional"]
    p["diverted_lbs_provisional"] = frozen["diverted_lbs_provisional"]
    p["diversion_rate_provisional_pct"] = frozen["diversion_rate_provisional_pct"]
    p["rebate_estimate_cents"] = frozen["rebate_estimate_cents"]
    p["contamination_event_count"] = frozen["contamination_event_count"]
    p["rebate_settled_cents"] = audit_adjusted_settlement(store, p)
    p["cost_avoided_cents"] = cost_avoidance(store, p, site)
    p["status"] = "CLOSED"
    touch(p)

    # Evaluate every ACTIVE goal whose window is fully contained in the period.
    for g in store.goals.values():
        if (g["site_id"] == site_id and g["status"] == "ACTIVE"
                and ws <= g["window_start"] and g["window_end"] <= we):
            g["status"] = "ACHIEVED" if _goal_achieved(g, p) else "MISSED"
            touch(g)

    # Contract expiry sweep: window_end earlier than the logical clock date.
    clock_date = store.clock_date()
    for c in store.contracts.values():
        if (c["site_id"] == site_id and c["status"] in ("ACTIVE", "SUSPENDED")
                and c["window_end"] < clock_date):
            c["status"] = "EXPIRED"
            touch(c)

    # Certification lapse sweep: decided_at + 12 months strictly before clock.
    lapsed = False
    for a in store.applications.values():
        if a["site_id"] == site_id and a["status"] == "APPROVED":
            decided = parse_iso_dt(a["decided_at"])
            if add_months(decided, 12) < store.clock_dt:
                a["status"] = "LAPSED"
                touch(a)
                lapsed = True
    if lapsed:
        rederive_tier(site_id)

    return success_object(pub_period(p))
