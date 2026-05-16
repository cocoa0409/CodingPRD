"""Composite setup helpers — multi-step preambles tests can reuse.

The hospital revenue cycle pipeline is long: patient -> policy ->
encounter (REGISTERED) -> verify-eligibility -> ELIGIBILITY_VERIFIED ->
add charges + post -> discharge -> CHARGES_CAPTURED -> coding finalize
-> CODED -> clearance -> CLEARED -> issue-bill -> BILLED -> payments
(RESOLVED) or 90-day wait + write-off (WRITTEN_OFF). Most interesting
test claims need the system in a late-pipeline state.

PRD §2.1 — all five roles are OPAQUE. X-User-ID is audit data; no
ownership check is performed against it. Shared role-header constants
in TEST_USERS are canonical for every call.

Setup helpers use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    clock_advance_payload,
    create_charge_payload,
    create_encounter_payload,
    create_patient_payload,
    create_policy_payload,
    iso_offset,
    post_payment_payload,
    submit_clearance_payload,
    submit_coding_payload,
    verify_eligibility_payload,
)
from .test_users import TEST_USERS


# ===========================================================================
# Clock — PRD §2.11
# ===========================================================================
def advance_clock_to(iso_timestamp: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    """POST /_clock/advance.

    PRD §2.11: "The capability is available to TestHarness, Biller, and
    RegistrationClerk."
    """
    headers = headers or TEST_USERS["test_harness_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(to_timestamp=iso_timestamp), headers,
    )
    return get_success_data(resp)


def anchor_clock_in_plan_year_2026() -> None:
    """Pin the server clock to 2026-02-01 so PRD §3.3's plan_year ==
    current calendar year predicate is satisfied for any
    plan_year=2026 policy created by these fixtures.
    """
    advance_clock_to(TEST_DEFAULTS["CLOCK_ANCHOR_2026"])


# ===========================================================================
# Tier 1: Patient + InsurancePolicy (basic registry)
# ===========================================================================
def create_patient(
    *,
    mrn: Optional[str] = None,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /patients — RegistrationClerk only per PRD §4."""
    headers = headers or TEST_USERS["registration_clerk_headers"]
    resp = api_client.create_patient(
        create_patient_payload(
            mrn=mrn, full_name=full_name, date_of_birth=date_of_birth,
        ),
        headers,
    )
    return get_success_data(resp)


def create_policy(
    *,
    patient: Dict[str, Any],
    payer_name: Optional[str] = None,
    policy_number: Optional[str] = None,
    plan_year: Optional[int] = None,
    deductible_cents: Optional[int] = None,
    coinsurance_rate_bps: Optional[int] = None,
    oop_max_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /patients/{patient_id}/policies — RegistrationClerk only."""
    headers = headers or TEST_USERS["registration_clerk_headers"]
    resp = api_client.create_policy(
        patient["id"],
        create_policy_payload(
            payer_name=payer_name,
            policy_number=policy_number,
            plan_year=plan_year,
            deductible_cents=deductible_cents,
            coinsurance_rate_bps=coinsurance_rate_bps,
            oop_max_cents=oop_max_cents,
        ),
        headers,
    )
    return get_success_data(resp)


def setup_patient_with_policy(
    *,
    plan_year: Optional[int] = None,
    deductible_cents: Optional[int] = None,
    coinsurance_rate_bps: Optional[int] = None,
    oop_max_cents: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Compose: patient + policy (defaults inside current plan year).
    Returns (patient, policy).
    """
    patient = create_patient()
    policy = create_policy(
        patient=patient,
        plan_year=plan_year,
        deductible_cents=deductible_cents,
        coinsurance_rate_bps=coinsurance_rate_bps,
        oop_max_cents=oop_max_cents,
    )
    return patient, policy


# ===========================================================================
# Tier 2: Encounter — REGISTERED
# ===========================================================================
def create_encounter(
    *,
    patient: Dict[str, Any],
    policy: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /encounters — RegistrationClerk only per PRD §4."""
    headers = headers or TEST_USERS["registration_clerk_headers"]
    resp = api_client.create_encounter(
        create_encounter_payload(
            patient_id=patient["id"], policy_id=policy["id"],
        ),
        headers,
    )
    return get_success_data(resp)


def setup_registered_encounter(
    *,
    plan_year: Optional[int] = None,
    deductible_cents: Optional[int] = None,
    coinsurance_rate_bps: Optional[int] = None,
    oop_max_cents: Optional[int] = None,
    anchor_clock: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Compose: clock anchor + patient + policy + REGISTERED encounter.
    Returns (patient, policy, encounter).
    """
    if anchor_clock:
        anchor_clock_in_plan_year_2026()
    patient, policy = setup_patient_with_policy(
        plan_year=plan_year,
        deductible_cents=deductible_cents,
        coinsurance_rate_bps=coinsurance_rate_bps,
        oop_max_cents=oop_max_cents,
    )
    encounter = create_encounter(patient=patient, policy=policy)
    return patient, policy, encounter


# ===========================================================================
# Tier 3: Encounter — ELIGIBILITY_VERIFIED (verify-eligibility)
# ===========================================================================
def verify_eligibility(
    *,
    encounter: Dict[str, Any],
    policy_eligible: bool = True,
    denial_code: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /encounters/{id}/verify-eligibility — RegistrationClerk."""
    headers = headers or TEST_USERS["registration_clerk_headers"]
    resp = api_client.verify_eligibility(
        encounter["id"],
        verify_eligibility_payload(
            policy_eligible=policy_eligible, denial_code=denial_code,
        ),
        headers,
    )
    return get_success_data(resp)


def setup_eligibility_verified_encounter(
    *,
    plan_year: Optional[int] = None,
    deductible_cents: Optional[int] = None,
    coinsurance_rate_bps: Optional[int] = None,
    oop_max_cents: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Compose: REGISTERED encounter + verify-eligibility (eligible).
    Returns (patient, policy, encounter) with encounter in
    ELIGIBILITY_VERIFIED.
    """
    patient, policy, encounter = setup_registered_encounter(
        plan_year=plan_year,
        deductible_cents=deductible_cents,
        coinsurance_rate_bps=coinsurance_rate_bps,
        oop_max_cents=oop_max_cents,
    )
    verify_eligibility(encounter=encounter, policy_eligible=True)
    encounter = re_get_encounter(encounter["id"])
    return patient, policy, encounter


# ===========================================================================
# Tier 4: ChargeItem creation + posting
# ===========================================================================
def add_charge(
    *,
    encounter: Dict[str, Any],
    cpt_code: Optional[str] = None,
    description: Optional[str] = None,
    quantity: Optional[int] = None,
    unit_price_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /encounters/{id}/charges — ChargeCaptureClerk only."""
    headers = headers or TEST_USERS["charge_capture_clerk_headers"]
    resp = api_client.create_charge(
        encounter["id"],
        create_charge_payload(
            cpt_code=cpt_code,
            description=description,
            quantity=quantity,
            unit_price_cents=unit_price_cents,
        ),
        headers,
    )
    return get_success_data(resp)


def post_charge(
    *,
    encounter: Dict[str, Any],
    charge: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /encounters/{id}/charges/{cid}/post — ChargeCaptureClerk."""
    headers = headers or TEST_USERS["charge_capture_clerk_headers"]
    resp = api_client.post_charge(encounter["id"], charge["id"], headers)
    return get_success_data(resp)


def void_charge(
    *,
    encounter: Dict[str, Any],
    charge: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /encounters/{id}/charges/{cid}/void — ChargeCaptureClerk."""
    headers = headers or TEST_USERS["charge_capture_clerk_headers"]
    resp = api_client.void_charge(encounter["id"], charge["id"], headers)
    return get_success_data(resp)


def add_and_post_charge(
    *,
    encounter: Dict[str, Any],
    cpt_code: Optional[str] = None,
    quantity: Optional[int] = None,
    unit_price_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """Compose: create one charge + post it. Returns the POSTED charge."""
    charge = add_charge(
        encounter=encounter, cpt_code=cpt_code, quantity=quantity,
        unit_price_cents=unit_price_cents,
    )
    return post_charge(encounter=encounter, charge=charge)


# ===========================================================================
# Tier 5: Encounter — CHARGES_CAPTURED (discharge)
# ===========================================================================
def discharge_encounter(
    *,
    encounter: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /encounters/{id}/discharge — RegistrationClerk only."""
    headers = headers or TEST_USERS["registration_clerk_headers"]
    resp = api_client.discharge_encounter(encounter["id"], headers)
    return get_success_data(resp)


def setup_charges_captured_encounter(
    *,
    plan_year: Optional[int] = None,
    deductible_cents: Optional[int] = None,
    coinsurance_rate_bps: Optional[int] = None,
    oop_max_cents: Optional[int] = None,
    charges: Optional[List[Dict[str, Any]]] = None,
    unit_price_cents: int = 150_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           List[Dict[str, Any]]]:
    """Compose: eligibility_verified encounter + N posted charges +
    discharge. Returns (patient, policy, CHARGES_CAPTURED encounter,
    [posted_charges]).

    If `charges` is provided, each dict supplies overrides for the
    charge factory; otherwise one default charge is created and posted.
    """
    patient, policy, encounter = setup_eligibility_verified_encounter(
        plan_year=plan_year,
        deductible_cents=deductible_cents,
        coinsurance_rate_bps=coinsurance_rate_bps,
        oop_max_cents=oop_max_cents,
    )
    posted: List[Dict[str, Any]] = []
    if charges is None:
        charges = [{"unit_price_cents": unit_price_cents}]
    for spec in charges:
        ch = add_and_post_charge(encounter=encounter, **spec)
        posted.append(ch)
    discharge_encounter(encounter=encounter)
    encounter = re_get_encounter(encounter["id"])
    return patient, policy, encounter, posted


# ===========================================================================
# Tier 6: Encounter — CODED (coding finalize)
# ===========================================================================
def finalize_coding(
    *,
    encounter: Dict[str, Any],
    primary_icd10: Optional[str] = None,
    secondary_icd10: Optional[List[str]] = None,
    cpt_codes: Optional[List[str]] = None,
    coder_id: Optional[str] = None,
    finalize: bool = True,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /encounters/{id}/coding — Coder only per PRD §4."""
    headers = headers or TEST_USERS["coder_headers"]
    resp = api_client.submit_coding(
        encounter["id"],
        submit_coding_payload(
            primary_icd10=primary_icd10,
            secondary_icd10=secondary_icd10,
            cpt_codes=cpt_codes,
            coder_id=coder_id,
            finalize=finalize,
        ),
        headers,
    )
    return get_success_data(resp)


def setup_coded_encounter(
    *,
    plan_year: Optional[int] = None,
    deductible_cents: Optional[int] = None,
    coinsurance_rate_bps: Optional[int] = None,
    oop_max_cents: Optional[int] = None,
    charges: Optional[List[Dict[str, Any]]] = None,
    unit_price_cents: int = 150_000,
    primary_icd10: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           List[Dict[str, Any]]]:
    """Compose: CHARGES_CAPTURED encounter + coding finalize.
    Returns (patient, policy, CODED encounter, [posted_charges]).
    """
    patient, policy, encounter, posted = (
        setup_charges_captured_encounter(
            plan_year=plan_year,
            deductible_cents=deductible_cents,
            coinsurance_rate_bps=coinsurance_rate_bps,
            oop_max_cents=oop_max_cents,
            charges=charges,
            unit_price_cents=unit_price_cents,
        )
    )
    cpt_codes = [c["cpt_code"] for c in posted]
    finalize_coding(
        encounter=encounter, primary_icd10=primary_icd10,
        cpt_codes=cpt_codes,
    )
    encounter = re_get_encounter(encounter["id"])
    return patient, policy, encounter, posted


# ===========================================================================
# Tier 7: Encounter — CLEARED (clearance)
# ===========================================================================
def submit_clearance(
    *,
    encounter: Dict[str, Any],
    decision: str = "APPROVED",
    allowed_amount_cents: int = 0,
    denial_reason_code: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /encounters/{id}/clearance — Biller only per PRD §4."""
    headers = headers or TEST_USERS["biller_headers"]
    resp = api_client.submit_clearance(
        encounter["id"],
        submit_clearance_payload(
            decision=decision,
            allowed_amount_cents=allowed_amount_cents,
            denial_reason_code=denial_reason_code,
        ),
        headers,
    )
    return get_success_data(resp)


def setup_cleared_encounter(
    *,
    deductible_cents: Optional[int] = None,
    coinsurance_rate_bps: Optional[int] = None,
    oop_max_cents: Optional[int] = None,
    unit_price_cents: int = 150_000,
    decision: str = "APPROVED",
    allowed_amount_cents: Optional[int] = None,
    denial_reason_code: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           List[Dict[str, Any]]]:
    """Compose: CODED encounter + clearance decision -> CLEARED.
    Returns (patient, policy, CLEARED encounter, [posted_charges]).

    allowed_amount_cents defaults to the total charges (full allowance).
    """
    patient, policy, encounter, posted = setup_coded_encounter(
        deductible_cents=deductible_cents,
        coinsurance_rate_bps=coinsurance_rate_bps,
        oop_max_cents=oop_max_cents,
        unit_price_cents=unit_price_cents,
    )
    if allowed_amount_cents is None:
        allowed_amount_cents = encounter["total_charges_cents"]
    submit_clearance(
        encounter=encounter,
        decision=decision,
        allowed_amount_cents=allowed_amount_cents,
        denial_reason_code=denial_reason_code,
    )
    encounter = re_get_encounter(encounter["id"])
    return patient, policy, encounter, posted


# ===========================================================================
# Tier 8: Encounter — BILLED (issue-bill)
# ===========================================================================
def issue_bill(
    *,
    encounter: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /encounters/{id}/issue-bill — Biller only per PRD §4."""
    headers = headers or TEST_USERS["biller_headers"]
    resp = api_client.issue_bill(encounter["id"], headers)
    return get_success_data(resp)


def setup_billed_encounter(
    *,
    deductible_cents: Optional[int] = None,
    coinsurance_rate_bps: Optional[int] = None,
    oop_max_cents: Optional[int] = None,
    unit_price_cents: int = 150_000,
    decision: str = "APPROVED",
    allowed_amount_cents: Optional[int] = None,
    denial_reason_code: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           List[Dict[str, Any]]]:
    """Compose: CLEARED encounter + issue-bill -> BILLED.
    Returns (patient, policy, BILLED encounter, [posted_charges]).
    """
    patient, policy, encounter, posted = setup_cleared_encounter(
        deductible_cents=deductible_cents,
        coinsurance_rate_bps=coinsurance_rate_bps,
        oop_max_cents=oop_max_cents,
        unit_price_cents=unit_price_cents,
        decision=decision,
        allowed_amount_cents=allowed_amount_cents,
        denial_reason_code=denial_reason_code,
    )
    issue_bill(encounter=encounter)
    encounter = re_get_encounter(encounter["id"])
    return patient, policy, encounter, posted


# ===========================================================================
# Tier 9: Billed encounter with a known patient_responsibility_cents
# (used to set the running balance for payment / write-off scenarios).
# ===========================================================================
def setup_billed_with_balance(
    *,
    patient_responsibility_cents: int = 10_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build a BILLED encounter whose patient_responsibility_cents
    equals the requested value. Returns (patient, policy, encounter).

    Trick: set deductible_cents = patient_responsibility_cents, set
    coinsurance_rate_bps = 0, set oop_max_cents = max(target,
    deductible_cents) so the OOP cap does not clip. Charge a single
    line of that exact value; approve at the same value. The waterfall
    yields patient = full deductible_portion = target, payer = 0.
    """
    target = patient_responsibility_cents
    patient, policy, encounter, _ = setup_billed_encounter(
        deductible_cents=target,
        coinsurance_rate_bps=0,
        oop_max_cents=max(target, 1),
        unit_price_cents=target,
        decision="APPROVED",
        allowed_amount_cents=target,
    )
    return patient, policy, encounter


# ===========================================================================
# Tier 10: Payments
# ===========================================================================
def post_payment(
    *,
    encounter: Dict[str, Any],
    amount_cents: int = 1,
    method: str = "CASH",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /encounters/{id}/payments — Biller only per PRD §4."""
    headers = headers or TEST_USERS["biller_headers"]
    resp = api_client.post_payment(
        encounter["id"],
        post_payment_payload(amount_cents=amount_cents, method=method),
        headers,
    )
    return get_success_data(resp)


def setup_resolved_encounter(
    *,
    patient_responsibility_cents: int = 10_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Compose: BILLED-with-balance + a single payment of the exact
    balance amount, driving the encounter to RESOLVED.
    Returns (patient, policy, RESOLVED encounter).
    """
    patient, policy, encounter = setup_billed_with_balance(
        patient_responsibility_cents=patient_responsibility_cents,
    )
    post_payment(
        encounter=encounter,
        amount_cents=patient_responsibility_cents,
        method="CASH",
    )
    encounter = re_get_encounter(encounter["id"])
    return patient, policy, encounter


# ===========================================================================
# Tier 11: Write-off
# ===========================================================================
def write_off_encounter(
    *,
    encounter: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /encounters/{id}/write-off — Biller only per PRD §4."""
    headers = headers or TEST_USERS["biller_headers"]
    resp = api_client.write_off_encounter(encounter["id"], headers)
    return get_success_data(resp)


def setup_written_off_encounter(
    *,
    patient_responsibility_cents: int = 10_000,
    billed_at_iso: str = "2026-02-01T00:00:00.000Z",
    write_off_at_iso: str = "2026-05-02T00:00:00.000Z",
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Compose: BILLED-with-balance + clock to billed_at_iso (i.e., the
    bill is issued at this point) + advance 90+ days + write-off.
    Returns (patient, policy, WRITTEN_OFF encounter).
    """
    # Anchor the clock so issue_bill (inside setup_billed_with_balance)
    # stamps billed_at = billed_at_iso.
    advance_clock_to(billed_at_iso)
    patient, policy, encounter = setup_billed_with_balance(
        patient_responsibility_cents=patient_responsibility_cents,
    )
    # Re-anchor the clock past the 90-day gate.
    advance_clock_to(write_off_at_iso)
    write_off_encounter(encounter=encounter)
    encounter = re_get_encounter(encounter["id"])
    return patient, policy, encounter


# ===========================================================================
# Re-fetch helpers
# ===========================================================================
def re_get_encounter(encounter_id: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["registration_clerk_headers"]
    return get_success_data(
        api_client.get_encounter(encounter_id, headers),
    )


def re_get_patient(patient_id: str,
                   headers: Optional[Dict[str, str]] = None
                   ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["registration_clerk_headers"]
    return get_success_data(api_client.get_patient(patient_id, headers))


def re_get_policy(patient_id: str, policy_id: str,
                  headers: Optional[Dict[str, str]] = None
                  ) -> Dict[str, Any]:
    """Re-fetch a specific policy by listing the patient's policies and
    selecting by id. PRD exposes list-policies; no GET-by-id is
    promised, so use the list endpoint."""
    headers = headers or TEST_USERS["registration_clerk_headers"]
    resp = api_client.list_policies(patient_id, headers)
    body = resp.json()
    rows = body.get("data") or []
    for row in rows:
        if row.get("id") == policy_id:
            return row
    raise RuntimeError(
        f"policy {policy_id} not present in list for patient {patient_id}",
    )


# ===========================================================================
# Difficulty-design composite recipes — pre-built helpers for the
# scaffold_difficulty_design instances in SCAFFOLD_DIFFICULTY_DESIGN.yaml.
# ===========================================================================
def setup_difficulty_estimate_vs_final(
    *,
    deductible_cents: int = 100_000,
    coinsurance_rate_bps: int = 2000,
    oop_max_cents: int = 200_000,
    unit_price_cents: int = 150_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build through CHARGES_CAPTURED with a single POSTED charge of
    unit_price_cents. Returns (patient, policy, encounter) at
    CHARGES_CAPTURED — ready for the estimate vs final comparison.
    Used by SCAFFOLD_DIFFICULTY_DESIGN.yaml
    estimate_vs_final_patient_responsibility.
    """
    patient, policy, encounter, _ = setup_charges_captured_encounter(
        deductible_cents=deductible_cents,
        coinsurance_rate_bps=coinsurance_rate_bps,
        oop_max_cents=oop_max_cents,
        unit_price_cents=unit_price_cents,
    )
    return patient, policy, encounter


def setup_difficulty_two_billed_encounters(
    *,
    patient_responsibility_cents: int = 10_000,
) -> Tuple[Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]],
           Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]]:
    """Build TWO independent BILLED encounters with identical
    patient_responsibility_cents. Used by
    encounter_branching_billed_to_resolved_or_written_off.
    Returns ((pA, polA, encA), (pB, polB, encB)).

    The clock is left at the 2026-02-01 anchor so each encounter's
    billed_at is recorded there; tests can advance the clock past 90
    days for branch B without affecting branch A's payment branch.
    """
    a = setup_billed_with_balance(
        patient_responsibility_cents=patient_responsibility_cents,
    )
    b = setup_billed_with_balance(
        patient_responsibility_cents=patient_responsibility_cents,
    )
    return a, b


def setup_difficulty_two_registered_encounters() -> Tuple[
    Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]],
    Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]],
]:
    """Build TWO independent REGISTERED encounters, each with its own
    UNVERIFIED policy. Used by
    insurance_policy_branching_at_verification.
    Returns ((pA, polA, encA), (pB, polB, encB)).
    """
    a = setup_registered_encounter()
    b = setup_registered_encounter()
    return a, b


__all__ = [
    "advance_clock_to",
    "anchor_clock_in_plan_year_2026",
    "create_patient",
    "create_policy",
    "setup_patient_with_policy",
    "create_encounter",
    "setup_registered_encounter",
    "verify_eligibility",
    "setup_eligibility_verified_encounter",
    "add_charge",
    "post_charge",
    "void_charge",
    "add_and_post_charge",
    "discharge_encounter",
    "setup_charges_captured_encounter",
    "finalize_coding",
    "setup_coded_encounter",
    "submit_clearance",
    "setup_cleared_encounter",
    "issue_bill",
    "setup_billed_encounter",
    "setup_billed_with_balance",
    "post_payment",
    "setup_resolved_encounter",
    "write_off_encounter",
    "setup_written_off_encounter",
    "re_get_encounter",
    "re_get_patient",
    "re_get_policy",
    "setup_difficulty_estimate_vs_final",
    "setup_difficulty_two_billed_encounters",
    "setup_difficulty_two_registered_encounters",
]
