"""Quantities that must balance whatever route was taken: pool capacity across
the occupation cycle, and the ledger against the policy total."""

from test_helpers import (
    assert_ledger_sums_to_total,
    assert_policy_money_zeroed,
    assert_pool_capacity_identity,
    bind_policy_ok,
    cancel_policy_ok,
    ledger_by_sequence,
    patch_item_ok,
    read_endorsement,
    read_item,
    read_ledger,
    read_policy,
    read_pool,
    read_reservations,
    reservation_by_peril,
    setup_policy_with_approved_endorsement,
    setup_rated_dwelling_policy,
)

RESERVED_BY_PERIL = {"HAIL": 20_000_000, "WIND": 12_000_000, "WILDFIRE": 8_000_000}


def _assert_pool_row(pool: dict, reserved: int, committed: int) -> None:
    assert pool["reserved_cents"] == reserved
    assert pool["committed_cents"] == committed
    assert pool["total_capacity_cents"] == 200_000_000
    assert_pool_capacity_identity(pool)


def test_pool_capacity_balances_at_every_stage_of_the_occupation(api):
    """"`available_cents` is `total_capacity_cents` less `reserved_cents` less
    `committed_cents`. All three start at zero on a new pool — so
    `available_cents` starts equal to `total_capacity_cents` — and all three are
    recomputed, with the pool's `version` incremented by 1, every single time a
    reservation on that pool changes status." Across creation, rating, binding
    and cancellation each pool is inspected four times and the identity holds
    every time, ending on a version of 4.

    Design: Difficulty/compensating_invariant/cat_pool_capacity_conserved_across_reserve_commit_release
    """
    scenario = setup_rated_dwelling_policy(with_labor_profile=True)

    for peril, amount in RESERVED_BY_PERIL.items():
        after_rating = read_pool(scenario.pools[peril]["id"])
        _assert_pool_row(after_rating, reserved=amount, committed=0)
        assert after_rating["available_cents"] == 200_000_000 - amount
        assert after_rating["version"] == 2

    bind_policy_ok(scenario.policy_id)
    for peril, amount in RESERVED_BY_PERIL.items():
        after_bind = read_pool(scenario.pools[peril]["id"])
        _assert_pool_row(after_bind, reserved=0, committed=amount)
        assert after_bind["available_cents"] == 200_000_000 - amount
        assert after_bind["version"] == 3

    cancel_policy_ok(scenario.policy_id, "Insured sold the operation")
    for peril in RESERVED_BY_PERIL:
        after_cancel = read_pool(scenario.pools[peril]["id"])
        _assert_pool_row(after_cancel, reserved=0, committed=0)
        assert after_cancel["available_cents"] == 200_000_000
        assert after_cancel["version"] == 4


def test_committing_moves_the_amount_between_buckets_and_releasing_returns_it(api):
    """"Reserved capacity becoming committed leaves `available_cents` unchanged —
    the amount simply moves from one bucket to the other — while any release
    returns the amount to `available_cents`." The three reservation rows keep
    their `amount_cents` after the release, so the released capacity is auditable
    rather than erased, and the zone is whole again at 600000000 cents available.

    Design: Difficulty/compensating_invariant/cat_pool_capacity_conserved_across_reserve_commit_release
    """
    scenario = setup_rated_dwelling_policy(with_labor_profile=True)
    available_after_rating = {
        peril: read_pool(scenario.pools[peril]["id"])["available_cents"]
        for peril in RESERVED_BY_PERIL
    }

    bind_policy_ok(scenario.policy_id)
    for peril, available in available_after_rating.items():
        assert read_pool(scenario.pools[peril]["id"])["available_cents"] == available

    cancel_policy_ok(scenario.policy_id, "Insured sold the operation")

    released = reservation_by_peril(scenario.policy_id)
    for peril, amount in RESERVED_BY_PERIL.items():
        assert released[peril]["status"] == "RELEASED"
        assert released[peril]["amount_cents"] == amount

    zone_available = sum(
        read_pool(scenario.pools[peril]["id"])["available_cents"] for peril in RESERVED_BY_PERIL
    )
    assert zone_available == 600_000_000


def test_the_ledger_still_sums_to_the_total_after_a_full_reversal(api):
    """"At every observable point in a policy's life, the sum of `amount_cents`
    across all of that policy's ledger entries equals its `total_premium_cents`."
    Three entries sum to 401200 while the peak-season increase is approved; after
    an item amendment reverts the quote, six entries sum to zero and the policy
    reports zero.

    Design: Difficulty/compensating_invariant/premium_ledger_sum_equals_total_after_reversal
    """
    scenario = setup_policy_with_approved_endorsement()
    before = read_policy(scenario.policy_id)
    assert before["endorsement_premium_cents"] == 132_000
    assert before["total_premium_cents"] == 401_200
    assert_ledger_sums_to_total(read_ledger(scenario.policy_id), 401_200)

    patch_item_ok(scenario.item["id"], scenario.agent_headers, stated_value_cents=45_000_000)

    after = read_policy(scenario.policy_id)
    assert after["uw_status"] == "DRAFT"
    assert_policy_money_zeroed(after)
    entries = read_ledger(scenario.policy_id)
    assert len(entries) == 6
    assert_ledger_sums_to_total(entries, after["total_premium_cents"])
    assert sum(row["amount_cents"] for row in entries) == 0


def test_the_reversal_batch_mirrors_each_prior_entry_in_sequence_order(api):
    """"A full reversal batch is appended, one `REVERSAL` entry per prior
    non-reversed entry replayed in `sequence_no` ascending order with
    `reason_code` `RATING_REVERT`." The three originals are left exactly as
    written and the mirrors at 4, 5 and 6 negate them one for one, while the
    suspended endorsement keeps its 132000 cents on the row because the replay
    has already removed that money.

    Design: Difficulty/compensating_invariant/premium_ledger_sum_equals_total_after_reversal
    """
    scenario = setup_policy_with_approved_endorsement()

    amended = patch_item_ok(
        scenario.item["id"], scenario.agent_headers, stated_value_cents=45_000_000
    )
    assert amended["insured_value_cents"] == 45_000_000
    assert amended["version"] == 2

    by_sequence = ledger_by_sequence(read_ledger(scenario.policy_id))
    assert [by_sequence[n]["amount_cents"] for n in (1, 2, 3)] == [144_000, 125_200, 132_000]
    assert [by_sequence[n]["reverses_sequence_no"] for n in (1, 2, 3)] == [None, None, None]
    for source, mirror in ((1, 4), (2, 5), (3, 6)):
        assert by_sequence[mirror]["txn_type"] == "REVERSAL"
        assert by_sequence[mirror]["reason_code"] == "RATING_REVERT"
        assert by_sequence[mirror]["reverses_sequence_no"] == source
        assert by_sequence[mirror]["amount_cents"] == -by_sequence[source]["amount_cents"]

    suspended = read_endorsement(scenario.endorsement["id"])
    assert suspended["status"] == "SUSPENDED"
    assert suspended["premium_cents"] == 132_000

    assert {row["status"] for row in read_reservations(scenario.policy_id)} == {"RELEASED"}
    assert read_pool(scenario.hail_pool["id"])["available_cents"] == 200_000_000
    assert read_item(scenario.item["id"])["insured_value_cents"] == 45_000_000
