"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch via PRD-declared endpoints —
each test runs against a freshly restarted server with an empty database.
Uses get_success_data() (lenient) so setup failures surface as clear
"Setup step failed" errors instead of confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_plan_payload,
    create_drug_payload,
    create_formulary_entry_payload,
    create_pharmacy_payload,
    create_member_payload,
    create_prior_authorization_payload,
    create_claim_payload,
    create_audit_payload,
)
from .test_users import TEST_USERS, make_pharmacist_headers, make_member_headers

ADMIN = TEST_USERS["pbm_admin_headers"]
REVIEWER = TEST_USERS["clinical_reviewer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ─── Tier 1: single-entity creation ─────────────────────────────────────────

def make_plan(**overrides) -> dict:
    """Create a plan (born DRAFT). Returns the plan."""
    return get_success_data(api_client.create_plan(create_plan_payload(**overrides), ADMIN))


def make_drug(**overrides) -> dict:
    return get_success_data(api_client.create_drug(create_drug_payload(**overrides), ADMIN))


def make_formulary_entry(plan_id: str, drug_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_formulary_entry(
            create_formulary_entry_payload(plan_id, drug_id, **overrides), ADMIN
        )
    )


def make_pharmacy(**overrides) -> dict:
    """Create a pharmacy (born ACTIVE, balance 0). Returns the pharmacy."""
    return get_success_data(
        api_client.create_pharmacy(create_pharmacy_payload(**overrides), ADMIN)
    )


def make_member(plan_id: str, **overrides) -> dict:
    """Enroll a member (born ACTIVE, zeroed accumulators). Returns the member."""
    return get_success_data(
        api_client.create_member(create_member_payload(plan_id, **overrides), ADMIN)
    )


def activate_plan(plan_id: str) -> dict:
    return get_success_data(api_client.activate_plan(plan_id, ADMIN))


# ─── Tier 2: the standard adjudication scenario ─────────────────────────────
# ACTIVE plan + formulary entry + ACTIVE pharmacy + eligible member.

def make_adjudication_scenario(
    plan_overrides=None,
    drug_overrides=None,
    entry_overrides=None,
    pharmacy_overrides=None,
    member_overrides=None,
) -> dict:
    """Plan (ACTIVE, one formulary entry) + pharmacy + member.

    Returns dict(plan, drug, entry, pharmacy, member, pharmacist_headers).
    """
    plan = make_plan(**(plan_overrides or {}))
    drug = make_drug(**(drug_overrides or {}))
    entry = make_formulary_entry(plan["id"], drug["id"], **(entry_overrides or {}))
    activate_plan(plan["id"])
    pharmacy = make_pharmacy(**(pharmacy_overrides or {}))
    member = make_member(plan["id"], **(member_overrides or {}))
    return {
        "plan": get_success_data(api_client.get_plan(plan["id"], ADMIN)),
        "drug": drug,
        "entry": entry,
        "pharmacy": pharmacy,
        "member": member,
        "pharmacist_headers": make_pharmacist_headers(pharmacy["id"]),
    }


# ─── Tier 3: claims ─────────────────────────────────────────────────────────

def submit_claim(member_id: str, drug_id: str, pharmacy_id: str, **overrides):
    """Submit a claim as the owning pharmacist. Returns the raw Response."""
    return api_client.create_claim(
        create_claim_payload(member_id, drug_id, **overrides),
        make_pharmacist_headers(pharmacy_id),
    )


def create_paid_claim(member_id: str, drug_id: str, pharmacy_id: str, **overrides) -> dict:
    """Submit a claim expected to adjudicate PAID (HTTP 201). Returns the claim."""
    return get_success_data(submit_claim(member_id, drug_id, pharmacy_id, **overrides))


def get_claim(claim_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_claim(claim_id, headers or ADMIN))


def get_pharmacy(pharmacy_id: str) -> dict:
    return get_success_data(api_client.get_pharmacy(pharmacy_id, ADMIN))


def get_member(member_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_member(member_id, headers or ADMIN))


def list_rejected_claims(member_id: str) -> list:
    data, _meta = _list_claims({"member_id": member_id, "status": "REJECTED"})
    return data


def get_only_rejected_claim(member_id: str) -> dict:
    data = list_rejected_claims(member_id)
    assert len(data) == 1, f"Expected exactly one REJECTED claim, got {len(data)}"
    return data[0]


def _list_claims(params: dict):
    res = api_client.list_claims(ADMIN, params=params)
    body = res.json()
    assert res.status_code == 200, f"Setup list_claims failed: {res.text}"
    return body["data"], body["meta"]


def list_dur_alerts(claim_id: str, headers=None) -> list:
    res = api_client.list_dur_alerts(claim_id, headers or ADMIN)
    body = res.json()
    assert res.status_code == 200, f"Setup list_dur_alerts failed: {res.text}"
    return body["data"]


# ─── Tier 3b: prior authorizations ──────────────────────────────────────────

def make_pending_pa(member_id: str, drug_id: str, **overrides) -> dict:
    """Member requests a PA for self. Returns the PENDING authorization."""
    return get_success_data(
        api_client.create_prior_authorization(
            create_prior_authorization_payload(member_id, drug_id, **overrides),
            make_member_headers(member_id),
        )
    )


def make_approved_pa(
    member_id: str,
    drug_id: str,
    approved_quantity: int,
    expires_at: str,
    requested_quantity: int = None,
    note: str = None,
) -> dict:
    """Create a PA and approve it. Returns the APPROVED authorization."""
    pa_overrides = {}
    if requested_quantity is not None:
        pa_overrides["requested_quantity"] = requested_quantity
    if note is not None:
        pa_overrides["note"] = note
    pa = make_pending_pa(member_id, drug_id, **pa_overrides)
    return get_success_data(
        api_client.approve_prior_authorization(
            pa["id"],
            {"approved_quantity": approved_quantity, "expires_at": expires_at},
            REVIEWER,
        )
    )


def get_pa(pa_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_prior_authorization(pa_id, headers or ADMIN))


# ─── Tier 4: audits ─────────────────────────────────────────────────────────

def make_audit(pharmacy_id: str, **overrides) -> dict:
    """Open an audit (born OPEN, findings empty). Returns the audit."""
    return get_success_data(
        api_client.create_audit(create_audit_payload(pharmacy_id, **overrides), AUDITOR)
    )


def record_findings(audit_id: str, findings: list) -> dict:
    return get_success_data(
        api_client.record_findings(audit_id, {"findings": findings}, AUDITOR)
    )


def get_audit(audit_id: str) -> dict:
    return get_success_data(api_client.get_audit(audit_id, AUDITOR))


# ─── Tier 5: suspension / clawback composite scenarios ──────────────────────

def make_suspended_pharmacy_scenario(
    clawback_cents: int = 16000,
    plan_overrides=None,
    drug_overrides=None,
    entry_overrides=None,
) -> dict:
    """Plan ACTIVE + pharmacy (threshold 5000) + member + one PAID claim
    (unit 1000, qty 10, fee 0, FLAT 0 -> plan_paid 10000), then a CLAIM_LEVEL
    audit closed with a single finding of `clawback_cents`.

    With the default clawback of 16000 the ledger lands at -6000 and the
    pharmacy auto-suspends. Returns the scenario dict augmented with
    claim and audit.
    """
    scenario = make_adjudication_scenario(
        plan_overrides=plan_overrides or {},
        drug_overrides={"unit_cost_cents": 1000, "max_daily_dose_units": 100}
        | (drug_overrides or {}),
        entry_overrides={"copay_flat_cents": 0} | (entry_overrides or {}),
        pharmacy_overrides={"auto_suspend_threshold_cents": 5000},
    )
    claim = create_paid_claim(
        scenario["member"]["id"], scenario["drug"]["id"], scenario["pharmacy"]["id"]
    )
    audit = make_audit(scenario["pharmacy"]["id"], extrapolation_method="CLAIM_LEVEL")
    record_findings(audit["id"], [{"claim_id": claim["id"], "clawback_cents": clawback_cents}])
    get_success_data(api_client.close_audit(audit["id"], AUDITOR))
    scenario["claim"] = claim
    scenario["audit"] = get_audit(audit["id"])
    scenario["pharmacy"] = get_pharmacy(scenario["pharmacy"]["id"])
    return scenario


def make_step_therapy_scenario(
    lookback_days: int = 180,
    member_overrides=None,
) -> dict:
    """ACTIVE plan covering two drugs: a step drug (FLAT 100 entry) and a target drug
    whose entry carries step_therapy_required pointing at the step drug. Retail
    pharmacy + member with eligibility from 2025-06-01.

    Returns dict(plan, step_drug, drug, step_entry, entry, pharmacy, member,
    pharmacist_headers) where `drug` is the step-gated target drug.
    """
    plan = make_plan()
    step_drug = make_drug(name="StepFirst", therapeutic_class="STATIN",
                          unit_cost_cents=500, max_daily_dose_units=100)
    drug = make_drug(name="StepNext", therapeutic_class="ANTILIPEMIC-2",
                     unit_cost_cents=5000, max_daily_dose_units=100)
    step_entry = make_formulary_entry(
        plan["id"], step_drug["id"], tier=1, quantity_limit_per_fill=90,
        max_days_supply=90, copay_type="FLAT", copay_flat_cents=100,
    )
    entry = make_formulary_entry(
        plan["id"], drug["id"], tier=2, quantity_limit_per_fill=90,
        max_days_supply=90, copay_type="FLAT", copay_flat_cents=500,
        step_therapy_required=True, step_drug_id=step_drug["id"],
        step_therapy_lookback_days=lookback_days,
    )
    activate_plan(plan["id"])
    pharmacy = make_pharmacy()
    member = make_member(
        plan["id"],
        **({"eligibility_start_date": "2025-06-01"} | (member_overrides or {})),
    )
    return {
        "plan": plan,
        "step_drug": step_drug,
        "drug": drug,
        "step_entry": step_entry,
        "entry": entry,
        "pharmacy": pharmacy,
        "member": member,
        "pharmacist_headers": make_pharmacist_headers(pharmacy["id"]),
    }


def make_dual_assistance_scenario() -> dict:
    """Two plans identical except the copay-assistance knobs (PRD §3.5):
    P_ACC is ACCUMULATOR with member_min_pay_cents 500; P_MAX is MAXIMIZER with
    card_fill_cap_cents 800. Both cover the same drug (unit 10000) with a FLAT-3000
    tier-2 entry; each plan has one member holding a copay card for the drug with a
    5000-cent balance. One shared retail pharmacy dispenses for both.
    """
    p_acc = make_plan(name="P-ACC", deductible_cents=0, oop_max_cents=1000000,
                      assistance_model="ACCUMULATOR", member_min_pay_cents=500,
                      card_fill_cap_cents=0, dispensing_fee_cents=200)
    p_max = make_plan(name="P-MAX", deductible_cents=0, oop_max_cents=1000000,
                      assistance_model="MAXIMIZER", member_min_pay_cents=0,
                      card_fill_cap_cents=800, dispensing_fee_cents=200)
    drug = make_drug(name="Brandstatin", therapeutic_class="STATIN",
                     unit_cost_cents=10000, max_daily_dose_units=3)
    make_formulary_entry(p_acc["id"], drug["id"], tier=2, quantity_limit_per_fill=90,
                         max_days_supply=90, copay_type="FLAT", copay_flat_cents=3000,
                         rebate_eligible=False)
    make_formulary_entry(p_max["id"], drug["id"], tier=2, quantity_limit_per_fill=90,
                         max_days_supply=90, copay_type="FLAT", copay_flat_cents=3000,
                         rebate_eligible=False)
    activate_plan(p_acc["id"])
    activate_plan(p_max["id"])
    pharmacy = make_pharmacy()
    m_acc = make_member(p_acc["id"], external_ref="M-ACC", full_name="Pat Acc",
                        card_drug_id=drug["id"], card_balance_cents=5000)
    m_max = make_member(p_max["id"], external_ref="M-MAX", full_name="Pat Max",
                        card_drug_id=drug["id"], card_balance_cents=5000)
    return {
        "p_acc": p_acc, "p_max": p_max, "drug": drug, "pharmacy": pharmacy,
        "m_acc": m_acc, "m_max": m_max,
        "pharmacist_headers": make_pharmacist_headers(pharmacy["id"]),
    }


def make_audit_universe_scenario(
    fills_a=("2026-03-01", "2026-04-01", "2026-05-01"),
    fills_b=("2026-03-15", "2026-04-15", "2026-05-15"),
) -> dict:
    """One ACTIVE plan (fee 100, FLAT-0 entry for a unit-1000 drug -> every 10-unit
    claim prices to allowed 10100, patient 0, plan_paid 10100), one member, and two
    retail pharmacies (threshold 1000000, never suspends), each holding three PAID
    claims at non-overlapping fill dates. For clawback-total tests.
    """
    plan = make_plan(dispensing_fee_cents=100)
    drug = make_drug(name="Genericillin", therapeutic_class="ANTIBIOTIC",
                     unit_cost_cents=1000, max_daily_dose_units=100)
    make_formulary_entry(plan["id"], drug["id"], tier=1, quantity_limit_per_fill=90,
                         max_days_supply=90, copay_type="FLAT", copay_flat_cents=0,
                         rebate_eligible=False)
    activate_plan(plan["id"])
    pharmacy_a = make_pharmacy(name="Rx One", auto_suspend_threshold_cents=1000000)
    pharmacy_b = make_pharmacy(name="Rx Two", auto_suspend_threshold_cents=1000000)
    member = make_member(plan["id"], external_ref="M-CLW", full_name="Pat Claw")
    claims_a = [
        create_paid_claim(member["id"], drug["id"], pharmacy_a["id"],
                          fill_date=fill, quantity=10, days_supply=10)
        for fill in fills_a
    ]
    claims_b = [
        create_paid_claim(member["id"], drug["id"], pharmacy_b["id"],
                          fill_date=fill, quantity=10, days_supply=10)
        for fill in fills_b
    ]
    return {
        "plan": plan, "drug": drug, "member": member,
        "pharmacy_a": pharmacy_a, "pharmacy_b": pharmacy_b,
        "claims_a": claims_a, "claims_b": claims_b,
    }
