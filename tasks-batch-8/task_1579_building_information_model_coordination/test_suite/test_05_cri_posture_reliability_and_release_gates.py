"""Coordination readiness index composition, project posture, partner
reliability decay, the reopen-breach-probation cascade, validation priority
pairs, and the release gates they drive."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_phase,
    advance_phase_to,
    assign_clash,
    create_and_accept_model,
    create_clash_run,
    create_commitment,
    create_federated_model,
    create_in_session_meeting,
    create_meeting,
    create_package,
    create_partner,
    create_project,
    freeze_fed,
    get_clash,
    get_commitment,
    get_package,
    get_partner,
    get_project,
    import_clash,
    list_package_signoffs,
    make_bim_coordinator_headers,
    make_fabrication_lead_headers,
    make_trade_model_author_headers,
    resolve_clash,
    run_coordination_sweep,
    set_clock,
    setup_in_session_meeting_with_assigned_clash,
    setup_partner_with_reliability,
    setup_probation_partner_via_reopen,
    setup_running_run,
    setup_verified_clash,
    sign_signoff,
    start_meeting,
    start_run,
    submit_package_for_signoff,
    validate_error,
    validate_paginated,
    validate_success,
    verify_clash,
    waive_commitment,
)

VDC = TEST_USERS["vdc_manager_headers"]
COORD = TEST_USERS["bim_coordinator_headers"]  # operator "coord-1"
COORD2 = make_bim_coordinator_headers("coord-2")


class TestCriComposition:
    def test_cri_multi_factor_threshold_blend(self, api):
        """PRD §2.6: "CRI starts from 100 and subtracts 25 points for each
        open `CRITICAL` clash in the project, 10 points for each open `MAJOR`
        clash, 5 points for each unassigned `MINOR` clash, and 15 points for
        each overdue commitment; a result below zero is floored at zero."
        PRD §2.6: "The project sits in `COORDINATION_HOLD` whenever the CRI
        falls below 60"
        PRD §2.5: "Advancing the clock recomputes the clock-dependent derived
        fields of every project — `overdue_commitment_count`,
        `coordination_readiness_index`, and `coordination_posture`. Advancing
        the clock does not by itself breach overdue commitments; breaching is
        the exclusive job of the coordination sweep described in §3.5."

        Design: Difficulty/combinatorial_formula/cri_multi_factor_threshold_blend
        """
        ws = setup_running_run("CF1")
        pid = ws["project"]["id"]
        c1 = import_clash(ws["run"]["id"], "STR-1/MEP-1", 75.0, True)  # CRITICAL
        import_clash(ws["run"]["id"], "STR-2/MEP-2", 30.0)             # MAJOR, NEW
        import_clash(ws["run"]["id"], "STR-3/MEP-3", 0.0)              # MINOR, NEW
        assign_clash(c1["id"], ws["partner"]["id"])  # CRITICAL stays open

        meeting = create_meeting(pid, room_id="RM-A",
                                 starts_at="2026-08-10T09:00:00Z",
                                 ends_at="2026-08-10T10:00:00Z")
        set_clock("2026-08-10T09:30:00Z")
        start_meeting(meeting["id"])
        commitment = create_commitment(meeting["id"], c1["id"],
                                       ws["partner"]["id"],
                                       "2026-08-11T00:00:00Z")

        # Advance past the deadline: the commitment becomes overdue WITHOUT
        # being breached (no sweep has run).
        set_clock("2026-08-12T00:00:00Z")

        project = get_project(pid)
        assert project["open_critical_count"] == 1
        assert project["open_major_count"] == 1
        assert project["unassigned_minor_count"] == 1
        assert project["overdue_commitment_count"] == 1
        assert project["coordination_readiness_index"] == 45, \
            "100 - 25 (open CRITICAL) - 10 (open MAJOR) - 5 (unassigned MINOR) - 15 (overdue)"
        assert project["coordination_posture"] == "COORDINATION_HOLD", "45 < 60"
        assert get_commitment(commitment["id"])["status"] == "COMMITTED", \
            "clock advancement alone never breaches"

    def test_cri_blend_recomputed_by_sweep_after_breach(self, api):
        """PRD §3.5: "Invoking it walks every commitment still `COMMITTED`
        whose `due_at` is strictly before the logical clock — processed in
        creation order, earlier `created_at` first, ties broken by earlier
        `due_at` — and marks each one `BREACHED`. Every breach applies the
        reliability decay to the breaching partner and recomputes the
        meeting's `breached_commitment_count`; the sweep then recomputes the
        project's CRI and posture, increments `ops_sweep_index` by one, and
        increments the project's `version` by one."
        PRD §2.6: "A commitment counts as overdue while `COMMITTED` with a
        `due_at` strictly earlier than the logical clock."

        Design: Difficulty/combinatorial_formula/cri_multi_factor_threshold_blend
        """
        ws = setup_running_run("CF1B")
        pid = ws["project"]["id"]
        c1 = import_clash(ws["run"]["id"], "STR-1/MEP-1", 75.0, True)
        import_clash(ws["run"]["id"], "STR-2/MEP-2", 30.0)
        import_clash(ws["run"]["id"], "STR-3/MEP-3", 0.0)
        assign_clash(c1["id"], ws["partner"]["id"])
        meeting = create_meeting(pid, room_id="RM-A",
                                 starts_at="2026-08-10T09:00:00Z",
                                 ends_at="2026-08-10T10:00:00Z")
        set_clock("2026-08-10T09:30:00Z")
        start_meeting(meeting["id"])
        commitment = create_commitment(meeting["id"], c1["id"],
                                       ws["partner"]["id"],
                                       "2026-08-11T00:00:00Z")
        set_clock("2026-08-12T00:00:00Z")
        assert get_commitment(commitment["id"])["status"] == "COMMITTED"

        run_coordination_sweep(pid)

        assert get_commitment(commitment["id"])["status"] == "BREACHED"
        partner = get_partner(pid, ws["partner"]["id"])
        assert partner["reliability_score"] == pytest.approx(95.0, abs=1e-6), \
            "first breach reads tier A (score 100 >= 80): -5"
        assert partner["breach_count"] == 1
        project = get_project(pid)
        # The breached commitment is no longer COMMITTED, so it no longer
        # counts as overdue: 100 - 25 - 10 - 5 = 60.
        assert project["overdue_commitment_count"] == 0
        assert project["coordination_readiness_index"] == 60
        assert project["coordination_posture"] == "NORMAL", \
            "60 is not below 60 and no PROBATION partner carries an open clash"
        assert project["ops_sweep_index"] == 1

    def test_cri_counts_unassigned_minor_only(self, api):
        """PRD §2.6: "5 points for each unassigned `MINOR` clash" and
        "A `MINOR` clash counts as unassigned while `NEW` or `REOPENED`."
        PRD §3.4: "Every assignment recomputes the project's CRI and posture."

        Design: Corner/calculations/cri_counts_unassigned_minor_only
        """
        ws = setup_running_run("CAL5")
        clash = import_clash(ws["run"]["id"], "M/1", 0.0)  # MINOR, NEW

        project = get_project(ws["project"]["id"])
        assert project["unassigned_minor_count"] == 1
        assert project["coordination_readiness_index"] == 95, "100 - 5"

        assign_clash(clash["id"], ws["partner"]["id"])
        project = get_project(ws["project"]["id"])
        assert project["unassigned_minor_count"] == 0
        assert project["coordination_readiness_index"] == 100, \
            "assignment removes the MINOR clash from the unassigned set " \
            "without closing it"

    def test_derived_cri_recomputed_per_mutation(self, api):
        """PRD §2.6: "The index is recomputed on every clash import,
        assignment, resolution, verification, and reopening"
        PRD §2.6: "A clash counts as open while its status is `NEW`,
        `ASSIGNED`, `RESOLVED`, or `REOPENED` — `VERIFIED` is closed."

        Design: Corner/complexity_layers/derived_cri_recomputed_per_mutation
        """
        ws = setup_running_run("CL4")
        pid = ws["project"]["id"]
        assert get_project(pid)["coordination_readiness_index"] == 100

        clash = import_clash(ws["run"]["id"], "D/1", 75.0, True)  # CRITICAL
        assert get_project(pid)["coordination_readiness_index"] == 75, \
            "one open CRITICAL: 100 - 25"

        assign_clash(clash["id"], ws["partner"]["id"])
        resolve_clash(clash["id"], ws["partner"]["id"], 1.0)
        assert get_project(pid)["coordination_readiness_index"] == 75, \
            "RESOLVED is still an open status"

        verify_clash(clash["id"], 0.0)
        assert get_project(pid)["coordination_readiness_index"] == 100, \
            "VERIFIED is closed"


class TestReliabilityDecay:
    def test_reliability_pre_event_tier_evaluation_order(self, api):
        """PRD §3.5: "Reliability decay is tiered, and the tier is always read
        from the partner's score immediately before the breach. A
        `reliability_score` of 80 or above loses 5 points; a score of at least
        50 but below 80 loses 10; a score below 50 loses 20."
        PRD §3.5: "when the resulting score falls below 40 while the partner
        is `ACTIVE`, the partner moves to `PROBATION`."

        Design: Difficulty/combinatorial_formula/reliability_pre_event_tier_evaluation_order
        """
        # Six swept breaches walk 100 -> 95 -> 90 -> 85 -> 80 -> 75 -> 65:
        # the sixth breach reads tier B from the pre-event score 75.
        ws = setup_partner_with_reliability("CF3", breach_count=6)
        partner = ws["partner"]
        assert partner["reliability_score"] == pytest.approx(65.0, abs=1e-6)
        assert partner["breach_count"] == 6
        assert partner["status"] == "ACTIVE", "65 >= 40: no probation"

        commitments, meta = validate_paginated(api.list_commitments(
            COORD, params={"meeting_id": ws["meeting"]["id"]}))
        assert meta["total_count"] == 6
        assert all(c["status"] == "BREACHED" for c in commitments)

    def test_reliability_tier_read_at_exactly_80_loses_5(self, api):
        """PRD §3.5: "A partner sitting at exactly 80 therefore loses 5 —
        reading the tier from the post-breach score is a different, rejected
        interpretation."

        Design: Difficulty/combinatorial_formula/reliability_pre_event_tier_evaluation_order
        """
        # Four breaches land on exactly 80 (100-5-5-5-5); the fifth breach
        # must read tier A from that pre-event 80 and subtract 5, landing on
        # 75 — the rejected post-event reading would land on 70.
        ws = setup_partner_with_reliability("CF3B", breach_count=5)
        partner = ws["partner"]
        assert partner["reliability_score"] == pytest.approx(75.0, abs=1e-6), \
            "fifth breach: tier read from pre-event 80 -> -5, not -10"
        assert partner["breach_count"] == 5
        assert partner["status"] == "ACTIVE"


class TestReopenBreachCascade:
    def test_reopen_breach_reliability_probation_chain(self, api):
        """PRD §3.4: "a linked commitment in `FULFILLED` becomes `BREACHED`,
        the reliability decay of §3.5 is applied to that commitment's partner
        with the probation consequence described there, and the project's CRI
        and posture are recomputed."
        PRD §3.5: "when the resulting score falls below 40 while the partner
        is `ACTIVE`, the partner moves to `PROBATION`."

        Design: Difficulty/transitive_cascade/reopen_breach_reliability_probation_chain
        """
        ws = setup_probation_partner_via_reopen("TC2")
        # The fixture: 8 swept breaches (score 45, ACTIVE, breach_count 8),
        # then a MINOR clash verified (commitment FULFILLED) and reopened.
        assert ws["reopened_clash"]["status"] == "REOPENED"
        assert ws["reopened_clash"]["cycle_count"] == 1
        assert get_commitment(ws["commitment"]["id"])["status"] == "BREACHED", \
            "the reopen invalidates the fulfilled resolution"

        partner = ws["partner"]
        assert partner["reliability_score"] == pytest.approx(25.0, abs=1e-6), \
            "pre-event 45 is tier C: -20"
        assert partner["breach_count"] == 9
        assert partner["status"] == "PROBATION", "25 < 40"

    def test_probation_blocks_new_assignment(self, api):
        """PRD §3.4: "The partner must also be `ACTIVE`; a partner on
        probation cannot take new clash work
        (`ERR_TRADE_PARTNER_ON_PROBATION`)."

        Design: Difficulty/transitive_cascade/reopen_breach_reliability_probation_chain
        """
        ws = setup_probation_partner_via_reopen("TC2B")
        assert ws["partner"]["status"] == "PROBATION"

        fresh = import_clash(ws["run"]["id"], "E/10", 0.0)
        resp = api.assign_clash(fresh["id"],
                                {"trade_partner_id": ws["partner"]["id"]}, COORD)
        validate_error(resp, ApiErrorId.ERR_TRADE_PARTNER_ON_PROBATION)
        assert get_clash(fresh["id"])["status"] == "NEW", \
            "no assignment persisted for a probated partner"


class TestCommitmentWaive:
    def test_commitment_waive_terminal_and_sweep_immunity(self, api):
        """PRD §3.5: "A `BIMCoordinator` may instead waive a `COMMITTED`
        commitment — waiving from any other state is `ERR_COMMITMENT_NOT_OPEN`"
        PRD §3.5: "Invoking it walks every commitment still `COMMITTED` whose
        `due_at` is strictly before the logical clock"
        PRD §3.5: "Every breach applies the reliability decay to the breaching
        partner" (a waived commitment is never breached, so no decay applies).

        Design: Corner/state_machines/commitment_waive_terminal_and_sweep_immunity
        """
        ws = setup_in_session_meeting_with_assigned_clash("SM16")
        commitment = create_commitment(ws["meeting"]["id"], ws["clash"]["id"],
                                       ws["partner"]["id"],
                                       "2026-08-02T00:00:00Z")

        waived = waive_commitment(commitment["id"])
        assert waived["status"] == "WAIVED"

        e1 = api.waive_commitment(commitment["id"], COORD)
        validate_error(e1, ApiErrorId.ERR_COMMITMENT_NOT_OPEN)

        # The clock passes the deadline and the sweep runs: a WAIVED
        # commitment is not COMMITTED, so the sweep never touches it.
        set_clock("2026-08-03T00:00:00Z")
        run_coordination_sweep(ws["project"]["id"])
        assert get_commitment(commitment["id"])["status"] == "WAIVED"
        partner = get_partner(ws["project"]["id"], ws["partner"]["id"])
        assert partner["reliability_score"] == pytest.approx(100.0, abs=1e-6), \
            "a waived commitment applies no reliability penalty"


class TestParallelStateDimensions:
    def test_project_phase_posture_parallel_dimensions(self, api):
        """PRD §2.6: "Alongside `current_phase`, every project carries a
        second, parallel state dimension: `coordination_posture`. The two
        evolve independently — posture is never set directly and never gates
        phase advancement."
        PRD §2.6: "The project returns to `NORMAL` once the CRI is again at
        least 60 and no probated partner carries an open assigned clash."

        Design: Difficulty/non_linear_state_machine/project_phase_posture_parallel_dimensions
        """
        ws = setup_running_run("NL2")
        pid = ws["project"]["id"]
        # Three open CRITICAL clashes: CRI = 100 - 3 x 25 = 25 < 60 -> HOLD.
        clashes = [import_clash(ws["run"]["id"], f"A/{i}", 75.0, True)
                   for i in (1, 2, 3)]

        # Phase advances while the hold is in force — the dimensions coexist.
        advanced = advance_phase(pid)
        assert advanced["current_phase"] == "DESIGN_DEVELOPMENT"
        project = get_project(pid)
        assert project["coordination_posture"] == "COORDINATION_HOLD"
        assert project["coordination_readiness_index"] == 25

        # Clearing the clashes returns posture to NORMAL; the phase is
        # untouched by clash work.
        for clash in clashes:
            assign_clash(clash["id"], ws["partner"]["id"])
            resolve_clash(clash["id"], ws["partner"]["id"], 1.0)
            verify_clash(clash["id"], 0.0)

        project = get_project(pid)
        assert project["coordination_posture"] == "NORMAL"
        assert project["coordination_readiness_index"] == 100
        assert project["current_phase"] == "DESIGN_DEVELOPMENT"

    def test_posture_hold_does_not_gate_phase_advancement(self, api):
        """PRD §2.6: "The two evolve independently — posture is never set
        directly and never gates phase advancement."

        Design: Difficulty/non_linear_state_machine/project_phase_posture_parallel_dimensions
        """
        ws = setup_running_run("NL2B")
        pid = ws["project"]["id"]
        # Two open CRITICAL clashes: CRI 50 < 60 -> HOLD.
        import_clash(ws["run"]["id"], "A/1", 75.0, True)
        import_clash(ws["run"]["id"], "A/2", 75.0, True)
        assert get_project(pid)["coordination_posture"] == "COORDINATION_HOLD"

        advanced = validate_success(api.advance_phase(pid, VDC))
        assert advanced["current_phase"] == "DESIGN_DEVELOPMENT", \
            "phase advancement is not gated by the coordination hold"
        assert get_project(pid)["coordination_posture"] == "COORDINATION_HOLD"


class TestValidationPriorityPairs:
    def test_resolve_state_beats_fiscal_on_dual_violation(self, api):
        """PRD §2.8: "Twelfth and last, the fiscal budget check on clash
        resolution — a request can only fail `ERR_COORDINATION_BUDGET_EXCEEDED`
        after passing every earlier business rule."
        PRD §3.4: "claims the fix from `ASSIGNED` (`ERR_CLASH_NOT_RESOLVABLE`
        otherwise) by reporting `actual_labor_hours`."

        Design: Difficulty/priority_pair_validation_conflict/resolve_state_beats_fiscal_on_dual_violation
        """
        # C1 is VERIFIED (fails the state gate) AND the claim of 90.0 h
        # exceeds the remaining budget 78.5 h (fails the fiscal gate). The
        # PRD's validation order makes the state error the only possible
        # response.
        ws = setup_verified_clash("PP1", overlap_mm=30.0, actual_labor_hours=21.5)
        resp = api.resolve_clash(
            ws["clash"]["id"], {"actual_labor_hours": 90.0},
            make_trade_model_author_headers(ws["partner"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CLASH_NOT_RESOLVABLE)

        assert get_clash(ws["clash"]["id"])["status"] == "VERIFIED"
        partner = get_partner(ws["project"]["id"], ws["partner"]["id"])
        assert partner["consumed_resolution_hours"] == pytest.approx(21.5, abs=1e-9), \
            "a rejected resolve debits nothing"

    def test_resolve_state_and_fiscal_errors_each_reachable_in_isolation(self, api):
        """PRD §3.4: "claims the fix from `ASSIGNED` (`ERR_CLASH_NOT_RESOLVABLE`
        otherwise)"
        PRD §3.4: "the claimed hours must not exceed the partner's remaining
        coordination budget, `coordination_budget_hours` less
        `consumed_resolution_hours`, or the resolve is rejected with
        `ERR_COORDINATION_BUDGET_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/resolve_state_beats_fiscal_on_dual_violation
        """
        ws = setup_running_run("PP1C")
        pid = ws["project"]["id"]
        c1 = import_clash(ws["run"]["id"], "P/1", 30.0)
        assign_clash(c1["id"], ws["partner"]["id"])
        resolve_clash(c1["id"], ws["partner"]["id"], 99.0)
        verify_clash(c1["id"], 0.0)  # VERIFIED

        # State-only violation: VERIFIED clash, tiny claim.
        e1 = api.resolve_clash(
            c1["id"], {"actual_labor_hours": 0.5},
            make_trade_model_author_headers(ws["partner"]["id"]))
        validate_error(e1, ApiErrorId.ERR_CLASH_NOT_RESOLVABLE)

        # Fiscal-only violation: ASSIGNED clash, claim 2.0 > remaining 1.0.
        c2 = import_clash(ws["run"]["id"], "P/2", 30.0)
        assign_clash(c2["id"], ws["partner"]["id"])
        e2 = api.resolve_clash(
            c2["id"], {"actual_labor_hours": 2.0},
            make_trade_model_author_headers(ws["partner"]["id"]))
        validate_error(e2, ApiErrorId.ERR_COORDINATION_BUDGET_EXCEEDED)
        assert get_partner(pid, ws["partner"]["id"])[
            "consumed_resolution_hours"] == pytest.approx(99.0, abs=1e-9)

    def test_assign_safety_beats_referential_on_dual_violation(self, api):
        """PRD §2.8: "Eighth, compliance and segregation gates: the LOD floor
        and the interoperability check at model submission, the member audit
        floor at freeze, the two segregation-of-duties rules at clash
        verification and at signing or declining a sign-off, the probation bar
        at clash assignment, and the posture gate at the two release
        operations."
        PRD §2.8: "Ninth, same-project referential integrity: every
        body-referenced resource must belong to the project in the path —
        enforced at federated-assembly creation, clash-run creation,
        commitment creation, package creation, as-built creation, takeoff
        creation, handover creation, freeze-window creation, and clash
        assignment — and a commitment's `committed_by_partner_id` must equal
        its clash's `assigned_trade_partner_id`
        (`ERR_COMMITMENT_TRADE_MISMATCH`)."
        PRD §3.4: "The partner must also be `ACTIVE`; a partner on probation
        cannot take new clash work (`ERR_TRADE_PARTNER_ON_PROBATION`)."

        Design: Difficulty/priority_pair_validation_conflict/assign_safety_beats_referential_on_dual_violation
        """
        # Project A hosts the NEW clash under assignment.
        project_a = create_project("PP2-A")
        pa = create_partner(project_a["id"], company_name="StructCoA")
        ma = create_and_accept_model(project_a["id"], pa["id"])
        fa = create_federated_model(project_a["id"], [ma["id"]], label="FA")
        freeze_fed(fa["id"])
        ra = create_clash_run(fa["id"], tolerance_mm=5.0)
        start_run(ra["id"])
        ca = import_clash(ra["id"], "A/1", 30.0)

        # Project B's partner is driven to PROBATION by nine swept breaches
        # (100 -> ... -> 45 after eight; the ninth reads tier C from the
        # pre-event 45 and subtracts 20, landing at 25 < 40).
        ws_b = setup_partner_with_reliability("PP2-B", breach_count=9)
        px = ws_b["partner"]
        assert px["status"] == "PROBATION"
        assert px["reliability_score"] == pytest.approx(25.0, abs=1e-6)

        # Dual violation: PROBATION (compliance layer, earlier) AND foreign
        # project (referential layer, later) — the compliance error wins.
        resp = api.assign_clash(ca["id"], {"trade_partner_id": px["id"]},
                                make_bim_coordinator_headers("coord-9"))
        validate_error(resp, ApiErrorId.ERR_TRADE_PARTNER_ON_PROBATION)
        assert get_clash(ca["id"])["status"] == "NEW", \
            "no assignment persisted on the rejected call"

    def test_assign_cross_project_only_violation(self, api):
        """PRD §3.4: "The payload's `trade_partner_id` must identify a partner
        in the clash's own project: an unknown identifier is
        `ERR_TRADE_PARTNER_NOT_FOUND`, and a partner belonging to a different
        project is `ERR_CROSS_PROJECT_REFERENCE`."

        Design: Difficulty/priority_pair_validation_conflict/assign_safety_beats_referential_on_dual_violation
        """
        project_a = create_project("PP2-C")
        pa = create_partner(project_a["id"], company_name="StructCoA")
        ma = create_and_accept_model(project_a["id"], pa["id"])
        fa = create_federated_model(project_a["id"], [ma["id"]], label="FA")
        freeze_fed(fa["id"])
        ra = create_clash_run(fa["id"], tolerance_mm=5.0)
        start_run(ra["id"])
        ca = import_clash(ra["id"], "A/1", 30.0)

        # An ACTIVE partner that merely belongs to a different project:
        # referential failure alone.
        project_b = create_project("PP2-D")
        py = create_partner(project_b["id"], company_name="OtherCoB",
                            discipline="ELECTRICAL", hourly_rate_cents=8000,
                            coordination_budget_hours=10.0,
                            software_platform="REVIT")
        assert py["status"] == "ACTIVE"

        resp = api.assign_clash(ca["id"], {"trade_partner_id": py["id"]}, COORD)
        validate_error(resp, ApiErrorId.ERR_CROSS_PROJECT_REFERENCE)
        assert get_clash(ca["id"])["status"] == "NEW"


class TestReleaseGates:
    def test_federated_release_blocked_by_hold_then_open_critical(self, api):
        """PRD §3.3: "It requires the assembly to be `FROZEN`
        (`ERR_FED_NOT_FROZEN`), the project posture to be `NORMAL`
        (`ERR_PROJECT_IN_COORDINATION_HOLD`), and zero open critical clashes
        across the assembly's clash runs — the assembly's
        `open_critical_count` tracks exactly that figure, and a nonzero value
        blocks release with `ERR_OPEN_CLASHES_REMAIN`. The posture gate is
        evaluated before the open-clash gate, so a project in hold surfaces
        `ERR_PROJECT_IN_COORDINATION_HOLD` even when critical clashes also
        remain."

        Design: Corner/validations/federated_release_blocked_by_hold_then_open_critical
        """
        ws = setup_running_run("V11")
        pid = ws["project"]["id"]
        c1 = import_clash(ws["run"]["id"], "X/1", 75.0, True)
        import_clash(ws["run"]["id"], "X/2", 75.0, True)
        # Two open CRITICAL: CRI 50 < 60 -> COORDINATION_HOLD.
        assert get_project(pid)["coordination_posture"] == "COORDINATION_HOLD"

        e1 = api.release_federated_model(ws["fed"]["id"], VDC)
        validate_error(e1, ApiErrorId.ERR_PROJECT_IN_COORDINATION_HOLD)

        # Close one clash: CRI 75 -> posture NORMAL, but one CRITICAL remains
        # open, so the constraint gate now surfaces.
        assign_clash(c1["id"], ws["partner"]["id"])
        resolve_clash(c1["id"], ws["partner"]["id"], 1.0)
        verify_clash(c1["id"], 0.0)
        project = get_project(pid)
        assert project["coordination_readiness_index"] == 75
        assert project["coordination_posture"] == "NORMAL"

        e2 = api.release_federated_model(ws["fed"]["id"], VDC)
        validate_error(e2, ApiErrorId.ERR_OPEN_CLASHES_REMAIN)

    def test_package_release_blocked_by_cri_in_normal_band(self, api):
        """PRD §3.6: "the project's `coordination_readiness_index` must be at
        least 85 (`ERR_CRI_BELOW_RELEASE_THRESHOLD`)"
        PRD §2.6: "The project sits in `COORDINATION_HOLD` whenever the CRI
        falls below 60" (so 75 sits in the NORMAL band and the CRI gate is
        observable independently of posture).

        Design: Corner/validations/package_release_blocked_by_cri_in_normal_band
        """
        ws = setup_running_run("V12")
        pid = ws["project"]["id"]
        c1 = import_clash(ws["run"]["id"], "X/1", 30.0)  # MAJOR
        assign_clash(c1["id"], ws["partner"]["id"])
        meeting = create_in_session_meeting(pid)
        create_commitment(meeting["id"], c1["id"], ws["partner"]["id"],
                          "2026-08-02T00:00:00Z")
        set_clock("2026-08-03T00:00:00Z")  # overdue, unswept: -15

        fabricator = create_partner(pid, company_name="FabCo",
                                    discipline="MECHANICAL",
                                    hourly_rate_cents=10000,
                                    coordination_budget_hours=50.0,
                                    software_platform="TEKLA")
        package = create_package(pid, ws["fed"]["id"], ["STRUCTURAL"],
                                 fabricator["id"])
        submit_package_for_signoff(package["id"], fabricator["id"])
        sign_signoff(list_package_signoffs(package["id"])[0]["id"])
        advance_phase_to(pid, "CONSTRUCTION_DOCUMENTS")

        project = get_project(pid)
        assert project["coordination_readiness_index"] == 75, \
            "open MAJOR (-10) + overdue commitment (-15)"
        assert project["coordination_posture"] == "NORMAL", "75 >= 60"

        resp = api.release_fabrication_package(
            package["id"], make_fabrication_lead_headers(fabricator["id"]))
        validate_error(resp, ApiErrorId.ERR_CRI_BELOW_RELEASE_THRESHOLD)
        assert get_package(package["id"])["status"] == "READY_FOR_RELEASE"

    def test_cri_exactly_85_release_permitted(self, api):
        """PRD §3.6: "the project's `coordination_readiness_index` must be at
        least 85 (`ERR_CRI_BELOW_RELEASE_THRESHOLD`)" — equality passes.
        PRD §3.6: "A released package stamps `released_at` from the logical
        clock and reaches its terminal `RELEASED` state."

        Design: Difficulty/boundary_precision_check/cri_exactly_85_release_permitted
        """
        ws = setup_running_run("BP2")
        pid = ws["project"]["id"]
        # One MINOR clash, assigned (assigned MINOR does not subtract CRI),
        # plus exactly one overdue commitment (-15): CRI == 85.
        ck = import_clash(ws["run"]["id"], "K/1", 0.0)
        assign_clash(ck["id"], ws["partner"]["id"])
        meeting = create_meeting(pid, room_id="RM-A",
                                 starts_at="2026-08-10T09:00:00Z",
                                 ends_at="2026-08-10T10:00:00Z")
        set_clock("2026-08-10T09:30:00Z")
        start_meeting(meeting["id"])
        create_commitment(meeting["id"], ck["id"], ws["partner"]["id"],
                          "2026-08-11T00:00:00Z")
        set_clock("2026-08-12T00:00:00Z")

        fabricator = create_partner(pid, company_name="FabCo",
                                    discipline="MECHANICAL",
                                    hourly_rate_cents=10000,
                                    coordination_budget_hours=50.0,
                                    software_platform="TEKLA")
        package = create_package(pid, ws["fed"]["id"], ["STRUCTURAL"],
                                 fabricator["id"])
        submit_package_for_signoff(package["id"], fabricator["id"])
        sign_signoff(list_package_signoffs(package["id"])[0]["id"])
        advance_phase_to(pid, "CONSTRUCTION_DOCUMENTS")

        project = get_project(pid)
        assert project["coordination_readiness_index"] == 85
        assert project["coordination_posture"] == "NORMAL"
        assert project["current_phase"] == "CONSTRUCTION_DOCUMENTS"

        released = validate_success(api.release_fabrication_package(
            package["id"], make_fabrication_lead_headers(fabricator["id"])))
        assert released["status"] == "RELEASED", "CRI >= 85 admits equality"
        assert released["released_at"] is not None
        assert released["released_at"].startswith("2026-08-12T00:00:00"), \
            "released_at is stamped from the logical clock"

    def test_cri_80_in_normal_band_release_rejected(self, api):
        """PRD §3.6: "the project's `coordination_readiness_index` must be at
        least 85 (`ERR_CRI_BELOW_RELEASE_THRESHOLD`)"
        PRD §2.6: "5 points for each unassigned `MINOR` clash, and 15 points
        for each overdue commitment"

        Design: Difficulty/boundary_precision_check/cri_exactly_85_release_permitted
        """
        ws = setup_running_run("BP2C")
        pid = ws["project"]["id"]
        ck = import_clash(ws["run"]["id"], "K/1", 0.0)
        assign_clash(ck["id"], ws["partner"]["id"])
        # One unassigned MINOR (-5) on top of the overdue commitment (-15):
        # CRI == 80 — the NORMAL band (>= 60) but below the release floor.
        import_clash(ws["run"]["id"], "K/2", 0.0)
        meeting = create_meeting(pid, room_id="RM-A",
                                 starts_at="2026-08-10T09:00:00Z",
                                 ends_at="2026-08-10T10:00:00Z")
        set_clock("2026-08-10T09:30:00Z")
        start_meeting(meeting["id"])
        create_commitment(meeting["id"], ck["id"], ws["partner"]["id"],
                          "2026-08-11T00:00:00Z")
        set_clock("2026-08-12T00:00:00Z")

        fabricator = create_partner(pid, company_name="FabCo",
                                    discipline="MECHANICAL",
                                    hourly_rate_cents=10000,
                                    coordination_budget_hours=50.0,
                                    software_platform="TEKLA")
        package = create_package(pid, ws["fed"]["id"], ["STRUCTURAL"],
                                 fabricator["id"])
        submit_package_for_signoff(package["id"], fabricator["id"])
        sign_signoff(list_package_signoffs(package["id"])[0]["id"])
        advance_phase_to(pid, "CONSTRUCTION_DOCUMENTS")

        project = get_project(pid)
        assert project["coordination_readiness_index"] == 80
        assert project["coordination_posture"] == "NORMAL"

        resp = api.release_fabrication_package(
            package["id"], make_fabrication_lead_headers(fabricator["id"]))
        validate_error(resp, ApiErrorId.ERR_CRI_BELOW_RELEASE_THRESHOLD)
        assert get_package(package["id"])["status"] == "READY_FOR_RELEASE"
