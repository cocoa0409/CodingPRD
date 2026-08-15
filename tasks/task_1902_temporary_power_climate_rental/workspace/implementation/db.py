"""In-memory data store. Starts empty on every boot; no persistence, no seeding."""
import threading
from decimal import Decimal


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.customers = {}
        self.sites = {}
        self.units = {}
        self.kits = {}
        self.contracts = {}
        self.lines = {}
        self.permits = {}
        self.visits = {}
        self.telemetry = {}
        self.incidents = {}
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


DB = Store()


def touch(rec, ts):
    """Bump version and refresh updated_at on a versioned resource (PRD 2.4)."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = ts


# ---------------------------------------------------------------------------
# Serializers: strip internals, format datetimes and Decimals for JSON output.
# ---------------------------------------------------------------------------
from util import fmt_ts, num_out  # noqa: E402

DT_FIELDS = {
    "created_at", "updated_at", "start_date", "expected_offhire_date",
    "quoted_at", "on_rent_at", "actual_offhire_at", "offhired_at",
    "submitted_at", "decided_at", "scheduled_start", "scheduled_end",
    "requested_at", "dispatched_at", "arrived_at", "recorded_at",
}


def _out(rec):
    result = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if v is None:
            result[k] = None
        elif k in DT_FIELDS:
            result[k] = fmt_ts(v)
        elif isinstance(v, Decimal):
            result[k] = num_out(v)
        elif isinstance(v, list):
            result[k] = [dict(item) for item in v]
        else:
            result[k] = v
    return result


def customer_out(c):
    return _out(c)


def site_out(s):
    return _out(s)


def unit_out(u):
    return _out(u)


def kit_out(k):
    return _out(k)


def contract_out(c):
    return _out(c)


def line_out(l):
    return _out(l)


def permit_out(p):
    return _out(p)


def visit_out(v):
    return _out(v)


def telemetry_out(t):
    return _out(t)


def incident_out(i):
    return _out(i)
