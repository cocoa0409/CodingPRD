from flask import Blueprint

from constants import ALL_ROLES
from db import store, stamp_new, bump, pub
from errors import raise_err
from middleware import authenticate
from response import success
from services import calc
from services.domain import get_or_404, list_response, pool_gate
from services.pipeline import run_quarter_close, rollback_supersede
from util import new_id, parse_body, req_str, req_int

bp = Blueprint("valuations", __name__)


def _eligible_managers(pool, quarter_index):
    """Managers owing a report for the quarter: coverage contains the quarter
    and status is neither PROSPECT nor DECLINED."""
    out = []
    for m in store.managers.values():
        if m["pool_id"] != pool["id"]:
            continue
        if m["engagement_status"] in ("PROSPECT", "DECLINED"):
            continue
        if m["coverage_start_quarter"] > quarter_index:
            continue
        end = m["coverage_end_quarter"]
        if end is not None and end < quarter_index:
            continue
        out.append(m)
    return out


@bp.route("/endowment/valuations", methods=["POST"])
def create_valuation():
    user_id, _ = authenticate(["InvestmentOfficer"])
    body = parse_body(required=True)
    pool_id = req_str(body, "pool_id")
    estimated = req_int(body, "estimated_pool_market_value_cents", minv=0)

    pool = get_or_404(store.pools, pool_id, "EndowmentPool")
    pool_gate(pool, "valuation_create")

    open_quarter = pool["current_quarter_index"] + 1
    conflict = any(
        v["pool_id"] == pool["id"]
        and v["quarter_index"] == open_quarter
        and v["valuation_status"] in ("PRELIMINARY", "FINAL")
        for v in store.valuations.values()
    )
    if conflict:
        raise_err(
            "ERR_VALUATION_OUT_OF_ORDER",
            "A PRELIMINARY or FINAL valuation already exists for the open quarter",
        )

    rec = {
        "id": new_id(),
        "pool_id": pool_id,
        "quarter_index": open_quarter,
        "valuation_status": "PRELIMINARY",
        "estimated_pool_market_value_cents": estimated,
        "final_pool_market_value_cents": None,
        "preliminary_unit_price_millicents": calc.preliminary_price(
            estimated, pool["total_units_outstanding_micro"]
        ),
        "final_unit_price_millicents": None,
        "created_by_user_id": user_id,
        "finalized_by_user_id": None,
        "supersedes_valuation_id": None,
        "version": 1,
    }
    stamp_new(rec)
    store.valuations[rec["id"]] = rec
    return success(pub(rec), status=201)


@bp.route("/endowment/valuations", methods=["GET"])
def list_valuations():
    authenticate(ALL_ROLES)
    return list_response(
        store.valuations,
        [
            ("pool_id", "pool_id", "str"),
            ("valuation_status", "valuation_status", "str"),
            ("supersedes_valuation_id", "supersedes_valuation_id", "str"),
        ],
    )


@bp.route("/endowment/valuations/<valuation_id>", methods=["GET"])
def get_valuation(valuation_id):
    authenticate(ALL_ROLES)
    return success(pub(get_or_404(store.valuations, valuation_id, "UnitValuation")))


@bp.route("/endowment/valuations/<valuation_id>/finalize", methods=["POST"])
def finalize_valuation(valuation_id):
    user_id, _ = authenticate(["InvestmentOfficer"])
    body = parse_body(required=True)
    final_mv = req_int(body, "final_pool_market_value_cents", minv=0)
    expected = req_int(body, "expected_pool_version")

    valuation = get_or_404(store.valuations, valuation_id, "UnitValuation")
    if valuation["valuation_status"] != "PRELIMINARY":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot finalize a valuation in state {valuation['valuation_status']}",
        )
    pool = store.pools.get(valuation["pool_id"])
    pool_gate(pool, "valuation_finalize")
    if expected != pool["version"]:
        raise_err(
            "ERR_STALE_POOL_VERSION",
            "expected_pool_version does not match the pool's current version",
        )

    q = valuation["quarter_index"]

    # Allocation targets must sum to exactly 10000.
    total_target = sum(
        a["target_pct_bps"]
        for a in store.allocations.values()
        if a["pool_id"] == pool["id"]
    )
    if total_target != 10000:
        raise_err(
            "ERR_ALLOCATION_SUM_INVALID",
            "Pool allocation targets must sum to exactly 10000 bps",
        )

    # Every coverage-eligible manager must have filed this quarter's report.
    eligible = _eligible_managers(pool, q)
    reports = []
    for m in eligible:
        rep = next(
            (
                r
                for r in store.manager_reports.values()
                if r["manager_id"] == m["id"] and r["quarter_index"] == q
            ),
            None,
        )
        if rep is None:
            raise_err(
                "ERR_MANAGER_REPORT_MISSING",
                f"Manager {m['id']} has not filed a report for quarter {q}",
            )
        reports.append(rep)

    # The supplied final value must reconcile with the manager reports.
    if final_mv != sum(r["ending_mv_cents"] for r in reports):
        raise_err(
            "ERR_POOL_MV_MISMATCH",
            "final_pool_market_value_cents differs from the sum of the "
            "quarter's manager ending market values",
        )

    run_quarter_close(pool, valuation, final_mv, user_id)
    return success(pub(valuation))


@bp.route("/endowment/valuations/<valuation_id>/supersede", methods=["POST"])
def supersede_valuation(valuation_id):
    user_id, _ = authenticate(["InvestmentOfficer"])
    body = parse_body(required=True)
    revised = req_int(body, "revised_pool_market_value_cents", minv=0)
    expected = req_int(body, "expected_pool_version")

    valuation = get_or_404(store.valuations, valuation_id, "UnitValuation")
    if valuation["valuation_status"] != "FINAL":
        raise_err(
            "ERR_INVALID_STATE_TRANSITION",
            f"Cannot supersede a valuation in state {valuation['valuation_status']}",
        )
    pool = store.pools.get(valuation["pool_id"])
    pool_gate(pool, "valuation_supersede")
    if expected != pool["version"]:
        raise_err(
            "ERR_STALE_POOL_VERSION",
            "expected_pool_version does not match the pool's current version",
        )

    q = valuation["quarter_index"]
    if q != pool["current_quarter_index"]:
        raise_err(
            "ERR_VALUATION_OUT_OF_ORDER",
            "Only the latest finalized quarter may be restated",
        )

    # Consumption lock.
    pool_fund_ids = {
        f["id"] for f in store.funds.values() if f["pool_id"] == pool["id"]
    }
    for g in store.gifts.values():
        if g["fund_id"] not in pool_fund_ids:
            continue
        if g.get("unitized_quarter_index") == q:
            raise_err(
                "ERR_VALUATION_LOCKED",
                "A gift has already unitized in this quarter",
            )
        if g.get("source_payout_id") and g.get("received_quarter_index") == q:
            raise_err(
                "ERR_VALUATION_LOCKED",
                "A payout was swept in this quarter",
            )
    for m in store.managers.values():
        if m["pool_id"] != pool["id"]:
            continue
        if any(
            r["manager_id"] == m["id"] and r["quarter_index"] == q
            for r in store.manager_reports.values()
        ):
            raise_err(
                "ERR_VALUATION_LOCKED",
                "A manager report exists for this quarter",
            )
    for d in store.distributions.values():
        if d["fund_id"] not in pool_fund_ids:
            continue
        if d["distribution_status"] == "DISTRIBUTED" and (
            d.get("_distributed_epoch") is not None and d["_distributed_epoch"] >= q
        ):
            raise_err(
                "ERR_VALUATION_LOCKED",
                "A distribution was distributed after this finalize",
            )

    valuation["valuation_status"] = "SUPERSEDED"
    bump(valuation)
    rollback_supersede(pool, valuation)

    corrective = {
        "id": new_id(),
        "pool_id": pool["id"],
        "quarter_index": q,
        "valuation_status": "PRELIMINARY",
        "estimated_pool_market_value_cents": revised,
        "final_pool_market_value_cents": None,
        "preliminary_unit_price_millicents": calc.preliminary_price(
            revised, pool["total_units_outstanding_micro"]
        ),
        "final_unit_price_millicents": None,
        "created_by_user_id": user_id,
        "finalized_by_user_id": None,
        "supersedes_valuation_id": valuation["id"],
        "version": 1,
    }
    stamp_new(corrective)
    store.valuations[corrective["id"]] = corrective
    bump(pool)
    return success(pub(corrective), status=201)
