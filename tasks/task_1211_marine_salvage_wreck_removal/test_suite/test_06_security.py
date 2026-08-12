"""Security lodgement, activation gates (safety vs fiscal), and disbursement."""
from test_helpers import (
    ApiErrorId,
    assert_security_conservation,
    disburse_security,
    lodge_security,
    setup_active_contract,
    setup_signed_contract,
    validate_error,
    validate_success,
)


class TestSecurityExactCoverage:
    """Held exactly at the requirement passes the activation fiscal gate."""

    def _setup_signed_800m(self, api):
        return setup_signed_contract(casualty_overrides={
            "vessel_name": "MV Kara",
            "casualty_type": "SUNK",
            "declared_salved_value_cents": 800_000_000,
            "position": "32N 64W",
        })

    def test_exact_coverage_activates(self, api, contracts_officer_headers):
        """PRD 3.4: "The fiscal gate: some deposit of the contract must hold
        `held_cents` of at least the contract's `security_required_cents` —
        exact equality passes — or activation is rejected with
        `ERR_SECURITY_INSUFFICIENT`."

        Design: Difficulty/boundary_precision_check/security_exact_coverage_passes_activation
        """
        ctx = self._setup_signed_800m(api)
        assert ctx["contract"]["security_required_cents"] == 120_000_000
        lodge_security(ctx["contract"]["id"], 120_000_000)
        activated = validate_success(
            api.activate_contract(ctx["contract"]["id"], contracts_officer_headers), 200
        )
        assert activated["status"] == "ACTIVE", (
            "held 120,000,000 >= required 120,000,000 — exact equality passes"
        )

    def test_activation_does_not_consume_deposit(self, api, contracts_officer_headers):
        """PRD 3.4: "The deposit opens in `LODGED` with `held_cents` equal to
        the lodged amount and both `released_cents` and `applied_cents` at zero;
        the lodged figure is immutable thereafter, and the conservation
        invariant of §2.6 binds every later movement."

        Design: Difficulty/boundary_precision_check/security_exact_coverage_passes_activation
        """
        ctx = self._setup_signed_800m(api)
        deposit = lodge_security(ctx["contract"]["id"], 120_000_000)
        validate_success(
            api.activate_contract(ctx["contract"]["id"], contracts_officer_headers), 200
        )
        after = validate_success(
            api.get_security(deposit["id"], contracts_officer_headers), 200
        )
        assert after["held_cents"] == 120_000_000, "activation does not consume the deposit"
        assert after["status"] == "LODGED"
        assert_security_conservation(after)


class TestEnvClearanceBeatsSecurityShortfall:
    """At activation the safety gate is reported before the fiscal gate."""

    def _setup_double_failure(self):
        # TIER_3 assessment with no ENV_AGENCY permit (safety failure) AND
        # held 1,000,000 < required 7,500,000 (fiscal failure).
        ctx = setup_signed_contract(
            casualty_overrides={
                "vessel_name": "MV Pyro",
                "casualty_type": "FIRE",
                "declared_salved_value_cents": 50_000_000,
                "position": "36N 5W",
            },
            assessment_overrides={
                "pollution_risk_tier": "TIER_3",
                "wreck_removal_required": True,
                "estimated_cost_cents": 9_000_000,
            },
            plan_method="WRECK_REMOVAL",
            plan_classes=["CRANE_BARGE"],
            scopic_clause_included=True,
        )
        lodge_security(ctx["contract"]["id"], 1_000_000)
        return ctx

    def test_safety_error_returned_not_fiscal(self, api, contracts_officer_headers):
        """PRD 2.7: "This ordering is observable at contract activation: a
        contract that fails both its environmental clearance and its security
        coverage surfaces the safety rejection `ERR_ENV_CLEARANCE_REQUIRED`,
        never the fiscal one, because safety is reported before fiscal."

        Design: Difficulty/priority_pair_validation_conflict/contract_activate_env_clearance_beats_security_shortfall
        """
        ctx = self._setup_double_failure()
        res = api.activate_contract(ctx["contract"]["id"], contracts_officer_headers)
        validate_error(res, ApiErrorId.ERR_ENV_CLEARANCE_REQUIRED, expected_status=422)
        assert res.json()["data"]["error_id"] != "ERR_SECURITY_INSUFFICIENT"

    def test_figures_and_state_unchanged_after_rejection(self, api, contracts_officer_headers):
        """PRD 3.3: "for a `NO_CURE_NO_PAY` contract, `provisional_award_cents`
        is twelve percent of the casualty's `declared_salved_value_cents`,
        rounded half up to integer cents" and "`security_required_cents` is the
        provisional award multiplied by 1.25, rounded half up to integer cents".

        Design: Difficulty/priority_pair_validation_conflict/contract_activate_env_clearance_beats_security_shortfall
        """
        ctx = self._setup_double_failure()
        validate_error(
            api.activate_contract(ctx["contract"]["id"], contracts_officer_headers),
            ApiErrorId.ERR_ENV_CLEARANCE_REQUIRED,
            expected_status=422,
        )
        after = validate_success(
            api.get_contract(ctx["contract"]["id"], contracts_officer_headers), 200
        )
        assert after["status"] == "SIGNED", "rejection leaves the contract signed"
        assert after["provisional_award_cents"] == 6_000_000, "12% of 50,000,000"
        assert after["security_required_cents"] == 7_500_000, "6,000,000 x 1.25"


def test_contract_activate_security_shortfall_by_one_cent(api, contracts_officer_headers):
    """PRD 3.4: "The fiscal gate: some deposit of the contract must hold
    `held_cents` of at least the contract's `security_required_cents` — exact
    equality passes — or activation is rejected with
    `ERR_SECURITY_INSUFFICIENT`."

    Design: Corner/validations/contract_activate_security_shortfall_by_one_cent
    """
    ctx = setup_signed_contract(casualty_overrides={
        "vessel_name": "MV Kara",
        "casualty_type": "SUNK",
        "declared_salved_value_cents": 800_000_000,
        "position": "32N 64W",
    })
    assert ctx["contract"]["security_required_cents"] == 120_000_000
    lodge_security(ctx["contract"]["id"], 119_999_999)
    res = api.activate_contract(ctx["contract"]["id"], contracts_officer_headers)
    validate_error(res, ApiErrorId.ERR_SECURITY_INSUFFICIENT, expected_status=422)
    after = validate_success(api.get_contract(ctx["contract"]["id"], contracts_officer_headers), 200)
    assert after["status"] == "SIGNED"


def test_security_disburse_mode_not_allowed_rejected(api, contracts_officer_headers):
    """PRD 3.4: "A `RELEASE` returns funds to the owner and is allowed only when
    the contract is `SETTLED` or `TERMINATED`; an `APPLY_TO_AWARD` directs funds
    toward award payment and is allowed only when the contract's salvage award
    has reached `PAID`. Either mode attempted outside its lawful state is
    rejected with `ERR_SECURITY_DISBURSE_NOT_ALLOWED`."

    Design: Corner/validations/security_disburse_mode_not_allowed_rejected
    """
    ctx = setup_active_contract(casualty_overrides={"vessel_name": "MV Pax"})
    deposit = ctx["security"]
    res1 = api.disburse_security(
        deposit["id"], {"mode": "RELEASE", "amount_cents": 1_000_000},
        contracts_officer_headers,
    )
    validate_error(res1, ApiErrorId.ERR_SECURITY_DISBURSE_NOT_ALLOWED, expected_status=422)
    res2 = api.disburse_security(
        deposit["id"], {"mode": "APPLY_TO_AWARD", "amount_cents": 1_000_000},
        contracts_officer_headers,
    )
    validate_error(res2, ApiErrorId.ERR_SECURITY_DISBURSE_NOT_ALLOWED, expected_status=422)
    after = validate_success(api.get_security(deposit["id"], contracts_officer_headers), 200)
    assert after["held_cents"] == 30_000_000, "rejected disbursements move nothing"


def test_security_disburse_exceeds_held_rejected(api, contracts_officer_headers):
    """PRD 3.4: "The amount may not exceed the current `held_cents` — a
    disbursement that would drive `held_cents` negative is rejected with
    `ERR_SECURITY_DISBURSE_EXCEEDS_HELD`."

    Design: Corner/validations/security_disburse_exceeds_held_rejected
    """
    ctx = setup_signed_contract(
        form="FIXED_PRICE", fixed_price_cents=50_000_000,
        casualty_overrides={"vessel_name": "MV Pax"},
    )
    deposit = lodge_security(ctx["contract"]["id"], 20_000_000)
    validate_success(
        api.terminate_contract(ctx["contract"]["id"], {"reason": "MUTUAL"},
                               contracts_officer_headers),
        200,
    )
    res = api.disburse_security(
        deposit["id"], {"mode": "RELEASE", "amount_cents": 20_000_001},
        contracts_officer_headers,
    )
    validate_error(res, ApiErrorId.ERR_SECURITY_DISBURSE_EXCEEDS_HELD, expected_status=422)
    after = validate_success(api.get_security(deposit["id"], contracts_officer_headers), 200)
    assert after["held_cents"] == 20_000_000
    assert_security_conservation(after)


class TestSecurityReleaseConservation:
    """Forward releases across two calls keep the lodged total conserved."""

    def _setup_terminated_with_20m(self, api, contracts_officer_headers):
        ctx = setup_signed_contract(
            form="FIXED_PRICE", fixed_price_cents=50_000_000,
            casualty_overrides={"vessel_name": "MV Pax"},
        )
        assert ctx["contract"]["security_required_cents"] == 15_000_000
        deposit = lodge_security(ctx["contract"]["id"], 20_000_000)
        validate_success(
            api.terminate_contract(ctx["contract"]["id"], {"reason": "MUTUAL"},
                                   contracts_officer_headers),
            200,
        )
        return ctx, deposit

    def test_partial_release_moves_between_buckets(self, api, contracts_officer_headers):
        """PRD 3.4: "A disbursement smaller than the held balance leaves the
        deposit in `PARTIALLY_DISBURSED` (from either `LODGED` or a previous
        `PARTIALLY_DISBURSED`), moving the amount into `released_cents` or
        `applied_cents` according to the mode"
        PRD 2.6: "For security funds, a deposit's `lodged_amount_cents` always
        equals the sum of its `held_cents`, `released_cents`, and
        `applied_cents`"

        Design: Difficulty/compensating_invariant/security_release_converses_lodged_total
        """
        _, deposit = self._setup_terminated_with_20m(api, contracts_officer_headers)
        step1 = disburse_security(deposit["id"], "RELEASE", 8_000_000)
        assert step1["status"] == "PARTIALLY_DISBURSED"
        assert step1["held_cents"] == 12_000_000
        assert step1["released_cents"] == 8_000_000
        assert step1["applied_cents"] == 0
        assert_security_conservation(step1)

    def test_final_release_closes_deposit_with_lodged_pinned(self, api, contracts_officer_headers):
        """PRD 3.4: "a disbursement exactly equal to the held balance zeroes
        `held_cents`, credits the mode's bucket, and closes the deposit in
        `CLOSED`."
        PRD 2.6: "the lodged figure is fixed at creation and never changes
        thereafter, so forward disbursements and any compensating actions only
        move money between the three buckets."

        Design: Difficulty/compensating_invariant/security_release_converses_lodged_total
        """
        _, deposit = self._setup_terminated_with_20m(api, contracts_officer_headers)
        disburse_security(deposit["id"], "RELEASE", 8_000_000)
        step2 = disburse_security(deposit["id"], "RELEASE", 12_000_000)
        assert step2["status"] == "CLOSED"
        assert step2["held_cents"] == 0
        assert step2["released_cents"] == 20_000_000
        assert step2["applied_cents"] == 0
        assert step2["lodged_amount_cents"] == 20_000_000, "lodged never changes"
        assert_security_conservation(step2)
