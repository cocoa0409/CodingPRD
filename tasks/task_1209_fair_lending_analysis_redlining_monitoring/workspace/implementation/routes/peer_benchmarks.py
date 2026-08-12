"""Peer benchmarks."""
from flask import Blueprint, request

import db
from errors import err
from middleware import (
    body, check_int, check_number, get_or_404, list_page, require_field, require_roles,
)
from response import success_list, success_obj

bp = Blueprint("peer_benchmarks", __name__)

ROLES = ("LendingDataOps", "FairLendingAnalyst", "FairLendingOfficer", "ComplianceDirector")


@bp.post("/fair-lending/peer-benchmarks")
@require_roles("LendingDataOps")
def create_benchmark():
    data = body()
    market_id = require_field(data, "market_id")
    period_start = require_field(data, "period_start")
    period_end = require_field(data, "period_end")
    rate = check_number(
        require_field(data, "peer_protected_origination_rate"),
        "peer_protected_origination_rate",
    )
    count = check_int(
        require_field(data, "peer_origination_count"), "peer_origination_count"
    )
    source = require_field(data, "source")
    get_or_404("markets", market_id, "Market")
    for b in db.STORES["benchmarks"].values():
        if b["market_id"] == market_id and b["period_start"] == period_start:
            raise err(
                "ERR_BENCHMARK_PERIOD_CONFLICT",
                "A PeerBenchmark already exists for this market_id + period_start",
            )
    rec = db.new_record(
        {
            "market_id": market_id,
            "period_start": period_start,
            "period_end": period_end,
            "peer_protected_origination_rate": rate,
            "peer_origination_count": count,
            "source": source,
        }
    )
    db.STORES["benchmarks"][rec["id"]] = rec
    return success_obj(db.public(rec), 201)


@bp.get("/fair-lending/peer-benchmarks")
@require_roles(*ROLES)
def list_benchmarks():
    page, total, limit, offset = list_page(
        "benchmarks", {"market_id": request.args.get("market_id")}
    )
    return success_list([db.public(r) for r in page], total, limit, offset)


@bp.get("/fair-lending/peer-benchmarks/<benchmarkId>")
@require_roles(*ROLES)
def get_benchmark(benchmarkId):
    rec = get_or_404("benchmarks", benchmarkId, "PeerBenchmark")
    return success_obj(db.public(rec))
