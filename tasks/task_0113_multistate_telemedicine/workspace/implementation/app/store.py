"""In-memory data store for all entities.

Each entity is a dict keyed by id. A single RLock serializes all mutations so
that the cascading "license revoke" and "issue prescription" multi-row
operations stay atomic.
"""
import secrets
import string
import uuid
from threading import RLock
from typing import Any, Dict, List, Optional

from app.clock import clock


def _new_id() -> str:
    return str(uuid.uuid4())


def _new_request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _now_iso() -> str:
    dt = clock.now()
    # ISO 8601 UTC with milliseconds: 2025-05-24T10:30:00.123Z
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self) -> None:
        self.lock = RLock()
        self.physicians: Dict[str, Dict[str, Any]] = {}
        self.state_licenses: Dict[str, Dict[str, Any]] = {}
        self.patients: Dict[str, Dict[str, Any]] = {}
        self.consults: Dict[str, Dict[str, Any]] = {}
        self.prescriptions: Dict[str, Dict[str, Any]] = {}
        self.claims: Dict[str, Dict[str, Any]] = {}
        self.invoices: Dict[str, Dict[str, Any]] = {}
        self.followups: Dict[str, Dict[str, Any]] = {}
        self.audit_events: List[Dict[str, Any]] = []

    # ------- ID generation -------
    @staticmethod
    def new_id() -> str:
        return _new_id()

    @staticmethod
    def now_iso() -> str:
        return _now_iso()

    @staticmethod
    def new_request_id() -> str:
        return _new_request_id()

    # ------- Audit -------
    def append_audit(
        self,
        event_type: str,
        subject_entity: str,
        subject_id: str,
        actor_role: str,
        payload_json: Optional[Any] = None,
    ) -> Dict[str, Any]:
        event = {
            "id": _new_id(),
            "event_type": event_type,
            "subject_entity": subject_entity,
            "subject_id": subject_id,
            "actor_role": actor_role,
            "payload_json": payload_json if payload_json is not None else {},
            "created_at": _now_iso(),
        }
        self.audit_events.append(event)
        return event


store = Store()
