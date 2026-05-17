"""Composite setup helpers — multi-step preambles tests can reuse.

The PBM workflow is long: catalog a plan -> author a drug -> attach a
formulary entry -> enroll a member -> (optionally) issue a copay card
and a rebate agreement -> (optionally) raise and approve a prior
authorization -> submit a claim -> adjudicate -> pay -> reverse.
Most interesting test claims need the system in a late-pipeline state.

IDENTITY THREADING — PRD §2.1:

Every PBM role is OPAQUE. Per PRD §2.1: "For every one of these four
roles, X-User-ID is an opaque operator identifier that is not tied to
any persisted entity … the server may record the identifier on side-
effect-bearing operations (for example, as part of audit on a
transition) but never compares X-User-ID to any entity's id."
Consequently, shared role-header constants from ``TEST_USERS`` are
canonical for every fixture call; there is no entity-id-threaded
ownership requirement.

Setup helpers use ``get_success_data`` (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CLAWBACK_WINDOW_DAYS,
    PA_EFFECTIVE_WINDOW_SECONDS,
    SECONDS_PER_DAY,
    TEST_DEFAULTS,
)
from .factories import (
    clock_advance_payload,
    create_claim_payload,
    create_copay_card_payload,
    create_drug_payload,
    create_formulary_entry_payload,
    create_member_payload,
    create_plan_payload,
    create_prior_authorization_payload,
    create_rebate_agreement_payload,
    deny_prior_authorization_payload,
    occ_payload,
)
from .test_users import TEST_USERS


# ===========================================================================
# Tier 1: simple primitive entity creation (admin-driven).
# ===========================================================================
def create_plan(
    *,
    deductible_cents: Optional[int] = None,
    oop_max_cents: Optional[int] = None,
    coinsurance_rate: Optional[float] = None,
    mail_order_discount_rate: Optional[float] = None,
    name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /pbm/plans — PBMAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_plan(
        create_plan_payload(
            name=name,
            deductible_cents=deductible_cents,
            oop_max_cents=oop_max_cents,
            coinsurance_rate=coinsurance_rate,
            mail_order_discount_rate=mail_order_discount_rate,
        ),
        headers,
    )
    return get_success_data(resp)


def create_drug(
    *,
    ndc: Optional[str] = None,
    unit_allowed_cents: Optional[int] = None,
    is_specialty: Optional[bool] = None,
    requires_prior_auth: Optional[bool] = None,
    step_therapy_predecessor_ndc: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /pbm/drugs — PBMAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_drug(
        create_drug_payload(
            ndc=ndc,
            unit_allowed_cents=unit_allowed_cents,
            is_specialty=is_specialty,
            requires_prior_auth=requires_prior_auth,
            step_therapy_predecessor_ndc=step_therapy_predecessor_ndc,
        ),
        headers,
    )
    return get_success_data(resp)


def create_formulary_entry(
    *,
    plan_id: str,
    drug_id: str,
    tier: Optional[int] = None,
    copay_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /pbm/formulary-entries — PBMAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_formulary_entry(
        create_formulary_entry_payload(
            plan_id=plan_id, drug_id=drug_id,
            tier=tier, copay_cents=copay_cents,
        ),
        headers,
    )
    return get_success_data(resp)


def create_member(
    *,
    plan_id: str,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /pbm/members — PBMAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_member(
        create_member_payload(
            plan_id=plan_id,
            full_name=full_name,
            date_of_birth=date_of_birth,
        ),
        headers,
    )
    return get_success_data(resp)


def create_copay_card(
    *,
    member_id: str,
    drug_id: str,
    max_benefit_cents: Optional[int] = None,
    per_claim_cap_cents: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /pbm/copay-cards — PBMAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_copay_card(
        create_copay_card_payload(
            member_id=member_id, drug_id=drug_id,
            max_benefit_cents=max_benefit_cents,
            per_claim_cap_cents=per_claim_cap_cents,
        ),
        headers,
    )
    return get_success_data(resp)


def create_rebate_agreement(
    *,
    drug_id: str,
    rebate_rate: Optional[float] = None,
    clawback_window_days: Optional[int] = None,
    manufacturer_name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /pbm/rebate-agreements — PBMAdmin only."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.create_rebate_agreement(
        create_rebate_agreement_payload(
            drug_id=drug_id, rebate_rate=rebate_rate,
            clawback_window_days=clawback_window_days,
            manufacturer_name=manufacturer_name,
        ),
        headers,
    )
    return get_success_data(resp)


def advance_clock(seconds: int,
                  headers: Optional[Dict[str, str]] = None
                  ) -> Dict[str, Any]:
    """POST /_clock/advance — PBMAdmin only. PRD §2.11."""
    headers = headers or TEST_USERS["admin_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(seconds=seconds), headers,
    )
    return get_success_data(resp)


def re_get_member(member_id: str) -> Dict[str, Any]:
    """Refresh a Member row via GET /pbm/members/{id}."""
    resp = api_client.get_member(
        member_id, TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


def re_get_claim(claim_id: str) -> Dict[str, Any]:
    """Refresh a Claim row via GET /pbm/claims/{id}."""
    resp = api_client.get_claim(
        claim_id, TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


def re_get_copay_card(card_id: str) -> Dict[str, Any]:
    """Refresh a CopayCard row via GET /pbm/copay-cards/{id}."""
    resp = api_client.get_copay_card(
        card_id, TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


def re_get_prior_authorization(pa_id: str) -> Dict[str, Any]:
    """Refresh a PA via GET /pbm/prior-authorizations/{id}."""
    resp = api_client.get_prior_authorization(
        pa_id, TEST_USERS["admin_headers"],
    )
    return get_success_data(resp)


def list_ledger_for_claim(claim_id: str) -> List[Dict[str, Any]]:
    """GET /pbm/ledger-entries?claim_id=... — PBMAdmin only."""
    resp = api_client.list_ledger_entries(
        TEST_USERS["admin_headers"],
        params={"claim_id": claim_id, "limit": 100},
    )
    body = resp.json()
    return list(body.get("data", []))


# ===========================================================================
# Tier 2: reference-data bundles (plan + drug + formulary + member).
# ===========================================================================
def setup_reference_data(
    *,
    plan_kwargs: Optional[Dict[str, Any]] = None,
    drug_kwargs: Optional[Dict[str, Any]] = None,
    formulary_kwargs: Optional[Dict[str, Any]] = None,
    member_kwargs: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create one Plan + Drug + FormularyEntry + Member.

    Returns (plan, drug, formulary_entry, member). The member is
    enrolled in the plan and the drug is on the plan's formulary.
    Used by the majority of claim-focused tests.
    """
    plan = create_plan(**(plan_kwargs or {}))
    drug = create_drug(**(drug_kwargs or {}))
    formulary_entry = create_formulary_entry(
        plan_id=plan["id"], drug_id=drug["id"],
        **(formulary_kwargs or {}),
    )
    member = create_member(
        plan_id=plan["id"], **(member_kwargs or {}),
    )
    return plan, drug, formulary_entry, member


# ===========================================================================
# Tier 3: PriorAuthorization lifecycle shortcuts.
# ===========================================================================
def create_pa_in_draft(
    *,
    member_id: str,
    drug_id: str,
    clinical_rationale: Optional[str] = None,
) -> Dict[str, Any]:
    """POST /pbm/prior-authorizations — Prescriber. PA starts in
    DRAFT per PRD §3.3."""
    resp = api_client.create_prior_authorization(
        create_prior_authorization_payload(
            member_id=member_id, drug_id=drug_id,
            clinical_rationale=clinical_rationale,
        ),
        TEST_USERS["prescriber_headers"],
    )
    return get_success_data(resp)


def submit_pa(pa: Dict[str, Any]) -> Dict[str, Any]:
    """POST /pbm/prior-authorizations/{id}/submit — Prescriber."""
    resp = api_client.submit_prior_authorization(
        pa["id"],
        occ_payload(version=pa["version"]),
        TEST_USERS["prescriber_headers"],
    )
    return get_success_data(resp)


def request_info_pa(pa: Dict[str, Any]) -> Dict[str, Any]:
    """POST /pbm/prior-authorizations/{id}/request-info —
    ClinicalReviewer."""
    resp = api_client.request_info_prior_authorization(
        pa["id"],
        occ_payload(version=pa["version"]),
        TEST_USERS["clinical_reviewer_headers"],
    )
    return get_success_data(resp)


def resubmit_pa(pa: Dict[str, Any],
                clinical_rationale: Optional[str] = None) -> Dict[str, Any]:
    """POST /pbm/prior-authorizations/{id}/resubmit — Prescriber.
    PRD §3.3 takes refreshed clinical_rationale and version."""
    body: Dict[str, Any] = {
        "clinical_rationale": (
            clinical_rationale if clinical_rationale is not None
            else "Additional clinical evidence supporting the request."
        ),
        "version": pa["version"],
    }
    resp = api_client.resubmit_prior_authorization(
        pa["id"], body, TEST_USERS["prescriber_headers"],
    )
    return get_success_data(resp)


def approve_pa(pa: Dict[str, Any]) -> Dict[str, Any]:
    """POST /pbm/prior-authorizations/{id}/approve —
    ClinicalReviewer."""
    resp = api_client.approve_prior_authorization(
        pa["id"],
        occ_payload(version=pa["version"]),
        TEST_USERS["clinical_reviewer_headers"],
    )
    return get_success_data(resp)


def deny_pa(pa: Dict[str, Any],
            denial_reason: Optional[str] = None) -> Dict[str, Any]:
    """POST /pbm/prior-authorizations/{id}/deny — ClinicalReviewer.
    PRD §3.3 takes denial_reason and version."""
    resp = api_client.deny_prior_authorization(
        pa["id"],
        deny_prior_authorization_payload(
            denial_reason=denial_reason, version=pa["version"],
        ),
        TEST_USERS["clinical_reviewer_headers"],
    )
    return get_success_data(resp)


def revoke_pa(pa: Dict[str, Any]) -> Dict[str, Any]:
    """POST /pbm/prior-authorizations/{id}/revoke —
    ClinicalReviewer."""
    resp = api_client.revoke_prior_authorization(
        pa["id"],
        occ_payload(version=pa["version"]),
        TEST_USERS["clinical_reviewer_headers"],
    )
    return get_success_data(resp)


def setup_submitted_pa(*, member_id: str,
                       drug_id: str) -> Dict[str, Any]:
    """DRAFT -> SUBMITTED. Returns the SUBMITTED PA."""
    pa = create_pa_in_draft(member_id=member_id, drug_id=drug_id)
    return submit_pa(pa)


def setup_approved_pa(*, member_id: str,
                      drug_id: str) -> Dict[str, Any]:
    """DRAFT -> SUBMITTED -> APPROVED. PRD §3.3: approve writes
    effective_start = clock_now() and effective_end = +180 days."""
    pa = setup_submitted_pa(member_id=member_id, drug_id=drug_id)
    return approve_pa(pa)


def setup_denied_pa(*, member_id: str,
                    drug_id: str,
                    denial_reason: Optional[str] = None
                    ) -> Dict[str, Any]:
    """DRAFT -> SUBMITTED -> DENIED."""
    pa = setup_submitted_pa(member_id=member_id, drug_id=drug_id)
    return deny_pa(pa, denial_reason=denial_reason)


def setup_revoked_pa(*, member_id: str,
                     drug_id: str) -> Dict[str, Any]:
    """DRAFT -> SUBMITTED -> APPROVED -> REVOKED."""
    pa = setup_approved_pa(member_id=member_id, drug_id=drug_id)
    return revoke_pa(pa)


def setup_pa_at_revision_count(*, member_id: str, drug_id: str,
                               revision_count: int
                               ) -> Dict[str, Any]:
    """Loop SUBMITTED <-> INFO_REQUESTED exactly ``revision_count``
    times so that the returned PA is in SUBMITTED with the exact
    revision_count requested. PRD §3.3: each resubmit hop increments
    revision_count by one.

    Legal values are 0, 1, 2 (resubmit from INFO_REQUESTED is gated
    by revision_count < 3 — see PRD §3.3 and §2.8 rung 13).
    """
    assert 0 <= revision_count <= 3, (
        "revision_count must be in 0..3"
    )
    pa = setup_submitted_pa(member_id=member_id, drug_id=drug_id)
    for _ in range(revision_count):
        pa = request_info_pa(pa)
        pa = resubmit_pa(pa)
    return pa


# ===========================================================================
# Tier 4: Claim lifecycle shortcuts.
# ===========================================================================
def submit_claim(
    *,
    member_id: str,
    drug_id: str,
    channel: str = "RETAIL_30",
    days_supply: Optional[int] = None,
    quantity: Optional[int] = None,
    prior_auth_id: Optional[str] = None,
    copay_card_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /pbm/claims — Prescriber or ClaimsAdjudicator."""
    headers = headers or TEST_USERS["claims_adjudicator_headers"]
    resp = api_client.create_claim(
        create_claim_payload(
            member_id=member_id, drug_id=drug_id,
            channel=channel, days_supply=days_supply,
            quantity=quantity,
            prior_auth_id=prior_auth_id,
            copay_card_id=copay_card_id,
        ),
        headers,
    )
    return get_success_data(resp)


def adjudicate_claim(claim: Dict[str, Any]) -> Dict[str, Any]:
    """POST /pbm/claims/{id}/adjudicate — ClaimsAdjudicator."""
    resp = api_client.adjudicate_claim(
        claim["id"],
        occ_payload(version=claim["version"]),
        TEST_USERS["claims_adjudicator_headers"],
    )
    return get_success_data(resp)


def pay_claim(claim: Dict[str, Any]) -> Dict[str, Any]:
    """POST /pbm/claims/{id}/pay — ClaimsAdjudicator."""
    resp = api_client.pay_claim(
        claim["id"],
        occ_payload(version=claim["version"]),
        TEST_USERS["claims_adjudicator_headers"],
    )
    return get_success_data(resp)


def reverse_claim(claim: Dict[str, Any]) -> Dict[str, Any]:
    """POST /pbm/claims/{id}/reverse — ClaimsAdjudicator."""
    resp = api_client.reverse_claim(
        claim["id"],
        occ_payload(version=claim["version"]),
        TEST_USERS["claims_adjudicator_headers"],
    )
    return get_success_data(resp)


def setup_adjudicated_claim(
    *,
    member_id: str,
    drug_id: str,
    channel: str = "RETAIL_30",
    days_supply: Optional[int] = None,
    quantity: Optional[int] = None,
    prior_auth_id: Optional[str] = None,
    copay_card_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Submit and adjudicate a claim. Returns the ADJUDICATED claim."""
    claim = submit_claim(
        member_id=member_id, drug_id=drug_id, channel=channel,
        days_supply=days_supply, quantity=quantity,
        prior_auth_id=prior_auth_id, copay_card_id=copay_card_id,
    )
    return adjudicate_claim(claim)


def setup_paid_claim(
    *,
    member_id: str,
    drug_id: str,
    channel: str = "RETAIL_30",
    days_supply: Optional[int] = None,
    quantity: Optional[int] = None,
    prior_auth_id: Optional[str] = None,
    copay_card_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Submit -> adjudicate -> pay. Returns the PAID claim."""
    claim = setup_adjudicated_claim(
        member_id=member_id, drug_id=drug_id, channel=channel,
        days_supply=days_supply, quantity=quantity,
        prior_auth_id=prior_auth_id, copay_card_id=copay_card_id,
    )
    return pay_claim(claim)


def setup_reversed_claim(
    *,
    member_id: str,
    drug_id: str,
    channel: str = "RETAIL_30",
    days_supply: Optional[int] = None,
    quantity: Optional[int] = None,
    prior_auth_id: Optional[str] = None,
    copay_card_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Submit -> adjudicate -> pay -> reverse. Returns the REVERSED
    claim."""
    claim = setup_paid_claim(
        member_id=member_id, drug_id=drug_id, channel=channel,
        days_supply=days_supply, quantity=quantity,
        prior_auth_id=prior_auth_id, copay_card_id=copay_card_id,
    )
    return reverse_claim(claim)


# ===========================================================================
# Tier 5: Threshold-targeting / accumulation fixtures.
# ===========================================================================
def setup_member_at_ytd(
    *,
    plan_kwargs: Optional[Dict[str, Any]] = None,
    target_ytd_deductible: int = 0,
    target_ytd_oop: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Bring a fresh Member's YTD deductible counter up to exactly
    ``target_ytd_deductible`` cents.

    Uses a sentinel "warm-up" Drug (separate from the test's drug of
    interest) so that YTD-state setup does NOT trigger refill-too-soon
    interactions with the test's primary supply window. Returns
    (plan, member, warm_up_drug) — the caller still creates its own
    test drug + formulary entry.

    target_ytd_oop is provided as a sanity contract: if a caller asks
    for an OOP value that disagrees with the deductible-only warm-up,
    we deliberately don't try to satisfy it; tests should rely on the
    refreshed Member returned by ``re_get_member`` to read the actual
    YTD counters after the warm-up adjudication completes.
    """
    plan = create_plan(**(plan_kwargs or {}))
    # Warm-up drug has tier-1 flat copay of 0, so the entire allowed
    # amount goes to the deductible (PRD §3.5). To deposit exactly
    # target_ytd_deductible cents the warm-up unit_allowed_cents
    # equals target_ytd_deductible cents and quantity == 1.
    warm_drug = create_drug(unit_allowed_cents=max(target_ytd_deductible, 1))
    create_formulary_entry(
        plan_id=plan["id"], drug_id=warm_drug["id"],
        tier=1, copay_cents=0,
    )
    member = create_member(plan_id=plan["id"])
    if target_ytd_deductible > 0:
        setup_paid_claim(
            member_id=member["id"], drug_id=warm_drug["id"],
            channel="RETAIL_30", days_supply=1, quantity=1,
        )
    # OOP delta is asserted-only when explicitly requested.
    if target_ytd_oop is not None:
        fresh = re_get_member(member["id"])
        # We do not raise here — caller is expected to assert.
        # Return value just communicates the actual state.
        assert fresh["ytd_oop_paid_cents"] >= 0
    return plan, member, warm_drug


def setup_step_therapy_predecessor_paid(
    *,
    plan: Dict[str, Any],
    member: Dict[str, Any],
    predecessor_ndc: str,
) -> Dict[str, Any]:
    """Create a predecessor Drug with the given NDC, add it to the
    plan's formulary, and dispense one PAID claim for the member.
    Returns the PAID claim. PRD §3.5: step-therapy gating is
    satisfied when the member has at least one PAID claim for the
    predecessor drug within the current benefit year."""
    predecessor = create_drug(ndc=predecessor_ndc, unit_allowed_cents=1000)
    create_formulary_entry(
        plan_id=plan["id"], drug_id=predecessor["id"],
        tier=1, copay_cents=0,
    )
    return setup_paid_claim(
        member_id=member["id"], drug_id=predecessor["id"],
        channel="RETAIL_30", days_supply=1, quantity=1,
    )


# ===========================================================================
# Difficulty-design composite fixtures
# (SCAFFOLD_DIFFICULTY_DESIGN.yaml drives shape & numbers).
# ===========================================================================

# -----------------------------------------------------------------------
# DD-1a: estimated_vs_adjudicated_member_cost_on_claim
# -----------------------------------------------------------------------
def setup_dd_estimated_vs_adjudicated() -> Dict[str, Any]:
    """Bring the system to the exact state of difficulty-design
    instance ``estimated_vs_adjudicated_member_cost_on_claim``.

    PRD §3.4 vs §3.5 distinction: same Claim, same Drug, same Plan;
    forward-looking estimate uses Member YTD at submission time;
    chronological adjudicated cost uses Member YTD at adjudication
    time. We adjudicate claim_B in between submission and adjudication
    of claim_A to advance Member YTD.
    """
    plan = create_plan(
        deductible_cents=50_000, oop_max_cents=200_000,
        coinsurance_rate=0.20,
        mail_order_discount_rate=0.90,
    )
    drug_a = create_drug(
        unit_allowed_cents=10_000,
        is_specialty=False, requires_prior_auth=False,
    )
    drug_b = create_drug(
        unit_allowed_cents=4_000,
        is_specialty=False, requires_prior_auth=False,
    )
    create_formulary_entry(plan_id=plan["id"], drug_id=drug_a["id"],
                           tier=3, copay_cents=0)
    create_formulary_entry(plan_id=plan["id"], drug_id=drug_b["id"],
                           tier=3, copay_cents=0)
    member = create_member(plan_id=plan["id"])

    # claim_A: estimate captured at submission; YTD=0 here.
    claim_a = submit_claim(
        member_id=member["id"], drug_id=drug_a["id"],
        channel="RETAIL_30", days_supply=30, quantity=30,
    )
    # claim_B: adjudicate this first so Member YTD advances.
    claim_b = submit_claim(
        member_id=member["id"], drug_id=drug_b["id"],
        channel="RETAIL_30", days_supply=30, quantity=10,
    )
    claim_b_adj = adjudicate_claim(claim_b)
    # Brief clock advance — supply windows are different drugs so
    # refill-too-soon doesn't apply, but advancing makes the
    # chronology unambiguous.
    advance_clock(60)
    # Now adjudicate claim_A. Its chronological cost reflects the
    # YTD increment from claim_B.
    claim_a_adj = adjudicate_claim(claim_a)

    return {
        "plan": plan, "member": member,
        "drug_a": drug_a, "drug_b": drug_b,
        "claim_a_submitted": claim_a,
        "claim_a_adjudicated": claim_a_adj,
        "claim_b_adjudicated": claim_b_adj,
    }


# -----------------------------------------------------------------------
# DD-1b / DD-9a: rebate accrual + clawback round-trip.
# -----------------------------------------------------------------------
def setup_dd_rebate_accrual_clawback() -> Dict[str, Any]:
    """Bring the system to the state where claim has been
    REBATE_ACCRUED and then REBATE_CLAWBACK posted (full clawback
    within window). Reproduces difficulty-design instances
    ``provisional_rebate_vs_final_after_clawback`` and
    ``rebate_ledger_zero_sum_after_clawback_within_window``.

    PRD §3.6: rebate_accrual = round_half_up(plan_paid * rate)
    PRD §3.7: REBATE_CLAWBACK negates the accrual when reverse
    happens within clawback_window_days.
    """
    plan = create_plan(
        deductible_cents=0, oop_max_cents=200_000,
        coinsurance_rate=0.20, mail_order_discount_rate=0.90,
    )
    drug = create_drug(unit_allowed_cents=5_000,
                       is_specialty=False, requires_prior_auth=False)
    create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                           tier=1, copay_cents=1000)
    member = create_member(plan_id=plan["id"])
    agreement = create_rebate_agreement(
        drug_id=drug["id"], rebate_rate=0.15,
        clawback_window_days=DEFAULT_CLAWBACK_WINDOW_DAYS,
    )
    claim = submit_claim(
        member_id=member["id"], drug_id=drug["id"],
        channel="MAIL_ORDER_90", days_supply=90, quantity=10,
    )
    claim_adj = adjudicate_claim(claim)
    claim_paid = pay_claim(claim_adj)
    claim_reversed = reverse_claim(claim_paid)
    return {
        "plan": plan, "drug": drug, "member": member,
        "agreement": agreement,
        "claim_paid": claim_paid,
        "claim_reversed": claim_reversed,
    }


# -----------------------------------------------------------------------
# DD-2a: tiered_copay_plus_oop_cap_plus_card_three_input_formula
# -----------------------------------------------------------------------
def setup_dd_three_input_formula_with_card() -> Dict[str, Any]:
    """Reproduce difficulty-design instance
    ``tiered_copay_plus_oop_cap_plus_card_three_input_formula``.

    PRD §3.5 inputs and arithmetic:
      Plan(deductible=5000, oop_max=10000, coinsurance=0.20)
      Drug(unit_allowed=2000)
      FormularyEntry(tier=3, copay=0)
      Member(ytd_ded=5000, ytd_oop=8000)
      CopayCard(max_benefit=500, per_claim_cap=500)
      Claim quantity=10, channel=RETAIL_30.
    Expected: allowed=20000, post_ded=20000, coins=4000, oop_rem=2000,
    member_pre_card=2000, card=500, adjudicated_member_cost=1500,
    copay_card_paid=500.
    """
    plan = create_plan(
        deductible_cents=5_000, oop_max_cents=10_000,
        coinsurance_rate=0.20, mail_order_discount_rate=0.90,
    )
    drug = create_drug(unit_allowed_cents=2_000,
                       is_specialty=False, requires_prior_auth=False)
    create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                           tier=3, copay_cents=0)
    member = create_member(plan_id=plan["id"])
    # Warm-up Member to (ytd_ded=5000, ytd_oop=8000) using two
    # adjudications on sentinel drugs separate from the test's drug
    # of interest. PRD §3.5 arithmetic:
    #
    # Sentinel A: tier-1 flat copay=0, allowed_per_unit=5000, q=1.
    #   allowed=5000. ded_remaining=5000. ded_portion=5000.
    #   post_ded=0. tier 1 -> member_share=min(0,0)=0.
    #   member_pre_card=5000. Member.ytd_ded+=5000 -> 5000.
    #   Member.ytd_oop+=5000 -> 5000.
    sentinel_a = create_drug(unit_allowed_cents=5_000,
                             is_specialty=False,
                             requires_prior_auth=False)
    create_formulary_entry(plan_id=plan["id"], drug_id=sentinel_a["id"],
                           tier=1, copay_cents=0)
    setup_paid_claim(
        member_id=member["id"], drug_id=sentinel_a["id"],
        channel="RETAIL_30", days_supply=1, quantity=1,
    )

    # Sentinel B: tier-3, allowed_per_unit=1500, q=10 -> allowed=15000.
    #   ded_remaining=0 (already spent). ded_portion=0.
    #   post_ded=15000. tier 3 -> member_share=15000*0.20=3000.
    #   member_pre_card=3000. oop_remaining=10000-5000=5000, so
    #   capped value remains 3000. Member.ytd_ded unchanged.
    #   Member.ytd_oop+=3000 -> 8000.
    sentinel_b = create_drug(unit_allowed_cents=1_500,
                             is_specialty=False,
                             requires_prior_auth=False)
    create_formulary_entry(plan_id=plan["id"], drug_id=sentinel_b["id"],
                           tier=3, copay_cents=0)
    setup_paid_claim(
        member_id=member["id"], drug_id=sentinel_b["id"],
        channel="RETAIL_30", days_supply=1, quantity=10,
    )

    # Advance the clock so the candidate claim's supply window does
    # not overlap any sentinel claim. The sentinels above each had
    # days_supply=1; advancing 2 days is more than enough to avoid
    # any half-open overlap with a fresh candidate.
    advance_clock(2 * SECONDS_PER_DAY)

    card = create_copay_card(
        member_id=member["id"], drug_id=drug["id"],
        max_benefit_cents=500, per_claim_cap_cents=500,
    )
    claim = submit_claim(
        member_id=member["id"], drug_id=drug["id"],
        channel="RETAIL_30", days_supply=10, quantity=10,
        copay_card_id=card["id"],
    )
    claim_adj = adjudicate_claim(claim)
    return {
        "plan": plan, "drug": drug, "member": member, "card": card,
        "claim_adjudicated": claim_adj,
    }


# -----------------------------------------------------------------------
# DD-2b: side_effect_ordering_deductible_then_oop_then_card
# -----------------------------------------------------------------------
def setup_dd_side_effect_ordering() -> Dict[str, Any]:
    """Reproduce difficulty-design instance
    ``side_effect_ordering_deductible_then_oop_then_card``.

    PRD §3.5 pinned side-effect order: deductible -> oop -> card. The
    OOP counter is incremented by member_pre_card (before card
    offset), NOT by the post-card adjudicated_member_cost_cents.

    Setup: plan(deductible=0, oop_max=100000, coinsurance=0.20),
    drug(unit_allowed=1000), tier=3 copay=0, card(max=1000, pcc=1000).
    Claim quantity=30 → allowed=30000, ded_portion=0,
    member_pre_card=6000, card=1000, adjudicated_member_cost=5000,
    copay_card_paid=1000, Member.ytd_oop=6000 (NOT 5000),
    CopayCard.used=1000.
    """
    plan = create_plan(
        deductible_cents=0, oop_max_cents=100_000,
        coinsurance_rate=0.20, mail_order_discount_rate=0.90,
    )
    drug = create_drug(unit_allowed_cents=1_000,
                       is_specialty=False, requires_prior_auth=False)
    create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                           tier=3, copay_cents=0)
    member = create_member(plan_id=plan["id"])
    card = create_copay_card(
        member_id=member["id"], drug_id=drug["id"],
        max_benefit_cents=1_000, per_claim_cap_cents=1_000,
    )
    claim = submit_claim(
        member_id=member["id"], drug_id=drug["id"],
        channel="RETAIL_30", days_supply=30, quantity=30,
        copay_card_id=card["id"],
    )
    claim_adj = adjudicate_claim(claim)
    return {
        "plan": plan, "drug": drug, "member": member, "card": card,
        "claim_adjudicated": claim_adj,
    }


# -----------------------------------------------------------------------
# DD-3a: PA cyclic SUBMITTED <-> INFO_REQUESTED.
# -----------------------------------------------------------------------
def setup_dd_pa_cyclic() -> Dict[str, Any]:
    """Build a PA at SUBMITTED, revision_count=2, ready for the
    third request-info / resubmit cycle that must be rejected.
    Difficulty-design instance ``prior_auth_cyclic_submitted_info_requested``.
    """
    plan, drug, _, member = setup_reference_data(
        drug_kwargs={"requires_prior_auth": True},
    )
    pa = setup_pa_at_revision_count(
        member_id=member["id"], drug_id=drug["id"],
        revision_count=2,
    )
    return {"plan": plan, "drug": drug, "member": member, "pa": pa}


# -----------------------------------------------------------------------
# DD-3b: claim parallel status axes (status vs payment_status).
# -----------------------------------------------------------------------
def setup_dd_claim_parallel_axes() -> Dict[str, Any]:
    """Build a Claim in ADJUDICATED with payment_status UNPAID, ready
    to be paid then reversed. Difficulty-design instance
    ``claim_parallel_status_axes``."""
    plan, drug, _, member = setup_reference_data()
    # Use a rebate agreement so the pay->reverse round-trip exercises
    # the ledger in addition to the parallel-axis test, but the test
    # itself only inspects the two enum fields per the difficulty
    # recipe. Adjudicate-then-stop here.
    claim = submit_claim(
        member_id=member["id"], drug_id=drug["id"],
        channel="RETAIL_30", days_supply=30, quantity=30,
    )
    claim_adj = adjudicate_claim(claim)
    return {
        "plan": plan, "drug": drug, "member": member,
        "claim_adjudicated": claim_adj,
    }


# -----------------------------------------------------------------------
# DD-4a: REVERSE causes downstream YTD-driven recompute (depth-3).
# -----------------------------------------------------------------------
def setup_dd_reverse_depth_three_cascade() -> Dict[str, Any]:
    """Reproduce difficulty-design instance
    ``reverse_claim_depth_three_cascade_through_member_ytd``.

    State at return:
      - claim_A is PAID. Member.ytd_deductible_paid_cents == 50000.
      - claim_B is SUBMITTED for D_B (different drug, no overlap
        with claim_A's supply window because D_A != D_B).
    Test then: REVERSE claim_A, then ADJUDICATE claim_B; claim_B is
    adjudicated against the post-reverse YTD (== 0), so its
    deductible_portion equals its full allowed (10000) and
    Member.ytd_ded becomes 10000 again.
    """
    plan = create_plan(
        deductible_cents=50_000, oop_max_cents=200_000,
        coinsurance_rate=0.20, mail_order_discount_rate=0.90,
    )
    drug_a = create_drug(unit_allowed_cents=10_000,
                         is_specialty=False, requires_prior_auth=False)
    drug_b = create_drug(unit_allowed_cents=10_000,
                         is_specialty=False, requires_prior_auth=False)
    create_formulary_entry(plan_id=plan["id"], drug_id=drug_a["id"],
                           tier=3, copay_cents=0)
    create_formulary_entry(plan_id=plan["id"], drug_id=drug_b["id"],
                           tier=3, copay_cents=0)
    member = create_member(plan_id=plan["id"])

    # claim_A: allowed = 10000*30 = 300000. deductible_portion =
    # min(300000, 50000) = 50000. Member.ytd_ded -> 50000.
    claim_a_paid = setup_paid_claim(
        member_id=member["id"], drug_id=drug_a["id"],
        channel="RETAIL_30", days_supply=30, quantity=30,
    )

    # claim_B: SUBMITTED, ready for the test to drive
    # reverse(A) -> adjudicate(B).
    claim_b = submit_claim(
        member_id=member["id"], drug_id=drug_b["id"],
        channel="RETAIL_30", days_supply=30, quantity=1,
    )
    return {
        "plan": plan, "drug_a": drug_a, "drug_b": drug_b,
        "member": member,
        "claim_a_paid": claim_a_paid,
        "claim_b_submitted": claim_b,
    }


# -----------------------------------------------------------------------
# DD-4b: REVOKE PA -> SUBMITTED Claim referencing that PA is REJECTED
#                with ERR_PA_REVOKED.
# -----------------------------------------------------------------------
def setup_dd_revoke_pa_depth_two() -> Dict[str, Any]:
    """Reproduce difficulty-design instance
    ``revoke_pa_depth_two_cascade_into_pending_claim``.

    State at return:
      - PA is APPROVED, member == member, drug == drug.
      - Claim is SUBMITTED, prior_auth_id=PA.id.
    Test then revokes PA then adjudicates Claim.
    """
    plan = create_plan()
    drug = create_drug(requires_prior_auth=True)
    create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                           tier=3, copay_cents=0)
    member = create_member(plan_id=plan["id"])
    pa = setup_approved_pa(member_id=member["id"], drug_id=drug["id"])
    claim = submit_claim(
        member_id=member["id"], drug_id=drug["id"],
        channel="RETAIL_30", days_supply=30, quantity=1,
        prior_auth_id=pa["id"],
    )
    return {
        "plan": plan, "drug": drug, "member": member,
        "pa_approved": pa, "claim_submitted": claim,
    }


# -----------------------------------------------------------------------
# DD-5a: state_beats_business_safety (ERR_INVALID_STATE beats
# ERR_SPECIALTY_CHANNEL_REQUIRED).
# -----------------------------------------------------------------------
def setup_dd_state_beats_specialty() -> Dict[str, Any]:
    """Reproduce difficulty-design instance
    ``state_beats_business_safety_pa_revoked_vs_specialty``.

    State at return:
      - Drug is is_specialty=true.
      - Claim is in ADJUDICATED (already past SUBMITTED).
      - Claim.channel = RETAIL_30 (wrong for a specialty drug).
    Test re-adjudicates: should see ERR_INVALID_STATE (priority 4),
    NOT ERR_SPECIALTY_CHANNEL_REQUIRED (priority 6).
    """
    # Build a base specialty-channel claim, adjudicate it. Then
    # re-adjudicate. But the difficulty design wants the channel
    # actually wrong at the moment of the second adjudicate. The
    # PRD ladder evaluates STATE (rung 4) before SPECIALTY (rung 6),
    # so we set up a successfully-adjudicated specialty claim (with
    # channel=SPECIALTY for the legal initial adjudication) and
    # re-adjudicate, expecting ERR_INVALID_STATE on the second hop.
    plan = create_plan()
    drug = create_drug(is_specialty=True, requires_prior_auth=False)
    create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                           tier=3, copay_cents=0)
    member = create_member(plan_id=plan["id"])
    claim_adj = setup_adjudicated_claim(
        member_id=member["id"], drug_id=drug["id"],
        channel="SPECIALTY", days_supply=30, quantity=1,
    )
    return {
        "plan": plan, "drug": drug, "member": member,
        "claim_adjudicated": claim_adj,
    }


# -----------------------------------------------------------------------
# DD-5b: business_safety beats business_referential (PA_REQUIRED beats
# COPAY_CARD_MISMATCH).
# -----------------------------------------------------------------------
def setup_dd_pa_required_beats_card_mismatch() -> Dict[str, Any]:
    """Reproduce difficulty-design instance
    ``business_safety_beats_business_referential_pa_required_vs_card_mismatch``.

    State at return:
      - Drug requires_prior_auth=true.
      - Member has NO APPROVED PA for this drug.
      - CopayCard is bound to a DIFFERENT drug.
      - Claim is SUBMITTED, drug_id=Drug.id, copay_card_id=Card.id,
        prior_auth_id=null.
    PRD §2.8 ladder: PA_REQUIRED (rung 7) fires before
    COPAY_CARD_MISMATCH (rung 12).
    """
    plan = create_plan()
    drug = create_drug(requires_prior_auth=True)
    other_drug = create_drug(requires_prior_auth=False)
    create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                           tier=3, copay_cents=0)
    create_formulary_entry(plan_id=plan["id"], drug_id=other_drug["id"],
                           tier=3, copay_cents=0)
    member = create_member(plan_id=plan["id"])
    # Card bound to other_drug, not drug.
    card = create_copay_card(
        member_id=member["id"], drug_id=other_drug["id"],
        max_benefit_cents=1_000, per_claim_cap_cents=1_000,
    )
    claim = submit_claim(
        member_id=member["id"], drug_id=drug["id"],
        channel="RETAIL_30", days_supply=30, quantity=1,
        copay_card_id=card["id"],
    )
    return {
        "plan": plan, "drug": drug, "other_drug": other_drug,
        "member": member, "card": card,
        "claim_submitted": claim,
    }


# -----------------------------------------------------------------------
# DD-6a: PA effective-window exact-end boundary (closed-left,
# open-right).
# -----------------------------------------------------------------------
def setup_dd_pa_window_boundary() -> Dict[str, Any]:
    """Reproduce difficulty-design instance
    ``pa_effective_window_exact_end_boundary``.

    State at return:
      - PA APPROVED, effective_start=now-of-approval,
        effective_end=approval+180d.
      - C1, C2 both in SUBMITTED referencing the PA.
    Test then advances clock to effective_end - 1s, adjudicates C1
    (accepted), advances 1s more, adjudicates C2 (rejected with
    ERR_PA_EXPIRED).
    """
    plan = create_plan()
    drug = create_drug(requires_prior_auth=True)
    create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                           tier=3, copay_cents=0)
    member = create_member(plan_id=plan["id"])
    pa = setup_approved_pa(member_id=member["id"], drug_id=drug["id"])
    c1 = submit_claim(
        member_id=member["id"], drug_id=drug["id"],
        channel="RETAIL_30", days_supply=30, quantity=1,
        prior_auth_id=pa["id"],
    )
    c2 = submit_claim(
        member_id=member["id"], drug_id=drug["id"],
        channel="RETAIL_30", days_supply=30, quantity=1,
        prior_auth_id=pa["id"],
    )
    return {
        "plan": plan, "drug": drug, "member": member,
        "pa_approved": pa,
        "claim_c1": c1, "claim_c2": c2,
    }


# -----------------------------------------------------------------------
# DD-6b: empty step-therapy predecessor history.
# -----------------------------------------------------------------------
def setup_dd_step_therapy_empty_history() -> Dict[str, Any]:
    """Reproduce difficulty-design instance
    ``empty_step_therapy_predecessor_history_on_claim_endpoint``.

    State at return:
      - D_pred drug exists (NDC pinned to '00000000001').
      - D_step drug has step_therapy_predecessor_ndc='00000000001'.
      - Member has NO claims for D_pred.
      - Claim C is SUBMITTED for D_step.
    """
    plan = create_plan()
    # Predecessor exists (it must be findable by NDC for the lookup),
    # but no member claim has been PAID for it. NDC is randomised so
    # repeated fixture invocations (e.g., from sibling test files
    # exercising the same difficulty rule) do not collide on the
    # PRD §3.1 "unique among ACTIVE drugs" rule.
    from .factories import random_ndc
    pred_ndc = random_ndc()
    pred = create_drug(ndc=pred_ndc,
                       is_specialty=False, requires_prior_auth=False)
    drug = create_drug(
        step_therapy_predecessor_ndc=pred_ndc,
        requires_prior_auth=False,
    )
    create_formulary_entry(plan_id=plan["id"], drug_id=pred["id"],
                           tier=1, copay_cents=0)
    create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                           tier=1, copay_cents=0)
    member = create_member(plan_id=plan["id"])
    claim = submit_claim(
        member_id=member["id"], drug_id=drug["id"],
        channel="RETAIL_30", days_supply=30, quantity=1,
    )
    return {
        "plan": plan, "drug_pred": pred, "drug_step": drug,
        "member": member, "claim_submitted": claim,
    }


# -----------------------------------------------------------------------
# DD-7a: Claim adjudicate blocked by Member.enrollment_status.
# -----------------------------------------------------------------------
def setup_dd_member_blocks_adjudicate() -> Dict[str, Any]:
    """Reproduce difficulty-design instance
    ``claim_adjudicate_blocked_by_member_status``.

    State at return:
      - Member ACTIVE.
      - Claim C SUBMITTED.
    Test then suspends the member and adjudicates.
    """
    plan, drug, _, member = setup_reference_data()
    claim = submit_claim(
        member_id=member["id"], drug_id=drug["id"],
        channel="RETAIL_30", days_supply=30, quantity=1,
    )
    return {
        "plan": plan, "drug": drug, "member": member,
        "claim_submitted": claim,
    }


# -----------------------------------------------------------------------
# DD-7b: PA-state cascade into adjudicate (PA -> DENIED ->
#       ERR_PA_DENIED).
# -----------------------------------------------------------------------
def setup_dd_pa_denied_blocks_adjudicate() -> Dict[str, Any]:
    """Reproduce difficulty-design instance
    ``claim_adjudicate_blocked_by_prior_auth_state``.

    State at return:
      - PA SUBMITTED.
      - Claim SUBMITTED referencing PA, drug requires_prior_auth.
    Test then denies the PA and adjudicates.
    """
    plan = create_plan()
    drug = create_drug(requires_prior_auth=True)
    create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                           tier=3, copay_cents=0)
    member = create_member(plan_id=plan["id"])
    pa = setup_submitted_pa(member_id=member["id"], drug_id=drug["id"])
    claim = submit_claim(
        member_id=member["id"], drug_id=drug["id"],
        channel="RETAIL_30", days_supply=30, quantity=1,
        prior_auth_id=pa["id"],
    )
    return {
        "plan": plan, "drug": drug, "member": member,
        "pa_submitted": pa, "claim_submitted": claim,
    }


# -----------------------------------------------------------------------
# DD-8a: Refill-too-soon half-open day-granularity.
# -----------------------------------------------------------------------
def setup_dd_refill_too_soon_half_open() -> Dict[str, Any]:
    """Reproduce difficulty-design instance
    ``refill_too_soon_half_open_day_granularity_on_member_drug_pair``.

    State at return:
      - C1 ADJUDICATED at clock T=0 with days_supply=30.
      - C2 SUBMITTED for the same (member, drug), days_supply=30,
        to be tested at T=29d (overlap).
      - C3 SUBMITTED for the same (member, drug), days_supply=30,
        to be tested at T=30d (adjacency, no overlap).
    """
    plan, drug, _, member = setup_reference_data()
    c1 = submit_claim(
        member_id=member["id"], drug_id=drug["id"],
        channel="RETAIL_30", days_supply=30, quantity=1,
    )
    c1_adj = adjudicate_claim(c1)
    c2 = submit_claim(
        member_id=member["id"], drug_id=drug["id"],
        channel="RETAIL_30", days_supply=30, quantity=1,
    )
    c3 = submit_claim(
        member_id=member["id"], drug_id=drug["id"],
        channel="RETAIL_30", days_supply=30, quantity=1,
    )
    return {
        "plan": plan, "drug": drug, "member": member,
        "claim_c1_adjudicated": c1_adj,
        "claim_c2_submitted": c2,
        "claim_c3_submitted": c3,
    }


# -----------------------------------------------------------------------
# DD-8b: PA effective-window closed-open at second granularity.
# -----------------------------------------------------------------------
def setup_dd_pa_window_closed_open() -> Dict[str, Any]:
    """Reproduce difficulty-design instance
    ``pa_effective_window_closed_open_second_granularity_on_pa_resource``.

    Same skeleton as DD-6a — two claims in SUBMITTED behind a freshly
    APPROVED PA. The test drives clock to effective_start (accept)
    and effective_end (reject).
    """
    return setup_dd_pa_window_boundary()


# -----------------------------------------------------------------------
# DD-9a: rebate ledger zero-sum within window. (Reuses DD-1b setup.)
# DD-9b: member YTD zero-drift round-trip.
# -----------------------------------------------------------------------
def setup_dd_member_ytd_round_trip() -> Dict[str, Any]:
    """Reproduce difficulty-design instance
    ``member_ytd_zero_drift_after_adjudicate_reverse_round_trip``.

    State at return:
      - Plan(deductible=50000, oop_max=200000, coinsurance=0.20).
      - Drug(unit_allowed=10000), Member fresh (ytd_*=0).
      - Claim C is SUBMITTED with channel=RETAIL_30, days_supply=30,
        quantity=30 (allowed=300000).
    Test then adjudicates -> pays -> reverses, observing Member YTD
    increments then drops back to 0.
    """
    plan = create_plan(
        deductible_cents=50_000, oop_max_cents=200_000,
        coinsurance_rate=0.20, mail_order_discount_rate=0.90,
    )
    drug = create_drug(unit_allowed_cents=10_000,
                       is_specialty=False, requires_prior_auth=False)
    create_formulary_entry(plan_id=plan["id"], drug_id=drug["id"],
                           tier=3, copay_cents=0)
    member = create_member(plan_id=plan["id"])
    claim = submit_claim(
        member_id=member["id"], drug_id=drug["id"],
        channel="RETAIL_30", days_supply=30, quantity=30,
    )
    return {
        "plan": plan, "drug": drug, "member": member,
        "claim_submitted": claim,
    }


__all__ = [
    "create_plan",
    "create_drug",
    "create_formulary_entry",
    "create_member",
    "create_copay_card",
    "create_rebate_agreement",
    "advance_clock",
    "re_get_member",
    "re_get_claim",
    "re_get_copay_card",
    "re_get_prior_authorization",
    "list_ledger_for_claim",
    "setup_reference_data",
    "create_pa_in_draft",
    "submit_pa",
    "request_info_pa",
    "resubmit_pa",
    "approve_pa",
    "deny_pa",
    "revoke_pa",
    "setup_submitted_pa",
    "setup_approved_pa",
    "setup_denied_pa",
    "setup_revoked_pa",
    "setup_pa_at_revision_count",
    "submit_claim",
    "adjudicate_claim",
    "pay_claim",
    "reverse_claim",
    "setup_adjudicated_claim",
    "setup_paid_claim",
    "setup_reversed_claim",
    "setup_member_at_ytd",
    "setup_step_therapy_predecessor_paid",
    # Difficulty-design composites.
    "setup_dd_estimated_vs_adjudicated",
    "setup_dd_rebate_accrual_clawback",
    "setup_dd_three_input_formula_with_card",
    "setup_dd_side_effect_ordering",
    "setup_dd_pa_cyclic",
    "setup_dd_claim_parallel_axes",
    "setup_dd_reverse_depth_three_cascade",
    "setup_dd_revoke_pa_depth_two",
    "setup_dd_state_beats_specialty",
    "setup_dd_pa_required_beats_card_mismatch",
    "setup_dd_pa_window_boundary",
    "setup_dd_step_therapy_empty_history",
    "setup_dd_member_blocks_adjudicate",
    "setup_dd_pa_denied_blocks_adjudicate",
    "setup_dd_refill_too_soon_half_open",
    "setup_dd_pa_window_closed_open",
    "setup_dd_member_ytd_round_trip",
]
