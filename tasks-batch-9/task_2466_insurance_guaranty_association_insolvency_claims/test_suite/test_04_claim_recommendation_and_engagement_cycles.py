"""Recommend/remand cycles, engagement windows and sister-association round trips."""

from test_helpers import (
    CLOCK_STARTUP_UTC,
    COMMITTEE_OFFICER_USER_ID,
    TEST_USERS,
    api_client,
    assert_instant_equals,
    assert_vendor_assignment,
    engage_vendor,
    get_success_data,
    make_claims_committee_officer_headers,
    raise_referral,
    read_claim,
    read_insolvency,
    read_vendor_assignment,
    recommend,
    remand,
    respond_to_referral,
    setup_claim_after_two_remand_cycles,
    setup_claim_under_adjustment,
    validate_error,
)

ADMIN = TEST_USERS["association_admin_headers"]

INCUMBENT_ADJUSTER = {
    "vendor_type": "ADJUSTER",
    "vendor_name": "Kestrel Claims Services",
    "settlement_authority_cents": 2_500_000,
    "hourly_rate_cents": 18_000,
    "engagement_start": "2026-08-01",
    "engagement_end": "2026-08-31",
}
DEFENSE_COUNSEL_SAME_WINDOW = {
    "vendor_type": "DEFENSE_COUNSEL",
    "vendor_name": "Halloran and Pike LLP",
    "settlement_authority_cents": 0,
    "hourly_rate_cents": 42_000,
    "engagement_start": "2026-08-01",
    "engagement_end": "2026-08-31",
}
TOUCHING_ADJUSTER = {
    "vendor_type": "ADJUSTER",
    "vendor_name": "Bluewater Adjusting",
    "settlement_authority_cents": 1_500_000,
    "hourly_rate_cents": 16_000,
    "engagement_start": "2026-08-31",
    "engagement_end": "2026-09-15",
}
CLEAR_ADJUSTER = {
    **TOUCHING_ADJUSTER,
    "engagement_start": "2026-09-01",
    "engagement_end": "2026-09-30",
}

OHIO_CLAIM = {
    "claim_number": "C-1",
    "claimant_name": "Ben Ortiz",
    "claimant_state_code": "OH",
    "gross_loss_cents": 900_000,
}
SMALL_AUTHORITY_ADJUSTER = {**INCUMBENT_ADJUSTER, "settlement_authority_cents": 900_000}


class TestBoundedRemandCycle:
    """The committee may send a number back twice, and no more."""

    def test_third_remand_is_refused_and_the_live_recommendation_survives(self):
        """Remand is permitted at most twice per claim: the check is that `remand_count` is currently
        below 2, so a first remand is allowed on a claim with `remand_count` 0, a second on a claim
        with `remand_count` 1, and a third attempt on a claim whose `remand_count` has already
        reached 2 is refused with `ERR_REMAND_LIMIT_REACHED`.

        Design: Difficulty/non_linear_state_machine/third_remand_refused_after_two_recommend_remand_cycles
        """
        env = setup_claim_after_two_remand_cycles(
            assignment_overrides=dict(INCUMBENT_ADJUSTER),
            claim_overrides={"claim_number": "C-1", "gross_loss_cents": 4_500_000},
        )
        assert env["claim"]["remand_count"] == 2, env["claim"]["remand_count"]

        response = api_client.remand_claim(
            env["claim"]["id"],
            {"remand_reason": "committee wants a further reduction"},
            make_claims_committee_officer_headers(COMMITTEE_OFFICER_USER_ID),
        )
        validate_error(response, "ERR_REMAND_LIMIT_REACHED", 409)

        claim = read_claim(env["claim"]["id"])
        assert claim["status"] == "RECOMMENDED", (
            f"the refused remand must leave the claim where it was, got {claim['status']}"
        )
        assert claim["remand_count"] == 2
        assert claim["recommended_amount_cents"] == 2_000_000, (
            f"the third recommendation is still live, got {claim['recommended_amount_cents']}"
        )

    def test_each_remand_clears_the_recommendation_and_books_no_reserve(self):
        """A remand clears `recommended_amount_cents`, `recommended_by_vendor_name` and
        `recommended_at_utc` back to null, so the next recommendation starts clean.

        Design: Difficulty/non_linear_state_machine/third_remand_refused_after_two_recommend_remand_cycles
        """
        env = setup_claim_under_adjustment(
            assignment_overrides=dict(INCUMBENT_ADJUSTER),
            claim_overrides={"claim_number": "C-1", "gross_loss_cents": 4_500_000},
        )
        recommended = recommend(env, 2_400_000, "first recommendation")
        assert recommended["status"] == "RECOMMENDED"
        assert recommended["recommended_by_vendor_name"] == "Kestrel Claims Services"
        assert recommended["remand_count"] == 0

        remanded = remand(env, "medical documentation incomplete")
        assert remanded["status"] == "ADJUSTING", remanded["status"]
        assert remanded["remand_count"] == 1
        assert remanded["recommended_amount_cents"] is None
        assert remanded["recommended_by_vendor_name"] is None
        assert remanded["recommended_at_utc"] is None

        recommend(env, 2_200_000, "second recommendation")
        second = remand(env, "wage loss unverified")
        assert second["remand_count"] == 2, second["remand_count"]

        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["reserved_claim_cents"] == 0, (
            "no estate reserve is booked before approval, got "
            f"{insolvency['reserved_claim_cents']}"
        )


class TestEngagementWindows:
    """A vendor engagement occupies a closed date interval."""

    def test_second_adjuster_starting_on_the_incumbents_last_day_collides(self):
        """Because the interval is closed at both ends, engagements that merely touch — one ending on
        the day the next begins — do collide, and the create is refused with
        `ERR_ADJUSTER_ENGAGEMENT_OVERLAP`; only engagements already in `SUPERSEDED` or `CLOSED` are
        ignored by this test.

        Design: Difficulty/resource_temporal_overlap/adjuster_engagements_are_closed_intervals_so_touching_dates_collide
        """
        env = setup_claim_under_adjustment(
            assignment_overrides=dict(INCUMBENT_ADJUSTER),
            claim_overrides={"claim_number": "C-1", "gross_loss_cents": 4_500_000},
        )

        response = api_client.create_vendor_assignment(
            env["claim"]["id"], dict(TOUCHING_ADJUSTER), ADMIN
        )
        validate_error(response, "ERR_ADJUSTER_ENGAGEMENT_OVERLAP", 409)

        incumbent = read_vendor_assignment(env["claim"]["id"], env["assignment"]["id"])
        assert incumbent["status"] == "ASSIGNED", (
            f"the refused create must not disturb the incumbent, got {incumbent['status']}"
        )
        rows = get_success_data(api_client.list_vendor_assignments(env["claim"]["id"], ADMIN))
        assert len(rows) == 1, f"the collided engagement must not have been created, got {rows}"

    def test_overlap_is_scoped_to_one_vendor_type_and_replacement_supersedes(self):
        """Two engagements of the same `vendor_type` on the same claim may not overlap in time while
        both are live.

        Design: Difficulty/resource_temporal_overlap/adjuster_engagements_are_closed_intervals_so_touching_dates_collide
        """
        env = setup_claim_under_adjustment(
            assignment_overrides=dict(INCUMBENT_ADJUSTER),
            claim_overrides={"claim_number": "C-1", "gross_loss_cents": 4_500_000},
        )

        counsel = engage_vendor(env, **DEFENSE_COUNSEL_SAME_WINDOW)
        assert_vendor_assignment(counsel)
        assert counsel["status"] == "ASSIGNED", (
            "defense counsel over the very same window is a different vendor type and is accepted, "
            f"got {counsel['status']}"
        )

        replacement = get_success_data(
            api_client.create_vendor_assignment(env["claim"]["id"], dict(CLEAR_ADJUSTER), ADMIN)
        )
        assert replacement["status"] == "ASSIGNED"

        incumbent = read_vendor_assignment(env["claim"]["id"], env["assignment"]["id"])
        assert incumbent["status"] == "SUPERSEDED", (
            f"the older adjuster engagement is superseded rather than kept live, got {incumbent['status']}"
        )
        claim = read_claim(env["claim"]["id"])
        assert claim["status"] == "ADJUSTING", (
            f"replacing a vendor does not move the claim, got {claim['status']}"
        )
        rows = get_success_data(api_client.list_vendor_assignments(env["claim"]["id"], ADMIN))
        assert len(rows) == 3, f"all three engagements remain on the claim, got {len(rows)}"


class TestDeclinedReferralReversal:
    """Parking a claim with a sister association and getting it back."""

    def test_offer_parks_the_claim_and_raises_the_pending_referral_counter(self):
        """A successful offer creates the referral in `OPEN` with `response_note` and
        `responded_at_utc` null, moves the claim from whichever of `SCREENED_ELIGIBLE` or `ADJUSTING`
        it was in into `REFERRAL_PENDING`, records the status it came from in `pre_referral_status`,
        and increments the insolvency file's `referral_pending_count` by one.

        Design: Difficulty/compensating_invariant/declined_referral_fully_reverses_the_pending_referral_counter
        """
        env = setup_claim_under_adjustment(
            assignment_overrides=dict(SMALL_AUTHORITY_ADJUSTER),
            claim_overrides=dict(OHIO_CLAIM),
        )
        before = read_insolvency(env["insolvency"]["id"])
        assert before["referral_pending_count"] == 0

        referral = raise_referral(env, "OH", "CLAIMANT_RESIDENCE")
        assert referral["status"] == "OPEN", referral["status"]
        assert referral["response_note"] is None
        assert referral["responded_at_utc"] is None

        claim = read_claim(env["claim"]["id"])
        assert claim["status"] == "REFERRAL_PENDING", claim["status"]
        assert claim["pre_referral_status"] == "ADJUSTING", (
            f"the status it was parked from is stashed, got {claim['pre_referral_status']}"
        )
        after = read_insolvency(env["insolvency"]["id"])
        assert after["referral_pending_count"] == 1, after["referral_pending_count"]

    def test_declined_disposition_restores_the_claim_and_the_counter_exactly(self):
        """A declined referral changes no money, closes no engagement and leaves `net_payable_cents`
        exactly as it was — the claim simply resumes where it left off.

        Design: Difficulty/compensating_invariant/declined_referral_fully_reverses_the_pending_referral_counter
        """
        env = setup_claim_under_adjustment(
            assignment_overrides=dict(SMALL_AUTHORITY_ADJUSTER),
            claim_overrides=dict(OHIO_CLAIM),
        )
        raise_referral(env, "OH", "CLAIMANT_RESIDENCE")
        referral = respond_to_referral(env, "DECLINED", "Ohio association denies jurisdiction")

        assert referral["status"] == "DECLINED", referral["status"]
        assert referral["basis_state_code"] == "OH", (
            f"claimant residence resolves to the claimant's own state, got {referral['basis_state_code']}"
        )
        assert_instant_equals(referral["responded_at_utc"], CLOCK_STARTUP_UTC)

        claim = read_claim(env["claim"]["id"])
        assert claim["status"] == "ADJUSTING", (
            f"the claim resumes the status it was parked from, got {claim['status']}"
        )
        assert claim["pre_referral_status"] is None
        assert claim["net_payable_cents"] == 890_000, (
            f"a 900000 loss less the 10000 statutory deductible is untouched, got {claim['net_payable_cents']}"
        )
        assert claim["remand_count"] == 0

        engagement = read_vendor_assignment(env["claim"]["id"], env["assignment"]["id"])
        assert engagement["status"] == "ASSIGNED", (
            f"a decline closes no engagement, got {engagement['status']}"
        )
        insolvency = read_insolvency(env["insolvency"]["id"])
        assert insolvency["referral_pending_count"] == 0, (
            f"the counter must return to 0 with no drift, got {insolvency['referral_pending_count']}"
        )
        assert insolvency["reserved_claim_cents"] == 0
