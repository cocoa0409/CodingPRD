"""Serialize entities into outgoing JSON payloads (deep copies to avoid leaks)."""
import copy


def serialize_account(a: dict) -> dict:
    return copy.deepcopy(a)


def serialize_vehicle(v: dict) -> dict:
    return copy.deepcopy(v)


def serialize_transponder(t: dict) -> dict:
    return copy.deepcopy(t)


def serialize_toll_event(e: dict) -> dict:
    return copy.deepcopy(e)


def serialize_reload(r: dict) -> dict:
    return copy.deepcopy(r)


def serialize_violation(v: dict) -> dict:
    return copy.deepcopy(v)


def serialize_fine(f: dict) -> dict:
    return copy.deepcopy(f)


def serialize_interop(p: dict) -> dict:
    return copy.deepcopy(p)


def account_summary(a: dict, vehicles_count: int, transponders_count: int) -> dict:
    payload = serialize_account(a)
    payload["vehicles_count"] = vehicles_count
    payload["transponders_count"] = transponders_count
    return payload
