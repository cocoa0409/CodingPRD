"""Catering confirmation, barista overlap, and maintenance cascades."""
import test_helpers as th
from test_helpers import validate_success, validate_error, ApiErrorId, validate_paginated


class TestMaintenanceCancelsCatering:
    def _window_over_confirmed(self, api, headers):
        ctx = th.setup_confirmed_catering(api, headers=headers,
                                          start="2026-03-02T14:00:00Z", end="2026-03-02T15:00:00Z")
        validate_success(api.create_maintenance_window(
            {"equipment_id": ctx["eq_id"], "start_at": "2026-03-02T14:30:00Z",
             "end_at": "2026-03-02T15:30:00Z", "kind": "REPAIR"}, headers), 201)
        return ctx

    def test_scheduling_window_takes_equipment_offline(self, api, manager_headers):
        """PRD 3.3: "Creating a window immediately drives the target equipment
        `OPERATIONAL -> IN_MAINTENANCE` (or `NEEDS_CALIBRATION -> IN_MAINTENANCE`),
        and as a cascade any `CONFIRMED` catering event on that same equipment whose
        scheduled interval `[scheduled_start, scheduled_end)` overlaps the window
        transitions `CONFIRMED -> CANCELLED`."

        Design: Difficulty/transitive_cascade/maintenance_offline_cancels_confirmed_catering
        """
        ctx = self._window_over_confirmed(api, manager_headers)
        equipment = validate_success(api.get_equipment(ctx["eq_id"], manager_headers))
        assert equipment["status"] == "IN_MAINTENANCE", f"got {equipment['status']}"

    def test_overlapping_confirmed_catering_cancelled(self, api, manager_headers):
        """PRD 3.3: "as a cascade any `CONFIRMED` catering event on that same
        equipment whose scheduled interval `[scheduled_start, scheduled_end)`
        overlaps the window transitions `CONFIRMED -> CANCELLED`."

        Design: Difficulty/transitive_cascade/maintenance_offline_cancels_confirmed_catering
        """
        ctx = self._window_over_confirmed(api, manager_headers)
        event = validate_success(api.get_catering_event(ctx["evt_id"], manager_headers))
        assert event["status"] == "CANCELLED", f"got {event['status']}"


class TestBaristaHalfOpenOverlap:
    def _two_events(self, api, headers, e2_start, e2_end):
        bar = th.new_barista(api, name="B", station_role="CATERING", headers=headers)
        eq = th.new_equipment(api, name="Eq", equipment_type="ESPRESSO", headers=headers)
        e1 = th.new_catering_event(api, client_name="E1", assigned_equipment_id=eq["id"],
                                   assigned_barista_id=bar["id"],
                                   scheduled_start="2026-03-02T14:00:00Z",
                                   scheduled_end="2026-03-02T15:00:00Z", headcount=20, headers=headers)
        validate_success(api.confirm_catering_event(e1["id"], headers))
        e2 = th.new_catering_event(api, client_name="E2", assigned_equipment_id=eq["id"],
                                   assigned_barista_id=bar["id"], scheduled_start=e2_start,
                                   scheduled_end=e2_end, headcount=20, headers=headers)
        return e2

    def test_overlapping_second_event_rejected(self, api, manager_headers):
        """PRD 3.9: "there must be no other `CONFIRMED` catering event on the same
        `assigned_barista_id` whose interval `[scheduled_start, scheduled_end)`
        overlaps this one, otherwise `ERR_BARISTA_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/catering_barista_halfopen_overlap
        """
        e2 = self._two_events(api, manager_headers, "2026-03-02T14:30:00Z", "2026-03-02T15:30:00Z")
        resp = api.confirm_catering_event(e2["id"], manager_headers)
        validate_error(resp, ApiErrorId.ERR_BARISTA_OVERLAP.value)

    def test_back_to_back_event_confirms(self, api, manager_headers):
        """PRD 3.9: "The overlap test is half-open, so two events that merely touch
        back-to-back (one ending exactly when the next begins) do not collide."

        Design: Difficulty/resource_temporal_overlap/catering_barista_halfopen_overlap
        """
        e2 = self._two_events(api, manager_headers, "2026-03-02T15:00:00Z", "2026-03-02T16:00:00Z")
        confirmed = validate_success(api.confirm_catering_event(e2["id"], manager_headers))
        assert confirmed["status"] == "CONFIRMED", f"got {confirmed['status']}"


class TestEquipmentUnavailableBeatsBaristaOverlap:
    def _setup(self, api, headers):
        bar = th.new_barista(api, name="B", station_role="CATERING", headers=headers)
        eq1 = th.new_equipment(api, name="Eq1", equipment_type="ESPRESSO", headers=headers)
        eq2 = th.new_equipment(api, name="Eq2", equipment_type="ESPRESSO", headers=headers)
        e1 = th.new_catering_event(api, client_name="E1", assigned_equipment_id=eq1["id"],
                                   assigned_barista_id=bar["id"],
                                   scheduled_start="2026-03-02T14:00:00Z",
                                   scheduled_end="2026-03-02T15:00:00Z", headcount=20, headers=headers)
        validate_success(api.confirm_catering_event(e1["id"], headers))
        e2 = th.new_catering_event(api, client_name="E2", assigned_equipment_id=eq2["id"],
                                   assigned_barista_id=bar["id"],
                                   scheduled_start="2026-03-02T14:30:00Z",
                                   scheduled_end="2026-03-02T15:30:00Z", headcount=20, headers=headers)
        validate_success(api.create_maintenance_window(
            {"equipment_id": eq2["id"], "start_at": "2026-03-02T13:00:00Z",
             "end_at": "2026-03-02T18:00:00Z", "kind": "REPAIR"}, headers), 201)
        return e2

    def test_equipment_error_reported_over_overlap(self, api, manager_headers):
        """PRD 3.9: "the assigned equipment's `status` must be `OPERATIONAL`,
        otherwise `ERR_EQUIPMENT_UNAVAILABLE`"
        PRD 2.8: "referenced companion resources are in the required status
        (assigned barista `ACTIVE`, assigned equipment `OPERATIONAL`, an `ACTIVE`
        bean lot present for origin-required lines, an `OPERATIONAL` machine of the
        required type), applicable to order fulfillment and catering confirmation."

        Design: Difficulty/priority_pair_validation_conflict/equipment_unavailable_beats_barista_overlap
        """
        e2 = self._setup(api, manager_headers)
        resp = api.confirm_catering_event(e2["id"], manager_headers)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_UNAVAILABLE.value)

    def test_conflict_returns_http_409(self, api, manager_headers):
        """PRD 2.8: "the requested interval does not collide with a conflicting
        existing interval on the same resource, applicable to maintenance-window
        creation (on equipment) and catering confirmation (on the barista)."
        PRD 5: the `ERR_EQUIPMENT_UNAVAILABLE` error carries HTTP status 409.

        Design: Difficulty/priority_pair_validation_conflict/equipment_unavailable_beats_barista_overlap
        """
        e2 = self._setup(api, manager_headers)
        resp = api.confirm_catering_event(e2["id"], manager_headers)
        assert resp.status_code == 409, f"got {resp.status_code}"


def test_catering_quote_and_deposit_computed(api, manager_headers):
    """PRD 3.9: "`quoted_total_cents` is the `headcount` multiplied by the per-head
    rate of 1500 cents plus the `travel_fee_cents`, and the `deposit_cents` is
    `quoted_total_cents` multiplied by the deposit rate of 25 percent, rounded
    half-up to whole cents."

    Design: Corner/entities/catering_quote_and_deposit_computed
    """
    bar = th.new_barista(api, name="B", station_role="CATERING", headers=manager_headers)
    eq = th.new_equipment(api, name="Cart", equipment_type="ESPRESSO", headers=manager_headers)
    event = th.new_catering_event(api, client_name="Gala", assigned_equipment_id=eq["id"],
                                  assigned_barista_id=bar["id"],
                                  scheduled_start="2026-03-05T18:00:00Z",
                                  scheduled_end="2026-03-05T21:00:00Z", headcount=30,
                                  travel_fee_cents=5000, headers=manager_headers)
    # 30 * 1500 + 5000 = 50000; deposit round_half_up(50000 * 0.25) = 12500
    assert event["quoted_total_cents"] == 50000, f"got {event['quoted_total_cents']}"
    assert event["deposit_cents"] == 12500, f"got {event['deposit_cents']}"


def test_maintenance_window_invalid_interval_rejected(api, manager_headers):
    """PRD 3.3: "a `start_at` and `end_at` (ISO 8601 UTC, with `end_at` strictly
    after `start_at` — otherwise `ERR_INVALID_INTERVAL`)"

    Design: Corner/validations/invalid_interval_maintenance_rejected
    """
    esp = th.new_equipment(api, name="esp1", equipment_type="ESPRESSO", headers=manager_headers)
    resp = api.create_maintenance_window(
        {"equipment_id": esp["id"], "start_at": "2026-03-02T12:00:00Z",
         "end_at": "2026-03-02T11:00:00Z", "kind": "REPAIR"}, manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL.value)


def test_maintenance_windows_listed_by_equipment(api, manager_headers):
    """PRD 2.3: "Each list response carries the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."
    PRD 4: the `GET /maintenance-windows` endpoint lists maintenance windows.

    Design: Corner/endpoints/maintenance_window_reverse_reachable_by_equipment
    """
    esp = th.new_equipment(api, name="esp1", equipment_type="ESPRESSO", headers=manager_headers)
    win = validate_success(api.create_maintenance_window(
        {"equipment_id": esp["id"], "start_at": "2026-03-07T10:00:00Z",
         "end_at": "2026-03-07T11:00:00Z", "kind": "CLEANING"}, manager_headers), 201)
    resp = api.list_maintenance_windows(manager_headers, params={"equipment_id": esp["id"]})
    data, meta = validate_paginated(resp)
    ids = [w["id"] for w in data]
    assert win["id"] in ids, f"window {win['id']} not in {ids}"
    for w in data:
        assert w["equipment_id"] == esp["id"], f"got {w['equipment_id']}"
