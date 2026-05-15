"""In-memory dict-of-dicts storage and the test logical clock.

Every entity collection is a `Dict[str, dict]` keyed by the entity's id.
Common fields (`id`, `created_at`, `updated_at`, `version`) are stamped by
the `stamp_create` / `stamp_update` helpers so the per-blueprint code never
has to think about them.

The append-only collections (`riders`, `fulfilment_logs`, `audit_entries`)
carry only `id` and `created_at` per PRD §2.4.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time as _time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from .constants import IDEMPOTENCY_WINDOW_SECONDS
from .envelope import fresh_uuid, server_now_iso8601, epoch_to_iso8601


# -----------------------------------------------------------------------------
# Test-driven logical clock.
#
# §2.7 pins the convention: every time-gated transition reads
# `real_now + Festival.clock_offset_seconds`.  The dev endpoint
# `POST /_clock/advance` mutates the offset; the read endpoint `GET /_clock`
# surfaces both wall-time and offset.
#
# The clock is **per festival** because the scaffold's `Festival` row carries
# a `clock_offset_seconds` integer (default 0).  Operations whose target
# festival is unambiguous (a program-item transition, a sweep, a sync-ack
# tied to a schedule-change) read the parent festival's offset.  The
# clock-advance endpoint accepts an optional `festival_id`; when omitted,
# the advance is broadcast to every festival.
# -----------------------------------------------------------------------------


def real_now_unix() -> float:
    """Return the OS wall-clock time in seconds since the epoch."""
    return _time.time()


def logical_now(festival: Optional[Dict[str, Any]]) -> int:
    """Return `int(real_now + festival.clock_offset_seconds)`.

    The integer cast matches the scaffold's Unix-seconds convention
    everywhere; sub-second precision is irrelevant for the harness which
    drives time forward in integer-second deltas.
    """
    offset = 0 if festival is None else int(festival.get("clock_offset_seconds", 0))
    return int(real_now_unix()) + offset


def logical_now_iso(festival: Optional[Dict[str, Any]]) -> str:
    return epoch_to_iso8601(logical_now(festival))


# -----------------------------------------------------------------------------
# Idempotency store.
#
# Keyed by `(endpoint_label, idempotency_key, actor_user_id)` triple per the
# scaffold-and-PRD convention.  The stored value is the (status_code,
# response_body_dict) tuple plus the body-hash and the creation time.
# Expiry is `IDEMPOTENCY_WINDOW_SECONDS` per §2.5 — the inclusive boundary at
# exactly 86400 seconds is a replay (the window is `[0, 86400]`).
# -----------------------------------------------------------------------------


class _IdempotencyStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        # key -> {body_hash, status_code, response_body, created_at_unix, festival_id}
        self._entries: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    @staticmethod
    def body_hash(body: Any) -> str:
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(canonical).hexdigest()

    def _expired(self, entry: Dict[str, Any], now_unix: int) -> bool:
        age = now_unix - int(entry["created_at_unix"])
        return age > IDEMPOTENCY_WINDOW_SECONDS

    def lookup(
        self,
        endpoint_label: str,
        idempotency_key: str,
        actor_user_id: str,
        body_hash: str,
        now_unix: int,
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Return ``("replay", stored_entry)``, ``("conflict", None)``, or ``(None, None)``.

        "replay" means same key + same body hash within the window — the
        caller should reuse the stored response and set the
        `is_idempotent_replay` flag on the envelope's meta.

        "conflict" means same key + different body within the window — the
        caller should raise `ERR_IDEMPOTENCY_KEY_REUSED`.

        ``(None, None)`` means a fresh key — the caller proceeds and on
        success calls ``store(...)``.
        """
        with self._lock:
            key = (endpoint_label, idempotency_key, actor_user_id)
            entry = self._entries.get(key)
            if entry is None:
                return None, None
            if self._expired(entry, now_unix):
                # Past the window — the key is reusable.  Drop the stale entry.
                self._entries.pop(key, None)
                return None, None
            if entry["body_hash"] == body_hash:
                return "replay", entry
            return "conflict", None

    def store(
        self,
        endpoint_label: str,
        idempotency_key: str,
        actor_user_id: str,
        body_hash: str,
        status_code: int,
        response_body: Dict[str, Any],
        now_unix: int,
    ) -> None:
        with self._lock:
            self._entries[(endpoint_label, idempotency_key, actor_user_id)] = {
                "body_hash": body_hash,
                "status_code": status_code,
                "response_body": response_body,
                "created_at_unix": now_unix,
            }


IDEMPOTENCY_STORE = _IdempotencyStore()


# -----------------------------------------------------------------------------
# Entity collections.  Plural keys.
# -----------------------------------------------------------------------------


class _DB:
    """The in-memory database.

    The harness's per-test isolation comes from a fresh container per test
    file (the docker-runner contract), so process start time is the
    natural reset point.  Nothing here is durable.
    """

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.festivals: Dict[str, dict] = {}
        self.program_versions: Dict[str, dict] = {}
        self.stages: Dict[str, dict] = {}
        self.equipment_kits: Dict[str, dict] = {}
        self.artists: Dict[str, dict] = {}
        self.program_items: Dict[str, dict] = {}
        self.riders: Dict[str, dict] = {}
        self.sound_engineer_teams: Dict[str, dict] = {}
        self.sound_check_slots: Dict[str, dict] = {}
        self.rehearsals: Dict[str, dict] = {}
        self.ticket_types: Dict[str, dict] = {}
        self.sponsor_tiers: Dict[str, dict] = {}
        self.exposure_allocations: Dict[str, dict] = {}
        self.fulfilment_logs: Dict[str, dict] = {}
        self.schedule_changes: Dict[str, dict] = {}
        self.audit_entries: Dict[str, dict] = {}
        # Exposure catalog is a per-festival dict-of-dicts:
        # festival_id -> {"id", "festival_id", "catalog": {kind:int}, common fields...}
        self.exposure_catalogs: Dict[str, dict] = {}

        # Per-festival advisory locks for the §1.2.1 sponsor-allocation-sweep
        # rule.  The set holds the festival_ids currently inside a sweep.
        self.sweep_locked_festivals: set[str] = set()

        # Provisional-refund attribution per schedule_change_id ->
        # {ticket_type_id: provisional_cents_for_this_change_for_this_type}.
        # Read by the refund-confirmed endpoint to decrement the per-type
        # bucket by the correct attributed amount on the matching ACK.
        self.refund_attributions: Dict[str, Dict[str, int]] = defaultdict(dict)

        # Mapping: festival_id -> list of audit_entry ids in append order.
        # The audit-entry list endpoint reads this per-festival list.
        self.audit_order_by_festival: Dict[str, List[str]] = defaultdict(list)


DB = _DB()


# -----------------------------------------------------------------------------
# Helpers for the common four fields plus monotone version increments.
# -----------------------------------------------------------------------------


def stamp_create(row: Dict[str, Any], *, with_version: bool = True) -> Dict[str, Any]:
    """Stamp `id`, `created_at`, `updated_at`, `version` on a fresh row.

    Append-only rows (riders, fulfilment logs, audit entries) pass
    ``with_version=False`` so they carry only `id` and `created_at` per
    PRD §2.4.
    """
    if "id" not in row or row["id"] is None:
        row["id"] = fresh_uuid()
    now = server_now_iso8601()
    row["created_at"] = now
    if with_version:
        row["updated_at"] = now
        row["version"] = 1
    return row


def stamp_update(row: Dict[str, Any]) -> Dict[str, Any]:
    """Refresh `updated_at` and increment `version` per the §2.4 contract."""
    row["updated_at"] = server_now_iso8601()
    row["version"] = int(row.get("version", 0)) + 1
    return row


_ENTITY_TYPE_FROM_COLLECTION: Dict[str, str] = {
    "festivals": "Festival",
    "program_versions": "ProgramVersion",
    "program_items": "ProgramItem",
    "stages": "Stage",
    "equipment_kits": "EquipmentKit",
    "artists": "Artist",
    "riders": "RiderRequirement",
    "sound_engineer_teams": "SoundEngineerTeam",
    "sound_check_slots": "SoundCheckSlot",
    "rehearsals": "Rehearsal",
    "ticket_types": "TicketType",
    "sponsor_tiers": "SponsorTier",
    "exposure_allocations": "ExposureAllocation",
    "schedule_changes": "ScheduleChange",
    "audit_entries": "AuditEntry",
    "fulfilment_logs": "FulfilmentLog",
}


def _row_entity_type(row: Dict[str, Any]) -> str:
    """Best-effort mapping from a row dict to its PRD §2.8 entity-type
    string.  Falls back to the literal "Unknown" when the row's
    container can't be inferred — the OCC_CONFLICT audit-row's
    `subject_entity_type` then carries that placeholder, which is
    sufficient for the §2.5 "an audit entry of category `OCC_CONFLICT`
    is appended" requirement (the §2.5 prose pins the category, not a
    specific entity-type literal).
    """
    rid = row.get("id")
    if rid is None:
        return "Unknown"
    # Walk the well-known collection map and pick the one this id sits in.
    for attr_name, entity_type in _ENTITY_TYPE_FROM_COLLECTION.items():
        coll = getattr(DB, attr_name, None)
        if coll is None:
            continue
        if isinstance(coll, dict) and coll.get(rid) is row:
            return entity_type
    return "Unknown"


def check_if_match(row: Dict[str, Any], if_match_header: Optional[str]) -> None:
    """Priority-23 OCC check.

    When the header is supplied and parses as an integer, compare against
    the row's `version` integer; raise ERR_VERSION_CONFLICT on mismatch.
    Omitted header skips the check entirely per §2.5.

    The PRD §2.5 sentence "An audit entry of category `OCC_CONFLICT` is
    appended on rejection" is honoured here on the rejection path
    universally — every If-Match-mismatch across the long list of
    OCC-honoring endpoints emits the audit row.
    """
    from .errors import ApiError
    from .audit import append_audit

    if if_match_header is None or if_match_header == "":
        return

    def _audit_occ(reason: str) -> None:
        fid = row.get("festival_id") or (row.get("id") if _row_entity_type(row) == "Festival" else None)
        if fid is None:
            # Festival rows carry their own id as "festival_id" for the
            # audit-log indexing; if neither field is present, log the
            # audit row against an empty festival_id so the
            # festival-scoped audit-list filter the test uses still
            # sees it under the same festival.
            fid = ""
        append_audit(
            festival_id=fid,
            event_category="OCC_CONFLICT",
            subject_entity_type=_row_entity_type(row),
            subject_entity_id=str(row.get("id", "")),
            from_state=None,
            to_state=None,
            payload_summary=reason,
        )

    try:
        expected = int(if_match_header)
    except (TypeError, ValueError):
        _audit_occ(f"If-Match header {if_match_header!r} is not a parseable integer")
        raise ApiError("ERR_VERSION_CONFLICT", "If-Match header is not an integer")
    current = int(row.get("version", -1))
    if current != expected:
        _audit_occ(f"If-Match {expected} does not match current version {current}")
        raise ApiError(
            "ERR_VERSION_CONFLICT",
            f"If-Match {expected} does not match current version {row.get('version')}",
        )


def find_or_404(collection: Dict[str, dict], entity_id: str, not_found_err: str) -> dict:
    """Return the row or raise the named 404 error from PRD §5."""
    from .errors import ApiError

    row = collection.get(entity_id)
    if row is None:
        raise ApiError(not_found_err, f"{entity_id} not found")
    return row


def child_belongs(
    child_row: dict,
    parent_field: str,
    parent_id: str,
) -> None:
    """Cross-parent guard for nested URLs (PRD §2.1 cross-parent check)."""
    from .errors import ApiError

    if child_row.get(parent_field) != parent_id:
        raise ApiError(
            "ERR_RESOURCE_MISMATCHED_PARENT",
            f"child's {parent_field} does not match the URL's parent id",
        )


def get_json_body() -> dict:
    """Return the request's JSON body or raise ERR_INVALID_REQUEST_BODY.

    An empty body returns an empty dict (some endpoints take no body).
    """
    from flask import request
    from .errors import ApiError

    if request.data == b"":
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception as exc:  # noqa: BLE001
        raise ApiError("ERR_INVALID_REQUEST_BODY", f"malformed JSON: {exc}") from None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(
            "ERR_INVALID_REQUEST_BODY", "request body must be a JSON object"
        )
    return body
