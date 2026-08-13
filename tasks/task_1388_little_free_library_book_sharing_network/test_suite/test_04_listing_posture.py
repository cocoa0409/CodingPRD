"""Listing posture: parallel state dimension, thresholds, and staleness sweeps."""
from test_helpers import (
    TEST_USERS,
    create_steward_with_active_box,
    create_upheld_complaint,
    pin_clock,
    report_maintenance,
    resolve_maintenance,
    run_sweep,
    triage_maintenance,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
MOD1 = TEST_USERS["mod1_headers"]


class TestPostureParallelDimension:
    def test_posture_flagged_by_upheld_complaint_while_charter_active(self, api):
        """PRD §3.4: "Posture is the network's second, parallel state dimension
        on every box, and no client ever sets it directly — it is recomputed by
        the system whenever the underlying facts change."
        PRD §3.4: "Fourth, failing that, the box is `FLAGGED` when any flagging
        condition holds: at least one upheld complaint in the window, at least
        one open high-severity request, or staleness of at least 120 days."

        Design: Difficulty/non_linear_state_machine/box_parallel_dimensions_posture_independent_of_charter
        """
        pin_clock()
        steward, box = create_steward_with_active_box(
            steward_name="Nels Petersen", box_name="Cedar Box",
            region_code="WA",
        )
        create_upheld_complaint(box["id"], steward["id"],
                                category="COMMERCIAL_SPAM",
                                description="Flyers stuffed in box")

        after = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert after["listing_posture"] == "FLAGGED"
        assert after["charter_status"] == "ACTIVE"
        assert after["upheld_complaints_90d"] == 1

    def test_posture_delisted_by_critical_maintenance_then_flagged_after_resolve(
        self, api
    ):
        """PRD §3.4: "Third, an `ACTIVE` box is `DELISTED` when any delisting
        condition holds: at least one open critical maintenance request, at
        least three upheld complaints in the 90-day window, or staleness of at
        least 180 days."
        PRD §3.4: "`FLAGGED` back to `LISTED` when neither flagging nor
        delisting condition survives, or down to `DELISTED` when a delisting
        condition appears."
        PRD §3.5: "Because triage changes the open-maintenance counters, the
        box's posture is recomputed at this moment."

        Design: Difficulty/non_linear_state_machine/box_parallel_dimensions_posture_independent_of_charter
        """
        pin_clock()
        steward, box = create_steward_with_active_box(
            steward_name="Nels Petersen", box_name="Cedar Box",
            region_code="WA",
        )
        create_upheld_complaint(box["id"], steward["id"],
                                category="COMMERCIAL_SPAM",
                                description="Flyers stuffed in box")

        request = report_maintenance(box["id"], category="WEATHER_DAMAGE",
                                     description="Roof caved after storm")
        triage_maintenance(request["id"], severity="CRITICAL",
                           scheduled_date="2026-08-02")
        after_triage = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert after_triage["listing_posture"] == "DELISTED"
        assert after_triage["charter_status"] == "ACTIVE"
        assert after_triage["open_critical_maintenance_count"] == 1

        resolve_maintenance(request["id"])
        after_resolve = validate_success(api.get_box(box["id"], ADMIN), 200)
        # crit back to 0, upheld still 1 -> posture moved without any
        # charter_status transition.
        assert after_resolve["listing_posture"] == "FLAGGED"
        assert after_resolve["charter_status"] == "ACTIVE"
        assert after_resolve["open_critical_maintenance_count"] == 0
        assert after_resolve["upheld_complaints_90d"] == 1


class TestDerivedCounters:
    def test_computed_box_counters_track_children(self, api):
        """PRD §3.4: "The `open_critical_maintenance_count` counts the box's
        maintenance requests with `severity` `CRITICAL` whose status is
        `SCHEDULED` or `REOPENED`; the `open_high_maintenance_count` counts the
        same two statuses at `severity` `HIGH`. Requests still in `REPORTED`
        carry a null severity and never count, and requests in `RESOLVED` or
        `WONT_FIX` never count."
        PRD §3.4: "Fourth, failing that, the box is `FLAGGED` when any flagging
        condition holds: at least one upheld complaint in the window, at least
        one open high-severity request, or staleness of at least 120 days."

        Design: Corner/endpoints/computed_box_counters_track_children
        """
        pin_clock()
        steward, box = create_steward_with_active_box(
            steward_name="Counter Owner", box_name="Counter Box"
        )
        request = report_maintenance(box["id"], category="VANDALISM",
                                     description="Door spray-painted")
        # REPORTED (untriaged) never counts: posture stays LISTED.
        after_report = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert after_report["listing_posture"] == "LISTED"
        assert after_report["open_high_maintenance_count"] == 0

        triage_maintenance(request["id"], severity="HIGH",
                           scheduled_date="2026-08-02")
        after_triage = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert after_triage["open_high_maintenance_count"] == 1
        assert after_triage["listing_posture"] == "FLAGGED"

        resolve_maintenance(request["id"])
        after_resolve = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert after_resolve["open_high_maintenance_count"] == 0
        assert after_resolve["listing_posture"] == "LISTED"


class TestStalenessThresholds:
    def test_posture_flag_threshold_at_120_days(self, api):
        """PRD §3.4: "Fourth, failing that, the box is `FLAGGED` when any
        flagging condition holds: at least one upheld complaint in the window,
        at least one open high-severity request, or staleness of at least 120
        days."
        PRD §3.3: "From that, `days_since_activity` is the whole number of days
        between `last_activity_at` and the current logical instant — the
        elapsed-second difference divided by 86,400 and rounded down."

        Design: Corner/calculations/posture_flag_threshold_at_120_days
        """
        pin_clock()
        _steward, box = create_steward_with_active_box(
            steward_name="Threshold Owner", box_name="Threshold Box"
        )

        # 2026-08-01 -> 2026-11-28 is 119 days: still LISTED, no suspension.
        pin_clock("2026-11-28T00:00:00Z")
        sweep1 = run_sweep()
        assert sweep1["suspended_box_count"] == 0
        at_119 = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert at_119["days_since_activity"] == 119
        assert at_119["listing_posture"] == "LISTED"
        assert at_119["charter_status"] == "ACTIVE"

        # Exactly 120 days: the FLAGGED threshold is inclusive.
        pin_clock("2026-11-29T00:00:00Z")
        sweep2 = run_sweep()
        assert sweep2["suspended_box_count"] == 0
        assert sweep2["posture_change_count"] == 1
        at_120 = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert at_120["days_since_activity"] == 120
        assert at_120["listing_posture"] == "FLAGGED"
        assert at_120["charter_status"] == "ACTIVE"

    def test_staleness_boundary_179_days_suspends_nothing(self, api):
        """PRD §3.9: "`ACTIVE` boxes whose `days_since_activity` has reached
        180 days are suspended with `suspended_at` stamped".
        PRD §3.4: "Fourth, failing that, the box is `FLAGGED` when any flagging
        condition holds: at least one upheld complaint in the window, at least
        one open high-severity request, or staleness of at least 120 days."

        Design: Difficulty/boundary_precision_check/staleness_boundary_sweep_at_exactly_180_days
        """
        pin_clock()
        _steward, box = create_steward_with_active_box(
            steward_name="Jane Addams", box_name="Spruce Box"
        )
        # 2026-08-01 -> 2027-01-27 is 179 days.
        pin_clock("2027-01-27T00:00:00Z")
        sweep = run_sweep()
        assert sweep["suspended_box_count"] == 0
        after = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert after["days_since_activity"] == 179
        assert after["listing_posture"] == "FLAGGED"
        assert after["charter_status"] == "ACTIVE"

    def test_staleness_boundary_exactly_180_days_suspends(self, api):
        """PRD §3.9: "`ACTIVE` boxes whose `days_since_activity` has reached
        180 days are suspended with `suspended_at` stamped".
        PRD §3.4: "Second, a box in `SUSPENDED` or `DECOMMISSIONED` is
        `DELISTED`."

        Design: Difficulty/boundary_precision_check/staleness_boundary_sweep_at_exactly_180_days
        """
        pin_clock()
        _steward, box = create_steward_with_active_box(
            steward_name="Jane Addams", box_name="Spruce Box"
        )
        # 2026-08-01 -> 2027-01-28 is exactly 180 days: inclusive boundary.
        pin_clock("2027-01-28T00:00:00Z")
        sweep = run_sweep()
        assert sweep["suspended_box_count"] == 1
        after = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert after["charter_status"] == "SUSPENDED"
        assert after["listing_posture"] == "DELISTED"
        assert after["days_since_activity"] == 180
