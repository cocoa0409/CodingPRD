"""Half-open assignment intervals against closed pool incurral periods."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ERR_ASSIGNMENT_PERIOD_OVERLAP,
    ERR_POOL_PERIOD_OVERLAP,
    IPA_ADMIN_HEADERS,
    NETWORK_MANAGER_HEADERS,
    assert_fields,
    assign_enrollee,
    assignment_payload,
    create_active_agreement,
    create_active_physician,
    create_enrollee,
    create_pool,
    enrollee_version,
    read_agreement,
    read_assignment,
    read_physician,
    risk_pool_payload,
    set_clock,
    terminate_assignment,
)


def _member_whose_first_assignment_termed_on_the_first_of_july(api):
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(api, max_panel_size=5)
    physician = create_active_physician(api, agreement["id"])
    enrollee = create_enrollee(api, agreement["id"], external_member_id="HO-0001")
    first = assign_enrollee(
        api, enrollee["id"], physician["id"], effective_date="2026-01-01T00:00:00Z"
    )

    set_clock(api, "2026-07-01T00:00:00Z")
    termed = terminate_assignment(api, first["id"])
    return agreement, physician, enrollee, termed


def _create_assignment_at_the_first_of_july(api, enrollee_id, physician_id):
    return api.create_assignment(
        assignment_payload(
            enrollee_id,
            physician_id,
            enrollee_version(api, enrollee_id),
            effective_date="2026-07-01T00:00:00Z",
        ),
        NETWORK_MANAGER_HEADERS,
    )


class TestAssignmentHalfOpenAdjacency:
    def test_termination_stamps_the_term_date_at_the_clock_instant(self, api):
        """PRD §3.4: "Terminating an assignment outright is a `NetworkManager`
        action, permitted when `status` is `ACTIVE` and either the holding
        physician's `continuity_of_care_until` is null or the logical clock has
        reached it."

        Design: Difficulty/resource_temporal_overlap/assignment_half_open_adjacency_allowed_then_overlap_rejected
        """
        _agreement, _physician, _enrollee, termed = (
            _member_whose_first_assignment_termed_on_the_first_of_july(api)
        )
        assert_fields(
            termed, {"status": "TERMINATED", "term_date": "2026-07-01T00:00:00Z"}
        )

    def test_a_new_assignment_at_the_same_instant_is_adjacent_not_overlapping(self, api):
        """PRD §2.11: "Consequently an assignment terming exactly at
        `2026-07-01T00:00:00Z` and a new assignment for the same enrollee starting
        at that same instant are adjacent rather than overlapping, and both may
        exist without triggering an overlap rejection."

        Design: Difficulty/resource_temporal_overlap/assignment_half_open_adjacency_allowed_then_overlap_rejected
        """
        _agreement, physician, enrollee, _termed = (
            _member_whose_first_assignment_termed_on_the_first_of_july(api)
        )

        successor = validate_success(
            _create_assignment_at_the_first_of_july(api, enrollee["id"], physician["id"]),
            201,
        )
        assert_fields(
            successor,
            {
                "status": "ACTIVE",
                "effective_date": "2026-07-01T00:00:00Z",
                "term_date": None,
            },
        )

    def test_a_third_assignment_at_that_instant_collides_with_the_live_successor(
        self, api
    ):
        """PRD §3.4: "Absent `supersede_prior`, an interval that overlaps a
        non-terminal assignment of the same member is refused with
        `ERR_ASSIGNMENT_PERIOD_OVERLAP`, subject to the half-open semantics of
        §2.11 and to the precedence rule of §2.10 that an out-of-coverage
        `effective_date` is reported as `ERR_ASSIGNMENT_BEFORE_COVERAGE` even when
        the same request also overlaps."

        Design: Difficulty/resource_temporal_overlap/assignment_half_open_adjacency_allowed_then_overlap_rejected
        """
        _agreement, physician, enrollee, _termed = (
            _member_whose_first_assignment_termed_on_the_first_of_july(api)
        )
        successor = validate_success(
            _create_assignment_at_the_first_of_july(api, enrollee["id"], physician["id"]),
            201,
        )

        response = _create_assignment_at_the_first_of_july(
            api, enrollee["id"], physician["id"]
        )
        validate_error(response, ERR_ASSIGNMENT_PERIOD_OVERLAP, 409)
        assert read_assignment(api, successor["id"])["status"] == "ACTIVE"

    def test_only_the_live_row_counts_toward_the_panel_and_the_agreement(self, api):
        """PRD §2.9: "`PhysicianMember.panel_size` is the count of that
        physician's assignments whose `status` is `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/assignment_half_open_adjacency_allowed_then_overlap_rejected
        """
        agreement, physician, enrollee, _termed = (
            _member_whose_first_assignment_termed_on_the_first_of_july(api)
        )
        _create_assignment_at_the_first_of_july(api, enrollee["id"], physician["id"])
        _create_assignment_at_the_first_of_july(api, enrollee["id"], physician["id"])

        assert read_physician(api, physician["id"])["panel_size"] == 1
        assert read_agreement(api, agreement["id"])["total_assigned_members"] == 1

    def test_both_adjacent_rows_remain_listable_for_the_member(self, api):
        """PRD §3.4: "Assignments may be listed with optional `enrollee_id`,
        `physician_id`, `pending_to_physician_id` and `status` filters, and an
        individual read exposes the transfer target and the continuity window."

        Design: Difficulty/resource_temporal_overlap/assignment_half_open_adjacency_allowed_then_overlap_rejected
        """
        _agreement, physician, enrollee, _termed = (
            _member_whose_first_assignment_termed_on_the_first_of_july(api)
        )
        _create_assignment_at_the_first_of_july(api, enrollee["id"], physician["id"])
        _create_assignment_at_the_first_of_july(api, enrollee["id"], physician["id"])

        rows, meta = validate_paginated(
            api.list_assignments(
                NETWORK_MANAGER_HEADERS,
                {"enrollee_id": enrollee["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 2
        assert sorted(row["status"] for row in rows) == ["ACTIVE", "TERMINATED"]


def _agreement_with_a_calendar_2026_professional_pool(api):
    set_clock(api, "2026-01-01T00:00:00Z")
    agreement = create_active_agreement(api, max_panel_size=5)
    pool = create_pool(
        api,
        agreement["id"],
        pool_type="PROFESSIONAL",
        pool_year_start="2026-01-01T00:00:00Z",
        pool_year_end="2026-12-31T23:59:59Z",
    )
    return agreement, pool


def _create_pool_response(api, agreement_id, **overrides):
    return api.create_risk_pool(
        agreement_id, risk_pool_payload(**overrides), IPA_ADMIN_HEADERS
    )


class TestPoolClosedIntervalSharedEndpoint:
    def test_a_pool_starting_on_the_prior_pool_s_last_instant_collides(self, api):
        """PRD §2.11: "A pool ending exactly at `2026-12-31T23:59:59Z` and a new
        pool of the same `pool_type` starting at that same instant therefore do
        collide, and the second create is refused."

        Design: Difficulty/resource_temporal_overlap/pool_year_closed_interval_shared_endpoint_collides
        """
        agreement, _pool = _agreement_with_a_calendar_2026_professional_pool(api)

        response = _create_pool_response(
            api,
            agreement["id"],
            pool_type="PROFESSIONAL",
            pool_year_start="2026-12-31T23:59:59Z",
            pool_year_end="2027-12-31T23:59:59Z",
        )
        validate_error(response, ERR_POOL_PERIOD_OVERLAP, 409)

    def test_a_professional_pool_starting_one_second_later_is_accepted(self, api):
        """PRD §2.10: "A new pool's period must not overlap an existing pool of
        the same agreement with the same `pool_type`."

        Design: Difficulty/resource_temporal_overlap/pool_year_closed_interval_shared_endpoint_collides
        """
        agreement, _pool = _agreement_with_a_calendar_2026_professional_pool(api)

        accepted = validate_success(
            _create_pool_response(
                api,
                agreement["id"],
                pool_type="PROFESSIONAL",
                pool_year_start="2027-01-01T00:00:00Z",
                pool_year_end="2027-12-31T23:59:59Z",
            ),
            201,
        )
        assert_fields(
            accepted,
            {
                "status": "ACCUMULATING",
                "pool_year_start": "2027-01-01T00:00:00Z",
                "settlement_due_date": "2028-06-28T23:59:59Z",
            },
        )

    def test_the_shared_endpoint_is_legal_for_the_other_pool_type(self, api):
        """PRD §3.7: "Two pools of the same agreement and the same `pool_type` may
        not have overlapping periods under the closed-interval semantics of
        §2.11, and a collision is refused with `ERR_POOL_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/pool_year_closed_interval_shared_endpoint_collides
        """
        agreement, _pool = _agreement_with_a_calendar_2026_professional_pool(api)

        accepted = validate_success(
            _create_pool_response(
                api,
                agreement["id"],
                pool_type="INSTITUTIONAL",
                pool_year_start="2026-12-31T23:59:59Z",
                pool_year_end="2027-12-31T23:59:59Z",
            ),
            201,
        )
        assert_fields(
            accepted,
            {
                "pool_type": "INSTITUTIONAL",
                "status": "ACCUMULATING",
                "settlement_due_date": "2028-09-26T23:59:59Z",
            },
        )

    def test_the_settlement_lag_differs_by_pool_type(self, api):
        """PRD §3.7: "Its `settlement_due_date` is derived at creation as
        `pool_year_end` advanced by the settlement lag for its `pool_type`: 180
        days for a `PROFESSIONAL` pool, reflecting the shorter professional claim
        tail, and 270 days for an `INSTITUTIONAL` pool."

        Design: Difficulty/resource_temporal_overlap/pool_year_closed_interval_shared_endpoint_collides
        """
        agreement, pool = _agreement_with_a_calendar_2026_professional_pool(api)
        assert pool["settlement_due_date"] == "2027-06-29T23:59:59Z"

        institutional = validate_success(
            _create_pool_response(
                api,
                agreement["id"],
                pool_type="INSTITUTIONAL",
                pool_year_start="2026-01-01T00:00:00Z",
                pool_year_end="2026-12-31T23:59:59Z",
            ),
            201,
        )
        assert institutional["settlement_due_date"] == "2027-09-27T23:59:59Z"

    def test_every_accepted_pool_is_listed_for_the_agreement(self, api):
        """PRD §3.7: "A new pool begins in `status` `ACCUMULATING` with every
        ledger counter at zero — `funded_cents`, `member_months_bps`,
        `paid_claims_cents`, `ibnr_reserve_cents`, `stop_loss_recovery_cents`,
        `stop_loss_eligible_enrollee_count`, `loss_ratio_bps`,
        `raw_surplus_cents`, `admin_fee_cents`, `distributable_surplus_cents` and
        `shared_savings_pool_cents` all 0, `deficit_flag` false, and both
        `ibnr_method_used` and `surplus_tier` null."

        Design: Difficulty/resource_temporal_overlap/pool_year_closed_interval_shared_endpoint_collides
        """
        agreement, _pool = _agreement_with_a_calendar_2026_professional_pool(api)
        _create_pool_response(
            api,
            agreement["id"],
            pool_type="PROFESSIONAL",
            pool_year_start="2026-12-31T23:59:59Z",
            pool_year_end="2027-12-31T23:59:59Z",
        )
        _create_pool_response(
            api,
            agreement["id"],
            pool_type="PROFESSIONAL",
            pool_year_start="2027-01-01T00:00:00Z",
            pool_year_end="2027-12-31T23:59:59Z",
        )
        _create_pool_response(
            api,
            agreement["id"],
            pool_type="INSTITUTIONAL",
            pool_year_start="2026-12-31T23:59:59Z",
            pool_year_end="2027-12-31T23:59:59Z",
        )

        rows, meta = validate_paginated(
            api.list_agreement_risk_pools(
                agreement["id"], IPA_ADMIN_HEADERS, {"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 3
        assert all(row["status"] == "ACCUMULATING" for row in rows)
        assert all(row["funded_cents"] == 0 for row in rows)
