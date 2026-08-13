"""SWPPP plans, inspections and BMP corrective actions: activation with OCC,
inspection spacing and findings cascade, the six-state corrective-action loop
with reopen compensation (PRD §2.7, §3.6)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    activate_swppp_plan,
    assert_corrective_action,
    assert_instant_equals,
    assert_inspection,
    assert_swppp_plan,
    create_active_permit,
    create_active_plan,
    create_exceedance_scenario,
    create_inspection,
    create_permit,
    create_swppp_plan,
    drive_corrective_action_to_verified,
    get_corrective_action,
    get_permit_state,
    get_permit_version,
    make_facility_inspector_headers,
    make_regulator_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers.fixtures import FI

ANY_HEADERS = TEST_USERS["regulator_headers"]  # reads are open to every role (PRD §2.1)

class TestPlanActivation:
    def test_swppp_activate_success_supersedes_prior_plan(self, api):
        """PRD §3.6: "Activation moves the plan `DRAFT → ACTIVE`, and because a
        permit operates under exactly one active plan, any other plan of the same
        permit currently `ACTIVE` flips to `SUPERSEDED` with a `PLAN_SUPERSEDED`
        audit entry; the permit's own `version` increments, and `PLAN_ACTIVATED`
        is appended."

        Design: Corner/state_machines/swppp_activate_success_supersedes_prior_plan
        """
        env = create_active_permit(permit_number="NPDES-SM25")
        plan_a = create_active_plan(
            env["permit"]["id"], plan_title="Plan A", version_label="rev-A"
        )
        plan_b = create_swppp_plan(
            env["permit"]["id"], plan_title="Plan B", version_label="rev-B",
            inspection_frequency_days=14,
        )
        version_before = get_permit_version(env["permit"]["id"])

        activated = activate_swppp_plan(plan_b["id"])
        assert_swppp_plan(activated)
        assert activated["status"] == "ACTIVE"
        old = validate_success(api.get_swppp_plan(plan_a["id"], ANY_HEADERS))
        assert old["status"] == "SUPERSEDED"
        assert get_permit_version(env["permit"]["id"]) == version_before + 1, (
            "activation increments the permit's version"
        )

    def test_swppp_activate_from_active_rejected(self, api):
        """PRD §3.6: "Activation publishes the plan: it requires the plan in `DRAFT`
        (`ERR_PLAN_NOT_DRAFT`)".

        Design: Corner/state_machines/swppp_activate_from_active_rejected
        """
        env = create_active_permit(permit_number="NPDES-SM26")
        plan = create_active_plan(env["permit"]["id"], plan_title="Plan A")

        resp = api.activate_swppp_plan(
            plan["id"],
            {"expected_permit_version": get_permit_version(env["permit"]["id"])},
            FI,
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_DRAFT)

    def test_occ_swppp_activate_stale_permit_version(self, api):
        """PRD §2.7: "Activating a stormwater plan requires the request to carry
        `expected_permit_version`, set to the `version` of the parent permit as last
        observed. Activation supersedes the permit's currently `ACTIVE` plan and
        increments the permit's `version`; a caller whose observed version predates
        the most recent activation is superseding a plan it never saw, and is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_swppp_activate_stale_permit_version
        """
        env = create_active_permit(permit_number="NPDES-OCC2")
        stale_version = get_permit_version(env["permit"]["id"])
        create_active_plan(env["permit"]["id"], plan_title="Plan A")  # bumps permit version
        assert get_permit_version(env["permit"]["id"]) != stale_version
        plan_b = create_swppp_plan(env["permit"]["id"], plan_title="Plan B",
                                   version_label="rev-B", inspection_frequency_days=14)

        resp = api.activate_swppp_plan(
            plan_b["id"], {"expected_permit_version": stale_version}, FI
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_error_plan_not_found_on_activate(self, api):
        """PRD §2.8: "The first identifier that does not resolve yields the
        corresponding 404: the resource-specific ... `ERR_PLAN_NOT_FOUND` ..."
        (existence is rung 3, ahead of the optimistic-concurrency rung 5).

        Design: Corner/errors/error_plan_not_found_on_activate
        """
        permit = create_permit(permit_number="NPDES-ERR13")
        resp = api.activate_swppp_plan(
            NON_EXISTENT_UUID,
            {"expected_permit_version": permit["version"]},
            FI,
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_FOUND)

class TestInspections:
    def test_inspection_spacing_buffer_semantics(self, api):
        """PRD §3.6: "A spacing rule protects inspection independence: no other
        inspection of the same plan that is not `CANCELLED` may be scheduled
        strictly less than 7 days away from the new one — a gap of exactly 7 days
        is allowed. Violations are rejected with `ERR_INSPECTION_TOO_SOON`."

        Design: Corner/calculations/inspection_spacing_buffer_semantics
        """
        env = create_active_permit(permit_number="NPDES-CALC9")
        plan = create_active_plan(env["permit"]["id"], inspection_frequency_days=7)
        create_inspection(plan["id"], "2026-08-10T08:00:00Z")

        resp = api.create_inspection(
            {"plan_id": plan["id"], "scheduled_for": "2026-08-16T08:00:00Z"}, FI
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_TOO_SOON)  # 6-day gap

        accepted = validate_success(
            api.create_inspection(
                {"plan_id": plan["id"], "scheduled_for": "2026-08-17T08:00:00Z"}, FI
            ),
            expected_status=201,
        )
        assert_inspection(accepted)
        assert accepted["status"] == "SCHEDULED", "exactly 7 days is allowed"

    def test_inspection_complete_creates_corrective_actions_per_finding(self, api):
        """PRD §3.6: "Completion stamps `completed_at` with the logical clock, moves
        the inspection `SCHEDULED → COMPLETED`, and then, for each finding, creates
        a CorrectiveAction with `source_type` `INSPECTION`, `inspection_id` set, the
        finding's description and severity, and status `OPEN`; each such creation
        increments the parent permit's `open_corrective_action_count` and recomputes
        its posture, so a permit with no other enforcement pressure moves
        `GOOD_STANDING → UNDER_CORRECTIVE_ACTION` on the first finding."

        Design: Corner/state_machines/inspection_complete_creates_corrective_actions_per_finding
        """
        env = create_active_permit(permit_number="NPDES-SM27")
        plan = create_active_plan(env["permit"]["id"], inspection_frequency_days=7)
        inspection = create_inspection(plan["id"], "2026-08-10T08:00:00Z")

        set_clock("2026-08-10T09:00:00Z")
        completed = validate_success(api.complete_inspection(
            inspection["id"],
            {"findings": [
                {"description": "torn silt fence", "severity": "MAJOR"},
                {"description": "uncapped stockpile", "severity": "MINOR"},
            ]},
            make_facility_inspector_headers("fi-1"),
        ))
        assert completed["status"] == "COMPLETED"
        assert_instant_equals(completed["completed_at"], "2026-08-10T09:00:00Z", "completed_at")

        actions, meta = validate_paginated(
            api.list_corrective_actions(
                ANY_HEADERS, params={"inspection_id": inspection["id"]}
            )
        )
        assert len(actions) == 2 and meta["total_count"] == 2
        assert {a["severity"] for a in actions} == {"MAJOR", "MINOR"}
        for action in actions:
            assert_corrective_action(action)
            assert action["source_type"] == "INSPECTION"
            assert action["inspection_id"] == inspection["id"]
            assert action["status"] == "OPEN"

        permit = get_permit_state(env["permit"]["id"])
        assert permit["open_corrective_action_count"] == 2
        assert permit["compliance_posture"] == "UNDER_CORRECTIVE_ACTION"

    def test_inspection_complete_on_cancelled_rejected(self, api):
        """PRD §3.6: "Completion requires the inspection `SCHEDULED`
        (`ERR_INSPECTION_NOT_SCHEDULED`)".

        Design: Corner/state_machines/inspection_complete_on_cancelled_rejected
        """
        env = create_active_permit(permit_number="NPDES-SM28")
        plan = create_active_plan(env["permit"]["id"], inspection_frequency_days=7)
        inspection = create_inspection(plan["id"], "2026-08-10T08:00:00Z")
        validate_success(api.cancel_inspection(inspection["id"], FI))

        resp = api.complete_inspection(inspection["id"], {"findings": []}, FI)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_SCHEDULED)

    def test_error_plan_not_active_on_inspection_complete(self, api):
        """PRD §3.6: "Completion requires the inspection `SCHEDULED`
        (`ERR_INSPECTION_NOT_SCHEDULED`) and its parent plan `ACTIVE`
        (`ERR_PLAN_NOT_ACTIVE`)."

        Design: Corner/errors/error_plan_not_active_on_inspection_complete
        """
        env = create_active_permit(permit_number="NPDES-ERR7")
        plan = create_swppp_plan(env["permit"]["id"], plan_title="Draft Plan",
                                 version_label="rev-0", inspection_frequency_days=7)
        inspection = create_inspection(plan["id"], "2026-08-10T08:00:00Z")

        resp = api.complete_inspection(inspection["id"], {"findings": []}, FI)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)

    def test_error_inspection_not_found_on_complete(self, api):
        """PRD §2.8: "The first identifier that does not resolve yields the
        corresponding 404: the resource-specific ... `ERR_INSPECTION_NOT_FOUND` ..."

        Design: Corner/errors/error_inspection_not_found_on_complete
        """
        resp = api.complete_inspection(NON_EXISTENT_UUID, {"findings": []}, FI)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_FOUND)

class TestCorrectiveActionLoop:
    def test_corrective_action_full_lifecycle_and_reopen_loop(self, api):
        """PRD §3.6: "A `Regulator` may instead reopen a `VERIFIED` action, supplying
        a `reason`: the action returns to `REOPENED`, `verified_by_user_id`,
        `resolved_at`, `resolved_by_user_id` and `actual_cost_cents` are all cleared
        to null, the action re-enters the permit's open set with count and posture
        recomputed, and `CA_REOPENED` is appended."
        PRD §3.6: "From `VERIFIED` a `FacilityInspector` closes the action into its
        terminal `CLOSED` state (`CA_CLOSED`)."

        Design: Corner/state_machines/corrective_action_full_lifecycle_and_reopen_loop
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-SM29")
        ca_id = scenario["corrective_action"]["id"]

        validate_success(api.start_corrective_action(ca_id, FI))
        validate_success(api.complete_corrective_action(
            ca_id, {"actual_cost_cents": 4000}, make_facility_inspector_headers("fi-1")
        ))
        validate_success(api.verify_corrective_action(
            ca_id, make_regulator_headers("reg-1")
        ))
        assert get_permit_state(scenario["permit"]["id"])["open_corrective_action_count"] == 0

        reopened = validate_success(api.reopen_corrective_action(
            ca_id, {"reason": "fix failed re-inspection"}, make_regulator_headers("reg-1")
        ))
        assert reopened["status"] == "REOPENED"
        assert reopened["resolved_by_user_id"] is None
        assert reopened["verified_by_user_id"] is None
        assert reopened["resolved_at"] is None
        assert reopened["actual_cost_cents"] is None
        assert get_permit_state(scenario["permit"]["id"])["open_corrective_action_count"] == 1, (
            "the reopened action re-enters the permit's open set"
        )

        validate_success(api.start_corrective_action(ca_id, FI))
        validate_success(api.complete_corrective_action(
            ca_id, {"actual_cost_cents": 6000}, make_facility_inspector_headers("fi-1")
        ))
        validate_success(api.verify_corrective_action(ca_id, make_regulator_headers("reg-1")))
        closed = validate_success(api.close_corrective_action(ca_id, FI))
        assert closed["status"] == "CLOSED", "terminal state"

    def test_corrective_action_start_from_completed_rejected(self, api):
        """PRD §3.6: "A `FacilityInspector` starts work from `OPEN` or `REOPENED` —
        from any other status the request fails with
        `ERR_CORRECTIVE_ACTION_INVALID_STATE`".

        Design: Corner/state_machines/corrective_action_start_from_completed_rejected
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-SM30")
        ca_id = scenario["corrective_action"]["id"]
        validate_success(api.start_corrective_action(ca_id, FI))
        validate_success(api.complete_corrective_action(
            ca_id, {"actual_cost_cents": 4000}, make_facility_inspector_headers("fi-1")
        ))

        resp = api.start_corrective_action(ca_id, FI)
        validate_error(resp, ApiErrorId.ERR_CORRECTIVE_ACTION_INVALID_STATE)

    def test_corrective_action_deadline_and_overdue_flag(self, api):
        """PRD §3.6: "Every corrective action — inspection-sourced or
        exceedance-sourced — gets its deadline from its severity at creation:
        `deadline_at` is `created_at` plus 7 days for `CRITICAL`, plus 30 days for
        `MAJOR`, plus 90 days for `MINOR`. An action's `is_overdue` flag is true
        whenever it sits in `OPEN`, `IN_PROGRESS` or `REOPENED` and the logical
        clock is strictly past the deadline; sitting exactly at the deadline is not
        overdue."

        Design: Corner/calculations/corrective_action_deadline_and_overdue_flag
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-CALC5")
        ca = scenario["corrective_action"]  # exceedance-sourced: always MAJOR
        assert ca["severity"] == "MAJOR"
        assert ca["status"] == "OPEN"
        assert_instant_equals(ca["created_at"], "2026-08-05T10:00:00Z", "created_at")
        assert_instant_equals(ca["deadline_at"], "2026-09-04T10:00:00Z",
                              "deadline_at == created_at + 30 days (MAJOR)")
        assert ca["is_overdue"] is False

        set_clock("2026-09-04T10:00:00Z")  # exactly at the deadline
        at_deadline = get_corrective_action(ca["id"])
        assert at_deadline["is_overdue"] is False, "exactly at the deadline is not overdue"

        set_clock("2026-09-04T10:00:01Z")  # strictly past
        past_deadline = get_corrective_action(ca["id"])
        assert past_deadline["is_overdue"] is True

    def test_derived_counters_reconciled_on_verify_compensation(self, api):
        """PRD §3.6: "the action moves to `VERIFIED`, records `verified_by_user_id`,
        leaves the permit's open set — the permit's `open_corrective_action_count`
        is recomputed and its posture may revert from `UNDER_CORRECTIVE_ACTION`
        back to `GOOD_STANDING`".

        Design: Corner/consistency_model/derived_counters_reconciled_on_verify_compensation
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-CON2")
        permit_before = get_permit_state(scenario["permit"]["id"])
        assert permit_before["open_corrective_action_count"] == 1
        assert permit_before["compliance_posture"] == "UNDER_CORRECTIVE_ACTION"

        verified = drive_corrective_action_to_verified(
            scenario["corrective_action"]["id"], actual_cost_cents=5000
        )
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == "reg-1"

        permit_after = get_permit_state(scenario["permit"]["id"])
        assert permit_after["open_corrective_action_count"] == 0
        assert permit_after["compliance_posture"] == "GOOD_STANDING"

    def test_sod_corrective_action_verifier_must_differ_from_resolver(self, api):
        """PRD §2.11: "A corrective action may not be verified by the person who
        marked it complete — the verifier's identifier must differ from
        `resolved_by_user_id`."

        Design: Corner/rbac/sod_corrective_action_verifier_must_differ_from_resolver
        """
        scenario = create_exceedance_scenario(permit_number="NPDES-RBAC7")
        ca_id = scenario["corrective_action"]["id"]
        validate_success(api.start_corrective_action(
            ca_id, make_facility_inspector_headers("fi-1")
        ))
        validate_success(api.complete_corrective_action(
            ca_id, {"actual_cost_cents": 4000}, make_facility_inspector_headers("fi-1")
        ))

        # Right role (Regulator) but the same operator id as the resolver.
        resp = api.verify_corrective_action(ca_id, make_regulator_headers("fi-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_error_corrective_action_not_found_on_start(self, api):
        """PRD §2.8: "The first identifier that does not resolve yields the
        corresponding 404: the resource-specific ...
        `ERR_CORRECTIVE_ACTION_NOT_FOUND` ..."

        Design: Corner/errors/error_corrective_action_not_found_on_start
        """
        resp = api.start_corrective_action(NON_EXISTENT_UUID, FI)
        validate_error(resp, ApiErrorId.ERR_CORRECTIVE_ACTION_NOT_FOUND)
