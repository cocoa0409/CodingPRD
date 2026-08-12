"""Salvage awards: provisional vs final math, arbitration, completion cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_salvage_award,
    compute_award,
    create_phase_activation_payload,
    create_phase_payload,
    get_success_data,
    grant_permit,
    log_property,
    report_pollution_event,
    setup_completed_operation,
    setup_running_phase,
    setup_signed_contract,
    setup_verified_lot,
    validate_error,
    validate_paginated,
    validate_success,
)

TEST_SM = TEST_USERS["salvage_master_headers"]


class TestProvisionalVsFinalAward:
    """Two valid algorithms on the same data: flat provisional vs tiered final."""

    def test_sign_computes_flat_provisional_and_security(self, api):
        """PRD 3.3: "for a `NO_CURE_NO_PAY` contract, `provisional_award_cents`
        is twelve percent of the casualty's `declared_salved_value_cents`,
        rounded half up to integer cents"
        PRD 3.3: "for a `NO_CURE_NO_PAY` contract, `security_required_cents` is
        the provisional award multiplied by 1.25, rounded half up to integer
        cents"

        Design: Difficulty/dual_variant_calc/award_provisional_flat_vs_final_tiered_enhanced
        """
        ctx = setup_signed_contract(
            scopic_clause_included=True,
            casualty_overrides={
                "vessel_name": "MV Kara", "casualty_type": "SUNK",
                "declared_salved_value_cents": 800_000_000, "position": "32N 64W",
            },
        )
        contract = ctx["contract"]
        assert contract["status"] == "SIGNED"
        assert contract["provisional_award_cents"] == 96_000_000, (
            "flat 12% of declared 800,000,000"
        )
        assert contract["security_required_cents"] == 120_000_000, "96,000,000 x 1.25"

    def test_final_award_tiered_enhanced_diverges(self, api, contracts_officer_headers):
        """PRD 3.9: "The base award is tiered against that verified value in
        exact rational arithmetic: ten percent of the portion up to one hundred
        million cents, plus eight percent of the portion between one hundred
        million and five hundred million cents, plus six percent of any portion
        above five hundred million cents. The base is then enhanced by two
        additive multipliers: a risk addition keyed to the casualty's
        `casualty_type` — ... fifteen percent for `SUNK` — and an environment
        addition keyed to the highest `tier` over all pollution events of the
        casualty regardless of their status — ... ten percent for `TIER_2`"
        PRD 3.9: "On identical declared-versus-verified data the final figure
        still diverges from the provisional one, because twelve percent flat is
        not the tiered-and-multiplied schedule."

        Design: Difficulty/dual_variant_calc/award_provisional_flat_vs_final_tiered_enhanced
        """
        ctx = setup_completed_operation(
            phase_duration_hours=336,
            scopic_clause_included=True,
            casualty_overrides={
                "vessel_name": "MV Kara", "casualty_type": "SUNK",
                "declared_salved_value_cents": 800_000_000, "position": "32N 64W",
            },
        )
        assert ctx["contract"]["provisional_award_cents"] == 96_000_000
        assert ctx["contract"]["security_required_cents"] == 120_000_000
        report_pollution_event(
            ctx["casualty"]["id"], pollutant_class="OIL_PERSISTENT",
            tier="TIER_2", est_volume_m3=40,
        )
        setup_verified_lot(ctx, quantity_tonnes=500, declared_value_cents=500_000_000,
                           site_capacity_tonnes=10_000)
        setup_verified_lot(ctx, property_type="VESSEL_HULL", quantity_tonnes=900,
                           declared_value_cents=300_000_000)
        award = compute_award(ctx["contract"]["id"])
        assert_salvage_award(award)
        assert award["status"] == "COMPUTED"
        # base 10M + 32M + 18M = 60M; x(1 + 0.15 SUNK + 0.10 TIER_2) = 75M.
        assert award["computed_amount_cents"] == 75_000_000
        assert award["computed_amount_cents"] != 96_000_000, (
            "final diverges from provisional on identical declared==verified data"
        )


class TestTierStraddleWithEnhancement:
    """A verified value straddling all three tiers with conditional additions."""

    def test_computed_amount_straddles_all_tiers(self, api, contracts_officer_headers):
        """PRD 3.9: "ten percent of the portion up to one hundred million cents,
        plus eight percent of the portion between one hundred million and five
        hundred million cents, plus six percent of any portion above five
        hundred million cents" enhanced by "eight percent for `COLLISION`" and
        "five percent for `TIER_1`", and "the final `computed_amount_cents` is
        the lesser of the enhanced figure and the verified value — the cap
        applied after rounding."

        Design: Difficulty/combinatorial_formula/article13_tier_straddle_with_conditional_enhancement
        """
        ctx = setup_completed_operation(
            phase_type="TOWAGE", phase_duration_hours=168,
            day_rate_cents=1_500_000, max_hs_meters=3.00, forecast_hs_meters=1.50,
            casualty_overrides={
                "vessel_name": "SV Norr", "casualty_type": "COLLISION",
                "declared_salved_value_cents": 600_000_000, "position": "58N 11E",
            },
            assessment_overrides={"estimated_cost_cents": 4_000_000},
        )
        report_pollution_event(
            ctx["casualty"]["id"], pollutant_class="DEBRIS", tier="TIER_1",
            est_volume_m3=5,
        )
        setup_verified_lot(ctx, quantity_tonnes=400, declared_value_cents=600_000_000,
                           site_capacity_tonnes=5_000)
        award = compute_award(ctx["contract"]["id"])
        # base = 10M + 32M + 6M = 48M; x(1 + 0.08 + 0.05) = 54,240,000; cap not binding.
        assert award["computed_amount_cents"] == 54_240_000

    def test_provisional_flat_at_sign_for_same_value(self, api):
        """PRD 3.3: "for a `NO_CURE_NO_PAY` contract, `provisional_award_cents`
        is twelve percent of the casualty's `declared_salved_value_cents`,
        rounded half up to integer cents"
        PRD 3.3: "The provisional figure deliberately ignores tiers, risk,
        pollution, and verification — it exists to size the security demand."

        Design: Difficulty/combinatorial_formula/article13_tier_straddle_with_conditional_enhancement
        """
        ctx = setup_signed_contract(casualty_overrides={
            "vessel_name": "SV Norr", "casualty_type": "COLLISION",
            "declared_salved_value_cents": 600_000_000, "position": "58N 11E",
        })
        assert ctx["contract"]["provisional_award_cents"] == 72_000_000, (
            "flat 12% of 600,000,000"
        )


def test_article13_tier1_exact_boundary(api, contracts_officer_headers):
    """PRD 3.9: "ten percent of the portion up to one hundred million cents" —
    a verified value of exactly one hundred million cents lies entirely in the
    first tier; enhanced by "five percent for `GROUNDING`" and "zero when the
    casualty has no events".

    Design: Corner/calculations/article13_tier1_exact_boundary
    """
    ctx = setup_completed_operation(casualty_overrides={
        "vessel_name": "MV Pax", "casualty_type": "GROUNDING",
        "declared_salved_value_cents": 100_000_000, "position": "10S 140W",
    })
    setup_verified_lot(ctx, quantity_tonnes=100, declared_value_cents=100_000_000,
                       site_capacity_tonnes=10_000)
    award = compute_award(ctx["contract"]["id"])
    # base = 10,000,000 (all in tier 1); x(1 + 0.05 + 0) = 10,500,000.
    assert award["computed_amount_cents"] == 10_500_000


class TestArbitrationBlockedUntilLotsTerminal:
    """Submit-arbitration reads another aggregate's custody states."""

    def _setup(self):
        ctx = setup_completed_operation(casualty_overrides={
            "vessel_name": "MV Kara", "casualty_type": "SUNK",
            "declared_salved_value_cents": 800_000_000, "position": "32N 64W",
        })
        lot = setup_verified_lot(ctx, quantity_tonnes=500,
                                 declared_value_cents=800_000_000,
                                 site_capacity_tonnes=10_000)
        award = compute_award(ctx["contract"]["id"])
        return ctx, lot, award

    def test_submit_blocked_while_lot_secured(self, api, contracts_officer_headers):
        """PRD 3.9: "or refer the award to arbitration, moving it from
        `COMPUTED` to `IN_ARBITRATION` — a referral lawful only when every lot
        of the casualty sits in terminal custody (`REDELIVERED`, `SOLD`, or
        `DISPOSED`), otherwise `ERR_PROPERTIES_NOT_DISPOSED`."

        Design: Difficulty/cross_entity_state_dependency/arbitration_blocked_until_all_lots_terminal
        """
        _, lot, award = self._setup()
        assert lot["custody_status"] == "SECURED_ASHORE", "secured is not terminal"
        res = api.submit_arbitration_award(award["id"], contracts_officer_headers)
        validate_error(res, ApiErrorId.ERR_PROPERTIES_NOT_DISPOSED, expected_status=422)
        after = validate_success(api.get_award(award["id"], contracts_officer_headers), 200)
        assert after["status"] == "COMPUTED"

    def test_submit_succeeds_after_terminal_disposition(
        self, api, contracts_officer_headers, salvage_master_headers
    ):
        """PRD 3.9: "a referral lawful only when every lot of the casualty sits
        in terminal custody (`REDELIVERED`, `SOLD`, or `DISPOSED`)"
        PRD 3.8: "the lot reaches terminal custody exactly when a dispose call
        zeroes `in_custody_tonnes`, and the terminal state takes the method of
        that zeroing call"

        Design: Difficulty/cross_entity_state_dependency/arbitration_blocked_until_all_lots_terminal
        """
        _, lot, award = self._setup()
        disposed = validate_success(
            api.dispose_property(lot["id"], {"method": "REDELIVER", "tonnes": 500},
                                 salvage_master_headers),
            200,
        )
        assert disposed["custody_status"] == "REDELIVERED"
        assert disposed["in_custody_tonnes"] == 0
        referred = validate_success(
            api.submit_arbitration_award(award["id"], contracts_officer_headers), 200
        )
        assert referred["status"] == "IN_ARBITRATION"


class TestFinalPhaseCompletionBubble:
    """Cascade B: the final phase completion bubbles contract then casualty."""

    def _setup_two_phases(self, api, salvage_master_headers):
        ctx = setup_running_phase(casualty_overrides={"vessel_name": "MV Pax"})
        grant_permit(ctx["casualty"]["id"], "PORT_AUTHORITY")
        ph2 = get_success_data(
            api.create_phase(
                create_phase_payload(
                    ctx["contract"]["id"], phase_type="DEMOBILIZATION",
                    planned_duration_hours=24,
                ),
                salvage_master_headers,
            )
        )
        ph2 = get_success_data(
            api.activate_phase(
                ph2["id"],
                create_phase_activation_payload(ctx["window"]["id"], [ctx["charter"]["id"]]),
                salvage_master_headers,
            )
        )
        return ctx, ph2

    def test_first_of_two_completions_leaves_contract_active(
        self, api, salvage_master_headers
    ):
        """PRD 3.6: "that completion fires cascade B of §2.10: when the
        completing phase leaves every phase of the contract in a terminal state
        — `COMPLETE` or `ABORTED` — with at least one phase existing, the
        contract moves from `ACTIVE` to `PERFORMANCE_COMPLETE`"

        Design: Difficulty/transitive_cascade/final_phase_completion_contract_casualty_bubble
        """
        ctx, _ = self._setup_two_phases(api, salvage_master_headers)
        completed = validate_success(
            api.complete_phase(ctx["phase"]["id"], salvage_master_headers), 200
        )
        assert completed["status"] == "COMPLETE"
        contract = validate_success(
            api.get_contract(ctx["contract"]["id"], salvage_master_headers), 200
        )
        assert contract["status"] == "ACTIVE", (
            "aggregate gate unsatisfied: the second phase is still running"
        )

    def test_final_completion_bubbles_to_performance_complete(
        self, api, salvage_master_headers
    ):
        """PRD 2.10: "Cascade B runs from operations upward: when a phase
        completion leaves every phase of a contract in a terminal state, the
        contract moves from `ACTIVE` to `PERFORMANCE_COMPLETE` (link 1), and
        that in turn moves the casualty from `IN_OPERATION` to
        `OPERATIONS_COMPLETE` (link 2), which is the gate that makes recovered
        property disposition-eligible."

        Design: Difficulty/transitive_cascade/final_phase_completion_contract_casualty_bubble
        """
        ctx, ph2 = self._setup_two_phases(api, salvage_master_headers)
        validate_success(api.complete_phase(ctx["phase"]["id"], salvage_master_headers), 200)
        completed2 = validate_success(api.complete_phase(ph2["id"], salvage_master_headers), 200)
        assert completed2["status"] == "COMPLETE"
        contract = validate_success(
            api.get_contract(ctx["contract"]["id"], salvage_master_headers), 200
        )
        assert contract["status"] == "PERFORMANCE_COMPLETE", "link 1"
        casualty = get_success_data(api.get_casualty(ctx["casualty"]["id"], salvage_master_headers))
        assert casualty["lifecycle_status"] == "OPERATIONS_COMPLETE", "link 2"


def test_award_compute_requires_verified_lots_rejected(api, contracts_officer_headers):
    """PRD 3.9: "A `ContractsOfficer` creates the contract's salvage award ...
    which requires the contract to be in `PERFORMANCE_COMPLETE`
    (`ERR_CONTRACT_NOT_ACTIVE` otherwise) and every recovered lot of the
    casualty to be `VALUE_VERIFIED`, a single unverified lot blocking
    computation with `ERR_PROPERTIES_NOT_VERIFIED`."

    Design: Corner/validations/award_compute_requires_verified_lots_rejected
    """
    ctx = setup_completed_operation(casualty_overrides={"vessel_name": "MV Pax"})
    # Lot logged but never surveyed: documentation stays PENDING_SURVEY.
    log_property(ctx["casualty"]["id"], property_type="CARGO",
                 quantity_tonnes=50, declared_value_cents=9_000_000)
    res = api.create_award(ctx["contract"]["id"], contracts_officer_headers)
    validate_error(res, ApiErrorId.ERR_PROPERTIES_NOT_VERIFIED, expected_status=422)
    listed, _ = validate_paginated(
        api.list_awards(contracts_officer_headers, params={"contract_id": ctx["contract"]["id"]})
    )
    assert listed == [], "no award is created"


def test_award_already_exists_rejected(api, contracts_officer_headers):
    """PRD 3.9: "A `ContractsOfficer` creates the contract's salvage award — one
    award per contract, a second attempt rejected with
    `ERR_AWARD_ALREADY_EXISTS`"

    Design: Corner/validations/award_already_exists_rejected
    """
    ctx = setup_completed_operation(casualty_overrides={"vessel_name": "MV Pax"})
    setup_verified_lot(ctx, quantity_tonnes=50, declared_value_cents=200_000_000)
    award = compute_award(ctx["contract"]["id"])
    assert award["status"] == "COMPUTED"
    res = api.create_award(ctx["contract"]["id"], contracts_officer_headers)
    validate_error(res, ApiErrorId.ERR_AWARD_ALREADY_EXISTS, expected_status=409)
    after = validate_success(api.get_award(award["id"], contracts_officer_headers), 200)
    assert after["status"] == "COMPUTED"


def test_award_arbitration_appeal_decide_cycle(
    api, contracts_officer_headers, arbitrator_headers
):
    """PRD 3.9: "In arbitration the `Arbitrator` publishes an award by supplying
    `awarded_amount_cents`, moving the award from `IN_ARBITRATION` to `AWARDED`.
    The `ContractsOfficer` may appeal with the stated `grounds`, moving the
    award from `AWARDED` to `APPEALED` and incrementing `appeal_count` by 1; a
    further arbitral decision returns the award from `APPEALED` to `AWARDED`,
    overwriting `awarded_amount_cents` with the new decision, and this appeal
    loop may repeat."

    Design: Corner/validations/award_arbitration_appeal_decide_cycle
    """
    ctx = setup_completed_operation(casualty_overrides={"vessel_name": "MV Pax"})
    lot = setup_verified_lot(ctx, quantity_tonnes=50, declared_value_cents=200_000_000)
    # Terminal custody so the award can be referred to arbitration.
    validate_success(
        api.dispose_property(lot["id"], {"method": "REDELIVER", "tonnes": 50},
                             TEST_SM),
        200,
    )
    award = compute_award(ctx["contract"]["id"])
    validate_success(api.submit_arbitration_award(award["id"], contracts_officer_headers), 200)

    decided = validate_success(
        api.decide_award(award["id"], {"awarded_amount_cents": 20_000_000},
                         arbitrator_headers),
        200,
    )
    assert decided["status"] == "AWARDED"
    assert decided["awarded_amount_cents"] == 20_000_000

    appealed = validate_success(
        api.appeal_award(award["id"], {"grounds": "criteria weighting error"},
                         contracts_officer_headers),
        200,
    )
    assert appealed["status"] == "APPEALED"
    assert appealed["appeal_count"] == 1

    redecided = validate_success(
        api.decide_award(award["id"], {"awarded_amount_cents": 19_000_000},
                         arbitrator_headers),
        200,
    )
    assert redecided["status"] == "AWARDED"
    assert redecided["awarded_amount_cents"] == 19_000_000, "the new decision overwrites"
    assert redecided["appeal_count"] == 1, "appeal_count does not reset"
