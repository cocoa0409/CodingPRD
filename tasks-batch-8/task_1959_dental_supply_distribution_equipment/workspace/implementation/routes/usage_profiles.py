"""Usage profiles and the OCC-guarded upsert (PRD sections 2.7 and 3.2)."""

from flask import Blueprint, request

import envelope
from auth import auth_and_roles, pm_owns_or_403
from calc import find_profile
from db import STORES, now
from errors import ApiError
from util import (
    base_record,
    body,
    dec,
    fk_exists,
    fmt_ts,
    get_or_404,
    paginate,
    pub,
    sorted_default,
    touch,
    v_bool,
    v_int,
    v_num,
    v_str,
)

bp = Blueprint("usage_profiles", __name__)

PROFILE_ROLES = ["DistributionAdmin", "SalesRep", "PracticeManager"]
PROFILE_PRODUCT_KINDS = {"CONSUMABLE", "REGULATED"}


@bp.put("/usage-profiles")
def upsert_usage_profile():
    uid, role = auth_and_roles(["PracticeManager", "SalesRep"])
    data = body()

    # Entity-backed ownership (rung 2) before existence (rung 3).
    if role == "PracticeManager":
        pid = data.get("practice_id")
        if pid is not None:
            pm_owns_or_403(role, uid, pid)

    # Existence (rung 3).
    fk_exists(data, "practice_id", "practices")
    fk_exists(data, "product_id", "products")

    # Request shape (rung 4).
    practice_id = v_str(data, "practice_id")
    product_id = v_str(data, "product_id")
    reorder_point = v_num(data, "reorder_point")
    target_stock_level = v_num(data, "target_stock_level")
    auto_replenish = v_bool(data, "auto_replenish_enabled", required=False, default=False)
    expected_version = v_int(data, "expected_practice_version")

    practice = STORES["practices"][practice_id]
    product = STORES["products"][product_id]

    # OCC staleness (rung 6) runs before the profile's own validity rules.
    if expected_version != practice["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_practice_version does not equal the Practice's current version",
        )

    # Profile validity: product must be CONSUMABLE or REGULATED and the target
    # must be strictly greater than the reorder point.
    if product["kind"] not in PROFILE_PRODUCT_KINDS or not (
        dec(target_stock_level) > dec(reorder_point)
    ):
        raise ApiError(
            "ERR_REORDER_TARGET_INVALID",
            422,
            "target_stock_level must exceed reorder_point and the product must be CONSUMABLE or REGULATED",
        )

    profile = find_profile(practice_id, product_id)
    if profile is None:
        profile = base_record()
        profile.update(
            {
                "practice_id": practice_id,
                "product_id": product_id,
                "reorder_point": reorder_point,
                "target_stock_level": target_stock_level,
                "auto_replenish_enabled": auto_replenish,
                "average_daily_usage": 0.0,
                "on_hand_estimate": 0.0,
                "last_evaluated_at": fmt_ts(now()),
                "_avg": dec(0),
                "_on_hand": dec(0),
                "_last_eval_dt": now(),
            }
        )
        STORES["usage_profiles"][profile["id"]] = profile
    else:
        # Supersede the configuration for the pair.
        profile["reorder_point"] = reorder_point
        profile["target_stock_level"] = target_stock_level
        profile["auto_replenish_enabled"] = auto_replenish
        touch(profile)

    # Every successful upsert advances the practice version.
    touch(practice)
    return envelope.success(pub(profile))


@bp.get("/usage-profiles/<rid>")
def get_usage_profile(rid):
    uid, role = auth_and_roles(PROFILE_ROLES)
    profile = get_or_404("usage_profiles", rid)
    pm_owns_or_403(role, uid, profile["practice_id"])
    return envelope.success(pub(profile))


@bp.get("/usage-profiles")
def list_usage_profiles():
    uid, role = auth_and_roles(PROFILE_ROLES)
    records = list(STORES["usage_profiles"].values())
    if role == "PracticeManager":
        records = [r for r in records if r["practice_id"] == uid]
    practice_id = request.args.get("practice_id")
    product_id = request.args.get("product_id")
    if practice_id is not None:
        records = [r for r in records if r["practice_id"] == practice_id]
    if product_id is not None:
        records = [r for r in records if r["product_id"] == product_id]
    records = sorted_default(records)
    page, pagination = paginate(records)
    return envelope.success([pub(r) for r in page], "array", 200, pagination)
