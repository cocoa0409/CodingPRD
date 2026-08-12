"""Fee schedule entries: filtered list, single read, and benchmark mapping."""

from flask import Blueprint, request

import store
from bodycheck import validate_body
from envelope import ok, ok_list
from errors import ApiError
from helpers import (
    contract_of_version, get_entry, get_version, provider_of_contract,
    sorted_by_created,
)
from pricing import compute_entry_rate, resolve_benchmark
from security import (
    ALL_ROLES, INTERNAL_ROLES, ROLE_CONFIG_ANALYST,
    auth, check_ownership, require_roles,
)

bp = Blueprint("entries", __name__)

MAPPABLE_VERSION_STATES = ("DRAFT", "LOADED", "REJECTED")


@bp.get("/fee-schedule-entries")
def list_entries_filtered():
    _, role = auth()
    require_roles(role, INTERNAL_ROLES)
    version_id = request.args.get("contract_version_id")
    benchmark_id = request.args.get("medicare_benchmark_id")
    items = store.entries.values()
    if version_id is not None:
        items = [e for e in items if e["contract_version_id"] == version_id]
    if benchmark_id is not None:
        items = [e for e in items if e["medicare_benchmark_id"] == benchmark_id]
    return ok_list([dict(e) for e in sorted_by_created(items)])


@bp.get("/fee-schedule-entries/<eid>")
def get_one_entry(eid):
    user_id, role = auth()
    require_roles(role, ALL_ROLES)
    entry = get_entry(eid)
    version = get_version(entry["contract_version_id"])
    contract = contract_of_version(version)
    check_ownership(role, user_id, contract["provider_id"])
    return ok(dict(entry))


@bp.post("/fee-schedule-entries/<eid>/map-benchmark")
def map_benchmark(eid):
    validate_body({})
    _, role = auth()
    require_roles(role, [ROLE_CONFIG_ANALYST])
    entry = get_entry(eid)
    if entry["entry_status"] != "STAGED":
        raise ApiError(
            "ERR_ENTRY_INVALID_STATE", 409,
            "Only a STAGED entry can be mapped to a benchmark.",
        )
    version = get_version(entry["contract_version_id"])
    if version["version_status"] not in MAPPABLE_VERSION_STATES:
        raise ApiError(
            "ERR_VERSION_INVALID_STATE", 409,
            "Parent version state does not permit benchmark mapping.",
        )
    contract = contract_of_version(version)
    provider = provider_of_contract(contract)
    benchmark = resolve_benchmark(entry, version, provider)
    entry["medicare_benchmark_id"] = benchmark["id"]
    entry["resolved_benchmark_cents"] = benchmark["benchmark_amount_cents"]
    entry["computed_rate_cents"] = compute_entry_rate(
        entry, benchmark["benchmark_amount_cents"])
    entry["entry_status"] = "MAPPED"
    store.touch(entry)
    return ok(dict(entry))
