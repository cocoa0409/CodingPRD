"""Analytics reads and the deterministic logical clock."""

from decimal import Decimal

from flask import Blueprint, request

import calc
from core import (ApiError, ROLES, authorize, body, db, dec4_str, iso3, parse_iso,
                  q4, query_dt, query_enum, req_str, respond_object, rhu4,
                  rhu_int)

bp = Blueprint("reports", __name__)

REPORT_ROLES = ("EnforcementPlanner", "EquityAnalyst")
LIVE_ADJUDICATION = calc.LIVE_ADJUDICATION
CASH_IN_SOURCES = ("DOWN_PAYMENT", "PLAN_INSTALLMENT", "DIRECT", "SERVICE_CREDIT")


def _window():
    """Half-open reporting window; window_end must be strictly later."""
    start = query_dt("window_start", error_id="ERR_INVALID_TIME_WINDOW")
    end = query_dt("window_end", error_id="ERR_INVALID_TIME_WINDOW")
    if not end > start:
        raise ApiError("ERR_INVALID_TIME_WINDOW",
                       "window_end must be strictly later than window_start.")
    return start, end


def _echo(name):
    return request.args.get(name)


@bp.get("/reports/equity-distribution")
def equity_distribution():
    authorize(*REPORT_ROLES)
    group_by = query_enum("group_by", calc.GROUP_BY_VALUES)
    start, end = _window()

    pool = []
    for encounter in db.encounters.values():
        if encounter["rider_id"] is None:
            continue
        if encounter["outcome"] == "VOIDED":
            continue
        if start <= encounter["occurred_at"] < end:
            pool.append(encounter)

    cited_ids = set()
    for citation in db.citations.values():
        if citation["adjudication_status"] in LIVE_ADJUDICATION:
            cited_ids.add(citation["encounter_id"])

    pool_count = len(pool)
    cited_count = sum(1 for e in pool if e["id"] in cited_ids)

    if pool_count == 0:
        systemwide = q4(0)
    else:
        systemwide = rhu4(cited_count, pool_count)

    buckets = {}
    for encounter in pool:
        rider = db.riders.get(encounter["rider_id"])
        if rider is None:
            continue
        key = (rider["demographic_band"] if group_by == "DEMOGRAPHIC_BAND"
               else rider["residence_geo_tract"])
        bucket = buckets.setdefault(key, {"pool": 0, "cited": 0})
        bucket["pool"] += 1
        if encounter["id"] in cited_ids:
            bucket["cited"] += 1

    groups = []
    deviation_total = Decimal("0")
    for key in sorted(buckets.keys()):
        bucket = buckets[key]
        rate = rhu4(bucket["cited"], bucket["pool"])
        deviation_total += abs(rate - systemwide)
        groups.append({
            "group_key": key,
            "encounter_pool_count": bucket["pool"],
            "citation_count": bucket["cited"],
            "citation_rate": dec4_str(rate),
            "rate_delta": dec4_str(rate - systemwide),
        })

    groups_evaluated = len(groups)
    if groups_evaluated == 0:
        disparity = q4(0)
    else:
        disparity = rhu4(deviation_total, groups_evaluated)

    return respond_object({
        "window_start": _echo("window_start"),
        "window_end": _echo("window_end"),
        "group_by": group_by,
        "groups_evaluated": groups_evaluated,
        "encounter_pool_count": pool_count,
        "citation_count": cited_count,
        "systemwide_citation_rate": dec4_str(systemwide),
        "disparity_index": dec4_str(disparity),
        "groups": groups,
    })


@bp.get("/reports/revenue-recovery")
def revenue_recovery():
    authorize(*REPORT_ROLES)
    basis = query_enum("basis", calc.BASIS_VALUES)
    start, end = _window()

    closed = [d for d in db.deployments.values()
              if d["status"] == "CLOSED" and start <= d["window_start"] < end]
    enforcement_cost = sum(d["enforcement_cost_cents"] or 0 for d in closed)
    deployments_counted = len(closed)

    if basis == "ACCRUAL":
        billed = [c for c in db.citations.values()
                  if start <= c["issued_at"] < end
                  and c["adjudication_status"] in LIVE_ADJUDICATION]
        recovered = sum(c["total_due_cents"] for c in billed)
        citations_counted = len(billed)
    else:
        rows = [p for p in db.payments.values() if start <= p["applied_at"] < end]
        recovered = (sum(p["amount_cents"] for p in rows
                         if p["source"] in CASH_IN_SOURCES)
                     - sum(p["amount_cents"] for p in rows
                           if p["source"] == "DISMISSAL_REVERSAL"))
        citations_counted = len({p["citation_id"] for p in rows})

    net = recovered - enforcement_cost
    ratio_bps = 0 if enforcement_cost == 0 else rhu_int(recovered * 10000, enforcement_cost)

    return respond_object({
        "window_start": _echo("window_start"),
        "window_end": _echo("window_end"),
        "basis": basis,
        "citations_counted": citations_counted,
        "deployments_counted": deployments_counted,
        "recovered_cents": recovered,
        "enforcement_cost_cents": enforcement_cost,
        "net_recovery_cents": net,
        "recovery_ratio_bps": ratio_bps,
    })


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize(*ROLES)
    payload = body()
    raw = req_str(payload, "to_iso8601", min_len=1)
    parsed = parse_iso(raw)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "to_iso8601 must be a UTC ISO-8601 instant.")
    db.clock = parsed
    return respond_object({"current_utc": iso3(db.clock)})
