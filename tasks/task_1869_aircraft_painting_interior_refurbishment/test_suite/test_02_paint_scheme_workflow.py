"""Paint scheme lifecycle: revision cycle, approval pin, supersede pair (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    assert_paint_scheme,
    approve_scheme,
    create_and_approve_scheme,
    create_engagement,
    create_scheme,
    get_program,
    make_customer_rep_headers,
    submit_scheme,
    validate_error,
    validate_success,
)


class TestSchemeRevisionCycle:
    def test_scheme_reject_revise_resubmit_cycle(self, api, design_lead_headers,
                                                 customer_rep_headers):
        """PRD §3.3: "A scheme begins in `DRAFT`; the design lead submits it,
        moving it to `SUBMITTED`, and the customer's representative then
        decides." and "Rejection is the lighter path: the customer moves the
        scheme to `REJECTED`, and the design lead may return it to `DRAFT` for
        revision, closing the cycle."

        Design: Difficulty/non_linear_state_machine/paint_scheme_revision_cycle
        """
        ctx = create_engagement()
        scheme = create_scheme(ctx["program"]["id"])
        assert scheme["status"] == "DRAFT"

        submitted = validate_success(api.submit_paint_scheme(scheme["id"], design_lead_headers))
        assert submitted["status"] == "SUBMITTED"

        rejected = validate_success(
            api.reject_paint_scheme(
                scheme["id"], make_customer_rep_headers(ctx["customer"]["id"])
            )
        )
        assert rejected["status"] == "REJECTED"

        revised = validate_success(api.revise_paint_scheme(scheme["id"], design_lead_headers))
        assert revised["status"] == "DRAFT", "revise must re-enter DRAFT (cyclic loop)"

        resubmitted = validate_success(
            api.submit_paint_scheme(scheme["id"], design_lead_headers)
        )
        assert resubmitted["status"] == "SUBMITTED"

    def test_scheme_cycle_leaves_program_version_for_approval(
        self, api, design_lead_headers
    ):
        """PRD §3.3: "The approval increments the program's `version` by
        one." — the draft/submit/reject/revise cycle does not touch the
        program, so the version captured at program creation still satisfies
        the OCC precondition after the loop.
        PRD §2.6: "If the program's current `version` no longer matches —
        because another writer has advanced it since the client last read the
        program — the request is rejected with `ERR_STALE_PROGRAM_VERSION`
        (HTTP 412)."

        Design: Difficulty/non_linear_state_machine/paint_scheme_revision_cycle
        """
        ctx = create_engagement()
        v0 = ctx["program"]["version"]
        scheme = create_scheme(ctx["program"]["id"])
        submit_scheme(scheme["id"])
        api.reject_paint_scheme(scheme["id"], make_customer_rep_headers(ctx["customer"]["id"]))
        api.revise_paint_scheme(scheme["id"], design_lead_headers)
        submit_scheme(scheme["id"])

        # The version observed at creation must still be current: only the
        # approval itself is a program mutation in this flow.
        approved = approve_scheme(scheme["id"], ctx["customer"]["id"], v0)
        assert approved["status"] == "APPROVED"
        program = get_program(ctx["program"]["id"])
        assert program["version"] == v0 + 1, "only the approval bumps the version"
        assert program["approved_scheme_id"] == scheme["id"]


class TestSchemeApprovalGuards:
    def test_approve_from_draft_rejected(self, api):
        """PRD §3.3: "The `CustomerRep` approves a `SUBMITTED` scheme by
        presenting `expected_program_version`" — approval is defined only from
        SUBMITTED. PRD §2.10: "**State validity** — the entity is in a valid
        from-state for the requested transition, including terminal lockdown
        (`ERR_INVALID_STATE`, 409)".

        Design: Corner/state_machines/scheme_approve_from_draft_rejected
        """
        ctx = create_engagement()
        scheme = create_scheme(ctx["program"]["id"])
        v0 = get_program(ctx["program"]["id"])["version"]
        resp = api.approve_paint_scheme(
            scheme["id"],
            {"expected_program_version": v0},
            make_customer_rep_headers(ctx["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_program(ctx["program"]["id"])["version"] == v0, (
            "a rejected approval must not mutate the program"
        )

    def test_approve_after_surface_review_rejected(self, api):
        """PRD §3.3: approval fails "with `ERR_SCHEME_PHASE_TOO_ADVANCED` if
        the program has already moved past `SURFACE_REVIEW` — approval is only
        possible while the program is `QUOTED`, `BOOKED`, `INDUCTED`, or
        `SURFACE_REVIEW`."

        Design: Corner/errors/scheme_approve_after_surface_review_rejected
        """
        from test_helpers import setup_in_work_program

        ctx = setup_in_work_program()  # scheme A already approved en route
        scheme_b = create_scheme(ctx["program"]["id"], drawing_ref="DWG-1869-B")
        submit_scheme(scheme_b["id"])
        resp = api.approve_paint_scheme(
            scheme_b["id"],
            {"expected_program_version": get_program(ctx["program"]["id"])["version"]},
            make_customer_rep_headers(ctx["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SCHEME_PHASE_TOO_ADVANCED)


class TestSchemeSupersedePair:
    def test_second_approval_supersedes_first_and_repins(self, api, design_lead_headers):
        """PRD §3.3: "On approval, any previously `APPROVED` scheme of the same
        program is moved to `SUPERSEDED` with its `superseded_by_id` pointing
        at the newly approved scheme — a compensating pair that keeps the count
        of approved schemes per program at exactly one — and the program's
        `approved_scheme_id` is pinned to the new scheme."

        Design: Corner/state_machines/scheme_supersede_pins_and_locks
        """
        ctx = create_engagement()
        scheme_a = create_and_approve_scheme(ctx["program"]["id"], ctx["customer"]["id"])
        scheme_b = create_scheme(ctx["program"]["id"], drawing_ref="DWG-1869-B")
        submit_scheme(scheme_b["id"])
        approved_b = approve_scheme(
            scheme_b["id"], ctx["customer"]["id"], get_program(ctx["program"]["id"])["version"]
        )
        assert approved_b["status"] == "APPROVED"

        a_after = validate_success(api.get_paint_scheme(scheme_a["id"], design_lead_headers))
        assert a_after["status"] == "SUPERSEDED"
        assert a_after["superseded_by_id"] == scheme_b["id"]
        assert get_program(ctx["program"]["id"])["approved_scheme_id"] == scheme_b["id"]

    def test_superseded_scheme_rejects_further_submit(self, api, design_lead_headers):
        """PRD §3.3: approval moves the prior scheme to `SUPERSEDED`;
        PRD §2.10: "**State validity** — the entity is in a valid from-state for
        the requested transition, including terminal lockdown
        (`ERR_INVALID_STATE`, 409)".

        Design: Corner/state_machines/scheme_supersede_pins_and_locks
        """
        ctx = create_engagement()
        scheme_a = create_and_approve_scheme(ctx["program"]["id"], ctx["customer"]["id"])
        scheme_b = create_scheme(ctx["program"]["id"], drawing_ref="DWG-1869-B")
        submit_scheme(scheme_b["id"])
        approve_scheme(
            scheme_b["id"], ctx["customer"]["id"], get_program(ctx["program"]["id"])["version"]
        )
        resp = api.submit_paint_scheme(scheme_a["id"], design_lead_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSchemeApproveOcc:
    def test_stale_program_version_rejected_then_fresh_succeeds(
        self, api, program_manager_headers
    ):
        """PRD §2.6: "If the program's current `version` no longer matches —
        because another writer has advanced it since the client last read the
        program — the request is rejected with `ERR_STALE_PROGRAM_VERSION`
        (HTTP 412)." PRD §3.3: "The approval increments the program's `version`
        by one."

        Design: Corner/cross_cutting_complexity_layers/occ_scheme_approve_stale_version_rejected
        """
        ctx = create_engagement()
        v0 = ctx["program"]["version"]
        scheme_a = create_scheme(ctx["program"]["id"])
        submit_scheme(scheme_a["id"])
        scheme_b = create_scheme(ctx["program"]["id"], drawing_ref="DWG-1869-B")
        submit_scheme(scheme_b["id"])

        approved_a = approve_scheme(scheme_a["id"], ctx["customer"]["id"], v0)
        assert approved_a["status"] == "APPROVED"

        stale = api.approve_paint_scheme(
            scheme_b["id"],
            {"expected_program_version": v0},
            make_customer_rep_headers(ctx["customer"]["id"]),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_PROGRAM_VERSION)

        v1 = validate_success(
            api.get_program(ctx["program"]["id"], program_manager_headers)
        )["version"]
        approved_b = approve_scheme(scheme_b["id"], ctx["customer"]["id"], v1)
        assert approved_b["status"] == "APPROVED"
        a_after = validate_success(
            api.get_paint_scheme(scheme_a["id"], program_manager_headers)
        )
        assert a_after["status"] == "SUPERSEDED"


class TestImmediateConsistency:
    def test_approval_visible_immediately_on_read(self, api, program_manager_headers):
        """PRD §2.7: "the program's derived fields are recomputed immediately,
        its `version` increments ... All mutations and their cascades are
        atomic within the request: the system never persists a partial
        application." PRD §3.3: "The approval increments the program's
        `version` by one."

        Design: Corner/consistency_model/immediate_visibility_after_mutation
        """
        ctx = create_engagement()
        v0 = ctx["program"]["version"]
        scheme = create_scheme(ctx["program"]["id"])
        submit_scheme(scheme["id"])

        resp = api.approve_paint_scheme(
            scheme["id"],
            {"expected_program_version": v0},
            make_customer_rep_headers(ctx["customer"]["id"]),
        )
        data = validate_success(resp)
        assert_paint_scheme(data)
        assert data["status"] == "APPROVED", "mutation response carries the new state"

        program = validate_success(
            api.get_program(ctx["program"]["id"], program_manager_headers)
        )
        assert program["approved_scheme_id"] == scheme["id"]
        assert program["version"] == v0 + 1, "approval bumped the version exactly once"
