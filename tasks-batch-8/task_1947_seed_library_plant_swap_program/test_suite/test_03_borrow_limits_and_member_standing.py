"""Borrow-limit derivation, tier boundaries, member defaults, and checkout
creation effects on member counters."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    api_client,
    borrow_packet,
    create_member,
    create_site,
    get_member,
    get_success_data,
    make_member_headers,
    make_volunteer_headers,
    setup_active_lot,
    setup_member_with_terminal_history,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestBorrowLimitDerivationOrder:
    def test_live_checkouts_never_enter_the_rate(self):
        """PRD §3.5: "First, the member's `simple_return_rate` is computed over
        terminal checkouts only — those in `VERIFIED` or `WRITTEN_OFF` — as the
        verified share of that terminal set, or 0.0 when the member has no
        terminal checkouts yet; `ACTIVE`, `OVERDUE`, `RETURNED`, and `DISPUTED`
        checkouts are excluded from both the numerator and the denominator."

        2 VERIFIED + 1 WRITTEN_OFF -> rate 0.6667 >= 0.60 -> STANDARD; five
        live checkouts do not demote the member.

        Design: Difficulty/combinatorial_formula/borrow_limit_derivation_order_mode_c
        """
        ctx = setup_member_with_terminal_history(verified=2, written_off=1)
        member = get_member(ctx["member"]["id"])
        assert member["terminal_checkout_count"] == 3
        assert member["simple_return_rate"] == 0.6667
        assert member["standing_tier"] == "STANDARD", (
            f"rate 0.6667 >= 0.60 with 3 terminals must stay STANDARD, "
            f"got {member['standing_tier']}"
        )
        assert member["effective_borrow_limit"] == 5
        # Five live checkouts (the in-flight attempt never participates either).
        for pid in ctx["remaining_packet_ids"][:5]:
            borrow_packet(ctx["member"], pid)
        member = get_member(ctx["member"]["id"])
        assert member["active_checkout_count"] == 5
        assert member["standing_tier"] == "STANDARD"
        assert member["effective_borrow_limit"] == 5

    def test_sixth_borrow_rejected_at_standard_cap(self):
        """PRD §3.5: "Finally, the attempt is admitted only while the member's
        `active_checkout_count` is strictly below that limit — sitting exactly
        at the limit is a rejection."
        PRD §3.5: "The member's borrow limit must admit one more checkout, else
        `ERR_BORROW_LIMIT_EXCEEDED`."

        STANDARD member (limit 5) holding 5 live checkouts is refused the 6th.

        Design: Difficulty/combinatorial_formula/borrow_limit_derivation_order_mode_c
        """
        ctx = setup_member_with_terminal_history(verified=2, written_off=1)
        for pid in ctx["remaining_packet_ids"][:4]:
            borrow_packet(ctx["member"], pid)
        fifth = borrow_packet(ctx["member"], ctx["remaining_packet_ids"][4])
        assert fifth["status"] == "ACTIVE"
        # Pack one more packet so the 6th attempt has an AVAILABLE target.
        extra = get_success_data(
            api_client.pack_seed_lot(
                ctx["lot"]["id"],
                {"packet_count": 1, "seeds_per_packet": 20},
                make_volunteer_headers(ctx["volunteer"]["id"]),
            ),
            201,
        )
        sixth_packet = extra["packet_ids"][0]
        resp = api_client.create_checkout(
            {"member_id": ctx["member"]["id"], "packet_id": sixth_packet},
            make_member_headers(ctx["member"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BORROW_LIMIT_EXCEEDED)


class TestBorrowLimitAtExactCap:
    def test_fifth_borrow_admitted(self):
        """PRD §3.5: "Finally, the attempt is admitted only while the member's
        `active_checkout_count` is strictly below that limit — sitting exactly
        at the limit is a rejection."

        Fresh member (STANDARD, limit 5): the 5th borrow moves the count
        4 -> 5 and is admitted.

        Design: Difficulty/boundary_precision_check/borrow_limit_at_exact_cap
        """
        ctx = setup_active_lot(num_packets=5, seeds_per_packet=20)
        member = create_member(ctx["site"]["id"])
        for pid in ctx["packet_ids"][:4]:
            borrow_packet(member, pid)
        fifth = borrow_packet(member, ctx["packet_ids"][4])
        assert fifth["status"] == "ACTIVE", (
            "5th borrow admitted: count 4 < limit 5 before the attempt"
        )
        assert get_member(member["id"])["active_checkout_count"] == 5

    def test_sixth_borrow_rejected_when_at_limit(self):
        """PRD §3.5: "The member's borrow limit must admit one more checkout,
        else `ERR_BORROW_LIMIT_EXCEEDED`."
        PRD §3.5: "Finally, the attempt is admitted only while the member's
        `active_checkout_count` is strictly below that limit — sitting exactly
        at the limit is a rejection."

        Design: Difficulty/boundary_precision_check/borrow_limit_at_exact_cap
        """
        ctx = setup_active_lot(num_packets=6, seeds_per_packet=20)
        member = create_member(ctx["site"]["id"])
        for pid in ctx["packet_ids"][:5]:
            borrow_packet(member, pid)
        resp = api_client.create_checkout(
            {"member_id": member["id"], "packet_id": ctx["packet_ids"][5]},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BORROW_LIMIT_EXCEEDED)


class TestProbationTierBoundary:
    def test_rate_below_0_60_with_three_terminals_is_probation_limit_2(self):
        """PRD §3.5: "Second, the `standing_tier` is derived: `TRUSTED` when
        the member has at least five terminal checkouts and a rate of at least
        0.90; `PROBATION` when the member has at least three terminal checkouts
        and a rate below 0.60; `STANDARD` otherwise, which covers every member
        with fewer than three terminal checkouts as unrated. Third, the tier
        maps to the `effective_borrow_limit`: 2 for `PROBATION`, 5 for
        `STANDARD`, 8 for `TRUSTED`."

        1 VERIFIED + 2 WRITTEN_OFF -> rate 0.3333 < 0.60 -> PROBATION, limit 2:
        two concurrent borrows admitted, the third rejected.

        Design: Corner/calculations/calc_tier_probation_boundary_0_60
        """
        ctx = setup_member_with_terminal_history(verified=1, written_off=2)
        member = get_member(ctx["member"]["id"])
        assert member["simple_return_rate"] == 0.3333, (
            f"Expected 1/3 rounded half up to 4dp = 0.3333, "
            f"got {member['simple_return_rate']}"
        )
        assert member["standing_tier"] == "PROBATION"
        assert member["effective_borrow_limit"] == 2
        remaining = ctx["remaining_packet_ids"]
        borrow_packet(ctx["member"], remaining[0])
        borrow_packet(ctx["member"], remaining[1])
        resp = api_client.create_checkout(
            {"member_id": ctx["member"]["id"], "packet_id": remaining[2]},
            make_member_headers(ctx["member"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BORROW_LIMIT_EXCEEDED)


class TestMemberCreationDefaults:
    def test_fresh_member_defaults(self):
        """PRD §3.1: "A fresh member starts `ACTIVE` with every counter at
        zero: `active_checkout_count`, `overdue_checkout_count`,
        `terminal_checkout_count`, `verified_return_count`, and all four credit
        totals; `simple_return_rate` and `decay_weighted_return_score` begin at
        0.0; `standing_tier` begins `STANDARD`, which yields an
        `effective_borrow_limit` of 5."

        Design: Corner/entities/entity_member_creation_defaults_applied
        """
        site = create_site()
        resp = api_client.create_member(
            {
                "email": "fresh@example.com",
                "full_name": "Fresh Member",
                "home_site_id": site["id"],
            },
            ADMIN,
        )
        member = validate_success(resp, 201)
        assert member["status"] == "ACTIVE"
        assert member["standing_tier"] == "STANDARD"
        assert member["effective_borrow_limit"] == 5
        assert member["active_checkout_count"] == 0
        assert member["overdue_checkout_count"] == 0
        assert member["terminal_checkout_count"] == 0
        assert member["verified_return_count"] == 0
        assert member["simple_return_rate"] == 0.0
        assert member["decay_weighted_return_score"] == 0.0
        assert member["credits_earned_total"] == 0
        assert member["credits_redeemed_total"] == 0
        assert member["credits_expired_total"] == 0
        assert member["credits_revoked_total"] == 0
        assert member["credits_balance"] == 0


class TestActiveCountReconciliation:
    def test_active_count_tracks_checkout_lifecycle(self):
        """PRD §3.5: "The `active_checkout_count` itself counts the member's
        non-terminal checkouts, meaning those in `ACTIVE`, `OVERDUE`,
        `RETURNED`, or `DISPUTED`."
        PRD §3.5: "A created checkout starts `ACTIVE` with `checked_out_at`
        stamped from the logical clock and `due_at` exactly twenty-one days
        later. The packet moves `AVAILABLE` → `CHECKED_OUT`, the member's
        `active_checkout_count` rises by one, and both the member's and the
        packet's `version` advance."

        0 -> 1 on create, still 1 while RETURNED (non-terminal), 0 once
        VERIFIED (terminal).

        Design: Corner/cross_cutting_layers/layer_derived_field_member_active_count_reconciled
        """
        ctx = setup_active_lot(num_packets=1, seeds_per_packet=10)
        member = create_member(ctx["site"]["id"])
        checkout = borrow_packet(member, ctx["packet_ids"][0])
        assert get_member(member["id"])["active_checkout_count"] == 1
        resp = api_client.return_checkout(
            checkout["id"], make_member_headers(member["id"])
        )
        validate_success(resp, 200)
        assert get_member(member["id"])["active_checkout_count"] == 1, (
            "RETURNED is still non-terminal and remains counted"
        )
        resp = api_client.verify_return(checkout["id"], ADMIN)
        validate_success(resp, 200)
        assert get_member(member["id"])["active_checkout_count"] == 0, (
            "VERIFIED is terminal and drops out of the active count"
        )


class TestCheckoutCreationImmediateEffects:
    def test_checkout_response_carries_status_and_due_date(self):
        """PRD §3.5: "A created checkout starts `ACTIVE` with `checked_out_at`
        stamped from the logical clock and `due_at` exactly twenty-one days
        later. The packet moves `AVAILABLE` → `CHECKED_OUT`, the member's
        `active_checkout_count` rises by one, and both the member's and the
        packet's `version` advance."
        PRD §2.5: "At startup, before any explicit set call, the logical clock
        reads exactly `2026-08-01T00:00:00Z`."

        Created at the startup default 2026-08-01T00:00:00Z -> due
        2026-08-22T00:00:00Z; the packet side effect is visible immediately.

        Design: Corner/cross_cutting_layers/layer_immediate_consistency_checkout_response
        """
        ctx = setup_active_lot(num_packets=1, seeds_per_packet=10)
        member = create_member(ctx["site"]["id"])
        checkout = borrow_packet(member, ctx["packet_ids"][0])
        assert checkout["status"] == "ACTIVE"

        def parse(ts: str) -> datetime:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))

        checked_out = parse(checkout["checked_out_at"])
        due = parse(checkout["due_at"])
        assert checked_out == datetime(2026, 8, 1, tzinfo=timezone.utc), (
            f"checked_out_at must be the startup default clock, "
            f"got {checkout['checked_out_at']}"
        )
        assert due == datetime(2026, 8, 22, tzinfo=timezone.utc), (
            f"due_at must be exactly twenty-one days later, "
            f"got {checkout['due_at']}"
        )
        packet = validate_success(
            api_client.get_seed_packet(ctx["packet_ids"][0], ADMIN), 200
        )
        assert packet["status"] == "CHECKED_OUT", (
            "packet side effect AVAILABLE -> CHECKED_OUT visible immediately"
        )
