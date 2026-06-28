"""Contract state-machine side effects and cascades (PRD 3.2-3.4, 3.7, 2.5)."""
from clock import clock
from db import store
from models import touch, new_record
from util import add_months
from services.lookup import devices_for_contract, get_plan
from services.device_service import recompute_next_test_due


def cascade_activate(contract):
    """PRD 3.2: every ENROLLED device -> ACTIVE; set last_test_at + next_test_due_at."""
    plan = store.monitoring_plans.get(contract["plan_id"])
    for d in devices_for_contract(contract["id"]):
        if d["status"] == "ENROLLED":
            d["status"] = "ACTIVE"
            d["last_test_at_dt"] = clock.now()
            recompute_next_test_due(d, plan)
            touch(d)


def cascade_suspend(contract):
    """PRD 3.4: every ACTIVE device -> SUSPENDED."""
    for d in devices_for_contract(contract["id"]):
        if d["status"] == "ACTIVE":
            d["status"] = "SUSPENDED"
            touch(d)


def cascade_reinstate(contract):
    """PRD 3.4: every SUSPENDED device -> ACTIVE."""
    for d in devices_for_contract(contract["id"]):
        if d["status"] == "SUSPENDED":
            d["status"] = "ACTIVE"
            touch(d)


def cascade_finalize(contract):
    """PRD 3.7: every not-yet-DEACTIVATED device -> DEACTIVATED; open one
    EquipmentReturn per deactivated device (INITIATED, due_back_at = now + 14d)."""
    now = clock.now()
    due_back = now + __import__("datetime").timedelta(days=14)
    for d in devices_for_contract(contract["id"]):
        if d["status"] != "DEACTIVATED":
            d["status"] = "DEACTIVATED"
            touch(d)
            r = new_record()
            r.update({
                "contract_id": contract["id"],
                "device_id": d["id"],
                "status": "INITIATED",
                "condition_grade": None,
                "damage_fee_cents": 0,
                "due_back_at_dt": due_back,
                "received_at_dt": None,
            })
            store.equipment_returns[r["id"]] = r


def pin_plan_terms(contract, plan):
    """PRD 3.2: pin commercial terms at activation."""
    contract["pinned_monthly_fee_cents"] = plan["monthly_fee_cents"]
    contract["pinned_addon_cents"] = plan["fall_detection_addon_cents"]
    contract["pinned_etf_cents"] = plan["early_termination_fee_cents"]
    contract["pinned_min_commitment_months"] = plan["min_commitment_months"]


def any_device_fall_detection(contract):
    """True if any device under the contract has fall_detection_enabled (PRD 3.7)."""
    return any(d["fall_detection_enabled"] for d in devices_for_contract(contract["id"]))


def compute_etf(contract):
    """PRD 3.7: pinned_etf_cents when now < activated_at + pinned_min_commitment_months, else 0."""
    activated_at = contract.get("activated_at_dt")
    if activated_at is None:
        return 0
    window_end = add_months(activated_at, contract.get("pinned_min_commitment_months", 0))
    if clock.now() < window_end:
        return contract.get("pinned_etf_cents", 0)
    return 0
