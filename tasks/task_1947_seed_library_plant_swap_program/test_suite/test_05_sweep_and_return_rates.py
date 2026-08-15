"""Daily sweep boundary semantics, suspension threshold, and the two
member return-rate variants."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId,
    api_client,
    borrow_packet,
    borrow_return_verify,
    create_member,
    create_site,
    get_member,
    run_sweep,
    set_clock,
    setup_active_lot,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
    write_off_overdue_checkout,
)

ADMIN = TEST_USERS["admin_headers"]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestReturnRateVariants:
    def _setup_two_terminal_checkouts(self):
        """Member with 1 VERIFIED (due 2026-01-22) and 1 WRITTEN_OFF
        (due 2025-10-24); final clock 2026-04-22 gives due-ages 90d and 180d.
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_active_lot(
            seeds_received=1000,
            provisional_viability_pct=90.00,
            num_packets=2,
            seeds_per_packet=20,
            label_stock=100,
        )
        member = create_member(ctx["site"]["id"])
        # C1: created 2026-01-01 (due 2026-01-22); returned + verified.
        borrow_return_verify(member, ctx["packet_ids"][0])
        # C2: created 2025-10-03 (due 2025-10-24); swept overdue, disputed,
        # written off.
        set_clock("2025-10-03T00:00:00Z")
        c2 = borrow_packet(member, ctx["packet_ids"][1])
        set_clock("2025-10-25T00:00:00Z")
        run_sweep()
        write_off_overdue_checkout(c2["id"], member["id"])
        # Final read instant: C1 due-age 90d, C2 due-age 180d.
        set_clock("2026-04-22T00:00:00Z")
        return member

    def test_simple_return_rate_is_flat_verified_share(self):
        """PRD §3.5: "First, the member's `simple_return_rate` is computed over
        terminal checkouts only — those in `VERIFIED` or `WRITTEN_OFF` — as the
        verified share of that terminal set, or 0.0 when the member has no
        terminal checkouts yet".
        PRD §3.5: "`STANDARD` otherwise, which covers every member with fewer
        than three terminal checkouts as unrated."

        1 VERIFIED + 1 WRITTEN_OFF -> simple_return_rate 0.5; with only 2
        terminals the member is unrated -> STANDARD.

        Design: Difficulty/dual_variant_calc/member_return_rate_simple_vs_decay_weighted
        """
        member = self._setup_two_terminal_checkouts()
        data = get_member(member["id"])
        assert data["simple_return_rate"] == 0.5, (
            f"Expected 1 verified / 2 terminal = 0.5, "
            f"got {data['simple_return_rate']}"
        )
        assert data["terminal_checkout_count"] == 2
        assert data["standing_tier"] == "STANDARD"

    def test_decay_weighted_score_diverges_from_simple_rate(self):
        """PRD §3.5: "Over the same terminal set, each checkout contributes an
        outcome of 1 for `VERIFIED` and 0 for `WRITTEN_OFF`, multiplied by a
        weight that decays with age: the elapsed time between the checkout's
        `due_at` and the current logical time, expressed in days by dividing
        its seconds by 86,400 and floored at zero for checkouts that closed
        before their due date, is divided by a ninety-day half-life, and the
        weight is one-half raised to that power. The score is the sum of
        weighted outcomes divided by the sum of weights — 0.0 when the terminal
        set is empty — held at four decimal places, rounded half up."

        History: 1 VERIFIED due 90 days ago (w = 0.5), 1 WRITTEN_OFF due 180
        days ago (w = 0.25): (0.5*1 + 0.25*0) / (0.5 + 0.25) = 0.6667 while
        the simple rate stays 0.5.

        Design: Difficulty/dual_variant_calc/member_return_rate_simple_vs_decay_weighted
        """
        member = self._setup_two_terminal_checkouts()
        data = get_member(member["id"])
        assert data["decay_weighted_return_score"] == 0.6667, (
            f"Expected (0.5*1 + 0.25*0)/(0.5+0.25) rounded half up to 4dp "
            f"= 0.6667, got {data['decay_weighted_return_score']}"
        )
        assert data["simple_return_rate"] == 0.5
        assert data["decay_weighted_return_score"] != data["simple_return_rate"]


class TestOverdueSweepBoundary:
    def test_due_exactly_now_stays_active_one_second_past_flips(self):
        """PRD §3.5: "Pass one walks every `ACTIVE` checkout ordered by
        `due_at` ascending with ties broken by `created_at` ascending, and
        flips each one whose `due_at` is strictly before the current logical
        time to `OVERDUE` — a checkout due exactly now stays `ACTIVE`".
        PRD §3.5: "A created checkout starts `ACTIVE` with `checked_out_at`
        stamped from the logical clock and `due_at` exactly twenty-one days
        later."
        PRD §2.5: "At startup, before any explicit set call, the logical clock
        reads exactly `2026-08-01T00:00:00Z`."

        Design: Corner/calculations/calc_overdue_sweep_boundary_strict_inequality
        """
        ctx = setup_active_lot(num_packets=2, seeds_per_packet=10)
        member1 = create_member(ctx["site"]["id"])
        member2 = create_member(ctx["site"]["id"])
        c1 = borrow_packet(member1, ctx["packet_ids"][0])
        borrow_packet(member2, ctx["packet_ids"][1])
        assert _parse(c1["due_at"]) == datetime(2026, 8, 22, tzinfo=timezone.utc), (
            f"default clock 2026-08-01 + 21 days, got {c1['due_at']}"
        )
        # due_at == now: strict less-than means no flip.
        set_clock("2026-08-22T00:00:00Z")
        report = run_sweep()
        assert report["overdue_flipped_count"] == 0, (
            "a checkout due exactly now stays ACTIVE"
        )
        # One second past due: both flip.
        set_clock("2026-08-22T00:00:01Z")
        report = run_sweep()
        assert report["overdue_flipped_count"] == 2
        after = validate_success(api_client.get_checkout(c1["id"], ADMIN), 200)
        assert after["status"] == "OVERDUE"


class TestSuspensionThreshold:
    def test_exactly_three_overdue_suspends_two_does_not(self):
        """PRD §3.5: "Pass two walks every `ACTIVE` member in `created_at`
        ascending order and suspends each whose overdue count has reached
        three: exactly three overdue checkouts suspends, two does not."
        PRD §3.5: "it reports `overdue_flipped_count`,
        `members_suspended_count`, and a `members_reinstated_count` that is
        always zero."

        Design: Corner/cross_cutting_layers/layer_ops_run_checkpoint_suspension_threshold
        """
        ctx = setup_active_lot(num_packets=5, seeds_per_packet=10)
        member3 = create_member(ctx["site"]["id"])
        member2 = create_member(ctx["site"]["id"])
        for pid in ctx["packet_ids"][:3]:
            borrow_packet(member3, pid)
        for pid in ctx["packet_ids"][3:5]:
            borrow_packet(member2, pid)
        set_clock("2026-09-01T00:00:00Z")
        report = run_sweep()
        assert report["overdue_flipped_count"] == 5
        assert report["members_suspended_count"] == 1
        assert report["members_reinstated_count"] == 0
        assert get_member(member3["id"])["status"] == "SUSPENDED", (
            "3 >= 3 suspends"
        )
        assert get_member(member2["id"])["status"] == "ACTIVE", (
            "2 < 3 stays ACTIVE"
        )


class TestCheckoutListFiltering:
    def test_checkout_list_filters_by_member(self):
        """PRD §3.5: "The checkout list is filterable by `member_id`,
        `packet_id`, and `status`."

        Design: Corner/endpoints/ep_filtered_list_checkouts_by_member
        """
        ctx = setup_active_lot(num_packets=2, seeds_per_packet=10)
        member1 = create_member(ctx["site"]["id"])
        member2 = create_member(ctx["site"]["id"])
        borrow_packet(member1, ctx["packet_ids"][0])
        borrow_packet(member2, ctx["packet_ids"][1])
        resp = api_client.list_checkouts(ADMIN, params={"member_id": member1["id"]})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["member_id"] == member1["id"]


class TestMemberRequiredFields:
    def test_missing_email_rejected(self):
        """PRD §3.1: "Members are registered with a unique `email`, a
        `full_name`, and a `home_site_id` pointing at their home branch".
        PRD §2.9: "Request-body shape: required fields present, types correct,
        enum values within their declared sets, and numeric ranges respected —
        ... Malformed bodies draw `ERR_INVALID_REQUEST` (HTTP 400)".

        Design: Corner/entities/entity_member_missing_required_email_returns_invalid_request
        """
        site = create_site()
        resp = api_client.create_member(
            {"full_name": "No Email", "home_site_id": site["id"]}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
