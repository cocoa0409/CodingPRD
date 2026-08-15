"""CommissionSchedule endpoints (create carries OCC on Product.version)."""
from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import auth, ADMIN_ACCT, ALL_ROLES
from response import ok
from services import (
    TIERS,
    by_seq,
    new_resource,
    ser_schedule,
    touch,
    windows_overlap_half_open,
)
from util import (
    apply_filters,
    as_bool,
    as_date_str,
    as_enum,
    as_int_range,
    get_body,
    is_date_str,
    is_int,
    req,
    respond_list,
)

bp = Blueprint("schedules", __name__)


@bp.post("/agency/products/<productId>/commission-schedules")
def create_schedule(productId):
    auth(ADMIN_ACCT)
    product = DB["products"].get(productId)
    if product is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Product not found")
    data = get_body()
    # Priority 4: optimistic concurrency on Product.version.
    ev = data.get("expected_product_version")
    if is_int(ev) and ev != product["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412, "expected_product_version does not match current version"
        )
    # Priority 6: temporal window rule — without supersede_existing, the new
    # half-open window must not intersect another ACTIVE same-tier window.
    tier_v = data.get("tier")
    eff_from = data.get("effective_from")
    eff_to = data.get("effective_to")
    supersede = data.get("supersede_existing", False)
    if (
        supersede is not True
        and tier_v in TIERS
        and is_date_str(eff_from)
        and (eff_to is None or is_date_str(eff_to))
    ):
        new_from = eff_from.strip()
        new_to = eff_to.strip() if eff_to is not None else None
        for s in by_seq(DB["schedules"].values()):
            if (
                s["product_id"] == product["id"]
                and s["tier"] == tier_v
                and s["status"] == "ACTIVE"
                and windows_overlap_half_open(
                    new_from, new_to, s["effective_from"], s["effective_to"]
                )
            ):
                raise ApiError(
                    "ERR_SCHEDULE_WINDOW_OVERLAP",
                    409,
                    "Schedule window overlaps an existing same-tier window",
                )
    # Priority 10: shape.
    tier = as_enum(req(data, "tier"), "tier", TIERS)
    commission_rate_bps = as_int_range(
        req(data, "commission_rate_bps"), "commission_rate_bps", 0, 10000
    )
    override_rate_bps = as_int_range(
        req(data, "override_rate_bps"), "override_rate_bps", 0, 10000
    )
    advance_months = as_int_range(req(data, "advance_months"), "advance_months", 1, 12)
    effective_from = as_date_str(req(data, "effective_from"), "effective_from")
    effective_to = None
    if data.get("effective_to") is not None:
        effective_to = as_date_str(data["effective_to"], "effective_to")
    supersede_existing = as_bool(data.get("supersede_existing", False), "supersede_existing")
    if not is_int(ev):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Field expected_product_version must be an integer"
        )
    # Execute. With supersede_existing the prior ACTIVE same-tier schedule is
    # retired in the same operation; the retirement itself advances the parent
    # product's version, and the creation advances it again (PRD 3.2).
    if supersede_existing:
        for s in by_seq(DB["schedules"].values()):
            if (
                s["product_id"] == product["id"]
                and s["tier"] == tier
                and s["status"] == "ACTIVE"
            ):
                s["effective_to"] = effective_from
                s["status"] = "RETIRED"
                touch(s)
                touch(product)
    schedule = new_resource({
        "product_id": product["id"],
        "tier": tier,
        "commission_rate_bps": commission_rate_bps,
        "override_rate_bps": override_rate_bps,
        "advance_months": advance_months,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "ACTIVE",
    })
    DB["schedules"][schedule["id"]] = schedule
    touch(product)
    return ok(ser_schedule(schedule), 201)


@bp.get("/agency/products/<productId>/commission-schedules")
def list_schedules(productId):
    auth(ALL_ROLES)
    product = DB["products"].get(productId)
    if product is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Product not found")
    items = [
        s for s in DB["schedules"].values() if s["product_id"] == product["id"]
    ]
    items = apply_filters(items, {"tier": "tier", "status": "status"})
    return respond_list(items, ser_schedule)


@bp.get("/agency/commission-schedules/<scheduleId>")
def get_schedule(scheduleId):
    auth(ALL_ROLES)
    s = DB["schedules"].get(scheduleId)
    if s is None:
        raise ApiError("ERR_NOT_FOUND", 404, "CommissionSchedule not found")
    return ok(ser_schedule(s))
