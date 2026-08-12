"""Contract versions: read, load/validate cycle, and child collections
(fee schedule entries, carve-outs, simulation batches, retro runs)."""

from flask import Blueprint

import store
from bodycheck import (
    DATE, ENUM, INT, STR, forbid_present, require_present, validate_body,
)
from envelope import ok, ok_list
from errors import ApiError
from helpers import (
    contract_of_version, get_version, provider_of_contract, sorted_by_created,
)
from pricing import SAFETY_FLOOR_BPS, carve_out_window_conflicts
from security import (
    ALL_ROLES, INTERNAL_ROLES, ROLE_CONFIG_ANALYST, ROLE_CONTRACT_LEGAL,
    auth, check_ownership, require_roles,
)

bp = Blueprint("versions", __name__)

EDITABLE_VERSION_STATES = ("DRAFT", "LOADED", "REJECTED")
BATCH_CREATABLE_VERSION_STATES = ("VALIDATED", "EFFECTIVE")
RATE_TYPES = ("PERCENT_OF_MEDICARE", "FLAT_RATE", "PER_DIEM", "CASE_RATE")
OVERRIDE_TYPES = ("FLAT_RATE", "PCT_OF_MEDICARE", "EXCLUDE")


def _version_invalid_state(action):
    return ApiError(
        "ERR_VERSION_INVALID_STATE", 409,
        f"ContractVersion state does not permit {action}.",
    )


# ---------------------------------------------------------------------------
# Version read / load / validate
# ---------------------------------------------------------------------------
@bp.get("/contract-versions/<vid>")
def get_one_version(vid):
    user_id, role = auth()
    require_roles(role, ALL_ROLES)
    version = get_version(vid)
    contract = contract_of_version(version)
    check_ownership(role, user_id, contract["provider_id"])
    return ok(dict(version))


@bp.post("/contract-versions/<vid>/load")
def load_version(vid):
    validate_body({})
    user_id, role = auth()
    require_roles(role, [ROLE_CONFIG_ANALYST])
    version = get_version(vid)
    if version["version_status"] == "DRAFT":
        version["version_status"] = "LOADED"
        store.touch(version)
        store.add_audit(version["contract_id"], "VERSION_LOADED", role, user_id,
                        "Contract version loaded.")
    elif version["version_status"] == "REJECTED":
        version["version_status"] = "DRAFT"
        store.touch(version)
        store.add_audit(version["contract_id"], "VERSION_RELOADED", role, user_id,
                        "Rejected version re-loaded to DRAFT for correction.")
    else:
        raise _version_invalid_state("load")
    return ok(dict(version))


@bp.post("/contract-versions/<vid>/validate")
def validate_version(vid):
    validate_body({})
    user_id, role = auth()
    require_roles(role, [ROLE_CONFIG_ANALYST])
    version = get_version(vid)
    if version["version_status"] != "LOADED":
        raise _version_invalid_state("validate")
    entries = [e for e in store.entries.values() if e["contract_version_id"] == vid]
    if entries and all(e["entry_status"] == "MAPPED" for e in entries):
        for entry in entries:
            entry["entry_status"] = "LOCKED"
            store.touch(entry)
        version["version_status"] = "VALIDATED"
        store.touch(version)
        store.add_audit(version["contract_id"], "VERSION_VALIDATED", role, user_id,
                        "Contract version validated; mapped entries locked.")
    else:
        version["version_status"] = "REJECTED"
        store.touch(version)
        store.add_audit(version["contract_id"], "VERSION_REJECTED", role, user_id,
                        "Contract version rejected: zero entries or unmapped entries.")
    return ok(dict(version))


# ---------------------------------------------------------------------------
# Fee schedule entries (creation and per-version listing)
# ---------------------------------------------------------------------------
@bp.post("/contract-versions/<vid>/fee-schedule-entries")
def create_entry(vid):
    data = validate_body({
        "hcpcs_code": (STR, True),
        "service_category": (STR, True),
        "rate_type": (ENUM(*RATE_TYPES), True),
        "pct_of_medicare_bps": (INT, False),
        "flat_rate_cents": (INT, False),
        "benchmark_lookup_mode": (ENUM("STRICT", "PROVISIONAL"), False),
    })
    # Conditionally required rate payload (tier 1 conformance).
    if data["rate_type"] == "PERCENT_OF_MEDICARE":
        require_present(data, "pct_of_medicare_bps")
    else:
        require_present(data, "flat_rate_cents")
    _, role = auth()
    require_roles(role, [ROLE_CONFIG_ANALYST])
    version = get_version(vid)
    if version["version_status"] not in EDITABLE_VERSION_STATES:
        raise _version_invalid_state("fee-schedule-entry creation")
    if (data["rate_type"] == "PERCENT_OF_MEDICARE"
            and data["pct_of_medicare_bps"] < SAFETY_FLOOR_BPS):
        raise ApiError(
            "ERR_RATE_BELOW_FLOOR", 422,
            "pct_of_medicare_bps below the 8000 bps regulatory floor.",
        )
    for e in store.entries.values():
        if e["contract_version_id"] == vid and e["hcpcs_code"] == data["hcpcs_code"]:
            raise ApiError(
                "ERR_DUPLICATE_SERVICE_CODE", 409,
                "hcpcs_code already present on this contract version.",
            )
    if data["rate_type"] == "PERCENT_OF_MEDICARE":
        contract = contract_of_version(version)
        provider = provider_of_contract(contract)
        resolvable = any(
            b["hcpcs_code"] == data["hcpcs_code"]
            and b["locality_code"] == provider["locality_code"]
            for b in store.benchmarks.values()
        )
        if not resolvable:
            raise ApiError(
                "ERR_BENCHMARK_UNRESOLVABLE", 422,
                "No MedicareBenchmark row exists for this hcpcs_code and provider locality.",
            )
    entry = store.stamp_new({
        "contract_version_id": vid,
        "hcpcs_code": data["hcpcs_code"],
        "service_category": data["service_category"],
        "rate_type": data["rate_type"],
        "pct_of_medicare_bps": data["pct_of_medicare_bps"],
        "flat_rate_cents": data["flat_rate_cents"],
        "benchmark_lookup_mode": data["benchmark_lookup_mode"] or "STRICT",
        "medicare_benchmark_id": None,
        "resolved_benchmark_cents": None,
        "computed_rate_cents": None,
        "entry_status": "STAGED",
    })
    store.entries[entry["id"]] = entry
    return ok(dict(entry), 201)


@bp.get("/contract-versions/<vid>/fee-schedule-entries")
def list_entries(vid):
    user_id, role = auth()
    require_roles(role, ALL_ROLES)
    version = get_version(vid)
    contract = contract_of_version(version)
    check_ownership(role, user_id, contract["provider_id"])
    items = [e for e in store.entries.values() if e["contract_version_id"] == vid]
    return ok_list([dict(e) for e in sorted_by_created(items)])


# ---------------------------------------------------------------------------
# Carve-outs (creation and per-version listing)
# ---------------------------------------------------------------------------
@bp.post("/contract-versions/<vid>/carve-outs")
def create_carve_out(vid):
    data = validate_body({
        "service_category": (STR, True),
        "override_type": (ENUM(*OVERRIDE_TYPES), True),
        "override_flat_cents": (INT, False),
        "override_pct_bps": (INT, False),
        "start_date": (DATE, True),
        "end_date": (DATE, True),
        "priority_rank": (INT, True),
    })
    # Conditionally required override payload (tier 1 conformance).
    if data["override_type"] == "FLAT_RATE":
        require_present(data, "override_flat_cents")
    elif data["override_type"] == "PCT_OF_MEDICARE":
        require_present(data, "override_pct_bps")
    else:  # EXCLUDE carries neither payload
        forbid_present(data, "override_flat_cents")
        forbid_present(data, "override_pct_bps")
    _, role = auth()
    require_roles(role, [ROLE_CONTRACT_LEGAL])
    version = get_version(vid)
    if version["version_status"] not in EDITABLE_VERSION_STATES:
        raise _version_invalid_state("carve-out creation")
    if carve_out_window_conflicts(vid, data["service_category"],
                                  data["start_date"], data["end_date"]):
        raise ApiError(
            "ERR_CARVE_OUT_WINDOW_CONFLICT", 409,
            "Carve-out window overlaps or is adjacent to an existing window "
            "for the same version and service_category.",
        )
    carve_out = store.stamp_new({
        "contract_version_id": vid,
        "service_category": data["service_category"],
        "override_type": data["override_type"],
        "override_flat_cents": data["override_flat_cents"],
        "override_pct_bps": data["override_pct_bps"],
        "start_date": data["start_date"],
        "end_date": data["end_date"],
        "priority_rank": data["priority_rank"],
    })
    store.carve_outs[carve_out["id"]] = carve_out
    return ok(dict(carve_out), 201)


@bp.get("/contract-versions/<vid>/carve-outs")
def list_carve_outs(vid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    get_version(vid)
    items = [c for c in store.carve_outs.values() if c["contract_version_id"] == vid]
    return ok_list([dict(c) for c in sorted_by_created(items)])


# ---------------------------------------------------------------------------
# Simulation batches (creation and per-version listing)
# ---------------------------------------------------------------------------
@bp.post("/contract-versions/<vid>/simulation-batches")
def create_batch(vid):
    data = validate_body({"label": (STR, True)})
    _, role = auth()
    require_roles(role, [ROLE_CONFIG_ANALYST])
    version = get_version(vid)
    if version["version_status"] not in BATCH_CREATABLE_VERSION_STATES:
        raise _version_invalid_state("simulation-batch creation")
    batch = store.stamp_new({
        "contract_version_id": vid,
        "label": data["label"],
        "batch_status": "OPEN",
        "total_claims": 0,
        "matched_claims": 0,
        "mismatched_claims": 0,
        "excluded_claims": 0,
        "pending_claims": 0,
        "total_priced_cents": 0,
    })
    store.batches[batch["id"]] = batch
    return ok(dict(batch), 201)


@bp.get("/contract-versions/<vid>/simulation-batches")
def list_batches(vid):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    get_version(vid)
    items = [b for b in store.batches.values() if b["contract_version_id"] == vid]
    return ok_list([dict(b) for b in sorted_by_created(items)])


# ---------------------------------------------------------------------------
# Retro adjustment runs (per-version listing)
# ---------------------------------------------------------------------------
@bp.get("/contract-versions/<vid>/retro-adjustment-runs")
def list_runs(vid):
    _, role = auth()
    require_roles(role, INTERNAL_ROLES)
    get_version(vid)
    items = [r for r in store.runs.values() if r["contract_version_id"] == vid]
    return ok_list([dict(r) for r in sorted_by_created(items)])
