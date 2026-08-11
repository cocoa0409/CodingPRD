"""Incentive awards: tier attainment, premium cap, RA variant, dispute loop
(PRD §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_settled_points,
    compute_awards,
    create_referral,
    create_screening,
    discharge_referral,
    engage_referral,
    get_enrollment_award,
    log_sessions,
    make_employee_headers,
    result_screening,
    set_clock,
    setup_active_enrollment,
    setup_confirmed_award,
    setup_discharged_referral,
    submit_hra,
    validate_error,
    validate_success,
)

BA = TEST_USERS["benefits_admin_headers"]


class TestReasonableAlternativeOverride:
    """Difficulty instance: identical settled points (200, tier NONE) produce
    award_cents 0 under STANDARD but 36000 under REASONABLE_ALTERNATIVE."""

    def _setup_ra_enrollment(self, api):
        ctx = setup_active_enrollment(ra_eligible=True)
        enr_id = ctx["enrollment"]["id"]
        add_settled_points(enr_id, 200)
        referral = create_referral(enr_id, reason="RA_REQUEST")
        engage_referral(referral["id"], "coach-1")
        log_sessions(referral["id"], "coach-1")
        discharge_referral(referral["id"], "coach-1", "GOALS_MET")
        compute_awards(ctx["program"]["id"])
        return ctx, get_enrollment_award(enr_id)

    def test_ra_variant_overrides_standard_award(self, api):
        """PRD §3.7: "When the enrollment is `ra_eligible` and at least one of its
        CoachingReferrals stands `DISCHARGED` with outcome `GOALS_MET`, the
        reasonable-alternative standard applies: `applied_variant` is
        `REASONABLE_ALTERNATIVE` and `award_cents` is the smaller of the program's
        `gold_award_cents` and the cap, regardless of the points tier — identical
        activity data thereby yields a different conferred award."

        Design: Difficulty/dual_variant_calc/reasonable_alternative_overrides_standard_award
        """
        _ctx, award = self._setup_ra_enrollment(api)
        assert award["tier"] == "NONE", "200 settled points is below BRONZE 500"
        assert award["standard_award_cents"] == 0, "STANDARD award of tier NONE is zero"
        assert award["applied_variant"] == "REASONABLE_ALTERNATIVE"
        assert award["award_cents"] == 36000, "min(gold 60000, cap 36000)"

    def test_ra_variant_net_differential(self, api):
        """PRD §3.7: "The `net_annual_differential_cents` is the surcharge minus the
        award; a positive figure means the employee pays more."
        PRD §3.7: "`surcharge_cents` is the employer's `tobacco_surcharge_cents` when
        the member's `tobacco_attested` is true and no `TOBACCO_CESSATION` referral
        of the enrollment stands `DISCHARGED` with `GOALS_MET`, and zero when the
        surcharge is waived by that completed cessation or no attestation exists."

        Design: Difficulty/dual_variant_calc/reasonable_alternative_overrides_standard_award
        """
        _ctx, award = self._setup_ra_enrollment(api)
        assert award["surcharge_cents"] == 0, "no tobacco attestation on file"
        assert award["net_annual_differential_cents"] == -36000, "0 - 36000"


class TestTierAttainmentMultiInput:
    """Difficulty instance: >=3 inputs with non-linear interaction — settled points,
    HRA existence, tobacco attestation and the min(tier_value, cap) clamp."""

    def _setup_silver_tobacco(self, api):
        ctx = setup_active_enrollment(tobacco_attested=True)
        enr_id = ctx["enrollment"]["id"]
        add_settled_points(enr_id, 1500)
        submit_hra(enr_id, ctx["employee"]["id"], answers=[2] * 10)
        compute_awards(ctx["program"]["id"])
        return ctx, get_enrollment_award(enr_id)

    def test_silver_tier_with_tobacco_stacks_to_net(self, api):
        """PRD §3.7: "The `tier` is ... `SILVER` when P reaches at least the
        `silver_threshold` and H is present..."
        PRD §3.7: "`surcharge_cents` is the employer's `tobacco_surcharge_cents` when
        the member's `tobacco_attested` is true and no `TOBACCO_CESSATION` referral
        of the enrollment stands `DISCHARGED` with `GOALS_MET`... The
        `net_annual_differential_cents` is the surcharge minus the award..."

        Design: Difficulty/combinatorial_formula/tier_attainment_multi_input_with_cap
        """
        _ctx, award = self._setup_silver_tobacco(api)
        assert award["tier"] == "SILVER", "P=1500 >= silver_threshold 1500 with HRA present"
        assert award["award_cents"] == 30000
        assert award["surcharge_cents"] == 50000, "attested tobacco, no cessation waiver"
        assert award["net_annual_differential_cents"] == 20000, "50000 - 30000"

    def test_silver_standard_variant_stored_for_comparison(self, api):
        """PRD §3.7: "The tier value is the matching tier award — `gold_award_cents`,
        `silver_award_cents`, `bronze_award_cents`, or zero for `NONE` — and the
        `standard_award_cents` is the smaller of the tier value and the cap, always
        stored for comparison."
        PRD §3.7: "Otherwise `applied_variant` is `STANDARD` and `award_cents`
        equals `standard_award_cents`."

        Design: Difficulty/combinatorial_formula/tier_attainment_multi_input_with_cap
        """
        _ctx, award = self._setup_silver_tobacco(api)
        assert award["applied_variant"] == "STANDARD"
        assert award["standard_award_cents"] == 30000, "min(silver 30000, cap 36000)"
        assert award["award_cents"] == award["standard_award_cents"]


class TestGoldTierBoundary:
    """Difficulty instance: exactly 3000 settled points (>= gold_threshold, not
    3001) attains GOLD; award clamps to the 36000 premium cap."""

    def _setup_gold(self, api):
        ctx = setup_active_enrollment()
        enr_id = ctx["enrollment"]["id"]
        add_settled_points(enr_id, 3000)
        submit_hra(enr_id, ctx["employee"]["id"], answers=[2] * 10)
        screening = create_screening(enr_id, ctx["employee"]["id"])
        resulted = result_screening(
            screening["id"], bmi=29.0, systolic_bp=139, total_cholesterol=199, glucose=110
        )
        compute_awards(ctx["program"]["id"])
        return ctx, resulted, get_enrollment_award(enr_id)

    def test_exact_3000_settled_attains_gold(self, api):
        """PRD §3.7: "The `tier` is `GOLD` when P reaches at least the program's
        `gold_threshold`, H is present, and B is at least 3..."
        PRD §3.7: "Every threshold comparison is inclusive — reaching the bar
        exactly attains the tier."

        Design: Difficulty/boundary_precision_check/gold_tier_at_exact_point_threshold
        """
        ctx, resulted, award = self._setup_gold(api)
        enr = validate_success(api.get_enrollment(ctx["enrollment"]["id"], BA), 200)
        assert enr["points_balance_settled"] == 3000, "exactly gold_threshold"
        assert resulted["targets_met"] == 3, "glucose 110 misses; the other three meet"
        assert award["tier"] == "GOLD"

    def test_gold_award_clamped_to_premium_cap(self, api):
        """PRD §3.7: "The cap is the program's `premium_cap_pct` multiplied by the
        employer's `annual_self_only_premium_cents`, rounded half-up to whole cents.
        ... the `standard_award_cents` is the smaller of the tier value and the
        cap..."

        Design: Difficulty/boundary_precision_check/gold_tier_at_exact_point_threshold
        """
        _ctx, _resulted, award = self._setup_gold(api)
        assert award["standard_award_cents"] == 36000, "min(gold 60000, cap 36000)"
        assert award["award_cents"] == 36000


class TestBronzeTierBoundary:
    def test_bronze_tier_exact_threshold(self, api):
        """PRD §3.7: "`BRONZE` when P reaches at least the `bronze_threshold`... Every
        threshold comparison is inclusive — reaching the bar exactly attains the
        tier."
        PRD §3.7: "The `net_annual_differential_cents` is the surcharge minus the
        award; a positive figure means the employee pays more."

        Design: Corner/calculations/bronze_tier_exact_threshold
        """
        ctx = setup_active_enrollment()
        enr_id = ctx["enrollment"]["id"]
        add_settled_points(enr_id, 500)
        compute_awards(ctx["program"]["id"])
        award = get_enrollment_award(enr_id)

        assert award["tier"] == "BRONZE", "P=500 >= bronze_threshold 500, no HRA needed"
        assert award["award_cents"] == 10000, "min(bronze 10000, cap 36000)"
        assert award["surcharge_cents"] == 0
        assert award["net_annual_differential_cents"] == -10000


class TestConfirmRequiresClosedProgram:
    """Difficulty instance: IncentiveAward -> WellnessProgram cross-entity state
    dependency on confirm."""

    def test_confirm_projected_award_while_active_rejected(self, api):
        """PRD §3.7: "Moving `PROJECTED → CONFIRMED` requires the program to be
        `CLOSED` (otherwise `ERR_PROGRAM_NOT_CLOSED`)..."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_closed_program
        """
        ctx = setup_active_enrollment()
        compute_awards(ctx["program"]["id"])
        award = get_enrollment_award(ctx["enrollment"]["id"])
        assert award["status"] == "PROJECTED"

        res = api.confirm_incentive_award(award["id"], BA)
        validate_error(res, ApiErrorId.ERR_PROGRAM_NOT_CLOSED, expected_status=409)

        awards = api.list_enrollment_incentive_awards(ctx["enrollment"]["id"], BA).json()
        assert awards["data"][0]["status"] == "PROJECTED", "award must be unchanged"

    def test_confirm_projected_award_after_close_succeeds(self, api):
        """PRD §3.7: "Moving `PROJECTED → CONFIRMED` requires the program to be
        `CLOSED` (otherwise `ERR_PROGRAM_NOT_CLOSED`) and the award's amounts to
        have been computed after the program's latest close..."
        PRD §3.7: "Confirmation stamps `confirmed_at` — null until this moment —
        with the current logical-clock instant and increments the award's `version`."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_closed_program
        """
        ctx = setup_active_enrollment()
        program_id = ctx["program"]["id"]
        validate_success(api.close_program(program_id, BA), 200)
        compute_awards(program_id)
        award = get_enrollment_award(ctx["enrollment"]["id"])
        assert award["confirmed_at"] is None

        confirmed = validate_success(api.confirm_incentive_award(award["id"], BA), 200)
        assert confirmed["status"] == "CONFIRMED"
        assert isinstance(confirmed["confirmed_at"], str) and confirmed["confirmed_at"]


class TestDisputeLoop:
    def test_dispute_after_appeal_window_rejected(self, api):
        """PRD §3.7: "The member — verified by matching the caller's `X-User-ID`
        against the award enrollment's `employee_id`, otherwise
        `ERR_OWNERSHIP_MISMATCH` — disputes with a required `dispute_reason`, but
        only while the logical clock reads no later than thirty days after
        `confirmed_at`; a later dispute is rejected with `ERR_APPEAL_WINDOW_CLOSED`."

        Design: Corner/errors/dispute_after_appeal_window_rejected
        """
        ctx = setup_confirmed_award()  # confirmed at the default clock 2026-05-01
        award = ctx["award"]
        assert award["status"] == "CONFIRMED"

        set_clock("2026-06-02T00:00:00Z")  # 31 days past the 2026-05-01 confirmation

        res = api.dispute_incentive_award(
            award["id"],
            {"dispute_reason": "late dispute"},
            make_employee_headers(ctx["employee"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED, expected_status=422)

        awards = api.list_enrollment_incentive_awards(ctx["enrollment"]["id"], BA).json()
        assert awards["data"][0]["status"] == "CONFIRMED", "award must be unchanged"

    def test_award_dispute_resolve_adjusted_branch(self, api):
        """PRD §3.7: "`ADJUSTED` requires `adjusted_award_cents` in the payload —
        omitting it is `ERR_INVALID_REQUEST` — and overwrites `award_cents` with
        that figure, recomputing `net_annual_differential_cents`. Either resolution
        refreshes `confirmed_at` to the current logical-clock instant, opening a
        fresh thirty-day dispute window, and increments the award's `version`."

        Design: Corner/endpoints/award_dispute_resolve_adjusted_branch
        """
        ctx = setup_confirmed_award()
        award = ctx["award"]

        disputed = validate_success(
            api.dispute_incentive_award(
                award["id"],
                {"dispute_reason": "points missing from april"},
                make_employee_headers(ctx["employee"]["id"]),
            ),
            200,
        )
        assert disputed["status"] == "DISPUTED"

        resolved = validate_success(
            api.resolve_incentive_award(
                award["id"], {"outcome": "ADJUSTED", "adjusted_award_cents": 12345}, BA
            ),
            200,
        )
        assert resolved["status"] == "CONFIRMED"
        assert resolved["award_cents"] == 12345
        assert resolved["net_annual_differential_cents"] == -12345, "0 - 12345"
