"""Record creation, lookup (with resource-specific not-found), version/timestamp
stamping, and the running-ledger recompute helpers (PRD §2.9)."""
from decimal import Decimal

from errors import err
from store import db, new_id, now_iso, serialize
from common import num

# collection name -> not-found error id
_NOT_FOUND = {
    "programs": "ERR_PROGRAM_NOT_FOUND",
    "aggregators": "ERR_AGGREGATOR_NOT_FOUND",
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "devices": "ERR_DEVICE_NOT_FOUND",
    "enrollments": "ERR_ENROLLMENT_NOT_FOUND",
    "dispatch_events": "ERR_DISPATCH_EVENT_NOT_FOUND",
    "dispatches": "ERR_DISPATCH_NOT_FOUND",
    "meter_readings": "ERR_METER_READING_NOT_FOUND",
    "settlements": "ERR_SETTLEMENT_NOT_FOUND",
    "payments": "ERR_PAYMENT_NOT_FOUND",
}


def get(collection, rid):
    return db.data[collection].get(rid)


def get_or_404(collection, rid):
    rec = db.data[collection].get(rid)
    if rec is None:
        raise err(_NOT_FOUND[collection], "%s %s not found." % (collection[:-1], rid))
    return rec


def insert(collection, rec, common=True):
    """Attach id + common fields, store, return the record."""
    rid = new_id()
    stamp = now_iso()
    base = {"id": rid, "created_at": stamp, "_seq": db.next_seq()}
    if common:
        base["updated_at"] = stamp
        base["version"] = 1
    base.update(rec)
    base["id"] = rid  # id is authoritative
    db.data[collection][rid] = base
    return base


def touch(rec, bump=True):
    """Refresh updated_at to the logical-clock instant and bump version by 1."""
    rec["updated_at"] = now_iso()
    if bump:
        rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Cross-aggregate helpers
# ---------------------------------------------------------------------------
def device_of_enrollment(enrollment):
    return get("devices", enrollment["device_id"])


def aggregator_id_of_dispatch(dispatch):
    enr = get("enrollments", dispatch["enrollment_id"])
    dev = get("devices", enr["device_id"]) if enr else None
    return dev["aggregator_id"] if dev else None


# ---------------------------------------------------------------------------
# Ledger recompute (PRD §2.9)
# ---------------------------------------------------------------------------
def recompute_committed_kw(program_id, aggregator_ids):
    """Program.total_committed_kw and each aggregator's enrolled_committed_kw as
    the exact sum of committed_kw over ACTIVE enrollments (kW held exact)."""
    prog = get("programs", program_id)
    if prog is not None:
        vals = [e["committed_kw"] for e in db.data["enrollments"].values()
                if e["program_id"] == program_id and e["status"] == "ACTIVE"]
        prog["total_committed_kw"] = num(_dsum(vals))
    for agg_id in aggregator_ids:
        agg = get("aggregators", agg_id)
        if agg is None:
            continue
        vals = []
        for e in db.data["enrollments"].values():
            if e["status"] != "ACTIVE":
                continue
            dev = get("devices", e["device_id"])
            if dev and dev["aggregator_id"] == agg_id:
                vals.append(e["committed_kw"])
        agg["enrolled_committed_kw"] = num(_dsum(vals))


def recompute_aggregator_season_kwh(aggregator_ids):
    for agg_id in aggregator_ids:
        agg = get("aggregators", agg_id)
        if agg is None:
            continue
        vals = []
        for e in db.data["enrollments"].values():
            dev = get("devices", e["device_id"])
            if dev and dev["aggregator_id"] == agg_id:
                vals.append(e.get("season_delivered_kwh") or 0)
        agg["season_delivered_kwh"] = num(_dsum(vals), places=3)


def recompute_paid_balance(aggregator_ids):
    for agg_id in aggregator_ids:
        agg = get("aggregators", agg_id)
        if agg is None:
            continue
        total = 0
        for p in db.data["payments"].values():
            if p["aggregator_id"] == agg_id and p["status"] in ("ISSUED", "CLEARED"):
                total += p["amount_cents"]
        agg["paid_balance_cents"] = total


def _dsum(values):
    total = Decimal("0")
    for v in values:
        total += Decimal(str(v))
    return total
