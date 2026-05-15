"""Cross-table lookup helpers."""

from db import DB


def battery_model_by_code(code: str):
    for bm in DB["battery_models"].values():
        if bm.get("code") == code:
            return bm
    return None


def vehicle_model_by_code(code: str):
    for vm in DB["vehicle_models"].values():
        if vm.get("code") == code:
            return vm
    return None


def compatibility_rule(vehicle_model_code: str, battery_model_code: str):
    for rule in DB["compatibility_rules"].values():
        if (rule.get("vehicle_model_code") == vehicle_model_code
                and rule.get("battery_model_code") == battery_model_code):
            return rule
    return None


def is_compatible(vehicle_model_code: str, battery_model_code: str) -> bool:
    rule = compatibility_rule(vehicle_model_code, battery_model_code)
    if rule is None:
        return False
    return bool(rule.get("connector_match")) and bool(rule.get("bms_handshake_supported"))


def charging_slot_for_battery(battery_id: str):
    for slot in DB["charging_slots"].values():
        if slot.get("battery_id") == battery_id:
            return slot
    return None
