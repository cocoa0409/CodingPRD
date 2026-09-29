"""
Programming then withdrawing the same candidate: money is conserved, the row is not.

PRD §3.8: "Withdrawing a programmed candidate is the compensating action of
programming".
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import fixtures as fx

FIELD_DAY = "2026-09-02T12:00:00Z"

RESERVE = 500000000
AVAILABLE = 9500000000
COST = 26588000


def _cycle_holding_one_identified_candidate(client, roster, bridge):
    """
    A cycle of ten billion cents at the default five per cent reserve, holding the
    single candidate the acceptance cascade files for Cedar Creek.
    """
    cycle = fx.create_cycle(client, fiscal_year=2028, reserve_pct=0.05)
    fx.accepted_report(client, bridge["id"], roster, qa_clock=FIELD_DAY)
    candidates = fx.candidates_in_cycle(client, cycle["id"])
    assert len(candidates) == 1, "the acceptance cascade files exactly one candidate"
    return {"cycle": cycle, "candidate": candidates[0]}


def test_the_buckets_start_with_the_reserve_off_the_top(client, roster, bridge):
    """
    Before any commitment: the reserve is taken from the authorised budget once, the
    remainder equals the available money, and the identified candidate sits entirely
    in the unprogrammed bucket.

    PRD §3.8: "`reserve_cents` is the reserve fraction multiplied by the authorised
    budget, rounded half up, and it comes off the top; it is computed **once, at
    creation, and never recomputed**".
    PRD §3.8: "`remaining_cents` is `available_cents` minus `committed_cents`, and
    therefore starts equal to `available_cents`. Alongside them,
    `unprogrammed_cost_cents` is the sum of `estimated_cost_cents` over the cycle's
    `IDENTIFIED` candidates."

    Design: Difficulty/compensating_invariant/program_then_withdraw_restores_budget_identity
    """
    setup = _cycle_holding_one_identified_candidate(client, roster, bridge)

    summary = fx.read_allocation(client, setup["cycle"]["id"])

    assert summary["authorized_budget_cents"] == 10000000000
    assert summary["reserve_cents"] == RESERVE
    assert summary["available_cents"] == AVAILABLE
    assert summary["committed_cents"] == 0
    assert summary["remaining_cents"] == AVAILABLE
    assert summary["identified_count"] == 1
    assert summary["programmed_count"] == 0
    assert summary["deferred_count"] == 0
    assert summary["unprogrammed_cost_cents"] == COST
    assert summary["identity_holds"] is True
    a.assert_allocation_summary_matches_cycle(
        summary, fx.read_cycle(client, setup["cycle"]["id"])
    )


def test_programming_moves_the_cost_from_unprogrammed_to_committed(
    client, roster, bridge
):
    """
    Programming commits the cost: it lands in `committed_cents`, leaves
    `unprogrammed_cost_cents`, and the reserve is not touched at all.

    PRD §3.8: "A successful programming moves the candidate `IDENTIFIED →
    PROGRAMMED` and stamps `programmed_at` from the logical clock. It adds the cost
    to `committed_cents`, re-derives `remaining_cents` from `available_cents` minus
    `committed_cents`, increases `programmed_count` by one, decreases
    `identified_count` by one, subtracts the cost from `unprogrammed_cost_cents`, and
    increments the cycle's `version` by one."

    Design: Difficulty/compensating_invariant/program_then_withdraw_restores_budget_identity
    """
    setup = _cycle_holding_one_identified_candidate(client, roster, bridge)

    programmed = validate_success(
        client.program_candidate(setup["candidate"]["id"], roster.district_headers), 200
    )
    assert programmed["status"] == "PROGRAMMED"
    a.assert_instant_equals(programmed["programmed_at"], FIELD_DAY, "programmed_at")

    summary = fx.read_allocation(client, setup["cycle"]["id"])
    assert summary["committed_cents"] == COST
    assert summary["remaining_cents"] == AVAILABLE - COST
    assert summary["remaining_cents"] == 9473412000
    assert summary["identified_count"] == 0
    assert summary["programmed_count"] == 1
    assert summary["unprogrammed_cost_cents"] == 0
    assert summary["reserve_cents"] == RESERVE
    assert summary["available_cents"] == AVAILABLE
    assert summary["identity_holds"] is True
    a.assert_budget_identity(fx.read_cycle(client, setup["cycle"]["id"]))


def test_withdrawing_restores_every_money_field_to_its_pre_program_value(
    client, roster, bridge
):
    """
    The compensation is exact: after the round trip the cycle's money reads exactly
    what it read before the commitment, and the reserve was never in play.

    PRD §3.8: "it moves the candidate `PROGRAMMED → WITHDRAWN`, stamps
    `withdrawn_at`, subtracts the cost from `committed_cents`, re-derives
    `remaining_cents`, decreases `programmed_count` by one, and increments the
    cycle's `version` by one — restoring the budget identity with committed spending
    back at its pre-programming value."
    PRD §3.8: "Neither ever touches `reserve_cents` or `available_cents`."

    Design: Difficulty/compensating_invariant/program_then_withdraw_restores_budget_identity
    """
    setup = _cycle_holding_one_identified_candidate(client, roster, bridge)
    before = fx.read_allocation(client, setup["cycle"]["id"])

    validate_success(
        client.program_candidate(setup["candidate"]["id"], roster.district_headers), 200
    )
    validate_success(
        client.withdraw_candidate(setup["candidate"]["id"], roster.district_headers), 200
    )

    after = fx.read_allocation(client, setup["cycle"]["id"])
    for field in (
        "authorized_budget_cents",
        "reserve_cents",
        "available_cents",
        "committed_cents",
        "remaining_cents",
    ):
        assert after[field] == before[field], f"{field} was not restored"
    assert after["committed_cents"] == 0
    assert after["remaining_cents"] == AVAILABLE
    assert after["programmed_count"] == 0
    assert after["deferred_count"] == 0
    assert after["identity_holds"] is True


def test_the_withdrawn_row_leaves_both_buckets_but_keeps_its_own_numbers(
    client, roster, bridge
):
    """
    The candidate does not come back to `IDENTIFIED`: it is terminal, contributes to
    neither money bucket, and yet its own cost and score are untouched — the
    compensation acted on the cycle, not on the estimate.

    PRD §3.8: "Candidates in `DEFERRED` or `WITHDRAWN` contribute to *neither* sum,
    and the reserve is the only rounded quantity in the whole waterfall."
    PRD §3.8: "Both `DEFERRED` and `WITHDRAWN` are terminal; neither a deferred nor a
    withdrawn candidate can be revived, re-programmed or re-deferred, and neither
    contributes to `committed_cents` or `unprogrammed_cost_cents` thereafter."

    Design: Difficulty/compensating_invariant/program_then_withdraw_restores_budget_identity
    """
    setup = _cycle_holding_one_identified_candidate(client, roster, bridge)

    validate_success(
        client.program_candidate(setup["candidate"]["id"], roster.district_headers), 200
    )
    withdrawn = validate_success(
        client.withdraw_candidate(setup["candidate"]["id"], roster.district_headers), 200
    )

    assert withdrawn["status"] == "WITHDRAWN"
    a.assert_instant_equals(withdrawn["withdrawn_at"], FIELD_DAY, "withdrawn_at")
    assert withdrawn["estimated_cost_cents"] == COST
    assert withdrawn["priority_score"] == 43.41

    summary = fx.read_allocation(client, setup["cycle"]["id"])
    assert summary["identified_count"] == 0
    assert summary["unprogrammed_cost_cents"] == 0, (
        "a withdrawn candidate leaves the unprogrammed bucket as well as the "
        "committed one"
    )


def test_the_restored_budget_cannot_be_re_consumed_by_the_same_row(
    client, roster, bridge
):
    """
    The money is back but the row is spent: programming the withdrawn candidate a
    second time is refused on its terminal state.

    PRD §3.8: "Both `DEFERRED` and `WITHDRAWN` are terminal; neither a deferred nor a
    withdrawn candidate can be revived, re-programmed or re-deferred".
    PRD §2.8: "9. **State gating** — the target resource, and any parent whose state
    gates the operation, is in a state from which the requested transition is
    declared, else the family-scoped 409 conflict code".

    Design: Difficulty/compensating_invariant/program_then_withdraw_restores_budget_identity
    """
    setup = _cycle_holding_one_identified_candidate(client, roster, bridge)
    validate_success(
        client.program_candidate(setup["candidate"]["id"], roster.district_headers), 200
    )
    validate_success(
        client.withdraw_candidate(setup["candidate"]["id"], roster.district_headers), 200
    )

    response = client.program_candidate(
        setup["candidate"]["id"], roster.district_headers
    )

    validate_error(response, e.ERR_PROGRAM_STATE_INVALID, 409)
    assert fx.read_candidate(client, setup["candidate"]["id"])["status"] == "WITHDRAWN"
    assert fx.read_allocation(client, setup["cycle"]["id"])["committed_cents"] == 0
