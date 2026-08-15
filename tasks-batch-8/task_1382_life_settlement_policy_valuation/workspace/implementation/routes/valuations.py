"""Valuation snapshots and investor reporting (PRD §3.9)."""

from datetime import datetime, timezone

from flask import Blueprint, request

import calc
from db import stamp, store, touch
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_PERIOD,
    ERR_INVALID_STATE_TRANSITION,
    ERR_INVESTOR_NOT_ALLOCATED,
    ERR_SNAPSHOT_PERIOD_OVERLAP,
    ERR_STALE_VERSION,
    ERR_VALUATION_INPUT_STALE,
)
from middleware import (
    PORTFOLIO_READERS,
    auth,
    get_body,
    lookup,
    page_args,
    req,
    require_role,
    v_date,
    v_int,
)
from response import ok, ok_list
from serialize import ser_snapshot

bp = Blueprint("valuations", __name__)


def _sorted(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def _check_investor(uid, role, portfolio):
    if role == "Investor" and not any(
        a["investor_id"] == uid for a in portfolio["allocations"]
    ):
        raise ApiError(ERR_INVESTOR_NOT_ALLOCATED, 403, "Investor holds no allocation in this portfolio")


def _overlaps_finalized(portfolio_id, period_start, period_end, exclude_id=None):
    """Half-open [start, end) overlap against FINALIZED snapshots; adjacency allowed."""
    for snap in store.snapshots.values():
        if snap["portfolio_id"] != portfolio_id or snap["status"] != "FINALIZED":
            continue
        if exclude_id and snap["id"] == exclude_id:
            continue
        if period_start < snap["period_end"] and period_end > snap["period_start"]:
            return True
    return False


@bp.post("/api/portfolios/<pid>/valuation-snapshots")
def create_snapshot(pid):
    uid, role = auth()
    require_role(role, ["PortfolioManager"])
    body = get_body()
    period_start = v_date(req(body, "period_start"), "period_start")
    period_end = v_date(req(body, "period_end"), "period_end")
    expected_version = v_int(req(body, "expected_portfolio_version"), "expected_portfolio_version")
    portfolio = lookup(store.portfolios, pid, "Portfolio")
    if period_end <= period_start:
        raise ApiError(ERR_INVALID_PERIOD, 422, "period_end must be after period_start")
    # Every ACQUIRED case needs at least one DELIVERED unexpired LE report.
    for case in calc.portfolio_cases(pid):
        if case["status"] == "ACQUIRED" and not calc.eligible_le_reports(case["id"]):
            raise ApiError(
                ERR_VALUATION_INPUT_STALE,
                422,
                "An ACQUIRED case has no unexpired LE report",
            )
    if _overlaps_finalized(pid, period_start, period_end):
        raise ApiError(ERR_SNAPSHOT_PERIOD_OVERLAP, 409, "Window overlaps a FINALIZED snapshot")
    if expected_version != portfolio["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Portfolio version has advanced")

    for snap in store.snapshots.values():
        if snap["portfolio_id"] == pid and snap["status"] == "DRAFT":
            snap["status"] = "SUPERSEDED"
            touch(snap)

    valued = [
        c
        for c in calc.portfolio_cases(pid)
        if c["status"] in ("ACQUIRED", "MATURED", "LAPSED")
    ]
    valued.sort(key=lambda c: (c["created_at"], c["_seq"]))
    period_end_dt = datetime(
        period_end.year, period_end.month, period_end.day, tzinfo=timezone.utc
    )
    rows = []
    for case in valued:
        policy = store.policies[case["policy_id"]]
        rows.append(calc.policy_value(case, policy, portfolio, period_end_dt))
    nav = sum(r["value_cents"] for r in rows)
    mwr, twr = calc.portfolio_performance(pid, period_start, period_end, nav)

    snapshot = {
        "portfolio_id": pid,
        "period_start": period_start,
        "period_end": period_end,
        "method_used": portfolio["valuation_method"],
        "nav_cents": nav,
        "money_weighted_return_bps": mwr,
        "time_weighted_return_bps": twr,
        "policy_valuations": rows,
        "status": "DRAFT",
    }
    stamp(snapshot)
    store.snapshots[snapshot["id"]] = snapshot
    touch(portfolio)
    return ok(ser_snapshot(snapshot), 201)


@bp.get("/api/portfolios/<pid>/valuation-snapshots")
def list_snapshots(pid):
    uid, role = auth()
    require_role(role, PORTFOLIO_READERS)
    portfolio = lookup(store.portfolios, pid, "Portfolio")
    _check_investor(uid, role, portfolio)
    items = [s for s in store.snapshots.values() if s["portfolio_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    limit, offset = page_args()
    items = _sorted(items)
    page = items[offset : offset + limit]
    return ok_list([ser_snapshot(s) for s in page], len(items), limit, offset)


@bp.get("/api/valuation-snapshots/<sid>")
def get_snapshot(sid):
    uid, role = auth()
    require_role(role, PORTFOLIO_READERS)
    snapshot = lookup(store.snapshots, sid, "ValuationSnapshot")
    portfolio = store.portfolios.get(snapshot["portfolio_id"])
    if portfolio:
        _check_investor(uid, role, portfolio)
    return ok(ser_snapshot(snapshot))


@bp.post("/api/valuation-snapshots/<sid>/finalize")
def finalize_snapshot(sid):
    uid, role = auth()
    require_role(role, ["PortfolioManager"])
    get_body()
    snapshot = lookup(store.snapshots, sid, "ValuationSnapshot")
    if snapshot["status"] == "SUPERSEDED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Snapshot is SUPERSEDED")
    if snapshot["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Only a DRAFT snapshot can be finalized")
    if _overlaps_finalized(
        snapshot["portfolio_id"], snapshot["period_start"], snapshot["period_end"]
    ):
        raise ApiError(ERR_SNAPSHOT_PERIOD_OVERLAP, 409, "Window overlaps a FINALIZED snapshot")
    for snap in store.snapshots.values():
        if (
            snap["portfolio_id"] == snapshot["portfolio_id"]
            and snap["id"] != snapshot["id"]
            and snap["status"] == "FINALIZED"
        ):
            snap["status"] = "SUPERSEDED"
            touch(snap)
    snapshot["status"] = "FINALIZED"
    touch(snapshot)
    portfolio = store.portfolios[snapshot["portfolio_id"]]
    portfolio["cached_nav_cents"] = snapshot["nav_cents"]
    portfolio["nav_stale"] = False
    touch(portfolio)
    return ok(ser_snapshot(snapshot))
