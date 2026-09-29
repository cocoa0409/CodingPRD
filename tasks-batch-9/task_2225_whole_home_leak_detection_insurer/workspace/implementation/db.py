"""In-memory data store.

The store starts completely empty on every boot: no seeding, no preloaded
rows.  Every entity a test needs is built through the declared API surface.
"""
import itertools

import clock
from util import new_id

_seq = itertools.count(1)

TABLES = (
    "homeowners",
    "emergency_contacts",
    "properties",
    "devices",
    "baseline_profiles",
    "telemetry_readings",
    "anomaly_events",
    "escalation_tickets",
    "irrigation_windows",
    "policies",
    "attestations",
    "claims",
    "transfers",
)

homeowners = {}
emergency_contacts = {}
properties = {}
devices = {}
baseline_profiles = {}
telemetry_readings = {}
anomaly_events = {}
escalation_tickets = {}
irrigation_windows = {}
policies = {}
attestations = {}
claims = {}
transfers = {}

_BY_NAME = {
    "homeowners": homeowners,
    "emergency_contacts": emergency_contacts,
    "properties": properties,
    "devices": devices,
    "baseline_profiles": baseline_profiles,
    "telemetry_readings": telemetry_readings,
    "anomaly_events": anomaly_events,
    "escalation_tickets": escalation_tickets,
    "irrigation_windows": irrigation_windows,
    "policies": policies,
    "attestations": attestations,
    "claims": claims,
    "transfers": transfers,
}


def table(name):
    return _BY_NAME[name]


def reset():
    for tbl in _BY_NAME.values():
        tbl.clear()
    clock.reset()


def insert(tbl, row, versioned=True):
    """Insert a row, stamping id / created_at / updated_at / version."""
    now = clock.now()
    row.setdefault("id", new_id())
    row["created_at"] = now
    if versioned:
        row["updated_at"] = now
        row["version"] = 1
    row["_seq"] = next(_seq)
    tbl[row["id"]] = row
    return row


def touch(row, bump=True):
    """Refresh updated_at and (by default) increment version by 1."""
    row["updated_at"] = clock.now()
    if bump and "version" in row:
        row["version"] = row["version"] + 1
    return row


def seq_of(row):
    return row.get("_seq", 0)


def rows(tbl):
    return list(tbl.values())


def by_seq(items):
    return sorted(items, key=lambda r: r.get("_seq", 0))


def sort_rows(items, key, reverse=False):
    """Stable sort by `key(row)` with insertion sequence as the tie-break."""
    return sorted(
        items,
        key=lambda r: (key(r), r.get("_seq", 0)),
        reverse=reverse,
    )


# ---------------------------------------------------------------- lookups
def homeowner(hid):
    return homeowners.get(hid)


def prop(pid):
    return properties.get(pid)


def device(did):
    return devices.get(did)


def profile_for_device(device_id):
    for row in baseline_profiles.values():
        if row["device_id"] == device_id:
            return row
    return None


def readings_for_device(device_id):
    return by_seq([r for r in telemetry_readings.values() if r["device_id"] == device_id])


def events_for_device(device_id):
    return by_seq([e for e in anomaly_events.values() if e["device_id"] == device_id])


def ticket_for_event(event_id):
    found = [t for t in escalation_tickets.values() if t["anomaly_event_id"] == event_id]
    return by_seq(found)[-1] if found else None


def contacts_for_homeowner(homeowner_id):
    return by_seq(
        [c for c in emergency_contacts.values() if c["homeowner_id"] == homeowner_id]
    )


def properties_for_homeowner(homeowner_id):
    return by_seq([p for p in properties.values() if p["homeowner_id"] == homeowner_id])


def devices_for_property(property_id):
    return by_seq([d for d in devices.values() if d["property_id"] == property_id])


def windows_for_property(property_id):
    return by_seq(
        [w for w in irrigation_windows.values() if w["property_id"] == property_id]
    )


def policies_for_property(property_id):
    return by_seq([p for p in policies.values() if p["property_id"] == property_id])


def attestations_for_policy(policy_id):
    return by_seq([a for a in attestations.values() if a["policy_id"] == policy_id])


def claims_for_device(device_id):
    return by_seq([c for c in claims.values() if c["device_id"] == device_id])


def transfers_for_device(device_id):
    return by_seq([t for t in transfers.values() if t["device_id"] == device_id])


# ---------------------------------------------------------------- ownership walk
def owner_of_property(row):
    return row["homeowner_id"] if row else None


def owner_of_device(row):
    p = properties.get(row["property_id"]) if row else None
    return p["homeowner_id"] if p else None


def owner_of_event(row):
    d = devices.get(row["device_id"]) if row else None
    return owner_of_device(d) if d else None


def owner_of_ticket(row):
    e = anomaly_events.get(row["anomaly_event_id"]) if row else None
    return owner_of_event(e) if e else None


def owner_of_policy(row):
    p = properties.get(row["property_id"]) if row else None
    return p["homeowner_id"] if p else None


def owner_of_attestation(row):
    pol = policies.get(row["policy_id"]) if row else None
    return owner_of_policy(pol) if pol else None


def owner_of_claim(row):
    return row["submitted_by_user_id"] if row else None


def owner_of_transfer(row):
    d = devices.get(row["device_id"]) if row else None
    return owner_of_device(d) if d else None
