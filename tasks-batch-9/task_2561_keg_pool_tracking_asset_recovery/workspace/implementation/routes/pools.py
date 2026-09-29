"""Pools, fleet import, keg reads, the dwell read and the replenishment sweep."""
from flask import Blueprint

import clock
import db
import middleware
import response
import util
from errors import fail
from services import calc, recompute, view

bp = Blueprint("pools", __name__)

ALL_ROLES = ("PoolOperator", "Brewer", "Distributor", "ServiceTechnician",
             "AssetRecoveryAnalyst")
SIZE_LITERS = (20, 30, 50, 58)
SEEDABLE_CUSTODY_STATES = ("IN_FLOAT", "IN_SERVICE", "QUARANTINED")
CUSTODY_STATES = ("IN_FLOAT", "ISSUED_TO_BREWER", "FILLED", "IN_TRADE",
                  "AT_RETAIL", "IN_SERVICE", "QUARANTINED", "EVIDENCE_HOLD",
                  "LOST", "STOLEN", "SCRAPPED")
SERVICE_STATES = ("SERVICE_OK", "SERVICE_DUE", "SERVICE_OVERDUE",
                  "SERVICE_FAILED")
DWELL_FLAGS = ("WITHIN_LIMIT", "APPROACHING", "OVERDUE")
REGION_PATTERN = r"^[A-Z]{2}$"


# --------------------------------------------------------------- pools -------


@bp.post("/pools")
def create_pool():
    middleware.authenticate("PoolOperator")
    payload = util.body()
    util.forbid_version_fields(payload)
    pool_code = util.req_string(payload, "pool_code", 3, 16)
    size_liters = util.req_int(payload, "size_liters")
    if size_liters not in SIZE_LITERS:
        util.bad("size_liters", "must be one of 20, 30, 50, 58")
    weight = util.req_number(payload, "stainless_weight_kg", minimum=0,
                             maximum=60, max_decimals=2)
    replacement = util.req_int(payload, "replacement_cost_cents", minimum=1)
    region_code = util.req_string(payload, "region_code", 2, 2,
                                  pattern=REGION_PATTERN)
    restrict = util.opt_int(payload, "restrict_threshold_pct", minimum=0,
                            maximum=100, default=25)
    freeze = util.opt_int(payload, "freeze_threshold_pct", minimum=0,
                          maximum=100, default=10)
    max_per_order = util.opt_int(payload, "restricted_max_kegs_per_order",
                                 minimum=1, default=2)
    if freeze >= restrict:
        util.bad("freeze_threshold_pct",
                 "must be strictly less than restrict_threshold_pct")
    for row in db.pools.values():
        if row["pool_code"] == pool_code:
            fail("ERR_DUPLICATE_POOL_CODE",
                 "pool_code %s is already in use." % pool_code)
    pool = util.common_fields()
    pool.update({
        "pool_code": pool_code,
        "size_liters": size_liters,
        "stainless_weight_kg": weight,
        "replacement_cost_cents": replacement,
        "region_code": region_code,
        "restrict_threshold_pct": restrict,
        "freeze_threshold_pct": freeze,
        "restricted_max_kegs_per_order": max_per_order,
        "kegs_total": 0,
        "kegs_available": 0,
        "kegs_circulating": 0,
        "kegs_servicing": 0,
        "kegs_held": 0,
        "kegs_written_off": 0,
        "available_pct": 0.00,
        "posture": "FROZEN",
    })
    db.pools[pool["id"]] = pool
    return response.created(pool)


@bp.get("/pools/<pool_id>")
def read_pool(pool_id):
    middleware.authenticate(*ALL_ROLES)
    pool = db.pools.get(pool_id)
    if pool is None:
        fail("ERR_POOL_NOT_FOUND")
    return response.ok(pool)


# ---------------------------------------------------------- fleet import -----


@bp.post("/pools/<pool_id>/kegs")
def import_keg(pool_id):
    middleware.authenticate("PoolOperator")
    payload = util.body()
    util.forbid_version_fields(payload)
    asset_tag = util.req_string(payload, "asset_tag", 3, 24)
    initial_state = util.opt_enum(payload, "initial_custody_state",
                                  SEEDABLE_CUSTODY_STATES, default="IN_FLOAT")
    fill_count = util.opt_int(payload, "fill_count", minimum=0, default=0)
    fills_at_test = util.opt_int(payload, "fills_at_last_pressure_test",
                                 minimum=0, default=0)
    last_test_raw = payload.get("last_pressure_test_at")
    last_test_at = None
    if last_test_raw is not None:
        last_test_at = util.parse_instant(last_test_raw,
                                          "last_pressure_test_at")
    pool = db.pools.get(pool_id)
    if pool is None:
        fail("ERR_POOL_NOT_FOUND")
    for row in db.kegs.values():
        if row["asset_tag"] == asset_tag:
            fail("ERR_DUPLICATE_ASSET_TAG",
                 "asset_tag %s is already etched onto another keg." % asset_tag)
    keg = util.common_fields()
    if last_test_at is None:
        # PRD: "when the caller omits it the server records the new keg's own
        # `created_at`" -- the copy therefore renders exactly like `created_at`.
        last_test_at = util.MillisInstant.of(keg["created_at"])
    keg.update({
        "pool_id": pool["id"],
        "asset_tag": asset_tag,
        "custody_state": initial_state,
        "service_state": calc.derive_service_state(fill_count, fills_at_test,
                                                   last_test_at),
        "dwell_flag": "WITHIN_LIMIT",
        "fill_count": fill_count,
        "fills_at_last_pressure_test": fills_at_test,
        "last_pressure_test_at": last_test_at,
        "current_brewer_id": None,
        "current_distributor_id": None,
        "filling_brewer_id": None,
        "issuance_order_id": None,
        "theft_investigation_id": None,
        "filled_brand_code": None,
        "dwell_started_at": None,
        "distributor_custody_started_at": None,
        "cumulative_dwell_days": 0,
        "last_scanned_at": None,
        "scan_count": 0,
        "pre_hold_custody_state": None,
        "misdelivery_open": False,
        "assessment_open": False,
        "stainless_scrap_value_cents": 0,
    })
    keg["stainless_scrap_value_cents"] = calc.keg_scrap_value(keg)
    db.kegs[keg["id"]] = keg
    recompute.cascade_pool(pool)
    return response.created(view.keg_out(keg))


@bp.get("/pools/<pool_id>/kegs")
def list_pool_kegs(pool_id):
    middleware.authenticate("PoolOperator", "ServiceTechnician",
                            "AssetRecoveryAnalyst")
    limit, offset = middleware.pagination()
    pool = db.pools.get(pool_id)
    if pool is None:
        fail("ERR_POOL_NOT_FOUND")
    custody_state = middleware.qparam("custody_state")
    service_state = middleware.qparam("service_state")
    rows = [keg for keg in db.kegs.values()
            if keg["pool_id"] == pool_id
            and view.match(keg, "custody_state", custody_state)
            and view.match(keg, "service_state", service_state)]
    rows = view.ordered(rows)
    page, total = view.paginate(rows, limit, offset)
    return response.listing(view.kegs_out(page), limit, offset, total)


@bp.get("/kegs")
def list_kegs():
    middleware.authenticate(*ALL_ROLES)
    limit, offset = middleware.pagination()
    filters = {}
    for field in ("pool_id", "current_brewer_id", "current_distributor_id",
                  "filling_brewer_id", "issuance_order_id",
                  "theft_investigation_id", "custody_state", "service_state",
                  "dwell_flag"):
        filters[field] = middleware.qparam(field)
    rows = []
    for keg in db.kegs.values():
        if all(view.match(keg, field, value)
               for field, value in filters.items()):
            rows.append(keg)
    rows = view.ordered(rows)
    page, total = view.paginate(rows, limit, offset)
    return response.listing(view.kegs_out(page), limit, offset, total)


@bp.get("/kegs/<keg_id>")
def read_keg(keg_id):
    middleware.authenticate(*ALL_ROLES)
    keg = db.kegs.get(keg_id)
    if keg is None:
        fail("ERR_KEG_NOT_FOUND")
    return response.ok(view.keg_out(keg))


@bp.get("/kegs/<keg_id>/dwell")
def read_dwell(keg_id):
    middleware.authenticate("PoolOperator", "Brewer", "Distributor",
                            "AssetRecoveryAnalyst")
    keg = db.kegs.get(keg_id)
    if keg is None:
        fail("ERR_KEG_NOT_FOUND")
    flag, _days, limit_days, approaching_days = calc.classify_dwell(keg)
    return response.ok({
        "keg_id": keg["id"],
        "custody_state": keg["custody_state"],
        "brewer_spell_days": calc.brewer_spell_days(keg),
        "distributor_spell_days": calc.distributor_spell_days(keg),
        "limit_days": limit_days,
        "approaching_days": approaching_days,
        "dwell_flag": flag,
        "cumulative_dwell_days": keg["cumulative_dwell_days"],
        "dwell_started_at": keg["dwell_started_at"],
        "distributor_custody_started_at":
            keg["distributor_custody_started_at"],
    })


# ------------------------------------------------- replenishment sweep -------


@bp.post("/pools/<pool_id>/replenishment-sweep")
def replenishment_sweep(pool_id):
    middleware.authenticate("PoolOperator")
    pool = db.pools.get(pool_id)
    if pool is None:
        fail("ERR_POOL_NOT_FOUND")
    swept = 0
    approaching = 0
    overdue = 0
    for keg in recompute.kegs_of_pool(pool_id):
        which, _limit, _approaching = calc.dwell_limits(keg["custody_state"])
        changes = {}
        if which is None:
            changes["dwell_flag"] = "WITHIN_LIMIT"
        else:
            swept += 1
            flag = calc.classify_dwell(keg)[0]
            changes["dwell_flag"] = flag
            if flag == "APPROACHING":
                approaching += 1
            elif flag == "OVERDUE":
                overdue += 1
        # The sweep is the only place a keg moves SERVICE_DUE ->
        # SERVICE_OVERDUE, which happens once the certification is stale.
        if keg["service_state"] == "SERVICE_DUE" \
                and calc.certification_lapsed(keg):
            changes["service_state"] = "SERVICE_OVERDUE"
        util.apply_changes(keg, changes)
    recompute.cascade_pool(pool)
    tight = []
    suspended = []
    pending_total = 0
    for agreement in view.ordered(recompute.active_agreements_of_pool(pool_id)):
        if agreement["float_posture"] == "TIGHT":
            tight.append(agreement["id"])
        elif agreement["float_posture"] == "SUSPENDED":
            suspended.append(agreement["id"])
        pending_total += agreement["pending_replenishment_kegs"]
    return response.ok({
        "pool_id": pool["id"],
        "swept_keg_count": swept,
        "approaching_keg_count": approaching,
        "overdue_keg_count": overdue,
        "available_pct": pool["available_pct"],
        "posture": pool["posture"],
        "tight_agreement_ids": tight,
        "suspended_agreement_ids": suspended,
        "pending_replenishment_kegs_total": pending_total,
    })
