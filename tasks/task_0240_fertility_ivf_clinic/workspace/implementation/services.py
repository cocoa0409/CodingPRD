"""Cross-entity business logic: consent gating, cascades, billing math glue."""

import db
import errors as E
from errors import fail
import calculations as calc


def has_active_consent_for_gate(patient_id, gate):
    """PRD §3.6: patient holds an ACTIVE consent whose signed PUBLISHED form's
    required_for contains `gate`."""
    for consent in db.patient_consents.values():
        if consent["patient_id"] != patient_id:
            continue
        if consent["status"] != "ACTIVE":
            continue
        form = db.consent_forms.get(consent["consent_form_id"])
        if form is None or form["status"] != "PUBLISHED":
            continue
        if gate in form.get("required_for", []):
            return True
    return False


def require_consent(patient_id, gate):
    if not has_active_consent_for_gate(patient_id, gate):
        fail(E.ERR_CONSENT_MISSING,
             "No ACTIVE consent covering gate %s" % gate)


def settle_prior_insurer_paid(package_id, exclude_cycle_id):
    """Sum insurer_paid_cents over OTHER cycles already SETTLED on same package."""
    total = 0
    for c in db.cycles.values():
        if c["id"] == exclude_cycle_id:
            continue
        if c["insurance_package_id"] != package_id:
            continue
        if c["billing_status"] == "SETTLED":
            total += c["insurer_paid_cents"]
    return total


def cancel_cascade(clinic_id, cycle):
    """Cascade a cycle cancellation across meds, appointments, specimens, tanks,
    and the donor reservation (PRD §3.2)."""
    cycle_id = cycle["id"]

    # L1: SCHEDULED medication orders -> CANCELLED
    for med in db.medications.values():
        if med["treatment_cycle_id"] == cycle_id and med["status"] == "SCHEDULED":
            med["status"] = "CANCELLED"
            db.touch(med)

    # L1: CONFIRMED/RESCHEDULED appointments -> CANCELLED (frees room window)
    for appt in db.appointments.values():
        if (appt["treatment_cycle_id"] == cycle_id
                and appt["status"] in ("CONFIRMED", "RESCHEDULED")):
            appt["status"] = "CANCELLED"
            db.touch(appt)

    # L1: PENDING/STORED specimens -> DISCARDED; STORED also releases tank slot
    # (L2) and forces tank free-slot recompute / version bump (L3).
    affected_tanks = set()
    for spec in db.specimens.values():
        if spec["treatment_cycle_id"] != cycle_id:
            continue
        if spec["status"] in ("PENDING", "STORED"):
            was_stored = spec["status"] == "STORED"
            spec["status"] = "DISCARDED"
            db.touch(spec)
            if was_stored:
                tank = db.tanks.get(spec["cryo_tank_id"])
                if tank is not None:
                    tank["reserved_slots"] -= 1
                    db.touch(tank)
                    affected_tanks.add(tank["id"])

    # Donor release: RESERVED (not yet CONSUMED) -> AVAILABLE
    donor_id = cycle.get("donor_profile_id")
    if donor_id:
        donor = db.donors.get(donor_id)
        if donor is not None and donor["status"] == "RESERVED":
            donor["status"] = "AVAILABLE"
            db.touch(donor)
