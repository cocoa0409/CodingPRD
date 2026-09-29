"""Path/FK resolution (rungs 5-6) and the program decision gate (rung 9)."""
from errors import ApiError
import store as db
import derive as dv

ITEM_CLASSES = ("APPAREL_TOP", "APPAREL_BOTTOM", "FOOTWEAR", "ACCESSORY")


def _find(collection, record_id, error_id):
    record = collection.get(record_id)
    if record is None:
        raise ApiError(error_id)
    return record


def get_program(pid):
    return _find(db.programs, pid, "ERR_PROGRAM_NOT_FOUND")


def get_store(sid):
    return _find(db.stores, sid, "ERR_STORE_NOT_FOUND")


def get_plan(pid):
    return _find(db.fixture_plans, pid, "ERR_FIXTURE_PLAN_NOT_FOUND")


def get_profile(pid):
    return _find(db.size_profiles, pid, "ERR_SIZE_PROFILE_NOT_FOUND")


def get_item(iid):
    return _find(db.items, iid, "ERR_ITEM_NOT_FOUND")


def get_position(pid):
    return _find(db.positions, pid, "ERR_POSITION_NOT_FOUND")


def get_receipt(rid):
    return _find(db.receipts, rid, "ERR_RECEIPT_NOT_FOUND")


def get_run(rid):
    return _find(db.runs, rid, "ERR_RUN_NOT_FOUND")


def get_line(lid):
    return _find(db.lines, lid, "ERR_LINE_NOT_FOUND")


def get_promo(eid):
    return _find(db.promo_events, eid, "ERR_PROMO_EVENT_NOT_FOUND")


def get_transfer(tid):
    return _find(db.transfers, tid, "ERR_RECOMMENDATION_NOT_FOUND")


def get_action(aid):
    return _find(db.actions, aid, "ERR_ASSORTMENT_ACTION_NOT_FOUND")


def get_snapshot(sid):
    return _find(db.snapshots, sid, "ERR_SNAPSHOT_NOT_FOUND")


def bad_state():
    raise ApiError("ERR_INVALID_STATE_TRANSITION")


def decision_gate(program):
    """Rung 9: allocation and transfer DECISIONS need an ACTIVE program."""
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_LOCKED")


def program_of_receipt(receipt):
    return db.programs[receipt["program_id"]]


def program_of_run(run):
    return program_of_receipt(db.receipts[run["receipt_id"]])


def program_of_item(item):
    return db.programs[item["program_id"]]


def item_of_run(run):
    return db.items[db.receipts[run["receipt_id"]]["item_id"]]


def plan_in_effect_or_reject(store_id, item_class):
    plan = dv.in_effect_plan(store_id, item_class)
    if plan is None:
        raise ApiError("ERR_NO_FIXTURE_PLAN_IN_EFFECT")
    return plan


def merge_sizes(size_array, additions):
    """Merge {size_code: units} additions into a stored size array in place."""
    index = {entry["size_code"]: entry for entry in size_array}
    for entry in additions:
        if entry["units"] == 0:
            continue
        if entry["size_code"] in index:
            index[entry["size_code"]]["units"] += entry["units"]
        else:
            size_array.append({"size_code": entry["size_code"], "units": entry["units"]})
            index[entry["size_code"]] = size_array[-1]


def subtract_sizes(size_array, removals):
    """Subtract units from a stored size array in place, never below zero."""
    index = {entry["size_code"]: entry for entry in size_array}
    for entry in removals:
        target = index.get(entry["size_code"])
        if target is None:
            continue
        target["units"] = max(0, target["units"] - entry["units"])
