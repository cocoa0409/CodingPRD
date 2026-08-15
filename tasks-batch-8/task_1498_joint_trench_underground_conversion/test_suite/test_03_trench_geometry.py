"""Trench geometry: separation variants, window conflicts, depth budget,
cover/capacity rails, deeper-first install order, and the retry cycle.

PRD §3.3 (segments, depth accounting), §3.4 (slots: geometry, windows, order).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_project,
    create_occupancy_slot_payload,
    setup_mobilized_project,
    create_scheduled_segment,
    reserve_slot,
    transition_slot,
    create_parcel_with_recorded_easement,
    create_issued_permit,
    lifecycle,
    transition_segment,
    make_coordinator_headers,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["pm_headers"]


def _waiver_project(api):
    """4-party mobilized project (bp 2500 x4): P2 TELECOM waiver, P3 CATV
    waiver, P4 CATV no waiver; segments SEG-A and SEG-B scheduled 09-01..09-10."""
    project, parts = setup_mobilized_project(
        [
            {"utility_name": "U-E", "utility_type": "ELECTRIC", "cost_share_bp": 2500, "sequence_order": 1, "has_separation_waiver": False},
            {"utility_name": "U-T", "utility_type": "TELECOM", "cost_share_bp": 2500, "sequence_order": 2, "has_separation_waiver": True},
            {"utility_name": "U-C1", "utility_type": "CATV", "cost_share_bp": 2500, "sequence_order": 3, "has_separation_waiver": True},
            {"utility_name": "U-C2", "utility_type": "CATV", "cost_share_bp": 2500, "sequence_order": 4, "has_separation_waiver": False},
        ],
        name="Waiver Project", rule20_credit_cents=0, estimated_total_cost_cents=4000000,
        target_cutover_on="2026-12-31T00:00:00Z", contingency_days=0,
    )
    seg_a = create_scheduled_segment(project["id"], segment_code="SEG-A", length_ft=300)
    seg_b = create_scheduled_segment(project["id"], segment_code="SEG-B", length_ft=300)
    return project, parts, seg_a, seg_b


class TestSeparationWaiverVariant:
    def test_waiver_pair_admits_six_inch_gap(self, api):
        """PRD §3.4: "The required gap is six inches only when both participants
        are non-`ELECTRIC` and both hold a signed separation waiver
        (`has_separation_waiver` true); in every other pairing it is twelve
        inches. Any pair below its requirement is rejected with
        `ERR_MIN_SEPARATION_VIOLATION` — which is also why overlapping bands
        can never pass."

        Design: Difficulty/dual_variant_calc/waiver_vs_standard_separation_variant
        """
        _project, parts, seg_a, _seg_b = _waiver_project(api)
        _p1, p2, p3, _p4 = parts

        resp = api.create_occupancy_slot(
            create_occupancy_slot_payload(
                seg_a["id"], p2["id"],
                depth_top_inches=30, depth_bottom_inches=42,
                install_start_at="2026-09-01T00:00:00Z",
                install_end_at="2026-09-03T00:00:00Z",
            ),
            make_coordinator_headers(p2["id"]),
        )
        validate_success(resp, 201)

        resp = api.create_occupancy_slot(
            create_occupancy_slot_payload(
                seg_a["id"], p3["id"],
                depth_top_inches=12, depth_bottom_inches=24,
                install_start_at="2026-09-03T00:00:00Z",
                install_end_at="2026-09-05T00:00:00Z",
            ),
            make_coordinator_headers(p3["id"]),
        )
        slot = validate_success(resp, 201)
        assert slot["status"] == "RESERVED", (
            "waiver pair with gap 6 >= 6 must be admitted; got " + slot["status"]
        )

    def test_missing_waiver_rejects_identical_geometry(self, api):
        """PRD §3.4: "The required gap is six inches only when both participants
        are non-`ELECTRIC` and both hold a signed separation waiver
        (`has_separation_waiver` true); in every other pairing it is twelve
        inches. Any pair below its requirement is rejected with
        `ERR_MIN_SEPARATION_VIOLATION` — which is also why overlapping bands
        can never pass."

        Design: Difficulty/dual_variant_calc/waiver_vs_standard_separation_variant
        """
        _project, parts, _seg_a, seg_b = _waiver_project(api)
        _p1, p2, _p3, p4 = parts

        resp = api.create_occupancy_slot(
            create_occupancy_slot_payload(
                seg_b["id"], p2["id"],
                depth_top_inches=30, depth_bottom_inches=42,
                install_start_at="2026-09-01T00:00:00Z",
                install_end_at="2026-09-03T00:00:00Z",
            ),
            make_coordinator_headers(p2["id"]),
        )
        validate_success(resp, 201)

        # Identical geometry (gap 6) but P4 holds no waiver: 12 inches required.
        resp = api.create_occupancy_slot(
            create_occupancy_slot_payload(
                seg_b["id"], p4["id"],
                depth_top_inches=12, depth_bottom_inches=24,
                install_start_at="2026-09-03T00:00:00Z",
                install_end_at="2026-09-05T00:00:00Z",
            ),
            make_coordinator_headers(p4["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MIN_SEPARATION_VIOLATION)


def _overlap_project(api):
    """Mobilized 2-party project; SEG-1 and SEG-2 each hold an electric slot
    (bands 36-60 and 48-60 respectively) with window 09-01..09-03."""
    project, parts = setup_mobilized_project(
        [
            {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 7000, "sequence_order": 1},
            {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 3000, "sequence_order": 2},
        ],
        name="Overlap Project", rule20_credit_cents=0, estimated_total_cost_cents=1000000,
        target_cutover_on="2026-12-31T00:00:00Z", contingency_days=0,
    )
    p1, p2 = parts
    seg1 = create_scheduled_segment(project["id"], segment_code="SEG-1")
    seg2 = create_scheduled_segment(project["id"], segment_code="SEG-2")
    reserve_slot(seg1["id"], p1["id"], depth_top_inches=36, depth_bottom_inches=60,
                 install_start_at="2026-09-01T00:00:00Z",
                 install_end_at="2026-09-03T00:00:00Z")
    reserve_slot(seg2["id"], p1["id"], depth_top_inches=48, depth_bottom_inches=60,
                 install_start_at="2026-09-01T00:00:00Z",
                 install_end_at="2026-09-03T00:00:00Z")
    return project, p1, p2, seg1, seg2


class TestSlotWindowBufferSemantics:
    def test_overlapping_windows_below_24_inches_rejected(self, api):
        """PRD §3.4: "Two slots on the same segment whose vertical gap is less
        than twenty-four inches must hold disjoint windows; touching windows,
        where one ends exactly when the other begins, are allowed, and the
        shallower slot's window may not begin before the deeper slot's window
        ends — crews always work deeper-first. Bands separated by twenty-four
        inches or more may overlap in time freely. Breaches are rejected with
        `ERR_SLOT_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/slot_window_buffer_semantics
        """
        _project, _p1, p2, seg1, _seg2 = _overlap_project(api)
        resp = api.create_occupancy_slot(
            create_occupancy_slot_payload(
                seg1["id"], p2["id"],
                depth_top_inches=12, depth_bottom_inches=24,
                install_start_at="2026-09-02T00:00:00Z",
                install_end_at="2026-09-04T00:00:00Z",
            ),
            make_coordinator_headers(p2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_WINDOW_CONFLICT)

    def test_adjacent_windows_and_full_24_inch_gap_allowed(self, api):
        """PRD §3.4: "Two slots on the same segment whose vertical gap is less
        than twenty-four inches must hold disjoint windows; touching windows,
        where one ends exactly when the other begins, are allowed, and the
        shallower slot's window may not begin before the deeper slot's window
        ends — crews always work deeper-first. Bands separated by twenty-four
        inches or more may overlap in time freely. Breaches are rejected with
        `ERR_SLOT_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/slot_window_buffer_semantics
        """
        _project, _p1, p2, seg1, seg2 = _overlap_project(api)
        # gap 12 < 24 but windows merely adjacent (deeper ends as shallower starts)
        resp = api.create_occupancy_slot(
            create_occupancy_slot_payload(
                seg1["id"], p2["id"],
                depth_top_inches=12, depth_bottom_inches=24,
                install_start_at="2026-09-03T00:00:00Z",
                install_end_at="2026-09-05T00:00:00Z",
            ),
            make_coordinator_headers(p2["id"]),
        )
        adj = validate_success(resp, 201)
        assert adj["status"] == "RESERVED"

        # overlapping windows but vertical gap exactly 24 >= 24: free overlap
        resp = api.create_occupancy_slot(
            create_occupancy_slot_payload(
                seg2["id"], p2["id"],
                depth_top_inches=12, depth_bottom_inches=24,
                install_start_at="2026-09-02T00:00:00Z",
                install_end_at="2026-09-04T00:00:00Z",
            ),
            make_coordinator_headers(p2["id"]),
        )
        wide = validate_success(resp, 201)
        assert wide["status"] == "RESERVED"


class TestSegmentDepthConservation:
    def _setup(self, api):
        project, parts = setup_mobilized_project(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 7000, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 3000, "sequence_order": 2},
            ],
            name="Depth Project", rule20_credit_cents=0, estimated_total_cost_cents=1000000,
            target_cutover_on="2026-12-31T00:00:00Z", contingency_days=0,
        )
        p1, p2 = parts
        seg = create_scheduled_segment(project["id"])
        return project, p1, p2, seg

    def test_occupied_depth_tracks_max_not_sum(self, api):
        """PRD §3.3: "`occupied_depth_inches` is the greatest
        `depth_bottom_inches` among the segment's slots in `RESERVED`,
        `INSTALLING`, `INSTALLED`, or `VERIFIED` — zero when no such slot
        exists — and `available_depth_inches` is `max_depth_inches` minus the
        occupied depth."

        Design: Difficulty/compensating_invariant/segment_depth_conservation_on_release
        """
        _project, p1, p2, seg = self._setup(api)
        assert seg["available_depth_inches"] == 60, (
            f"creation-time budget equals max_depth_inches, got {seg['available_depth_inches']}"
        )
        assert seg["occupied_depth_inches"] == 0

        reserve_slot(seg["id"], p1["id"], depth_top_inches=36, depth_bottom_inches=60,
                     install_start_at="2026-09-01T00:00:00Z",
                     install_end_at="2026-09-03T00:00:00Z")
        reserve_slot(seg["id"], p2["id"], depth_top_inches=12, depth_bottom_inches=24,
                     install_start_at="2026-09-03T00:00:00Z",
                     install_end_at="2026-09-05T00:00:00Z")
        mid = validate_success(api.get_trench_segment(seg["id"], PM), 200)
        assert mid["occupied_depth_inches"] == 60, (
            f"occupied tracks max depth_bottom (60), not the sum (84): {mid['occupied_depth_inches']}"
        )
        assert mid["available_depth_inches"] == 0

    def test_release_restores_depth_budget_exactly(self, api):
        """PRD §3.4: "A slot in `RESERVED` or `INSTALL_FAILED` may instead be
        released (`→ RELEASED`) by its owning coordinator — or by the system
        during a withdrawal cascade — and each release recomputes the segment's
        occupied and available depth."
        PRD §3.3: "`occupied_depth_inches` is the greatest `depth_bottom_inches`
        among the segment's slots in `RESERVED`, `INSTALLING`, `INSTALLED`, or
        `VERIFIED` — zero when no such slot exists — and `available_depth_inches`
        is `max_depth_inches` minus the occupied depth."

        Design: Difficulty/compensating_invariant/segment_depth_conservation_on_release
        """
        _project, p1, p2, seg = self._setup(api)
        s1 = reserve_slot(seg["id"], p1["id"], depth_top_inches=36, depth_bottom_inches=60,
                          install_start_at="2026-09-01T00:00:00Z",
                          install_end_at="2026-09-03T00:00:00Z")
        s2 = reserve_slot(seg["id"], p2["id"], depth_top_inches=12, depth_bottom_inches=24,
                          install_start_at="2026-09-03T00:00:00Z",
                          install_end_at="2026-09-05T00:00:00Z")

        transition_slot(s2["id"], "RELEASED", p2["id"])
        after_shallow = validate_success(api.get_trench_segment(seg["id"], PM), 200)
        assert after_shallow["occupied_depth_inches"] == 60, (
            "electric band bottom still pins occupied at 60 after the shallow release"
        )
        assert after_shallow["available_depth_inches"] == 0

        transition_slot(s1["id"], "RELEASED", p1["id"])
        after_all = validate_success(api.get_trench_segment(seg["id"], PM), 200)
        assert after_all["occupied_depth_inches"] == 0
        assert after_all["available_depth_inches"] == 60, (
            "reserve/reserve followed by release/release conserves the budget exactly"
        )


class TestDepthRails:
    def _setup(self, api):
        project, parts = setup_mobilized_project(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 9999, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 1, "sequence_order": 2},
            ],
            name="V10", rule20_credit_cents=0, estimated_total_cost_cents=1000000,
            target_cutover_on="2026-12-31T00:00:00Z", contingency_days=0,
        )
        seg = create_scheduled_segment(project["id"])
        return project, parts, seg

    def test_slot_min_cover_and_depth_capacity(self, api):
        """PRD §3.4: "The top of any band must sit at least twelve inches below
        grade (`depth_top_inches` of 12 or more; less is
        `ERR_MIN_COVER_VIOLATION`), and the bottom must lie within the
        segment's usable depth (`depth_bottom_inches` no greater than
        `max_depth_inches`, else `ERR_DEPTH_CAPACITY_EXCEEDED`); the bottom
        must also exceed the top, with malformed bands caught as
        `ERR_VALIDATION`."

        Design: Corner/validations/slot_min_cover_and_depth_capacity
        """
        _project, parts, seg = self._setup(api)
        p1, _p2 = parts
        resp = api.create_occupancy_slot(
            create_occupancy_slot_payload(
                seg["id"], p1["id"], depth_top_inches=11, depth_bottom_inches=30,
                install_start_at="2026-09-01T00:00:00Z",
                install_end_at="2026-09-03T00:00:00Z",
            ),
            make_coordinator_headers(p1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MIN_COVER_VIOLATION)

        resp = api.create_occupancy_slot(
            create_occupancy_slot_payload(
                seg["id"], p1["id"], depth_top_inches=50, depth_bottom_inches=61,
                install_start_at="2026-09-01T00:00:00Z",
                install_end_at="2026-09-03T00:00:00Z",
            ),
            make_coordinator_headers(p1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DEPTH_CAPACITY_EXCEEDED)

    def test_slot_window_outside_excavation_rejected(self, api):
        """PRD §3.4: "Every window must lie entirely within the segment's
        excavation window, both endpoints inclusive
        (`ERR_SLOT_WINDOW_OUT_OF_RANGE`)."

        Design: Corner/validations/slot_window_outside_excavation_rejected
        """
        _project, parts, seg = self._setup(api)
        p1, _p2 = parts
        resp = api.create_occupancy_slot(
            create_occupancy_slot_payload(
                seg["id"], p1["id"], depth_top_inches=36, depth_bottom_inches=60,
                install_start_at="2026-09-09T00:00:00Z",
                install_end_at="2026-09-12T00:00:00Z",
            ),
            make_coordinator_headers(p1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SLOT_WINDOW_OUT_OF_RANGE)


class TestInstallOrderAndRetry:
    def _excavating_segment(self, api, name):
        project, parts = setup_mobilized_project(
            [
                {"utility_name": "U1", "utility_type": "ELECTRIC", "cost_share_bp": 9999, "sequence_order": 1},
                {"utility_name": "U2", "utility_type": "TELECOM", "cost_share_bp": 1, "sequence_order": 2},
            ],
            name=name, rule20_credit_cents=0, estimated_total_cost_cents=1000000,
            target_cutover_on="2026-12-31T00:00:00Z", contingency_days=0,
        )
        parcel, _es = create_parcel_with_recorded_easement(
            project["id"], address="6 B St", owner_name="O",
            existing_panel_amps=100, load_calc_amps=50,
        )
        create_issued_permit(project["id"])
        seg = create_scheduled_segment(project["id"], parcel_ids=[parcel["id"]])
        lifecycle(project["id"], "START_TRENCHING")
        transition_segment(seg["id"], "EXCAVATING")
        return project, parts, seg

    def test_deeper_first_install_order_enforced(self, api):
        """PRD §3.4: "Moving `RESERVED → INSTALLING` requires the segment to be
        `EXCAVATING` and every deeper slot on the same segment — any slot whose
        `depth_top_inches` is greater — to be `INSTALLED` or `VERIFIED`
        (`ERR_SLOT_ORDER_VIOLATION`)."

        Design: Corner/validations/deeper_first_install_order_enforced
        """
        _project, parts, seg = self._excavating_segment(api, "V9")
        p1, p2 = parts
        deep = reserve_slot(seg["id"], p1["id"], depth_top_inches=36, depth_bottom_inches=60,
                            install_start_at="2026-09-01T00:00:00Z",
                            install_end_at="2026-09-03T00:00:00Z")
        shallow = reserve_slot(seg["id"], p2["id"], depth_top_inches=12, depth_bottom_inches=24,
                               install_start_at="2026-09-03T00:00:00Z",
                               install_end_at="2026-09-05T00:00:00Z")

        resp = api.transition_occupancy_slot(
            shallow["id"], {"to": "INSTALLING"}, make_coordinator_headers(p2["id"]))
        validate_error(resp, ApiErrorId.ERR_SLOT_ORDER_VIOLATION)

        transition_slot(deep["id"], "INSTALLING", p1["id"])
        transition_slot(deep["id"], "INSTALLED", p1["id"])
        resp = api.transition_occupancy_slot(
            shallow["id"], {"to": "INSTALLING"}, make_coordinator_headers(p2["id"]))
        data = validate_success(resp, 200)
        assert data["status"] == "INSTALLING", (
            f"shallow install proceeds once the deeper band is INSTALLED, got {data['status']}"
        )

    def test_slot_install_failed_retry_cycle(self, api):
        """PRD §3.4: "From `INSTALLING` the coordinator reports success
        (`→ INSTALLED`) or failure (`→ INSTALL_FAILED`); a failed install may
        be retried (`INSTALL_FAILED → INSTALLING`) under the same deeper-first
        gate."

        Design: Corner/state_machines/slot_install_failed_retry_cycle
        """
        _project, parts, seg = self._excavating_segment(api, "SM3")
        p1, _p2 = parts
        s1 = reserve_slot(seg["id"], p1["id"], depth_top_inches=36, depth_bottom_inches=60,
                          install_start_at="2026-09-01T00:00:00Z",
                          install_end_at="2026-09-03T00:00:00Z")
        transition_slot(s1["id"], "INSTALLING", p1["id"])
        failed = transition_slot(s1["id"], "INSTALL_FAILED", p1["id"])
        assert failed["status"] == "INSTALL_FAILED"
        retried = transition_slot(s1["id"], "INSTALLING", p1["id"])
        assert retried["status"] == "INSTALLING", (
            f"retry cycle re-enters INSTALLING, got {retried['status']}"
        )


class TestSegmentCreation:
    def test_create_segment_missing_required_field(self, api):
        """PRD §3.3: "The `ProgramManager` decomposes the route into trench
        segments, each created in `PLANNED` status with `project_id`, a
        human-readable `segment_code`, a `length_ft` in feet (greater than
        zero), a `max_depth_inches` usable depth (greater than zero), and an
        optional `parcel_ids` array naming every parcel the segment passes
        through."
        PRD §2.10: "Structural validation follows — required fields present,
        types valid, enum members recognized, and start-before-end ordering on
        windows — with failures returning `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/create_segment_missing_required_field
        """
        project = create_project(name="ReqFields", rule20_credit_cents=0,
                                 estimated_total_cost_cents=500000,
                                 target_cutover_on="2026-12-31T00:00:00Z")
        resp = api.create_trench_segment(
            {"project_id": project["id"], "segment_code": "SEG-X", "length_ft": 100},
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
