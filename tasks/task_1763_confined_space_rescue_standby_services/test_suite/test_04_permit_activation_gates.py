"""Entry-permit creation gates and the activation safety chain
(PRD §2.6, §3.3)."""
from test_helpers import (
    OPS,
    ApiErrorId,
    approve_plan,
    cancel_permit,
    create_account,
    create_ops_team,
    create_permit,
    create_plan,
    create_space,
    issue_permit,
    post_reading,
    read_permit,
    read_space,
    schedule_standby,
    set_clock,
    setup_issued_permit,
    standby_checkin,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPermitCreationGates:
    def test_space_occupied_on_create(self, api):
        """PRD §3.3: "no other permit of the same space may currently be in
        `ISSUED`, `ACTIVE`, or `SUSPENDED`, otherwise `ERR_SPACE_OCCUPIED`".

        Design: Corner/validations/corner_space_occupied_on_create
        """
        team = create_ops_team()
        set_clock("2026-08-03T06:00:00Z")
        account = create_account(name="Occupy Co")
        space = create_space(account["id"], space_code="TK-OC")
        permit_a = create_permit(space["id"], team["supervisor_headers"],
                                 purpose="First",
                                 planned_start_at="2026-08-03T06:00:00Z",
                                 planned_end_at="2026-08-03T20:00:00Z")
        issue_permit(permit_a["id"], team["supervisor_headers"])

        # The OCC version is fresh: only the occupancy gate can fail.
        fresh_version = read_space(space["id"])["version"]
        resp = api.create_entry_permit(
            space["id"],
            {"purpose": "Second",
             "planned_start_at": "2026-08-03T06:00:00Z",
             "planned_end_at": "2026-08-03T20:00:00Z",
             "expected_space_version": fresh_version},
            team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_SPACE_OCCUPIED)
        assert resp.status_code == 409

        permits, meta = validate_paginated(
            api.list_entry_permits(OPS, params={"space_id": space["id"]}))
        assert meta["total_count"] == 1 and permits[0]["id"] == permit_a["id"]

    def test_space_out_of_service_blocks_create(self, api):
        """PRD §3.3: "the space must be `AVAILABLE`, otherwise
        `ERR_SPACE_OUT_OF_SERVICE`".
        PRD §3.1: "Space records can later be updated — reclassification,
        capacity changes, monitoring-flag changes, or a status toggle — by an
        `OperationsManager` or `SafetyOfficer` carrying
        `expected_space_version`, and each successful update increments the
        space's `version`."

        Design: Corner/errors/corner_space_out_of_service_blocks_create
        """
        team = create_ops_team()
        set_clock("2026-08-03T06:00:00Z")
        account = create_account(name="OOS Co")
        space = create_space(account["id"], space_code="TK-OOS")

        patched = validate_success(api.patch_confined_space(
            space["id"], {"status": "OUT_OF_SERVICE",
                          "expected_space_version": space["version"]},
            team["officer_headers"]))
        assert patched["status"] == "OUT_OF_SERVICE", (
            "with no non-terminal permits the toggle succeeds")

        resp = api.create_entry_permit(
            space["id"],
            {"purpose": "Blocked job",
             "planned_start_at": "2026-08-03T06:00:00Z",
             "planned_end_at": "2026-08-03T20:00:00Z",
             "expected_space_version": patched["version"]},
            team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_SPACE_OUT_OF_SERVICE)
        assert resp.status_code == 409

    def test_non_permit_space_rejected(self, api):
        """PRD §3.3: "the space must be classified `PERMIT_REQUIRED` or
        `PERMIT_REQUIRED_HAZARDOUS` — a permit on a `NON_PERMIT` space is
        rejected with `ERR_SPACE_NOT_PERMIT_REQUIRED`".

        Design: Corner/errors/corner_non_permit_space_rejected
        """
        team = create_ops_team()
        set_clock("2026-08-03T06:00:00Z")
        account = create_account(name="NP Co")
        space = create_space(account["id"], space_code="TK-NP",
                             classification="NON_PERMIT")
        resp = api.create_entry_permit(
            space["id"],
            {"purpose": "NP job",
             "planned_start_at": "2026-08-03T06:00:00Z",
             "planned_end_at": "2026-08-03T20:00:00Z",
             "expected_space_version": space["version"]},
            team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_SPACE_NOT_PERMIT_REQUIRED)
        assert resp.status_code == 422
        _, meta = validate_paginated(
            api.list_entry_permits(OPS, params={"space_id": space["id"]}))
        assert meta["total_count"] == 0


class TestActivationSafetyChain:
    def test_activate_draft_permit_reports_state_error_not_safety(self, api):
        """PRD §2.6: "Every mutation request passes through a fixed pipeline
        of validation categories, evaluated in priority order so that earlier
        failures mask later ones." and "Only after these come
        optimistic-concurrency checks, state-transition legality, and then the
        domain safety, capacity, temporal, qualification, and fiscal gates
        described throughout §3."
        PRD §3.3: "Activation moves `ISSUED` to `ACTIVE` and is the most
        heavily guarded transition in the system."

        Design: Difficulty/priority_pair_validation_conflict/activate_state_error_precedes_safety_error
        """
        team = create_ops_team()
        set_clock("2026-08-03T06:00:00Z")
        account = create_account(name="Prio Co")
        space = create_space(account["id"], space_code="TK-P")
        # Permit left in DRAFT (never issued) AND no rescue plan exists at
        # all: both a state failure and a safety failure are present.
        permit = create_permit(space["id"], team["supervisor_headers"],
                               purpose="Prio job")
        assert permit["status"] == "DRAFT"

        resp = api.activate_permit(permit["id"], team["supervisor_headers"])
        err = validate_error(resp, ApiErrorId.ERR_PERMIT_INVALID_STATE)
        assert resp.status_code == 409
        assert err["error_id"] != "ERR_RESCUE_PLAN_NOT_APPROVED", (
            "state-transition legality is evaluated before the safety chain")
        assert read_permit(permit["id"])["status"] == "DRAFT"

    def test_activate_issued_permit_without_plan_reports_safety_error(self, api):
        """PRD §3.3: "The safety chain is evaluated in a fixed order: first,
        an `APPROVED` rescue plan must exist for the space
        (`ERR_RESCUE_PLAN_NOT_APPROVED`)".

        Design: Difficulty/priority_pair_validation_conflict/activate_state_error_precedes_safety_error
        """
        # The state check passes (permit ISSUED), so the isolated safety
        # failure surfaces.
        ctx = setup_issued_permit(at="2026-08-03T05:30:00Z", with_plan=False)
        post_reading(ctx["permit"]["id"], ctx["team"]["attendant_headers"],
                     reading_kind="PRE_ENTRY")
        resp = api.activate_permit(ctx["permit"]["id"],
                                   ctx["team"]["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_RESCUE_PLAN_NOT_APPROVED)
        assert resp.status_code == 409
        assert read_permit(ctx["permit"]["id"])["status"] == "ISSUED"

    def test_activation_blocked_while_plan_draft(self, api):
        """PRD §3.3: "The safety chain is evaluated in a fixed order: first,
        an `APPROVED` rescue plan must exist for the space
        (`ERR_RESCUE_PLAN_NOT_APPROVED`)".
        PRD §3.2: "A plan begins in `DRAFT` and becomes effective only when a
        `RescueTeamLead` approves it".

        Design: Difficulty/cross_entity_state_dependency/permit_activation_gated_by_plan_approval
        """
        ctx = setup_issued_permit(at="2026-08-03T05:30:00Z", with_plan=False)
        team = ctx["team"]
        # The space's only plan stays DRAFT.
        create_plan(ctx["space"]["id"], team["lead_headers"])
        post_reading(ctx["permit"]["id"], team["attendant_headers"],
                     reading_kind="PRE_ENTRY")

        resp = api.activate_permit(ctx["permit"]["id"],
                                   team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_RESCUE_PLAN_NOT_APPROVED)
        assert read_permit(ctx["permit"]["id"])["status"] == "ISSUED", (
            "a rejected activation leaves the permit ISSUED")

    def test_activation_succeeds_after_plan_approval(self, api):
        """PRD §3.3: "The safety chain is evaluated in a fixed order: first,
        an `APPROVED` rescue plan must exist for the space
        (`ERR_RESCUE_PLAN_NOT_APPROVED`)" and "Successful activation stamps
        `actual_entry_at` with the current logical time and increments the
        permit's `version`."
        PRD §3.5: "Scheduling requires an `APPROVED` rescue plan for the space
        (`ERR_RESCUE_PLAN_NOT_APPROVED`)".

        Design: Difficulty/cross_entity_state_dependency/permit_activation_gated_by_plan_approval
        """
        ctx = setup_issued_permit(at="2026-08-03T05:30:00Z", with_plan=False)
        team = ctx["team"]
        plan = create_plan(ctx["space"]["id"], team["lead_headers"])
        approve_plan(ctx["space"]["id"], plan["id"], team["lead_headers"])
        post_reading(ctx["permit"]["id"], team["attendant_headers"],
                     reading_kind="PRE_ENTRY")
        # Standby scheduling is itself gated on the approved plan, so it is
        # only possible after approval.
        standby = schedule_standby(ctx["permit"]["id"], team["lead_headers"],
                                   team["rescuer"]["id"])
        standby_checkin(standby["id"], team["lead_headers"])

        activated = validate_success(
            api.activate_permit(ctx["permit"]["id"],
                                team["supervisor_headers"]))
        assert activated["status"] == "ACTIVE"
        assert activated["actual_entry_at"] is not None

    def test_understaffed_activation_rejected(self, api):
        """PRD §3.3: "fifth, standby coverage at the activation instant —
        assignments in `SCHEDULED` or `ON_STANDBY` whose half-open window
        `[standby_start_at, standby_end_at)` contains now — must be at least
        the approved plan's `required_team_size`
        (`ERR_RESCUE_TEAM_UNDERSTAFFED`)".

        Design: Corner/validations/corner_understaffed_activation_rejected
        """
        ctx = setup_issued_permit(at="2026-08-03T05:30:00Z")
        post_reading(ctx["permit"]["id"], ctx["team"]["attendant_headers"],
                     reading_kind="PRE_ENTRY")
        # No standby assignment exists: coverage 0 < required_team_size 1.
        resp = api.activate_permit(ctx["permit"]["id"],
                                   ctx["team"]["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_RESCUE_TEAM_UNDERSTAFFED)
        assert read_permit(ctx["permit"]["id"])["status"] == "ISSUED"

    def test_activate_outside_planned_window(self, api):
        """PRD §3.3: "sixth, now must fall within the planned window, at or
        after `planned_start_at` and at or before `planned_end_at`
        (`ERR_OUTSIDE_PLANNED_WINDOW`)".

        Design: Corner/errors/corner_activate_outside_planned_window
        """
        ctx = setup_issued_permit(at="2026-08-03T05:30:00Z",
                                  planned_start_at="2026-08-03T05:00:00Z",
                                  planned_end_at="2026-08-03T06:00:00Z")
        team = ctx["team"]
        standby = schedule_standby(ctx["permit"]["id"], team["lead_headers"],
                                   team["rescuer"]["id"])
        standby_checkin(standby["id"], team["lead_headers"])
        # Move past the planned window, then post a fresh reading so checks
        # (a)-(e) all pass and only the window gate fails.
        set_clock("2026-08-03T07:00:00Z")
        post_reading(ctx["permit"]["id"], team["attendant_headers"],
                     reading_kind="PRE_ENTRY")
        resp = api.activate_permit(ctx["permit"]["id"],
                                   team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_PLANNED_WINDOW)
        assert read_permit(ctx["permit"]["id"])["status"] == "ISSUED"

    def test_atmosphere_out_of_limits_on_activate(self, api):
        """PRD §3.3: "third, the latest `PRE_ENTRY` reading for the permit
        must exist and be within limits (`ERR_ATMOSPHERE_OUT_OF_LIMITS`)".
        PRD §3.6: "computes `within_limits`: true exactly when `o2_pct` is at
        least 19.5 and at most 23.5, `lel_pct` is at most 10, `h2s_ppm` is at
        most 10, and `co_ppm` is at most 35 — all bounds inclusive."

        Design: Corner/errors/corner_atmosphere_out_of_limits_on_activate
        """
        ctx = setup_issued_permit(at="2026-08-03T05:30:00Z")
        team = ctx["team"]
        # Plausible but out of limits: o2 24.0 > 23.5.
        reading = post_reading(ctx["permit"]["id"], team["attendant_headers"],
                               reading_kind="PRE_ENTRY", o2_pct=24.0)
        assert reading["within_limits"] is False
        standby = schedule_standby(ctx["permit"]["id"], team["lead_headers"],
                                   team["rescuer"]["id"])
        standby_checkin(standby["id"], team["lead_headers"])

        resp = api.activate_permit(ctx["permit"]["id"],
                                   team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_ATMOSPHERE_OUT_OF_LIMITS)
        assert read_permit(ctx["permit"]["id"])["status"] == "ISSUED", (
            "a PRE_ENTRY reading on an ISSUED permit does not fire the alarm "
            "cascade, which is defined only for CONTINUOUS readings on an "
            "ACTIVE permit")


class TestTerminalLockdown:
    def test_permit_terminal_lockdown(self, api):
        """PRD §3.5: "Manual cancellation is available from `DRAFT`, `ISSUED`,
        `ACTIVE`, or `SUSPENDED` (any other state is
        `ERR_PERMIT_INVALID_STATE`)"; "Orderly closure moves a permit from
        `ACTIVE` or `SUSPENDED` to `CLOSED` with `close_reason` `COMPLETED` and
        `closed_at` stamped."; "Resumption — re-entry authorization from
        `SUSPENDED` back to `ACTIVE` by an `EntrySupervisor` — reruns the
        safety chain in order".

        Design: Corner/state_machines/corner_permit_terminal_lockdown
        """
        team = create_ops_team()
        set_clock("2026-08-03T06:00:00Z")
        account = create_account(name="Terminal Co")
        space = create_space(account["id"], space_code="TK-T")
        permit = create_permit(space["id"], team["supervisor_headers"],
                               purpose="Terminal job")
        cancelled = cancel_permit(permit["id"], team["supervisor_headers"])
        assert cancelled["status"] == "CANCELLED"

        for action in (api.resume_permit, api.close_permit,
                       api.activate_permit, api.cancel_permit):
            resp = action(permit["id"], team["supervisor_headers"])
            err = validate_error(resp, ApiErrorId.ERR_PERMIT_INVALID_STATE)
            assert resp.status_code == 409, (
                f"{action.__name__} on a CANCELLED permit must fail with 409: "
                f"{err}")
        assert read_permit(permit["id"])["status"] == "CANCELLED"
