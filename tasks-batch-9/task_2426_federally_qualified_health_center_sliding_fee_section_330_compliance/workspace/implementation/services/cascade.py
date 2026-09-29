"""The multi-hop cascades of PRD 3.4, 3.7 and 3.8."""

import db
from services import charge
from services import fee_schedule as fs
from services import health_center as hc_svc


def windows_overlap(a, b):
    """Both windows are CLOSED intervals."""
    return a["effective_date"] <= b["expires_at"] and b["effective_date"] <= a["expires_at"]


# --------------------------------------------------------------------------- #
# income-verification VERIFY cascade (depth 5)
# --------------------------------------------------------------------------- #


def verify_cascade(verification):
    """Hops 1, 2 and 4.  The caller performs hop 3 (patient ledger + version)
    and hop 5 (grantee receivable + version)."""
    patient_id = verification["patient_id"]

    # Hop 1 — supersede the patient's overlapping VERIFIED verification.
    others = [
        v
        for v in db.db.income_verifications.values()
        if v["patient_id"] == patient_id
        and v["id"] != verification["id"]
        and v["status"] == "VERIFIED"
    ]
    superseded_id = None
    for other in db.in_creation_order(others):
        if windows_overlap(other, verification):
            other["status"] = "SUPERSEDED"
            db.touch(other)
            superseded_id = other["id"]
    verification["supersedes_income_verification_id"] = superseded_id

    # Hop 2 — rewrite already-billed charges under the FINAL variant.
    candidates = [e for e in db.db.encounters.values() if e["patient_id"] == patient_id]
    affected = []
    for enc in db.in_creation_order(candidates):
        if enc["pps_claim_status"] not in ("BILLED", "PAID"):
            continue
        if not (
            verification["effective_date"] <= enc["encounter_date"] <= verification["expires_at"]
        ):
            continue
        schedule = db.db.fee_schedules.get(enc["fee_schedule_id"])
        if schedule is None:
            continue
        chosen = fs.select_verification(patient_id, enc["encounter_date"])
        result = charge.patient_charge(
            enc["payer_type"], enc["gross_charge_cents"], schedule, chosen
        )
        previous = enc["patient_charge_cents"]
        enc["patient_charge_cents"] = result["patient_charge_cents"]
        enc["charge_basis"] = result["charge_basis"]
        enc["sliding_fee_applied"] = result["sliding_fee_applied"]
        enc["pinned_discount_tier_id"] = result["pinned_discount_tier_id"]
        enc["income_verification_id"] = result["income_verification_id"]
        enc["charge_adjustment_cents"] = result["patient_charge_cents"] - previous
        enc["pps_claim_status"] = "PENDING_ADJUSTMENT"
        db.touch(enc)
        affected.append(enc)

    # Hop 4 — revisit the wraparound residual of the recomputed encounters.
    for enc in affected:
        if enc["payer_type"] == "MEDICAID_MCO":
            charge.recompute_wraparound(enc)

    return affected


# --------------------------------------------------------------------------- #
# encounter void (compensating action)
# --------------------------------------------------------------------------- #


def void_encounter(enc, reason, adjustment_excludes_waiver=False):
    """PRD 3.7 for the operator-driven edges; the REMOVE_SITE cascade of PRD 3.8
    pins charge_adjustment_cents to the negative of patient_charge_cents alone,
    which is what `adjustment_excludes_waiver` selects."""
    enc["pps_claim_status"] = "VOID"
    enc["void_reason"] = reason
    if adjustment_excludes_waiver:
        enc["charge_adjustment_cents"] = -enc["patient_charge_cents"]
    else:
        enc["charge_adjustment_cents"] = -(
            enc["patient_charge_cents"] - enc["waived_amount_cents"]
        )
    enc["wraparound_status"] = "NOT_APPLICABLE"
    db.touch(enc)

    patient = db.db.patients.get(enc["patient_id"])
    if patient is not None:
        db.touch(patient)


# --------------------------------------------------------------------------- #
# site-visit-finding escalation / resolution
# --------------------------------------------------------------------------- #


def escalate_finding(finding):
    """Escalation cascade hops 1, 4 and 5.  Hops 2 and 3 are derived postures;
    the grantee's own version increment is the caller's (sweep step S4)."""
    finding["status"] = "ESCALATED"
    finding["escalated_at"] = db.now()
    db.touch(finding)
    hc_svc.apply_posture_side_effects(finding["health_center_id"])


def resolve_finding(finding):
    """Compensating cascade hops 1, 3 and 4."""
    finding["status"] = "RESOLVED"
    db.touch(finding)
    hc_svc.apply_posture_side_effects(finding["health_center_id"])
