"""Interval semantics for surge windows (half-open, touching allowed) and promo windows
(closed, 2-day buffered)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_surge_window_payload, create_promo_window_payload, create_promotion_payload,
)


class TestSurgeWindowOverlap:
    """Surge windows are half-open [starts_at, ends_at): interiors clash, endpoints may touch."""

    def test_interior_overlap_rejected(self, api, admin_headers):
        """PRD 3.8: "A new surge window must not overlap any existing surge window; overlaps are
        rejected with ERR_WINDOW_OVERLAP, though because surge intervals are half-open, two windows
        that merely touch at an endpoint (one's ends_at equal to the next's starts_at) are allowed."

        Design: Difficulty/resource_temporal_overlap/surge_window_halfopen_touching_allowed
        """
        validate_success(api.create_surge_window(create_surge_window_payload(
            name="W1", starts_at="2026-06-01T00:00:00Z", ends_at="2026-06-10T00:00:00Z",
            turnaround_extra_days=2, capacity_per_day=100), admin_headers), 201)
        res = api.create_surge_window(create_surge_window_payload(
            name="W2", starts_at="2026-06-05T00:00:00Z", ends_at="2026-06-15T00:00:00Z",
            turnaround_extra_days=2, capacity_per_day=100), admin_headers)
        validate_error(res, "ERR_WINDOW_OVERLAP", 409)

    def test_touching_endpoint_allowed(self, api, admin_headers):
        """PRD 3.8: "A new surge window must not overlap any existing surge window; overlaps are
        rejected with ERR_WINDOW_OVERLAP, though because surge intervals are half-open, two windows
        that merely touch at an endpoint (one's ends_at equal to the next's starts_at) are allowed."

        Design: Difficulty/resource_temporal_overlap/surge_window_halfopen_touching_allowed
        """
        validate_success(api.create_surge_window(create_surge_window_payload(
            name="W1", starts_at="2026-06-01T00:00:00Z", ends_at="2026-06-10T00:00:00Z",
            turnaround_extra_days=2, capacity_per_day=100), admin_headers), 201)
        # New window starts exactly where the old one ends -> allowed under half-open semantics.
        data = validate_success(api.create_surge_window(create_surge_window_payload(
            name="W3", starts_at="2026-06-10T00:00:00Z", ends_at="2026-06-20T00:00:00Z",
            turnaround_extra_days=2, capacity_per_day=100), admin_headers), 201)
        assert data["id"], "touching window must be created"


class TestPromoWindowBuffer:
    """Promo windows are closed [starts_at, ends_at] and require a >= 2-day buffer from siblings."""

    def _promo_with_window(self, api, admin_headers):
        promo = validate_success(api.create_promotion(
            create_promotion_payload("FALL", "PERCENT", 15, min_subtotal_cents=0, stackable=True, per_customer_limit=5),
            admin_headers), 201)
        validate_success(api.create_promo_window(
            promo["id"], create_promo_window_payload("2026-06-01T00:00:00Z", "2026-06-10T00:00:00Z"),
            admin_headers), 201)
        return promo

    def test_overlapping_window_rejected(self, api, admin_headers):
        """PRD 3.8: "A new window must not overlap any existing window of the same promotion and must
        additionally stand clear of every existing window by a buffer of at least 2 calendar days"

        Design: Difficulty/resource_temporal_overlap/promo_window_closed_buffered
        """
        promo = self._promo_with_window(api, admin_headers)
        res = api.create_promo_window(
            promo["id"], create_promo_window_payload("2026-06-05T00:00:00Z", "2026-06-08T00:00:00Z"), admin_headers)
        validate_error(res, "ERR_WINDOW_OVERLAP", 409)

    def test_within_buffer_rejected(self, api, admin_headers):
        """PRD 3.8: "the new window is accepted only when the gap from an existing window's ends_at
        to the new window's starts_at is at least 2 days, or the gap from the new window's ends_at to
        the existing window's starts_at is at least 2 days; any window that overlaps or violates that
        buffer is rejected with ERR_WINDOW_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/promo_window_closed_buffered
        """
        promo = self._promo_with_window(api, admin_headers)
        # Existing ends 2026-06-10; new starts 2026-06-11 -> only a 1-day gap (< 2) -> rejected.
        res = api.create_promo_window(
            promo["id"], create_promo_window_payload("2026-06-11T00:00:00Z", "2026-06-20T00:00:00Z"), admin_headers)
        validate_error(res, "ERR_WINDOW_OVERLAP", 409)

    def test_buffered_window_accepted(self, api, admin_headers):
        """PRD 3.8: "the new window is accepted only when the gap from an existing window's ends_at
        to the new window's starts_at is at least 2 days, or the gap from the new window's ends_at to
        the existing window's starts_at is at least 2 days; any window that overlaps or violates that
        buffer is rejected with ERR_WINDOW_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/promo_window_closed_buffered
        """
        promo = self._promo_with_window(api, admin_headers)
        # Existing ends 2026-06-10; new starts 2026-06-13 -> 3-day gap (>= 2) -> accepted.
        data = validate_success(api.create_promo_window(
            promo["id"], create_promo_window_payload("2026-06-13T00:00:00Z", "2026-06-20T00:00:00Z"), admin_headers), 201)
        assert data["id"], "buffered window must be created"
