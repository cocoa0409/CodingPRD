"""Policy updates and training rollouts."""
from test_helpers import (
    ApiErrorId,
    create_business_owner,
    create_control,
    create_policy_update_payload,
    department_records,
    get_control_now,
    make_business_owner_headers,
    make_manager_headers,
    make_officer_headers,
    parse_iso,
    set_clock,
    setup_published_policy,
    setup_plan,
    validate_error,
    validate_paginated,
    validate_success,
    MANAGER_1,
    OFFICER_A,
    api_client,
)


def _rollout_with_attestations(records, citation_code="CTL-RO", effective_date="2026-08-20T00:00:00Z"):
    """Published policy + rollout with the given attestation records posted."""
    owner = create_business_owner()
    pub = setup_published_policy(effective_date=effective_date, control_code=citation_code)
    rollout = pub["rollout"]
    resp = api_client.upsert_attestations(
        rollout["id"], {"records": records}, make_business_owner_headers(owner["id"])
    )
    assert resp.status_code == 200, f"Setup failed (attestations): {resp.text}"
    return owner, pub, validate_success(resp)


class TestPolicyRevisionCycle:
    def test_reject_revise_cycle_keeps_version_unset(self, api, officer_a_headers, manager_1_headers):
        """PRD §3.7: "Rejection carries a `reason`, and a rejected draft returns to
        `DRAFTING` through revision — a cycle that may repeat as often as needed."
        PRD §3.7: "The draft enters as `DRAFTING` with `drafted_by_user_id`
        stamped from the caller and `new_policy_version` unset."

        Design: Corner/state_machines/sm_policy_reject_revise_cycle
        """
        ctl = create_control(control_code="CTL-SM-6")
        resp = api.create_policy_update(
            create_policy_update_payload(control_id=ctl["id"]), officer_a_headers
        )
        update = validate_success(resp, 201)
        assert update["new_policy_version"] is None
        api.submit_policy_update(update["id"], officer_a_headers)
        resp = api.reject_policy_update(update["id"], {"reason": "Legal review failed"}, manager_1_headers)
        assert validate_success(resp)["status"] == "REJECTED"
        resp = api.revise_policy_update(update["id"], officer_a_headers)
        revised = validate_success(resp, 200)
        assert revised["status"] == "DRAFTING"
        assert revised["new_policy_version"] is None
        resp = api.submit_policy_update(update["id"], officer_a_headers)
        assert validate_success(resp)["status"] == "PENDING_APPROVAL"


class TestPolicyPlanLinkage:
    def test_plan_link_state_guard(self, api, officer_a_headers, manager_1_headers):
        """PRD §3.7: "An optional `implementation_plan_id` links the update to the
        plan it discharges; when given, that plan must stand in `APPROVED`,
        `IN_EXECUTION`, or `COMPLETED` (`ERR_INVALID_STATE` otherwise)."

        Design: Corner/endpoints/ep_policy_plan_link_state_guard
        """
        ctl = create_control(control_code="CTL-EP-4")
        pipe = setup_plan(target_status="DRAFT", citation="EP-4", criticality="CRITICAL")
        plan, owner = pipe["plan"], pipe["owner"]

        resp = api.create_policy_update(
            create_policy_update_payload(
                control_id=ctl["id"], implementation_plan_id=plan["id"], title="Too early"
            ),
            officer_a_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        api.submit_implementation_plan(plan["id"], make_business_owner_headers(owner["id"]))
        approve = api.approve_implementation_plan(plan["id"], manager_1_headers)
        assert approve.status_code == 200, f"Setup failed: {approve.text}"
        resp = api.create_policy_update(
            create_policy_update_payload(
                control_id=ctl["id"], implementation_plan_id=plan["id"], title="Now fine"
            ),
            officer_a_headers,
        )
        validate_success(resp, 201)


class TestRetract:
    def test_retract_restores_version_and_cancels_rollout(self, api, manager_1_headers):
        """PRD §3.7: "Retraction carries a `reason`, moves the update to its
        terminal `RETRACTED` state, and performs the compensating bookkeeping —
        the control's `policy_version` is restored to the snapshotted
        `new_policy_version` minus one, the control's `version` increments by one,
        and the update's in-flight training rollout is cancelled (`IN_PROGRESS` →
        `CANCELLED`)."

        Design: Corner/state_machines/sm_retract_cascades_rollout_cancel_and_version_restore
        """
        create_business_owner()
        pub = setup_published_policy(control_code="CTL-SM-10")
        assert pub["policy_update"]["status"] == "PUBLISHED"
        assert get_control_now(pub["control"]["id"])["policy_version"] == 2

        resp = api.retract_policy_update(
            pub["policy_update"]["id"], {"reason": "Regulator withdrew guidance"}, manager_1_headers
        )
        retracted = validate_success(resp, 200)
        assert retracted["status"] == "RETRACTED"
        assert get_control_now(pub["control"]["id"])["policy_version"] == 1
        rollout = validate_success(api.get_training_rollout(pub["rollout"]["id"], manager_1_headers))
        assert rollout["status"] == "CANCELLED"

    def test_retract_after_effective_date_closed(self, api, manager_1_headers):
        """PRD §3.7: "A published update can still be retracted, but only from
        `PUBLISHED` and only before it takes effect: once the logical clock
        reaches the `effective_date`, the retract window has closed
        (`ERR_RETRACT_WINDOW_CLOSED`)."

        Design: Corner/errors/err_retract_window_closed_after_effective_date
        """
        create_business_owner()
        pub = setup_published_policy(control_code="CTL-RW-1")
        set_clock("2026-08-21T00:00:00Z")
        resp = api.retract_policy_update(
            pub["policy_update"]["id"], {"reason": "too late"}, manager_1_headers
        )
        validate_error(resp, ApiErrorId.ERR_RETRACT_WINDOW_CLOSED)
        update = validate_success(api.get_policy_update(pub["policy_update"]["id"], manager_1_headers))
        assert update["status"] == "PUBLISHED"
        assert get_control_now(pub["control"]["id"])["policy_version"] == 2


class TestRolloutWindowConflict:
    def _second_approved_update(self, ctl, pu2_effective):
        """Draft + submit + approve a second update for the same control."""
        current = get_control_now(ctl["id"])
        resp = api_client.create_policy_update(
            create_policy_update_payload(control_id=ctl["id"], title="Update 2", effective_date=pu2_effective),
            make_officer_headers(OFFICER_A),
        )
        pu2 = validate_success(resp, 201)
        api_client.submit_policy_update(pu2["id"], make_officer_headers(OFFICER_A))
        resp = api_client.approve_policy_update(
            pu2["id"], {"expected_control_version": current["version"]}, make_manager_headers(MANAGER_1)
        )
        assert resp.status_code == 200, f"Setup failed: {resp.text}"
        return validate_success(resp)

    def test_publish_conflicting_window_rejected(self, api, manager_1_headers):
        """PRD §3.7: "it requires the new rollout window to be clear of siblings:
        for the same control, no non-`CANCELLED` training rollout may have a
        window lying within seven days before or after the new window, which
        spans from the publish clock to the `effective_date`
        (`ERR_ROLLOUT_WINDOW_CONFLICT`)".
        PRD §3.7: "A successful approval snapshots `new_policy_version` as the
        control's `policy_version` plus one".

        Design: Difficulty/resource_temporal_overlap/rto_rollout_windows_require_buffer
        """
        create_business_owner()
        pub = setup_published_policy(control_code="CTL-RT2")
        pu2 = self._second_approved_update(pub["control"], "2026-08-25T00:00:00Z")
        assert pu2["new_policy_version"] == 3, "Snapshot at approve: policy_version 2 + 1"
        resp = api.publish_policy_update(pu2["id"], manager_1_headers)
        validate_error(resp, ApiErrorId.ERR_ROLLOUT_WINDOW_CONFLICT)
        update = validate_success(api.get_policy_update(pu2["id"], manager_1_headers))
        assert update["status"] == "APPROVED"

    def test_publish_succeeds_after_sibling_rollout_cancelled(self, api, manager_1_headers):
        """PRD §3.7: "no non-`CANCELLED` training rollout may have a window lying
        within seven days before or after the new window".
        PRD §3.7: "On publish, the control's `policy_version` becomes the
        snapshotted `new_policy_version`".

        Design: Difficulty/resource_temporal_overlap/rto_rollout_windows_require_buffer
        """
        create_business_owner()
        pub = setup_published_policy(control_code="CTL-RT2B")
        pu2 = self._second_approved_update(pub["control"], "2026-08-25T00:00:00Z")
        retract = api.retract_policy_update(
            pub["policy_update"]["id"], {"reason": "Superseded by update 2"}, manager_1_headers
        )
        assert retract.status_code == 200, f"Setup failed: {retract.text}"
        resp = api.publish_policy_update(pu2["id"], manager_1_headers)
        published = validate_success(resp, 200)
        assert published["status"] == "PUBLISHED"
        assert get_control_now(pub["control"]["id"])["policy_version"] == 3


class TestPublishTemporalPrecedence:
    def test_short_window_beats_conflict(self, api, manager_1_headers):
        """PRD §2.10: "When a request would fail several checks at once, the
        checks are evaluated in a fixed priority order and the earliest failing
        check determines the response, so an earlier failure masks later ones".
        PRD §2.10: "Priority 6 — clock-relative temporal rules, yielding the 422
        temporal family: `ERR_DEADLINE_IN_PAST`, `ERR_DEADLINE_EXCEEDS_MANDATE`,
        `ERR_TRAINING_WINDOW_TOO_SHORT`, `ERR_RETRACT_WINDOW_CLOSED`,
        `ERR_TRAINING_WINDOW_CLOSED`, `ERR_INVALID_EXTENSION`,
        `ERR_INVALID_REPORT_PERIOD`."
        PRD §2.10: "Priority 7 — uniqueness and structural caps, yielding the 409
        constraint family: duplicate codes, duplicate mappings, existing plans or
        packages, an empty register, overlapping report windows, conflicting
        rollout windows, exhausted extensions, unmet completion thresholds, an
        empty evidence package, or a change attempting to supersede itself."

        Design: Difficulty/priority_pair_validation_conflict/pp_temporal_beats_constraint_on_publish
        """
        create_business_owner()
        pub = setup_published_policy(control_code="CTL-PP2")
        pu2 = self._conflicting_approved_update(pub["control"], "2026-08-04T00:00:00Z")
        resp = api.publish_policy_update(pu2["id"], manager_1_headers)
        validate_error(resp, ApiErrorId.ERR_TRAINING_WINDOW_TOO_SHORT)
        update = validate_success(api.get_policy_update(pu2["id"], manager_1_headers))
        assert update["status"] == "APPROVED"
        rollouts, meta = validate_paginated(
            api.list_training_rollouts(manager_1_headers, params={"control_id": pub["control"]["id"]})
        )
        assert meta["total_count"] == 1, "No second rollout created on a rejected publish"

    def test_short_window_alone_still_rejected(self, api, manager_1_headers):
        """PRD §3.7: "it requires the `effective_date` to be at least seven days
        after the current clock — otherwise `ERR_TRAINING_WINDOW_TOO_SHORT`,
        because staff are guaranteed a minimum one-week training runway".

        Design: Difficulty/priority_pair_validation_conflict/pp_temporal_beats_constraint_on_publish
        """
        create_business_owner()
        pub = setup_published_policy(control_code="CTL-PP2B")
        pu2 = self._conflicting_approved_update(pub["control"], "2026-08-04T00:00:00Z")
        # Cancel the sibling window so only the temporal rule can fire.
        retract = api.retract_policy_update(
            pub["policy_update"]["id"], {"reason": "clearing the window"}, manager_1_headers
        )
        assert retract.status_code == 200, f"Setup failed: {retract.text}"
        resp = api.publish_policy_update(pu2["id"], manager_1_headers)
        validate_error(resp, ApiErrorId.ERR_TRAINING_WINDOW_TOO_SHORT)
        update = validate_success(api.get_policy_update(pu2["id"], manager_1_headers))
        assert update["status"] == "APPROVED"

    def _conflicting_approved_update(self, ctl, effective):
        current = get_control_now(ctl["id"])
        resp = api_client.create_policy_update(
            create_policy_update_payload(control_id=ctl["id"], title="Update 2", effective_date=effective),
            make_officer_headers(OFFICER_A),
        )
        pu2 = validate_success(resp, 201)
        api_client.submit_policy_update(pu2["id"], make_officer_headers(OFFICER_A))
        resp = api_client.approve_policy_update(
            pu2["id"], {"expected_control_version": current["version"]}, make_manager_headers(MANAGER_1)
        )
        assert resp.status_code == 200, f"Setup failed: {resp.text}"
        return validate_success(resp)


class TestTrainingCompletion:
    def test_nested_rounding_yields_ninety_five(self, api):
        """PRD §3.7: "The pinned order matters: a rollout where one department
        completes 20 of 20 attestations and another completes 9 of 10 yields
        95.0 — the mean of 100.0 and 90.0 — whereas pooling all persons before
        rounding would yield 96.7, a reading the system deliberately rejects."

        Design: Difficulty/combinatorial_formula/cf_training_pct_nested_rounding
        """
        records = department_records("ENG", 20, 20, prefix="cf") + department_records("OPS", 10, 9, prefix="cf")
        _owner, _pub, rollout = _rollout_with_attestations(records, citation_code="CTL-CF-1")
        assert rollout["assigned_count"] == 30
        assert rollout["completed_count"] == 29
        assert rollout["completion_pct"] == 95.0, "(100.0 + 90.0) / 2 = 95.0; pooled would give 96.7"

    def test_complete_at_exact_threshold(self, api):
        """PRD §3.7: "The owner completes it (`IN_PROGRESS` → `COMPLETED`) only
        when `completion_pct` has reached at least 95.0
        (`ERR_COMPLETION_THRESHOLD_NOT_MET`) and the clock has not passed
        `window_end` (`ERR_TRAINING_WINDOW_CLOSED`)."

        Design: Difficulty/combinatorial_formula/cf_training_pct_nested_rounding
        """
        records = department_records("ENG", 20, 20, prefix="cf2") + department_records("OPS", 10, 9, prefix="cf2")
        owner, pub, rollout = _rollout_with_attestations(records, citation_code="CTL-CF-2")
        assert rollout["completion_pct"] == 95.0
        resp = api.complete_training_rollout(rollout["id"], make_business_owner_headers(owner["id"]))
        completed = validate_success(resp, 200)
        assert completed["status"] == "COMPLETED", "95.0 meets the inclusive threshold"

    def test_complete_at_exact_threshold_small_batch(self, api):
        """PRD §3.7: "The owner completes it (`IN_PROGRESS` → `COMPLETED`) only
        when `completion_pct` has reached at least 95.0
        (`ERR_COMPLETION_THRESHOLD_NOT_MET`)".
        PRD §3.7: "For each department, the percentage complete is rounded half-up
        to one decimal place first; only then are those rounded department
        percentages averaged — unweighted, each department counting equally".

        Design: Difficulty/boundary_precision_check/bp_rollout_complete_at_exact_threshold
        """
        records = department_records("ENG", 5, 5) + department_records("OPS", 10, 9)
        owner, _pub, rollout = _rollout_with_attestations(records, citation_code="CTL-BP1")
        assert rollout["completion_pct"] == 95.0, "(100.0 + 90.0) / 2"
        resp = api.complete_training_rollout(rollout["id"], make_business_owner_headers(owner["id"]))
        assert validate_success(resp, 200)["status"] == "COMPLETED"

    def test_complete_just_below_threshold_rejected(self, api):
        """PRD §3.7: "The owner completes it (`IN_PROGRESS` → `COMPLETED`) only
        when `completion_pct` has reached at least 95.0
        (`ERR_COMPLETION_THRESHOLD_NOT_MET`)".

        Design: Difficulty/boundary_precision_check/bp_rollout_complete_at_exact_threshold
        """
        records = department_records("ENG", 5, 5) + department_records("OPS", 10, 8)
        owner, _pub, rollout = _rollout_with_attestations(records, citation_code="CTL-BP1B")
        assert rollout["completion_pct"] == 90.0, "(100.0 + 80.0) / 2 < 95.0"
        resp = api.complete_training_rollout(rollout["id"], make_business_owner_headers(owner["id"]))
        validate_error(resp, ApiErrorId.ERR_COMPLETION_THRESHOLD_NOT_MET)
        data = validate_success(api.get_training_rollout(rollout["id"], make_business_owner_headers(owner["id"])))
        assert data["status"] == "IN_PROGRESS"

    def test_completion_threshold_not_met_error(self, api):
        """PRD §3.7: "The owner completes it (`IN_PROGRESS` → `COMPLETED`) only
        when `completion_pct` has reached at least 95.0
        (`ERR_COMPLETION_THRESHOLD_NOT_MET`)".

        Design: Corner/errors/err_completion_threshold_not_met
        """
        records = department_records("ENG", 5, 5, prefix="ct") + department_records("OPS", 10, 8, prefix="ct")
        owner, _pub, rollout = _rollout_with_attestations(records, citation_code="CTL-CT-1")
        assert rollout["completion_pct"] == 90.0
        resp = api.complete_training_rollout(rollout["id"], make_business_owner_headers(owner["id"]))
        validate_error(resp, ApiErrorId.ERR_COMPLETION_THRESHOLD_NOT_MET)
        data = validate_success(api.get_training_rollout(rollout["id"], make_business_owner_headers(owner["id"])))
        assert data["status"] == "IN_PROGRESS"

    def test_exception_threshold_not_met(self, api, manager_1_headers):
        """PRD §3.7: "Alternatively, a `ComplianceManager` closes it with
        exceptions (`IN_PROGRESS` → `CLOSED_WITH_EXCEPTIONS`) once
        `completion_pct` is at least 80.0 (`ERR_EXCEPTION_THRESHOLD_NOT_MET`),
        recording an `exception_rationale`."

        Design: Corner/errors/err_exception_threshold_not_met
        """
        records = department_records("ENG", 10, 5, prefix="et")
        _owner, _pub, rollout = _rollout_with_attestations(records, citation_code="CTL-ET-1")
        assert rollout["completion_pct"] == 50.0
        resp = api.close_training_rollout_with_exceptions(
            rollout["id"], {"exception_rationale": "Half the department on leave"}, manager_1_headers
        )
        validate_error(resp, ApiErrorId.ERR_EXCEPTION_THRESHOLD_NOT_MET)
        data = validate_success(api.get_training_rollout(rollout["id"], manager_1_headers))
        assert data["status"] == "IN_PROGRESS"


class TestRolloutWindowsAndStates:
    def test_attestation_upsert_idempotent_by_person_ref(self, api):
        """PRD §3.7: "items are upserted keyed by `person_ref`, so re-posting the
        same person updates their record — refreshing its `updated_at` — and
        never duplicates it."
        PRD §3.7: "`assigned_count` is the number of distinct `person_ref`
        entries in `attestation_records`, `completed_count` is how many of those
        records are flagged complete".

        Design: Corner/endpoints/ep_attestation_upsert_idempotent_by_person_ref
        """
        owner = create_business_owner()
        pub = setup_published_policy(control_code="CTL-EP-2")
        rollout = pub["rollout"]
        assert rollout["status"] == "IN_PROGRESS"
        owner_headers = make_business_owner_headers(owner["id"])
        first = api.upsert_attestations(
            rollout["id"],
            {"records": [
                {"person_ref": "p1", "department": "ENG", "completed": True},
                {"person_ref": "p2", "department": "ENG", "completed": True},
            ]},
            owner_headers,
        )
        data = validate_success(first, 200)
        assert data["assigned_count"] == 2 and data["completed_count"] == 2

        second = api.upsert_attestations(
            rollout["id"],
            {"records": [{"person_ref": "p1", "department": "ENG", "completed": False}]},
            owner_headers,
        )
        data = validate_success(second, 200)
        assert data["assigned_count"] == 2, "Re-posting p1 must not duplicate"
        assert data["completed_count"] == 1
        assert data["completion_pct"] == 50.0

    def test_attest_on_completed_rollout_rejected(self, api):
        """PRD §3.7: "Posting attestations to a rollout that no longer stands
        `IN_PROGRESS` is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/sm_attest_terminal_rollout_rejected
        """
        records = department_records("ENG", 5, 5)
        owner, _pub, rollout = _rollout_with_attestations(records, citation_code="CTL-SM-9")
        owner_headers = make_business_owner_headers(owner["id"])
        complete = api.complete_training_rollout(rollout["id"], owner_headers)
        assert complete.status_code == 200, f"Setup failed: {complete.text}"
        resp = api.upsert_attestations(
            rollout["id"],
            {"records": [{"person_ref": "a06", "department": "ENG", "completed": True}]},
            owner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        data = validate_success(api.get_training_rollout(rollout["id"], owner_headers))
        assert data["completed_count"] == 5

    def test_complete_after_window_closed(self, api):
        """PRD §3.7: "the clock has not passed `window_end`
        (`ERR_TRAINING_WINDOW_CLOSED`)".
        PRD §3.7: "whose training window runs from `window_start` equal to the
        publish timestamp to `window_end` equal to the `effective_date`".
        PRD §3.7: "The rollout also tracks `past_due`, true when the logical
        clock has passed `window_end` while the rollout still stands
        `IN_PROGRESS`."

        Design: Corner/errors/err_training_window_closed_blocks_complete
        """
        records = department_records("ENG", 5, 5, prefix="tw")
        owner, pub, rollout = _rollout_with_attestations(records, citation_code="CTL-TW-1")
        assert parse_iso(rollout["window_start"]) == parse_iso("2026-08-01T00:00:00Z")
        assert parse_iso(rollout["window_end"]) == parse_iso("2026-08-20T00:00:00Z")
        assert rollout["completion_pct"] == 100.0
        set_clock("2026-08-21T00:00:00Z")
        resp = api.complete_training_rollout(rollout["id"], make_business_owner_headers(owner["id"]))
        validate_error(resp, ApiErrorId.ERR_TRAINING_WINDOW_CLOSED)
        data = validate_success(api.get_training_rollout(rollout["id"], make_business_owner_headers(owner["id"])))
        assert data["past_due"] is True
        assert data["status"] == "IN_PROGRESS"
