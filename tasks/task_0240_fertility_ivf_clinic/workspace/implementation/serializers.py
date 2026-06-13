"""Output serializers — strip internal fields (e.g. _seq) and project the
public shape of each entity (SCAFFOLD §1.1)."""

import db


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def clinic(rec):
    return _public(rec)


def package(rec):
    return _public(rec)


def patient(rec):
    return _public(rec)


def donor(rec):
    return _public(rec)


def surrogate(rec):
    return _public(rec)


def consent_form(rec):
    return _public(rec)


def patient_consent(rec):
    return _public(rec)


def _tank_with_free_slots(rec):
    """Derive committed_free_slots / projected_free_slots fresh (PRD §3.7)."""
    stored = 0
    pending = 0
    for s in db.specimens.values():
        if s["cryo_tank_id"] == rec["id"]:
            if s["status"] == "STORED":
                stored += 1
            elif s["status"] == "PENDING":
                pending += 1
    out = _public(rec)
    out["committed_free_slots"] = rec["capacity_slots"] - stored
    out["projected_free_slots"] = rec["capacity_slots"] - (stored + pending)
    return out


def tank(rec):
    return _tank_with_free_slots(rec)


def cycle(rec):
    return _public(rec)


def medication(rec):
    return _public(rec)


def appointment(rec):
    return _public(rec)


def specimen(rec):
    return _public(rec)


def invoice(rec):
    return _public(rec)


def outcome(rec):
    return _public(rec)
