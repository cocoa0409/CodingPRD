"""Weather readings, go/no-go limits, windows, wind-adjusted fallout,
go/no-go OCC (PRD §3.6, §2.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_batch_payload,
    create_display_payload,
    create_go_no_go_payload,
    create_magazine_payload,
    create_weather_reading_payload,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    add_secured_post,
    add_lead_crew,
    add_site_plan,
    approve_permit,
    checkout_product,
    confirm_standby,
    create_magazine_with_batch,
    create_operator,
    go_decision,
    post_weather,
    set_clock,
    setup_event_ready,
    setup_event_submitted,
)


def _build_two_ready_events(api):
    """Two READY events on distinct venues, 6in declared, boundary 600,
    one 6in batch checked out to each. Arc centers 0 and 90 degrees."""
    op, op_headers = create_operator()
    mag = get_success_data(api.create_magazine(create_magazine_payload(), op_headers))
    b1 = get_success_data(api.create_batch(
        mag["id"],
        create_batch_payload(
            product_name="Shell 6in", shell_diameter_in=6, quantity_units=50,
            new_per_unit_lbs=0.50, lot_number="L6"),
        op_headers,
    ))
    crew, crew_headers = add_lead_crew(op, op_headers)
    events = {}
    for key, venue, arc in (("e1", "VEN-W1", 0), ("e2", "VEN-W2", 90)):
        ev = get_success_data(api.create_display(
            create_display_payload(venue_id=venue, declared_max_shell_diameter_in=6),
            op_headers,
        ))
        sp = add_site_plan(ev, op_headers, spectator_boundary_ft=600,
                           spectator_arc_center_deg=arc, nearest_structure_ft=700)
        app = get_success_data(api.create_permit_application(
            ev["id"], {"site_plan_id": sp["id"], "standby_engines": 1}, op_headers
        ))
        approve_permit(app)
        confirm_standby(ev, engines_on_site=1)
        checkout_product(b1, ev, op_headers, 10)
        add_secured_post(ev, op_headers, arc_degrees=30, radius_ft=600)
        validate_success(api.ready_display(ev["id"], op_headers))
        events[key] = get_success_data(api.get_display(ev["id"], op_headers))
    set_clock("2026-09-01T19:30:00Z")
    for key in ("e1", "e2"):
        post_weather(events[key], crew_headers,
                     wind_speed_mph=12.0, gust_mph=18.0, source="NWS")
    return op, op_headers, crew_headers, events


class TestWindAdjustedFallout:
    def test_downwind_branch_full_factor(self, api):
        """PRD §3.6: "When delta is at most 45 degrees the full factor
        applies"; factor is "1 + (wind minus 8) × 0.05 ... capped at 1.5, with
        no intermediate rounding of the factor"; base radius is "70 feet per
        inch of the greatest `shell_diameter_in` among batches with net
        `qty_at_show` above zero for the event at decision time".

        Design: Difficulty/combinatorial_formula/wind_adjusted_fallout_downwind_branch
        """
        op, op_headers, crew_headers, events = _build_two_ready_events(api)
        e1 = events["e1"]  # arc center 0; wind from 180 -> downwind 0 -> delta 0
        resp = go_decision(e1, op_headers, "GO")
        data = validate_success(resp)
        # base 420 (70x6); wind 12 >= 8 -> factor 1+(12-8)*0.05 = 1.2; 420*1.2 = 504
        assert data["final_fallout_radius_ft"] == 504
        assert data["status"] == "IN_PROGRESS"

    def test_oblique_branch_half_factor(self, api):
        """PRD §3.6: "when delta is greater than 45 but at most 135 degrees,
        half the excess applies — one plus half of (factor minus one)".

        Design: Difficulty/combinatorial_formula/wind_adjusted_fallout_downwind_branch
        """
        op, op_headers, crew_headers, events = _build_two_ready_events(api)
        e2 = events["e2"]  # arc center 90; downwind 0 -> delta 90 in (45,135]
        resp = go_decision(e2, op_headers, "GO")
        data = validate_success(resp)
        # base 420; factor 1.2; half-excess 1.1; 420*1.1 = 462
        assert data["final_fallout_radius_ft"] == 462
        assert data["status"] == "IN_PROGRESS"


class TestWindLimitBoundary:
    def test_wind_exactly_20_rejected(self, api):
        """PRD §3.6: "The GO limits themselves are strict: a `GO` fails with
        `ERR_WEATHER_NO_GO` when the latest reading's `wind_speed_mph` reaches
        20.0 mph or more".

        Design: Difficulty/boundary_precision_check/wind_limit_exact_20_no_go
        """
        ctx = setup_event_ready()
        set_clock("2026-09-01T19:30:00Z")
        post_weather(ctx["ev"], ctx["crew_headers"], wind_speed_mph=20.0, gust_mph=12.0)
        resp = go_decision(ctx["ev"], ctx["op_headers"], "GO")
        validate_error(resp, ApiErrorId.ERR_WEATHER_NO_GO)
        assert resp.status_code == 422

    def test_wind_19_9_accepted(self, api):
        """PRD §3.6: "a `GO` fails with `ERR_WEATHER_NO_GO` when the latest
        reading's `wind_speed_mph` reaches 20.0 mph or more" — 19.9 mph is
        below the strict limit and GO succeeds, moving the event
        "`READY → IN_PROGRESS`".

        Design: Difficulty/boundary_precision_check/wind_limit_exact_20_no_go
        """
        # Boundary 700 keeps the wind-adjusted fallout gate (PRD §3.6: 280-ft
        # base x capped 1.5 factor = 420 ft downwind) from independently
        # rejecting this GO, so the wind-limit rule alone decides the outcome.
        ctx = setup_event_ready(
            site_plan_overrides={"spectator_boundary_ft": 700}
        )
        set_clock("2026-09-01T19:30:00Z")
        post_weather(ctx["ev"], ctx["crew_headers"], wind_speed_mph=19.9, gust_mph=12.0)
        resp = go_decision(ctx["ev"], ctx["op_headers"], "GO")
        data = validate_success(resp)
        assert data["status"] == "IN_PROGRESS"


class TestGoNoGoPriorityAndOcc:
    def test_safety_beats_temporal_error(self, api):
        """PRD §2.8: "Eighth, safety and compliance gates: quarantined stock (`ERR_BATCH_QUARANTINED`), fallout geometry (`ERR_FALLOUT_EXCEEDS_BOUNDARY`), weather limits (`ERR_WEATHER_NO_GO`), and segregation of duties (`ERR_SOD_VIOLATION`)."
        PRD §2.8: "Tenth, temporal rules: license containment (`ERR_LICENSE_EXPIRED`), certification validity (`ERR_CERT_NOT_VALID`), weather freshness (`ERR_WEATHER_STALE`), misfire soak completion (`ERR_SOAK_INCOMPLETE`), decision-window containment (`ERR_SHOW_WINDOW_NOT_OPEN`), and venue booking buffers (`ERR_VENUE_CONFLICT`)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_go_no_go
        """
        ctx = setup_event_ready()
        set_clock("2026-09-01T23:30:00Z")  # past scheduled_end 23:00 (window closed)
        post_weather(ctx["ev"], ctx["crew_headers"], wind_speed_mph=25.0, gust_mph=18.0)
        resp = go_decision(ctx["ev"], ctx["op_headers"], "GO")
        validate_error(resp, ApiErrorId.ERR_WEATHER_NO_GO)
        assert resp.status_code == 422

    def test_failed_go_leaves_event_ready_pending(self, api):
        """PRD §3.6: "The decision is only accepted while the event is
        `READY`"; a rejected GO must not mutate the event (§2.8 errors return
        before side effects), leaving status READY and weather_decision
        PENDING (the initial dimension value per §3.2).

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_go_no_go
        """
        ctx = setup_event_ready()
        set_clock("2026-09-01T23:30:00Z")
        post_weather(ctx["ev"], ctx["crew_headers"], wind_speed_mph=25.0, gust_mph=18.0)
        validate_error(go_decision(ctx["ev"], ctx["op_headers"], "GO"),
                       ApiErrorId.ERR_WEATHER_NO_GO)
        fresh = get_success_data(api.get_display(ctx["ev"]["id"], ctx["op_headers"]))
        assert fresh["status"] == "READY"
        assert fresh["weather_decision"] == "PENDING"

    def test_go_no_go_stale_version_rejected(self, api):
        """PRD §2.7: "If the event's current `version` has advanced past that value — because any authorized write has mutated the event in the meantime — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.7: "for the go/no-go decision it guarantees the GO is issued against the exact event state the shooter reviewed."

        Design: Corner/cross_cutting_layers/occ_go_no_go_stale_version_rejected
        """
        ctx = setup_event_ready()
        set_clock("2026-09-01T19:30:00Z")
        post_weather(ctx["ev"], ctx["crew_headers"])
        fresh = get_success_data(api.get_display(ctx["ev"]["id"], ctx["op_headers"]))
        stale = api.go_no_go(
            ctx["ev"]["id"],
            create_go_no_go_payload("GO", fresh["version"] - 1),
            ctx["op_headers"],
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert stale.status_code == 412

    def test_go_no_go_fresh_version_accepted(self, api):
        """PRD §2.7: the go/no-go request "must carry
        `expected_display_event_version`, a non-optional field holding the
        `version` of the `DisplayEvent` the client last observed" — a matching
        version admits the decision; PRD §3.6: "Success sets
        `weather_decision` to `GO` and moves the event `READY → IN_PROGRESS`".

        Design: Corner/cross_cutting_layers/occ_go_no_go_stale_version_rejected
        """
        ctx = setup_event_ready()
        set_clock("2026-09-01T19:30:00Z")
        post_weather(ctx["ev"], ctx["crew_headers"])
        resp = go_decision(ctx["ev"], ctx["op_headers"], "GO")
        data = validate_success(resp)
        assert data["status"] == "IN_PROGRESS"


class TestWeatherWindows:
    def test_weather_staleness_stale_side(self, api):
        """PRD §3.6: "if no reading exists, or the latest reading by
        `created_at` is older than 30 minutes ago, the decision is rejected
        with `ERR_WEATHER_STALE` — exactly 30 minutes old is still fresh, as
        the comparison is inclusive."

        Design: Corner/calculations/weather_staleness_boundary
        """
        ctx = setup_event_ready()
        set_clock("2026-09-01T19:00:00Z")
        post_weather(ctx["ev"], ctx["crew_headers"])
        set_clock("2026-09-01T19:30:01Z")  # age 30:01 — stale
        resp = go_decision(ctx["ev"], ctx["op_headers"], "GO")
        validate_error(resp, ApiErrorId.ERR_WEATHER_STALE)
        assert resp.status_code == 409
        fresh = get_success_data(api.get_display(ctx["ev"]["id"], ctx["op_headers"]))
        assert fresh["status"] == "READY"

    def test_weather_staleness_inclusive_fresh_side(self, api):
        """PRD §3.6: "exactly 30 minutes old is still fresh, as the comparison
        is inclusive" — a reading taken 30:00 ago admits the GO.

        Design: Corner/calculations/weather_staleness_boundary
        """
        ctx = setup_event_ready()
        set_clock("2026-09-01T19:00:00Z")
        post_weather(ctx["ev"], ctx["crew_headers"])
        # Stale probe reading first to prove ordering, then fresh boundary reading.
        set_clock("2026-09-01T19:30:01Z")
        post_weather(ctx["ev"], ctx["crew_headers"])  # posted at 19:30:01
        set_clock("2026-09-01T20:00:01Z")  # age exactly 30:00 — fresh
        resp = go_decision(ctx["ev"], ctx["op_headers"], "GO")
        data = validate_success(resp)
        assert data["status"] == "IN_PROGRESS"

    def test_window_not_open_before_start_minus_60(self, api):
        """PRD §3.6: "the clock must be at or after 60 minutes before
        `scheduled_start_at` and at or before `scheduled_end_at` — both bounds
        inclusive — otherwise `ERR_SHOW_WINDOW_NOT_OPEN`."

        Design: Corner/calculations/go_no_go_window_boundary
        """
        ctx = setup_event_ready()
        set_clock("2026-09-01T18:58:59Z")  # window opens 19:00:00
        post_weather(ctx["ev"], ctx["crew_headers"])
        resp = go_decision(ctx["ev"], ctx["op_headers"], "GO")
        validate_error(resp, ApiErrorId.ERR_SHOW_WINDOW_NOT_OPEN)
        assert resp.status_code == 409

    def test_window_open_at_exact_lower_bound(self, api):
        """PRD §3.6: "the clock must be at or after 60 minutes before `scheduled_start_at` and at or before `scheduled_end_at` — both bounds inclusive — otherwise `ERR_SHOW_WINDOW_NOT_OPEN`."

        Design: Corner/calculations/go_no_go_window_boundary
        """
        ctx = setup_event_ready()
        set_clock("2026-09-01T19:00:00Z")  # exactly start - 60 min
        post_weather(ctx["ev"], ctx["crew_headers"])
        resp = go_decision(ctx["ev"], ctx["op_headers"], "GO")
        data = validate_success(resp)
        assert data["status"] == "IN_PROGRESS"


class TestDecisionOutcomes:
    def test_go_decision_sets_parallel_dimensions(self, api):
        """PRD §3.6: "Success sets `weather_decision` to `GO` and moves the
        event `READY → IN_PROGRESS`, incrementing its `version`." Final
        radius: "70 feet per inch of the greatest `shell_diameter_in` among
        batches with net `qty_at_show` above zero"; "When the sustained wind
        is below the 8-mph drift threshold, no adjustment applies."

        Design: Corner/state_machines/go_decision_sets_parallel_dimensions
        """
        ctx = setup_event_ready()
        set_clock("2026-09-01T19:30:00Z")
        post_weather(ctx["ev"], ctx["crew_headers"], wind_speed_mph=5.0, gust_mph=12.0)
        resp = go_decision(ctx["ev"], ctx["op_headers"], "GO")
        data = validate_success(resp)
        assert data["status"] == "IN_PROGRESS"
        assert data["weather_decision"] == "GO"
        assert data["final_fallout_radius_ft"] == 280  # 70 x 4 in, no wind adjustment

    def test_no_go_cancels_event_with_weather_reason(self, api):
        """PRD §3.6: "On the `NO_GO` path, `weather_decision` becomes `NO_GO`
        and `cancellation_reason` becomes `WEATHER_NO_GO`"; §3.7: "Every
        security post of the event in `UNSTAFFED`, `STAFFED`, or `SECURED`
        moves to `RELEASED`" and "the system writes a `RETURN` movement marked
        `auto_generated` true ... bringing the remaining on-site quantity
        home".

        Design: Corner/state_machines/no_go_cancels_event_with_weather_reason
        """
        ctx = setup_event_ready(checkout_qty=10)
        set_clock("2026-09-01T19:30:00Z")
        post_weather(ctx["ev"], ctx["crew_headers"],
                     wind_speed_mph=22.0, gust_mph=30.0, precipitation=True)
        resp = go_decision(ctx["ev"], ctx["op_headers"], "NO_GO")
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"
        assert data["cancellation_reason"] == "WEATHER_NO_GO"
        assert data["weather_decision"] == "NO_GO"
        posts, _ = validate_paginated(
            api.list_security_posts(ctx["ev"]["id"], ctx["op_headers"])
        )
        assert posts[0]["status"] == "RELEASED"
        batch = get_success_data(api.get_batch(ctx["batch"]["id"], ctx["op_headers"]))
        assert batch["qty_at_show"] == 0
        assert batch["qty_at_magazine"] == 50
