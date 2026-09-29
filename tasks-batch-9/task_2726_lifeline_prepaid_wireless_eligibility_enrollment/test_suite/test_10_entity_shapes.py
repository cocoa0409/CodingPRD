"""Entity shapes: creation, retrieval, listing, defaults, computed fields and the graph."""

from test_helpers import (
    NON_EXISTENT_UUID,
    PROGRAM_ADMIN,
    ApiErrorId,
    assert_common_fields,
    assert_household_address,
    assert_instant,
    assert_meta_envelope,
    assert_provider,
    assert_subscriber,
    expected_income_threshold,
    factories as f,
    fixtures as fx,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
CANONICAL_HASH = "1200NMAINST|APT4B|ELPASO|TX|79901"
NO_UNIT_HASH = "1200NMAINST||ELPASO|TX|79901"


def test_carrier_registration_returns_every_field_with_the_ledger_at_zero(api):
    """A full-input registration echoes the inputs and starts all eleven counters at zero.

    PRD: "At registration every derived figure on the carrier starts at zero and
    `audit_hold_flag` starts false."

    Design: Corner/entities/provider_creation_with_all_required_fields_returns_201_and_zeroed_ledger
    """
    fx.set_clock(api, CLOCK)

    carrier = validate_success(
        api.create_provider(
            f.provider_payload(
                name="SafeLink Wireless",
                spin_id="143100001",
                study_area_code="489100",
                licensed_state_codes=["TX", "NM"],
                enrollment_cap=25,
                status="ACTIVE",
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert_provider(carrier)
    assert carrier["name"] == "SafeLink Wireless"
    assert carrier["spin_id"] == "143100001"
    assert carrier["study_area_code"] == "489100"
    assert carrier["licensed_state_codes"] == ["TX", "NM"]
    assert carrier["enrollment_cap"] == 25
    assert carrier["status"] == "ACTIVE"

    for counter in (
        "active_enrollment_count",
        "devices_total_count",
        "devices_in_stock_count",
        "devices_issued_count",
        "devices_reclaim_pending_count",
        "devices_retired_count",
        "open_claim_count",
        "claim_gross_cents",
        "recouped_cents",
        "net_reimbursed_cents",
    ):
        assert carrier[counter] == 0, f"{counter} must start at zero, got {carrier[counter]}"
    assert carrier["audit_hold_flag"] is False
    assert carrier["version"] == 1


def test_reading_a_dwelling_returns_its_stored_row_with_the_computed_hash(api):
    """The read echoes what the write stored, including the cohort and slot figures.

    PRD: "`cohort_address_count` on every dwelling is the number of registered dwellings
    sharing its hash, counting itself, so a dwelling standing alone reports 1."

    Design: Corner/entities/address_retrieval_returns_stored_row_with_computed_hash_and_slot_counters
    """
    fx.set_clock(api, CLOCK)
    created = fx.register_address(
        api,
        address_line1="1200 N Main St",
        unit_designator="Apt 4B",
        city="El Paso",
        state_code="TX",
        postal_code="79901",
    )

    dwelling = validate_success(api.get_address(created["id"], PROGRAM_ADMIN))
    assert_household_address(dwelling)
    assert dwelling["id"] == created["id"]
    assert dwelling["address_hash"] == CANONICAL_HASH
    assert dwelling["status"] == "UNVERIFIED", (
        f"a dwelling alone in its cohort is never flagged, got {dwelling['status']}"
    )
    assert dwelling["cohort_address_count"] == 1
    assert dwelling["max_permitted_benefit_slots"] == 1
    assert dwelling["occupied_benefit_slots"] == 0
    assert dwelling["unit_designator"] == "Apt 4B", "the unit is stored as typed"
    assert dwelling["declared_household_count"] is None
    assert dwelling["independent_household_worksheet_ref"] is None


def test_the_applicant_listing_reports_the_filtered_total_not_the_page_size(api):
    """Two pages over three co-resident applicants, with has_more flipping on the last page.

    PRD: "The `meta` block of a list response carries `limit` (the page size actually
    applied), `offset` (the starting position actually applied), `total_count` (the number of
    rows matching the filters before pagination), and `has_more` (true when rows remain beyond
    the current page)."

    Design: Corner/entities/subscriber_listing_paginates_with_total_count_and_has_more
    """
    fx.set_clock(api, CLOCK)
    address = fx.register_distinct_address(api, 1)
    created = [fx.create_subscriber(api, address["id"]) for _ in range(3)]

    first_rows, first_meta = validate_paginated(
        api.list_subscribers(PROGRAM_ADMIN, {"address_id": address["id"], "limit": 2, "offset": 0})
    )
    assert_meta_envelope(first_meta)
    assert len(first_rows) == 2, f"the page holds two rows, got {len(first_rows)}"
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3, (
        f"the total counts the matching rows, not the page, got {first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True

    second_rows, second_meta = validate_paginated(
        api.list_subscribers(PROGRAM_ADMIN, {"address_id": address["id"], "limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False, "no rows remain beyond the second page"

    paged_ids = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
    assert sorted(paged_ids) == sorted(row["id"] for row in created), (
        "the two pages together cover every applicant exactly once"
    )
    for row in first_rows + second_rows:
        assert_subscriber(row)
        assert row["status"] == "PROSPECT"


def test_an_unallocated_carrier_id_reports_the_carrier_specific_not_found_code(api):
    """A well-formed but unused UUID is a 404 with the entity's own code.

    PRD: "Path existence, resolved outer to inner: for every identifier segment in the path,
    the addressed row must exist, otherwise the entity-specific not-found code for that
    segment: `ERR_PROVIDER_NOT_FOUND`, `ERR_ADDRESS_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`,
    `ERR_ELIGIBILITY_CHECK_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`,
    `ERR_SERVICE_TRANSFER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_AUDIT_SAMPLE_NOT_FOUND` or
    `ERR_CASE_NOT_FOUND`, each with HTTP 404."

    Design: Corner/entities/provider_get_with_unknown_uuid_returns_provider_not_found
    """
    fx.set_clock(api, CLOCK)
    response = api.get_provider(NON_EXISTENT_UUID, PROGRAM_ADMIN)
    validate_error(response, ApiErrorId.PROVIDER_NOT_FOUND.value, 404)


def test_omitting_the_required_household_size_is_a_schema_failure(api):
    """household_size has no default, so leaving it out creates nothing.

    PRD: "Body schema: a required input field missing, of the wrong JSON type, outside a
    declared numeric range, or carrying a value outside a declared enumeration —
    `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/subscriber_creation_missing_required_household_size_returns_invalid_request
    """
    fx.set_clock(api, CLOCK)
    address = fx.register_distinct_address(api, 1)

    payload = f.subscriber_payload(address["id"])
    payload.pop("household_size")
    response = api.create_subscriber(payload, PROGRAM_ADMIN)
    validate_error(response, ApiErrorId.INVALID_REQUEST.value, 422)

    rows, meta = validate_paginated(
        api.list_subscribers(PROGRAM_ADMIN, {"address_id": address["id"]})
    )
    assert meta["total_count"] == 0, "the refused request wrote no applicant row"
    assert rows == []


def test_every_omitted_optional_input_lands_on_its_declared_default(api):
    """Three declared defaults in one chain: carrier status, unit designator and benefit route.

    PRD: "Two further optional inputs describe the qualification route:
    `qualifying_benefit`, naming the federal assistance program the applicant claims
    participation in, which is one of `NONE`, `SNAP`, `MEDICAID`, `SSI`, `FPHA`,
    `VETERANS_PENSION`, `TRIBAL_TANF`, `BIA_GENERAL_ASSISTANCE` and defaults to `NONE`; and
    `tribal_lands_flag`, which defaults to false and, when true, both raises the income
    multiplier of §2.11 and unlocks the Tribal support enhancement of §3.8."

    Design: Corner/entities/subscriber_and_provider_defaults_applied_when_optional_inputs_omitted
    """
    fx.set_clock(api, CLOCK)

    carrier = validate_success(
        api.create_provider(
            f.provider_payload(enrollment_cap=None, status=None), PROGRAM_ADMIN
        ),
        201,
    )
    assert carrier["status"] == "ACTIVE", "an omitted status defaults to ACTIVE"
    assert carrier["enrollment_cap"] == 1000, (
        f"an omitted cap defaults to 1000, got {carrier['enrollment_cap']}"
    )

    dwelling = validate_success(
        api.create_address(
            f.address_payload(
                address_line1="1200 N Main St",
                city="El Paso",
                state_code="TX",
                postal_code="79901",
                include_unit=False,
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert dwelling["unit_designator"] is None, "an omitted unit designator defaults to null"
    assert dwelling["address_hash"] == NO_UNIT_HASH, (
        f"the missing unit normalises to an empty part, got {dwelling['address_hash']}"
    )

    applicant = validate_success(
        api.create_subscriber(
            f.subscriber_payload(
                dwelling["id"], qualifying_benefit=None, tribal_lands_flag=None
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert applicant["qualifying_benefit"] == "NONE"
    assert applicant["tribal_lands_flag"] is False
    assert applicant["eligibility_basis"] == "NONE"
    assert applicant["income_threshold_cents"] == expected_income_threshold(4, False)
    assert applicant["income_threshold_cents"] == 4341600
    assert applicant["status"] == "PROSPECT"
    assert applicant["de_enrollment_count"] == 0


def test_the_identity_fingerprint_is_derived_and_a_client_supplied_one_is_ignored(api):
    """identity_key and the income threshold are computed, never accepted from the body.

    PRD: "The system computes `identity_key`, a duplicate-identity fingerprint formed by
    taking the applicant's name, deleting every character that is not a letter or digit,
    uppercasing what remains, and then appending a vertical bar, the date of birth as
    supplied, another vertical bar, and the four SSN digits."

    Design: Corner/entities/subscriber_identity_key_computed_and_client_input_ignored
    """
    fx.set_clock(api, CLOCK)
    address = fx.register_distinct_address(api, 1)

    applicant = validate_success(
        api.create_subscriber(
            f.subscriber_payload(
                address["id"],
                full_name="Ana Ruiz",
                date_of_birth="1980-04-11",
                last4_ssn="4417",
                household_size=4,
                identity_key="CLIENT-SUPPLIED-KEY",
                income_threshold_cents=1,
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert applicant["identity_key"] == "ANARUIZ|1980-04-11|4417", (
        f"the fingerprint is derived from the three identity facts, got {applicant['identity_key']}"
    )
    assert applicant["identity_key"] != "CLIENT-SUPPLIED-KEY"
    assert applicant["income_threshold_cents"] == 4341600
    assert applicant["income_threshold_cents"] != 1, "the supplied threshold was ignored"


def test_server_minted_system_fields_ignore_the_ids_the_client_sends(api):
    """The id, version and both timestamps are the server's to write.

    PRD: "`version` (integer): starts at 1 when the row is created and increases by exactly
    one on every subsequent mutation."

    Design: Corner/entities/provider_system_fields_generated_and_client_input_ignored
    """
    fx.set_clock(api, CLOCK)

    carrier = validate_success(
        api.create_provider(
            f.provider_payload(
                id="00000000-0000-0000-0000-000000000001",
                version=99,
                created_at="1999-01-01T00:00:00.000Z",
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert_common_fields(carrier)
    assert carrier["id"] != "00000000-0000-0000-0000-000000000001"
    assert is_valid_uuid(carrier["id"]), (
        f"the id is a bare UUID with no type prefix, got {carrier['id']}"
    )
    assert carrier["version"] == 1, f"a fresh row starts at version 1, got {carrier['version']}"
    assert_instant(carrier["created_at"], CLOCK, "created_at")
    assert_instant(carrier["updated_at"], CLOCK, "updated_at")


def test_three_declared_type_constraints_each_surface_as_one_schema_failure(api):
    """A bad enum, an out-of-range household size and a short spin id all fail the same way.

    PRD: "It also carries the household facts the income test needs: `household_size`, an
    integer of at least 1 and at most 12; `annual_income_cents`, the self-reported gross
    annual household income, zero or greater; and optionally `last_3mo_income_cents`, the
    gross household income over the trailing three months, also zero or greater."

    Design: Corner/entities/subscriber_type_constraints_reject_bad_enum_and_out_of_range_household_size
    """
    fx.set_clock(api, CLOCK)
    address = fx.register_distinct_address(api, 1)

    bad_enum = api.create_subscriber(
        f.subscriber_payload(address["id"], qualifying_benefit="FOOD_STAMPS"), PROGRAM_ADMIN
    )
    validate_error(bad_enum, ApiErrorId.INVALID_REQUEST.value, 422)

    out_of_range = api.create_subscriber(
        f.subscriber_payload(address["id"], household_size=13), PROGRAM_ADMIN
    )
    validate_error(out_of_range, ApiErrorId.INVALID_REQUEST.value, 422)

    short_spin = api.create_provider(f.provider_payload(spin_id="14310"), PROGRAM_ADMIN)
    validate_error(short_spin, ApiErrorId.INVALID_REQUEST.value, 422)

    _rows, meta = validate_paginated(
        api.list_subscribers(PROGRAM_ADMIN, {"address_id": address["id"]})
    )
    assert meta["total_count"] == 0, "none of the three refusals wrote a row"


def test_opening_a_check_under_an_unknown_applicant_fails_on_the_path_segment(api):
    """The nested route resolves its parent before it looks at the body at all.

    PRD: "When an applicant's eligibility check is opened, for instance, the applicant is
    resolved before the body is examined at all."

    Design: Corner/entities/eligibility_check_creation_under_unknown_parent_subscriber_not_found
    """
    fx.set_clock(api, CLOCK)

    response = api.create_eligibility_check(
        NON_EXISTENT_UUID,
        f.eligibility_check_payload(claimed_basis="INCOME", proof_document_ref="DOC-Z9"),
        PROGRAM_ADMIN,
    )
    validate_error(response, ApiErrorId.SUBSCRIBER_NOT_FOUND.value, 404)


def test_the_benefit_junction_is_reachable_by_each_of_its_four_parents(api):
    """One enrollment row answers a filter on every one of its four foreign keys.

    PRD: "Benefits can be read individually, with all four dimensions visible at once, and
    listed with filters on `subscriber_id`, `provider_id`, `eligibility_check_id`,
    `certified_address_id` and on any of the four state dimensions independently —
    `benefit_status`, `usage_status`, `recert_status` and `device_status`."

    Design: Corner/entities/enrollment_graph_junction_resolves_all_four_parents_by_filter
    """
    fx.set_clock(api, CLOCK)
    context = fx.active_benefit(api)
    enrollment_id = context["enrollment"]["id"]

    filters = {
        "subscriber_id": context["subscriber"]["id"],
        "provider_id": context["provider"]["id"],
        "eligibility_check_id": context["check"]["id"],
        "certified_address_id": context["address"]["id"],
    }
    for key, value in filters.items():
        rows, meta = validate_paginated(api.list_enrollments(PROGRAM_ADMIN, {key: value}))
        assert meta["total_count"] == 1, (
            f"the filter on {key} must match exactly one benefit, got {meta['total_count']}"
        )
        assert rows[0]["id"] == enrollment_id, f"the filter on {key} returned the wrong row"

    benefit = validate_success(api.get_enrollment(enrollment_id, PROGRAM_ADMIN))
    assert benefit["benefit_status"] == "ACTIVE"
    assert benefit["usage_status"] == "PENDING_FIRST_USE"
    assert benefit["recert_status"] == "NOT_DUE"
    assert benefit["device_status"] == "AWAITING_DEVICE"
