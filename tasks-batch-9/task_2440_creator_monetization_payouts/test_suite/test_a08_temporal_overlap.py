"""Two window shapes coexist: one half-open, one fully closed."""

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as err
from test_helpers import factories as fac
from test_helpers.assertions import assert_total_count
from test_helpers.constants import (
    ELIGIBILITY_ELIGIBLE,
    INVESTIGATION_CLEARED,
    INVESTIGATION_OPEN,
    PAYOUT_STATE_ACCRUING,
    PERIOD_OPEN,
)
from test_helpers.fixtures import (
    close,
    eligible_creator,
    july_period,
    refresh_creator,
    tips_product,
)
from test_helpers.test_users import ADMIN, FINANCE, REVIEWER, REVIEWER_ALT


def test_a_period_may_start_exactly_where_its_predecessor_ends(api):
    """Abutment is legal but a single second of overlap is not.

    A window pulled back one second onto July's last instant is refused, a
    window wholly inside July is refused, and a window starting precisely at
    July's excluded end is accepted and open.

    Design: Difficulty/resource_temporal_overlap/earnings_period_half_open_interval_permits_abutment
    """
    july_period(api)

    validate_error(
        api.create_period(
            fac.period_payload(
                label="2026-08-early",
                period_start="2026-07-31T23:59:59Z",
                period_end="2026-09-01T00:00:00Z",
            ),
            ADMIN,
        ),
        err.ERR_PERIOD_WINDOW_OVERLAP,
        409,
    )
    validate_error(
        api.create_period(
            fac.period_payload(
                label="2026-07-inner",
                period_start="2026-07-10T00:00:00Z",
                period_end="2026-07-20T00:00:00Z",
            ),
            ADMIN,
        ),
        err.ERR_PERIOD_WINDOW_OVERLAP,
        409,
    )

    abutting = validate_success(
        api.create_period(
            fac.period_payload(
                label="2026-08",
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-09-01T00:00:00Z",
            ),
            ADMIN,
        ),
        201,
    )
    assert abutting["status"] == PERIOD_OPEN
    assert_total_count(api.list_periods(ADMIN), 2)


def test_the_shared_instant_belongs_to_the_later_period_only(api):
    """The end of a window is excluded and its start is included.

    An accrual at the shared instant routes to the second window while an
    accrual one second earlier stays in the first, and an accrual at the second
    window's own end has nowhere to go.

    Design: Difficulty/resource_temporal_overlap/earnings_period_half_open_interval_permits_abutment
    """
    first = july_period(api)
    creator = eligible_creator(api, display_name="Dot Cal")
    product = tips_product(api)
    second = validate_success(
        api.create_period(
            fac.period_payload(
                label="2026-08",
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-09-01T00:00:00Z",
            ),
            ADMIN,
        ),
        201,
    )

    boundary = validate_success(
        api.create_revenue_event(
            fac.revenue_event_payload(
                creator["id"], product["id"], occurred_at="2026-08-01T00:00:00Z"
            ),
            FINANCE,
        ),
        201,
    )
    assert boundary["period_id"] == second["id"]
    assert boundary["period_id"] != first["id"]

    last = validate_success(
        api.create_revenue_event(
            fac.revenue_event_payload(
                creator["id"], product["id"], occurred_at="2026-07-31T23:59:59Z"
            ),
            FINANCE,
        ),
        201,
    )
    assert last["period_id"] == first["id"]

    validate_error(
        api.create_revenue_event(
            fac.revenue_event_payload(
                creator["id"], product["id"], occurred_at="2026-09-01T00:00:00Z"
            ),
            FINANCE,
        ),
        err.ERR_NO_OPEN_PERIOD_FOR_EVENT,
        422,
    )


def test_a_closed_period_still_reserves_its_window(api):
    """Occupancy does not depend on the period's own status.

    A window inside a period that has already been closed is still refused as
    an overlap, and no third period is stored.

    Design: Difficulty/resource_temporal_overlap/earnings_period_half_open_interval_permits_abutment
    """
    first = july_period(api)
    validate_success(
        api.create_period(
            fac.period_payload(
                label="2026-08",
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-09-01T00:00:00Z",
            ),
            ADMIN,
        ),
        201,
    )
    close(api, first["id"])

    validate_error(
        api.create_period(
            fac.period_payload(
                label="2026-07-retry",
                period_start="2026-07-15T00:00:00Z",
                period_end="2026-07-25T00:00:00Z",
            ),
            ADMIN,
        ),
        err.ERR_PERIOD_WINDOW_OVERLAP,
        409,
    )
    assert_total_count(api.list_periods(ADMIN), 2)


def _baseline_case(api, creator_id):
    return get_success_data(
        api.create_investigation(
            fac.investigation_payload(
                creator_id,
                scope="July window baseline.",
                violation_window_start="2026-07-01T00:00:00Z",
                violation_window_end="2026-07-31T00:00:00Z",
                hold_payouts=False,
            ),
            REVIEWER,
        )
    )


def test_two_cases_collide_when_their_windows_merely_touch(api):
    """Case windows include both endpoints, so touching is overlapping.

    A window opening at the exact instant the first one ends is refused, and the
    same window one second later is accepted and open.

    Design: Difficulty/resource_temporal_overlap/investigation_closed_interval_collides_on_touch_and_releases_on_clear
    """
    creator = eligible_creator(api, display_name="Eli Win")
    baseline = _baseline_case(api, creator["id"])
    assert baseline["state"] == INVESTIGATION_OPEN
    assert baseline["opened_by_user_id"] == "reviewer-r1"

    validate_error(
        api.create_investigation(
            fac.investigation_payload(
                creator["id"],
                scope="Touching at the end instant.",
                violation_window_start="2026-07-31T00:00:00Z",
                violation_window_end="2026-08-15T00:00:00Z",
                hold_payouts=False,
            ),
            REVIEWER,
        ),
        err.ERR_INVESTIGATION_WINDOW_OVERLAP,
        409,
    )

    clear_of_it = validate_success(
        api.create_investigation(
            fac.investigation_payload(
                creator["id"],
                scope="One second clear of the end instant.",
                violation_window_start="2026-07-31T00:00:01Z",
                violation_window_end="2026-08-15T00:00:00Z",
                hold_payouts=False,
            ),
            REVIEWER,
        ),
        201,
    )
    assert clear_of_it["state"] == INVESTIGATION_OPEN


def test_a_window_is_reserved_per_channel_and_only_while_open(api):
    """Another channel may hold the same window, and clearing releases it.

    The identical window is accepted for a second channel, and once the first
    case is cleared the window it had reserved can be claimed again, leaving
    three cases on that channel and no strike.

    Design: Difficulty/resource_temporal_overlap/investigation_closed_interval_collides_on_touch_and_releases_on_clear
    """
    first = eligible_creator(api, display_name="Eli Win")
    second = eligible_creator(api, display_name="Fay Win")
    baseline = _baseline_case(api, first["id"])
    validate_success(
        api.create_investigation(
            fac.investigation_payload(
                first["id"],
                scope="One second clear of the end instant.",
                violation_window_start="2026-07-31T00:00:01Z",
                violation_window_end="2026-08-15T00:00:00Z",
                hold_payouts=False,
            ),
            REVIEWER,
        ),
        201,
    )
    validate_success(
        api.create_investigation(
            fac.investigation_payload(
                second["id"],
                scope="Same window, different creator.",
                violation_window_start="2026-07-01T00:00:00Z",
                violation_window_end="2026-07-31T00:00:00Z",
                hold_payouts=False,
            ),
            REVIEWER,
        ),
        201,
    )

    cleared = validate_success(
        api.clear_investigation(
            baseline["id"],
            fac.clear_payload(finding="No violation in the July window."),
            REVIEWER_ALT,
        )
    )
    assert cleared["state"] == INVESTIGATION_CLEARED
    assert cleared["clawback_base_cents"] == 0

    reopened = validate_success(
        api.create_investigation(
            fac.investigation_payload(
                first["id"],
                scope="Re-opened after the first window was released.",
                violation_window_start="2026-07-01T00:00:00Z",
                violation_window_end="2026-07-31T00:00:00Z",
                hold_payouts=False,
            ),
            REVIEWER,
        ),
        201,
    )
    assert reopened["state"] == INVESTIGATION_OPEN
    assert_total_count(
        api.list_investigations(FINANCE, {"creator_id": first["id"]}), 3
    )

    after = refresh_creator(api, first["id"])
    assert after["payout_state"] == PAYOUT_STATE_ACCRUING
    assert after["active_strike_count"] == 0
    assert after["eligibility_status"] == ELIGIBILITY_ELIGIBLE


def _channel_under_mid_july_case(api):
    creator = eligible_creator(api, display_name="Gus Point")
    product = tips_product(api)
    period = july_period(api)
    get_success_data(
        api.create_investigation(
            fac.investigation_payload(
                creator["id"],
                scope="Mid-July anomaly.",
                violation_window_start="2026-07-10T00:00:00Z",
                violation_window_end="2026-07-20T00:00:00Z",
                hold_payouts=False,
            ),
            REVIEWER,
        )
    )
    return creator, product, period


@pytest.mark.parametrize(
    "occurred_at",
    ["2026-07-10T00:00:00Z", "2026-07-15T00:00:00Z", "2026-07-20T00:00:00Z"],
)
def test_an_accrual_inside_or_on_the_case_window_is_refused(api, occurred_at):
    """Both endpoints of the case window are inclusive for accruals.

    The refused instants all sit inside an open period, so the refusal can only
    come from the case, and nothing is stored.

    Design: Difficulty/resource_temporal_overlap/accrual_blocked_at_both_inclusive_endpoints_of_investigation_window
    """
    creator, product, period = _channel_under_mid_july_case(api)

    validate_error(
        api.create_revenue_event(
            fac.revenue_event_payload(
                creator["id"], product["id"], occurred_at=occurred_at
            ),
            FINANCE,
        ),
        err.ERR_ACCRUAL_UNDER_INVESTIGATION,
        409,
    )
    assert_total_count(
        api.list_revenue_events(FINANCE, {"creator_id": creator["id"]}), 0
    )
    assert validate_success(api.get_period(period["id"], FINANCE))["status"] == (
        PERIOD_OPEN
    )


def test_the_instants_one_second_outside_each_endpoint_still_accrue(api):
    """One second before the start and one second after the end are clear.

    Both accruals earn their 5000-cent share and land in the open period, and
    the ledger holds exactly the two of them.

    Design: Difficulty/resource_temporal_overlap/accrual_blocked_at_both_inclusive_endpoints_of_investigation_window
    """
    creator, product, period = _channel_under_mid_july_case(api)

    before = validate_success(
        api.create_revenue_event(
            fac.revenue_event_payload(
                creator["id"], product["id"], occurred_at="2026-07-09T23:59:59Z"
            ),
            FINANCE,
        ),
        201,
    )
    assert before["creator_share_cents"] == 5000
    assert before["period_id"] == period["id"]

    after = validate_success(
        api.create_revenue_event(
            fac.revenue_event_payload(
                creator["id"], product["id"], occurred_at="2026-07-20T00:00:01Z"
            ),
            FINANCE,
        ),
        201,
    )
    assert after["creator_share_cents"] == 5000

    assert refresh_creator(api, creator["id"])["ledger_balance_cents"] == 10000
    assert_total_count(
        api.list_revenue_events(FINANCE, {"creator_id": creator["id"]}), 2
    )
