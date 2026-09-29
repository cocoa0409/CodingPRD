"""Chart-migration batches: cutover windows and the conserved chart ledger (PRD 3.5)."""

from datetime import timedelta

from flask import Blueprint

import clock
import config
import db
import middleware
import payload
import support
from errors import ApiError, invalid
from services import calc, derive, uow

bp = Blueprint("batches", __name__)

READ_ROLES = (
    config.ROLE_INTEGRATION_LEAD,
    config.ROLE_DEAL_COUNSEL,
    config.ROLE_FINANCE_CONTROLLER,
)

BUFFER = timedelta(hours=config.CUTOVER_BUFFER_HOURS)


def _require_batch_status(batch, allowed, message):
    if batch["status"] not in allowed:
        raise ApiError("ERR_INVALID_BATCH_STATE", message)


@bp.post("/migration-batches")
@support.transactional
def create_batch():
    middleware.authorize([config.ROLE_INTEGRATION_LEAD])
    data = payload.body()
    practice = support.load_fk(data, "practice_id", "practices")
    payload.string(data, "practice_id")
    batch_label = payload.string(data, "batch_label")
    records_total = payload.integer(data, "records_total", minimum=1)
    expected_practice_version = payload.integer(data, "expected_practice_version")
    support.require_occ_practice(practice, expected_practice_version)

    # Every earlier STAGED batch of the practice is superseded, created_at ASC.
    for existing in derive.batches_of_practice(practice["id"]):
        if existing["status"] == "STAGED":
            existing["status"] = "SUPERSEDED"
            uow.touch(existing)

    row = db.insert(
        "migration_batches",
        {
            "practice_id": practice["id"],
            "batch_label": batch_label,
            "records_total": records_total,
            "records_validated": 0,
            "records_quarantined": 0,
            "status": "STAGED",
            "cutover_start_at": None,
            "cutover_end_at": None,
            "validation_error_rate_bps": None,
            "remediation_round": 0,
        },
    )
    uow.touch(practice)
    return "migration_batches", row, 201


@bp.get("/migration-batches/<migration_batch_id>")
def get_batch(migration_batch_id):
    middleware.authorize(READ_ROLES)
    row = support.load("migration_batches", migration_batch_id)
    return support.read_one("migration_batches", row)


@bp.get("/migration-batches")
def list_batches():
    middleware.authorize(READ_ROLES)
    rows = db.all_rows("migration_batches")
    rows = support.filter_rows(rows, "practice_id", payload.filter_value("practice_id"))
    rows = support.filter_rows(rows, "status", payload.filter_value("status"))
    return support.read_many("migration_batches", rows)


@bp.post("/migration-batches/<migration_batch_id>/schedule-cutover")
@support.transactional
def schedule_cutover(migration_batch_id):
    middleware.authorize([config.ROLE_INTEGRATION_LEAD])
    batch = support.load("migration_batches", migration_batch_id)
    data = payload.body()
    start_at = payload.timestamp(data, "cutover_start_at")
    end_at = payload.timestamp(data, "cutover_end_at")
    if end_at <= start_at:
        raise invalid("'cutover_end_at' must be strictly after 'cutover_start_at'.")

    _require_batch_status(
        batch,
        ("STAGED", "QUARANTINED"),
        "Only a staged or quarantined batch can reserve a cutover window.",
    )
    practice = db.get("practices", batch["practice_id"])
    support.require_affiliated(practice)
    support.require_posture(practice, ("STABILIZING", "INTEGRATED"))
    effective = [
        agreement
        for agreement in derive.agreements_of_practice(practice["id"])
        if agreement["status"] == "EFFECTIVE"
    ]
    if not effective:
        raise ApiError(
            "ERR_SERVICE_AGREEMENT_NOT_EFFECTIVE",
            "The practice has no effective service agreement.",
        )

    # 48-hour buffer against every other reserved or parked window of this practice.
    for other in derive.batches_of_practice(practice["id"]):
        if other["id"] == batch["id"] or other["status"] not in ("SCHEDULED", "HELD"):
            continue
        if other["cutover_start_at"] is None or other["cutover_end_at"] is None:
            continue
        separated = (
            start_at >= other["cutover_end_at"] + BUFFER
            or end_at + BUFFER <= other["cutover_start_at"]
        )
        if not separated:
            raise ApiError(
                "ERR_CUTOVER_WINDOW_CONFLICT",
                "The requested window is within 48 hours of another reserved window.",
            )

    # Aggregate vendor capacity across every practice the vendor serves.
    vendor = db.get("conversion_vendors", practice["conversion_vendor_id"])
    intersecting = 0
    for other in db.all_rows("migration_batches"):
        if other["id"] == batch["id"] or other["status"] not in ("SCHEDULED", "HELD"):
            continue
        other_practice = db.get("practices", other["practice_id"])
        if other_practice is None or other_practice["conversion_vendor_id"] != vendor["id"]:
            continue
        if other["cutover_start_at"] is None or other["cutover_end_at"] is None:
            continue
        if start_at <= other["cutover_end_at"] and other["cutover_start_at"] <= end_at:
            intersecting += 1
    if intersecting >= vendor["max_concurrent_windows"]:
        raise ApiError(
            "ERR_VENDOR_WINDOW_CAPACITY",
            "The conversion vendor has no crew left for an intersecting window.",
        )

    batch["cutover_start_at"] = start_at
    batch["cutover_end_at"] = end_at
    batch["status"] = "SCHEDULED"
    uow.touch(batch)
    uow.touch(vendor)
    return "migration_batches", batch, 200


@bp.post("/migration-batches/<migration_batch_id>/validate")
@support.transactional
def validate_batch(migration_batch_id):
    middleware.authorize([config.ROLE_INTEGRATION_LEAD])
    batch = support.load("migration_batches", migration_batch_id)
    data = payload.body()
    quarantined_count = payload.integer(data, "quarantined_count", minimum=0)
    _require_batch_status(
        batch, ("SCHEDULED",), "Only a scheduled batch can report validation results."
    )
    practice = db.get("practices", batch["practice_id"])
    support.require_posture(practice, ("STABILIZING", "INTEGRATED", "RESTRICTED"))
    if batch["cutover_start_at"] is None or clock.now() < batch["cutover_start_at"]:
        raise ApiError(
            "ERR_CUTOVER_WINDOW_NOT_STARTED",
            "The batch's cutover window has not opened yet.",
        )
    if quarantined_count > batch["records_total"]:
        raise ApiError(
            "ERR_QUARANTINE_COUNT_EXCEEDS_TOTAL",
            "quarantined_count exceeds the batch record total.",
        )

    rate = calc.validation_error_rate_bps(quarantined_count, batch["records_total"])
    batch["validation_error_rate_bps"] = rate
    if rate <= config.MAX_VALIDATION_ERROR_RATE_BPS:
        batch["records_quarantined"] = quarantined_count
        batch["records_validated"] = batch["records_total"] - quarantined_count
        batch["status"] = "VALIDATED"
    else:
        # Above tolerance the whole batch is quarantined and earns no chart credit.
        batch["records_quarantined"] = batch["records_total"]
        batch["records_validated"] = 0
        batch["status"] = "QUARANTINED"
    uow.touch(batch)
    return "migration_batches", batch, 200


@bp.post("/migration-batches/<migration_batch_id>/remediate")
@support.transactional
def remediate_batch(migration_batch_id):
    middleware.authorize([config.ROLE_INTEGRATION_LEAD])
    batch = support.load("migration_batches", migration_batch_id)
    data = payload.body()
    payload.string(data, "remediation_note", required=False)
    _require_batch_status(
        batch, ("QUARANTINED",), "Only a quarantined batch can be remediated."
    )
    batch["remediation_round"] += 1
    batch["records_quarantined"] = 0
    batch["records_validated"] = 0
    batch["validation_error_rate_bps"] = None
    batch["status"] = "SCHEDULED"
    uow.touch(batch)
    return "migration_batches", batch, 200


@bp.post("/migration-batches/<migration_batch_id>/rollback")
@support.transactional
def rollback_batch(migration_batch_id):
    middleware.authorize([config.ROLE_INTEGRATION_LEAD])
    batch = support.load("migration_batches", migration_batch_id)
    data = payload.body()
    payload.string(data, "rollback_reason")
    _require_batch_status(
        batch, ("VALIDATED",), "Only a validated batch can be rolled back."
    )
    # Chart credit is withdrawn by exactly the amount granted: zero drift.
    batch["records_validated"] = 0
    batch["records_quarantined"] = batch["records_total"]
    batch["status"] = "QUARANTINED"
    uow.touch(batch)
    return "migration_batches", batch, 200


@bp.post("/migration-batches/<migration_batch_id>/reconcile")
@support.transactional
def reconcile_batch(migration_batch_id):
    middleware.authorize([config.ROLE_INTEGRATION_LEAD])
    batch = support.load("migration_batches", migration_batch_id)
    payload.body()
    if batch["status"] != "VALIDATED" or derive.records_pending(batch) != 0:
        raise ApiError(
            "ERR_INVALID_BATCH_STATE",
            "Only a validated batch with no pending records can be reconciled.",
        )
    batch["status"] = "RECONCILED"
    uow.touch(batch)
    return "migration_batches", batch, 200
