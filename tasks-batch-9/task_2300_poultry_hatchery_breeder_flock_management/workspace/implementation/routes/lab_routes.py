"""Laboratory testing, the biosecurity cascade and corrective actions
(PRD §3.3, §3.9)."""

from flask import Blueprint

import serializers
import services
from errors import fail
from helpers import (apply_filters, authorize, body, must_get, need_dt, need_enum,
                     need_str, ok, ok_list, pagination, paginate)
from store import store

bp = Blueprint("lab", __name__)

SUBJECT_TYPES = ("BREEDER_FLOCK", "INCUBATION_UNIT", "GROWER_FARM")
SUBJECT_TABLES = {
    "BREEDER_FLOCK": "breeder_flocks",
    "INCUBATION_UNIT": "incubation_units",
    "GROWER_FARM": "grower_farms",
}
TEST_CODES = ("SALMONELLA_PULLORUM", "MYCOPLASMA_GALLISEPTICUM", "AVIAN_INFLUENZA",
              "SHELL_HYGIENE")
LAB_READ_ROLES = ("HatcheryManager", "Veterinarian", "FlockManager")
ACTION_READ_ROLES = ("HatcheryManager", "FlockManager", "Veterinarian")


@bp.post("/lab-tests")
def create_lab_test():
    authorize(("Veterinarian",))
    data = body()

    subject_type = need_enum(data, "subject_type", SUBJECT_TYPES)
    subject_id = need_str(data, "subject_id", 1)
    test_code = need_enum(data, "test_code", TEST_CODES)
    collected_at = need_dt(data, "collected_at")

    if collected_at > store.clock:
        fail("ERR_TIMESTAMP_OUT_OF_RANGE", "collected_at may not be in the future.")

    # rank 36 — the discriminator alone decides where subject_id is looked up
    table = getattr(store, SUBJECT_TABLES[subject_type])
    if subject_id not in table:
        fail("ERR_LAB_SUBJECT_INVALID",
             "subject_id does not resolve in the discriminated table.")

    rec = store.new_record(subject_type=subject_type, subject_id=subject_id,
                           test_code=test_code, collected_at=collected_at,
                           released_at=None, result=None, status="PENDING")
    store.lab_tests[rec["id"]] = rec
    return ok(serializers.lab_test(rec), 201)


@bp.get("/lab-tests/<rid>")
def get_lab_test(rid):
    authorize(LAB_READ_ROLES)
    return ok(serializers.lab_test(must_get("lab_tests", rid)))


@bp.get("/lab-tests")
def list_lab_tests():
    authorize(LAB_READ_ROLES)
    limit, offset = pagination()
    rows = apply_filters(store.sorted_rows("lab_tests"),
                         {"subject_type": "subject_type", "subject_id": "subject_id",
                          "test_code": "test_code", "status": "status"})
    page, limit, offset, total = paginate(rows, limit, offset, serializers.lab_test)
    return ok_list(page, limit, offset, total)


@bp.post("/lab-tests/<rid>/release")
def release_lab_test(rid):
    user_id, _ = authorize(("Veterinarian",))
    test = must_get("lab_tests", rid)
    data = body()
    result = need_enum(data, "result", ("NEGATIVE", "POSITIVE", "INVALID"))

    # rank 18 — release is one-shot and terminal
    if test["status"] != "PENDING":
        fail("ERR_LAB_TEST_ALREADY_RELEASED", "The test has already been released.")

    test["result"] = result
    test["status"] = result
    test["released_at"] = store.clock
    store.touch(test)

    if result == "POSITIVE":
        if test["subject_type"] == "INCUBATION_UNIT":
            unit = store.incubation_units.get(test["subject_id"])
            if unit is not None:
                unit["sanitation_status"] = "DIRTY"
                store.touch(unit)
        elif test["subject_type"] == "GROWER_FARM":
            farm = store.grower_farms.get(test["subject_id"])
            if farm is not None:
                farm["biosecurity_status"] = "QUARANTINED"
                store.touch(farm)
        else:
            flock = store.breeder_flocks.get(test["subject_id"])
            if flock is not None and flock["status"] == "IN_LAY":
                flock["status"] = "EGG_HOLD"
                flock["egg_hold_opened_at"] = store.clock
                flock["egg_hold_opened_by_user_id"] = user_id
                services.refresh_flock(flock)
                store.touch(flock)
                services.run_flock_egg_hold_cascade(flock)

    return ok(serializers.lab_test(test))


# ---------------------------------------------------------------------------
# Corrective actions
# ---------------------------------------------------------------------------
@bp.get("/corrective-actions/<rid>")
def get_corrective_action(rid):
    authorize(ACTION_READ_ROLES)
    return ok(serializers.corrective_action(must_get("corrective_actions", rid)))


@bp.get("/corrective-actions")
def list_corrective_actions():
    authorize(ACTION_READ_ROLES)
    limit, offset = pagination()
    rows = apply_filters(store.sorted_rows("corrective_actions"),
                         {"flock_id": "flock_id", "status": "status",
                          "trigger_reason": "trigger_reason"})
    page, limit, offset, total = paginate(rows, limit, offset,
                                         serializers.corrective_action)
    return ok_list(page, limit, offset, total)


@bp.post("/corrective-actions/<rid>/acknowledge")
def acknowledge_action(rid):
    authorize(("FlockManager",))
    action = must_get("corrective_actions", rid)
    if action["status"] != "OPEN":
        fail("ERR_CORRECTIVE_ACTION_INVALID_STATE",
             "Only an OPEN action can be acknowledged.")
    action["status"] = "ACKNOWLEDGED"
    store.touch(action)
    return ok(serializers.corrective_action(action))


@bp.post("/corrective-actions/<rid>/implement")
def implement_action(rid):
    authorize(("FlockManager",))
    action = must_get("corrective_actions", rid)
    data = body()
    note = need_str(data, "note", 1)
    if action["status"] != "ACKNOWLEDGED":
        fail("ERR_CORRECTIVE_ACTION_INVALID_STATE",
             "Only an ACKNOWLEDGED action can be implemented.")
    action["implementation_note"] = note
    action["status"] = "IMPLEMENTED"
    store.touch(action)
    return ok(serializers.corrective_action(action))


@bp.post("/corrective-actions/<rid>/verify")
def verify_action(rid):
    user_id, _ = authorize(("Veterinarian",))
    action = must_get("corrective_actions", rid)
    data = body()
    outcome = need_enum(data, "outcome", ("PASS", "FAIL"))

    # rank 9 — segregation of duties, before the state check
    if action["opened_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The principal that opened the action may not verify it.")

    # rank 19 — state
    if action["status"] != "IMPLEMENTED":
        fail("ERR_CORRECTIVE_ACTION_INVALID_STATE",
             "Only an IMPLEMENTED action can be verified.")

    if outcome == "PASS":
        action["status"] = "VERIFIED"
        store.touch(action)
        flock = store.breeder_flocks.get(action["flock_id"])
        if flock is not None:
            flock["corrective_action_count"] = max(
                0, flock["corrective_action_count"] - 1)
            services.refresh_flock(flock)
            store.touch(flock)
    else:
        action["status"] = "OPEN"
        action["verification_round"] = action["verification_round"] + 1
        action["implementation_note"] = None
        store.touch(action)

    return ok(serializers.corrective_action(action))
