"""Program plan-year lifecycle: activation windows, finalize, close, settle (PRD §3.2)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    compute_awards,
    create_active_program,
    create_employer,
    create_program,
    get_enrollment_award,
    post_activity,
    setup_active_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
)

BA = TEST_USERS["benefits_admin_headers"]


class TestProgramWindowOverlap:
    """Difficulty instance: half-open interval exclusion on the employer's
    program calendar; pure adjacency is allowed."""

    def test_overlapping_program_activation_rejected(self, api):
        """PRD §3.2: "if another program of the same employer in `ACTIVE` or `CLOSED`
        status has a half-open window overlapping this one, activation fails with
        `ERR_PROGRAM_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/program_window_halfopen_overlap
        """
        employer = create_employer()
        program_1 = create_active_program(employer["id"])
        program_2 = create_program(
            employer["id"], name="PY2026H2",
            plan_year_start="2026-06-01", plan_year_end="2027-06-01",
        )

        res = api.activate_program(program_2["id"], BA)
        validate_error(res, ApiErrorId.ERR_PROGRAM_WINDOW_OVERLAP, expected_status=409)

        after = validate_success(api.get_program(program_2["id"], BA), 200)
        assert after["status"] == "DRAFT", "rejected activation must leave the program DRAFT"

    def test_adjacent_program_activation_allowed(self, api):
        """PRD §3.2: "Because both windows are half-open, pure adjacency — one
        program's `plan_year_end` landing exactly on the other's `plan_year_start` —
        does not count as overlap and is allowed."

        Design: Difficulty/resource_temporal_overlap/program_window_halfopen_overlap
        """
        employer = create_employer()
        create_active_program(employer["id"])  # [2026-01-01, 2027-01-01)
        program_2 = create_program(
            employer["id"], name="PY2027",
            plan_year_start="2027-01-01", plan_year_end="2028-01-01",
        )

        activated = validate_success(api.activate_program(program_2["id"], BA), 200)
        assert activated["status"] == "ACTIVE"


class TestFinalizePoints:
    def test_finalize_moves_provisional_to_settled(self, api):
        """PRD §3.2: "While a program is `ACTIVE`, a `BenefitsAdmin` may also finalize
        its points: every `PROVISIONAL` ledger entry of every enrollment in the
        program transitions to `POSTED`, both balances of each affected enrollment
        are recomputed, and the response reports how many entries were moved via
        `finalized_count`."

        Design: Corner/cross_cutting_layers/finalize_moves_provisional_to_settled
        """
        ctx = setup_active_enrollment()
        enr = ctx["enrollment"]
        post_activity(enr["id"], ctx["employee"]["id"], "evt-1", quantity=100000)

        before = validate_success(api.get_enrollment(enr["id"], BA), 200)
        assert before["points_balance_provisional"] == 100
        assert before["points_balance_settled"] == 0

        result = validate_success(api.finalize_program_points(ctx["program"]["id"], BA), 200)
        assert result["finalized_count"] == 1

        entries, _meta = validate_paginated(
            api.list_enrollment_points_ledger_entries(enr["id"], BA)
        )
        assert len(entries) == 1
        assert entries[0]["status"] == "POSTED"

        after = validate_success(api.get_enrollment(enr["id"], BA), 200)
        assert after["points_balance_provisional"] == 100
        assert after["points_balance_settled"] == 100, (
            "settled balance reconciles from 0 to 100 after finalize"
        )


class TestProgramCloseCascade:
    def test_program_close_expires_provisional_entries(self, api):
        """PRD §3.2: "The ledger expiry sweep runs second: every `PROVISIONAL`
        PointsLedgerEntry of every enrollment in the program — including the
        completion bonuses created moments earlier in the same close — transitions
        to `EXPIRED`, and both enrollment balances are recomputed from what remains."
        PRD §2.8: "`EXPIRED` entries contribute to neither balance."

        Design: Corner/consistency_model/program_close_expires_provisional_entries
        """
        ctx = setup_active_enrollment()
        enr = ctx["enrollment"]
        post_activity(enr["id"], ctx["employee"]["id"], "evt-1", quantity=100000)

        closed = validate_success(api.close_program(ctx["program"]["id"], BA), 200)
        assert closed["status"] == "CLOSED"

        entries, _meta = validate_paginated(
            api.list_enrollment_points_ledger_entries(enr["id"], BA)
        )
        assert len(entries) == 1
        assert entries[0]["status"] == "EXPIRED", (
            "the un-finalized EARNED entry must expire on program close"
        )

        after = validate_success(api.get_enrollment(enr["id"], BA), 200)
        assert after["points_balance_provisional"] == 0
        assert after["points_balance_settled"] == 0


class TestSettlePreconditions:
    def test_program_settle_with_open_awards_rejected(self, api):
        """PRD §3.2: "The terminal transition, `CLOSED → SETTLED`, is permitted only
        once every IncentiveAward of the program has reached `APPLIED`; any open
        award blocks settlement with `ERR_PROGRAM_HAS_OPEN_AWARDS`."

        Design: Corner/state_machines/program_settle_with_open_awards_rejected
        """
        ctx = setup_active_enrollment()
        program_id = ctx["program"]["id"]
        validate_success(api.close_program(program_id, BA), 200)
        compute_awards(program_id)
        award = get_enrollment_award(ctx["enrollment"]["id"])
        confirmed = validate_success(api.confirm_incentive_award(award["id"], BA), 200)
        assert confirmed["status"] == "CONFIRMED"

        res = api.settle_program(program_id, BA)
        validate_error(res, ApiErrorId.ERR_PROGRAM_HAS_OPEN_AWARDS, expected_status=409)

        after = validate_success(api.get_program(program_id, BA), 200)
        assert after["status"] == "CLOSED"
