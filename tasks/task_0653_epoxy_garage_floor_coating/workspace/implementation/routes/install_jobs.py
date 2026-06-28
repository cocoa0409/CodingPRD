"""Install job endpoints: book, list, start, complete, mark-cured
(SCAFFOLD §1.5 / PRD §3.6, §3.7, §3.8)."""
from flask import Blueprint

from db import db
from errors import err
from middleware import authenticate, require_role
from response import success
from services import serialize
from services.calc import (DEFAULT_TERM_MONTHS, REFERRAL_CREDIT_CENTS, cure_window,
                           financing_payment, quote_pricing)
from services.common import (get_body, new_row, parse_pagination, paginate,
                             require_int, require_str, touch)
from services.timeutil import parse_iso8601

bp = Blueprint("install_jobs", __name__)


def _accepted_quote(project):
    if project["accepted_quote_id"] is None:
        return None
    return db.quotes.get(project["accepted_quote_id"])


def _same_utc_day(a, b):
    return (a.year, a.month, a.day) == (b.year, b.month, b.day)


# ---------------------------------------------------------------------------
# Book install (Scheduler)
# ---------------------------------------------------------------------------
@bp.route("/projects/<id>/install-jobs", methods=["POST"])
def book_install(id):
    _, role = authenticate()
    require_role(role, {"Scheduler"})
    project = db.projects.get(id)
    if project is None:
        raise err("ERR_NOT_FOUND", "Project not found")

    body = get_body()
    crew_id = require_str(body, "crew_id")
    install_date_raw = body.get("install_date")
    if install_date_raw is None:
        raise err("ERR_VALIDATION", "install_date is required")

    # priority 5: body reference resolves
    crew = db.crews.get(crew_id)
    if crew is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "crew_id does not resolve")

    # priority 9: cross-dimension guard — sales_status must be ACCEPTED
    if project["sales_status"] != "ACCEPTED":
        raise err("ERR_SALES_NOT_ACCEPTED", "Project sales track has not reached ACCEPTED")

    # priority 8: build_status state guard
    if project["build_status"] != "PRE_BUILD":
        raise err("ERR_INVALID_STATE", "Project build_status is not PRE_BUILD")

    install_date = parse_iso8601(install_date_raw, "install_date")

    accepted_quote = _accepted_quote(project)
    coating_system = db.coating_systems.get(accepted_quote["coating_system_id"])
    family = coating_system["family"]

    # priority 11: METALLIC requires metallic_certified crew
    if family == "METALLIC" and not crew["metallic_certified"]:
        raise err("ERR_CREW_NOT_METALLIC_CERTIFIED",
                  "METALLIC system requires a metallic_certified crew")

    # priority 12: crew same-day double-booking (discrete day bucket)
    for j in db.install_jobs.values():
        if j["crew_id"] == crew_id and j["status"] in ("BOOKED", "IN_PROGRESS"):
            if _same_utc_day(j["install_date"], install_date):
                raise err("ERR_CREW_DAY_DOUBLE_BOOKED",
                          "Crew already booked on this UTC calendar day")

    # compute this job's cure window for the overlap check
    _, _, new_vehicle_ok = cure_window(install_date, family)

    # priority 13: site cure-window overlap (continuous half-open interval) on
    # other non-terminal jobs of a DIFFERENT project of the SAME customer
    for j in db.install_jobs.values():
        if j["status"] not in ("BOOKED", "IN_PROGRESS", "COMPLETED"):
            continue
        other_project = db.projects.get(j["project_id"])
        if other_project is None:
            continue
        if other_project["id"] == project["id"]:
            continue
        if other_project["customer_id"] != project["customer_id"]:
            continue
        # half-open [install_date, vehicle_traffic_ok_at); touching does not overlap
        a_start, a_end = install_date, new_vehicle_ok
        b_start, b_end = j["install_date"], j["vehicle_traffic_ok_at"]
        if a_start < b_end and b_start < a_end:
            raise err("ERR_SITE_CURE_WINDOW_OVERLAP",
                      "New install's cure window overlaps another install of this customer")

    # priority 14: capacity — accepted quote priced_sqft <= crew.max_sqft_per_day
    if accepted_quote["priced_sqft"] > crew["max_sqft_per_day"]:
        raise err("ERR_CREW_CAPACITY_EXCEEDED",
                  "priced_sqft exceeds crew max_sqft_per_day")

    install_end, foot_ok, vehicle_ok = cure_window(install_date, family)

    row = new_row({
        "project_id": id,
        "crew_id": crew_id,
        "install_date": install_date,
        "install_end": install_end,
        "foot_traffic_ok_at": foot_ok,
        "vehicle_traffic_ok_at": vehicle_ok,
        "as_measured_sqft": None,
        "as_measured_crack_ft": None,
        "status": "BOOKED",
    })
    db.install_jobs[row["id"]] = row

    project["build_status"] = "SCHEDULED"
    touch(project)

    return success(serialize.install_job(row), 201)


@bp.route("/projects/<id>/install-jobs", methods=["GET"])
def list_project_install_jobs(id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "Scheduler", "Crew"})
    if db.projects.get(id) is None:
        raise err("ERR_NOT_FOUND", "Project not found")
    limit, offset = parse_pagination()
    rows = [j for j in db.install_jobs.values() if j["project_id"] == id]
    page, meta = paginate(rows, limit, offset)
    return success([serialize.install_job(r) for r in page], 200, pagination=meta)


# ---------------------------------------------------------------------------
# Start (Crew)
# ---------------------------------------------------------------------------
@bp.route("/install-jobs/<id>/start", methods=["POST"])
def start_install(id):
    user_id, role = authenticate()
    require_role(role, {"Crew"})
    job = db.install_jobs.get(id)
    if job is None:
        raise err("ERR_NOT_FOUND", "Install job not found")

    # state guard
    if job["status"] != "BOOKED":
        raise err("ERR_INVALID_STATE", "Install job is not BOOKED")
    # priority 16: install_date reached
    if db.now() < job["install_date"]:
        raise err("ERR_INSTALL_DATE_NOT_REACHED", "Install date not yet reached")

    job["status"] = "IN_PROGRESS"
    touch(job)
    return success(serialize.install_job(job), 200)


# ---------------------------------------------------------------------------
# Complete (Crew) — creates FINAL quote, advances build to CURING
# ---------------------------------------------------------------------------
@bp.route("/install-jobs/<id>/complete", methods=["POST"])
def complete_install(id):
    _, role = authenticate()
    require_role(role, {"Crew"})
    job = db.install_jobs.get(id)
    if job is None:
        raise err("ERR_NOT_FOUND", "Install job not found")

    # state guard
    if job["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Install job is not IN_PROGRESS")

    body = get_body()
    as_measured_sqft = require_int(body, "as_measured_sqft", minimum=1)
    as_measured_crack_ft = require_int(body, "as_measured_crack_ft", minimum=0)

    project = db.projects.get(job["project_id"])
    accepted_quote = _accepted_quote(project)
    coating_system = db.coating_systems.get(accepted_quote["coating_system_id"])
    assessment = db.assessments.get(accepted_quote["assessment_id"])

    job["status"] = "COMPLETED"
    job["as_measured_sqft"] = as_measured_sqft
    job["as_measured_crack_ft"] = as_measured_crack_ft
    touch(job)

    # FINAL quote re-priced from on-site numbers, same engine, prep_tier from assessment
    priced = quote_pricing(
        sqft_in=as_measured_sqft,
        crack_ft_in=as_measured_crack_ft,
        prep_tier=assessment["prep_tier"],
        coating_family=coating_system["family"],
        sku=coating_system["sku"],
        install_season=accepted_quote["install_season"],
    )

    monthly_payment_cents = 0
    financing_plan_id = accepted_quote["financing_plan_id"]
    if financing_plan_id is not None:
        plan = db.financing_plans.get(financing_plan_id)
        if plan is not None:
            monthly_payment_cents = financing_payment(
                priced["grand_total_cents"], plan["apr_bps"], plan["term_months"])

    final_quote = new_row({
        "project_id": project["id"],
        "assessment_id": accepted_quote["assessment_id"],
        "coating_system_id": accepted_quote["coating_system_id"],
        "color_option_id": accepted_quote["color_option_id"],
        "financing_plan_id": financing_plan_id,
        "install_season": accepted_quote["install_season"],
        "variant": "FINAL",
        "priced_sqft": priced["priced_sqft"],
        "system_material_cents": priced["system_material_cents"],
        "prep_labor_cents": priced["prep_labor_cents"],
        "volume_discount_pct_bps": priced["volume_discount_pct_bps"],
        "discount_cents": priced["discount_cents"],
        "mobilization_cents": priced["mobilization_cents"],
        "grand_total_cents": priced["grand_total_cents"],
        "monthly_payment_cents": monthly_payment_cents,
        "status": "ACCEPTED",
    })
    db.quotes[final_quote["id"]] = final_quote

    # prior ACCEPTED estimate quote -> SUPERSEDED; repoint accepted_quote_id
    accepted_quote["status"] = "SUPERSEDED"
    touch(accepted_quote)
    project["accepted_quote_id"] = final_quote["id"]

    # build track SCHEDULED -> INSTALLED -> CURING within one call (rests at CURING)
    project["build_status"] = "CURING"
    touch(project)

    return success(serialize.install_job(job), 200)


# ---------------------------------------------------------------------------
# Mark cured (Scheduler) — creates Warranty, may convert referral
# ---------------------------------------------------------------------------
@bp.route("/install-jobs/<id>/mark-cured", methods=["POST"])
def mark_cured(id):
    _, role = authenticate()
    require_role(role, {"Scheduler"})
    job = db.install_jobs.get(id)
    if job is None:
        raise err("ERR_NOT_FOUND", "Install job not found")

    # state guard
    if job["status"] != "COMPLETED":
        raise err("ERR_INVALID_STATE", "Install job is not COMPLETED")
    # priority 15: cure window elapsed
    if db.now() < job["vehicle_traffic_ok_at"]:
        raise err("ERR_CURE_WINDOW_NOT_ELAPSED", "Cure window has not elapsed")

    project = db.projects.get(job["project_id"])
    final_quote = _accepted_quote(project)

    job["status"] = "CURED"
    touch(job)

    project["build_status"] = "COMPLETE"

    # create Warranty (ACTIVE)
    warranty = new_row({
        "project_id": project["id"],
        "install_job_id": job["id"],
        "covered_install_price_cents": final_quote["grand_total_cents"],
        "term_months": DEFAULT_TERM_MONTHS,
        "coverage_start_at": job["vehicle_traffic_ok_at"],
        "status": "ACTIVE",
    })
    db.warranties[warranty["id"]] = warranty

    # convert PENDING referral -> CONVERTED; referrer credit += 15000
    if project["referral_id"]:
        ref = db.referrals.get(project["referral_id"])
        if ref and ref["status"] == "PENDING":
            ref["status"] = "CONVERTED"
            touch(ref)
            referrer = db.customers.get(ref["referrer_customer_id"])
            if referrer is not None:
                referrer["account_credit_balance_cents"] += REFERRAL_CREDIT_CENTS
                touch(referrer)

    touch(project)
    return success(serialize.install_job(job), 200)
