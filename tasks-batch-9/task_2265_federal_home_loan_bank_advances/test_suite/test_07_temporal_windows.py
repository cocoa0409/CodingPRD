"""Two interval-conflict rules with opposite edge semantics: half-open field-work
windows per member, and closed custody windows per asset widened by two days."""
from test_helpers import *  # noqa: F401,F403


class TestReviewWindowOverlap:
    """Half-open windows: touching endpoints are adjacency, not intersection."""

    def _member_with_two_scheduled_windows(self, api):
        env = pledging_member(api)
        pledge_asset(api, env.member_id)
        first = schedule_review(
            api, env, window_start="2026-08-01T00:00:00Z", window_end="2026-08-20T00:00:00Z"
        )
        second = api.create_verification_review(
            verification_review_payload(
                env.member_id,
                window_start="2026-08-20T00:00:00Z",
                window_end="2026-08-30T00:00:00Z",
                sample_size=25,
            ),
            AUDITOR,
        )
        return env, first, second

    def _schedule(self, api, env, window_start, window_end, sample_size=30):
        return api.create_verification_review(
            verification_review_payload(
                env.member_id,
                window_start=window_start,
                window_end=window_end,
                sample_size=sample_size,
            ),
            AUDITOR,
        )

    def test_a_window_starting_where_another_ends_is_accepted(self, api):
        """PRD §3.8: "Adjacency is not intersection — a new window whose `window_start`
        equals an existing window's `window_end` is accepted."

        Design: Difficulty/resource_temporal_overlap/review_window_adjacent_allowed_overlap_rejected
        """
        _env, _first, second = self._member_with_two_scheduled_windows(api)

        review = validate_success(second, 201)

        assert_fields(review, status="SCHEDULED", sample_size=25)
        assert_same_instant(review["window_start"], "2026-08-20T00:00:00Z")
        assert_same_instant(review["window_end"], "2026-08-30T00:00:00Z")

    def test_an_intersecting_window_is_refused_and_creates_nothing(self, api):
        """PRD §3.8: "A member may not have two live reviews whose field-work windows
        overlap: taking every other review for that member whose `status` is not
        `CLOSED`, the requested half-open interval from `window_start` up to but
        excluding `window_end` must not intersect that review's interval; an
        intersection is rejected with `ERR_REVIEW_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/review_window_adjacent_allowed_overlap_rejected
        """
        env, _first, _second = self._member_with_two_scheduled_windows(api)

        response = self._schedule(
            api, env, "2026-08-19T00:00:00Z", "2026-08-25T00:00:00Z"
        )

        validate_error(response, "ERR_REVIEW_WINDOW_OVERLAP", 409)
        assert_total_count(
            api.list_verification_reviews(AUDITOR, {"member_bank_id": env.member_id}), 2
        )

    def test_the_adjacency_edge_holds_one_day_out_in_either_direction(self, api):
        """PRD §3.8: "Adjacency is not intersection — a new window whose `window_start`
        equals an existing window's `window_end` is accepted."

        Design: Difficulty/resource_temporal_overlap/review_window_adjacent_allowed_overlap_rejected
        """
        env, _first, _second = self._member_with_two_scheduled_windows(api)

        accepted = self._schedule(
            api, env, "2026-08-30T00:00:00Z", "2026-09-05T00:00:00Z"
        )
        refused = self._schedule(
            api, env, "2026-08-29T00:00:00Z", "2026-09-05T00:00:00Z"
        )

        validate_success(accepted, 201)
        validate_error(refused, "ERR_REVIEW_WINDOW_OVERLAP", 409)

    def test_a_closed_review_leaves_the_conflict_candidate_set(self, api):
        """PRD §3.8: "taking every other review for that member whose `status` is not
        `CLOSED`, the requested half-open interval from `window_start` up to but
        excluding `window_end` must not intersect that review's interval."

        Design: Difficulty/resource_temporal_overlap/review_window_adjacent_allowed_overlap_rejected
        """
        env, first, _second = self._member_with_two_scheduled_windows(api)
        validate_error(
            self._schedule(api, env, "2026-08-05T00:00:00Z", "2026-08-15T00:00:00Z"),
            "ERR_REVIEW_WINDOW_OVERLAP",
            409,
        )

        begin_field_work(api, first["id"])
        issue_findings(api, first["id"])
        assert close_review(api, first["id"])["status"] == "CLOSED"

        validate_success(
            self._schedule(api, env, "2026-08-05T00:00:00Z", "2026-08-15T00:00:00Z"),
            201,
        )


class TestCustodyWindowBuffer:
    """Closed windows widened two days at each end: touching endpoints conflict."""

    def _asset_with_two_booked_windows(self, api):
        env = member_with_eligible_sf(api)
        first = book_receipt(
            api,
            env.assets["sf"]["id"],
            delivery_date="2026-08-10T00:00:00Z",
            return_date="2026-08-20T00:00:00Z",
        )
        second = api.create_safekeeping_receipt(
            env.assets["sf"]["id"],
            safekeeping_receipt_payload(
                delivery_date="2026-08-23T00:00:00Z",
                return_date="2026-08-28T00:00:00Z",
            ),
            CUSTODIAN,
        )
        return env, first, second

    def _book(self, api, asset_id, delivery_date, return_date):
        return api.create_safekeeping_receipt(
            asset_id,
            safekeeping_receipt_payload(
                delivery_date=delivery_date, return_date=return_date
            ),
            CUSTODIAN,
        )

    def test_a_three_day_gap_clears_the_two_day_buffer(self, api):
        """PRD §3.3: "the requested window conflicts if its `delivery_date` falls on or
        before that receipt's `return_date` extended forward by a two-day grace period
        **and** its `return_date` falls on or after that receipt's `delivery_date`
        pulled back by the same two days."

        Design: Difficulty/resource_temporal_overlap/custody_window_buffer_boundary_conflict_rejected
        """
        _env, first, second = self._asset_with_two_booked_windows(api)

        accepted = validate_success(second, 201)

        assert first["status"] == "PENDING_DELIVERY"
        assert_fields(accepted, status="PENDING_DELIVERY")
        assert_same_instant(accepted["delivery_date"], "2026-08-23T00:00:00Z")
        assert_same_instant(accepted["return_date"], "2026-08-28T00:00:00Z")

    def test_a_gap_of_exactly_two_days_still_conflicts(self, api):
        """PRD §3.3: "Because the buffer expands both endpoints, two windows separated
        by only one or two days still conflict."

        Design: Difficulty/resource_temporal_overlap/custody_window_buffer_boundary_conflict_rejected
        """
        env, _first, _second = self._asset_with_two_booked_windows(api)

        response = self._book(
            api, env.assets["sf"]["id"], "2026-08-22T00:00:00Z", "2026-08-26T00:00:00Z"
        )

        validate_error(response, "ERR_CUSTODY_WINDOW_CONFLICT", 409)
        assert_total_count(
            api.list_safekeeping_receipts(
                CUSTODIAN, {"collateral_asset_id": env.assets["sf"]["id"]}
            ),
            2,
        )

    def test_the_conflict_is_scoped_to_the_single_asset(self, api):
        """PRD §3.3: "And the same asset may not have two live custody windows crowding
        each other: taking every other receipt for that asset whose `status` is
        `PENDING_DELIVERY`, `RECEIVED` or `EXCEPTION`."

        Design: Difficulty/resource_temporal_overlap/custody_window_buffer_boundary_conflict_rejected
        """
        env, _first, _second = self._asset_with_two_booked_windows(api)
        other = add_heloc(api, env)

        response = self._book(
            api, other["id"], "2026-08-22T00:00:00Z", "2026-08-26T00:00:00Z"
        )

        validate_success(response, 201)

    def test_the_buffer_is_symmetric_and_touching_endpoints_conflict(self, api):
        """PRD §3.3: "The custody window is a closed interval: both endpoints belong to
        it, and `return_date` must be strictly later than `delivery_date`."

        Design: Difficulty/resource_temporal_overlap/custody_window_buffer_boundary_conflict_rejected
        """
        env, _first, _second = self._asset_with_two_booked_windows(api)
        asset_id = env.assets["sf"]["id"]

        validate_error(
            self._book(api, asset_id, "2026-08-01T00:00:00Z", "2026-08-08T00:00:00Z"),
            "ERR_CUSTODY_WINDOW_CONFLICT",
            409,
        )
        validate_error(
            self._book(api, asset_id, "2026-08-20T00:00:00Z", "2026-08-21T00:00:00Z"),
            "ERR_CUSTODY_WINDOW_CONFLICT",
            409,
        )
        validate_success(
            self._book(api, asset_id, "2026-08-01T00:00:00Z", "2026-08-07T00:00:00Z"),
            201,
        )
