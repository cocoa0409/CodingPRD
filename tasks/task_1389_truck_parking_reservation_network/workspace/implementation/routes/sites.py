"""Sites: CRUD, availability, forecast, ops-run (PRD §3.1, §3.2, §3.8)."""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, request

import auth
import db
import domain
import errors
import services
import util

bp = Blueprint("sites", __name__)

READ_ROLES = ("Driver", "FleetManager", "SiteOperator", "NetworkAdmin")
OPS_ROLES = ("Driver", "SiteOperator", "NetworkAdmin")


def _site_or_404(site_id):
    site = domain.get("sites", site_id)
    if site is None:
        raise errors.not_found("Site not found")
    return site


def _serialize(site):
    return domain.serialize_site(site, services.site_posture(site["id"]))


@bp.post("/sites")
def create_site():
    ident = auth.identity()
    auth.require_roles(ident, ("NetworkAdmin",))
    body = util.get_body(required=True)
    util.req_fields(body, ["name", "base_nightly_rate_cents"])
    name = util.req_str(body, "name")
    rate = util.req_int(body, "base_nightly_rate_cents")
    no_show = util.opt_int(body, "no_show_grace_minutes", 60)
    overstay = util.opt_int(body, "overstay_grace_minutes", 30)
    free_window = util.opt_int(body, "cancellation_free_window_hours", 24)

    site = domain.new_entity("sites", {
        "name": name,
        "base_nightly_rate_cents": rate,
        "no_show_grace_minutes": no_show,
        "overstay_grace_minutes": overstay,
        "cancellation_free_window_hours": free_window,
        "ops_run_index": 0,
    })
    # Auto-create the default ACTIVE rate plan; site.version stays 1 (PRD §3.1).
    plan_fields = dict(services.RATE_PLAN_DEFAULTS)
    plan_fields["site_id"] = site["id"]
    plan_fields["status"] = "ACTIVE"
    domain.new_entity("rate_plans", plan_fields)
    return util.ok(_serialize(site), status=201)


@bp.get("/sites")
def list_sites():
    ident = auth.identity()
    auth.require_roles(ident, READ_ROLES)
    items = util.sort_created(list(domain.all_of("sites")))
    page, pg = util.paginate(items)
    return util.ok([_serialize(s) for s in page], pagination=pg)


@bp.get("/sites/<site_id>")
def get_site(site_id):
    ident = auth.identity()
    auth.require_roles(ident, READ_ROLES)
    return util.ok(_serialize(_site_or_404(site_id)))


@bp.patch("/sites/<site_id>")
def update_site(site_id):
    ident = auth.identity()
    auth.require_roles(ident, ("NetworkAdmin",))
    site = _site_or_404(site_id)
    body = util.get_body()
    if "name" in body and body["name"] is not None:
        site["name"] = util.req_str(body, "name")
    if "base_nightly_rate_cents" in body and body["base_nightly_rate_cents"] is not None:
        site["base_nightly_rate_cents"] = util.req_int(body, "base_nightly_rate_cents")
    if "no_show_grace_minutes" in body and body["no_show_grace_minutes"] is not None:
        site["no_show_grace_minutes"] = util.req_int(body, "no_show_grace_minutes")
    if "overstay_grace_minutes" in body and body["overstay_grace_minutes"] is not None:
        site["overstay_grace_minutes"] = util.req_int(body, "overstay_grace_minutes")
    if ("cancellation_free_window_hours" in body
            and body["cancellation_free_window_hours"] is not None):
        site["cancellation_free_window_hours"] = util.req_int(
            body, "cancellation_free_window_hours")
    domain.touch(site)  # every edit bumps the site version
    return util.ok(_serialize(site))


@bp.get("/sites/<site_id>/availability")
def site_availability(site_id):
    ident = auth.identity()
    auth.require_roles(ident, OPS_ROLES)
    site = _site_or_404(site_id)

    now = db.clock_now()
    start_s = request.args.get("window_start")
    end_s = request.args.get("window_end")
    if start_s is None:
        window_start = now
    else:
        window_start = db._parse_dt(start_s)
        if window_start is None:
            raise errors.window_invalid("window_start is unparseable")
    if end_s is None:
        candidate = datetime.combine(now.date(), time(11, 0), tzinfo=timezone.utc)
        window_end = candidate if candidate > window_start \
            else candidate + timedelta(days=1)
    else:
        window_end = db._parse_dt(end_s)
        if window_end is None:
            raise errors.window_invalid("window_end is unparseable")
    if not window_start < window_end:
        raise errors.window_invalid("window_start must be before window_end")

    reservable_total = reservable_free = first_total = first_free = 0
    for s in domain.all_of("stalls"):
        if s["site_id"] != site_id or s["status"] != "ACTIVE":
            continue
        free = services.stall_free_of_bookings(s["id"], (window_start, window_end))
        if s["is_reservable"]:
            reservable_total += 1
            reservable_free += 1 if free else 0
        else:
            first_total += 1
            first_free += 1 if free else 0
    return util.ok({
        "reservable_total": reservable_total,
        "reservable_free": reservable_free,
        "first_come_total": first_total,
        "first_come_free": first_free,
    })


@bp.get("/sites/<site_id>/forecast")
def site_forecast(site_id):
    ident = auth.identity()
    auth.require_roles(ident, OPS_ROLES)
    _site_or_404(site_id)

    date_s = request.args.get("date")
    if date_s is None:
        raise errors.validation("Query parameter date is required")
    d = services.parse_date(date_s)
    if d is None:
        raise errors.window_invalid("date is unparseable")

    total_stalls = sum(1 for s in domain.all_of("stalls")
                       if s["site_id"] == site_id and s["status"] == "ACTIVE")
    n_start, n_end = services.night_interval(d)

    occupied_stalls = set()
    for b in domain.all_of("bookings"):
        if (b["site_id"] == site_id and b["status"] in services.NON_TERMINAL_BOOKING
                and services.overlaps(b["checkin_open_at"], b["checkout_due_at"],
                                      n_start, n_end)):
            occupied_stalls.add(b["stall_id"])
    confirmed = len(occupied_stalls)

    queued = offered = 0
    for e in domain.all_of("waitlist_entries"):
        if e["site_id"] != site_id or e["status"] not in ("QUEUED", "OFFERED"):
            continue
        e_start, e_end = services.entry_window(e)
        if services.overlaps(e_start, e_end, n_start, n_end):
            if e["status"] == "QUEUED":
                queued += 1
            else:
                offered += 1

    weighted = Decimal(confirmed) + Decimal("0.5") * queued + Decimal("0.25") * offered
    if total_stalls > 0:
        confirmed_pct = util.rhu_pct_2dp(Decimal(100 * confirmed) / total_stalls)
        committed_pct = util.rhu_pct_2dp(Decimal(100) * weighted / total_stalls)
    else:
        confirmed_pct = committed_pct = 0.0
    return util.ok({
        "date": d.isoformat(),
        "confirmed_occupied_stalls": confirmed,
        "confirmed_occupancy_pct": confirmed_pct,
        "committed_weighted_demand": float(weighted),
        "committed_occupancy_pct": committed_pct,
    })


@bp.post("/sites/<site_id>/ops-run")
def site_ops_run(site_id):
    ident = auth.identity()
    auth.require_roles(ident, ("SiteOperator", "NetworkAdmin"))
    site = _site_or_404(site_id)
    services.site_ops_run(site)
    return util.ok(_serialize(site))
