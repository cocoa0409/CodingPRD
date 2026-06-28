"""Work-window confirmation: weather branch, gates, temporal overlaps, occupancy.

Covers cross-entity confirm gates (compliance + material), the validation-priority
conflict between the compliance and material gates, crew/site interval overlap
rules, the weather-hold branch and reweather, and the crew-occupancy compensating
invariant.
"""
from test_helpers import (
    api_client as _ac,
    get_success_data, validate_success, validate_error,
    ApiErrorId,
    bootstrap_actors, create_baselined_project,
    setup_ordered_cleared_delivered, setup_scheduled_window,
    create_crew, propose_window, clear_compliance,
    create_measured_project,
)
from test_helpers.factories import create_material_order_payload


# ---------------------------------------------------------------------------
# Helper for building a confirmable ORDERED/CLEARED/DELIVERED project + window
# sharing a single PM/crew across multiple projects.
# ---------------------------------------------------------------------------
def _confirmed_window_on_shared_crew(actors, crew_id, start_iso, end_iso, address):
    """Create a fresh BASELINE+CLEARED+DELIVERED project under the same actors,
    propose a window on the shared crew, confirm it. Returns (project, ws)."""
    proj = get_success_data(_ac.create_project(
        {"client_id": actors["client_id"], "project_manager_id": actors["pm_id"],
         "property_address": address}, actors["pm_h"]))
    meas = get_success_data(_ac.create_measurement(
        proj["id"], {"estimator_id": actors["est_id"], "gross_wall_sqft": 1100,
                     "opening_sqft": 100, "linear_trim_ft": 300, "color_code": "ARCTIC_WHITE_HZ10"},
        actors["est_h"]))
    est = get_success_data(_ac.create_estimate(
        {"project_id": proj["id"], "measurement_id": meas["id"], "waste_factor_pct": 0.10},
        actors["est_h"]))
    get_success_data(_ac.create_line_item(
        est["id"], {"scope_kind": "SIDING", "quantity": 1000, "unit_price_cents": 1000}, actors["est_h"]))
    get_success_data(_ac.baseline_estimate(est["id"], actors["pm_h"]))
    clear_compliance(proj["id"], actors, permit_number=f"P-{address[:3]}")
    mo = get_success_data(_ac.create_material_order(
        create_material_order_payload(proj["id"], est["id"]), actors["pm_h"]))
    get_success_data(_ac.confirm_material_order(mo["id"], {"delivery_eta_iso": "2026-04-10T00:00:00Z"}, actors["pm_h"]))
    get_success_data(_ac.deliver_material_order(mo["id"], actors["pm_h"]))
    ws = propose_window(proj["id"], crew_id, actors, window_start_iso=start_iso,
                        window_end_iso=end_iso, forecast_wind_mph=10)
    # Return the CONFIRMED window object (the confirm response), not the stale
    # PROPOSED snapshot from propose_window.
    confirmed = get_success_data(_ac.confirm_work_schedule(ws["id"], actors["pm_h"]))
    return proj, confirmed


class TestCrossEntityConfirmGates:
    def test_confirm_succeeds_when_cleared_and_delivered(self, api):
        """PRD §3.6: "When the forecast wind is at or below the crew's `max_wind_mph`
        and all other gates pass, the window's `status` becomes `CONFIRMED`, and as an
        additional side effect, if the project's `workflow_status` is `ORDERED` it
        advances to `SCHEDULED`."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_workschedule_confirm_requires_project_cleared_and_order_delivered
        """
        base = setup_ordered_cleared_delivered()
        proj, actors = base["project"], base["actors"]
        crew = create_crew(actors, name="Crew Conf", max_wind_mph=30)
        ws = propose_window(proj["id"], crew["id"], actors)
        confirmed = validate_success(_ac.confirm_work_schedule(ws["id"], actors["pm_h"]))
        assert confirmed["status"] == "CONFIRMED"
        refetched = validate_success(_ac.get_project(proj["id"], actors["pm_h"]))
        assert refetched["workflow_status"] == "SCHEDULED", \
            f"project should advance ORDERED->SCHEDULED, got {refetched['workflow_status']}"

    def test_confirm_blocked_when_compliance_not_cleared(self, api):
        """PRD §3.6: "The project's `compliance_status` must be `CLEARED`; otherwise
        the confirmation is rejected with `ERR_COMPLIANCE_NOT_CLEARED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_workschedule_confirm_requires_project_cleared_and_order_delivered
        """
        # ORDERED + DELIVERED but compliance still PENDING (no permit issued).
        proj, est, line_map, actors = create_baselined_project()
        mo = get_success_data(_ac.create_material_order(
            create_material_order_payload(proj["id"], est["id"]), actors["pm_h"]))
        get_success_data(_ac.confirm_material_order(mo["id"], {"delivery_eta_iso": "2026-04-10T00:00:00Z"}, actors["pm_h"]))
        get_success_data(_ac.set_clock("2026-04-10T00:00:00Z", actors["pm_h"]))
        get_success_data(_ac.deliver_material_order(mo["id"], actors["pm_h"]))
        crew = create_crew(actors, name="Crew NC", max_wind_mph=30)
        ws = propose_window(proj["id"], crew["id"], actors)
        resp = _ac.confirm_work_schedule(ws["id"], actors["pm_h"])
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_NOT_CLEARED.value)

    def test_confirm_blocked_when_material_not_delivered(self, api):
        """PRD §3.6: "The project's `MaterialOrder` must be `DELIVERED`; otherwise the
        confirmation is rejected with `ERR_MATERIAL_NOT_DELIVERED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/cross_entity_workschedule_confirm_requires_project_cleared_and_order_delivered
        """
        # CLEARED but material only PLACED (not delivered).
        proj, est, line_map, actors = create_baselined_project()
        clear_compliance(proj["id"], actors)
        get_success_data(_ac.create_material_order(
            create_material_order_payload(proj["id"], est["id"]), actors["pm_h"]))
        crew = create_crew(actors, name="Crew MND", max_wind_mph=30)
        ws = propose_window(proj["id"], crew["id"], actors)
        resp = _ac.confirm_work_schedule(ws["id"], actors["pm_h"])
        validate_error(resp, ApiErrorId.ERR_MATERIAL_NOT_DELIVERED.value)


class TestComplianceVsMaterialPriority:
    def test_compliance_error_wins_over_material_error(self, api):
        """PRD §3.6: "The project's `compliance_status` must be `CLEARED`; otherwise
        the confirmation is rejected with `ERR_COMPLIANCE_NOT_CLEARED` (HTTP 409)."
        PRD §3.6: "The project's `MaterialOrder` must be `DELIVERED`; otherwise the
        confirmation is rejected with `ERR_MATERIAL_NOT_DELIVERED` (HTTP 409)."

        The PRD §3.6 confirmation gates are stated in a fixed order (compliance gate
        before material gate); a window failing BOTH is rejected with the
        compliance-gate error.

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_compliance_safety_vs_material_referential
        """
        # ORDERED, compliance PENDING (no permit), material only PLACED.
        proj, est, line_map, actors = create_baselined_project()
        get_success_data(_ac.create_material_order(
            create_material_order_payload(proj["id"], est["id"]), actors["pm_h"]))
        crew = create_crew(actors, name="Crew Both", max_wind_mph=30)
        ws = propose_window(proj["id"], crew["id"], actors)
        resp = _ac.confirm_work_schedule(ws["id"], actors["pm_h"])
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_NOT_CLEARED.value)

    def test_compliance_gate_fires_first_status_409(self, api):
        """PRD §3.6: "The project's `compliance_status` must be `CLEARED`; otherwise
        the confirmation is rejected with `ERR_COMPLIANCE_NOT_CLEARED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/priority_conflict_compliance_safety_vs_material_referential
        """
        proj, est, line_map, actors = create_baselined_project()
        get_success_data(_ac.create_material_order(
            create_material_order_payload(proj["id"], est["id"]), actors["pm_h"]))
        crew = create_crew(actors, name="Crew Both2", max_wind_mph=30)
        ws = propose_window(proj["id"], crew["id"], actors)
        resp = _ac.confirm_work_schedule(ws["id"], actors["pm_h"])
        assert resp.status_code == 409
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_NOT_CLEARED.value)


class TestWeatherBranch:
    def test_high_wind_confirm_parks_weather_hold(self, api):
        """PRD §3.6: "When a `ProjectManager` confirms a `PROPOSED` window whose
        `forecast_wind_mph` exceeds the assigned crew's `max_wind_mph`, the window is
        not confirmed; instead its `status` is parked at `WEATHER_HOLD`."

        Design: Corner/state_machines/weather_hold_branch_on_high_wind_confirm
        """
        base = setup_ordered_cleared_delivered()
        proj, actors = base["project"], base["actors"]
        crew = create_crew(actors, name="Crew WH", max_wind_mph=25)
        ws = propose_window(proj["id"], crew["id"], actors, forecast_wind_mph=40)
        confirmed = validate_success(_ac.confirm_work_schedule(ws["id"], actors["pm_h"]))
        assert confirmed["status"] == "WEATHER_HOLD", \
            f"high wind must park WEATHER_HOLD, got {confirmed['status']}"
        refetched = validate_success(_ac.get_project(proj["id"], actors["pm_h"]))
        assert refetched["workflow_status"] == "ORDERED", \
            f"project must stay ORDERED, got {refetched['workflow_status']}"

    def test_reweather_still_high_returns_wind_exceeds_limit(self, api):
        """PRD §3.6: "Re-weathering a held window whose revised `forecast_wind_mph` is
        still greater than the crew's `max_wind_mph` is rejected with
        `ERR_WIND_EXCEEDS_LIMIT` (HTTP 409)."

        Design: Corner/state_machines/reweather_still_high_wind_returns_wind_exceeds_limit
        """
        base = setup_ordered_cleared_delivered()
        proj, actors = base["project"], base["actors"]
        crew = create_crew(actors, name="Crew RW", max_wind_mph=25)
        ws = propose_window(proj["id"], crew["id"], actors, forecast_wind_mph=40)
        get_success_data(_ac.confirm_work_schedule(ws["id"], actors["pm_h"]))  # WEATHER_HOLD
        resp = _ac.reweather_work_schedule(ws["id"], {"forecast_wind_mph": 35}, actors["pm_h"])
        validate_error(resp, ApiErrorId.ERR_WIND_EXCEEDS_LIMIT.value)


class TestCrewOverlap:
    def test_overlapping_window_same_crew_rejected(self, api):
        """PRD §3.6: "The window's half-open interval, from `window_start_iso`
        inclusive to `window_end_iso` exclusive, must not overlap any other
        `CONFIRMED` window for the same `crew_id`. Because the interval is half-open
        and carries no buffer, adjacency is permitted — one window ending exactly when
        the next begins does not collide. An overlap is rejected with
        `ERR_CREW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/overlap_crew_half_open_no_buffer
        """
        actors = bootstrap_actors()
        crew = create_crew(actors, name="Shared Crew", max_wind_mph=30)
        get_success_data(_ac.set_clock("2026-04-10T00:00:00Z", actors["pm_h"]))
        # Window A [09:00,12:00) confirmed on the shared crew.
        _projA, _wsA = _confirmed_window_on_shared_crew(
            actors, crew["id"], "2026-04-20T09:00:00Z", "2026-04-20T12:00:00Z", "15A Hardie Way")
        # Window B [11:00,13:00) on the same crew (different project) overlaps.
        projB = get_success_data(_ac.create_project(
            {"client_id": actors["client_id"], "project_manager_id": actors["pm_id"],
             "property_address": "15B Hardie Way"}, actors["pm_h"]))
        measB = get_success_data(_ac.create_measurement(
            projB["id"], {"estimator_id": actors["est_id"], "gross_wall_sqft": 1100,
                          "opening_sqft": 100, "linear_trim_ft": 300, "color_code": "ARCTIC_WHITE_HZ10"},
            actors["est_h"]))
        estB = get_success_data(_ac.create_estimate(
            {"project_id": projB["id"], "measurement_id": measB["id"], "waste_factor_pct": 0.10}, actors["est_h"]))
        get_success_data(_ac.create_line_item(
            estB["id"], {"scope_kind": "SIDING", "quantity": 1000, "unit_price_cents": 1000}, actors["est_h"]))
        get_success_data(_ac.baseline_estimate(estB["id"], actors["pm_h"]))
        clear_compliance(projB["id"], actors, permit_number="P-15B")
        moB = get_success_data(_ac.create_material_order(
            create_material_order_payload(projB["id"], estB["id"]), actors["pm_h"]))
        get_success_data(_ac.confirm_material_order(moB["id"], {"delivery_eta_iso": "2026-04-10T00:00:00Z"}, actors["pm_h"]))
        get_success_data(_ac.deliver_material_order(moB["id"], actors["pm_h"]))
        wsB = propose_window(projB["id"], crew["id"], actors,
                             window_start_iso="2026-04-20T11:00:00Z",
                             window_end_iso="2026-04-20T13:00:00Z", forecast_wind_mph=10)
        resp = _ac.confirm_work_schedule(wsB["id"], actors["pm_h"])
        validate_error(resp, ApiErrorId.ERR_CREW_OVERLAP.value)

    def test_back_to_back_windows_same_crew_adjacency_allowed(self, api):
        """PRD §3.6: "Because the interval is half-open and carries no buffer,
        adjacency is permitted — one window ending exactly when the next begins does
        not collide."

        Design: Difficulty/resource_temporal_overlap/overlap_crew_half_open_no_buffer
        """
        actors = bootstrap_actors()
        crew = create_crew(actors, name="Adj Crew", max_wind_mph=30)
        get_success_data(_ac.set_clock("2026-04-10T00:00:00Z", actors["pm_h"]))
        # Window A [09:00,12:00) confirmed.
        _projA, _wsA = _confirmed_window_on_shared_crew(
            actors, crew["id"], "2026-04-20T09:00:00Z", "2026-04-20T12:00:00Z", "19A Hardie Way")
        # Window B [12:00,15:00) starts exactly when A ends -> adjacency, must confirm.
        projB = get_success_data(_ac.create_project(
            {"client_id": actors["client_id"], "project_manager_id": actors["pm_id"],
             "property_address": "19B Hardie Way"}, actors["pm_h"]))
        measB = get_success_data(_ac.create_measurement(
            projB["id"], {"estimator_id": actors["est_id"], "gross_wall_sqft": 1100,
                          "opening_sqft": 100, "linear_trim_ft": 300, "color_code": "ARCTIC_WHITE_HZ10"},
            actors["est_h"]))
        estB = get_success_data(_ac.create_estimate(
            {"project_id": projB["id"], "measurement_id": measB["id"], "waste_factor_pct": 0.10}, actors["est_h"]))
        get_success_data(_ac.create_line_item(
            estB["id"], {"scope_kind": "SIDING", "quantity": 1000, "unit_price_cents": 1000}, actors["est_h"]))
        get_success_data(_ac.baseline_estimate(estB["id"], actors["pm_h"]))
        clear_compliance(projB["id"], actors, permit_number="P-19B")
        moB = get_success_data(_ac.create_material_order(
            create_material_order_payload(projB["id"], estB["id"]), actors["pm_h"]))
        get_success_data(_ac.confirm_material_order(moB["id"], {"delivery_eta_iso": "2026-04-10T00:00:00Z"}, actors["pm_h"]))
        get_success_data(_ac.deliver_material_order(moB["id"], actors["pm_h"]))
        wsB = propose_window(projB["id"], crew["id"], actors,
                             window_start_iso="2026-04-20T12:00:00Z",
                             window_end_iso="2026-04-20T15:00:00Z", forecast_wind_mph=10)
        confirmed = validate_success(_ac.confirm_work_schedule(wsB["id"], actors["pm_h"]))
        assert confirmed["status"] == "CONFIRMED", \
            f"adjacent (end==next start) windows must not collide, got {confirmed['status']}"


class TestSiteOverlap:
    def test_site_buffer_blocks_window_within_24h_different_crew(self, api):
        """PRD §3.6: "The window, expanded by a 24-hour buffer on each side and then
        treated as a closed interval, must not overlap or even touch any other
        `CONFIRMED` window for the same `project_id` — a single home site hosts only
        one trade crew at a time, with a mandatory 24-hour gap between trades. A
        conflict is rejected with `ERR_SITE_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/overlap_site_closed_with_24h_buffer
        """
        base = setup_ordered_cleared_delivered()
        proj, actors = base["project"], base["actors"]
        crew1 = create_crew(actors, name="Crew Site1", max_wind_mph=30)
        crew2 = create_crew(actors, name="Crew Site2", max_wind_mph=30)
        # Window A [Apr20 09:00, 17:00) confirmed on crew1.
        wsA = propose_window(proj["id"], crew1["id"], actors,
                             window_start_iso="2026-04-20T09:00:00Z",
                             window_end_iso="2026-04-20T17:00:00Z", forecast_wind_mph=10)
        get_success_data(_ac.confirm_work_schedule(wsA["id"], actors["pm_h"]))
        # Window B [Apr21 05:00, 12:00) on crew2 — only 12h after A's end, inside the 24h buffer.
        wsB = propose_window(proj["id"], crew2["id"], actors, milestone="SIDING_INSTALL",
                             window_start_iso="2026-04-21T05:00:00Z",
                             window_end_iso="2026-04-21T12:00:00Z", forecast_wind_mph=10)
        resp = _ac.confirm_work_schedule(wsB["id"], actors["pm_h"])
        validate_error(resp, ApiErrorId.ERR_SITE_WINDOW_CONFLICT.value)

    def test_window_beyond_24h_buffer_same_project_confirms(self, api):
        """PRD §3.6: "The window, expanded by a 24-hour buffer on each side and then
        treated as a closed interval, must not overlap or even touch any other
        `CONFIRMED` window for the same `project_id` — a single home site hosts only
        one trade crew at a time, with a mandatory 24-hour gap between trades."

        A second window separated from the first by more than the 24h buffer clears
        the site sequencing gate and confirms.

        Design: Difficulty/resource_temporal_overlap/overlap_site_closed_with_24h_buffer
        """
        base = setup_ordered_cleared_delivered()
        proj, actors = base["project"], base["actors"]
        crew1 = create_crew(actors, name="Crew Far1", max_wind_mph=30)
        crew2 = create_crew(actors, name="Crew Far2", max_wind_mph=30)
        # Window A [Apr20 09:00, 17:00) confirmed on crew1.
        wsA = propose_window(proj["id"], crew1["id"], actors,
                             window_start_iso="2026-04-20T09:00:00Z",
                             window_end_iso="2026-04-20T17:00:00Z", forecast_wind_mph=10)
        get_success_data(_ac.confirm_work_schedule(wsA["id"], actors["pm_h"]))
        # Window B starts Apr22 09:00 — 40h after A's end, well beyond the 24h buffer.
        wsB = propose_window(proj["id"], crew2["id"], actors, milestone="SIDING_INSTALL",
                             window_start_iso="2026-04-22T09:00:00Z",
                             window_end_iso="2026-04-22T17:00:00Z", forecast_wind_mph=10)
        confirmed = validate_success(_ac.confirm_work_schedule(wsB["id"], actors["pm_h"]))
        assert confirmed["status"] == "CONFIRMED", \
            f"window beyond 24h buffer must confirm, got {confirmed['status']}"


class TestCrewOccupancyCompensation:
    def test_cancelling_blocking_window_frees_crew_for_overlapping_window(self, api):
        """PRD §3.6: "A window in `PROPOSED`, `CONFIRMED`, or `WEATHER_HOLD` may be
        cancelled, setting its `status` to `CANCELLED`; this cascades to set any
        `ProgressDraw` on that window in `REQUESTED` or `APPROVED` status to
        `REJECTED`, and it frees the crew and site occupancy the window had held — a
        window that was previously blocking an overlapping candidate no longer does so
        once cancelled, so the candidate becomes confirmable again."

        Design: Difficulty/compensating_invariant/compensating_crew_occupancy_confirm_then_cancel
        """
        actors = bootstrap_actors()
        crew = create_crew(actors, name="Shared Crew 18", max_wind_mph=30)
        get_success_data(_ac.set_clock("2026-04-10T00:00:00Z", actors["pm_h"]))
        projA, wsA = _confirmed_window_on_shared_crew(
            actors, crew["id"], "2026-04-22T09:00:00Z", "2026-04-22T12:00:00Z", "18A Hardie Way")
        # Project B + overlapping window [11:00,13:00) on the same crew.
        projB = get_success_data(_ac.create_project(
            {"client_id": actors["client_id"], "project_manager_id": actors["pm_id"],
             "property_address": "18B Hardie Way"}, actors["pm_h"]))
        measB = get_success_data(_ac.create_measurement(
            projB["id"], {"estimator_id": actors["est_id"], "gross_wall_sqft": 1100,
                          "opening_sqft": 100, "linear_trim_ft": 300, "color_code": "ARCTIC_WHITE_HZ10"},
            actors["est_h"]))
        estB = get_success_data(_ac.create_estimate(
            {"project_id": projB["id"], "measurement_id": measB["id"], "waste_factor_pct": 0.10}, actors["est_h"]))
        get_success_data(_ac.create_line_item(
            estB["id"], {"scope_kind": "SIDING", "quantity": 1000, "unit_price_cents": 1000}, actors["est_h"]))
        get_success_data(_ac.baseline_estimate(estB["id"], actors["pm_h"]))
        clear_compliance(projB["id"], actors, permit_number="P-18B")
        moB = get_success_data(_ac.create_material_order(
            create_material_order_payload(projB["id"], estB["id"]), actors["pm_h"]))
        get_success_data(_ac.confirm_material_order(moB["id"], {"delivery_eta_iso": "2026-04-10T00:00:00Z"}, actors["pm_h"]))
        get_success_data(_ac.deliver_material_order(moB["id"], actors["pm_h"]))
        wsB = propose_window(projB["id"], crew["id"], actors,
                             window_start_iso="2026-04-22T11:00:00Z",
                             window_end_iso="2026-04-22T13:00:00Z", forecast_wind_mph=10)
        # B collides while A holds the crew.
        resp_blocked = _ac.confirm_work_schedule(wsB["id"], actors["pm_h"])
        validate_error(resp_blocked, ApiErrorId.ERR_CREW_OVERLAP.value)
        # Cancel A -> frees the crew.
        get_success_data(_ac.cancel_work_schedule(wsA["id"], actors["pm_h"]))
        # Now B confirms.
        confirmed = validate_success(_ac.confirm_work_schedule(wsB["id"], actors["pm_h"]))
        assert confirmed["status"] == "CONFIRMED", \
            f"B should confirm once A is cancelled, got {confirmed['status']}"
        cancelled_a = validate_success(_ac.get_work_schedule(wsA["id"], actors["pm_h"]))
        assert cancelled_a["status"] == "CANCELLED"

    def test_cancelling_window_sets_cancelled_and_unblocks_same_crew(self, api):
        """PRD §3.6: "A window in `PROPOSED`, `CONFIRMED`, or `WEATHER_HOLD` may be
        cancelled, setting its `status` to `CANCELLED`; this cascades to set any
        `ProgressDraw` on that window in `REQUESTED` or `APPROVED` status to
        `REJECTED`, and it frees the crew and site occupancy the window had held — a
        window that was previously blocking an overlapping candidate no longer does so
        once cancelled, so the candidate becomes confirmable again."

        Design: Difficulty/compensating_invariant/compensating_crew_occupancy_confirm_then_cancel
        """
        actors = bootstrap_actors()
        crew = create_crew(actors, name="Free Crew", max_wind_mph=30)
        get_success_data(_ac.set_clock("2026-04-10T00:00:00Z", actors["pm_h"]))
        projA, wsA = _confirmed_window_on_shared_crew(
            actors, crew["id"], "2026-04-24T09:00:00Z", "2026-04-24T12:00:00Z", "20A Hardie Way")
        assert wsA["status"] == "CONFIRMED"
        # Cancel A; its status flips to CANCELLED and frees the crew.
        cancelled = validate_success(_ac.cancel_work_schedule(wsA["id"], actors["pm_h"]))
        assert cancelled["status"] == "CANCELLED"
        # An overlapping window on the SAME crew now confirms (occupancy freed).
        projB = get_success_data(_ac.create_project(
            {"client_id": actors["client_id"], "project_manager_id": actors["pm_id"],
             "property_address": "20B Hardie Way"}, actors["pm_h"]))
        measB = get_success_data(_ac.create_measurement(
            projB["id"], {"estimator_id": actors["est_id"], "gross_wall_sqft": 1100,
                          "opening_sqft": 100, "linear_trim_ft": 300, "color_code": "ARCTIC_WHITE_HZ10"},
            actors["est_h"]))
        estB = get_success_data(_ac.create_estimate(
            {"project_id": projB["id"], "measurement_id": measB["id"], "waste_factor_pct": 0.10}, actors["est_h"]))
        get_success_data(_ac.create_line_item(
            estB["id"], {"scope_kind": "SIDING", "quantity": 1000, "unit_price_cents": 1000}, actors["est_h"]))
        get_success_data(_ac.baseline_estimate(estB["id"], actors["pm_h"]))
        clear_compliance(projB["id"], actors, permit_number="P-20B")
        moB = get_success_data(_ac.create_material_order(
            create_material_order_payload(projB["id"], estB["id"]), actors["pm_h"]))
        get_success_data(_ac.confirm_material_order(moB["id"], {"delivery_eta_iso": "2026-04-10T00:00:00Z"}, actors["pm_h"]))
        get_success_data(_ac.deliver_material_order(moB["id"], actors["pm_h"]))
        wsB = propose_window(projB["id"], crew["id"], actors,
                             window_start_iso="2026-04-24T10:00:00Z",
                             window_end_iso="2026-04-24T13:00:00Z", forecast_wind_mph=10)
        confirmed_b = validate_success(_ac.confirm_work_schedule(wsB["id"], actors["pm_h"]))
        assert confirmed_b["status"] == "CONFIRMED", \
            f"overlapping window must confirm after A cancelled, got {confirmed_b['status']}"
