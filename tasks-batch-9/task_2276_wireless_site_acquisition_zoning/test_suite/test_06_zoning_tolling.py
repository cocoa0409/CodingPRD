"""The completeness loop is re-entrant and each cure accrues its own tolled days."""

from typing import Any, Dict

from test_helpers import constants as C
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_fields, assert_instant, ok
from test_helpers.constants import iso

UNTOLLED_DEADLINE = iso("2026-10-30")
FIRST_CURE_DEADLINE = iso("2026-11-14")
SECOND_CURE_DEADLINE = iso("2026-11-24")
FIRST_INCOMPLETE_DAY = iso("2026-08-16")
SECOND_INCOMPLETE_DAY = iso("2026-08-26")
CONDITIONAL_USE_REVIEW_DAYS = 90


def _application_under_review(api: ApiClient) -> Dict[str, Any]:
    """A submitted `CONDITIONAL_USE` filing that has been found complete."""
    chain = S.executed_lease_chain(api)
    application = S.create_zoning_application(api, chain["cand_id"])
    za_id = application["id"]
    S.add_visual_simulations(api, za_id)
    S.submit_zoning_application(api, za_id)
    S.set_completeness(api, za_id, "COMPLETE")
    chain["za_id"] = za_id
    return chain


def test_two_cures_accrue_fifteen_then_ten_days_of_tolling(api: ApiClient) -> None:
    """The second pass through the loop adds its own days on top of the first.

    PRD: "`CURED` is accepted only from `INCOMPLETE`, requires
    `incomplete_since_date` to be set, and moves the application `INCOMPLETE →
    UNDER_REVIEW`; it adds to `tolled_days` the whole UTC days elapsed from
    `incomplete_since_date` to the logical clock, discarding any partial day,
    recomputes `shot_clock_deadline_date` with the new total, and clears
    `incomplete_since_date` back to null."

    PRD: "The `INCOMPLETE → UNDER_REVIEW → INCOMPLETE` loop is repeatable, and each
    cure adds its own days to the running total, in cure order."

    Design: Difficulty/non_linear_state_machine/zoning_tolling_cycle_repeats_and_accrues_days
    """
    chain = _application_under_review(api)
    za_id = chain["za_id"]

    S.set_completeness(api, za_id, "INCOMPLETE")
    S.set_clock(api, FIRST_INCOMPLETE_DAY)
    first_cure = ok(
        api.set_completeness(za_id, {"outcome": "CURED"}, headers=S.planner())
    )
    assert_fields(first_cure, tolled_days=15, status="UNDER_REVIEW")
    assert_instant(
        first_cure["shot_clock_deadline_date"],
        FIRST_CURE_DEADLINE,
        "shot_clock_deadline_date",
    )

    S.set_completeness(api, za_id, "INCOMPLETE")
    S.set_clock(api, SECOND_INCOMPLETE_DAY)
    second_cure = ok(
        api.set_completeness(za_id, {"outcome": "CURED"}, headers=S.planner())
    )
    assert_fields(second_cure, tolled_days=25, status="UNDER_REVIEW")
    assert_instant(
        second_cure["shot_clock_deadline_date"],
        SECOND_CURE_DEADLINE,
        "shot_clock_deadline_date",
    )
    assert second_cure["incomplete_since_date"] is None, (
        "a cure clears the tolling origin"
    )


def test_the_incomplete_determination_stamps_the_tolling_origin(api: ApiClient) -> None:
    """Tolling accrues from the stamped origin, and the shot-clock read exposes the total.

    PRD: "`INCOMPLETE` is accepted from either `SUBMITTED` or `UNDER_REVIEW`, moves
    the application to `INCOMPLETE`, and stamps `incomplete_since_date` with the
    logical clock — the origin from which tolling accrues."

    PRD: "It reports `review_days`, the nominal review-day count the jurisdiction
    publishes for this application's `application_type`; `tolled_days`, the
    accumulated tolling; `shot_clock_deadline_date` as stored; `days_remaining`, the
    whole days from the current logical clock to that deadline, which goes negative
    once the deadline has passed; and `deemed_grantable`, true exactly when the
    logical clock is strictly after `shot_clock_deadline_date`."

    Design: Difficulty/non_linear_state_machine/zoning_tolling_cycle_repeats_and_accrues_days
    """
    chain = _application_under_review(api)
    za_id = chain["za_id"]

    before = ok(api.get_zoning_application(za_id, headers=S.planner()))
    assert_fields(before, tolled_days=0)
    assert_instant(
        before["shot_clock_deadline_date"], UNTOLLED_DEADLINE, "shot_clock_deadline_date"
    )

    incomplete = ok(
        api.set_completeness(
            za_id, {"outcome": "INCOMPLETE", "note": "site plan missing"}, headers=S.planner()
        )
    )
    assert_fields(incomplete, status="INCOMPLETE", tolled_days=0)
    assert_instant(
        incomplete["incomplete_since_date"], C.CLOCK_DEFAULT, "incomplete_since_date"
    )

    S.set_clock(api, FIRST_INCOMPLETE_DAY)
    S.set_completeness(api, za_id, "CURED")
    S.set_completeness(api, za_id, "INCOMPLETE")
    S.set_clock(api, SECOND_INCOMPLETE_DAY)
    S.set_completeness(api, za_id, "CURED")

    shot_clock = ok(api.get_shot_clock(za_id, headers=S.planner()))
    assert_fields(
        shot_clock,
        review_days=CONDITIONAL_USE_REVIEW_DAYS,
        tolled_days=25,
        deemed_grantable=False,
    )
    assert_instant(
        shot_clock["shot_clock_deadline_date"],
        SECOND_CURE_DEADLINE,
        "shot_clock_deadline_date",
    )
