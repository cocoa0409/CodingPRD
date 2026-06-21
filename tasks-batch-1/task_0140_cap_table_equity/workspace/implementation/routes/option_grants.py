"""OptionGrant routes. PRD §3.6, §3.7."""
from __future__ import annotations

from flask import Blueprint, g, request

import db
from common import (
    get_body, optional_int, pagination_params, paginate_and_sort, require_bool,
    require_datetime, require_enum, require_int, require_string, stamp_common_fields, touch,
)
from errors import (
    APIError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_TABLE_NOT_OPEN,
    ERR_WRONG_CLASS_TYPE, ERR_409A_NONCOMPLIANT, ERR_VALUATION_EXPIRED,
    ERR_SEGREGATION_OF_DUTIES, ERR_POOL_INSUFFICIENT, ERR_VALIDATION,
    ERR_GRANT_HAS_EXERCISES,
)
from middleware import require_roles
from response import created, success, list_response
from services import core

bp = Blueprint("option_grants", __name__)

# post-termination exercise window (months) used by EXPIRE. SCAFFOLD calc constants.
PTE_MONTHS = 3


@bp.post("/option-grants")
@require_roles("Administrator")
def create_option_grant():
    body = get_body()
    # existence checks left-to-right (PRD §2.7)
    cap_table_id = require_string(body, "cap_table_id")
    ct = core.get_cap_table(cap_table_id)
    option_pool_id = require_string(body, "option_pool_id")
    pool = core.get_option_pool(option_pool_id)
    shareholder_id = require_string(body, "shareholder_id")
    core.get_shareholder(shareholder_id)
    security_class_id = require_string(body, "security_class_id")
    sc = core.get_security_class(security_class_id)
    valuation_id = require_string(body, "valuation_id")
    val = core.get_valuation(valuation_id)

    share_count = require_int(body, "share_count", strict_positive=True)
    strike_price_cents = require_int(body, "strike_price_cents", strict_positive=True)
    grant_date = require_datetime(body, "grant_date")
    vesting_months = require_int(body, "vesting_months", strict_positive=True)
    cliff_months = optional_int(body, "cliff_months", default=0, min_value=0)
    if cliff_months > vesting_months:
        raise APIError(ERR_VALIDATION, "cliff_months must be <= vesting_months.", 400)
    vesting_style = body.get("vesting_style", "GRADED")
    if vesting_style not in ("GRADED", "CLIFF_ONLY"):
        raise APIError(ERR_VALIDATION, "vesting_style must be GRADED or CLIFF_ONLY.", 400)
    early_exercise_allowed = require_bool(body, "early_exercise_allowed", default=False)

    # cross-aggregate consistency (resolve to same cap table)
    for ent, label in ((pool, "OptionPool"), (sc, "SecurityClass"), (val, "Valuation")):
        if ent["cap_table_id"] != cap_table_id:
            raise APIError(ERR_NOT_FOUND, f"{label} not found.", 404)

    # --- compliance gates in PRD §3.6 prose order ---
    # 1. target class must be COMMON
    if sc["class_type"] != "COMMON":
        raise APIError(ERR_WRONG_CLASS_TYPE, "Grant target class must be COMMON.", 422)
    # 2. 409A: valuation EFFECTIVE and strike >= fmv
    if val["status"] != "EFFECTIVE" or strike_price_cents < val["fmv_per_share_cents"]:
        raise APIError(
            ERR_409A_NONCOMPLIANT,
            "Strike below FMV or valuation not EFFECTIVE.",
            422,
        )
    # 3. valuation not expired relative to grant_date (expires_at >= grant_date)
    if val["expires_at"] < grant_date:
        raise APIError(ERR_VALUATION_EXPIRED, "Valuation is expired relative to grant_date.", 422)
    # 4. table must be OPEN
    if ct["status"] != "OPEN":
        raise APIError(ERR_TABLE_NOT_OPEN, "Cap table is not OPEN.", 409)

    now = db.now_utc()
    grant = {
        "cap_table_id": cap_table_id,
        "option_pool_id": option_pool_id,
        "shareholder_id": shareholder_id,
        "security_class_id": security_class_id,
        "valuation_id": valuation_id,
        "share_count": share_count,
        "strike_price_cents": strike_price_cents,
        "grant_date": grant_date,
        "vesting_months": vesting_months,
        "cliff_months": cliff_months,
        "vesting_style": vesting_style,
        "early_exercise_allowed": early_exercise_allowed,
        "vested_shares": 0,
        "exercised_shares": 0,
        "status": "DRAFT",
        "approved_by_user_id": None,
        # internal: who drafted (for segregation of duties)
        "_created_by_user_id": getattr(g, "user_id", None),
    }
    stamp_common_fields(grant, now)
    db.option_grants[grant["id"]] = grant
    return created(core.serialize_grant(grant, now))


@bp.get("/option-grants/<cid>")
@require_roles("Administrator", "BoardApprover", "Auditor", "Stakeholder")
def get_option_grant(cid):
    grant = core.get_option_grant(cid)
    now = db.now_utc()
    return success(core.serialize_grant(grant, now))


@bp.get("/option-grants")
@require_roles("Administrator", "BoardApprover", "Auditor", "Stakeholder")
def list_option_grants():
    limit, offset = pagination_params()
    items = list(db.option_grants.values())
    for key in ("cap_table_id", "option_pool_id", "shareholder_id", "security_class_id", "valuation_id"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i[key] == val]
    # Stakeholder reads scoped to own holdings (PRD §2.1)
    if g.user_role == "Stakeholder":
        items = [i for i in items if i["shareholder_id"] == g.user_id]
    page, total = paginate_and_sort(items, limit, offset)
    now = db.now_utc()
    return list_response(
        [core.serialize_grant(i, now) for i in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.post("/option-grants/<cid>/approve")
@require_roles("BoardApprover")
def approve_option_grant(cid):
    grant = core.get_option_grant(cid)
    ct = core.get_cap_table(grant["cap_table_id"])
    pool = core.get_option_pool(grant["option_pool_id"])
    val = core.get_valuation(grant["valuation_id"])

    # state: must be DRAFT (priority 4)
    if grant["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, "Grant must be DRAFT to approve.", 409)
    # table must be OPEN
    if ct["status"] != "OPEN":
        raise APIError(ERR_TABLE_NOT_OPEN, "Cap table is not OPEN.", 409)
    # segregation of duties (priority 5)
    if grant.get("_created_by_user_id") is not None and g.user_id == grant["_created_by_user_id"]:
        raise APIError(
            ERR_SEGREGATION_OF_DUTIES,
            "Approver must differ from the drafter (segregation of duties).",
            403,
        )
    # 409A re-check (priority 6)
    if val["status"] != "EFFECTIVE" or grant["strike_price_cents"] < val["fmv_per_share_cents"]:
        raise APIError(ERR_409A_NONCOMPLIANT, "Strike below FMV or valuation not EFFECTIVE.", 422)
    # pool sufficiency (priority 13)
    core.refresh_pool_totals(pool)
    if pool["available_shares"] < grant["share_count"]:
        raise APIError(ERR_POOL_INSUFFICIENT, "Pool has insufficient available shares.", 422)

    now = db.now_utc()
    grant["status"] = "ACTIVE"
    grant["approved_by_user_id"] = g.user_id
    touch(grant, now)
    # cascade: pool allocation rises, may flip ACTIVE -> EXHAUSTED
    _bump_pool_after_alloc(pool, now)
    core.recompute_ledger(ct, now, bump=True)
    return success(core.serialize_grant(grant, now))


def _bump_pool_after_alloc(pool, now):
    """Recompute totals, flip status, bump pool version (allocation is a mutation)."""
    core.refresh_pool_totals(pool)
    core.maybe_flip_pool_status(pool)
    touch(pool, now)


@bp.post("/option-grants/<cid>/cancel")
@require_roles("Administrator")
def cancel_option_grant(cid):
    grant = core.get_option_grant(cid)
    ct = core.get_cap_table(grant["cap_table_id"])
    now = db.now_utc()

    if grant["status"] == "DRAFT":
        grant["status"] = "CANCELLED"
        touch(grant, now)
        return success(core.serialize_grant(grant, now))

    if grant["status"] == "ACTIVE":
        if grant["exercised_shares"] != 0:
            raise APIError(ERR_GRANT_HAS_EXERCISES, "Grant has exercised shares.", 409)
        grant["status"] = "CANCELLED"
        touch(grant, now)
        pool = core.get_option_pool(grant["option_pool_id"])
        _bump_pool_after_alloc(pool, now)
        core.recompute_ledger(ct, now, bump=True)
        return success(core.serialize_grant(grant, now))

    raise APIError(ERR_INVALID_STATE, "Grant cannot be cancelled from its current state.", 409)


@bp.post("/option-grants/<cid>/expire")
@require_roles("Administrator")
def expire_option_grant(cid):
    grant = core.get_option_grant(cid)
    ct = core.get_cap_table(grant["cap_table_id"])
    if grant["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, "Grant must be ACTIVE to expire.", 409)
    now = db.now_utc()
    months = core.whole_months_between(grant["grant_date"], now)
    if months < grant["vesting_months"] + PTE_MONTHS:
        raise APIError(
            ERR_INVALID_STATE,
            "Grant is not yet past its vesting + post-termination window.",
            409,
        )
    grant["status"] = "EXPIRED"
    touch(grant, now)
    pool = core.get_option_pool(grant["option_pool_id"])
    _bump_pool_after_alloc(pool, now)
    core.recompute_ledger(ct, now, bump=True)
    return success(core.serialize_grant(grant, now))
