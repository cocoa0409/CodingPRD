"""Provisional vs final scoring, interim vs reconciled subsidy, and the coaching fee band."""
import pytest

from test_helpers import (
    ADMIN_USER_ID,
    DOMAINS_UNEQUAL_CEILINGS,
    REVIEWER_USER_ID,
    TEST_USERS,
    api_client,
    approve_claim,
    build_rating_spine,
    create_allocation,
    create_coaching_allocation_payload,
    create_enrolled_provider,
    credential_specs,
    file_appeal,
    make_provider_headers,
    make_reviewer_headers,
    pay_claim,
    run_expiry_run,
    set_clock,
    submit_claim,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]

CLAIMED_A = {
    "LEARNING_ENVIRONMENT": 36,
    "STAFF_QUALIFICATIONS": 28,
    "FAMILY_PARTNERSHIP": 18,
    "ADMINISTRATION": 16,
    "CHILD_ASSESSMENT": 9,
}
VERIFIED_A = {
    "LEARNING_ENVIRONMENT": 30,
    "STAFF_QUALIFICATIONS": 26,
    "FAMILY_PARTNERSHIP": 15,
    "ADMINISTRATION": 14,
    "CHILD_ASSESSMENT": 8,
}


def _spine_variant_a(stop_at):
    """Unequal-ceiling domain set, compliance 92.00, two reliable observers at 5.5."""
    return build_rating_spine(
        stop_at=stop_at,
        domains=DOMAINS_UNEQUAL_CEILINGS,
        provider_overrides={
            "legal_name": "Maple Grove Early Learning",
            "county_code": "MRN",
            "region_code": "RURAL",
            "licensed_capacity": 80,
            "active_staff_fte": 10.00,
            "weekly_onsite_cap_hours": 20,
        },
        credentials=credential_specs(9.20),
        claimed=CLAIMED_A,
        verified=VERIFIED_A,
        raw_score=5.5,
        with_secondary=True,
        window_start="2026-08-12T09:00:00Z",
        window_end="2026-08-12T13:00:00Z",
        award_clock="2026-08-12T00:00:00Z",
    )


def test_provisional_preview_keeps_claimed_points_for_the_observation_linked_domain(api):
    """PRD §3.5: "For the observation-linked domain, if the cycle has no observation
    composite yet the credited number is used unchanged, which is why a provisional run
    before finalization simply keeps the claimed points; once a composite exists, the
    domain's points are instead derived from it by multiplying the domain's `max_points`
    by an observation fraction and rounding half up to a whole integer."
    PRD §3.5: "From that total alone comes `points_tier`: 5 when the weighted total is at
    least 85.00, 4 when it is at least 70.00, 3 when it is at least 55.00, 2 when it is at
    least 40.00, and 1 otherwise."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_domain_points_on_rating_cycle
    """
    ctx = _spine_variant_a("RELIABILITY_CHECK")
    preview = validate_success(
        api.get_score_preview(ctx["cycle"]["id"], ADMIN, params={"variant": "PROVISIONAL"})
    )
    assert preview["weighted_total"] == pytest.approx(86.00, abs=0.005), (
        f"provisional weighted_total must be 86.00, got {preview['weighted_total']}"
    )
    assert preview["awarded_tier"] == 5, (
        f"provisional awarded_tier must be 5, got {preview['awarded_tier']}"
    )
    provider = validate_success(api.get_provider(ctx["provider"]["id"], ADMIN))
    assert provider["credential_compliance_pct"] == pytest.approx(92.00, abs=0.005)


def test_final_award_derives_observation_linked_points_from_the_composite(api):
    """PRD §3.5: "Under the final variant that number is the verified value the state
    confirmed for that domain code; under the provisional variant it is the value the
    provider claimed."
    PRD §3.5: "That fraction is 1.00 when the composite is at least 6.00, 0.80 when it is
    at least 5.00, 0.60 when it is at least 4.00, 0.40 when it is at least 3.00, and 0.20
    otherwise."
    PRD §3.5: "`validity_months` is 36 when `awarded_tier` is at least 4 and 24 otherwise."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_domain_points_on_rating_cycle
    """
    ctx = _spine_variant_a("AWARDED")
    cycle = ctx["cycle"]
    assert cycle["observation_composite"] == pytest.approx(5.50, abs=0.005)
    assert cycle["weighted_total"] == pytest.approx(77.50, abs=0.005), (
        f"final weighted_total must be 77.50, got {cycle['weighted_total']}"
    )
    assert cycle["points_tier"] == 4
    assert cycle["awarded_tier"] == 4
    assert cycle["domain_points"]["LEARNING_ENVIRONMENT"] == 32
    assert cycle["domain_points"]["STAFF_QUALIFICATIONS"] == 24
    assert cycle["domain_points"]["FAMILY_PARTNERSHIP"] == 15
    assert cycle["domain_points"]["ADMINISTRATION"] == 14
    assert cycle["domain_points"]["CHILD_ASSESSMENT"] == 8
    assert cycle["highest_block_cleared"] == 3
    assert cycle["score_variant"] == "FINAL"
    assert cycle["validity_months"] == 36
    assert cycle["effective_date"] == "2026-09-01T00:00:00.000Z"
    assert cycle["expires_on"] == "2029-08-31T23:59:59.999Z"
    assert cycle["rerating_window_opens_on"] == "2029-06-02T00:00:00.000Z"


def test_provisional_and_final_runs_diverge_on_identical_stored_rows(api):
    """PRD §3.5: "Both stages exist in a **provisional** and a **final** variant, and the
    same stored data can legitimately produce a higher tier under the provisional variant
    than under the final one."
    PRD §3.5: "For the `STAFF_QUALIFICATIONS` domain, the credited number is capped: the
    cap is the domain's `max_points` multiplied by a credential fraction and rounded half
    up to a whole integer, and the awarded points are the smaller of the credited number
    and that cap."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_domain_points_on_rating_cycle
    """
    ctx = _spine_variant_a("RELIABILITY_CHECK")
    provisional = validate_success(
        api.get_score_preview(ctx["cycle"]["id"], ADMIN, params={"variant": "PROVISIONAL"})
    )
    validate_success(api.finalize_visit(ctx["visit"]["id"], ADMIN))
    set_clock("2026-08-12T00:00:00Z")
    awarded = validate_success(api.award_cycle(ctx["cycle"]["id"], {"score_variant": "FINAL"}, ADMIN))
    assert provisional["weighted_total"] != awarded["weighted_total"], (
        "the provisional projection must differ from the final award on these rows"
    )
    assert provisional["awarded_tier"] == 5 and awarded["awarded_tier"] == 4


# --- interim vs reconciled subsidy multiplier --------------------------------

VERIFIED_B = {
    "LEARNING_ENVIRONMENT": 24,
    "STAFF_QUALIFICATIONS": 22,
    "FAMILY_PARTNERSHIP": 13,
    "ADMINISTRATION": 11,
    "CHILD_ASSESSMENT": 7,
}


def _spine_variant_b():
    """FRONTIER provider, compliance 85.00, single observer at 4.5, awarded tier 3."""
    return build_rating_spine(
        stop_at="PUBLISHED",
        domains=DOMAINS_UNEQUAL_CEILINGS,
        provider_overrides={
            "legal_name": "Frontier Pines Child Care",
            "county_code": "FRT",
            "region_code": "FRONTIER",
            "licensed_capacity": 50,
            "active_staff_fte": 10.00,
        },
        credentials=credential_specs(8.50),
        claimed=VERIFIED_B,
        verified=VERIFIED_B,
        raw_score=4.5,
        window_start="2026-08-06T09:00:00Z",
        window_end="2026-08-06T13:00:00Z",
        award_clock="2026-08-10T00:00:00Z",
        activation_clock="2026-09-01T00:00:00Z",
    )


def test_interim_variant_prices_the_month_at_the_first_day_tier(api):
    """PRD §3.7: "Under the **interim** variant a single multiplier is used for the whole
    month, taken from the tier in force on the first calendar day of the service month, so
    a mid-month tier change is ignored; that value is rounded half up to four decimal
    places and stored as `tier_multiplier_applied`."
    PRD §3.7: "each age band's subsidised child-days are multiplied by that band's base
    daily rate — 4,500 cents per infant day, 3,800 cents per toddler day, and 3,200 cents
    per preschool day — and the three products are added to give `base_amount_cents`."

    Design: Difficulty/dual_variant_calc/interim_vs_reconciled_subsidy_multiplier_on_subsidy_claim
    """
    ctx = _spine_variant_b()
    assert ctx["cycle"]["weighted_total"] == pytest.approx(64.58, abs=0.005)
    assert ctx["cycle"]["points_tier"] == 3
    assert ctx["cycle"]["awarded_tier"] == 3
    provider = validate_success(api.get_provider(ctx["provider"]["id"], ADMIN))
    assert provider["credential_compliance_pct"] == pytest.approx(85.00, abs=0.005)

    claim = submit_claim(ctx["provider"]["id"], "2026-09", infant=22, toddler=41, preschool=53)
    assert claim["base_amount_cents"] == 424400, (
        f"base_amount_cents must be 424400, got {claim['base_amount_cents']}"
    )
    approved = approve_claim(claim["id"], variant="INTERIM")
    assert approved["tier_multiplier_applied"] == pytest.approx(1.1500, abs=0.00005)
    assert approved["reimbursement_cents"] == 561270, (
        f"INTERIM reimbursement_cents must be 561270, got {approved['reimbursement_cents']}"
    )


def test_reconciled_repay_after_sustained_appeal_uses_the_day_weighted_multiplier(api):
    """PRD §3.7: "Under the **reconciled** variant the multiplier is day-weighted: the
    system adds up the tier multiplier for each calendar day of the service month, divides
    that sum by the number of calendar days in the month, and rounds half up to four
    decimal places."
    PRD §3.7: "A reconciled payment rewrites `reimbursement_cents` under the reconciled
    variant and returns the provider's `reimbursement_adjustment_cents` to its pre-cascade
    value, so the pair of flagging-then-repaying leaves that conserved balance unchanged."
    PRD §3.6: "In the first hop the cycle returns `UNDER_APPEAL → AWARDED` with its
    `awarded_tier` replaced by the ordered `adjusted_tier`, `appeal_adjusted` set to true,
    and the validity arithmetic rerun while keeping the original `effective_date` — which
    means `validity_months`, `expires_on`, and `rerating_window_opens_on` may change while
    the effective date does not."

    Design: Difficulty/dual_variant_calc/interim_vs_reconciled_subsidy_multiplier_on_subsidy_claim
    """
    ctx = _spine_variant_b()
    claim = submit_claim(ctx["provider"]["id"], "2026-09", infant=22, toddler=41, preschool=53)
    interim = approve_claim(claim["id"], variant="INTERIM")
    pay_claim(claim["id"])
    interim_cents = interim["reimbursement_cents"]

    set_clock("2026-09-08T00:00:00Z")
    appeal = file_appeal(ctx["provider"]["id"], ctx["cycle"]["id"], "SCORING_ERROR",
                         "learning environment subscales mis-entered")
    validate_success(
        api.appeal_review_action(appeal["id"], {"action": "START"}, make_reviewer_headers())
    )
    validate_success(
        api.appeal_review_action(
            appeal["id"],
            {"action": "SUSTAIN", "adjusted_tier": 5, "note": "rescored to tier 5"},
            make_reviewer_headers(),
        )
    )
    cycle = validate_success(api.get_rating_cycle(ctx["cycle"]["id"], ADMIN))
    assert cycle["awarded_tier"] == 5
    assert cycle["appeal_adjusted"] is True
    assert cycle["effective_date"] == "2026-09-01T00:00:00.000Z"
    assert cycle["validity_months"] == 36
    assert cycle["expires_on"] == "2029-08-31T23:59:59.999Z"

    run_expiry_run()
    repaid = validate_success(api.pay_claim(claim["id"], ADMIN))
    assert repaid["tier_multiplier_applied"] == pytest.approx(1.5000, abs=0.00005)
    assert repaid["reimbursement_cents"] == 732090, (
        f"RECONCILED reimbursement_cents must be 732090, got {repaid['reimbursement_cents']}"
    )
    assert repaid["variant_applied"] == "RECONCILED"
    assert repaid["status"] == "PAID"
    assert repaid["reimbursement_cents"] - interim_cents == 170820


# --- coaching administrative fee band ---------------------------------------


def test_admin_fee_band_is_keyed_on_the_base_cost_not_the_total(api):
    """PRD §3.9: "Second, `admin_fee_cents` is that base cost multiplied by an
    administrative fee rate and rounded half up to whole cents, where the rate is 0.12
    when the base cost is below 50,000 cents, 0.09 when the base cost is below 200,000
    cents, and 0.06 otherwise; both breakpoints are strict on their upper bound, so a base
    cost of exactly 50,000 cents falls in the 0.09 band while 49,999 cents falls in the
    0.12 band."
    PRD §3.9: "Third, `total_cost_cents` is the base cost plus the administrative fee."

    Design: Difficulty/dual_variant_calc/fee_on_base_vs_fee_on_total_coaching_cost
    """
    set_clock("2026-08-01T00:00:00Z")
    provider = create_enrolled_provider(
        legal_name="Cedar Hollow Learning Center",
        county_code="SNO",
        region_code="URBAN",
        licensed_capacity=45,
        active_staff_fte=6.00,
        weekly_onsite_cap_hours=12,
    )
    assert provider["current_tier"] is None
    allocation = validate_success(
        api.create_coaching_allocation(
            provider["id"],
            create_coaching_allocation_payload(
                "coach-11",
                funding_source="STATE_BASE",
                funding_grant_id=None,
                period_start="2026-08-03",
                period_end="2026-10-30",
                allocated_hours=15.5,
                hourly_rate_cents=12261,
            ),
            ADMIN,
        ),
        201,
    )
    assert allocation["base_hours_cost_cents"] == 190046, (
        f"base_hours_cost_cents must be 190046, got {allocation['base_hours_cost_cents']}"
    )
    assert allocation["admin_fee_cents"] == 17104, (
        "the 0.09 band keyed on the base cost gives 17104; keying on the total would "
        f"give a 0.06 fee instead, got {allocation['admin_fee_cents']}"
    )
    assert allocation["total_cost_cents"] == 207150
    assert allocation["total_cost_cents"] != 201449


def test_state_base_funding_balance_binds_the_spend_cap_for_an_unrated_provider(api):
    """PRD §3.9: "The **effective tier** is the provider's `current_tier`, or 1 when the
    provider has no current tier."
    PRD §3.9: "The allocation's `spend_cap_cents` is the smaller of the tier spend ceiling
    and that funding balance, and `total_cost_cents` above `spend_cap_cents` is refused
    with `ERR_COACHING_SPEND_CAP_EXCEEDED` and HTTP 422."
    PRD §3.9: "A newly created allocation sits in `PROPOSED` with `scheduled_hours` at 0,
    `delivered_hours` at 0, and `remaining_hours` equal to `allocated_hours`."

    Design: Difficulty/dual_variant_calc/fee_on_base_vs_fee_on_total_coaching_cost
    """
    set_clock("2026-08-01T00:00:00Z")
    provider = create_enrolled_provider(
        legal_name="Cedar Hollow Learning Center",
        county_code="SNO",
        region_code="URBAN",
        licensed_capacity=45,
        active_staff_fte=6.00,
    )
    allocation = create_allocation(
        provider["id"],
        "coach-11",
        funding_source="STATE_BASE",
        funding_grant_id=None,
        period_start="2026-08-03",
        period_end="2026-10-30",
        allocated_hours=15.5,
        hourly_rate_cents=12261,
    )
    assert allocation["spend_cap_cents"] == 500000, (
        "tier-1 spend ceiling is 900000 but the state base appropriation caps the funding "
        f"balance at 500000, got {allocation['spend_cap_cents']}"
    )
    assert allocation["status"] == "PROPOSED"
    assert float(allocation["remaining_hours"]) == pytest.approx(15.5, abs=0.05)
