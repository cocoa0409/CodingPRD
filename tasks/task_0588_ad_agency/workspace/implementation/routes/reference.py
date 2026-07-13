"""Reference data: clients, rate cards, staff members, media placements, and the logical clock."""
from datetime import timedelta

from flask import Blueprint

import calc
import db
import response
import services
import validate
from auth import ALL_ROLES, endpoint

bp = Blueprint("reference", __name__)


# --- Client -----------------------------------------------------------------
@bp.post("/clients")
@endpoint(["AgencyAdmin"])
def create_client():
    b = validate.body()
    name = validate.req_str(b, "name", max_len=120)
    industry = validate.req_enum(b, "industry", validate.INDUSTRIES)
    billing_email = validate.req_str(b, "billing_email")

    obj = db.base_entity()
    obj.update(
        {
            "name": name,
            "industry": industry,
            "billing_email": billing_email,
            "status": "ACTIVE",
        }
    )
    db.CLIENTS[obj["id"]] = obj
    return response.created(db.public(obj))


@bp.get("/clients/<cid>")
@endpoint(ALL_ROLES)
def get_client(cid):
    return response.ok(db.public(services.must("client", cid)))


# --- RateCard ---------------------------------------------------------------
@bp.post("/rate-cards")
@endpoint(["AgencyAdmin"])
def create_rate_card():
    b = validate.body()
    name = validate.req_str(b, "name")
    junior = validate.req_int(b, "rate_junior_cents_per_hour", minimum=0)
    senior = validate.req_int(b, "rate_senior_cents_per_hour", minimum=0)
    director = validate.req_int(b, "rate_director_cents_per_hour", minimum=0)

    obj = db.base_entity()
    obj.update(
        {
            "name": name,
            "rate_junior_cents_per_hour": junior,
            "rate_senior_cents_per_hour": senior,
            "rate_director_cents_per_hour": director,
        }
    )
    db.RATE_CARDS[obj["id"]] = obj
    return response.created(db.public(obj))


@bp.patch("/rate-cards/<rid>")
@endpoint(["AgencyAdmin"])
def patch_rate_card(rid):
    b = validate.body()
    junior = validate.req_int(b, "rate_junior_cents_per_hour", required=False, minimum=0)
    senior = validate.req_int(b, "rate_senior_cents_per_hour", required=False, minimum=0)
    director = validate.req_int(b, "rate_director_cents_per_hour", required=False, minimum=0)

    card = services.must("rate_card", rid)
    if junior is not None:
        card["rate_junior_cents_per_hour"] = junior
    if senior is not None:
        card["rate_senior_cents_per_hour"] = senior
    if director is not None:
        card["rate_director_cents_per_hour"] = director
    services.touch(card)
    return response.ok(db.public(card))


# --- StaffMember ------------------------------------------------------------
@bp.post("/staff-members")
@endpoint(["AgencyAdmin"])
def create_staff_member():
    b = validate.body()
    full_name = validate.req_str(b, "full_name")
    grade = validate.req_enum(b, "grade", validate.GRADES)
    capacity = validate.req_int(
        b, "standard_daily_capacity_minutes", required=False, minimum=1, maximum=1440, default=480
    )
    cost_rate = validate.req_int(b, "cost_rate_cents_per_hour", minimum=0)

    obj = db.base_entity()
    obj.update(
        {
            "full_name": full_name,
            "grade": grade,
            "standard_daily_capacity_minutes": capacity,
            "cost_rate_cents_per_hour": cost_rate,
        }
    )
    db.STAFF[obj["id"]] = obj
    return response.created(db.public(obj))


@bp.get("/staff-members/<sid>/utilization")
@endpoint(["AgencyAdmin", "AccountManager", "CreativeLead", "MediaBuyer"])
def staff_utilization(sid):
    staff = services.must("staff", sid)
    period_start = validate.query_date("period_start")
    period_end = validate.query_date("period_end")
    if period_end <= period_start:
        validate.bad("period_end must be strictly after period_start.")

    weekdays = 0
    day = period_start
    while day < period_end:
        if day.weekday() < 5:
            weekdays += 1
        day += timedelta(days=1)
    capacity_minutes = weekdays * staff["standard_daily_capacity_minutes"]

    rows = [
        t
        for t in db.TIME_ENTRIES.values()
        if t["staff_id"] == sid and period_start <= t["_work_date"] < period_end
    ]
    billable_rows = [
        t for t in rows if t["billable"] and t["status"] in ("APPROVED", "BILLED")
    ]
    logged_rows = [t for t in rows if t["status"] in ("SUBMITTED", "APPROVED", "BILLED")]

    billable_minutes = sum(t["minutes"] for t in billable_rows)
    logged_minutes = sum(t["minutes"] for t in logged_rows)
    billed_amount_cents = sum(t["billable_amount_cents"] for t in billable_rows)

    capacity_pct = (
        calc.pct1(calc.dec(billable_minutes) / calc.dec(capacity_minutes) * 100)
        if capacity_minutes > 0
        else 0.0
    )
    logged_pct = (
        calc.pct1(calc.dec(billable_minutes) / calc.dec(logged_minutes) * 100)
        if logged_minutes > 0
        else 0.0
    )
    effective_rate = (
        calc.rhu(calc.dec(billed_amount_cents) * 60 / calc.dec(billable_minutes))
        if billable_minutes > 0
        else 0
    )

    return response.ok(
        {
            "staff_id": sid,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "capacity_minutes": capacity_minutes,
            "logged_minutes": logged_minutes,
            "billable_minutes": billable_minutes,
            "billed_amount_cents": billed_amount_cents,
            "utilization_pct_capacity_based": capacity_pct,
            "utilization_pct_logged_based": logged_pct,
            "effective_billable_rate_cents_per_hour": effective_rate,
        }
    )


# --- MediaPlacement ---------------------------------------------------------
@bp.post("/media-placements")
@endpoint(["AgencyAdmin"])
def create_placement():
    b = validate.body()
    publisher_name = validate.req_str(b, "publisher_name")
    channel = validate.req_enum(b, "channel", validate.CHANNELS)
    min_dark_days = validate.req_int(
        b, "min_dark_days", required=False, minimum=0, maximum=30, default=0
    )

    obj = db.base_entity()
    obj.update(
        {
            "publisher_name": publisher_name,
            "channel": channel,
            "min_dark_days": min_dark_days,
        }
    )
    db.PLACEMENTS[obj["id"]] = obj
    return response.created(db.public(obj))


# --- Logical clock ----------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@endpoint(["AgencyAdmin"])
def set_clock():
    b = validate.body()
    to = validate.req_datetime(b, "to_iso8601")
    db.clock_set(to)

    expired = []
    for sow in db.ordered(db.SOWS):
        if sow["status"] == "COUNTERSIGNED" and to >= sow["_effective_end_dt"]:
            sow["status"] = "EXPIRED"
            services.touch(sow)
            expired.append(sow["id"])

    return response.ok({"now_utc": db.fmt_iso(to), "expired_sow_ids": expired})
