"""Lookups and the cascades of PRD 2.6.

A cascade hop is caused by the mutation the previous hop performed, and every
intermediate row is written with its own version bump. The deepest chain is the
five-level media-fill failure:

  media fill FAILED
    -> suite aseptic_qualification_status INVALIDATED  (posture FROZEN)
      -> live batches SUSPENDED / QUARANTINED
        -> their RESERVED reservations RELEASED
          -> lots un-EXHAUSTED
"""

from common import ApiError, add_days, clock_now
from store import (
    DB,
    batches_of_project,
    batches_of_suite,
    by_created,
    deviations_of_batch,
    quals_of_suite,
    reservations_of_batch,
    review_of_batch,
    set_raw,
    touch,
)
import calc

# --------------------------------------------------------------------------
# Lookups (PRD 2.11 - the same codes serve path ids and body foreign keys)
# --------------------------------------------------------------------------

_NOT_FOUND = {
    "project": "ERR_CLIENT_PROJECT_NOT_FOUND",
    "suite": "ERR_FILLING_SUITE_NOT_FOUND",
    "media_fill": "ERR_MEDIA_FILL_NOT_FOUND",
    "qualification": "ERR_QUALIFICATION_NOT_FOUND",
    "batch": "ERR_BATCH_ORDER_NOT_FOUND",
    "lot": "ERR_COMPONENT_LOT_NOT_FOUND",
    "reservation": "ERR_RESERVATION_NOT_FOUND",
    "ipc": "ERR_IN_PROCESS_CHECK_NOT_FOUND",
    "em_sample": "ERR_EM_SAMPLE_NOT_FOUND",
    "deviation": "ERR_DEVIATION_NOT_FOUND",
    "review": "ERR_BR_REVIEW_NOT_FOUND",
    "engagement": "ERR_AUDIT_ENGAGEMENT_NOT_FOUND",
}

_COLLECTIONS = {
    "project": "projects",
    "suite": "suites",
    "media_fill": "media_fills",
    "qualification": "quals",
    "batch": "batches",
    "lot": "lots",
    "reservation": "reservations",
    "ipc": "ipcs",
    "em_sample": "em_samples",
    "deviation": "deviations",
    "review": "reviews",
    "engagement": "engagements",
}


def require(kind, row_id):
    collection = getattr(DB, _COLLECTIONS[kind])
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(_NOT_FOUND[kind], 404, "The addressed %s does not exist." % kind)
    return row


def state_conflict(error_id, message=None):
    return ApiError(error_id, 409, message)


# --------------------------------------------------------------------------
# Component ledger hops
# --------------------------------------------------------------------------


def restore_lot_availability(lot, quantity):
    """Hand units back to a lot and un-exhaust it if that lifts it above 0."""
    lot["quantity_available"] += quantity
    if lot["status"] == "EXHAUSTED" and lot["quantity_available"] > 0:
        lot["status"] = "RELEASED"
    touch(lot)


def draw_lot_availability(lot, quantity):
    lot["quantity_available"] -= quantity
    if lot["status"] == "RELEASED" and lot["quantity_available"] == 0:
        lot["status"] = "EXHAUSTED"
    touch(lot)


def release_reservations(batch, reason):
    """Every RESERVED reservation of the batch goes back to its lot."""
    for res in reservations_of_batch(batch["id"]):
        if res["status"] != "RESERVED":
            continue
        res["status"] = "RELEASED"
        res["released_reason"] = reason
        touch(res)
        lot = DB.lots.get(res["component_lot_id"])
        if lot is not None:
            restore_lot_availability(lot, res["quantity_reserved"])


def consume_reservations(batch):
    """Fill completion retires the units without moving quantity_available."""
    for res in reservations_of_batch(batch["id"]):
        if res["status"] != "RESERVED":
            continue
        res["status"] = "CONSUMED"
        touch(res)


def reserved_unit_total(batch_id):
    total = 0
    for res in DB.reservations.values():
        if res["batch_order_id"] == batch_id and res["status"] == "RESERVED":
            total += res["quantity_reserved"]
    return total


# --------------------------------------------------------------------------
# Suspension / restoration hops
# --------------------------------------------------------------------------


def suspend_batch(batch, reason):
    batch["production_status"] = "SUSPENDED"
    if batch["quality_status"] not in ("RELEASED", "REJECTED"):
        batch["quality_status"] = "QUARANTINED"
    touch(batch)
    release_reservations(batch, reason)


def suspend_suite_batches(suite):
    """Hop 3 of the freeze cascade: SCHEDULED or SETUP batches of this suite."""
    for batch in batches_of_suite(suite["id"]):
        if batch["production_status"] in ("SCHEDULED", "SETUP"):
            suspend_batch(batch, "SUITE_FREEZE_SUSPENSION")


def suspend_project_batches(project):
    """The project-hold arm of the critical-deviation cascade."""
    for batch in batches_of_project(project["id"]):
        if batch["production_status"] in ("SCHEDULED", "SETUP"):
            suspend_batch(batch, "SUITE_FREEZE_SUSPENSION")


def restore_suite_batches(suite):
    """SUSPENDED -> SCHEDULED on requalification (project must be ACTIVE)."""
    if calc.suite_posture(suite) == "FROZEN":
        return
    for batch in batches_of_suite(suite["id"]):
        if batch["production_status"] != "SUSPENDED":
            continue
        project = DB.projects.get(batch["client_project_id"])
        if project is None or project["status"] != "ACTIVE":
            continue
        batch["production_status"] = "SCHEDULED"
        touch(batch)


def restore_project_batches(project):
    """SUSPENDED -> SCHEDULED on hold release (suite must not be FROZEN)."""
    for batch in batches_of_project(project["id"]):
        if batch["production_status"] != "SUSPENDED":
            continue
        suite = DB.suites.get(batch["suite_id"])
        if suite is not None and calc.suite_posture(suite) == "FROZEN":
            continue
        batch["production_status"] = "SCHEDULED"
        touch(batch)


# --------------------------------------------------------------------------
# Media-fill outcome branches (PRD 3.2)
# --------------------------------------------------------------------------


def qualify_suite_from_media_fill(media_fill, suite):
    """The PASSED branch: qualify, stamp validity, requalify if invalidated."""
    was_invalidated = suite["aseptic_qualification_status"] == "INVALIDATED"
    if was_invalidated:
        invalidated_at = suite.get("_invalidated_read_at")
        run_date = media_fill["scheduled_run_date"]
        if invalidated_at is not None and (run_date is None or run_date <= invalidated_at):
            # Not an eligible requalification: the simulation still passes but
            # the suite is left exactly as it was.
            return False
    suite["aseptic_qualification_status"] = "QUALIFIED"
    suite["media_fill_valid_until"] = add_days(
        media_fill["read_at"], calc.MEDIA_FILL_VALIDITY_DAYS
    )
    suite["_raw"].pop("media_fill_valid_until", None)
    touch(suite)
    if was_invalidated:
        suite["_invalidated_read_at"] = None
        restore_suite_batches(suite)
    return True


def fail_suite_from_media_fill(media_fill, suite):
    """The FAILED branch: the full depth-five cascade plus revocations."""
    suite["aseptic_qualification_status"] = "INVALIDATED"
    suite["media_fill_valid_until"] = None
    suite["_raw"].pop("media_fill_valid_until", None)
    suite["_invalidated_read_at"] = media_fill.get("read_at")
    touch(suite)
    suspend_suite_batches(suite)
    revoke_qualifications_citing(media_fill)


def revoke_qualifications_citing(media_fill):
    rows = [
        q
        for q in DB.quals.values()
        if q["media_fill_id"] == media_fill["id"] and q["status"] == "QUALIFIED"
    ]
    for qual in by_created(rows):
        qual["status"] = "REVOKED"
        touch(qual)


# --------------------------------------------------------------------------
# ACTION excursion reach into the quality axis (PRD 3.7)
# --------------------------------------------------------------------------


def demote_qp_review_batches(suite):
    for batch in batches_of_suite(suite["id"]):
        if batch["quality_status"] != "QP_REVIEW":
            continue
        batch["quality_status"] = "BR_REVIEW"
        touch(batch)
        reopen_review(batch)


def reopen_review(batch):
    review = review_of_batch(batch["id"])
    if review is None or review["status"] != "CLOSED":
        return
    review["status"] = "COMPLETE_WITH_FINDINGS"
    review["open_findings_count"] += 1
    review["closed_at"] = None
    review["_raw"].pop("closed_at", None)
    touch(review)


# --------------------------------------------------------------------------
# Critical-deviation cascade (PRD 3.7)
# --------------------------------------------------------------------------


def critical_deviation_cascade(deviation):
    batch = DB.batches.get(deviation["batch_order_id"])
    if batch is None:
        return
    was_br_review = batch["quality_status"] == "BR_REVIEW"
    if batch["quality_status"] not in ("RELEASED", "REJECTED"):
        batch["quality_status"] = "QUARANTINED"
        touch(batch)
        if was_br_review:
            reopen_review(batch)
    project = DB.projects.get(batch["client_project_id"])
    if project is not None and project["status"] == "ACTIVE":
        project["status"] = "ON_HOLD"
        touch(project)
        suspend_project_batches(project)


def maybe_close_quarantine_loop(batch):
    """After an approved CAPA closes the last open deviation of the batch."""
    if batch is None:
        return
    for dev in deviations_of_batch(batch["id"]):
        if dev["status"] != "CLOSED":
            return
    if batch["quality_status"] != "QUARANTINED":
        return
    if batch["production_status"] != "FILLED":
        return
    suite = DB.suites.get(batch["suite_id"])
    if suite is not None and calc.suite_posture(suite) == "FROZEN":
        return
    batch["quality_status"] = "BR_REVIEW"
    touch(batch)


# --------------------------------------------------------------------------
# Clock movement (PRD 2.4)
# --------------------------------------------------------------------------


def apply_clock_move(new_now):
    lapsed = 0
    expired = 0
    quals = [
        q
        for q in DB.quals.values()
        if q["status"] == "QUALIFIED" and q["expires_on"] is not None
        and q["expires_on"] <= new_now
    ]
    quals.sort(key=lambda q: (q["expires_on"], q["created_at"], q["_seq"]))
    for qual in quals:
        qual["status"] = "LAPSED"
        touch(qual)
        lapsed += 1
    lots = [
        l
        for l in DB.lots.values()
        if l["status"] in ("RELEASED", "EXHAUSTED") and l["sterilization_expiry"] is not None
        and l["sterilization_expiry"] <= new_now
    ]
    lots.sort(key=lambda l: (l["sterilization_expiry"], l["created_at"], l["_seq"]))
    for lot in lots:
        lot["status"] = "EXPIRED"
        lot["quantity_available"] = 0
        touch(lot)
        expired += 1
    return lapsed, expired
