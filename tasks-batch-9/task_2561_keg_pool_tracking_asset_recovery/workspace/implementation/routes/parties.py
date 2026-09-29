"""Brewers, distributors, the stainless commodity index and the logical clock."""
from flask import Blueprint

import clock
import db
import middleware
import response
import util
from errors import fail
from services import calc, recompute, view

bp = Blueprint("parties", __name__)

BREWER_STATUSES = ("ACTIVE", "PROBATION", "SUSPENDED")
DISTRIBUTOR_STATUSES = ("ACTIVE", "SUSPENDED")
COOPERATION_TIERS = ("NONE", "BRONZE", "SILVER", "GOLD")
ALL_ROLES = ("PoolOperator", "Brewer", "Distributor", "ServiceTechnician",
             "AssetRecoveryAnalyst")

BRAND_CODE_PATTERN = r"^[A-Z0-9]{2,8}$"
REGION_PATTERN = r"^[A-Z]{2}$"


# ------------------------------------------------------------- brewers -------


@bp.post("/brewers")
def create_brewer():
    middleware.authenticate("PoolOperator")
    payload = util.body()
    util.forbid_version_fields(payload)
    name = util.req_string(payload, "name", 1, 120)
    brand_code = util.req_string(payload, "brand_code", 2, 8,
                                 pattern=BRAND_CODE_PATTERN)
    credit_limit = util.opt_int(payload, "credit_limit_cents", minimum=0,
                                default=40000)
    for row in db.brewers.values():
        if row["brand_code"] == brand_code:
            fail("ERR_DUPLICATE_BRAND_CODE",
                 "brand_code %s is already registered." % brand_code)
    brewer = util.common_fields()
    brewer.update({
        "name": name,
        "brand_code": brand_code,
        "status": "ACTIVE",
        "credit_limit_cents": credit_limit,
        "chargeback_balance_cents": 0,
        "lifetime_fill_count": 0,
        "upheld_loss_count": 0,
        "loss_rate_bp_trailing_90d": 0,
        "loss_rate_bp_lifetime": 0,
        "status_reason": None,
    })
    db.brewers[brewer["id"]] = brewer
    return response.created(brewer)


@bp.get("/brewers/<brewer_id>")
def read_brewer(brewer_id):
    middleware.authenticate(*ALL_ROLES)
    brewer = db.brewers.get(brewer_id)
    if brewer is None:
        fail("ERR_BREWER_NOT_FOUND")
    return response.ok(brewer)


@bp.get("/brewers/<brewer_id>/loss-rate")
def read_loss_rate(brewer_id):
    middleware.authenticate("PoolOperator", "Brewer", "AssetRecoveryAnalyst")
    basis = middleware.qparam("basis") or "TRAILING_90D"
    if basis not in ("TRAILING_90D", "LIFETIME"):
        fail("ERR_INVALID_REQUEST", "basis must be TRAILING_90D or LIFETIME.")
    brewer = db.brewers.get(brewer_id)
    if brewer is None:
        fail("ERR_BREWER_NOT_FOUND")
    result = calc.loss_rate(brewer, basis)
    return response.ok({
        "brewer_id": brewer["id"],
        "basis": basis,
        "loss_rate_bp": result["loss_rate_bp"],
        "upheld_loss_count": result["upheld_loss_count"],
        "fill_count": result["fill_count"],
        "window_start": result["window_start"],
        "window_end": result["window_end"],
        "basis_insufficient": result["basis_insufficient"],
    })


@bp.post("/brewers/<brewer_id>/status")
def override_brewer_status(brewer_id):
    middleware.authenticate("PoolOperator")
    payload = util.body()
    util.forbid_version_fields(payload)
    status = util.req_enum(payload, "status", BREWER_STATUSES)
    reason = util.opt_string(payload, "status_reason", 1, 500)
    brewer = db.brewers.get(brewer_id)
    if brewer is None:
        fail("ERR_BREWER_NOT_FOUND")
    brewer["status"] = status
    brewer["status_reason"] = reason
    util.bump(brewer)
    recompute.cascade_brewer(brewer)
    return response.ok(brewer)


# -------------------------------------------------------- distributors -------


@bp.post("/distributors")
def create_distributor():
    middleware.authenticate("PoolOperator")
    payload = util.body()
    util.forbid_version_fields(payload)
    name = util.req_string(payload, "name", 1, 120)
    region_code = util.req_string(payload, "region_code", 2, 2,
                                  pattern=REGION_PATTERN)
    rate = util.opt_int(payload, "return_incentive_rate_cents_per_keg",
                        minimum=0, maximum=2000, default=250)
    distributor = util.common_fields()
    distributor.update({
        "name": name,
        "region_code": region_code,
        "cooperation_tier": "NONE",
        "return_incentive_rate_cents_per_keg": rate,
        "status": "ACTIVE",
        "total_returns_count": 0,
        "on_time_returns_count": 0,
        "on_time_return_pct": 0.00,
        "incentive_accrual_cents": 0,
        "avg_dwell_days": 0.00,
        "cooperation_effective_date": None,
    })
    db.distributors[distributor["id"]] = distributor
    return response.created(distributor)


@bp.get("/distributors/<distributor_id>")
def read_distributor(distributor_id):
    middleware.authenticate(*ALL_ROLES)
    distributor = db.distributors.get(distributor_id)
    if distributor is None:
        fail("ERR_DISTRIBUTOR_NOT_FOUND")
    return response.ok(distributor)


@bp.post("/distributors/<distributor_id>/cooperation-agreement")
def cooperation_agreement(distributor_id):
    middleware.authenticate("PoolOperator")
    payload = util.body()
    util.forbid_version_fields(payload)
    tier = util.req_enum(payload, "cooperation_tier", COOPERATION_TIERS)
    effective_date = util.parse_date(
        util.req_present(payload, "effective_date"), "effective_date")
    rate = util.opt_int(payload, "return_incentive_rate_cents_per_keg",
                        minimum=0, maximum=2000)
    status = util.opt_enum(payload, "status", DISTRIBUTOR_STATUSES)
    distributor = db.distributors.get(distributor_id)
    if distributor is None:
        fail("ERR_DISTRIBUTOR_NOT_FOUND")
    distributor["cooperation_tier"] = tier
    distributor["cooperation_effective_date"] = effective_date
    if rate is not None:
        distributor["return_incentive_rate_cents_per_keg"] = rate
    if status is not None:
        distributor["status"] = status
    util.bump(distributor)
    return response.ok(distributor)


# ----------------------------------------------------- commodity index -------


@bp.post("/commodity-index")
def post_index():
    middleware.authenticate("PoolOperator")
    payload = util.body()
    util.forbid_version_fields(payload)
    effective_date = util.parse_date(
        util.req_present(payload, "effective_date"), "effective_date")
    price = util.req_int(payload, "usd_cents_per_kg", minimum=1)
    source = util.req_string(payload, "source", 2, 40)
    for row in db.commodity_index.values():
        if row["effective_date"] == effective_date:
            fail("ERR_DUPLICATE_INDEX_DATE",
                 "An index row already exists for that effective_date.")
    row = util.common_fields(versioned=False)
    row.update({"effective_date": effective_date,
                "usd_cents_per_kg": price,
                "source": source})
    db.commodity_index[row["id"]] = row
    return response.created(row)


@bp.get("/commodity-index")
def list_index():
    middleware.authenticate("PoolOperator", "Brewer", "Distributor",
                            "AssetRecoveryAnalyst")
    limit, offset = middleware.pagination()
    rows = sorted(db.commodity_index.values(),
                  key=lambda row: row["effective_date"])
    page, total = view.paginate(rows, limit, offset)
    return response.listing(page, limit, offset, total)


# ------------------------------------------------------- logical clock -------


@bp.post("/_clock/set_current_utc")
def set_clock():
    middleware.authenticate("PoolOperator")
    payload = util.body()
    util.forbid_version_fields(payload)
    target = util.parse_instant(util.req_present(payload, "to_iso8601"),
                                "to_iso8601")
    previous = clock.set_now(target)
    return response.ok({"current_utc": util.iso_instant(clock.now()),
                        "previous_utc": util.iso_instant(previous)})
