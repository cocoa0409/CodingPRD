"""The two occupancy gates on a visit booking use deliberately different interval algebra.

Cabinet exclusivity is half-open and per cabinet, so a window ending at 12:00 and a
window starting at 12:00 coexist on the same cabinet. Escort capacity is closed and
aggregated across the whole row, so that same touching pair consumes two escort slots.
Both gates only count visits that are still occupying space, so a cancellation gives
back exactly what the visit held.
"""

from test_helpers import factories as f, fixtures as fx
from test_helpers import ApiErrorId, validate_success, validate_error, validate_paginated
from test_helpers import SECURITY_OFFICER

W_10_12 = ("2026-08-01T10:00:00Z", "2026-08-01T12:00:00Z")
W_12_14 = ("2026-08-01T12:00:00Z", "2026-08-01T14:00:00Z")
W_11_13 = ("2026-08-01T11:00:00Z", "2026-08-01T13:00:00Z")
W_1200_01_14 = ("2026-08-01T12:00:01Z", "2026-08-01T14:00:00Z")


def _book(api, scenario, cabinet_id, window, purpose="MAINTENANCE"):
    """Raise one booking and return the raw response, so refusals can be asserted."""
    start, end = window
    payload = f.create_access_visit_payload(
        scenario.contract_id,
        scenario.contacts[0]["id"],
        cabinet_id,
        start,
        end,
        purpose=purpose,
    )
    return api.create_access_visit(payload, SECURITY_OFFICER)


def _cancel(api, visit_id):
    return validate_success(
        api.set_access_visit_state(visit_id, f.state_payload("CANCELLED"), SECURITY_OFFICER)
    )


class TestCabinetWindowsAreHalfOpen:
    """Two cabinets on one row, visited by an unescorted contact doing maintenance, so
    `escort_required` is false throughout and only the cabinet gate can fire."""

    def _scenery(self, api):
        scenario = fx.setup_visit_scenery(
            api,
            contract={"committed_cabinet_count": 2},
            cabinet={"cabinet_code": "C01"},
            access_level="UNESCORTED",
        )
        fx.add_installed_cabinet(api, scenario, cabinet_code="C02")
        return scenario

    def test_touching_windows_on_one_cabinet_both_schedule(self, api):
        """PRD §3.7: "The first gate is cabinet exclusivity, and it treats windows as half-open: a booking collides with an existing visit on the same `cabinet_id` when the new window starts strictly before the existing window ends *and* the existing window starts strictly before the new window ends."
        PRD §3.7: "Windows that merely touch — one ending at 12:00 and the next starting at 12:00 — do not collide."

        Design: Difficulty/resource_temporal_overlap/cabinet_visit_windows_are_half_open_so_touching_windows_coexist
        """
        scenario = self._scenery(api)
        cabinet_id = scenario.cabinets[0]["id"]

        first = validate_success(_book(api, scenario, cabinet_id, W_10_12), 201)
        assert first["status"] == "SCHEDULED", (
            f"a new visit opens in SCHEDULED, got {first['status']}"
        )
        assert first["escort_required"] is False, (
            "an UNESCORTED contact doing MAINTENANCE in a CABINET footprint requires no escort, got "
            f"{first['escort_required']!r}"
        )

        second = validate_success(_book(api, scenario, cabinet_id, W_12_14), 201)
        assert second["status"] == "SCHEDULED", (
            f"the touching window must be admitted on the same cabinet, got {second['status']}"
        )
        assert second["escort_required"] is False, (
            f"the touching window also requires no escort, got {second['escort_required']!r}"
        )

    def test_straddling_window_conflicts_on_the_same_cabinet_only(self, api):
        """PRD §3.7: "The first gate is cabinet exclusivity, and it treats windows as half-open: a booking collides with an existing visit on the same `cabinet_id` when the new window starts strictly before the existing window ends *and* the existing window starts strictly before the new window ends."
        PRD §3.7: "A collision is refused with `ERR_VISIT_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/cabinet_visit_windows_are_half_open_so_touching_windows_coexist
        """
        scenario = self._scenery(api)
        first_cabinet_id = scenario.cabinets[0]["id"]
        second_cabinet_id = scenario.cabinets[1]["id"]

        validate_success(_book(api, scenario, first_cabinet_id, W_10_12), 201)
        validate_success(_book(api, scenario, first_cabinet_id, W_12_14), 201)

        validate_error(
            _book(api, scenario, first_cabinet_id, W_11_13),
            ApiErrorId.ERR_VISIT_WINDOW_CONFLICT,
        )

        elsewhere = validate_success(_book(api, scenario, second_cabinet_id, W_11_13), 201)
        assert elsewhere["cabinet_id"] == second_cabinet_id, (
            "the gate is scoped to one cabinet_id, so the identical window on another cabinet stands"
        )
        assert elsewhere["escort_required"] is False, (
            f"the row escort gate never participates here, got escort_required {elsewhere['escort_required']!r}"
        )

    def test_cancelled_visits_stop_occupying_the_cabinet_window(self, api):
        """PRD §3.7: "Two occupancy gates are then evaluated against the visits that are still occupying space — those in `SCHEDULED` or `CHECKED_IN`; visits in `CHECKED_OUT` or `CANCELLED` have released everything they held."
        PRD §3.7: "Checking a `CHECKED_IN` visit out stamps `checked_out_at`, and both check-out and the cancellation of a still-`SCHEDULED` visit release the cabinet window and the row escort slot the visit was occupying."

        Design: Difficulty/resource_temporal_overlap/cabinet_visit_windows_are_half_open_so_touching_windows_coexist
        """
        scenario = self._scenery(api)
        cabinet_id = scenario.cabinets[0]["id"]

        first = validate_success(_book(api, scenario, cabinet_id, W_10_12), 201)
        second = validate_success(_book(api, scenario, cabinet_id, W_12_14), 201)
        validate_error(
            _book(api, scenario, cabinet_id, W_11_13), ApiErrorId.ERR_VISIT_WINDOW_CONFLICT
        )

        assert _cancel(api, first["id"])["status"] == "CANCELLED", "the first visit must cancel"
        assert _cancel(api, second["id"])["status"] == "CANCELLED", "the second visit must cancel"

        readmitted = validate_success(_book(api, scenario, cabinet_id, W_11_13), 201)
        assert readmitted["status"] == "SCHEDULED", (
            f"the straddling window is admitted once both incumbents released, got {readmitted['status']}"
        )

        visits, meta = validate_paginated(
            api.list_access_visits(
                SECURITY_OFFICER, params={"cabinet_id": cabinet_id, "status": "SCHEDULED"}
            )
        )
        assert meta["total_count"] == 1, (
            f"only the re-admitted visit still occupies the cabinet, got {meta['total_count']}"
        )
        assert [v["id"] for v in visits] == [readmitted["id"]], (
            f"the surviving SCHEDULED visit must be the re-admitted one, got {[v['id'] for v in visits]}"
        )


class TestRowEscortCapacityIsClosedInterval:
    """The same touching pair, booked by an `ESCORTED_ONLY` contact across two cabinets
    of a row whose `escort_slot_count` is 1."""

    def _scenery(self, api):
        scenario = fx.setup_visit_scenery(
            api,
            row={"escort_slot_count": 1},
            contract={"committed_cabinet_count": 2},
            cabinet={"cabinet_code": "C01"},
            access_level="ESCORTED_ONLY",
        )
        fx.add_installed_cabinet(api, scenario, cabinet_code="C02")
        return scenario

    def test_touching_escort_windows_across_the_row_exhaust_the_single_slot(self, api):
        """PRD §3.7: "The second gate applies only when the new visit requires an escort, and it counts rather than excludes: across every cabinet in the same row, the server counts the occupying visits that themselves require an escort and whose window boundaries meet the new window on **closed** intervals — the new window's start at or before the peer's end, and the peer's start at or before the new window's end — excluding the candidate itself."
        PRD §3.7: "When that count has already reached the row's `escort_slot_count`, the booking is refused with `ERR_ESCORT_CAPACITY_EXCEEDED`."
        PRD §3.7: "The asymmetry between the two gates is intentional: a touching window does not consume a cabinet, but it does consume an escort, because a single officer cannot hand over instantaneously."

        Design: Difficulty/resource_temporal_overlap/row_escort_capacity_is_closed_interval_so_touching_windows_collide
        """
        scenario = self._scenery(api)
        first_cabinet_id = scenario.cabinets[0]["id"]
        second_cabinet_id = scenario.cabinets[1]["id"]

        incumbent = validate_success(
            _book(api, scenario, first_cabinet_id, W_10_12, purpose="AUDIT"), 201
        )
        assert incumbent["escort_required"] is True, (
            f"an ESCORTED_ONLY contact always requires an escort, got {incumbent['escort_required']!r}"
        )

        validate_error(
            _book(api, scenario, second_cabinet_id, W_12_14, purpose="AUDIT"),
            ApiErrorId.ERR_ESCORT_CAPACITY_EXCEEDED,
        )

    def test_one_second_past_the_touch_point_clears_the_closed_interval(self, api):
        """PRD §3.7: "The second gate applies only when the new visit requires an escort, and it counts rather than excludes: across every cabinet in the same row, the server counts the occupying visits that themselves require an escort and whose window boundaries meet the new window on **closed** intervals — the new window's start at or before the peer's end, and the peer's start at or before the new window's end — excluding the candidate itself."
        PRD §3.7: "All of these comparisons are made at second resolution with no rounding."

        Design: Difficulty/resource_temporal_overlap/row_escort_capacity_is_closed_interval_so_touching_windows_collide
        """
        scenario = self._scenery(api)
        first_cabinet_id = scenario.cabinets[0]["id"]
        second_cabinet_id = scenario.cabinets[1]["id"]

        validate_success(_book(api, scenario, first_cabinet_id, W_10_12, purpose="AUDIT"), 201)
        validate_error(
            _book(api, scenario, second_cabinet_id, W_12_14, purpose="AUDIT"),
            ApiErrorId.ERR_ESCORT_CAPACITY_EXCEEDED,
        )

        shifted = validate_success(
            _book(api, scenario, second_cabinet_id, W_1200_01_14, purpose="AUDIT"), 201
        )
        assert shifted["status"] == "SCHEDULED", (
            f"a start one second past the incumbent's end must be admitted, got {shifted['status']}"
        )
        assert shifted["escort_required"] is True, (
            f"the shifted visit still requires an escort, got {shifted['escort_required']!r}"
        )

    def test_cancelled_escorted_visits_release_the_row_escort_slot(self, api):
        """PRD §3.7: "Checking a `CHECKED_IN` visit out stamps `checked_out_at`, and both check-out and the cancellation of a still-`SCHEDULED` visit release the cabinet window and the row escort slot the visit was occupying."
        PRD §3.7: "When that count has already reached the row's `escort_slot_count`, the booking is refused with `ERR_ESCORT_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/row_escort_capacity_is_closed_interval_so_touching_windows_collide
        """
        scenario = self._scenery(api)
        first_cabinet_id = scenario.cabinets[0]["id"]
        second_cabinet_id = scenario.cabinets[1]["id"]

        incumbent = validate_success(
            _book(api, scenario, first_cabinet_id, W_10_12, purpose="AUDIT"), 201
        )
        shifted = validate_success(
            _book(api, scenario, second_cabinet_id, W_1200_01_14, purpose="AUDIT"), 201
        )

        _cancel(api, incumbent["id"])
        _cancel(api, shifted["id"])

        _visits, meta = validate_paginated(
            api.list_access_visits(
                SECURITY_OFFICER,
                params={"contract_id": scenario.contract_id, "status": "SCHEDULED"},
            )
        )
        assert meta["total_count"] == 0, (
            f"both incumbents were cancelled, so nothing still occupies the row, got {meta['total_count']}"
        )

        readmitted = validate_success(
            _book(api, scenario, second_cabinet_id, W_12_14, purpose="AUDIT"), 201
        )
        assert readmitted["status"] == "SCHEDULED", (
            f"the released escort slot must admit the original touching window, got {readmitted['status']}"
        )
        assert readmitted["escort_required"] is True, (
            f"the re-admitted visit still requires an escort, got {readmitted['escort_required']!r}"
        )
        assert readmitted["escort_officer_user_id"] is None, (
            "the escorting officer is only recorded at check-in, got "
            f"{readmitted['escort_officer_user_id']!r}"
        )
