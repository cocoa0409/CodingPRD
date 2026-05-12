"""LockerMachine + Compartment helpers, capacity calculation."""

from clock import now, iso, parse_iso
from constants import (
    NEAR_FULL_RATIO,
    PEAK_NEAR_FULL_RATIO,
    FULL_BLOCK_RATIO,
    MIN_FIRMWARE_VERSION,
)
from db import DB, new_id
from errors import (
    APIError,
    invalid_request,
    not_found,
)
from services.util import semver_ge, stamp_create, stamp_update


SIZES = ["SMALL", "MEDIUM", "LARGE"]
LEVEL_RANK = {"NORMAL": 0, "NEAR_FULL": 1, "FULL_BLOCK_DEPOSITS": 2}


def _is_peak(now_dt) -> bool:
    h = now_dt.hour
    return (10 <= h < 12) or (18 <= h < 21)


def per_size_level(machine_id: str, size: str) -> str:
    """Compute per-size capacity warning level for a single size class."""
    total = 0
    occupied = 0
    for c in DB.compartments.values():
        if c["locker_machine_id"] != machine_id or c.get("size") != size:
            continue
        if c.get("status") == "DECOMMISSIONED":
            continue
        total += 1
        if c.get("status") == "OCCUPIED":
            occupied += 1
    denom = total if total > 0 else 1
    ratio = occupied / denom

    near = PEAK_NEAR_FULL_RATIO if _is_peak(now()) else NEAR_FULL_RATIO
    if ratio >= FULL_BLOCK_RATIO:
        return "FULL_BLOCK_DEPOSITS"
    if ratio >= near:
        return "NEAR_FULL"
    return "NORMAL"


def per_size_ratio(machine_id: str, size: str) -> float:
    total = 0
    occupied = 0
    for c in DB.compartments.values():
        if c["locker_machine_id"] != machine_id or c.get("size") != size:
            continue
        if c.get("status") == "DECOMMISSIONED":
            continue
        total += 1
        if c.get("status") == "OCCUPIED":
            occupied += 1
    denom = total if total > 0 else 1
    return occupied / denom


def machine_warning_level(machine_id: str) -> str:
    """The most-severe per-size level across the three sizes."""
    worst = "NORMAL"
    for sz in SIZES:
        lvl = per_size_level(machine_id, sz)
        if LEVEL_RANK[lvl] > LEVEL_RANK[worst]:
            worst = lvl
    return worst


def is_degraded(machine: dict) -> bool:
    if machine.get("online_status") == "OFFLINE":
        return True
    if not semver_ge(machine.get("firmware_version"), MIN_FIRMWARE_VERSION):
        return True
    return False


def serialize_machine(m: dict) -> dict:
    mid = m["id"]
    # Counts
    total = 0
    occ_s = occ_m = occ_l = 0
    last_open = None
    for c in DB.compartments.values():
        if c["locker_machine_id"] != mid:
            continue
        if c.get("status") != "DECOMMISSIONED":
            total += 1
        if c.get("status") == "OCCUPIED":
            sz = c.get("size")
            if sz == "SMALL":
                occ_s += 1
            elif sz == "MEDIUM":
                occ_m += 1
            elif sz == "LARGE":
                occ_l += 1
        # last_open_at across machine
        lo = c.get("last_open_at")
        if lo and (last_open is None or lo > last_open):
            last_open = lo
    return {
        "id": m["id"],
        "site_code": m.get("site_code"),
        "partner_id": m.get("partner_id"),
        "firmware_version": m.get("firmware_version"),
        "online_status": m.get("online_status"),
        "last_heartbeat_at": m.get("last_heartbeat_at"),
        "degraded_mode": is_degraded(m),
        "total_compartments": total,
        "occupied_count_small": occ_s,
        "occupied_count_medium": occ_m,
        "occupied_count_large": occ_l,
        "last_open_at": last_open,
        "capacity_warning_level": machine_warning_level(mid),
        "created_at": m.get("created_at"),
        "updated_at": m.get("updated_at"),
        "version": m.get("version", 0),
    }


def serialize_compartment(c: dict) -> dict:
    return {
        "id": c["id"],
        "locker_machine_id": c["locker_machine_id"],
        "slot_label": c.get("slot_label"),
        "size": c.get("size"),
        "status": c.get("status"),
        "current_parcel_id": c.get("current_parcel_id"),
        "last_open_at": c.get("last_open_at"),
        "created_at": c.get("created_at"),
        "updated_at": c.get("updated_at"),
        "version": c.get("version", 0),
    }


def get_machine(machine_id: str):
    m = DB.locker_machines.get(machine_id)
    if not m:
        raise not_found(f"LockerMachine not found: {machine_id}")
    return m


def get_compartment(machine_id: str, compartment_id: str):
    # validate machine first per PRD §2.6
    get_machine(machine_id)
    c = DB.compartments.get(compartment_id)
    if not c or c.get("locker_machine_id") != machine_id:
        raise not_found(f"Compartment not found: {compartment_id}")
    return c


def create_machine(payload: dict) -> dict:
    site_code = payload.get("site_code")
    partner_id = payload.get("partner_id")
    firmware_version = payload.get("firmware_version")
    if not site_code or not partner_id or not firmware_version:
        raise invalid_request("site_code, partner_id, firmware_version required")
    rid = new_id()
    base = stamp_create()
    record = {
        "id": rid,
        "site_code": site_code,
        "partner_id": partner_id,
        "firmware_version": firmware_version,
        "online_status": "ONLINE",
        "last_heartbeat_at": None,
        **base,
    }
    DB.locker_machines[rid] = record
    return record


def heartbeat(machine_id: str, payload: dict) -> dict:
    m = get_machine(machine_id)
    from services.util import check_version, opt_field
    check_version(m, opt_field(payload, "version"))
    fw = payload.get("firmware_version")
    if not fw:
        raise invalid_request("firmware_version required")
    m["firmware_version"] = fw
    m["last_heartbeat_at"] = iso(now())
    if m["online_status"] == "OFFLINE" and semver_ge(fw, MIN_FIRMWARE_VERSION):
        m["online_status"] = "ONLINE"
    stamp_update(m)
    return m


def force_offline(machine_id: str, payload: dict = None) -> dict:
    m = get_machine(machine_id)
    if payload:
        from services.util import check_version, opt_field
        check_version(m, opt_field(payload, "version"))
    if m["online_status"] != "OFFLINE":
        m["online_status"] = "OFFLINE"
        stamp_update(m)
    return m


def create_compartment(machine_id: str, payload: dict) -> dict:
    get_machine(machine_id)
    slot_label = payload.get("slot_label")
    size = payload.get("size")
    if not slot_label or size not in ("SMALL", "MEDIUM", "LARGE"):
        raise invalid_request("slot_label and valid size required")
    # uniqueness within machine
    for c in DB.compartments.values():
        if c["locker_machine_id"] == machine_id and c.get("slot_label") == slot_label:
            raise invalid_request(f"slot_label '{slot_label}' already exists")
    rid = new_id()
    base = stamp_create()
    record = {
        "id": rid,
        "locker_machine_id": machine_id,
        "slot_label": slot_label,
        "size": size,
        "status": "AVAILABLE",
        "current_parcel_id": None,
        "last_open_at": None,
        **base,
    }
    DB.compartments[rid] = record
    return record


def list_machines(args):
    out = list(DB.locker_machines.values())
    online = args.get("online_status")
    if online:
        out = [m for m in out if m.get("online_status") == online]
    out.sort(key=lambda r: (r.get("created_at") or "", r["id"]))
    return out


def list_compartments(machine_id: str, args):
    get_machine(machine_id)
    out = [c for c in DB.compartments.values() if c["locker_machine_id"] == machine_id]
    sz = args.get("size")
    st = args.get("status")
    if sz:
        out = [c for c in out if c.get("size") == sz]
    if st:
        out = [c for c in out if c.get("status") == st]
    out.sort(key=lambda r: (r.get("created_at") or "", r["id"]))
    return out
