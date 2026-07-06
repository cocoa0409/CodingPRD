"""Boundary precision: inclusive wage floor at exact equality, and the empty
lottery candidate set (PRD §3.4, §3.5).

Queue A / Difficulty — rule `boundary_precision_check`.
"""
from test_helpers import (
    api_client, validate_success, TEST_USERS,
    create_employer, create_lca, create_cap_program, run_lottery,
)

DOL = TEST_USERS["dol_analyst_headers"]


def test_lca_certifies_when_offered_exactly_equals_prevailing(api):
    """PRD §3.4: "Certification is defined only from `DRAFT`, and requires that
    `offered_wage_cents` be at least `prevailing_wage_cents` (otherwise
    `ERR_WAGE_BELOW_PREVAILING`)."

    Design: Difficulty/boundary_precision_check/lca_wage_exactly_equal_prevailing_certifies
    """
    emp = create_employer()
    lca = create_lca(emp["id"], offered_wage_cents=10000000, prevailing_wage_cents=10000000,
                     area_wage_map={"AREA_A": 10000000})
    certified = validate_success(api.transition_lca(lca["id"], {"to_status": "CERTIFIED"}, DOL), 200)
    assert certified["status"] == "CERTIFIED"


def test_lca_locks_required_wage_at_equal_boundary(api):
    """PRD §3.4: "On certification the system locks `required_wage_cents` to the
    greater of `prevailing_wage_cents` and `offered_wage_cents` as of that
    instant".

    Design: Difficulty/boundary_precision_check/lca_wage_exactly_equal_prevailing_certifies
    """
    emp = create_employer()
    lca = create_lca(emp["id"], offered_wage_cents=10000000, prevailing_wage_cents=10000000,
                     area_wage_map={"AREA_A": 10000000})
    certified = validate_success(api.transition_lca(lca["id"], {"to_status": "CERTIFIED"}, DOL), 200)
    assert certified["required_wage_cents"] == 10000000


def test_empty_lottery_selects_nothing_and_keeps_all_seats(api):
    """PRD §3.5: "If no candidates qualify, nothing is selected and
    `available_seats` remains equal to `selection_quota`."

    Design: Difficulty/boundary_precision_check/lottery_empty_candidate_set
    """
    cap = create_cap_program(fiscal_year=2029, selection_quota=5)
    program = run_lottery(cap["id"])
    assert program["selected_count"] == 0
    assert program["available_seats"] == 5


def test_empty_lottery_still_marks_lottery_run(api):
    """PRD §3.5: "After the walk, `lottery_run` is set to true."

    Design: Difficulty/boundary_precision_check/lottery_empty_candidate_set
    """
    cap = create_cap_program(fiscal_year=2029, selection_quota=5)
    program = run_lottery(cap["id"])
    assert program["lottery_run"] is True
