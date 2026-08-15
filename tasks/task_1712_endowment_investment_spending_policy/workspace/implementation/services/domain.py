# Shared domain helpers: record lookup, the pool posture gate, exemption rules.
from db import store
from errors import raise_err
from response import success_list
from util import is_int


def get_or_404(collection, rec_id, label):
    rec = collection.get(rec_id)
    if rec is None:
        raise_err("ERR_NOT_FOUND", f"{label} not found: {rec_id}")
    return rec


# Operations blocked while the pool is SUSPENDED (PRD section 2.6 blocked set).
SUSPENDED_BLOCKED = {
    "gift_receive",
    "valuation_create",
    "valuation_finalize",
    "valuation_supersede",
    "distribution_create",
    "distribution_propose",
    "distribution_repropose",
    "distribution_approve",
    "distribution_distribute",
    "payout_create",
    "payout_disburse",
    "manager_engage",
    "manager_report_create",
    "allocation_bulk_upsert",
    "policy_create",
    "policy_adopt",
    "fund_activate",
    "fund_redeem_corpus",
}


def pool_gate(pool, op):
    """Priority 7: pool posture gate.

    SUSPENDED blocks the listed value-moving child operations; TERMINATED
    renders the whole pool read-only (all pool-scoped mutations blocked).
    """
    if pool["pool_status"] == "TERMINATED":
        raise_err(
            "ERR_POOL_SUSPENDED",
            "Pool is TERMINATED and read-only; all mutations are rejected",
        )
    if pool["pool_status"] == "SUSPENDED" and op in SUSPENDED_BLOCKED:
        raise_err(
            "ERR_POOL_SUSPENDED",
            f"Pool is SUSPENDED; operation {op} is blocked",
        )


def pool_of_fund(fund):
    return store.pools.get(fund["pool_id"])


def pool_of_distribution(dist):
    fund = store.funds.get(dist["fund_id"])
    return store.pools.get(fund["pool_id"]) if fund else None


def fund_of_distribution(dist):
    return store.funds.get(dist["fund_id"])


def fund_of_payout(payout):
    dist = store.distributions.get(payout["distribution_id"])
    return store.funds.get(dist["fund_id"]) if dist else None


def pool_of_payout(payout):
    fund = fund_of_payout(payout)
    return store.pools.get(fund["pool_id"]) if fund else None


def pool_of_exception(exc):
    fund = store.funds.get(exc["fund_id"])
    return store.pools.get(fund["pool_id"]) if fund else None


def is_term_matured(fund, pool):
    """Term restriction lifts once current_quarter_index >= term_end_quarter_index."""
    return (
        fund["endowment_class"] == "TERM_ENDOWMENT"
        and fund["term_end_quarter_index"] is not None
        and pool["current_quarter_index"] >= fund["term_end_quarter_index"]
    )


def is_exempt(fund, pool):
    """QUASI funds and matured TERM funds are exempt from the underwater gate."""
    return fund["endowment_class"] == "QUASI_ENDOWMENT" or is_term_matured(fund, pool)


def parse_pagination():
    """limit/offset per PRD 2.3: default 10 / 0, limit in 1..100."""
    from flask import request

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise_err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def list_response(collection, filters):
    """Shared list handler: created_at-ascending sort, exact-match filters,
    limit/offset pagination envelope.

    filters: list of (query_param, record_field, kind) where kind is
    'str' or 'int'. A supplied filter that fails to parse as int simply
    matches nothing.
    """
    from flask import request

    limit, offset = parse_pagination()
    parsed = []
    for param, field, kind in filters:
        raw = request.args.get(param)
        if raw is None:
            continue
        if kind == "int":
            try:
                val = int(raw)
            except (TypeError, ValueError):
                val = ("__no_match__",)
        else:
            val = raw
        parsed.append((field, val))

    items = [
        rec
        for rec in collection.values()
        if all(rec.get(field) == val for field, val in parsed)
    ]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([_public(r) for r in page], limit, offset, total)


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def check_int_field(value):
    return is_int(value)
