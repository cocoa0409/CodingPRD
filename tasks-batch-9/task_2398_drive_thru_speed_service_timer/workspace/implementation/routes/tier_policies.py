"""Volume-tier band table (chain configuration)."""

from decimal import Decimal

from flask import Blueprint

from constants import ALL_ROLES, MERGE_BIASES, TIERS
from db import base_row, db
from errors import fail, invalid
from middleware import authenticate
from response import ok
from serialize import tier_policy as tier_policy_json
from routes.helpers import list_rows
from validation import body_or_400, opt_num, q_enum, req_enum, req_int, req_num

bp = Blueprint("tier_policies", __name__)


@bp.route("/volume-tier-policies", methods=["POST"])
def create_policy():
    authenticate(("ProgramAdmin",))
    body = body_or_400()

    tier = req_enum(body, "tier", TIERS)
    floor = req_num(body, "cars_per_hour_floor", minimum=Decimal("0"))
    ceiling = opt_num(body, "cars_per_hour_ceiling")
    relief = req_num(body, "target_relief_pct", minimum=Decimal("0"), maximum=Decimal("0.25"))
    min_oot = req_int(body, "min_oot_count", minimum=0, maximum=4)
    bias = req_enum(body, "merge_award_bias", MERGE_BIASES)

    if ceiling is not None and ceiling <= floor:
        invalid("cars_per_hour_ceiling must be greater than cars_per_hour_floor")

    for row in db.tier_policies.values():
        if row["tier"] == tier:
            fail("ERR_DUPLICATE_TIER_POLICY", "a band already exists for %s" % tier)

    row = base_row()
    row.update({
        "tier": tier,
        "cars_per_hour_floor": floor,
        "cars_per_hour_ceiling": ceiling,
        "target_relief_pct": relief,
        "min_oot_count": min_oot,
        "merge_award_bias": bias,
    })
    db.tier_policies[row["id"]] = row
    return ok(tier_policy_json(row), 201)


@bp.route("/volume-tier-policies", methods=["GET"])
def list_policies():
    authenticate(ALL_ROLES)
    return list_rows(db.tier_policies, tier_policy_json,
                     (("tier", q_enum("tier", TIERS)),))
