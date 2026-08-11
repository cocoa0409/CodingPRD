"""Holdover auto-recommendation boundary (PRD §3.8): inclusive >= threshold.

Threshold = min_weeks_committed * 100000 cents. Each test drives the agreement
to holdover-eligible (two settled weeks, min_weeks_committed=2), then files a
known week-2 gross and closes the week so the just-closed week's locked gross
is unambiguous under every reading of "the prior week's locked gross".
"""
from test_helpers import (
    validate_success,
    setup_holdover_eligible_agreement,
    close_week_with_reports,
    TEST_USERS,
)

BOOKER = TEST_USERS["booker_headers"]

MIN_WEEKS = 2
THRESHOLD = MIN_WEEKS * 100000  # 200000 cents


def _latest_decision(api, did, baid):
    data = api.list_holdover_decisions(did, baid, BOOKER).json()["data"]
    assert len(data) == 1, (
        f"expected exactly one automatic recommendation, got {len(data)}: {data}"
    )
    return data[0]


def test_one_cent_below_threshold_recommends_release(api):
    """PRD §3.8: "When the prior week's locked gross is at least the product of
    `min_weeks_committed` and 100000 cents — one thousand dollars per committed week —
    the system records a decision of `AUTO_HOLD`; below that threshold it records
    `AUTO_RELEASE`."
    199999 < 2 * 100000 -> AUTO_RELEASE.

    Design: Difficulty/boundary_precision_check/holdover_threshold_gte_boundary
    """
    env = setup_holdover_eligible_agreement(min_weeks_committed=MIN_WEEKS)
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    close_week_with_reports(did, 2, [(baid, THRESHOLD - 1, 2000)])
    decision = _latest_decision(api, did, baid)
    assert decision["prior_week_gross_cents"] == THRESHOLD - 1
    assert decision["decision"] == "AUTO_RELEASE", (
        f"one cent below the threshold must recommend AUTO_RELEASE, got {decision['decision']}"
    )


def test_exactly_at_threshold_recommends_hold(api):
    """PRD §3.8: "The boundary is inclusive: a gross exactly equal to the threshold
    recommends the hold."
    200000 == 2 * 100000 -> AUTO_HOLD.

    Design: Difficulty/boundary_precision_check/holdover_threshold_gte_boundary
    """
    env = setup_holdover_eligible_agreement(min_weeks_committed=MIN_WEEKS)
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    close_week_with_reports(did, 2, [(baid, THRESHOLD, 2000)])
    decision = _latest_decision(api, did, baid)
    assert decision["prior_week_gross_cents"] == THRESHOLD
    assert decision["decision"] == "AUTO_HOLD", (
        f"exactly at the threshold must recommend AUTO_HOLD, got {decision['decision']}"
    )


def test_one_cent_above_threshold_recommends_hold(api):
    """PRD §3.8: "When the prior week's locked gross is at least the product of
    `min_weeks_committed` and 100000 cents — one thousand dollars per committed week —
    the system records a decision of `AUTO_HOLD`; below that threshold it records
    `AUTO_RELEASE`."
    200001 > 2 * 100000 -> AUTO_HOLD.

    Design: Difficulty/boundary_precision_check/holdover_threshold_gte_boundary
    """
    env = setup_holdover_eligible_agreement(min_weeks_committed=MIN_WEEKS)
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    close_week_with_reports(did, 2, [(baid, THRESHOLD + 1, 2000)])
    decision = _latest_decision(api, did, baid)
    assert decision["prior_week_gross_cents"] == THRESHOLD + 1
    assert decision["decision"] == "AUTO_HOLD", (
        f"one cent above the threshold must recommend AUTO_HOLD, got {decision['decision']}"
    )
