"""Domain engine — entity helpers and cross-aggregate cascades.

Centralizes everything that mutates state. Routes call into here so the
cascade rules (SCAFFOLD §1.2 transitions, §1.3 calculations, PRD §3) live
in one place, behind the store's single global lock.
"""

from datetime import datetime
from decimal import Decimal

from config import (
    INSPECTION_CANCELLED,
    INSPECTION_IN_PROGRESS,
    INSPECTION_SCHEDULED,
    JURISDICTION_STATE_CODE,
    LIEN_STATUS_NONE,
    PLATE_ACTIVE,
    PLATE_ISSUED,
    PLATE_SURRENDER_SALVAGE_TRIGGERED,
    PLATE_SURRENDERED,
    PLATE_SUSPENDED,
    REAL_ID_NOT_APPLIED,
    TITLE_BRAND_CLEAN,
    TITLE_BRAND_REBUILT,
    TITLE_STATUS_CLEAN,
    TITLE_STATUS_NON_REPAIRABLE,
    TITLE_STATUS_REBUILT,
    TITLE_STATUS_SALVAGE_PENDING_REBUILD,
    TXAPP_EMISSIONS_PASSED,
    TXAPP_EMISSIONS_PENDING,
    TXAPP_REJECTED,
    TXAPP_SALVAGE_CASCADE_STATES,
    TXAPP_SALVAGE_REVIEW,
    TXAPP_TAX_ASSESSED,
    TXAPP_VIN_VERIFIED,
    UNPAID_TIMEOUT_DAYS,
    VIN_UNVERIFIED,
)
from db import store
from utils import add_days, iso_format, new_uuid


# -----------------------------------------------------------------------------
# Common-field stamping helpers
# -----------------------------------------------------------------------------
def stamp_create(entity: dict, *, now: datetime, with_common: bool = True) -> None:
    """Initialize id and common (created_at/updated_at/version) fields."""
    if "id" not in entity:
        entity["id"] = new_uuid()
    if with_common:
        ts = iso_format(now)
        entity["created_at"] = ts
        entity["updated_at"] = ts
        entity["version"] = 1


def stamp_update(entity: dict, *, now: datetime) -> None:
    """Bump updated_at and version for an existing entity."""
    if "version" in entity:
        entity["version"] = entity["version"] + 1
    if "updated_at" in entity:
        entity["updated_at"] = iso_format(now)


# -----------------------------------------------------------------------------
# Owner helpers
# -----------------------------------------------------------------------------
def create_owner(*, full_name: str, date_of_birth: str, residency_state: str,
                 now: datetime) -> dict:
    owner = {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "residency_state": residency_state,
        "real_id_status": REAL_ID_NOT_APPLIED,
        "real_id_score": None,
        "real_id_expires_at": None,
        "is_resident": (residency_state == JURISDICTION_STATE_CODE),
        "outstanding_holds_count": 0,
    }
    stamp_create(owner, now=now)
    store.owners[owner["id"]] = owner
    return owner


# -----------------------------------------------------------------------------
# Vehicle helpers
# -----------------------------------------------------------------------------
def create_vehicle(*, vin: str, make: str, model: str, model_year: int,
                   curb_weight_lbs: int, fuel_type: str, now: datetime) -> dict:
    vehicle = {
        "vin": vin,
        "make": make,
        "model": model,
        "model_year": model_year,
        "curb_weight_lbs": curb_weight_lbs,
        "fuel_type": fuel_type,
        "vin_verification_status": VIN_UNVERIFIED,
        "vin_verified_at": None,
        "title_status": TITLE_STATUS_CLEAN,
        "lien_status": LIEN_STATUS_NONE,
        "current_title_id": None,
        "emissions_expires_at": None,
    }
    stamp_create(vehicle, now=now)
    store.vehicles[vehicle["id"]] = vehicle
    return vehicle


# -----------------------------------------------------------------------------
# Cascade: Salvage event on a vehicle (PRD §3.3 / SCAFFOLD Title transitions)
# -----------------------------------------------------------------------------
def cascade_partial_salvage(vehicle: dict, *, now: datetime) -> None:
    """When title_status flips to SALVAGE_PENDING_REBUILD:
       - Clear Vehicle.emissions_expires_at
       - Cancel SCHEDULED/IN_PROGRESS EmissionsInspection rows on this vehicle
       - Suspend any ACTIVE Plate bound to this vehicle
       - Reroute in-flight TransferApplications into SALVAGE_REVIEW
    """
    vehicle["title_status"] = TITLE_STATUS_SALVAGE_PENDING_REBUILD
    vehicle["emissions_expires_at"] = None
    stamp_update(vehicle, now=now)

    for insp in store.emissions_inspections.values():
        if insp["vehicle_id"] == vehicle["id"] and insp["status"] in (
                INSPECTION_SCHEDULED, INSPECTION_IN_PROGRESS):
            insp["status"] = INSPECTION_CANCELLED
            stamp_update(insp, now=now)

    for plate in store.plates.values():
        if plate["vehicle_id"] == vehicle["id"] and plate["status"] == PLATE_ACTIVE:
            plate["status"] = PLATE_SUSPENDED
            plate["suspended_at"] = iso_format(now)
            stamp_update(plate, now=now)

    for tx in store.transfer_applications.values():
        if tx["vehicle_id"] == vehicle["id"] and tx["status"] in TXAPP_SALVAGE_CASCADE_STATES:
            tx["status"] = TXAPP_SALVAGE_REVIEW
            tx["salvage_branch_taken"] = True
            stamp_update(tx, now=now)


def cascade_total_salvage(vehicle: dict, *, now: datetime) -> None:
    """When title_status flips to NON_REPAIRABLE:
       - Surrender every ACTIVE/SUSPENDED plate (reason SALVAGE_TRIGGERED)
       - Vehicle removed from registration pipeline permanently
       - Also cancel SCHEDULED/IN_PROGRESS inspections
       - In-flight transfer applications follow §3.3 — rerouted to SALVAGE_REVIEW
    """
    vehicle["title_status"] = TITLE_STATUS_NON_REPAIRABLE
    vehicle["emissions_expires_at"] = None
    stamp_update(vehicle, now=now)

    for insp in store.emissions_inspections.values():
        if insp["vehicle_id"] == vehicle["id"] and insp["status"] in (
                INSPECTION_SCHEDULED, INSPECTION_IN_PROGRESS):
            insp["status"] = INSPECTION_CANCELLED
            stamp_update(insp, now=now)

    for plate in store.plates.values():
        if plate["vehicle_id"] == vehicle["id"] and plate["status"] in (
                PLATE_ACTIVE, PLATE_SUSPENDED):
            plate["status"] = PLATE_SURRENDERED
            plate["surrender_reason"] = PLATE_SURRENDER_SALVAGE_TRIGGERED
            stamp_update(plate, now=now)

    for tx in store.transfer_applications.values():
        if tx["vehicle_id"] == vehicle["id"] and tx["status"] in TXAPP_SALVAGE_CASCADE_STATES:
            tx["status"] = TXAPP_SALVAGE_REVIEW
            tx["salvage_branch_taken"] = True
            stamp_update(tx, now=now)


# -----------------------------------------------------------------------------
# Fee ledger helpers (PRD §3.7 + §3.8)
# -----------------------------------------------------------------------------
def _append_ledger(application_id: str, kind: str, amount_cents: int, *,
                   now: datetime) -> dict:
    entry = {
        "id": new_uuid(),
        "application_id": application_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "occurred_at": iso_format(now),
    }
    store.fee_ledger.append(entry)
    return entry


def append_assessment_ledger(application_id: str, *,
                             sales_tax_cents: int, reg_fee_cents: int,
                             processing_fee_cents: int, now: datetime) -> list[dict]:
    """Append the three SALES_TAX/REG_FEE/PROCESSING_FEE rows."""
    from config import LEDGER_PROCESSING_FEE, LEDGER_REG_FEE, LEDGER_SALES_TAX
    return [
        _append_ledger(application_id, LEDGER_SALES_TAX, sales_tax_cents, now=now),
        _append_ledger(application_id, LEDGER_REG_FEE, reg_fee_cents, now=now),
        _append_ledger(application_id, LEDGER_PROCESSING_FEE, processing_fee_cents, now=now),
    ]


def append_refund_ledger(application_id: str, *,
                         sales_tax_cents: int, reg_fee_cents: int,
                         processing_fee_cents: int, now: datetime) -> list[dict]:
    """Append the three REFUND_* rows (negatives of the originals)."""
    from config import (
        LEDGER_REFUND_PROCESSING,
        LEDGER_REFUND_REG,
        LEDGER_REFUND_TAX,
    )
    return [
        _append_ledger(application_id, LEDGER_REFUND_TAX, -sales_tax_cents, now=now),
        _append_ledger(application_id, LEDGER_REFUND_REG, -reg_fee_cents, now=now),
        _append_ledger(application_id, LEDGER_REFUND_PROCESSING, -processing_fee_cents, now=now),
    ]


# -----------------------------------------------------------------------------
# Clock advance — sweep unpaid TAX_ASSESSED applications past 7d (PRD §3.8)
# -----------------------------------------------------------------------------
def sweep_unpaid_timeout(now: datetime) -> None:
    """For every TransferApplication in TAX_ASSESSED with paid_at IS NULL and
    updated_at + 7d <= now, revert to EMISSIONS_PASSED, post refunds, clear amounts.
    """
    from utils import parse_iso8601

    for tx in store.transfer_applications.values():
        if tx["status"] != TXAPP_TAX_ASSESSED:
            continue
        if tx.get("paid_at") is not None:
            continue
        last_update = parse_iso8601(tx["updated_at"])
        if add_days(last_update, UNPAID_TIMEOUT_DAYS) > now:
            continue
        # Find this application's last assessment debits to refund (signed cents)
        from config import (
            LEDGER_PROCESSING_FEE,
            LEDGER_REG_FEE,
            LEDGER_SALES_TAX,
        )
        sales_tax_cents = None
        reg_fee_cents = None
        processing_fee_cents = None
        for entry in reversed(store.fee_ledger):
            if entry["application_id"] != tx["id"]:
                continue
            if entry["kind"] == LEDGER_SALES_TAX and sales_tax_cents is None:
                sales_tax_cents = entry["amount_cents"]
            elif entry["kind"] == LEDGER_REG_FEE and reg_fee_cents is None:
                reg_fee_cents = entry["amount_cents"]
            elif entry["kind"] == LEDGER_PROCESSING_FEE and processing_fee_cents is None:
                processing_fee_cents = entry["amount_cents"]
            if (sales_tax_cents is not None and reg_fee_cents is not None
                    and processing_fee_cents is not None):
                break
        # Defensive: if not found, fall back to 0; should not happen in normal flows
        sales_tax_cents = sales_tax_cents or 0
        reg_fee_cents = reg_fee_cents or 0
        processing_fee_cents = processing_fee_cents or 0

        append_refund_ledger(tx["id"],
                             sales_tax_cents=sales_tax_cents,
                             reg_fee_cents=reg_fee_cents,
                             processing_fee_cents=processing_fee_cents,
                             now=now)
        tx["status"] = TXAPP_EMISSIONS_PASSED
        tx["fee_subtotal"] = None
        tx["processing_fee"] = None
        tx["total_due"] = None
        # Clear the recorded assessment actor so a new assess-fees call later
        # can rebind segregation-of-duties to whichever assessor next runs.
        store.assess_fees_actor.pop(tx["id"], None)
        stamp_update(tx, now=now)


# -----------------------------------------------------------------------------
# REAL ID revocation cascade (PRD §3.10)
# -----------------------------------------------------------------------------
def cascade_realid_revocation(owner_id: str, *, now: datetime) -> None:
    """Suspend ACTIVE plates whose current title owner_id == this owner_id.
    The TransferApplication freeze is observational — guarded at assess-fees
    and issue-plate call sites by the ERR_OWNER_REAL_ID_REVOKED check.
    """
    # Build set of vehicle ids whose current-active title.owner_id == owner_id
    affected_vehicle_ids = set()
    for vehicle in store.vehicles.values():
        cur_title_id = vehicle.get("current_title_id")
        if not cur_title_id:
            continue
        title = store.titles.get(cur_title_id)
        if title and title.get("is_active") and title.get("owner_id") == owner_id:
            affected_vehicle_ids.add(vehicle["id"])

    for plate in store.plates.values():
        if plate["status"] == PLATE_ACTIVE and plate["vehicle_id"] in affected_vehicle_ids:
            plate["status"] = PLATE_SUSPENDED
            plate["suspended_at"] = iso_format(now)
            stamp_update(plate, now=now)


# -----------------------------------------------------------------------------
# Title supersession (PRD §3.8 plate-issuance completion side effect)
# -----------------------------------------------------------------------------
def supersede_title_and_create_new(vehicle: dict, *, owner_id: str,
                                   application_id: str, now: datetime) -> dict:
    """Supersede the prior active Title for the vehicle (if any) and create
    a new Title row pointing at the application. Updates Vehicle.current_title_id.
    Brand: REBUILT if vehicle.title_status == REBUILT, else CLEAN.
    """
    # Mark prior title superseded
    prior_title_id = vehicle.get("current_title_id")
    if prior_title_id:
        prior_title = store.titles.get(prior_title_id)
        if prior_title is not None:
            prior_title["superseded_at"] = iso_format(now)
            prior_title["is_active"] = False
            # Title rows do not carry updated_at/version — no stamp_update.

    brand = TITLE_BRAND_REBUILT if vehicle["title_status"] == TITLE_STATUS_REBUILT else TITLE_BRAND_CLEAN

    new_title = {
        "id": new_uuid(),
        "vehicle_id": vehicle["id"],
        "owner_id": owner_id,
        "brand": brand,
        "issued_at": iso_format(now),
        "superseded_at": None,
        "is_active": True,
        "source_application_id": application_id,
    }
    store.titles[new_title["id"]] = new_title
    vehicle["current_title_id"] = new_title["id"]
    stamp_update(vehicle, now=now)
    return new_title
