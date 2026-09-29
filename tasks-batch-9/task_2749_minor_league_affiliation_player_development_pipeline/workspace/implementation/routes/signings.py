"""International bonus pool and signing endpoints (PRD Section 3.9)."""
from flask import Blueprint

import auth
import calc
import common
import config
import derive
import envelope
import flows
import serialize
import store
import validate
from errors import ApiError

bp = Blueprint("signings", __name__)

TRANSITIONS = {
    "APPROVE": ("SUBMITTED",),
    "REJECT": ("SUBMITTED",),
    "VOID": ("APPROVED",),
}


# ------------------------------------------------------------------- pools
@bp.post("/signing-pools")
def create_pool():
    auth.require(config.ROLE_COMPLIANCE)
    body = validate.json_body()
    season_year = validate.int_field(body, "season_year", lo=2020, hi=2040)
    base_cents = validate.int_field(body, "base_pool_cents", lo=1)
    trade_cents = validate.int_field(body, "trade_adjustment_cents", required=False,
                                    default=0)

    for other in store.pools.values():
        if other["season_year"] == season_year:
            raise ApiError("ERR_DUPLICATE_POOL_SEASON")

    record = store.base_record()
    record.update({
        "season_year": season_year,
        "base_pool_cents": base_cents,
        "trade_adjustment_cents": trade_cents,
        "forfeited_cents": 0,
        "effective_pool_cents": base_cents + trade_cents,
        "allocated_cents": 0,
        "remaining_cents": base_cents + trade_cents,
        "overage_tax_accrued_cents": 0,
        "status": "OPEN",
    })
    store.pools[record["id"]] = record
    common.commit()
    return envelope.object_response(serialize.pool(record), 201)


@bp.get("/signing-pools/<pool_id>")
def get_pool(pool_id):
    auth.require(config.ROLE_COMPLIANCE, config.ROLE_SCOUT)
    pool = common.need("pools", pool_id)
    return envelope.object_response(serialize.pool(pool))


# ---------------------------------------------------------------- signings
@bp.post("/international-signings")
def create_signing():
    auth.require(config.ROLE_SCOUT)
    body = validate.json_body()
    pool_id = validate.id_field(body, "pool_id")
    player_id = validate.id_field(body, "player_id")
    academy_id = validate.id_field(body, "academy_affiliate_id")
    bonus_cents = validate.int_field(body, "bonus_cents", lo=0)
    expected = validate.int_field(body, "expected_pool_version")

    pool = common.need("pools", pool_id)
    player = common.need("players", player_id)
    academy = common.need("affiliates", academy_id)

    if expected != pool["version"]:
        raise ApiError("ERR_STALE_POOL_VERSION")

    if player["origin"] != "INTERNATIONAL_FA" or academy["level"] != "DOMINICAN_ACADEMY":
        raise ApiError("ERR_SIGNING_ELIGIBILITY_VIOLATION")

    record = store.base_record()
    record.update({
        "pool_id": pool_id,
        "player_id": player_id,
        "academy_affiliate_id": academy_id,
        "bonus_cents": bonus_cents,
        "status": "SUBMITTED",
        "rejection_reason": None,
        "pool_charge_cents": 0,
        "overage_tax_cents": 0,
        "tier3_breach": False,
        "approved_by_user_id": None,
    })
    store.signings[record["id"]] = record
    store.touch(pool)
    common.commit()
    return envelope.object_response(serialize.signing(record), 201)


@bp.get("/international-signings")
def list_signings():
    auth.require(config.ROLE_COMPLIANCE, config.ROLE_SCOUT)
    rows = list(store.signings.values())
    rows = common.apply_filters(rows, (
        ("pool_id", "pool_id"),
        ("player_id", "player_id"),
        ("academy_affiliate_id", "academy_affiliate_id"),
        ("status", "status"),
    ))
    return envelope.paginate(rows, serialize.signing)


@bp.get("/international-signings/<signing_id>")
def get_signing(signing_id):
    auth.require(config.ROLE_COMPLIANCE, config.ROLE_SCOUT)
    signing = common.need("signings", signing_id)
    return envelope.object_response(serialize.signing(signing))


@bp.post("/international-signings/<signing_id>/disposition")
def dispose_signing(signing_id):
    user_id, role = auth.require(config.ROLE_COMPLIANCE)
    raw = auth.raw_body()
    auth.check_action_role(raw.get("action"), role, config.SIGNING_ACTION_ROLES)
    signing = common.need("signings", signing_id)
    body = validate.json_body()
    action = auth.require_action(body, config.SIGNING_ACTION_ROLES)
    validate.str_field(body, "note", required=False, default=None, allow_blank=True)

    if signing["status"] not in TRANSITIONS[action]:
        raise ApiError("ERR_INVALID_SIGNING_STATE",
                       "A signing in status %s does not accept %s."
                       % (signing["status"], action))

    pool = store.pools.get(signing["pool_id"])
    academy = store.affiliates.get(signing["academy_affiliate_id"])

    if action == "APPROVE":
        agreement = derive.active_agreement(signing["academy_affiliate_id"])
        if agreement is None:
            raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
        if agreement["posture"] == "FROZEN":
            raise ApiError("ERR_AGREEMENT_POSTURE_FROZEN")
        if agreement["posture"] == "RESTRICTED":
            raise ApiError("ERR_AGREEMENT_POSTURE_RESTRICTED")
        if pool is None or pool["status"] != "OPEN":
            raise ApiError("ERR_POOL_HARD_CAPPED")
        housed = academy["reserve_list_count"] if academy is not None else 0
        housed += sum(1 for s in derive.signings_of_academy(
            signing["academy_affiliate_id"]) if s["status"] == "APPROVED")
        if academy is not None and housed >= academy["housing_beds"]:
            raise ApiError("ERR_ACADEMY_HOUSING_FULL")

    store.touch(signing)
    if action == "APPROVE":
        result = calc.signing_charge(
            pool["base_pool_cents"], pool["trade_adjustment_cents"],
            pool["forfeited_cents"], pool["allocated_cents"],
            signing["bonus_cents"])
        signing["status"] = "APPROVED"
        signing["approved_by_user_id"] = user_id
        signing["pool_charge_cents"] = result["pool_charge_cents"]
        signing["overage_tax_cents"] = result["overage_tax_cents"]
        signing["tier3_breach"] = result["tier3_breach"]
        pool["forfeited_cents"] = result["forfeited_cents"]
        derive.recompute_pool(pool)
        store.touch(pool)
        if result["hard_capped"]:
            pool["status"] = "HARD_CAPPED"
            flows.cascade_pool_hard_capped(pool, signing["id"])
    elif action == "REJECT":
        signing["status"] = "REJECTED"
        signing["rejection_reason"] = "COMPLIANCE_DENIED"
    elif action == "VOID":
        signing["status"] = "VOIDED"
        if pool is not None:
            if signing["tier3_breach"]:
                pool["forfeited_cents"] = pool["forfeited_cents"] - config.TIER3_FORFEIT_CENTS
            derive.recompute_pool(pool)
            if (pool["status"] == "HARD_CAPPED"
                    and pool["allocated_cents"] <= pool["effective_pool_cents"]):
                pool["status"] = "OPEN"
            store.touch(pool)

    common.commit()
    return envelope.object_response(serialize.signing(signing))
