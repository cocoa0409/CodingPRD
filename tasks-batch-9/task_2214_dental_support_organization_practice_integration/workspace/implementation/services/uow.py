"""Unit of work for mutating requests.

PRD 2.4 says `version` increments and `updated_at` refreshes on *every* mutation
of a row, "including mutations that only change a derived counter or a derived
enum", and PRD 2.7 says a cascade hop bumps every row it touches, not just the
addressed row. Both are honoured here:

  * `touch()` records an explicit mutation (state writes),
  * `begin()` fingerprints the derived surface of every existing row,
  * `finalize()` re-runs the derived state machine (posture freeze/release,
    contract credentialing edges, credentialing rollup, measurement state) and
    then bumps exactly once every row whose derived surface moved without an
    explicit touch.

A row is therefore never bumped twice in one request, and a counter can never
drift from the rows it summarises.
"""

from flask import g

import clock
import db
from services import derive


def begin():
    g.touched = set()
    g.dirty = set()
    snapshot = {}
    for kind in derive.DERIVED_KINDS:
        for row in db.store[kind].values():
            snapshot[(kind, row["id"])] = derive.fingerprint(kind, row)
    g.snapshot = snapshot


def _key(row):
    return (row["_kind"], row["id"])


def touch(row):
    """Explicit mutation: refresh updated_at and bump version, at most once."""
    key = _key(row)
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    if key in touched:
        row["updated_at"] = clock.now()
        return row
    touched.add(key)
    if "version" in row:
        row["version"] += 1
    if "updated_at" in row:
        row["updated_at"] = clock.now()
    return row


def mark_dirty(row):
    """A derived-state write made by finalize(); bumped unless already touched."""
    getattr(g, "dirty", set()).add(_key(row))


# ----------------------------------------------------------- derived cascades


def _apply_posture_effects():
    """Freeze parks scheduled windows and open enrollments; release restores them."""
    for practice in db.all_rows("practices"):
        frozen = derive.integration_posture(practice) == "FROZEN"
        if frozen:
            for batch in derive.batches_of_practice(practice["id"]):
                if batch["status"] == "SCHEDULED":
                    batch["status"] = "HELD"
                    mark_dirty(batch)
            for enrollment in derive.enrollments_of_practice(practice["id"]):
                if enrollment["status"] == "SUBMITTED":
                    enrollment["status"] = "SUSPENDED"
                    mark_dirty(enrollment)
            # The reverse credentialing edge exists only for a posture freeze.
            for contract in derive.contracts_of_practice(practice["id"]):
                if (
                    contract["transition_state"] == "PENDING_CREDENTIALING"
                    and derive.enrollment_open_count(contract) == 0
                    and not derive.contract_has_approved_enrollment(contract)
                ):
                    contract["transition_state"] = "LEGACY"
                    mark_dirty(contract)
        else:
            for batch in derive.batches_of_practice(practice["id"]):
                if batch["status"] == "HELD":
                    batch["status"] = "SCHEDULED"
                    mark_dirty(batch)
            for enrollment in derive.enrollments_of_practice(practice["id"]):
                if enrollment["status"] == "SUSPENDED":
                    enrollment["status"] = "SUBMITTED"
                    mark_dirty(enrollment)


def _apply_contract_forward_edge():
    """LEGACY -> PENDING_CREDENTIALING whenever enrollment_open_count leaves zero."""
    for contract in db.all_rows("payer_contracts"):
        if (
            contract["transition_state"] == "LEGACY"
            and derive.enrollment_open_count(contract) > 0
        ):
            contract["transition_state"] = "PENDING_CREDENTIALING"
            mark_dirty(contract)


def _apply_credentialing_rollup():
    for employment in db.all_rows("doctor_employments"):
        rollup = derive.credentialing_rollup(employment)
        if employment["credentialing_status"] != rollup:
            employment["credentialing_status"] = rollup
            mark_dirty(employment)


def _apply_measurement_state():
    """A frozen practice suspends its affiliation's earn-out measurement window."""
    for affiliation in db.all_rows("affiliations"):
        if affiliation["status"] != "CLOSED":
            continue
        frozen = any(
            derive.integration_posture(practice) == "FROZEN"
            for practice in derive.practices_of_affiliation(affiliation["id"])
        )
        desired = "SUSPENDED" if frozen else "OPEN"
        if affiliation["earnout_measurement_state"] != desired:
            affiliation["earnout_measurement_state"] = desired
            mark_dirty(affiliation)


def finalize():
    _apply_posture_effects()
    _apply_contract_forward_edge()
    _apply_credentialing_rollup()
    _apply_measurement_state()

    snapshot = getattr(g, "snapshot", {})
    touched = getattr(g, "touched", set())
    dirty = getattr(g, "dirty", set())
    for kind in derive.DERIVED_KINDS:
        for row in list(db.store[kind].values()):
            key = (kind, row["id"])
            if key in touched or key not in snapshot:
                continue
            if key in dirty or derive.fingerprint(kind, row) != snapshot[key]:
                touch(row)
    # Rows that only carry a state write made by finalize (enrollments, batches).
    for key in list(dirty):
        if key in touched:
            continue
        kind, row_id = key
        row = db.get(kind, row_id)
        if row is not None:
            touch(row)
