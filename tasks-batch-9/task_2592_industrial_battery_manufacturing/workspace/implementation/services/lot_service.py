"""Sampling plans, capacity verdicts, lot yield and the quarantine cascade."""
import math
from decimal import Decimal

from helpers import assemblies_of_lot, tests_of_assembly
from store import db
from util import ceil_dec, q
from services.constants import (
    CAPACITY_PASS_RATIO,
    CYCLE_LIFE_CAPACITY_RATIO,
    CYCLE_LIFE_CYCLE_RATIO,
    CHEM_LITHIUM,
    LITHIUM_SAMPLE_BONUS,
    SAMPLE_MAX,
    SAMPLE_MIN,
    SAMPLE_TIGHTENED_MAX,
)


def bump_lot(lot):
    """Lot version advances only for the writes PRD 2.6 names."""
    db.touch(lot)


def sampling_plan(lot, design):
    """Calculation 3: integer arithmetic, clamp, tier table, retest tightening."""
    base = int(math.ceil(math.sqrt(int(lot["quantity"]))))
    adjusted = base + (LITHIUM_SAMPLE_BONUS if lot["chemistry"] == CHEM_LITHIUM else 0)
    clamped = max(SAMPLE_MIN, min(adjusted, SAMPLE_MAX))
    if clamped <= 4:
        tier = 0
    elif clamped <= 8:
        tier = 1
    else:
        tier = 2
    tightened = lot.get("retest_count", 0) >= 1 and bool(design.get("retest_tightening_enabled"))
    if tightened:
        return min(clamped * 2, SAMPLE_TIGHTENED_MAX), max(tier - 1, 0)
    return clamped, tier


def draw_plan(lot, design):
    size, acceptance = sampling_plan(lot, design)
    lot["sample_size"] = size
    lot["acceptance_number"] = acceptance
    lot["sampling_plan_revision"] = lot.get("sampling_plan_revision", 0) + 1
    lot["_plan_drawn_at"] = db.now()
    recompute_lot_yield(lot)
    return lot


def capacity_verdict(test, design):
    """Calculation 4: yield always stored, thresholds rounded to 1dp first."""
    measured = test["measured_capacity_ah"]
    nominal = design["nominal_capacity_ah"]
    yield_pct = q(measured / nominal * Decimal("100"), 2)
    if test["test_type"] == "CAPACITY":
        threshold = q(nominal * CAPACITY_PASS_RATIO, 1)
        result = "PASS" if measured >= threshold else "FAIL"
    else:
        cycle_floor = ceil_dec(Decimal(design["rated_cycles"]) * CYCLE_LIFE_CYCLE_RATIO)
        capacity_floor = q(nominal * CYCLE_LIFE_CAPACITY_RATIO, 1)
        cycles = test.get("cycles_completed")
        ok = cycles is not None and cycles >= cycle_floor and measured >= capacity_floor
        result = "PASS" if ok else "FAIL"
    return yield_pct, result


def yield_window_tests(lot):
    """Completed PASS tests of this lot created at or after the current draw."""
    drawn_at = lot.get("_plan_drawn_at")
    rows = []
    for assembly in assemblies_of_lot(lot["id"]):
        for test in tests_of_assembly(assembly["id"]):
            if test.get("test_state") != "COMPLETED" or test.get("result") != "PASS":
                continue
            if drawn_at is not None and test["created_at"] < drawn_at:
                continue
            rows.append(test)
    rows.sort(key=lambda t: (t["created_at"], t["_seq"]))
    return rows


def recompute_lot_yield(lot):
    """Calculation 5: mean of already-rounded per-test yields, rounded again."""
    rows = yield_window_tests(lot)
    if not rows:
        lot["lot_capacity_yield_pct"] = None
        return None
    total = Decimal("0")
    for test in rows:
        total += test["yield_pct"]
    lot["lot_capacity_yield_pct"] = q(total / Decimal(len(rows)), 2)
    return lot["lot_capacity_yield_pct"]


def derive_certification(assembly):
    """Pure join of the two axes; REVOKED is never produced here."""
    torque = assembly["torque_status"]
    insulation = assembly["insulation_status"]
    if torque == "FAIL" or insulation == "FAIL":
        assembly["certification_status"] = "REJECTED"
    elif torque == "PASS" and insulation == "PASS":
        assembly["certification_status"] = "CERTIFIED"
    else:
        assembly["certification_status"] = "PENDING"
    return assembly["certification_status"]


def void_scheduled_tests(assembly):
    for test in tests_of_assembly(assembly["id"]):
        if test.get("test_state") == "SCHEDULED":
            test["test_state"] = "VOIDED"
            db.touch(test)


def quarantine_cascade(lot):
    """Cascade B hops 2-4."""
    lot["process_state"] = "QUARANTINED"
    for assembly in assemblies_of_lot(lot["id"]):
        if assembly.get("certification_status") == "CERTIFIED":
            assembly["certification_status"] = "REVOKED"
            db.touch(assembly)
            void_scheduled_tests(assembly)


def scrap_cascade(lot):
    lot["process_state"] = "SCRAPPED"
    for assembly in assemblies_of_lot(lot["id"]):
        assembly["certification_status"] = "REJECTED"
        db.touch(assembly)
        void_scheduled_tests(assembly)


def restore_revoked_assemblies(lot):
    for assembly in assemblies_of_lot(lot["id"]):
        if assembly.get("certification_status") == "REVOKED":
            assembly["certification_status"] = "PENDING"
            assembly["torque_status"] = "PENDING"
            assembly["insulation_status"] = "PENDING"
            db.touch(assembly)


def release_blocked_by(lot, plant):
    """Actor-independent gate report for the quality summary read."""
    if lot.get("process_state") != "LOT_TESTING":
        return "ERR_LOT_STATE_INVALID"
    if lot.get("env_hold_status") == "HELD":
        return "ERR_LOT_ENV_HELD"
    if plant is not None and plant.get("compliance_posture") == "FROZEN":
        return "ERR_PLANT_FROZEN"
    sample_size = lot.get("sample_size")
    if sample_size is None:
        return "ERR_SAMPLING_INCOMPLETE"
    if lot.get("completed_test_count", 0) < sample_size:
        return "ERR_SAMPLING_INCOMPLETE"
    if lot.get("passed_cycle_life_count", 0) < 1:
        return "ERR_SAMPLING_INCOMPLETE"
    if lot.get("failed_test_count", 0) > lot.get("acceptance_number", 0):
        return "ERR_ACCEPTANCE_EXCEEDED"
    return "NONE"
