"""
The adjustment authority ladder, the two independent state dimensions, the
approval guards and the reversal invariant.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ADJUSTMENT_ABOVE_SUPERVISOR_CAP,
    ERR_ADJUSTMENT_INVALID_STATE,
    ERR_INVESTIGATION_NOT_CLOSED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_ZERO_DELTA_UNITS,
)
from test_helpers.assertions import (
    assert_adjustment_dimensions,
    assert_clock_instant,
)
from test_helpers.constants import DEFAULT_CLOCK_DATE
from test_helpers.test_users import (
    ANALYST,
    CONTROLLER,
    SUPERVISOR,
    SUPERVISOR_2,
    USER_ANALYST_1,
    USER_SUPERVISOR_1,
)


class TestAuthorityThresholdLadder:
    def test_a_prior_posted_sibling_tightens_the_threshold_for_the_next_request(
        self, api
    ):
        """
        The repeat-offender penalty is read from the position's posted siblings.

        "a category tolerance of 20000, a linked and `CLOSED` investigation whose
        `approved_root_cause` is `THEFT`, and one prior `POSTED` sibling on the
        position give a candidate of 20000, a base of 20000, a strictness of 5000
        basis points and a penalty of 1000 basis points, so the threshold is the
        floor of 20000 × 0.5 × 0.9, which is 9000."

        Design: Difficulty/combinatorial_formula/adjustment_authority_nested_threshold
        """
        world = fx.closed_theft_world(api, counted_units=105, baseline=100)

        first = fx.create_adjustment(
            api,
            world["position_id"],
            -5,
            investigation_id=world["investigation_id"],
            headers=ANALYST,
        )
        assert first["value_impact_cents"] == 6170
        assert first["authority_threshold_cents"] == 10000
        assert_adjustment_dimensions(
            first, approval_state="NOT_REQUIRED", posting_state="UNPOSTED"
        )

        fx.post_adjustment(api, first["id"], SUPERVISOR)
        assert fx.read_position(api, world["position_id"])["on_hand_units"] == 95

        second = fx.create_adjustment(
            api,
            world["position_id"],
            -8,
            investigation_id=world["investigation_id"],
            headers=ANALYST,
        )
        assert second["value_impact_cents"] == 9872
        assert second["authority_threshold_cents"] == 9000
        assert_adjustment_dimensions(
            second, approval_state="PENDING", posting_state="UNPOSTED"
        )

    def test_the_boundary_between_the_two_requests_is_the_frozen_threshold(self, api):
        """
        The threshold is frozen on the row at creation.

        "`value_impact_cents` and `authority_threshold_cents` are both computed
        once at creation and frozen on the row."

        Design: Difficulty/combinatorial_formula/adjustment_authority_nested_threshold
        """
        world = fx.closed_theft_world(api, counted_units=105, baseline=100)

        first = fx.create_adjustment(
            api,
            world["position_id"],
            -5,
            investigation_id=world["investigation_id"],
            headers=ANALYST,
        )
        fx.post_adjustment(api, first["id"], SUPERVISOR)

        fx.create_adjustment(
            api,
            world["position_id"],
            -8,
            investigation_id=world["investigation_id"],
            headers=ANALYST,
        )

        reread = fx.read_adjustment(api, first["id"])
        assert reread["authority_threshold_cents"] == 10000
        assert reread["value_impact_cents"] == 6170
        assert reread["approval_state"] == "NOT_REQUIRED"


class TestParallelStateDimensions:
    def test_approval_does_not_post_and_posting_moves_the_units(
        self, api, clock_at_default
    ):
        """
        The approval and posting dimensions advance separately.

        "The two advance separately and never drive each other: approving an
        adjustment does not post it, posting one does not change its approval, an
        adjustment created as `NOT_REQUIRED` may be posted with no approval step
        ever occurring, and an adjustment that is approved but never posted stays
        `UNPOSTED` forever and contributes nothing to any position."

        Design: Difficulty/non_linear_state_machine/adjustment_parallel_approval_and_posting_dimensions
        """
        world = fx.apparel_reference_world(api, baseline=100)

        created = fx.create_adjustment(api, world["position_id"], -20, headers=ANALYST)
        assert created["value_impact_cents"] == 24680
        assert created["authority_threshold_cents"] == 20000
        assert_adjustment_dimensions(
            created, approval_state="PENDING", posting_state="UNPOSTED"
        )
        assert created["requested_by_user_id"] == USER_ANALYST_1

        approved = validate_success(api.approve_adjustment(created["id"], SUPERVISOR))
        assert_adjustment_dimensions(
            approved, approval_state="APPROVED", posting_state="UNPOSTED"
        )
        assert approved["approved_by_user_id"] == USER_SUPERVISOR_1
        assert approved["posted_at"] is None

        held = fx.read_position(api, world["position_id"])
        assert held["on_hand_units"] == 100
        assert held["book_value_cents"] == 123400

        posted = validate_success(api.post_adjustment(created["id"], SUPERVISOR))
        assert_adjustment_dimensions(
            posted, approval_state="APPROVED", posting_state="POSTED"
        )
        assert_clock_instant(posted["posted_at"], clock_at_default)

        moved = fx.read_position(api, world["position_id"])
        assert moved["on_hand_units"] == 80
        assert moved["book_value_cents"] == 98720

    def test_posting_a_second_time_is_refused_on_the_posting_dimension(self, api):
        """
        `POSTED` does not permit another posting step.

        "`posting_state` must be `UNPOSTED`, otherwise
        `ERR_ADJUSTMENT_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/adjustment_parallel_approval_and_posting_dimensions
        """
        world = fx.apparel_reference_world(api, baseline=100)
        created = fx.create_adjustment(api, world["position_id"], -20, headers=ANALYST)
        validate_success(api.approve_adjustment(created["id"], SUPERVISOR))
        fx.post_adjustment(api, created["id"], SUPERVISOR)

        validate_error(
            api.post_adjustment(created["id"], SUPERVISOR),
            ERR_ADJUSTMENT_INVALID_STATE,
            409,
        )

        assert fx.read_position(api, world["position_id"])["on_hand_units"] == 80


class TestZeroDeltaUnits:
    def test_a_zero_delta_is_rejected_and_writes_nothing(self, api):
        """
        A zero movement is not an adjustment.

        "`delta_units` is a signed whole-unit movement and must not be zero — a
        zero is rejected with `ERR_ZERO_DELTA_UNITS`."

        Design: Difficulty/boundary_precision_check/zero_delta_units_rejected_on_adjustment_create
        """
        world = fx.apparel_reference_world(api, baseline=100)
        version_before = fx.position_version(api, world["position_id"])

        validate_error(
            api.create_adjustment(
                world["position_id"],
                f.adjustment_payload(0, version_before),
                ANALYST,
            ),
            ERR_ZERO_DELTA_UNITS,
            422,
        )

        rows, meta = validate_paginated(api.list_adjustments(SUPERVISOR))
        assert rows == []
        assert meta["total_count"] == 0

        position = fx.read_position(api, world["position_id"])
        assert position["version"] == version_before
        assert position["on_hand_units"] == 100

    def test_the_smallest_movement_in_each_direction_is_accepted(self, api):
        """
        One unit either way is a legitimate movement.

        "`value_impact_cents` is the absolute value of `delta_units` multiplied
        by the `unit_cost_cents` of the SKU behind the position."

        Design: Difficulty/boundary_precision_check/zero_delta_units_rejected_on_adjustment_create
        """
        world = fx.apparel_reference_world(api, baseline=100)

        down = fx.create_adjustment(api, world["position_id"], -1, headers=ANALYST)
        assert down["value_impact_cents"] == 1234
        assert down["approval_state"] == "NOT_REQUIRED"

        up = fx.create_adjustment(api, world["position_id"], 1, headers=ANALYST)
        assert up["value_impact_cents"] == 1234
        assert up["approval_state"] == "NOT_REQUIRED"

        rows, meta = validate_paginated(api.list_adjustments(SUPERVISOR))
        assert meta["total_count"] == 2


class TestApprovalGuardOrder:
    def test_the_requester_approving_their_own_row_reports_segregation_of_duties(
        self, api
    ):
        """
        The audit rule outranks the money rule.

        "A request that fails both an audit rule and a money rule always reports
        the audit rule — for example, an adjustment approval by the very operator
        who requested it reports `ERR_SEGREGATION_OF_DUTIES` even when the value
        impact also exceeds the supervisor cap."

        Design: Difficulty/priority_pair_validation_conflict/sod_beats_supervisor_cap_on_adjustment_approve
        """
        category = fx.create_category(api, f.elec_category_payload())
        store = fx.create_store(api)
        vendor = fx.create_vendor(api)
        item = fx.create_item(api, f.tv_item_payload(category["id"], vendor["id"]))
        position = fx.create_position(api, store["id"], item["id"], baseline=100)

        requested = fx.create_adjustment(api, position["id"], -20, headers=SUPERVISOR)
        assert requested["value_impact_cents"] == 800000
        assert requested["authority_threshold_cents"] == 5000
        assert requested["approval_state"] == "PENDING"
        assert requested["requested_by_user_id"] == USER_SUPERVISOR_1

        validate_error(
            api.approve_adjustment(requested["id"], SUPERVISOR),
            ERR_SEGREGATION_OF_DUTIES,
            403,
        )

        untouched = fx.read_adjustment(api, requested["id"])
        assert untouched["approval_state"] == "PENDING"
        assert untouched["approved_by_user_id"] is None

    def test_a_different_supervisor_is_stopped_by_the_financial_cap(self, api):
        """
        Above the cap only a controller may approve.

        "when `value_impact_cents` is strictly greater than 500000 cents, only a
        `ShrinkController` may approve, and an `InventorySupervisor` attempting it
        is rejected with `ERR_ADJUSTMENT_ABOVE_SUPERVISOR_CAP`."

        Design: Difficulty/priority_pair_validation_conflict/sod_beats_supervisor_cap_on_adjustment_approve
        """
        category = fx.create_category(api, f.elec_category_payload())
        store = fx.create_store(api)
        vendor = fx.create_vendor(api)
        item = fx.create_item(api, f.tv_item_payload(category["id"], vendor["id"]))
        position = fx.create_position(api, store["id"], item["id"], baseline=100)
        requested = fx.create_adjustment(api, position["id"], -20, headers=SUPERVISOR)

        validate_error(
            api.approve_adjustment(requested["id"], SUPERVISOR_2),
            ERR_ADJUSTMENT_ABOVE_SUPERVISOR_CAP,
            403,
        )
        assert fx.read_adjustment(api, requested["id"])["approval_state"] == "PENDING"

        approved = validate_success(api.approve_adjustment(requested["id"], CONTROLLER))
        assert approved["approval_state"] == "APPROVED"
        assert approved["posting_state"] == "UNPOSTED"


class TestPostingRequiresAClosedInvestigation:
    def test_a_cause_approved_investigation_still_blocks_the_posting(self, api):
        """
        Units may not move while the attribution work is unfinished.

        "When `investigation_id` is not null, that investigation's `status` must
        be `CLOSED`, otherwise `ERR_INVESTIGATION_NOT_CLOSED`; an adjustment
        justified by an investigation may not move units until the attribution
        work behind it is finished."

        Design: Difficulty/cross_entity_state_dependency/adjustment_post_requires_investigation_closed
        """
        world = fx.cause_approved_world(api, root_cause="THEFT", counted_units=105)
        assert (
            fx.read_investigation(api, world["investigation_id"])["status"]
            == "CAUSE_APPROVED"
        )

        adjustment = fx.create_adjustment(
            api,
            world["position_id"],
            -5,
            investigation_id=world["investigation_id"],
            headers=ANALYST,
        )
        assert adjustment["value_impact_cents"] == 6170
        assert adjustment["approval_state"] == "NOT_REQUIRED"

        validate_error(
            api.post_adjustment(adjustment["id"], SUPERVISOR),
            ERR_INVESTIGATION_NOT_CLOSED,
            409,
        )

        stalled = fx.read_adjustment(api, adjustment["id"])
        assert stalled["posting_state"] == "UNPOSTED"
        assert stalled["posted_at"] is None

        position = fx.read_position(api, world["position_id"])
        assert position["on_hand_units"] == 100
        assert position["book_value_cents"] == 123400

    def test_closing_the_investigation_releases_the_identical_posting(self, api):
        """
        Once the investigation is closed the same request succeeds.

        "Hop two re-derives the position: `on_hand_units` becomes
        `baseline_on_hand_units` plus the sum of `delta_units` over every
        adjustment on that position whose `posting_state` is `POSTED`"

        Design: Difficulty/cross_entity_state_dependency/adjustment_post_requires_investigation_closed
        """
        world = fx.cause_approved_world(api, root_cause="THEFT", counted_units=105)
        adjustment = fx.create_adjustment(
            api,
            world["position_id"],
            -5,
            investigation_id=world["investigation_id"],
            headers=ANALYST,
        )
        validate_error(
            api.post_adjustment(adjustment["id"], SUPERVISOR),
            ERR_INVESTIGATION_NOT_CLOSED,
            409,
        )

        validate_success(api.close_investigation(world["investigation_id"], SUPERVISOR))

        posted = validate_success(api.post_adjustment(adjustment["id"], SUPERVISOR))
        assert posted["posting_state"] == "POSTED"
        assert fx.read_position(api, world["position_id"])["on_hand_units"] == 95


class TestReversalConservesUnits:
    def test_reversal_returns_on_hand_to_the_pre_posting_figure(
        self, api, clock_at_default
    ):
        """
        Removing a row from the posted set restores the earlier on-hand exactly.

        "Consequently reversing a posted adjustment removes it from the set and
        returns on-hand to precisely the value it would have had if the adjustment
        had never posted, with zero drift."

        Design: Difficulty/compensating_invariant/adjustment_reverse_conserves_on_hand_units
        """
        world = fx.apparel_reference_world(api, baseline=5)
        fx.create_schedule(
            api,
            world["store_id"],
            world["category_id"],
            first_due_date="2026-08-15",
            cadence_days=30,
        )

        adjustment = fx.create_adjustment(api, world["position_id"], -10, headers=ANALYST)
        assert adjustment["value_impact_cents"] == 12340
        assert adjustment["approval_state"] == "NOT_REQUIRED"
        fx.post_adjustment(api, adjustment["id"], SUPERVISOR)

        driven_down = fx.read_position(api, world["position_id"])
        assert driven_down["on_hand_units"] == -5
        assert driven_down["book_value_cents"] == -6170
        assert driven_down["promising_state"] == "BLOCKED"

        reversed_row = validate_success(
            api.reverse_adjustment(adjustment["id"], SUPERVISOR)
        )
        assert reversed_row["posting_state"] == "REVERSED"
        assert reversed_row["approval_state"] == "NOT_REQUIRED"
        assert_clock_instant(reversed_row["reversed_at"], clock_at_default)

        restored = fx.read_position(api, world["position_id"])
        assert restored["on_hand_units"] == 5
        assert restored["book_value_cents"] == 6170
        assert restored["promising_state"] == "PROMISABLE"

        eligibility = fx.read_eligibility(api, world["store_id"])
        assert eligibility["blocked_position_count"] == 0
        assert eligibility["blocked_ratio_bps"] == 0
        assert eligibility["accuracy_index_bps"] == 10000
        assert eligibility["fulfillment_status"] == "ELIGIBLE"

        rows, meta = validate_paginated(api.list_adjustments(SUPERVISOR))
        assert meta["total_count"] == 1

    def test_the_accelerated_calendar_is_not_rolled_back_by_the_reversal(
        self, api, clock_at_default
    ):
        """
        Schedule acceleration survives the recovery.

        "One thing is deliberately **not** undone: if the earlier posting's hop
        five accelerated the store's count schedules, a recovery of
        `fulfillment_status` does not restore the old `cadence_days` or the old
        `next_due_date`."

        Design: Difficulty/compensating_invariant/adjustment_reverse_conserves_on_hand_units
        """
        world = fx.apparel_reference_world(api, baseline=5)
        schedule = fx.create_schedule(
            api,
            world["store_id"],
            world["category_id"],
            first_due_date="2026-08-15",
            cadence_days=30,
        )
        assert schedule["cadence_days"] == 30
        assert schedule["next_due_date"] == "2026-08-15"

        adjustment = fx.create_adjustment(api, world["position_id"], -10, headers=ANALYST)
        fx.post_adjustment(api, adjustment["id"], SUPERVISOR)

        accelerated = fx.read_schedule(api, schedule["id"])
        assert accelerated["cadence_days"] == 15
        assert accelerated["next_due_date"] == DEFAULT_CLOCK_DATE
        assert accelerated["status"] == "ACTIVE"

        validate_success(api.reverse_adjustment(adjustment["id"], SUPERVISOR))

        after = fx.read_schedule(api, schedule["id"])
        assert after["cadence_days"] == 15
        assert after["next_due_date"] == DEFAULT_CLOCK_DATE

    def test_a_reversed_row_may_not_be_reversed_again(self, api):
        """
        `REVERSED` is terminal on the posting dimension.

        "`REJECTED` is terminal on the approval dimension and `REVERSED` is
        terminal on the posting dimension."

        Design: Difficulty/compensating_invariant/adjustment_reverse_conserves_on_hand_units
        """
        world = fx.apparel_reference_world(api, baseline=5)
        adjustment = fx.create_adjustment(api, world["position_id"], -10, headers=ANALYST)
        fx.post_adjustment(api, adjustment["id"], SUPERVISOR)
        validate_success(api.reverse_adjustment(adjustment["id"], SUPERVISOR))

        validate_error(
            api.reverse_adjustment(adjustment["id"], SUPERVISOR),
            ERR_ADJUSTMENT_INVALID_STATE,
            409,
        )

        assert fx.read_position(api, world["position_id"])["on_hand_units"] == 5
