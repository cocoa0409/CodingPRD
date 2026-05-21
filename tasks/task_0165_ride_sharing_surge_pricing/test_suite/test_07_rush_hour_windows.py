"""Rush-hour windows: creation, half-open overlap, adjacency."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_rush_hour_window,
    create_rush_hour_window,
    create_rush_hour_window_payload,
    patch_rush_hour_window_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Creation shape.
# ===========================================================================
class TestRushHourWindowCreate:

    def test_create_returns_201_with_active_flag_true(self, api,
                                                     admin_headers):
        """PRD §3.5: "Each window also carries an is_active flag that
        defaults to true."
        PRD §4: POST returns 201.
        """
        payload = create_rush_hour_window_payload(
            day_of_week="MON", start_minute=480, end_minute=540,
            additive_bonus=0.50,
        )
        resp = api.create_rush_hour_window(payload, admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_rush_hour_window(data)
        assert data["is_active"] is True

    def test_create_with_start_after_end_rejected(self, api,
                                                  admin_headers):
        """PRD §2.9 (eleventh): "on rush-hour window creation and
        update the start_minute must be strictly less than the
        end_minute and the new window's half-open interval must not
        intersect any existing active window on the same day_of_week;
        failure yields ERR_RUSH_HOUR_OVERLAP."

        Either ERR_RUSH_HOUR_OVERLAP (priority 11 lumps shape and
        overlap) or ERR_INVALID_INPUT (priority 16, generic
        range-validation) is faithful to PRD prose — accept both.
        """
        from test_helpers import validate_error_is_one_of
        resp = api.create_rush_hour_window(
            {"label": "x", "day_of_week": "MON",
             "start_minute": 600, "end_minute": 540,
             "additive_bonus": 0.5},
            admin_headers,
        )
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_RUSH_HOUR_OVERLAP.value,
                ApiErrorId.ERR_INVALID_INPUT.value,
            ],
        )

    def test_create_with_invalid_bonus_too_high_rejected(self, api,
                                                         admin_headers):
        """PRD §3.5: "an additive_bonus (a number at least 0.00 and at
        most 1.00)."
        PRD §2.9 (sixteenth): generic shape/range validation yields
        ERR_INVALID_INPUT.
        """
        resp = api.create_rush_hour_window(
            {"label": "x", "day_of_week": "MON",
             "start_minute": 0, "end_minute": 60,
             "additive_bonus": 1.5},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)


# ===========================================================================
# Half-open overlap semantics — PRD §3.5.
# ===========================================================================
class TestRushHourHalfOpenOverlap:

    def test_adjacent_windows_at_boundary_allowed(self, api, admin_headers):
        """PRD §3.5: "Two windows on the same day_of_week may abut but
        not overlap. The intervals are half-open: a new window whose
        start_minute equals an existing window's end_minute is
        permitted (adjacency at the boundary is allowed), but any
        genuine intersection rejects the request with
        ERR_RUSH_HOUR_OVERLAP."
        # difficulty: boundary_precision_check/rush_hour_minute_half_open_boundary
        """
        create_rush_hour_window(
            day_of_week="MON", start_minute=480, end_minute=540,
            additive_bonus=0.5,
        )
        resp = api.create_rush_hour_window(
            create_rush_hour_window_payload(
                day_of_week="MON", start_minute=540, end_minute=600,
                additive_bonus=0.5,
            ),
            admin_headers,
        )
        # Adjacency at 540 is allowed per half-open semantics.
        data = validate_success(resp, expected_status=201)
        assert data["start_minute"] == 540

    def test_interior_overlap_rejected(self, api, admin_headers):
        """PRD §3.5: "any genuine intersection rejects the request with
        ERR_RUSH_HOUR_OVERLAP."
        # difficulty: resource_temporal_overlap/rush_hour_half_open_overlap
        """
        create_rush_hour_window(
            day_of_week="TUE", start_minute=480, end_minute=540,
            additive_bonus=0.5,
        )
        # New window covers 539..600 — interior overlap at minute 539.
        resp = api.create_rush_hour_window(
            create_rush_hour_window_payload(
                day_of_week="TUE", start_minute=539, end_minute=600,
                additive_bonus=0.5,
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RUSH_HOUR_OVERLAP.value)

    def test_overlap_on_different_day_allowed(self, api, admin_headers):
        """PRD §3.5: overlap is tested per day_of_week. A window on
        WED that happens to share minutes with a MON window is fine.
        """
        create_rush_hour_window(
            day_of_week="WED", start_minute=480, end_minute=540,
            additive_bonus=0.5,
        )
        resp = api.create_rush_hour_window(
            create_rush_hour_window_payload(
                day_of_week="THU", start_minute=480, end_minute=540,
                additive_bonus=0.5,
            ),
            admin_headers,
        )
        validate_success(resp, expected_status=201)


# ===========================================================================
# Patch semantics — PRD §3.5.
# ===========================================================================
class TestRushHourPatch:

    def test_patch_set_is_active_false_makes_inert(self, api,
                                                  admin_headers):
        """PRD §3.5: "an is_active set to false makes the window inert
        without deleting the row."
        """
        w = create_rush_hour_window(
            day_of_week="FRI", start_minute=400, end_minute=460,
        )
        resp = api.patch_rush_hour_window(
            w["id"],
            patch_rush_hour_window_payload(version=w["version"],
                                           is_active=False),
            admin_headers,
        )
        data = validate_success(resp)
        assert data["is_active"] is False

    def test_patch_label_increments_version(self, api, admin_headers):
        """PRD §2.4: version increments by 1 on every mutation."""
        w = create_rush_hour_window(day_of_week="SAT")
        v0 = w["version"]
        resp = api.patch_rush_hour_window(
            w["id"],
            patch_rush_hour_window_payload(version=v0,
                                           label="Renamed"),
            admin_headers,
        )
        data = validate_success(resp)
        assert data["version"] == v0 + 1
        assert data["label"] == "Renamed"
