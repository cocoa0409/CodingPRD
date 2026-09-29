"""Multi-hop cascades from identity suspension and license termination, and the
coverage map over an empty cell universe.
"""

import pytest

from test_helpers import (
    COMPLIANCE_OFFICER_2_USER_ID,
    AuditEventType,
    AuditSubjectEntity,
    CoverageBasis,
    EntitlementStatus,
    IdentityStatus,
    JobAbortReason,
    JobStatus,
    LicenseStatus,
    SeatRevocationReason,
    SeatStatus,
    SessionStatus,
    SessionTerminationReason,
    SettlementStatus,
    ToolStatus,
    assert_coverage_map,
    assert_gateway_fee_breakdown,
    assert_gateway_session,
    assert_seat_counts,
    assert_single_audit_event,
    assert_technician,
    factories,
    fixtures,
    make_compliance_officer_headers,
    validate_paginated,
    validate_success,
)


def _tool_row(api, ctx, tool_id):
    rows, _meta = validate_paginated(
        api.list_shop_diagnostic_tools(
            ctx["shop"]["id"], ctx["manager_headers"], {"limit": 100}
        )
    )
    return next(row for row in rows if row["id"] == tool_id)


class TestTechnicianSuspensionCascade:
    """Suspending one identity walks seat, session, job and version pin."""

    def test_suspension_revokes_the_seat_and_terminates_the_priced_session(self, api):
        """The first two hops revoke the seat and close out the session.

        PRD 3.5: hop one "takes every seat held by this technician that is still
        `ACTIVE` to `REVOKED` with `revocation_reason` of `TECHNICIAN_SUSPENDED`",
        and hop two "takes every gateway session on one of those just-revoked
        seats that is still `ACTIVE` through `ACTIVE → TERMINATED` with
        `termination_reason` of `TECHNICIAN_SUSPENDED`, computes and stamps its
        access fee". With one module flash the base subtotal is 2,500 plus 300
        plus 3,000, the discount is five percent of 5,800 and the surcharge four
        percent.

        Design: Difficulty/transitive_cascade/technician_suspend_four_hop_seat_session_job_pin_cascade
        """
        ctx = fixtures.build_session_with_started_job(
            api, covered_area_codes=("POWERTRAIN",)
        )
        technician_id = ctx["technicians"]["main"]["id"]

        suspended = validate_success(
            api.suspend_technician(
                technician_id,
                factories.reason_payload("identity document flagged"),
                make_compliance_officer_headers(COMPLIANCE_OFFICER_2_USER_ID),
            )
        )
        assert_technician(suspended)
        assert suspended["identity_status"] == IdentityStatus.SUSPENDED

        seat = validate_success(
            api.get_seat_assignment(ctx["seats"]["main"]["id"], ctx["manager_headers"])
        )
        assert seat["status"] == SeatStatus.REVOKED
        assert seat["revocation_reason"] == SeatRevocationReason.TECHNICIAN_SUSPENDED

        entitlement = fixtures.refresh_entitlement(api, ctx)
        assert_seat_counts(entitlement, 0, 3)

        session = validate_success(
            api.get_gateway_session(
                ctx["sessions"]["main"]["id"], ctx["manager_headers"]
            )
        )
        assert_gateway_session(session)
        assert session["status"] == SessionStatus.TERMINATED
        assert (
            session["termination_reason"]
            == SessionTerminationReason.TECHNICIAN_SUSPENDED
        )
        assert_gateway_fee_breakdown(session, 5800, 290, 232, 5742)

        shop = fixtures.refresh_shop(api, ctx)
        assert shop["gateway_fee_accrued_cents"] == 5742

        tool = _tool_row(api, ctx, ctx["tools"]["main"]["id"])
        assert tool["status"] == ToolStatus.IDLE
        assert tool["occupied_by_session_id"] is None

    def test_the_cascade_aborts_the_live_job_and_releases_the_version_pin(self, api):
        """The last two hops abort the job and decrement the pin count.

        PRD 3.5: hop three "takes every programming job on one of those
        just-terminated sessions whose status is `QUEUED` or `IN_PROGRESS` to
        `ABORTED` with `abort_reason` of `SESSION_TERMINATED`", and hop four
        "decrements by 1 the `active_pin_count` of the publication version each
        just-aborted job was pinned to".

        Design: Difficulty/transitive_cascade/technician_suspend_four_hop_seat_session_job_pin_cascade
        """
        ctx = fixtures.build_session_with_started_job(
            api, covered_area_codes=("POWERTRAIN",)
        )
        technician_id = ctx["technicians"]["main"]["id"]
        validate_success(
            api.suspend_technician(
                technician_id,
                factories.reason_payload("identity document flagged"),
                make_compliance_officer_headers(COMPLIANCE_OFFICER_2_USER_ID),
            )
        )

        job = validate_success(
            api.get_programming_job(ctx["jobs"]["main"]["id"], ctx["manager_headers"])
        )
        assert job["status"] == JobStatus.ABORTED
        assert job["abort_reason"] == JobAbortReason.SESSION_TERMINATED

        version = fixtures.refresh_version(api, ctx)
        assert version["active_pin_count"] == 0

        events, _meta = validate_paginated(
            api.list_audit_events(
                make_compliance_officer_headers(),
                {
                    "subject_entity": AuditSubjectEntity.TECHNICIAN,
                    "subject_id": technician_id,
                    "limit": 100,
                },
            )
        )
        assert_single_audit_event(
            events, AuditEventType.TECHNICIAN_SUSPENDED, subject_id=technician_id
        )


class TestLicenseTerminationCascade:
    """Terminating a license settles entitlements, revokes seats, closes sessions."""

    def test_termination_lapses_and_settles_the_entitlement(self, api):
        """Hop one runs the final settlement arithmetic on the live entitlement.

        PRD 3.2: termination "takes every entitlement drawing on this license that
        is currently `ACTIVE` through `ACTIVE → LAPSED`, running the final
        settlement arithmetic of §3.4 on each", and "The supplied `reason` is
        written to `suspension_reason`, the status becomes `TERMINATED`, `version`
        advances by 1". Ten elapsed days of a 31-day window settle 84,999 at
        27,419.

        Design: Difficulty/transitive_cascade/license_terminate_three_hop_entitlement_settlement_cascade
        """
        ctx = fixtures.build_terminated_license_scenario(api)

        license_row = ctx["license"]
        assert license_row["status"] == LicenseStatus.TERMINATED
        assert license_row["suspension_reason"] == "OEM withdrew the independent offer"

        entitlement = fixtures.refresh_entitlement(api, ctx)
        assert entitlement["status"] == EntitlementStatus.LAPSED
        assert entitlement["settled_cents"] == 27419
        assert entitlement["settlement_status"] == SettlementStatus.SETTLED

        shop = ctx["shop"]
        assert shop["data_credit_balance_cents"] == 172581
        assert shop["funded_credit_total_cents"] == 200000
        assert shop["coverage_completeness_pct"] == pytest.approx(0.00, abs=0.005)

    def test_termination_revokes_the_seat_and_prices_the_terminated_session(self, api):
        """Hops two and three revoke the seat and close the session with its fee.

        PRD 3.2: "every seat on each just-lapsed entitlement that is still
        `ACTIVE` goes `ACTIVE → REVOKED` with its `revocation_reason` set to
        `LICENSE_TERMINATED`", and "every gateway session held on one of those
        just-revoked seats that is still `ACTIVE` goes `ACTIVE → TERMINATED` with
        its `termination_reason` set to `SEAT_REVOKED`". A session with no
        billable job prices at 2,500 plus 300 with no discount and a four percent
        surcharge.

        Design: Difficulty/transitive_cascade/license_terminate_three_hop_entitlement_settlement_cascade
        """
        ctx = fixtures.build_terminated_license_scenario(api)

        seat = validate_success(
            api.get_seat_assignment(ctx["seats"]["main"]["id"], ctx["manager_headers"])
        )
        assert seat["status"] == SeatStatus.REVOKED
        assert seat["revocation_reason"] == SeatRevocationReason.LICENSE_TERMINATED

        entitlement = fixtures.refresh_entitlement(api, ctx)
        assert_seat_counts(entitlement, 0, 3)

        session = validate_success(
            api.get_gateway_session(
                ctx["sessions"]["main"]["id"], ctx["manager_headers"]
            )
        )
        assert session["status"] == SessionStatus.TERMINATED
        assert session["termination_reason"] == SessionTerminationReason.SEAT_REVOKED
        assert_gateway_fee_breakdown(session, 2800, 0, 112, 2912)

        shop = fixtures.refresh_shop(api, ctx)
        assert shop["gateway_fee_accrued_cents"] == 2912

        tool = _tool_row(api, ctx, ctx["tools"]["main"]["id"])
        assert tool["status"] == ToolStatus.IDLE
        assert tool["occupied_by_session_id"] is None


class TestCoverageMapOverAnEmptyUniverse:
    """With no active entitlement there are no cells to grade."""

    def test_an_empty_cell_universe_reports_zeroes_and_an_empty_gap_list(self, api):
        """No active entitlement means no cells, and completeness is exactly 0.00.

        PRD 3.9: "Only entitlements in status `ACTIVE` contribute — `PENDING`,
        `LAPSED` and `CANCELLED` entitlements are excluded entirely, so a shop
        with no active entitlement has a cell universe of size zero", and
        "`completeness_pct` is 100 multiplied by the numerator, divided by
        `total_cells`, rounded half up to two decimal places, and it is exactly
        `0.00` when `total_cells` is zero".

        Design: Difficulty/boundary_precision_check/coverage_map_with_zero_active_entitlements_returns_empty_set_zeros
        """
        ctx = fixtures.build_entitled_shop(
            api,
            area_codes=("POWERTRAIN",),
            covered_area_codes=("POWERTRAIN",),
            activate_entitlement=False,
        )
        fixtures.add_publication_version(api, ctx, system_area_code="POWERTRAIN")

        coverage = validate_success(
            api.get_coverage_map(
                ctx["shop"]["id"],
                ctx["manager_headers"],
                {"basis": CoverageBasis.EFFECTIVE},
            )
        )

        assert_coverage_map(coverage)
        assert coverage["basis"] == CoverageBasis.EFFECTIVE
        assert coverage["total_cells"] == 0
        assert coverage["covered_cells"] == 0
        assert coverage["degraded_cells"] == 0
        assert coverage["gap_cells"] == 0
        assert coverage["completeness_pct"] == pytest.approx(0.00, abs=0.005)
        assert coverage["gaps"] == []

    def test_a_pending_entitlement_leaves_the_stored_percentage_at_zero(self, api):
        """The pending purchase contributes nothing and the shop reads 0.00.

        PRD 3.9: "Only entitlements in status `ACTIVE` contribute — `PENDING`,
        `LAPSED` and `CANCELLED` entitlements are excluded entirely, so a shop with
        no active entitlement has a cell universe of size zero." And "The
        effective-basis value is additionally **stored** on the shop as
        `coverage_completeness_pct`", which therefore stays at `0.00` while the
        only entitlement is still `PENDING`.

        Design: Difficulty/boundary_precision_check/coverage_map_with_zero_active_entitlements_returns_empty_set_zeros
        """
        ctx = fixtures.build_entitled_shop(
            api,
            area_codes=("POWERTRAIN",),
            covered_area_codes=("POWERTRAIN",),
            activate_entitlement=False,
        )
        fixtures.add_publication_version(api, ctx, system_area_code="POWERTRAIN")
        validate_success(
            api.get_coverage_map(
                ctx["shop"]["id"],
                ctx["manager_headers"],
                {"basis": CoverageBasis.EFFECTIVE},
            )
        )

        entitlement = fixtures.refresh_entitlement(api, ctx)
        assert entitlement["status"] == EntitlementStatus.PENDING

        shop = fixtures.refresh_shop(api, ctx)
        assert shop["coverage_completeness_pct"] == pytest.approx(0.00, abs=0.005)
