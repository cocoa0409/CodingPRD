"""In-memory data store, logical clock, and entity helpers.

Everything lives in module globals, so a fresh process boots with an empty
store and the clock at its default. No seeding of any kind happens here.
"""
import uuid
from datetime import datetime

from util import parse_dt, fmt_dt

DEFAULT_CLOCK = "2026-03-01T00:00:00Z"

# Entity collections keyed by id
DB = {
    "districts": {},
    "parcels": {},
    "protests": {},
    "rolls": {},
    "bonds": {},
    "installments": {},
    "payments": {},
    "quotes": {},
    "liens": {},
    "foreclosures": {},
}

_state = {
    "clock": parse_dt(DEFAULT_CLOCK),
    "seq": 0,
}


def now():
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def new_id():
    return str(uuid.uuid4())


def make(type_key, fields, versioned=True):
    e = dict(fields)
    e["id"] = new_id()
    e["_seq"] = next_seq()
    e["_type"] = type_key
    e["created_at"] = now()
    if versioned:
        e["updated_at"] = now()
        e["version"] = 1
    DB[type_key][e["id"]] = e
    return e


def touch(e):
    e["updated_at"] = now()
    if "version" in e:
        e["version"] += 1


def ser(e):
    """Serialize an entity for output, dropping internal (_-prefixed) keys."""
    out = {}
    for k, v in e.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------
def parcels_of_district(did):
    return [p for p in DB["parcels"].values() if p["district_id"] == did]


def rolls_of_district(did):
    return [r for r in DB["rolls"].values() if r["district_id"] == did]


def bonds_of_district(did):
    return [b for b in DB["bonds"].values() if b["district_id"] == did]


def installments_of_parcel(pid):
    return [i for i in DB["installments"].values() if i["parcel_id"] == pid]


def installments_of_bond(bid):
    return [i for i in DB["installments"].values() if i["bond_id"] == bid]


def liens_of_parcel(pid):
    return [l for l in DB["liens"].values() if l["parcel_id"] == pid]


def quotes_of_parcel(pid):
    return [q for q in DB["quotes"].values() if q["parcel_id"] == pid]


def protests_of_parcel(pid):
    return [p for p in DB["protests"].values() if p["parcel_id"] == pid]


def foreclosures_of_parcel(pid):
    return [f for f in DB["foreclosures"].values() if f["parcel_id"] == pid]


def payments_of_installment(iid):
    return [p for p in DB["payments"].values() if p["installment_id"] == iid]


def by_seq(items):
    return sorted(items, key=lambda e: e["_seq"])
