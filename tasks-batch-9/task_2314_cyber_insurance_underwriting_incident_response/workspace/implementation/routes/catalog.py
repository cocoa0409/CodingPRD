"""Control catalog, response panel, logical clock and epoch processing."""

from flask import Blueprint, g

import calc
import validate
from cascades import set_application_status
from db import iso3, new_row, now_iso, round2, store, touch
from errors import bad_request
from middleware import (CLAIMS_ADJUSTER, INSURED, PANEL_ADMIN, PORTFOLIO_ACTUARY,
                        UNDERWRITER, endpoint, find_vendor)
from response import created, listing, ok
from routes.common import apply_eq, filter_bool, filter_value

bp = Blueprint("catalog", __name__, url_prefix="/cyber")


# --------------------------------------------------------------------------
# control requirements (immutable catalog -- no updated_at, no version)
# --------------------------------------------------------------------------

@bp.route("/control-requirements", methods=["POST"])
@endpoint(roles=[UNDERWRITER])
def create_control_requirement():
    payload = validate.body()
    control_key = validate.req_enum(payload, "control_key", calc.CONTROL_KEYS)
    min_level = validate.req_enum(payload, "min_level_required", calc.LEVELS)
    weight = validate.req_int(payload, "weight", 1, 100)
    is_mandatory = validate.req_bool(payload, "is_mandatory", default=False)
    grace_days = validate.opt_int(payload, "remediation_grace_days", 0, 365, default=30)
    for row in store.control_requirements.values():
        if row["control_key"] == control_key:
            raise bad_request("control_key %s already exists in the catalog" % control_key)
    row = new_row({
        "control_key": control_key,
        "is_mandatory": is_mandatory,
        "min_level_required": min_level,
        "weight": weight,
        "remediation_grace_days": grace_days,
    }, common=False)
    store.control_requirements[row["id"]] = row
    return created(row)


@bp.route("/control-requirements", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, PANEL_ADMIN, INSURED])
def list_control_requirements():
    rows = calc.catalog_rows()
    mandatory = filter_bool("is_mandatory")
    if mandatory is not None:
        rows = [row for row in rows if row["is_mandatory"] == mandatory]
    rows.sort(key=lambda row: (-row["weight"], row["control_key"]))
    return listing(rows)


# --------------------------------------------------------------------------
# panel vendors
# --------------------------------------------------------------------------

@bp.route("/panel-vendors", methods=["POST"])
@endpoint(roles=[PANEL_ADMIN])
def create_panel_vendor():
    payload = validate.body()
    row = new_row({
        "vendor_name": validate.req_str(payload, "vendor_name", 1, 160),
        "vendor_type": validate.req_enum(payload, "vendor_type", calc.VENDOR_TYPES),
        "pre_approved_hourly_rate_usd": validate.req_num(
            payload, "pre_approved_hourly_rate_usd", minimum=0, exclusive_min=True, money=True),
        "per_record_notification_rate_usd": validate.opt_num(
            payload, "per_record_notification_rate_usd", minimum=0, money=True,
            default=round2(0)),
        "specialty_sectors": validate.req_array(
            payload, "specialty_sectors", calc.INDUSTRY_CODES, non_empty=True),
        "tier": validate.req_int(payload, "tier", 1, 3),
        "capacity_concurrent_engagements": validate.req_int(
            payload, "capacity_concurrent_engagements", 1, 20),
        "status": validate.opt_enum(payload, "status", calc.VENDOR_STATES, default="ACTIVE"),
        "active_engagement_count": 0,
    })
    row["pre_approved_hourly_rate_usd"] = round2(row["pre_approved_hourly_rate_usd"])
    row["per_record_notification_rate_usd"] = round2(row["per_record_notification_rate_usd"])
    store.panel_vendors[row["id"]] = row
    return created(row)


@bp.route("/panel-vendors/<vendor_id>", methods=["PATCH"])
@endpoint(roles=[PANEL_ADMIN])
def amend_panel_vendor(vendor_id):
    vendor = find_vendor(vendor_id)
    payload = validate.body()
    if validate.present(payload, "status"):
        vendor["status"] = validate.req_enum(payload, "status", calc.VENDOR_STATES)
    if validate.present(payload, "pre_approved_hourly_rate_usd"):
        vendor["pre_approved_hourly_rate_usd"] = round2(validate.req_num(
            payload, "pre_approved_hourly_rate_usd", minimum=0, exclusive_min=True, money=True))
    if validate.present(payload, "per_record_notification_rate_usd"):
        vendor["per_record_notification_rate_usd"] = round2(validate.req_num(
            payload, "per_record_notification_rate_usd", minimum=0, money=True))
    if validate.present(payload, "specialty_sectors"):
        vendor["specialty_sectors"] = validate.req_array(
            payload, "specialty_sectors", calc.INDUSTRY_CODES, non_empty=True)
    if validate.present(payload, "tier"):
        vendor["tier"] = validate.req_int(payload, "tier", 1, 3)
    if validate.present(payload, "capacity_concurrent_engagements"):
        vendor["capacity_concurrent_engagements"] = validate.req_int(
            payload, "capacity_concurrent_engagements", 1, 20)
    touch(vendor)
    return ok(vendor)


@bp.route("/panel-vendors", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, PANEL_ADMIN, INSURED])
def list_panel_vendors():
    rows = list(store.panel_vendors.values())
    rows = apply_eq(rows, "vendor_type", filter_value("vendor_type", calc.VENDOR_TYPES))
    rows = apply_eq(rows, "status", filter_value("status", calc.VENDOR_STATES))
    rows.sort(key=calc.panel_rank_key)
    return listing(rows)


@bp.route("/panel-vendors/<vendor_id>", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, PANEL_ADMIN, INSURED])
def read_panel_vendor(vendor_id):
    return ok(find_vendor(vendor_id))


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(anonymous=True)
def set_clock():
    payload = validate.body()
    raw, parsed = validate.req_dt(payload, "current_utc")
    store.clock = parsed
    store.clock_raw = raw
    return ok({"current_utc": store.clock_raw})


# --------------------------------------------------------------------------
# epoch processing
# --------------------------------------------------------------------------

@bp.route("/_ops/run-epoch", methods=["POST"])
@endpoint(roles=[UNDERWRITER, PORTFOLIO_ACTUARY])
def run_epoch():
    now = store.clock
    expired_applications = 0
    expired_policies = 0
    non_renewed_assessments = 0

    for application in calc.sorted_by_created(list(store.applications.values())):
        if application["status"] != "QUOTED":
            continue
        expires_at = application.get("_quote_expires_at")
        if expires_at is not None and now >= expires_at:
            application["premium_usd"] = None
            set_application_status(application, "EXPIRED")
            expired_applications += 1

    for policy in calc.sorted_by_created(list(store.policies.values())):
        if policy["lifecycle_status"] != "INFORCE":
            continue
        if now >= policy["_period_end"]:
            policy["lifecycle_status"] = "EXPIRED"
            touch(policy)
            expired_policies += 1

    for assessment in calc.sorted_by_created(list(store.renewal_assessments.values())):
        if assessment["status"] != "CONDITIONS_ISSUED":
            continue
        due_at = assessment.get("_remediation_due_at")
        if due_at is None or now < due_at:
            continue
        assessment["status"] = "NON_RENEWED"
        assessment["non_renewal_reason"] = "REMEDIATION_DEADLINE_MISSED"
        touch(assessment)
        policy = store.policies.get(assessment["policy_id"])
        if policy is not None:
            policy["lifecycle_status"] = "NON_RENEWED"
            touch(policy)
        non_renewed_assessments += 1

    return ok({
        "expired_application_count": expired_applications,
        "expired_policy_count": expired_policies,
        "non_renewed_assessment_count": non_renewed_assessments,
        "run_at": now_iso(),
    })
