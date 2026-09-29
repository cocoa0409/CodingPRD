"""Queue B — §1.7 consistency-model corner: the declared model is immediate, so the two
most cascade-heavy writes in the system are used as the proof. The response body of each
already carries every derived figure, and four other entities agree on the very next read."""
from test_helpers import (
    ADMIN,
    PREPARER,
    assert_allocations_sum_to,
    assert_instant_equals,
    assert_pool_allocation,
    close_shift,
    declare_shift_tips,
    list_allocations_of,
    new_active_policy,
    new_employee,
    new_job_role,
    new_location,
    new_pay_period,
    new_role_assignment,
    new_shift,
    read_employee,
    read_location,
    read_pool,
    read_shift,
    set_logical_clock,
    validate_paginated,
    validate_success,
)
from test_helpers import create_shift_tip_pool_payload

CLOCK = "2026-08-10T12:00:00Z"
BUSINESS_DATE = "2026-08-04T00:00:00Z"


def _pool_ready_world() -> dict:
    """A Texas unit under an ACTIVE TIPPED_ONLY / TIPS_RECEIVED_PCT / POINTS_ONLY policy
    that does not pass the card fee through, where Ana the server declared 4000 cash and
    Bea the busser declared nothing on 2026-08-04; both shifts CLOSED and unpooled."""
    set_logical_clock()
    location = new_location()
    role_server = new_job_role()
    role_busser = new_job_role(
        code="BUSSER",
        title="Busser",
        pool_contribution_pct_bps=0,
        pool_share_points=4,
    )
    ana = new_employee(location["id"], full_name="Ana Reyes")
    bea = new_employee(
        location["id"], full_name="Bea Lima", external_payroll_ref="E2"
    )
    new_role_assignment(ana["id"], role_server["id"])
    new_role_assignment(bea["id"], role_busser["id"])
    policy = new_active_policy(
        location["id"],
        location["version"],
        share_basis="POINTS_ONLY",
        cc_fee_pass_through=False,
    )
    period = new_pay_period(location["id"])

    shifts = {}
    for key, employee, role in (
        ("ana_shift", ana, role_server),
        ("bea_shift", bea, role_busser),
    ):
        shift = new_shift(employee["id"], location["id"], role["id"], period["id"])
        close_shift(shift["id"])
        shifts[key] = shift
    declare_shift_tips(shifts["ana_shift"]["id"], ana["id"], 4000, 0)
    declare_shift_tips(shifts["bea_shift"]["id"], bea["id"], 0, 0)

    return {
        "location": location,
        "role_server": role_server,
        "role_busser": role_busser,
        "ana": ana,
        "bea": bea,
        "policy": policy,
        "period": period,
        **shifts,
    }


def _create_pool(api, location_id: str):
    return api.create_shift_tip_pool(
        create_shift_tip_pool_payload(location_id, business_date=BUSINESS_DATE), PREPARER
    )


# ---------------------------------------------------------------------------
# consistency_model / distribution_response_already_carries_every_cascaded_field
# ---------------------------------------------------------------------------
def test_the_creation_response_already_carries_the_debit_it_made_on_two_shifts(api):
    """The 201 body reports the contribution, and the shifts and the unit agree with it on
    the very next read, with no second write in between.

    PRD §2.8: "The system reconciles immediately and synchronously within the request that
    triggers the change: by the time a response is returned, every derived figure the change
    touches has been rewritten, and there is no eventual-consistency window."
    PRD §3.7: "A role carrying `pool_share_points` above 0 but a `pool_contribution_pct_bps`
    of 0 — the classic busser — is inside that input set and is stamped into the pool with a
    contribution of 0, because it must still be recognised as a participant when the pool is
    paid out."
    PRD §3.7: "Each contributing shift then has its `pool_contribution_cents` set to that
    contribution, its `shift_tip_pool_id` stamped with the new pool, and its
    `retained_tips_cents` reset to the tips it received less the contribution."
    PRD §3.7: "On the pool itself, `total_contributed_cents` becomes the sum of the
    contributions across the contributing shifts and `contributing_shift_count` becomes the
    number of those shifts whose contribution came out greater than 0 — a stamped-in busser
    with a contribution of 0 is therefore not counted there."
    PRD §3.7: "Creation also absorbs the date's `TIPS`-treated service charges into
    `service_charge_tips_cents` as described in §3.6, leaves `cc_fee_deducted_cents`,
    `distributed_cents`, `participant_count` and `total_share_weight` at 0 with
    `distributed_at` and `reversed_at` null, and recomputes the unit's `pending_pool_cents`
    — which the new pool now joins, since it is `CONTRIBUTED` and `PENDING`."

    Design: Corner/consistency_model/distribution_response_already_carries_every_cascaded_field
    """
    world = _pool_ready_world()

    pool = validate_success(
        _create_pool(api, world["location"]["id"]), expected_status=201
    )
    assert pool["total_contributed_cents"] == 600, "1500 bps of the 4000 Ana received"
    assert pool["contributing_shift_count"] == 1, "the busser contributed 0 and is not counted"
    assert pool["contribution_status"] == "CONTRIBUTED"
    assert pool["distribution_status"] == "PENDING"
    assert pool["service_charge_tips_cents"] == 0
    assert pool["cc_fee_deducted_cents"] == 0
    assert pool["distributed_cents"] == 0
    assert pool["participant_count"] == 0
    assert pool["total_share_weight"] == 0
    assert pool["distributed_at"] is None
    assert pool["reversed_at"] is None
    assert pool["tip_pool_policy_id"] == world["policy"]["id"]

    contributor = read_shift(world["ana_shift"]["id"])
    assert contributor["shift_tip_pool_id"] == pool["id"]
    assert contributor["pool_contribution_cents"] == 600
    assert contributor["retained_tips_cents"] == 3400

    stamped_in = read_shift(world["bea_shift"]["id"])
    assert stamped_in["shift_tip_pool_id"] == pool["id"], (
        "the busser is in the input set even though she funds nothing"
    )
    assert stamped_in["pool_contribution_cents"] == 0
    assert stamped_in["retained_tips_cents"] == 0

    assert read_location(world["location"]["id"])["pending_pool_cents"] == 600, (
        "the unit's balance already carries the new pool"
    )


def test_the_distribution_response_and_four_other_entities_need_no_settling_period(api):
    """Every figure the split produced is already in the 200 body, in the ledger, on both
    employees and on the unit, and a second identical read changes nothing.

    PRD §2.8: "The system reconciles immediately and synchronously within the request that
    triggers the change: by the time a response is returned, every derived figure the change
    touches has been rewritten, and there is no eventual-consistency window."
    PRD §3.7: "If the pinned policy's `cc_fee_pass_through` is false, or the unit's
    `cc_fee_policy` is `PROHIBITED`, then `cc_fee_deducted_cents` is 0 and the fee
    calculation stops there."
    PRD §3.7: "With the fee settled, `net_pool_cents` is `total_contributed_cents` plus
    `service_charge_tips_cents` less `cc_fee_deducted_cents`."
    PRD §3.7: "Under `POINTS_ONLY` it is simply the job role's `pool_share_points`."
    PRD §3.7: "Each participant's base share is `net_pool_cents` multiplied by that
    participant's `share_weight`, divided by `total_share_weight`, with any fraction
    discarded. The leftover is `net_pool_cents` less the sum of the base shares, and because
    every base share was floored the leftover is strictly smaller than `participant_count`.
    Exactly one extra cent goes to each of the first however-many participants the leftover
    permits, taken in descending order of `share_weight` and, where two participants tie on
    weight, in ascending order of their shifts' `created_at`."
    PRD §3.7: "Distribution appends exactly one pool-allocation ledger row per participant,
    each carrying its `shift_tip_pool_id`, the receiving `employee_id`, the earning
    `shift_id`, an `entry_type` of `DISTRIBUTION`, the participant's `share_weight`, its
    `allocated_cents` — the base share plus the leftover cent where won — its
    `remainder_cent_awarded` flag, and a copy of the pool's `business_date`, carried on the
    row so that allocations can be read and filtered without joining back to the pool."
    PRD §3.7: "`distributed_at` is stamped with the current logical instant,
    `distribution_status` moves `PENDING → DISTRIBUTED`, the unit's `pending_pool_cents` is
    recomputed with this pool now dropped from the pending sum, and each recipient's credit
    will raise that employee's `pool_tips_cents` at the next compute."
    PRD §3.2: "Hiring also sets `trailing_pool_receipts_cents` to 0; thereafter it is the
    running sum of `allocated_cents` over every pool-allocation ledger row naming this
    employee, counting both `DISTRIBUTION` rows and `REVERSAL` rows, so that a reversed pool
    leaves it back where it started."

    Design: Corner/consistency_model/distribution_response_already_carries_every_cascaded_field
    """
    world = _pool_ready_world()
    pool = validate_success(
        _create_pool(api, world["location"]["id"]), expected_status=201
    )

    settled = validate_success(api.distribute_shift_tip_pool(pool["id"], PREPARER))
    assert settled["cc_fee_deducted_cents"] == 0, "this policy does not pass the fee through"
    assert settled["net_pool_cents"] == 600
    assert settled["participant_count"] == 2, "the server and the busser both receive"
    assert settled["total_share_weight"] == 14, "10 points plus 4 points under POINTS_ONLY"
    assert settled["distributed_cents"] == 600
    assert settled["distribution_status"] == "DISTRIBUTED"
    assert_instant_equals(settled["distributed_at"], CLOCK, "distributed_at")

    rows, meta = validate_paginated(
        api.list_pool_allocations(PREPARER, params={"shift_tip_pool_id": pool["id"]})
    )
    assert meta["total_count"] == 2, "the ledger is written inside the distributing request"
    by_employee = {row["employee_id"]: row for row in rows}
    for row in rows:
        assert_pool_allocation(row)
        assert row["shift_tip_pool_id"] == pool["id"]
        assert row["entry_type"] == "DISTRIBUTION"
        assert_instant_equals(row["business_date"], BUSINESS_DATE, "business_date")

    server_row = by_employee[world["ana"]["id"]]
    assert server_row["share_weight"] == 10
    assert server_row["allocated_cents"] == 429, "428 floored plus the single leftover cent"
    assert server_row["remainder_cent_awarded"] is True
    assert server_row["shift_id"] == world["ana_shift"]["id"]

    busser_row = by_employee[world["bea"]["id"]]
    assert busser_row["share_weight"] == 4
    assert busser_row["allocated_cents"] == 171
    assert busser_row["remainder_cent_awarded"] is False
    assert busser_row["shift_id"] == world["bea_shift"]["id"]
    assert_allocations_sum_to(rows, 600)

    assert read_employee(world["ana"]["id"], ADMIN)["trailing_pool_receipts_cents"] == 429
    assert read_employee(world["bea"]["id"], ADMIN)["trailing_pool_receipts_cents"] == 171
    assert read_location(world["location"]["id"])["pending_pool_cents"] == 0, (
        "the pool left the pending set in the same request that distributed it"
    )

    again = read_pool(pool["id"])
    assert again["distributed_cents"] == 600
    assert again["participant_count"] == 2
    assert again["total_share_weight"] == 14
    assert again["distribution_status"] == "DISTRIBUTED"
    assert read_employee(world["ana"]["id"], ADMIN)["trailing_pool_receipts_cents"] == 429
    assert read_location(world["location"]["id"])["pending_pool_cents"] == 0
    assert len(list_allocations_of(pool["id"])) == 2, "no field moves without a further write"
