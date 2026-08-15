"""Clash detection runs, severity classification, the assignment / resolution
/ verification cycle with its dual cost variants, and the verify-reopen
compensating invariant."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assign_clash,
    create_clash_run,
    create_commitment,
    create_in_session_meeting,
    create_model,
    create_partner,
    freeze_fed,
    get_clash,
    get_commitment,
    get_fed,
    get_model,
    get_partner,
    get_run,
    import_clash,
    make_bim_coordinator_headers,
    make_trade_model_author_headers,
    reopen_clash,
    resolve_clash,
    setup_assigned_clash,
    setup_frozen_assembly,
    setup_running_run,
    setup_verified_clash,
    unfreeze_fed,
    validate_error,
    validate_paginated,
    validate_success,
    verify_clash,
)

VDC = TEST_USERS["vdc_manager_headers"]
COORD = TEST_USERS["bim_coordinator_headers"]  # operator "coord-1"
COORD2 = make_bim_coordinator_headers("coord-2")


class TestSeverityClassification:
    def test_severity_classification_exact_50mm_boundary(self, api):
        """PRD §3.4: "Severity is classified at import: an overlap strictly
        greater than 50.0 mm is `CRITICAL`; a positive overlap of at most
        50.0 mm — exactly 50.0 mm included — is `MAJOR`; an overlap of exactly
        0.0 mm is `MINOR`."
        PRD §3.4: "The new clash starts `NEW`, the run's `total_clash_count`
        and `open_clash_count` grow by one"

        Design: Difficulty/boundary_precision_check/severity_classification_exact_50mm_boundary
        """
        ws = setup_running_run("BP1")

        c50 = import_clash(ws["run"]["id"], "B/exact", 50.0)
        assert c50["severity"] == "MAJOR", "50.0 exactly is NOT critical"

        c501 = import_clash(ws["run"]["id"], "B/over", 50.1)
        assert c501["severity"] == "CRITICAL", "strictly greater than 50.0"

        c0 = import_clash(ws["run"]["id"], "B/zero", 0.0)
        assert c0["severity"] == "MINOR", "zero denotes a clearance-only violation"

        run = get_run(ws["run"]["id"])
        assert run["total_clash_count"] == 3
        assert run["open_clash_count"] == 3
        assert run["closed_clash_count"] == 0

    def test_severity_classification_one_decimal_place_precision(self, api):
        """PRD §2.10: "Distances in millimetres are compared at one decimal
        place: the clash-severity boundary sits at 50.0 mm"
        PRD §3.4: "a positive overlap of at most 50.0 mm — exactly 50.0 mm
        included — is `MAJOR`"

        Design: Difficulty/boundary_precision_check/severity_classification_exact_50mm_boundary
        """
        ws = setup_running_run("BP1B")
        c499 = import_clash(ws["run"]["id"], "B/under", 49.9)
        assert c499["severity"] == "MAJOR", "49.9 is one step below the boundary"
        c501 = import_clash(ws["run"]["id"], "B/over", 50.1)
        assert c501["severity"] == "CRITICAL", \
            "50.1 is one step above at 0.1 mm comparison precision"


class TestRunLifecycle:
    def test_run_start_requires_federated_model_frozen(self, api):
        """PRD §3.4: "Starting the run requires four conditions: the run still
        `QUEUED` (`ERR_RUN_NOT_QUEUED`), the assembly still `FROZEN`
        (`ERR_FED_NOT_FROZEN`), every member model `ACCEPTED`
        (`ERR_MODEL_NOT_ACCEPTED`), and no `COORDINATION_FREEZE` freeze window
        on the assembly active at the logical clock"
        PRD §3.3: "Freezing re-pins every member's `pinned_model_version` to
        that model's current version and clears `is_stale`."

        Design: Difficulty/cross_entity_state_dependency/run_start_requires_federated_model_frozen
        """
        ws = setup_frozen_assembly("CE1")
        run = create_clash_run(ws["fed"]["id"], tolerance_mm=5.0)

        # Unfreeze the assembly: the run's own status never changes, yet the
        # start gate now fails on the parent assembly's state.
        unfreeze_fed(ws["fed"]["id"])
        e1 = api.start_clash_run(run["id"], COORD)
        validate_error(e1, ApiErrorId.ERR_FED_NOT_FROZEN)

        # Re-freeze restores startability.
        freeze_fed(ws["fed"]["id"])
        started = validate_success(api.start_clash_run(run["id"], COORD))
        assert started["status"] == "RUNNING"
        assert get_fed(ws["fed"]["id"])["is_stale"] is False

    def test_failed_start_leaves_run_untouched(self, api):
        """PRD §3.4: "Starting the run requires four conditions: the run still
        `QUEUED` (`ERR_RUN_NOT_QUEUED`), the assembly still `FROZEN`
        (`ERR_FED_NOT_FROZEN`)..." and "A started run stamps `started_at` from
        the logical clock and becomes `RUNNING`."

        Design: Difficulty/cross_entity_state_dependency/run_start_requires_federated_model_frozen
        """
        ws = setup_frozen_assembly("CE1B")
        run = create_clash_run(ws["fed"]["id"], tolerance_mm=5.0)
        unfreeze_fed(ws["fed"]["id"])

        validate_error(api.start_clash_run(run["id"], COORD),
                       ApiErrorId.ERR_FED_NOT_FROZEN)
        after = get_run(run["id"])
        assert after["status"] == "QUEUED", \
            "the run's own state is untouched; the gate lives on the assembly"
        assert after.get("started_at") is None, \
            "started_at is stamped only when the run actually starts"

    def test_run_complete_requires_all_clashes_assigned(self, api):
        """PRD §3.4: "Completing the run requires it `RUNNING`
        (`ERR_RUN_NOT_RUNNING`) with no clash still `NEW`
        (`ERR_RUN_HAS_UNASSIGNED_CLASHES`); completion stamps `completed_at`
        and lands the run in its terminal `COMPLETED` state."
        PRD §3.4: "the run still `QUEUED` (`ERR_RUN_NOT_QUEUED`)"
        PRD §2.5: "Before any call has been made, the logical clock reads
        exactly 2026-08-01T00:00:00Z"

        Design: Corner/state_machines/run_complete_requires_all_clashes_assigned
        """
        ws = setup_running_run("SM7")
        clash = import_clash(ws["run"]["id"], "S/1", 10.0)

        e1 = api.complete_clash_run(ws["run"]["id"], COORD)
        validate_error(e1, ApiErrorId.ERR_RUN_HAS_UNASSIGNED_CLASHES)

        assign_clash(clash["id"], ws["partner"]["id"])
        completed = validate_success(api.complete_clash_run(ws["run"]["id"], COORD))
        assert completed["status"] == "COMPLETED"
        assert completed["completed_at"] is not None
        assert completed["completed_at"].startswith("2026-08-01T00:00:00"), \
            "completed_at is stamped from the logical clock (still at its default)"

        e2 = api.start_clash_run(ws["run"]["id"], COORD)
        validate_error(e2, ApiErrorId.ERR_RUN_NOT_QUEUED)
        e3 = api.import_clash(ws["run"]["id"],
                              {"element_pair": "S/2", "overlap_mm": 10.0,
                               "spans_disciplines": False}, COORD)
        validate_error(e3, ApiErrorId.ERR_RUN_NOT_RUNNING)


class TestClashFromStateGates:
    def test_clash_invalid_from_transitions_rejected(self, api):
        """PRD §3.4: "Assignment is allowed from `NEW` or `REOPENED` — any
        other state draws `ERR_CLASH_NOT_ASSIGNABLE`."
        PRD §3.4: "Verification requires `RESOLVED`
        (`ERR_CLASH_NOT_VERIFIABLE`)"
        PRD §3.4: "reopening from any other state is
        `ERR_CLASH_NOT_REOPENABLE`"

        Design: Corner/state_machines/clash_invalid_from_transitions_rejected
        """
        ws = setup_assigned_clash("SM6", overlap_mm=30.0)
        clash_id = ws["clash"]["id"]

        e1 = api.assign_clash(clash_id,
                              {"trade_partner_id": ws["partner"]["id"]}, COORD)
        validate_error(e1, ApiErrorId.ERR_CLASH_NOT_ASSIGNABLE)

        e2 = api.verify_clash(clash_id, {"re_inspection_overlap_mm": 0.0}, COORD2)
        validate_error(e2, ApiErrorId.ERR_CLASH_NOT_VERIFIABLE)

        e3 = api.reopen_clash(clash_id, COORD)
        validate_error(e3, ApiErrorId.ERR_CLASH_NOT_REOPENABLE)

        assert get_clash(clash_id)["status"] == "ASSIGNED"


class TestVerifyBranches:
    def test_verify_failed_measurement_reopens_clash(self, api):
        """PRD §3.4: "When the re-inspection overlap exceeds the tolerance,
        the re-inspection has failed: the clash returns to `REOPENED`, its
        `cycle_count` increments by one, and CRI and posture are recomputed."
        PRD §3.5: "The happy path is the verification cascade of §3.4: when
        the linked clash passes re-inspection while the commitment is
        `COMMITTED` and its `due_at` has not yet passed at the logical clock,
        the commitment becomes `FULFILLED`"

        Design: Corner/state_machines/verify_failed_measurement_reopens_clash
        """
        ws = setup_assigned_clash("SM9", overlap_mm=30.0)
        # The commitment references an ASSIGNED clash (PRD §3.5), so it is
        # recorded before the resolve.
        meeting = create_in_session_meeting(ws["project"]["id"])
        commitment = create_commitment(meeting["id"], ws["clash"]["id"],
                                       ws["partner"]["id"],
                                       "2026-09-01T00:00:00Z")
        resolve_clash(ws["clash"]["id"], ws["partner"]["id"], 3.0)

        # 5.1 > run tolerance 5.0: the re-inspection fails.
        verified = api.verify_clash(ws["clash"]["id"],
                                    {"re_inspection_overlap_mm": 5.1}, COORD2)
        data = validate_success(verified)
        assert data["status"] == "REOPENED"
        assert data["cycle_count"] == 1
        assert get_commitment(commitment["id"])["status"] == "COMMITTED", \
            "no fulfillment on a failed re-inspection"

    def test_verify_at_exact_tolerance_verifies(self, api):
        """PRD §3.4: "When the re-inspection overlap is at most the tolerance
        — equality passes — the clash becomes `VERIFIED`." and "a linked
        commitment still `COMMITTED` whose `due_at` is not earlier than the
        logical clock becomes `FULFILLED` with `fulfilled_at` stamped from the
        clock"
        PRD §2.5: "Before any call has been made, the logical clock reads
        exactly 2026-08-01T00:00:00Z"

        Design: Corner/state_machines/verify_at_exact_tolerance_verifies
        """
        ws = setup_assigned_clash("SM10", overlap_mm=30.0)
        # The commitment references an ASSIGNED clash (PRD §3.5), so it is
        # recorded before the resolve.
        meeting = create_in_session_meeting(ws["project"]["id"])
        commitment = create_commitment(meeting["id"], ws["clash"]["id"],
                                       ws["partner"]["id"],
                                       "2026-09-01T00:00:00Z")
        resolve_clash(ws["clash"]["id"], ws["partner"]["id"], 3.0)

        # 5.0 <= tolerance 5.0: equality verifies.
        data = validate_success(api.verify_clash(
            ws["clash"]["id"], {"re_inspection_overlap_mm": 5.0}, COORD2))
        assert data["status"] == "VERIFIED"

        commitment = get_commitment(commitment["id"])
        assert commitment["status"] == "FULFILLED"
        assert commitment["fulfilled_at"] is not None
        assert commitment["fulfilled_at"].startswith("2026-08-01T00:00:00"), \
            "fulfilled_at is stamped from the (default) logical clock"


class TestDualCostVariants:
    def test_clash_cost_provisional_vs_actual_diverge(self, api):
        """PRD §3.4: "computes the forward-looking `provisional_cost_cents`:
        a severity-based base of 40 hours for `CRITICAL`, 16 hours for
        `MAJOR`, or 4 hours for `MINOR`, multiplied by 1.5 when the clash
        spans disciplines and by 1 otherwise, multiplied by the assigned
        partner's current `hourly_rate_cents`, rounded half-up to whole
        cents."
        PRD §3.4: "Its `actual_cost_cents` is computed as the claimed
        `actual_labor_hours` multiplied by the partner's `hourly_rate_cents`
        current at verify time, rounded half-up to whole cents, with no spans
        multiplier"
        PRD §3.4: "adds the hours to the partner's
        `consumed_resolution_hours` — a debit that is never refunded."

        Design: Difficulty/dual_variant_calc/clash_cost_provisional_vs_actual_diverge
        """
        ws = setup_running_run("DV1")
        # CRITICAL (75.0 > 50.0), spans disciplines, partner rate 12000 c/h.
        clash = import_clash(ws["run"]["id"], "STR-1/MEP-1", 75.0, True)
        assigned = assign_clash(clash["id"], ws["partner"]["id"])
        assert assigned["provisional_cost_cents"] == 720000, \
            "40 h x 1.5 spans x 12000 cents/h, forward-looking variant"

        resolve_clash(clash["id"], ws["partner"]["id"], 21.5)
        verified = verify_clash(clash["id"], 2.0)
        assert verified["status"] == "VERIFIED"
        assert verified["provisional_cost_cents"] == 720000
        assert verified["actual_cost_cents"] == 258000, \
            "21.5 h x 12000 cents/h, chronological actual variant"
        assert verified["provisional_cost_cents"] != verified["actual_cost_cents"]

        partner = get_partner(ws["project"]["id"], ws["partner"]["id"])
        assert partner["consumed_resolution_hours"] == pytest.approx(21.5, abs=1e-9)

    def test_actual_cost_null_until_first_passing_verification(self, api):
        """PRD §3.4: "A clash's `actual_cost_cents` stays null until its first
        passing verification and is overwritten by each passing verification
        after a reopen cycle."

        Design: Difficulty/dual_variant_calc/clash_cost_provisional_vs_actual_diverge
        """
        ws = setup_running_run("DV1B")
        clash = import_clash(ws["run"]["id"], "STR-1/MEP-1", 75.0, True)
        assigned = assign_clash(clash["id"], ws["partner"]["id"])
        assert assigned["provisional_cost_cents"] == 720000
        assert assigned.get("actual_cost_cents") is None, \
            "actual cost is a verify-time (final) variant only"

        resolved = resolve_clash(clash["id"], ws["partner"]["id"], 21.5)
        assert resolved.get("actual_cost_cents") is None, \
            "resolution alone does not produce the final cost"

        verified = verify_clash(clash["id"], 2.0)
        assert verified["actual_cost_cents"] == 258000


class TestClashCycle:
    def test_clash_issue_verified_reopened_cycle(self, api):
        """PRD §3.4: "A clash's `actual_cost_cents` stays null until its first
        passing verification and is overwritten by each passing verification
        after a reopen cycle."
        PRD §3.4: "A `BIMCoordinator` may reopen a verified clash — reopening
        from any other state is `ERR_CLASH_NOT_REOPENABLE` — which increments
        `cycle_count`, moves one count from `closed_clash_count` back to
        `open_clash_count`, and invalidates the fulfilled resolution: a linked
        commitment in `FULFILLED` becomes `BREACHED`, the reliability decay of
        §3.5 is applied to that commitment's partner with the probation
        consequence described there, and the project's CRI and posture are
        recomputed."
        PRD §3.4: "adds the hours to the partner's
        `consumed_resolution_hours` — a debit that is never refunded."

        Design: Difficulty/non_linear_state_machine/clash_issue_verified_reopened_cycle
        """
        ws = setup_running_run("NL1")
        clash = import_clash(ws["run"]["id"], "STR-1/MEP-1", 30.0)
        assign_clash(clash["id"], ws["partner"]["id"])
        resolve_clash(clash["id"], ws["partner"]["id"], 4.0)
        verified = verify_clash(clash["id"], 1.0)
        assert verified["actual_cost_cents"] == 48000, "4.0 h x 12000"

        # The full loop: VERIFIED -> REOPENED -> ASSIGNED -> RESOLVED ->
        # VERIFIED.
        reopened = reopen_clash(clash["id"])
        assert reopened["status"] == "REOPENED"
        assert reopened["cycle_count"] == 1

        assign_clash(clash["id"], ws["partner"]["id"])
        resolve_clash(clash["id"], ws["partner"]["id"], 2.0)
        re_verified = verify_clash(clash["id"], 1.0)
        assert re_verified["status"] == "VERIFIED"
        assert re_verified["cycle_count"] == 1
        assert re_verified["actual_cost_cents"] == 24000, \
            "2.0 h x 12000 overwrites the first verify's 48000"

        run = get_run(ws["run"]["id"])
        assert run["total_clash_count"] == 1
        assert run["open_clash_count"] == 0
        assert run["closed_clash_count"] == 1

        partner = get_partner(ws["project"]["id"], ws["partner"]["id"])
        assert partner["consumed_resolution_hours"] == pytest.approx(6.0, abs=1e-9), \
            "4.0 + 2.0; resolved hours are never refunded"

    def test_cycle_count_starts_at_zero_and_tracks_reopens_only(self, api):
        """PRD §3.4: "When the re-inspection overlap exceeds the tolerance,
        the re-inspection has failed: the clash returns to `REOPENED`, its
        `cycle_count` increments by one"

        Design: Difficulty/non_linear_state_machine/clash_issue_verified_reopened_cycle
        """
        ws = setup_verified_clash("NL1C", overlap_mm=30.0, actual_labor_hours=2.0)
        assert ws["clash"]["cycle_count"] == 0, \
            "a clean assign-resolve-verify path never enters REOPENED"

        reopened = reopen_clash(ws["clash"]["id"])
        assert reopened["cycle_count"] == 1
        assign_clash(ws["clash"]["id"], ws["partner"]["id"])
        resolve_clash(ws["clash"]["id"], ws["partner"]["id"], 1.0)
        # A failing re-inspection also cycles the clash.
        failed = validate_success(api.verify_clash(
            ws["clash"]["id"], {"re_inspection_overlap_mm": 9.9}, COORD2))
        assert failed["status"] == "REOPENED"
        assert failed["cycle_count"] == 2


class TestVerifyReopenConservation:
    def test_verify_reopen_conserves_run_clash_counts(self, api):
        """PRD §3.4: "the run's `open_clash_count` decreases by one and its
        `closed_clash_count` increases by one, conserving the total" and
        reopen "moves one count from `closed_clash_count` back to
        `open_clash_count`"

        Design: Difficulty/compensating_invariant/verify_reopen_conserves_run_clash_counts
        """
        ws = setup_running_run("CI1")
        c1 = import_clash(ws["run"]["id"], "I/1", 75.0, True)
        import_clash(ws["run"]["id"], "I/2", 30.0)
        import_clash(ws["run"]["id"], "I/3", 0.0)
        assign_clash(c1["id"], ws["partner"]["id"])
        resolve_clash(c1["id"], ws["partner"]["id"], 4.0)

        verify_clash(c1["id"], 1.0)
        run = get_run(ws["run"]["id"])
        assert (run["open_clash_count"], run["closed_clash_count"],
                run["total_clash_count"]) == (2, 1, 3)

        reopen_clash(c1["id"])
        run = get_run(ws["run"]["id"])
        assert (run["open_clash_count"], run["closed_clash_count"],
                run["total_clash_count"]) == (3, 0, 3), \
            "the compensating reopen moves the count back with zero drift"

        assign_clash(c1["id"], ws["partner"]["id"])
        resolve_clash(c1["id"], ws["partner"]["id"], 2.0)
        verify_clash(c1["id"], 1.0)
        run = get_run(ws["run"]["id"])
        assert (run["open_clash_count"], run["closed_clash_count"],
                run["total_clash_count"]) == (2, 1, 3)

    def test_import_grows_open_and_total_from_zero(self, api):
        """PRD §3.4: "counts `total_clash_count`, `open_clash_count`, and
        `closed_clash_count` from zero" and "The new clash starts `NEW`, the
        run's `total_clash_count` and `open_clash_count` grow by one"

        Design: Difficulty/compensating_invariant/verify_reopen_conserves_run_clash_counts
        """
        ws = setup_running_run("CI1B")
        run = get_run(ws["run"]["id"])
        assert (run["total_clash_count"], run["open_clash_count"],
                run["closed_clash_count"]) == (0, 0, 0)

        import_clash(ws["run"]["id"], "I/1", 75.0, True)
        import_clash(ws["run"]["id"], "I/2", 0.0)
        run = get_run(ws["run"]["id"])
        assert (run["total_clash_count"], run["open_clash_count"],
                run["closed_clash_count"]) == (2, 2, 0)


class TestAssignAndResolveGates:
    def test_assign_unknown_partner_and_interop_submit_rejected(self, api):
        """PRD §3.4: "The payload's `trade_partner_id` must identify a partner
        in the clash's own project: an unknown identifier is
        `ERR_TRADE_PARTNER_NOT_FOUND`"
        PRD §3.2: "a revision whose `interop_status` is `INCOMPATIBLE` is
        rejected with `ERR_INTEROP_INCOMPATIBLE_FORMAT`."

        Design: Corner/validations/assign_unknown_partner_and_interop_submit_rejected
        """
        ws = setup_running_run("V14")
        clash = import_clash(ws["run"]["id"], "V/1", 10.0)

        e1 = api.assign_clash(clash["id"],
                              {"trade_partner_id": NON_EXISTENT_UUID}, COORD)
        validate_error(e1, ApiErrorId.ERR_TRADE_PARTNER_NOT_FOUND)

        # IFC_ONLY partner uploading RVT computes INCOMPATIBLE at creation.
        p3 = create_partner(ws["project"]["id"], company_name="IfcCo",
                            discipline="ELECTRICAL", hourly_rate_cents=9000,
                            coordination_budget_hours=40.0,
                            software_platform="IFC_ONLY")
        mx = create_model(ws["project"]["id"], p3["id"], file_format="RVT",
                          life_safety_elements=1, life_safety_compliant=1,
                          envelope_elements=0, envelope_compliant=0,
                          finish_elements=0, finish_compliant=0)
        assert mx["interop_status"] == "INCOMPATIBLE"

        e2 = api.submit_trade_model(
            mx["id"], make_trade_model_author_headers(p3["id"]))
        validate_error(e2, ApiErrorId.ERR_INTEROP_INCOMPATIBLE_FORMAT)
        assert get_clash(clash["id"])["status"] == "NEW"
        assert get_model(mx["id"])["status"] == "DRAFT"

    def test_ownership_resolve_by_wrong_partner_rejected(self, api):
        """PRD §3.4: "A `TradeModelAuthor` acting for the assigned partner —
        the caller's `X-User-ID` must equal the clash's
        `assigned_trade_partner_id`, else `ERR_FORBIDDEN_OWNERSHIP` —"

        Design: Corner/rbac/ownership_resolve_by_wrong_partner_rejected
        """
        ws = setup_assigned_clash("RB3", overlap_mm=10.0)
        p2 = create_partner(ws["project"]["id"], company_name="OtherCo",
                            discipline="ELECTRICAL", hourly_rate_cents=9000,
                            coordination_budget_hours=40.0,
                            software_platform="IFC_ONLY")

        resp = api.resolve_clash(ws["clash"]["id"], {"actual_labor_hours": 1.0},
                                 make_trade_model_author_headers(p2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
        assert get_clash(ws["clash"]["id"])["status"] == "ASSIGNED"
        assert get_partner(ws["project"]["id"],
                           p2["id"])["consumed_resolution_hours"] == 0

    def test_sod_verify_equals_assign_rejected(self, api):
        """PRD §3.4: "the verifying `BIMCoordinator` must not be the operator
        who assigned the clash, so a caller whose `X-User-ID` equals the
        clash's `assigned_by_user_id` is rejected with
        `ERR_SOD_VERIFY_EQUALS_ASSIGN`."

        Design: Corner/rbac/sod_verify_equals_assign_rejected
        """
        ws = setup_assigned_clash("RB5", overlap_mm=10.0)  # assigned by coord-1
        resolve_clash(ws["clash"]["id"], ws["partner"]["id"], 1.0)

        # coord-1 assigned the clash and may not verify it.
        e1 = api.verify_clash(ws["clash"]["id"],
                              {"re_inspection_overlap_mm": 0.0}, COORD)
        validate_error(e1, ApiErrorId.ERR_SOD_VERIFY_EQUALS_ASSIGN)
        assert get_clash(ws["clash"]["id"])["status"] == "RESOLVED"

        # A different coordinator verifies successfully.
        verified = validate_success(api.verify_clash(
            ws["clash"]["id"], {"re_inspection_overlap_mm": 0.0}, COORD2))
        assert verified["status"] == "VERIFIED"

    def test_resolve_budget_exact_remaining_boundary(self, api):
        """PRD §3.4: "the claimed hours must not exceed the partner's
        remaining coordination budget, `coordination_budget_hours` less
        `consumed_resolution_hours`, or the resolve is rejected with
        `ERR_COORDINATION_BUDGET_EXCEEDED`."

        Design: Corner/calculations/resolve_budget_exact_remaining_boundary
        """
        ws = setup_running_run("CAL4")
        p5 = create_partner(ws["project"]["id"], company_name="TightCo",
                            discipline="ELECTRICAL", hourly_rate_cents=9000,
                            coordination_budget_hours=10.0,
                            software_platform="IFC_ONLY")
        c1 = import_clash(ws["run"]["id"], "B/1", 30.0)
        c2 = import_clash(ws["run"]["id"], "B/2", 30.0)
        c3 = import_clash(ws["run"]["id"], "B/3", 30.0)
        for c in (c1, c2, c3):
            assign_clash(c["id"], p5["id"])

        resolve_clash(c1["id"], p5["id"], 6.0)
        # Exactly the remaining budget (10.0 - 6.0 == 4.0): "must not exceed"
        # admits equality.
        resolved = resolve_clash(c2["id"], p5["id"], 4.0)
        assert resolved["status"] == "RESOLVED"

        # The budget is now exhausted; any positive claim exceeds it.
        e1 = api.resolve_clash(c3["id"], {"actual_labor_hours": 0.2},
                               make_trade_model_author_headers(p5["id"]))
        validate_error(e1, ApiErrorId.ERR_COORDINATION_BUDGET_EXCEEDED)
        partner = get_partner(ws["project"]["id"], p5["id"])
        assert partner["consumed_resolution_hours"] == pytest.approx(10.0, abs=1e-9), \
            "no partial debit on the rejected resolve"


class TestProvisionalCostConstants:
    def test_provisional_cost_constants_minor_no_spans(self, api):
        """PRD §3.4: "computes the forward-looking `provisional_cost_cents`:
        a severity-based base of 40 hours for `CRITICAL`, 16 hours for
        `MAJOR`, or 4 hours for `MINOR`, multiplied by 1.5 when the clash
        spans disciplines and by 1 otherwise, multiplied by the assigned
        partner's current `hourly_rate_cents`, rounded half-up to whole
        cents."

        Design: Corner/calculations/provisional_cost_constants_minor_no_spans
        """
        ws = setup_running_run("CAL3")
        p4 = create_partner(ws["project"]["id"], company_name="PlumbCo",
                            discipline="PLUMBING", hourly_rate_cents=9500,
                            coordination_budget_hours=40.0,
                            software_platform="ARCHICAD")
        # MINOR (overlap 0.0), does not span disciplines, rate 9500 cents/h.
        clash = import_clash(ws["run"]["id"], "P/1", 0.0, False)
        assigned = assign_clash(clash["id"], p4["id"])
        assert assigned["severity"] == "MINOR"
        assert assigned["provisional_cost_cents"] == 38000, "4 x 1.0 x 9500"


class TestClashListing:
    def test_clash_issue_filtered_list_combination(self, api):
        """PRD §3.4: "Clash issues are listable by `clash_run_id`,
        `federated_model_id`, `assigned_trade_partner_id`, `status`, and
        `severity`."

        Design: Corner/endpoints/clash_issue_filtered_list_combination
        """
        ws = setup_running_run("EP1")
        c1 = import_clash(ws["run"]["id"], "F/1", 75.0, True)   # CRITICAL
        c2 = import_clash(ws["run"]["id"], "F/2", 0.0)           # MINOR, NEW
        c3 = import_clash(ws["run"]["id"], "F/3", 0.0)           # MINOR
        assign_clash(c1["id"], ws["partner"]["id"])
        assign_clash(c3["id"], ws["partner"]["id"])

        data, meta = validate_paginated(api.list_clash_issues(
            VDC, params={"clash_run_id": ws["run"]["id"], "status": "NEW",
                         "severity": "MINOR"}))
        assert meta["total_count"] == 1
        assert [c["id"] for c in data] == [c2["id"]]

        data, meta = validate_paginated(api.list_clash_issues(
            VDC, params={"assigned_trade_partner_id": ws["partner"]["id"],
                         "status": "ASSIGNED"}))
        assert meta["total_count"] == 2
        assert {c["id"] for c in data} == {c1["id"], c3["id"]}
