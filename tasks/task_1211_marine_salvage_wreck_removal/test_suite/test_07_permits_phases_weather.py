"""Phase activation gates: weather, permits, environmental posture, state."""
from test_helpers import (
    ApiErrorId,
    create_phase_activation_payload,
    get_success_data,
    grant_permit,
    report_pollution_event,
    setup_running_phase,
    setup_signed_contract,
    validate_error,
    validate_success,
)


class TestWaveHeightBoundary:
    """Inclusive boundary: forecast equal to the smallest asset limit passes."""

    def test_wave_height_equality_passes_activation(self, api, salvage_master_headers):
        """PRD 3.6: "The weather gate requires the named window to be `OPEN`;
        requires the window's `forecast_hs_meters` not to exceed the smallest
        `max_hs_meters` among the assets of the attached charters — an inclusive
        boundary, so a forecast exactly equal to the limit passes, and exceeding
        it yields `ERR_WEATHER_LIMIT_EXCEEDED`"

        Design: Difficulty/boundary_precision_check/wave_height_equality_passes_activation
        """
        ctx = setup_running_phase(
            phase_duration_hours=336, max_hs_meters=2.50, forecast_hs_meters=2.50,
            casualty_overrides={
                "vessel_name": "MV Kara", "casualty_type": "SUNK",
                "declared_salved_value_cents": 800_000_000, "position": "32N 64W",
            },
        )
        assert ctx["phase"]["status"] == "ACTIVE", (
            "forecast 2.50 <= asset max 2.50 — inclusive equality passes"
        )

    def test_first_activation_lifts_casualty_and_links_charter(
        self, api, salvage_master_headers
    ):
        """PRD 3.6: "Successful activation moves the phase from `PLANNED` to
        `ACTIVE`, stamps `activated_at` with the logical clock, stores the
        `weather_window_id` and `charter_ids` on the phase, writes the phase's
        identity into each charter's `linked_phase_id`, and — on the first
        activation of the contract — lifts the casualty from `CONTRACTED` to
        `IN_OPERATION`."

        Design: Difficulty/boundary_precision_check/wave_height_equality_passes_activation
        """
        ctx = setup_running_phase(
            phase_duration_hours=336, max_hs_meters=2.50, forecast_hs_meters=2.50,
            casualty_overrides={
                "vessel_name": "MV Kara", "casualty_type": "SUNK",
                "declared_salved_value_cents": 800_000_000, "position": "32N 64W",
            },
        )
        casualty = get_success_data(api.get_casualty(ctx["casualty"]["id"], salvage_master_headers))
        assert casualty["lifecycle_status"] == "IN_OPERATION"
        charter = get_success_data(api.get_charter(ctx["charter"]["id"], salvage_master_headers))
        assert charter["linked_phase_id"] == ctx["phase"]["id"]
        phase = ctx["phase"]
        assert phase["weather_window_id"] == ctx["window"]["id"]
        assert phase["charter_ids"] == [ctx["charter"]["id"]]
        assert phase["activated_at"] is not None


def test_wave_height_above_limit_rejected(api, salvage_master_headers):
    """PRD 3.6: "requires the window's `forecast_hs_meters` not to exceed the
    smallest `max_hs_meters` among the assets of the attached charters — an
    inclusive boundary, so a forecast exactly equal to the limit passes, and
    exceeding it yields `ERR_WEATHER_LIMIT_EXCEEDED`"

    Design: Corner/validations/wave_height_above_limit_rejected
    """
    ctx = setup_running_phase(
        activate=False, phase_duration_hours=336,
        max_hs_meters=2.50, forecast_hs_meters=2.51,
        casualty_overrides={
            "vessel_name": "MV Kara", "casualty_type": "SUNK",
            "declared_salved_value_cents": 800_000_000, "position": "32N 64W",
        },
    )
    res = api.activate_phase(
        ctx["phase"]["id"],
        create_phase_activation_payload(ctx["window"]["id"], [ctx["charter"]["id"]]),
        salvage_master_headers,
    )
    validate_error(res, ApiErrorId.ERR_WEATHER_LIMIT_EXCEEDED, expected_status=422)
    after = validate_success(api.get_phase(ctx["phase"]["id"], salvage_master_headers), 200)
    assert after["status"] == "PLANNED"


def test_weather_buffer_containment_rejected(api, salvage_master_headers):
    """PRD 3.6: "requires the plan to fit inside the window with a six-hour
    buffer at both ends — activation no earlier than six hours after the
    window's start, and the current time plus `planned_duration_hours` no later
    than six hours before the window's end, with equality at both buffer edges
    passing and any violation raising `ERR_WEATHER_WINDOW_INFEASIBLE`."

    Design: Corner/validations/weather_buffer_containment_rejected
    """
    # Window is only 72h long; a 96h plan plus the 6h end buffer cannot fit.
    ctx = setup_running_phase(
        activate=False, phase_duration_hours=96,
        max_hs_meters=3.00, forecast_hs_meters=1.00,
        weather_window=("2026-05-09T00:00:00Z", "2026-05-12T00:00:00Z"),
        casualty_overrides={
            "vessel_name": "MV Kara", "casualty_type": "SUNK",
            "declared_salved_value_cents": 800_000_000, "position": "32N 64W",
        },
    )
    res = api.activate_phase(
        ctx["phase"]["id"],
        create_phase_activation_payload(ctx["window"]["id"], [ctx["charter"]["id"]]),
        salvage_master_headers,
    )
    validate_error(res, ApiErrorId.ERR_WEATHER_WINDOW_INFEASIBLE, expected_status=422)


def test_permit_expired_by_clock_sweep_rejected(
    api, salvage_master_headers, operations_director_headers
):
    """PRD 2.4: "Advancing the clock triggers an automatic expiry sweep at the
    new time: every Permit whose status is `GRANTED`, `SUSPENDED`, or
    `REQUESTED` and whose `valid_to` is strictly earlier than the new time
    transitions to `EXPIRED`"
    PRD 3.5: "A permit swept to `EXPIRED` by the clock fails this validity check
    like any other out-of-window permit."

    Design: Corner/validations/permit_expired_by_clock_sweep_rejected
    """
    ctx = setup_running_phase(
        activate=False, phase_duration_hours=24,
        max_hs_meters=3.00, forecast_hs_meters=1.00,
        permit_valid_to="2026-05-15T00:00:00Z",
        casualty_overrides={
            "vessel_name": "MV Kara", "casualty_type": "SUNK",
            "declared_salved_value_cents": 800_000_000, "position": "32N 64W",
        },
    )
    permit = ctx["permits"]["COAST_GUARD"]
    sweep = api.set_clock(
        {"to_iso8601": "2026-05-16T00:00:00Z"}, operations_director_headers
    )
    sweep_data = get_success_data(sweep)
    assert permit["id"] in sweep_data["expired_permit_ids"], (
        "the sweep reports the GRANTED permit passing valid_to"
    )
    res = api.activate_phase(
        ctx["phase"]["id"],
        create_phase_activation_payload(ctx["window"]["id"], [ctx["charter"]["id"]]),
        salvage_master_headers,
    )
    validate_error(res, ApiErrorId.ERR_PERMIT_NOT_VALID, expected_status=422)
    after = validate_success(api.get_phase(ctx["phase"]["id"], salvage_master_headers), 200)
    assert after["status"] == "PLANNED"


def test_permit_suspend_reinstate_cycle_gates_activation(
    api, salvage_master_headers, environmental_officer_headers
):
    """PRD 3.5: "Granting moves a permit from `REQUESTED` to `GRANTED`;
    suspension moves it from `GRANTED` to `SUSPENDED`; reinstatement returns it
    from `SUSPENDED` to `GRANTED`, and the grant–suspend loop may repeat as
    agencies revisit conditions."
    PRD 3.5: "For each required agency, a permit of that type in `GRANTED`
    status must exist for the casualty — its absence is `ERR_PERMIT_MISSING`"

    Design: Corner/validations/permit_suspend_reinstate_cycle_gates_activation
    """
    ctx = setup_running_phase(activate=False)
    permit = ctx["permits"]["COAST_GUARD"]
    suspended = validate_success(
        api.suspend_permit(permit["id"], environmental_officer_headers), 200
    )
    assert suspended["status"] == "SUSPENDED"

    res = api.activate_phase(
        ctx["phase"]["id"],
        create_phase_activation_payload(ctx["window"]["id"], [ctx["charter"]["id"]]),
        salvage_master_headers,
    )
    validate_error(res, ApiErrorId.ERR_PERMIT_MISSING, expected_status=422)

    reinstated = validate_success(
        api.reinstate_permit(permit["id"], environmental_officer_headers), 200
    )
    assert reinstated["status"] == "GRANTED"
    activated = validate_success(
        api.activate_phase(
            ctx["phase"]["id"],
            create_phase_activation_payload(ctx["window"]["id"], [ctx["charter"]["id"]]),
            salvage_master_headers,
        ),
        200,
    )
    assert activated["status"] == "ACTIVE"


def test_env_hold_blocks_clean_phase_activation(api, salvage_master_headers):
    """PRD 3.6: "The environmental gate rejects with `ERR_ENV_HOLD_ACTIVE` when
    the casualty's `env_posture` is `ENV_HOLD`."
    PRD 3.7: "If any open event carries tier `TIER_2` or `TIER_3`, the posture
    is `ENV_HOLD`"

    Design: Corner/validations/env_hold_blocks_clean_phase_activation
    """
    ctx = setup_running_phase(activate=False)
    # Every other gate (charter ON_HIRE, feasible window, granted permit) holds;
    # only the environmental posture blocks this activation.
    report_pollution_event(
        ctx["casualty"]["id"], pollutant_class="OIL_PERSISTENT",
        tier="TIER_2", est_volume_m3=25,
    )
    casualty = get_success_data(api.get_casualty(ctx["casualty"]["id"], salvage_master_headers))
    assert casualty["env_posture"] == "ENV_HOLD"
    res = api.activate_phase(
        ctx["phase"]["id"],
        create_phase_activation_payload(ctx["window"]["id"], [ctx["charter"]["id"]]),
        salvage_master_headers,
    )
    validate_error(res, ApiErrorId.ERR_ENV_HOLD_ACTIVE, expected_status=422)
    after = validate_success(api.get_phase(ctx["phase"]["id"], salvage_master_headers), 200)
    assert after["status"] == "PLANNED"


class TestStateErrorBeatsEnvHold:
    """A phase in WEATHER_HOLD activated during ENV_HOLD violates the state
    tier and the safety tier; the state error is reported."""

    def _setup(self, api, salvage_master_headers):
        ctx = setup_running_phase()
        held = validate_success(api.hold_weather_phase(ctx["phase"]["id"], salvage_master_headers), 200)
        assert held["status"] == "WEATHER_HOLD"
        # The environmental cascade only touches ACTIVE phases, so this phase
        # stays WEATHER_HOLD while the casualty enters ENV_HOLD.
        report_pollution_event(
            ctx["casualty"]["id"], pollutant_class="OIL_PERSISTENT",
            tier="TIER_2", est_volume_m3=25,
        )
        return ctx

    def test_state_error_returned_not_env_hold(self, api, salvage_master_headers):
        """PRD 2.7: "Every request passes through a fixed pipeline of validation
        tiers, evaluated in ascending priority order, so that an earlier failure
        masks later checks on the same request. The order is normative."
        PRD 2.7: "Priority 5 covers state permission: an action whose target is
        in the wrong from-state is rejected with `ERR_INVALID_STATE_TRANSITION`"

        Design: Difficulty/priority_pair_validation_conflict/phase_activate_state_error_beats_env_hold
        """
        ctx = self._setup(api, salvage_master_headers)
        casualty = get_success_data(api.get_casualty(ctx["casualty"]["id"], salvage_master_headers))
        assert casualty["env_posture"] == "ENV_HOLD"
        res = api.activate_phase(
            ctx["phase"]["id"],
            create_phase_activation_payload(ctx["window"]["id"], [ctx["charter"]["id"]]),
            salvage_master_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
        assert res.json()["data"]["error_id"] != "ERR_ENV_HOLD_ACTIVE"

    def test_rejection_fires_no_side_effects(self, api, salvage_master_headers):
        """PRD 2.7: "an earlier failure masks later checks on the same request."
        PRD 3.6: "Successful activation moves the phase from `PLANNED` to
        `ACTIVE`" — a rejected activation performs none of this.

        Design: Difficulty/priority_pair_validation_conflict/phase_activate_state_error_beats_env_hold
        """
        ctx = self._setup(api, salvage_master_headers)
        api.activate_phase(
            ctx["phase"]["id"],
            create_phase_activation_payload(ctx["window"]["id"], [ctx["charter"]["id"]]),
            salvage_master_headers,
        )
        phase = validate_success(api.get_phase(ctx["phase"]["id"], salvage_master_headers), 200)
        assert phase["status"] == "WEATHER_HOLD", "the rejected activation changes nothing"
        casualty = get_success_data(api.get_casualty(ctx["casualty"]["id"], salvage_master_headers))
        assert casualty["env_posture"] == "ENV_HOLD"


class TestWreckRemovalPermitDependency:
    """WRECK_REMOVAL activation depends on permits owned by another workflow."""

    def _setup(self):
        return setup_running_phase(
            activate=False, phase_type="WRECK_REMOVAL", phase_duration_hours=96,
            asset_class="CRANE_BARGE", day_rate_cents=4_000_000, max_hs_meters=2.00,
            forecast_hs_meters=1.50,
            permit_agencies=["COAST_GUARD"],  # ENV_AGENCY deliberately absent
            plan_method="WRECK_REMOVAL", plan_classes=["CRANE_BARGE"],
            assessment_overrides={"wreck_removal_required": True},
            casualty_overrides={
                "vessel_name": "MV Kara", "casualty_type": "SUNK",
                "declared_salved_value_cents": 800_000_000, "position": "32N 64W",
            },
        )

    def test_missing_env_agency_permit_blocks_activation(self, api, salvage_master_headers):
        """PRD 3.5: "Permits become operational gates at phase activation, where
        the required agencies depend on the phase type: ... `WRECK_REMOVAL`
        requires both `COAST_GUARD` and `ENV_AGENCY`" and "For each required
        agency, a permit of that type in `GRANTED` status must exist for the
        casualty — its absence is `ERR_PERMIT_MISSING`"

        Design: Difficulty/cross_entity_state_dependency/wreck_removal_requires_both_agency_permits
        """
        ctx = self._setup()
        res = api.activate_phase(
            ctx["phase"]["id"],
            create_phase_activation_payload(ctx["window"]["id"], [ctx["charter"]["id"]]),
            salvage_master_headers,
        )
        validate_error(res, ApiErrorId.ERR_PERMIT_MISSING, expected_status=422)
        after = validate_success(api.get_phase(ctx["phase"]["id"], salvage_master_headers), 200)
        assert after["status"] == "PLANNED", "the phase is unmoved by the rejection"

    def test_activation_succeeds_after_env_agency_grant(self, api, salvage_master_headers):
        """PRD 3.5: "`WRECK_REMOVAL` requires both `COAST_GUARD` and
        `ENV_AGENCY`" and "a permit of that type in `GRANTED` status must exist
        for the casualty"

        Design: Difficulty/cross_entity_state_dependency/wreck_removal_requires_both_agency_permits
        """
        ctx = self._setup()
        validate_error(
            api.activate_phase(
                ctx["phase"]["id"],
                create_phase_activation_payload(ctx["window"]["id"], [ctx["charter"]["id"]]),
                salvage_master_headers,
            ),
            ApiErrorId.ERR_PERMIT_MISSING,
            expected_status=422,
        )
        grant_permit(ctx["casualty"]["id"], "ENV_AGENCY")
        activated = validate_success(
            api.activate_phase(
                ctx["phase"]["id"],
                create_phase_activation_payload(ctx["window"]["id"], [ctx["charter"]["id"]]),
                salvage_master_headers,
            ),
            200,
        )
        assert activated["status"] == "ACTIVE"


def test_phase_create_requires_active_contract(api, salvage_master_headers):
    """PRD 3.6: "A `SalvageMaster` creates a phase under an `ACTIVE` contract
    (`ERR_CONTRACT_NOT_ACTIVE` otherwise)"

    Design: Corner/validations/phase_create_requires_active_contract
    """
    ctx = setup_signed_contract(casualty_overrides={"vessel_name": "MV Pax"})
    assert ctx["contract"]["status"] == "SIGNED"
    res = api.create_phase(
        {"contract_id": ctx["contract"]["id"], "phase_type": "REFLOAT",
         "planned_duration_hours": 96},
        salvage_master_headers,
    )
    validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE, expected_status=422)


def test_phase_complete_from_planned_rejected(api, salvage_master_headers):
    """PRD 3.6: "An `ACTIVE` phase completes on the master's completion action"
    PRD 2.7: "Priority 5 covers state permission: an action whose target is in
    the wrong from-state is rejected with `ERR_INVALID_STATE_TRANSITION`"

    Design: Corner/state_machines/phase_complete_from_planned_rejected
    """
    ctx = setup_running_phase(activate=False)
    assert ctx["phase"]["status"] == "PLANNED"
    res = api.complete_phase(ctx["phase"]["id"], salvage_master_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)
    contract = validate_success(api.get_contract(ctx["contract"]["id"], salvage_master_headers), 200)
    assert contract["status"] == "ACTIVE", "no completion bubble fires"
