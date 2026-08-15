"""Destruction helpers shared by withdrawal cascade, manual orders, return-to-service."""
from datetime import timedelta

import db
from services.common import make_record, touch

DESTRUCTION_SLA_HOURS = 48


def create_destruction_order(specimen_id, reason, created_by_user_id, consent_record_id=None):
    """Create a DestructionOrder and flip specimen/aliquots to DESTRUCTION_PENDING."""
    from clock import now as clock_now

    order = make_record(db.destruction_orders, {
        "specimen_id": specimen_id,
        "consent_record_id": consent_record_id,
        "reason": reason,
        "created_by_user_id": created_by_user_id,
        "confirmed_by_user_id": None,
        "status": "PENDING",
        "due_at": clock_now() + timedelta(hours=DESTRUCTION_SLA_HOURS),
        "completed_late": False,
    })
    flip_specimen_to_destruction_pending(specimen_id)
    return order


def flip_specimen_to_destruction_pending(specimen_id):
    """Flip specimen (if ACCESSIONED/IN_STORAGE) and child aliquots to DESTRUCTION_PENDING."""
    from services.specimen import recompute_volumes

    specimen = db.specimens.get(specimen_id)
    if specimen is None:
        return
    flipped_aliquots = []
    if specimen["lifecycle_status"] in ("ACCESSIONED", "IN_STORAGE"):
        specimen["lifecycle_status"] = "DESTRUCTION_PENDING"
        touch(specimen)
    for a in db.aliquots.values():
        if a["specimen_id"] == specimen_id and a["status"] in ("IN_STORAGE", "RESERVED", "QUARANTINED"):
            a["status"] = "DESTRUCTION_PENDING"
            touch(a)
            flipped_aliquots.append(a)
    if flipped_aliquots:
        recompute_volumes(specimen)
    return flipped_aliquots


def execute_destruction(order, confirmer_user_id):
    """Confirm a PENDING order: destroy specimen, aliquots, revoke keys."""
    from clock import now as clock_now
    from services.specimen import recompute_volumes

    specimen = db.specimens[order["specimen_id"]]
    order["confirmed_by_user_id"] = confirmer_user_id
    order["completed_late"] = clock_now() > order["due_at"]
    order["status"] = "COMPLETED"
    touch(order)

    if specimen["lifecycle_status"] == "DESTRUCTION_PENDING":
        specimen["lifecycle_status"] = "DESTROYED"
        touch(specimen)
    for a in db.aliquots.values():
        if a["specimen_id"] == specimen["id"] and a["status"] == "DESTRUCTION_PENDING":
            a["status"] = "DESTROYED"
            a["remaining_volume_ml"] = 0
            touch(a)
    recompute_volumes(specimen)
    for k in db.deidentification_keys.values():
        if k["specimen_id"] == specimen["id"] and k["status"] == "ACTIVE":
            k["status"] = "REVOKED"
            touch(k)
