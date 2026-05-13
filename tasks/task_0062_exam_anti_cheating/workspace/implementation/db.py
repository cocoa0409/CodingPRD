"""In-memory data store + helpers for stamping common fields."""
import threading
import uuid

from clock import iso, now


# Tables — id -> entity dict
exams = {}
questions = {}
registrations = {}
attempts = {}
identity_records = {}        # id -> IdentityVerificationRecord
abnormal_events = {}         # id -> AbnormalEvent
grading_assignments = {}     # id -> GradingAssignment
appeals = {}                 # id -> Appeal
audit_logs = {}              # id -> AuditLogEntry


_seq_lock = threading.Lock()
_seq = 0
_lock = threading.RLock()


def next_seq() -> int:
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


def lock():
    return _lock


def gen_id() -> str:
    return str(uuid.uuid4())


def stamp_create(d: dict, *, common_fields: bool = True) -> dict:
    """Stamp id, created_at and (when common_fields) updated_at + version=1."""
    ts = iso(now())
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
        d["updated_at"] = iso(now())


def public(d: dict) -> dict:
    """Strip private (underscore-prefixed) fields before serialization."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


def reset_all() -> None:
    global _seq
    for tbl in [
        exams, questions, registrations, attempts, identity_records,
        abnormal_events, grading_assignments, appeals, audit_logs,
    ]:
        tbl.clear()
    with _seq_lock:
        _seq = 0
