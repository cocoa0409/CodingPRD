"""Logical clock, ordinances and AMI schedules."""

from flask import Blueprint

import db
import middleware as mw
import response
from errors import ApiError, invalid
from services import calc, lookup, sweep

bp = Blueprint("reference", __name__)

READ_ROLES = (mw.PROGRAM_ADMINISTRATOR, mw.HOUSING_COMPLIANCE_OFFICER,
              mw.DEVELOPER, mw.FUND_AUDITOR)

DISTRICTS = ("R-2", "R-4", "C-2")
GAP_LEVEL_KEYS = ("5000", "8000", "12000")
HOUSEHOLD_SIZE_KEYS = ("1", "2", "3", "4", "5")
BEDROOM_KEYS = ("0", "1", "2", "3")
ALTERNATIVE_PATHS = ("OFFSITE", "IN_LIEU_FEE", "LAND_DEDICATION")


# --------------------------------------------------------------------------
# POST /_clock/set_current_utc
# --------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    mw.auth(*mw.ALL_ROLES)
    payload = mw.body()
    if "current_utc" not in payload or payload["current_utc"] is None:
        raise invalid("Field 'current_utc' is required.")
    parsed = db.parse_dt(payload["current_utc"]) if isinstance(payload["current_utc"], str) else None
    if parsed is None:
        raise invalid("Field 'current_utc' must be an ISO 8601 UTC timestamp.")
    return response.ok(sweep.run(parsed))


# --------------------------------------------------------------------------
# Ordinances
# --------------------------------------------------------------------------
def _validate_discount_tiers(payload):
    raw = payload.get("discount_tiers")
    if raw is None:
        raise invalid("Field 'discount_tiers' is required.")
    if not isinstance(raw, list) or not raw:
        raise invalid("Field 'discount_tiers' must be a non-empty array.")
    tiers = []
    previous = None
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise invalid("Each discount tier must be an object.")
        threshold = entry.get("min_pre_discount_cents")
        discount = entry.get("discount_bps")
        if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 0:
            raise invalid("Tier field 'min_pre_discount_cents' must be a non-negative integer.")
        if isinstance(discount, bool) or not isinstance(discount, int) or discount < 0 or discount > calc.BPS:
            raise invalid("Tier field 'discount_bps' must be an integer between 0 and 10000.")
        if index == 0 and threshold != 0:
            raise invalid("The first discount tier must have min_pre_discount_cents of exactly 0.")
        if previous is not None and threshold <= previous:
            raise invalid("Discount tiers must ascend by min_pre_discount_cents.")
        previous = threshold
        tiers.append({"min_pre_discount_cents": threshold, "discount_bps": discount})
    return tiers


@bp.route("/iz-compliance/ordinances", methods=["POST"])
def create_ordinance():
    mw.auth(mw.PROGRAM_ADMINISTRATOR)
    payload = mw.body()

    code = mw.take_str(payload, "code", min_len=1, max_len=40)
    effective_date = mw.take_date(payload, "effective_date")
    threshold = mw.take_int(payload, "min_project_units_threshold", lo=1)
    set_aside = mw.take_int_map(payload, "set_aside_bps_by_district",
                               allowed_keys=DISTRICTS, lo=1, hi=calc.BPS)
    gap_basis = mw.take_int_map(payload, "gap_basis_cents_by_level",
                                allowed_keys=GAP_LEVEL_KEYS, lo=1)
    fee_gap_level_bps = mw.take_int(payload, "fee_gap_level_bps")
    surcharge_bps = mw.take_int(payload, "surcharge_bps", lo=0, hi=calc.BPS)
    surcharge_cap_cents = mw.take_int(payload, "surcharge_cap_cents", lo=0)
    tiers = _validate_discount_tiers(payload)
    fee_due_days = mw.take_int(payload, "fee_due_days", lo=1)
    alternative_paths = mw.take_str_set(payload, "alternative_paths_allowed",
                                       ALTERNATIVE_PATHS, required=False, default=[])

    if str(fee_gap_level_bps) not in gap_basis:
        raise invalid("Field 'fee_gap_level_bps' must be a key of gap_basis_cents_by_level.")

    for existing in db.all_rows(db.ordinances):
        if existing.get("code") == code:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "An ordinance with code '%s' already exists." % code)

    row = db.insert(db.ordinances, {
        "code": code,
        "effective_date": effective_date,
        "min_project_units_threshold": threshold,
        "set_aside_bps_by_district": set_aside,
        "gap_basis_cents_by_level": gap_basis,
        "fee_gap_level_bps": fee_gap_level_bps,
        "surcharge_bps": surcharge_bps,
        "surcharge_cap_cents": surcharge_cap_cents,
        "discount_tiers": tiers,
        "fee_due_days": fee_due_days,
        "alternative_paths_allowed": alternative_paths,
        "status": "ACTIVE",
    })

    # Publishing a newer vintage supersedes every earlier ACTIVE ordinance.
    new_effective = db.parse_date(effective_date)
    for existing in db.all_rows(db.ordinances):
        if existing["id"] == row["id"] or existing.get("status") != "ACTIVE":
            continue
        prior = db.parse_date(existing.get("effective_date"))
        if prior is not None and prior < new_effective:
            existing["status"] = "SUPERSEDED"
            db.touch(existing)

    return response.created(db.public(row))


@bp.route("/iz-compliance/ordinances/<ordinance_id>", methods=["GET"])
def get_ordinance(ordinance_id):
    mw.auth(*READ_ROLES)
    return response.ok(db.public(lookup.fetch("ordinance", ordinance_id)))


@bp.route("/iz-compliance/ordinances", methods=["GET"])
def list_ordinances():
    mw.auth(*READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.filtered(db.ordinances, ("status",))
    return response.listing([db.public(r) for r in mw.page(rows, limit, offset)],
                            limit, offset, len(rows))


# --------------------------------------------------------------------------
# AMI schedules
# --------------------------------------------------------------------------
@bp.route("/iz-compliance/ami-schedules", methods=["POST"])
def create_ami_schedule():
    mw.auth(mw.PROGRAM_ADMINISTRATOR)
    payload = mw.body()

    effective_year = mw.take_int(payload, "effective_year", lo=2000, hi=2100)
    medians = mw.take_int_map(payload, "median_income_cents_by_size",
                              allowed_keys=HOUSEHOLD_SIZE_KEYS,
                              required_keys=HOUSEHOLD_SIZE_KEYS, lo=1)
    allowances = mw.take_int_map(payload, "utility_allowance_cents_by_bedrooms",
                                 allowed_keys=BEDROOM_KEYS,
                                 required_keys=BEDROOM_KEYS, lo=0)

    for existing in db.all_rows(db.ami_schedules):
        if int(existing.get("effective_year")) == effective_year:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "An AMI schedule for %s already exists." % effective_year)

    row = db.insert(db.ami_schedules, {
        "effective_year": effective_year,
        "median_income_cents_by_size": medians,
        "utility_allowance_cents_by_bedrooms": allowances,
        "status": "ACTIVE",
    })

    for existing in db.all_rows(db.ami_schedules):
        if existing["id"] == row["id"] or existing.get("status") != "ACTIVE":
            continue
        if int(existing.get("effective_year")) < effective_year:
            existing["status"] = "SUPERSEDED"
            db.touch(existing)

    return response.created(db.public(row))


@bp.route("/iz-compliance/ami-schedules/<ami_schedule_id>", methods=["GET"])
def get_ami_schedule(ami_schedule_id):
    mw.auth(*READ_ROLES)
    return response.ok(db.public(lookup.fetch("ami_schedule", ami_schedule_id)))


@bp.route("/iz-compliance/ami-schedules", methods=["GET"])
def list_ami_schedules():
    mw.auth(*READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.filtered(db.ami_schedules, ("status",))
    return response.listing([db.public(r) for r in mw.page(rows, limit, offset)],
                            limit, offset, len(rows))
