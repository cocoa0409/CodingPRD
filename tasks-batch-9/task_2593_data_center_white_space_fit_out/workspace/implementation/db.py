"""In-memory store.  Starts EMPTY on every boot -- nothing is ever seeded."""

import uuid

from flask import g, has_app_context

from constants import CLOCK_DEFAULT
from response import format_dt, iso_now
from util import parse_iso

KINDS = [
    "halls",
    "tenants",
    "pdus",
    "busways",
    "zones",
    "cooling_units",
    "cages",
    "devices",
    "racks",
    "feeds",
    "packages",
    "load_bank_tests",
    "mops",
    "approvals",
    "packets",
]

NOT_FOUND = {
    "halls": "ERR_HALL_NOT_FOUND",
    "tenants": "ERR_TENANT_NOT_FOUND",
    "pdus": "ERR_PDU_NOT_FOUND",
    "busways": "ERR_BUSWAY_NOT_FOUND",
    "zones": "ERR_CONTAINMENT_ZONE_NOT_FOUND",
    "cooling_units": "ERR_COOLING_UNIT_NOT_FOUND",
    "cages": "ERR_CAGE_NOT_FOUND",
    "devices": "ERR_SECURITY_DEVICE_NOT_FOUND",
    "racks": "ERR_RACK_NOT_FOUND",
    "feeds": "ERR_RACK_FEED_NOT_FOUND",
    "packages": "ERR_PACKAGE_NOT_FOUND",
    "load_bank_tests": "ERR_LOAD_BANK_TEST_NOT_FOUND",
    "mops": "ERR_MOP_NOT_FOUND",
    "approvals": "ERR_MOP_NOT_FOUND",
    "packets": "ERR_RELEASE_PACKET_NOT_FOUND",
}

TABLES = {kind: {} for kind in KINDS}

_STATE = {"seq": 0, "clock": parse_iso(CLOCK_DEFAULT)}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _STATE["seq"] += 1
    return _STATE["seq"]


# --- logical clock (PRD 2.4) -------------------------------------------------

def clock_now():
    return _STATE["clock"]


def clock_iso():
    return format_dt(_STATE["clock"])


def set_clock(dt):
    _STATE["clock"] = dt


# --- row bookkeeping --------------------------------------------------------

def _bag(name):
    if has_app_context():
        return g.setdefault(name, [])
    return _STATE.setdefault(name, [])


def insert(kind, row):
    row["_kind"] = kind
    row["_seq"] = next_seq()
    TABLES[kind][row["id"]] = row
    _bag("_fresh").append(row["id"])
    return row


def touch(row):
    """Mark a row mutated: one version bump / updated_at refresh per request."""
    if row is None:
        return row
    _bag("_dirty").append(row["id"])
    return row


def assign(row, values):
    """Write derived fields, marking the row dirty only when something changed."""
    if row is None:
        return False
    changed = False
    for key, value in values.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def commit():
    """Apply the pending version bumps.  Call before serialising a response."""
    fresh = set(_bag("_fresh"))
    stamp = iso_now()
    seen = set()
    for row_id in list(_bag("_dirty")):
        if row_id in fresh or row_id in seen:
            continue
        seen.add(row_id)
        row = None
        for kind in KINDS:
            if row_id in TABLES[kind]:
                row = TABLES[kind][row_id]
                break
        if row is None or "version" not in row:
            continue
        row["version"] = row["version"] + 1
        row["updated_at"] = stamp
    _bag("_dirty").clear()


def get(kind, row_id):
    if not isinstance(row_id, str):
        return None
    return TABLES[kind].get(row_id)


def all_rows(kind):
    return list(TABLES[kind].values())


def where(kind, **criteria):
    out = []
    for row in TABLES[kind].values():
        ok = True
        for key, value in criteria.items():
            if isinstance(value, (list, tuple, set)):
                if row.get(key) not in value:
                    ok = False
                    break
            elif row.get(key) != value:
                ok = False
                break
        if ok:
            out.append(row)
    return out


def ordered(rows):
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def new_row(kind, fields, versioned=True):
    row = {"id": new_id(), "created_at": iso_now()}
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row.update(fields)
    return insert(kind, row)
