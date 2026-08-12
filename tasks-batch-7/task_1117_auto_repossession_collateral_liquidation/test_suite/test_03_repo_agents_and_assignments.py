"""Repossession agents and field assignments: performance scoring (both
variants), the breach/suspension cascade, half-open field-window overlap,
the auto-selection policy, and assignment lifecycle rejections."""
from test_helpers import (
    ApiErrorId,
    accept_assignment,
    assign_agent,
    create_agent,
    create_borrower,
    create_loan,
    get_agent,
    issue_cure_notice,
    list_case_assignments,
    make_agent_headers,
    make_compliance_officer_headers,
    open_case,
    rm_headers,
    set_clock,
    setup_case_collateral_secured,
    setup_case_cure_expired,
    setup_case_cure_pending,
    validate_error,
    validate_success,
)

CO = make_compliance_officer_headers("co_1")


def _small_loan(vin):
    return {
        "vin": vin,
        "principal_balance_cents": 500_000,
        "apr_bps": 900,
        "monthly_payment_cents": 20_000,
        "missed_installments": 2,
        "accrued_interest_cents": 8_000,
        "late_fees_cents": 3_000,
    }


class TestAssignmentLifecycle:
    def test_report_secured_invalid_enum_rejected(self, api):
        """PRD §3.4: "The report carries the vehicle's `odometer`, a
        `condition_grade` of `EXCELLENT`, `GOOD`, `FAIR`, or `POOR`, the clean
        trade-in appraisal `trade_in_value_cents`, and the wholesale
        `auction_guide_low_cents`."
        PRD §2.7: "the request body is well-formed — required fields present,
        types correct, enum values valid, unknown fields rejected, amount fields
        positive integers"

        Design: Corner/entities/report_secured_invalid_enum_rejected
        """
        ctx = setup_case_cure_expired(
            borrower_overrides={"full_name": "EN", "email": "en@x.com"},
            loan_overrides=_small_loan("VIN00000000000043"))
        agent = create_agent(name="Agent E", license_number="LIC-E")
        assignment = assign_agent(ctx["case"]["id"], agent["id"])
        accept_assignment(assignment["id"], agent["id"])

        resp = api.report_secured(
            assignment["id"],
            {"odometer": 10_000, "condition_grade": "SUPERB",
             "trade_in_value_cents": 600_000, "auction_guide_low_cents": 450_000},
            make_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assignments = list_case_assignments(ctx["case"]["id"])
        assert assignments[0]["status"] == "ACCEPTED", "rejected report must not move the assignment"

    def test_unaccepted_assignment_expires_by_clock(self, api):
        """PRD §3.3: "An assignment left unacknowledged expires automatically:
        once the logical clock passes 48 hours beyond the assignment's creation
        while it still stands `ASSIGNED`, it moves to `EXPIRED`, the agent's
        scores are recomputed with one more expired count (a 10-point penalty),
        and if the recomputed rolling score falls below 40 the agent is
        auto-suspended and the suspension cascade fires."

        Design: Corner/state_machines/unaccepted_assignment_expires_by_clock
        """
        ctx = setup_case_cure_expired(
            borrower_overrides={"full_name": "UA", "email": "ua@x.com"},
            loan_overrides=_small_loan("VIN00000000000050"))
        agent = create_agent(name="Agent O", license_number="LIC-O")
        assignment = assign_agent(ctx["case"]["id"], agent["id"])  # created 2026-05-16

        set_clock("2026-05-19T00:00:00Z")  # 72h past creation > 48h window
        agent_after = get_agent(agent["id"])
        assert agent_after["performance_score_rolling"] == 90
        assert agent_after["status"] == "ACTIVE"
        assignments = validate_success(api.list_agent_assignments(agent["id"], rm_headers()))
        assert assignments[0]["id"] == assignment["id"]
        assert assignments[0]["status"] == "EXPIRED"

    def test_double_accept_rejected_invalid_assignment_state(self, api):
        """PRD §3.3: "Acceptance requires the assignment to be in `ASSIGNED`
        (`ERR_INVALID_ASSIGNMENT_STATE`), the caller to be the assignment's
        agent (`ERR_FORBIDDEN_OWNERSHIP`), and — a business-safety check
        evaluated only after the state tier — the agent to still be `ACTIVE`
        (`ERR_AGENT_SUSPENDED`)."

        Design: Corner/state_machines/double_accept_rejected_invalid_assignment_state
        """
        ctx = setup_case_cure_expired(
            borrower_overrides={"full_name": "DA", "email": "da@x.com"},
            loan_overrides=_small_loan("VIN00000000000079"))
        agent = create_agent(name="Agent DA", license_number="LIC-DA")
        assignment = assign_agent(ctx["case"]["id"], agent["id"])
        accepted = accept_assignment(assignment["id"], agent["id"])
        assert accepted["status"] == "ACCEPTED"
        version_after_accept = accepted["version"]

        resp = api.accept_assignment(assignment["id"], make_agent_headers(agent["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE)
        current = list_case_assignments(ctx["case"]["id"])[0]
        assert current["status"] == "ACCEPTED"
        assert current["version"] == version_after_accept, "a rejected request mutates nothing (PRD §2.7)"


class TestAgentScoreClamping:
    def test_fast_secure_bonus_clamped_at_100(self, api):
        """PRD §3.3: "start from 100, subtract 25 for every assignment that
        ended in `BREACHED_PEACE`, subtract 10 for every assignment that went
        `EXPIRED`, and add 2 for every assignment that reached `SECURED`
        quickly — within fourteen days of its creation, a fact recorded on the
        assignment as `secured_fast`. The result is clamped so it never falls
        below 0 or rises above 100."

        Design: Corner/calculations/fast_secure_bonus_clamped_at_100
        """
        ctx = setup_case_cure_expired(
            borrower_overrides={"full_name": "FB", "email": "fb@x.com"},
            loan_overrides=_small_loan("VIN00000000000058"))
        agent = create_agent(name="Agent J", license_number="LIC-J")
        assignment = assign_agent(ctx["case"]["id"], agent["id"])
        accept_assignment(assignment["id"], agent["id"])
        resp = api.report_secured(
            assignment["id"],
            {"odometer": 40_000, "condition_grade": "FAIR",
             "trade_in_value_cents": 600_000, "auction_guide_low_cents": 450_000},
            make_agent_headers(agent["id"]))
        secured = validate_success(resp)
        assert secured["secured_fast"] is True, "created and secured the same day (<= 14 days)"
        agent_after = get_agent(agent["id"])
        assert agent_after["performance_score_rolling"] == 100, "100 + 2 clamps back to 100"
        assert agent_after["performance_score_lifetime"] == 100


class TestRollingVsLifetimeScore:
    """Same assignment history; the LIFETIME window counts everything, the
    ROLLING_90D window only the trailing ninety days."""

    def _setup_old_history_agent(self, api):
        """One agent with: A1 BREACHED_PEACE (created 2026-05-16) and A2 left
        ASSIGNED at 2026-05-31 then auto-EXPIRED by the clock. Final clock
        2026-09-01 puts both events more than 90 days behind it."""
        ctx1 = setup_case_cure_pending(
            borrower_overrides={"full_name": "B One", "email": "b1@x.com"},
            loan_overrides=_small_loan("VIN00000000000001"))
        agent = create_agent(name="Old History Agent", license_number="LIC-9",
                             max_active_assignments=10)
        set_clock("2026-05-16T00:00:00Z")  # ctx1's cure deadline (05-15) passes
        a1 = assign_agent(ctx1["case"]["id"], agent["id"],
                          field_window_start="2026-05-16T00:00:00Z",
                          field_window_end="2026-05-17T00:00:00Z")
        breach = api.report_breach(a1["id"], CO)
        validate_success(breach)

        ctx2 = setup_case_cure_pending(
            borrower_overrides={"full_name": "B Two", "email": "b2@x.com"},
            loan_overrides=_small_loan("VIN00000000000002"))
        set_clock("2026-05-31T00:00:00Z")
        assign_agent(ctx2["case"]["id"], agent["id"],
                     field_window_start="2026-05-31T00:00:00Z",
                     field_window_end="2026-06-01T00:00:00Z")
        set_clock("2026-06-03T00:00:00Z")  # A2 unacknowledged > 48h -> EXPIRED
        set_clock("2026-09-01T00:00:00Z")  # both events now > 90 days old
        return agent

    def test_agent_score_lifetime_counts_all_history(self, api):
        """PRD §3.3: "`performance_score_lifetime` spans all of the agent's
        assignments regardless of age, while `performance_score_rolling`
        restricts the same weights to assignments created within the trailing
        ninety days of the logical clock."
        PRD §3.3: "start from 100, subtract 25 for every assignment that ended
        in `BREACHED_PEACE`, subtract 10 for every assignment that went
        `EXPIRED`"

        Design: Difficulty/dual_variant_calc/agent_score_rolling_vs_lifetime_diverge
        """
        agent = self._setup_old_history_agent(api)
        agent_after = get_agent(agent["id"])
        assert agent_after["performance_score_lifetime"] == 65, (
            "100 - 25 (breach) - 10 (expired) over all history")

    def test_agent_score_rolling_excludes_old_events_and_skips_suspension(self, api):
        """PRD §3.3: "The rolling variant alone drives auto-suspension and
        auto-assignment ranking, so an agent whose violations are all older
        than ninety days reads 100 on the rolling score even while its
        lifetime score reads lower."

        Design: Difficulty/dual_variant_calc/agent_score_rolling_vs_lifetime_diverge
        """
        agent = self._setup_old_history_agent(api)
        agent_after = get_agent(agent["id"])
        assert agent_after["performance_score_rolling"] == 100, (
            "both events are older than 90 days: the rolling window is empty")
        assert agent_after["status"] == "ACTIVE", (
            "suspension is driven by the rolling variant only")


class TestBreachSuspensionCascade:
    """Three-link cascade: breach -> rolling score recompute -> suspension ->
    cancellation of the agent's other live assignments."""

    def _setup_four_case_agent(self, api):
        """One CA agent holding assignments on four CURE_EXPIRED cases:
        A1 and A2 already BREACHED_PEACE (rolling 50), A3 ACCEPTED, A4
        ASSIGNED. Windows are disjoint days so no overlap check fires."""
        contexts = []
        for i in range(1, 5):
            ctx = setup_case_cure_pending(
                borrower_overrides={"full_name": f"K{i}", "email": f"k{i}@x.com"},
                loan_overrides=_small_loan(f"VIN0000000000001{i}"))
            contexts.append(ctx)
        agent = create_agent(name="Cascade Agent", license_number="LIC-C",
                             max_active_assignments=10)
        set_clock("2026-05-16T00:00:00Z")  # all four cure deadlines (05-15) pass
        assignments = []
        for idx, ctx in enumerate(contexts):
            day = 16 + idx
            a = assign_agent(
                ctx["case"]["id"], agent["id"],
                field_window_start=f"2026-05-{day}T00:00:00Z",
                field_window_end=f"2026-05-{day + 1}T00:00:00Z")
            assignments.append(a)
        validate_success(api.report_breach(assignments[0]["id"], CO))
        validate_success(api.report_breach(assignments[1]["id"], CO))
        accept_assignment(assignments[2]["id"], agent["id"])
        return agent, assignments, contexts

    def test_breach_recomputes_rolling_score_below_threshold(self, api):
        """PRD §3.3: "The breach triggers a three-link cascade, applied
        atomically: first, the agent's scores are recomputed with one more
        breach count (a 25-point penalty); second, if the recomputed
        `performance_score_rolling` has fallen below the suspension threshold
        of 40, the agent transitions to `SUSPENDED`"

        Design: Difficulty/transitive_cascade/breach_suspension_cascade
        """
        agent, assignments, _ = self._setup_four_case_agent(api)
        resp = api.report_breach(assignments[2]["id"], CO)
        breached = validate_success(resp)
        assert breached["status"] == "BREACHED_PEACE"
        agent_after = get_agent(agent["id"])
        assert agent_after["performance_score_rolling"] == 25, "100 - 3 x 25"
        assert agent_after["status"] == "SUSPENDED", "25 < 40 suspends the agent"

    def test_suspension_cancels_other_live_assignments_case_survives(self, api):
        """PRD §3.3: "third, every other assignment of that agent still
        standing in `ASSIGNED` or `ACCEPTED` is moved to `CANCELLED`. The case
        itself remains in `REPO_ACTIVE` with no live assignment, so the
        manager is free to assign a different agent."

        Design: Difficulty/transitive_cascade/breach_suspension_cascade
        """
        agent, assignments, contexts = self._setup_four_case_agent(api)
        validate_success(api.report_breach(assignments[2]["id"], CO))

        case4_assignments = list_case_assignments(contexts[3]["case"]["id"])
        assert case4_assignments[0]["id"] == assignments[3]["id"]
        assert case4_assignments[0]["status"] == "CANCELLED", (
            "link 3: the untouched fourth assignment is cancelled transitively")
        case4 = validate_success(api.get_recovery_case(contexts[3]["case"]["id"], rm_headers()))
        assert case4["status"] == "REPO_ACTIVE"
        # Re-assignment is now possible on the surviving case.
        agent2 = create_agent(name="Replacement", license_number="LIC-R2")
        reassigned = api.create_repo_assignment(
            contexts[3]["case"]["id"],
            {"agent_id": agent2["id"],
             "field_window_start": "2026-05-19T00:00:00Z",
             "field_window_end": "2026-05-20T00:00:00Z"},
            rm_headers())
        validate_success(reassigned, expected_status=201)


class TestFieldWindowOverlap:
    """Half-open interval semantics on the agent's field schedule."""

    def _setup_agent_with_first_window(self, api):
        ctx1 = setup_case_cure_expired(
            borrower_overrides={"full_name": "H1", "email": "h1@x.com"},
            loan_overrides=_small_loan("VIN00000000000031"))
        ctx2 = setup_case_cure_expired(
            borrower_overrides={"full_name": "H2", "email": "h2@x.com"},
            loan_overrides=_small_loan("VIN00000000000032"))
        ctx3 = setup_case_cure_expired(
            borrower_overrides={"full_name": "H3", "email": "h3@x.com"},
            loan_overrides=_small_loan("VIN00000000000033"))
        agent = create_agent(name="HalfOpen Agent", license_number="LIC-H",
                             max_active_assignments=10)
        assign_agent(ctx1["case"]["id"], agent["id"],
                     field_window_start="2026-05-16T00:00:00Z",
                     field_window_end="2026-05-17T00:00:00Z")
        return agent, ctx1, ctx2, ctx3

    def test_agent_field_window_adjacency_accepted(self, api):
        """PRD §3.3: "Two half-open windows overlap only when each starts
        strictly before the other ends — two windows that merely abut, one
        ending exactly when the other begins, do not overlap."

        Design: Difficulty/resource_temporal_overlap/agent_field_window_half_open_adjacency
        """
        agent, _, ctx2, _ = self._setup_agent_with_first_window(api)
        # [05-17, 05-18) abuts [05-16, 05-17) at the point 05-17: not overlap.
        resp = api.create_repo_assignment(
            ctx2["case"]["id"],
            {"agent_id": agent["id"],
             "field_window_start": "2026-05-17T00:00:00Z",
             "field_window_end": "2026-05-18T00:00:00Z"},
            rm_headers())
        created = validate_success(resp, expected_status=201)
        assert created["status"] == "ASSIGNED"
        assert created["auto_selected"] is False

    def test_agent_field_window_true_overlap_rejected(self, api):
        """PRD §3.3: "the new half-open window must not overlap the window of
        any `ASSIGNED` or `ACCEPTED` assignment the agent already holds
        (`ERR_FIELD_WINDOW_OVERLAP`, HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/agent_field_window_half_open_adjacency
        """
        agent, _, ctx2, ctx3 = self._setup_agent_with_first_window(api)
        resp = api.create_repo_assignment(
            ctx3["case"]["id"],
            {"agent_id": agent["id"],
             "field_window_start": "2026-05-16T12:00:00Z",
             "field_window_end": "2026-05-18T00:00:00Z"},
            rm_headers())
        validate_error(resp, ApiErrorId.ERR_FIELD_WINDOW_OVERLAP)
        assert list_case_assignments(ctx3["case"]["id"]) == []


class TestExplicitAssignmentPriority:
    """Business-safety tier (PRD §2.7 step 6) beats business constraints
    (step 8) when both fail on the same request."""

    def _setup_dual_violation(self, api):
        """TX-only agent, capacity 1, already holding one ASSIGNED assignment;
        the target case is CA-governed. The next explicit assignment violates
        licensing (step 6) AND capacity (step 8)."""
        ctx_tx = setup_case_cure_pending(
            borrower_overrides={"full_name": "TXB", "state_code": "TX", "email": "txb@x.com"},
            loan_overrides={"vin": "VIN00000000000017", "governing_state_code": "TX",
                            "principal_balance_cents": 500_000, "apr_bps": 900,
                            "monthly_payment_cents": 20_000, "missed_installments": 2,
                            "accrued_interest_cents": 8_000, "late_fees_cents": 3_000})
        agent = create_agent(name="TX Only", license_number="LIC-TX",
                             licensed_state_codes=["TX"], max_active_assignments=1)
        set_clock("2026-05-16T00:00:00Z")  # TX case cure-expires
        assign_agent(ctx_tx["case"]["id"], agent["id"],
                     field_window_start="2026-05-16T00:00:00Z",
                     field_window_end="2026-05-17T00:00:00Z")

        ctx_ca = setup_case_cure_pending(
            borrower_overrides={"full_name": "CAB", "email": "cab@x.com"},
            loan_overrides=_small_loan("VIN00000000000018"))
        set_clock("2026-05-31T00:00:00Z")  # CA case cure-expires (deadline 05-15)
        return agent, ctx_ca

    def test_license_beats_capacity_on_assignment_error_id(self, api):
        """PRD §2.7: "Every mutating request passes through a fixed validation
        cascade, and the first failing check wins — later checks are never
        evaluated for a rejected request. The order is: ... (6) business-safety
        rules — segregation of duties, agent-suspension, and agent-licensing
        checks (`ERR_SEGREGATION_OF_DUTIES`, `ERR_AGENT_SUSPENDED`,
        `ERR_AGENT_LICENSE_MISMATCH`); ... (8) business constraints
        (`ERR_DUPLICATE_OPEN_CASE`, `ERR_AGENT_CAPACITY_EXCEEDED`,
        `ERR_FIELD_WINDOW_OVERLAP`, `ERR_NO_ELIGIBLE_AGENT`,
        `ERR_AUCTION_WINDOW_OVERLAP`)"

        Design: Difficulty/priority_pair_validation_conflict/license_beats_capacity_on_assignment
        """
        agent, ctx_ca = self._setup_dual_violation(api)
        resp = api.create_repo_assignment(
            ctx_ca["case"]["id"],
            {"agent_id": agent["id"],
             "field_window_start": "2026-06-05T00:00:00Z",
             "field_window_end": "2026-06-06T00:00:00Z"},
            rm_headers())
        validate_error(resp, ApiErrorId.ERR_AGENT_LICENSE_MISMATCH)

    def test_license_beats_capacity_on_assignment_no_partial_creation(self, api):
        """PRD §2.7: "Every mutating request passes through a fixed validation
        cascade, and the first failing check wins — later checks are never
        evaluated for a rejected request."
        PRD §3.3: "the case's loan `governing_state_code` must appear among
        the agent's `licensed_state_codes` (`ERR_AGENT_LICENSE_MISMATCH`,
        HTTP 422)"

        Design: Difficulty/priority_pair_validation_conflict/license_beats_capacity_on_assignment
        """
        agent, ctx_ca = self._setup_dual_violation(api)
        resp = api.create_repo_assignment(
            ctx_ca["case"]["id"],
            {"agent_id": agent["id"],
             "field_window_start": "2026-06-05T00:00:00Z",
             "field_window_end": "2026-06-06T00:00:00Z"},
            rm_headers())
        validate_error(resp, ApiErrorId.ERR_AGENT_LICENSE_MISMATCH)
        assert list_case_assignments(ctx_ca["case"]["id"]) == [], (
            "no assignment is created when the create is rejected")
        agent_after = get_agent(agent["id"])
        held = validate_success(api.list_agent_assignments(agent_after["id"], rm_headers()))
        assert len(held) == 1, "the agent still holds exactly its original assignment"


class TestAutoSelection:
    def test_auto_select_ranks_score_then_created_at(self, api):
        """PRD §3.3: "The eligible pool is ranked by `performance_score_rolling`
        descending, with ties broken by the agent's `created_at` in ascending
        order — the earliest-registered agent wins a tie. The first agent of
        that ranking is selected"
        PRD §3.3: "When `agent_id` is omitted, the server selects the agent and
        marks the assignment `auto_selected`."

        Design: Corner/complexity_layers/auto_select_ranks_score_then_created_at
        """
        # Score-fodder case: gives Lo one EXPIRED assignment (rolling 90).
        ctx1 = setup_case_cure_pending(
            borrower_overrides={"full_name": "SA", "email": "sa@x.com"},
            loan_overrides=_small_loan("VIN00000000000074"))
        agent_lo = create_agent(name="Lo", license_number="LIC-LO")  # created at the 05-01 epoch
        set_clock("2026-05-16T00:00:00Z")  # ctx1 cure-expires
        assign_agent(ctx1["case"]["id"], agent_lo["id"],
                     field_window_start="2026-05-16T00:00:00Z",
                     field_window_end="2026-05-17T00:00:00Z")
        set_clock("2026-05-19T00:00:00Z")  # Lo's assignment expires unaccepted -> rolling 90
        agent_ha = create_agent(name="HiA", license_number="LIC-HA")  # created 05-19
        set_clock("2026-05-20T00:00:00Z")
        agent_hb = create_agent(name="HiB", license_number="LIC-HB")  # created 05-20

        # Target case: notice issued 05-20, deadline 06-03; at 06-04 it is CURE_EXPIRED.
        ctx2 = setup_case_cure_pending(
            borrower_overrides={"full_name": "SB", "email": "sb@x.com"},
            loan_overrides=_small_loan("VIN00000000000075"))
        set_clock("2026-06-04T00:00:00Z")

        resp = api.create_repo_assignment(
            ctx2["case"]["id"],
            {"field_window_start": "2026-06-04T00:00:00Z",
             "field_window_end": "2026-06-05T00:00:00Z"},
            rm_headers())
        assignment = validate_success(resp, expected_status=201)
        assert assignment["auto_selected"] is True
        assert assignment["agent_id"] == agent_ha["id"], (
            "HiA and HiB tie at 100 rolling; HiA's earlier created_at wins; "
            "Lo at 90 is never reached")
        assert agent_hb["id"] != assignment["agent_id"]

    def test_auto_select_empty_pool_returns_no_eligible_agent(self, api):
        """PRD §3.3: "Eligibility for the pool requires all of: the agent is
        `ACTIVE`; the agent is licensed in the case loan's governing state; the
        agent's live `ASSIGNED`-or-`ACCEPTED` count is below its capacity cap;
        the new field window does not overlap (in the same half-open sense) any
        of the agent's live assignment windows; and the agent has never held an
        assignment on this very case that ended in `BREACHED_PEACE`. ... an
        empty pool rejects the create with `ERR_NO_ELIGIBLE_AGENT` (HTTP 422)."

        Design: Corner/complexity_layers/auto_select_empty_pool_returns_no_eligible_agent
        """
        ctx = setup_case_cure_pending(
            borrower_overrides={"full_name": "NE", "email": "ne@x.com"},
            loan_overrides=_small_loan("VIN00000000000076"))
        create_agent(name="TX only", license_number="LIC-TX2",
                     licensed_state_codes=["TX"], max_active_assignments=5)
        set_clock("2026-05-16T00:00:00Z")  # cure-expires
        resp = api.create_repo_assignment(
            ctx["case"]["id"],
            {"field_window_start": "2026-05-16T00:00:00Z",
             "field_window_end": "2026-05-18T00:00:00Z"},
            rm_headers())
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_AGENT)
