"""Playbook lifecycle: capacity testing, SoD approval, posture-gated
activation, mutual exclusion, execution, settlement, closure, revision.

Difficulty instances: playbook_stood_down_revision_cycle,
single_active_playbook_mutual_exclusion,
activate_draft_playbook_state_beats_posture_gate,
playbook_activation_gated_by_current_posture.
Corner instances: capacity_test_failure_keeps_draft_with_inline_failures,
approve_by_playbook_creator_violates_sod,
completed_playbook_rejects_activation,
patch_playbook_stale_version_rejected,
patch_playbook_missing_version_rejected.
"""
from test_helpers import (
    ApiErrorId,
    USER_ANALYST_1,
    USER_OFFICER_2,
    add_action,
    assert_playbook,
    assert_playbook_action,
    create_playbook_payload,
    make_activated_playbook,
    make_analyst_headers,
    make_approved_playbook,
    make_asset,
    make_committee_headers,
    make_line,
    make_metric,
    make_officer_headers,
    make_playbook,
    make_pledge,
    make_scenario,
    make_tested_playbook,
    post_reading,
    setup_active_drawdown_playbook,
    setup_executing_drawdown,
    setup_line_with_pledge,
    validate_error,
    validate_success,
)

ANALYST = make_analyst_headers(USER_ANALYST_1)
OFFICER = make_officer_headers("ro_1")
OFFICER_2 = make_officer_headers(USER_OFFICER_2)
COMMITTEE = make_committee_headers("lc_1")


def _drawdown_action(line_id, proceeds, seq=1, lag=0):
    return {
        "kind": "LINE_DRAWDOWN", "sequence_no": seq,
        "estimated_proceeds_cents": proceeds, "settlement_lag_days": lag,
        "line_id": line_id,
    }


class TestCapacityTest:
    def test_capacity_test_failure_keeps_draft_with_inline_failures(self, api, officer_headers):
        """PRD §3.8: "A failing test leaves the playbook in `DRAFT` and returns
        the detail inline rather than as an error: the `result`, the
        `total_estimated_cents`, the `total_realizable_cents` — the sum, per
        action, of the smaller of its estimated proceeds and its realizable
        capacity — and the `failures` list."
        PRD §3.8: "a `LINE_DRAWDOWN` counts its referenced line's current
        `borrowing_power_cents` when the line is `ACTIVE`, and zero otherwise".

        Design: Corner/calculations/capacity_test_failure_keeps_draft_with_inline_failures
        """
        scenario = make_scenario(name="Base", tier="BASELINE")
        line = make_line(total_capacity_cents=100_000_000, advance_rate_bps=10_000)
        # No pledges: the line's borrowing power is 0.
        playbook = make_playbook(scenario["id"], name="PB",
                                 target_capacity_cents=60_000_000)
        add_action(playbook["id"], **_drawdown_action(line["id"], 60_000_000))

        result = validate_success(api.run_capacity_test(playbook["id"], officer_headers))
        assert result["result"] == "FAILED", f"capacity 0 < estimate must fail, got {result['result']}"
        assert result["total_estimated_cents"] == 60_000_000
        assert result["total_realizable_cents"] == 0, (
            f"line power 0 yields zero realizable capacity, got {result['total_realizable_cents']}"
        )
        playbook_now = validate_success(api.get_playbook(playbook["id"], officer_headers))
        assert playbook_now["status"] == "DRAFT", (
            f"a FAILED capacity test leaves the playbook DRAFT, got {playbook_now['status']}"
        )


class TestApproveSod:
    def test_approve_by_playbook_creator_violates_sod(self, api, officer_2_headers):
        """PRD §3.9: "Approval is a `RiskOfficer` act guarded by segregation of
        duties: the approver's `X-User-ID` must differ from the playbook's
        `created_by_user_id`, or the request fails with `ERR_SOD_VIOLATION`. A
        clean approval moves the playbook `TESTED` → `APPROVED` and records
        `approved_by_user_id`."

        Design: Corner/validations/approve_by_playbook_creator_violates_sod
        """
        scenario = make_scenario(name="Base", tier="BASELINE")
        line, _asset, _pledge = setup_line_with_pledge()
        playbook, _actions = make_tested_playbook(
            scenario["id"], [_drawdown_action(line["id"], 60_000_000)],
            target_capacity_cents=60_000_000, creator=USER_ANALYST_1,
        )
        # The creator cannot approve their own playbook, even in officer guise:
        # the SoD comparison is on X-User-ID against created_by_user_id.
        creator_as_officer = make_officer_headers(USER_ANALYST_1)
        resp = api.approve_playbook(playbook["id"], creator_as_officer)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)

        approved = validate_success(api.approve_playbook(playbook["id"], officer_2_headers))
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == USER_OFFICER_2, (
            f"approved_by_user_id records the approver, got {approved['approved_by_user_id']}"
        )


class TestActivationGates:
    def test_activate_draft_playbook_state_beats_posture_gate(self, api, committee_headers):
        """PRD §2.9: "Sixth, state-machine admissibility of the requested
        transition on the addressed resource (`ERR_INVALID_STATE`)."
        PRD §2.9: "Seventh, business-safety gates: segregation of duties
        (`ERR_SOD_VIOLATION`), posture sufficiency (`ERR_POSTURE_INSUFFICIENT`),
        line availability (`ERR_LINE_SUSPENDED`), asset availability
        (`ERR_ASSET_NOT_PLEDGEABLE`, `ERR_ASSET_NOT_AVAILABLE`), scenario
        status (`ERR_SCENARIO_RETIRED`), and de-escalation conditions
        (`ERR_DEESCALATION_BLOCKED`)."
        PRD §3.9: "Every transition in this section is available only from its
        named from-state; invoking one against a playbook or action standing in
        any other status is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/activate_draft_playbook_state_beats_posture_gate
        """
        scenario = make_scenario(name="Base", tier="BASELINE")
        playbook = make_playbook(scenario["id"], name="PB",
                                 min_activation_posture="SEVERE",
                                 target_capacity_cents=1000)
        # DRAFT playbook (invalid from-state) AND posture NORMAL below SEVERE:
        # the state error is the earlier check and must surface.
        resp = api.activate_playbook(playbook["id"], committee_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_activate_draft_playbook_never_reaches_posture_gate(self, api, committee_headers):
        """PRD §2.9: "Validation runs in a fixed order so that a request
        failing several checks always surfaces the earliest failure."
        PRD §2.9: "Sixth, state-machine admissibility of the requested
        transition on the addressed resource (`ERR_INVALID_STATE`)."
        PRD §2.9: "Seventh, business-safety gates: segregation of duties
        (`ERR_SOD_VIOLATION`), posture sufficiency (`ERR_POSTURE_INSUFFICIENT`),
        line availability (`ERR_LINE_SUSPENDED`), asset availability
        (`ERR_ASSET_NOT_PLEDGEABLE`, `ERR_ASSET_NOT_AVAILABLE`), scenario
        status (`ERR_SCENARIO_RETIRED`), and de-escalation conditions
        (`ERR_DEESCALATION_BLOCKED`)."

        Design: Difficulty/priority_pair_validation_conflict/activate_draft_playbook_state_beats_posture_gate
        """
        scenario = make_scenario(name="Base", tier="BASELINE")
        # Escalate posture to SEVERE so ONLY the state check can fail:
        # a single RED reading on a fresh metric does that via READING_AUTO.
        metric = make_metric(code="M", name="m")
        post_reading(metric["id"], 6000)
        playbook = make_playbook(scenario["id"], name="PB",
                                 min_activation_posture="SEVERE",
                                 target_capacity_cents=1000)
        # The posture gate is satisfied (SEVERE >= SEVERE) but the playbook is
        # DRAFT, so activation is a state error.
        resp = api.activate_playbook(playbook["id"], committee_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_activation_gated_by_current_posture(self, api, committee_headers, analyst_headers):
        """PRD §3.9: "The current posture's ordinal must be at least the
        ordinal of the playbook's `min_activation_posture` — `NORMAL` at 0,
        `HEIGHTENED` at 1, `SEVERE` at 2, `CRISIS` at 3 — with shortfalls
        rejected as `ERR_POSTURE_INSUFFICIENT`".
        PRD §3.6: "Whenever a posted reading makes a metric's `current_band`
        become `RED`, the system immediately evaluates posture and appends a
        snapshot with trigger `READING_AUTO`."

        Design: Difficulty/cross_entity_state_dependency/playbook_activation_gated_by_current_posture
        """
        scenario = make_scenario(name="Base", tier="BASELINE")
        line, _asset, _pledge = setup_line_with_pledge()
        playbook, _actions = make_approved_playbook(
            scenario["id"], [_drawdown_action(line["id"], 60_000_000)],
            min_activation_posture="SEVERE", target_capacity_cents=60_000_000,
        )
        metric = make_metric(code="M", name="m")

        # Posture is NORMAL (no snapshots): below the SEVERE gate.
        resp = api.activate_playbook(playbook["id"], committee_headers)
        validate_error(resp, ApiErrorId.ERR_POSTURE_INSUFFICIENT)

        # A RED reading escalates posture to SEVERE via READING_AUTO.
        post_reading(metric["id"], 6000)

        activated = validate_success(api.activate_playbook(playbook["id"], committee_headers))
        assert activated["status"] == "ACTIVATED", (
            f"SEVERE posture satisfies the SEVERE gate, got {activated['status']}"
        )

    def test_activation_flips_pending_actions_to_ready(self, api, committee_headers):
        """PRD §3.9: "Success moves the playbook `APPROVED` → `ACTIVATED`,
        stamps `activated_at` with the logical clock, and flips every `PENDING`
        action of the playbook to `READY`."

        Design: Difficulty/cross_entity_state_dependency/playbook_activation_gated_by_current_posture
        """
        scenario = make_scenario(name="Base", tier="BASELINE")
        line, _asset, _pledge = setup_line_with_pledge()
        playbook, actions = make_approved_playbook(
            scenario["id"], [_drawdown_action(line["id"], 60_000_000)],
            target_capacity_cents=60_000_000,
        )
        assert actions[0]["status"] == "PENDING"
        activated = validate_success(api.activate_playbook(playbook["id"], committee_headers))
        assert activated["status"] == "ACTIVATED"
        assert activated.get("activated_at") is not None
        action_now = validate_success(api.get_playbook_action(actions[0]["id"], ANALYST))
        assert action_now["status"] == "READY", (
            f"activation flips PENDING actions to READY, got {action_now['status']}"
        )


class TestMutualExclusion:
    def test_single_active_playbook_mutual_exclusion(self, api, committee_headers):
        """PRD §3.9: "the desk runs at most one active playbook at a time, so
        when any other playbook holds `ACTIVATED` or `EXECUTING` the activation
        fails with `ERR_PLAYBOOK_ALREADY_ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/single_active_playbook_mutual_exclusion
        """
        scenario = make_scenario(name="Base", tier="BASELINE")
        line, _asset, _pledge = setup_line_with_pledge()
        pb1, _a1 = make_approved_playbook(
            scenario["id"], [_drawdown_action(line["id"], 60_000_000)],
            name="PB1", target_capacity_cents=60_000_000,
        )
        pb2, _a2 = make_approved_playbook(
            scenario["id"], [_drawdown_action(line["id"], 30_000_000)],
            name="PB2", target_capacity_cents=30_000_000,
        )
        first = validate_success(api.activate_playbook(pb1["id"], committee_headers))
        assert first["status"] == "ACTIVATED"
        # PB1 occupies the single active slot; PB2's activation collides.
        resp = api.activate_playbook(pb2["id"], committee_headers)
        validate_error(resp, ApiErrorId.ERR_PLAYBOOK_ALREADY_ACTIVE)

    def test_slot_frees_after_stand_down(self, api, committee_headers):
        """PRD §3.9: "the desk runs at most one active playbook at a time, so
        when any other playbook holds `ACTIVATED` or `EXECUTING` the activation
        fails with `ERR_PLAYBOOK_ALREADY_ACTIVE`."
        PRD §3.9: "Stand-down, a `LiquidityCommittee` act from `ACTIVATED` or
        `EXECUTING`, is refused while any action of the playbook stands
        `EXECUTING` (`ERR_INVALID_STATE`); otherwise the playbook moves to
        `STOOD_DOWN`".

        Design: Difficulty/resource_temporal_overlap/single_active_playbook_mutual_exclusion
        """
        scenario = make_scenario(name="Base", tier="BASELINE")
        line, _asset, _pledge = setup_line_with_pledge()
        pb1, _a1 = make_approved_playbook(
            scenario["id"], [_drawdown_action(line["id"], 60_000_000)],
            name="PB1", target_capacity_cents=60_000_000,
        )
        pb2, _a2 = make_approved_playbook(
            scenario["id"], [_drawdown_action(line["id"], 30_000_000)],
            name="PB2", target_capacity_cents=30_000_000,
        )
        validate_success(api.activate_playbook(pb1["id"], committee_headers))
        validate_error(api.activate_playbook(pb2["id"], committee_headers),
                       ApiErrorId.ERR_PLAYBOOK_ALREADY_ACTIVE)
        stood_down = validate_success(api.stand_down_playbook(pb1["id"], committee_headers))
        assert stood_down["status"] == "STOOD_DOWN"
        # The slot is free once PB1 left ACTIVATED/EXECUTING.
        second = validate_success(api.activate_playbook(pb2["id"], committee_headers))
        assert second["status"] == "ACTIVATED"


class TestRevisionCycle:
    def test_playbook_stood_down_revision_cycle(self, api, committee_headers):
        """PRD §3.9: "Stand-down, a `LiquidityCommittee` act from `ACTIVATED`
        or `EXECUTING`, is refused while any action of the playbook stands
        `EXECUTING` (`ERR_INVALID_STATE`); otherwise the playbook moves to
        `STOOD_DOWN` and every `PENDING`, `READY`, or `BLOCKED` action becomes
        `SKIPPED`. Revision, a `TreasuryAnalyst` act from `STOOD_DOWN`, returns
        the playbook to `DRAFT`, clears both `tested_at` and
        `approved_by_user_id` so that re-testing and re-approval are required,
        and returns every `SKIPPED` action to `PENDING`."

        Design: Difficulty/non_linear_state_machine/playbook_stood_down_revision_cycle
        """
        scenario = make_scenario(name="Base", tier="BASELINE")
        line, _ap, _pledge = setup_line_with_pledge()
        sale_asset = make_asset(asset_class="LEVEL_1", reference="S1",
                                market_value_cents=50_000_000)
        playbook, actions = make_activated_playbook(
            scenario["id"],
            [_drawdown_action(line["id"], 60_000_000, seq=1),
             {"kind": "ASSET_SALE", "sequence_no": 2,
              "estimated_proceeds_cents": 40_000_000, "settlement_lag_days": 0,
              "asset_id": sale_asset["id"]}],
            target_capacity_cents=90_000_000,
        )
        stood_down = validate_success(api.stand_down_playbook(playbook["id"], committee_headers))
        assert stood_down["status"] == "STOOD_DOWN"

        revised = validate_success(api.revise_playbook(playbook["id"], ANALYST))
        assert revised["status"] == "DRAFT", f"revision closes the cycle to DRAFT, got {revised['status']}"
        assert revised.get("tested_at") is None, "revision clears tested_at"
        assert revised.get("approved_by_user_id") is None, "revision clears approved_by_user_id"

        action_now = validate_success(api.get_playbook_action(actions[0]["id"], ANALYST))
        assert action_now["status"] == "PENDING", (
            f"SKIPPED actions re-arm to PENDING on revise, got {action_now['status']}"
        )

    def test_revised_playbook_retakes_the_full_cycle(self, api, committee_headers):
        """PRD §3.9: "Revision, a `TreasuryAnalyst` act from `STOOD_DOWN`,
        returns the playbook to `DRAFT`, clears both `tested_at` and
        `approved_by_user_id` so that re-testing and re-approval are required".
        PRD §3.8: "A passing test moves the playbook `DRAFT` → `TESTED` and
        stamps `tested_at` with the logical clock."
        PRD §3.9: "A clean approval moves the playbook `TESTED` → `APPROVED`
        and records `approved_by_user_id`."

        Design: Difficulty/non_linear_state_machine/playbook_stood_down_revision_cycle
        """
        scenario = make_scenario(name="Base", tier="BASELINE")
        line, _ap, _pledge = setup_line_with_pledge()
        playbook, actions = make_activated_playbook(
            scenario["id"], [_drawdown_action(line["id"], 60_000_000)],
            target_capacity_cents=60_000_000,
        )
        validate_success(api.stand_down_playbook(playbook["id"], committee_headers))
        validate_success(api.revise_playbook(playbook["id"], ANALYST))
        # Re-test passes (DRAFT -> TESTED) and re-approval records the approver.
        result = validate_success(api.run_capacity_test(playbook["id"], OFFICER))
        assert result["result"] == "PASSED"
        approved = validate_success(api.approve_playbook(playbook["id"], OFFICER_2))
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == USER_OFFICER_2


class TestTerminalLockdown:
    def test_completed_playbook_rejects_activation(self, api, committee_headers, ops_headers):
        """PRD §3.9: "Every transition in this section is available only from
        its named from-state; invoking one against a playbook or action
        standing in any other status is rejected with `ERR_INVALID_STATE`."
        PRD §3.9: "Completion, a `LiquidityCommittee` act from `EXECUTING`,
        requires every action of the playbook to stand in a terminal state —
        `SETTLED`, `FAILED`, or `SKIPPED` — with stragglers earning
        `ERR_ACTIONS_NOT_ALL_TERMINAL`, and lands the playbook in `COMPLETED`,
        its terminal state."

        Design: Corner/state_machines/completed_playbook_rejects_activation
        """
        ctx = setup_executing_drawdown(
            target_capacity_cents=60_000_000, draw_amount_cents=60_000_000,
            settlement_lag_days=0,
        )
        # Lag 0 settles immediately at the default logical clock.
        settled = validate_success(api.settle_playbook_action(ctx["action"]["id"], ops_headers))
        assert settled["status"] == "SETTLED"
        completed = validate_success(api.complete_playbook(ctx["playbook"]["id"], committee_headers))
        assert completed["status"] == "COMPLETED"
        # COMPLETED is terminal: activation is rejected.
        resp = api.activate_playbook(ctx["playbook"]["id"], committee_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPlaybookOcc:
    def test_patch_playbook_stale_version_rejected(self, api, analyst_headers):
        """PRD §2.7: "A `PATCH /liquidity/contingency-playbooks/{id}` request
        must carry `expected_playbook_version` equal to the playbook's current
        `version`. If another writer has advanced the playbook's version since
        the client last read it — for example through a successful edit of the
        same draft — the update is rejected, so the client cannot overwrite
        changes it has not observed."
        PRD §3.8: "each accepted edit bumps the playbook's `version` by one".

        Design: Corner/cross_cutting_layers/patch_playbook_stale_version_rejected
        """
        scenario = make_scenario(name="Base", tier="BASELINE")
        playbook = make_playbook(scenario["id"], name="PB", target_capacity_cents=1000)
        assert playbook["version"] == 1
        first = validate_success(api.patch_playbook(
            playbook["id"],
            {"expected_playbook_version": playbook["version"], "name": "PB v2"},
            analyst_headers,
        ))
        assert first["version"] == 2, f"an accepted edit bumps version, got {first['version']}"
        resp = api.patch_playbook(
            playbook["id"],
            {"expected_playbook_version": playbook["version"], "name": "PB v3"},
            analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_patch_playbook_missing_version_rejected(self, api, analyst_headers):
        """PRD §2.7: "A `PATCH /liquidity/contingency-playbooks/{id}` request
        must carry `expected_playbook_version` equal to the playbook's current
        `version`."
        PRD §2.9: "Fourth, request shape: required fields present, types valid,
        enum membership respected, numeric ranges honored, and cross-field
        rules such as threshold coherence (`ERR_INVALID_REQUEST`,
        `ERR_THRESHOLD_CONFIG_INVALID`)".

        Design: Corner/errors/patch_playbook_missing_version_rejected
        """
        scenario = make_scenario(name="Base", tier="BASELINE")
        playbook = make_playbook(scenario["id"], name="PB", target_capacity_cents=1000)
        resp = api.patch_playbook(playbook["id"], {"name": "PB renamed"}, analyst_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
