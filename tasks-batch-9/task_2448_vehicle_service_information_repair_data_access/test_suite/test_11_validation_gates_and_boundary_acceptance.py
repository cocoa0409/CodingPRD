"""Validation gates seen from both sides: the refusal and the neighbouring pass.

Covers seat availability against the re-seat exemption, tool ownership measured
through the seat, the fiscal-capacity rung, inclusive session-window
containment, and the ADAS-only calibration-document gate.
"""

import pytest

from test_helpers import (
    DEFAULT_ENTITLEMENT_WINDOW_END,
    DEFAULT_ENTITLEMENT_WINDOW_START,
    VIN_SECONDARY,
    ApiErrorId,
    EntitlementStatus,
    JobStatus,
    JobType,
    SeatStatus,
    SessionStatus,
    ToolStatus,
    assert_gateway_session,
    assert_programming_job,
    assert_seat_assignment,
    assert_seat_counts,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSeatAvailabilityAndTheReseatExemption:
    """A full entitlement refuses a newcomer but still accepts the sitting holder."""

    def test_a_second_technician_is_refused_while_the_holder_may_re_seat(self, api):
        """One purchased seat blocks the newcomer and re-seats the incumbent.

        PRD 3.5: "Seating a technician who does **not** already hold an active
        seat on the entitlement consumes capacity, and requires at least one free
        seat: if the entitlement's `seats_available` is 0, the request is refused
        with `ERR_NO_SEATS_AVAILABLE` (HTTP 409)." The exemption is explicit:
        "Seating the *same* technician again on the *same* entitlement is not an
        error — it is a **re-seat**, and it drives the prior row
        `ACTIVE → SUPERSEDED` while the new row opens `ACTIVE`", so "the
        entitlement's `seats_assigned` is unchanged by a re-seat, and the
        seat-availability check below does not apply to it".

        Design: Corner/validations/no_seats_available_violation_returns_error
        """
        ctx = fixtures.build_entitled_shop(
            api, covered_area_codes=("POWERTRAIN",), seats_total=1
        )
        fixtures.add_technician(api, ctx, key="holder", full_name="Tina Tech")
        fixtures.add_technician(
            api,
            ctx,
            key="newcomer",
            full_name="Raj Wrench",
            identity_document_ref="DL-77124",
        )
        fixtures.add_seat(api, ctx, key="holder")
        first_seat_id = ctx["seats"]["holder"]["id"]
        manager = ctx["manager_headers"]

        entitlement = fixtures.refresh_entitlement(api, ctx)
        assert_seat_counts(entitlement, 1, 0)

        validate_error(
            api.create_seat_assignment(
                factories.seat_assignment_payload(
                    entitlement["id"],
                    ctx["technicians"]["newcomer"]["id"],
                    entitlement["version"],
                ),
                manager,
            ),
            ApiErrorId.NO_SEATS_AVAILABLE,
            409,
        )

        reseated = validate_success(
            api.create_seat_assignment(
                factories.seat_assignment_payload(
                    entitlement["id"],
                    ctx["technicians"]["holder"]["id"],
                    entitlement["version"],
                ),
                manager,
            ),
            201,
        )
        assert_seat_assignment(reseated)
        assert reseated["technician_id"] == ctx["technicians"]["holder"]["id"]
        assert reseated["status"] == SeatStatus.ACTIVE
        assert reseated["revocation_reason"] is None

        superseded = validate_success(api.get_seat_assignment(first_seat_id, manager))
        assert superseded["status"] == SeatStatus.SUPERSEDED

        after = fixtures.refresh_entitlement(api, ctx)
        assert_seat_counts(after, 1, 0)

        active_rows, active_meta = validate_paginated(
            api.list_seat_assignments(
                manager,
                {"entitlement_id": entitlement["id"], "status": SeatStatus.ACTIVE},
            )
        )
        assert active_meta["total_count"] == 1
        assert active_rows[0]["id"] == reseated["id"]


class TestToolOwnershipIsMeasuredThroughTheSeat:
    """The tool must belong to the shop holding the entitlement behind the seat."""

    def test_a_foreign_tool_is_refused_while_the_shops_own_tool_is_accepted(self, api):
        """The rival shop's scanner is a 422; the home scanner opens the session.

        PRD 3.7: "The requested tool must belong to the same shop as that
        entitlement; a tool from another shop is refused with
        `ERR_TOOL_SHOP_MISMATCH` (HTTP 422)." On the accepted call, "A successful
        request opens the session in `REQUESTED` with `credential_token` null,
        `termination_reason` null, and all four money fields ... at 0", and a
        tool "starts `IDLE`, and `occupied_by_session_id` names the session
        currently holding it or is null while the tool is idle".

        Design: Corner/validations/tool_shop_mismatch_violation_returns_error
        """
        ctx = fixtures.build_seated_technician(
            api, covered_area_codes=("POWERTRAIN",), tool_serial_no="SN-A-1"
        )
        rival = fixtures.add_second_shop(api, ctx, name="Rival Auto", funding_cents=0)
        fixtures.add_tool(
            api,
            ctx,
            key="rival",
            serial_no="SN-B-1",
            shop_id=rival["shop"]["id"],
            headers=rival["headers"],
        )
        technician_headers = ctx["tech_headers"]["main"]
        seat_id = ctx["seats"]["main"]["id"]

        validate_error(
            api.create_gateway_session(
                factories.gateway_session_payload(
                    seat_id, ctx["tools"]["rival"]["id"]
                ),
                technician_headers,
            ),
            ApiErrorId.TOOL_SHOP_MISMATCH,
            422,
        )

        session = validate_success(
            api.create_gateway_session(
                factories.gateway_session_payload(seat_id, ctx["tools"]["main"]["id"]),
                technician_headers,
            ),
            201,
        )
        assert_gateway_session(session)
        assert session["status"] == SessionStatus.REQUESTED
        assert session["diagnostic_tool_id"] == ctx["tools"]["main"]["id"]
        assert session["credential_token"] is None

        _rows, meta = validate_paginated(
            api.list_gateway_sessions(
                ctx["manager_headers"],
                {"diagnostic_tool_id": ctx["tools"]["rival"]["id"]},
            )
        )
        assert meta["total_count"] == 0

        rival_tools, _tool_meta = validate_paginated(
            api.list_shop_diagnostic_tools(
                rival["shop"]["id"], rival["headers"], {"limit": 100}
            )
        )
        rival_tool = next(
            row for row in rival_tools if row["id"] == ctx["tools"]["rival"]["id"]
        )
        assert rival_tool["status"] == ToolStatus.IDLE
        assert rival_tool["occupied_by_session_id"] is None


class TestFiscalCapacityIsTheLastRung:
    """A thin balance leaves no partial row and no negative ledger."""

    def test_a_shop_that_cannot_pay_buys_nothing_and_keeps_its_balance(self, api):
        """The 85,000 purchase is refused at 402 and the 1,000 balance is intact.

        PRD 3.3: "Only after every other check has passed does the platform test
        whether the shop can pay: if `data_credit_balance_cents` is below the
        provisional `charged_cents` just computed, the purchase is refused with
        `ERR_INSUFFICIENT_DATA_CREDIT` (HTTP 402)." Nothing is stamped, because
        it is only "On success" that "the platform stamps `charged_cents`, debits
        the shop's `data_credit_balance_cents` by that amount"; and
        "`funded_credit_total_cents` is a lifetime total and never decreases for
        any reason."

        Design: Corner/validations/insufficient_data_credit_violation_returns_402
        """
        ctx = fixtures.build_funded_shop(
            api,
            funding_cents=1000,
            shop_name="Thin Wallet",
            covered_area_codes=("POWERTRAIN",),
        )

        validate_error(
            api.create_entitlement(
                factories.entitlement_payload(
                    ctx["shop"]["id"], ctx["license"]["id"]
                ),
                ctx["manager_headers"],
            ),
            ApiErrorId.INSUFFICIENT_DATA_CREDIT,
            402,
        )

        _rows, meta = validate_paginated(
            api.list_entitlements(
                ctx["manager_headers"], {"shop_id": ctx["shop"]["id"]}
            )
        )
        assert meta["total_count"] == 0

        shop = fixtures.refresh_shop(api, ctx)
        assert shop["data_credit_balance_cents"] == 1000
        assert shop["funded_credit_total_cents"] == 1000
        assert shop["gateway_fee_accrued_cents"] == 0
        assert shop["coverage_completeness_pct"] == pytest.approx(0.00, abs=0.005)


class TestSessionWindowContainmentIsInclusive:
    """Coinciding with the entitlement window is inside it; one second past is not."""

    def test_the_exact_entitlement_bounds_are_accepted_and_one_second_over_is_not(
        self, api
    ):
        """A window equal to the entitlement's own window opens a session.

        PRD 3.7: "The session window must sit wholly inside the entitlement's
        coverage window — its start at or after the entitlement's `window_start`
        and its end at or before the entitlement's `window_end` — and its own end
        must be strictly after its own start; any of those failures returns
        `ERR_SESSION_WINDOW_OUTSIDE_ENTITLEMENT` (HTTP 422)." PRD 3.7 also lets
        sessions "be narrowed by `seat_assignment_id`, by `diagnostic_tool_id`
        and by `status`".

        Design: Corner/validations/session_window_exactly_at_entitlement_bounds_satisfaction_passes
        """
        ctx = fixtures.build_seated_technician(api, covered_area_codes=("POWERTRAIN",))
        technician_headers = ctx["tech_headers"]["main"]
        seat_id = ctx["seats"]["main"]["id"]
        tool_id = ctx["tools"]["main"]["id"]

        accepted = validate_success(
            api.create_gateway_session(
                factories.gateway_session_payload(
                    seat_id,
                    tool_id,
                    window_start=DEFAULT_ENTITLEMENT_WINDOW_START,
                    window_end=DEFAULT_ENTITLEMENT_WINDOW_END,
                ),
                technician_headers,
            ),
            201,
        )
        assert_gateway_session(accepted)
        assert accepted["status"] == SessionStatus.REQUESTED
        assert accepted["window_start"] == DEFAULT_ENTITLEMENT_WINDOW_START
        assert accepted["window_end"] == DEFAULT_ENTITLEMENT_WINDOW_END

        validate_error(
            api.create_gateway_session(
                factories.gateway_session_payload(
                    seat_id,
                    tool_id,
                    vin=VIN_SECONDARY,
                    window_start=DEFAULT_ENTITLEMENT_WINDOW_START,
                    window_end="2026-09-01T00:00:01Z",
                ),
                technician_headers,
            ),
            ApiErrorId.SESSION_WINDOW_OUTSIDE_ENTITLEMENT,
            422,
        )

        rows, meta = validate_paginated(
            api.list_gateway_sessions(
                technician_headers, {"seat_assignment_id": seat_id}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == accepted["id"]


class TestTheCalibrationGateIsConditionalOnJobType:
    """Same cell, same pinned version, two job types, two different outcomes."""

    def test_a_flash_starts_where_an_adas_calibration_is_refused(self, api):
        """Only the ADAS_CALIBRATION start looks for a calibration document.

        PRD 3.8: "one gate applies only to ADAS work: when the `job_type` is
        `ADAS_CALIBRATION`, there must exist, for the same model-and-system cell
        as the pinned version's own publication, a publication of type
        `CALIBRATION_DOC` carrying a version that is simultaneously `VALIDATED`
        on its editorial axis and `PUBLISHED` on its availability axis. If no
        such calibration document exists, the start is refused with
        `ERR_CALIBRATION_DOC_REQUIRED` (HTTP 422)." Each queued job left the pin
        count raised, since "A successful queue opens the job in `QUEUED` with
        `repin_count` at 0 and `abort_reason` null, and increments the pinned
        version's `active_pin_count` by 1", and a refused start moves nothing.

        Design: Corner/validations/calibration_doc_gate_applies_only_to_adas_calibration_job_type
        """
        ctx = fixtures.build_active_session(
            api,
            area_codes=("ADAS",),
            covered_area_codes=("ADAS",),
            system_area_code="ADAS",
            validate=False,
        )
        fixtures.add_job(
            api, ctx, key="flash", job_type=JobType.MODULE_FLASH, start=False
        )
        fixtures.add_job(
            api, ctx, key="adas", job_type=JobType.ADAS_CALIBRATION, start=False
        )
        technician_headers = ctx["tech_headers"]["main"]

        started = validate_success(
            api.start_programming_job(ctx["jobs"]["flash"]["id"], technician_headers)
        )
        assert_programming_job(started)
        assert started["status"] == JobStatus.IN_PROGRESS
        assert started["job_type"] == JobType.MODULE_FLASH

        validate_error(
            api.start_programming_job(ctx["jobs"]["adas"]["id"], technician_headers),
            ApiErrorId.CALIBRATION_DOC_REQUIRED,
            422,
        )

        refused = fixtures.refresh_job(api, ctx, key="adas")
        assert refused["status"] == JobStatus.QUEUED
        assert refused["repin_count"] == 0
        assert refused["abort_reason"] is None

        version = fixtures.refresh_version(api, ctx)
        assert version["active_pin_count"] == 2

        entitlement = fixtures.refresh_entitlement(api, ctx)
        assert entitlement["status"] == EntitlementStatus.ACTIVE
