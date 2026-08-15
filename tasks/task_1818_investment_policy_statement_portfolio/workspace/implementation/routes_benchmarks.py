from flask import Blueprint, request

import store as db
from auth import authorize
from envelope import obj, page
from errors import ApiError
from logic import new_common, touch, get_or_404
from serialize import benchmark_out
from validate import body, no_unknown, req_str, opt_str, pagination

bp = Blueprint("benchmarks", __name__)


@bp.post("/advisory/benchmarks")
def create_benchmark():
    authorize("ComplianceOfficer")
    b = body()
    no_unknown(b, {"name", "description"})
    name = req_str(b, "name")
    description = opt_str(b, "description", "")
    for existing in db.benchmarks.values():
        if existing["name"] == name:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Benchmark name must be unique")
    bm = new_common()
    bm.update({"name": name, "description": description, "status": "ACTIVE"})
    db.benchmarks[bm["id"]] = bm
    return obj(benchmark_out(bm), 201)


@bp.get("/advisory/benchmarks")
def list_benchmarks():
    authorize("Advisor", "ComplianceOfficer", "CommitteeMember", "CommitteeChair")
    limit, offset = pagination()
    status = request.args.get("status")
    rows = sorted(db.benchmarks.values(), key=lambda e: (e["created_dt"], e["_seq"]))
    if status is not None:
        rows = [x for x in rows if x["status"] == status]
    total = len(rows)
    return page([benchmark_out(x) for x in rows[offset:offset + limit]],
                limit, offset, total)


@bp.post("/advisory/benchmarks/<bid>/retire")
def retire_benchmark(bid):
    authorize("ComplianceOfficer")
    if request.data:
        b = body()
        no_unknown(b, set())
    bm = get_or_404(db.benchmarks, bid)
    if bm["status"] != "ACTIVE":
        raise ApiError("ERR_BENCHMARK_INVALID_STATE", 409,
                       "Benchmark retire requires ACTIVE status")
    for ips in db.ips_policies.values():
        if ips["benchmark_id"] == bid and ips["status"] == "ACTIVE":
            raise ApiError("ERR_BENCHMARK_IN_USE", 422,
                           "An ACTIVE IPS references this benchmark")
    bm["status"] = "RETIRED"
    touch(bm)
    return obj(benchmark_out(bm))
