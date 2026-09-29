"""Resource presentation: strips internals and applies read-time derivations."""

from db import get, public
from services.derive import CADENCE_CODES, derive_readiness


def plain(row):
    return public(row)


def appointment_out(appointment):
    data = public(appointment)
    # readiness_status is a pure derivation (PRD 3.6) — a clock move alone must not
    # bump the row's version, so it is re-derived on every read.
    data["readiness_status"] = derive_readiness(appointment)
    patient = get("patients", appointment.get("patient_id"))
    tier = (patient or {}).get("reminder_tier") or "STANDARD"
    data["reminder_cadence_code"] = CADENCE_CODES.get(tier, "C_STANDARD")
    return data


def out(collection, row):
    if collection == "appointments":
        return appointment_out(row)
    return plain(row)


def many(collection, items):
    return [out(collection, row) for row in items]
