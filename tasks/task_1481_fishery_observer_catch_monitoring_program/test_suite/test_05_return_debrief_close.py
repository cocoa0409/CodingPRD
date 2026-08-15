"""Return reconciliation, debriefing gates, the data-rejection revision loop,
decertification and plan-close guards, and close-time credit visibility."""
from test_helpers import (
    ApiErrorId,
    assert_notice_day_invariant,
    assert_same_instant,
    assign_debriefer,
    board_deployment,
    create_deployment_for_notice,
    make_debriefer,
    make_debriefer_headers,
    make_observer,
    make_observer_headers,
    record_fail_inspection,
    record_haul_sample,
    record_pass_inspection,
    return_deployment,
    setup_notice_scenario,
    submit_data,
    validate_error,
    validate_success,
)


def _deployment_in_debriefing(api, coordinator_headers, *, person_ref_shared=False):
    """Deployment driven to DEBRIEFING with one RECORDED sample and no
    debriefer assigned."""
    if person_ref_shared:
        bundle = setup_notice_scenario(with_debriefer=False)
    else:
        bundle = setup_notice_scenario()
    obs_id = bundle["observer"]["id"]
    deployment = create_deployment_for_notice(
        bundle["notice"]["id"], obs_id,
        "2026-09-10T00:00:00Z", "2026-09-15T00:00:00Z",
    )
    record_pass_inspection(deployment["id"], obs_id)
    board_deployment(deployment["id"], obs_id)
    sample = record_haul_sample(
        deployment["id"], obs_id, haul_date="2026-09-12T00:00:00Z"
    )
    return_deployment(deployment["id"], obs_id, "2026-09-15T00:00:00Z")
    submit_data(deployment["id"], obs_id)
    return bundle, deployment, sample


class TestReturnAndReconciliation:
    def test_return_reconciliation_split(self, api, coordinator_headers):
        """PRD §3.5: "The deployment moves `AT_SEA` → `RETURNED`, its
        `actual_sea_days` is computed as the inclusive day count from
        `scheduled_departure_date` through `actual_return_date`, and the notice
        ledger converts the reservation into consumption exactly as §2.9
        describes: `reserved_sea_days` falls by `planned_sea_days`,
        `consumed_sea_days` rises by `actual_sea_days`, and `remaining_sea_days`
        is credited with the difference between planned and actual days."

        Design: Corner/calculations/sea_day_accounting_return_reconciliation_split
        """
        bundle = setup_notice_scenario()
        obs_id = bundle["observer"]["id"]
        deployment = create_deployment_for_notice(
            bundle["notice"]["id"], obs_id,
            "2026-09-10T00:00:00Z", "2026-09-19T00:00:00Z",
        )
        assert deployment["planned_sea_days"] == 10
        record_pass_inspection(deployment["id"], obs_id)
        board_deployment(deployment["id"], obs_id)
        returned = return_deployment(deployment["id"], obs_id, "2026-09-14T00:00:00Z")
        assert returned["status"] == "RETURNED"
        assert returned["actual_sea_days"] == 5
        notice = validate_success(
            api.get_selection_notice(bundle["notice"]["id"], coordinator_headers)
        )
        assert notice["reserved_sea_days"] == 0
        assert notice["consumed_sea_days"] == 5
        assert notice["remaining_sea_days"] == 25
        assert_notice_day_invariant(notice)

    def test_return_outside_scheduled_window_rejected(self, api, coordinator_headers):
        """PRD §3.5: "The observer ends the trip by recording the
        `actual_return_date` — null until this moment, as is `actual_sea_days`
        — which must fall on or after the scheduled departure and on or before
        the scheduled return, else `ERR_DATE_RANGE_INVALID`."

        Design: Corner/errors/err_return_outside_scheduled_window
        """
        bundle = setup_notice_scenario()
        obs_id = bundle["observer"]["id"]
        deployment = create_deployment_for_notice(
            bundle["notice"]["id"], obs_id,
            "2026-09-10T00:00:00Z", "2026-09-19T00:00:00Z",
        )
        record_pass_inspection(deployment["id"], obs_id)
        board_deployment(deployment["id"], obs_id)
        resp = api.return_deployment(
            deployment["id"],
            {"actual_return_date": "2026-09-21T00:00:00Z"},
            make_observer_headers(obs_id),
        )
        validate_error(resp, ApiErrorId.ERR_DATE_RANGE_INVALID, 422)
        current = validate_success(api.get_deployment(deployment["id"], coordinator_headers))
        assert current["status"] == "AT_SEA"


class TestDebriefingGates:
    def test_submit_data_without_samples_rejected(self, api, coordinator_headers):
        """PRD §3.6: "After a return — or an early termination — the observer
        submits the trip's data, which requires at least one haul sample to
        exist on the deployment: a submission with none is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/errors/err_submit_data_without_haul_samples
        """
        bundle = setup_notice_scenario()
        obs_id = bundle["observer"]["id"]
        deployment = create_deployment_for_notice(
            bundle["notice"]["id"], obs_id,
            "2026-09-10T00:00:00Z", "2026-09-15T00:00:00Z",
        )
        record_pass_inspection(deployment["id"], obs_id)
        board_deployment(deployment["id"], obs_id)
        return_deployment(deployment["id"], obs_id, "2026-09-15T00:00:00Z")
        resp = api.submit_deployment_data(
            deployment["id"], {}, make_observer_headers(obs_id)
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        current = validate_success(api.get_deployment(deployment["id"], coordinator_headers))
        assert current["status"] == "RETURNED"
        assert current["submitted_at"] is None

    def test_validate_without_assigned_debriefer_rejected(self, api, coordinator_headers):
        """PRD §3.6: "The validation and rejection calls that follow require an
        assigned debriefer (`ERR_DEBRIEFER_NOT_ASSIGNED` when none is set) and
        require the caller to be exactly that debriefer (`ERR_FORBIDDEN`
        otherwise)."

        Design: Corner/errors/err_debriefer_not_assigned_on_validate
        """
        bundle, deployment, sample = _deployment_in_debriefing(api, coordinator_headers)
        resp = api.validate_data(
            deployment["id"], {}, make_debriefer_headers(bundle["debriefer"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_DEBRIEFER_NOT_ASSIGNED, 409)
        current = validate_success(api.get_deployment(deployment["id"], coordinator_headers))
        assert current["status"] == "DEBRIEFING"

    def test_sample_gates_unresolved_then_zero_verified(self, api, coordinator_headers):
        """PRD §3.6: "Gate one: every haul sample of the deployment must stand
        in `VERIFIED` or `DISCARDED` — any sample still `RECORDED` or `FLAGGED`
        fails validation with `ERR_SAMPLES_NOT_RESOLVED`. Gate two: at least
        one sample must be `VERIFIED`, else `ERR_SAMPLE_COVERAGE_INSUFFICIENT`."

        Design: Corner/validations/sample_coverage_gate_layered_failures
        """
        # Both samples are recorded while the deployment is AT_SEA — PRD §3.5
        # permits haul-sample recording "While the deployment is `AT_SEA` — and
        # only then" — before the drive continues into DEBRIEFING.
        bundle = setup_notice_scenario()
        obs_id = bundle["observer"]["id"]
        deployment = create_deployment_for_notice(
            bundle["notice"]["id"], obs_id,
            "2026-09-10T00:00:00Z", "2026-09-15T00:00:00Z",
        )
        record_pass_inspection(deployment["id"], obs_id)
        board_deployment(deployment["id"], obs_id)
        sample_a = record_haul_sample(
            deployment["id"], obs_id, haul_date="2026-09-12T00:00:00Z"
        )
        sample_b = record_haul_sample(
            deployment["id"], obs_id,
            haul_date="2026-09-13T00:00:00Z", haul_number=2,
        )
        return_deployment(deployment["id"], obs_id, "2026-09-15T00:00:00Z")
        submit_data(deployment["id"], obs_id)
        assign_debriefer(deployment["id"], bundle["debriefer"]["id"])
        deb = make_debriefer_headers(bundle["debriefer"]["id"])

        # Gate 1: both samples still RECORDED.
        unresolved = api.validate_data(deployment["id"], {}, deb)
        validate_error(unresolved, ApiErrorId.ERR_SAMPLES_NOT_RESOLVED, 409)

        # Resolve both to DISCARDED (RECORDED -> FLAGGED -> DISCARDED), leaving
        # zero VERIFIED samples.
        for sample in (sample_a, sample_b):
            validate_success(
                api.flag_haul_sample(sample["id"], {"reason": "Suspect tally"}, deb)
            )
            validate_success(
                api.discard_haul_sample(sample["id"], {"reason": "Confirmed unusable"}, deb)
            )
        # Gate 2: everything resolved but nothing VERIFIED.
        no_verified = api.validate_data(deployment["id"], {}, deb)
        validate_error(no_verified, ApiErrorId.ERR_SAMPLE_COVERAGE_INSUFFICIENT, 422)
        current = validate_success(api.get_deployment(deployment["id"], coordinator_headers))
        assert current["status"] == "DEBRIEFING"


class TestDeploymentNonLinearFlow:
    def test_safety_hold_fork_and_join(self, api, coordinator_headers):
        """PRD §3.4: "A fail requires `deficiency_notes` — absent notes on a
        failing checklist again yield `ERR_SAFETY_CHECKLIST_INCOMPLETE` — drops
        the deployment into `SAFETY_HOLD`, and sets `latest_safety_result` to
        `FAIL`." and "Re-inspection from `SAFETY_HOLD` must reference the
        failed inspection it supersedes via `supersedes_inspection_id`;
        pointing anywhere but the deployment's most recent `FAIL` inspection
        yields `ERR_SAFETY_SUPERSESSION_REQUIRED`, and a passing re-inspection
        lifts the deployment to `READY_TO_DEPLOY`."

        Design: Difficulty/non_linear_state_machine/deployment_data_rejected_revision_loop
        """
        bundle = setup_notice_scenario()
        obs_id = bundle["observer"]["id"]
        deployment = create_deployment_for_notice(
            bundle["notice"]["id"], obs_id,
            "2026-09-10T00:00:00Z", "2026-09-19T00:00:00Z",
        )
        failed = record_fail_inspection(deployment["id"], obs_id)
        current = validate_success(api.get_deployment(deployment["id"], coordinator_headers))
        assert current["status"] == "SAFETY_HOLD"
        assert current["latest_safety_result"] == "FAIL"

        passed = record_pass_inspection(
            deployment["id"], obs_id, supersedes_inspection_id=failed["id"]
        )
        assert passed["supersedes_inspection_id"] == failed["id"]
        current = validate_success(api.get_deployment(deployment["id"], coordinator_headers))
        assert current["status"] == "READY_TO_DEPLOY"
        assert current["latest_safety_result"] == "PASS"
        boarded = board_deployment(deployment["id"], obs_id)
        assert boarded["status"] == "AT_SEA"

    def test_data_rejected_revision_loop(self, api, coordinator_headers):
        """PRD §3.6: "Alternatively, the debriefer rejects the data with a
        `rejection_reason`, moving the deployment to `DATA_REJECTED`, from
        which the observer may resubmit the trip data — resubmission restamps
        `submitted_at` and returns the deployment to `DEBRIEFING` for another
        pass."

        Design: Difficulty/non_linear_state_machine/deployment_data_rejected_revision_loop
        """
        bundle, deployment, sample = _deployment_in_debriefing(api, coordinator_headers)
        obs_id = bundle["observer"]["id"]
        assign_debriefer(deployment["id"], bundle["debriefer"]["id"])
        deb = make_debriefer_headers(bundle["debriefer"]["id"])

        rejected = validate_success(
            api.reject_data(
                deployment["id"],
                {"rejection_reason": "Haul 1 species composition incomplete"},
                deb,
            )
        )
        assert rejected["status"] == "DATA_REJECTED"

        resubmitted = submit_data(deployment["id"], obs_id)
        assert resubmitted["status"] == "DEBRIEFING", "resubmission re-enters DEBRIEFING"

        validate_success(api.verify_haul_sample(sample["id"], {}, deb))
        validated = validate_success(api.validate_data(deployment["id"], {}, deb))
        assert validated["status"] == "DATA_VALIDATED"


class TestRegistryAndPlanGuards:
    def test_decertify_blocked_while_deployment_open(self, api, admin_headers, coordinator_headers):
        """PRD §3.1: "Decertification — from either `ACTIVE` or `SUSPENDED`
        into the terminal `DECERTIFIED` — is refused while the observer still
        holds a deployment in `SCHEDULED`, `SAFETY_HOLD`, `READY_TO_DEPLOY`, or
        `AT_SEA`."

        Design: Corner/state_machines/observer_decertify_blocked_while_active_deployment_exists
        """
        bundle = setup_notice_scenario()
        obs_id = bundle["observer"]["id"]
        deployment = create_deployment_for_notice(
            bundle["notice"]["id"], obs_id,
            "2026-09-10T00:00:00Z", "2026-09-15T00:00:00Z",
        )
        blocked = api.patch_observer(obs_id, {"status": "DECERTIFIED"}, admin_headers)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE, 409)

        validate_success(api.cancel_deployment(deployment["id"], {}, coordinator_headers))
        decertified = validate_success(
            api.patch_observer(obs_id, {"status": "DECERTIFIED"}, admin_headers)
        )
        assert decertified["status"] == "DECERTIFIED"
        # DECERTIFIED is terminal: no way back to ACTIVE.
        revive = api.patch_observer(obs_id, {"status": "ACTIVE"}, admin_headers)
        validate_error(revive, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_plan_close_blocked_while_deployment_open(self, api, coordinator_headers):
        """PRD §3.2: "Closing is refused while any deployment under the plan
        remains open — that is, in any of `SCHEDULED`, `SAFETY_HOLD`,
        `READY_TO_DEPLOY`, `AT_SEA`, `RETURNED`, `EARLY_TERMINATED`,
        `DEBRIEFING`, `DATA_REJECTED`, or `DATA_VALIDATED` — with
        `ERR_PLAN_HAS_OPEN_DEPLOYMENTS`." PRD §3.3: "It is defaulted by the
        plan-close cascade when the season ends with `remaining_sea_days` still
        positive — an outcome that also adds 2 points to the vessel's
        `selection_penalty_points`."

        Design: Corner/state_machines/plan_close_blocked_while_any_deployment_open
        """
        bundle = setup_notice_scenario()
        deployment = create_deployment_for_notice(
            bundle["notice"]["id"], bundle["observer"]["id"],
            "2026-09-10T00:00:00Z", "2026-09-15T00:00:00Z",
        )
        blocked = api.close_coverage_plan(
            bundle["plan"]["id"], {"actual_fleet_effort_days": 100}, coordinator_headers
        )
        validate_error(blocked, ApiErrorId.ERR_PLAN_HAS_OPEN_DEPLOYMENTS, 409)

        validate_success(api.cancel_deployment(deployment["id"], {}, coordinator_headers))
        closed = validate_success(
            api.close_coverage_plan(
                bundle["plan"]["id"], {"actual_fleet_effort_days": 100}, coordinator_headers
            )
        )
        assert closed["status"] == "CLOSED"
        # FINAL variant: em_cap floor(100*0.40)=40, credited min(0,40)=0,
        # base 100, requirement ceil(100*0.30)=30.
        assert closed["final_required_observer_sea_days"] == 30
        notice = validate_success(
            api.get_selection_notice(bundle["notice"]["id"], coordinator_headers)
        )
        assert notice["status"] == "DEFAULTED"
        vessel = validate_success(api.get_vessel(bundle["vessel"]["id"], coordinator_headers))
        assert vessel["selection_penalty_points"] == 2


class TestCloseTimeConsistency:
    def test_close_credits_are_immediately_visible(self, api, coordinator_headers):
        """PRD §3.6: "Closing is the coordinator's final act on a validated
        deployment and credits the season tallies in one sweep: the observer's
        `sea_days_used_ytd` grows by `actual_sea_days`, the vessel's
        `sea_days_observed_ytd` grows by the same, the vessel's
        `last_observed_end_date` is set to the `actual_return_date`, and the
        plan's `actual_observer_sea_days` grows by `actual_sea_days`."

        Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_same_response
        """
        bundle = setup_notice_scenario()
        obs_id = bundle["observer"]["id"]
        deployment = create_deployment_for_notice(
            bundle["notice"]["id"], obs_id,
            "2026-09-10T00:00:00Z", "2026-09-19T00:00:00Z",
        )
        record_pass_inspection(deployment["id"], obs_id)
        board_deployment(deployment["id"], obs_id)
        sample = record_haul_sample(
            deployment["id"], obs_id, haul_date="2026-09-12T00:00:00Z"
        )
        return_deployment(deployment["id"], obs_id, "2026-09-19T00:00:00Z")
        submit_data(deployment["id"], obs_id)
        assign_debriefer(deployment["id"], bundle["debriefer"]["id"])
        deb = make_debriefer_headers(bundle["debriefer"]["id"])
        validate_success(api.verify_haul_sample(sample["id"], {}, deb))
        validate_success(api.validate_data(deployment["id"], {}, deb))

        closed = validate_success(api.close_deployment(deployment["id"], {}, coordinator_headers))
        assert closed["status"] == "CLOSED"

        observer = validate_success(api.get_observer(obs_id, coordinator_headers))
        assert observer["sea_days_used_ytd"] == 10
        vessel = validate_success(api.get_vessel(bundle["vessel"]["id"], coordinator_headers))
        assert vessel["sea_days_observed_ytd"] == 10
        assert_same_instant(
            vessel["last_observed_end_date"], "2026-09-19T00:00:00Z",
            "vessel.last_observed_end_date",
        )
        plan = validate_success(api.get_coverage_plan(bundle["plan"]["id"], coordinator_headers))
        assert plan["actual_observer_sea_days"] == 10
        notice = validate_success(
            api.get_selection_notice(bundle["notice"]["id"], coordinator_headers)
        )
        # remaining 20 > 0, so auto-fulfillment does not fire.
        assert notice["status"] == "ACCEPTED"
        assert notice["remaining_sea_days"] == 20
        assert_notice_day_invariant(notice)


class TestOwnershipAndSegregation:
    def test_observer_cannot_board_anothers_deployment(self, api, coordinator_headers):
        """PRD §2.1: "When `X-User-Role` is `Observer`, `X-User-ID` is the `id`
        of the acting `Observer`; ownership checks on any resource that
        references an `Observer` — such as a deployment's `observer_id` —
        compare that foreign-key field to `X-User-ID`."

        Design: Corner/rbac/observer_cannot_act_on_another_observers_deployment
        """
        bundle = setup_notice_scenario()
        obs_id = bundle["observer"]["id"]
        other = make_observer()
        deployment = create_deployment_for_notice(
            bundle["notice"]["id"], obs_id,
            "2026-09-10T00:00:00Z", "2026-09-15T00:00:00Z",
        )
        record_pass_inspection(deployment["id"], obs_id)
        resp = api.board_deployment(
            deployment["id"], {}, make_observer_headers(other["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        current = validate_success(api.get_deployment(deployment["id"], coordinator_headers))
        assert current["status"] == "READY_TO_DEPLOY"

    def test_debriefer_conflict_of_interest(self, api, coordinator_headers):
        """PRD §3.6: "Segregation of duties forbids assigning a debriefer whose
        `person_ref` equals the deployment observer's `person_ref` — such a
        pairing is rejected with `ERR_DEBRIEFER_CONFLICT_OF_INTEREST`."

        Design: Corner/rbac/debriefer_conflict_of_interest_same_person_as_observer
        """
        bundle, deployment, sample = _deployment_in_debriefing(
            api, coordinator_headers, person_ref_shared=True
        )
        # Register a debriefer who IS the deployment's observer (same person).
        same_person = make_debriefer(person_ref=bundle["observer"]["person_ref"])
        resp = api.assign_debriefer(
            deployment["id"], {"debriefer_id": same_person["id"]}, coordinator_headers
        )
        validate_error(resp, ApiErrorId.ERR_DEBRIEFER_CONFLICT_OF_INTEREST, 403)
        current = validate_success(api.get_deployment(deployment["id"], coordinator_headers))
        assert current["assigned_debriefer_id"] is None

    def test_suspended_debriefer_forbidden(self, api, admin_headers, coordinator_headers):
        """PRD §2.1: "An entity-backed actor whose registry record is currently
        in `SUSPENDED` status is refused with `ERR_FORBIDDEN` even on endpoints
        their role would normally reach."

        Design: Corner/rbac/suspended_entity_backed_actor_forbidden
        """
        bundle, deployment, sample = _deployment_in_debriefing(api, coordinator_headers)
        assign_debriefer(deployment["id"], bundle["debriefer"]["id"])
        validate_success(
            api.patch_debriefer(
                bundle["debriefer"]["id"], {"status": "SUSPENDED"}, admin_headers
            )
        )
        resp = api.validate_data(
            deployment["id"], {}, make_debriefer_headers(bundle["debriefer"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        current = validate_success(api.get_deployment(deployment["id"], coordinator_headers))
        assert current["status"] == "DEBRIEFING"
