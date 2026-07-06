"""Serialization: strip internal fields and compute derived fields for output."""
from calculations import PHASE_ORDER
from db import db

INTERNAL_KEYS = {"_seq"}


def _public(obj, extra=None):
    out = {k: v for k, v in obj.items() if k not in INTERNAL_KEYS}
    if extra:
        out.update(extra)
    return out


def compute_available(escrow):
    return (
        escrow["deposited_cents"]
        - escrow["disbursed_cents"]
        - escrow["reserved_cents"]
    )


def journey_current_phase(journey):
    """Derived from the latest ACHIEVED milestone on the journey."""
    phase = "PRE_TRANSFER"
    for m in db.milestones.values():
        if m["journey_id"] != journey["id"] or m["status"] != "ACHIEVED":
            continue
        if m["milestone_type"] == "EMBRYO_TRANSFER":
            candidate = "TRANSFERRED"
        elif m["milestone_type"] == "HEARTBEAT":
            candidate = "HEARTBEAT_CONFIRMED"
        elif m["milestone_type"] == "BIRTH":
            candidate = "BORN"
        else:
            continue
        if PHASE_ORDER[candidate] > PHASE_ORDER[phase]:
            phase = candidate
    return phase


def ser_intended_parent(obj):
    return _public(obj)


def ser_carrier(obj):
    return _public(obj)


def ser_donor(obj):
    return _public(obj)


def ser_match(obj):
    return _public(obj)


def ser_contract(obj):
    return _public(obj)


def ser_escrow(obj):
    return _public(obj, {"available_cents": compute_available(obj)})


def ser_journey(obj):
    return _public(obj, {"current_phase": journey_current_phase(obj)})


def ser_milestone(obj):
    return _public(obj)


def ser_comp_schedule(obj):
    return _public(obj)


def ser_disbursement(obj):
    return _public(obj)


def ser_insurance_review(obj):
    return _public(obj)
