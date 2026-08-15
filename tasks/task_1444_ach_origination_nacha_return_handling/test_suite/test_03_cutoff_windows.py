"""Cutoff-window interval semantics: half-open overlap vs. adjacency."""
from test_helpers import (
    ApiErrorId,
    assert_cutoff_window,
    create_cutoff_window_payload,
    define_cutoff_window,
    validate_error,
    validate_success,
)


class TestCutoffWindowAdjacency:
    def test_overlapping_same_day_window_rejected(self, api, operations_headers):
        """PRD 3.2: "A duplicate kind, a close not strictly later than its open,
        or an overlapping same-day interval is rejected with
        `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/cutoff_window_half_open_adjacency
        """
        define_cutoff_window(window_kind="SAME_DAY_1", opens_at_utc="09:00",
                             closes_at_utc="12:00", per_entry_fee_cents=150,
                             file_fee_cents=500, large_entry_surcharge_cents=400)

        res = api.create_cutoff_window(
            create_cutoff_window_payload("SAME_DAY_2", "11:00", "14:00", 130,
                                         450, 300),
            operations_headers)
        validate_error(res, ApiErrorId.ERR_WINDOW_OVERLAP, expected_status=409)

    def test_adjacent_same_day_window_accepted(self, api, operations_headers):
        """PRD 3.2: "Among the three same-day kinds, the half-open time
        intervals — open inclusive, close exclusive — must not overlap, though
        adjacency is allowed: one window closing at exactly the instant another
        opens is legal."

        Design: Difficulty/resource_temporal_overlap/cutoff_window_half_open_adjacency
        """
        define_cutoff_window(window_kind="SAME_DAY_1", opens_at_utc="09:00",
                             closes_at_utc="12:00", per_entry_fee_cents=150,
                             file_fee_cents=500, large_entry_surcharge_cents=400)

        res = api.create_cutoff_window(
            create_cutoff_window_payload("SAME_DAY_2", "12:00", "15:00", 130,
                                         450, 300),
            operations_headers)
        window = validate_success(res, 201)
        assert_cutoff_window(window)
        assert window["window_kind"] == "SAME_DAY_2"
        assert window["opens_at_utc"] == "12:00"
        assert window["closes_at_utc"] == "15:00"
