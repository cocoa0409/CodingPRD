"""Installations, BAH rates, the waitlist offer run and the allotment run."""

from flask import Blueprint

import middleware as mw
import response as resp
from db import (base_row, bump, db, iso, now, now_iso, parse_date, sort_rows,
                timedelta)
from errors import ApiError
from services import core, lookup

bp = Blueprint("installations", __name__)

READ_INSTALLATION_ROLES = mw.ALL_ROLES
BAH_READ_ROLES = (mw.PLATFORM_ADMIN, mw.PROPERTY_MANAGER, mw.SERVICE_MEMBER,
                  mw.INSTALLATION_HOUSING_OFFICE)


@bp.post("/installations")
def create_installation():
    mw.authenticate((mw.PLATFORM_ADMIN,))
    body = mw.json_body()
    row = base_row()
    row["name"] = mw.v_str(body, "name")
    row["branch"] = mw.v_enum(body, "branch", mw.BRANCHES)
    row["mha_code"] = mw.v_str(body, "mha_code")
    row["bill_of_rights_version"] = mw.v_str(body, "bill_of_rights_version")
    row["turn_buffer_days"] = mw.v_int(body, "turn_buffer_days", required=False,
                                      default=5, minimum=0)
    row["offer_response_hours"] = mw.v_int(body, "offer_response_hours", required=False,
                                          default=72, minimum=1)
    row["decline_limit"] = mw.v_int(body, "decline_limit", required=False,
                                   default=2, minimum=1)
    row["decline_penalty_days"] = mw.v_int(body, "decline_penalty_days", required=False,
                                          default=15, minimum=0)
    row["incentive_base_pct"] = mw.v_number(body, "incentive_base_pct", required=False,
                                            default=0.03, minimum=0, maximum=1)
    row["total_unit_count"] = 0
    row["available_unit_count"] = 0
    row["assigned_unit_count"] = 0
    row["occupied_unit_count"] = 0
    row["offline_unit_count"] = 0
    row["hazard_hold_unit_count"] = 0
    row["pending_application_count"] = 0
    row["offer_run_epoch"] = 0
    row["last_offer_run_at"] = None
    db.installations[row["id"]] = row
    return resp.created(row)


@bp.get("/installations/<installation_id>")
def get_installation(installation_id):
    mw.authenticate(READ_INSTALLATION_ROLES)
    return resp.ok(lookup.installation(installation_id))


@bp.get("/installations/<installation_id>/bah-rates")
def list_bah_rates(installation_id):
    mw.authenticate(BAH_READ_ROLES)
    limit, offset = mw.pagination()
    pay_grade = mw.q_pay_grade("pay_grade")
    with_dependents = mw.q_bool("with_dependents")
    effective_year = mw.q_int("effective_year")
    installation = lookup.installation(installation_id)
    rows = lookup.bah_rates_of(installation["id"])
    if pay_grade is not None:
        rows = [r for r in rows if r["pay_grade"] == pay_grade]
    if with_dependents is not None:
        rows = [r for r in rows if bool(r["with_dependents"]) == with_dependents]
    if effective_year is not None:
        rows = [r for r in rows if int(r["effective_year"]) == effective_year]
    return resp.page(rows, limit, offset)


@bp.post("/bah-rates")
def create_bah_rate():
    mw.authenticate((mw.PLATFORM_ADMIN,))
    body = mw.json_body()
    installation_id = mw.v_id(body, "installation_id")
    pay_grade = mw.v_pay_grade(body, "pay_grade")
    with_dependents = mw.v_bool(body, "with_dependents")
    effective_year = mw.v_int(body, "effective_year", minimum=2024, maximum=2030)
    monthly = mw.v_int(body, "monthly_rate_cents", minimum=1)
    utility = mw.v_int(body, "utility_allowance_cents", minimum=0)
    if utility >= monthly:
        mw.bad("utility_allowance_cents", "must be less than monthly_rate_cents")
    installation = lookup.installation(installation_id)
    row = base_row(common=False)
    row["installation_id"] = installation["id"]
    row["pay_grade"] = pay_grade
    row["with_dependents"] = with_dependents
    row["effective_year"] = effective_year
    row["monthly_rate_cents"] = monthly
    row["utility_allowance_cents"] = utility
    db.bah_rates[row["id"]] = row
    return resp.created(row)


# ------------------------------------------------------------ 3.4 the offer run

@bp.post("/installations/<installation_id>/waitlist-offer-run")
def offer_run(installation_id):
    mw.authenticate((mw.PROPERTY_MANAGER, mw.INSTALLATION_HOUSING_OFFICE))
    installation = lookup.installation(installation_id)

    units = [u for u in lookup.units_of(installation["id"]) if u["status"] == "AVAILABLE"]
    units.sort(key=lambda u: (int(u["bedroom_count"]), u["created_at"], u["_seq"]))

    already_offered = set()
    moment = now()
    expires_at = iso(moment + timedelta(hours=int(installation["offer_response_hours"])))

    for unit in units:
        pool = []
        for app in sort_rows(list(db.applications.values())):
            if app["installation_id"] != installation["id"]:
                continue
            if app["status"] != "PENDING":
                continue
            if app["id"] in already_offered:
                continue
            if int(app["bedroom_eligibility"]) != int(unit["bedroom_count"]):
                continue
            if app["rank_category"] != unit["designated_rank_category"]:
                continue
            if app["accessibility_required"] and \
                    "ROLL_IN_SHOWER" not in (unit["accessibility_features"] or []):
                continue
            pool.append(app)
        if not pool:
            continue
        pool.sort(key=lambda a: (a["effective_control_date"],
                                 -int(a["bedroom_eligibility"]),
                                 a["created_at"], a["_seq"]))
        winner = pool[0]
        winner["status"] = "OFFERED"
        winner["offered_unit_id"] = unit["id"]
        winner["offer_expires_at"] = expires_at
        winner["offer_count"] = int(winner["offer_count"]) + 1
        bump(winner)
        unit["status"] = "ASSIGNED"
        bump(unit)
        already_offered.add(winner["id"])

    core.recount(installation, bump_row=False)
    installation["offer_run_epoch"] = int(installation["offer_run_epoch"]) + 1
    installation["last_offer_run_at"] = now_iso()
    bump(installation)
    return resp.ok(installation)


# -------------------------------------------------------- 3.9 the allotment run

@bp.post("/installations/<installation_id>/allotment-run")
def allotment_run(installation_id):
    mw.authenticate((mw.PROPERTY_MANAGER, mw.PLATFORM_ADMIN))
    body = mw.json_body()
    period_month = mw.v_period(body, "period_month")
    installation = lookup.installation(installation_id)

    for lease in lookup.leases_of_installation(installation["id"]):
        if lease["allotment_status"] != "ACTIVE":
            continue
        existing = [t for t in lookup.transactions_of(lease["id"])
                    if t["type"] == "CHARGE" and t["period_month"] == period_month]
        if existing:
            continue
        core.post_transaction(lease, "CHARGE", period_month,
                              int(lease["net_rent_cents"]),
                              "ALLOTMENT_RUN:" + period_month)
        bump(lease)
    return resp.ok(installation)
