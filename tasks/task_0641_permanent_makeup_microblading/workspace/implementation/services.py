"""Cross-entity business operations: posture recompute, license expiry detection,
deposit transaction emission, and the license-suspension cascade.
"""
from clock import clock
from db import db, new_id, iso_ms
import serialize
import helpers
import calculations as calc


def now():
    return clock.now()


def now_iso():
    return iso_ms(clock.now())


# ----------------------------------------------------------------------------
# License expiry detection (lazy, at procedure-gating checks) — PRD 3.1
# ----------------------------------------------------------------------------
def check_license_expiry(tech):
    """If license_expiry or bbp_cert_expiry <= current logical time, transition
    to LICENSE_EXPIRED (from ACTIVE or SUSPENDED). Recompute studio posture and
    bump studio version. Returns True if a transition occurred."""
    if tech["license_status"] == "LICENSE_EXPIRED":
        return False
    le = helpers.parse_dt(tech["license_expiry"], "license_expiry")
    be = helpers.parse_dt(tech["bbp_cert_expiry"], "bbp_cert_expiry")
    if le <= now() or be <= now():
        tech["license_status"] = "LICENSE_EXPIRED"
        helpers.touch(tech)
        studio = db.studios.get(tech["studio_id"])
        if studio:
            helpers.touch(studio)
        return True
    return False


def effective_license_status(tech):
    """Return license status after applying lazy expiry."""
    check_license_expiry(tech)
    return tech["license_status"]


# ----------------------------------------------------------------------------
# DepositTransaction emission (append-only) — scaffold DepositTransaction
# ----------------------------------------------------------------------------
def emit_txn(appointment_id, txn_type, amount_cents):
    tid = new_id()
    txn = {
        "id": tid,
        "appointment_id": appointment_id,
        "txn_type": txn_type,
        "amount_cents": amount_cents,
    }
    helpers.stamp_common(txn, versioned=False)
    db.deposit_transactions[tid] = txn
    return txn


# ----------------------------------------------------------------------------
# Void a single BOOKED appointment (compliance void OR cascade) — PRD 3.9
# ----------------------------------------------------------------------------
def void_appointment(appt):
    """lifecycle BOOKED->VOIDED. Restore kit if consumed (bump studio version).
    Refund deposit if DEPOSIT_PAID. Bumps appointment version."""
    appt["lifecycle_status"] = "VOIDED"
    studio_bumped = False
    if appt.get("kit_consumed"):
        appt["kit_consumed"] = False
        tech = db.technicians.get(appt["technician_id"])
        if tech:
            studio = db.studios.get(tech["studio_id"])
            if studio:
                helpers.touch(studio)
                studio_bumped = True
    if appt["payment_status"] == "DEPOSIT_PAID":
        deposit_paid = serialize.appointment_deposit_paid(appt["id"])
        if deposit_paid > 0:
            emit_txn(appt["id"], "REFUND", deposit_paid)
        appt["payment_status"] = "REFUNDED"
    helpers.touch(appt)
    return studio_bumped


# ----------------------------------------------------------------------------
# License suspension cascade — PRD 2.6 / 3.1
# ----------------------------------------------------------------------------
def suspend_license_cascade(tech):
    """Suspend an active license and fire the full settlement cascade.

    - All this technician's BOOKED appointments -> VOIDED
    - Each voided appt with kit_consumed restores the kit (sterile_kit_consumed
      reduced; recomputed at read), payment refund if DEPOSIT_PAID
    - Studio compliance posture recomputed; Studio.version incremented (once for
      the suspension event; cascades that restore kits also bump it)
    """
    tech["license_status"] = "LICENSE_SUSPENDED"
    helpers.touch(tech)

    studio = db.studios.get(tech["studio_id"])

    # Cascade L1: void this technician's BOOKED appointments
    for appt in list(db.appointments.values()):
        if appt["technician_id"] == tech["id"] and appt["lifecycle_status"] == "BOOKED":
            appt["lifecycle_status"] = "VOIDED"
            if appt.get("kit_consumed"):
                appt["kit_consumed"] = False
                # kit restoration reflected in studio recompute; bump studio version
                if studio:
                    helpers.touch(studio)
            if appt["payment_status"] == "DEPOSIT_PAID":
                deposit_paid = serialize.appointment_deposit_paid(appt["id"])
                if deposit_paid > 0:
                    emit_txn(appt["id"], "REFUND", deposit_paid)
                appt["payment_status"] = "REFUNDED"
            helpers.touch(appt)

    # Studio posture recomputed (derived at read) + version increment for the event
    if studio:
        helpers.touch(studio)


# ----------------------------------------------------------------------------
# Package auto-expiry (lazy) — PRD 3.8
# ----------------------------------------------------------------------------
def check_package_expiry(pkg):
    """If source appointment's touch-up window has closed (now > completed_at+60d)
    and remaining sessions still exist, move ACTIVE -> EXPIRED."""
    if pkg["status"] != "ACTIVE":
        return
    source = db.appointments.get(pkg["source_appointment_id"])
    if not source or not source.get("completed_at"):
        return
    completed = helpers.parse_dt(source["completed_at"], "completed_at")
    from datetime import timedelta
    if now() > completed + timedelta(days=60):
        remaining = serialize.package_remaining_sessions(pkg)
        if remaining > 0:
            pkg["status"] = "EXPIRED"
            helpers.touch(pkg)
