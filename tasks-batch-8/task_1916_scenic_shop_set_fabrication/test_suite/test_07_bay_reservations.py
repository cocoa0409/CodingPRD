"""Bay reservations: overlap, half-open adjacency, slot range, deadline,
soft-delete semantics."""
import pytest

from test_helpers import (
    EST,
    FOREMAN,
    ApiErrorId,
    create_bay_reservation_payload,
    get_success_data,
    setup_accepted_production,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBayOverlap:
    def test_same_slot_overlap_rejected(self, api):
        """PRD §3.6: "A new reservation is rejected with `ERR_BAY_OVERLAP`
        (HTTP 409) if its window overlaps any `ACTIVE` reservation on the
        same `bay_slot`."

        Design: Difficulty/resource_temporal_overlap/bay_overlap_same_slot_half_open_rejected
        """
        _, _, _, _, production = setup_accepted_production()
        get_success_data(api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 1,
             "window_start": "2026-09-01T00:00:00Z",
             "window_end": "2026-09-10T00:00:00Z"},
            FOREMAN,
        ))
        resp = api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 1,
             "window_start": "2026-09-05T00:00:00Z",
             "window_end": "2026-09-12T00:00:00Z"},
            FOREMAN,
        )
        validate_error(resp, ApiErrorId.ERR_BAY_OVERLAP, 409)

    def test_different_slot_identical_window_succeeds(self, api):
        """PRD §3.6: "A new reservation is rejected with `ERR_BAY_OVERLAP`
        (HTTP 409) if its window overlaps any `ACTIVE` reservation on the
        same `bay_slot`." — a different slot is outside the predicate.

        Design: Difficulty/resource_temporal_overlap/bay_overlap_same_slot_half_open_rejected
        """
        _, _, _, _, production = setup_accepted_production()
        get_success_data(api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 1,
             "window_start": "2026-09-01T00:00:00Z",
             "window_end": "2026-09-10T00:00:00Z"},
            FOREMAN,
        ))
        resp = api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 2,
             "window_start": "2026-09-05T00:00:00Z",
             "window_end": "2026-09-12T00:00:00Z"},
            FOREMAN,
        )
        created = validate_success(resp, expected_status=201)
        assert created["status"] == "ACTIVE"


class TestHalfOpenAdjacency:
    def test_adjacency_end_equals_start_allowed(self, api):
        """PRD §3.6: "Windows are **half-open** — the occupation spans from
        `window_start` up to but not including `window_end` — so two
        reservations on the same bay slot may be adjacent, one ending exactly
        when the next begins."

        Design: Difficulty/boundary_precision_check/bay_window_adjacency_end_equals_start_allowed
        """
        _, _, _, _, production = setup_accepted_production()
        get_success_data(api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 1,
             "window_start": "2026-09-01T00:00:00Z",
             "window_end": "2026-09-10T00:00:00Z"},
            FOREMAN,
        ))
        resp = api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 1,
             "window_start": "2026-09-10T00:00:00Z",
             "window_end": "2026-09-20T00:00:00Z"},
            FOREMAN,
        )
        created = validate_success(resp, expected_status=201)
        assert created["status"] == "ACTIVE"

    def test_overlap_by_one_day_rejected(self, api):
        """PRD §3.6: "A new reservation is rejected with `ERR_BAY_OVERLAP`
        (HTTP 409) if its window overlaps any `ACTIVE` reservation on the
        same `bay_slot`."

        Design: Difficulty/boundary_precision_check/bay_window_adjacency_end_equals_start_allowed
        """
        _, _, _, _, production = setup_accepted_production()
        get_success_data(api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 1,
             "window_start": "2026-09-01T00:00:00Z",
             "window_end": "2026-09-10T00:00:00Z"},
            FOREMAN,
        ))
        # [09-09, 09-11) intersects [09-01, 09-10)
        resp = api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 1,
             "window_start": "2026-09-09T00:00:00Z",
             "window_end": "2026-09-11T00:00:00Z"},
            FOREMAN,
        )
        validate_error(resp, ApiErrorId.ERR_BAY_OVERLAP, 409)


class TestSlotRangeAndDeadline:
    def test_slot_range_checked_before_window_deadline(self, api):
        """PRD §2.6 lists structural constraints (priority 7) before temporal
        and capacity-window constraints (priority 8). PRD §3.6: "`bay_slot`
        (which must lie between 1 and the shop's `bay_count` inclusive, else
        `ERR_BAY_SLOT_INVALID`, HTTP 422)".

        Design: Difficulty/priority_pair_validation_conflict/bay_reservation_slot_range_before_window_deadline
        """
        _, _, _, _, production = setup_accepted_production()
        # bay_slot 99 (out of range for bay_count 2) AND window past deadline
        resp = api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 99,
             "window_start": "2026-09-20T00:00:00Z",
             "window_end": "2026-09-30T00:00:00Z"},
            FOREMAN,
        )
        validate_error(resp, ApiErrorId.ERR_BAY_SLOT_INVALID, 422)

    def test_no_reservation_persisted_on_slot_invalid(self, api):
        """PRD §3.6: "`bay_slot` (which must lie between 1 and the shop's
        `bay_count` inclusive, else `ERR_BAY_SLOT_INVALID`, HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/bay_reservation_slot_range_before_window_deadline
        """
        _, _, _, _, production = setup_accepted_production()
        api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 99,
             "window_start": "2026-09-20T00:00:00Z",
             "window_end": "2026-09-30T00:00:00Z"},
            FOREMAN,
        )
        data, meta = validate_paginated(api.list_bay_reservations(
            FOREMAN, params={"production_id": production["id"]},
        ))
        assert meta["total_count"] == 0

    def test_window_end_past_deadline_fails(self, api):
        """PRD §3.6: "and with `ERR_WINDOW_PAST_DEADLINE` (HTTP 409) if
        `window_end` lies after the production's `load_in_deadline_at` at
        creation."

        Design: Corner/validations/reservation_window_past_deadline_returns_409
        """
        _, _, _, _, production = setup_accepted_production()
        resp = api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 1,
             "window_start": "2026-09-20T00:00:00Z",
             "window_end": "2026-09-27T00:00:00Z"},
            FOREMAN,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_PAST_DEADLINE, 409)

    def test_window_end_equal_to_deadline_passes(self, api):
        """PRD §3.6: "with `ERR_WINDOW_PAST_DEADLINE` (HTTP 409) if
        `window_end` lies after the production's `load_in_deadline_at`" — a
        window_end exactly equal to the deadline is not after it.

        Design: Corner/validations/reservation_window_past_deadline_returns_409
        """
        _, _, _, _, production = setup_accepted_production()
        resp = api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 1,
             "window_start": "2026-09-20T00:00:00Z",
             "window_end": "2026-09-26T00:00:00Z"},
            FOREMAN,
        )
        assert validate_success(resp, expected_status=201)["status"] == "ACTIVE"


class TestSoftDelete:
    def test_released_reservation_remains_listed_but_frees_slot(self, api):
        """PRD §3.6: "Releasing a reservation is a soft delete: the row
        transitions `ACTIVE → RELEASED`, remains queryable thereafter — list
        and get endpoints include `RELEASED` rows, distinguishable by
        `status` — but is excluded from overlap checks and from the
        reserved-count sums that gate start-build."

        Design: Corner/endpoints/released_reservation_remains_listed_but_frees_slot
        """
        _, _, _, _, production = setup_accepted_production()
        res_1 = get_success_data(api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 1,
             "window_start": "2026-09-01T00:00:00Z",
             "window_end": "2026-09-10T00:00:00Z"},
            FOREMAN,
        ))
        del_resp = api.delete_bay_reservation(res_1["id"], FOREMAN)
        assert del_resp.status_code == 204
        # Row still listed, status RELEASED
        data, _meta = validate_paginated(api.list_bay_reservations(
            FOREMAN, params={"production_id": production["id"]},
        ))
        ids = {row["id"]: row["status"] for row in data}
        assert ids.get(res_1["id"]) == "RELEASED"
        # New overlapping reservation on same slot succeeds
        new_resp = api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 1,
             "window_start": "2026-09-05T00:00:00Z",
             "window_end": "2026-09-15T00:00:00Z"},
            FOREMAN,
        )
        assert validate_success(new_resp, expected_status=201)["status"] == "ACTIVE"

    def test_release_on_non_active_fails_invalid_state(self, api):
        """PRD §3.6: "Releasing a reservation that is not `ACTIVE` is
        `ERR_INVALID_STATE`."

        Design: Corner/endpoints/released_reservation_remains_listed_but_frees_slot
        """
        _, _, _, _, production = setup_accepted_production()
        res_1 = get_success_data(api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 1,
             "window_start": "2026-09-01T00:00:00Z",
             "window_end": "2026-09-10T00:00:00Z"},
            FOREMAN,
        ))
        api.delete_bay_reservation(res_1["id"], FOREMAN)
        resp = api.delete_bay_reservation(res_1["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
