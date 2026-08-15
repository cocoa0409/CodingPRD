"""Shortage-allocation claims: PRO_RATA vs RATCHET divergence, the
publish -> shortage -> rationed-reservation cascade, and pool membership."""
from test_helpers import (
    ALLOC,
    OPER,
    ApiErrorId,
    create_published_notice,
    create_published_schedule,
    get_lifting_right,
    get_terminal,
    reserve_ticket,
    setup_terminal_with_rights,
    validate_error,
    validate_success,
)


class TestProRataVsRatchetDiverge:
    def test_pro_rata_floor_plus_remainder(self, api):
        """PRD §3.4: "Under `PRO_RATA`, each right's initial share is the
        largest whole number of gallons not exceeding the pool multiplied by
        that right's `daily_ratable_gallons` and divided by the sum of
        `daily_ratable_gallons` across all participating rights. Because
        every share is rounded down, the distributed total may fall short of
        the pool, and the leftover gallons are dealt out one gallon at a time
        to rights in order of descending `daily_ratable_gallons`, ties broken
        by earlier `created_at`, until the remainder is gone."

        Pool 100 over ratables [100, 200, 300]: floors are 16/33/50 (total
        99), and the single remainder gallon goes to the largest ratable.

        Design: Difficulty/dual_variant_calc/ratable_allocation_pro_rata_vs_ratchet_diverge
        """
        env = setup_terminal_with_rights([100, 200, 300])
        notice = create_published_notice(
            env["terminal"]["id"], total_pool_gallons=100,
            allocation_method="PRO_RATA",
        )
        assert notice["status"] == "PUBLISHED"

        expected = [16, 33, 51]
        for right, want in zip(env["rights"], expected):
            got = get_lifting_right(right["id"])["allocated_gallons"]
            assert got == want, (
                f"PRO_RATA allocation for ratable "
                f"{right['daily_ratable_gallons']}: expected {want}, got {got}"
            )

    def test_ratchet_equal_share_then_surplus(self, api):
        """PRD §3.4: "Under `RATCHET`, the pool is first divided into an equal
        share — the largest whole number of gallons not exceeding the pool
        divided by the number of participating rights — and each right
        receives the lesser of its `daily_ratable_gallons` and that equal
        share. The surplus remaining after this first pass is then
        distributed one gallon at a time to rights still below their
        `daily_ratable_gallons`, again visiting rights in order of descending
        `daily_ratable_gallons` with ties broken by earlier `created_at`, and
        repeating until no surplus remains or every right has reached its
        full entitlement."

        Pool 450 over ratables [100, 200, 300]: equal share 150 caps LR1 at
        100; the 50-gallon surplus alternates down the descending-ratable
        order, leaving LR2 and LR3 at 175 each. The superseded PRO_RATA
        notice leaves no trace in the final allocations.

        Design: Difficulty/dual_variant_calc/ratable_allocation_pro_rata_vs_ratchet_diverge
        """
        env = setup_terminal_with_rights([100, 200, 300])
        first = create_published_notice(
            env["terminal"]["id"], total_pool_gallons=100,
            allocation_method="PRO_RATA",
        )
        second = create_published_notice(
            env["terminal"]["id"], total_pool_gallons=450,
            allocation_method="RATCHET",
        )

        notices = {
            n["id"]: n["status"]
            for n in [
                validate_success(api.get_allocation_notice(first["id"], ALLOC)),
                validate_success(api.get_allocation_notice(second["id"], ALLOC)),
            ]
        }
        assert notices[first["id"]] == "SUPERSEDED"
        assert notices[second["id"]] == "PUBLISHED"

        expected = [100, 175, 175]
        for right, want in zip(env["rights"], expected):
            got = get_lifting_right(right["id"])["allocated_gallons"]
            assert got == want, (
                f"RATCHET allocation for ratable "
                f"{right['daily_ratable_gallons']}: expected {want}, got {got}"
            )


class TestPublishThreeHopCascade:
    def test_publish_flips_terminal_to_shortage_and_recomputes(self, api):
        """PRD §3.4: "The terminal's posture is re-evaluated: if the pool is
        smaller than the combined `daily_ratable_gallons` of the `ACTIVE`
        rights at that terminal, the terminal moves `OPEN` → `SHORTAGE`; if
        the pool meets or exceeds that combined entitlement, a `SHORTAGE`
        terminal returns to `OPEN`."
        PRD §3.4: "once a shortage notice publishes, `allocated_gallons`
        carries the output of the allocation math below."

        Design: Difficulty/transitive_cascade/allocation_publish_three_hop_cascade
        """
        env = setup_terminal_with_rights([100, 300])
        assert env["terminal"]["rack_status"] == "OPEN"

        create_published_notice(
            env["terminal"]["id"], total_pool_gallons=200,
            allocation_method="PRO_RATA",
        )

        terminal = get_terminal(env["terminal"]["id"])
        assert terminal["rack_status"] == "SHORTAGE", (
            f"pool 200 < combined ratable 400 must move terminal to "
            f"SHORTAGE, got {terminal['rack_status']}"
        )
        assert terminal["daily_allocation_pool_gallons"] == 200

        lr1 = get_lifting_right(env["rights"][0]["id"])
        lr2 = get_lifting_right(env["rights"][1]["id"])
        assert lr1["allocated_gallons"] == 50
        assert lr2["allocated_gallons"] == 150

    def test_shortage_caps_reservation_at_allocated_share(self, api):
        """PRD §3.6: "Second, the requested gallons must fit the right's
        remaining entitlement: under `OPEN` that remainder is
        `daily_ratable_gallons` minus `lifted_today_gallons` minus
        `reserved_gallons`, and when the terminal is in `SHORTAGE` with a
        notice published for the current date, the right's
        `allocated_gallons` takes the place of `daily_ratable_gallons` in
        that computation — an overrun is `ERR_ALLOCATION_EXCEEDED`
        (HTTP 422)."

        Design: Difficulty/transitive_cascade/allocation_publish_three_hop_cascade
        """
        env = setup_terminal_with_rights([100, 300])
        create_published_notice(
            env["terminal"]["id"], total_pool_gallons=200,
            allocation_method="PRO_RATA",
        )
        # A published price keeps the provisional-gross step of an accepted
        # reservation well-defined.
        create_published_schedule(
            env["terminal"]["id"], env["product"]["id"],
            posted_rack_cents_per_gal=280,
        )

        lr1 = env["rights"][0]
        over = api.create_lifting_ticket(
            {
                "lifting_right_id": lr1["id"],
                "requested_gallons": 51,
                "branded": False,
            },
            OPER,
        )
        validate_error(over, ApiErrorId.ERR_ALLOCATION_EXCEEDED, 422)

        # Exactly the allocated share still fits.
        ticket = reserve_ticket(lr1["id"], 50)
        assert ticket["status"] == "RESERVED"
        right_after = get_lifting_right(lr1["id"])
        assert right_after["reserved_gallons"] == 50


def test_suspended_rights_excluded_from_pool(api):
    """PRD §3.4: "Only rights `ACTIVE` on the notice's effective date
    participate in the pool; `SUSPENDED` and `EXPIRED` rights are excluded
    entirely."

    Pool 300 over ACTIVE ratables [100, 200] (a third right with ratable 300
    is SUSPENDED before publish): exact shares 100 and 200 with no remainder.

    Design: Corner/calculations/ratable_allocation_excludes_suspended_rights
    """
    env = setup_terminal_with_rights([100, 200, 300])
    suspended = env["rights"][2]
    validate_success(api.suspend_lifting_right(suspended["id"], ALLOC))

    create_published_notice(
        env["terminal"]["id"], total_pool_gallons=300,
        allocation_method="PRO_RATA",
    )

    lr1 = get_lifting_right(env["rights"][0]["id"])
    lr2 = get_lifting_right(env["rights"][1]["id"])
    assert lr1["allocated_gallons"] == 100, (
        f"suspended right must not dilute the pool: expected 100, got "
        f"{lr1['allocated_gallons']}"
    )
    assert lr2["allocated_gallons"] == 200
    assert get_lifting_right(suspended["id"])["status"] == "SUSPENDED"
