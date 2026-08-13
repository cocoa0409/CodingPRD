"""Leak reporting, grading, re-grading, and leak listing (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_timestamp_eq,
    get_success_data,
    make_leak,
    setup_accepted_run,
    setup_open_leak,
    setup_repair_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_leak_payload, create_regrade_payload


class TestLeakCreationAndGrading:
    def test_leak_creation_computes_grade_and_repair_due(self, api):
        """PRD §3.5: "The server stamps `discovered_at` from the logical clock,
        computes the `grade`, computes `repair_due_at`."
        PRD §3.5: "Failing that, the leak is `G2` if `concentration_ppm` is at
        least 10000" and "The grade sets the repair clock: `repair_due_at` is
        `discovered_at` plus 1 day for `G1`, 30 days for `G2`, or 365 days for `G3`."
        PRD §3.5: "A leak is born in `OPEN` status with `regrade_count` of 0."

        Design: Corner/entities/leak_creation_computes_grade_and_repair_due
        """
        ctx = setup_accepted_run(route_code="R-LC")
        segment = ctx["segments"][0]
        leak = validate_success(api.create_leak(
            create_leak_payload(segment["id"], ctx["run"]["id"]), ctx["ft_h"],
        ), expected_status=201)
        assert leak["grade"] == "G2"
        assert_timestamp_eq(leak["discovered_at"], "2026-08-01T00:00:00Z", "discovered_at")
        assert_timestamp_eq(leak["repair_due_at"], "2026-08-31T00:00:00Z", "repair_due_at")
        assert leak["status"] == "OPEN"
        assert leak["regrade_count"] == 0

    def test_leak_without_building_distance_omits_proximity_term(self, api):
        """PRD §3.5: "the optional `distance_to_building_feet` (null when the leak
        sits in an open field)" and "or if a building distance was recorded and is
        at most 50 feet" — with no distance recorded the proximity term does not
        apply, so low readings grade `G3`.
        PRD §3.5: "365 days for `G3`."

        Design: Corner/entities/leak_without_building_distance_omits_proximity_term
        """
        ctx = setup_accepted_run(
            route_code="R-LD",
            segment_overrides={
                "segment_code": "SEG-LD",
                "install_year": 2015,
                "material": "PLASTIC_PE",
                "diameter_inches": 2.0,
                "length_feet": 300.0,
                "operating_pressure_psi": 30.0,
                "pressure_class": "SERVICE",
            },
            distance_covered_feet=300.0,
        )
        segment = ctx["segments"][0]
        payload = create_leak_payload(
            segment["id"], ctx["run"]["id"],
            concentration_ppm=500.0, bar_hole_reading_pct_lel=1.0,
        )
        del payload["distance_to_building_feet"]
        leak = validate_success(api.create_leak(payload, ctx["ft_h"]), expected_status=201)
        assert leak["distance_to_building_feet"] is None
        assert leak["grade"] == "G3"
        assert_timestamp_eq(leak["repair_due_at"], "2027-08-01T00:00:00Z", "repair_due_at")

    def test_leak_grade_g1_threshold_applies_on_non_hca(self, api):
        """PRD §3.5: "The leak is `G1` if the bar-hole reading is at least 25
        percent of LEL" and "outside high consequence areas the thresholds apply
        exactly as written."

        Design: Difficulty/dual_variant_calc/leak_grade_hca_vs_non_hca
        """
        ctx = setup_accepted_run(route_code="R-HCA1")
        segment = ctx["segments"][0]  # non-HCA by default
        leak = make_leak(
            ctx, segment["id"], ctx["run"]["id"],
            concentration_ppm=8000.0, distance_to_building_feet=25.0,
            bar_hole_reading_pct_lel=30.0, is_migration_evidence=False,
        )
        assert leak["grade"] == "G1"

    def test_leak_grade_hca_escalates_only_on_boundary(self, api):
        """PRD §3.5: "When the segment lies in a high consequence area
        (`is_high_consequence_area` true), grading is conservative — whenever the
        inputs land exactly on a threshold boundary the grade escalates one level
        (`G3` becomes `G2`, `G2` becomes `G1`; `G1` remains `G1`); outside high
        consequence areas the thresholds apply exactly as written."

        Design: Difficulty/dual_variant_calc/leak_grade_hca_vs_non_hca
        """
        # Bar-hole exactly 5.0 % LEL sits on the G2 threshold boundary:
        # non-HCA grades G2 (5 >= 5); HCA escalates the boundary hit to G1.
        ctx_plain = setup_accepted_run(
            route_code="R-HCA2", segment_overrides={"segment_code": "SEG-PLAIN"},
        )
        leak_plain = make_leak(
            ctx_plain, ctx_plain["segments"][0]["id"], ctx_plain["run"]["id"],
            concentration_ppm=8000.0, distance_to_building_feet=200.0,
            bar_hole_reading_pct_lel=5.0, is_migration_evidence=False,
        )
        assert leak_plain["grade"] == "G2"

        ctx_hca = setup_accepted_run(
            route_code="R-HCA3",
            segment_overrides={"segment_code": "SEG-HCA", "is_high_consequence_area": True},
        )
        leak_hca = make_leak(
            ctx_hca, ctx_hca["segments"][0]["id"], ctx_hca["run"]["id"],
            concentration_ppm=8000.0, distance_to_building_feet=200.0,
            bar_hole_reading_pct_lel=5.0, is_migration_evidence=False,
        )
        assert leak_hca["grade"] == "G1"


class TestLeakRegrading:
    def test_regrade_same_grade_rejected(self, api):
        """PRD §3.5: "finally the `new_grade` must differ from the current `grade`
        (`ERR_REGRADE_SAME_GRADE`)."

        Design: Corner/validations/regrade_same_grade_rejected
        """
        ctx = setup_open_leak(route_code="R-RG")
        leak = ctx["leak"]
        assert leak["grade"] == "G2"
        resp = api.regrade_leak(
            leak["id"], create_regrade_payload(new_grade="G2", reason="same grade attempt"),
            ctx["ft_h"],
        )
        validate_error(resp, ApiErrorId.ERR_REGRADE_SAME_GRADE)
        after = get_success_data(api.get_leak(leak["id"], ctx["ft_h"]))
        assert after["regrade_count"] == 0

    def test_regrade_limit_exceeded_on_fourth_regrade(self, api):
        """PRD §3.5: "a leak whose `regrade_count` has already reached the ceiling
        of 3 rejects a further attempt with `ERR_REGRADE_LIMIT_EXCEEDED`."

        Design: Corner/validations/regrade_limit_exceeded_on_fourth_regrade
        """
        ctx = setup_open_leak(route_code="R-RL")
        leak = ctx["leak"]
        for grade in ("G3", "G2", "G1"):
            get_success_data(api.regrade_leak(
                leak["id"], create_regrade_payload(new_grade=grade), ctx["ft_h"],
            ))
        resp = api.regrade_leak(
            leak["id"], create_regrade_payload(new_grade="G2", reason="fourth attempt"),
            ctx["ft_h"],
        )
        validate_error(resp, ApiErrorId.ERR_REGRADE_LIMIT_EXCEEDED)
        after = get_success_data(api.get_leak(leak["id"], ctx["ft_h"]))
        assert after["regrade_count"] == 3
        assert after["grade"] == "G1"

    def test_leak_regrade_after_schedule_rejected(self, api):
        """PRD §3.5: "Regrading requires the leak to be `OPEN` (`ERR_LEAK_NOT_OPEN`)."

        Design: Corner/state_machines/leak_regrade_after_schedule_rejected
        """
        ctx = setup_repair_order(route_code="R-RS2")  # leak is now REPAIR_SCHEDULED
        resp = api.regrade_leak(
            ctx["leak"]["id"],
            create_regrade_payload(new_grade="G1", reason="attempted escalation after scheduling"),
            ctx["ft_h"],
        )
        validate_error(resp, ApiErrorId.ERR_LEAK_NOT_OPEN)

    def test_regrade_events_listed_after_regrade(self, api):
        """PRD §3.5: "Each regrade persists a `RegradeEvent` recording the
        `leak_id`, the `previous_grade`, the `new_grade`, the `reason`, the
        `performed_by_user_id` of the technician, and the `triggered_at` timestamp"
        and "each leak exposes its regrade-event history."

        Design: Corner/endpoints/regrade_events_listed_after_regrade
        """
        ctx = setup_open_leak(route_code="R-RGE")
        leak = ctx["leak"]
        get_success_data(api.regrade_leak(
            leak["id"],
            create_regrade_payload(new_grade="G1", reason="escalation after excavation exposure"),
            ctx["ft_h"],
        ))
        rows, meta = validate_paginated(api.list_regrade_events(leak["id"], ctx["ft_h"]))
        assert meta["total_count"] == 1
        event = rows[0]
        assert event["previous_grade"] == "G2"
        assert event["new_grade"] == "G1"
        assert event["performed_by_user_id"] == ctx["ft"]["id"]
        assert event["leak_id"] == leak["id"]

    def test_regrade_self_loop_keeps_open_and_recomputes_clock(self, api):
        """PRD §3.5: "it recomputes `repair_due_at` from the new grade against the
        **original** `discovered_at`" and "it increments `regrade_count` by 1".
        After G3 -> G2 -> G1 the leak is still OPEN with `repair_due_at` =
        original discovered_at + 1 day.

        Design: Difficulty/non_linear_state_machine/leak_regrade_cyclic_self_loop
        """
        ctx = setup_open_leak(
            route_code="R-L1",
            segment_overrides={
                "segment_code": "SEG-L1",
                "install_year": 2010,
                "material": "PLASTIC_PE",
                "diameter_inches": 4.0,
                "length_feet": 500.0,
                "operating_pressure_psi": 30.0,
                "pressure_class": "SERVICE",
            },
            leak_overrides={
                "concentration_ppm": 500.0,
                "distance_to_building_feet": 200.0,
                "bar_hole_reading_pct_lel": 1.0,
                "is_migration_evidence": False,
            },
            distance_covered_feet=500.0,
        )
        leak = ctx["leak"]
        assert leak["grade"] == "G3"
        get_success_data(api.regrade_leak(
            leak["id"], create_regrade_payload(new_grade="G2", reason="follow-up sniff"),
            ctx["ft_h"],
        ))
        get_success_data(api.regrade_leak(
            leak["id"], create_regrade_payload(new_grade="G1", reason="excavation revealed bigger issue"),
            ctx["ft_h"],
        ))
        after = get_success_data(api.get_leak(leak["id"], ctx["ft_h"]))
        assert after["regrade_count"] == 2
        assert after["grade"] == "G1"
        assert after["status"] == "OPEN"
        # Original discovered_at 2026-08-01 + G1 1-day clock.
        assert_timestamp_eq(after["repair_due_at"], "2026-08-02T00:00:00Z", "repair_due_at")

    def test_regrade_shifts_segment_grade_counters(self, api):
        """PRD §3.5: "it shifts the segment's open-grade counters (decrementing the
        old grade's counter, incrementing the new grade's) and recomputes `posture`."

        Design: Difficulty/non_linear_state_machine/leak_regrade_cyclic_self_loop
        """
        ctx = setup_open_leak(
            route_code="R-L2",
            leak_overrides={
                "concentration_ppm": 500.0,
                "distance_to_building_feet": 200.0,
                "bar_hole_reading_pct_lel": 1.0,
                "is_migration_evidence": False,
            },
        )
        segment = ctx["segments"][0]
        leak = ctx["leak"]
        assert leak["grade"] == "G3"
        get_success_data(api.regrade_leak(
            leak["id"], create_regrade_payload(new_grade="G2", reason="escalation"),
            ctx["ft_h"],
        ))
        seg = get_success_data(api.get_pipe_segment(segment["id"], ctx["ia_h"]))
        assert seg["open_grade3_count"] == 0
        assert seg["open_grade2_count"] == 1
        assert seg["posture"] == "ELEVATED"  # one open G2 (PRD §2.8)


class TestLeakListing:
    def test_list_leaks_filter_by_status(self, api):
        """PRD §3.5: "Leaks list with filters on `status`, `grade`, and
        `segment_id`."

        Design: Corner/endpoints/list_leaks_filter_by_status
        """
        from test_helpers import setup_repair_order as _setup_order
        from test_helpers import make_leak as _mk_leak
        ctx = _setup_order(route_code="R-FL")  # leak1 -> REPAIR_SCHEDULED
        segment = ctx["segments"][0]
        leak2 = _mk_leak(ctx, segment["id"], ctx["run"]["id"], concentration_ppm=13000.0)

        rows, meta = validate_paginated(
            api.list_leaks(ctx["dc_h"], params={"status": "OPEN"})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == leak2["id"]
        assert rows[0]["status"] == "OPEN"

    def test_segment_leaks_subresource_returns_only_own(self, api):
        """PRD §3.1: "From a segment one can also navigate to its leaks (filterable
        by `status` and `grade`)."

        Design: Corner/endpoints/segment_leaks_subresource_returns_only_own
        """
        from test_helpers import make_route, make_run, make_segment, make_instrument, make_org
        ctx = make_org()
        make_instrument(ctx, serial_number="I-CGI-SR")
        seg_a = make_segment(ctx, segment_code="SEG-SR-A")
        seg_b = make_segment(ctx, segment_code="SEG-SR-B")
        route = make_route(ctx, [seg_a["id"], seg_b["id"]], route_code="R-SR")
        run = make_run(ctx, route["id"], ctx["instrument"]["id"],
                       distance_covered_feet=2000.0, submit=True, accept=False)
        leak_a = make_leak(ctx, seg_a["id"], run["id"], concentration_ppm=12000.0)
        make_leak(ctx, seg_b["id"], run["id"], concentration_ppm=13000.0)

        rows, meta = validate_paginated(api.list_segment_leaks(seg_a["id"], ctx["ia_h"]))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == leak_a["id"]
        assert rows[0]["segment_id"] == seg_a["id"]
