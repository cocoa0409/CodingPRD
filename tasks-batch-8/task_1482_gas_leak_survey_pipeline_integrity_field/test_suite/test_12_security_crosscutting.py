"""Authentication, RBAC, optimistic concurrency, and cascade invariants
(PRD §2.1, §2.5, §2.7, §3.12)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    get_success_data,
    make_leak,
    make_org,
    setup_open_leak,
    setup_repair_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_field_technician_payload,
    create_leak_payload,
    create_pipe_segment_payload,
    create_regrade_payload,
    create_schedule_repair_payload,
)


class TestAuthentication:
    def test_unauthenticated_missing_role_header(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role string
        outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/unauthenticated_missing_role_header
        """
        make_org()
        resp = api.create_pipe_segment(
            create_pipe_segment_payload(segment_code="SEG-AUTH"),
            {"Content-Type": "application/json"},  # auth headers stripped
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRbac:
    def test_field_technician_cannot_create_pipe_segment(self, api):
        """PRD §4: POST /pipe-segments is authorized for `IntegrityAnalyst` only;
        §2.1: "A request whose role is recognized but not permitted to invoke the
        endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/field_technician_cannot_create_pipe_segment
        """
        ctx = make_org()
        resp = api.create_pipe_segment(
            create_pipe_segment_payload(segment_code="SEG-RB1"), ctx["ft_h"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_dispatch_coordinator_cannot_accept_survey_run(self, api):
        """PRD §4: POST /survey-runs/{id}/accept is authorized for
        `IntegrityAnalyst` only; §2.1: rejected with `ERR_FORBIDDEN` (HTTP 403)
        when invoked by another recognized role.

        Design: Corner/rbac/dispatch_coordinator_cannot_accept_survey_run
        """
        ctx = make_org()
        resp = api.accept_run(NON_EXISTENT_UUID, ctx["dc_h"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_integrity_analyst_cannot_create_instrument(self, api):
        """PRD §4: POST /instruments is authorized for `CalibrationTech` only —
        even the program-owning `IntegrityAnalyst` is rejected with
        `ERR_FORBIDDEN` (HTTP 403) per §2.1.

        Design: Corner/rbac/integrity_analyst_cannot_create_instrument
        """
        ctx = make_org()
        resp = api.create_instrument(
            {"serial_number": "I-CGI-RB3", "instrument_type": "CGI"}, ctx["ia_h"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_compliance_officer_cannot_dispatch_repair_order(self, api):
        """PRD §4: POST /repair-orders/{id}/dispatch is authorized for
        `DispatchCoordinator` only; §2.1: `ERR_FORBIDDEN` (HTTP 403) otherwise.

        Design: Corner/rbac/compliance_officer_cannot_dispatch_repair_order
        """
        ctx = make_org()
        resp = api.dispatch_repair_order(NON_EXISTENT_UUID, {}, ctx["co_h"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_field_technician_cannot_list_compliance_reports(self, api):
        """PRD §4: GET /compliance-reports is authorized for `ComplianceOfficer`
        and `IntegrityAnalyst` only; §2.1: `ERR_FORBIDDEN` (HTTP 403) applies to
        reads as well as writes.

        Design: Corner/rbac/field_technician_cannot_list_compliance_reports
        """
        ctx = make_org()
        resp = api.list_compliance_reports(ctx["ft_h"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_shared_segment_list_allowed_for_peer_roles(self, api):
        """PRD §4: GET /pipe-segments is authorized for `IntegrityAnalyst`,
        `ComplianceOfficer`, `FieldTechnician`, and `DispatchCoordinator` — the
        two peer roles both receive the array listing.

        Design: Corner/rbac/shared_segment_list_allowed_for_peer_roles
        """
        ctx = make_org()
        get_success_data(api.create_pipe_segment(
            create_pipe_segment_payload(segment_code="SEG-RB6"), ctx["ia_h"],
        ))
        _, meta_dc = validate_paginated(api.list_pipe_segments(ctx["dc_h"]))
        _, meta_co = validate_paginated(api.list_pipe_segments(ctx["co_h"]))
        assert meta_dc["total_count"] == 1
        assert meta_co["total_count"] == 1


class TestValidationOrdering:
    def test_forbidden_role_beats_not_found(self, api):
        """PRD §2.5: "Authorization comes second: a recognized role invoking an
        endpoint it is not permitted to use yields `ERR_FORBIDDEN`. Third, every
        identifier referenced by the request — path-template identifiers resolved
        left to right, then identifiers referenced in the request body — must
        resolve to an existing entity, else `ERR_NOT_FOUND`." — a
        `DispatchCoordinator` probing a non-existent run id on the analyst-only
        accept endpoint gets 403, not 404.

        Design: Corner/validations/forbidden_role_beats_not_found
        """
        ctx = make_org()
        resp = api.accept_run(NON_EXISTENT_UUID, ctx["dc_h"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_schedule_repair_missing_leak_returns_not_found(self, api):
        """PRD §2.5: "Third, every identifier referenced by the request —
        path-template identifiers resolved left to right, then identifiers
        referenced in the request body — must resolve to an existing entity, else
        `ERR_NOT_FOUND`."

        Design: Corner/validations/schedule_repair_missing_leak_returns_not_found
        """
        ctx = setup_open_leak(route_code="R-NF")
        resp = api.schedule_repair(
            NON_EXISTENT_UUID,
            create_schedule_repair_payload(ctx["leak"]["version"]),
            ctx["dc_h"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestOptimisticConcurrency:
    def test_occ_stale_leak_version_on_schedule_repair(self, api):
        """PRD §2.7: "scheduling a repair for a leak requires the request body to
        carry `expected_leak_version`, the value of the leak's `version` the
        dispatcher last observed; if the leak's current `version` has advanced
        since then — for example because the leak was re-graded or already
        scheduled — the request is rejected with `ERR_STALE_LEAK_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting/occ_stale_leak_version_on_schedule_repair
        """
        ctx = setup_open_leak(route_code="R-OCC1")
        leak = ctx["leak"]
        observed_version = leak["version"]
        get_success_data(api.regrade_leak(
            leak["id"], create_regrade_payload(new_grade="G1"), ctx["ft_h"],
        ))
        resp = api.schedule_repair(
            leak["id"],
            create_schedule_repair_payload(observed_version),
            ctx["dc_h"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_LEAK_VERSION)
        after = get_success_data(api.get_leak(leak["id"], ctx["dc_h"]))
        assert after["status"] == "OPEN"


class TestSegmentCascadeInvariant:
    def test_out_of_service_clears_counters_and_abandons_leaks(self, api):
        """PRD §3.12: "The transition `ACTIVE → OUT_OF_SERVICE` cascades: every
        leak on the segment in `OPEN` or `REPAIR_SCHEDULED` moves to
        `ABANDONED_SEGMENT`; any repair order on those leaks still in
        `PENDING_DISPATCH` moves to `CANCELLED`; all three open-grade counters
        recompute to 0; and `posture` recomputes to `NORMAL`."

        Design: Difficulty/compensating_invariant/leak_open_grade_counters_invariant_on_out_of_service
        """
        ctx = setup_open_leak(
            route_code="R-INV2",
            leak_overrides={
                "concentration_ppm": 30000.0,
                "distance_to_building_feet": 2.0,
                "bar_hole_reading_pct_lel": 40.0,
                "is_migration_evidence": True,
            },
        )
        segment, run = ctx["segments"][0], ctx["run"]
        g3 = {"concentration_ppm": 500.0, "bar_hole_reading_pct_lel": 1.0,
              "is_migration_evidence": False}
        leak_g3a = make_leak(ctx, segment["id"], run["id"],
                             distance_to_building_feet=300.0, **g3)
        leak_g3b = make_leak(ctx, segment["id"], run["id"],
                             concentration_ppm=600.0, distance_to_building_feet=350.0,
                             bar_hole_reading_pct_lel=1.0, is_migration_evidence=False)

        before = get_success_data(api.get_pipe_segment(segment["id"], ctx["ia_h"]))
        assert before["open_grade1_count"] == 1
        assert before["open_grade3_count"] == 2
        assert before["posture"] == "CRITICAL"  # one open G1 (PRD §2.8)

        get_success_data(api.out_of_service_segment(segment["id"], ctx["ia_h"]))
        after = get_success_data(api.get_pipe_segment(segment["id"], ctx["ia_h"]))
        assert after["open_grade1_count"] == 0
        assert after["open_grade2_count"] == 0
        assert after["open_grade3_count"] == 0
        assert after["posture"] == "NORMAL"
        for leak in (ctx["leak"], leak_g3a, leak_g3b):
            state = get_success_data(api.get_leak(leak["id"], ctx["ia_h"]))
            assert state["status"] == "ABANDONED_SEGMENT"

    def test_out_of_service_cancels_pending_repair_orders(self, api):
        """PRD §3.12: "any repair order on those leaks still in `PENDING_DISPATCH`
        moves to `CANCELLED`" when the segment goes out of service, while the
        leak itself moves to `ABANDONED_SEGMENT`.

        Design: Difficulty/compensating_invariant/leak_open_grade_counters_invariant_on_out_of_service
        """
        ctx = setup_repair_order(route_code="R-INV3")  # order PENDING_DISPATCH
        segment = ctx["segments"][0]
        get_success_data(api.out_of_service_segment(segment["id"], ctx["ia_h"]))
        order = get_success_data(api.get_repair_order(ctx["order"]["id"], ctx["dc_h"]))
        assert order["dispatch_status"] == "CANCELLED"
        leak = get_success_data(api.get_leak(ctx["leak"]["id"], ctx["ia_h"]))
        assert leak["status"] == "ABANDONED_SEGMENT"
