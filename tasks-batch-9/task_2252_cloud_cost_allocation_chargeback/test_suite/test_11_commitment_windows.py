"""Commitments: where the discount is rounded, and where the padded term collides."""

from test_helpers import (
    CONTROLLER_HEADERS,
    ApiErrorId,
    assert_cents,
    assert_commitment_figures,
    assert_pct,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import AUGUST_START

TERM_START = "2026-06-30T00:00:00Z"
PADDED_END_INSTANT = "2026-08-02T00:00:00Z"
CLEAR_OF_PAD_INSTANT = "2026-08-02T00:00:01Z"


def _instant_prefix(instant: str) -> str:
    """The instant without its trailing Z, so a fractional-seconds suffix matches."""
    return instant[:-1]


def _three_covered_records(api):
    """Three 10100-cent COMPUTE records under one PENDING savings plan.

    The plan's 720-hour envelope of 36000 cents is wide enough to cover all
    three records, so the waterfall never has to skip a candidate and the only
    open question is where the discount gets rounded.
    """
    built = fixtures.discounted_compute_model(api, activate=False)
    assert built["commitment"]["status"] == "PENDING"
    return built


def test_the_savings_plan_discount_is_rounded_once_per_record_before_summing(api):
    """Three records of 10100 cents give 2778 each and 8334 in total, not 8333.

    PRD §3.4: "The per-record rounding position matters: summing the list costs
    first and rounding a single time at the end produces a different
    `total_discount_cents` and is wrong."

    Design: Difficulty/combinatorial_formula/commitment_discount_round_per_record_then_sum
    """
    built = _three_covered_records(api)

    activated = validate_success(
        api.activate_commitment(built["commitment"]["id"], CONTROLLER_HEADERS)
    )
    assert activated["status"] == "ACTIVE"
    assert_commitment_figures(
        activated,
        committed_capacity_cents=36000,
        covered_spend_cents=30300,
        total_discount_cents=8334,
        waste_cents=5700,
        coverage_pct=100.00,
        utilization_pct=84.17,
    )
    assert activated["total_discount_cents"] != 8333

    for record in built["records"]:
        covered = validate_success(api.get_cost_record(record["id"], CONTROLLER_HEADERS))
        assert_cents(covered["list_cost_cents"], 10100, "list_cost_cents")
        assert_cents(covered["effective_cost_cents"], 7322, "effective_cost_cents")
        assert_cents(
            covered["list_cost_cents"] - covered["effective_cost_cents"], 2778, "per-record discount"
        )
        assert covered["applied_commitment_id"] == built["commitment"]["id"]


def test_re_evaluating_the_plan_above_its_utilization_target_keeps_it_active(api):
    """84.17 percent clears an 80.00 percent target, so the status does not oscillate.

    PRD §3.4: "Otherwise, coverage is recomputed and the commitment oscillates:
    `ACTIVE → UNDER_UTILIZED` when the recomputed `utilization_pct` is strictly
    below `utilization_target_pct`, and `UNDER_UTILIZED → ACTIVE` when it is at
    or above `utilization_target_pct`."

    Design: Difficulty/combinatorial_formula/commitment_discount_round_per_record_then_sum
    """
    built = _three_covered_records(api)
    commitment_id = built["commitment"]["id"]
    validate_success(api.activate_commitment(commitment_id, CONTROLLER_HEADERS))

    evaluated = validate_success(api.evaluate_commitment(commitment_id, CONTROLLER_HEADERS))
    assert evaluated["status"] == "ACTIVE"
    assert_pct(evaluated["utilization_target_pct"], 80.00, "utilization_target_pct")
    assert_commitment_figures(
        evaluated,
        committed_capacity_cents=36000,
        covered_spend_cents=30300,
        total_discount_cents=8334,
        waste_cents=5700,
        coverage_pct=100.00,
        utilization_pct=84.17,
    )

    for record in built["records"]:
        unchanged = validate_success(api.get_cost_record(record["id"], CONTROLLER_HEADERS))
        assert_cents(unchanged["effective_cost_cents"], 7322, "effective_cost_cents")
        assert unchanged["applied_commitment_id"] == commitment_id


def _pending_us_east_savings_plan(api):
    """A PENDING savings plan running 2026-06-30 through 2026-08-01 in us-east-1."""
    fixtures.set_clock(api)
    return fixtures.create_commitment(
        api,
        commitment_type="SAVINGS_PLAN",
        covered_resource_kind=None,
        region="us-east-1",
        term_start=TERM_START,
        term_end=AUGUST_START,
        hourly_commit_cents=50,
        coverage_target_pct=80.00,
        utilization_target_pct=80.00,
    )


def test_a_same_type_term_is_refused_until_it_clears_the_padded_end_by_a_second(api):
    """The pad makes the abutting term collide; one second past it purchases cleanly.

    PRD §2.5: "**Commitment terms are closed on both ends**, spanning
    `term_start` through `term_end` inclusive, and they are compared with a
    24-hour cool-off pad applied to both ends before the comparison."

    Design: Difficulty/resource_temporal_overlap/commitment_terms_closed_interval_with_twenty_four_hour_buffer
    """
    base = _pending_us_east_savings_plan(api)

    def purchase(term_start):
        return api.create_commitment(
            factories.commitment_payload(
                commitment_type="SAVINGS_PLAN",
                covered_resource_kind=None,
                region="us-east-1",
                term_start=term_start,
                term_end="2026-09-15T00:00:00Z",
                hourly_commit_cents=50,
            ),
            CONTROLLER_HEADERS,
        )

    validate_error(
        purchase(AUGUST_START), ApiErrorId.COMMITMENT_WINDOW_CONFLICT.value, 409
    )
    validate_error(
        purchase(PADDED_END_INSTANT), ApiErrorId.COMMITMENT_WINDOW_CONFLICT.value, 409
    )

    accepted = validate_success(purchase(CLEAR_OF_PAD_INSTANT), 201)
    assert accepted["status"] == "PENDING"
    assert accepted["term_start"].startswith(_instant_prefix(CLEAR_OF_PAD_INSTANT))
    assert_cents(accepted["committed_capacity_cents"], 36000, "committed_capacity_cents")

    untouched = validate_success(api.get_commitment(base["id"], CONTROLLER_HEADERS))
    assert untouched["status"] == "PENDING"
    assert untouched["term_start"].startswith(_instant_prefix(TERM_START))
    assert untouched["term_end"].startswith(_instant_prefix(AUGUST_START))
    assert untouched["version"] == base["version"]

    _, meta = validate_paginated(
        api.list_commitments(CONTROLLER_HEADERS, {"region": "us-east-1"})
    )
    assert meta["total_count"] == 2


def test_the_same_padded_term_in_another_region_is_not_a_conflict(api):
    """The conflict is keyed on the region, so us-west-2 takes the same instants.

    PRD §2.5: "A new commitment in the same `region` and of the same
    `commitment_type` may not sit within 24 hours of the term of any existing
    commitment in `PENDING`, `ACTIVE` or `UNDER_UTILIZED` status."

    Design: Difficulty/resource_temporal_overlap/commitment_terms_closed_interval_with_twenty_four_hour_buffer
    """
    base = _pending_us_east_savings_plan(api)

    validate_error(
        api.create_commitment(
            factories.commitment_payload(
                commitment_type="SAVINGS_PLAN",
                covered_resource_kind=None,
                region="us-east-1",
                term_start=AUGUST_START,
                term_end="2026-09-15T00:00:00Z",
                hourly_commit_cents=50,
            ),
            CONTROLLER_HEADERS,
        ),
        ApiErrorId.COMMITMENT_WINDOW_CONFLICT.value,
        409,
    )

    elsewhere = validate_success(
        api.create_commitment(
            factories.commitment_payload(
                commitment_type="SAVINGS_PLAN",
                covered_resource_kind=None,
                region="us-west-2",
                term_start=AUGUST_START,
                term_end="2026-09-15T00:00:00Z",
                hourly_commit_cents=50,
            ),
            CONTROLLER_HEADERS,
        ),
        201,
    )
    assert elsewhere["status"] == "PENDING"
    assert elsewhere["region"] == "us-west-2"
    assert elsewhere["term_start"].startswith(_instant_prefix(AUGUST_START))
    assert_cents(elsewhere["committed_capacity_cents"], 36000, "committed_capacity_cents")

    still_pending = validate_success(api.get_commitment(base["id"], CONTROLLER_HEADERS))
    assert still_pending["status"] == "PENDING"
    assert still_pending["region"] == "us-east-1"

    _, west = validate_paginated(
        api.list_commitments(CONTROLLER_HEADERS, {"region": "us-west-2"})
    )
    assert west["total_count"] == 1


def test_the_same_padded_term_of_another_commitment_type_is_not_a_conflict(api):
    """A reserved instance may take the instants the savings plan's pad forbids.

    PRD §2.5: "Because the buffer is applied first, abutting terms are rejected
    here — the opposite of the allocation-run rule."

    Design: Difficulty/resource_temporal_overlap/commitment_terms_closed_interval_with_twenty_four_hour_buffer
    """
    base = _pending_us_east_savings_plan(api)

    validate_error(
        api.create_commitment(
            factories.commitment_payload(
                commitment_type="SAVINGS_PLAN",
                covered_resource_kind=None,
                region="us-east-1",
                term_start=PADDED_END_INSTANT,
                term_end="2026-09-15T00:00:00Z",
                hourly_commit_cents=50,
            ),
            CONTROLLER_HEADERS,
        ),
        ApiErrorId.COMMITMENT_WINDOW_CONFLICT.value,
        409,
    )

    other_type = validate_success(
        api.create_commitment(
            factories.commitment_payload(
                commitment_type="RESERVED_INSTANCE",
                covered_resource_kind="COMPUTE",
                region="us-east-1",
                term_start=AUGUST_START,
                term_end="2026-09-15T00:00:00Z",
                hourly_commit_cents=50,
            ),
            CONTROLLER_HEADERS,
        ),
        201,
    )
    assert other_type["status"] == "PENDING"
    assert other_type["commitment_type"] == "RESERVED_INSTANCE"
    assert other_type["covered_resource_kind"] == "COMPUTE"
    assert other_type["term_start"].startswith(_instant_prefix(AUGUST_START))
    assert_cents(other_type["committed_capacity_cents"], 36000, "committed_capacity_cents")

    unchanged = validate_success(api.get_commitment(base["id"], CONTROLLER_HEADERS))
    assert unchanged["status"] == "PENDING"
    assert unchanged["commitment_type"] == "SAVINGS_PLAN"
    assert unchanged["covered_resource_kind"] is None

    _, reserved = validate_paginated(
        api.list_commitments(CONTROLLER_HEADERS, {"commitment_type": "RESERVED_INSTANCE"})
    )
    assert reserved["total_count"] == 1
