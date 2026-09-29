"""Multi-hop cascades: appeal sustain, cycle expiry, provider suspension, grant close."""
import pytest

from test_helpers import (
    COACH_USER_ID,
    TEST_USERS,
    accept_grant,
    adjudicate_expenditure,
    approve_claim,
    build_rating_spine,
    create_allocation,
    file_appeal,
    make_provider_headers,
    make_reviewer_headers,
    offer_grant,
    pay_claim,
    run_expiry_run,
    schedule_session,
    set_clock,
    start_appeal_review,
    submit_claim,
    submit_expenditure,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER = make_reviewer_headers()
COACH_ID = COACH_USER_ID

#: Five domains, weights 0.30/0.25/0.20/0.15/0.10, LEARNING_ENVIRONMENT observation-linked.
DOMAINS = [
    {
        "domain_code": "LEARNING_ENVIRONMENT",
        "block_level": 1,
        "max_points": 30,
        "block_min_points": 12,
        "weight": 0.30,
        "observation_linked": True,
        "min_composite_for_block": 4.00,
    },
    {
        "domain_code": "STAFF_QUALIFICATIONS",
        "block_level": 1,
        "max_points": 25,
        "block_min_points": 10,
        "weight": 0.25,
        "observation_linked": False,
    },
    {
        "domain_code": "FAMILY_PARTNERSHIP",
        "block_level": 2,
        "max_points": 20,
        "block_min_points": 8,
        "weight": 0.20,
        "observation_linked": False,
    },
    {
        "domain_code": "ADMINISTRATION",
        "block_level": 2,
        "max_points": 15,
        "block_min_points": 6,
        "weight": 0.15,
        "observation_linked": False,
    },
    {
        "domain_code": "CHILD_ASSESSMENT",
        "block_level": 3,
        "max_points": 10,
        "block_min_points": 4,
        "weight": 0.10,
        "observation_linked": False,
    },
]

#: Verified points that carry the two-observer spine to weighted_total 80.00 / tier 4.
POINTS = {
    "LEARNING_ENVIRONMENT": 26,
    "STAFF_QUALIFICATIONS": 22,
    "FAMILY_PARTNERSHIP": 16,
    "ADMINISTRATION": 12,
    "CHILD_ASSESSMENT": 8,
}
#: Verified points that carry the single-observer spine to weighted_total 50.00 / tier 2.
POINTS_SINGLE_OBSERVER = {
    "LEARNING_ENVIRONMENT": 15,
    "STAFF_QUALIFICATIONS": 12,
    "FAMILY_PARTNERSHIP": 10,
    "ADMINISTRATION": 7,
    "CHILD_ASSESSMENT": 5,
}

#: Lead subscales summing to 35, so the composite is 5.83.
LEAD_SCORES = {
    "SPACE_FURNISHINGS": 6.0,
    "PERSONAL_CARE": 6.0,
    "LANGUAGE_REASONING": 6.0,
    "ACTIVITIES": 6.0,
    "INTERACTION": 6.0,
    "PROGRAM_STRUCTURE": 5.0,
}
#: Secondary subscales agreeing within 1.0 on five of six, so reliability is 83.33.
SECONDARY_SCORES = {
    "SPACE_FURNISHINGS": 6.0,
    "PERSONAL_CARE": 6.0,
    "LANGUAGE_REASONING": 6.0,
    "ACTIVITIES": 5.0,
    "INTERACTION": 7.0,
    "PROGRAM_STRUCTURE": 3.0,
}

#: 1.80 qualifying FTE over a 2.00 denominator, so credential_compliance_pct is 90.00.
CREDENTIALS_90 = [
    {"role_type": "DIRECTOR", "credential_level": 5, "fte": 1.00, "expires_on": "2027-12-31"},
    {"role_type": "LEAD_TEACHER", "credential_level": 3, "fte": 0.80, "expires_on": "2027-12-31"},
]
#: 1.20 qualifying FTE over a 2.00 denominator, so credential_compliance_pct is 60.00.
CREDENTIALS_60 = [
    {"role_type": "DIRECTOR", "credential_level": 4, "fte": 1.00, "expires_on": "2029-12-31"},
    {"role_type": "ASSISTANT", "credential_level": 1, "fte": 0.20, "expires_on": "2029-12-31"},
]


def _tier_four_spine(stop_at, legal_name, license_number, licensed_capacity):
    """Two-observer RURAL spine awarded FINAL at tier 4 on 2026-08-10, active 2026-09-05."""
    return build_rating_spine(
        stop_at=stop_at,
        domains=DOMAINS,
        provider_overrides={
            "legal_name": legal_name,
            "license_number": license_number,
            "county_code": "MARION",
            "region_code": "RURAL",
            "licensed_capacity": licensed_capacity,
            "active_staff_fte": 2.00,
            "weekly_onsite_cap_hours": 12.0,
        },
        credentials=CREDENTIALS_90,
        claimed=POINTS,
        verified=POINTS,
        lead_per_subscale=LEAD_SCORES,
        secondary_per_subscale=SECONDARY_SCORES,
        with_secondary=True,
        window_start="2026-08-05T09:00:00Z",
        window_end="2026-08-05T13:00:00Z",
        enrol_clock="2026-08-03T00:00:00Z",
        cycle_clock="2026-08-04T00:00:00Z",
        award_clock="2026-08-10T00:00:00Z",
        activation_clock="2026-09-05T00:00:00Z",
    )


# --- appeal sustain: tier -> claim -> provider adjustment --------------------


def _gladstone_paid_claim_under_review(api):
    """Provider G published at tier 4, one PAID 2026-09 claim, appeal in UNDER_REVIEW."""
    ctx = _tier_four_spine("PUBLISHED", "Gladstone Family Care", "LIC-2207-G", 65)
    claim = submit_claim(ctx["provider"]["id"], "2026-09", infant=100, toddler=200, preschool=300)
    claim = approve_claim(claim["id"], variant="INTERIM")
    claim = pay_claim(claim["id"])
    set_clock("2026-09-08T00:00:00Z")
    appeal = file_appeal(
        ctx["provider"]["id"],
        ctx["cycle"]["id"],
        "SCORING_ERROR",
        "PROGRAM_STRUCTURE subscale mis-keyed; composite understated.",
    )
    start_appeal_review(appeal["id"])
    return ctx, claim, appeal


def _sustain(api, appeal_id):
    return validate_success(
        api.appeal_review_action(
            appeal_id,
            {"action": "SUSTAIN", "adjusted_tier": 5, "note": "Tier adjusted to 5."},
            REVIEWER,
        )
    )


def test_sustained_appeal_rewrites_the_tier_and_unpublishes_the_cycle(api):
    """PRD §3.6: "The appeal moves `UNDER_REVIEW → SUSTAINED` and stamps `decided_on`, and
    a three-hop cascade follows. In the first hop the cycle returns `UNDER_APPEAL →
    AWARDED` with its `awarded_tier` replaced by the ordered `adjusted_tier`,
    `appeal_adjusted` set to true, and the validity arithmetic rerun while keeping the
    original `effective_date` — which means `validity_months`, `expires_on`, and
    `rerating_window_opens_on` may change while the effective date does not."
    PRD §3.6: "Finally, the cycle's publication state becomes `UNPUBLISHED`, so a
    corrected snapshot has to be republished rather than the stale one silently
    persisting."

    Design: Difficulty/transitive_cascade/appeal_sustain_tier_to_claim_to_provider_adjustment_chain
    """
    ctx, _claim, appeal = _gladstone_paid_claim_under_review(api)
    assert ctx["cycle"]["awarded_tier"] == 4, (
        f"the spine must award tier 4, got {ctx['cycle']['awarded_tier']}"
    )
    assert ctx["cycle"]["weighted_total"] == pytest.approx(80.00, abs=0.005)
    assert ctx["cycle"]["highest_block_cleared"] == 3

    sustained = _sustain(api, appeal["id"])
    assert sustained["status"] == "SUSTAINED", (
        f"appeal must reach SUSTAINED, got {sustained['status']}"
    )

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "AWARDED", (
        f"hop 1 must return the cycle to AWARDED, got {cycle['status']}"
    )
    assert cycle["awarded_tier"] == 5, (
        f"hop 1 must replace awarded_tier with the ordered 5, got {cycle['awarded_tier']}"
    )
    assert cycle["appeal_adjusted"] is True
    assert cycle["effective_date"] == "2026-09-01T00:00:00.000Z", (
        "the validity rerun keeps the original effective_date, got "
        f"{cycle['effective_date']}"
    )
    assert cycle["validity_months"] == 36
    assert cycle["expires_on"] == "2029-08-31T23:59:59.999Z"
    assert cycle["rerating_window_opens_on"] == "2029-06-02T00:00:00.000Z"
    assert cycle["publication_status"] == "UNPUBLISHED", (
        f"the sustained appeal must unpublish the cycle, got {cycle['publication_status']}"
    )


def test_tier_change_flags_the_already_paid_claim_without_rewriting_its_money(api):
    """PRD §3.6: "In the second hop, caused by the tier change, every subsidy claim of
    that provider in `PAID` whose service month starts inside the cycle's validity window
    moves `PAID → RECONCILE_REQUIRED`."
    PRD §3.7: "A reconciled payment rewrites `reimbursement_cents` under the reconciled
    variant and returns the provider's `reimbursement_adjustment_cents` to its
    pre-cascade value, so the pair of flagging-then-repaying leaves that conserved
    balance unchanged."

    Design: Difficulty/transitive_cascade/appeal_sustain_tier_to_claim_to_provider_adjustment_chain
    """
    ctx, claim, appeal = _gladstone_paid_claim_under_review(api)
    assert claim["base_amount_cents"] == 2170000, (
        f"base_amount_cents must be 2170000, got {claim['base_amount_cents']}"
    )
    assert claim["tier_multiplier_applied"] == pytest.approx(1.3000, abs=0.00005)
    assert claim["reimbursement_cents"] == 3046680, (
        f"INTERIM reimbursement_cents must be 3046680, got {claim['reimbursement_cents']}"
    )
    assert claim["status"] == "PAID"

    _sustain(api, appeal["id"])

    flagged = validate_success(api.get_subsidy_claim(claim["id"], ADMIN))
    assert flagged["status"] == "RECONCILE_REQUIRED", (
        "hop 2 must move the PAID claim to RECONCILE_REQUIRED, got "
        f"{flagged['status']}"
    )
    assert flagged["reimbursement_cents"] == 3046680, (
        "hop 2 only moves state; the reconciled rewrite happens on the later pay, got "
        f"{flagged['reimbursement_cents']}"
    )
    assert flagged["tier_multiplier_applied"] == pytest.approx(1.3000, abs=0.00005)
    assert flagged["variant_applied"] == "INTERIM"


def test_flagged_claim_pushes_the_provider_adjustment_up_by_the_reconciled_difference(api):
    """PRD §3.6: "In the third hop, caused by each of those claims being flagged, the
    provider's `reimbursement_adjustment_cents` changes by the difference between what
    the claim would be worth under the reconciled variant and what was actually paid."
    PRD §3.7: "The provider's `reimbursement_adjustment_cents` is a signed cumulative
    figure: a positive balance is a retroactive correction owed to the provider, and a
    negative balance is an amount the state expects to recover. Appeal cascades push it
    up when a tier increase means past months were underpaid, and grant recovery pushes
    it down, as the next section describes."
    PRD §3.7: "A tier maps to a multiplier: tier 1 pays at 1.00, tier 2 at 1.05, tier 3
    at 1.15, tier 4 at 1.30, and tier 5 at 1.50."

    Design: Difficulty/transitive_cascade/appeal_sustain_tier_to_claim_to_provider_adjustment_chain
    """
    ctx, _claim, appeal = _gladstone_paid_claim_under_review(api)
    before = validate_success(api.get_provider(ctx["provider"]["id"], ADMIN))
    assert before["reimbursement_adjustment_cents"] == 0, (
        "the chain must start from a zero adjustment so all three hops are attributable "
        f"to the single sustain call, got {before['reimbursement_adjustment_cents']}"
    )
    assert before["credential_compliance_pct"] == pytest.approx(90.00, abs=0.005)

    _sustain(api, appeal["id"])

    after = validate_success(api.get_provider(ctx["provider"]["id"], ADMIN))
    assert after["reimbursement_adjustment_cents"] == 468720, (
        "the reconciled total 3515400 at the 1.5000 multiplier minus the paid 3046680 "
        f"is 468720, got {after['reimbursement_adjustment_cents']}"
    )


# --- cycle expiry: cycle -> provider -> allocation/grant -> session/line -----


def _harborlight_ready_for_expiry(api):
    """Provider H published at tier 2 with an OPEN grant, ACTIVE allocation, live leaves."""
    ctx = build_rating_spine(
        stop_at="PUBLISHED",
        domains=DOMAINS,
        provider_overrides={
            "legal_name": "Harborlight Early Learning",
            "license_number": "LIC-2207-H",
            "county_code": "LANE",
            "region_code": "URBAN",
            "licensed_capacity": 45,
            "active_staff_fte": 2.00,
            "weekly_onsite_cap_hours": 12.0,
        },
        credentials=CREDENTIALS_60,
        claimed=POINTS_SINGLE_OBSERVER,
        verified=POINTS_SINGLE_OBSERVER,
        raw_score=4.0,
        with_secondary=False,
        window_start="2026-08-05T09:00:00Z",
        window_end="2026-08-05T13:00:00Z",
        enrol_clock="2026-08-03T00:00:00Z",
        cycle_clock="2026-08-04T00:00:00Z",
        award_clock="2026-08-10T00:00:00Z",
        activation_clock="2026-09-05T00:00:00Z",
    )
    provider_id = ctx["provider"]["id"]
    grant = offer_grant(provider_id, ctx["cycle"]["id"], 1_000_000, "2029-06-30")
    grant = accept_grant(provider_id, grant["id"])
    allocation = create_allocation(
        provider_id,
        COACH_ID,
        funding_source="GRANT",
        funding_grant_id=grant["id"],
        period_start="2026-09-07",
        period_end="2028-12-31",
        allocated_hours=20.0,
        hourly_rate_cents=9000,
    )
    allocation = validate_success(
        api.accept_coaching_allocation(allocation["id"], make_provider_headers(provider_id))
    )
    expenditure = submit_expenditure(
        provider_id, grant["id"], "EQUIPMENT", 300_000, "2026-09-10"
    )
    session = schedule_session(
        allocation["id"], "2028-09-10T09:00:00Z", "2028-09-10T13:00:00Z", COACH_ID
    )
    return ctx, grant, allocation, expenditure, session


def test_expiry_run_past_the_inclusive_expiry_date_withdraws_the_cycle_and_unrates_the_provider(api):
    """PRD §3.5: "On an expiry run, every cycle in `ACTIVE` whose `expires_on` is strictly
    earlier than the logical clock date moves `ACTIVE → EXPIRED` — the expiry boundary is
    inclusive, so a cycle survives a run whose clock date equals `expires_on` exactly and
    expires on the first run whose clock date is strictly greater. That transition fires
    four hops. First, the cycle's publication state becomes `WITHDRAWN`. Second, because
    the cycle has left `ACTIVE`, the provider's `current_rating_cycle_id` and
    `current_tier` become null and `public_listing_visible` becomes false."

    Design: Difficulty/transitive_cascade/cycle_expiry_four_hop_provider_allocation_grant_leaf_chain
    """
    ctx, _grant, _alloc, _exp, _sess = _harborlight_ready_for_expiry(api)
    cycle_before = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle_before["weighted_total"] == pytest.approx(50.00, abs=0.005), (
        f"the single-observer spine must total 50.00, got {cycle_before['weighted_total']}"
    )
    assert cycle_before["awarded_tier"] == 2
    assert cycle_before["validity_months"] == 24
    assert cycle_before["expires_on"] == "2028-08-31T23:59:59.999Z"
    assert cycle_before["status"] == "ACTIVE"

    set_clock("2028-09-02T00:00:00Z")
    run_expiry_run()

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["status"] == "EXPIRED", (
        f"hop 1 must expire the cycle, got {cycle['status']}"
    )
    assert cycle["publication_status"] == "WITHDRAWN", (
        f"hop 1 must withdraw the publication, got {cycle['publication_status']}"
    )
    provider = validate_success(api.get_provider(ctx["provider"]["id"], ADMIN))
    assert provider["current_rating_cycle_id"] is None, (
        f"hop 2 must null current_rating_cycle_id, got {provider['current_rating_cycle_id']}"
    )
    assert provider["current_tier"] is None, (
        f"hop 2 must null current_tier, got {provider['current_tier']}"
    )
    assert provider["public_listing_visible"] is False


def test_lost_tier_suspends_the_allocation_and_freezes_the_grant_before_its_deadline(api):
    """PRD §3.5: "Third, because the provider has lost its tier, every coaching allocation
    of that provider in `ACTIVE` becomes `SUSPENDED` and every improvement grant of that
    provider in `OPEN` becomes `FROZEN`."
    PRD §3.8: "A grant in `OPEN` moves to `FROZEN` when an expiry run finds it, when the
    rating cycle expiry cascade reaches it, or simply when the logical clock date passes
    its `spend_deadline`; the precondition is that the grant be `OPEN` and that either its
    funding cycle is no longer `ACTIVE` or the clock date is strictly past the deadline."

    Design: Difficulty/transitive_cascade/cycle_expiry_four_hop_provider_allocation_grant_leaf_chain
    """
    _ctx, grant, allocation, _exp, _sess = _harborlight_ready_for_expiry(api)
    assert grant["status"] == "OPEN"
    assert allocation["status"] == "ACTIVE"

    set_clock("2028-09-02T00:00:00Z")
    run_expiry_run()

    allocation_after = validate_success(api.get_coaching_allocation(allocation["id"], ADMIN))
    assert allocation_after["status"] == "SUSPENDED", (
        f"hop 3 must suspend the ACTIVE allocation, got {allocation_after['status']}"
    )
    grant_after = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert grant_after["status"] == "FROZEN", (
        "hop 3 must freeze the OPEN grant even though the 2028-09-02 clock date is still "
        f"before the 2029-06-30 spend_deadline, got {grant_after['status']}"
    )


def test_expiry_cascade_reaches_the_leaves_returning_hours_and_committed_cents(api):
    """PRD §3.5: "Fourth, each of those consequences has its own consequence: every
    `SCHEDULED` coaching session under a newly suspended allocation becomes `CANCELLED`
    with its scheduled hours returned to the allocation's remaining hours, and every
    `SUBMITTED` expenditure under a newly frozen grant becomes `VOIDED` with its amount
    returned to the grant's available balance."
    PRD §3.8: "Freezing voids every expenditure of that grant still in `SUBMITTED`,
    returning each line's `amount_cents` to `available_cents` and reducing
    `committed_cents` by the same total, and it suspends every coaching allocation funded
    by that grant whose own state is `ACTIVE`."

    Design: Difficulty/transitive_cascade/cycle_expiry_four_hop_provider_allocation_grant_leaf_chain
    """
    _ctx, grant, allocation, expenditure, session = _harborlight_ready_for_expiry(api)
    assert session["status"] == "SCHEDULED"
    assert expenditure["status"] == "SUBMITTED"
    grant_before = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert grant_before["committed_cents"] == 300000
    assert grant_before["available_cents"] == 700000
    alloc_before = validate_success(api.get_coaching_allocation(allocation["id"], ADMIN))
    assert float(alloc_before["scheduled_hours"]) == pytest.approx(4.0, abs=0.05)
    assert float(alloc_before["remaining_hours"]) == pytest.approx(16.0, abs=0.05)

    set_clock("2028-09-02T00:00:00Z")
    run_expiry_run()

    session_after = validate_success(api.get_coaching_session(session["id"], ADMIN))
    assert session_after["status"] == "CANCELLED", (
        f"hop 4 must cancel the scheduled session, got {session_after['status']}"
    )
    alloc_after = validate_success(api.get_coaching_allocation(allocation["id"], ADMIN))
    assert float(alloc_after["scheduled_hours"]) == pytest.approx(0.0, abs=0.05), (
        f"the cancelled 4.0 hours must leave scheduled_hours at 0.0, got "
        f"{alloc_after['scheduled_hours']}"
    )
    assert float(alloc_after["delivered_hours"]) == pytest.approx(0.0, abs=0.05)
    assert float(alloc_after["remaining_hours"]) == pytest.approx(20.0, abs=0.05), (
        f"the cancelled 4.0 hours must return to remaining_hours, got "
        f"{alloc_after['remaining_hours']}"
    )
    line_after = validate_success(api.get_grant_expenditure(expenditure["id"], ADMIN))
    assert line_after["status"] == "VOIDED", (
        f"hop 4 must void the submitted expenditure, got {line_after['status']}"
    )
    grant_after = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert grant_after["committed_cents"] == 0, (
        f"the voided 300000 must leave committed_cents at 0, got "
        f"{grant_after['committed_cents']}"
    )
    assert grant_after["available_cents"] == 1000000, (
        f"the voided 300000 must return to available_cents, got "
        f"{grant_after['available_cents']}"
    )


def test_expiry_cascade_moves_the_status_axis_only_and_leaves_the_cost_breakdown_intact(api):
    """PRD §3.8: "Every grant carries **two independent state dimensions**. The
    disbursement dimension runs through `OFFERED`, `ACCEPTED`, `OPEN`, `FROZEN`, `CLOSED`,
    and `DECLINED`, with `CLOSED` and `DECLINED` terminal. The compliance dimension runs
    through `COMPLIANT`, `UNDER_REVIEW`, `FINDING_ISSUED`, `REMEDIATED`, and `RECOVERY`,
    with `RECOVERY` terminal."
    PRD §3.9: "The spend ceiling is 900,000 cents at tier 1, 750,000 at tier 2, 600,000 at
    tier 3, 400,000 at tier 4, and 250,000 at tier 5, and it is further limited by what
    the funding source can actually bear: the funding balance is the linked grant's
    `available_cents` when the source is a grant, and a flat 500,000 cents when the source
    is the state base appropriation."

    Design: Difficulty/transitive_cascade/cycle_expiry_four_hop_provider_allocation_grant_leaf_chain
    """
    _ctx, grant, allocation, _exp, _sess = _harborlight_ready_for_expiry(api)
    assert allocation["base_hours_cost_cents"] == 180000, (
        f"20.0 hours at 9000 cents gives 180000, got {allocation['base_hours_cost_cents']}"
    )
    assert allocation["admin_fee_cents"] == 16200
    assert allocation["total_cost_cents"] == 196200
    assert allocation["spend_cap_cents"] == 750000, (
        "the tier-2 spend ceiling 750000 is below the grant balance 1000000, got "
        f"{allocation['spend_cap_cents']}"
    )

    set_clock("2028-09-02T00:00:00Z")
    run_expiry_run()

    alloc_after = validate_success(api.get_coaching_allocation(allocation["id"], ADMIN))
    assert alloc_after["base_hours_cost_cents"] == 180000
    assert alloc_after["admin_fee_cents"] == 16200
    assert alloc_after["total_cost_cents"] == 196200
    assert alloc_after["spend_cap_cents"] == 750000
    grant_after = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert grant_after["compliance_status"] == "COMPLIANT", (
        "the status axis cascaded but the compliance axis did not, got "
        f"{grant_after['compliance_status']}"
    )


# --- provider suspension: publication -> allocation -> session --------------


def _ivywood_with_scheduled_session(api):
    """Provider I published at tier 4 with an ACTIVE state-funded allocation and one session."""
    ctx = _tier_four_spine("PUBLISHED", "Ivywood Child Development", "LIC-2207-I", 75)
    provider_id = ctx["provider"]["id"]
    allocation = create_allocation(
        provider_id,
        COACH_ID,
        funding_source="STATE_BASE",
        funding_grant_id=None,
        period_start="2026-09-07",
        period_end="2026-12-31",
        allocated_hours=10.0,
        hourly_rate_cents=12000,
    )
    allocation = validate_success(
        api.accept_coaching_allocation(allocation["id"], make_provider_headers(provider_id))
    )
    session = schedule_session(
        allocation["id"], "2026-09-15T09:00:00Z", "2026-09-15T13:00:00Z", COACH_ID
    )
    return ctx, allocation, session


def test_suspension_suppresses_the_listing_suspends_the_allocation_and_cancels_the_session(api):
    """PRD §3.1: "Suspension is available only from `ACTIVE` and is a three-hop cascade:
    the provider's active cycle has its publication state set to `SUPPRESSED` and the
    provider's `public_listing_visible` becomes false; then, as a second hop, every
    coaching allocation of that provider whose own state is `ACTIVE` becomes `SUSPENDED`;
    then, as a third hop caused by each allocation's suspension, every coaching session
    under that allocation still in `SCHEDULED` becomes `CANCELLED` and its scheduled hours
    return to that allocation's remaining hours."
    PRD §3.9: "Second, `admin_fee_cents` is that base cost multiplied by an administrative
    fee rate and rounded half up to whole cents, where the rate is 0.12 when the base cost
    is below 50,000 cents, 0.09 when the base cost is below 200,000 cents, and 0.06
    otherwise."

    Design: Difficulty/transitive_cascade/provider_suspend_three_hop_publication_allocation_session_chain
    """
    ctx, allocation, session = _ivywood_with_scheduled_session(api)
    assert allocation["base_hours_cost_cents"] == 120000, (
        f"10.0 hours at 12000 cents gives 120000, got {allocation['base_hours_cost_cents']}"
    )
    assert allocation["admin_fee_cents"] == 10800
    assert allocation["total_cost_cents"] == 130800
    assert allocation["spend_cap_cents"] == 400000, (
        "the tier-4 spend ceiling 400000 is below the 500000 state base appropriation, got "
        f"{allocation['spend_cap_cents']}"
    )
    assert allocation["status"] == "ACTIVE"
    provider_before = validate_success(api.get_provider(ctx["provider"]["id"], ADMIN))
    assert provider_before["status"] == "ACTIVE"
    assert provider_before["current_tier"] == 4
    assert provider_before["public_listing_visible"] is True

    suspended = validate_success(
        api.change_provider_status(
            ctx["provider"]["id"],
            {"action": "SUSPEND", "reason": "Licensing complaint under investigation."},
            ADMIN,
        )
    )
    assert suspended["status"] == "SUSPENDED", (
        f"the trigger must suspend the provider, got {suspended['status']}"
    )
    assert suspended["public_listing_visible"] is False

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["publication_status"] == "SUPPRESSED", (
        f"hop 1 must suppress the active cycle, got {cycle['publication_status']}"
    )
    alloc_after = validate_success(api.get_coaching_allocation(allocation["id"], ADMIN))
    assert alloc_after["status"] == "SUSPENDED", (
        f"hop 2 must suspend the ACTIVE allocation, got {alloc_after['status']}"
    )
    session_after = validate_success(api.get_coaching_session(session["id"], ADMIN))
    assert session_after["status"] == "CANCELLED", (
        f"hop 3 must cancel the scheduled session, got {session_after['status']}"
    )
    assert float(alloc_after["scheduled_hours"]) == pytest.approx(0.0, abs=0.05)
    assert float(alloc_after["delivered_hours"]) == pytest.approx(0.0, abs=0.05)
    assert float(alloc_after["remaining_hours"]) == pytest.approx(10.0, abs=0.05), (
        f"the cancelled 4.0 hours must return to remaining_hours, got "
        f"{alloc_after['remaining_hours']}"
    )
    assert alloc_after["total_cost_cents"] == 130800
    assert alloc_after["spend_cap_cents"] == 400000


def test_reinstatement_reverses_the_first_two_hops_but_never_recreates_the_session(api):
    """PRD §3.1: "Reinstatement is available only from `SUSPENDED` and additionally
    requires that `current_rating_cycle_id` be non-null and that the cycle it names still
    be `ACTIVE`; it moves the provider `SUSPENDED → ACTIVE`, restores that cycle's
    publication state to `PUBLISHED` when it had been published before the suspension and
    otherwise leaves it `UNPUBLISHED`, and returns the provider's `SUSPENDED` allocations
    to `ACTIVE` — but sessions cancelled during the suspension are never recreated."

    Design: Difficulty/transitive_cascade/provider_suspend_three_hop_publication_allocation_session_chain
    """
    ctx, allocation, session = _ivywood_with_scheduled_session(api)
    validate_success(
        api.change_provider_status(
            ctx["provider"]["id"],
            {"action": "SUSPEND", "reason": "Licensing complaint under investigation."},
            ADMIN,
        )
    )
    reinstated = validate_success(
        api.change_provider_status(
            ctx["provider"]["id"],
            {"action": "REINSTATE", "reason": "Complaint closed with no finding."},
            ADMIN,
        )
    )
    assert reinstated["status"] == "ACTIVE", (
        f"reinstatement must return the provider to ACTIVE, got {reinstated['status']}"
    )

    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["publication_status"] == "PUBLISHED", (
        "the cycle had been published before the suspension, so hop 1 reverses, got "
        f"{cycle['publication_status']}"
    )
    alloc_after = validate_success(api.get_coaching_allocation(allocation["id"], ADMIN))
    assert alloc_after["status"] == "ACTIVE", (
        f"hop 2 must reverse to ACTIVE, got {alloc_after['status']}"
    )
    session_after = validate_success(api.get_coaching_session(session["id"], ADMIN))
    assert session_after["status"] == "CANCELLED", (
        f"hop 3 is never reversed, got {session_after['status']}"
    )
    assert float(alloc_after["remaining_hours"]) == pytest.approx(10.0, abs=0.05), (
        "the cancelled session's hours stay released, got "
        f"{alloc_after['remaining_hours']}"
    )


# --- grant close: recovery -> compliance axis -> provider adjustment --------


def _junipergrove_reimbursed_grant(api):
    """Provider J published at tier 4 with a reimbursed grant and one ACTIVE allocation."""
    ctx = _tier_four_spine("PUBLISHED", "Junipergrove Preschool", "LIC-2207-J", 50)
    provider_id = ctx["provider"]["id"]
    grant = offer_grant(provider_id, ctx["cycle"]["id"], 1_000_000, "2026-12-31")
    grant = accept_grant(provider_id, grant["id"])
    allocation = create_allocation(
        provider_id,
        COACH_ID,
        funding_source="GRANT",
        funding_grant_id=grant["id"],
        period_start="2026-09-07",
        period_end="2026-12-31",
        allocated_hours=8.0,
        hourly_rate_cents=10000,
    )
    allocation = validate_success(
        api.accept_coaching_allocation(allocation["id"], make_provider_headers(provider_id))
    )
    set_clock("2026-10-06T00:00:00Z")
    prof_dev = submit_expenditure(
        provider_id, grant["id"], "PROF_DEV", 100_000, "2026-10-01"
    )
    equipment = submit_expenditure(
        provider_id, grant["id"], "EQUIPMENT", 200_000, "2026-10-05"
    )
    adjudicate_expenditure(prof_dev["id"], "APPROVE")
    adjudicate_expenditure(equipment["id"], "APPROVE")
    grant = validate_success(api.reimburse_grant(grant["id"], ADMIN))
    return ctx, grant, allocation, prof_dev, equipment


def test_close_prices_the_prof_dev_shortfall_and_drives_the_compliance_axis_to_recovery(api):
    """PRD §3.8: "The second is a professional-development shortfall penalty: the grant is
    expected to have reimbursed at least one quarter of its `awarded_amount_cents` in the
    `PROF_DEV` category, computed by multiplying the awarded amount by 0.25 and discarding
    any fractional cent; the shortfall is that requirement minus the total
    `reimbursable_cents` actually reimbursed in `PROF_DEV`, floored at zero; and the
    penalty is half of that shortfall, rounded half up to whole cents."
    PRD §3.8: "The first is the sum of `reimbursable_cents` over reimbursed lines whose
    `invoice_date` is strictly later than the grant's `spend_deadline` — an invoice dated
    exactly on the deadline is eligible and contributes nothing."
    PRD §3.8: "Closing moves the disbursement dimension to `CLOSED`. When
    `recovery_amount_cents` is greater than zero, the compliance dimension advances from
    wherever it stands — `COMPLIANT` or `UNDER_REVIEW` — through `FINDING_ISSUED` to
    `RECOVERY`, and the provider's `reimbursement_adjustment_cents` decreases by the
    recovered amount, recording a debt the state expects back."

    Design: Difficulty/transitive_cascade/grant_close_recovery_compliance_to_provider_adjustment_chain
    """
    ctx, grant, _alloc, _pd, _eq = _junipergrove_reimbursed_grant(api)
    assert grant["compliance_status"] == "COMPLIANT"
    before = validate_success(api.get_provider(ctx["provider"]["id"], ADMIN))
    assert before["reimbursement_adjustment_cents"] == 0, (
        "the chain must start from a zero adjustment, got "
        f"{before['reimbursement_adjustment_cents']}"
    )

    closed = validate_success(api.close_grant(grant["id"], ADMIN))
    assert closed["recovery_amount_cents"] == 75000, (
        "no invoice is later than the 2026-12-31 deadline, so recovery is half of the "
        "250000 requirement less the 100000 reimbursed in PROF_DEV, got "
        f"{closed['recovery_amount_cents']}"
    )
    assert closed["status"] == "CLOSED", (
        f"hop 1 must close the disbursement dimension, got {closed['status']}"
    )
    assert closed["compliance_status"] == "RECOVERY", (
        "hop 2 must carry the compliance dimension to RECOVERY because the recovery "
        f"amount is positive, got {closed['compliance_status']}"
    )
    after = validate_success(api.get_provider(ctx["provider"]["id"], ADMIN))
    assert after["reimbursement_adjustment_cents"] == -75000, (
        "hop 3 must decrease the provider adjustment by the recovered 75000, got "
        f"{after['reimbursement_adjustment_cents']}"
    )


def test_close_leaves_the_waterfall_ledger_intact_and_closes_the_funded_allocation(api):
    """PRD §3.8: "Its gross entitlement is its `amount_cents` multiplied by the match rate
    for its category — 0.90 for `EQUIPMENT`, 1.00 for `PROF_DEV`, 0.75 for `FACILITY`, and
    0.50 for `ADMIN` — rounded half up to whole cents."
    PRD §3.8: "Unspent `available_cents` is never recovered — it was never disbursed — so
    the grant's ledger identity still holds after close."
    PRD §3.8: "Closing also drives every coaching allocation funded by that grant whose
    state is `PROPOSED`, `ACTIVE`, or `SUSPENDED` to `CLOSED`, and increments both the
    grant's `version` and the provider's `version` by 1."

    Design: Difficulty/transitive_cascade/grant_close_recovery_compliance_to_provider_adjustment_chain
    """
    _ctx, grant, allocation, prof_dev, equipment = _junipergrove_reimbursed_grant(api)
    assert allocation["base_hours_cost_cents"] == 80000, (
        f"8.0 hours at 10000 cents gives 80000, got {allocation['base_hours_cost_cents']}"
    )
    assert allocation["admin_fee_cents"] == 7200
    assert allocation["total_cost_cents"] == 87200
    assert allocation["spend_cap_cents"] == 400000
    assert allocation["status"] == "ACTIVE"

    validate_success(api.close_grant(grant["id"], ADMIN))

    pd_line = validate_success(api.get_grant_expenditure(prof_dev["id"], ADMIN))
    assert pd_line["status"] == "REIMBURSED"
    assert pd_line["reimbursable_cents"] == 100000, (
        f"PROF_DEV matches at 1.00, got {pd_line['reimbursable_cents']}"
    )
    assert pd_line["disallowed_cents"] == 0
    eq_line = validate_success(api.get_grant_expenditure(equipment["id"], ADMIN))
    assert eq_line["status"] == "REIMBURSED"
    assert eq_line["reimbursable_cents"] == 180000, (
        f"EQUIPMENT matches at 0.90, got {eq_line['reimbursable_cents']}"
    )
    assert eq_line["disallowed_cents"] == 20000
    grant_after = validate_success(api.get_improvement_grant(grant["id"], ADMIN))
    assert grant_after["reimbursed_cents"] == 280000, (
        f"the two rounded lines sum to 280000, got {grant_after['reimbursed_cents']}"
    )
    assert grant_after["committed_cents"] == 0
    assert grant_after["available_cents"] == 720000, (
        "the awarded 1000000 is still 0 committed plus 280000 reimbursed plus 720000 "
        f"available after close, got {grant_after['available_cents']}"
    )
    alloc_after = validate_success(api.get_coaching_allocation(allocation["id"], ADMIN))
    assert alloc_after["status"] == "CLOSED", (
        f"the grant close must close its funded allocation, got {alloc_after['status']}"
    )
