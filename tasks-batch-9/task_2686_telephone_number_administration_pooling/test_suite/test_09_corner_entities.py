"""Entity shape: defaults, computed fields, identity, listings and parentage."""
from test_helpers import (
    ADMIN_HEADERS,
    APPROVER_HEADERS,
    COMMENTER_HEADERS,
    DEFAULT_CLOCK,
    TEST_DEFAULTS,
    UNKNOWN_ID,
    ApiErrorId,
    api_client,
    assert_block_label,
    assert_fresh_carrier,
    assert_identity,
    assert_is_pooling_eligible_is_derived,
    assert_mutable_identity,
    assert_public_comment,
    assert_unheld_block,
    create_block_payload,
    create_carrier_payload,
    create_eligible_carrier,
    create_filing,
    create_licensed_carrier,
    create_public_comment_payload,
    create_rate_center_payload,
    create_utilization_filing_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_carrier_representative_headers,
    rate_center_version,
    read_carrier,
    read_rate_center,
    register_carrier,
    set_clock,
    setup_npa_with_rate_center,
    setup_plan_in_public_comment,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCarrierRegistrationOpensOnBothAxesAtTheirStart:
    """Registration alone authorizes nothing."""

    def test_a_freshly_registered_carrier_is_ineligible_on_both_axes(self):
        """The licensing and facilities axes both open at their initial value, so the
        computed eligibility can only read ineligible.

        A freshly registered carrier has `license_status` of `NONE`, `facilities_readiness_status` of

        and consequently a computed `eligibility_status` of `INELIGIBLE`. Its `version` starts at 1.

        Design: Corner/entities/carrier_creation_stamps_default_license_and_readiness_axes
        """
        set_clock()

        carrier = validate_success(
            api_client.create_carrier(create_carrier_payload("A"), ADMIN_HEADERS), 201
        )

        assert carrier["ocn"] == "1234"
        assert carrier["legal_name"] == "Acme Telecom LLC"
        assert carrier["carrier_type"] == "CLEC"
        assert carrier["home_state_code"] == "OH"
        assert carrier["months_in_operation"] == 24
        assert_fresh_carrier(carrier)


class TestCarrierRetrievalReturnsTheRowTheTwoAxesBuilt:
    """A read reports the eligibility the two axes together imply."""

    def test_the_stored_row_reads_eligible_once_both_axes_are_satisfied(self):
        """A licence and a verified inspection are two separate events, and eligibility is
        computed from their combination rather than written by either one.

        It is `ELIGIBLE` when `license_status` is `GRANTED` and `facilities_readiness_status` is `VERIFIED` and `reclamation_strike_count` is below 2

        `ATTEST` sets `facilities_readiness_status` to `ATTESTED`, copies `switch_clli` and `interconnection_ready` from the payload

        Design: Corner/entities/carrier_retrieval_returns_stored_row_with_eligible_status
        """
        set_clock()
        carrier = create_eligible_carrier("A")

        fetched = validate_success(api_client.get_carrier(carrier["id"], APPROVER_HEADERS))

        assert fetched["id"] == carrier["id"]
        assert fetched["license_status"] == "GRANTED"
        assert fetched["license_expires_on"] == TEST_DEFAULTS["LICENSE_EXPIRES_ON"]
        assert fetched["facilities_readiness_status"] == "VERIFIED"
        assert fetched["switch_clli"] == TEST_DEFAULTS["SWITCH_CLLI_A"]
        assert fetched["interconnection_ready"] is True
        assert fetched["eligibility_status"] == "ELIGIBLE"


class TestCarrierListingPaginates:
    """Two pages cover three rows and the envelope says so on both."""

    def test_a_page_of_two_reports_three_rows_and_more_to_come(self):
        """The first page carries two of the three registered carriers, and the second
        carries the remaining one with nothing beyond it.

        `limit` controls page size: it defaults to 10 when omitted, may not be lower than 1, and may not exceed 100.

        `total_count` giving the number of rows matching the filter before pagination was applied, and `has_more` indicating whether any further rows exist beyond this page

        Design: Corner/entities/carrier_listing_paginates_with_total_count_and_has_more
        """
        set_clock()
        for profile in ("A", "B", "C"):
            register_carrier(profile)

        first_rows, first_meta = validate_paginated(
            api_client.list_carriers(ADMIN_HEADERS, params={"limit": 2, "offset": 0})
        )
        assert len(first_rows) == 2
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True

        second_rows, second_meta = validate_paginated(
            api_client.list_carriers(ADMIN_HEADERS, params={"limit": 2, "offset": 2})
        )
        assert len(second_rows) == 1
        assert second_meta["offset"] == 2
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False

        seen = [row["ocn"] for row in first_rows] + [row["ocn"] for row in second_rows]
        assert sorted(seen) == ["1234", "5678", "9012"]


class TestUnknownCarrierIdIsANotFound:
    """A well-formed identifier that names nothing is still a 404."""

    def test_an_unknown_carrier_id_in_the_path_is_reported_as_not_found(self):
        """Reading a carrier that was never registered is refused rather than answered
        with an empty body.

        The available not-found codes are `ERR_CARRIER_NOT_FOUND`, `ERR_NPA_NOT_FOUND`, `ERR_RATE_CENTER_NOT_FOUND`

        the first segment that names a row which does not exist terminates the request with that segment's own 404 code

        Design: Corner/entities/carrier_not_found_for_unknown_path_id
        """
        set_clock()

        validate_error(
            api_client.get_carrier(UNKNOWN_ID, ADMIN_HEADERS),
            ApiErrorId.ERR_CARRIER_NOT_FOUND,
            404,
        )


class TestBlockLoadingRequiresTheThousandsDigit:
    """The digit that names the run of one thousand numbers carries no default."""

    def test_omitting_the_thousands_digit_is_a_malformed_payload(self):
        """Without the digit the platform cannot even name the block, so the load is
        refused and the rate center stays empty.

        every required field present, every field of the declared type, every enumerated field carrying a declared value

        `thousands_digit`, an integer from 0 through 9 identifying which run of one thousand numbers inside that NXX the block covers

        Design: Corner/entities/block_creation_missing_thousands_digit_returns_invalid_request
        """
        set_clock()
        npa, rate_center = setup_npa_with_rate_center()

        validate_error(
            api_client.create_block(
                {"npa_id": npa["id"], "rate_center_id": rate_center["id"], "nxx_code": "554"},
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        rows = get_success_data(
            api_client.list_rate_center_blocks(rate_center["id"], ADMIN_HEADERS)
        )
        assert rows == []


class TestAreaCodeTypeDefaultsToGeographic:
    """An overlay is minted by relief, never by an omitted field."""

    def test_an_omitted_npa_type_opens_the_code_as_geographic_and_active(self):
        """The code that a client creates without naming a type is an original geographic
        code with an untouched relief posture.

        The optional `npa_type` defaults to `GEOGRAPHIC` and may otherwise be `OVERLAY`

        A new code opens at `status` `ACTIVE`, with `available_block_count` and `total_block_count` both 0, `relief_parent_npa_id` null, `jeopardy_declared_at` null, `permissive_dialing_end_at` null

        Design: Corner/entities/npa_type_defaults_to_geographic_when_omitted
        """
        set_clock()

        npa = validate_success(
            api_client.create_npa(
                {"npa_code": TEST_DEFAULTS["NPA_CODE"], "state_code": "OH"}, ADMIN_HEADERS
            ),
            201,
        )

        assert npa["npa_type"] == "GEOGRAPHIC"
        assert npa["status"] == "ACTIVE"
        assert npa["relief_parent_npa_id"] is None
        assert npa["jeopardy_declared_at"] is None
        assert npa["permissive_dialing_end_at"] is None
        assert npa["available_block_count"] == 0
        assert npa["total_block_count"] == 0


class TestBlockLabelIsComputedFromItsThreeParts:
    """The label is derived from the parent code and the payload, never supplied."""

    def test_the_label_reads_the_area_code_the_nxx_and_the_digit(self):
        """A block loaded under 614 with central office code 554 and digit 3 publishes the
        label the three parts spell out, and opens in the pool untouched.

        the platform computes `block_label` as the concatenation NPA-NXX-D, which must be unique across every block on file

        A block loaded without a holder opens at `POOL_AVAILABLE` and `UNROUTED`, with `holder_carrier_id`, `assigned_at`, `activation_due_at`, `activated_at`, `aging_release_at` and `current_lrn` all null, and `npac_db_version` at 0.

        Design: Corner/entities/block_label_computed_from_npa_code_nxx_and_thousands_digit
        """
        set_clock()
        npa, rate_center = setup_npa_with_rate_center()

        block = validate_success(
            api_client.create_block(
                create_block_payload(npa["id"], rate_center["id"], "554", 3), ADMIN_HEADERS
            ),
            201,
        )

        assert block["block_label"] == "614-554-3"
        assert_block_label(block, TEST_DEFAULTS["NPA_CODE"])
        assert block["allocation_status"] == "POOL_AVAILABLE"
        assert block["routing_status"] == "UNROUTED"
        assert_unheld_block(block)
        assert block["aging_release_at"] is None
        assert block["current_lrn"] is None
        assert block["contaminated_count"] == 0
        assert block["is_pooling_eligible"] is True
        assert_is_pooling_eligible_is_derived(block)
        assert block["npac_db_version"] == 0


class TestIdentityFieldsAreStampedByTheServer:
    """None of the four identity fields is a client input."""

    def test_the_server_mints_the_identity_quartet_and_the_optional_counter_defaults(self):
        """A registration that names only the four required attributes still comes back with
        an identifier, both timestamps, a version and a zeroed optional counter.

        Every persisted resource carries a server-minted `id` that is a UUID string with no type prefix and no embedded meaning; clients never supply it.

        Most resources additionally carry `updated_at`, in the same ISO 8601 UTC format with three fractional digits, and `version`, an integer that starts at 1 when the row is created

        The optional `months_in_operation` records how long the carrier has been providing service; it defaults to 0 when omitted

        The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.

        Design: Corner/entities/carrier_system_fields_are_server_stamped_on_create
        """
        set_clock()

        response = api_client.create_carrier(
            {
                "ocn": "5678",
                "legal_name": "Buckeye Comm Inc",
                "carrier_type": "CLEC",
                "home_state_code": "OH",
            },
            ADMIN_HEADERS,
        )
        carrier = validate_success(response, 201)

        assert is_valid_uuid(carrier["id"])
        assert_mutable_identity(carrier)
        assert is_iso8601_timestamp(carrier["created_at"])
        assert is_iso8601_timestamp(carrier["updated_at"])
        assert carrier["version"] == 1
        assert carrier["months_in_operation"] == 0

        meta = response.json()["meta"]
        assert meta["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(meta["api_request_timestamp"])


class TestCarrierTypeIsAClosedEnumeration:
    """Four service categories exist and nothing else is accepted."""

    def test_a_service_category_outside_the_four_is_refused(self):
        """A plausible-looking but undeclared category is a malformed payload, and nothing
        is written.

        `carrier_type`, the service category, which must be one of `ILEC`, `CLEC`, `WIRELESS` or `VOIP_INTERCONNECTED`

        every required field present, every field of the declared type, every enumerated field carrying a declared value

        Design: Corner/entities/carrier_type_invalid_enum_returns_invalid_request
        """
        set_clock()

        validate_error(
            api_client.create_carrier(
                {
                    "ocn": "1234",
                    "legal_name": "Acme Telecom LLC",
                    "carrier_type": "MOBILE",
                    "home_state_code": "OH",
                },
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        _rows, meta = validate_paginated(api_client.list_carriers(ADMIN_HEADERS))
        assert meta["total_count"] == 0


class TestRequestedBlockCountIsBoundedAtTen:
    """Payload shape is tested long before any business gate speaks."""

    def test_an_ask_of_eleven_blocks_is_malformed_rather_than_ineligible(self):
        """The applicant is ineligible and has filed no utilization report, yet the refusal
        names neither of those grounds because the shape check runs first.

        `requested_block_count` states how many thousand-blocks the carrier is asking for and must be between 1 and 10 inclusive.

        Implementations must evaluate in this order rather than returning whichever check happens to run first, because the choice of error code is observable.

        Design: Corner/entities/allocation_request_block_count_above_ten_returns_invalid_request
        """
        set_clock()
        carrier = register_carrier("A")
        _npa, rate_center = setup_npa_with_rate_center()
        assert read_carrier(carrier["id"])["eligibility_status"] == "INELIGIBLE"

        error = validate_error(
            api_client.create_allocation_request(
                {
                    "carrier_id": carrier["id"],
                    "rate_center_id": rate_center["id"],
                    "request_type": "GROWTH",
                    "requested_block_count": 11,
                    "justification": "expansion",
                    "expected_rate_center_version": rate_center_version(rate_center["id"]),
                },
                make_carrier_representative_headers(carrier["id"]),
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )
        assert error["error_id"] != ApiErrorId.ERR_CARRIER_NOT_ELIGIBLE.value
        assert error["error_id"] != ApiErrorId.ERR_UTILIZATION_FILING_REQUIRED.value

        _rows, meta = validate_paginated(
            api_client.list_allocation_requests(
                ADMIN_HEADERS, params={"rate_center_id": rate_center["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert read_rate_center(rate_center["id"])["pending_request_count"] == 0


class TestAFiledCommentIsImmutable:
    """The comment ledger carries identity and nothing that could be revised."""

    def test_a_government_comment_carries_a_weight_but_no_revision_counter(self):
        """A government body's comment is weighted at three, stamped at the logical clock,
        and published without either of the two mutation fields.

        a public comment and a routing record have only `id` and `created_at`. Neither has an `updated_at` field, neither has a `version` field

        The system computes `weight` from the commenter category — 1.0 for a consumer, 1.5 for a business, 2.0 for a carrier and 3.0 for a government body

        Design: Corner/entities/public_comment_is_immutable_and_carries_no_version_field
        """
        set_clock()
        _npa, plan = setup_plan_in_public_comment(comment_window_days=30)

        comment = validate_success(
            api_client.create_public_comment(
                plan["id"],
                create_public_comment_payload(
                    "GOVERNMENT", "SUPPORT_SPLIT",
                    "The county opposes a second code over the same geography.",
                ),
                COMMENTER_HEADERS,
            ),
            201,
        )

        assert comment["weight"] == 3.0
        assert comment["position"] == "SUPPORT_SPLIT"
        assert comment["commenter_type"] == "GOVERNMENT"
        assert comment["submitted_at"] == DEFAULT_CLOCK
        assert "version" not in comment
        assert "updated_at" not in comment
        assert_identity(comment)
        assert_public_comment(comment)

        rows = get_success_data(
            api_client.list_relief_plan_comments(plan["id"], COMMENTER_HEADERS)
        )
        assert len(rows) == 1
        assert rows[0]["id"] == comment["id"]


class TestARateCenterNeedsAnExistingParentCode:
    """A body reference that resolves to nothing is a not-found, not a mismatch."""

    def test_an_unknown_parent_code_is_reported_as_a_missing_area_code(self):
        """The payload also carries a jurisdiction that could not possibly agree with a code
        that does not exist, and the refusal names the missing code.

        Body-borne references are resolved in the order the payload declares them, and the first unresolvable reference reports its own 404 code.

        every foreign key in the body resolves, checked in payload declaration order, else that key's own not-found code

        Design: Corner/entities/rate_center_creation_requires_an_existing_parent_npa
        """
        set_clock()

        error = validate_error(
            api_client.create_rate_center(
                create_rate_center_payload(UNKNOWN_ID), ADMIN_HEADERS
            ),
            ApiErrorId.ERR_NPA_NOT_FOUND,
            404,
        )
        assert error["error_id"] != ApiErrorId.ERR_JURISDICTION_MISMATCH.value

        _rows, meta = validate_paginated(api_client.list_rate_centers(ADMIN_HEADERS))
        assert meta["total_count"] == 0


class TestFilingsAreKeyedOnACarrierAndRateCenterPair:
    """Period uniqueness is per carrier, so two holders may share one period."""

    def test_two_carriers_may_each_hold_one_filing_for_the_same_period(self):
        """The second carrier's report for the same half-year and the same rate center is
        accepted, and the rate-center listing returns both.

        A carrier may hold at most one filing per rate center and reporting period that is not in `REJECTED` status; a second one is refused with `ERR_DUPLICATE_FILING_PERIOD`.

        Filing listings can be narrowed by `carrier_id`, `rate_center_id`, `reporting_period` and `status`.

        A newly created filing sits at `DRAFT` with `submitted_at` null, `amendment_count` at 0 and `audited_utilization_pct` null.

        Design: Corner/entities/utilization_filing_joins_two_carriers_to_one_rate_center
        """
        set_clock()
        carrier_a = create_licensed_carrier("A")
        carrier_b = create_licensed_carrier("B")
        _npa, rate_center = setup_npa_with_rate_center()

        filing_a = create_filing(
            carrier_a, rate_center,
            numbers_assigned=2000, numbers_intermediate=0, numbers_reserved=0,
            numbers_aging=0, numbers_administrative=0,
            blocks_held_at_period_end=3, forecast_quarters=[1800, 1800, 1800, 1800],
        )

        filing_b = validate_success(
            api_client.create_utilization_filing(
                create_utilization_filing_payload(
                    carrier_b["id"], rate_center["id"],
                    numbers_assigned=95, numbers_intermediate=0, numbers_reserved=0,
                    numbers_aging=0, numbers_administrative=0,
                    blocks_held_at_period_end=1, forecast_quarters=[100, 100, 100, 100],
                ),
                make_carrier_representative_headers(carrier_b["id"]),
            ),
            201,
        )

        assert filing_a["reporting_period"] == TEST_DEFAULTS["REPORTING_PERIOD"]
        assert filing_b["reporting_period"] == TEST_DEFAULTS["REPORTING_PERIOD"]
        assert filing_a["carrier_id"] != filing_b["carrier_id"]

        rows, meta = validate_paginated(
            api_client.list_utilization_filings(
                ADMIN_HEADERS, params={"rate_center_id": rate_center["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {filing_a["id"], filing_b["id"]}
        for row in rows:
            assert row["status"] == "DRAFT"
            assert row["submitted_at"] is None
            assert row["amendment_count"] == 0
            assert row["audited_utilization_pct"] is None
