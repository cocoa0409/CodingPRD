"""Cyclic state-machine tests: proposal counter rounds, costing rework loop
(difficulty rule 3)."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_draft_agreement,
    create_employer_proposal_on_table,
    create_proposal_payload,
    create_union,
    get_success_data,
    make_union_representative_headers,
    validate_error,
    validate_success,
    ApiErrorId,
)

ADMIN = TEST_USERS["lr_admin_headers"]
NEG1 = TEST_USERS["negotiator_headers"]
NEG2 = TEST_USERS["negotiator_2_headers"]
CHIEF = TEST_USERS["chief_negotiator_headers"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / proposal_counter_round_cycle
# ---------------------------------------------------------------------------

def _setup_union_proposal_on_table(api):
    union = create_union(name="Union E")
    agreement = create_draft_agreement(
        union["id"],
        title="CBA E",
        headcount_baseline=50,
        fte_projected=60,
        avg_loaded_wage_cents=4000,
        costing_envelope_cents=1_000_000_000_000,
    )
    rep = make_union_representative_headers(union["id"])
    p1 = get_success_data(
        api.create_proposal(
            create_proposal_payload(
                agreement_id=agreement["id"],
                side="UNION",
                title="Scheduling art 1",
                proposal_type="NON_ECONOMIC",
            ),
            rep,
        )
    )
    get_success_data(api.transition_proposal(p1["id"], {"to_status": "TENDERED"}, rep))
    p1 = get_success_data(api.transition_proposal(p1["id"], {"to_status": "ON_TABLE"}, CHIEF))
    return union, agreement, p1


def test_counter_chain_status_and_sides(api):
    """PRD §3.4: "The original proposal becomes `COUNTERED`, and a new proposal
    is created in the same request with `side` flipped, `status` `ON_TABLE`,
    `round_number` equal to the original's `round_number` plus 1,
    `supersedes_proposal_id` set to the original's `id`, and `agreement_id`
    and `clause_id` carried over."

    Design: Difficulty/non_linear_state_machine/proposal_counter_round_cycle
    """
    union, _, p1 = _setup_union_proposal_on_table(api)
    rep = make_union_representative_headers(union["id"])
    p2 = get_success_data(api.counter_proposal(p1["id"], {"title": "Employer counter 1"}, CHIEF))
    p3 = get_success_data(api.counter_proposal(p2["id"], {"title": "Union counter 2"}, rep))

    p1_after = get_success_data(api.get_proposal(p1["id"], NEG1))
    p2_after = get_success_data(api.get_proposal(p2["id"], NEG1))
    p3_after = get_success_data(api.get_proposal(p3["id"], NEG1))

    assert p1_after["status"] == "COUNTERED"
    assert p2_after["status"] == "COUNTERED"
    assert p2_after["round_number"] == 2
    assert p2_after["side"] == "EMPLOYER"
    assert p3_after["status"] == "ON_TABLE"
    assert p3_after["round_number"] == 3
    assert p3_after["side"] == "UNION"


def test_counter_chain_supersedes_link(api):
    """PRD §3.4: "a new proposal is created in the same request with `side`
    flipped, `status` `ON_TABLE`, `round_number` equal to the original's
    `round_number` plus 1, `supersedes_proposal_id` set to the original's
    `id`, and `agreement_id` and `clause_id` carried over."

    Design: Difficulty/non_linear_state_machine/proposal_counter_round_cycle
    """
    union, _, p1 = _setup_union_proposal_on_table(api)
    rep = make_union_representative_headers(union["id"])
    p2 = get_success_data(api.counter_proposal(p1["id"], {"title": "Employer counter 1"}, CHIEF))
    p3 = get_success_data(api.counter_proposal(p2["id"], {"title": "Union counter 2"}, rep))

    assert p3["supersedes_proposal_id"] == p2["id"]
    assert p2["supersedes_proposal_id"] == p1["id"]
    assert p3["agreement_id"] == p1["agreement_id"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / costing_scenario_rework_cycle
# ---------------------------------------------------------------------------

def _setup_rework_scenario(api):
    union = create_union(name="Union F")
    agreement = create_draft_agreement(
        union["id"],
        title="CBA F",
        headcount_baseline=100,
        fte_projected=120,
        avg_loaded_wage_cents=5000,
        costing_envelope_cents=1_000_000_000_000,
    )
    proposal = create_employer_proposal_on_table(
        agreement["id"],
        union["id"],
        title="Allowance",
        proposal_type="ECONOMIC",
        recurring_annual_cost_cents=100,
    )
    scenario = get_success_data(
        api.create_costing_scenario(
            {
                "agreement_id": agreement["id"],
                "name": "rework",
                "scenario_mode": "FINAL",
                "term_years": 3,
                "proposal_ids": [proposal["id"]],
            },
            NEG1,
        )
    )
    return scenario


def test_scenario_rework_loop_recomputes_idempotently(api):
    """PRD §3.5: "A scenario in `REVIEWED` may be sent back to `DRAFT` by a
    `Negotiator` (the rework loop); totals are retained but stale until the
    next compute." and "A `Negotiator` triggers it by transitioning the
    scenario to `COMPUTED`; the same transition is reused for a re-compute
    after rework, so the from-state may be `DRAFT` or `REVIEWED`."

    Design: Difficulty/non_linear_state_machine/costing_scenario_rework_cycle
    """
    scenario = _setup_rework_scenario(api)
    get_success_data(api.transition_costing_scenario(scenario["id"], {"to_status": "COMPUTED"}, NEG1))
    get_success_data(api.transition_costing_scenario(scenario["id"], {"to_status": "REVIEWED"}, NEG2))
    get_success_data(api.transition_costing_scenario(scenario["id"], {"to_status": "DRAFT"}, NEG2))
    recomputed = get_success_data(
        api.transition_costing_scenario(scenario["id"], {"to_status": "COMPUTED"}, NEG2)
    )
    assert recomputed["status"] == "COMPUTED"
    # FINAL mode: basis 100; wage 0 (pct null); recurring 100/yr * 3 = 300;
    # reserve round_half_up(0.05*300) = 15; total = 315.
    assert recomputed["total_cost_cents"] == 315


def test_scenario_rework_tracks_latest_computer(api):
    """PRD §3.5: "The compute records the acting `X-User-ID` as
    `computed_by_user_id` and increments the scenario's `version`."

    Design: Difficulty/non_linear_state_machine/costing_scenario_rework_cycle
    """
    scenario = _setup_rework_scenario(api)
    get_success_data(api.transition_costing_scenario(scenario["id"], {"to_status": "COMPUTED"}, NEG1))
    get_success_data(api.transition_costing_scenario(scenario["id"], {"to_status": "REVIEWED"}, NEG2))
    get_success_data(api.transition_costing_scenario(scenario["id"], {"to_status": "DRAFT"}, NEG2))
    recomputed = get_success_data(
        api.transition_costing_scenario(scenario["id"], {"to_status": "COMPUTED"}, NEG2)
    )
    assert recomputed["computed_by_user_id"] == "neg-2", (
        f"latest computer must be tracked; got {recomputed['computed_by_user_id']!r}"
    )
