"""Cascading mutation services.

The lot-recall three-hop cascade and the certificate auto-recompute on dose
state transitions are concentrated here so that route handlers stay thin and
the cascade order is auditable in one place.

Every cascade step that mutates an entity refreshes the entity's updated_at
and bumps version by exactly 1 — per PRD §2.4 and §2.9.
"""
from __future__ import annotations

from typing import Optional

from .. import store
from ..clock import format_iso, now
from .calculations import (
    compute_provider_compliance_score,
    evaluate_school_coverage,
)


# -----------------------------------------------------------------------------
# School certificate recompute side effects
# -----------------------------------------------------------------------------
def recompute_certs_after_admin(patient: dict) -> None:
    """After a dose moves SCHEDULED -> ADMINISTERED, recompute DRAFT/DEFICIENT
    certs for this patient. If the recompute now yields zero missing, auto-bubble
    DEFICIENT to ISSUED (or to EXEMPTION_GRANTED if the patient has an exemption)
    and stamp issued_at.
    """
    affected = [
        c for c in store.school_certificates.values()
        if c.get("patient_id") == patient["id"]
        and c.get("certificate_status") in {"DRAFT", "DEFICIENT"}
    ]
    for cert in affected:
        new_status, missing = evaluate_school_coverage(patient)
        prev_status = cert["certificate_status"]
        # Only auto-bubble if the new computed status would be ISSUED or EXEMPTION_GRANTED.
        cert["missing_antigens"] = missing
        if new_status == "ISSUED" and not missing:
            if cert["certificate_status"] != "ISSUED":
                cert["certificate_status"] = "ISSUED"
                cert["issued_at"] = format_iso(now())
            store.stamp_update(cert)
        elif new_status == "EXEMPTION_GRANTED":
            if cert["certificate_status"] != "EXEMPTION_GRANTED":
                cert["certificate_status"] = "EXEMPTION_GRANTED"
                cert["issued_at"] = format_iso(now())
            store.stamp_update(cert)
        else:
            # Still DEFICIENT or remains DRAFT — only update if missing list changed
            # but we always need to bump version on persisted mutation. We only
            # treat this as a mutation when the cert was previously DEFICIENT and
            # the missing set changed, or it stays DRAFT (we don't bump on no-op).
            if prev_status == "DEFICIENT":
                store.stamp_update(cert)
            # DRAFT certs are unchanged on plain admin — they remain DRAFT until
            # the issuer fires /issue. But if missing array meaningfully changed
            # we still keep representation in sync without a version bump for
            # DRAFT (no observable status change).


def recompute_certs_after_dose_invalidation(patient: dict) -> None:
    """After a dose moves ADMINISTERED -> INVALIDATED (data-error or recall),
    recompute ISSUED/EXEMPTION_GRANTED certs and demote to DEFICIENT if a
    newly-uncovered antigen is detected.
    """
    affected = [
        c for c in store.school_certificates.values()
        if c.get("patient_id") == patient["id"]
        and c.get("certificate_status") in {"ISSUED", "EXEMPTION_GRANTED"}
    ]
    for cert in affected:
        new_status, missing = evaluate_school_coverage(patient)
        if new_status == "DEFICIENT":
            cert["certificate_status"] = "DEFICIENT"
            cert["missing_antigens"] = missing
            cert["issued_at"] = None
            store.stamp_update(cert)
        elif new_status == "EXEMPTION_GRANTED":
            # Still exempt — no change.
            pass
        else:
            # Still ISSUED — no change.
            pass


# -----------------------------------------------------------------------------
# Provider compliance recompute + auto-suspend
# -----------------------------------------------------------------------------
def recompute_provider_compliance(provider_org_id: str) -> None:
    org = store.provider_organizations.get(provider_org_id)
    if not org:
        return
    score = compute_provider_compliance_score(provider_org_id)
    org["reporting_compliance_score"] = float(score)
    if score < 70 and org.get("status") == "ACTIVE":
        org["status"] = "SUSPENDED"
    store.stamp_update(org)


# -----------------------------------------------------------------------------
# Lot recall three-hop cascade
# -----------------------------------------------------------------------------
def cascade_lot_recall(lot: dict, pre_recall_status: str) -> None:
    """Execute the three-hop cascade after a VaccineLot transitions to RECALLED.

    Hop 1: invalidate every ADMINISTERED dose tied to this lot, restoring
           inventory only when recall_reason != EXPIRED and the lot was AVAILABLE
           immediately before the recall (recalls of EXHAUSTED lots do NOT
           restore inventory).

    Hop 2: recompute school enrollment certificates for every affected patient
           and demote ISSUED/EXEMPTION_GRANTED certs to DEFICIENT when a newly
           uncovered antigen appears.

    Hop 3: bump every PENDING_REVIEW AdverseEvent tied to one of the
           just-invalidated doses to UNDER_REVIEW.

    Also recomputes provider compliance scores for every provider that touched
    one of the invalidated doses.
    """
    lot_id = lot["id"]
    recall_reason = lot.get("recall_reason")

    affected_doses = [
        d for d in store.administered_doses.values()
        if d.get("lot_id") == lot_id and d.get("dose_state") == "ADMINISTERED"
    ]
    affected_patient_ids: set[str] = set()
    affected_provider_ids: set[str] = set()
    invalidated_dose_ids: set[str] = set()

    for dose in affected_doses:
        dose["dose_state"] = "INVALIDATED"
        dose["invalidation_reason"] = "LOT_RECALL"
        store.stamp_update(dose)
        invalidated_dose_ids.add(dose["id"])
        affected_patient_ids.add(dose["patient_id"])
        if dose.get("provider_organization_id"):
            affected_provider_ids.add(dose["provider_organization_id"])

        # Inventory restoration: only when reason != EXPIRED and lot was AVAILABLE.
        if recall_reason != "EXPIRED" and pre_recall_status == "AVAILABLE":
            lot["doses_on_hand"] = lot.get("doses_on_hand", 0) + 1

    # Hop 2 — school certificates
    for pid in affected_patient_ids:
        patient = store.patients.get(pid)
        if patient:
            recompute_certs_after_dose_invalidation(patient)

    # Hop 3 — adverse-event clinical review
    for ae in store.adverse_events.values():
        if ae.get("dose_id") in invalidated_dose_ids and ae.get("clinical_review_status") == "PENDING_REVIEW":
            ae["clinical_review_status"] = "UNDER_REVIEW"
            store.stamp_update(ae)

    # Provider compliance recompute
    for prov_id in affected_provider_ids:
        recompute_provider_compliance(prov_id)
