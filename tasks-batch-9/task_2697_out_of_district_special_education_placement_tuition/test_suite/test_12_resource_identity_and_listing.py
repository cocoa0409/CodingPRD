"""
Resource identity, declared field sets, list envelopes, the not-found catalogue,
referential linkage, the stale-view guard on rate publication and the version
counter's read/write discipline.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ADDENDUM_NOT_FOUND,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_ATTENDANCE_PLACEMENT_MISMATCH,
    ERR_ATTENDANCE_RECORD_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_DECISION_NOT_FOUND,
    ERR_FISCAL_ACCOUNT_NOT_FOUND,
    ERR_FUNDING_CLAIM_LINKAGE_MISMATCH,
    ERR_FUNDING_CLAIM_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVOICE_NOT_FOUND,
    ERR_PLACEMENT_LINKAGE_MISMATCH,
    ERR_PLACEMENT_NOT_FOUND,
    ERR_PROGRESS_REPORT_NOT_FOUND,
    ERR_RATE_SCHEDULE_NOT_FOUND,
    ERR_ROUTE_NOT_FOUND,
    ERR_SCHOOL_NOT_FOUND,
    ERR_STALE_SCHOOL_VERSION,
    ERR_STUDENT_NOT_FOUND,
    ERR_TRANSITION_PLAN_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_ledger,
    assert_pagination_meta,
    assert_route_seats,
    assert_unchanged,
)
from test_helpers.fixtures import (
    build_contracted_day_placement,
    build_reference_data,
    build_two_addenda_billing_cycle,
    file_attendance,
    file_funding_claim,
    list_rows,
    make_active_placement,
    make_approved_decision,
    make_fiscal_account,
    make_student,
    make_transport_route,
    read_account,
    read_placement,
    read_school,
    read_student,
    reset_clock,
    set_clock,
    verify_attendance,
)
from test_helpers.test_users import (
    COORDINATOR_HEADERS,
    FISCAL_OFFICER_HEADERS,
    SYSTEM_ADMIN_HEADERS,
)

AUTHORIZED_CENTS = 100000000
CORNER_ACCOUNT_CENTS = 6250000
FULL_STUDENT = {
    "state_student_id": "SS-C001",
    "full_name": "Ada Whitcombe",
    "district_of_residence": "Northvale USD",
    "disability_category": "MULTIPLE_DISABILITIES",
    "iep_effective_date": "2026-08-15",
    "lre_current_setting": "SEPARATE_CLASS_UNDER_40",
    "medicaid_eligible": True,
    "medicaid_consent_on_file": True,
}
PLAIN_STUDENT = {
    "state_student_id": "SS-C003",
    "full_name": "Cleo Marchetti",
    "district_of_residence": "Northvale USD",
    "disability_category": "OTHER_HEALTH_IMPAIRMENT",
    "iep_effective_date": "2026-08-15",
    "lre_current_setting": "GENERAL_ED_80_PLUS",
}
CORNER_ROUTE = {
    "route_code": "R-C01",
    "seat_capacity": 6,
    "daily_rate_cents": 5400,
    "service_window_start_min": 400,
    "service_window_end_min": 620,
}
PAGE_ROUTE_CODES = ["R-C11", "R-C12", "R-C13"]
MISSING_PLACEMENT_UUID = "00000000-0000-0000-0000-0000000000ff"
MISSING_ATTENDANCE_PLACEMENT_UUID = "00000000-0000-0000-0000-0000000000aa"


class TestStudentResource:
    """The student row: declared inputs, defaults and shape rejection."""

    def test_creation_returns_every_declared_field(self, api):
        """
        A registration that supplies all six required inputs and both optional
        booleans comes back with all of them plus the three system-derived floors.

        PRD: "Three further fields are system-derived and always start at their floor: `placement_status` at `NONE`, `high_cost_flag` at false and `projected_state_recovery_cents` at 0."

        Design: Corner/entities/student_creation_returns_all_declared_fields
        """
        reset_clock(api)
        response = api.create_student(
            f.student_payload(**FULL_STUDENT), COORDINATOR_HEADERS
        )
        student = validate_success(response, 201)

        for field, value in FULL_STUDENT.items():
            assert student[field] == value, field
        assert student["placement_status"] == "NONE"
        assert student["high_cost_flag"] is False
        assert student["projected_state_recovery_cents"] == 0
        assert is_valid_uuid(student["id"])
        assert is_iso8601_timestamp(student["created_at"])
        assert student["version"] == 1
        assert response.json()["meta"]["api_request_id"].startswith("req_")

    def test_the_two_medicaid_booleans_default_to_false(self, api):
        """
        Omitting both optional booleans leaves the student not Medicaid-eligible and
        without consent on file.

        PRD: "Two optional booleans may be supplied at registration and both default to false: `medicaid_eligible`, true when the student is Medicaid-enrolled, and `medicaid_consent_on_file`, true when signed parental consent to bill Medicaid has been received."

        Design: Corner/entities/student_medicaid_flags_default_to_false
        """
        reset_clock(api)
        student = validate_success(
            api.create_student(f.student_payload(**PLAIN_STUDENT), COORDINATOR_HEADERS),
            201,
        )

        assert student["medicaid_eligible"] is False
        assert student["medicaid_consent_on_file"] is False
        assert student["disability_category"] == PLAIN_STUDENT["disability_category"]
        assert student["lre_current_setting"] == PLAIN_STUDENT["lre_current_setting"]
        assert student["version"] == 1

    def test_a_registration_missing_the_district_of_residence_is_rejected(self, api):
        """
        A required field left out of the body is a shape failure, and nothing is
        persisted.

        PRD: "On every creating or modifying request: required fields present, enum values inside their declared sets, integers non-negative where required, dates well-formed ISO 8601 calendar dates or date-times, monetary fields supplied as integer cents rather than decimal strings, and no unknown field names."

        Design: Corner/entities/student_create_missing_district_of_residence_rejected
        """
        reset_clock(api)
        payload = f.student_payload(**PLAIN_STUDENT)
        payload.pop("district_of_residence")

        validate_error(
            api.create_student(payload, COORDINATOR_HEADERS), ERR_INVALID_REQUEST
        )

        _rows, meta = list_rows(api.list_students(COORDINATOR_HEADERS))
        assert meta["total_count"] == 0


class TestFiscalAccountResource:
    """The appropriation seeds its own ledger and its own audit columns."""

    def test_the_ledger_and_the_system_columns_are_server_generated(self, api):
        """
        Opening an account seeds the three derived buckets from the authorisation
        and mints the identity columns.

        PRD: "The three derived ledger columns are seeded at creation: `available_cents` equals `authorized_cents`, while `encumbered_cents` and `disbursed_cents` both start at zero."

        Design: Corner/entities/fiscal_account_system_fields_are_server_generated
        """
        reset_clock(api)
        account = make_fiscal_account(
            api, account_code="OOD-CORNER-A", authorized_cents=CORNER_ACCOUNT_CENTS
        )

        assert account["authorized_cents"] == CORNER_ACCOUNT_CENTS
        assert_ledger(
            account, available=CORNER_ACCOUNT_CENTS, encumbered=0, disbursed=0
        )
        assert is_valid_uuid(account["id"])
        assert is_iso8601_timestamp(account["created_at"])
        assert is_iso8601_timestamp(account["updated_at"])
        assert account["version"] == 1


class TestTransportRouteResource:
    """Route reads and the list envelope."""

    def test_a_read_returns_the_stored_route_with_its_seat_position(self, api):
        """
        The detail read echoes the five supplied fields and the seat pair the server
        seeded from the capacity.

        PRD: "On creation `seats_committed` is zero and `seats_available` equals `seat_capacity`, so the seat conservation identity of §2.6 holds from the very first moment."

        Design: Corner/entities/transport_route_retrieval_returns_stored_entity
        """
        reset_clock(api)
        created = make_transport_route(api, **CORNER_ROUTE)

        route = validate_success(
            api.get_transport_route(created["id"], SYSTEM_ADMIN_HEADERS)
        )
        for field, value in CORNER_ROUTE.items():
            assert route[field] == value, field
        assert_route_seats(route, 0, CORNER_ROUTE["seat_capacity"])
        assert route["id"] == created["id"]
        assert route["version"] == 1

    def test_the_route_list_reports_total_count_and_has_more(self, api):
        """
        Two windows over three routes: the first says rows remain, the second says
        they do not, and both report the unpaginated total.

        PRD: "For list responses the `meta` object of the envelope carries `limit`, `offset`, `total_count` and `has_more` alongside `api_request_id` and `api_request_timestamp`; `total_count` reports the number of rows matching the request's filters before pagination is applied, and `has_more` is true when rows remain beyond the current window."

        Design: Corner/entities/transport_route_list_paginates_with_total_count_and_has_more
        """
        reset_clock(api)
        for code in PAGE_ROUTE_CODES:
            make_transport_route(api, route_code=code)

        first_rows, first_meta = list_rows(
            api.list_transport_routes(SYSTEM_ADMIN_HEADERS, {"limit": 2, "offset": 0})
        )
        assert_pagination_meta(first_meta, 2, 0, 3, True)
        assert [row["route_code"] for row in first_rows] == PAGE_ROUTE_CODES[:2]

        second_rows, second_meta = list_rows(
            api.list_transport_routes(SYSTEM_ADMIN_HEADERS, {"limit": 2, "offset": 2})
        )
        assert_pagination_meta(second_meta, 2, 2, 3, False)
        assert [row["route_code"] for row in second_rows] == PAGE_ROUTE_CODES[2:]


class TestPlacementCreateAndRead:
    """Path existence, enum membership and body reference existence."""

    def test_an_unallocated_placement_id_is_not_found(self, api):
        """
        A well-formed identifier that names no row is refused with the placement's
        own not-found code.

        PRD: "Every identifier in the path resolves to an existing row, checked left to right, yielding that entity's not-found code (404)."

        Design: Corner/entities/unknown_placement_id_returns_not_found
        """
        reset_clock(api)

        validate_error(
            api.get_placement(MISSING_PLACEMENT_UUID, SYSTEM_ADMIN_HEADERS),
            ERR_PLACEMENT_NOT_FOUND,
        )

    def test_a_placement_type_outside_the_enum_is_rejected(self, api):
        """
        An out-of-enum placement type is a shape failure, so no placement exists and
        no money is committed.

        PRD: "On every creating or modifying request: required fields present, enum values inside their declared sets, integers non-negative where required, dates well-formed ISO 8601 calendar dates or date-times, monetary fields supplied as integer cents rather than decimal strings, and no unknown field names."

        Design: Corner/entities/placement_type_outside_enum_rejected
        """
        ref = build_reference_data(api)
        decision = make_approved_decision(api, ref["student"]["id"])

        validate_error(
            api.create_placement(
                f.placement_payload(
                    ref["student"]["id"],
                    ref["school"]["id"],
                    decision["id"],
                    ref["schedule"]["id"],
                    ref["account"]["id"],
                    placement_type="HYBRID",
                ),
                COORDINATOR_HEADERS,
            ),
            ERR_INVALID_REQUEST,
        )

        _rows, meta = list_rows(api.list_placements(COORDINATOR_HEADERS))
        assert meta["total_count"] == 0
        assert_ledger(
            read_account(api, ref["account"]["id"]),
            available=AUTHORIZED_CENTS,
            encumbered=0,
            disbursed=0,
        )

    def test_an_attendance_record_naming_an_unknown_placement_is_not_found(self, api):
        """
        A body identifier that resolves to nothing yields that entity's not-found
        code rather than a shape error.

        PRD: "Every identifier-bearing field in the body resolves to an existing row — `student_id`, `school_id`, `rate_schedule_id`, `decision_id`, `placement_id`, `route_id`, `attendance_record_id`, `fiscal_account_id`, `prior_placement_id`, `superseding_placement_id`, and every `service_addendum_id` inside a service-delivery line — each yielding its entity's not-found code (404)."

        Design: Corner/entities/attendance_record_create_with_unknown_placement_id_returns_not_found
        """
        ref = build_reference_data(api)

        validate_error(
            api.create_attendance_record(
                f.attendance_record_payload(MISSING_ATTENDANCE_PLACEMENT_UUID),
                ref["school_headers"],
            ),
            ERR_PLACEMENT_NOT_FOUND,
        )

        _rows, meta = list_rows(api.list_attendance_records(COORDINATOR_HEADERS))
        assert meta["total_count"] == 0


class TestFundingClaimComputedFields:
    """Every money field on a Medicaid claim is derived, never supplied."""

    MEDICAID_HOURS = 7.5
    ELIGIBLE_BASE_CENTS = 67500
    TIER_RATE = 0.5432
    REIMBURSABLE_CENTS = 36666

    def test_the_claim_arithmetic_and_the_student_rollup_are_server_derived(self, api):
        """
        The claim is filed naming only its placement, type and fiscal year, and the
        server computes the hours, the base, the rate and the award.

        PRD: "The `tier_rate` is the federal match percentage of 0.5432, and `reimbursable_amount_cents` is `eligible_base_cents` multiplied by 0.5432, rounded half up to whole cents — a second rounding applied to the already-rounded base, not a single rounding of the combined product."

        Design: Corner/entities/funding_claim_computed_fields_are_server_derived
        """
        world = build_two_addenda_billing_cycle(
            api,
            student_overrides={
                "medicaid_eligible": True,
                "medicaid_consent_on_file": True,
            },
        )

        claim = file_funding_claim(
            api, world["placement"]["id"], claim_type="MEDICAID"
        )

        assert claim["billable_service_hours"] == self.MEDICAID_HOURS
        assert claim["eligible_base_cents"] == self.ELIGIBLE_BASE_CENTS
        assert claim["tier_rate"] == self.TIER_RATE
        assert claim["reimbursable_amount_cents"] == self.REIMBURSABLE_CENTS
        assert claim["source"] == "MANUAL"
        assert claim["status"] == "ELIGIBLE"
        assert claim["submitted_at"] is None
        assert claim["state_claim_reference"] is None

        student = read_student(api, world["student"]["id"])
        assert student["projected_state_recovery_cents"] == self.REIMBURSABLE_CENTS


class TestRateScheduleSupersession:
    """A second state-approved schedule for the same year displaces the first."""

    SECOND_RATES = {
        "day_rate_cents": 33000,
        "residential_rate_cents": 52000,
        "service_hourly_rate_cents": 11500,
    }
    PINNED_ENCUMBRANCE_CENTS = 5760000

    def test_the_incumbent_is_superseded_and_pinned_contracts_are_not_repriced(
        self, api
    ):
        """
        Publishing the replacement repoints the school at the new schedule while the
        placement that already executed keeps the rates it pinned.

        PRD: "Publishing a schedule whose `approval_state` is `STATE_APPROVED` for a school and fiscal year that already has a `STATE_APPROVED` schedule drives the incumbent from `STATE_APPROVED` to `SUPERSEDED`, writes the new schedule's identifier into the incumbent's `superseded_by_schedule_id`, repoints the school's `active_rate_schedule_id` at the new schedule and increments the school's `version`."

        Design: Corner/state_machines/rate_schedule_state_approved_supersedes_prior_schedule_for_same_year
        """
        ref = build_contracted_day_placement(api)
        school_before = read_school(api, ref["school"]["id"])
        assert school_before["active_rate_schedule_id"] == ref["schedule"]["id"]

        replacement = validate_success(
            api.create_rate_schedule(
                f.rate_schedule_payload(
                    ref["school"]["id"],
                    school_before["version"],
                    **self.SECOND_RATES,
                ),
                FISCAL_OFFICER_HEADERS,
            ),
            201,
        )
        assert replacement["approval_state"] == "STATE_APPROVED"

        incumbent = validate_success(
            api.get_rate_schedule(ref["schedule"]["id"], FISCAL_OFFICER_HEADERS)
        )
        assert incumbent["approval_state"] == "SUPERSEDED"
        assert incumbent["superseded_by_schedule_id"] == replacement["id"]

        school_after = read_school(api, ref["school"]["id"])
        assert school_after["active_rate_schedule_id"] == replacement["id"]
        assert school_after["version"] == school_before["version"] + 1

        placement = read_placement(api, ref["placement"]["id"])
        assert placement["status"] == "CONTRACTED"
        assert placement["rate_schedule_id"] == ref["schedule"]["id"]
        assert placement["contract_encumbrance_cents"] == self.PINNED_ENCUMBRANCE_CENTS


class TestSchoolApprovalStatusPatch:
    """Approval standing is maintained by its own endpoint, one version per write."""

    def test_each_patch_updates_the_status_and_bumps_the_version(self, api):
        """
        A school registered without an approval status starts provisional, and each
        approval-status write advances the row by exactly one version.

        PRD: "Because this write increments the school's `version`, it also invalidates any expected-version value a rate-setter is holding, as described in §2.7."

        Design: Corner/endpoints/private_school_approval_status_patch_updates_and_bumps_version
        """
        reset_clock(api)
        payload = f.private_school_payload(
            name="Corner Day Academy", state_approval_id="SA-C01"
        )
        payload.pop("approval_status")
        created = validate_success(
            api.create_private_school(payload, SYSTEM_ADMIN_HEADERS), 201
        )
        school = created

        assert created["approval_status"] == "PROVISIONAL"
        assert created["active_rate_schedule_id"] is None
        assert created["version"] == 1

        approved = validate_success(
            api.patch_school_approval_status(
                school["id"], f.approval_status_payload("APPROVED"),
                SYSTEM_ADMIN_HEADERS,
            )
        )
        assert approved["approval_status"] == "APPROVED"
        assert approved["version"] == 2

        revoked = validate_success(
            api.patch_school_approval_status(
                school["id"], f.approval_status_payload("REVOKED"),
                SYSTEM_ADMIN_HEADERS,
            )
        )
        assert revoked["approval_status"] == "REVOKED"
        assert revoked["version"] == 3


class TestNotFoundCatalogue:
    """Each entity type answers a path-id miss with its own dedicated code."""

    PATH_MISSES = [
        ("get_student", "00000000-0000-0000-0000-000000000001", ERR_STUDENT_NOT_FOUND),
        (
            "get_private_school",
            "00000000-0000-0000-0000-000000000002",
            ERR_SCHOOL_NOT_FOUND,
        ),
        (
            "get_rate_schedule",
            "00000000-0000-0000-0000-000000000003",
            ERR_RATE_SCHEDULE_NOT_FOUND,
        ),
        (
            "get_placement_decision",
            "00000000-0000-0000-0000-000000000004",
            ERR_DECISION_NOT_FOUND,
        ),
        (
            "get_service_addendum",
            "00000000-0000-0000-0000-000000000005",
            ERR_ADDENDUM_NOT_FOUND,
        ),
        (
            "get_transport_route",
            "00000000-0000-0000-0000-000000000006",
            ERR_ROUTE_NOT_FOUND,
        ),
        (
            "get_transportation_assignment",
            "00000000-0000-0000-0000-000000000007",
            ERR_ASSIGNMENT_NOT_FOUND,
        ),
        (
            "get_attendance_record",
            "00000000-0000-0000-0000-000000000008",
            ERR_ATTENDANCE_RECORD_NOT_FOUND,
        ),
        (
            "get_tuition_invoice",
            "00000000-0000-0000-0000-000000000009",
            ERR_INVOICE_NOT_FOUND,
        ),
        (
            "get_reimbursement_claim",
            "00000000-0000-0000-0000-00000000000a",
            ERR_CLAIM_NOT_FOUND,
        ),
        (
            "get_progress_report",
            "00000000-0000-0000-0000-00000000000b",
            ERR_PROGRESS_REPORT_NOT_FOUND,
        ),
        (
            "get_transition_plan",
            "00000000-0000-0000-0000-00000000000c",
            ERR_TRANSITION_PLAN_NOT_FOUND,
        ),
        (
            "get_funding_claim",
            "00000000-0000-0000-0000-00000000000d",
            ERR_FUNDING_CLAIM_NOT_FOUND,
        ),
        (
            "get_fiscal_account",
            "00000000-0000-0000-0000-00000000000e",
            ERR_FISCAL_ACCOUNT_NOT_FOUND,
        ),
    ]

    def test_all_fourteen_entity_types_answer_with_their_own_code(self, api):
        """
        Reading an absent row of each of the fourteen path-addressed entity types
        against an empty database yields that entity's own not-found code.

        PRD: "Every identifier in the path resolves to an existing row, checked left to right, yielding that entity's not-found code (404)."

        Design: Corner/errors/every_entity_has_its_own_path_id_not_found_code
        """
        reset_clock(api)

        for method_name, missing_id, expected_error in self.PATH_MISSES:
            response = getattr(api, method_name)(missing_id, SYSTEM_ADMIN_HEADERS)
            validate_error(response, expected_error)

        codes = [error for _, _, error in self.PATH_MISSES]
        assert len(set(codes)) == len(codes)


class TestBodyForeignKeys:
    """A bogus identifier in the body names the entity it failed to resolve."""

    BODY_MISSES = [
        ("student_id", "00000000-0000-0000-0000-000000000011", ERR_STUDENT_NOT_FOUND),
        ("school_id", "00000000-0000-0000-0000-000000000012", ERR_SCHOOL_NOT_FOUND),
        ("decision_id", "00000000-0000-0000-0000-000000000013", ERR_DECISION_NOT_FOUND),
        (
            "rate_schedule_id",
            "00000000-0000-0000-0000-000000000014",
            ERR_RATE_SCHEDULE_NOT_FOUND,
        ),
        (
            "fiscal_account_id",
            "00000000-0000-0000-0000-000000000015",
            ERR_FISCAL_ACCOUNT_NOT_FOUND,
        ),
    ]

    def test_each_unresolvable_body_id_reports_its_own_entity(self, api):
        """
        Five placement creates that differ only in which one of the five body
        identifiers is bogus each report that field's own entity as not found, and
        none of them creates a placement.

        PRD: "Every identifier-bearing field in the body resolves to an existing row — `student_id`, `school_id`, `rate_schedule_id`, `decision_id`, `placement_id`, `route_id`, `attendance_record_id`, `fiscal_account_id`, `prior_placement_id`, `superseding_placement_id`, and every `service_addendum_id` inside a service-delivery line — each yielding its entity's not-found code (404)."

        Design: Corner/errors/body_foreign_keys_report_the_specific_entity_that_was_not_found
        """
        ref = build_reference_data(api)
        decision = make_approved_decision(api, ref["student"]["id"])

        for field, missing_id, expected_error in self.BODY_MISSES:
            payload = f.placement_payload(
                ref["student"]["id"],
                ref["school"]["id"],
                decision["id"],
                ref["schedule"]["id"],
                ref["account"]["id"],
            )
            payload[field] = missing_id
            validate_error(
                api.create_placement(payload, COORDINATOR_HEADERS), expected_error
            )

        rows, meta = list_rows(api.list_placements(COORDINATOR_HEADERS))
        assert rows == []
        assert meta["total_count"] == 0

        account = read_account(api, ref["account"]["id"])
        assert_ledger(account, available=AUTHORIZED_CENTS, encumbered=0, disbursed=0)


class TestCrossEntityLinkage:
    """Rows that exist but belong elsewhere are refused at the ninth rung."""

    SECOND_STUDENT = {
        "state_student_id": "SS-C009",
        "full_name": "Ravi Balakrishnan",
        "district_of_residence": "Northvale USD",
        "disability_category": "SPECIFIC_LEARNING_DISABILITY",
        "iep_effective_date": "2026-08-15",
        "lre_current_setting": "RESOURCE_40_79",
    }
    SUBMITTED_CENTS = 654400
    LATER_START = "2027-01-04"
    LATER_DAYS = 100

    def test_the_three_reachable_mismatches_are_each_named_precisely(self, api):
        """
        An attendance record from a sibling placement, a decision belonging to another
        student and a funding claim for the wrong fiscal year are each refused by the
        referential-consistency rung rather than by any later business rule.

        PRD: "Four checks, all 409: an invoice's attendance record must belong to the invoice's own placement (`ERR_ATTENDANCE_PLACEMENT_MISMATCH`); a new placement's decision must belong to the named student and its rate schedule to the named school (`ERR_PLACEMENT_LINKAGE_MISMATCH`); every service-delivery line on an attendance record must name an addendum on that same placement (`ERR_ADDENDUM_PLACEMENT_MISMATCH`); and a funding claim's fiscal year must match the fiscal year of the placement's pinned rate schedule, with that placement's contract actually executed (`ERR_FUNDING_CLAIM_LINKAGE_MISMATCH`)."

        Design: Corner/errors/cross_entity_linkage_mismatches_are_rejected_at_priority_nine
        """
        ref = build_reference_data(api)
        second_student = make_student(api, **self.SECOND_STUDENT)
        first = make_active_placement(api, ref)
        second = make_active_placement(api, ref, student=second_student)

        record = file_attendance(api, ref, first["id"])
        verify_attendance(api, record["id"])

        validate_error(
            api.create_tuition_invoice(
                f.tuition_invoice_payload(
                    second["id"],
                    record["id"],
                    self.SUBMITTED_CENTS,
                    read_placement(api, second["id"])["version"],
                ),
                ref["school_headers"],
            ),
            ERR_ATTENDANCE_PLACEMENT_MISMATCH,
        )

        validate_error(
            api.create_placement(
                f.placement_payload(
                    second_student["id"],
                    ref["school"]["id"],
                    first["_decision_id"],
                    ref["schedule"]["id"],
                    ref["account"]["id"],
                    start_date=self.LATER_START,
                    contracted_instructional_days=self.LATER_DAYS,
                ),
                COORDINATOR_HEADERS,
            ),
            ERR_PLACEMENT_LINKAGE_MISMATCH,
        )

        validate_error(
            api.create_funding_claim(
                f.funding_claim_payload(first["id"], fiscal_year=2026),
                FISCAL_OFFICER_HEADERS,
            ),
            ERR_FUNDING_CLAIM_LINKAGE_MISMATCH,
        )

        invoices, invoice_meta = list_rows(
            api.list_tuition_invoices(
                FISCAL_OFFICER_HEADERS, params={"placement_id": second["id"]}
            )
        )
        assert invoices == []
        assert invoice_meta["total_count"] == 0

        claims, claim_meta = list_rows(
            api.list_funding_claims(
                FISCAL_OFFICER_HEADERS, params={"placement_id": first["id"]}
            )
        )
        assert claims == []
        assert claim_meta["total_count"] == 0


class TestStaleSchoolVersionOnRatePublication:
    """Rate publication carries the school version the setter last read."""

    FY2028_RATES = {
        "fiscal_year": 2028,
        "day_rate_cents": 33500,
        "residential_rate_cents": 53000,
        "service_hourly_rate_cents": 11500,
        "effective_from": "2027-07-01",
        "effective_to": "2028-06-30",
    }

    def test_a_stale_expected_school_version_is_refused_then_the_retry_succeeds(
        self, api
    ):
        """
        Publishing the first schedule advances the school, so a second publication
        quoting the original version is refused until the setter re-reads.

        PRD: "If it does not equal that school's current `version`, the create is rejected with `ERR_STALE_SCHOOL_VERSION` (412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_school_version_on_rate_schedule_create_returns_412
        """
        ref = build_reference_data(api)
        school_after_first = read_school(api, ref["school"]["id"])
        assert school_after_first["version"] == 2
        assert school_after_first["active_rate_schedule_id"] == ref["schedule"]["id"]

        validate_error(
            api.create_rate_schedule(
                f.rate_schedule_payload(ref["school"]["id"], 1, **self.FY2028_RATES),
                FISCAL_OFFICER_HEADERS,
            ),
            ERR_STALE_SCHOOL_VERSION,
        )
        assert_unchanged(school_after_first, read_school(api, ref["school"]["id"]))

        published = validate_success(
            api.create_rate_schedule(
                f.rate_schedule_payload(ref["school"]["id"], 2, **self.FY2028_RATES),
                FISCAL_OFFICER_HEADERS,
            ),
            201,
        )
        assert published["fiscal_year"] == 2028
        assert published["approval_state"] == "STATE_APPROVED"

        school_after_second = read_school(api, ref["school"]["id"])
        assert school_after_second["version"] == 3
        assert school_after_second["active_rate_schedule_id"] == published["id"]

        rows, meta = list_rows(
            api.list_rate_schedules(
                FISCAL_OFFICER_HEADERS, params={"school_id": ref["school"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        by_year = {row["fiscal_year"]: row for row in rows}
        assert by_year[2027]["approval_state"] == "STATE_APPROVED"
        assert by_year[2027]["superseded_by_schedule_id"] is None


class TestVersionCounterDiscipline:
    """Writes advance the counter by exactly one; reads never move it."""

    FIRST_WRITE_INSTANT = "2026-08-05T10:00:00Z"
    SECOND_WRITE_INSTANT = "2026-08-09T14:30:00Z"

    def test_two_writes_advance_the_row_and_the_three_reads_do_not(self, api):
        """
        A student read, written, read, written identically and read again ends at
        version three, with created_at fixed and updated_at moving only on the writes.

        PRD: "`version` (integer): a counter that increments by exactly one on every mutation of that row."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_write_and_never_on_a_read
        """
        reset_clock(api)
        created = make_student(api, **PLAIN_STUDENT)
        assert created["version"] == 1

        first_read = read_student(api, created["id"])
        assert first_read["version"] == 1
        assert_unchanged(created, first_read)
        assert first_read["medicaid_eligible"] is False
        assert first_read["medicaid_consent_on_file"] is False

        consent = f.medicaid_consent_payload(
            medicaid_eligible=True, medicaid_consent_on_file=False
        )

        set_clock(api, self.FIRST_WRITE_INSTANT)
        first_write = validate_success(
            api.patch_medicaid_consent(created["id"], consent, COORDINATOR_HEADERS)
        )
        assert first_write["version"] == 2
        assert first_write["medicaid_eligible"] is True
        assert first_write["medicaid_consent_on_file"] is False
        assert first_write["updated_at"].startswith("2026-08-05T10:00:00")
        assert first_write["updated_at"] > first_read["updated_at"]

        second_read = read_student(api, created["id"])
        assert second_read["version"] == 2
        assert_unchanged(first_write, second_read)

        set_clock(api, self.SECOND_WRITE_INSTANT)
        second_write = validate_success(
            api.patch_medicaid_consent(created["id"], consent, COORDINATOR_HEADERS)
        )
        assert second_write["version"] == 3
        assert second_write["medicaid_eligible"] is True
        assert second_write["medicaid_consent_on_file"] is False
        assert second_write["updated_at"].startswith("2026-08-09T14:30:00")
        assert second_write["updated_at"] > first_write["updated_at"]

        third_read = read_student(api, created["id"])
        assert third_read["version"] == 3
        assert_unchanged(second_write, third_read)

        reads = [created, first_read, first_write, second_read, second_write, third_read]
        assert len({row["created_at"] for row in reads}) == 1
        assert is_iso8601_timestamp(created["created_at"])
        assert is_valid_uuid(created["id"])
