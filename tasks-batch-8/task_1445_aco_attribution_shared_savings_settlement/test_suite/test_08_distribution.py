"""Distribution waterfall: allocation math, run gates, line lifecycle, bubble-up."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_line,
    assert_distribution_pool_conservation,
    build_period_scenario,
    finalize_settlement,
    list_distribution_lines,
    make_actuary_headers,
    make_approver_headers,
    propose_settlement,
    reopen_settlement,
    run_distribution,
    setup_lite_distributed,
    setup_lite_final_settlement,
    setup_lite_proposed_settlement,
    validate_error,
    validate_paginated,
    validate_success,
    get_period,
)

ACTUARY = make_actuary_headers()
APPROVER = make_approver_headers()

THREE_PARTICIPANTS = (("100000001", "PA", 5000), ("100000002", "PB", 3000),
                      ("100000003", "PC", 2000))


def _canonical_final_for_distribution(tax_id):
    """Canonical two-beneficiary period: FINAL settlement with pool 23054 and
    participants weighted 5000/3000/2000 (PA created first)."""
    return build_period_scenario(
        tax_id=tax_id,
        participants=THREE_PARTICIPANTS,
        beneficiaries=(
            {"medicare_id": "MBI-DW-R", "birth_year": 1960,
             "dual_eligible": True, "disabled": True},
            {"medicare_id": "MBI-DW-P", "birth_year": 1990},
        ),
        claims=(
            {"beneficiary": 0, "participant": 0, "service_date": "2026-02-01",
             "amount": 20000, "claim_type": "PART_B"},
            {"beneficiary": 1, "participant": 0, "service_date": "2026-02-05",
             "amount": 20000, "claim_type": "PART_B"},
            {"beneficiary": 0, "participant": 0, "service_date": "2026-03-01",
             "amount": 1500000, "claim_type": "PART_A"},
            {"beneficiary": 1, "participant": 0, "service_date": "2026-03-02",
             "amount": 1341670, "claim_type": "PART_A"},
        ),
        settlement=True, finalize=True,
    )


class TestWaterfallAllocation:
    def test_distribution_allocates_floor_then_remainder_penny(self, api, actuary_headers):
        """PRD §3.7: "Each participant's line starts as the pool multiplied by
        that participant's weight and divided by the sum of all weights, floored
        to whole cents. The remainder — the pool minus the sum of floored lines,
        always less than the participant count — is then handed out one cent per
        line in allocation order: descending `share_weight_bp`, ties broken by
        earliest participant `created_at`, at most one pass."

        Design: Difficulty/combinatorial_formula/distribution_floor_then_remainder_vs_naive_round
        """
        ctx = _canonical_final_for_distribution("ACO-DW")
        settlement = ctx["settlement"]
        assert settlement["distributable_pool_cents"] == 23054
        run = run_distribution(settlement["id"])
        assert run["created_count"] == 3
        assert run["allocated_total_cents"] == 23054

        res = api.list_distribution_lines(actuary_headers,
                                          params={"settlement_id": settlement["id"]})
        lines, _meta = validate_paginated(res)
        # list order is amount_cents descending (PRD §2.3)
        pa, pb, pc = (p["id"] for p in ctx["participants"])
        assert lines[0]["amount_cents"] == 11528 and lines[0]["participant_id"] == pa
        assert lines[1]["amount_cents"] == 6916 and lines[1]["participant_id"] == pb
        assert lines[2]["amount_cents"] == 4610 and lines[2]["participant_id"] == pc

    def test_distribution_lines_sum_to_pool_exactly(self, api, actuary_headers):
        """PRD §3.7: "the invariant is that the created lines sum to the pool
        exactly."

        Design: Difficulty/combinatorial_formula/distribution_floor_then_remainder_vs_naive_round
        """
        ctx = _canonical_final_for_distribution("ACO-DW2")
        settlement = ctx["settlement"]
        run_distribution(settlement["id"])
        res = api.list_distribution_lines(actuary_headers,
                                          params={"settlement_id": settlement["id"]})
        lines, _meta = validate_paginated(res)
        assert_distribution_pool_conservation(lines, 23054)
        assert all(line["status"] == "PENDING" for line in lines)


class TestDistributionRunGates:
    def test_distribution_run_on_proposed_settlement_rejected(self, api, actuary_headers):
        """PRD §3.7: "A `SettlementActuary` triggers a distribution run against a
        `FINAL` settlement (any other status: `ERR_SETTLEMENT_NOT_FINAL`)".

        Design: Difficulty/cross_entity_state_dependency/distribution_run_blocked_until_settlement_final
        """
        ctx = setup_lite_proposed_settlement(tax_id="ACO-XD2")
        assert ctx["settlement"]["status"] == "PROPOSED"
        res = api.create_distribution_run(ctx["settlement"]["id"], actuary_headers)
        validate_error(res, ApiErrorId.ERR_SETTLEMENT_NOT_FINAL, expected_status=409)

    def test_distribution_run_succeeds_after_finalize(self, api, actuary_headers):
        """PRD §3.7: "the run records the running user's id on the settlement as
        `last_distribution_run_by_user_id`, returns the `created_count`, the
        `allocated_total_cents`, and the `settlement_id`".

        Design: Difficulty/cross_entity_state_dependency/distribution_run_blocked_until_settlement_final
        """
        ctx = setup_lite_final_settlement(tax_id="ACO-XD2B")
        res = api.create_distribution_run(ctx["settlement"]["id"], actuary_headers)
        run = validate_success(res, 201)
        assert run["created_count"] == 1
        assert run["allocated_total_cents"] == 168097
        assert run["settlement_id"] == ctx["settlement"]["id"]

    def test_second_distribution_run_rejected(self, api, actuary_headers):
        """PRD §3.7: "no non-`VOIDED` distribution lines already exist for the
        settlement (else `ERR_DISTRIBUTION_RUN_EXISTS`) — one live run at a
        time."

        Design: Corner/validations/second_distribution_run_rejected
        """
        ctx = setup_lite_distributed(tax_id="ACO-V9")
        res = api.create_distribution_run(ctx["settlement"]["id"], actuary_headers)
        validate_error(res, ApiErrorId.ERR_DISTRIBUTION_RUN_EXISTS, expected_status=409)


class TestLineLifecycle:
    def test_distribution_double_approve_rejected(self, api, approver_headers):
        """PRD §3.7: "A `DistributionApprover` approves a `PENDING` line — any
        other status, `ERR_DISTRIBUTION_INVALID_STATE`".

        Design: Corner/state_machines/distribution_double_approve_rejected
        """
        ctx = setup_lite_distributed(tax_id="ACO-S6")
        line = list_distribution_lines(ctx["settlement"]["id"])[0]
        approve_line(line["id"])
        res = api.approve_distribution_line(line["id"], approver_headers)
        validate_error(res, ApiErrorId.ERR_DISTRIBUTION_INVALID_STATE, expected_status=409)

    def test_pay_last_line_bubbles_settlement_and_period(self, api, actuary_headers):
        """PRD §3.7: "Payment bubbles upward: when no `PENDING` or `APPROVED`
        lines remain on the settlement and at least one `PAID` line exists, the
        settlement moves from `FINAL` to `SETTLED`, and that transition in turn
        bubbles the agreement period from `ASSIGNMENT_LOCKED` to `SETTLED`".

        Design: Corner/state_machines/pay_last_line_bubbles_settlement_and_period
        """
        ctx = setup_lite_distributed(tax_id="ACO-S9")
        settlement = ctx["settlement"]
        assert settlement["distributable_pool_cents"] == 168097
        line = list_distribution_lines(settlement["id"])[0]
        assert line["amount_cents"] == 168097
        approve_line(line["id"])
        paid = validate_success(api.pay_distribution_line(line["id"], APPROVER), 200)
        assert paid["status"] == "PAID"
        settlement_after = validate_success(
            api.get_settlement(settlement["id"], actuary_headers), 200,
        )
        assert settlement_after["status"] == "SETTLED"
        period_after = get_period(ctx["period"]["id"])
        assert period_after["status"] == "SETTLED"


class TestDistributionSegregation:
    def test_distribution_approver_must_not_be_runner(self, api):
        """PRD §3.7: "the approver must not be the user recorded as
        `last_distribution_run_by_user_id` on the settlement, or the approval is
        rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/distribution_approver_must_not_be_runner
        """
        ctx = setup_lite_distributed(tax_id="ACO-R5")
        line = list_distribution_lines(ctx["settlement"]["id"])[0]
        res = api.approve_distribution_line(line["id"], make_approver_headers("sa-1"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
        ok = validate_success(
            api.approve_distribution_line(line["id"], make_approver_headers("da-1")), 200,
        )
        assert ok["status"] == "APPROVED"


class TestReopenRegenerateConservation:
    def test_regenerated_distribution_matches_original_allocation(self, api,
                                                                  actuary_headers):
        """PRD §3.7: "Reopening moves the settlement to `REOPENED`, recomputes
        every computed money field against current inputs" and the waterfall
        "invariant is that the created lines sum to the pool exactly."

        Design: Difficulty/compensating_invariant/reopen_then_regenerate_conserves_pool_allocation
        """
        ctx = _canonical_final_for_distribution("ACO-RG")
        settlement = ctx["settlement"]
        assert settlement["distributable_pool_cents"] == 23054
        run_distribution(settlement["id"])
        reopen_settlement(settlement["id"], reason="recount")
        finalize_settlement(settlement["id"])
        run2 = run_distribution(settlement["id"])
        assert run2["created_count"] == 3
        assert run2["allocated_total_cents"] == 23054

        res = api.list_distribution_lines(
            actuary_headers,
            params={"settlement_id": settlement["id"], "status": "PENDING"},
        )
        lines, _meta = validate_paginated(res)
        assert [line["amount_cents"] for line in lines] == [11528, 6916, 4610]

    def test_live_lines_sum_to_pool_across_reopen_cycle(self, api, actuary_headers):
        """PRD §3.7: "every distribution line in `PENDING` or `APPROVED` is
        voided" on reopen, and the waterfall "invariant is that the created
        lines sum to the pool exactly."

        Design: Difficulty/compensating_invariant/reopen_then_regenerate_conserves_pool_allocation
        """
        ctx = _canonical_final_for_distribution("ACO-RG2")
        settlement = ctx["settlement"]
        run_distribution(settlement["id"])
        reopen_settlement(settlement["id"], reason="recount")
        finalize_settlement(settlement["id"])
        run_distribution(settlement["id"])
        res = api.list_distribution_lines(
            actuary_headers,
            params={"settlement_id": settlement["id"], "status": "PENDING"},
        )
        lines, _meta = validate_paginated(res)
        assert_distribution_pool_conservation(lines, 23054)
