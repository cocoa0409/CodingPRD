"""Standing up a program: employers, clinic sites, contracts and their registries."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_employer,
    assert_site,
    create_eligibility_record_payload,
    create_employer_payload,
    create_provider_payload,
    create_reporting_period_payload,
    create_site_payload,
    create_vendor_contract_payload,
    make_employer_admin_headers,
    new_employer,
    new_site,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
MANAGER = TEST_USERS["clinic_manager_headers"]


def test_employer_registration_zeroes_budget_counters():
    """PRD §3.1: "At registration the committed figure is 0, the remaining figure
    equals the full budget, and the program cost to date is 0."
    PRD §3.1: "An optional `tobacco_program_enabled` flag declares whether the
    wellness program includes a tobacco-cessation component; when the caller omits
    it the server stores `false`."
    PRD §3.1: "An employer's `status` is `ACTIVE` from creation and never changes
    through any operation this API exposes."
    PRD §2.4: "`version` is an integer that starts at 1 when the resource is created."

    Design: Corner/entities/employer_creation_returns_all_fields_with_zeroed_budget_counters
    """
    payload = create_employer_payload(
        legal_name="Fresh Co",
        employer_code="FRS",
        annual_total_cost_of_coverage_cents=1200000,
        wellness_budget_cents=250000,
    )
    response = api_client.create_employer(payload, ADMIN)
    employer = validate_success(response, 201)

    assert_employer(employer)
    assert employer["status"] == "ACTIVE"
    assert employer["tobacco_program_enabled"] is False
    assert employer["wellness_budget_committed_cents"] == 0
    assert employer["wellness_budget_remaining_cents"] == 250000
    assert employer["program_cost_to_date_cents"] == 0
    assert employer["version"] == 1


def test_site_creation_defaults_closure_dates_and_slot_counters():
    """PRD §3.1: "Holidays and one-off shutdowns go into `closure_dates`, an array
    of ISO dates on which the site is shut regardless of the weekday pattern; when
    the caller omits it the server stores an empty array."
    PRD §3.1: "for a `NEAR_SITE` clinic that field is normally omitted, which is
    entirely legitimate and stores null."
    PRD §3.1: "Five counters travel with every site and are maintained entirely by
    the server, all starting at 0: `slots_held_count` counts that site's appointments
    currently `BOOKED`, `slots_consumed_count` counts those checked in,
    `slots_no_show_count` counts those marked as no-shows, `slots_released_count`
    counts those cancelled, and `slots_requested_total` counts every appointment ever
    created at the site in any status."

    Design: Corner/entities/site_defaults_closure_dates_to_empty_array_and_zeroes_slot_counters
    """
    new_employer(legal_name="Default Co", employer_code="DEF")
    payload = create_site_payload(
        site_name="DEF Clinic", site_type="NEAR_SITE", daily_slot_capacity=4
    )
    site = validate_success(api_client.create_site(payload, ADMIN), 201)

    assert_site(site)
    assert site["closure_dates"] == []
    assert site["host_employer_id"] is None
    assert site["slots_held_count"] == 0
    assert site["slots_consumed_count"] == 0
    assert site["slots_no_show_count"] == 0
    assert site["slots_released_count"] == 0
    assert site["slots_requested_total"] == 0


def test_site_listing_pages_and_filters_by_host_employer():
    """PRD §3.1: "Sites can be listed and filtered by `host_employer_id` and by
    `site_type`; reading a single site returns its live counters together with the
    `version` a booking must echo back."
    PRD §2.3: "The `meta` object of a list response carries `limit` (the effective
    page size actually applied), `offset` (the effective skip actually applied),
    `total_count` (the number of records matching the filters before paging) and
    `has_more` (true when records matching the filters remain beyond the current
    page, false otherwise)."

    Design: Corner/entities/site_listing_paginates_and_filters_by_host_employer
    """
    employer = new_employer(legal_name="List Co", employer_code="LST")
    new_site(site_name="LST Site A", host_employer_id=employer["id"])
    new_site(site_name="LST Site B", host_employer_id=employer["id"])
    new_site(site_name="Shared Near-Site", site_type="NEAR_SITE")

    paged, meta = validate_paginated(
        api_client.list_sites(ADMIN, params={"limit": 1, "offset": 1})
    )
    assert len(paged) == 1, f"limit 1 must return one site, got {len(paged)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True, (
        "offset 1 + limit 1 of 3 matching sites leaves the third beyond the page"
    )
    assert meta["limit"] == 1
    assert meta["offset"] == 1

    filtered, filtered_meta = validate_paginated(
        api_client.list_sites(ADMIN, params={"host_employer_id": employer["id"]})
    )
    assert filtered_meta["total_count"] == 2
    assert all(row["host_employer_id"] == employer["id"] for row in filtered)

    body = api_client.list_sites(ADMIN).json()
    assert body["response_type"] == "array"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_patch_site_writes_only_supplied_fields_and_bumps_version():
    """PRD §3.1: "A `ProgramAdmin` or a `ClinicManager` may revise a site's
    `open_time_utc`, `close_time_utc`, `operating_weekdays`, `closure_dates` or
    `daily_slot_capacity`; every one of those inputs is optional on that update and
    only the fields actually supplied are written. Any such revision increments the
    site's `version` by one, which by construction invalidates any booking still
    holding the older value."

    Design: Corner/endpoints/patch_site_updates_calendar_and_bumps_version
    """
    employer = new_employer(legal_name="Patch Co", employer_code="PCH")
    site = new_site(site_name="PCH Clinic", host_employer_id=employer["id"])
    before = site["version"]

    updated = validate_success(
        api_client.update_site(
            site["id"], {"daily_slot_capacity": 6, "closure_dates": ["2026-07-03"]}, MANAGER
        )
    )

    assert updated["daily_slot_capacity"] == 6
    assert updated["closure_dates"] == ["2026-07-03"]
    assert updated["open_time_utc"] == "08:00", "open_time_utc was not supplied"
    assert updated["close_time_utc"] == "17:00", "close_time_utc was not supplied"
    assert updated["version"] == before + 1


def test_unknown_participant_id_returns_participant_not_found():
    """PRD §2.6: "Every identifier in the path exists, resolved left to right, and
    then every foreign-key identifier in the body exists. Otherwise the matching 404:
    `ERR_EMPLOYER_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
    `ERR_PARTICIPANT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`,
    `ERR_PERIOD_NOT_FOUND`, or `ERR_RESOURCE_NOT_FOUND` for an `EligibilityRecord`,
    `VendorContract`, `StaffingShift` or `AlternativeStandard` identifier."

    Design: Corner/entities/participant_get_with_unknown_id_not_found
    """
    response = api_client.get_participant(NON_EXISTENT_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_PARTICIPANT_NOT_FOUND.value, 404)


def test_employer_site_and_provider_not_found_codes():
    """PRD §2.6: "Every identifier in the path exists, resolved left to right, and
    then every foreign-key identifier in the body exists. Otherwise the matching 404:
    `ERR_EMPLOYER_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
    `ERR_PARTICIPANT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`,
    `ERR_PERIOD_NOT_FOUND`, or `ERR_RESOURCE_NOT_FOUND` for an `EligibilityRecord`,
    `VendorContract`, `StaffingShift` or `AlternativeStandard` identifier."

    Design: Corner/entities/employer_site_and_provider_ids_not_found_sweep
    """
    period_response = api_client.create_reporting_period(
        create_reporting_period_payload(NON_EXISTENT_UUID), ADMIN
    )
    validate_error(period_response, ApiErrorId.ERR_EMPLOYER_NOT_FOUND.value, 404)

    provider_response = api_client.create_provider(
        create_provider_payload(NON_EXISTENT_UUID, full_name="Ghost"), MANAGER
    )
    validate_error(provider_response, ApiErrorId.ERR_SITE_NOT_FOUND.value, 404)

    read_response = api_client.get_provider(NON_EXISTENT_UUID, MANAGER)
    validate_error(read_response, ApiErrorId.ERR_PROVIDER_NOT_FOUND.value, 404)


def test_appointment_award_and_period_not_found_codes():
    """PRD §2.6: "Every identifier in the path exists, resolved left to right, and
    then every foreign-key identifier in the body exists. Otherwise the matching 404:
    `ERR_EMPLOYER_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
    `ERR_PARTICIPANT_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`,
    `ERR_PERIOD_NOT_FOUND`, or `ERR_RESOURCE_NOT_FOUND` for an `EligibilityRecord`,
    `VendorContract`, `StaffingShift` or `AlternativeStandard` identifier."
    PRD §3.8: "The award collection is not behind the confidentiality wall — an
    incentive is a payroll fact, not a clinical one — and `PayrollProcessor` may read
    it even though it may read almost nothing else."

    Design: Corner/entities/appointment_award_and_period_ids_not_found_sweep
    """
    employer = new_employer(legal_name="NF Co", employer_code="NFC")

    validate_error(
        api_client.get_appointment(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_APPOINTMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.get_incentive_award(
            NON_EXISTENT_UUID, make_employer_admin_headers(employer["id"])
        ),
        ApiErrorId.ERR_AWARD_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.get_reporting_period(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_PERIOD_NOT_FOUND.value,
        404,
    )


def test_eligibility_record_missing_effective_date_rejected():
    """PRD §2.6: "Every required field is present, every value carries the declared
    type, every integer declared non-negative is non-negative, every ISO date and
    every ISO instant parses, and every conditionally-required field is honoured.
    Otherwise `ERR_VALIDATION`, HTTP 400."
    PRD §3.3: "Each row names the `employer_id` it belongs to, the
    `subscriber_external_id` of the contract holder and the `member_external_id` of
    the covered person as the employer's own systems know them, the relationship
    `tier` — `EMPLOYEE`, `SPOUSE`, `DEPENDENT` or `RETIREE` — and the
    `effective_date` on which coverage begins."

    Design: Corner/entities/eligibility_record_missing_required_field_returns_validation
    """
    employer = new_employer(legal_name="Required Co", employer_code="REQ")
    headers = make_employer_admin_headers(employer["id"])

    payload = create_eligibility_record_payload(
        employer["id"], subscriber_external_id="S-X", member_external_id="M-X"
    )
    payload.pop("effective_date")

    validate_error(
        api_client.create_eligibility_record(payload, headers),
        ApiErrorId.ERR_VALIDATION.value,
        400,
    )

    rows, meta = validate_paginated(
        api_client.list_eligibility_records(headers, params={"employer_id": employer["id"]})
    )
    assert meta["total_count"] == 0, "a rejected request must write nothing"
    assert rows == []


def test_vendor_contract_unknown_fee_model_rejected():
    """PRD §2.6: "Every enum-typed field carries a declared member of its
    enumeration — `visit_type`, `site_type`, `fee_model`, `tier`, `coverage_role`,
    `source_type`, `steerage_tier`, `urgency`, `award_type`, `alternative_type`,
    `cancellation_reason`, `decision` and `provider_function`. Otherwise
    `ERR_INVALID_ENUM`, HTTP 400."
    PRD §3.1: "`fee_model` is either `PER_VISIT`, in which case `per_visit_fee_cents`
    prices each billable visit, or `FTE_HOUR`, in which case `fte_hourly_rate_cents`
    prices each staffed hour; both fee fields are supplied at creation whatever the
    model, and the unused one simply does not participate in pricing."

    Design: Corner/entities/vendor_contract_invalid_enum_fee_model_rejected
    """
    employer = new_employer(legal_name="Enum Co", employer_code="ENM")
    site = new_site(site_name="ENM Clinic", host_employer_id=employer["id"])

    payload = create_vendor_contract_payload(
        site["id"], employer["id"], vendor_name="Bad Model LLC", fee_model="PER_HEADCOUNT"
    )
    validate_error(
        api_client.create_vendor_contract(payload, ADMIN),
        ApiErrorId.ERR_INVALID_ENUM.value,
        400,
    )

    _, meta = validate_paginated(
        api_client.list_vendor_contracts(ADMIN, params={"site_id": site["id"]})
    )
    assert meta["total_count"] == 0, "the rejected contract must not exist"
