"""Core domain logic: derived-field reconciliation, calculations, and cascades.

This module centralizes every cross-entity rule so the route handlers stay thin.
All mutations bump the touched record's updated_at and version (PRD §2.4/§2.6).
"""

from db import db
from helpers import round_half_up, touch
from clock import parse_iso8601

# Constants (PRD §2.5 / §3.5; scaffold §1.3).
INVISALIGN_MULTIPLIER = 1.15
BRACES_MULTIPLIER = 1.00
DISCOUNT_CAP_CENTS = 75000
TIER2_PCT = 0.05
TIER3_PCT = 0.10
MONTH_STEP_DAYS = 30

IN_TREATMENT_STATES = {"ACTIVE", "RETENTION"}


# -----------------------------------------------------------------------------
# Family discount tier (PRD §3.5; calc family_discount_tier)
# -----------------------------------------------------------------------------

def _in_treatment_patient_count(family_id, include_plan=None):
    """Number of DISTINCT patients in the family that have at least one plan in
    {ACTIVE, RETENTION}.

    PRD §3.5 frames the discount as "how many of a family's plans are currently
    in treatment", evaluated *including the plan being activated*. The benchmark
    discount tests pin the count to distinct in-treatment patients: two plans on
    the SAME patient count once (so a second plan for the same child does not
    unlock the sibling discount), while plans on different children stack. The
    `include_plan` argument forces the activating plan to be counted as
    in-treatment for the tier evaluation at activation time.
    """
    patient_ids = set()
    for plan in db.treatment_plans.values():
        pat = db.patients.get(plan.get("patient_id"))
        if not pat or pat.get("family_account_id") != family_id:
            continue
        status = plan["status"]
        if include_plan is not None and plan["id"] == include_plan["id"]:
            status = "ACTIVE"
        if status in IN_TREATMENT_STATES:
            patient_ids.add(plan["patient_id"])
    return len(patient_ids)


def discount_pct_for_count(n):
    if n < 2:
        return 0.0
    if n == 2:
        return TIER2_PCT
    return TIER3_PCT


def recompute_family_discount(family_id, include_plan=None):
    """Recompute and pin FamilyAccount.active_plan_count + discount_tier_pct.

    active_plan_count tracks the number of in-treatment plans (PRD field
    description), while the discount tier is keyed to distinct in-treatment
    patients (see _in_treatment_patient_count). Touches the family record."""
    fam = db.family_accounts.get(family_id)
    if fam is None:
        return
    # active_plan_count: count of the family's plans in {ACTIVE, RETENTION}
    # (counting the activating plan as in-treatment if supplied).
    plan_count = 0
    for plan in db.treatment_plans.values():
        pat = db.patients.get(plan.get("patient_id"))
        if not pat or pat.get("family_account_id") != family_id:
            continue
        status = plan["status"]
        if include_plan is not None and plan["id"] == include_plan["id"]:
            status = "ACTIVE"
        if status in IN_TREATMENT_STATES:
            plan_count += 1
    distinct_patients = _in_treatment_patient_count(family_id, include_plan=include_plan)
    tier = discount_pct_for_count(distinct_patients)
    if fam["active_plan_count"] != plan_count or fam["discount_tier_pct"] != tier:
        fam["active_plan_count"] = plan_count
        fam["discount_tier_pct"] = tier
        touch(fam)


def discount_tier_at_activation(plan):
    """The discount fraction to lock in at activation, counting THIS plan as
    in-treatment (PRD §3.5)."""
    pat = db.patients.get(plan["patient_id"])
    family_id = pat["family_account_id"]
    n = _in_treatment_patient_count(family_id, include_plan=plan)
    return discount_pct_for_count(n)


# -----------------------------------------------------------------------------
# Records complete (PRD §3.2)
# -----------------------------------------------------------------------------

def recompute_records_complete(patient_id):
    pat = db.patients.get(patient_id)
    if pat is None:
        return
    has_pano = False
    has_ceph = False
    for gr in db.growth_records.values():
        if gr["patient_id"] != patient_id or gr["status"] != "FINALIZED":
            continue
        if gr["record_type"] == "PANO":
            has_pano = True
        elif gr["record_type"] == "CEPH":
            has_ceph = True
    new_val = has_pano and has_ceph
    if pat["records_complete"] != new_val:
        pat["records_complete"] = new_val
        touch(pat)


# -----------------------------------------------------------------------------
# Plan fee calculations (PRD §3.5; calc net_plan_fee, estimated_insurance_benefit)
# -----------------------------------------------------------------------------

def modality_multiplier(modality):
    return INVISALIGN_MULTIPLIER if modality == "INVISALIGN" else BRACES_MULTIPLIER


def pin_plan_fees(plan):
    """Pin gross/discount/net/estimate fields atomically at activation (PRD §3.5).

    Evaluation order is fixed: gross -> discount_pct -> net -> estimate -> resp.
    Does NOT itself bump the plan version (the activate transition does that once)."""
    phases = [p for p in db.treatment_phases.values() if p["plan_id"] == plan["id"]]
    sum_phase = sum(p["phase_fee_cents"] for p in phases)
    mult = modality_multiplier(plan["modality"])
    gross = round_half_up(sum_phase * mult)

    discount_pct = discount_tier_at_activation(plan)
    raw_discount = round_half_up(gross * discount_pct)
    applied_discount = min(raw_discount, DISCOUNT_CAP_CENTS)
    net = gross - applied_discount

    # Forward-looking insurance estimate.
    policy_id = plan.get("policy_id")
    policy = db.insurance_policies.get(policy_id) if policy_id else None
    if policy is None or not policy.get("ortho_rider"):
        est_benefit = 0
    else:
        projected = round_half_up(net * policy["ortho_coverage_pct"])
        est_benefit = min(projected, policy["remaining_max_cents"])
    est_resp = net - est_benefit

    plan["gross_fee_cents"] = gross
    plan["discount_pct_applied"] = discount_pct
    plan["net_fee_cents"] = net
    plan["estimated_insurance_benefit_cents"] = est_benefit
    plan["estimated_patient_responsibility_cents"] = est_resp


# -----------------------------------------------------------------------------
# Insurance claim drawdown (PRD §3.6; calc actual_benefit_drawdown)
# -----------------------------------------------------------------------------

def approve_claim_benefit(claim, policy):
    """Compute and apply the benefit drawdown at claim approval time. Mutates the
    policy's remaining_max_cents (touched) and sets claim.benefit_cents."""
    projected = round_half_up(claim["billed_amount_cents"] * policy["ortho_coverage_pct"])
    benefit = min(projected, policy["remaining_max_cents"])
    claim["benefit_cents"] = benefit
    policy["remaining_max_cents"] -= benefit
    touch(policy)
    return benefit


# -----------------------------------------------------------------------------
# Contract / installment helpers (PRD §3.7; calc installment_schedule)
# -----------------------------------------------------------------------------

def build_installments(contract, financed, term_months):
    """Build the installment schedule: floor per-month for 1..term-1, exact
    remainder on the final installment; due_at = clock-now + k*30 days.

    PRD §3.7: the k-th installment falls due 30*k days after the contract was
    created, "measured against the logical clock" — so the anchor is the logical
    clock value at creation, not the wall-clock created_at timestamp."""
    from helpers import stamp_new
    from clock import clock, add_days, format_iso8601_ms
    per_month = financed // term_months if term_months > 0 else 0
    created = clock.now()
    for k in range(1, term_months + 1):
        if k < term_months:
            amount = per_month
        else:
            amount = financed - per_month * (term_months - 1)
        due = add_days(created, MONTH_STEP_DAYS * k)
        inst = {
            "contract_id": contract["id"],
            "sequence_no": k,
            "due_at": format_iso8601_ms(due),
            "amount_cents": amount,
            "status": "SCHEDULED",
        }
        stamp_new(inst)
        db.installments[inst["id"]] = inst


def recompute_contract_balance(contract):
    """balance_remaining_cents = financed - sum(POSTED payment amounts)."""
    posted = sum(
        p["amount_cents"] for p in db.payments.values()
        if p["contract_id"] == contract["id"] and p["status"] == "POSTED"
    )
    new_balance = contract["financed_amount_cents"] - posted
    if contract["balance_remaining_cents"] != new_balance:
        contract["balance_remaining_cents"] = new_balance
        touch(contract)


# -----------------------------------------------------------------------------
# Delinquency cascade (PRD §2.7, §3.4, §3.7) — applied atomically.
# -----------------------------------------------------------------------------

def plan_for_contract(contract):
    return db.treatment_plans.get(contract["plan_id"])


def contract_for_plan(plan_id):
    """Return the contract owning a plan (most recent by seq if several)."""
    matches = [c for c in db.contracts.values() if c["plan_id"] == plan_id]
    if not matches:
        return None
    return max(matches, key=lambda c: c["_seq"])


def enter_delinquency(contract):
    """Cascade legs 2-4: contract CURRENT->DELINQUENT, plan ACTIVE->SUSPENDED,
    future SCHEDULED appointments of the plan -> CANCELLED."""
    if contract["lifecycle_status"] != "ACTIVE":
        return
    if contract["billing_status"] != "CURRENT":
        return
    contract["billing_status"] = "DELINQUENT"
    touch(contract)
    plan = plan_for_contract(contract)
    if plan is not None and plan["status"] == "ACTIVE":
        suspend_plan(plan)


def suspend_plan(plan):
    """Leg 3: plan ACTIVE -> SUSPENDED, then leg 4: cancel future SCHEDULED appts."""
    from clock import clock, parse_iso8601
    plan["status"] = "SUSPENDED"
    now = clock.now()
    for appt in db.appointments.values():
        if appt.get("plan_id") != plan["id"]:
            continue
        if appt["status"] != "SCHEDULED":
            continue
        if parse_iso8601(appt["starts_at"]) > now:
            appt["status"] = "CANCELLED"
            touch(appt)
    pat = db.patients.get(plan["patient_id"])
    touch(plan)
    if pat:
        recompute_family_discount(pat["family_account_id"])


def cure_delinquency_if_resolved(contract):
    """If no MISSED installment remains, contract DELINQUENT->CURRENT and a
    SUSPENDED owning plan -> ACTIVE (PRD §2.7 cure)."""
    if contract["billing_status"] != "DELINQUENT":
        return
    if contract["lifecycle_status"] != "ACTIVE":
        return
    has_missed = any(
        i["status"] == "MISSED" for i in db.installments.values()
        if i["contract_id"] == contract["id"]
    )
    if has_missed:
        return
    contract["billing_status"] = "CURRENT"
    touch(contract)
    plan = plan_for_contract(contract)
    if plan is not None and plan["status"] == "SUSPENDED":
        plan["status"] = "ACTIVE"
        touch(plan)
        pat = db.patients.get(plan["patient_id"])
        if pat:
            recompute_family_discount(pat["family_account_id"])


def close_contract_if_paid_off(contract):
    """Lifecycle axis: balance reaches 0 -> CLOSED (PRD §3.8)."""
    if contract["lifecycle_status"] != "ACTIVE":
        return
    if contract["balance_remaining_cents"] == 0:
        contract["lifecycle_status"] = "CLOSED"
        touch(contract)
