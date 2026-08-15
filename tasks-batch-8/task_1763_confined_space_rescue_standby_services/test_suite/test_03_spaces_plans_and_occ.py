"""Space registry, rescue-plan lineage, and optimistic concurrency
(PRD §2.7, §3.1, §3.2)."""
from test_helpers import (
    OPS,
    ApiErrorId,
    approve_plan,
    create_account,
    create_confined_space_payload,
    create_ops_team,
    create_permit,
    create_plan,
    create_rescue_plan_payload,
    create_space,
    read_space,
    set_clock,
    setup_issued_permit,
    submit_isolation,
    validate_error,
    validate_success,
    verify_isolation_record,
)


class TestPlanLineage:
    def test_plan_supersede_on_create(self, api):
        """PRD §3.2: "Each plan receives a per-space monotonically increasing
        `plan_revision` — the first plan created for a space is revision 1, and
        each subsequent creation takes the prior maximum revision plus one.
        Creating a new plan supersedes any existing `DRAFT` plans of the same
        space, moving them to `SUPERSEDED`, and increments the space's
        `version`."

        Design: Corner/state_machines/corner_plan_supersede_on_create
        """
        team = create_ops_team()
        set_clock("2026-08-03T06:00:00Z")
        account = create_account(name="Supersede Co")
        space = create_space(account["id"], space_code="TK-SP")
        v0 = space["version"]

        plan1 = create_plan(space["id"], team["lead_headers"],
                            required_team_size=1)
        v1 = read_space(space["id"])["version"]
        assert v1 == v0 + 1, "plan creation increments the space version by 1"

        plan2 = create_plan(space["id"], team["lead_headers"],
                            required_team_size=2,
                            required_certifications=["CONFINED_SPACE_RESCUE",
                                                     "HIGH_ANGLE"],
                            retrieval_system_type="MECHANICAL_RETRIEVAL")
        v2 = read_space(space["id"])["version"]
        assert v2 == v1 + 1, "each create advances the space version by 1"

        assert plan1["plan_revision"] == 1
        assert plan2["plan_revision"] == 2
        assert plan2["status"] == "DRAFT"
        plan1_after = validate_success(api.get_rescue_plan(plan1["id"], OPS))
        assert plan1_after["status"] == "SUPERSEDED", (
            "the older DRAFT is superseded by the newer creation")

    def test_plan_approve_twice_invalid(self, api):
        """PRD §3.2: "Approving a plan that is not in `DRAFT` is rejected with
        `ERR_PLAN_INVALID_STATE`."

        Design: Corner/errors/corner_plan_approve_twice_invalid
        """
        team = create_ops_team()
        set_clock("2026-08-03T06:00:00Z")
        account = create_account(name="Twice Co")
        space = create_space(account["id"], space_code="TK-TA")
        plan = create_plan(space["id"], team["lead_headers"])
        approved = approve_plan(space["id"], plan["id"], team["lead_headers"])
        assert approved["status"] == "APPROVED"

        # OCC passes with the fresh version, so only the state guard can fail.
        fresh_version = read_space(space["id"])["version"]
        resp = api.approve_rescue_plan(
            plan["id"], {"expected_space_version": fresh_version},
            team["lead_headers"])
        validate_error(resp, ApiErrorId.ERR_PLAN_INVALID_STATE)
        plan_after = validate_success(api.get_rescue_plan(plan["id"], OPS))
        assert plan_after["status"] == "APPROVED"


class TestIsolationVerificationState:
    def test_verify_twice_invalid(self, api):
        """PRD §3.4: "Verifying a record not in `PENDING` is
        `ERR_VERIFICATION_INVALID_STATE`."

        Design: Corner/errors/corner_verify_twice_invalid
        """
        ctx = setup_issued_permit(at="2026-08-03T06:00:00Z", with_plan=False)
        team = ctx["team"]
        iso = submit_isolation(ctx["permit"]["id"], team["officer_headers"],
                               isolation_type="VENTILATION",
                               evidence_ref="vent-2")
        verified = verify_isolation_record(iso["id"], team["officer_headers"])
        assert verified["status"] == "VERIFIED"

        resp = api.verify_isolation(iso["id"], team["officer_headers"])
        validate_error(resp, ApiErrorId.ERR_VERIFICATION_INVALID_STATE)
        iso_after = validate_success(
            api.get_isolation_verification(iso["id"], OPS))
        assert iso_after["status"] == "VERIFIED"
        assert iso_after["expires_at"] == verified["expires_at"], (
            "a rejected re-verify mutates nothing")


class TestOptimisticConcurrency:
    def test_occ_plan_create_stale(self, api):
        """PRD §2.7: "If the supplied value does not match the space's current
        `version` — because a plan creation, a plan approval, a permit
        creation, or a space update has advanced the space since the client
        last read it — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412). All four of these operations themselves increment the
        space's `version` by one on success."

        Design: Corner/cross_cutting_layers/corner_occ_plan_create_stale
        """
        team = create_ops_team()
        set_clock("2026-08-03T06:00:00Z")
        account = create_account(name="OCC Co")
        space = create_space(account["id"], space_code="TK-OC1")
        stale_version = space["version"]

        plan1 = create_plan(space["id"], team["lead_headers"])
        assert plan1["status"] == "DRAFT"

        # Replay with the version captured before plan1's create bumped it.
        payload = create_rescue_plan_payload(stale_version,
                                             required_team_size=2)
        resp = api.create_rescue_plan(space["id"], payload,
                                      team["lead_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412
        plan1_after = validate_success(api.get_rescue_plan(plan1["id"], OPS))
        assert plan1_after["status"] == "DRAFT", (
            "the failed create superseded nothing")

    def test_occ_plan_approve_stale(self, api):
        """PRD §2.7: "If the supplied value does not match the space's current
        `version` — because a plan creation, a plan approval, a permit
        creation, or a space update has advanced the space since the client
        last read it — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD §3.2: "A plan begins in `DRAFT` and becomes effective only when a
        `RescueTeamLead` approves it — again carrying `expected_space_version`,
        again rejected with `ERR_STALE_VERSION` on mismatch."

        Design: Corner/cross_cutting_layers/corner_occ_plan_approve_stale
        """
        team = create_ops_team()
        set_clock("2026-08-03T06:00:00Z")
        account = create_account(name="OCC2 Co")
        space = create_space(account["id"], space_code="TK-OC2")
        plan1 = create_plan(space["id"], team["lead_headers"])

        # Capture the version, then bump it by creating plan2.
        stale_version = read_space(space["id"])["version"]
        plan2 = create_plan(space["id"], team["lead_headers"],
                            required_team_size=2,
                            required_certifications=["CONFINED_SPACE_RESCUE",
                                                     "HIGH_ANGLE"],
                            retrieval_system_type="MECHANICAL_RETRIEVAL")

        resp = api.approve_rescue_plan(
            plan2["id"], {"expected_space_version": stale_version},
            team["lead_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412

        approved = approve_plan(space["id"], plan2["id"], team["lead_headers"])
        assert approved["status"] == "APPROVED"
        plan1_after = validate_success(api.get_rescue_plan(plan1["id"], OPS))
        assert plan1_after["status"] == "SUPERSEDED", (
            "plan1 was superseded by plan2's creation, before any approval")

    def test_occ_permit_create_stale(self, api):
        """PRD §2.7: "If the supplied value does not match the space's current
        `version` — because a plan creation, a plan approval, a permit
        creation, or a space update has advanced the space since the client
        last read it — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD §3.3: "the request must carry `expected_space_version` matching the
        space's current `version` (`ERR_STALE_VERSION` on mismatch)."

        Design: Corner/cross_cutting_layers/corner_occ_permit_create_stale
        """
        team = create_ops_team()
        set_clock("2026-08-03T06:00:00Z")
        account = create_account(name="OCC3 Co")
        space = create_space(account["id"], space_code="TK-OC3")
        stale_version = space["version"]

        permit_a = create_permit(space["id"], team["supervisor_headers"],
                                 purpose="First")
        assert permit_a["status"] == "DRAFT"

        # Replay with the stale version: the first create bumped the space.
        payload = {
            "purpose": "Second",
            "planned_start_at": "2026-08-03T06:00:00Z",
            "planned_end_at": "2026-08-03T20:00:00Z",
            "expected_space_version": stale_version,
        }
        resp = api.create_entry_permit(space["id"], payload,
                                       team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412
        permit_a_after = validate_success(
            api.get_entry_permit(permit_a["id"], OPS))
        assert permit_a_after["status"] == "DRAFT", (
            "a rejected supersede attempt must not cancel the existing permit")

    def test_occ_space_patch_stale_then_success(self, api):
        """PRD §2.7: "If the supplied value does not match the space's current
        `version` — because a plan creation, a plan approval, a permit
        creation, or a space update has advanced the space since the client
        last read it — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412). All four of these operations themselves increment the
        space's `version` by one on success."
        PRD §3.1: "Space records can later be updated — reclassification,
        capacity changes, monitoring-flag changes, or a status toggle — by an
        `OperationsManager` or `SafetyOfficer` carrying
        `expected_space_version`, and each successful update increments the
        space's `version`."

        Design: Corner/cross_cutting_layers/corner_occ_space_patch_stale_then_success
        """
        set_clock("2026-08-03T06:00:00Z")
        account = create_account(name="OCC4 Co")
        space = create_space(account["id"], space_code="TK-OC4")
        captured = space["version"]

        patched = validate_success(api.patch_confined_space(
            space["id"], {"max_entrants": 3,
                          "expected_space_version": captured}, OPS))
        assert patched["max_entrants"] == 3
        assert patched["version"] == captured + 1, (
            "a successful update increments the space version by exactly 1")

        resp = api.patch_confined_space(
            space["id"], {"max_entrants": 4,
                          "expected_space_version": captured}, OPS)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412
        space_after = read_space(space["id"])
        assert space_after["max_entrants"] == 3, (
            "the stale replay mutates nothing")


class TestRequestShape:
    def test_invalid_enum_rejected(self, api):
        """PRD §2.6: "enum values must belong to their declared enumerations,
        and numeric values must fall inside sane ranges, all reported as
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/corner_invalid_enum_rejected
        """
        set_clock("2026-08-03T06:00:00Z")
        account = create_account(name="Enum Co")
        payload = create_confined_space_payload(space_code="TK-BAD",
                                                classification="MAYBE")
        resp = api.create_confined_space(account["id"], payload, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400

    def test_invalid_time_range_rejected(self, api):
        """PRD §2.6: "Time-range shape is enforced here as well:
        `planned_end_at` strictly after `planned_start_at` on permits,
        `scheduled_end_at` strictly after `scheduled_start_at` on roster
        entries, `standby_end_at` strictly after `standby_start_at` on standby
        assignments, and `period_end` strictly after `period_start` on billing
        statements — any violation is `ERR_INVALID_TIME_RANGE`."

        Design: Corner/validations/corner_invalid_time_range_rejected
        """
        team = create_ops_team()
        set_clock("2026-08-03T06:00:00Z")
        account = create_account(name="Range Co")
        space = create_space(account["id"], space_code="TK-TR")
        v_before = space["version"]
        payload = {
            "purpose": "Zero window",
            "planned_start_at": "2026-08-03T06:00:00Z",
            "planned_end_at": "2026-08-03T06:00:00Z",
            "expected_space_version": v_before,
        }
        resp = api.create_entry_permit(space["id"], payload,
                                       team["supervisor_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)
        assert resp.status_code == 400
        assert read_space(space["id"])["version"] == v_before, (
            "a rejected request does not advance the space version")
