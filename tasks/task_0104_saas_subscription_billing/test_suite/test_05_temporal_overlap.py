"""Half-open price-schedule overlap and buffered-gap pause-window conflict.

Queue A (difficulty) translations for:
  resource_temporal_overlap (both instances).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    make_account_owner_headers,
    TEST_USERS,
    create_price_schedule_payload,
    create_pause_window_payload,
    setup_plan_with_price_schedule,
    setup_subscription_with_pause_window,
)

ADMIN = TEST_USERS["billing_admin_headers"]


def _owner(account_id):
    return make_account_owner_headers(account_id)


class TestPriceSchedulePositiveOverlap:
    """A positive-measure overlap on half-open windows is rejected."""

    def test_positive_overlap_window_rejected(self, api):
        """PRD §3.1: "A new window may not overlap any other non-canceled schedule on the same plan by any positive span of time; because the intervals are half-open, two windows that merely touch — where one window's `effective_to` equals the next window's `effective_from` — are permitted, but any overlap of positive measure is rejected with `ERR_PRICE_SCHEDULE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/price_schedule_half_open_positive_overlap_rejected
        """
        plan, schedule = setup_plan_with_price_schedule(
            effective_from="2026-01-01T00:00:00Z", effective_to="2026-04-01T00:00:00Z"
        )
        res = api.create_price_schedule(
            plan["id"],
            create_price_schedule_payload(3500, "2026-03-01T00:00:00Z", "2026-06-01T00:00:00Z"),
            ADMIN,
        )
        validate_error(res, "ERR_PRICE_SCHEDULE_OVERLAP")

    def test_overlapping_window_not_persisted(self, api):
        """PRD §3.1: "A new window may not overlap any other non-canceled schedule on the same plan by any positive span of time; because the intervals are half-open, two windows that merely touch — where one window's `effective_to` equals the next window's `effective_from` — are permitted, but any overlap of positive measure is rejected with `ERR_PRICE_SCHEDULE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/price_schedule_half_open_positive_overlap_rejected
        """
        plan, schedule = setup_plan_with_price_schedule(
            effective_from="2026-01-01T00:00:00Z", effective_to="2026-04-01T00:00:00Z"
        )
        validate_error(
            api.create_price_schedule(
                plan["id"],
                create_price_schedule_payload(3500, "2026-03-01T00:00:00Z", "2026-06-01T00:00:00Z"),
                ADMIN,
            ),
            "ERR_PRICE_SCHEDULE_OVERLAP",
        )
        data, meta = validate_paginated(api.list_price_schedules(plan["id"], ADMIN))
        assert meta["total_count"] == 1, (
            f"rejected overlap must not be persisted; total_count={meta['total_count']}"
        )


class TestPauseWindowBufferedGap:
    """A non-overlapping window inside the 7-day buffer is still rejected."""

    def test_window_within_buffer_gap_rejected(self, api):
        """PRD §3.9: "a new window must be separated from every still-`SCHEDULED` window on the same subscription by a buffer of at least 7 days. Concretely, the request is rejected with `ERR_PAUSE_WINDOW_CONFLICT` if the new window expanded by 7 days on each side — the interval from 7 days before `pause_from` to 7 days after `pause_to` — intersects an existing scheduled window; this is a buffered-gap rule, not mere non-adjacency".

        Design: Difficulty/resource_temporal_overlap/pause_window_buffer_gap_conflict_rejected
        """
        account, sub, pw = setup_subscription_with_pause_window(
            pause_from="2026-06-01T00:00:00Z", pause_to="2026-06-10T00:00:00Z", email="pw@x.com"
        )
        res = api.create_pause_window(
            account["id"],
            sub["id"],
            create_pause_window_payload("2026-06-12T00:00:00Z", "2026-06-15T00:00:00Z"),
            _owner(account["id"]),
        )
        validate_error(res, "ERR_PAUSE_WINDOW_CONFLICT")

    def test_conflicting_window_not_persisted(self, api):
        """PRD §3.9: "the request is rejected with `ERR_PAUSE_WINDOW_CONFLICT` if the new window expanded by 7 days on each side — the interval from 7 days before `pause_from` to 7 days after `pause_to` — intersects an existing scheduled window".

        Design: Difficulty/resource_temporal_overlap/pause_window_buffer_gap_conflict_rejected
        """
        account, sub, pw = setup_subscription_with_pause_window(
            pause_from="2026-06-01T00:00:00Z", pause_to="2026-06-10T00:00:00Z", email="pw2@x.com"
        )
        validate_error(
            api.create_pause_window(
                account["id"],
                sub["id"],
                create_pause_window_payload("2026-06-12T00:00:00Z", "2026-06-15T00:00:00Z"),
                _owner(account["id"]),
            ),
            "ERR_PAUSE_WINDOW_CONFLICT",
        )
        data, meta = validate_paginated(api.list_pause_windows(sub["id"], _owner(account["id"])))
        assert meta["total_count"] == 1, (
            f"rejected pause window must not be persisted; total_count={meta['total_count']}"
        )
