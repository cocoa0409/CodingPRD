"""Shared state-transition logic so manual endpoints and clock sweeps behave
identically (SCAFFOLD §1.2, PRD §3.5, §3.6, §3.11, §3.12).
"""

from clock import clock, parse_iso
from db import db, touch


# ---- KilnBatch completion (PRD §3.5) ----------------------------------------

def complete_firing(batch):
    """FIRING -> COMPLETED. Cascade every FIRING piece on the batch to READY,
    stamped ready_at = current logical clock. Caller guarantees batch.status ==
    FIRING."""
    now_iso = clock.now_iso()
    for piece in db.bisque_pieces.values():
        if piece["kiln_batch_id"] == batch["id"] and piece["status"] == "FIRING":
            piece["status"] = "READY"
            piece["ready_at"] = now_iso
            touch(piece)
    batch["status"] = "COMPLETED"
    touch(batch)
    return batch


# ---- PartyBooking expiry (PRD §3.6) -----------------------------------------

def expire_booking(booking):
    """DEPOSIT_PENDING -> EXPIRED. Caller guarantees preconditions."""
    booking["status"] = "EXPIRED"
    touch(booking)
    return booking


# ---- ClassSeries start (PRD §3.11) ------------------------------------------

def start_series(series):
    """OPEN/FULL -> STARTED. Caller guarantees preconditions."""
    series["status"] = "STARTED"
    touch(series)
    return series


# ---- Clock sweeps (PRD §3.12) -----------------------------------------------

def run_sweeps():
    """Advancing the clock triggers three sweeps over affected records:
      - any FIRING batch whose firing_completes_at <= clock is completed
      - any DEPOSIT_PENDING booking whose scheduled_for <= clock is expired
      - any OPEN/FULL series whose starts_at <= clock is started
    """
    now = clock.now()

    # Firing completion sweep
    for batch in list(db.kiln_batches.values()):
        if batch["status"] == "FIRING" and batch["firing_completes_at"]:
            if parse_iso(batch["firing_completes_at"]) <= now:
                complete_firing(batch)

    # Booking expiry sweep
    for booking in list(db.party_bookings.values()):
        if booking["status"] == "DEPOSIT_PENDING" and booking["scheduled_for"]:
            if parse_iso(booking["scheduled_for"]) <= now:
                expire_booking(booking)

    # Series start sweep
    for series in list(db.class_series.values()):
        if series["status"] in ("OPEN", "FULL") and series["starts_at"]:
            if parse_iso(series["starts_at"]) <= now:
                start_series(series)
