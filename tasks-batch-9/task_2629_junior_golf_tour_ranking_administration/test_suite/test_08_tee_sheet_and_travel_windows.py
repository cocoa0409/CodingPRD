"""Two scarce resources with half-open and padded edges: the starting grid and the
junior's own travel calendar.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_SCHEDULE_CONFLICT, ERR_TEE_SLOT_FULL
from test_helpers.test_users import CHIEF_REFEREE, TOUR_ADMIN, member_headers
from test_helpers.types import ENTRY_ACCEPTED, ENTRY_APPLIED, ROUND_SCHEDULED

TEE_1300 = "2026-09-10T13:00:00Z"
TEE_1305 = "2026-09-10T13:05:00Z"
TEE_1310 = "2026-09-10T13:10:00Z"
TEE_ROUND_TWO_1305 = "2026-09-11T13:05:00Z"


def _tee_sheet_field(api):
    """A four-strong field on a course whose tee slots hold two cards each."""
    ctx = fx.field_set(
        api, member_count=4,
        member_overrides={3: {"handicap_index": 7.0,
                              "handicap_effective_date": "2026-07-18"}},
        name="Tee Sheet Regional", field_size_limit=4, tee_group_size=2,
    )
    assert ctx["tournament"]["accepted_count"] == 4
    first, second = ctx["member_ids"][0], ctx["member_ids"][1]
    ctx["existing"] = [
        fx.create_round(api, ctx["entry_ids"][0], second, 1, TEE_1305),
        fx.create_round(api, ctx["entry_ids"][1], first, 1, TEE_1310),
        fx.create_round(api, ctx["entry_ids"][0], second, 2, TEE_ROUND_TWO_1305),
    ]
    return ctx


class TestTeeSlotCapacityWindow:
    """The slot runs from the requested tee time up to, but not including, its end."""

    def test_a_card_exactly_one_interval_later_is_adjacent_and_admitted(self, api):
        """The 13:00 window holds the 13:05 card but not the 13:10 one, so one seat is free.

        PRD: "A round whose `tee_time` is exactly `tee_interval_minutes` later than
        an existing group is **adjacent, not overlapping**, and is allowed."

        Design: Difficulty/resource_temporal_overlap/tee_slot_half_open_upper_bound_and_group_capacity
        """
        ctx = _tee_sheet_field(api)

        added = validate_success(
            api.create_round(
                f.round_payload(ctx["entry_ids"][2], 1, TEE_1300, ctx["member_ids"][0]),
                CHIEF_REFEREE,
            ),
            201,
        )
        assert added["status"] == ROUND_SCHEDULED
        assert added["tee_time"] == TEE_1300

        for existing in ctx["existing"]:
            assert fx.read_round(api, existing["id"])["status"] == ROUND_SCHEDULED

    def test_the_capacity_is_aggregate_across_the_whole_slot(self, api):
        """Once 13:00 and 13:05 both sit in the window, a group of two is full.

        PRD: "For the requested `round_number`, the number of existing rounds of
        that tournament whose `tee_time` falls inside the interval beginning at the
        requested `tee_time` and extending forward by `tee_interval_minutes` —
        including the starting instant and excluding the ending instant — must be
        fewer than the tournament's `tee_group_size`."

        Design: Difficulty/resource_temporal_overlap/tee_slot_half_open_upper_bound_and_group_capacity
        """
        ctx = _tee_sheet_field(api)
        validate_success(
            api.create_round(
                f.round_payload(ctx["entry_ids"][2], 1, TEE_1300, ctx["member_ids"][0]),
                CHIEF_REFEREE,
            ),
            201,
        )

        validate_error(
            api.create_round(
                f.round_payload(ctx["entry_ids"][3], 1, TEE_1300, ctx["member_ids"][0]),
                CHIEF_REFEREE,
            ),
            ERR_TEE_SLOT_FULL,
            409,
        )
        assert fx.read_entry(api, ctx["entry_ids"][3])["entry_status"] == ENTRY_ACCEPTED


def _travel_window_season(api):
    """A junior holding a slot in an event that runs 10 to 11 September."""
    ctx = fx.verified_roster(api, member_count=1)
    held = fx.create_tournament(api, ctx["season_id"], name="Week One Regional",
                                field_size_limit=1)
    adjacent = fx.create_tournament(
        api, ctx["season_id"], name="Adjacent Regional", field_size_limit=4,
        start_date="2026-09-12", end_date="2026-09-13",
        entry_close_at="2026-09-08T00:00:00Z",
        withdrawal_deadline_at="2026-09-09T00:00:00Z",
    )
    gapped = fx.create_tournament(
        api, ctx["season_id"], name="Gapped Regional", field_size_limit=4,
        start_date="2026-09-13", end_date="2026-09-14",
        entry_close_at="2026-09-08T00:00:00Z",
        withdrawal_deadline_at="2026-09-09T00:00:00Z",
    )
    for tournament in (held, adjacent, gapped):
        validate_success(api.open_entries(tournament["id"], TOUR_ADMIN), 200)

    entry = fx.submit_entry(api, ctx["member_ids"][0], held["id"])
    fx.set_clock(api, fx.CLOCK_AFTER_ENTRY_CLOSE)
    validate_success(api.close_entries(held["id"], TOUR_ADMIN), 200)
    field = validate_success(api.set_field(held["id"], TOUR_ADMIN), 200)
    assert field["accepted_count"] == 1
    assert fx.read_entry(api, entry["id"])["entry_status"] == ENTRY_ACCEPTED

    ctx["adjacent"] = adjacent
    ctx["gapped"] = gapped
    return ctx


class TestTravelWindowOverlap:
    """One day of padding on each side of a commitment, and not two."""

    def test_an_event_starting_the_day_after_the_finish_is_refused(self, api):
        """The travel window reaches 12 September, so the adjacent event conflicts.

        PRD: "The other tournament's travel window runs from one day before its
        `start_date` to one day after its `end_date` inclusive, and this
        tournament's dates are its closed interval from `start_date` to `end_date`
        inclusive; if those two ranges share even a single day, the submission is
        refused with `ERR_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/member_travel_window_blocks_back_to_back_but_not_gapped_entry
        """
        ctx = _travel_window_season(api)

        validate_error(
            api.submit_entry(
                f.entry_payload(ctx["member_ids"][0], ctx["adjacent"]["id"]),
                member_headers(ctx["member_ids"][0]),
            ),
            ERR_SCHEDULE_CONFLICT,
            409,
        )
        assert fx.read_tournament(api, ctx["adjacent"]["id"])["entry_count"] == 0

    def test_an_event_two_days_after_the_finish_is_admitted(self, api):
        """The padding stops one day short, so 13 September is free.

        PRD: "The one-day padding on either side of the existing commitment is
        deliberate: juniors travel to these events, and a Sunday finish two states
        away does not permit a Monday first tee."

        Design: Difficulty/resource_temporal_overlap/member_travel_window_blocks_back_to_back_but_not_gapped_entry
        """
        ctx = _travel_window_season(api)

        entry = fx.submit_entry(api, ctx["member_ids"][0], ctx["gapped"]["id"])
        assert entry["entry_status"] == ENTRY_APPLIED

        gapped = fx.read_tournament(api, ctx["gapped"]["id"])
        assert gapped["entry_count"] == 1
        assert gapped["applied_count"] == 1
