"""Compatibility rules: prior-load restriction data (PRD 3.2)."""
from flask import Blueprint, request

from authz import ALL_ROLES, FLEET_ADMIN, require_roles
from calc import find_rule
from db import store
from errors import err
from respond import success
from serialize import ser_compat_rule
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, opt_bool, paginate,
    reject_unknown, req_enum, sorted_by_creation,
)
from routes.products import COMPATIBILITY_GROUPS

bp = Blueprint("compat_rules", __name__)

WASH_LEVELS_WITH_NONE = ("NONE", "FLUSH", "DETERGENT_WASH", "CHEMICAL_KOSHER")


@bp.route("/compatibility-rules", methods=["POST"])
def create_rule():
    require_roles([FLEET_ADMIN])
    data = json_body()
    reject_unknown(data, {"prior_group", "next_group", "required_wash_level", "forbidden"})
    prior = req_enum(data, "prior_group", COMPATIBILITY_GROUPS)
    nxt = req_enum(data, "next_group", COMPATIBILITY_GROUPS)
    level = req_enum(data, "required_wash_level", WASH_LEVELS_WITH_NONE)
    forbidden = opt_bool(data, "forbidden", False)
    # Priority 9: the (prior_group, next_group) pair is unique.
    if find_rule(prior, nxt) is not None:
        raise err("ERR_DUPLICATE_COMPATIBILITY_RULE",
                  "A rule already exists for (%s, %s)" % (prior, nxt))
    r = {
        "id": new_id(),
        "_seq": next(store.seq),
        "prior_group": prior,
        "next_group": nxt,
        "required_wash_level": level,
        "forbidden": forbidden,
    }
    r.update(new_common_fields())
    store.compat_rules[r["id"]] = r
    return success(ser_compat_rule(r), status=201)


@bp.route("/compatibility-rules", methods=["GET"])
def list_rules():
    require_roles(ALL_ROLES)
    prior = request.args.get("prior_group")
    nxt = request.args.get("next_group")
    items = [r for r in store.compat_rules.values()
             if (prior is None or r["prior_group"] == prior)
             and (nxt is None or r["next_group"] == nxt)]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_compat_rule(r) for r in page],
                   response_type="array", pagination=pagination)


@bp.route("/compatibility-rules/<rid>", methods=["GET"])
def get_rule(rid):
    require_roles(ALL_ROLES)
    return success(ser_compat_rule(get_or_404(store.compat_rules, "compat_rules", rid)))
