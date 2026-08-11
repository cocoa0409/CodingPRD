"""Construction phasing: closure-duration limits, half-open overlap, contractor buffers,
activation windows, and cross-sponsor integrity (PRD §3.8)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    assert_construction_phase,
    create_phase_payload,
    create_sponsor, create_facility, create_contractor,
    create_phase, setup_active_grant, setup_phase_scenario, set_clock,
    TEST_USERS, ApiErrorId,
)

FAA = TEST_USERS["faa_manager_headers"]
SPONSOR = TEST_USERS["sponsor_staff_headers"]


class TestFacilityOverlap:
    def _setup_with_phase_a(self):
        """ACTIVE grant with facility F1, three distinct contractors (so the contractor
        buffer rule cannot interfere), and phase A FULL_CLOSURE 06-01 -> 06-03 on F1."""
        ctx = setup_phase_scenario()
        ctx["c_b"] = create_contractor(ctx["sponsor"]["id"], name="Beta")
        ctx["c_c"] = create_contractor(ctx["sponsor"]["id"], name="Gamma")
        phase_a = create_phase(ctx["grant"]["id"], ctx["project"]["id"],
                               ctx["facility"]["id"], ctx["contractor"]["id"],
                               closure_type="FULL_CLOSURE",
                               start_utc="2026-06-01T00:00:00Z",
                               end_utc="2026-06-03T00:00:00Z")
        return ctx, phase_a

    def test_facility_full_closure_adjacency_allowed(self):
        """PRD §3.8: "a `FULL_CLOSURE` phase must not overlap any other `FULL_CLOSURE` phase
        on the same facility that is in `PLANNED` or `ACTIVE`, compared under half-open
        interval semantics so that pure adjacency, one phase's `end_utc` equaling another's
        `start_utc`, is allowed, with a true overlap rejected as `ERR_FACILITY_OVERLAP`
        (HTTP 409)".

        Design: Difficulty/resource_temporal_overlap/facility_full_closure_adjacency
        """
        ctx, phase_a = self._setup_with_phase_a()
        # Phase B starts exactly at A's end: legal adjacency under half-open semantics.
        phase_b = validate_success(api_client.create_phase(
            create_phase_payload(ctx["grant"]["id"], ctx["project"]["id"],
                                 ctx["facility"]["id"], ctx["c_b"]["id"],
                                 closure_type="FULL_CLOSURE",
                                 start_utc="2026-06-03T00:00:00Z",
                                 end_utc="2026-06-04T00:00:00Z"), SPONSOR), 201)
        assert_construction_phase(phase_b)
        assert phase_b["status"] == "PLANNED"

    def test_facility_full_closure_overlap_rejected(self):
        """PRD §3.8: "a true overlap rejected as `ERR_FACILITY_OVERLAP` (HTTP 409)" —
        phase C starts one hour before phase A's end, so the half-open windows intersect.

        Design: Difficulty/resource_temporal_overlap/facility_full_closure_adjacency
        """
        ctx, phase_a = self._setup_with_phase_a()
        res = api_client.create_phase(
            create_phase_payload(ctx["grant"]["id"], ctx["project"]["id"],
                                 ctx["facility"]["id"], ctx["c_c"]["id"],
                                 closure_type="FULL_CLOSURE",
                                 start_utc="2026-06-02T23:00:00Z",
                                 end_utc="2026-06-04T12:00:00Z"), SPONSOR)
        validate_error(res, ApiErrorId.ERR_FACILITY_OVERLAP, expected_status=409)


class TestContractorBuffer:
    def _setup_with_phase_a(self):
        """ACTIVE grant with facilities F1/F2 (so the facility rule cannot interfere), one
        shared contractor, and phase A on F1 FULL_CLOSURE 06-01 -> 06-03."""
        ctx = setup_phase_scenario()
        ctx["f2"] = create_facility(ctx["sponsor"]["id"], name="Taxiway B",
                                    facility_type="TAXIWAY")
        phase_a = create_phase(ctx["grant"]["id"], ctx["project"]["id"],
                               ctx["facility"]["id"], ctx["contractor"]["id"],
                               closure_type="FULL_CLOSURE",
                               start_utc="2026-06-01T00:00:00Z",
                               end_utc="2026-06-03T00:00:00Z")
        return ctx, phase_a

    def test_contractor_buffer_exactly_24h_allowed(self):
        """PRD §3.8: "any two phases sharing the same `contractor_id` must leave at least a
        24-hour buffer between their windows in either direction, with a gap of exactly 24
        hours permitted and anything shorter rejected as
        `ERR_CONTRACTOR_BUFFER_CONFLICT` (HTTP 409)".
        Phase B starts 2026-06-04T00:00:00Z, exactly 24 hours after A's end.

        Design: Difficulty/resource_temporal_overlap/contractor_minimum_buffer_gap
        """
        ctx, phase_a = self._setup_with_phase_a()
        phase_b = validate_success(api_client.create_phase(
            create_phase_payload(ctx["grant"]["id"], ctx["project"]["id"],
                                 ctx["f2"]["id"], ctx["contractor"]["id"],
                                 closure_type="NIGHT_ONLY",
                                 start_utc="2026-06-04T00:00:00Z",
                                 end_utc="2026-06-04T06:00:00Z"), SPONSOR), 201)
        assert phase_b["status"] == "PLANNED"

    def test_contractor_buffer_23h_rejected(self):
        """PRD §3.8: "with a gap of exactly 24 hours permitted and anything shorter rejected
        as `ERR_CONTRACTOR_BUFFER_CONFLICT` (HTTP 409)" — phase C leaves only 23 hours
        between the shared contractor's windows.

        Design: Difficulty/resource_temporal_overlap/contractor_minimum_buffer_gap
        """
        ctx, phase_a = self._setup_with_phase_a()
        res = api_client.create_phase(
            create_phase_payload(ctx["grant"]["id"], ctx["project"]["id"],
                                 ctx["f2"]["id"], ctx["contractor"]["id"],
                                 closure_type="NIGHT_ONLY",
                                 start_utc="2026-06-03T23:00:00Z",
                                 end_utc="2026-06-04T05:00:00Z"), SPONSOR)
        validate_error(res, ApiErrorId.ERR_CONTRACTOR_BUFFER_CONFLICT, expected_status=409)


class TestPhaseCreationOrder:
    def test_phase_create_safety_check_masks_cross_sponsor(self):
        """PRD §3.8: "Creation enforces its checks in a fixed order after reference
        existence: the closure-duration safety limits — a `FULL_CLOSURE` phase may span at
        most 72 hours and a `NIGHT_ONLY` phase at most 8 hours, with longer windows rejected
        as `ERR_CLOSURE_DURATION_EXCEEDED` (HTTP 422)".
        PRD §3.8: "and finally cross-sponsor integrity — the referenced facility, contractor,
        and project must all belong to the same sponsor as the grant, otherwise
        `ERR_CROSS_SPONSOR_REFERENCE` (HTTP 422)".
        A 100-hour FULL_CLOSURE referencing another sponsor's facility fails the safety
        check first.

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_phase_create
        """
        ctx = setup_active_grant()
        sponsor_b = create_sponsor(name="Sponsor B")
        facility_b = create_facility(sponsor_b["id"], name="Runway 09/27",
                                     facility_type="RUNWAY")
        contractor = create_contractor(ctx["sponsor"]["id"])
        res = api_client.create_phase(create_phase_payload(
            ctx["grant"]["id"], ctx["project"]["id"], facility_b["id"], contractor["id"],
            closure_type="FULL_CLOSURE",
            start_utc="2026-06-01T00:00:00Z",
            end_utc="2026-06-05T04:00:00Z"), SPONSOR)  # 100 hours > 72-hour cap
        validate_error(res, ApiErrorId.ERR_CLOSURE_DURATION_EXCEEDED, expected_status=422)
        assert res.json()["data"]["error_id"] != "ERR_CROSS_SPONSOR_REFERENCE"

    def test_phase_create_cross_sponsor_reference_isolated(self):
        """PRD §3.8: "and finally cross-sponsor integrity — the referenced facility,
        contractor, and project must all belong to the same sponsor as the grant, otherwise
        `ERR_CROSS_SPONSOR_REFERENCE` (HTTP 422)."
        With duration, window, overlap, and buffer all clean, the referential check fires.

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_phase_create
        """
        ctx = setup_active_grant()
        sponsor_b = create_sponsor(name="Sponsor B")
        facility_b = create_facility(sponsor_b["id"], name="Runway 09/27",
                                     facility_type="RUNWAY")
        contractor = create_contractor(ctx["sponsor"]["id"])
        res = api_client.create_phase(create_phase_payload(
            ctx["grant"]["id"], ctx["project"]["id"], facility_b["id"], contractor["id"],
            closure_type="FULL_CLOSURE",
            start_utc="2026-06-01T00:00:00Z",
            end_utc="2026-06-02T00:00:00Z"), SPONSOR)  # 24 hours: within the cap
        validate_error(res, ApiErrorId.ERR_CROSS_SPONSOR_REFERENCE, expected_status=422)


class TestPhaseWindowAndActivation:
    def test_phase_activation_window_enforced(self):
        """PRD §3.8: "Activation by `SponsorStaff` moves `PLANNED` to `ACTIVE` under two
        checks: the funding grant must be `ACTIVE` (otherwise `ERR_GRANT_NOT_ACTIVE`) and
        the logical clock must sit inside the window — at or after `start_utc` and strictly
        before `end_utc` — otherwise `ERR_PHASE_OUTSIDE_WINDOW` (HTTP 422)."

        Design: Corner/state_machines/phase_activation_window_enforced
        """
        set_clock("2026-05-01T00:00:00Z")
        ctx = setup_phase_scenario()
        phase = create_phase(ctx["grant"]["id"], ctx["project"]["id"],
                             ctx["facility"]["id"], ctx["contractor"]["id"],
                             closure_type="NIGHT_ONLY",
                             start_utc="2026-06-01T22:00:00Z",
                             end_utc="2026-06-02T06:00:00Z")
        # Clock (2026-05-01) is before the window opens.
        res = api_client.activate_phase(phase["id"], SPONSOR)
        validate_error(res, ApiErrorId.ERR_PHASE_OUTSIDE_WINDOW, expected_status=422)

        set_clock("2026-06-01T23:00:00Z")  # inside [start, end)
        activated = validate_success(api_client.activate_phase(phase["id"], SPONSOR), 200)
        assert activated["status"] == "ACTIVE"

    def test_phase_window_invalid_rejected(self):
        """PRD §3.8: "window validity — `end_utc` must be strictly after `start_utc`,
        otherwise `ERR_PHASE_WINDOW_INVALID` (HTTP 422)".
        A zero-length window (end == start) violates strict ordering.

        Design: Corner/validations/phase_window_invalid_rejected
        """
        ctx = setup_phase_scenario()
        res = api_client.create_phase(create_phase_payload(
            ctx["grant"]["id"], ctx["project"]["id"], ctx["facility"]["id"],
            ctx["contractor"]["id"], closure_type="FULL_CLOSURE",
            start_utc="2026-06-01T00:00:00Z",
            end_utc="2026-06-01T00:00:00Z"), SPONSOR)
        validate_error(res, ApiErrorId.ERR_PHASE_WINDOW_INVALID, expected_status=422)
