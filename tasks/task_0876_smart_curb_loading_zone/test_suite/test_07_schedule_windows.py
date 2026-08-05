"""Schedule windows: turnover-buffer boundary and exclusive-vs-shared semantics.

Covers difficulty queue A: boundary_precision_check (gap == 15 accepted, gap 14
rejected), resource_temporal_overlap (non-exclusive shares, exclusive within buffer
conflicts).
"""
from test_helpers import (
    validate_error,
    is_valid_uuid,
    ApiErrorId,
    make_permittee_headers,
    setup_permit_with_zone_no_approval,
    make_schedule_window,
    create_schedule_window_payload,
)


class TestTurnoverBufferBoundary:
    """gap == 15 (== buffer) is accepted; gap 14 (< buffer) is rejected."""

    def _setup_two_exclusive_windows(self, api):
        ctx = setup_permit_with_zone_no_approval(api, zone_overrides={"designation": "VALET"})
        # Window A [540,600) exclusive.
        make_schedule_window(api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
                             0, 540, 600, exclusive=True)
        return ctx

    def test_gap_equal_to_buffer_is_accepted(self, api):
        """PRD §3.3: "Two exclusive windows conflict when this gap is strictly less than
        the turnover buffer of 15 minutes; a gap of exactly 15 minutes is permitted, and
        because a direct overlap produces a negative gap it is always a conflict."

        Design: Difficulty/boundary_precision_check/schedule_buffer_gap_lt_15_rejects
        """
        ctx = self._setup_two_exclusive_windows(api)
        # Window B [615,675): gap to A = 615-600 = 15 == buffer -> accepted.
        window_b = make_schedule_window(api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
                                        0, 615, 675, exclusive=True)
        assert is_valid_uuid(window_b["id"]), "gap exactly 15 must be accepted"

    def test_gap_below_buffer_is_rejected(self, api):
        """PRD §3.3: "Two exclusive windows conflict when this gap is strictly less than
        the turnover buffer of 15 minutes ... A conflicting insertion is refused with
        ERR_SCHEDULE_WINDOW_CONFLICT."

        Design: Difficulty/boundary_precision_check/schedule_buffer_gap_lt_15_rejects
        """
        ctx = self._setup_two_exclusive_windows(api)
        # Also add the accepted window B, mirroring the design setup.
        make_schedule_window(api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
                             0, 615, 675, exclusive=True)
        # Candidate [500,526): gap to A = 540-526 = 14 < 15 -> conflict.
        resp = api.create_schedule_window(
            create_schedule_window_payload(ctx["permit_id"], ctx["zone_id"], 0, 500, 526, exclusive=True),
            make_permittee_headers(ctx["permittee_id"]))
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_WINDOW_CONFLICT)


class TestExclusiveVsSharedWindows:
    """Non-exclusive windows share freely; a second exclusive within buffer conflicts."""

    def test_non_exclusive_windows_share_identical_slot(self, api):
        """PRD §3.3: "Non-exclusive windows represent shared, aggregate use and never
        conflict with one another."

        Design: Difficulty/resource_temporal_overlap/schedule_exclusive_buffer_overlap
        """
        ctx = setup_permit_with_zone_no_approval(api, zone_overrides={"designation": "VALET"})
        w1 = make_schedule_window(api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
                                  0, 540, 600, exclusive=False)
        w2 = make_schedule_window(api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
                                  0, 540, 600, exclusive=False)
        assert is_valid_uuid(w1["id"]) and is_valid_uuid(w2["id"]), "identical non-exclusive windows both accepted"

    def test_exclusive_within_buffer_conflicts(self, api):
        """PRD §3.3: "An exclusive window, however, claims sole use of its zone and must
        respect a turnover buffer against other exclusive windows on the same zone_id and
        the same day_of_week."

        Design: Difficulty/resource_temporal_overlap/schedule_exclusive_buffer_overlap
        """
        ctx = setup_permit_with_zone_no_approval(api, zone_overrides={"designation": "VALET"})
        # Two non-exclusive windows coexist, then an exclusive window A [540,600).
        make_schedule_window(api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
                             0, 540, 600, exclusive=False)
        make_schedule_window(api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
                             0, 540, 600, exclusive=False)
        make_schedule_window(api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
                             0, 540, 600, exclusive=True)
        # Trigger exclusive [590,640) directly overlaps A -> negative gap -> conflict.
        resp = api.create_schedule_window(
            create_schedule_window_payload(ctx["permit_id"], ctx["zone_id"], 0, 590, 640, exclusive=True),
            make_permittee_headers(ctx["permittee_id"]))
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_WINDOW_CONFLICT)
