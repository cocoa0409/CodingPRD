"""The Idempotency-Key registry for the GPS-report ingest endpoint.

The PRD §2.10's idempotency contract — "the optional request header
`Idempotency-Key` is a deduplication slot key scoped per parent trip" — is
implemented as a module-level dict keyed by the pair `(trip_id, key)` whose
value is the tuple `(body_hash, cached_response_payload, cached_status_code)`.

The contract's behavior is:
  - Header absent:
        no slot consultation; the request proceeds as a fresh insert and is
        not recorded in the registry.
  - Header present and the `(trip_id, key)` slot is empty:
        the request proceeds as a fresh insert; on success the response's
        payload and status are written into the slot, keyed by the request
        body's hash. The on-disk GPS-report-and-auto-penalty side-effects
        happen as the gps-ingest's transaction commits.
  - Header present and the slot is full with a `body_hash` matching the
    current request's body-hash:
        the request is a replay; the cached response payload is returned with
        the cached HTTP status (201 from the original `POST` ingestion) and
        a `meta.replayed = True` flag is added to the response envelope so
        the client can observe the replay had no fresh effect. No new row is
        inserted, the parent trip's `latest_gps_at` and `gps_violation_count`
        are not touched, no new auto-Penalty rows are written.
  - Header present and the slot is full with a `body_hash` not matching the
    current request's body-hash:
        the request is the "same key, different body" race the
        §2.10 H3 paragraph names; the response is the 409
        `ERR_IDEMPOTENCY_KEY_REUSED` error with no on-disk side-effect.

The body-hash is SHA-256 over the canonical-JSON-serialized request body
(after the body-shape validation has parsed the body but before the
business-rule validations have evaluated). The canonicalization is the
standard `json.dumps(body, sort_keys=True, separators=(",", ":"))` form so
two requests with the same JSON-payload-after-key-reordering-and-whitespace-
normalization map to the same hash.

The registry's GC contract per the scaffold's §1.0 idempotency block is
"the slot's lifetime is the trip's lifetime; the scaffold does not pin a
slot-GC window because no test exercises a stale-slot revival". The
in-memory dict grows monotonically across the run, which is fine for the
test-harness's bounded test-case sizes. A real-world deployment would add a
TTL-based eviction.

The reset hook `init_idempotency_registry()` is called at app-startup and
by the `/v1/_admin/reset` test-harness endpoint to wipe the registry between
tests.
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any


_LOCK = threading.RLock()
# The slot key is the `(trip_id, idempotency_key)` tuple of strings; the
# slot value is the `(body_hash, response_payload, http_status)` tuple. The
# response_payload is the JSON-serializable Python object representing the
# response's `data` field (the GPSReport row that the original ingest
# inserted, with the `auto_penalty_ids` array and the cascade-summary
# sub-object the standard gps-ingest response embeds).
_SLOTS: dict[tuple[str, str], tuple[str, Any, int]] = {}


def init_idempotency_registry() -> None:
    """Clear the registry. Called at app startup and on `/v1/_admin/reset`."""
    with _LOCK:
        _SLOTS.clear()


def hash_body(body: dict[str, Any]) -> str:
    """Canonical SHA-256 of the JSON-serialized body. The canonicalization
    is `sort_keys=True, separators=(",", ":")` for the byte-for-byte stable
    encoding regardless of the original ordering or whitespace.
    """
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return h


def lookup_slot(trip_id: str, key: str) -> tuple[str, Any, int] | None:
    """Return the slot's stored tuple `(body_hash, response_payload,
    http_status)`, or None if the slot is empty. The lookup is under the
    module-level lock so a concurrent write does not tear the read.
    """
    with _LOCK:
        return _SLOTS.get((trip_id, key))


def write_slot(
    trip_id: str,
    key: str,
    body_hash: str,
    response_payload: Any,
    http_status: int,
) -> None:
    """Store the slot's triple — body hash, the response payload to replay
    on a future matching-hash retry, and the HTTP status code of the
    original response. The standard original status for the gps-ingest is
    201. The caller fills the cached response with the canonical envelope's
    `data` sub-object so a replay returns the bytes-identical body modulo
    the new request's `meta.api_request_id` and `meta.api_request_timestamp`
    fields (which the envelope-shaper rewrites on each response regardless
    of whether the payload is a fresh insert or a cached replay) and the
    presence of the `meta.replayed = True` flag.
    """
    with _LOCK:
        _SLOTS[(trip_id, key)] = (body_hash, response_payload, http_status)
