"""Shared expenses, custom splits, void, and the net-balance ledger.

Translates queue-A compensating_invariant (expense void preserves ledger sum),
transitive_cascade (dispute resolve adjusts expense -> shares -> balances), plus
queue-B calculation/consistency corner instances.
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    make_roommate_headers,
    make_mediator_headers,
    build_household_with_members,
    post_expense,
    find_split_for_profile,
    freeze_household_via_dispute,
    assert_ledger_conserved,
)

api = api_client


def test_custom_expense_overrides_used_verbatim_and_net_balance_reflects():
    """PRD §3.6: "Under `CUSTOM`, the `share_overrides` map assigns explicit cents per
    profile; its keys must be exactly the `participant_ids` and its values must sum to
    `total_amount_cents`, or the request is rejected with `ERR_SHARES_DO_NOT_SUM`."
    PRD §2.6: "a negative value means the member owes the household (they are a debtor)."

    CUSTOM 10000 with M1:7000, M2:3000 -> shares 7000/3000; M2 owes 3000 so its
    net_balance_cents is -3000.

    Design: Corner/calculations/custom_expense_share_overrides_applied
    """
    env = build_household_with_members(
        api, [{"full_name": "CustM1"}, {"full_name": "CustM2"}],
        listing_overrides={"capacity": 3},
    )
    m1, m2 = env["members"]
    lh = make_roommate_headers(env["lister"]["id"])
    expense = post_expense(
        api, env, payer=m1, participants=[m1, m2], total_amount_cents=10000,
        split_mode="CUSTOM", share_overrides={m1["id"]: 7000, m2["id"]: 3000},
    )
    shares = validate_success(api.list_expense_shares(expense["id"], lh))
    assert find_split_for_profile(shares, m1["id"])["share_cents"] == 7000
    assert find_split_for_profile(shares, m2["id"])["share_cents"] == 3000

    m2_after = validate_success(api.get_profile(m2["id"], lh))
    assert m2_after["net_balance_cents"] == -3000


def test_expense_posts_net_balance_immediately_visible():
    """PRD §2.6: "the total of all amounts they paid up front on `POSTED` expenses
    (their credits), minus the total of the expense shares assigned to them across
    `POSTED` expenses and any unpaid bill shares they still owe (their obligations)"
    PRD §3.6: "logging it recomputes every household member's `net_balance_cents` while
    keeping `ledger_sum_cents` at zero."

    A 9000 EQUAL expense by M1 over M1,M2 -> M1 +4500, M2 -4500, visible immediately.

    Design: Corner/consistency_model/immediate_visibility_of_expense_net_balance
    """
    env = build_household_with_members(
        api, [{"full_name": "ImmM1"}, {"full_name": "ImmM2"}],
        listing_overrides={"capacity": 3},
    )
    m1, m2 = env["members"]
    lh = make_roommate_headers(env["lister"]["id"])
    post_expense(api, env, payer=m1, participants=[m1, m2], total_amount_cents=9000)

    m1_after = validate_success(api.get_profile(m1["id"], lh))
    m2_after = validate_success(api.get_profile(m2["id"], lh))
    assert m1_after["net_balance_cents"] == 4500
    assert m2_after["net_balance_cents"] == -4500


def test_expense_void_returns_balances_to_zero_and_conserves_ledger():
    """PRD §3.6: "A posted expense can be reversed with a void, a compensating action
    that moves the expense from `POSTED` to `VOIDED` and undoes its ledger impact.
    Voiding recomputes the household's net balances and again leaves `ledger_sum_cents`
    at zero."

    Design: Difficulty/compensating_invariant/expense_void_preserves_ledger_sum_zero
    """
    env = build_household_with_members(
        api, [{"full_name": "M1.17"}, {"full_name": "M2.17"}],
        listing_overrides={"capacity": 3},
    )
    m1, m2 = env["members"]
    lh = make_roommate_headers(env["lister"]["id"])
    expense = post_expense(api, env, payer=m1, participants=[m1, m2], total_amount_cents=9000)

    voided = validate_success(api.void_expense(expense["id"], make_roommate_headers(m1["id"])))
    assert voided["status"] == "VOIDED"

    assert validate_success(api.get_profile(m1["id"], lh))["net_balance_cents"] == 0
    assert validate_success(api.get_profile(m2["id"], lh))["net_balance_cents"] == 0
    assert_ledger_conserved(validate_success(api.get_household(env["household"]["id"], lh)))


def test_expense_void_leaves_ledger_sum_zero_three_members():
    """PRD §2.6: "After every ledger-mutating operation — logging or voting an expense,
    confirming a settlement, resolving a dispute that adjusts an expense, or moving a
    member out — `ledger_sum_cents` must come back to exactly zero."

    A second arrangement (three participants) confirms the conservation invariant holds
    across the void compensation regardless of participant count.

    Design: Difficulty/compensating_invariant/expense_void_preserves_ledger_sum_zero
    """
    env = build_household_with_members(
        api, [{"full_name": "V1"}, {"full_name": "V2"}, {"full_name": "V3"}],
        listing_overrides={"capacity": 4},
    )
    m1, m2, m3 = env["members"]
    lh = make_roommate_headers(env["lister"]["id"])
    expense = post_expense(
        api, env, payer=m1, participants=[m1, m2, m3], total_amount_cents=9000
    )
    validate_success(api.void_expense(expense["id"], make_roommate_headers(m1["id"])))

    for m in (m1, m2, m3):
        assert validate_success(api.get_profile(m["id"], lh))["net_balance_cents"] == 0
    assert_ledger_conserved(validate_success(api.get_household(env["household"]["id"], lh)))


def test_dispute_resolve_adjusts_expense_recomputes_shares_and_balances():
    """PRD §3.9: "Resolving sets the dispute to `RESOLVED` and records the
    `adjusted_amount_cents`; when the dispute targets an expense, an
    `adjusted_amount_cents` greater than zero must be supplied, and the targeted
    expense's `total_amount_cents` is reset to that adjusted amount, its `ExpenseShare`
    rows are recomputed, every member's `net_balance_cents` is recomputed, and
    `ledger_sum_cents` stays zero."

    9000 EQUAL over M1,M2,M3 (3000 each), adjusted to 6000 -> shares 2000 each; payer
    M1 credit becomes 6000 - 2000 = 4000.

    Design: Difficulty/transitive_cascade/dispute_resolve_cascade_expense_shares_balances
    """
    env = build_household_with_members(
        api, [{"full_name": "M1.8"}, {"full_name": "M2.8"}, {"full_name": "M3.8"}],
        listing_overrides={"capacity": 4},
    )
    m1, m2, m3 = env["members"]
    lh = make_roommate_headers(env["lister"]["id"])
    expense = post_expense(
        api, env, payer=m1, participants=[m1, m2, m3], total_amount_cents=9000,
        description="groceries",
    )
    dispute = freeze_household_via_dispute(api, env, filer=m2, expense=expense, mediator_id="med-1")

    resolved = validate_success(
        api.resolve_dispute(dispute["id"], {"adjusted_amount_cents": 6000}, make_mediator_headers("med-1"))
    )
    assert resolved["status"] == "RESOLVED"

    expense_after = validate_success(api.get_expense(expense["id"], lh))
    assert expense_after["total_amount_cents"] == 6000

    shares = validate_success(api.list_expense_shares(expense["id"], lh))
    assert find_split_for_profile(shares, m1["id"])["share_cents"] == 2000
    assert find_split_for_profile(shares, m2["id"])["share_cents"] == 2000

    assert validate_success(api.get_profile(m1["id"], lh))["net_balance_cents"] == 4000
    assert_ledger_conserved(validate_success(api.get_household(env["household"]["id"], lh)))


def test_dispute_resolve_keeps_ledger_conserved_with_full_adjustment():
    """PRD §2.6: "After every ledger-mutating operation — logging or voting an expense,
    confirming a settlement, resolving a dispute that adjusts an expense, or moving a
    member out — `ledger_sum_cents` must come back to exactly zero."
    PRD §3.9: "every member's `net_balance_cents` is recomputed, and `ledger_sum_cents`
    stays zero."

    A second resolve scenario over three members confirms the cascade's terminal
    conservation hop independently of the specific adjusted amount.

    Design: Difficulty/transitive_cascade/dispute_resolve_cascade_expense_shares_balances
    """
    env = build_household_with_members(
        api, [{"full_name": "R1"}, {"full_name": "R2"}, {"full_name": "R3"}],
        listing_overrides={"capacity": 4},
    )
    m1, m2, m3 = env["members"]
    lh = make_roommate_headers(env["lister"]["id"])
    expense = post_expense(
        api, env, payer=m1, participants=[m1, m2, m3], total_amount_cents=9000
    )
    dispute = freeze_household_via_dispute(api, env, filer=m3, expense=expense, mediator_id="med-2")
    validate_success(
        api.resolve_dispute(dispute["id"], {"adjusted_amount_cents": 3000}, make_mediator_headers("med-2"))
    )
    expense_after = validate_success(api.get_expense(expense["id"], lh))
    assert expense_after["total_amount_cents"] == 3000
    assert_ledger_conserved(validate_success(api.get_household(env["household"]["id"], lh)))
