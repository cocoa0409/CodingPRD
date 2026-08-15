"""Rate filings: revision loop, half-open window overlap, effectivity gating,
and the supersession cascade onto QUOTED policies."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    bind_policy,
    create_allocation,
    create_carrier,
    create_filing,
    create_guideline,
    create_program,
    get_policy_fresh,
    make_carrier_underwriter_headers,
    move_filing_to_effective,
    quote_policy,
    set_clock,
    setup_active_program,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["mga_underwriter_headers"]


class TestFilingRevisionLoop:
    def test_disapproved_filing_revises_to_draft_and_completes_loop(self, api):
        """PRD §3.3: "Disapproval moves the filing to `DISAPPROVED`, from which
        the MGA underwriter may revise it back to `DRAFT`, resetting
        `submitted_at` and `approved_at` to null; the
        draft–submit–disapprove–revise loop is unbounded."

        Design: Difficulty/non_linear_state_machine/filing_revision_loop_cycle
        """
        carrier = create_carrier()
        program = create_program(carrier)
        create_guideline(program)
        create_allocation(program)
        filing = create_filing(program)
        cu = make_carrier_underwriter_headers(carrier["id"])

        validate_success(api.submit_filing(filing["id"], UW))
        dis = validate_success(api.disapprove_filing(filing["id"], cu))
        assert dis["status"] == "DISAPPROVED"

        revised = validate_success(api.revise_filing(filing["id"], UW))
        assert revised["status"] == "DRAFT"
        assert revised["submitted_at"] is None
        assert revised["approved_at"] is None

        # Second pass through the loop reaches EFFECTIVE on the same row.
        validate_success(api.submit_filing(filing["id"], UW))
        validate_success(api.approve_filing(filing["id"], cu))
        eff = validate_success(api.mark_effective_filing(filing["id"], cu))
        assert eff["status"] == "EFFECTIVE"
        assert eff["id"] == filing["id"], "revision loop mutates one filing row"

    def test_revision_loop_second_cycle_resubmits_successfully(self, api):
        """PRD §3.3: "Submission moves a filing `DRAFT → SUBMITTED` and stamps
        `submitted_at` from the clock" — after a revise returns the filing to
        DRAFT, a fresh submission is legal again (the loop is unbounded).

        Design: Difficulty/non_linear_state_machine/filing_revision_loop_cycle
        """
        carrier = create_carrier()
        program = create_program(carrier)
        filing = create_filing(program)
        cu = make_carrier_underwriter_headers(carrier["id"])

        validate_success(api.submit_filing(filing["id"], UW))
        validate_success(api.disapprove_filing(filing["id"], cu))
        validate_success(api.revise_filing(filing["id"], UW))
        second = validate_success(api.submit_filing(filing["id"], UW))
        assert second["status"] == "SUBMITTED"
        assert second["submitted_at"] is not None


class TestFilingApproveStateGate:
    def test_approve_from_draft_rejected(self, api):
        """PRD §3.3: "The carrier underwriter then decides. Approval
        (`SUBMITTED → APPROVED`)" — approval is defined only from `SUBMITTED`;
        PRD §2.11: state-legality violations yield `ERR_INVALID_STATE`.

        Design: Corner/state_machines/filing_approve_from_draft_invalid
        """
        carrier = create_carrier()
        program = create_program(carrier)
        filing = create_filing(program)
        cu = make_carrier_underwriter_headers(carrier["id"])

        resp = api.approve_filing(filing["id"], cu)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fresh = validate_success(api.get_filing(filing["id"], UW))
        assert fresh["status"] == "DRAFT"


class TestMarkEffectiveGate:
    def test_mark_effective_before_window_rejected_then_succeeds(self, api):
        """PRD §3.3: "marking an `APPROVED` filing effective (`APPROVED →
        EFFECTIVE`) requires the clock to have reached the filing's
        `effective_from`, failing with `ERR_FILING_NOT_YET_EFFECTIVE` before
        then."

        Design: Corner/state_machines/filing_mark_effective_before_window_rejected
        """
        carrier = create_carrier()
        program = create_program(carrier)
        filing = create_filing(
            program, effective_from="2026-09-01T00:00:00Z",
            effective_to="2027-09-01T00:00:00Z")
        cu = make_carrier_underwriter_headers(carrier["id"])
        validate_success(api.submit_filing(filing["id"], UW))
        validate_success(api.approve_filing(filing["id"], cu))

        early = api.mark_effective_filing(filing["id"], cu)
        validate_error(early, ApiErrorId.ERR_FILING_NOT_YET_EFFECTIVE)

        set_clock("2026-09-01T00:00:00Z")
        ok = validate_success(api.mark_effective_filing(filing["id"], cu))
        assert ok["status"] == "EFFECTIVE"


class TestFilingWindowOverlap:
    def test_adjacent_window_approved_and_overlapping_window_rejected(self, api):
        """PRD §3.3: "no other filing of the same program and `state_code` in
        `APPROVED` or `EFFECTIVE` status may have a half-open window that
        intersects this one. Because windows are half-open, adjacency is not
        intersection — a filing whose `effective_from` is exactly another's
        `effective_to`, or whose `effective_to` is exactly another's
        `effective_from`, merely touches the other and is permitted; any true
        overlap is rejected with `ERR_FILING_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/filing_window_half_open_adjacency
        """
        carrier = create_carrier()
        program = create_program(carrier)
        create_guideline(program)
        create_allocation(program)
        cu = make_carrier_underwriter_headers(carrier["id"])

        fil_a = create_filing(program, base_rates={"ARTISAN": 1500})
        validate_success(api.submit_filing(fil_a["id"], UW))
        approved_a = validate_success(api.approve_filing(fil_a["id"], cu))
        assert approved_a["status"] == "APPROVED"

        fil_b = create_filing(
            program, base_rates={"ARTISAN": 1600},
            effective_from="2027-08-01T00:00:00Z",
            effective_to="2028-08-01T00:00:00Z")
        validate_success(api.submit_filing(fil_b["id"], UW))
        approved_b = validate_success(api.approve_filing(fil_b["id"], cu))
        assert approved_b["status"] == "APPROVED", "adjacency is not intersection"

        fil_c = create_filing(
            program, base_rates={"ARTISAN": 1700},
            effective_from="2027-06-01T00:00:00Z",
            effective_to="2028-01-01T00:00:00Z")
        validate_success(api.submit_filing(fil_c["id"], UW))
        conflict = api.approve_filing(fil_c["id"], cu)
        validate_error(conflict, ApiErrorId.ERR_FILING_WINDOW_OVERLAP)
        fresh_c = validate_success(api.get_filing(fil_c["id"], UW))
        assert fresh_c["status"] == "SUBMITTED"

    def test_overlap_check_ignores_other_states_and_scopes(self, api):
        """PRD §3.3: "no other filing of the same program and `state_code` in
        `APPROVED` or `EFFECTIVE` status may have a half-open window that
        intersects this one" — the exclusivity predicate names both the status
        set and the program+state scope.

        Design: Difficulty/resource_temporal_overlap/filing_window_half_open_adjacency
        """
        carrier = create_carrier()
        program = create_program(carrier, states_covered=["CA", "NV"])
        create_guideline(program)
        create_allocation(program)
        cu = make_carrier_underwriter_headers(carrier["id"])

        # An APPROVED CA filing occupies [2026-08-01, 2027-08-01).
        fil_a = create_filing(program)
        validate_success(api.submit_filing(fil_a["id"], UW))
        validate_success(api.approve_filing(fil_a["id"], cu))

        # Same window but a different state scope: no intersection per the rule.
        fil_nv = create_filing(program, state_code="NV")
        validate_success(api.submit_filing(fil_nv["id"], UW))
        ok = validate_success(api.approve_filing(fil_nv["id"], cu))
        assert ok["status"] == "APPROVED"


class TestFilingSupersedeCascade:
    def test_mark_effective_supersedes_prior_and_withdraws_its_quotes(self, api):
        """PRD §3.3: "At effectivity, the prior `EFFECTIVE` filing of the same
        program and state, if one exists, becomes `SUPERSEDED` — and that
        supersession cascades: every policy still in `QUOTED` whose `filing_id`
        names the superseded filing is withdrawn (`QUOTED → WITHDRAWN`), while
        policies already `BOUND` or `ISSUED` keep their original `filing_id`
        and are never re-rated."

        Design: Difficulty/transitive_cascade/filing_supersede_cascade_depth2
        """
        carrier, program, _g, _a, fil1 = setup_active_program()

        qpol = quote_policy(program, insured_name="Q Co", exposure_units=10,
                            coverage_limit_cents=100000)
        assert qpol["filing_id"] == fil1["id"]
        bpol = quote_policy(program, insured_name="B Co")
        bpol = bind_policy(bpol)

        fil2 = create_filing(program, base_rates={"ARTISAN": 1600},
                             effective_from="2027-08-01T00:00:00Z",
                             effective_to="2028-08-01T00:00:00Z")
        cu = make_carrier_underwriter_headers(carrier["id"])
        validate_success(api.submit_filing(fil2["id"], UW))
        validate_success(api.approve_filing(fil2["id"], cu))
        set_clock("2027-08-01T00:00:00Z")
        eff = validate_success(api.mark_effective_filing(fil2["id"], cu))
        assert eff["status"] == "EFFECTIVE"

        fil1_fresh = validate_success(api.get_filing(fil1["id"], UW))
        assert fil1_fresh["status"] == "SUPERSEDED"
        assert get_policy_fresh(qpol["id"])["status"] == "WITHDRAWN"
        bpol_fresh = get_policy_fresh(bpol["id"])
        assert bpol_fresh["status"] == "BOUND"
        assert bpol_fresh["filing_id"] == fil1["id"]

    def test_bound_policy_keeps_original_filing_after_supersession(self, api):
        """PRD §3.3: "policies already `BOUND` or `ISSUED` keep their original
        `filing_id` and are never re-rated" — the cascade is conditional on the
        child policy still being `QUOTED`.

        Design: Difficulty/transitive_cascade/filing_supersede_cascade_depth2
        """
        carrier, program, _g, _a, fil1 = setup_active_program()
        policy = quote_policy(program)
        policy = bind_policy(policy)
        gross_before = policy["gross_premium_cents"]

        fil2 = create_filing(program, base_rates={"ARTISAN": 3000},
                             effective_from="2027-08-01T00:00:00Z",
                             effective_to="2028-08-01T00:00:00Z")
        cu = make_carrier_underwriter_headers(carrier["id"])
        validate_success(api.submit_filing(fil2["id"], UW))
        validate_success(api.approve_filing(fil2["id"], cu))
        set_clock("2027-08-01T00:00:00Z")
        validate_success(api.mark_effective_filing(fil2["id"], cu))

        fresh = get_policy_fresh(policy["id"])
        assert fresh["status"] == "BOUND"
        assert fresh["filing_id"] == fil1["id"]
        assert fresh["gross_premium_cents"] == gross_before, "no re-rate after supersession"
