"""
The multi-hop cascades: a posting that reaches the store's calendar, a closure
that reaches the vendor's sampling obligation, the vacuous empty store, and the
return-to-count that unwinds a period.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_REWORK_LIMIT_REACHED
from test_helpers.assertions import assert_pct
from test_helpers.constants import DEFAULT_CLOCK_DATE
from test_helpers.test_users import ADMIN, ANALYST, SUPERVISOR


class TestPostingCascadesToStorePosture:
    def test_a_posting_that_drives_on_hand_negative_suspends_the_store(
        self, api, clock_at_default
    ):
        """
        Hop three and hop four follow the position down.

        "Hop three re-derives the position's `promising_state` — a negative
        `on_hand_units` or a `value_accuracy_pct` that has fallen below the
        category's `min_accuracy_pct` flips the position downward. Hop four
        re-derives the store's `blocked_position_count`,
        `restricted_position_count`, `accuracy_index_bps` and
        `fulfillment_status`."

        Design: Difficulty/transitive_cascade/adjustment_post_cascades_position_to_store_fulfillment
        """
        world = fx.apparel_reference_world(api, baseline=5)

        adjustment = fx.create_adjustment(api, world["position_id"], -10, headers=ANALYST)
        assert adjustment["value_impact_cents"] == 12340
        assert adjustment["authority_threshold_cents"] == 20000
        assert adjustment["approval_state"] == "NOT_REQUIRED"

        fx.post_adjustment(api, adjustment["id"], SUPERVISOR)

        position = fx.read_position(api, world["position_id"])
        assert position["on_hand_units"] == -5
        assert position["book_value_cents"] == -6170
        assert position["promising_state"] == "BLOCKED"

        eligibility = fx.read_eligibility(api, world["store_id"])
        assert eligibility["total_position_count"] == 1
        assert eligibility["blocked_position_count"] == 1
        assert eligibility["restricted_position_count"] == 0
        assert eligibility["blocked_ratio_bps"] == 10000
        assert eligibility["restricted_ratio_bps"] == 0
        assert eligibility["accuracy_index_bps"] == 10000
        assert eligibility["fulfillment_status"] == "SUSPENDED"

    def test_hop_five_halves_the_cadence_and_pulls_the_due_date_to_today(
        self, api, clock_at_default
    ):
        """
        The fifth hop only fires when the store lands in `SUSPENDED`.

        "Hop five fires only when hop four leaves the store's
        `fulfillment_status` at `SUSPENDED`: every count schedule at that store
        whose `status` is `ACTIVE` has its `cadence_days` replaced by the larger
        of 7 and the floor of half its current `cadence_days`, and its
        `next_due_date` set to the calendar date of the current logical-clock
        instant, making every such schedule immediately due."

        Design: Difficulty/transitive_cascade/adjustment_post_cascades_position_to_store_fulfillment
        """
        world = fx.apparel_reference_world(api, baseline=5)
        schedule = fx.create_schedule(
            api,
            world["store_id"],
            world["category_id"],
            first_due_date="2026-09-01",
            cadence_days=30,
        )
        assert schedule["next_due_date"] == "2026-09-01"

        adjustment = fx.create_adjustment(api, world["position_id"], -10, headers=ANALYST)
        fx.post_adjustment(api, adjustment["id"], SUPERVISOR)

        accelerated = fx.read_schedule(api, schedule["id"])
        assert accelerated["cadence_days"] == 15
        assert accelerated["next_due_date"] == DEFAULT_CLOCK_DATE
        assert accelerated["status"] == "ACTIVE"


class TestInvestigationClosureCascade:
    def test_closing_a_vendor_shortage_moves_the_bucket_and_the_vendor_score(self, api):
        """
        Hop two names the bucket and hop three reaches the vendor.

        "Hop three, caused by hop two and occurring **only** when
        `approved_root_cause` is `VENDOR_SHORTAGE`, reaches the vendor: the
        `primary_vendor_id` of the SKU on the investigation's originating count
        line has its `shortage_event_count` incremented by 1 and its
        `tag_compliance_score_bps` reduced by 1500 basis points, floored at 0."

        Design: Difficulty/transitive_cascade/investigation_close_cascades_shrink_vendor_tag_sample
        """
        world = fx.counted_variance_world(api, counted_units=105, baseline=100)

        before_attribution = fx.read_attribution(api, world["shrink_period_id"])
        assert before_attribution["unresolved_cents"] == 6633
        assert before_attribution["vendor_shortage_cents"] == 0

        before_vendor = fx.read_vendor(api, world["vendor_id"])
        assert before_vendor["tag_compliance_score_bps"] == 10000
        assert before_vendor["required_verification_sample_pct"] == 5
        assert before_vendor["shortage_event_count"] == 0

        closed = fx.drive_to_closed(
            api, world["investigation_id"], "VENDOR_SHORTAGE"
        )
        assert closed["status"] == "CLOSED"
        assert closed["approved_root_cause"] == "VENDOR_SHORTAGE"

        attribution = fx.read_attribution(api, world["shrink_period_id"])
        assert attribution["vendor_shortage_cents"] == 6633
        assert attribution["unresolved_cents"] == 0
        assert attribution["total_attributable_variance_cents"] == 6633
        assert attribution["provisional_total_shrink_cents"] == 6633
        assert attribution["final_total_shrink_cents"] == 6633

        vendor = fx.read_vendor(api, world["vendor_id"])
        assert vendor["shortage_event_count"] == 1
        assert vendor["tag_compliance_score_bps"] == 8500
        assert vendor["required_verification_sample_pct"] == 10

    def test_the_closure_refreezes_the_sample_obligation_on_a_draft_batch(self, api):
        """
        Hop four reaches the vendor's undelivered batches.

        "Hop four, caused by hop three, re-derives that vendor's
        `required_verification_sample_pct` from the new score band and re-freezes
        `required_sample_units` on every one of that vendor's tag batches still in
        `DRAFT` or `ENCODED`, so a shortage finding tightens the vendor's future
        receipt sampling as well as its score."

        Design: Difficulty/transitive_cascade/investigation_close_cascades_shrink_vendor_tag_sample
        """
        world = fx.counted_variance_world(api, counted_units=105, baseline=100)
        batch = validate_success(
            api.create_tag_batch(
                f.tag_batch_payload(
                    world["vendor_id"],
                    world["item_id"],
                    world["store_id"],
                    quantity_encoded=1000,
                ),
                ADMIN,
            ),
            201,
        )
        assert batch["status"] == "DRAFT"

        fx.drive_to_closed(api, world["investigation_id"], "VENDOR_SHORTAGE")

        retightened = fx.read_tag_batch(api, batch["id"])
        assert retightened["required_sample_units"] == 100

        encoded = validate_success(
            api.encode_tag_batch(batch["id"], f.encode_payload(), ADMIN)
        )
        assert encoded["status"] == "ENCODED"
        assert encoded["required_sample_units"] == 100

    def test_the_position_stays_restricted_on_the_frozen_accuracy(self, api):
        """
        The closure releases the investigation clause but not the accuracy floor.

        "Alongside the cascade the investigated position's `promising_state` is
        re-derived — the position is no longer held back by a non-terminal
        investigation — and the store's `fulfillment_status` follows."

        Design: Difficulty/transitive_cascade/investigation_close_cascades_shrink_vendor_tag_sample
        """
        world = fx.counted_variance_world(api, counted_units=105, baseline=100)
        fx.drive_to_closed(api, world["investigation_id"], "VENDOR_SHORTAGE")

        position = fx.read_position(api, world["position_id"])
        assert_pct(position["value_accuracy_pct"], 94.62)
        assert position["promising_state"] == "RESTRICTED"


class TestEmptyStorePosture:
    def test_a_store_with_no_positions_is_vacuously_accurate(self, api):
        """
        The empty-store branch is decided before any division.

        "**The empty-store case is decided first:** when `total_position_count` is
        0, `accuracy_index_bps` is 10000, `blocked_position_count` and
        `restricted_position_count` are 0, `fulfillment_status` is `ELIGIBLE`, and
        nothing further is evaluated."

        Design: Difficulty/boundary_precision_check/empty_store_reads_ten_thousand_bps_and_eligible
        """
        store = fx.create_store(api, f.handheld_only_store_payload())

        eligibility = fx.read_eligibility(api, store["id"])
        assert eligibility["store_id"] == store["id"]
        assert eligibility["total_position_count"] == 0
        assert eligibility["blocked_position_count"] == 0
        assert eligibility["restricted_position_count"] == 0
        assert eligibility["blocked_ratio_bps"] == 0
        assert eligibility["restricted_ratio_bps"] == 0
        assert eligibility["accuracy_index_bps"] == 10000
        assert eligibility["fulfillment_status"] == "ELIGIBLE"
        assert not eligibility["demotion_reason"]

    def test_the_first_uncounted_position_keeps_the_index_at_ten_thousand(self, api):
        """
        A never-counted position reads a perfect accuracy.

        "Both accuracy figures, `unit_accuracy_pct` and `value_accuracy_pct`, read
        exactly 100.00, because a position that has never been counted is treated
        as perfectly accurate."

        Design: Difficulty/boundary_precision_check/empty_store_reads_ten_thousand_bps_and_eligible
        """
        category = fx.create_category(api)
        vendor = fx.create_vendor(api)
        item = fx.create_item(api, f.item_payload(category["id"], vendor["id"]))
        store = fx.create_store(api, f.handheld_only_store_payload())

        position = fx.create_position(api, store["id"], item["id"], baseline=10)
        assert_pct(position["unit_accuracy_pct"], 100.00)
        assert position["promising_state"] == "PROMISABLE"

        eligibility = fx.read_eligibility(api, store["id"])
        assert eligibility["total_position_count"] == 1
        assert eligibility["accuracy_index_bps"] == 10000
        assert eligibility["blocked_position_count"] == 0
        assert eligibility["restricted_position_count"] == 0
        assert eligibility["fulfillment_status"] == "ELIGIBLE"


class TestReturnToCountUnwind:
    def test_the_return_discards_the_count_and_waives_the_open_investigation(self, api):
        """
        The return unwinds the task and the period together.

        "Every investigation whose originating line was just deleted and whose
        status is still `OPEN` moves to `WAIVED`, and its `variance_value_cents` is
        removed from the covering period's `unresolved_cents`, with that period's
        `total_attributable_variance_cents` and both shrink totals re-derived."

        Design: Difficulty/compensating_invariant/count_return_to_count_waives_investigations_and_restores_shrink_unresolved
        """
        world = fx.counted_variance_world(api, counted_units=105, baseline=100)
        assert fx.read_attribution(api, world["shrink_period_id"])["unresolved_cents"] == 6633

        returned = validate_success(
            api.return_count_task_to_count(world["task_id"], SUPERVISOR)
        )
        assert returned["status"] == "IN_PROGRESS"
        assert returned["recount_round"] == 1
        assert returned["counted_line_count"] == 0
        assert_pct(returned["coverage_pct"], 0.00)
        assert returned["variance_line_count"] == 0
        assert returned["total_variance_value_cents"] == 0

        attribution = fx.read_attribution(api, world["shrink_period_id"])
        assert attribution["unresolved_cents"] == 0
        assert attribution["total_attributable_variance_cents"] == 0
        assert attribution["provisional_total_shrink_cents"] == 0
        assert attribution["final_total_shrink_cents"] == 0
        assert attribution["provisional_shrink_rate_bps"] == 0
        assert attribution["final_shrink_rate_bps"] == 0

        assert fx.read_investigation(api, world["investigation_id"])["status"] == "WAIVED"

        rows, meta = validate_paginated(
            api.list_count_lines(ANALYST, {"count_task_id": world["task_id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_the_position_keeps_the_frozen_count_figures_after_the_return(self, api):
        """
        The discarded count does not rewrite the position's frozen inputs.

        "Adjustments never rewrite the frozen inputs, so the two accuracy figures
        are stable across postings and move only at the next count."

        Design: Difficulty/compensating_invariant/count_return_to_count_waives_investigations_and_restores_shrink_unresolved
        """
        world = fx.counted_variance_world(api, counted_units=105, baseline=100)
        validate_success(api.return_count_task_to_count(world["task_id"], SUPERVISOR))

        position = fx.read_position(api, world["position_id"])
        assert position["last_count_system_units"] == 100
        assert position["last_variance_units"] == 5
        assert position["last_variance_value_cents"] == 6633
        assert_pct(position["value_accuracy_pct"], 94.62)
        assert position["promising_state"] == "RESTRICTED"

    def test_only_one_return_is_available_per_task(self, api):
        """
        The recount counter caps the loop at one traversal.

        "This is permitted only while `recount_round` is strictly below 1, so
        exactly one return is available per task; a second attempt is rejected
        with `ERR_REWORK_LIMIT_REACHED`."

        Design: Difficulty/compensating_invariant/count_return_to_count_waives_investigations_and_restores_shrink_unresolved
        """
        world = fx.counted_variance_world(api, counted_units=105, baseline=100)
        validate_success(api.return_count_task_to_count(world["task_id"], SUPERVISOR))

        fx.add_line(api, world["task_id"], world["item_id"], 105)
        recounted = fx.submit_task(api, world["task_id"])
        assert recounted["status"] == "COUNTED"

        validate_error(
            api.return_count_task_to_count(world["task_id"], SUPERVISOR),
            ERR_REWORK_LIMIT_REACHED,
            409,
        )

        assert fx.read_task(api, world["task_id"])["status"] == "COUNTED"
