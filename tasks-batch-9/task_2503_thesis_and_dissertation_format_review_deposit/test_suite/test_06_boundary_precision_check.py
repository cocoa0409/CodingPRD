"""Values sitting exactly on a published threshold, and one hundredth either side.

A defect score of exactly 12.00 mandates revisions while 11.95 is accepted, and an
adjusted similarity of exactly 18.00 flags while 17.99 clears.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_instant
from test_helpers.factories import format_review_decision_payload
from test_helpers.test_users import ANALYST_ONE_USER_ID, TEST_USERS

REGISTRAR = TEST_USERS["registrar_headers"]
ANALYST_ONE = TEST_USERS["analyst_headers"]


def _pending_cycle_on_a_100_page_document() -> dict:
    """A cleared 100-page document whose cycle 1 awaits the analyst's decision."""
    world = fx.setup_open_format_cycle(
        cycle_clock="2026-10-05T09:00:00Z",
        thesis_overrides={"title": "Exactly Twelve", "page_count": 100},
    )
    fx.set_clock("2026-10-12T09:00:00Z")
    return world


def test_defect_score_of_exactly_twelve_refuses_the_acceptance(api: ApiClient) -> None:
    """One critical, five major and one minor defect score 12.00 and block accept.

    PRD §3.5: "And the computed `severity_weighted_defect_score` must be strictly below 12.00 — a score of exactly 12.00 already mandates revisions — otherwise the acceptance is refused with `ERR_DEFECT_SCORE_REQUIRES_REVISIONS` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/defect_score_exactly_at_threshold_blocks_accept
    """
    world = _pending_cycle_on_a_100_page_document()

    validate_error(
        api.decide_format_review(
            world["format_review"]["id"],
            format_review_decision_payload("ACCEPT", 1, 5, 1),
            ANALYST_ONE,
        ),
        "ERR_DEFECT_SCORE_REQUIRES_REVISIONS",
        422,
    )

    cycle = get_success_data(
        api.get_format_review(world["format_review"]["id"], REGISTRAR)
    )
    assert cycle["status"] == "PENDING_REVIEW"
    assert cycle["severity_weighted_defect_score"] == pytest.approx(0.0, abs=0.001)
    assert cycle["decided_at"] is None
    assert cycle["decision"] is None

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "UNDER_FORMAT_REVIEW"
    assert thesis["accepted_at"] is None


def test_defect_score_one_hundredth_below_the_threshold_is_accepted(
    api: ApiClient,
) -> None:
    """Two critical, one major and ten minor defects score 11.95 and are accepted.

    PRD §3.5: "When all four pass, the cycle moves `PENDING_REVIEW → ACCEPTED` with `decision` recorded as `ACCEPT`, `decided_at` and `decided_by_user_id` written, the score and `turnaround_bdays` written, `revision_due_at` left null, `analyst_turnaround_bdays_total` recomputed, the document advanced `UNDER_FORMAT_REVIEW → FORMAT_ACCEPTED` with `accepted_at` set to the current logical instant, and clearance recomputed with the format-acceptance item satisfied under both variants."

    Design: Difficulty/boundary_precision_check/defect_score_exactly_at_threshold_blocks_accept
    """
    world = _pending_cycle_on_a_100_page_document()

    cycle = fx.decide_format_review(
        world,
        world["format_review"],
        decision="ACCEPT",
        critical_defect_count=2,
        major_defect_count=1,
        minor_defect_count=10,
    )
    assert cycle["severity_weighted_defect_score"] == pytest.approx(11.95, abs=0.001)
    assert cycle["status"] == "ACCEPTED"
    assert cycle["turnaround_bdays"] == 5
    assert cycle["revision_due_at"] is None
    assert cycle["decided_by_user_id"] == ANALYST_ONE_USER_ID

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["workflow_state"] == "FORMAT_ACCEPTED"
    assert_instant(thesis["accepted_at"], "2026-10-12T09:00:00Z", "accepted_at")
    assert thesis["analyst_turnaround_bdays_total"] == 5


def _document_awaiting_its_first_screening() -> dict:
    """A document under format review that has never been screened."""
    return fx.setup_open_format_cycle(
        cycle_clock="2026-10-05T09:00:00Z",
        with_screening=False,
        thesis_overrides={"title": "Exactly Eighteen"},
    )


def test_adjusted_similarity_one_hundredth_below_the_tolerance_clears(
    api: ApiClient,
) -> None:
    """A raw 22.50 less 4.51 quoted points leaves 17.99, which clears.

    PRD §3.6: "The institution's tolerance is 18.00 per cent: the screening resolves to `FLAGGED` when `adjusted_similarity_pct` is at least 18.00 and to `CLEARED` when it is below, so exactly 18.00 flags."

    Design: Difficulty/boundary_precision_check/adjusted_similarity_exactly_at_flag_threshold_flags
    """
    world = _document_awaiting_its_first_screening()

    cleared = fx.record_screening(
        world, similarity_pct=22.5, excluded_quoted_pct=4.51
    )
    assert cleared["adjusted_similarity_pct"] == pytest.approx(17.99, abs=0.001)
    assert cleared["status"] == "CLEARED"
    assert_instant(cleared["screened_at"], "2026-10-05T09:00:00Z", "screened_at")

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["integrity_state"] == "SCREEN_CLEARED"


def test_adjusted_similarity_exactly_at_the_tolerance_flags_and_supersedes(
    api: ApiClient,
) -> None:
    """A raw 22.50 less 4.50 quoted points leaves exactly 18.00, which flags.

    PRD §3.6: "Any earlier screening for the same document whose `status` is `CLEARED` or `FLAGGED` is moved to `SUPERSEDED`, so exactly one screening ever carries the governing result."

    Design: Difficulty/boundary_precision_check/adjusted_similarity_exactly_at_flag_threshold_flags
    """
    world = _document_awaiting_its_first_screening()
    cleared = fx.record_screening(world, similarity_pct=22.5, excluded_quoted_pct=4.51)

    flagged = fx.record_screening(world, similarity_pct=22.5, excluded_quoted_pct=4.5)
    assert flagged["adjusted_similarity_pct"] == pytest.approx(18.00, abs=0.001)
    assert flagged["status"] == "FLAGGED"

    screenings = get_success_data(
        api.list_thesis_integrity_screenings(world["thesis"]["id"], REGISTRAR)
    )
    assert [row["id"] for row in screenings] == [cleared["id"], flagged["id"]]
    assert screenings[0]["status"] == "SUPERSEDED"

    thesis = get_success_data(api.get_thesis(world["thesis"]["id"], REGISTRAR))
    assert thesis["integrity_state"] == "SCREEN_FLAGGED"
    assert thesis["workflow_state"] == "UNDER_FORMAT_REVIEW"
