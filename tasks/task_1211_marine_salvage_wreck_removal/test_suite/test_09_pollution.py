"""Pollution events: posture derivation, cascade A, special compensation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    book_charter,
    compute_award,
    get_success_data,
    register_asset,
    report_casualty,
    report_pollution_event,
    set_clock,
    setup_active_contract,
    setup_running_phase,
    setup_verified_lot,
    validate_error,
    validate_success,
)

TEST_SM = TEST_USERS["salvage_master_headers"]
TEST_ENV_HEADERS = TEST_USERS["environmental_officer_headers"]


class TestPollutionEscalationCascade:
    """Depth-3 cascade: event escalation -> posture -> phase -> charter."""

    def _setup_and_escalate(self, api, salvage_master_headers):
        ctx = setup_running_phase(casualty_overrides={
            "vessel_name": "MV Kara", "casualty_type": "SUNK",
            "declared_salved_value_cents": 800_000_000, "position": "32N 64W",
        })
        event = report_pollution_event(
            ctx["casualty"]["id"], pollutant_class="OIL_NON_PERSISTENT",
            tier="TIER_1", est_volume_m3=8,
        )
        escalated = validate_success(
            api.escalate_pollution_event(event["id"], {"new_tier": "TIER_2"},
                                         TEST_ENV_HEADERS),
            200,
        )
        return ctx, escalated

    def test_event_and_posture_and_phase_links(self, api, salvage_master_headers):
        """PRD 3.7: "Escalation raises the stakes: the officer supplies a
        `new_tier` that must be strictly higher than the event's current tier ...
        moving the event from `REPORTED` or `CONTAINED` to `ESCALATED`, updating
        its `tier`, and recomputing the posture with the full cascade."
        PRD 2.10: "Cascade A runs from pollution to operations: a pollution
        event change recomputes the casualty's environmental posture (link 1);
        the posture entering `ENV_HOLD` forces every `ACTIVE` operation phase of
        the casualty's contracts into `ENV_SUSPENDED` (link 2)"

        Design: Difficulty/transitive_cascade/pollution_escalation_posture_phase_charter_cascade
        """
        ctx, escalated = self._setup_and_escalate(api, salvage_master_headers)
        assert escalated["status"] == "ESCALATED"
        assert escalated["tier"] == "TIER_2"
        casualty = get_success_data(api.get_casualty(ctx["casualty"]["id"], salvage_master_headers))
        assert casualty["env_posture"] == "ENV_HOLD", "link 1: posture recomputed"
        phase = validate_success(api.get_phase(ctx["phase"]["id"], salvage_master_headers), 200)
        assert phase["status"] == "ENV_SUSPENDED", "link 2: active phase suspended"

    def test_charter_standby_link_and_contract_untouched(self, api, salvage_master_headers):
        """PRD 2.10: "and each suspended phase pushes its linked on-hire
        charters into `STANDBY_ENV` (link 3)."
        PRD 2.10 names only the posture, phases, and charters as cascade
        targets; the contract's negotiation/operating state is not among them.

        Design: Difficulty/transitive_cascade/pollution_escalation_posture_phase_charter_cascade
        """
        ctx, _ = self._setup_and_escalate(api, salvage_master_headers)
        charter = validate_success(
            api.get_charter(ctx["charter"]["id"], salvage_master_headers), 200
        )
        assert charter["status"] == "STANDBY_ENV", "link 3: on-hire charter stood down"
        contract = validate_success(
            api.get_contract(ctx["contract"]["id"], salvage_master_headers), 200
        )
        assert contract["status"] == "ACTIVE", "the cascade does not touch contract state"


class TestExposureTariffVsActual:
    """Provisional tariff exposure vs final actual-cost exposure."""

    def _setup_response(self):
        ctx = setup_active_contract(
            plan_classes=["TUG", "OIL_RESPONSE"],
            scopic_clause_included=True,
            casualty_overrides={
                "vessel_name": "MT Lir", "casualty_type": "GROUNDING",
                "declared_salved_value_cents": 800_000_000, "position": "51N 2E",
            },
        )
        asset = register_asset(
            asset_class="OIL_RESPONSE", day_rate_cents=2_000_000, max_hs_meters=3.00
        )
        set_clock("2026-05-11T00:00:00Z")
        event = report_pollution_event(
            ctx["casualty"]["id"], pollutant_class="OIL_PERSISTENT",
            tier="TIER_2", est_volume_m3=15,
        )
        charter = book_charter(
            ctx["casualty"]["id"], asset["id"],
            window_start="2026-05-11T00:00:00Z", window_end="2026-05-21T00:00:00Z",
            purpose="POLLUTION_RESPONSE", pollution_event_id=event["id"],
        )
        return ctx, event, charter

    def test_provisional_exposure_uses_booked_days_at_uplifted_tariff(
        self, api, salvage_master_headers
    ):
        """PRD 3.7: "whenever a response charter is booked, the event's
        `provisional_exposure_cents` becomes the sum, across the whole response
        set regardless of charter status, of each charter's uplifted daily rate
        — the asset's `day_rate_cents` multiplied by 1.25 and rounded half up to
        integer cents — multiplied by the charter's booked days."

        Design: Difficulty/dual_variant_calc/exposure_tariff_booked_vs_actual_verified
        """
        _, event, charter = self._setup_response()
        booked = get_success_data(api.get_pollution_event(event["id"], salvage_master_headers))
        assert booked["provisional_exposure_cents"] == 25_000_000, (
            "tariff 2,500,000 x 10 booked days"
        )
        # Run the charter: on-hire 05-11, off-hire 05-19 (8 active days).
        validate_success(api.on_hire_charter(charter["id"], salvage_master_headers), 200)
        set_clock("2026-05-19T00:00:00Z")
        off = validate_success(api.off_hire_charter(charter["id"], salvage_master_headers), 200)
        assert off["total_cost_cents"] == 16_000_000, "8 active days x 2,000,000"

    def test_final_exposure_uses_actual_cost_times_pollutant_multiplier(
        self, api, environmental_officer_headers, salvage_master_headers
    ):
        """PRD 3.7: "The final, actual-cost variant runs at verify-clean over
        the response charters that have reached `OFF_HIRE`: the sum of their
        `total_cost_cents` is multiplied by the pollutant multiplier — 1.5 for
        `OIL_PERSISTENT`"
        PRD 3.7: "otherwise it is simply the `final_exposure_cents`" (no award
        exists yet, so the payable is un-netted).

        Design: Difficulty/dual_variant_calc/exposure_tariff_booked_vs_actual_verified
        """
        _, event, charter = self._setup_response()
        # PRD 4: on-hire / off-hire are SalvageMaster actions.
        validate_success(api.on_hire_charter(charter["id"], salvage_master_headers), 200)
        set_clock("2026-05-19T00:00:00Z")
        validate_success(api.off_hire_charter(charter["id"], salvage_master_headers), 200)
        validate_success(api.contain_pollution_event(event["id"], environmental_officer_headers), 200)
        verified = validate_success(
            api.verify_clean_pollution_event(event["id"], environmental_officer_headers), 200
        )
        assert verified["status"] == "VERIFIED_CLEAN"
        assert verified["final_exposure_cents"] == 24_000_000, "16,000,000 x 1.5"
        assert verified["special_compensation_payable_cents"] == 24_000_000, (
            "no award exists, so payable is the un-netted final exposure"
        )
        assert verified["provisional_exposure_cents"] == 25_000_000
        assert verified["final_exposure_cents"] != verified["provisional_exposure_cents"], (
            "the two variants diverge when actual usage deviates from the booking"
        )


class TestScopicNettingAfterAward:
    """Netting is pinned after charter cost and after the final award."""

    def _setup_full(self, api):
        ctx = setup_running_phase(
            phase_duration_hours=336,
            plan_classes=["TUG", "OIL_RESPONSE"],
            scopic_clause_included=True,
            casualty_overrides={
                "vessel_name": "MV Kara", "casualty_type": "SUNK",
                "declared_salved_value_cents": 800_000_000, "position": "32N 64W",
            },
        )
        # Complete the operation phase (contract PERFORMANCE_COMPLETE).
        validate_success(api.complete_phase(ctx["phase"]["id"], TEST_SM), 200)
        # Pollution event plus a dedicated response charter (7 booked days).
        event = report_pollution_event(
            ctx["casualty"]["id"], pollutant_class="OIL_PERSISTENT",
            tier="TIER_2", est_volume_m3=40,
        )
        response_asset = register_asset(
            asset_class="OIL_RESPONSE", day_rate_cents=2_000_000, max_hs_meters=3.00
        )
        response_charter = book_charter(
            ctx["casualty"]["id"], response_asset["id"],
            window_start="2026-05-24T00:00:00Z", window_end="2026-05-31T00:00:00Z",
            purpose="POLLUTION_RESPONSE", pollution_event_id=event["id"],
        )
        set_clock("2026-05-24T00:00:00Z")
        validate_success(api.on_hire_charter(response_charter["id"], TEST_SM), 200)
        # Two verified lots totalling 800,000,000, then the award is computed.
        setup_verified_lot(ctx, quantity_tonnes=500, declared_value_cents=500_000_000,
                           site_capacity_tonnes=10_000)
        setup_verified_lot(ctx, property_type="VESSEL_HULL", quantity_tonnes=900,
                           declared_value_cents=300_000_000)
        award = compute_award(ctx["contract"]["id"])
        # Response charter off-hire 05-28 (4 active days = 8,000,000).
        set_clock("2026-05-28T00:00:00Z")
        off = validate_success(api.off_hire_charter(response_charter["id"], TEST_SM), 200)
        validate_success(api.contain_pollution_event(event["id"], TEST_ENV_HEADERS), 200)
        return ctx, event, award, off

    def test_award_computed_before_netting(self, api, environmental_officer_headers):
        """PRD 3.9: "The base award is tiered against that verified value in
        exact rational arithmetic: ten percent of the portion up to one hundred
        million cents, plus eight percent of the portion between one hundred
        million and five hundred million cents, plus six percent of any portion
        above five hundred million cents. The base is then enhanced by two
        additive multipliers: a risk addition keyed to the casualty's
        `casualty_type` ... fifteen percent for `SUNK` ... and an environment
        addition keyed to the highest `tier` over all pollution events of the
        casualty regardless of their status — ... ten percent for `TIER_2`"
        PRD 3.7: "Netting turns exposure into a payable amount, under a pinned
        evaluation order: charter costs are computed at each off-hire first, the
        final salvage award is computed second, and only then is special
        compensation netted"

        Design: Difficulty/combinatorial_formula/scopic_netting_after_award_pinned_order
        """
        _, event, award, off = self._setup_full(api)
        assert award["computed_amount_cents"] == 75_000_000, (
            "tiered base 60,000,000 x 1.25 (SUNK 0.15 + TIER_2 0.10)"
        )
        assert off["total_cost_cents"] == 8_000_000, "4 active days x 2,000,000"
        verified = validate_success(
            api.verify_clean_pollution_event(event["id"], environmental_officer_headers), 200
        )
        assert verified["final_exposure_cents"] == 12_000_000, "8,000,000 x 1.5"

    def test_payable_floors_at_zero_against_existing_award(
        self, api, environmental_officer_headers, salvage_master_headers
    ):
        """PRD 3.7: "When the contract's `scopic_clause_included` is true and a
        salvage award exists, `special_compensation_payable_cents` is the final
        exposure minus the award's `computed_amount_cents`, floored at zero"

        Design: Difficulty/combinatorial_formula/scopic_netting_after_award_pinned_order
        """
        _, event, award, _ = self._setup_full(api)
        assert award["computed_amount_cents"] == 75_000_000
        verified = validate_success(
            api.verify_clean_pollution_event(event["id"], environmental_officer_headers), 200
        )
        assert verified["special_compensation_payable_cents"] == 0, (
            "max(0, 12,000,000 - 75,000,000): netting applies because the award exists"
        )
        assert verified["provisional_exposure_cents"] == 17_500_000, (
            "tariff 2,500,000 x 7 booked days"
        )


def test_env_posture_contain_does_not_relax_hold(
    api, environmental_officer_headers, salvage_master_headers
):
    """PRD 3.7: "The posture derivation is a pure function of the casualty's
    open events — those in `REPORTED`, `ESCALATED`, or `CONTAINED`, containment
    still counting as open."
    PRD 3.7: "Leaving the hold is deliberately asymmetric: only verify-clean
    relaxes the posture ... Containment alone never relaxes anything."

    Design: Corner/calculations/env_posture_contain_does_not_relax_hold
    """
    casualty = report_casualty(
        vessel_name="MT Lir", casualty_type="GROUNDING",
        declared_salved_value_cents=800_000_000, position="51N 2E",
    )
    event = report_pollution_event(
        casualty["id"], pollutant_class="OIL_PERSISTENT", tier="TIER_2", est_volume_m3=15
    )
    contained = validate_success(
        api.contain_pollution_event(event["id"], environmental_officer_headers), 200
    )
    assert contained["status"] == "CONTAINED"
    posture1 = get_success_data(api.get_casualty(casualty["id"], salvage_master_headers))
    assert posture1["env_posture"] == "ENV_HOLD", "containment does not relax the hold"
    validate_success(api.verify_clean_pollution_event(event["id"], environmental_officer_headers), 200)
    posture2 = get_success_data(api.get_casualty(casualty["id"], salvage_master_headers))
    assert posture2["env_posture"] == "ENV_CLEAR", "verify-clean relaxes the posture"


def test_escalate_same_tier_rejected(api, environmental_officer_headers):
    """PRD 3.7: "the officer supplies a `new_tier` that must be strictly higher
    than the event's current tier — anything else is rejected with
    `ERR_POLLUTION_TIER_NOT_RAISED`"

    Design: Corner/validations/escalate_same_tier_rejected
    """
    casualty = report_casualty(vessel_name="MV Pax")
    event = report_pollution_event(
        casualty["id"], pollutant_class="DEBRIS", tier="TIER_1", est_volume_m3=2
    )
    res = api.escalate_pollution_event(
        event["id"], {"new_tier": "TIER_1"}, environmental_officer_headers
    )
    validate_error(res, ApiErrorId.ERR_POLLUTION_TIER_NOT_RAISED, expected_status=422)
    after = validate_success(
        api.get_pollution_event(event["id"], environmental_officer_headers), 200
    )
    assert after["status"] == "REPORTED"
    assert after["tier"] == "TIER_1"


def test_double_verify_clean_rejected(api, environmental_officer_headers):
    """PRD 3.7: "Verification of clean-up, from `CONTAINED`, moves the event to
    its terminal `VERIFIED_CLEAN`"
    PRD 2.7: "an action attempted on a resource already in a terminal state is
    rejected with `ERR_ALREADY_TERMINAL`"

    Design: Corner/state_machines/double_verify_clean_rejected
    """
    casualty = report_casualty(vessel_name="MV Pax")
    event = report_pollution_event(
        casualty["id"], pollutant_class="DEBRIS", tier="TIER_1", est_volume_m3=2
    )
    validate_success(api.contain_pollution_event(event["id"], environmental_officer_headers), 200)
    validate_success(api.verify_clean_pollution_event(event["id"], environmental_officer_headers), 200)
    res = api.verify_clean_pollution_event(event["id"], environmental_officer_headers)
    validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL, expected_status=409)


def test_exposure_input_set_excludes_salvage_charters(api, salvage_master_headers):
    """PRD 3.7: "Special compensation is accounted in two variants over the
    response set — the charters of the same casualty whose `purpose` is
    `POLLUTION_RESPONSE` and whose `pollution_event_id` names this event;
    `SALVAGE` charters never contribute."

    Design: Corner/calculations/exposure_input_set_excludes_salvage_charters
    """
    ctx = setup_active_contract(
        plan_classes=["TUG", "OIL_RESPONSE"],
        scopic_clause_included=True,
        casualty_overrides={
            "vessel_name": "MT Lir", "casualty_type": "GROUNDING",
            "declared_salved_value_cents": 800_000_000, "position": "51N 2E",
        },
    )
    tug = register_asset(asset_class="TUG", day_rate_cents=9_000_000, max_hs_meters=3.00)
    responder = register_asset(
        asset_class="OIL_RESPONSE", day_rate_cents=2_000_000, max_hs_meters=3.00
    )
    event = report_pollution_event(
        ctx["casualty"]["id"], pollutant_class="OIL_PERSISTENT",
        tier="TIER_2", est_volume_m3=15,
    )
    salvage_charter = book_charter(
        ctx["casualty"]["id"], tug["id"],
        window_start="2026-05-11T00:00:00Z", window_end="2026-05-16T00:00:00Z",
        purpose="SALVAGE",
    )
    book_charter(
        ctx["casualty"]["id"], responder["id"],
        window_start="2026-05-11T00:00:00Z", window_end="2026-05-15T00:00:00Z",
        purpose="POLLUTION_RESPONSE", pollution_event_id=event["id"],
    )
    after = get_success_data(api.get_pollution_event(event["id"], salvage_master_headers))
    assert after["provisional_exposure_cents"] == 10_000_000, (
        "only the response charter counts: 2,500,000 x 4 booked days; the "
        "9,000,000/day SALVAGE charter contributes 0"
    )
    assert salvage_charter["purpose"] == "SALVAGE"
