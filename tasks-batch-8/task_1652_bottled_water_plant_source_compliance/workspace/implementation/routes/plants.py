"""Plant, logical clock, test-driving injection, and the daily compliance run."""
from datetime import timedelta

from flask import Blueprint

from db import store, new_resource, touch, fmt_ts, logical_date, by_creation
from errors import ApiError
from middleware import auth, ALL_ROLES
from response import ok_object
from services import (
    as_datetime,
    as_int,
    get_body,
    get_or_404,
    plant_json,
    bottle_json,
    raise_shape,
    suspend_permit,
    sweep,
    create_lab_test,
)

bp = Blueprint("plants", __name__)


@bp.post("/api/_clock/set_current_utc")
@auth(["PlantAdmin"])
def set_clock():
    body = get_body()
    dt, ok = as_datetime(body.get("to_iso8601"))
    if not ok:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 timestamp", 400)
    store.clock = dt
    # The response echoes the supplied value.
    return ok_object({"current_utc": body.get("to_iso8601")})


@bp.post("/api/_inject/bottle-wash-cycles")
@auth(["PlantAdmin"])
def inject_wash_cycles():
    body = get_body()
    bottle_id = body.get("bottle_id")
    bottle = None
    if isinstance(bottle_id, str):
        bottle = store.bottles.get(bottle_id)
    if bottle is None:
        raise ApiError("ERR_NOT_FOUND", "bottle not found", 404)
    count, ok = as_int(body.get("wash_cycle_count"))
    if not ok or count < 0:
        raise ApiError("ERR_INVALID_REQUEST", "wash_cycle_count must be a non-negative integer", 400)
    bottle["wash_cycle_count"] = count
    touch(bottle)
    return ok_object(bottle_json(bottle))


@bp.post("/api/plants")
@auth(["PlantAdmin"])
def create_plant():
    body = get_body()
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ApiError("ERR_INVALID_REQUEST", "name is required", 400)
    plant = new_resource(
        {
            "name": name,
            "compliance_posture": "GREEN",
            "ops_run_index": 0,
            "bottle_gross_pool_units": 0,
            "bottle_sanitized_pool_units": 0,
        }
    )
    store.plants[plant["id"]] = plant
    return ok_object(plant_json(plant), 201)


@bp.get("/api/plants/<plant_id>")
@auth(ALL_ROLES)
def get_plant(plant_id):
    plant = get_or_404(store.plants, plant_id, "plant")
    return ok_object(plant_json(plant))


@bp.post("/api/plants/<plant_id>/compliance-runs")
@auth(["PlantAdmin"])
def compliance_run(plant_id):
    plant = get_or_404(store.plants, plant_id, "plant")
    cur = logical_date()
    now_ts = fmt_ts(store.clock)

    permit_ids = {
        p["id"] for p in store.permits.values() if p["plant_id"] == plant_id
    }
    plant_permits = by_creation(
        [p for p in store.permits.values() if p["plant_id"] == plant_id]
    )
    plant_tests = by_creation(
        [t for t in store.lab_tests.values() if t["plant_id"] == plant_id]
    )

    # (1) Finalize RECORDED withdrawal events dated strictly before today.
    events_finalized = 0
    for e in by_creation(list(store.withdrawal_events.values())):
        if (
            e["permit_id"] in permit_ids
            and e["status"] == "RECORDED"
            and e["_date"] < cur
        ):
            e["status"] = "FINALIZED"
            e["finalized_at"] = now_ts
            touch(e)
            events_finalized += 1

    # (2) Flip lab tests SCHEDULED -> DUE / SCHEDULED|DUE -> OVERDUE.
    tests_flipped = 0
    for t in plant_tests:
        if t["status"] not in ("SCHEDULED", "DUE"):
            continue
        due = t["_due"]
        if cur > due:
            t["status"] = "OVERDUE"
            touch(t)
            tests_flipped += 1
        elif t["status"] == "SCHEDULED" and (due - cur).days <= 3:
            t["status"] = "DUE"
            touch(t)
            tests_flipped += 1

    # (3) Auto-schedule SOURCE_RAW tests for ACTIVE permits lacking an
    # upcoming one (SCHEDULED/DUE with due_date >= current date).
    tests_auto_created = 0
    for p in plant_permits:
        if p["status"] != "ACTIVE":
            continue
        covered = any(
            t["test_type"] == "SOURCE_RAW"
            and t.get("subject_permit_id") == p["id"]
            and t["status"] in ("SCHEDULED", "DUE")
            and t["_due"] >= cur
            for t in store.lab_tests.values()
        )
        if not covered:
            create_lab_test(
                plant_id, "SOURCE_RAW", "subject_permit_id", p["id"],
                cur + timedelta(days=7), "AUTO",
            )
            tests_auto_created += 1

    # (4) Suspend ACTIVE permits whose SOURCE_RAW test is OVERDUE by more
    # than 7 days (current date > due_date + 7 days).
    permits_suspended = 0
    for p in plant_permits:
        if p["status"] != "ACTIVE":
            continue
        bad = any(
            t["test_type"] == "SOURCE_RAW"
            and t.get("subject_permit_id") == p["id"]
            and t["status"] == "OVERDUE"
            and cur > t["_due"] + timedelta(days=7)
            for t in store.lab_tests.values()
        )
        if bad and suspend_permit(p, "TEST_OVERDUE"):
            permits_suspended += 1

    # (5) Expire permits past valid_to.
    permits_expired = 0
    for p in plant_permits:
        if p["status"] in ("ACTIVE", "SUSPENDED") and cur > p["_valid_to"]:
            p["status"] = "EXPIRED"
            touch(p)
            permits_expired += 1

    # (6) Recompute posture (and pools) synchronously.
    sweep()

    # (7) Increment ops_run_index and plant version.
    plant["ops_run_index"] += 1
    touch(plant)

    summary = {
        "ops_run_index": plant["ops_run_index"],
        "events_finalized": events_finalized,
        "tests_flipped": tests_flipped,
        "tests_auto_created": tests_auto_created,
        "permits_suspended": permits_suspended,
        "permits_expired": permits_expired,
        "posture": plant["compliance_posture"],
    }
    return ok_object(summary)
