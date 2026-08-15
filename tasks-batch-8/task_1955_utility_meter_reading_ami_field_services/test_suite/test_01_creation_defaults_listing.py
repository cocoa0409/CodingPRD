"""Resource creation defaults, computed fields, listing and pagination.

Covers the PRD's master-data creation contract (section 3.1), the response
envelope (section 2.2), the logical clock default (section 2.4), and
pagination behavior (section 2.3).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_LOGICAL_CLOCK,
    UNKNOWN_UUID,
    assert_hazard_flag,
    assert_iso_instant_equal,
    assert_meter,
    assert_service_account,
    capture_read_payload,
    create_billing_period_payload,
    create_field_technician_payload,
    create_hazard_flag_payload,
    create_meter_payload,
    create_ops_snapshot_payload,
    create_replacement_campaign_payload,
    create_route_payload,
    create_service_account_payload,
    create_work_order_payload,
    get_success_data,
    is_valid_uuid,
    make_field_technician_headers,
    report_hazard,
    set_clock_payload,
    set_logical_clock,
    setup_account_with_installed_meter,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCreationDefaults:
    def test_field_technician_creation_defaults_and_envelope(
        self, api, meter_ops_admin_headers
    ):
        """PRD section 3.1: "the new technician starts `ACTIVE`, and the
        technician collection can be filtered by `technician_status` when
        listing."
        PRD section 2.4: "Before any clock-setting call has been made, the
        logical clock starts at `2026-08-01T00:00:00Z`; it never falls back to
        wall-clock time thereafter."

        Design: Corner/entities/entity_creation_field_technician_defaults_and_envelope
        """
        res = api.create_field_technician(
            create_field_technician_payload(display_name="Corner Tech"),
            meter_ops_admin_headers,
        )
        body = res.json()
        assert res.status_code == 201, f"expected 201, got {res.status_code}: {res.text}"
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")

        tech = body["data"]
        assert is_valid_uuid(tech["id"])
        assert tech["technician_status"] == "ACTIVE"
        assert tech["version"] == 1
        assert_iso_instant_equal(tech["created_at"], DEFAULT_LOGICAL_CLOCK)

    def test_service_account_creation_estimation_method_default(
        self, api, meter_ops_admin_headers
    ):
        """PRD section 3.1: "optionally an `estimation_method` selecting the
        estimate variant — `TRAILING_AVERAGE` or `SAME_PERIOD_LAST_YEAR` —
        which defaults to `TRAILING_AVERAGE` when omitted."
        PRD section 3.1: "Every account begins with `account_status` `ACTIVE`."

        Design: Corner/entities/entity_creation_service_account_estimation_method_default
        """
        res = api.create_service_account(
            create_service_account_payload(
                account_number="C-0001",
                service_address="1 Default Way",
                billing_cycle_code="C01",
            ),
            meter_ops_admin_headers,
        )
        account = validate_success(res, 201)
        assert_service_account(account)
        assert account["estimation_method"] == "TRAILING_AVERAGE"
        assert account["account_status"] == "ACTIVE"
        assert account["estimated_read_streak"] == 0
        assert account["current_meter_id"] is None
        assert account["last_validated_read_value"] is None
        assert account["last_validated_read_at"] is None

    def test_meter_creation_parallel_dimension_defaults(self, api, meter_ops_admin_headers):
        """PRD section 3.1: "A new meter starts with `meter_status` `IN_STOCK`,
        `tamper_status` `NONE`, and an `endpoint_comms_status` that defaults by
        type — `COMMUNICATING` for an `AMI` meter, `NOT_APPLICABLE` for a
        `HANDHELD` one — with `consecutive_missed_days` at zero and
        `non_communicating_since` null."

        Design: Corner/entities/entity_creation_meter_parallel_dimension_defaults
        """
        ami = validate_success(
            api.create_meter(
                create_meter_payload(serial_number="SN-Z-AMI", meter_type="AMI"),
                meter_ops_admin_headers,
            ),
            201,
        )
        hh = validate_success(
            api.create_meter(
                create_meter_payload(serial_number="SN-Z-HH", meter_type="HANDHELD"),
                meter_ops_admin_headers,
            ),
            201,
        )
        assert_meter(ami)
        assert_meter(hh)
        assert ami["meter_status"] == "IN_STOCK"
        assert ami["endpoint_comms_status"] == "COMMUNICATING"
        assert ami["tamper_status"] == "NONE"
        assert ami["consecutive_missed_days"] == 0
        assert ami["non_communicating_since"] is None
        assert hh["meter_status"] == "IN_STOCK"
        assert hh["endpoint_comms_status"] == "NOT_APPLICABLE"
        assert hh["tamper_status"] == "NONE"

    def test_composite_initial_states_on_creation(
        self, api, meter_ops_admin_headers, dispatcher_headers
    ):
        """PRD section 3.7: "A new order starts `OPEN` with `technician_id`
        null; the work-order list filters by `service_account_id`, `meter_id`,
        `technician_id`, `route_stop_id`, `investigation_id`,
        `campaign_enrollment_id`, `new_meter_id`, `work_order_status`, or
        `work_order_type`."
        PRD section 3.8: "the campaign starts `DRAFT`"
        PRD section 3.9: "the system creates an OpsSnapshot in `DRAFT`"
        PRD section 3.2: "The period begins `SCHEDULED`."

        Design: Corner/state_machines/composite_initial_states_on_creation
        """
        account, meter = setup_account_with_installed_meter("C-0043", "C43")

        wo = validate_success(
            api.create_work_order(
                create_work_order_payload(
                    "EXCHANGE",
                    account["id"],
                    meter_id=meter["id"],
                    scheduled_date="2026-08-10",
                    work_shift="AM",
                ),
                dispatcher_headers,
            ),
            201,
        )
        campaign = validate_success(
            api.create_replacement_campaign(
                create_replacement_campaign_payload(campaign_name="Init Check", quota=5),
                meter_ops_admin_headers,
            ),
            201,
        )
        snapshot = validate_success(
            api.create_ops_snapshot(
                create_ops_snapshot_payload("2026-08-02T00:00:00Z"), meter_ops_admin_headers
            ),
            201,
        )
        period = validate_success(
            api.create_billing_cycle_period(
                create_billing_period_payload(
                    cycle_code="C43",
                    period_start_date="2026-09-01",
                    period_end_date="2026-09-30",
                    read_window_open_date="2026-09-03",
                    read_window_close_date="2026-09-07",
                    bill_run_date="2026-09-30",
                ),
                meter_ops_admin_headers,
            ),
            201,
        )

        assert wo["work_order_status"] == "OPEN"
        assert wo["technician_id"] is None
        assert campaign["campaign_status"] == "DRAFT"
        assert snapshot["snapshot_status"] == "DRAFT"
        assert period["period_status"] == "SCHEDULED"


class TestCreationConstraints:
    def test_duplicate_account_number_rejected(self, api, meter_ops_admin_headers):
        """PRD section 3.1: "Creating one requires an `account_number` that is
        unique across all accounts (a duplicate is rejected with
        `ERR_DUPLICATE_ACCOUNT_NUMBER`, HTTP 409)"

        Design: Corner/entities/entity_creation_duplicate_account_number_rejected
        """
        first = api.create_service_account(
            create_service_account_payload(
                account_number="C-0002", service_address="2 Dup Ln", billing_cycle_code="C01"
            ),
            meter_ops_admin_headers,
        )
        validate_success(first, 201)

        res = api.create_service_account(
            create_service_account_payload(
                account_number="C-0002", service_address="3 Dup Ln", billing_cycle_code="C02"
            ),
            meter_ops_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_ACCOUNT_NUMBER.value, 409)

        data, meta = validate_paginated(api.list_service_accounts(meter_ops_admin_headers))
        assert meta["total_count"] == 1
        assert len(data) == 1

    def test_duplicate_serial_number_rejected(self, api, meter_ops_admin_headers):
        """PRD section 3.1: "Registering a meter takes a `serial_number`
        unique across all meters (duplicates fail with
        `ERR_DUPLICATE_SERIAL_NUMBER`, HTTP 409)"

        Design: Corner/entities/entity_creation_duplicate_serial_number_rejected
        """
        validate_success(
            api.create_meter(
                create_meter_payload(serial_number="SN-DUP", meter_type="HANDHELD"),
                meter_ops_admin_headers,
            ),
            201,
        )
        res = api.create_meter(
            create_meter_payload(serial_number="SN-DUP", meter_type="AMI"),
            meter_ops_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_SERIAL_NUMBER.value, 409)

    def test_period_inverted_window_dates_rejected(self, api, meter_ops_admin_headers):
        """PRD section 2.8: "At creation the dates must form a non-decreasing
        chain — the period start on or before the window open, the window open
        on or before the window close, the window close on or before the
        period end, and the period end on or before the bill run date — or
        creation is rejected with `ERR_WINDOW_DATE_ORDER` (HTTP 422)."

        Design: Corner/entities/entity_creation_period_inverted_window_dates_rejected
        """
        res = api.create_billing_cycle_period(
            create_billing_period_payload(
                cycle_code="C02",
                period_start_date="2026-08-01",
                period_end_date="2026-08-31",
                read_window_open_date="2026-08-10",
                read_window_close_date="2026-08-05",
                bill_run_date="2026-08-31",
            ),
            meter_ops_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_WINDOW_DATE_ORDER.value, 422)


class TestNotFoundAndEnvelope:
    def test_get_unknown_meter_returns_404_error_envelope(self, api, meter_ops_admin_headers):
        """PRD section 2.6: "Fifth, path resource identifiers must exist,
        validated in left-to-right order along the path; the first missing
        identifier yields `ERR_NOT_FOUND` (HTTP 404)."
        PRD section 2.2: "The `error_id` is a unique, machine-readable string
        that identifies the specific error."

        Design: Corner/entities/entity_not_found_returns_404_error_envelope
        """
        res = api.get_meter(UNKNOWN_UUID, meter_ops_admin_headers)
        error = validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, 404)
        assert error["message"].strip() != ""

    def test_error_envelope_carries_meta_and_error_id(self, api, investigator_headers):
        """PRD section 2.2: "The `meta` object for error responses contains
        only `api_request_id` and `api_request_timestamp`."
        PRD section 2.2: "The `message` provides a human-readable explanation
        of what went wrong."

        Design: Corner/errors/error_envelope_carries_meta_and_error_id
        """
        res = api.get_investigation(UNKNOWN_UUID, investigator_headers)
        body = res.json()
        assert res.status_code == 404
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == ApiErrorId.ERR_NOT_FOUND.value
        assert body["data"]["message"].strip() != ""
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)

    def test_clock_default_pins_created_at_before_any_set(self, api, meter_ops_admin_headers):
        """PRD section 2.4: "Before any clock-setting call has been made, the
        logical clock starts at `2026-08-01T00:00:00Z`; it never falls back to
        wall-clock time thereafter."
        PRD section 2.5: "`created_at` (string): an ISO 8601 timestamp in UTC
        with three fractional digits (e.g., `2026-08-01T06:00:00.123Z`),
        recording when the resource was first created; it reads the logical
        clock."

        Design: Corner/endpoints/clock_default_pins_created_at_before_any_set
        """
        meter = validate_success(
            api.create_meter(
                create_meter_payload(serial_number="SN-CLK-1", meter_type="HANDHELD"),
                meter_ops_admin_headers,
            ),
            201,
        )
        assert_iso_instant_equal(meter["created_at"], "2026-08-01T00:00:00Z")


class TestComputedFields:
    def test_current_meter_id_derived_from_install(self, api, meter_ops_admin_headers):
        """PRD section 3.1: "`current_meter_id` names the meter whose
        `installed_service_account_id` points at this account and whose
        `meter_status` is `IN_SERVICE` (null when none exists)"
        PRD section 3.1: "On success the meter's `installed_service_account_id`
        is set and the account's `current_meter_id` recomputes to this meter."

        Design: Corner/entities/entity_computed_current_meter_id_derived_from_install
        """
        account = validate_success(
            api.create_service_account(
                create_service_account_payload(
                    account_number="C-0003",
                    service_address="3 Derived Dr",
                    billing_cycle_code="C01",
                ),
                meter_ops_admin_headers,
            ),
            201,
        )
        assert account["current_meter_id"] is None

        meter = validate_success(
            api.create_meter(
                create_meter_payload(serial_number="SN-DER-1", meter_type="HANDHELD"),
                meter_ops_admin_headers,
            ),
            201,
        )
        installed = validate_success(
            api.install_meter(
                meter["id"], {"service_account_id": account["id"]}, meter_ops_admin_headers
            ),
            200,
        )
        assert installed["meter_status"] == "IN_SERVICE"
        assert installed["installed_service_account_id"] == account["id"]

        after = validate_success(
            api.get_service_account(account["id"], meter_ops_admin_headers), 200
        )
        assert after["current_meter_id"] == meter["id"]

    def test_hazard_expires_at_exact_literal(self, api, meter_ops_admin_headers):
        """PRD section 3.5: "The new flag starts `ACTIVE`, stamps
        `reported_by_technician_id` from the caller's `X-User-ID`, stamps
        `reported_at` from the logical clock, computes `expires_at` as
        `reported_at` plus thirty days, and starts `renewed_count` at zero."

        Design: Corner/entities/entity_computed_hazard_expires_at_exact_literal
        """
        get_success_data(
            api.set_clock(set_clock_payload("2026-08-01T09:00:00Z"), meter_ops_admin_headers)
        )
        account = validate_success(
            api.create_service_account(
                create_service_account_payload(
                    account_number="C-0004",
                    service_address="4 Hazard Ln",
                    billing_cycle_code="C01",
                ),
                meter_ops_admin_headers,
            ),
            201,
        )
        tech = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="Flag Tech"),
                meter_ops_admin_headers,
            ),
            201,
        )
        flag = validate_success(
            api.report_hazard_flag(
                create_hazard_flag_payload(
                    account["id"], hazard_type="LOCKED_GATE", severity="LOW"
                ),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )
        assert_hazard_flag(flag)
        assert flag["flag_status"] == "ACTIVE"
        assert flag["renewed_count"] == 0
        assert flag["reported_by_technician_id"] == tech["id"]
        assert_iso_instant_equal(flag["reported_at"], "2026-08-01T09:00:00Z")
        assert_iso_instant_equal(flag["expires_at"], "2026-08-31T09:00:00Z")


class TestListingAndPagination:
    def test_meter_listing_pagination_defaults_and_offset(
        self, api, meter_ops_admin_headers, dispatcher_headers
    ):
        """PRD section 2.3: "The `limit` parameter specifies the maximum
        number of items to return. If not provided, it defaults to 10, with a
        minimum of 1 and a maximum of 100. The `offset` parameter specifies
        the number of items to skip and defaults to 0."
        PRD section 2.3: "Paginated list-based responses include the following
        fields in the `meta` object of the response envelope: `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/entity_listing_pagination_defaults_and_offset
        """
        for i in range(1, 13):
            validate_success(
                api.create_meter(
                    create_meter_payload(serial_number=f"SN-PG-{i:02d}", meter_type="HANDHELD"),
                    meter_ops_admin_headers,
                ),
                201,
            )

        data, meta = validate_paginated(api.list_meters(dispatcher_headers))
        assert len(data) == 10
        assert meta["total_count"] == 12
        assert meta["has_more"] is True
        assert meta["limit"] == 10
        assert meta["offset"] == 0

        data, meta = validate_paginated(
            api.list_meters(dispatcher_headers, params={"limit": 2, "offset": 10})
        )
        assert len(data) == 2
        assert meta["total_count"] == 12
        assert meta["has_more"] is False

    def test_meter_listing_enum_filter_and_filter_limit_interaction(
        self, api, meter_ops_admin_headers, dispatcher_headers
    ):
        """PRD section 3.1: "The meter list filters by `meter_status`,
        `endpoint_comms_status`, `tamper_status`, or
        `installed_service_account_id`."
        PRD section 2.3: "Paginated list-based responses include the following
        fields in the `meta` object of the response envelope: `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/entity_listing_enum_filter_and_filter_limit_interaction
        """
        account = validate_success(
            api.create_service_account(
                create_service_account_payload(
                    account_number="C-0007",
                    service_address="7 Filter Rd",
                    billing_cycle_code="C01",
                ),
                meter_ops_admin_headers,
            ),
            201,
        )
        validate_success(
            api.create_meter(
                create_meter_payload(serial_number="SN-FL-1", meter_type="HANDHELD"),
                meter_ops_admin_headers,
            ),
            201,
        )
        validate_success(
            api.create_meter(
                create_meter_payload(serial_number="SN-FL-2", meter_type="HANDHELD"),
                meter_ops_admin_headers,
            ),
            201,
        )
        m3 = validate_success(
            api.create_meter(
                create_meter_payload(serial_number="SN-FL-3", meter_type="HANDHELD"),
                meter_ops_admin_headers,
            ),
            201,
        )
        validate_success(
            api.install_meter(
                m3["id"], {"service_account_id": account["id"]}, meter_ops_admin_headers
            ),
            200,
        )

        data, meta = validate_paginated(
            api.list_meters(dispatcher_headers, params={"meter_status": "IN_STOCK"})
        )
        assert meta["total_count"] == 2
        assert len(data) == 2

        data, meta = validate_paginated(
            api.list_meters(
                dispatcher_headers, params={"meter_status": "IN_STOCK", "limit": 1}
            )
        )
        assert len(data) == 1
        assert meta["total_count"] == 2
        assert meta["has_more"] is True

        data, meta = validate_paginated(
            api.list_meters(dispatcher_headers, params={"meter_status": "IN_SERVICE"})
        )
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == m3["id"]

    def test_fk_reverse_reachability_filtered_lists(
        self, api, meter_ops_admin_headers, dispatcher_headers
    ):
        """PRD section 3.4: "The read collection filters by
        `service_account_id`, `meter_id`, `route_stop_id`, `read_status`, or
        `supersedes_read_id`."
        PRD section 3.2: "the stop collection itself filters by `route_id`,
        `service_account_id`, `billing_cycle_period_id`, `stop_status`,
        `hazard_flag_id`, or `current_read_id`."
        PRD section 3.5: "The flag collection filters by `service_account_id`,
        `reported_by_technician_id`, or `flag_status`."

        Design: Corner/entities/entity_fk_reverse_reachability_filtered_lists
        """
        set_logical_clock("2026-08-01T00:00:00Z")
        tech = validate_success(
            api.create_field_technician(
                create_field_technician_payload(display_name="FK Tech"), meter_ops_admin_headers
            ),
            201,
        )
        account, meter = setup_account_with_installed_meter(
            "C-0008", "C24", service_address="8 FK Blvd"
        )
        flag = report_hazard(account["id"], tech["id"], hazard_type="OTHER", severity="LOW")

        # A hazard-flag id path must reference an actual flag: clearing with
        # the account id (a valid UUID but not a flag) is a path-existence miss.
        bogus = api.clear_hazard_flag(account["id"], dispatcher_headers)
        validate_error(bogus, ApiErrorId.ERR_NOT_FOUND.value, 404)

        period = validate_success(
            api.create_billing_cycle_period(
                create_billing_period_payload(
                    cycle_code="C24",
                    period_start_date="2026-08-01",
                    period_end_date="2026-08-31",
                    read_window_open_date="2026-08-03",
                    read_window_close_date="2026-08-07",
                    bill_run_date="2026-08-31",
                ),
                meter_ops_admin_headers,
            ),
            201,
        )
        set_logical_clock("2026-08-03T08:00:00Z")
        validate_success(api.open_read_window(period["id"], meter_ops_admin_headers), 200)
        route = validate_success(
            api.create_route(
                create_route_payload(
                    period["id"],
                    scheduled_date="2026-08-03",
                    route_shift="AM",
                    two_person_crew=True,
                ),
                dispatcher_headers,
            ),
            201,
        )
        stops = validate_paginated(api.list_route_stops(route["id"], dispatcher_headers))[0]
        assert len(stops) == 1
        stop = stops[0]
        validate_success(
            api.assign_route(route["id"], {"technician_id": tech["id"]}, dispatcher_headers),
            200,
        )
        validate_success(
            api.start_route(route["id"], make_field_technician_headers(tech["id"])), 200
        )
        read = validate_success(
            api.capture_read(
                stop["id"],
                capture_read_payload(
                    meter["id"], 42, "2026-08-03T09:00:00Z", stop["version"]
                ),
                make_field_technician_headers(tech["id"]),
            ),
            201,
        )

        data, meta = validate_paginated(
            api.list_reads(dispatcher_headers, params={"meter_id": meter["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == read["id"]

        data, meta = validate_paginated(
            api.list_stops(dispatcher_headers, params={"route_id": route["id"]})
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == stop["id"]

        data, meta = validate_paginated(
            api.list_hazard_flags(
                dispatcher_headers, params={"service_account_id": account["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == flag["id"]
