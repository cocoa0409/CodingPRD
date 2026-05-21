"""Dependent service: creation, age check, spouse uniqueness, removal cascade."""
from __future__ import annotations

from datetime import datetime

from ..calculations import utc_age_years, voc_rehab_subsistence
from ..clock import Clock
from ..errors import ApiError
from ..store import Store
from ..util import new_id, to_utc

VALID_RELATIONSHIPS = {"SPOUSE", "CHILD", "PARENT"}


def _now_iso(store: Store) -> str:
    return Clock.format(store.clock.now())


def create_dependent(store: Store, body: dict) -> dict:
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_BODY", "request body must be a JSON object")

    veteran_id = body.get("veteran_id")
    relationship = body.get("relationship")
    dob = body.get("date_of_birth")
    school_enrolled = body.get("school_enrolled", False)

    if not isinstance(veteran_id, str) or veteran_id not in store.veterans:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "veteran_id does not resolve")
    if relationship not in VALID_RELATIONSHIPS:
        raise ApiError("ERR_INVALID_BODY", "invalid relationship")
    if not isinstance(dob, str):
        raise ApiError("ERR_INVALID_BODY", "date_of_birth required as ISO 8601 string")
    try:
        Clock.parse(dob)
    except ValueError as e:
        raise ApiError("ERR_INVALID_BODY", str(e))
    if not isinstance(school_enrolled, bool):
        raise ApiError("ERR_INVALID_BODY", "school_enrolled must be boolean")

    # CHILD age check.
    if relationship == "CHILD":
        age = utc_age_years(dob, store.clock.now())
        if age < 0:
            raise ApiError("ERR_DEPENDENT_AGE", "child date_of_birth is in the future")
        if age < 18:
            pass  # OK
        elif 18 <= age <= 23:
            if not school_enrolled:
                raise ApiError("ERR_DEPENDENT_AGE", "child 18..23 must have school_enrolled=true")
        else:
            raise ApiError("ERR_DEPENDENT_AGE", "child must be under 18 or 18..23 with school_enrolled")

    # SPOUSE uniqueness.
    if relationship == "SPOUSE":
        for d in store.dependents.values():
            if (
                d["veteran_id"] == veteran_id
                and d["relationship"] == "SPOUSE"
                and d["status"] == "ACTIVE"
            ):
                raise ApiError("ERR_DUPLICATE_SPOUSE", "veteran already has an ACTIVE spouse dependent")

    now = _now_iso(store)
    did = new_id()
    dep = {
        "id": did,
        "veteran_id": veteran_id,
        "relationship": relationship,
        "date_of_birth": dob,
        "school_enrolled": school_enrolled,
        "status": "ACTIVE",
        "removed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.dependents[did] = dep
    return dep


def update_dependent(store: Store, dep_id: str, body: dict) -> dict:
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_BODY", "request body must be a JSON object")
    d = store.dependents.get(dep_id)
    if d is None:
        raise ApiError("ERR_NOT_FOUND", "dependent not found")

    if "version" in body and body["version"] is not None:
        if body["version"] != d["version"]:
            raise ApiError("ERR_VERSION_CONFLICT", "version conflict")

    if "school_enrolled" not in body:
        raise ApiError("ERR_INVALID_BODY", "school_enrolled required")
    if not isinstance(body["school_enrolled"], bool):
        raise ApiError("ERR_INVALID_BODY", "school_enrolled must be boolean")

    d["school_enrolled"] = body["school_enrolled"]

    # Re-check age constraint if CHILD.
    if d["relationship"] == "CHILD":
        age = utc_age_years(d["date_of_birth"], store.clock.now())
        if age >= 18 and age <= 23 and not d["school_enrolled"]:
            raise ApiError("ERR_DEPENDENT_AGE", "child 18..23 requires school_enrolled=true")
        if age > 23:
            raise ApiError("ERR_DEPENDENT_AGE", "child over 23 cannot retain dependent status")

    _bump_version(store, d)
    return d


def remove_dependent(store: Store, dep_id: str) -> dict:
    d = store.dependents.get(dep_id)
    if d is None:
        raise ApiError("ERR_NOT_FOUND", "dependent not found")
    if d["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "dependent is not ACTIVE")

    now = _now_iso(store)
    d["status"] = "REMOVED"
    d["removed_at"] = now
    _bump_version(store, d)

    # Cascade: re-run voc_rehab_subsistence_compute on the veteran's ACTIVE plan.
    veteran_id = d["veteran_id"]
    active_count = sum(
        1
        for x in store.dependents.values()
        if x["veteran_id"] == veteran_id and x["status"] == "ACTIVE"
    )
    for plan in store.voc_rehab_plans.values():
        if plan["veteran_id"] == veteran_id and plan["status"] == "ACTIVE":
            new_sub = voc_rehab_subsistence(plan["training_mode"], active_count)
            if new_sub != plan.get("monthly_subsistence"):
                plan["monthly_subsistence"] = new_sub
                _bump_version(store, plan)

    return d


def _bump_version(store: Store, entity: dict) -> None:
    entity["updated_at"] = _now_iso(store)
    entity["version"] = entity["version"] + 1
