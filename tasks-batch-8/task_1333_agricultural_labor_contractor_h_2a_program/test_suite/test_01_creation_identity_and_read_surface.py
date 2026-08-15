"""Creation defaults, identity minting, not-found surface, uniqueness,
pagination envelope, read-your-writes, and RBAC/authentication gates."""
from test_helpers import (
    ApiErrorId,
    J1_CUTOFF_DATE,
    TEST_USERS,
    assert_grower,
    assert_job_order,
    assert_worker,
    create_grower,
    create_grower_payload,
    create_job_order,
    create_job_order_payload,
    create_wage_determination,
    create_worker,
    create_worker_payload,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
REVIEWER = TEST_USERS["program_reviewer_headers"]
AUDITOR = TEST_USERS["wage_auditor_headers"]
INSPECTOR = TEST_USERS["housing_inspector_headers"]
SYSADMIN = TEST_USERS["system_admin_headers"]

MISSING = "11111111-1111-1111-1111-111111111111"
MISSING_2 = "22222222-2222-2222-2222-222222222222"


class TestCreationAndDerivedTerms:
    def test_job_order_creation_derives_terms(self, api):
        """PRD 3.2: "`required_hourly_floor_cents` is the greatest of four values:
        the determination's AEWR, the determination's prevailing hourly wage, the
        offered hourly wage, and the federal minimum wage of 725 cents per hour."
        PRD 3.2: "`recruitment_cutoff_date` marks the midpoint of the contract: the
        system takes half of `total_calendar_days` (rounding down when the total is
        odd), subtracts one day, and advances `work_start_date` by that many days;
        `transport_threshold_date` is always the same date, the 50-percent point of
        the contract period."
        PRD 3.2: "The order is created in `DRAFT` status with `deficiency_note`
        null and all three locked wage snapshots —
        `locked_aewr_hourly_cents`, `locked_prevailing_hourly_cents`,
        `locked_prevailing_piece_rate_cents_per_unit` — still null."

        Design: Corner/entities/job_order_creation_derives_terms
        """
        grower = create_grower()
        wd = create_wage_determination()
        resp = api.create_job_order(create_job_order_payload(grower["id"], wd["id"]), ADMIN)
        jo = validate_success(resp, 201)
        assert_job_order(jo)

        assert jo["status"] == "DRAFT"
        assert jo["deficiency_note"] is None
        assert jo["locked_aewr_hourly_cents"] is None
        assert jo["locked_prevailing_hourly_cents"] is None
        assert jo["locked_prevailing_piece_rate_cents_per_unit"] is None
        # max(aewr 1850, prevailing 1775, offered 1800, federal 725)
        assert jo["required_hourly_floor_cents"] == 1850
        # max(offered piece 400, prevailing piece 450)
        assert jo["effective_piece_rate_cents_per_unit"] == 450
        # 2026-09-01..2026-10-20 inclusive = 50 days; 7 Sundays excluded -> 43.
        assert jo["total_calendar_days"] == 50
        assert jo["total_workdays"] == 43
        # start + (floor(50/2) - 1) days = 2026-09-01 + 24 days.
        assert jo["recruitment_cutoff_date"] == J1_CUTOFF_DATE == "2026-09-25"
        assert jo["transport_threshold_date"] == "2026-09-25"
        assert jo["domestic_hired_count"] == 0
        assert jo["visa_worker_ceiling"] == 4

        # Immediate consistency: a re-read returns identical derived values.
        reread = validate_success(api.get_job_order(jo["id"], AUDITOR), 200)
        for field in (
            "required_hourly_floor_cents", "effective_piece_rate_cents_per_unit",
            "total_calendar_days", "total_workdays", "recruitment_cutoff_date",
            "transport_threshold_date", "domestic_hired_count", "visa_worker_ceiling",
        ):
            assert reread[field] == jo[field], f"{field} drifted between create and re-read"

    def test_job_order_piece_rate_default_null_hourly_only(self, api):
        """PRD 3.2: "`effective_piece_rate_cents_per_unit` is null when both the
        offered piece rate and the prevailing piece rate are null, and otherwise
        the greater of whichever of those two are non-null; ties resolve to the
        same value regardless of source."
        PRD 3.2: "`required_hourly_floor_cents` is the greatest of four values: the
        determination's AEWR, the determination's prevailing hourly wage, the
        offered hourly wage, and the federal minimum wage of 725 cents per hour."

        Design: Corner/entities/job_order_piece_rate_default_null_hourly_only
        """
        grower = create_grower()
        wd = create_wage_determination(hourly_only=True)
        payload = create_job_order_payload(
            grower["id"], wd["id"],
            title="Chile harvest", crop="CHILE", work_end_date="2026-09-20",
            workers_requested=1, offered_hourly_cents=725,
            inbound_transport_cents=0, outbound_transport_cents=0,
        )
        payload.pop("offered_piece_rate_cents_per_unit")  # optional input omitted
        jo = validate_success(api.create_job_order(payload, ADMIN), 201)
        assert_job_order(jo)
        assert jo["offered_piece_rate_cents_per_unit"] is None
        assert jo["effective_piece_rate_cents_per_unit"] is None
        # max(700, 710, 725 offered, 725 federal minimum) = 725
        assert jo["required_hourly_floor_cents"] == 725


class TestIdentityAndExistence:
    def test_worker_create_missing_required_passport_returns_invalid_request(self, api):
        """PRD 3.4: "Foreign workers are registered by a `ContractorAdmin` with
        `full_name`, `passport_number`, `date_of_birth`, and `country_code`."
        PRD 2.9: "Tenth and last come the field-domain and fiscal checks —
        malformed bodies, invalid enum values, non-positive amounts, invalid
        counts, invalid date ranges, invalid hours, invalid debarment terms,
        invalid findings, and the optimistic-concurrency version match — surfaced
        as `ERR_INVALID_REQUEST`, `ERR_INVALID_DATE_RANGE`, `ERR_INVALID_HOURS`,
        `ERR_INVALID_DEBARMENT_TERM`, `ERR_INVALID_FINDINGS`, or
        `ERR_STALE_JOB_ORDER_VERSION`."

        Design: Corner/entities/worker_create_missing_required_passport_returns_invalid_request
        """
        payload = create_worker_payload()
        del payload["passport_number"]
        resp = api.create_worker(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        rows, meta = validate_paginated(api.list_workers(ADMIN))
        assert meta["total_count"] == 0 and rows == []

    def test_worker_create_client_supplied_id_input_ignored(self, api):
        """PRD 2.5: "`id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/worker_create_client_supplied_id_input_ignored
        """
        supplied = "00000000-0000-0000-0000-000000000000"
        payload = create_worker_payload()
        payload["id"] = supplied
        worker = validate_success(api.create_worker(payload, ADMIN), 201)
        assert_worker(worker)
        assert worker["id"] != supplied, "server must mint its own id, ignoring the client's"
        assert is_valid_uuid(worker["id"])

    def test_resource_not_found_errors_return_404(self, api):
        """PRD 2.7: "The server confirms the existence of each path identifier in
        sequence and rejects the request immediately with a 404 carrying the error
        identifier of the first missing resource, before evaluating any later
        segment or any business rule."
        PRD 2.7: "Identifiers referenced inside a request body are validated for
        existence the same way after the path itself resolves."

        Design: Corner/entities/resource_not_found_errors_return_404
        """
        # Path-identifier checks across every resource family.
        cases = [
            (api.refresh_grower_status(MISSING, AUDITOR), ApiErrorId.ERR_GROWER_NOT_FOUND),
            (api.get_job_order(MISSING, ADMIN), ApiErrorId.ERR_JOB_ORDER_NOT_FOUND),
            (
                api.decide_domestic_application(MISSING, {"decision": "HIRE", "qualification": "QUALIFIED"}, ADMIN),
                ApiErrorId.ERR_DOMESTIC_APPLICATION_NOT_FOUND,
            ),
            (api.get_worker(MISSING, ADMIN), ApiErrorId.ERR_WORKER_NOT_FOUND),
            (api.get_visa_petition(MISSING, ADMIN), ApiErrorId.ERR_VISA_PETITION_NOT_FOUND),
            (api.get_consular_appointment(MISSING, ADMIN), ApiErrorId.ERR_CONSULAR_APPOINTMENT_NOT_FOUND),
            (api.get_housing_unit(MISSING, ADMIN), ApiErrorId.ERR_HOUSING_UNIT_NOT_FOUND),
            (api.get_housing_assignment(MISSING, ADMIN), ApiErrorId.ERR_HOUSING_ASSIGNMENT_NOT_FOUND),
            (api.get_worker_assignment(MISSING, ADMIN), ApiErrorId.ERR_WORKER_ASSIGNMENT_NOT_FOUND),
            (api.get_transfer_request(MISSING, ADMIN), ApiErrorId.ERR_TRANSFER_REQUEST_NOT_FOUND),
            (api.get_audit_case(MISSING, ADMIN), ApiErrorId.ERR_AUDIT_CASE_NOT_FOUND),
        ]
        for resp, error_id in cases:
            validate_error(resp, error_id)

        # Body-referenced identifiers: with both ids bogus, the first missing
        # resource in the payload's documented order (grower_id) is reported.
        resp = api.create_job_order(
            create_job_order_payload(MISSING, MISSING_2), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_GROWER_NOT_FOUND)

        # Grower exists but determination does not -> ERR_WAGE_DETERMINATION_NOT_FOUND.
        grower = create_grower()
        resp = api.create_job_order(create_job_order_payload(grower["id"], MISSING), ADMIN)
        validate_error(resp, ApiErrorId.ERR_WAGE_DETERMINATION_NOT_FOUND)

    def test_identity_uniqueness_duplicates_rejected(self, api):
        """PRD 3.1: "The `fein` is unique across growers; a registration repeating
        an existing one is rejected with `ERR_DUPLICATE_FEIN`."
        PRD 3.4: "Passport numbers are unique across workers; a duplicate is
        rejected with `ERR_DUPLICATE_PASSPORT`."
        PRD 3.4: "The creation payload carries the petition's `receipt_code`,
        unique across all petitions (a repeat is rejected with
        `ERR_DUPLICATE_RECEIPT_CODE`)"

        Design: Corner/errors/identity_uniqueness_duplicates_rejected
        """
        grower = create_grower()
        create_worker(passport_number="P0001")
        wd = create_wage_determination()
        jo = create_job_order(grower["id"], wd["id"])
        get_success_data(api.submit_job_order(jo["id"], ADMIN))
        get_success_data(api.certify_job_order(jo["id"], REVIEWER))
        get_success_data(
            api.create_visa_petition(jo["id"], {"receipt_code": "RCPT-1", "requested_worker_count": 1}, ADMIN)
        )

        resp = api.create_grower(
            create_grower_payload(legal_name="Clone Acres", fein="12-3456789"), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_FEIN)

        resp = api.create_worker(
            create_worker_payload(full_name="Worker Clone", passport_number="P0001",
                                  date_of_birth="1992-02-02", country_code="GT"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PASSPORT)

        resp = api.create_visa_petition(
            jo["id"], {"receipt_code": "RCPT-1", "requested_worker_count": 2}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RECEIPT_CODE)


class TestReadSurface:
    def test_workers_list_pagination_and_filter_envelope(self, api):
        """PRD 2.3: "`limit` sets the maximum number of items returned: it defaults
        to 10 when omitted, accepts a minimum of 1, and caps at 100. `offset` sets
        the number of items to skip and defaults to 0."
        PRD 2.3: "Unless otherwise specified, every list endpoint returns resources
        sorted by creation timestamp in ascending order, and the `meta` object of a
        list response carries `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/workers_list_pagination_and_filter_envelope
        """
        create_worker(passport_number="P0001", full_name="Worker A")
        create_worker(passport_number="P0002", full_name="Worker B")

        page1 = api.list_workers(AUDITOR, params={"limit": 1})
        assert page1.json()["response_type"] == "array"
        rows1, meta1 = validate_paginated(page1)
        assert len(rows1) == 1 and meta1["total_count"] == 2 and meta1["has_more"] is True
        assert isinstance(page1.json()["meta"].get("api_request_id"), str)

        rows2, meta2 = validate_paginated(api.list_workers(AUDITOR, params={"limit": 1, "offset": 1}))
        assert len(rows2) == 1 and meta2["total_count"] == 2 and meta2["has_more"] is False
        assert rows1[0]["passport_number"] != rows2[0]["passport_number"]

        rows3, meta3 = validate_paginated(api.list_workers(AUDITOR, params={"status": "REGISTERED"}))
        assert meta3["total_count"] == 2
        assert all(r["status"] == "REGISTERED" for r in rows3)

    def test_immediate_consistency_on_create_and_list(self, api, grower_rep_headers_factory):
        """PRD 3.1: "A newly registered grower starts in `ACTIVE` status, and its
        `debarment_ends_on` is null — that date exists only while the grower is
        `DEBARRED`."
        PRD 2.3: "Every filter is optional; omitting a filter simply returns all
        rows."

        Design: Corner/consistency_model/immediate_consistency_on_create_and_list
        """
        grower = create_grower()
        rows, meta = validate_paginated(
            api.list_growers(grower_rep_headers_factory(grower["id"]), params={"status": "ACTIVE"})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == grower["id"]
        assert rows[0]["legal_name"] == "Green Acres LLC"
        assert rows[0]["debarment_ends_on"] is None


class TestAccessControl:
    def test_exclusive_operations_denied_to_other_roles(self, api):
        """PRD 2.1: "Each endpoint admits a defined set of roles; a caller whose
        role is not admitted is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD 2.1: "`HousingInspector` is an independent inspector who records
        housing inspections — a deliberate segregation of duties, since the
        contractor may never certify its own housing."

        Design: Corner/rbac/exclusive_operations_denied_to_other_roles
        """
        grower = create_grower()
        wd = create_wage_determination()
        jo = create_job_order(grower["id"], wd["id"])
        get_success_data(api.submit_job_order(jo["id"], ADMIN))
        unit = get_success_data(
            api.create_housing_unit({"grower_id": grower["id"], "name": "U1", "capacity": 4}, ADMIN)
        )

        # ContractorAdmin may not certify (ProgramReviewer exclusive).
        resp = api.certify_job_order(jo["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        # ContractorAdmin may not record inspections (HousingInspector exclusive).
        resp = api.record_housing_inspection(
            unit["id"], {"inspected_on": "2026-08-01", "result": "PASS"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        # ContractorAdmin may not drive the logical clock (SystemAdmin exclusive).
        resp = api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        # Positive control: the same class of action succeeds for the right role.
        certified = validate_success(api.certify_job_order(jo["id"], REVIEWER), 200)
        assert certified["status"] == "CERTIFIED"

    def test_request_without_auth_headers_unauthenticated(self, api):
        """PRD 2.1: "Every request must carry two authentication headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the
        caller's operational capacity. If either header is missing or empty, the
        request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/rbac/request_without_auth_headers_unauthenticated
        """
        resp = api.list_growers({})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
