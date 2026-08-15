"""Proposal recommendation gating, concentration checks, SoD, and error
precedence among posture/safety/constraint checks."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    commitment_for_proposal,
    complete_review,
    contribute,
    create_approved_plan,
    create_approved_vehicle,
    create_ic_approved_proposal,
    create_manager,
    create_open_program,
    create_proposal,
    create_recommended_proposal,
    create_vehicle,
    get_latest_review,
    get_program,
    make_analyst_headers,
    make_ic_headers,
    make_ops_headers,
    make_staff_trio,
    program_version,
    register_staff,
    run_vehicle_to_approved,
    score_and_submit_review,
    setup_open_program_with_plan,
    setup_with_executed_commitment,
    validate_error,
    validate_success,
)


class TestRecommendGating:
    def test_proposal_recommend_requires_vehicle_approved(self):
        """PRD §3.4: "The program must be `OPEN` with posture `NORMAL`
        (otherwise `ERR_POSTURE_GATED`); the vehicle must be `APPROVED`
        (otherwise `ERR_VEHICLE_NOT_APPROVED`, HTTP 422); the manager must be
        `APPROVED` (otherwise `ERR_MANAGER_NOT_ELIGIBLE`); the referenced
        pacing plan must be `APPROVED` for this program (otherwise
        `ERR_PLAN_NOT_APPROVED`, HTTP 422)"

        Design: Difficulty/cross_entity_state_dependency/proposal_recommend_requires_vehicle_approved
        """
        ctx = setup_open_program_with_plan(cash=20_000_000, staff_prefix="13", program_name="P13")
        ana_h, ic_h = ctx.analyst_headers, ctx.ic_headers
        manager = create_manager(ana_h, legal_name="MuCap")
        vehicle = create_vehicle(manager["id"], ana_h, fund_name="Mu I")
        validate_success(api_client.begin_diligence(manager["id"], vehicle["id"], ana_h))
        review = get_latest_review(vehicle["id"], ana_h)
        score_and_submit_review(vehicle["id"], review["id"], ana_h, score=80)
        complete_review(vehicle["id"], review["id"], ic_h)

        proposal = create_proposal(vehicle["id"], ctx.program["id"], ctx.plan["id"], ana_h, 1_000_000)
        resp1 = api_client.recommend_proposal(proposal["id"], ana_h)
        validate_error(resp1, ApiErrorId.ERR_VEHICLE_NOT_APPROVED)

        validate_success(api_client.approve_vehicle(manager["id"], vehicle["id"], ic_h))
        ok = validate_success(api_client.recommend_proposal(proposal["id"], ana_h))
        assert ok["status"] == "RECOMMENDED"
        assert ok["concentration_strategy_pct"] == pytest.approx(0.0100, abs=0.00005)
        assert ok["concentration_manager_pct"] == pytest.approx(0.0100, abs=0.00005)

    def test_proposal_recommend_concentration_counts_executed_commitments(self):
        """PRD §3.4: "Each is a post-trade fraction of `total_nav_budget`: the
        strategy figure adds the proposal's `proposed_amount` to the sum of
        `sized_amount` over existing commitments whose vehicle shares the
        proposal vehicle's strategy; the manager figure does the same across
        existing commitments whose vehicle belongs to the proposal vehicle's
        manager."
        PRD §2.9: "Percentage fields reported as fractions —
        `concentration_strategy_pct` and `concentration_manager_pct` — are
        reported to 4 decimal places, round half up, on a 0..1 scale."

        Second test on the same instance: with an EXECUTED 10,000,000 BUYOUT
        commitment in place, recommending a 5,000,000 BUYOUT proposal on a
        second manager's vehicle yields strategy 0.1500 and manager 0.0500.

        Design: Difficulty/cross_entity_state_dependency/proposal_recommend_requires_vehicle_approved
        """
        ctx = setup_with_executed_commitment(
            cash=30_000_000, proposed_amount=10_000_000, staff_prefix="13b",
            program_name="P13B", strategy_cap_pct=0.95, manager_cap_pct=0.95,
            plan_overrides={"target_strategy_mix": [{"strategy": "BUYOUT", "weight": 1.0}]},
        )
        manager2, vehicle2 = create_approved_vehicle(ctx.analyst_headers, ctx.ic_headers)
        proposal2 = create_proposal(
            vehicle2["id"], ctx.program["id"], ctx.plan["id"], ctx.analyst_headers, 5_000_000
        )
        rec = validate_success(api_client.recommend_proposal(proposal2["id"], ctx.analyst_headers))
        assert rec["status"] == "RECOMMENDED"
        # (10,000,000 EXECUTED + 5,000,000) / 100,000,000 = 0.1500
        assert rec["concentration_strategy_pct"] == pytest.approx(0.1500, abs=0.00005)
        # different manager: 5,000,000 / 100,000,000 = 0.0500
        assert rec["concentration_manager_pct"] == pytest.approx(0.0500, abs=0.00005)


class TestConcentrationInputSet:
    def test_concentration_check_excludes_pending_and_cancelled(self):
        """PRD §3.4: "Both figures count commitments in `EXECUTED` status and
        commitments in `REDUCED` status at their reduced `sized_amount`;
        `PENDING_DOCS` and `CANCELLED` rows are excluded."

        Design: Corner/calculations/concentration_check_excludes_pending_and_cancelled
        """
        ctx = setup_open_program_with_plan(
            cash=30_000_000, staff_prefix="d1", program_name="PCX",
            plan_overrides={"target_strategy_mix": [{"strategy": "BUYOUT", "weight": 1.0}]},
        )
        ana_h, ic_h = ctx.analyst_headers, ctx.ic_headers
        manager1, vehicle1 = create_approved_vehicle(ana_h, ic_h)
        # IC_APPROVED (PENDING_DOCS commitment, 20,000,000) but NOT executed.
        create_ic_approved_proposal(
            vehicle1["id"], ctx.program["id"], ctx.plan["id"], ana_h, ic_h, 20_000_000
        )
        manager2, vehicle2 = create_approved_vehicle(ana_h, ic_h)
        proposal2 = create_proposal(
            vehicle2["id"], ctx.program["id"], ctx.plan["id"], ana_h, 5_000_000
        )
        rec = validate_success(api_client.recommend_proposal(proposal2["id"], ana_h))
        # PENDING_DOCS 20M excluded; only the proposed 5M counts.
        assert rec["concentration_strategy_pct"] == pytest.approx(0.0500, abs=0.00005)
        assert rec["concentration_manager_pct"] == pytest.approx(0.0500, abs=0.00005)


class TestIcApproveChecks:
    def test_error_pacing_capacity_exceeded(self):
        """PRD §3.4: "The proposal's `proposed_amount` must fit within the
        remaining pacing capacity for the vehicle's vintage year under the
        approved plan — that is, the year's target minus the amounts of
        already `IC_APPROVED` proposals for that year (else
        `ERR_PACING_CAPACITY_EXCEEDED`, HTTP 422)."

        Design: Corner/errors/error_pacing_capacity_exceeded
        """
        ctx = setup_open_program_with_plan(cash=30_000_000, staff_prefix="f6", program_name="PF6",
                                           strategy_cap_pct=0.95, manager_cap_pct=0.95)
        ana_h, ic_h = ctx.analyst_headers, ctx.ic_headers
        manager1, vehicle1 = create_approved_vehicle(ana_h, ic_h)
        # Plan: 100,000,000 / 4 years = 25,000,000 annual pool; BUYOUT 0.5 ->
        # 12,500,000 target for (2026, BUYOUT).
        create_ic_approved_proposal(
            vehicle1["id"], ctx.program["id"], ctx.plan["id"], ana_h, ic_h, 10_000_000
        )
        manager2, vehicle2 = create_approved_vehicle(ana_h, ic_h)
        proposal_b = create_recommended_proposal(
            vehicle2["id"], ctx.program["id"], ctx.plan["id"], ana_h, 3_000_000
        )
        resp = api_client.ic_approve_proposal(proposal_b["id"], ic_h)
        validate_error(resp, ApiErrorId.ERR_PACING_CAPACITY_EXCEEDED)
        after = validate_success(api_client.get_proposal(proposal_b["id"], ana_h))
        assert after["status"] == "RECOMMENDED"

    def test_sod_violation_safety_beats_strategy_cap_constraint(self):
        """PRD §3.4: "Finally, segregation of duties: the acting IC member's
        `StaffUser` row is resolved via `X-User-ID`, the recommending analyst's
        row via `recommended_by_analyst_id`, and if the two rows share an
        `email` — the model's representation of one person holding two
        appointments — the approval is rejected with `ERR_SOD_VIOLATION`
        (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/sod_violation_safety_beats_strategy_cap_constraint
        """
        ops = register_staff("Ops Ten", "OPS_ANALYST", "ops10@x.com")
        ana = register_staff("Ana Ten", "ANALYST", "shared@x.com")
        ic_a = register_staff("IC Ten A", "IC_MEMBER", "ic10a@x.com")
        ic_shared = register_staff("IC Ten Shared", "IC_MEMBER", "shared@x.com")
        ops_h, ana_h = make_ops_headers(ops["id"]), make_analyst_headers(ana["id"])
        ic_a_h, ic_shared_h = make_ic_headers(ic_a["id"]), make_ic_headers(ic_shared["id"])

        program = create_open_program(
            program_name="P10", strategy_cap_pct=0.10, manager_cap_pct=0.95,
            cash=20_000_000, ops_headers=ops_h,
        )
        plan = create_approved_plan(
            program["id"], ana_h, plan_label="FY26",
            target_strategy_mix=[{"strategy": "BUYOUT", "weight": 1.0}],
        )
        manager = create_manager(ana_h, legal_name="KappaCap", relationship_since_year=2010)
        vehicle = create_vehicle(manager["id"], ana_h, fund_name="Kappa I")
        run_vehicle_to_approved(manager["id"], vehicle["id"], ana_h, ic_a_h)

        prop1 = create_ic_approved_proposal(
            vehicle["id"], program["id"], plan["id"], ana_h, ic_a_h, 9_000_000
        )
        com1 = commitment_for_proposal(prop1["id"], ops_h)
        pv = program_version(program["id"], ops_h)
        validate_success(
            api_client.execute_commitment(
                program["id"], com1["id"],
                {"sized_amount": 9_000_000, "expected_program_version": pv},
                ops_h,
            )
        )
        prop2 = create_recommended_proposal(vehicle["id"], program["id"], plan["id"], ana_h, 2_000_000)
        # (9,000,000 + 2,000,000) / 100,000,000 = 0.11 > 0.10 strategy cap —
        # but the SoD violation (same email) must be the reported error.
        resp = api_client.ic_approve_proposal(prop2["id"], ic_shared_h)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        after = validate_success(api_client.get_proposal(prop2["id"], ana_h))
        assert after["status"] == "RECOMMENDED"
        lst = validate_success(api_client.list_proposal_commitments(prop2["id"], ops_h))
        rows = lst if isinstance(lst, list) else lst.get("items", [])
        assert rows == [], "no Commitment row created for the rejected approval"

    def test_sod_violation_detected_even_without_cap_pressure(self):
        """PRD §3.4: "Finally, segregation of duties: the acting IC member's
        `StaffUser` row is resolved via `X-User-ID`, the recommending analyst's
        row via `recommended_by_analyst_id`, and if the two rows share an
        `email` — the model's representation of one person holding two
        appointments — the approval is rejected with `ERR_SOD_VIOLATION`
        (HTTP 409)."

        Second test on the same instance: the SoD rule fires on its own (no
        concentration pressure in play).

        Design: Difficulty/priority_pair_validation_conflict/sod_violation_safety_beats_strategy_cap_constraint
        """
        ops = register_staff("Ops TenB", "OPS_ANALYST", "ops10b@x.com")
        ana = register_staff("Ana TenB", "ANALYST", "sharedb@x.com")
        ic_a = register_staff("IC TenB A", "IC_MEMBER", "ic10ba@x.com")
        ic_shared = register_staff("IC TenB Shared", "IC_MEMBER", "sharedb@x.com")
        ops_h, ana_h = make_ops_headers(ops["id"]), make_analyst_headers(ana["id"])
        ic_a_h, ic_shared_h = make_ic_headers(ic_a["id"]), make_ic_headers(ic_shared["id"])

        program = create_open_program(
            program_name="P10B", strategy_cap_pct=0.95, manager_cap_pct=0.95,
            cash=20_000_000, ops_headers=ops_h,
        )
        plan = create_approved_plan(
            program["id"], ana_h, plan_label="FY26",
            target_strategy_mix=[{"strategy": "BUYOUT", "weight": 1.0}],
        )
        manager = create_manager(ana_h, legal_name="KappaBCap")
        vehicle = create_vehicle(manager["id"], ana_h, fund_name="KappaB I")
        run_vehicle_to_approved(manager["id"], vehicle["id"], ana_h, ic_a_h)
        prop = create_recommended_proposal(vehicle["id"], program["id"], plan["id"], ana_h, 1_000_000)
        resp = api_client.ic_approve_proposal(prop["id"], ic_shared_h)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        # a genuinely different IC member can approve
        ok = validate_success(api_client.ic_approve_proposal(prop["id"], ic_a_h))
        assert ok["status"] == "IC_APPROVED"


class TestErrorPrecedencePosture:
    def test_posture_gated_state_beats_buffer_breach_safety(self):
        """PRD §2.4: "While `RESTRICTED`, the program continues to accept the
        cash-restoring writes — paying a capital call, receiving a
        distribution, posting a contribution ledger entry, settling a
        secondary bid — but four forward-committing writes are blocked with
        `ERR_POSTURE_GATED`: recommending a proposal, IC-approving a proposal,
        executing a commitment, and accepting a secondary bid."
        PRD §3.4: "The execution is validated in order: the program must be
        `OPEN` with posture `NORMAL` (`ERR_POSTURE_GATED`); the final size
        must lie within the band of ninety percent to one hundred ten percent
        of the original `proposed_amount` inclusive (else
        `ERR_SIZE_OUT_OF_BAND`, HTTP 422); the vehicle's `vintage_year`,
        measured against the earliest and the latest `vintage_year` among
        existing `EXECUTED` commitments, must keep both spans within
        `max_vintage_band_years` (else `ERR_VINTAGE_BAND_BREACH`, HTTP 422);
        and program-level unfunded after execution must leave projected
        liquidity coverage at or above the buffer (else `ERR_BUFFER_BREACH`)."

        Design: Difficulty/priority_pair_validation_conflict/posture_gated_state_beats_buffer_breach_safety
        """
        ana_h, ic_h, ops_h, _ = make_staff_trio("nine")
        program = create_open_program(
            program_name="P9", strategy_cap_pct=0.95, manager_cap_pct=0.95,
            cash=5_000_000, ops_headers=ops_h,
        )
        plan = create_approved_plan(program["id"], ana_h, plan_label="FY26")
        manager, vehicle = create_approved_vehicle(ana_h, ic_h)
        proposal = create_ic_approved_proposal(
            vehicle["id"], program["id"], plan["id"], ana_h, ic_h, 10_000_000
        )
        commitment = commitment_for_proposal(proposal["id"], ops_h)
        # Drain cash to 1,050,000 -> RESTRICTED (1,050,000 < 1.10 * 1,000,000).
        contribute(program["id"], -3_950_000, ops_h, note="seed a RESTRICTED posture",
                   entry_kind="MANUAL_ADJUSTMENT")
        prog = get_program(program["id"], ops_h)
        assert prog["posture"] == "RESTRICTED"
        resp = api_client.execute_commitment(
            program["id"], commitment["id"],
            {"sized_amount": 10_000_000, "expected_program_version": prog["version"]},
            ops_h,
        )
        # The posture gate must fire, not the buffer safety check.
        validate_error(resp, ApiErrorId.ERR_POSTURE_GATED)
        after = validate_success(
            api_client.get_commitment_flat(commitment["id"], ops_h)
        )
        assert after["status"] == "PENDING_DOCS"

    def test_posture_restricted_blocks_recommend_even_with_clean_books(self):
        """PRD §2.4: "While `RESTRICTED`, the program continues to accept the
        cash-restoring writes — paying a capital call, receiving a
        distribution, posting a contribution ledger entry, settling a
        secondary bid — but four forward-committing writes are blocked with
        `ERR_POSTURE_GATED`: recommending a proposal, IC-approving a proposal,
        executing a commitment, and accepting a secondary bid."

        Second test on the same instance: recommend (not execute) is one of
        the four blocked writes.

        Design: Difficulty/priority_pair_validation_conflict/posture_gated_state_beats_buffer_breach_safety
        """
        ana_h, ic_h, ops_h, _ = make_staff_trio("nineb")
        program = create_open_program(
            program_name="P9B", strategy_cap_pct=0.95, manager_cap_pct=0.95,
            cash=5_000_000, ops_headers=ops_h,
        )
        plan = create_approved_plan(program["id"], ana_h, plan_label="FY26")
        manager, vehicle = create_approved_vehicle(ana_h, ic_h)
        proposal = create_proposal(vehicle["id"], program["id"], plan["id"], ana_h, 1_000_000)
        contribute(program["id"], -3_950_000, ops_h, note="drain", entry_kind="MANUAL_ADJUSTMENT")
        assert get_program(program["id"], ops_h)["posture"] == "RESTRICTED"
        resp = api_client.recommend_proposal(proposal["id"], ana_h)
        validate_error(resp, ApiErrorId.ERR_POSTURE_GATED)
