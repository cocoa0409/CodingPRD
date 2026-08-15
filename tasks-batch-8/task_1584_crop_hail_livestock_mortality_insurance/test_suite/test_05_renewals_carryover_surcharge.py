"""Renewals, continuous-coverage carryover credit, and the high-risk surcharge
tier boundaries (PRD §3.4, §3.9, §2.8)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_coverage_unit,
    approve_claim,
    assert_renewal,
    bind_policy,
    create_adjuster,
    create_carrier,
    create_grower,
    create_policy_application,
    create_published_rate,
    drive_hail_claim_to_under_review,
    expire_policy,
    pay_premium,
    post_renewal,
    read_policy,
    set_clock,
    submit_planting_report,
    validate_error,
    validate_success,
)

UW = TEST_USERS["underwriter_headers"]


def _build_bound_paid_policy(api, carrier_code, acres_list,
                             effective="2026-08-02T00:00:00Z",
                             expiration="2026-08-20T00:00:00Z"):
    """Crop-hail policy with one unit per acreage entry, bound and paid in full;
    clock advanced to 2026-08-03 so the policy is ACTIVE. Returns a context
    dict including a registered adjuster."""
    carrier = create_carrier(carrier_code=carrier_code)
    cid = carrier["id"]
    grower = create_grower(cid)
    adjuster = create_adjuster(cid, capacity_max_open_claims=50)
    create_published_rate(cid)
    policy = create_policy_application(
        cid, grower["id"], "CROP_HAIL",
        effective_date=effective, expiration_date=expiration,
    )
    units = [
        add_coverage_unit(cid, policy["id"], "CROP_HAIL", declared_acres=a)
        for a in acres_list
    ]
    bound = bind_policy(cid, policy["id"])
    pay_premium(cid, policy["id"], grower["id"], bound["premium_cents"])
    set_clock(cid, "2026-08-03T00:00:00Z")
    return {
        "carrier_id": cid, "grower": grower, "adjuster": adjuster,
        "policy": bound, "units": units,
    }


def _drive_approved_claims(ctx, approved_per_unit):
    """File, inspect, review and decide (PARTIAL) one hail claim per
    (unit, amount). Each approval increments the grower's prior_claims_count
    (PRD §3.8). PARTIAL pins the final indemnity to the approver's figure —
    "a partial decision substitutes the approver's own figure" (PRD §3.8)."""
    cid = ctx["carrier_id"]
    gid = ctx["grower"]["id"]
    adj_id = ctx["adjuster"]["id"]
    for unit, approved_cents in zip(ctx["units"], approved_per_unit):
        acres = unit["declared_acres"]
        submit_planting_report(cid, ctx["policy"]["id"], unit["id"], gid,
                               reported_acres=acres)
        claim = drive_hail_claim_to_under_review(
            cid, ctx["policy"]["id"], gid, unit["id"], adj_id,
            observed_percent_damage_pct=10,
        )
        approve_claim(cid, ctx["policy"]["id"], claim["id"], approved_cents,
                      decision="PARTIAL")


class TestNestedRoundingSurchargeThenCredit:
    def _setup_renewal_with_two_prior_claims(self, api):
        """Prior policy (3-acre + 1-acre units, premium 5_328) with two approved
        claims, expired; renewed with a 3-day gap. The renewal policy carries a
        10% surcharge (two prior claims) and a 266-cent carryover credit, and
        gets 3-acre and 5-acre units."""
        ctx = _build_bound_paid_policy(api, "CHL-C2", [3, 1])
        prior = ctx["policy"]
        assert prior["premium_cents"] == 5_328  # 3_996 + 1_332
        _drive_approved_claims(ctx, [2_000, 5_000])
        expired = expire_policy(ctx["carrier_id"], prior["id"],
                                "2026-08-21T00:00:00Z")
        assert expired["lifecycle_state"] == "EXPIRED"
        renewal = validate_success(
            post_renewal(
                ctx["carrier_id"], prior["id"], "RENEW",
                "2026-08-23T00:00:00Z", "2026-12-31T00:00:00Z",
                expired["version"],
            ),
            201,
        )
        new_policy = read_policy(ctx["carrier_id"], renewal["policy_id"])
        add_coverage_unit(ctx["carrier_id"], new_policy["id"], "CROP_HAIL",
                          declared_acres=3)
        add_coverage_unit(ctx["carrier_id"], new_policy["id"], "CROP_HAIL",
                          declared_acres=5)
        return ctx["carrier_id"], renewal, new_policy

    def test_renewal_carryover_credit_and_gap_days(self, api):
        """PRD §3.9: "The renewal record itself stores the new policy as its
        `policy_id`, the renewed policy as its `prior_policy_id`, the
        `continuity_gap_days` between the prior expiration and the new effective
        date — zero when the two periods are contiguous — the computed
        `carryover_credit_cents`, which is five percent of the prior policy's
        premium when the gap is at most seven days and the prior policy expired
        rather than being cancelled, and zero otherwise, the `decision`, and a
        `decided_at` stamp from the logical clock."
        Gap 2026-08-20 → 2026-08-23 is 3 days; credit =
        round_half_up(5_328 * 5%) = 266.

        Design: Difficulty/combinatorial_formula/nested_rounding_per_unit_then_sum_then_surcharge_then_credit
        """
        _, renewal, new_policy = self._setup_renewal_with_two_prior_claims(api)
        assert_renewal(renewal)
        assert renewal["continuity_gap_days"] == 3
        assert renewal["carryover_credit_cents"] == 266
        assert new_policy["continuous_coverage_carryover_credit_cents"] == 266
        assert new_policy["high_risk_surcharge_pct"] == 10, (
            "two prior approved claims land on the inclusive ten-percent tier"
        )

    def test_new_policy_premium_rounding_order(self, api):
        """PRD §3.4: "Binding then aggregates the premium in pinned order — each
        unit's premium is rounded half up to whole cents first, then the units
        are summed; the high-risk surcharge is applied to that sum as a
        multiplier of one plus the surcharge percent, again rounded half up; and
        the carryover credit is subtracted last, with the result floored at zero
        — and freezes it as the policy's `premium_cents`."
        Per-unit: round_half_up(120_000*333/10_000)=3_996 and
        round_half_up(200_000*333/10_000)=6_660; sum 10_656; surcharge ×1.10 →
        round_half_up(11_721.6)=11_722; minus credit 266 → 11_456.

        Design: Difficulty/combinatorial_formula/nested_rounding_per_unit_then_sum_then_surcharge_then_credit
        """
        cid, _, new_policy = self._setup_renewal_with_two_prior_claims(api)
        bound = validate_success(api.bind_policy(cid, new_policy["id"], UW), 200)
        assert bound["premium_cents"] == 11_456, (
            f"pinned order round-then-sum-then-surcharge-then-credit: "
            f"{bound['premium_cents']}"
        )
        assert bound["lifecycle_state"] == "BOUND"


class TestCarryoverCreditConservedAcrossRenewal:
    def _setup_simple_renewal(self, api):
        """Prior policy (10 acres, premium 13_320), paid and expired; renewed
        with a 3-day gap; the renewal policy carries one 10-acre unit."""
        ctx = _build_bound_paid_policy(api, "CHL-R", [10])
        prior = ctx["policy"]
        assert prior["premium_cents"] == 13_320
        expired = expire_policy(ctx["carrier_id"], prior["id"],
                                "2026-08-21T00:00:00Z")
        renewal = validate_success(
            post_renewal(
                ctx["carrier_id"], prior["id"], "RENEW",
                "2026-08-23T00:00:00Z", "2026-12-31T00:00:00Z",
                expired["version"],
            ),
            201,
        )
        new_policy = read_policy(ctx["carrier_id"], renewal["policy_id"])
        add_coverage_unit(ctx["carrier_id"], new_policy["id"], "CROP_HAIL",
                          declared_acres=10)
        return ctx["carrier_id"], renewal, new_policy, prior["premium_cents"]

    def test_renewal_carryover_credit_amounts(self, api):
        """PRD §3.4: "When `prior_policy_id` is present, the
        `continuous_coverage_carryover_credit_cents` is five percent of the prior
        policy's `premium_cents`, rounded half up to whole cents, granted only
        when the prior policy expired — was not cancelled — no more than seven
        days before the new policy's effective date; in every other case the
        credit is zero."
        Prior premium 13_320 → credit round_half_up(13_320 * 5%) = 666.

        Design: Difficulty/compensating_invariant/renewal_carryover_credit_conserved_through_policy_amount
        """
        _, renewal, new_policy, _ = self._setup_simple_renewal(api)
        assert_renewal(renewal)
        assert renewal["continuity_gap_days"] == 3
        assert renewal["carryover_credit_cents"] == 666
        assert new_policy["continuous_coverage_carryover_credit_cents"] == 666

    def test_premium_conservation_across_renewal_boundary(self, api):
        """PRD §3.4: "Binding then aggregates the premium in pinned order — each
        unit's premium is rounded half up to whole cents first, then the units
        are summed; the high-risk surcharge is applied to that sum as a
        multiplier of one plus the surcharge percent, again rounded half up; and
        the carryover credit is subtracted last, with the result floored at zero
        — and freezes it as the policy's `premium_cents`."
        New premium = 13_320 - 666 = 12_654; total billed across both periods
        (13_320 + 12_654 = 25_974) differs from two uncredited premiums
        (26_640) by exactly the 666-cent credit.

        Design: Difficulty/compensating_invariant/renewal_carryover_credit_conserved_through_policy_amount
        """
        cid, _, new_policy, prior_premium = self._setup_simple_renewal(api)
        bound = validate_success(api.bind_policy(cid, new_policy["id"], UW), 200)
        assert bound["premium_cents"] == 12_654
        assert prior_premium + bound["premium_cents"] == 2 * prior_premium - 666, (
            "the credit is conserved: total billed across periods falls by "
            "exactly the carryover credit"
        )


class TestHighRiskSurchargeInclusiveBoundary:
    def test_one_prior_claim_yields_zero_surcharge(self, api):
        """PRD §3.4: "The `high_risk_surcharge_pct` reads the grower's
        `prior_claims_count`: zero surcharge when the grower has at most one
        approved-or-paid claim, ten percent when the count is two or three, and
        twenty-five percent when it is four or more — the tier boundaries are
        inclusive."

        Design: Difficulty/boundary_precision_check/high_risk_surcharge_threshold_inclusive_boundary
        """
        ctx = _build_bound_paid_policy(api, "CHL-K1", [1],
                                       expiration="2026-12-31T00:00:00Z")
        _drive_approved_claims(ctx, [1_000])
        res = api.create_policy(
            ctx["carrier_id"],
            {"grower_id": ctx["grower"]["id"], "policy_kind": "CROP_HAIL",
             "effective_date": "2026-08-10T00:00:00Z",
             "expiration_date": "2026-12-31T00:00:00Z"},
            UW,
        )
        new_policy = validate_success(res, 201)
        assert new_policy["high_risk_surcharge_pct"] == 0, (
            "one approved claim is at most one — zero surcharge"
        )

    def test_two_prior_claims_yield_ten_percent_surcharge(self, api):
        """PRD §3.4: "The `high_risk_surcharge_pct` reads the grower's
        `prior_claims_count`: zero surcharge when the grower has at most one
        approved-or-paid claim, ten percent when the count is two or three, and
        twenty-five percent when it is four or more — the tier boundaries are
        inclusive."

        Design: Difficulty/boundary_precision_check/high_risk_surcharge_threshold_inclusive_boundary
        """
        ctx = _build_bound_paid_policy(api, "CHL-K2", [1, 1],
                                       expiration="2026-12-31T00:00:00Z")
        _drive_approved_claims(ctx, [1_000, 1_000])
        res = api.create_policy(
            ctx["carrier_id"],
            {"grower_id": ctx["grower"]["id"], "policy_kind": "CROP_HAIL",
             "effective_date": "2026-08-10T00:00:00Z",
             "expiration_date": "2026-12-31T00:00:00Z"},
            UW,
        )
        new_policy = validate_success(res, 201)
        assert new_policy["high_risk_surcharge_pct"] == 10, (
            "two approved claims hit the inclusive ten-percent boundary"
        )


class TestRenewalOptimisticConcurrency:
    def test_occ_stale_version_on_renewal_returns_412(self, api):
        """PRD §2.8: "Creating a renewal requires the request to carry
        `expected_prior_policy_version`, holding the `version` of the policy
        being renewed as the client last observed it. If the prior policy's
        current `version` has advanced since that read — because a premium
        payment posted, a claim was filed, or any other mutation landed in
        between — the renewal is rejected with `ERR_STALE_VERSION` (HTTP 412),
        preventing the client from renewing a policy whose current state it has
        not observed."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_renewal_returns_412
        """
        ctx = _build_bound_paid_policy(api, "CHL-CC2", [1])
        expired = expire_policy(ctx["carrier_id"], ctx["policy"]["id"],
                                "2026-08-21T00:00:00Z")
        assert expired["lifecycle_state"] == "EXPIRED"
        res = post_renewal(
            ctx["carrier_id"], ctx["policy"]["id"], "RENEW",
            "2026-08-23T00:00:00Z", "2026-12-31T00:00:00Z",
            expired["version"] - 1,  # stale: one behind the current version
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
