# Spending computation: applicable-policy lookup, smoothed base, and the
# full distribution amount computation (raw -> band clamp -> underwater gate).
from db import store
from errors import raise_err
from services.domain import is_exempt
from util import rhu


def applicable_policy(pool, fiscal_year):
    """Policy with the greatest effective_from_fiscal_year <= fiscal_year among
    the pool's ADOPTED or SUPERSEDED policies."""
    candidates = [
        p
        for p in store.policies.values()
        if p["pool_id"] == pool["id"]
        and p["policy_status"] in ("ADOPTED", "SUPERSEDED")
        and p["effective_from_fiscal_year"] <= fiscal_year
    ]
    if not candidates:
        raise_err(
            "ERR_NO_APPLICABLE_POLICY",
            f"No ADOPTED or SUPERSEDED policy covers fiscal year {fiscal_year}",
        )
    candidates.sort(
        key=lambda p: (p["effective_from_fiscal_year"], p["created_at"], p["_seq"])
    )
    return candidates[-1]


def _final_price_of_quarter(pool, quarter_index):
    for v in store.valuations.values():
        if (
            v["pool_id"] == pool["id"]
            and v["quarter_index"] == quarter_index
            and v["valuation_status"] == "FINAL"
        ):
            return v["final_unit_price_millicents"]
    return None


def _units_at_end(fund, quarter_index):
    """Replay the fund's ledger entries with quarter_index <= q."""
    total = 0
    for e in store.ledger.values():
        if e["fund_id"] == fund["id"] and e["quarter_index"] <= quarter_index:
            total += e["units_delta_micro"]
    return total


def smoothed_base(fund, pool, policy):
    """Average quarter-end MVs over the trailing window of finalized quarters
    in which the fund held units. Per-quarter round FIRST, average SECOND."""
    window = policy["smoothing_window_quarters"]
    current = pool["current_quarter_index"]
    start = max(1, current - window + 1)
    values = []
    for q in range(start, current + 1):
        units = _units_at_end(fund, q)
        if units <= 0:
            continue
        price = _final_price_of_quarter(pool, q)
        if price is None:
            continue
        values.append(rhu(units * price, 1000000000))
    if not values:
        return fund["market_value_cents"]
    return rhu(sum(values), len(values))


def prior_year_distribution(fund, fiscal_year):
    """final_amount_cents of the fund's DISTRIBUTED distribution for fy-1."""
    for d in store.distributions.values():
        if (
            d["fund_id"] == fund["id"]
            and d["fiscal_year"] == fiscal_year - 1
            and d["distribution_status"] == "DISTRIBUTED"
        ):
            return d["final_amount_cents"]
    return None


def approved_exception_for(fund, fiscal_year):
    for e in store.exceptions.values():
        if (
            e["fund_id"] == fund["id"]
            and e["fiscal_year"] == fiscal_year
            and e["exception_status"] == "APPROVED"
        ):
            return e
    return None


def compute_distribution(dist, fund, pool):
    """Full recomputation against current data. Returns the exception used
    (or None) so the caller can set applied_exception_id where appropriate."""
    policy = applicable_policy(pool, dist["fiscal_year"])
    dist["policy_id"] = policy["id"]

    base = smoothed_base(fund, pool, policy)
    dist["smoothed_base_cents"] = base

    raw = rhu(base * policy["spending_rate_bps"], 10000)
    dist["raw_amount_cents"] = raw

    prior = prior_year_distribution(fund, dist["fiscal_year"])
    dist["prior_year_distribution_cents"] = prior
    if prior is None:
        band_adjusted = raw
    else:
        cap = rhu(prior * (10000 + policy["band_cap_bps"]), 10000)
        floor = rhu(prior * (10000 - policy["band_floor_bps"]), 10000)
        band_adjusted = max(floor, min(raw, cap))
    dist["band_adjusted_amount_cents"] = band_adjusted

    dist["was_underwater_at_proposal"] = fund["is_underwater"]

    exc = None
    if fund["is_underwater"] and not is_exempt(fund, pool):
        exc = approved_exception_for(fund, dist["fiscal_year"])
        if exc is not None:
            dist["final_amount_cents"] = min(
                exc["approved_amount_cents"], band_adjusted
            )
        else:
            dist["final_amount_cents"] = 0
    else:
        dist["final_amount_cents"] = band_adjusted
    return exc
