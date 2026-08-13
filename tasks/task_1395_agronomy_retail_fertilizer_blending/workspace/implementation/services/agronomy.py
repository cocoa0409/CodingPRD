"""Agronomy calculations: nutrient recommendation rates, formulation solver."""

from decimal import Decimal

import db
from errors import business, ERR_FORMULATION_UNSOLVABLE, ERR_VALIDATION_FAILED
from util import D, r1, r3, round_half_up

# Constants (per scaffold calculations table)
P_CRITICAL_PPM = 20
P_DRAWDOWN_PPM = 40
P_BUILD_LBS_PER_PPM = 9
P2O5_REMOVAL_LB_PER_BU = Decimal("0.37")
K_CRITICAL_PPM = 130
K_DRAWDOWN_PPM = 170
K_BUILD_LBS_PER_PPM = 4
K2O_REMOVAL_LB_PER_BU = Decimal("0.27")
N_LB_PER_BU = Decimal("1.0")
PREV_SOYBEAN_N_CREDIT = 30


def compute_recommendation_rates(soil, crop, yield_goal, rate_variant, previous_crop, manure_credit_n_lbs):
    removal_p = P2O5_REMOVAL_LB_PER_BU * D(yield_goal)
    removal_k = K2O_REMOVAL_LB_PER_BU * D(yield_goal)
    if rate_variant == "BUILD_RATE":
        p2o5 = removal_p + D(max(0, P_CRITICAL_PPM - soil["p_ppm"])) * D(P_BUILD_LBS_PER_PPM)
        k2o = removal_k + D(max(0, K_CRITICAL_PPM - soil["k_ppm"])) * D(K_BUILD_LBS_PER_PPM)
    else:  # MAINTENANCE_RATE
        p2o5 = removal_p if soil["p_ppm"] < P_DRAWDOWN_PPM else Decimal(0)
        k2o = removal_k if soil["k_ppm"] < K_DRAWDOWN_PPM else Decimal(0)
    n = N_LB_PER_BU * D(yield_goal) - D(manure_credit_n_lbs)
    if previous_crop == "SOYBEAN":
        n -= D(PREV_SOYBEAN_N_CREDIT)
    if n < 0:
        n = Decimal(0)
    return (
        int(round_half_up(n, 0)),
        int(round_half_up(p2o5, 0)),
        int(round_half_up(k2o, 0)),
    )


def _earliest(products):
    return sorted(products, key=lambda p: (p["created_at"], p["id"]))


def formulation_preview(rec, product_ids):
    """Run the blend formulation solver; returns list of lines. Raises
    ERR_FORMULATION_UNSOLVABLE / ERR_VALIDATION_FAILED / 404 as appropriate."""
    n_need = D(rec["n_lbs_per_acre"])
    p_need = D(rec["p2o5_lbs_per_acre"])
    k_need = D(rec["k2o_lbs_per_acre"])

    products = list(product_ids)  # already resolved to entities by caller

    def pct(p, key):
        return D(p[key]) / D(100)

    lines = {}  # product_id -> {"product_id", "target_rate_lbs_per_acre"}

    # 1. P-source: highest analysis_p2o5_pct > 0, tie-break earliest created
    p_candidates = [p for p in products if D(p["analysis_p2o5_pct"]) > 0]
    n_from_p = Decimal(0)
    p_rate = Decimal(0)
    p_source = None
    if p_need > 0:
        if not p_candidates:
            raise business(ERR_FORMULATION_UNSOLVABLE, 422, "No P2O5-carrying product selected")
        p_candidates.sort(key=lambda p: (-D(p["analysis_p2o5_pct"]), p["created_at"], p["id"]))
        p_source = p_candidates[0]
        p_rate = r1(p_need / pct(p_source, "analysis_p2o5_pct"))
        if p_rate > 0:
            lines[p_source["id"]] = {"product_id": p_source["id"], "target_rate_lbs_per_acre": float(p_rate)}
    if p_source is not None and p_rate > 0:
        n_from_p = r3(p_rate * pct(p_source, "analysis_n_pct"))
        if n_from_p > n_need:
            raise business(ERR_FORMULATION_UNSOLVABLE, 422, "P-source nitrogen credit exceeds nitrogen need")

    # 3. K-source: highest analysis_k2o_pct > 0, same tie-break
    k_candidates = [p for p in products if D(p["analysis_k2o_pct"]) > 0]
    n_from_k = Decimal(0)
    k_rate = Decimal(0)
    k_source = None
    if k_need > 0:
        if not k_candidates:
            raise business(ERR_FORMULATION_UNSOLVABLE, 422, "No K2O-carrying product selected")
        k_candidates.sort(key=lambda p: (-D(p["analysis_k2o_pct"]), p["created_at"], p["id"]))
        k_source = k_candidates[0]
        k_rate = r1(k_need / pct(k_source, "analysis_k2o_pct"))
        if k_rate > 0:
            if k_source["id"] in lines:
                lines[k_source["id"]]["target_rate_lbs_per_acre"] = float(
                    D(lines[k_source["id"]]["target_rate_lbs_per_acre"]) + k_rate)
            else:
                lines[k_source["id"]] = {"product_id": k_source["id"], "target_rate_lbs_per_acre": float(k_rate)}
    if k_source is not None and k_rate > 0:
        n_from_k = r3(k_rate * pct(k_source, "analysis_n_pct"))

    # 4. Remaining N from a pure N source (p2o5 == 0 and k2o == 0)
    rem_n = r3(n_need - n_from_p - n_from_k)
    if rem_n > 0:
        n_candidates = [p for p in products
                        if D(p["analysis_n_pct"]) > 0
                        and D(p["analysis_p2o5_pct"]) == 0
                        and D(p["analysis_k2o_pct"]) == 0]
        if not n_candidates:
            raise business(ERR_FORMULATION_UNSOLVABLE, 422, "No pure nitrogen source selected")
        n_candidates.sort(key=lambda p: (-D(p["analysis_n_pct"]), p["created_at"], p["id"]))
        n_source = n_candidates[0]
        n_rate = r1(rem_n / pct(n_source, "analysis_n_pct"))
        if n_rate > 0:
            if n_source["id"] in lines:
                lines[n_source["id"]]["target_rate_lbs_per_acre"] = float(
                    D(lines[n_source["id"]]["target_rate_lbs_per_acre"]) + n_rate)
            else:
                lines[n_source["id"]] = {"product_id": n_source["id"], "target_rate_lbs_per_acre": float(n_rate)}

    return list(lines.values())
