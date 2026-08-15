"""RBAC role screening and the request validation ladder (PRD 2.1/2.6)."""
import pytest

from test_helpers import (
    TEST_USERS,
    UNKNOWN_UUID,
    ApiErrorId,
    advance_investigation_to_pending_disposition,
    capture_read_payload,
    create_billing_period,
    create_billing_period_payload,
    create_field_technician_payload,
    create_meter_payload,
    create_replacement_campaign_payload,
    create_route_payload,
    create_service_account_payload,
    create_work_order_payload,
    get_investigation,
    get_period,
    get_read,
    get_route_stops,
    get_work_order,
    make_field_technician_headers,
    make_investigator_headers,
    make_meter_ops_admin_headers,
    open_investigation,
    set_logical_clock,
    setup_account_with_installed_meter,
    setup_in_progress_route,
    validate_error,
    validate_success,
    assign_route_payload,
    get_route,
)

ADMIN = TEST_USERS["meter_ops_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_liaison_headers"]
INVESTIGATOR = TEST_USERS["investigator_headers"]
TECH_SHARED = TEST_USERS["field_technician_headers"]


class TestValidationLadderHead:
    def test_headers_missing_auth_returns_400(self, api):
        """PRD section 2.1: "A request missing either header, or presenting a
        malformed one, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/headers_missing_auth_returns_400
        """
        res = api.list_meters(headers=None)
        validate_error(
            res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value, 400
        )

    def test_role_not_listed_on_endpoint_returns_403(self, api, meter_ops_admin_headers):
        """PRD section 2.1: "A caller whose role is not listed for the
        requested operation is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP
        403)"
        PRD section 2.1: "`MeterOpsAdmin` alone registers technicians,
        accounts, and meters, installs and retires meters, ingests AMI reads,
        creates billing periods, runs replacement campaigns and operations
        checkpoints, verifies or reworks completed work orders, and drives the
        logical clock."

        Design: Corner/validations/role_not_listed_on_endpoint_returns_403
        """
        tech = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="RBAC Tech"),
                meter_ops_admin_headers,
            ),
            201,
        )
        res = api.create_service_account(
            create_service_account_payload(
                account_number="C-0070",
                service_address="70 Rbac Rd",
                billing_cycle_code="C70",
            ),
            make_field_technician_headers(tech["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, 403)

    def test_payload_missing_required_field_returns_invalid_request(
        self, api, meter_ops_admin_headers
    ):
        """PRD section 2.6: "Third, request-body shape: required fields
        present, enum membership, and type sanity, including the period
        date-ordering rule and the back-bill array-length rule
        (`ERR_INVALID_REQUEST` at HTTP 400, or `ERR_WINDOW_DATE_ORDER` /
        `ERR_BACKBILL_INPUT_MISMATCH` at HTTP 422)."

        Design: Corner/validations/payload_missing_required_field_returns_invalid_request
        """
        res = api.create_meter({"meter_type": "HANDHELD"}, meter_ops_admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    def test_invalid_enum_value_returns_invalid_request(self, api, meter_ops_admin_headers):
        """PRD section 2.6: "Third, request-body shape: required fields
        present, enum membership, and type sanity, including the period
        date-ordering rule and the back-bill array-length rule
        (`ERR_INVALID_REQUEST` at HTTP 400, or `ERR_WINDOW_DATE_ORDER` /
        `ERR_BACKBILL_INPUT_MISMATCH` at HTTP 422)."
        PRD section 3.1: "Registering a meter takes a `serial_number` unique
        across all meters (duplicates fail with `ERR_DUPLICATE_SERIAL_NUMBER`,
        HTTP 409) and a `meter_type` of `HANDHELD` or `AMI`."

        Design: Corner/validations/invalid_enum_value_returns_invalid_request
        """
        res = api.create_meter(
            create_meter_payload(serial_number="SN-BAD-ENUM", meter_type="SMART"),
            meter_ops_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    def test_body_fk_reference_not_found_returns_404(self, api, dispatcher_headers):
        """PRD section 2.6: "Sixth, body-referenced entities —
        `technician_id`, `meter_id`, `hazard_flag_id`, period identifiers,
        `new_meter_id`, and their kin — must exist
        (`ERR_REFERENCED_ENTITY_NOT_FOUND`, HTTP 404)."

        Design: Corner/validations/body_fk_reference_not_found_returns_404
        """
        res = api.create_route(
            create_route_payload(UNKNOWN_UUID, scheduled_date="2026-08-03"),
            dispatcher_headers,
        )
        validate_error(res, ApiErrorId.ERR_REFERENCED_ENTITY_NOT_FOUND.value, 404)

    def test_nested_path_existence_left_to_right(self, api, dispatcher_headers):
        """PRD section 2.6: "Fifth, path resource identifiers must exist,
        validated in left-to-right order along the path; the first missing
        identifier yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/endpoints/nested_path_existence_left_to_right
        """
        res = api.list_route_stops(UNKNOWN_UUID, dispatcher_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, 404)


class TestRoleDeny:
    def test_field_technician_cannot_dispatch_work_order(self, api):
        """PRD section 2.1: "`Dispatcher` alone builds routes, assigns and
        reassigns crews, and creates, dispatches, reschedules, and cancels
        work orders."
        PRD section 2.1: "A caller whose role is not listed for the requested
        operation is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)"

        Design: Corner/rbac/field_technician_cannot_dispatch_work_order
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        tech = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Deny Tech"), ADMIN
            ),
            201,
        )
        account, m1 = setup_account_with_installed_meter(
            "C-0120", "CD1", service_address="120 Deny Rd"
        )
        wo = validate_success(
            api.create_work_order(
                create_work_order_payload(
                    "EXCHANGE", account["id"], meter_id=m1["id"],
                    scheduled_date="2026-08-10", work_shift="AM",
                ),
                DISPATCHER,
            ),
            201,
        )
        res = api.dispatch_work_order(
            wo["id"],
            {"technician_id": tech["id"]},
            make_field_technician_headers(tech["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, 403)
        assert get_work_order(wo["id"])["work_order_status"] == "OPEN"

    def test_dispatcher_cannot_validate_reads(self, api):
        """PRD section 2.1: "`BillingLiaison` alone validates or rejects
        reads, generates estimates, and finalizes and closes billing periods."
        PRD section 2.1: "A caller whose role is not listed for the requested
        operation is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)"

        Design: Corner/rbac/dispatcher_cannot_validate_reads
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        account, meter = setup_account_with_installed_meter(
            "C-0121", "CD2", service_address="121 Val Rd"
        )
        period, route, stops, tech = setup_in_progress_route(
            "CD2",
            "2026-08-01", "2026-08-31", "2026-08-03", "2026-08-07", "2026-08-31",
            "2026-08-03",
            open_clock="2026-08-03T08:00:00Z",
            tech_name="Val Tech",
        )
        read = validate_success(
            api.capture_read(
                stops[0]["id"],
                capture_read_payload(
                    meter["id"], 100, "2026-08-03T09:00:00Z", stops[0]["version"]
                ),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )
        res = api.validate_read(read["id"], DISPATCHER)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, 403)
        assert get_read(read["id"])["read_status"] == "PROVISIONAL"

    def test_investigator_cannot_open_read_window(self, api, meter_ops_admin_headers):
        """PRD section 2.1: "Window open and close are shared between
        `BillingLiaison` and `MeterOpsAdmin`; hazard-flag clearing is shared
        among `FieldTechnician`, `Dispatcher`, and `MeterOpsAdmin`; ordinary
        read capture is shared between the assigned `FieldTechnician` and
        `MeterOpsAdmin` acting in correction mode."
        PRD section 2.1: "A caller whose role is not listed for the requested
        operation is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)"

        Design: Corner/rbac/investigator_cannot_open_read_window
        """
        period = validate_success(
            api.create_billing_cycle_period(
                create_billing_period_payload(cycle_code="CD3"), meter_ops_admin_headers
            ),
            201,
        )
        set_logical_clock("2026-08-03T08:00:00Z")
        res = api.open_read_window(period["id"], make_investigator_headers("inv-x1"))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, 403)
        assert get_period(period["id"])["period_status"] == "SCHEDULED"

    def test_billing_liaison_cannot_create_replacement_campaign(self, api):
        """PRD section 2.1: "`MeterOpsAdmin` alone registers technicians,
        accounts, and meters, installs and retires meters, ingests AMI reads,
        creates billing periods, runs replacement campaigns and operations
        checkpoints, verifies or reworks completed work orders, and drives the
        logical clock."
        PRD section 2.1: "A caller whose role is not listed for the requested
        operation is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)"

        Design: Corner/rbac/billing_liaison_cannot_create_replacement_campaign
        """
        res = api.create_replacement_campaign(
            create_replacement_campaign_payload(campaign_name="Nope", quota=1), BILLING
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, 403)

    def test_meter_ops_admin_cannot_close_investigation(self, api):
        """PRD section 2.1: "`Investigator` alone drives tamper and theft
        investigations end to end, subject to the segregation-of-duties close
        gate in §3.6."
        PRD section 2.1: "A caller whose role is not listed for the requested
        operation is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)"

        Design: Corner/rbac/meter_ops_admin_cannot_close_investigation
        """
        account, meter = setup_account_with_installed_meter(
            "C-0122", "CD4", service_address="122 Admin Rd"
        )
        inv = open_investigation(
            account["id"], meter["id"], indication_type="USAGE_ANOMALY", opened_by="inv-a"
        )
        advance_investigation_to_pending_disposition(inv["id"], "inv-a")
        validate_success(
            api.clear_investigation(inv["id"], make_investigator_headers("inv-a")), 200
        )

        res = api.close_investigation(inv["id"], make_meter_ops_admin_headers("admin-1"))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, 403)
        assert get_investigation(inv["id"])["investigation_status"] == "CLEARED"

    def test_non_assigned_technician_cannot_start_route(self, api, meter_ops_admin_headers):
        """PRD section 3.3: "Field work starts when the assigned technician
        starts the route: the caller's `X-User-ID` must equal the route's
        `technician_id` (`ERR_NOT_ASSIGNED_TECHNICIAN`, HTTP 403), and the
        route moves from `ASSIGNED` to `IN_PROGRESS`."
        PRD section 2.1: "When `X-User-Role` is `FieldTechnician`, `X-User-ID`
        is the `id` of the acting FieldTechnician entity; ownership checks on
        any resource that references a FieldTechnician compare the resource's
        foreign-key field to `X-User-ID`."

        Design: Corner/rbac/non_assigned_technician_cannot_start_route
        """
        tech_a = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Owner A"), meter_ops_admin_headers
            ),
            201,
        )
        tech_b = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Owner B"), meter_ops_admin_headers
            ),
            201,
        )
        period = create_billing_period(
            "CD5", "2026-08-01", "2026-08-31", "2026-08-03", "2026-08-07", "2026-08-31"
        )
        route = validate_success(
            api.create_route(
                create_route_payload(period["id"], scheduled_date="2026-08-03"), DISPATCHER
            ),
            201,
        )
        validate_success(
            api.assign_route(route["id"], assign_route_payload(tech_a["id"]), DISPATCHER),
            200,
        )

        res = api.start_route(route["id"], make_field_technician_headers(tech_b["id"]))
        validate_error(res, ApiErrorId.ERR_NOT_ASSIGNED_TECHNICIAN.value, 403)
        assert get_route(route["id"])["route_status"] == "ASSIGNED"
