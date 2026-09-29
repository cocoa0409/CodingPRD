"""Entity shape, envelope, defaults, derived fields and reference resolution."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.factories import (
    OMIT,
    make_acquirer_payload,
    make_incentive_enrollment_payload,
    make_mcc_definition_payload,
    make_processing_platform_payload,
)
from test_helpers.fixtures import (
    add_record,
    board_merchant,
    canonical_environment,
    create_acquirer,
    create_incentive_program,
    create_mcc,
    create_platform,
    open_batch,
    read_enrollment,
    read_merchant,
    set_clock,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_category_analyst_headers,
    make_compliance_auditor_headers,
)

NETWORK_ADMIN = TEST_USERS["network_admin_headers"]
CLOCK = "2026-09-03T00:00:00Z"
CLOCK_STAMP = "2026-09-03T00:00:00.000Z"


class TestEntityShapeAndEnvelope:
    def test_registering_a_platform_returns_the_created_row_in_the_object_envelope(self):
        """The create call answers 201 with the stored platform wrapped in the
        standard envelope, echoing every supplied field at version 1.

        PRD 4: "Creating a new resource returns HTTP 201 with the created resource
        in `data`; every other successful operation — state transitions, retrievals
        and listings alike — returns HTTP 200, with the modified resource in `data`
        for mutations and an array in `data` for listings."

        Design: Corner/entities/entity_creation_processing_platform_returns_object_envelope_with_all_fields
        """
        set_clock(CLOCK)
        response = api_client.create_processing_platform(
            make_processing_platform_payload(
                name="PLAT-NA-1",
                region_code="NA",
                max_concurrent_windows=1,
                blackout_buffer_days=3,
            ),
            NETWORK_ADMIN,
        )
        platform = validate_success(response, 201)
        body = response.json()

        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"]
        assert body["meta"]["api_request_timestamp"]
        assert platform["name"] == "PLAT-NA-1"
        assert platform["region_code"] == "NA"
        assert platform["max_concurrent_windows"] == 1
        assert platform["blackout_buffer_days"] == 3
        assert platform["version"] == 1
        assert isinstance(platform["id"], str) and platform["id"]

    def test_fetching_an_acquirer_returns_the_stored_row_with_its_opening_posture(self):
        """A read hands back exactly what registration stored, including the two
        system-defaulted compliance fields.

        PRD 3.1: "Every newly registered acquirer starts life with
        `compliance_status` set to `COMPLIANT` and `missed_window_count` set to 0."

        Design: Corner/entities/entity_retrieval_acquirer_by_id_returns_the_stored_row
        """
        set_clock(CLOCK)
        platform = create_platform()
        acquirer = create_acquirer(platform["id"])

        fetched = validate_success(
            api_client.get_acquirer(
                acquirer["id"], make_compliance_auditor_headers("CA-1")
            )
        )
        assert fetched["id"] == acquirer["id"]
        assert fetched["name"] == "Acme Acquiring"
        assert fetched["bin_prefix"] == "411111"
        assert fetched["platform_id"] == platform["id"]
        assert fetched["country_code"] == "US"
        assert fetched["settlement_currency"] == "USD"
        assert fetched["compliance_status"] == "COMPLIANT"
        assert fetched["missed_window_count"] == 0

    def test_the_acquirer_timestamps_and_version_come_from_the_server(self):
        """`id`, `created_at`, `updated_at` and `version` are server-minted, and the
        two timestamps take the logical clock rather than the host clock.

        PRD 2.4: "`created_at` and `updated_at` are ISO 8601 UTC timestamps rendered
        with exactly three fractional-second digits. `version` is an integer that
        starts at 1 when the row is created and increments by exactly 1 on every
        mutation of that row."

        Design: Corner/entities/entity_system_fields_acquirer_timestamps_and_version_are_server_generated
        """
        set_clock(CLOCK)
        platform = create_platform()
        acquirer = create_acquirer(platform["id"])

        assert acquirer["created_at"] == CLOCK_STAMP
        assert acquirer["updated_at"] == CLOCK_STAMP
        assert acquirer["version"] == 1
        assert isinstance(acquirer["id"], str) and acquirer["id"]


class TestCollectionPagination:
    def test_the_category_directory_pages_with_total_count_and_has_more(self):
        """Three definitions read two at a time: the first page reports more rows
        beyond it, the second page reports none.

        PRD 2.3: "For list responses, `response_type` is `"array"` and the `meta`
        object additionally carries `limit` (the effective page size), `offset` (the
        effective skip), `total_count` (the number of rows matching the filters
        before pagination) and `has_more` (true when rows remain beyond the current
        page)."

        Design: Corner/entities/entity_listing_mcc_definitions_paginated_with_total_count_and_has_more
        """
        set_clock(CLOCK)
        create_mcc("5411", "GROCERY", description="Grocery Stores")
        create_mcc(
            "5311",
            "DEPARTMENT_STORE",
            description="Department Stores",
            program_eligibility=[],
        )
        create_mcc(
            "4900",
            "UTILITY_SERVICE",
            description="Utilities",
            program_eligibility=["UTILITY"],
            requires_documentation=True,
        )
        analyst = make_category_analyst_headers("CAN-1")

        first = api_client.list_mcc_definitions(analyst, params={"limit": 2, "offset": 0})
        rows, meta = validate_paginated(first)
        assert first.json()["response_type"] == "array"
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["has_more"] is True

        second = api_client.list_mcc_definitions(analyst, params={"limit": 2, "offset": 2})
        rows, meta = validate_paginated(second)
        assert len(rows) == 1
        assert meta["total_count"] == 3
        assert meta["offset"] == 2
        assert meta["has_more"] is False

    def test_a_listing_without_paging_parameters_uses_the_declared_defaults(self):
        """Omitting both parameters yields the default page rather than an unbounded
        one.

        PRD 2.3: "`limit` defaults to 10 when omitted, may not be smaller than 1,
        and may not exceed 100. `offset` defaults to 0 and is a zero-based row skip."

        Design: Corner/entities/entity_defaults_listing_without_limit_applies_default_page_size_of_ten
        """
        set_clock(CLOCK)
        create_platform(name="PLAT-NA-1", region_code="NA")
        create_platform(
            name="PLAT-EU-1",
            region_code="EU",
            max_concurrent_windows=2,
            blackout_buffer_days=0,
        )

        rows, meta = validate_paginated(
            api_client.list_processing_platforms(NETWORK_ADMIN)
        )
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert len(rows) == 2


class TestFieldDefaultsAndDerivedValues:
    def test_omitting_the_waitlist_flag_stores_false_rather_than_null(self):
        """The one optional input on an enrollment defaults to false, and with free
        capacity the row resolves straight to `ENROLLED` with its scoring fields at
        rest.

        PRD 3.8: "Enrolling is an acquirer action, and the request carries
        `incentive_program_id`, `merchant_id`, `committed_volume_cents` (strictly
        positive), the optional `waitlist_requested` flag which defaults to false,
        and `expected_incentive_program_version`."

        Design: Corner/entities/entity_defaults_enrollment_omitting_waitlist_requested_defaults_to_false
        """
        env = canonical_environment(CLOCK, program_keys=())
        program = create_incentive_program(
            program_name="Grocery Growth 2026",
            eligible_mcc_codes=["5411"],
            total_capacity_cents=100000000,
            min_commitment_cents=5000000,
            reopen_threshold_cents=5000000,
            performance_threshold_pct=80.00,
        )
        merchant = board_merchant(env["acquirer"]["id"], "GROCERY")

        payload = make_incentive_enrollment_payload(
            program["id"], merchant["id"], 5000000, program["version"]
        )
        assert "waitlist_requested" not in payload

        enrollment = validate_success(
            api_client.create_incentive_enrollment(payload, env["acquirer_headers"]),
            201,
        )
        assert enrollment["waitlist_requested"] is False
        assert enrollment["status"] == "ENROLLED"
        assert enrollment["probation_count"] == 0
        assert enrollment["achieved_volume_cents"] == 0
        assert enrollment["tier_code"] is None
        assert read_enrollment(enrollment["id"])["enrolled_at"] == CLOCK_STAMP

    def test_the_assigned_category_tie_breaks_on_the_code_not_on_creation_order(self):
        """Both telecom definitions are non-high-risk, so the second ranking key
        decides and 4814 wins even though 4816 was recorded first.

        PRD 3.3: "Otherwise the candidates are ranked by three keys applied in
        order: `high_risk` ascending, so definitions that are not flagged high-risk
        are preferred over those that are; then `mcc_code` ascending as a
        lexicographic comparison over the four-digit string; and finally, only if
        both of those tie, `created_at` ascending."

        Design: Corner/entities/entity_computed_field_assigned_mcc_tie_breaks_on_mcc_code_ascending
        """
        set_clock(CLOCK)
        platform = create_platform()
        acquirer = create_acquirer(platform["id"])
        create_mcc(
            "4816",
            "TELECOM",
            description="Computer Network Services",
            program_eligibility=[],
        )
        create_mcc(
            "4814",
            "TELECOM",
            description="Telecommunication Services",
            program_eligibility=[],
        )

        merchant = board_merchant(
            acquirer["id"], "TELECOM", legal_name="Northline Telecom"
        )
        assert merchant["assigned_mcc"] == "4814"
        assert merchant["mcc_status"] == "VERIFIED"
        assert merchant["mcc_status_before_review"] is None
        assert merchant["downgrade_count_current_quarter"] == 0
        assert merchant["lifetime_net_assessed_cents"] == 0
        assert read_merchant(merchant["id"])["version"] == 1

    def test_a_high_risk_definition_sorts_behind_a_numerically_larger_safe_one(self):
        """The risk flag dominates the code comparison, so 6051 is assigned in
        preference to the smaller but high-risk 4829.

        PRD 3.1: "`high_risk` is the flag that sorts a definition to the back of the
        queue when the assignment rule has a choice."

        Design: Corner/entities/entity_computed_field_assigned_mcc_ranks_high_risk_ascending_before_mcc_code
        """
        set_clock(CLOCK)
        platform = create_platform()
        acquirer = create_acquirer(platform["id"])
        create_mcc(
            "4829",
            "MONEY_TRANSFER",
            description="Wire Transfer Money Orders",
            program_eligibility=[],
            high_risk=True,
        )
        create_mcc(
            "6051",
            "MONEY_TRANSFER",
            description="Quasi Cash Financial Institutions",
            program_eligibility=[],
        )

        merchant = board_merchant(
            acquirer["id"], "MONEY_TRANSFER", legal_name="Sendwell Remit"
        )
        assert merchant["assigned_mcc"] == "6051"
        assert merchant["assigned_mcc"] != "4829"
        assert merchant["mcc_status"] == "VERIFIED"
        assert merchant["business_type_key"] == "MONEY_TRANSFER"

    def test_a_clearing_record_is_discoverable_from_its_batch_and_from_its_merchant(self):
        """Both cross-aggregate edges are queryable: the same row comes back when
        the record list is narrowed by batch and when it is narrowed by merchant.

        PRD 3.5: "Batches can be listed and narrowed by `acquirer_id`, `status` and
        `batch_date`; records can be listed and narrowed by `settlement_batch_id`,
        `merchant_id`, `provisional_rate_program_id`, `qualified_rate_program_id`,
        `qualification_status` and `authorization_status`."

        Design: Corner/entities/entity_graph_transaction_record_is_reachable_from_both_batch_and_merchant
        """
        env = canonical_environment(
            CLOCK, program_keys=("SMALL_TICKET", "STANDARD")
        )
        acquirer_id = env["acquirer"]["id"]
        merchant = board_merchant(acquirer_id, "GROCERY")
        batch = open_batch(acquirer_id, "2026-09-02", "USD")
        record = add_record(
            batch["id"],
            merchant["id"],
            1400,
            acquirer_id,
            expected_batch_version=batch["version"],
            auth_code="A00200",
            auth_timestamp="2026-09-02T00:00:00Z",
            clearing_timestamp="2026-09-02T01:00:00Z",
            data_elements=["AUTH_CODE", "TERMINAL_ID"],
        )

        by_batch, batch_meta = validate_paginated(
            api_client.list_transaction_records(
                NETWORK_ADMIN, params={"settlement_batch_id": batch["id"]}
            )
        )
        assert batch_meta["total_count"] == 1
        assert by_batch[0]["id"] == record["id"]

        by_merchant, merchant_meta = validate_paginated(
            api_client.list_transaction_records(
                NETWORK_ADMIN, params={"merchant_id": merchant["id"]}
            )
        )
        assert merchant_meta["total_count"] == 1
        assert by_merchant[0]["id"] == record["id"]

        assert record["settlement_batch_id"] == batch["id"]
        assert record["merchant_id"] == merchant["id"]
        assert record["qualification_status"] == "PENDING"
        assert record["provisional_assessed_cents"] == 27


class TestRejectedShapesAndUnresolvableReferences:
    def test_a_well_formed_but_unstored_merchant_id_answers_not_found(self):
        """The path identifier resolves to nothing, so the read is a 404 naming the
        merchant rather than an empty success body.

        PRD 2.5: "The first identifier that does not resolve to a stored row
        terminates the request with HTTP 404 and the not-found code belonging to that
        identifier's entity type, so a request against a record inside a batch that
        does not exist reports the missing batch rather than the missing record."

        Design: Corner/entities/entity_not_found_get_merchant_with_unknown_id_returns_404
        """
        set_clock(CLOCK)
        response = api_client.get_merchant(NON_EXISTENT_UUID, NETWORK_ADMIN)
        error = validate_error(response, "ERR_MERCHANT_NOT_FOUND", 404)

        assert response.json()["response_type"] == "error"
        assert error["message"].strip()

    def test_an_acquirer_without_its_bin_prefix_is_refused_and_nothing_is_stored(self):
        """`bin_prefix` has no default, so the request is malformed and no acquirer
        row survives the attempt.

        PRD 2.9: "The request body is well formed — otherwise `ERR_INVALID_REQUEST`
        (400). Applies to every POST endpoint."

        Design: Corner/entities/entity_required_fields_acquirer_without_bin_prefix_is_rejected_with_400
        """
        set_clock(CLOCK)
        platform = create_platform()

        response = api_client.create_acquirer(
            make_acquirer_payload(platform["id"], bin_prefix=OMIT), NETWORK_ADMIN
        )
        validate_error(response, "ERR_INVALID_REQUEST", 400)

        _rows, meta = validate_paginated(
            api_client.list_acquirers(
                NETWORK_ADMIN, params={"platform_id": platform["id"]}
            )
        )
        assert meta["total_count"] == 0

    def test_a_region_code_outside_the_declared_set_is_refused(self):
        """`XX` is not one of the five network regions, so the platform is never
        created.

        PRD 3.1: "Registering a platform records a human label as `name`, unique
        across platforms and between 1 and 80 characters; the network region it
        serves as `region_code`, which must be one of `NA`, `EU`, `AP`, `LAC` or
        `CEMEA`; and two capacity parameters."

        Design: Corner/entities/entity_type_constraints_invalid_region_code_enum_is_rejected_with_400
        """
        set_clock(CLOCK)
        response = api_client.create_processing_platform(
            make_processing_platform_payload(name="PLAT-XX-1", region_code="XX"),
            NETWORK_ADMIN,
        )
        validate_error(response, "ERR_INVALID_REQUEST", 400)

        _rows, meta = validate_paginated(
            api_client.list_processing_platforms(NETWORK_ADMIN)
        )
        assert meta["total_count"] == 0

    def test_a_three_digit_category_code_is_refused_on_format(self):
        """A category code is exactly four digits, so `541` fails the shape check and
        the directory stays empty.

        PRD 3.1: "Each definition records `mcc_code`, exactly four digits and
        globally unique; `description`, the category text as published in the
        directory, between 1 and 200 characters; and `business_type_key`, an
        uppercase key of A–Z characters and underscores, 1 to 40 characters long,
        which is how a declared business type is mapped onto a category."

        Design: Corner/entities/entity_type_constraints_mcc_code_shorter_than_four_digits_is_rejected_with_400
        """
        set_clock(CLOCK)
        response = api_client.create_mcc_definition(
            make_mcc_definition_payload(
                mcc_code="541",
                business_type_key="GROCERY",
                description="Grocery Stores",
                program_eligibility=["SMALL_TICKET"],
            ),
            NETWORK_ADMIN,
        )
        validate_error(response, "ERR_INVALID_REQUEST", 400)

        _rows, meta = validate_paginated(api_client.list_mcc_definitions(NETWORK_ADMIN))
        assert meta["total_count"] == 0

    def test_an_acquirer_naming_an_unstored_platform_answers_not_found(self):
        """The body-supplied foreign key is resolved too, and its failure is a 404
        naming the platform rather than the 400 a malformed body would raise.

        PRD 2.9: "Every identifier supplied in the request body resolves to a stored
        row, checked in the order the endpoint declares its input fields — otherwise
        the matching 404 not-found code."

        Design: Corner/entities/entity_parent_relationships_acquirer_with_unknown_platform_id_returns_404
        """
        set_clock(CLOCK)
        response = api_client.create_acquirer(
            make_acquirer_payload(NON_EXISTENT_UUID), NETWORK_ADMIN
        )
        validate_error(response, "ERR_PLATFORM_NOT_FOUND", 404)

        _rows, meta = validate_paginated(api_client.list_acquirers(NETWORK_ADMIN))
        assert meta["total_count"] == 0
