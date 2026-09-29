"""Breeder flock placement, photostimulation, depletion, hold release (PRD §3.2)."""

from flask import Blueprint

import calc
import serializers
import services
from errors import fail
from helpers import (apply_filters, authorize, body, must_get, need_dt, need_enum,
                     need_int, need_str, ok, ok_list, pagination, paginate, resolve_fk)
from store import store

bp = Blueprint("flocks", __name__)

FLOCK_STATUSES = ("PLACED", "IN_LAY", "EGG_HOLD", "DEPLETED")


def _latest_pullorum_test(flock_id):
    tests = [t for t in store.sorted_rows("lab_tests")
             if t["subject_type"] == "BREEDER_FLOCK"
             and t["subject_id"] == flock_id
             and t["test_code"] == "SALMONELLA_PULLORUM"]
    if not tests:
        return None
    tests.sort(key=lambda t: (t["collected_at"], t["created_at"], t["_seq"]))
    return tests[-1]


def _has_negative_pullorum(flock_id):
    for test in store.lab_tests.values():
        if (test["subject_type"] == "BREEDER_FLOCK"
                and test["subject_id"] == flock_id
                and test["test_code"] == "SALMONELLA_PULLORUM"
                and test["status"] == "NEGATIVE"):
            return True
    return False


@bp.post("/breeder-flocks")
def create_breeder_flock():
    authorize(("FlockManager",))
    data = body()

    # rank 5 — body foreign keys, in entity declaration order
    program = resolve_fk("flock_programs", data, "program_id")
    resolve_fk("breeder_flocks", data, "source_flock_id")

    # rank 6 — shape
    code = need_str(data, "code", 1, 40)
    if program is None:
        need_str(data, "program_id", 1)
    source_flock_id = data.get("source_flock_id")
    if source_flock_id is not None and not isinstance(source_flock_id, str):
        from errors import invalid_request
        invalid_request("source_flock_id must be a string.")
    breed = need_enum(data, "breed", calc.BREEDS)
    house_code = need_str(data, "house_code", 1, 20)
    hatch_date = need_dt(data, "hatch_date")
    placed_at = need_dt(data, "placed_at")
    hen_count = need_int(data, "hen_count")

    # rank 8 — semantically impossible counts
    if hen_count < 1:
        fail("ERR_NON_POSITIVE_COUNT", "hen_count must be at least 1.")

    # rank 20 — retired configuration
    if program["retired"]:
        fail("ERR_PROGRAM_RETIRED", "The flock program is retired.")

    # rank 25 — client timestamps
    if hatch_date >= placed_at:
        fail("ERR_TIMESTAMP_OUT_OF_RANGE", "hatch_date must be strictly before placed_at.")
    if placed_at > store.clock:
        fail("ERR_TIMESTAMP_OUT_OF_RANGE", "placed_at may not be in the future.")

    # rank 35 — breed agreement
    if breed != program["breed"]:
        fail("ERR_BREED_MISMATCH", "Flock breed must equal the program breed.")

    rec = store.new_record(
        code=code, program_id=program["id"],
        source_flock_id=source_flock_id if isinstance(source_flock_id, str) else None,
        breed=breed, house_code=house_code, hatch_date=hatch_date, placed_at=placed_at,
        hen_count=hen_count, status="PLACED",
        hatchability_rolling_pct=None, hatchability_fertile_pct=None,
        corrective_action_count=0, late_pull_count=0,
        egg_hold_opened_by_user_id=None, egg_hold_opened_at=None,
    )
    services.refresh_flock(rec)
    store.breeder_flocks[rec["id"]] = rec
    return ok(serializers.breeder_flock(rec), 201)


@bp.get("/breeder-flocks/<rid>")
def get_breeder_flock(rid):
    authorize(("HatcheryManager", "FlockManager", "Veterinarian"))
    rec = must_get("breeder_flocks", rid)
    return ok(serializers.breeder_flock(rec))


@bp.get("/breeder-flocks")
def list_breeder_flocks():
    authorize(("HatcheryManager", "FlockManager", "Veterinarian"))
    limit, offset = pagination()
    rows = store.sorted_rows("breeder_flocks")
    rows = apply_filters(rows, {"program_id": "program_id",
                                "source_flock_id": "source_flock_id",
                                "status": "status"})
    page, limit, offset, total = paginate(rows, limit, offset, serializers.breeder_flock)
    return ok_list(page, limit, offset, total)


@bp.post("/breeder-flocks/<rid>/start-lay")
def start_lay(rid):
    authorize(("FlockManager",))
    flock = must_get("breeder_flocks", rid)

    # rank 11 — state
    if flock["status"] != "PLACED":
        fail("ERR_FLOCK_INVALID_STATE", "The flock is not in PLACED.")

    program = store.flock_programs.get(flock["program_id"])

    # rank 20 — retired program
    if program is not None and program["retired"]:
        fail("ERR_PROGRAM_RETIRED", "The flock program is retired.")

    # rank 21 — salmonella clearance
    if not _has_negative_pullorum(flock["id"]):
        fail("ERR_LAB_CLEARANCE_MISSING",
             "A NEGATIVE SALMONELLA_PULLORUM test is required.")

    # rank 34 — maturity
    age_weeks = calc.age_weeks_of(flock["hatch_date"], store.clock)
    if program is not None and age_weeks < program["stimulation_week"]:
        fail("ERR_FLOCK_NOT_MATURE", "The flock is not old enough to photostimulate.")

    flock["status"] = "IN_LAY"
    services.refresh_flock(flock)
    store.touch(flock)
    return ok(serializers.breeder_flock(flock))


@bp.post("/breeder-flocks/<rid>/deplete")
def deplete(rid):
    authorize(("FlockManager",))
    flock = must_get("breeder_flocks", rid)

    if flock["status"] not in ("PLACED", "IN_LAY"):
        fail("ERR_FLOCK_INVALID_STATE", "The flock cannot be depleted from its state.")
    if flock["status"] == "IN_LAY":
        for lot in store.egg_lots.values():
            if lot["flock_id"] == flock["id"] and lot["status"] == "ALLOCATED":
                fail("ERR_FLOCK_INVALID_STATE",
                     "An egg lot of the flock is still ALLOCATED.")

    flock["status"] = "DEPLETED"
    services.refresh_flock(flock)
    store.touch(flock)
    return ok(serializers.breeder_flock(flock))


@bp.post("/breeder-flocks/<rid>/release-hold")
def release_hold(rid):
    user_id, _ = authorize(("Veterinarian",))
    flock = must_get("breeder_flocks", rid)

    # rank 9 — segregation of duties, before the state check
    if flock["egg_hold_opened_by_user_id"] is not None \
            and flock["egg_hold_opened_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The principal that opened the hold may not release it.")

    # rank 11 — state
    if flock["status"] != "EGG_HOLD":
        fail("ERR_FLOCK_INVALID_STATE", "The flock is not on EGG_HOLD.")

    # rank 21 — the most recently collected pullorum test must be NEGATIVE
    latest = _latest_pullorum_test(flock["id"])
    if latest is None or latest["status"] != "NEGATIVE":
        fail("ERR_LAB_CLEARANCE_MISSING",
             "The latest SALMONELLA_PULLORUM test is not NEGATIVE.")

    flock["status"] = "IN_LAY"
    flock["egg_hold_opened_at"] = None
    flock["egg_hold_opened_by_user_id"] = None
    services.refresh_flock(flock)
    store.touch(flock)
    return ok(serializers.breeder_flock(flock))


@bp.post("/breeder-flocks/<rid>/recompute-forecast")
def recompute_forecast(rid):
    authorize(("FlockManager",))
    flock = must_get("breeder_flocks", rid)
    services.refresh_flock(flock)
    store.touch(flock)
    return ok(serializers.breeder_flock(flock))
