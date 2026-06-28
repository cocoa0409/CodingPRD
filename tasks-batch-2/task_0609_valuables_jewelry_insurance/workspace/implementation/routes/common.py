"""Shared route helpers: pagination, listing, ownership checks."""
from flask import request

import db
import lookups
import response
from errors import err

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def parse_pagination():
    """Read limit/offset query params, clamped to scaffold defaults."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit_v = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit_v = int(limit)
        except (TypeError, ValueError):
            limit_v = PAGINATION_DEFAULT_LIMIT
        if limit_v < PAGINATION_MIN_LIMIT:
            limit_v = PAGINATION_MIN_LIMIT
        if limit_v > PAGINATION_MAX_LIMIT:
            limit_v = PAGINATION_MAX_LIMIT
    if offset is None:
        offset_v = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset_v = int(offset)
        except (TypeError, ValueError):
            offset_v = PAGINATION_DEFAULT_OFFSET
        if offset_v < 0:
            offset_v = 0
    return limit_v, offset_v


def paginate_and_respond(records, serializer):
    """Sort by created_at asc (stable via _seq), paginate, envelope."""
    ordered = sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    limit, offset = parse_pagination()
    page = ordered[offset:offset + limit]
    return response.list_success([serializer(r) for r in page], limit, offset, total)


# ---- ownership (PRD §2.1) ----------------------------------------------
def policy_owner_id(policy):
    return policy["policyholder_id"]


def assert_policy_access(policy, user_id, role):
    """A Policyholder may only act on policies they own."""
    if role == "Policyholder" and policy["policyholder_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Policyholder does not own this policy")


def assert_appraisal_access(appraisal, user_id, role):
    if role == "Policyholder" and appraisal["policyholder_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Policyholder does not own this appraisal")


def assert_repair_order_access(repair_order, user_id, role):
    if role == "RepairShop" and repair_order["repair_shop_id"] != user_id:
        raise err("ERR_FORBIDDEN", "RepairShop does not own this repair order")
    if role == "Policyholder":
        claim = db.claims.get(repair_order["claim_id"])
        if claim is not None:
            policy = db.policies.get(claim["policy_id"])
            if policy is not None and policy["policyholder_id"] != user_id:
                raise err("ERR_FORBIDDEN", "Policyholder does not own this repair order")
