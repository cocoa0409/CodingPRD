"""Voc Rehab plan service: create, approve, start, suspend, resume, complete."""
from __future__ import annotations

from decimal import Decimal

from ..calculations import VOC_REHAB_BASE, voc_rehab_subsistence
from ..clock import Clock
from ..errors import ApiError
from ..store import Store
from ..util import new_id

VALID_TRAINING_MODE = set(VOC_REHAB_BASE.keys())


def _now_iso(store: Store) -> str:
    return Clock.format(store.clock.now())


def _bump_version(store: Store, entity: dict) -> None:
    entity["updated_at"] = _now_iso(store)
    entity["version"] = entity["version"] + 1


def create_plan(store: Store, body: dict) -> dict:
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_BODY", "request body must be a JSON object")
    veteran_id = body.get("veteran_id")
    training_mode = body.get("training_mode")
    if not isinstance(veteran_id, str):
        raise ApiError("ERR_INVALID_BODY", "veteran_id required")
    if veteran_id not in store.veterans:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "veteran_id does not resolve")
    if training_mode not in VALID_TRAINING_MODE:
        raise ApiError("ERR_INVALID_BODY", "invalid training_mode")

    now = _now_iso(store)
    pid = new_id()
    plan = {
        "id": pid,
        "veteran_id": veteran_id,
        "training_mode": training_mode,
        "counselor_id": None,
        "status": "DRAFT",
        "suspension_count": 0,
        "monthly_subsistence": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.voc_rehab_plans[pid] = plan
    return plan


def approve_plan(store: Store, pid: str, *, counselor_id: str) -> dict:
    p = store.voc_rehab_plans.get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "voc rehab plan not found")
    if p["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "plan not in DRAFT")

    veteran = store.veterans[p["veteran_id"]]
    if veteran["combined_rating"] < 20:
        raise ApiError(
            "ERR_CROSS_ENTITY_PRECONDITION",
            "veteran combined_rating must be >= 20",
        )
    if veteran["discharge_status"] != "HONORABLE":
        raise ApiError("ERR_INELIGIBLE_DISCHARGE", "veteran discharge status not HONORABLE")

    active_count = sum(
        1
        for d in store.dependents.values()
        if d["veteran_id"] == veteran["id"] and d["status"] == "ACTIVE"
    )
    subsistence = voc_rehab_subsistence(p["training_mode"], active_count)

    p["status"] = "APPROVED"
    p["counselor_id"] = counselor_id
    p["monthly_subsistence"] = subsistence
    _bump_version(store, p)
    return p


def start_plan(store: Store, pid: str) -> dict:
    p = store.voc_rehab_plans.get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "voc rehab plan not found")
    if p["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "plan not in APPROVED")
    p["status"] = "ACTIVE"
    _bump_version(store, p)
    return p


def suspend_plan(store: Store, pid: str) -> dict:
    p = store.voc_rehab_plans.get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "voc rehab plan not found")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "plan not in ACTIVE")

    p["status"] = "SUSPENDED"
    p["suspension_count"] = p["suspension_count"] + 1
    _bump_version(store, p)

    if p["suspension_count"] >= 3:
        # Auto-terminate.
        p["status"] = "TERMINATED"
        _bump_version(store, p)

    return p


def resume_plan(store: Store, pid: str, *, counselor_id: str) -> dict:
    p = store.voc_rehab_plans.get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "voc rehab plan not found")
    if p["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "plan not in SUSPENDED")
    if p["suspension_count"] >= 3:
        raise ApiError("ERR_INVALID_STATE", "plan suspension_count >= 3")
    if p.get("counselor_id") and p["counselor_id"] == counselor_id:
        raise ApiError("ERR_SEGREGATION_VIOLATION", "resume counselor must differ from approver")

    p["status"] = "ACTIVE"
    _bump_version(store, p)
    return p


def complete_plan(store: Store, pid: str) -> dict:
    p = store.voc_rehab_plans.get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", "voc rehab plan not found")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "plan not in ACTIVE")
    p["status"] = "COMPLETED"
    _bump_version(store, p)
    return p


def auto_suspend_active_plans_for_veteran(store: Store, veteran_id: str) -> None:
    """Cascade from Claim.reopen — auto-suspend each ACTIVE plan of a veteran."""
    for p in store.voc_rehab_plans.values():
        if p["veteran_id"] != veteran_id or p["status"] != "ACTIVE":
            continue
        p["status"] = "SUSPENDED"
        p["suspension_count"] = p["suspension_count"] + 1
        _bump_version(store, p)
        if p["suspension_count"] >= 3:
            p["status"] = "TERMINATED"
            _bump_version(store, p)
