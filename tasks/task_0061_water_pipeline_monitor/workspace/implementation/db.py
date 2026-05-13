"""In-memory data store and helpers for stamping common fields.

All entity tables live here as dicts keyed by UUID id (or a logical key).
Common-field stamping (id, created_at, updated_at, version) lives here so
every route writes the same shape.
"""
import threading
import uuid

from clock import iso, server_now


# ---------- Tables ----------
networks = {}                # id -> Network
topology_versions = {}       # id -> TopologyVersion
pipeline_nodes = {}          # id -> PipelineNode
pipeline_segments = {}       # id -> PipelineSegment
dmas = {}                    # id -> DMA
devices = {}                 # id -> Device
readings = {}                # id -> Reading
alerts = {}                  # id -> Alert
investigations = {}          # id -> LeakInvestigation
work_orders = {}             # id -> WorkOrder
water_balance_reports = {}   # id -> WaterBalanceReport
sync_events = {}             # id -> SyncEvent
audit_logs = {}              # id -> AuditLog

# Idempotency table for reading ingest: (device_id, idempotency_key) -> reading_id
reading_idempotency = {}

# Sync sequence counters per (network_id, target_system)
_sync_seq_counters = {}

# Monotonic insertion sequence for stable ordering of audit/sync rows
_seq_lock = threading.Lock()
_seq = 0

_lock = threading.RLock()


def lock():
    return _lock


def next_seq() -> int:
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


def next_sync_seq(network_id: str, target_system: str) -> int:
    key = (network_id, target_system)
    counter = _sync_seq_counters.get(key, 0) + 1
    _sync_seq_counters[key] = counter
    return counter


def gen_id() -> str:
    return str(uuid.uuid4())


def stamp_create(d: dict, *, common_fields: bool = True) -> dict:
    """Stamp id, created_at, and (when common_fields) updated_at + version=1."""
    ts = iso(server_now())
    d.setdefault("id", gen_id())
    d["created_at"] = ts
    d["_seq"] = next_seq()
    if common_fields:
        d["updated_at"] = ts
        d["version"] = 1
    return d


def stamp_update(d: dict) -> None:
    """Refresh updated_at and bump version when those fields exist on the row."""
    if "version" in d:
        d["version"] = int(d["version"]) + 1
    if "updated_at" in d:
        d["updated_at"] = iso(server_now())


def public(d: dict) -> dict:
    """Strip private (underscore-prefixed) fields before serialization."""
    if d is None:
        return None
    return {k: v for k, v in d.items() if not k.startswith("_")}


def reset_all() -> None:
    global _seq, _sync_seq_counters
    for tbl in [
        networks, topology_versions, pipeline_nodes, pipeline_segments,
        dmas, devices, readings, alerts, investigations, work_orders,
        water_balance_reports, sync_events, audit_logs, reading_idempotency,
    ]:
        tbl.clear()
    _sync_seq_counters = {}
    with _seq_lock:
        _seq = 0
