"""Reference data: networks, Medicare benchmarks, rate parity rules, and the
test-driving logical clock."""

from flask import Blueprint, request

import store
from bodycheck import ENUM, INT, STR, DATETIME, validate_body, parse_datetime_value
from envelope import ok, ok_list
from errors import ApiError
from helpers import (
    get_benchmark, get_network, get_parity_rule, sorted_by_created,
)
from security import ALL_ROLES, ROLE_PLAN_ADMIN, auth, require_roles

bp = Blueprint("reference", __name__)

LOBS = ("COMMERCIAL_HMO", "COMMERCIAL_PPO", "MEDICARE_ADVANTAGE", "MEDICAID")


# ---------------------------------------------------------------------------
# Networks
# ---------------------------------------------------------------------------
@bp.post("/networks")
def create_network():
    data = validate_body({
        "name": (STR, True),
        "line_of_business": (ENUM(*LOBS), True),
    })
    _, role = auth()
    require_roles(role, [ROLE_PLAN_ADMIN])
    network = store.stamp_new({
        "name": data["name"],
        "line_of_business": data["line_of_business"],
        "network_status": "ACTIVE",
    })
    store.networks[network["id"]] = network
    return ok(dict(network), 201)


@bp.get("/networks")
def list_networks():
    _, role = auth()
    require_roles(role, ALL_ROLES)
    lob = request.args.get("line_of_business")
    items = store.networks.values()
    if lob is not None:
        items = [n for n in items if n["line_of_business"] == lob]
    return ok_list([dict(n) for n in sorted_by_created(items)])


@bp.get("/networks/<nid>")
def get_one_network(nid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    return ok(dict(get_network(nid)))


@bp.post("/networks/<nid>/retire")
def retire_network(nid):
    validate_body({})
    _, role = auth()
    require_roles(role, [ROLE_PLAN_ADMIN])
    network = get_network(nid)
    if network["network_status"] == "ACTIVE":
        network["network_status"] = "RETIRED"
        store.touch(network)
    return ok(dict(network))


@bp.get("/networks/<nid>/contracts")
def list_network_contracts(nid):
    _, role = auth()
    require_roles(role, ALL_ROLES[:5])
    get_network(nid)
    items = [c for c in store.contracts.values() if c["network_id"] == nid]
    return ok_list([dict(c) for c in sorted_by_created(items)])


# ---------------------------------------------------------------------------
# Medicare benchmarks
# ---------------------------------------------------------------------------
@bp.post("/medicare-benchmarks")
def create_benchmark():
    data = validate_body({
        "benchmark_year": (INT, True),
        "locality_code": (STR, True),
        "hcpcs_code": (STR, True),
        "benchmark_amount_cents": (INT, True),
    })
    _, role = auth()
    require_roles(role, [ROLE_PLAN_ADMIN])
    for b in store.benchmarks.values():
        if (b["benchmark_year"] == data["benchmark_year"]
                and b["locality_code"] == data["locality_code"]
                and b["hcpcs_code"] == data["hcpcs_code"]):
            raise ApiError(
                "ERR_DUPLICATE_BENCHMARK", 409,
                "A Medicare benchmark already exists for this (year, locality, hcpcs) triple.",
            )
    benchmark = store.stamp_new({
        "benchmark_year": data["benchmark_year"],
        "locality_code": data["locality_code"],
        "hcpcs_code": data["hcpcs_code"],
        "benchmark_amount_cents": data["benchmark_amount_cents"],
        "benchmark_status": "DRAFT",
    })
    store.benchmarks[benchmark["id"]] = benchmark
    return ok(dict(benchmark), 201)


@bp.get("/medicare-benchmarks")
def list_benchmarks():
    _, role = auth()
    require_roles(role, ALL_ROLES)
    year = request.args.get("benchmark_year")
    hcpcs = request.args.get("hcpcs_code")
    locality = request.args.get("locality_code")
    items = store.benchmarks.values()
    if year is not None:
        items = [b for b in items if str(b["benchmark_year"]) == year]
    if hcpcs is not None:
        items = [b for b in items if b["hcpcs_code"] == hcpcs]
    if locality is not None:
        items = [b for b in items if b["locality_code"] == locality]
    return ok_list([dict(b) for b in sorted_by_created(items)])


@bp.get("/medicare-benchmarks/<bid>")
def get_one_benchmark(bid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    return ok(dict(get_benchmark(bid)))


@bp.post("/medicare-benchmarks/<bid>/publish")
def publish_benchmark(bid):
    validate_body({})
    _, role = auth()
    require_roles(role, [ROLE_PLAN_ADMIN])
    benchmark = get_benchmark(bid)
    if benchmark["benchmark_status"] != "DRAFT":
        raise ApiError(
            "ERR_BENCHMARK_INVALID_STATE", 409,
            "Only a DRAFT benchmark can be published.",
        )
    benchmark["benchmark_status"] = "PUBLISHED"
    store.touch(benchmark)
    return ok(dict(benchmark))


# ---------------------------------------------------------------------------
# Rate parity rules
# ---------------------------------------------------------------------------
@bp.post("/rate-parity-rules")
def create_parity_rule():
    data = validate_body({
        "line_of_business_a": (ENUM(*LOBS), True),
        "line_of_business_b": (ENUM(*LOBS), True),
        "band_bps": (INT, True),
    })
    if data["line_of_business_a"] == data["line_of_business_b"]:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "line_of_business_a and line_of_business_b must differ.",
        )
    _, role = auth()
    require_roles(role, [ROLE_PLAN_ADMIN])
    new_pair = {data["line_of_business_a"], data["line_of_business_b"]}
    for rule in store.parity_rules.values():
        if rule["rule_status"] != "ACTIVE":
            continue
        if {rule["line_of_business_a"], rule["line_of_business_b"]} == new_pair:
            raise ApiError(
                "ERR_DUPLICATE_PARITY_RULE", 409,
                "An ACTIVE rate parity rule already exists for this unordered pair.",
            )
    rule = store.stamp_new({
        "line_of_business_a": data["line_of_business_a"],
        "line_of_business_b": data["line_of_business_b"],
        "band_bps": data["band_bps"],
        "rule_status": "ACTIVE",
    })
    store.parity_rules[rule["id"]] = rule
    return ok(dict(rule), 201)


@bp.get("/rate-parity-rules")
def list_parity_rules():
    _, role = auth()
    require_roles(role, ALL_ROLES)
    return ok_list([dict(r) for r in sorted_by_created(store.parity_rules.values())])


@bp.get("/rate-parity-rules/<rid>")
def get_one_parity_rule(rid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    return ok(dict(get_parity_rule(rid)))


# ---------------------------------------------------------------------------
# Test-driving logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    data = validate_body({"to_iso8601": (DATETIME, True)})
    _, role = auth()
    require_roles(role, [ROLE_PLAN_ADMIN])
    store.clock.set(parse_datetime_value(data["to_iso8601"], "to_iso8601"))
    return ok({}, 200)
