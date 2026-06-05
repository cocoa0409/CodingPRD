"""Composite setup helpers for multi-step test prerequisites (PRD §3).

Uses get_success_data() (lenient validator) so setup failures surface clear
"Setup step failed" errors rather than confusing assertion failures.

All four roles carry opaque user ids; the only identity that matters semantically
is the PA submitter vs decider pair (segregation of duties). The reviewer/director
helpers thread distinct user ids so APPROVE/DENY succeed by default.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from . import factories
from .test_users import (
    TEST_USERS, make_reviewer_headers, make_director_headers,
    REVIEWER_ID, DIRECTOR_ID,
)

ADMIN = TEST_USERS["plan_admin_headers"]
PROVIDER = TEST_USERS["pharmacy_provider_headers"]


# ─── Clock ────────────────────────────────────────────────────────────────
def set_clock(to_iso8601):
    """Advance the server clock (PRD §2.8). Returns the response data."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: single-entity creation ───────────────────────────────────────
def create_plan(**overrides):
    """Create an ACTIVE benefit plan. Returns the plan dict."""
    return get_success_data(api_client.create_plan(factories.create_plan_payload(**overrides), ADMIN))


def create_drug(plan_id, **overrides):
    """Create an ACTIVE formulary drug under plan_id."""
    return get_success_data(
        api_client.create_formulary_drug(
            factories.create_formulary_drug_payload(plan_id, **overrides), ADMIN
        )
    )


def create_protocol(plan_id, **overrides):
    """Create a step-therapy protocol under plan_id."""
    return get_success_data(
        api_client.create_step_therapy_protocol(
            factories.create_step_therapy_protocol_payload(plan_id, **overrides), ADMIN
        )
    )


def create_member(plan_id, **overrides):
    """Enroll an ACTIVE member under plan_id."""
    return get_success_data(
        api_client.create_member(factories.create_member_payload(plan_id, **overrides), ADMIN)
    )


def archive_plan(plan_id):
    """Archive a plan (status -> ARCHIVED). Returns the plan dict."""
    return get_success_data(api_client.archive_plan(plan_id, ADMIN))


def terminate_member(member_id):
    """Terminate a member (status -> TERMINATED). Returns the member dict."""
    return get_success_data(api_client.terminate_member(member_id, ADMIN))


def delist_drug(drug_id):
    """Delist a drug (status -> INACTIVE). Returns the drug dict."""
    return get_success_data(api_client.delist_formulary_drug(drug_id, ADMIN))


def create_copay_card(member_id, drug_id, **overrides):
    """Issue a copay card to member_id for drug_id."""
    return get_success_data(
        api_client.create_copay_card(
            factories.create_copay_card_payload(member_id, drug_id, **overrides), ADMIN
        )
    )


def create_rebate_agreement(plan_id, **overrides):
    """Create a rebate agreement for plan_id."""
    return get_success_data(
        api_client.create_rebate_agreement(
            factories.create_rebate_agreement_payload(plan_id, **overrides), ADMIN
        )
    )


# ─── Tier 2: common base scenarios ────────────────────────────────────────
def setup_plan_drug_member(plan_overrides=None, drug_overrides=None, clock=None):
    """Active plan + one drug + one member. Returns (plan, drug, member).
    Optionally sets the clock first."""
    if clock is not None:
        set_clock(clock)
    plan = create_plan(**(plan_overrides or {}))
    drug = create_drug(plan["id"], **(drug_overrides or {}))
    member = create_member(plan["id"])
    return plan, drug, member


# ─── Tier 3: PA lifecycle shortcuts ───────────────────────────────────────
def submit_pa(member_id, drug_id, submitter_id=REVIEWER_ID, **overrides):
    """Submit a PriorAuthorization as the given reviewer user id.
    Returns the PENDING_REVIEW PA dict."""
    return get_success_data(
        api_client.create_prior_authorization(
            factories.create_prior_authorization_payload(member_id, drug_id, **overrides),
            make_reviewer_headers(submitter_id),
        )
    )


def decide_pa(pa_id, decision, expected_version, decider_id=DIRECTOR_ID):
    """Decide a PA (APPROVE/DENY) as the given director user id. Returns PA dict."""
    return get_success_data(
        api_client.decide_prior_authorization(
            pa_id,
            {"decision": decision, "expected_prior_authorization_version": expected_version},
            make_director_headers(decider_id),
        )
    )


def appeal_pa(pa_id, appellant_id=REVIEWER_ID):
    """Appeal a DENIED PA. Returns the APPEALED PA dict."""
    return get_success_data(
        api_client.appeal_prior_authorization(pa_id, make_reviewer_headers(appellant_id))
    )


def submit_and_approve_pa(member_id, drug_id, submitter_id=REVIEWER_ID,
                          decider_id=DIRECTOR_ID, **overrides):
    """Submit a PA then APPROVE it (distinct submitter/decider). Returns APPROVED PA dict."""
    pa = submit_pa(member_id, drug_id, submitter_id=submitter_id, **overrides)
    return decide_pa(pa["id"], "APPROVE", pa["version"], decider_id=decider_id)


# ─── Tier 4: claim lifecycle shortcuts ────────────────────────────────────
def submit_claim(member_id, drug_id, **overrides):
    """Submit and inline-adjudicate a claim. Returns the claim dict (PAID or REJECTED)."""
    return get_success_data(
        api_client.create_claim(
            factories.create_claim_payload(member_id, drug_id, **overrides), PROVIDER
        )
    )


def reverse_claim(claim_id):
    """Reverse a PAID claim. Returns the REVERSED claim dict."""
    return get_success_data(api_client.reverse_claim(claim_id, PROVIDER))


# ─── Tier 5: accrual / finalization shortcuts ─────────────────────────────
def get_member(member_id):
    return get_success_data(api_client.get_member(member_id, ADMIN))


def get_claim(claim_id):
    return get_success_data(api_client.get_claim(claim_id, ADMIN))


def get_pa(pa_id):
    return get_success_data(api_client.get_prior_authorization(pa_id, ADMIN))


def get_copay_card(card_id):
    return get_success_data(api_client.get_copay_card(card_id, ADMIN))


def get_accrual_for_claim(claim_id):
    """Return the single RebateAccrual dict for a claim via FK reverse list, or None."""
    resp = api_client.list_rebate_accruals(ADMIN, params={"claim_id": claim_id})
    body = resp.json()
    rows = body.get("data", [])
    return rows[0] if rows else None


def finalize_rebates(plan_id, expected_plan_version):
    """Run the rebate-finalization sweep. Returns the response data
    ({finalized_count, finalized_accrual_ids})."""
    return get_success_data(
        api_client.finalize_rebates(
            plan_id, {"expected_benefit_plan_version": expected_plan_version}, ADMIN
        )
    )


def setup_finalized_rebate_claim(clock, clawback_pct=1.0, rebate_per_fill_cents=4000,
                                 days_supply=30, pharmacy_type="RETAIL", tier="TIER_1",
                                 ingredient_cost_cents=10000, mail_multiplier=None):
    """Plan + rebate agreement + rebate drug + member; file one PAID claim that
    accrues PROVISIONAL; then finalize the plan's rebates so the accrual is FINALIZED.

    Returns (plan, drug, member, claim, accrual_after_finalize).
    """
    set_clock(clock)
    plan_kw = {"deductible_cents": 0, "oop_max_cents": 200000}
    if mail_multiplier is not None:
        plan_kw["mail_order_copay_multiplier"] = mail_multiplier
    plan = create_plan(**plan_kw)
    create_rebate_agreement(plan["id"], clawback_pct=clawback_pct)
    drug = create_drug(plan["id"], tier=tier, ingredient_cost_cents=ingredient_cost_cents,
                       rebate_per_fill_cents=rebate_per_fill_cents)
    member = create_member(plan["id"])
    claim = submit_claim(member["id"], drug["id"], days_supply=days_supply,
                         pharmacy_type=pharmacy_type)
    finalize_rebates(plan["id"], plan["version"])
    accrual = get_accrual_for_claim(claim["id"])
    return plan, drug, member, claim, accrual
