"""Time-gated auto-transitions fired by /_clock/advance (SCAFFOLD §1.2, PRD §3.16).

For each clock advance:
  - PowerOfAttorney rows in PENDING with now()>=effective_at AND estate.admin_phase=DRAFT
       → ACTIVE
  - GuardianshipDirective rows in DRAFT with now()>=effective_at,
       estate.admin_phase=IN_PROBATE, guardian fiduciary CONFIRMED → EFFECTIVE
       Side-effect: Beneficiary.guardianship_id = directive.id
  - HIPAAAuthorization rows in ACTIVE with expires_at!=null and now()>=expires_at
       → EXPIRED
"""
from __future__ import annotations

from db import store
from services.common import bump


def sweep_time_gated() -> None:
    """Evaluate every time-gated auto-transition. Must be called holding store.lock."""
    now = store.logical_now()

    # 1. POA PENDING → ACTIVE when estate is DRAFT.
    for poa in store.poas.values():
        if poa["status"] != "PENDING":
            continue
        eff = poa.get("effective_at")
        if not eff or now < eff:
            continue
        estate = store.estates.get(poa["estate_id"])
        if not estate or estate["admin_phase"] != "DRAFT":
            continue
        poa["status"] = "ACTIVE"
        bump(poa)

    # 2. GuardianshipDirective DRAFT → EFFECTIVE.
    for g in store.guardianships.values():
        if g["status"] != "DRAFT":
            continue
        eff = g.get("effective_at")
        if not eff or now < eff:
            continue
        estate = store.estates.get(g["estate_id"])
        if not estate or estate["admin_phase"] != "IN_PROBATE":
            continue
        guardian = store.fiduciaries.get(g["guardian_fiduciary_id"])
        if not guardian or guardian.get("status") != "CONFIRMED":
            continue
        if guardian.get("scope_type") != "GUARDIAN":
            continue

        # If there is already an EFFECTIVE directive for the same minor,
        # supersede it.
        for prior in store.guardianships.values():
            if prior["id"] == g["id"]:
                continue
            if prior["estate_id"] != g["estate_id"]:
                continue
            if prior["minor_beneficiary_id"] != g["minor_beneficiary_id"]:
                continue
            if prior["status"] == "EFFECTIVE":
                prior["status"] = "SUPERSEDED"
                bump(prior)

        g["status"] = "EFFECTIVE"
        bump(g)
        # Wire the minor's guardianship_id.
        minor = store.beneficiaries.get(g["minor_beneficiary_id"])
        if minor:
            minor["guardianship_id"] = g["id"]
            bump(minor)

    # 3. HIPAA ACTIVE → EXPIRED when expires_at non-null and reached.
    for h in store.hipaa_auths.values():
        if h["status"] != "ACTIVE":
            continue
        exp = h.get("expires_at")
        if exp is None or now < exp:
            continue
        h["status"] = "EXPIRED"
        bump(h)
