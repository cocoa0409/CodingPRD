"""Vendor engagements (window overlap semantics, lifecycle) and the
improvement-action loop (segregation of duties, ineffective loop)."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_program_director_headers,
    validate_error,
    validate_success,
)
from test_helpers.factories import engagement_payload
from test_helpers.fixtures import (
    create_active_program,
    create_cycle,
    create_improvement_action,
)
from test_helpers.test_users import DIRECTOR, LEAD


class TestEngagementWindowOverlap:
    def test_engagement_window_half_open_touch_allowed(self, api):
        """PRD section 2.6: "**Vendor engagements** occupy a *half-open*
        interval that begins at `access_start` and runs up to - but does not
        include - `access_end`. Two engagements whose windows merely touch
        (one's `access_end` equal to the other's `access_start`) do **not**
        overlap."
        PRD section 3.9: "a conflict exists only when the new engagement's
        window *overlaps* - touching does not count - the window of another
        engagement of the same program in `PROPOSED` or `ACTIVE` status whose
        scope shares at least one cycle with the new scope; a conflict is
        rejected with `ERR_ENGAGEMENT_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/engagement_window_half_open_touch_allowed
        """
        program = create_active_program(name="Clinic", code="CLN")
        cycle1 = create_cycle(program["id"], label="C1")
        cycle2 = create_cycle(
            program["id"], label="C2",
            cycle_start="2026-10-01T00:00:00Z",
            cycle_end="2026-10-31T23:59:59Z",
            reporting_due_date="2026-11-15T00:00:00Z")

        first = validate_success(api.create_engagement(
            program["id"],
            engagement_payload(vendor_name="EvalCo",
                               scope_program_cycle_ids=[cycle1["id"]],
                               access_start="2026-09-01T00:00:00Z",
                               access_end="2026-10-01T00:00:00Z",
                               deliverable_due="2026-10-10T00:00:00Z"),
            DIRECTOR,
        ), expected_status=201)
        assert first["status"] == "PROPOSED"

        touching = validate_success(api.create_engagement(
            program["id"],
            engagement_payload(vendor_name="TouchingOK",
                               scope_program_cycle_ids=[cycle1["id"]],
                               access_start="2026-10-01T00:00:00Z",
                               access_end="2026-11-01T00:00:00Z",
                               deliverable_due="2026-11-10T00:00:00Z"),
            DIRECTOR,
        ), expected_status=201)
        assert touching["vendor_name"] == "TouchingOK"

        overlapping = api.create_engagement(
            program["id"],
            engagement_payload(vendor_name="OverlapBad",
                               scope_program_cycle_ids=[cycle1["id"]],
                               access_start="2026-09-15T00:00:00Z",
                               access_end="2026-11-01T00:00:00Z",
                               deliverable_due="2026-11-10T00:00:00Z"),
            DIRECTOR,
        )
        validate_error(overlapping, ApiErrorId.ERR_ENGAGEMENT_WINDOW_OVERLAP)

        disjoint_scope = validate_success(api.create_engagement(
            program["id"],
            engagement_payload(vendor_name="DisjointScopeOK",
                               scope_program_cycle_ids=[cycle2["id"]],
                               access_start="2026-09-15T00:00:00Z",
                               access_end="2026-11-01T00:00:00Z",
                               deliverable_due="2026-11-10T00:00:00Z"),
            DIRECTOR,
        ), expected_status=201)
        assert disjoint_scope["vendor_name"] == "DisjointScopeOK"

    def test_engagement_window_overlap_true_overlap_rejected(self, api):
        """PRD section 3.9: "a conflict exists only when the new engagement's
        window *overlaps* - touching does not count - the window of another
        engagement of the same program in `PROPOSED` or `ACTIVE` status whose
        scope shares at least one cycle with the new scope; a conflict is
        rejected with `ERR_ENGAGEMENT_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/engagement_window_half_open_touch_allowed
        """
        program = create_active_program(name="Clinic2", code="CL2")
        cycle1 = create_cycle(program["id"], label="C1")

        validate_success(api.create_engagement(
            program["id"],
            engagement_payload(vendor_name="EvalCo",
                               scope_program_cycle_ids=[cycle1["id"]],
                               access_start="2026-09-01T00:00:00Z",
                               access_end="2026-10-01T00:00:00Z",
                               deliverable_due="2026-10-10T00:00:00Z"),
            DIRECTOR,
        ), expected_status=201)

        overlap = api.create_engagement(
            program["id"],
            engagement_payload(vendor_name="OverlapBad",
                               scope_program_cycle_ids=[cycle1["id"]],
                               access_start="2026-09-30T00:00:00Z",
                               access_end="2026-11-01T00:00:00Z",
                               deliverable_due="2026-11-10T00:00:00Z"),
            DIRECTOR,
        )
        validate_error(overlap, ApiErrorId.ERR_ENGAGEMENT_WINDOW_OVERLAP)


class TestEngagementLifecycle:
    def test_engagement_terminated_before_activation_blocks_activate(self, api):
        """PRD section 3.9: "An engagement that sours can be terminated from
        either `PROPOSED` or `ACTIVE` (`→ TERMINATED`)."
        PRD section 3.4: "Every transition into or out of the wrong state is
        `ERR_INVALID_STATE`." (applies to lifecycle machines across entities)

        Design: Corner/cross_cutting_layers/engagement_terminated_before_activation_blocks_activate
        """
        program = create_active_program(name="Cancel", code="CNC")
        cycle = create_cycle(program["id"], label="C1")
        eng = validate_success(api.create_engagement(
            program["id"],
            engagement_payload(vendor_name="CancelCo",
                               scope_program_cycle_ids=[cycle["id"]]),
            DIRECTOR,
        ), expected_status=201)

        terminated = get_success_data(
            api.terminate_engagement(eng["id"], DIRECTOR))
        assert terminated["status"] == "TERMINATED"

        blocked = api.activate_engagement(eng["id"], DIRECTOR)
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE)


class TestImprovementActionLoop:
    def test_improvement_action_ineffective_loop(self, api):
        """PRD section 3.9: "Verification is again the `ProgramDirector`'s
        call and takes an `outcome`: `EFFECTIVE` moves the action
        `IMPLEMENTED → VERIFIED_EFFECTIVE` (terminal), while `INEFFECTIVE`
        moves it `IMPLEMENTED → VERIFIED_INEFFECTIVE`; either way
        `effectiveness_reviewed_at` is stamped. An ineffective verdict is not
        a dead end - reopening moves `VERIFIED_INEFFECTIVE → PROPOSED`,
        returning the action to the front of the loop for a redesigned
        attempt."

        Design: Difficulty/non_linear_state_machine/improvement_action_ineffective_loop
        """
        program = create_active_program(name="Housing", code="HSG")
        action = create_improvement_action(
            program["id"], title="Tighten data collection SOP",
            description="retrain collectors", creator_user="lead-1")
        assert action["status"] == "PROPOSED"

        # First pass: ends VERIFIED_INEFFECTIVE.
        get_success_data(api.approve_improvement_action(
            action["id"], make_program_director_headers("dir-9")))
        get_success_data(api.start_improvement_action(action["id"], LEAD))
        get_success_data(api.implement_improvement_action(action["id"], LEAD))
        ineffective = get_success_data(api.verify_improvement_action(
            action["id"], {"outcome": "INEFFECTIVE"}, DIRECTOR))
        assert ineffective["status"] == "VERIFIED_INEFFECTIVE"
        assert ineffective["effectiveness_reviewed_at"] is not None

        # Reopen returns the SAME entity to PROPOSED.
        reopened = get_success_data(
            api.reopen_improvement_action(action["id"], LEAD))
        assert reopened["id"] == action["id"]
        assert reopened["status"] == "PROPOSED"

        # Second pass: reaches VERIFIED_EFFECTIVE.
        get_success_data(api.approve_improvement_action(
            action["id"], make_program_director_headers("dir-9")))
        get_success_data(api.start_improvement_action(action["id"], LEAD))
        get_success_data(api.implement_improvement_action(action["id"], LEAD))
        effective = get_success_data(api.verify_improvement_action(
            action["id"], {"outcome": "EFFECTIVE"}, DIRECTOR))
        assert effective["status"] == "VERIFIED_EFFECTIVE"
        assert effective["effectiveness_reviewed_at"] is not None

    def test_improvement_action_effective_first_pass(self, api):
        """PRD section 3.9: "Approval (`PROPOSED → APPROVED`) is a
        `ProgramDirector` call ... Execution then runs `APPROVED →
        IN_PROGRESS → IMPLEMENTED` under the `EvaluationLead`. Verification
        is again the `ProgramDirector`'s call and takes an `outcome`:
        `EFFECTIVE` moves the action `IMPLEMENTED → VERIFIED_EFFECTIVE`
        (terminal)".

        Design: Difficulty/non_linear_state_machine/improvement_action_ineffective_loop
        """
        program = create_active_program(name="Housing2", code="HS2")
        action = create_improvement_action(
            program["id"], title="Tighten data collection SOP",
            creator_user="lead-1")

        approved = get_success_data(api.approve_improvement_action(
            action["id"], make_program_director_headers("dir-9")))
        assert approved["status"] == "APPROVED"

        started = get_success_data(
            api.start_improvement_action(action["id"], LEAD))
        assert started["status"] == "IN_PROGRESS"

        implemented = get_success_data(
            api.implement_improvement_action(action["id"], LEAD))
        assert implemented["status"] == "IMPLEMENTED"

        verified = get_success_data(api.verify_improvement_action(
            action["id"], {"outcome": "EFFECTIVE"}, DIRECTOR))
        assert verified["status"] == "VERIFIED_EFFECTIVE"
        assert verified["effectiveness_reviewed_at"] is not None

    def test_segregation_self_approve_improvement_rejected(self, api):
        """PRD section 3.9: "the proposer cannot approve their own action -
        when the approver's `X-User-ID` equals the recorded creator's, the
        approval is rejected with `ERR_SEGREGATION_OF_DUTY`."
        PRD section 2.9: "a `ProgramDirector` cannot approve an
        `ImprovementAction` they themselves created".

        Design: Corner/validations/segregation_self_approve_improvement_rejected
        """
        program = create_active_program(name="SoD2", code="SD2")
        action = create_improvement_action(
            program["id"], title="Fix training",
            description="re-certify staff", creator_user="lead-1")

        self_approve = api.approve_improvement_action(
            action["id"], make_program_director_headers("lead-1"))
        validate_error(self_approve, ApiErrorId.ERR_SEGREGATION_OF_DUTY)

        other = get_success_data(api.approve_improvement_action(
            action["id"], make_program_director_headers("dir-9")))
        assert other["status"] == "APPROVED"
