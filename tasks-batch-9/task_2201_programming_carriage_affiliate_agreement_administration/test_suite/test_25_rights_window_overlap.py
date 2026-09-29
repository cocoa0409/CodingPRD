"""Contended intervals on two resources with opposite conventions.

Licensing windows occupy a half-open interval with no separation buffer, so
back-to-back adjacency is legal and the smallest violation is a single second of
true intersection. Blackout rules occupy a closed interval expanded by a 24-hour
buffer, so a gap of exactly one day is refused. The third concern replaces
pairwise exclusion with a counted ceiling of simultaneous non-exclusive
licensees, and shows a blocked licensee's slot being recycled.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    block_window,
    clear_window,
    fetch_title,
    fetch_window,
    plan_window,
    register_cleared_title,
    schedule_blackout,
    setup_executed_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)

RIGHTS = TEST_USERS["rights_administrator_headers"]

# A title whose linear premiere anchors every holdback below.
PREMIERE = "2026-08-15T00:00:00Z"

SMALL_OPERATOR = {"total_subscribers": 1_000_000, "credit_limit_cents": 100_000_000}
FLAT_TERMS = {
    "term_start_date": "2025-01-01T00:00:00Z",
    "term_end_date": "2027-12-31T00:00:00Z",
    "base_license_fee_cents_per_sub": 40.0000,
    "escalator_pct": 0.00,
    "penetration_floor_pct": 0.50,
    "committed_tier": "BASIC",
}


def _plan_streaming_window(agreement_id, title_id, window_start, window_end):
    return plan_window(
        agreement_id,
        title_id,
        platform="STREAMING",
        territory_code="US",
        window_start=window_start,
        window_end=window_end,
        exclusivity="EXCLUSIVE",
    )


def _setup_streaming_key():
    """Executed agreement plus an OWNED_CLEARED title premiering 2026-08-15, so
    every September STREAMING window below clears the 7-day holdback and lies
    wholly inside the term. Returns (agreement, title)."""
    _distributor, agreement = setup_executed_agreement()
    title = register_cleared_title(linear_premiere_at=PREMIERE)
    return agreement, title


def _setup_nonexclusive_vod_key(licensee_count):
    """`licensee_count` separate operators, each with an executed agreement and
    an identical PLANNED NON_EXCLUSIVE VOD/US window over October 2026 on one
    shared title. Returns (title, [windows])."""
    title = register_cleared_title(linear_premiere_at=PREMIERE)
    windows = []
    for _ in range(licensee_count):
        _distributor, agreement = setup_executed_agreement(SMALL_OPERATOR, FLAT_TERMS)
        windows.append(
            plan_window(
                agreement["id"],
                title["id"],
                platform="VOD",
                territory_code="US",
                window_start="2026-10-01T00:00:00Z",
                window_end="2026-10-31T00:00:00Z",
                exclusivity="NON_EXCLUSIVE",
            )
        )
    return title, windows


# ---------------------------------------------------------------------------
# Half-open licensing windows: adjacency legal, one second of overlap fatal
# ---------------------------------------------------------------------------
class TestLicensingWindowHalfOpenInterval:
    def test_abutting_exclusive_windows_both_clear(self, api):
        """PRD §2.10: "Two windows overlap only when each one's start is strictly
        before the other's end, which means adjacency is legal: a window ending at
        exactly the instant another begins does not conflict, and there is no
        separation buffer on this resource at all."
        PRD §3.6: "Occupancy is computed over the neighbours that share the
        window's `content_title_id`, `platform` and `territory_code`, excluding
        the window itself, whose `status` is `CLEARED` or `ACTIVE`, and whose
        interval overlaps this one under the half-open rule of §2.10 — each side's
        start strictly before the other side's end."
        PRD §3.6: "Either way, a window that clears successfully has
        `concurrent_licensee_count` stamped with the number of neighbours found —
        not including itself."
        PRD §3.6: "Its `windowing_holdback_days` is stamped immediately, as the
        whole number of days from the title's `linear_premiere_at` to the window's
        `window_start`, discarding any fraction; a window that opens before the
        linear premiere therefore carries a negative holdback."

        Design: Difficulty/resource_temporal_overlap/rights_window_adjacency_legal_but_one_second_overlap_rejected
        """
        agreement, title = _setup_streaming_key()
        first = _plan_streaming_window(
            agreement["id"], title["id"], "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z"
        )
        second = _plan_streaming_window(
            agreement["id"], title["id"], "2026-09-08T00:00:00Z", "2026-09-15T00:00:00Z"
        )

        first_cleared = validate_success(
            api.rights_window_lifecycle(first["id"], {"action": "CLEAR"}, RIGHTS), 200
        )
        assert first_cleared["status"] == "CLEARED", (
            f"the first window clears an empty key, got {first_cleared['status']!r}"
        )
        assert first_cleared["concurrent_licensee_count"] == 0, (
            f"no neighbours exist yet, got {first_cleared['concurrent_licensee_count']}"
        )

        second_cleared = validate_success(
            api.rights_window_lifecycle(second["id"], {"action": "CLEAR"}, RIGHTS), 200
        )
        assert second_cleared["status"] == "CLEARED", (
            "a window starting exactly where its neighbour ends does not conflict, "
            f"got {second_cleared['status']!r}"
        )
        assert second_cleared["concurrent_licensee_count"] == 0, (
            "adjacency at 2026-09-08T00:00:00Z is not an overlap, expected 0 "
            f"neighbours, got {second_cleared['concurrent_licensee_count']}"
        )
        assert second_cleared["windowing_holdback_days"] == 24, (
            "2026-08-15 premiere to a 2026-09-08 start is 24 whole days, got "
            f"{second_cleared['windowing_holdback_days']}"
        )

        after_title = fetch_title(title["id"])
        assert after_title["cleared_window_count"] == 2, (
            "both abutting windows occupy the key, expected 2, got "
            f"{after_title['cleared_window_count']}"
        )

    def test_one_second_overlap_of_exclusive_window_rejected(self, api):
        """PRD §2.10: "Two windows overlap only when each one's start is strictly
        before the other's end, which means adjacency is legal: a window ending at
        exactly the instant another begins does not conflict, and there is no
        separation buffer on this resource at all."
        PRD §3.6: "An `EXCLUSIVE` grant tolerates no overlap whatsoever, of any
        exclusivity. If even one neighbour exists, the clearance is refused with
        `ERR_WINDOW_EXCLUSIVITY_CONFLICT`."
        PRD §3.6: "The new window opens in `PLANNED` with `block_reason` of
        `NONE`, `concurrent_licensee_count` of 0 and `version` 1."

        Design: Difficulty/resource_temporal_overlap/rights_window_adjacency_legal_but_one_second_overlap_rejected
        """
        agreement, title = _setup_streaming_key()
        first = _plan_streaming_window(
            agreement["id"], title["id"], "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z"
        )
        second = _plan_streaming_window(
            agreement["id"], title["id"], "2026-09-08T00:00:00Z", "2026-09-15T00:00:00Z"
        )
        clear_window(first["id"])
        clear_window(second["id"])

        # One second of true intersection with the first window: its start lies
        # strictly before that window's end, and vice versa.
        overlapping = _plan_streaming_window(
            agreement["id"], title["id"], "2026-09-07T23:59:59Z", "2026-09-08T00:00:00Z"
        )
        response = api.rights_window_lifecycle(
            overlapping["id"], {"action": "CLEAR"}, RIGHTS
        )
        validate_error(response, "ERR_WINDOW_EXCLUSIVITY_CONFLICT", 409)

        after_window = fetch_window(overlapping["id"])
        assert after_window["status"] == "PLANNED", (
            f"the refused clearance leaves the window PLANNED, got {after_window['status']!r}"
        )
        assert after_window["concurrent_licensee_count"] == 0, (
            "a refused clearance stamps no neighbour count, got "
            f"{after_window['concurrent_licensee_count']}"
        )
        assert after_window["windowing_holdback_days"] == 23, (
            "2026-08-15 premiere to a 2026-09-07T23:59:59 start floors to 23 whole "
            f"days, got {after_window['windowing_holdback_days']}"
        )

        after_title = fetch_title(title["id"])
        assert after_title["cleared_window_count"] == 2, (
            "only the two abutting windows occupy the key, expected 2, got "
            f"{after_title['cleared_window_count']}"
        )


# ---------------------------------------------------------------------------
# Closed blackout intervals with a mandatory 24-hour buffer
# ---------------------------------------------------------------------------
class TestBlackoutSeparationBuffer:
    def test_blackout_exactly_twenty_four_hours_after_the_previous_end_rejected(self, api):
        """PRD §2.10: "A **blackout** occupies the closed interval from
        `blackout_start` through `blackout_end`, both ends inclusive, and it
        additionally carries a mandatory separation buffer of 24 hours on each
        side."
        PRD §2.10: "Two blackouts on the same key conflict when each one's start,
        pulled back by the buffer, is at or before the other's end — so adjacency
        is illegal here, and a gap of zero hours, or even of 23 hours, is refused
        where the window resource would have accepted it."
        PRD §3.6: "The separation check comes first: applying the closed-interval
        convention and the 24-hour buffer of §2.10, a proposed rule that comes
        within a day of an existing rule on the same key — including touching it
        exactly — is refused with `ERR_BLACKOUT_SEPARATION_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/blackout_buffer_rejects_exactly_twenty_four_hour_gap
        """
        _distributor, agreement = setup_executed_agreement()
        first = schedule_blackout(
            agreement["id"],
            territory_code="US",
            blackout_start="2026-09-01T00:00:00Z",
            blackout_end="2026-09-01T04:00:00Z",
            substitution_required=False,
        )
        assert first["status"] == "SCHEDULED", (
            f"a new rule opens in SCHEDULED, got {first['status']!r}"
        )
        assert first["blackout_hours"] == pytest.approx(4.00, abs=0.01), (
            f"a four-hour blackout carries blackout_hours 4.00, got {first['blackout_hours']}"
        )
        assert first["monthly_blackout_hours"] == pytest.approx(4.00, abs=0.01), (
            "it is the only September rule on the key, so the month totals 4.00, got "
            f"{first['monthly_blackout_hours']}"
        )

        response = api.create_blackout_rule(
            {
                "agreement_id": agreement["id"],
                "territory_code": "US",
                "blackout_start": "2026-09-02T04:00:00Z",
                "blackout_end": "2026-09-02T08:00:00Z",
                "substitution_required": False,
            },
            RIGHTS,
        )
        validate_error(response, "ERR_BLACKOUT_SEPARATION_VIOLATION", 409)

        rows, meta = validate_paginated(
            api.list_blackout_rules(RIGHTS, params={"agreement_id": agreement["id"]})
        )
        assert meta["total_count"] == 1, (
            f"the refused rule must not be persisted, expected 1 row, got {meta['total_count']}"
        )
        assert len(rows) == 1, (
            f"the refused rule must not be persisted, expected 1 row, got {len(rows)}"
        )
        assert rows[0]["id"] == first["id"], "the surviving row is the original rule"
        assert rows[0]["monthly_blackout_hours"] == pytest.approx(4.00, abs=0.01), (
            "the month still totals only the original 4.00 hours, got "
            f"{rows[0]['monthly_blackout_hours']}"
        )

    def test_blackout_one_second_beyond_the_buffer_is_scheduled(self, api):
        """PRD §2.10: "Two blackouts on the same key conflict when each one's
        start, pulled back by the buffer, is at or before the other's end — so
        adjacency is illegal here, and a gap of zero hours, or even of 23 hours, is
        refused where the window resource would have accepted it."
        PRD §3.6: "The rule's own `blackout_hours` is the elapsed time from
        `blackout_start` to `blackout_end` expressed in hours and rounded half up
        to two decimal places."
        PRD §3.6: "`monthly_blackout_hours` is that figure plus the
        `blackout_hours` of every other qualifying rule on the same key whose
        `blackout_start` falls in the same UTC calendar month, and if the total
        exceeds 72 hours — three full days of blackout in one operator territory
        in one month — the rule is refused with
        `ERR_BLACKOUT_MONTHLY_CAP_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/blackout_buffer_rejects_exactly_twenty_four_hour_gap
        """
        _distributor, agreement = setup_executed_agreement()
        schedule_blackout(
            agreement["id"],
            territory_code="US",
            blackout_start="2026-09-01T00:00:00Z",
            blackout_end="2026-09-01T04:00:00Z",
            substitution_required=False,
        )
        refused = api.create_blackout_rule(
            {
                "agreement_id": agreement["id"],
                "territory_code": "US",
                "blackout_start": "2026-09-02T04:00:00Z",
                "blackout_end": "2026-09-02T08:00:00Z",
                "substitution_required": False,
            },
            RIGHTS,
        )
        validate_error(refused, "ERR_BLACKOUT_SEPARATION_VIOLATION", 409)

        response = api.create_blackout_rule(
            {
                "agreement_id": agreement["id"],
                "territory_code": "US",
                "blackout_start": "2026-09-02T04:00:01Z",
                "blackout_end": "2026-09-02T08:00:01Z",
                "substitution_required": False,
            },
            RIGHTS,
        )
        data = validate_success(response, 201)
        assert data["status"] == "SCHEDULED", (
            "one second beyond the buffer is admissible, got "
            f"{data['status']!r}"
        )
        assert data["blackout_hours"] == pytest.approx(4.00, abs=0.01), (
            f"the second rule also runs four hours, got {data['blackout_hours']}"
        )
        assert data["monthly_blackout_hours"] == pytest.approx(8.00, abs=0.01), (
            "two four-hour September rules on the same key total 8.00 hours, got "
            f"{data['monthly_blackout_hours']}"
        )

    def test_blackout_separation_key_includes_territory_code(self, api):
        """PRD §3.6: "Two aggregate checks run at scheduling time, and both are
        keyed on the *operator* rather than the agreement: rules are compared
        across every agreement of the operator resolved through the naming
        agreement's `distributor_id`, restricted to the same `territory_code` and
        to rules in `SCHEDULED` or `ENFORCED` status."
        PRD §3.6: "The separation check comes first: applying the closed-interval
        convention and the 24-hour buffer of §2.10, a proposed rule that comes
        within a day of an existing rule on the same key — including touching it
        exactly — is refused with `ERR_BLACKOUT_SEPARATION_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/blackout_buffer_rejects_exactly_twenty_four_hour_gap
        """
        _distributor, agreement = setup_executed_agreement()
        schedule_blackout(
            agreement["id"],
            territory_code="US",
            blackout_start="2026-09-01T00:00:00Z",
            blackout_end="2026-09-01T04:00:00Z",
            substitution_required=False,
        )
        interval = {
            "blackout_start": "2026-09-02T04:00:00Z",
            "blackout_end": "2026-09-02T08:00:00Z",
            "substitution_required": False,
        }
        refused = api.create_blackout_rule(
            {"agreement_id": agreement["id"], "territory_code": "US", **interval}, RIGHTS
        )
        validate_error(refused, "ERR_BLACKOUT_SEPARATION_VIOLATION", 409)

        response = api.create_blackout_rule(
            {"agreement_id": agreement["id"], "territory_code": "CA", **interval}, RIGHTS
        )
        data = validate_success(response, 201)
        assert data["status"] == "SCHEDULED", (
            "the identical interval on another territory is a different key, got "
            f"{data['status']!r}"
        )
        assert data["territory_code"] == "CA", (
            f"the new rule blacks out CA, got {data['territory_code']!r}"
        )
        assert data["monthly_blackout_hours"] == pytest.approx(4.00, abs=0.01), (
            "the CA key carries only its own four hours, got "
            f"{data['monthly_blackout_hours']}"
        )


# ---------------------------------------------------------------------------
# Counted ceiling of simultaneous non-exclusive licensees
# ---------------------------------------------------------------------------
class TestNonExclusiveCapacityCeiling:
    def test_three_nonexclusive_licensees_clear_with_incrementing_neighbour_counts(self, api):
        """PRD §3.6: "Otherwise the aggregate cap applies: counting this window
        together with its neighbours, at most three simultaneous non-exclusive
        licensees may hold the same title, platform and territory, and a fourth is
        refused with `ERR_WINDOW_CONCURRENCY_CAP_EXCEEDED`."
        PRD §3.6: "Either way, a window that clears successfully has
        `concurrent_licensee_count` stamped with the number of neighbours found —
        not including itself."
        PRD §3.6: "`distribution_coverage_status` is derived from the *set of
        distinct platforms* among exactly those windows, by a pinned ladder
        evaluated top to bottom and stopping at the first arm that matches: if the
        set is empty the status is `UNDISTRIBUTED`; otherwise if the set is
        exactly `LINEAR` and nothing else the status is `LINEAR_ONLY`; otherwise
        if the set holds two or more distinct platforms the status is
        `MULTIPLATFORM`; otherwise the set holds exactly one platform which is not
        `LINEAR`, and the status is `EXCLUSIVE_UNCLEARED`, meaning a downstream
        platform is cleared while the linear window that is supposed to precede it
        is not."

        Design: Difficulty/resource_temporal_overlap/nonexclusive_window_capacity_ceiling_and_slot_recycling
        """
        title, windows = _setup_nonexclusive_vod_key(3)
        for index, window in enumerate(windows):
            data = validate_success(
                api.rights_window_lifecycle(window["id"], {"action": "CLEAR"}, RIGHTS), 200
            )
            assert data["status"] == "CLEARED", (
                f"licensee {index + 1} of three clears, got {data['status']!r}"
            )
            assert data["concurrent_licensee_count"] == index, (
                f"licensee {index + 1} finds {index} neighbours, got "
                f"{data['concurrent_licensee_count']}"
            )

        after_title = fetch_title(title["id"])
        assert after_title["cleared_window_count"] == 3, (
            f"three windows occupy the key, got {after_title['cleared_window_count']}"
        )
        assert after_title["distribution_coverage_status"] == "EXCLUSIVE_UNCLEARED", (
            "all three occupants are VOD, so the platform set is a single "
            f"non-LINEAR platform, got {after_title['distribution_coverage_status']!r}"
        )

    def test_fourth_simultaneous_nonexclusive_licensee_rejected(self, api):
        """PRD §3.6: "Otherwise the aggregate cap applies: counting this window
        together with its neighbours, at most three simultaneous non-exclusive
        licensees may hold the same title, platform and territory, and a fourth is
        refused with `ERR_WINDOW_CONCURRENCY_CAP_EXCEEDED`."
        PRD §3.6: "The new window opens in `PLANNED` with `block_reason` of
        `NONE`, `concurrent_licensee_count` of 0 and `version` 1."

        Design: Difficulty/resource_temporal_overlap/nonexclusive_window_capacity_ceiling_and_slot_recycling
        """
        title, windows = _setup_nonexclusive_vod_key(4)
        for window in windows[:3]:
            clear_window(window["id"])
        fourth = windows[3]
        assert fourth["status"] == "PLANNED", (
            f"the fourth licensee is still only planned, got {fourth['status']!r}"
        )

        response = api.rights_window_lifecycle(fourth["id"], {"action": "CLEAR"}, RIGHTS)
        validate_error(response, "ERR_WINDOW_CONCURRENCY_CAP_EXCEEDED", 422)

        after_window = fetch_window(fourth["id"])
        assert after_window["status"] == "PLANNED", (
            f"the refused clearance leaves the window PLANNED, got {after_window['status']!r}"
        )
        assert after_window["concurrent_licensee_count"] == 0, (
            "a refused clearance stamps no neighbour count, got "
            f"{after_window['concurrent_licensee_count']}"
        )
        assert fetch_title(title["id"])["cleared_window_count"] == 3, (
            "the key still holds exactly its three admitted licensees"
        )

    def test_blocking_a_licensee_recycles_its_slot_for_the_fourth(self, api):
        """PRD §3.6: "Windows in `PLANNED`, `BLOCKED` or `EXPIRED` never occupy
        the resource, which is why a blocked window's slot is immediately reusable
        by someone else."
        PRD §3.6: "Whichever route fires, the title's `cleared_window_count`
        decrements by one and `distribution_coverage_status` is re-derived from the
        remaining window set."
        PRD §3.6: "Otherwise the aggregate cap applies: counting this window
        together with its neighbours, at most three simultaneous non-exclusive
        licensees may hold the same title, platform and territory, and a fourth is
        refused with `ERR_WINDOW_CONCURRENCY_CAP_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/nonexclusive_window_capacity_ceiling_and_slot_recycling
        """
        title, windows = _setup_nonexclusive_vod_key(4)
        for window in windows[:3]:
            clear_window(window["id"])
        fourth = windows[3]
        refused = api.rights_window_lifecycle(fourth["id"], {"action": "CLEAR"}, RIGHTS)
        validate_error(refused, "ERR_WINDOW_CONCURRENCY_CAP_EXCEEDED", 422)

        blocked = block_window(windows[1]["id"], "MANUAL_BLOCK")
        assert blocked["status"] == "BLOCKED", (
            f"the second licensee is blocked, got {blocked['status']!r}"
        )
        assert fetch_title(title["id"])["cleared_window_count"] == 2, (
            "blocking decrements the occupying count to 2"
        )

        response = api.rights_window_lifecycle(fourth["id"], {"action": "CLEAR"}, RIGHTS)
        data = validate_success(response, 200)
        assert data["status"] == "CLEARED", (
            f"the freed slot admits the fourth licensee, got {data['status']!r}"
        )
        assert data["concurrent_licensee_count"] == 2, (
            "only the two remaining CLEARED windows are neighbours, got "
            f"{data['concurrent_licensee_count']}"
        )
        assert fetch_title(title["id"])["cleared_window_count"] == 3, (
            "the key is back to three occupants"
        )
