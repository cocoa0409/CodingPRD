"""Interval overlap semantics: half-open pause windows with adjacency allowed
(PRD 3.7) versus buffered stop windows needing a full 15-minute gap (PRD 3.3)."""
from test_helpers import (
    ApiErrorId,
    add_active_subscription,
    create_pause,
    create_pause_payload,
    create_route,
    create_route_stop_payload,
    read_subscription_version,
    setup_active_subscription,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _client
from test_helpers.fixtures import ADMIN


class TestPauseWindowAdjacency:
    def test_adjacent_pause_windows_are_allowed(self, api):
        """PRD 3.7: "Overlap: the half-open window must not intersect any other
        `SCHEDULED` or `ACTIVE` pause of the same subscription — adjacency, where one
        pause ends exactly when another begins, is allowed — else
        `ERR_PAUSE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/pause_windows_half_open_adjacency
        """
        ctx = setup_active_subscription()
        sub_id = ctx["subscription"]["id"]

        pause_a = create_pause(
            sub_id, "2026-08-05", "2026-08-10",
            ctx["subscription_version"], ctx["customer_headers"],
        )
        assert pause_a["status"] == "SCHEDULED"

        v1 = read_subscription_version(sub_id)
        pause_b = create_pause(
            sub_id, "2026-08-10", "2026-08-14", v1, ctx["customer_headers"]
        )
        assert pause_b["status"] == "SCHEDULED", (
            "pause B starts exactly when pause A ends — adjacency is not overlap "
            "under half-open semantics"
        )

    def test_overlapping_pause_rejected(self, api):
        """PRD 3.7: "Overlap: the half-open window must not intersect any other
        `SCHEDULED` or `ACTIVE` pause of the same subscription — adjacency, where one
        pause ends exactly when another begins, is allowed — else
        `ERR_PAUSE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/pause_windows_half_open_adjacency
        """
        ctx = setup_active_subscription()
        sub_id = ctx["subscription"]["id"]
        create_pause(
            sub_id, "2026-08-05", "2026-08-10",
            ctx["subscription_version"], ctx["customer_headers"],
        )
        create_pause(
            sub_id, "2026-08-10", "2026-08-14",
            read_subscription_version(sub_id), ctx["customer_headers"],
        )

        response = _client.create_pause(
            create_pause_payload(
                sub_id, "2026-08-09", "2026-08-12", read_subscription_version(sub_id)
            ),
            ctx["customer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_PAUSE_OVERLAP.value)


class TestStopWindowBuffer:
    def _setup_route_with_auto_stops(self):
        """Two ACTIVE subscriptions whose auto-created stops occupy window
        480-720 on a freshly created (still PLANNED) route."""
        ctx = setup_active_subscription()
        member_b = add_active_subscription(ctx, customer_overrides={"full_name": "Window B"})
        route = create_route(ctx["zone"], "2026-08-03")
        ctx.update({"member_b": member_b, "route": route})
        return ctx

    def test_window_with_exactly_15_minute_gap_allowed(self, api):
        """PRD 3.3: "the new window must clear the scheduling buffer against every
        non-terminal stop already on the route: the new start must be at least 15
        minutes after the existing stop's end, or the new end plus 15 minutes must be
        at or before the existing start — exactly 15 minutes of gap is allowed — else
        `ERR_STOP_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/stop_window_buffer_overlap_semantics
        """
        ctx = self._setup_route_with_auto_stops()
        stop = validate_success(
            _client.create_route_stop(
                create_route_stop_payload(
                    ctx["route"]["id"], ctx["member_b"]["subscription"]["id"], 735, 800
                ),
                ADMIN,
            ),
            201,
        )
        assert stop["is_makeup"] is True, "manually added stops carry is_makeup true"
        assert stop["status"] == "PLANNED"

    def test_window_one_minute_short_of_buffer_rejected(self, api):
        """PRD 3.3: "the new start must be at least 15 minutes after the existing
        stop's end, or the new end plus 15 minutes must be at or before the existing
        start — exactly 15 minutes of gap is allowed — else
        `ERR_STOP_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/stop_window_buffer_overlap_semantics
        """
        ctx = self._setup_route_with_auto_stops()
        response = _client.create_route_stop(
            create_route_stop_payload(
                ctx["route"]["id"], ctx["member_b"]["subscription"]["id"], 734, 800
            ),
            ADMIN,
        )
        # 734 < 720 + 15: one minute short of the required buffer.
        validate_error(response, ApiErrorId.ERR_STOP_WINDOW_CONFLICT.value)
