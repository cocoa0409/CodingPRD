"""Expo assignments: half-open overlap vs adjacency, cancel cascade, capacity guard."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    setup_available_animal, create_expo, assign_animal_to_expo,
)

_SALES = TEST_USERS["sales_associate_headers"]
_SM = TEST_USERS["store_manager_headers"]


class TestExpoAssignmentOverlap:
    def _animal_assigned_to_a(self, api, email):
        _, animal = setup_available_animal(
            api, animal_overrides={"list_price_cents": 12000, "acquisition_cost_cents": 4000})
        ex_a = create_expo(api, name="Expo A", venue="Hall 1",
                           start_at="2026-07-10T00:00:00Z", end_at="2026-07-12T00:00:00Z",
                           venue_capacity=10)
        ex_b = create_expo(api, name="Expo B", venue="Hall 2",
                           start_at="2026-07-11T00:00:00Z", end_at="2026-07-13T00:00:00Z",
                           venue_capacity=10)
        ex_c = create_expo(api, name="Expo C", venue="Hall 3",
                           start_at="2026-07-12T00:00:00Z", end_at="2026-07-14T00:00:00Z",
                           venue_capacity=10)
        assign_animal_to_expo(api, ex_a["id"], animal["id"])
        return animal, ex_b, ex_c

    def test_interior_overlap_is_rejected(self, api):
        """PRD §3.9: "if the animal is already `ASSIGNED` to another expo whose window overlaps the target expo's window, the assignment is refused with `ERR_EXPO_OVERLAP`, where windows are compared as half-open intervals — each treated as including its `start_at` and excluding its `end_at`, so two expos that merely touch at an endpoint do not overlap."

        Design: Difficulty/resource_temporal_overlap/expo_assignment_half_open_overlap_vs_adjacency
        """
        animal, ex_b, ex_c = self._animal_assigned_to_a(api, "overlap-b@x.com")
        resp = api.create_expo_assignment(ex_b["id"], {"animal_id": animal["id"]}, headers=_SALES)
        validate_error(resp, ApiErrorId.ERR_EXPO_OVERLAP.value)

    def test_adjacent_window_touching_endpoint_is_accepted(self, api):
        """PRD §3.9: "windows are compared as half-open intervals — each treated as including its `start_at` and excluding its `end_at`, so two expos that merely touch at an endpoint do not overlap."

        Design: Difficulty/resource_temporal_overlap/expo_assignment_half_open_overlap_vs_adjacency
        """
        animal, ex_b, ex_c = self._animal_assigned_to_a(api, "overlap-c@x.com")
        # Expo C starts exactly at Expo A's end (2026-07-12): adjacency, not overlap
        assignment = validate_success(api.create_expo_assignment(
            ex_c["id"], {"animal_id": animal["id"]}, headers=_SALES), expected_status=201)
        assert assignment["status"] == "ASSIGNED"


class TestExpoCancelCascade:
    def test_cancel_expo_cancels_its_assignments(self, api):
        """PRD §3.9: "cancelling an expo instead moves every still-`ASSIGNED` assignment to `CANCELLED`."

        Design: Corner/state_machines/expo_cancel_cascades_assignment_cancel
        """
        _, animal = setup_available_animal(
            api, animal_overrides={"list_price_cents": 9000, "acquisition_cost_cents": 2000})
        expo = create_expo(api, name="Cancel Expo", venue="Center",
                           start_at="2026-08-01T00:00:00Z", end_at="2026-08-03T00:00:00Z",
                           venue_capacity=5)
        assignment = assign_animal_to_expo(api, expo["id"], animal["id"])
        cancelled = validate_success(api.cancel_expo(expo["id"], headers=_SM))
        assert cancelled["status"] == "CANCELLED"
        after = get_success_data(api.get_expo_assignment(assignment["id"], headers=_SM))
        assert after["status"] == "CANCELLED"


class TestExpoCapacity:
    def test_assign_to_full_capacity_expo_returns_capacity_exceeded(self, api):
        """PRD §3.9: "if the count of currently `ASSIGNED` assignments on the expo is already at `venue_capacity`, the assignment is refused with `ERR_EXPO_CAPACITY_EXCEEDED`."

        Design: Corner/validations/expo_assignment_capacity_exceeded_returns_error
        """
        _, animal = setup_available_animal(
            api, animal_overrides={"list_price_cents": 16000, "acquisition_cost_cents": 6000})
        expo = create_expo(api, name="Tiny Expo", venue="Booth",
                           start_at="2026-09-01T00:00:00Z", end_at="2026-09-02T00:00:00Z",
                           venue_capacity=0)
        resp = api.create_expo_assignment(expo["id"], {"animal_id": animal["id"]}, headers=_SALES)
        validate_error(resp, ApiErrorId.ERR_EXPO_CAPACITY_EXCEEDED.value)
