"""Two interval regimes: closed integer plan-year intervals where adjacency is
permitted, and half-open measurement windows guarded by a quiet buffer."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    current_employer_version,
    file_contribution_history,
    file_valuation,
    get_record,
    get_valuation,
    register_controlled_group,
    register_employer,
    register_plan,
)
from test_helpers.test_users import FUND_ADMINISTRATOR_HEADERS, PLAN_ACTUARY_HEADERS
from test_helpers.types import AllocationMethod, CommonControlBasis, DeMinimisVariant

ADJACENT_HISTORY = (
    {
        "plan_year_start": 2021,
        "plan_year_end": 2023,
        "contribution_base_units": 30_000,
        "contribution_amount_cents": 30_000_000,
        "contribution_rate_cents_per_cbu": 1_000,
    },
    {
        "plan_year_start": 2024,
        "plan_year_end": 2025,
        "contribution_base_units": 20_000,
        "contribution_amount_cents": 20_000_000,
        "contribution_rate_cents_per_cbu": 1_000,
    },
)

INCUMBENT_WINDOW = {
    "measurement_window_start": "2025-01-01T00:00:00Z",
    "measurement_window_end": "2025-10-01T00:00:00Z",
    "uvb_total_cents": 6_000_000_000,
    "uvb_pool_cents": 600_000_000,
    "all_employer_contributions_cents": 1_500_000_000,
    "all_employer_cbu": 1_500_000,
    "interest_rate_bps": 725,
}

# The incumbent window closes on 1 October 2025; a successor may not begin before
# 31 October 2025, which is that end advanced by the thirty-day quiet buffer.
INSIDE_THE_BUFFER = "2025-10-15T00:00:00Z"
EXACTLY_THIRTY_DAYS_LATER = "2025-10-31T00:00:00Z"


def _employer_with_adjacent_records(api):
    plan = register_plan(
        api, allocation_method=AllocationMethod.ROLLING_5.value, interest_rate_bps=650
    )
    group = register_controlled_group(
        api, common_control_basis=CommonControlBasis.PARENT_SUBSIDIARY.value
    )
    employer = register_employer(
        api, plan["id"], group["id"], obligation_start_year=2021, cba_count=1
    )
    records = file_contribution_history(api, employer["id"], ADJACENT_HISTORY)
    return employer, records


def _plan_with_one_window(api):
    plan = register_plan(
        api,
        allocation_method=AllocationMethod.MODIFIED_PRESUMPTIVE.value,
        de_minimis_variant=DeMinimisVariant.PLAN_ELECTED_HIGH.value,
        interest_rate_bps=725,
    )
    incumbent = file_valuation(api, plan["id"], 2025, **INCUMBENT_WINDOW)
    return plan, incumbent


def _successor_window(plan_id, start):
    return factories.valuation_payload(
        plan_id,
        2026,
        measurement_window_start=start,
        measurement_window_end="2026-06-01T00:00:00Z",
        uvb_total_cents=6_100_000_000,
        uvb_pool_cents=610_000_000,
        all_employer_contributions_cents=1_500_000_000,
        all_employer_cbu=1_500_000,
        interest_rate_bps=725,
        certify_on_create=True,
    )


class TestContributionIntervalsAreClosedAndMayTouch:
    def test_two_touching_intervals_are_both_accepted(self, api):
        """An interval ending in 2023 and an interval starting in 2024 touch without sharing
        a plan year, so both records certify.

        PRD 3.3: "Touching endpoints are explicitly permitted: an existing interval ending
        in some year and a new interval starting in the following year do not conflict."

        Design: Difficulty/resource_temporal_overlap/contribution_record_plan_year_intervals_are_closed_and_adjacency_is_allowed
        """
        employer, records = _employer_with_adjacent_records(api)
        first, second = records

        assert get_record(api, first["id"])["status"] == "CERTIFIED"
        assert first["plan_year_end"] == 2023
        assert get_record(api, second["id"])["status"] == "CERTIFIED"
        assert second["plan_year_start"] == 2024

        _data, meta = validate_paginated(
            api.list_contribution_records(
                FUND_ADMINISTRATOR_HEADERS, {"employer_id": employer["id"]}
            )
        )
        assert meta["total_count"] == 2

    def test_an_interval_sharing_years_with_both_incumbents_is_refused(self, api):
        """The interval 2023 through 2024 shares 2023 with one certified record and 2024
        with the other, so it is refused and nothing about the employer moves.

        PRD 3.3: "A filing is rejected with `ERR_CONTRIBUTION_PERIOD_OVERLAP` when its
        interval shares any plan year with the interval of any other certified record of the
        same employer."

        Design: Difficulty/resource_temporal_overlap/contribution_record_plan_year_intervals_are_closed_and_adjacency_is_allowed
        """
        employer, _records = _employer_with_adjacent_records(api)
        version_before = current_employer_version(api, employer["id"])

        response = api.create_contribution_record(
            factories.contribution_record_payload(
                employer["id"],
                2023,
                2024,
                version_before,
                contribution_base_units=5_000,
                contribution_amount_cents=5_000_000,
                contribution_rate_cents_per_cbu=1_000,
            ),
            FUND_ADMINISTRATOR_HEADERS,
        )
        validate_error(response, ApiErrorId.CONTRIBUTION_PERIOD_OVERLAP.value, 409)

        assert current_employer_version(api, employer["id"]) == version_before
        _data, meta = validate_paginated(
            api.list_contribution_records(
                FUND_ADMINISTRATOR_HEADERS, {"employer_id": employer["id"]}
            )
        )
        assert meta["total_count"] == 2


class TestValuationWindowsCarryAQuietBuffer:
    def test_a_window_inside_the_quiet_buffer_is_refused(self, api):
        """A window starting on 15 October 2025 is disjoint from an incumbent ending on
        1 October 2025 in raw terms, yet it falls inside the thirty-day buffer.

        PRD 3.2: "A new valuation is rejected with `ERR_VALUATION_WINDOW_CONFLICT` when,
        against any existing `DRAFT` or `CERTIFIED` valuation of the same plan, its
        `measurement_window_start` falls earlier than that other valuation's
        `measurement_window_end` advanced by a thirty-day quiet buffer *and* its
        `measurement_window_end` falls later than that other valuation's
        `measurement_window_start`."

        Design: Difficulty/resource_temporal_overlap/valuation_measurement_windows_are_half_open_with_a_thirty_day_quiet_buffer
        """
        plan, incumbent = _plan_with_one_window(api)

        response = api.create_plan_year_valuation(
            _successor_window(plan["id"], INSIDE_THE_BUFFER), PLAN_ACTUARY_HEADERS
        )
        validate_error(response, ApiErrorId.VALUATION_WINDOW_CONFLICT.value, 409)

        assert get_valuation(api, incumbent["id"])["status"] == "CERTIFIED"
        _data, meta = validate_paginated(
            api.list_plan_year_valuations(FUND_ADMINISTRATOR_HEADERS, {"plan_id": plan["id"]})
        )
        assert meta["total_count"] == 1

    def test_a_window_beginning_exactly_thirty_days_after_the_incumbent_is_accepted(self, api):
        """Moving the same window's start to 31 October 2025 clears the buffer exactly, and
        the successor valuation files and certifies alongside the untouched incumbent.

        PRD 3.2: "A window that begins exactly thirty days after another window's end is
        therefore permitted, as is a window that ends exactly when another begins."

        Design: Difficulty/resource_temporal_overlap/valuation_measurement_windows_are_half_open_with_a_thirty_day_quiet_buffer
        """
        plan, incumbent = _plan_with_one_window(api)
        refused = api.create_plan_year_valuation(
            _successor_window(plan["id"], INSIDE_THE_BUFFER), PLAN_ACTUARY_HEADERS
        )
        validate_error(refused, ApiErrorId.VALUATION_WINDOW_CONFLICT.value, 409)

        successor = validate_success(
            api.create_plan_year_valuation(
                _successor_window(plan["id"], EXACTLY_THIRTY_DAYS_LATER), PLAN_ACTUARY_HEADERS
            ),
            201,
        )
        assert successor["measurement_window_start"].startswith("2025-10-31T00:00:00")
        assert successor["status"] == "CERTIFIED"
        assert get_valuation(api, incumbent["id"])["status"] == "CERTIFIED"

        _data, meta = validate_paginated(
            api.list_plan_year_valuations(FUND_ADMINISTRATOR_HEADERS, {"plan_id": plan["id"]})
        )
        assert meta["total_count"] == 2
