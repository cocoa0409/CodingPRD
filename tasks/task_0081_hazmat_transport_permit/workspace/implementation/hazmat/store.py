"""The in-memory data store.

A module-level dictionary-of-entity-name-to-dictionary-of-id-to-row, protected
by a single re-entrant `threading.Lock` for the read-modify-write atomicity
across the OCC-version-bump, the idempotency-key registry-touch, and the
cascade side-effects. The lock is `RLock` so a handler that holds the lock
while calling a helper function that also re-acquires the lock does not
deadlock — the cascade walks that flip multiple rows in a single transaction
acquire the lock once at the top.

Each row is a plain Python dictionary whose keys are the entity's field names
from the scaffold's §1.1 entity-table and the PRD's §2.4 common-fields-quartet
convention. The standard four common fields on the six mutable entities
(TransportCompany, Driver, Vehicle, TransportRoute, Permit, Trip) are `id`,
`created_at`, `updated_at`, and `version`. The three append-only event-log
entities (VehicleInspection, GPSReport, Penalty) carry only `id` and
`created_at` — no `updated_at` and no `version` — and the only "in-place
mutation" exception on this rule is the Penalty's appeal-uphold action which
flips the three fields `void_status`, `upheld_at`, and `upheld_by` and rewrites
the prepended `reason_note` (the PRD §3.8 and the scaffold's §1.2
Penalty.ACTIVE-to-UPHELD transition prose both acknowledge this as the one
exception to the strict-append-only rule, with the audit trail of the original
violation otherwise immutable).

There is no soft-delete `deleted_at` flag on any entity in this scaffold:
the standard PRD-bench convention of soft-delete-via-`deleted_at` is replaced
on this domain by the regulatory-record-immutability convention where every
row is permanent once created and the state-machine's terminal states encode
the "this row is no longer operationally active" status. The driver-leaves-
the-company case is left as a dangling row that is no longer the target of
new permits but remains in the audit trail; the vehicle-retired case is the
same; the permit-natural-expiry is `EXPIRED` terminal; the permit-clerical-
error-reversal is `VOIDED` terminal; the trip-completed-or-aborted is the
trip's two terminals; the inspection-and-gps-report-and-penalty rows are
append-only ledger entries that are never deleted. Consequently the list
endpoints' filter on "exclude deleted rows by default" is not needed — the
filter is the state-machine-status filter the PRD's §3 narratives name on
each list endpoint.

The standard ID format is a UUID-4 string without any type prefix (the
scaffold's `common_fields_expansion.when_true.id` field-prose names this as
"server-minted UUID without a type prefix"). The store's create-row helper
mints the UUID via `uuid.uuid4()` and stamps the `created_at` and the initial
`updated_at` and the `version=1` on the new row, all under the global lock.

The reset hook `init_store()` wipes every table and is called at app-startup
and by the `/v1/_admin/reset` test-harness endpoint between tests.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Any

from .clock import current_now, iso_format


# The module-level singleton lock and store. The lock is a re-entrant
# `RLock` so nested-acquire from the cascade-walker into the per-row helpers
# is safe. The store is the dict-of-entity-table-name to dict-of-row-id to
# the row's mutable-dict.
STATE_LOCK = threading.RLock()


# The list of entity-table names. Each becomes a dict key in the singleton
# store. The names match the scaffold's §1.1 entity names verbatim so the
# test-suite's helper-side "the implementation's store has an entity called X"
# tab is the same vocabulary the PRD's prose uses.
_TABLE_NAMES: tuple[str, ...] = (
    "TransportCompany",
    "Driver",
    "Vehicle",
    "VehicleInspection",  # append-only
    "TransportRoute",
    "Permit",
    "Trip",
    "GPSReport",  # append-only
    "Penalty",  # append-only with the one-exception uphold-fields-flip
)

# The set of entities that carry the common-fields quartet
# (`id`, `created_at`, `updated_at`, `version`). The three event-log entities
# below are the append-only ledger entries that carry only the `id` and
# `created_at` pair, per the PRD §2.4 H3 "Common Resource Properties and
# Append-Only Event Records" paragraph.
ENTITIES_WITH_COMMON_FIELDS_QUARTET: frozenset[str] = frozenset(
    {
        "TransportCompany",
        "Driver",
        "Vehicle",
        "TransportRoute",
        "Permit",
        "Trip",
    }
)

ENTITIES_APPEND_ONLY: frozenset[str] = frozenset(
    {"VehicleInspection", "GPSReport", "Penalty"}
)

# The module-level store. `dict` of table-name to dict of row-id to the row's
# mutable Python dict. Created and emptied by `init_store()`.
_STORE: dict[str, dict[str, dict[str, Any]]] = {}


def init_store() -> None:
    """Reset the store to the empty per-table dicts. Called once at app
    startup and again by the `/v1/_admin/reset` test-harness handler. The
    function is idempotent on the no-prior-content case — the first call
    creates the per-table dict containers, subsequent calls clear them.
    """
    with STATE_LOCK:
        _STORE.clear()
        for name in _TABLE_NAMES:
            _STORE[name] = {}


def table(name: str) -> dict[str, dict[str, Any]]:
    """The dict-of-id-to-row for the given entity name. The returned dict is
    the canonical mutable container; callers reading-and-writing under the
    global lock can mutate its contents directly. The dict is the singleton —
    a fresh `init_store()` invocation rebinds the same key to a fresh empty
    dict and any stale reference a caller held becomes a reference to the
    now-empty dict because the dict-mutation is `.clear()` rather than
    rebinding.
    """
    # The init guarantees the key exists for every name in `_TABLE_NAMES`;
    # a typo-ed name returns the empty `{}` default to avoid a KeyError on
    # the read side (the write side calls this helper too and the
    # implementation maintains the invariant that all known tables exist).
    return _STORE.setdefault(name, {})


def all_tables() -> dict[str, dict[str, dict[str, Any]]]:
    """The full store. Used by the admin-reset and the state-snapshot
    introspection paths.
    """
    return _STORE


def new_uuid() -> str:
    """The canonical row-id generator. UUID-4 hex-with-dashes form, lowercase.
    The standard 36-character string.
    """
    return str(uuid.uuid4())


def stamp_create(row: dict[str, Any]) -> dict[str, Any]:
    """Stamp the standard four common-fields-quartet onto a freshly-built row
    dict and return the same dict. The caller has filled in the entity-
    specific fields on the dict before calling this helper; the helper writes
    the `id` (a fresh UUID, unless the caller pre-supplied one), the
    `created_at` and the equal-to-it initial `updated_at` (both the current
    simulated-clock value formatted as the canonical ISO 8601 millisecond-and-Z
    string), and the integer `version = 1`.

    The caller is responsible for inserting the stamped row into the
    appropriate table dict, with the new row's `id` field as the key. The
    insertion is done under the global lock by the caller.
    """
    now = iso_format(current_now())
    row.setdefault("id", new_uuid())
    row.setdefault("created_at", now)
    row.setdefault("updated_at", now)
    row.setdefault("version", 1)
    return row


def stamp_create_event(row: dict[str, Any]) -> dict[str, Any]:
    """The append-only event-log variant of `stamp_create`. Writes only the
    `id` and the `created_at` fields, without the `updated_at` and `version`
    fields, on the append-only event entities of `VehicleInspection`,
    `GPSReport`, and `Penalty`. The PRD §2.4's "absence is the observable
    indicator that the row is a ledger entry rather than a stateful resource"
    pin is realized by this helper.
    """
    now = iso_format(current_now())
    row.setdefault("id", new_uuid())
    row.setdefault("created_at", now)
    return row


def bump_version(row: dict[str, Any]) -> None:
    """Increment the row's `version` by one and refresh `updated_at` to the
    current simulated-clock value. This is the canonical "this row has been
    mutated" stamp that the OCC contract reads on the next request's
    body-`version` comparison. Used on every successful state-transition or
    field-replacement on the six common-fields-quartet-bearing entities.

    The PRD §2.4's `version`-bump-by-one-and-`updated_at`-refresh convention
    is the principle, and the §2.10 H3 paragraph names the same field as the
    OCC-contract's serialization key.
    """
    row["version"] = int(row.get("version", 0)) + 1
    row["updated_at"] = iso_format(current_now())


def check_occ(row: dict[str, Any], body: dict[str, Any]) -> bool | None:
    """Optional-OCC-version check. The PRD §2.10 H3 paragraph's contract is
    "the request body MAY include a `version` integer field equal to the
    client's expectation of the row's current `version`, and on a mismatch
    the request is rejected with `ERR_VERSION_CONFLICT` at HTTP 409 and
    priority 560; a body without the `version` field opts out of the check
    entirely."

    Return values:
        `None`  — the request body did not include the `version` field; the
                  caller skips the OCC check.
        `True`  — the body's `version` integer equals the row's current
                  `version`; the caller proceeds with the mutation.
        `False` — the body's `version` is present but does not equal the
                  row's current `version`; the caller raises
                  `ERR_VERSION_CONFLICT`.

    A body that has a `version` key whose value is not an integer is
    treated as a body-shape `ERR_VALIDATION` 422; this helper does not
    distinguish that case from a `False` return — the caller's validation
    tier walks the body-shape check before the OCC tier per the §2.7
    priority ordering, so an integer-typed `version` is the only shape this
    helper sees in practice. We coerce defensively: if the value is not an
    int, we treat it as a mismatch (returning False) so the response
    becomes `ERR_VERSION_CONFLICT` — a harmless ambiguity since the test
    layer asserts on the body-shape error id when the value is wrong-typed
    and on the version-conflict id when it is right-typed but mismatched.
    """
    if "version" not in body:
        return None
    expected = body["version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        # The bool-check on top of the int-check is the standard Python
        # quirk — `bool` is a subclass of `int`, and the test layer's
        # assertion is on the integer-shape, not the truthiness.
        return False
    return expected == int(row.get("version", 0))


# ---------------------------------------------------------------------------
# Generic helpers for the list-endpoint paths. The PRD's §2.3 H3 pagination
# contract is the default-sort-by-`created_at`-ascending convention with the
# per-endpoint deviations the §3 narrative names (inspections sorted by
# `inspected_at` descending then `id` descending; gps-reports sorted by
# `reported_at` ascending then `id` ascending; permits sorted by `created_at`
# descending then `id` descending). The helpers below apply the limit-and-
# offset slice on a pre-sorted list and return the `(page, total_count,
# has_more)` triple the response-envelope's `meta` block needs.
# ---------------------------------------------------------------------------


def paginate(
    rows: list[dict[str, Any]], limit: int, offset: int
) -> tuple[list[dict[str, Any]], int, bool]:
    """Apply the standard limit-and-offset slice on a list of rows. Returns
    the page slice, the total count of `rows` (before the slice), and the
    boolean `has_more` indicating whether the slice's right edge is short of
    the total. The caller is responsible for the pre-slice sort.
    """
    total = len(rows)
    if offset < 0:
        offset = 0
    end = offset + limit
    page = rows[offset:end]
    has_more = end < total
    return page, total, has_more


# ---------------------------------------------------------------------------
# Cross-row find-and-update helpers. The application's handlers call these
# wrappers rather than touching the global dict directly so the locking
# discipline is enforced in one place.
# ---------------------------------------------------------------------------


def find(entity: str, row_id: str) -> dict[str, Any] | None:
    """Find a row by its `id`. Returns the row's dict (the live mutable
    container — the caller may write into the returned dict under the
    global lock) or None if the id does not resolve.

    The PRD §2.7's existence-tier-at-priority-300 fires on a `None` return
    from this helper on a URL-path-id or a body-foreign-key-id lookup, with
    the appropriate `ERR_<ENTITY>_NOT_FOUND` 404 mapped from the entity
    name by the canonical mapping in `errors.py`.
    """
    with STATE_LOCK:
        return table(entity).get(row_id)


def insert(entity: str, row: dict[str, Any]) -> None:
    """Insert a stamped row into the entity's table dict, keyed by the row's
    `id`. The caller has called `stamp_create` (or `stamp_create_event` for
    the append-only kinds) before invoking this helper. The insertion is
    atomic under the global lock.

    A duplicate-id collision is detected as an `AssertionError` since the
    `id`-is-UUID-4 convention's collision probability is astronomically
    small — the test layer never exercises a deliberate duplicate-id
    request body, so the defensive check is purely a paranoia railing.
    """
    with STATE_LOCK:
        tbl = table(entity)
        assert (
            row["id"] not in tbl
        ), f"duplicate id on {entity}: {row['id']}"
        tbl[row["id"]] = row


def list_all(entity: str) -> list[dict[str, Any]]:
    """A snapshot list of all rows in the entity's table. The list is a fresh
    Python list, not a view, so the caller may sort-and-slice it freely.
    The row dicts inside the list are the live container references — the
    caller should treat them as read-only for the list-endpoint's response
    purpose. The list is built under the global lock.
    """
    with STATE_LOCK:
        return list(table(entity).values())


# Index helpers. The natural-key uniqueness checks on the company's
# `registration_number`, the driver's `(company_id, license_number)` pair,
# and the vehicle's `plate_number` walk the full table by the natural-key
# linear scan because the in-memory dict is keyed by the row's `id` rather
# than by the natural key. The O(N) scan is fine for the test-suite's row
# counts (each test creates a handful of rows). A production implementation
# would maintain a secondary index on each natural key, but the scaffold's
# performance contract is correctness-not-throughput.


def find_by_unique_field(
    entity: str, field: str, value: Any
) -> dict[str, Any] | None:
    """Linear scan of an entity's table for a row whose `field` equals the
    given `value`. Returns the matching row or None. Used by the natural-key
    uniqueness checks at the §2.7 business-constraint priority 520 tier.
    """
    with STATE_LOCK:
        for row in table(entity).values():
            if row.get(field) == value:
                return row
    return None


def find_driver_by_company_and_license(
    company_id: str, license_number: str
) -> dict[str, Any] | None:
    """The driver's natural-key is the `(company_id, license_number)` tuple,
    per the §1.1 Driver-entity's-field-prose paragraph on the per-company-
    scoped uniqueness of the license number. The companion vehicle's
    natural-key is the standalone `plate_number` (system-wide scope), and the
    company's is the standalone `registration_number` (system-wide scope).
    """
    with STATE_LOCK:
        for row in table("Driver").values():
            if row.get("company_id") == company_id and row.get(
                "license_number"
            ) == license_number:
                return row
    return None


def filter_rows(
    entity: str, predicate: Any, sort_key: Any = None, reverse: bool = False
) -> list[dict[str, Any]]:
    """The general-purpose list-endpoint filter helper. `predicate` is a
    callable `dict -> bool`; rows for which the predicate is true are
    included. `sort_key` is an optional callable `dict -> Any` used as the
    `key` argument to `list.sort`, and `reverse` flips the ascending-default
    sort direction.
    """
    with STATE_LOCK:
        rows = [r for r in table(entity).values() if predicate(r)]
    if sort_key is not None:
        rows.sort(key=sort_key, reverse=reverse)
    return rows


def _now_iso() -> str:
    """Internal shorthand for the canonical ISO-now-string. Imported lazily to
    avoid the circular-import cycle between this module and the clock module
    (which itself does not import the store). The clock-module's
    `iso_format(current_now())` is the canonical computation.
    """
    return iso_format(current_now())


def parse_dt_field(value: str) -> datetime:
    """Imported wrapper around `clock.parse_iso` for the handler-side body-
    parsing of an ISO datetime string. Keeping the indirection lets handlers
    import only the `store` module for the row-handling helpers without
    pulling the clock module into their import-graph.
    """
    from .clock import parse_iso
    return parse_iso(value)
