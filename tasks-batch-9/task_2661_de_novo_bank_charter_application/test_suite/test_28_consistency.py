"""
Visibility: everything a write cascades into is already true in the very next read.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    COUNSEL_HEADERS,
    INSURANCE_EXAMINER_HEADERS,
    fixtures as fx,
)
from test_helpers.assertions import assert_fields_equal
from test_helpers.factories import filing_decision_payload
from test_helpers.types import (
    AUTHORITY_CHARTERING,
    BLOCKED_REASON_NONE,
    DECISION_CONDITIONALLY_APPROVED,
    FILING_CONDITIONALLY_APPROVED,
    PLAN_PINNED,
    STAGE_CONDITIONALLY_APPROVED,
    STAGE_UNDER_REVIEW,
)


# ---------------------------------------------------------------------------
# Corner / consistency_model
# ---------------------------------------------------------------------------
def test_the_cascaded_stage_is_already_true_in_the_very_next_read(api):
    """
    The chartering authority has already blessed the application, and the plan it pinned is
    visible as pinned without any waiting; the project nevertheless sits under review, because
    the stage is compound and one blessing is half of it. The deposit insurer's decision
    completes the pair, and the reads that follow it are taken once each, with no retry, no
    polling and no intervening write: the project is already at conditional approval with
    nothing blocking it, and the plan is still pinned. Both filings report clearance for
    pre-opening, since no condition has been attached to either.

    PRD: "Derived fields are recomputed **eagerly and immediately** at the end of every request that could change one of their inputs, before the response is serialized, so a response always shows a self-consistent snapshot."
    PRD: "When one operation changes more than one row, every downstream change is part of the same request and must be visible by the time the response is written."
    PRD: "And because the group's stage is compound, the group advances only when **both** filings are `CONDITIONALLY_APPROVED` at the same instant: on that second approval the group moves from `UNDER_REVIEW` to `CONDITIONALLY_APPROVED` with `opening_blocked_reason` reset to `NONE` and its `version` incremented by one."
    PRD: "When the filing's `authority` is `CHARTERING_AUTHORITY`, its pinned business plan moves from `SUBMITTED` to `PINNED` and that plan's `version` increments by one — this is the moment the plan becomes the fixed benchmark for heightened supervision."

    Design: Corner/consistency_model/cascaded_group_stage_is_visible_without_any_re_read_lag
    """
    world = fx.filing_ready_group(api)
    fx.both_filings_filed(api, world)
    fx.decide_filing(
        api, world["f_ca"], DECISION_CONDITIONALLY_APPROVED, AUTHORITY_CHARTERING
    )
    assert_fields_equal(fx.read_group(api, world["group_id"]), stage=STAGE_UNDER_REVIEW)
    assert_fields_equal(fx.read_plan(api, world["plan_id"]), status=PLAN_PINNED)

    insurer = validate_success(
        api.record_filing_decision(
            world["f_di"],
            filing_decision_payload(DECISION_CONDITIONALLY_APPROVED),
            INSURANCE_EXAMINER_HEADERS,
        ),
        expected_status=200,
    )
    assert_fields_equal(insurer, status=FILING_CONDITIONALLY_APPROVED)

    group = validate_success(
        api.get_organizing_group(world["group_id"], COUNSEL_HEADERS), expected_status=200
    )
    assert_fields_equal(
        group,
        stage=STAGE_CONDITIONALLY_APPROVED,
        opening_blocked_reason=BLOCKED_REASON_NONE,
    )
    plan = validate_success(
        api.get_business_plan(world["plan_id"], COUNSEL_HEADERS), expected_status=200
    )
    assert_fields_equal(plan, status=PLAN_PINNED)

    assert_fields_equal(
        fx.read_filing(api, world["f_ca"]), pre_opening_clearance=True
    )
    assert_fields_equal(
        fx.read_filing(api, world["f_di"]), pre_opening_clearance=True
    )
