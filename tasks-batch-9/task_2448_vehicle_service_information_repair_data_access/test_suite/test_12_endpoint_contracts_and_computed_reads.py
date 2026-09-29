"""Endpoint contracts: round trips, action endpoints, links, computed reads, the clock.

Covers the publication create/read/list triple, what the license suspend action
does and blocks, the two different not-found errors behind a session's two
links, the ordering of the coverage map's gap list, the clock-driven expiry
branch of session closure, and the default reading of the logical clock.
"""

import pytest

from test_helpers import (
    COMPLIANCE_OFFICER_1_USER_ID,
    CONTENT_PUBLISHER_1_USER_ID,
    INITIAL_CLOCK,
    NON_EXISTENT_UUID,
    ApiErrorId,
    AuditEventType,
    AuditSubjectEntity,
    CellState,
    CoverageBasis,
    IdentityStatus,
    JobAbortReason,
    JobStatus,
    LicenseStatus,
    PublicationType,
    SessionStatus,
    ToolStatus,
    assert_coverage_map,
    assert_coverage_partition,
    assert_gateway_fee_breakdown,
    assert_gateway_session,
    assert_gaps_sorted,
    assert_license,
    assert_publication,
    assert_single_audit_event,
    assert_technician,
    factories,
    fixtures,
    make_compliance_officer_headers,
    make_content_publisher_headers,
    make_platform_admin_headers,
    make_shop_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_TOOL_ID = "00000000-0000-4000-8000-000000000001"


class TestPublicationRoundTrip:
    """One row created, read back unchanged and found once under its filter."""

    def test_the_created_publication_reads_back_and_lists_exactly_once(self, api):
        """Create, read and list agree on the same cell and the same pointers.

        PRD 3.6: "a `ContentPublisher` opens it against exactly one
        `vehicle_model_id`, one `system_area_id` and one `publication_type`, where
        the type is `REPAIR_PROCEDURE`, `TSB` or `CALIBRATION_DOC`", "A newly
        opened publication has `current_version_no` of 0 and
        `published_version_id` of null", and "Publications can be listed with
        narrowing by `vehicle_model_id`, `system_area_id` and `publication_type`."
        PRD 2.4 opens `version` at 1 on a freshly created row.

        Design: Corner/endpoints/standard_crud_publication_create_read_list_round_trip
        """
        ctx = fixtures.build_catalogue(api, area_codes=("POWERTRAIN",))
        author = make_content_publisher_headers(CONTENT_PUBLISHER_1_USER_ID)
        model_id = ctx["vehicle_model"]["id"]
        area_id = ctx["areas"]["POWERTRAIN"]["id"]

        created = validate_success(
            api.create_publication(
                factories.publication_payload(
                    model_id, area_id, publication_type=PublicationType.TSB
                ),
                author,
            ),
            201,
        )
        assert_publication(created)
        assert created["publication_type"] == PublicationType.TSB

        read = validate_success(api.get_publication(created["id"], author))
        assert read["id"] == created["id"]
        assert read["vehicle_model_id"] == model_id
        assert read["system_area_id"] == area_id
        assert read["publication_type"] == PublicationType.TSB
        assert read["current_version_no"] == 0
        assert read["published_version_id"] is None
        assert read["version"] == 1

        rows, meta = validate_paginated(
            api.list_publications(
                author,
                {"system_area_id": area_id, "publication_type": PublicationType.TSB},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == created["id"]


class TestLicenseSuspendAction:
    """The suspend action stamps its reason and blocks only new business."""

    def test_suspension_stamps_the_reason_and_refuses_the_next_purchase(self, api):
        """Status, reason and version move; the follow-on purchase is a 409.

        PRD 3.2: "Suspension drives `ACTIVE → SUSPENDED` and stamps the supplied
        `reason` into `suspension_reason`, advancing `version` by 1", and "What
        suspension blocks is new business — buying a new entitlement against this
        license, and activating a `PENDING` one, are both refused with
        `ERR_LICENSE_NOT_ACTIVE` (HTTP 409)." The refused purchase debits nothing,
        because it is only "On success" that the platform "debits the shop's
        `data_credit_balance_cents` by that amount".

        Design: Corner/endpoints/action_endpoint_license_suspend_transitions_and_stamps_reason
        """
        ctx = fixtures.build_funded_shop(api, covered_area_codes=("POWERTRAIN",))
        admin = make_platform_admin_headers()

        suspended = validate_success(
            api.suspend_license(
                ctx["license"]["id"], factories.reason_payload("PARITY_REVIEW"), admin
            )
        )
        assert_license(suspended)
        assert suspended["status"] == LicenseStatus.SUSPENDED
        assert suspended["suspension_reason"] == "PARITY_REVIEW"
        assert suspended["version"] == 3

        validate_error(
            api.create_entitlement(
                factories.entitlement_payload(
                    ctx["shop"]["id"], ctx["license"]["id"]
                ),
                ctx["manager_headers"],
            ),
            ApiErrorId.LICENSE_NOT_ACTIVE,
            409,
        )

        shop = fixtures.refresh_shop(api, ctx)
        assert shop["data_credit_balance_cents"] == 200000
        assert shop["funded_credit_total_cents"] == 200000

        _rows, meta = validate_paginated(
            api.list_manufacturer_licenses(
                ctx["manufacturer"]["id"], admin, {"status": LicenseStatus.SUSPENDED}
            )
        )
        assert meta["total_count"] == 1


class TestSessionLinksReportDifferentNotFounds:
    """The seat is a primary reference; the tool is a secondary one."""

    def test_an_unknown_seat_and_an_unknown_tool_answer_with_different_errors(
        self, api
    ):
        """The seat gets its typed 404 while the tool gets the referenced-resource 404.

        PRD 2.6: each entity type has its own not-found error, among them
        `ERR_SEAT_ASSIGNMENT_NOT_FOUND`, "and the same error is used whether the
        missing identifier arrived in the path or in the request body". A distinct
        error covers secondary references, and the list of them includes "the
        `diagnostic_tool_id` supplied when a session is requested", where "all of
        these resolve to `ERR_REFERENCED_RESOURCE_NOT_FOUND` (HTTP 404) when they
        fail."

        Design: Corner/endpoints/cross_reference_link_session_unknown_tool_and_unknown_seat_not_found
        """
        ctx = fixtures.build_seated_technician(api, covered_area_codes=("POWERTRAIN",))
        technician_headers = ctx["tech_headers"]["main"]
        seat_id = ctx["seats"]["main"]["id"]
        tool_id = ctx["tools"]["main"]["id"]

        validate_error(
            api.create_gateway_session(
                factories.gateway_session_payload(NON_EXISTENT_UUID, tool_id),
                technician_headers,
            ),
            ApiErrorId.SEAT_ASSIGNMENT_NOT_FOUND,
            404,
        )
        validate_error(
            api.create_gateway_session(
                factories.gateway_session_payload(seat_id, UNKNOWN_TOOL_ID),
                technician_headers,
            ),
            ApiErrorId.REFERENCED_RESOURCE_NOT_FOUND,
            404,
        )

        session = validate_success(
            api.create_gateway_session(
                factories.gateway_session_payload(seat_id, tool_id),
                technician_headers,
            ),
            201,
        )
        assert_gateway_session(session)
        assert session["seat_assignment_id"] == seat_id
        assert session["diagnostic_tool_id"] == tool_id

        rows, meta = validate_paginated(
            api.list_gateway_sessions(
                technician_headers, {"seat_assignment_id": seat_id}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == session["id"]


class TestCoverageMapGapOrdering:
    """Gap entries read like a catalogue, not like an insertion log."""

    def test_gaps_are_ordered_by_model_code_and_not_by_creation_order(self, api):
        """BX3 was registered first, yet AX7 leads the gap list.

        PRD 3.9: "each such license contributes one cell for every pairing of a
        vehicle model built by that license's manufacturer with a system area
        named in that license's `covered_system_area_ids`", "Every remaining cell
        is a `GAP`", and "Gap entries are ordered by ascending `model_code` and
        then by ascending system-area `code`; no identifier ever enters the
        ordering, so the report reads the way a human catalogue would."

        Design: Corner/endpoints/computed_read_coverage_map_gaps_sorted_by_model_code
        """
        ctx = fixtures.build_entitled_shop(
            api,
            area_codes=("POWERTRAIN",),
            covered_area_codes=("POWERTRAIN",),
            model_codes=("BX3", "AX7"),
        )
        officer = make_compliance_officer_headers(COMPLIANCE_OFFICER_1_USER_ID)

        coverage = validate_success(
            api.get_coverage_map(ctx["shop"]["id"], officer, None)
        )

        assert_coverage_map(coverage)
        assert_coverage_partition(coverage)
        assert coverage["basis"] == CoverageBasis.EFFECTIVE
        assert coverage["total_cells"] == 2
        assert coverage["covered_cells"] == 0
        assert coverage["degraded_cells"] == 0
        assert coverage["gap_cells"] == 2
        assert coverage["completeness_pct"] == pytest.approx(0.00, abs=0.005)

        gaps = coverage["gaps"]
        assert_gaps_sorted(gaps)
        assert len(gaps) == 2
        assert gaps[0]["model_code"] == "AX7"
        assert gaps[0]["vehicle_model_id"] == ctx["vehicle_models"]["AX7"]["id"]
        assert gaps[0]["cell_state"] == CellState.GAP
        assert gaps[1]["model_code"] == "BX3"
        assert gaps[1]["vehicle_model_id"] == ctx["vehicle_models"]["BX3"]["id"]
        assert gaps[1]["cell_state"] == CellState.GAP
        for entry in gaps:
            assert entry["system_area_code"] == "POWERTRAIN"

        _models, model_meta = validate_paginated(
            api.list_manufacturer_vehicle_models(ctx["manufacturer"]["id"], officer)
        )
        assert model_meta["total_count"] == 2
        assert model_meta["has_more"] is False


class TestClosingAtWindowEndTakesTheExpiredBranch:
    """One endpoint, two outcomes, and the clock chooses."""

    def test_closing_at_the_window_end_expires_the_session_and_aborts_the_live_job(
        self, api
    ):
        """At exactly window_end the live flash job is aborted, not a blocker.

        PRD 3.7: "When the current logical clock is at or after `window_end`, the
        branch is `ACTIVE → EXPIRED`, and that precondition does not apply — an
        expired window is closed regardless of what is in flight." That branch
        "aborts jobs in `QUEUED`, `IN_PROGRESS` and `REVALIDATION_REQUIRED` with
        `abort_reason` of `SESSION_EXPIRED`", releases "the diagnostic tool back
        to `IDLE` with `occupied_by_session_id` cleared", and "appends a
        `SESSION_TERMINATED` audit row whose `detail` is the literal text
        `reason=SESSION_EXPIRED`". One module flash prices at 2,500 plus 300 plus
        3,000 with a five percent discount and a four percent surcharge.

        Design: Corner/endpoints/conditional_action_session_complete_after_window_end_branches_to_expired
        """
        ctx = fixtures.build_session_with_started_job(
            api, covered_area_codes=("POWERTRAIN",)
        )
        session_id = ctx["sessions"]["main"]["id"]
        fixtures.set_clock(api, ctx, "2026-08-03T12:00:00Z")

        expired = validate_success(
            api.complete_gateway_session(session_id, ctx["tech_headers"]["main"])
        )

        assert_gateway_session(expired)
        assert expired["status"] == SessionStatus.EXPIRED
        assert_gateway_fee_breakdown(expired, 5800, 290, 232, 5742)

        job = fixtures.refresh_job(api, ctx)
        assert job["status"] == JobStatus.ABORTED
        assert job["abort_reason"] == JobAbortReason.SESSION_EXPIRED

        version = fixtures.refresh_version(api, ctx)
        assert version["active_pin_count"] == 0

        tools, _tool_meta = validate_paginated(
            api.list_shop_diagnostic_tools(
                ctx["shop"]["id"], ctx["manager_headers"], {"limit": 100}
            )
        )
        tool = next(row for row in tools if row["id"] == ctx["tools"]["main"]["id"])
        assert tool["status"] == ToolStatus.IDLE
        assert tool["occupied_by_session_id"] is None

        shop = fixtures.refresh_shop(api, ctx)
        assert shop["gateway_fee_accrued_cents"] == 5742

        events, _event_meta = validate_paginated(
            api.list_audit_events(
                make_compliance_officer_headers(),
                {
                    "subject_entity": AuditSubjectEntity.GATEWAY_SESSION,
                    "subject_id": session_id,
                    "event_type": AuditEventType.SESSION_TERMINATED,
                },
            )
        )
        assert_single_audit_event(
            events,
            AuditEventType.SESSION_TERMINATED,
            subject_id=session_id,
            detail="reason=SESSION_EXPIRED",
        )

        job_rows, job_meta = validate_paginated(
            api.list_programming_jobs(
                ctx["tech_headers"]["main"], {"session_id": session_id}
            )
        )
        assert job_meta["total_count"] == 1
        assert job_rows[0]["status"] == JobStatus.ABORTED


class TestTheLogicalClockDefault:
    """With no clock call ever made, the platform still knows what time it is."""

    def test_the_default_clock_governs_credential_expiry_before_any_set_call(self, api):
        """A 2026-07-31 expiry is lapsed and a 2026-08-01T00:00:01Z expiry is not.

        PRD 2.9: "Before any clock-setting call has been made, the logical clock
        reads exactly `2026-08-01T00:00:00Z`; the platform must never fall back to
        real wall-clock time", and the clock-setting capability "answers with the
        new `current_utc`". PRD 3.5 measures the credential against it: the
        supplied `credential_expires_at` "must lie strictly after the current
        logical clock; a verification offering an already-lapsed expiry is refused
        with `ERR_SECURITY_CREDENTIAL_EXPIRED` (HTTP 409)", while on success "both
        `identity_document_ref` and `credential_expires_at` are re-stamped from
        the request".

        Design: Corner/endpoints/clock_endpoint_default_reads_2026_08_01_before_any_set_call
        """
        admin = make_platform_admin_headers()
        shop = validate_success(api.create_shop(factories.shop_payload(), admin), 201)
        manager = make_shop_manager_headers(shop["id"])
        lapsing = validate_success(
            api.create_technician(
                factories.technician_payload(shop["id"], full_name="Tina Tech"), manager
            ),
            201,
        )
        surviving = validate_success(
            api.create_technician(
                factories.technician_payload(shop["id"], full_name="Raj Wrench"),
                manager,
            ),
            201,
        )
        officer = make_compliance_officer_headers(COMPLIANCE_OFFICER_1_USER_ID)

        validate_error(
            api.verify_technician(
                lapsing["id"],
                factories.verify_technician_payload(
                    identity_document_ref="DL-OLD",
                    credential_expires_at="2026-07-31T23:59:59Z",
                ),
                officer,
            ),
            ApiErrorId.SECURITY_CREDENTIAL_EXPIRED,
            409,
        )

        roster, _meta = validate_paginated(
            api.list_shop_technicians(shop["id"], manager, {"limit": 100})
        )
        untouched = next(row for row in roster if row["id"] == lapsing["id"])
        assert untouched["identity_status"] == IdentityStatus.UNVERIFIED

        verified = validate_success(
            api.verify_technician(
                surviving["id"],
                factories.verify_technician_payload(
                    identity_document_ref="DL-NEW",
                    credential_expires_at="2026-08-01T00:00:01Z",
                ),
                officer,
            )
        )
        assert_technician(verified)
        assert verified["identity_status"] == IdentityStatus.VERIFIED
        assert verified["identity_document_ref"] == "DL-NEW"
        assert verified["credential_expires_at"].startswith("2026-08-01T00:00:01")

        clock = validate_success(api.set_clock(INITIAL_CLOCK, admin))
        assert clock["current_utc"].startswith("2026-08-01T00:00:00")
