"""
Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures
produce clear "Setup failed" errors instead of confusing assertion failures.

Every helper builds its preconditions from scratch via PRD-declared
endpoints — each test runs against a freshly restarted server with an empty
database.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CONFIG_DEFAULTS
from .factories import (
    create_adjustment_payload,
    create_claim_line_payload,
    create_claim_payload,
    create_coverage_payload,
    create_lead_payload,
    create_member_payload,
    create_msp_questionnaire_payload,
    create_primacy_determination_payload,
    create_provider_payload,
    create_recovery_request_payload,
    create_reimbursement_payload,
    create_rule_config_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
ELIG = TEST_USERS["eligibility_analyst_headers"]
COB = TEST_USERS["cob_analyst_headers"]
EXAMINER = TEST_USERS["claims_examiner_headers"]
RECOVERY = TEST_USERS["recovery_specialist_headers"]
AUDITOR = TEST_USERS["cob_auditor_headers"]

OUR_PLAN_EFFECTIVE = "2026-01-01"
GROUP_EFFECTIVE = "2025-01-01"  # earlier than OUR_PLAN -> group sorts primary


# ─── Tier 1: single-resource creation ───────────────────────────────────────

def create_config(expected_active_config_version=None, **overrides):
    """Create the ACTIVE rule config. On a fresh server the first creation
    omits expected_active_config_version (PRD §2.7); pass it when an ACTIVE
    config already exists."""
    res = api_client.create_rule_config(
        create_rule_config_payload(
            expected_active_config_version=expected_active_config_version, **overrides
        ),
        ADMIN,
    )
    return get_success_data(res)


def create_provider(**overrides):
    res = api_client.create_provider(create_provider_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_member(**overrides):
    res = api_client.create_member(create_member_payload(**overrides), ELIG)
    return get_success_data(res)


def set_clock(to_iso8601: str):
    res = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(res)


# ─── Tier 2: coverage registration / verification ───────────────────────────

def create_verified_coverage(member_id, verify=True, **cov_overrides):
    """Register a coverage for the member and (by default) verify it."""
    res = api_client.create_coverage(member_id, create_coverage_payload(**cov_overrides), COB)
    coverage = get_success_data(res)
    if verify:
        verified = api_client.verify_coverage(member_id, coverage["id"], COB)
        return get_success_data(verified)
    return coverage


def create_lead(member_id, **overrides):
    res = api_client.create_lead(member_id, create_lead_payload(**overrides), COB)
    return get_success_data(res)


def current_member_version(member_id) -> int:
    """Re-read the member; the caller threads the fresh version into the
    expected_member_version guard when drafting a determination (PRD §2.7)."""
    member = get_success_data(api_client.get_member(member_id, COB))
    return member["version"]


# ─── Tier 3: primacy determination lifecycle ────────────────────────────────

def draft_determination(member_id, as_of_service_date, msp_questionnaire_id=None):
    """Draft a primacy determination, threading the member's current version
    into the expected_member_version guard."""
    version = current_member_version(member_id)
    res = api_client.create_primacy_determination(
        member_id,
        create_primacy_determination_payload(
            as_of_service_date, version, msp_questionnaire_id=msp_questionnaire_id
        ),
        COB,
    )
    return get_success_data(res)


def finalize_determination(member_id, determination_id):
    res = api_client.finalize_primacy_determination(member_id, determination_id, COB)
    return get_success_data(res)


def draft_and_finalize_determination(member_id, as_of_service_date, msp_questionnaire_id=None):
    draft = draft_determination(member_id, as_of_service_date, msp_questionnaire_id)
    return finalize_determination(member_id, draft["id"])


# ─── Tier 4: composite member/coverage/determination scenarios ───────────────

def setup_member_with_our_plan(member_overrides=None):
    """Fresh config + member + one VERIFIED OUR_PLAN coverage (eff 2026-01-01).

    Returns (member, own_coverage).
    """
    create_config()
    member = create_member(**(member_overrides or {}))
    own = create_verified_coverage(
        member["id"],
        payer_id="OWN",
        plan_name="Our Plan",
        coverage_kind="OUR_PLAN",
        subscriber_relationship="SELF",
        policy_holder_dob=member["date_of_birth"],
        effective_from=OUR_PLAN_EFFECTIVE,
        verification_source="ELIGIBILITY_MATCH",
    )
    return member, own


def setup_member_with_our_plan_and_group(member_overrides=None, group_overrides=None):
    """Member + VERIFIED OUR_PLAN (eff 2026-01-01) + VERIFIED GROUP_HEALTH
    (eff 2025-01-01, earlier, so it orders primary over ours).

    Returns (member, own_coverage, group_coverage).
    """
    member, own = setup_member_with_our_plan(member_overrides)
    group_defaults = dict(
        payer_id="GRP",
        plan_name="Other Group",
        coverage_kind="GROUP_HEALTH",
        subscriber_relationship="SPOUSE",
        policy_holder_dob="1978-01-01",
        policy_holder_gender="MALE",
        effective_from=GROUP_EFFECTIVE,
        verification_source="DATA_MATCH_CMS",
    )
    group_defaults.update(group_overrides or {})
    group = create_verified_coverage(member["id"], **group_defaults)
    return member, own, group


def setup_secondary_position_claim(
    line_specs=None, as_of="2026-02-10", service_date="2026-02-10",
):
    """Full pipeline to an ADJUDICATED claim where this plan is SECONDARY:
    member with OUR_PLAN + GROUP_HEALTH verified, determination finalized
    (group coverage effective earlier -> primary), claim + lines, adjudicated.

    line_specs: list of dicts for create_claim_line_payload.
    Returns dict(member, own, group, provider, determination, claim, lines).
    """
    member, own, group = setup_member_with_our_plan_and_group()
    provider = create_provider()
    determination = draft_and_finalize_determination(member["id"], as_of)
    claim = get_success_data(api_client.create_claim(
        create_claim_payload(member["id"], provider["id"], service_date=service_date),
        EXAMINER,
    ))
    if line_specs is None:
        line_specs = [dict(billed_cents=50000, allowed_cents=40000, primary_paid_cents=25000)]
    lines = []
    for i, spec in enumerate(line_specs, start=1):
        line = get_success_data(api_client.add_claim_line(
            claim["id"], create_claim_line_payload(line_number=i, **spec), EXAMINER,
        ))
        lines.append(line)
    adjudicated = get_success_data(api_client.adjudicate_claim(claim["id"], EXAMINER))
    return {
        "member": member, "own": own, "group": group, "provider": provider,
        "determination": determination, "claim": adjudicated, "lines": lines,
    }


def setup_paid_secondary_claim(**kwargs):
    """Secondary-position claim advanced through PAID."""
    ctx = setup_secondary_position_claim(**kwargs)
    ctx["claim"] = get_success_data(api_client.pay_claim(ctx["claim"]["id"], EXAMINER))
    return ctx


# ─── Tier 5: rework / recovery pipelines ────────────────────────────────────

def rework_paid_claim(claim_id, cause="NEW_COVERAGE_DISCOVERED",
                      triggering_determination_id=None):
    """Apply an adjustment to a PAID claim, then reopen -> readjudicate ->
    repay. Returns dict(adjustment, claim) with the claim in REPAID."""
    adjustment = get_success_data(api_client.create_adjustment(
        claim_id,
        create_adjustment_payload(
            cause=cause, triggering_determination_id=triggering_determination_id
        ),
        EXAMINER,
    ))
    applied = get_success_data(api_client.apply_adjustment(claim_id, adjustment["id"], EXAMINER))
    get_success_data(api_client.reopen_claim(claim_id, RECOVERY))
    get_success_data(api_client.readjudicate_claim(claim_id, EXAMINER))
    repaid = get_success_data(api_client.repay_claim(claim_id, EXAMINER))
    return {"adjustment": applied, "claim": repaid}


def setup_repaid_claim_with_overpayment(
    billed=50000, allowed=40000, primary_paid=10000,
    as_of="2026-02-10", service_date="2026-02-10",
):
    """Pipeline producing a genuine overpayment and a REPAID claim:

    1. Member with ONLY the VERIFIED OUR_PLAN coverage; determination D1
       finalized for the service date (single coverage -> this plan primary).
    2. Claim adjudicated as primary (paid = min(allowed, billed)), then paid.
    3. A GROUP_HEALTH coverage effective EARLIER than ours is registered and
       verified; a new determination D2 for the same service date is
       finalized -> we become secondary, D1 is superseded, and a draft
       adjustment (cause PRIMACY_DETERMINATION_SUPERSEDED) is auto-created.
    4. The adjustment is applied: post = allowed - primary_paid, so
       overpayment = primary_paid.
    5. Claim reopened -> readjudicated -> repaid.

    Returns dict(member, provider, d1, d2, adjustment, claim, overpayment).
    """
    member, own = setup_member_with_our_plan()
    provider = create_provider()
    d1 = draft_and_finalize_determination(member["id"], as_of)
    claim = get_success_data(api_client.create_claim(
        create_claim_payload(member["id"], provider["id"],
                             service_date=service_date, total_billed_cents=billed),
        EXAMINER,
    ))
    get_success_data(api_client.add_claim_line(
        claim["id"],
        create_claim_line_payload(
            line_number=1, billed_cents=billed, allowed_cents=allowed,
            primary_paid_cents=primary_paid,
        ),
        EXAMINER,
    ))
    get_success_data(api_client.adjudicate_claim(claim["id"], EXAMINER))
    get_success_data(api_client.pay_claim(claim["id"], EXAMINER))

    # Retroactively discovered earlier group coverage flips primacy.
    group = create_verified_coverage(
        member["id"],
        payer_id="GRP", plan_name="Other Group", coverage_kind="GROUP_HEALTH",
        subscriber_relationship="SPOUSE", policy_holder_dob="1978-01-01",
        policy_holder_gender="MALE", effective_from=GROUP_EFFECTIVE,
        verification_source="DATA_MATCH_CMS",
    )
    d2 = draft_and_finalize_determination(member["id"], as_of)

    # The supersession auto-created a draft adjustment for the claim.
    adjustments, _meta = _list_adjustment_data(claim["id"])
    auto = [a for a in adjustments if a.get("cause") == "PRIMACY_DETERMINATION_SUPERSEDED"]
    assert auto, "Setup failed: supersession did not auto-create an adjustment"
    adjustment = auto[0]
    applied = get_success_data(api_client.apply_adjustment(claim["id"], adjustment["id"], EXAMINER))
    overpayment = applied["overpayment_cents"]
    assert overpayment > 0, "Setup failed: expected a positive overpayment"

    get_success_data(api_client.reopen_claim(claim["id"], RECOVERY))
    get_success_data(api_client.readjudicate_claim(claim["id"], EXAMINER))
    repaid = get_success_data(api_client.repay_claim(claim["id"], EXAMINER))
    return {
        "member": member, "provider": provider, "d1": d1, "d2": d2, "group": group,
        "adjustment": applied, "claim": repaid, "overpayment": overpayment,
    }


def _list_adjustment_data(claim_id):
    from prd_bench_local_runner.testing import validate_paginated
    res = api_client.list_adjustments(claim_id, EXAMINER)
    return validate_paginated(res)


def setup_issued_recovery_request(**kwargs):
    """REPAID claim with a positive overpayment + recovery request drafted for
    exactly the overpayment amount and issued.

    Returns the setup_repaid_claim_with_overpayment context plus "recovery".
    """
    ctx = setup_repaid_claim_with_overpayment(**kwargs)
    recovery = get_success_data(api_client.create_recovery_request(
        ctx["claim"]["id"],
        create_recovery_request_payload(ctx["provider"]["id"], ctx["overpayment"]),
        RECOVERY,
    ))
    recovery = get_success_data(
        api_client.issue_recovery_request(ctx["claim"]["id"], recovery["id"], RECOVERY)
    )
    ctx["recovery"] = recovery
    return ctx


# ─── Tier 6: MSP helpers ────────────────────────────────────────────────────

def submit_msp_questionnaire(member_id, **overrides):
    res = api_client.create_msp_questionnaire(
        member_id, create_msp_questionnaire_payload(**overrides), COB
    )
    return get_success_data(res)


def submit_and_adjudicate_msp(member_id, **overrides):
    questionnaire = submit_msp_questionnaire(member_id, **overrides)
    res = api_client.adjudicate_msp_questionnaire(member_id, questionnaire["id"], COB)
    return get_success_data(res)


def setup_medicare_claim_pipeline(as_of="2026-02-10", service_date="2026-02-10"):
    """Member with OUR_PLAN + MEDICARE_PART_A verified, an ADJUDICATED MSP
    questionnaire (MEDICARE_PRIMARY), a finalized determination referencing
    it, and a claim adjudicated (as secondary) and paid.

    Returns dict(member, medicare_coverage, questionnaire, determination, claim).
    """
    member, own = setup_member_with_our_plan(dict(
        date_of_birth="1945-01-01", employment_status="RETIRED",
        employer_size=10, medicare_entitlement_reason="AGE",
    ))
    provider = create_provider()
    medicare = create_verified_coverage(
        member["id"],
        payer_id="MCR", plan_name="Medicare A", coverage_kind="MEDICARE_PART_A",
        subscriber_relationship="SELF", policy_holder_dob="1945-01-01",
        effective_from="2010-01-01", verification_source="DATA_MATCH_CMS",
    )
    questionnaire = submit_and_adjudicate_msp(
        member["id"], has_employer_group_health=False, employer_size=0,
        disability_flag=False, esrd_flag=False,
    )
    determination = draft_and_finalize_determination(
        member["id"], as_of, msp_questionnaire_id=questionnaire["id"]
    )
    claim = get_success_data(api_client.create_claim(
        create_claim_payload(member["id"], provider["id"], service_date=service_date),
        EXAMINER,
    ))
    get_success_data(api_client.add_claim_line(
        claim["id"],
        create_claim_line_payload(
            line_number=1, billed_cents=50000, allowed_cents=40000,
            primary_paid_cents=30000,
        ),
        EXAMINER,
    ))
    get_success_data(api_client.adjudicate_claim(claim["id"], EXAMINER))
    paid = get_success_data(api_client.pay_claim(claim["id"], EXAMINER))
    return {
        "member": member, "own": own, "medicare": medicare,
        "questionnaire": questionnaire, "determination": determination,
        "provider": provider, "claim": paid,
    }
