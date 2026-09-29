"""The three named cascades and the posture reconciliation they drive.

Every cascade completes inside the triggering request; each affected row's
observable projection changes, so the tracking layer advances its updated_at and
version exactly once.
"""

from decimal import Decimal

from db import now
from services import calc, derive
from util import D, qd

PROFILE_SUSPENDED_FINDING = "PROFILE_SUSPENDED"


def reconcile_unit(u, hold_reason=None):
    """Recompute a unit's posture and reconcile the batches standing on it.

    A PLANNED batch is only pushed to HELD when the caller names the cascade that
    took the posture out of OPEN (condemnation / deficiency / profile suspension);
    posture that is merely RESTRICTED through utilization never holds a batch.
    A HELD batch always returns to PLANNED once the posture is OPEN again.
    """
    posture = derive.unit_posture(u)
    if posture == "OPEN":
        for b in derive.batches_of_unit(u["id"]):
            if b["status"] == "HELD":
                b["status"] = "PLANNED"
                b["held_reason_code"] = "NONE"
    elif hold_reason is not None:
        for b in derive.batches_of_unit(u["id"]):
            if b["status"] == "PLANNED":
                b["status"] = "HELD"
                b["held_reason_code"] = hold_reason
    return posture


def reconcile_units_of_facility(facility_id, hold_reason=None):
    for u in derive.units_of_facility(facility_id):
        reconcile_unit(u, hold_reason)


# ---------------------------------------------------------------------------
# CASCADE-1: condemnation
# ---------------------------------------------------------------------------

def condemnation_cascade(c):
    """Container -> CONDEMNED forces the unit to SUSPENDED and holds its batches."""
    u = derive.unit(c["storage_unit_id"])
    if u is None:
        return
    reconcile_unit(u, "UNIT_POSTURE")


def deficiency_cascade(c):
    u = derive.unit(c["storage_unit_id"])
    if u is None:
        return
    reconcile_unit(u, "UNIT_POSTURE")


# ---------------------------------------------------------------------------
# CASCADE-2: profile suspension / reinstatement
# ---------------------------------------------------------------------------

def profile_suspension_cascade(p):
    affected = set()
    for c in derive.containers_of_profile(p["id"]):
        if c["custody_state"] in ("FILLING", "SEALED", "STAGED") and c["compliance_state"] == "COMPLIANT":
            c["compliance_state"] = "DEFICIENT"
            c["last_finding_code"] = PROFILE_SUSPENDED_FINDING
            affected.add(c["storage_unit_id"])
    for unit_id in affected:
        u = derive.unit(unit_id)
        if u is not None:
            reconcile_unit(u, "PROFILE_SUSPENDED")


def profile_reinstatement_cascade(p):
    affected = set()
    for c in derive.containers_of_profile(p["id"]):
        if c["compliance_state"] == "DEFICIENT" and c["last_finding_code"] == PROFILE_SUSPENDED_FINDING:
            c["compliance_state"] = "COMPLIANT"
            affected.add(c["storage_unit_id"])
    for unit_id in affected:
        u = derive.unit(unit_id)
        if u is not None:
            reconcile_unit(u)


# ---------------------------------------------------------------------------
# CASCADE-3: shipment rejection
# ---------------------------------------------------------------------------

def shipment_rejection_cascade(m):
    """Every line returns, every still-held container is voided, every affected
    unit recomputes, and the provisional charge is voided on the generator."""
    affected = set()
    for ln in derive.lines_of(m["id"]):
        ln["returned_quantity_kg"] = qd(D(ln["received_quantity_kg"] or 0), 3)
        ln["accepted_quantity_kg"] = qd(Decimal(0), 3)
        ln["line_status"] = "RETURNED"
        for c in derive.containers_of_line(ln["id"]):
            if c["custody_state"] in ("FILLING", "SEALED"):
                c["custody_state"] = "VOIDED"
                affected.add(c["storage_unit_id"])
    for unit_id in affected:
        u = derive.unit(unit_id)
        if u is not None:
            reconcile_unit(u)

    g = derive.generator(m["generator_id"])
    if g is not None:
        provisional = int(m["provisional_charge_cents"] or 0)
        g["open_charge_cents"] -= provisional
        g["voided_charge_cents"] += provisional

    m["status"] = "REJECTED_RETURNED"
    m["resolution_type"] = "REJECT_RETURN"
    m["discrepancy_resolved_at"] = now()


# ---------------------------------------------------------------------------
# permit termination cascade
# ---------------------------------------------------------------------------

def permit_termination_cascade(f):
    for u in derive.units_of_facility(f["id"]):
        if u["status"] == "ACTIVE":
            u["status"] = "CLOSING"
            u["closure_plan_ref"] = "PERMIT_TERMINATION"
            reconcile_unit(u)
