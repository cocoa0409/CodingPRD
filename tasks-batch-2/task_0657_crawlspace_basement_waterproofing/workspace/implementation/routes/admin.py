"""Admin / test-driving endpoints: logical clock + seed fast-forwards."""
from flask import Blueprint

import db
import errors
import helpers
from clock import clock
from middleware import authenticate, authorize, get_json_body
from response import object_response
from services import calculations, factory

bp = Blueprint("admin", __name__)

ALL_ROLES = ["Scheduler", "WarrantyAdmin", "Estimator", "Inspector", "FinancePartner", "Homeowner"]


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    # Roles: any of the six (PRD §4).
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    body = get_json_body()
    helpers.require_fields(body, ["to_iso8601"])
    new_dt = helpers.parse_iso(body["to_iso8601"])
    clock.set(new_dt)
    return object_response({}, status=200)


@bp.route("/_seed/scheduled-job", methods=["POST"])
def seed_scheduled_job():
    """Provision a Job to lifecycle SCHEDULED: sump-only accepted quote (total 395900),
    CASH financing, fresh PLANNED InstallOrder. (SCAFFOLD §1.5 / PRD §3.12)"""
    _uid, role = authenticate()
    authorize(role, ["Scheduler"])
    body = get_json_body()
    helpers.require_fields(body, ["homeowner_id"])
    homeowner_id = body["homeowner_id"]
    homeowner = helpers.fk_or_422(db.homeowners, homeowner_id, "Homeowner")

    # Build the full chain. Footprint <= 800 -> base tier 1 (250000). Sump-only scope:
    # subtotal = 250000 + 120000 = 370000; no discount; tax 7% = 25900; total = 395900.
    job = factory.create_job(homeowner_id, "Seeded Property", "CRAWLSPACE", 800)

    inspection = factory.create_inspection(job["id"], 50.0, 0, False)
    inspection["status"] = "FINALIZED"
    inspection["severity"] = calculations.compute_severity(50.0, 0, False)
    helpers.touch(inspection)
    job["assessment_severity"] = inspection["severity"]
    job["lifecycle_status"] = "INSPECTED"
    helpers.touch(job)

    scope = {
        "includes_vapor_barrier": False,
        "includes_sump": True,
        "includes_dehumidifier": False,
        "includes_drain": False,
        "includes_battery_backup": False,
    }
    quote = factory.create_quote(job["id"], job["footprint_sqft"], scope, 0, "NONE", revision=1)
    quote["status"] = "SENT"
    quote["expires_at"] = helpers.iso_from_dt(helpers.add_days(helpers.parse_iso(quote["created_at"]), 30))
    helpers.touch(quote)
    job["lifecycle_status"] = "QUOTED"
    helpers.touch(job)

    quote["status"] = "ACCEPTED"
    helpers.touch(quote)
    job["accepted_quote_id"] = quote["id"]
    job["lifecycle_status"] = "SOLD"
    helpers.touch(job)

    # pay-cash
    job["financing_status"] = "CASH"
    helpers.touch(job)

    install_order = factory.create_install_order(
        job["id"], job["accepted_quote_id"],
        helpers.iso_from_dt(clock.now()),
        helpers.iso_from_dt(helpers.add_days(clock.now(), 1)),
    )
    job["install_order_id"] = install_order["id"]
    job["lifecycle_status"] = "SCHEDULED"
    helpers.touch(job)

    out = {
        "job_id": job["id"],
        "quote_id": quote["id"],
        "install_order_id": install_order["id"],
        "job_version": job["version"],
    }
    return object_response(out, status=201)


@bp.route("/_seed/warranted-job", methods=["POST"])
def seed_warranted_job():
    """Provision a Job to lifecycle WARRANTED with COMPLETED InstallOrder and ACTIVE
    Warranty held by the given homeowner. (SCAFFOLD §1.5 / PRD §3.12)"""
    _uid, role = authenticate()
    authorize(role, ["WarrantyAdmin"])
    body = get_json_body()
    helpers.require_fields(body, ["homeowner_id"])
    homeowner_id = body["homeowner_id"]
    helpers.fk_or_422(db.homeowners, homeowner_id, "Homeowner")

    job = factory.create_job(homeowner_id, "Seeded Property", "CRAWLSPACE", 800)

    inspection = factory.create_inspection(job["id"], 50.0, 0, False)
    inspection["status"] = "FINALIZED"
    inspection["severity"] = calculations.compute_severity(50.0, 0, False)
    helpers.touch(inspection)
    job["assessment_severity"] = inspection["severity"]
    job["lifecycle_status"] = "INSPECTED"
    helpers.touch(job)

    scope = {
        "includes_vapor_barrier": False,
        "includes_sump": True,
        "includes_dehumidifier": False,
        "includes_drain": False,
        "includes_battery_backup": False,
    }
    quote = factory.create_quote(job["id"], job["footprint_sqft"], scope, 0, "NONE", revision=1)
    quote["status"] = "SENT"
    quote["expires_at"] = helpers.iso_from_dt(helpers.add_days(helpers.parse_iso(quote["created_at"]), 30))
    helpers.touch(quote)
    job["lifecycle_status"] = "QUOTED"
    helpers.touch(job)

    quote["status"] = "ACCEPTED"
    helpers.touch(quote)
    job["accepted_quote_id"] = quote["id"]
    job["lifecycle_status"] = "SOLD"
    helpers.touch(job)

    job["financing_status"] = "CASH"
    helpers.touch(job)

    install_order = factory.create_install_order(
        job["id"], job["accepted_quote_id"],
        helpers.iso_from_dt(clock.now()),
        helpers.iso_from_dt(helpers.add_days(clock.now(), 1)),
    )
    job["install_order_id"] = install_order["id"]
    job["lifecycle_status"] = "SCHEDULED"
    helpers.touch(job)

    # dispatch -> start -> pass -> complete
    install_order["status"] = "COMPLETED"
    final_total, variance = calculations.reconcile_install(
        job["footprint_sqft"], quote, install_order["actual_drain_linear_ft"]
    )
    install_order["final_total_cents"] = final_total
    install_order["variance_cents"] = variance
    helpers.touch(install_order)
    job["lifecycle_status"] = "INSTALLED"
    helpers.touch(job)

    # issue warranty
    next_due = helpers.iso_from_dt(helpers.add_years(clock.now(), 1))
    warranty = factory.create_warranty(
        job["id"], install_order["id"], job["homeowner_id"], 25, next_due
    )
    job["lifecycle_status"] = "WARRANTED"
    helpers.touch(job)

    out = {
        "job_id": job["id"],
        "warranty_id": warranty["id"],
        "install_order_id": install_order["id"],
    }
    return object_response(out, status=201)
