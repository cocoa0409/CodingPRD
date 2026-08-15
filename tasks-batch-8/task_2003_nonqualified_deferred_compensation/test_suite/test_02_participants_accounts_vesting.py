"""Participants, accounts, vesting boundary, and the separation/rehire cycle.

PRD §3.3 (Participants, Accounts, the Ledger), §3.4 (Separation determination).
"""
from test_helpers import (
    TEST_USERS,
    add_member,
    advance_clock,
    assert_account,
    assert_participant,
    create_active_plan,
    create_draft_specified_list,
    create_election,
    determine_case,
    enroll_participant,
    finalize_list,
    get_participant,
    get_statement,
    open_account,
    open_separation_case,
    post_deferral,
    setup_funded_account,
    setup_plan_fund_window,
    settle_account,
    standard_evidence,
    submit_election,
    validate_error,
    validate_paginated,
    validate_success,
)

PS = TEST_USERS["plan_sponsor_headers"]
BA = TEST_USERS["benefits_admin_headers"]


def test_participant_create_initializes_computed_fields(api):
    """PRD §3.3: "A new participant starts `ACTIVE` with `is_specified_employee`
    false and an `inclusion_liability_cents` of zero."

    Design: Corner/entities/participant_create_initializes_computed_fields
    """
    plan = create_active_plan(name="Plan P", distribution_events_allowed=["SEPARATION"])
    participant = validate_success(api.create_participant({
        "plan_id": plan["id"], "employee_ref": "EMP-1", "hire_date": "2023-01-02",
        "initial_eligibility_date": "2026-01-05", "annual_compensation_cents": 30000000,
    }, BA), 201)
    assert_participant(participant)
    assert participant["status"] == "ACTIVE"
    assert participant["is_specified_employee"] is False
    assert participant["inclusion_liability_cents"] == 0


def test_participants_list_pagination_defaults(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return. If not provided, it defaults to 10, with a minimum of 1 and maximum
    of 100. The `offset` parameter specifies the number of items to skip and
    defaults to 0."
    PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/participants_list_pagination_defaults
    """
    plan = create_active_plan(name="Plan PG", distribution_events_allowed=["SEPARATION"])
    for i in range(1, 13):
        enroll_participant(plan["id"], employee_ref=f"EMP-P{i:02d}")

    page1, meta1 = validate_paginated(api.list_participants(BA, params={"plan_id": plan["id"]}))
    assert len(page1) == 10, f"default page returns 10 items, got {len(page1)}"
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True
    assert meta1["limit"] == 10
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_participants(BA, params={"plan_id": plan["id"], "offset": 10}))
    assert len(page2) == 2, f"offset=10 returns the remaining 2 items, got {len(page2)}"
    assert meta2["total_count"] == 12
    assert meta2["has_more"] is False


def test_account_create_duplicate_rejected(api):
    """PRD §3.3: "there is exactly one account per participant per plan, a second
    attempt being rejected with `ERR_ACCOUNT_EXISTS`."

    Design: Corner/entities/account_create_duplicate_rejected
    """
    plan = create_active_plan(name="Plan AD", distribution_events_allowed=["SEPARATION"])
    participant = enroll_participant(plan["id"], employee_ref="EMP-AD")
    account = open_account(participant["id"], plan["id"])
    assert_account(account)
    assert account["status"] == "ACTIVE"

    dup = api.create_account({"participant_id": participant["id"], "plan_id": plan["id"]}, BA)
    validate_error(dup, "ERR_ACCOUNT_EXISTS", expected_status=409)

    rows, meta = validate_paginated(
        api.list_accounts(BA, params={"participant_id": participant["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == account["id"], "the first account is untouched"


def test_vesting_cliff_exact_third_year_boundary(api):
    """PRD §3.3: "Service is measured in whole days from the participant's
    `hire_date` to the clock date, converted to thousandths of a year by
    multiplying the day count by one thousand and dividing by 365 with the
    quotient rounded down. When that figure reaches at least the plan's
    `vesting_cliff_years` expressed in thousandths — cliff vesting is
    all-or-nothing — the participant's `vested_bp` is 10000; below the cliff it
    is 0. Service of exactly the cliff duration counts as vested, the boundary
    being inclusive."

    At clock 2027-08-04: participant Q (hire 2024-08-04) has exactly 1095 days =
    3000 thousandths == 3-year cliff and IS vested; participant R (hire
    2024-08-05) has 1094 days = 2997 thousandths and is NOT vested.

    Design: Difficulty/boundary_precision_check/vesting_cliff_exact_third_year_boundary
    """
    ctx = setup_plan_fund_window(
        plan_overrides={"name": "Plan VB", "distribution_events_allowed": ["SEPARATION"],
                        "vesting_cliff_years": 3})
    q = enroll_participant(ctx["plan"]["id"], employee_ref="EMP-Q", hire_date="2024-08-04")
    r = enroll_participant(ctx["plan"]["id"], employee_ref="EMP-R", hire_date="2024-08-05")
    acct_q = open_account(q["id"], ctx["plan"]["id"])
    acct_r = open_account(r["id"], ctx["plan"]["id"])

    advance_clock("2026-10-15T00:00:00Z")  # window OPEN
    e_q = create_election(q["id"], ctx["window"]["id"], ctx["fund"]["id"],
                          deferral_percent_bp=5000)
    submit_election(e_q["id"], q["id"])
    e_r = create_election(r["id"], ctx["window"]["id"], ctx["fund"]["id"],
                          deferral_percent_bp=5000)
    submit_election(e_r["id"], r["id"])

    advance_clock("2027-01-01T00:00:00Z")  # window CLOSED -> both LOCKED
    post_deferral(e_q["id"], 100000)
    post_deferral(e_r["id"], 100000)
    settle_account(acct_q["id"])
    settle_account(acct_r["id"])

    advance_clock("2027-08-04T00:00:00Z")  # exactly Q's third service anniversary
    st_q = get_statement(acct_q["id"])
    st_r = get_statement(acct_r["id"])
    assert st_q["settled_balance_cents"] == 100000
    assert st_r["settled_balance_cents"] == 100000
    assert st_q["vested_bp"] == 10000, "3000 thousandths == cliff*1000, inclusive boundary"
    assert st_q["vested_balance_cents"] == 100000
    assert st_r["vested_bp"] == 0, "2997 thousandths is below the cliff"
    assert st_r["vested_balance_cents"] == 0


def test_vesting_cliff_one_year_boundary_at_default_clock(api):
    """PRD §3.3: "Service of exactly the cliff duration counts as vested, the
    boundary being inclusive."

    A plan with `vesting_cliff_years` of 1 and a participant hired 2025-08-01
    reaches exactly 365 days = 1000 thousandths at the startup clock
    2026-08-01T00:00:00Z; vesting evaluated at the statement read is vested at
    the inclusive boundary (the funding flow later advances the clock, at which
    point service only grows).

    Design: Difficulty/boundary_precision_check/vesting_cliff_exact_third_year_boundary
    """
    ctx = setup_funded_account(
        100000,
        plan_overrides={"name": "Plan VB1", "distribution_events_allowed": ["SEPARATION"],
                        "vesting_cliff_years": 1},
        participant_overrides={"employee_ref": "EMP-VB1", "hire_date": "2025-08-01"},
    )
    statement = get_statement(ctx["account"]["id"])
    assert statement["settled_balance_cents"] == 100000
    assert statement["vested_bp"] == 10000, "at least one year of service is vested"
    assert statement["vested_balance_cents"] == 100000


def test_participant_separation_rehire_cycle(api):
    """PRD §3.4: "the participant moves from `SEPARATION_REVIEW` to `SEPARATED`
    with `separation_date` set to the case's `alleged_separation_date`".
    PRD §3.3: "a participant who is `SEPARATED` — and only one who is
    `SEPARATED`, else `ERR_PARTICIPANT_STATE_INVALID` — may be returned to
    `ACTIVE`, which clears `separation_date` to null and resets
    `is_specified_employee` to false."

    Design: Difficulty/non_linear_state_machine/participant_separation_rehire_cycle
    """
    plan = create_active_plan(name="Plan CY", distribution_events_allowed=["SEPARATION"])
    participant = enroll_participant(plan["id"], employee_ref="EMP-CY")
    case = open_separation_case(participant["id"], "2027-03-15", "RESIGNATION")
    standard_evidence(case["id"])

    determined = determine_case(case["id"], "CONFIRMED_SEPARATION")
    assert determined["status"] == "DETERMINED_SEPARATED"

    mid = get_participant(participant["id"])
    assert mid["status"] == "SEPARATED", "cycle hop ACTIVE->SEPARATION_REVIEW->SEPARATED"
    assert mid["separation_date"] == "2027-03-15"

    rehired = validate_success(api.rehire_participant(participant["id"], BA), 200)
    assert rehired["status"] == "ACTIVE", "rehire closes the cycle SEPARATED->ACTIVE"
    assert rehired["separation_date"] is None


def test_rehire_resets_specified_employee_flag(api):
    """PRD §3.3: "a participant who is `SEPARATED` — and only one who is
    `SEPARATED`, else `ERR_PARTICIPANT_STATE_INVALID` — may be returned to
    `ACTIVE`, which clears `separation_date` to null and resets
    `is_specified_employee` to false."

    A participant marked as a specified employee via a finalized list loses the
    flag on rehire — the cycle resets both per-hop fields.

    Design: Difficulty/non_linear_state_machine/participant_separation_rehire_cycle
    """
    plan = create_active_plan(name="Plan CY2", distribution_events_allowed=["SEPARATION"])
    participant = enroll_participant(plan["id"], employee_ref="EMP-CY2")

    lst = create_draft_specified_list(plan["id"])
    add_member(lst["id"], participant["id"], "FIVE_PERCENT_OWNER", 30000000)
    finalize_list(lst["id"])
    assert get_participant(participant["id"])["is_specified_employee"] is True

    case = open_separation_case(participant["id"], "2027-03-15", "RESIGNATION")
    standard_evidence(case["id"])
    determine_case(case["id"], "CONFIRMED_SEPARATION")
    assert get_participant(participant["id"])["status"] == "SEPARATED"

    rehired = validate_success(api.rehire_participant(participant["id"], BA), 200)
    assert rehired["status"] == "ACTIVE"
    assert rehired["is_specified_employee"] is False, "rehire resets the specified flag"
    assert rehired["separation_date"] is None
