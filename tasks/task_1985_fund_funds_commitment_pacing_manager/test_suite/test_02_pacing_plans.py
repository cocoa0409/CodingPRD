"""Pacing plan approval, supersede, waterfall targets, and OCC on supersede."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    commitment_for_proposal,
    contribute,
    create_approved_plan,
    create_ic_approved_proposal,
    create_open_program,
    create_plan,
    create_proposal,
    create_approved_vehicle,
    make_cio_headers,
    make_staff_trio,
    program_version,
    validate_error,
    validate_success,
)


def _rows_by_year_strategy(plan):
    return {(r["vintage_year"], r["strategy"]): r["amount"] for r in plan["target_commit_by_year"]}


class TestPacingTargetsRounding:
    def test_pacing_targets_remainder_swept_into_first_row(self):
        """PRD §3.2: "Each row's amount is rounded to 2 decimal places round
        half up, and the remainder cents from per-row rounding are swept into
        the first row — the earliest vintage year and the first strategy in the
        input order of the mix — so that the row amounts sum exactly to the
        rounded remaining budget."

        Design: Difficulty/combinatorial_formula/pacing_targets_row_rounding_remainder_sweep
        """
        ana_h, ic_h, ops_h, _ = make_staff_trio("four")
        program = create_open_program(
            program_name="P4",
            total_nav_budget=99_999_999.97,
            strategy_cap_pct=0.95,
            manager_cap_pct=0.95,
            cash=20_000_000,
            ops_headers=ops_h,
        )
        seed = create_approved_plan(program["id"], ana_h, plan_label="SEED")
        manager, vehicle = create_approved_vehicle(ana_h, ic_h)
        proposal = create_ic_approved_proposal(
            vehicle["id"], program["id"], seed["id"], ana_h, ic_h, 3_333_333.32
        )
        commitment = commitment_for_proposal(proposal["id"], ops_h)
        pv = program_version(program["id"], ops_h)
        validate_success(
            api_client.execute_commitment(
                program["id"],
                commitment["id"],
                {"sized_amount": 3_333_333.32, "expected_program_version": pv},
                ops_h,
            )
        )
        main = create_plan(program["id"], ana_h, plan_label="MAIN")
        pv2 = program_version(program["id"])
        validate_success(
            api_client.supersede_pacing_plan(
                program["id"],
                seed["id"],
                {"replacement_plan_id": main["id"], "expected_program_version": pv2},
                make_cio_headers(),
            )
        )
        resp = api_client.get_pacing_plan_flat(main["id"], ana_h)
        plan = validate_success(resp)
        assert plan["status"] == "APPROVED"

        # remaining_budget = 99,999,999.97 - 3,333,333.32 = 96,666,666.65
        # annual_pool (unrounded) = 24,166,666.6625
        rows = _rows_by_year_strategy(plan)
        assert rows[(2026, "BUYOUT")] == pytest.approx(12_083_333.34, abs=0.005), (
            "first row receives the +0.01 remainder sweep"
        )
        for year in (2027, 2028, 2029):
            assert rows[(year, "BUYOUT")] == pytest.approx(12_083_333.33, abs=0.005)
        for year in (2026, 2027, 2028, 2029):
            assert rows[(year, "VENTURE")] == pytest.approx(7_250_000.00, abs=0.005)
            assert rows[(year, "CREDIT")] == pytest.approx(4_833_333.33, abs=0.005)
        total = sum(rows.values())
        assert total == pytest.approx(96_666_666.65, abs=0.005)
        assert plan["projected_total_commit"] == pytest.approx(96_666_666.65, abs=0.005)

    def test_pacing_targets_row_sum_equals_rounded_remaining_budget(self):
        """PRD §3.2: "The pacing waterfall allocates the remaining budget —
        `total_nav_budget` minus `committed_total` counting only `EXECUTED`
        commitments — evenly across the plan's horizon: the remaining budget
        divided by `horizon_years` gives an annual pool, and each vintage year
        from `start_vintage_year` through `start_vintage_year + horizon_years -
        1` receives one row per mix entry, carrying that year's pool multiplied
        by the entry's weight."

        Second test on the same instance: with a clean budget the row grid is
        4 years x 3 strategies and the per-year pool is budget / 4.

        Design: Difficulty/combinatorial_formula/pacing_targets_row_rounding_remainder_sweep
        """
        ana_h, _, ops_h, _ = make_staff_trio("fourb")
        program = create_open_program(
            program_name="P4-clean",
            total_nav_budget=100_000_000,
            cash=20_000_000,
            ops_headers=ops_h,
        )
        resp = api_client.create_pacing_plan(
            program["id"],
            {
                "plan_label": "CLEAN",
                "horizon_years": 4,
                "start_vintage_year": 2026,
                "target_strategy_mix": [
                    {"strategy": "BUYOUT", "weight": 0.5},
                    {"strategy": "VENTURE", "weight": 0.3},
                    {"strategy": "CREDIT", "weight": 0.2},
                ],
            },
            ana_h,
        )
        plan = validate_success(resp, expected_status=201)
        approved = validate_success(
            api_client.approve_pacing_plan(program["id"], plan["id"], make_cio_headers())
        )
        rows = _rows_by_year_strategy(approved)
        assert set(r["vintage_year"] for r in approved["target_commit_by_year"]) == {
            2026, 2027, 2028, 2029,
        }
        # annual pool = 25,000,000; BUYOUT 12.5M, VENTURE 7.5M, CREDIT 5.0M
        for year in (2026, 2027, 2028, 2029):
            assert rows[(year, "BUYOUT")] == pytest.approx(12_500_000.00, abs=0.005)
            assert rows[(year, "VENTURE")] == pytest.approx(7_500_000.00, abs=0.005)
            assert rows[(year, "CREDIT")] == pytest.approx(5_000_000.00, abs=0.005)
        assert approved["projected_total_commit"] == pytest.approx(100_000_000.00, abs=0.005)


class TestPacingPlanGatingAndSupersede:
    def test_pacing_targets_input_set_excludes_pending_commitments(self):
        """PRD §3.2: "The pacing waterfall allocates the remaining budget —
        `total_nav_budget` minus `committed_total` counting only `EXECUTED`
        commitments — evenly across the plan's horizon"
        PRD §2.6: "`committed_total` is the sum of `sized_amount` over
        `Commitment` rows in status `EXECUTED`"

        Design: Corner/calculations/pacing_targets_input_set_excludes_pending_commitments
        """
        ana_h, ic_h, ops_h, _ = make_staff_trio("d2")
        program = create_open_program(
            program_name="PIS",
            total_nav_budget=80_000_000,
            strategy_cap_pct=0.95,
            manager_cap_pct=0.95,
            cash=30_000_000,
            ops_headers=ops_h,
        )
        manager, vehicle = create_approved_vehicle(ana_h, ic_h)

        # Proposal referencing a non-existent pacing plan -> ERR_REF_NOT_FOUND.
        resp_pre = api_client.create_proposal(
            vehicle["id"],
            {
                "program_id": program["id"],
                "pacing_plan_id": "placeholder-until-plan-exists",
                "proposed_amount": 10_000_000,
            },
            ana_h,
        )
        validate_error(resp_pre, ApiErrorId.ERR_REF_NOT_FOUND)

        plan = create_plan(
            program["id"], ana_h, plan_label="MAIN",
            target_strategy_mix=[{"strategy": "BUYOUT", "weight": 1.0}],
        )
        proposal = create_proposal(vehicle["id"], program["id"], plan["id"], ana_h, 10_000_000)
        # Recommend while plan still DRAFT -> ERR_PLAN_NOT_APPROVED.
        resp_plan = api_client.recommend_proposal(proposal["id"], ana_h)
        validate_error(resp_plan, ApiErrorId.ERR_PLAN_NOT_APPROVED)

        validate_success(api_client.approve_pacing_plan(program["id"], plan["id"], make_cio_headers()))
        validate_success(api_client.recommend_proposal(proposal["id"], ana_h))
        validate_success(api_client.ic_approve_proposal(proposal["id"], ic_h))
        # The spawned commitment is PENDING_DOCS (never executed): it must NOT
        # reduce the remaining budget seen by the replacement plan.

        plan2 = create_plan(
            program["id"], ana_h, plan_label="SECOND",
            target_strategy_mix=[{"strategy": "BUYOUT", "weight": 1.0}],
        )
        pv = program_version(program["id"])
        validate_success(
            api_client.supersede_pacing_plan(
                program["id"], plan["id"],
                {"replacement_plan_id": plan2["id"], "expected_program_version": pv},
                make_cio_headers(),
            )
        )
        plan2_after = validate_success(api_client.get_pacing_plan_flat(plan2["id"], ana_h))
        assert plan2_after["projected_total_commit"] == pytest.approx(80_000_000.00, abs=0.005), (
            "PENDING_DOCS commitment excluded from committed_total; full budget remains"
        )

    def test_error_active_plan_exists(self):
        """PRD §3.2: "if another plan for the same program is already
        `APPROVED`, the approval is rejected with `ERR_ACTIVE_PLAN_EXISTS`
        (HTTP 409)."

        Design: Corner/errors/error_active_plan_exists
        """
        ana_h, _, ops_h, _ = make_staff_trio("f1")
        program = create_open_program(
            program_name="PF1", total_nav_budget=50_000_000, cash=5_000_000, ops_headers=ops_h
        )
        create_approved_plan(
            program["id"], ana_h, plan_label="A", horizon_years=2,
            target_strategy_mix=[{"strategy": "BUYOUT", "weight": 1.0}],
        )
        plan_b = create_plan(
            program["id"], ana_h, plan_label="B", horizon_years=2, start_vintage_year=2027,
            target_strategy_mix=[{"strategy": "VENTURE", "weight": 1.0}],
        )
        resp = api_client.approve_pacing_plan(program["id"], plan_b["id"], make_cio_headers())
        validate_error(resp, ApiErrorId.ERR_ACTIVE_PLAN_EXISTS)
        plan_b_after = validate_success(api_client.get_pacing_plan_flat(plan_b["id"], ana_h))
        assert plan_b_after["status"] == "DRAFT"

    def test_error_plan_not_draft_on_supersede(self):
        """PRD §3.2: "The `CIO` names a `replacement_plan_id` that must
        reference a plan of the same program still in `DRAFT` — otherwise
        `ERR_PLAN_NOT_DRAFT` (HTTP 422)"

        Design: Corner/errors/error_plan_not_draft_on_supersede
        """
        ana_h, _, ops_h, _ = make_staff_trio("f2")
        program = create_open_program(
            program_name="PF2", total_nav_budget=50_000_000, cash=5_000_000, ops_headers=ops_h
        )
        plan_s = create_approved_plan(
            program["id"], ana_h, plan_label="SEED", horizon_years=2,
            target_strategy_mix=[{"strategy": "BUYOUT", "weight": 1.0}],
        )
        plan_b = create_plan(
            program["id"], ana_h, plan_label="B", horizon_years=2, start_vintage_year=2027,
            target_strategy_mix=[{"strategy": "VENTURE", "weight": 1.0}],
        )
        pv = program_version(program["id"])
        validate_success(
            api_client.supersede_pacing_plan(
                program["id"], plan_s["id"],
                {"replacement_plan_id": plan_b["id"], "expected_program_version": pv},
                make_cio_headers(),
            )
        )
        plan_c = create_plan(
            program["id"], ana_h, plan_label="C", horizon_years=2, start_vintage_year=2028,
            target_strategy_mix=[{"strategy": "CREDIT", "weight": 1.0}],
        )
        pv2 = program_version(program["id"])
        # plan C is DRAFT (not APPROVED), so supersede FROM C is an invalid
        # state; the recipe targets the replacement not being DRAFT instead:
        # supersede the APPROVED plan B naming plan B itself is nonsense; the
        # canonical case: supersede B with replacement = B (APPROVED, not DRAFT).
        resp = api_client.supersede_pacing_plan(
            program["id"], plan_b["id"],
            {"replacement_plan_id": plan_b["id"], "expected_program_version": pv2},
            make_cio_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_DRAFT)
        plan_c_after = validate_success(api_client.get_pacing_plan_flat(plan_c["id"], ana_h))
        assert plan_c_after["status"] == "DRAFT"

    def test_occ_stale_version_on_plan_supersede(self):
        """PRD §2.5: "Each such request must carry a non-optional
        `expected_program_version` field carrying the client's last observed
        `version` of the parent `FoFProgram`. If the supplied value does not
        match the program's current `version`, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the
        program before retrying."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_plan_supersede
        """
        ana_h, _, ops_h, _ = make_staff_trio("x2")
        program = create_open_program(
            program_name="PX2", total_nav_budget=50_000_000, cash=5_000_000, ops_headers=ops_h
        )
        plan_a = create_approved_plan(
            program["id"], ana_h, plan_label="A", horizon_years=2,
            target_strategy_mix=[{"strategy": "BUYOUT", "weight": 1.0}],
        )
        plan_b = create_plan(
            program["id"], ana_h, plan_label="B", horizon_years=2, start_vintage_year=2027,
            target_strategy_mix=[{"strategy": "VENTURE", "weight": 1.0}],
        )
        pv_stale = program_version(program["id"])
        contribute(program["id"], 1_000_000, ops_h)  # bumps version
        resp = api_client.supersede_pacing_plan(
            program["id"], plan_a["id"],
            {"replacement_plan_id": plan_b["id"], "expected_program_version": pv_stale},
            make_cio_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        pv_fresh = program_version(program["id"])
        validate_success(
            api_client.supersede_pacing_plan(
                program["id"], plan_a["id"],
                {"replacement_plan_id": plan_b["id"], "expected_program_version": pv_fresh},
                make_cio_headers(),
            )
        )
        plan_a_after = validate_success(api_client.get_pacing_plan_flat(plan_a["id"], ana_h))
        plan_b_after = validate_success(api_client.get_pacing_plan_flat(plan_b["id"], ana_h))
        assert plan_a_after["status"] == "SUPERSEDED"
        assert plan_b_after["status"] == "APPROVED"
