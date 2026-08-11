"""Agencies, ORIs, service types and applicants: registration, derivation, listing."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_agency,
    assert_applicant,
    assert_authority_profile,
    assert_ori,
    create_agency_payload,
    create_applicant_payload,
    create_ori_payload,
    create_service_type_payload,
    new_agency,
    new_applicant,
    new_appointment,
    new_ori,
    set_clock,
    setup_registry,
    validate_error,
    validate_paginated,
    validate_success,
)

VA = TEST_USERS["vendor_admin_headers"]
TECH = TEST_USERS["technician_headers"]


def test_new_agency_starts_current_with_zeroed_ledgers(api):
    """PRD 3.1: "Everything else about an agency is derived: `billing_status` starts at `CURRENT`,
    `outstanding_balance_cents` and `max_aging_days` and `mtd_billed_cents` all start at 0, and
    `suspended_at` starts null and holds the logical-clock instant at which the agency's posture
    most recently became `SUSPENDED`."
    PRD 2.4: "`version` — an integer that is 1 when the row is created and increases by exactly 1
    on each request that mutates the row."

    Design: Corner/entities/create_agency_applies_defaults_and_starts_at_version_one
    """
    set_clock("2026-06-01T09:00:00Z")

    payload = create_agency_payload(name="Default Agency")
    payload.pop("payer_regime_default")
    payload.pop("invoice_terms_days")
    agency = validate_success(api.create_agency(payload, VA), 201)

    assert_agency(agency)
    assert agency["billing_status"] == "CURRENT"
    assert agency["outstanding_balance_cents"] == 0
    assert agency["max_aging_days"] == 0
    assert agency["mtd_billed_cents"] == 0
    assert agency["suspended_at"] is None
    assert agency["version"] == 1


def test_agency_optional_settings_default_when_omitted(api):
    """PRD 3.1: "Two optional settings may accompany it: `payer_regime_default`, which is
    `APPLICANT_PAID` when omitted and is otherwise `AGENCY_BILLED` or `FEE_WAIVED`, and
    `invoice_terms_days`, the calendar-day payment terms stamped onto each invoice at issue, which
    is 30 when omitted and must fall between 1 and 90 inclusive."

    Design: Corner/entities/create_agency_applies_defaults_and_starts_at_version_one
    """
    set_clock("2026-06-01T09:00:00Z")

    payload = create_agency_payload(name="Default Agency")
    payload.pop("payer_regime_default")
    payload.pop("invoice_terms_days")
    agency = validate_success(api.create_agency(payload, VA), 201)

    assert agency["payer_regime_default"] == "APPLICANT_PAID"
    assert agency["invoice_terms_days"] == 30


def test_noncriminal_statutory_authority_derives_its_whole_profile(api):
    """PRD 3.1: "- `NONCRIMINAL_STATUTORY` yields `destination_requirement` `STATE_AND_FBI`,
    `dissemination_tier` `FITNESS_CODE_ONLY`, `retention_permitted` true and `rapback_authority` true."
    PRD 3.1: "If a registration request supplies `destination_requirement`, `dissemination_tier`,
    `retention_permitted` or `rapback_authority` directly, the supplied values are ignored and the
    derived ones are stored."

    Design: Corner/entities/ori_derived_fields_computed_and_extra_field_ignored
    """
    set_clock("2026-06-01T09:00:00Z")
    agency = new_agency(name="School District", payer_regime_default="AGENCY_BILLED")

    payload = create_ori_payload(
        agency["id"],
        statutory_authority="NONCRIMINAL_STATUTORY",
        fee_waiver_eligible=True,
        dissemination_tier="FULL_CHR",
    )
    ori = validate_success(api.create_ori(payload, VA), 201)

    assert_ori(ori)
    assert ori["dissemination_tier"] == "FITNESS_CODE_ONLY", "the supplied FULL_CHR is ignored"
    assert ori["destination_requirement"] == "STATE_AND_FBI"
    assert ori["retention_permitted"] is True
    assert ori["rapback_authority"] is True
    assert_authority_profile(ori)


def test_new_ori_starts_active_with_an_empty_tcn_ledger(api):
    """PRD 3.1: "An ORI additionally carries `authority_status`, which starts at `ACTIVE`, and two
    ledger counters that both start at 0: `tcn_consumed_count`, the number of transaction control
    numbers this ORI's transmissions have consumed — one per destination per allocating
    transmission — and `tcn_released_count`, the number released back by purge reconciliation."

    Design: Corner/entities/ori_derived_fields_computed_and_extra_field_ignored
    """
    set_clock("2026-06-01T09:00:00Z")
    agency = new_agency(name="School District")

    ori = validate_success(
        api.create_ori(create_ori_payload(agency["id"], statutory_authority="NONCRIMINAL_STATUTORY"), VA),
        201,
    )

    assert ori["authority_status"] == "ACTIVE"
    assert ori["tcn_consumed_count"] == 0
    assert ori["tcn_released_count"] == 0


def test_unknown_statutory_authority_is_an_enum_violation(api):
    """PRD 2.9 rung 6: "Exactly these request fields route here when they carry a value outside
    their declared member set: an agency's `payer_regime_default`; an ORI's `statutory_authority`;
    a service type's `applicant_type`, the members of its `required_document_codes` and the members
    of its `accepted_id_document_types`; a capture site's `site_kind`; an appointment's
    `booking_channel` and its `presented_document_type`; an applicant's `sex` and
    `id_document_type`; a position closure's `exception_code`; a destination result's `destination`
    and `result_code`; a fitness determination's `outcome` and a challenge resolution's
    `amended_outcome`; a challenge resolution's `resolution`; a purge decision's `decision`; a
    rap-back notification's `event_type`; and an ORI authority change's `to_status`. Violations
    raise `ERR_INVALID_ENUM`, HTTP 422."

    Design: Corner/entities/create_ori_with_invalid_enum_authority_is_rejected
    """
    set_clock("2026-06-01T09:00:00Z")
    agency = new_agency()

    response = api.create_ori(
        create_ori_payload(agency["id"], statutory_authority="MILITARY_JUSTICE"), VA
    )

    error = validate_error(response, ApiErrorId.ERR_INVALID_ENUM.value)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value

    rows, meta = validate_paginated(api.list_oris(VA, {"agency_id": agency["id"]}))
    assert meta["total_count"] == 0, "no ORI is created by a rejected registration"
    assert rows == []


def test_ori_authority_cycles_suspended_and_back_to_active(api):
    """PRD 3.1: "A `VendorAdmin` supplies `to_status` naming either `SUSPENDED` or `ACTIVE`; the ORI
    moves `ACTIVE → SUSPENDED` only from `ACTIVE`, and `SUSPENDED → ACTIVE` only from `SUSPENDED`."
    PRD 2.5: "**Suspending or reinstating an ORI's authority** — the ORI row bumps once. The owning
    agency does not bump."

    Design: Corner/state_machines/ori_authority_suspend_then_reinstate_completes_the_cycle
    """
    set_clock("2026-06-01T09:00:00Z")
    agency = new_agency()
    ori = new_ori(agency["id"])
    assert ori["version"] == 1

    suspended = validate_success(api.set_ori_authority_status(ori["id"], "SUSPENDED", VA), 200)
    assert suspended["authority_status"] == "SUSPENDED"
    assert suspended["version"] == 2

    reinstated = validate_success(api.set_ori_authority_status(ori["id"], "ACTIVE", VA), 200)
    assert reinstated["authority_status"] == "ACTIVE"
    assert reinstated["version"] == 3
    assert reinstated["dissemination_tier"] == "FULL_CHR", "the cycle leaves the profile alone"


def test_service_type_without_state_fee_is_a_body_validity_failure(api):
    """PRD 3.1: "It fixes the statutory money through `state_fee_cents` and `federal_fee_cents`,
    each between 0 and 20000 inclusive; the federal component is charged only when the transmission
    actually includes the FBI destination."
    PRD 2.9 rung 5: "Violations raise `ERR_INVALID_REQUEST`, HTTP 400."

    Design: Corner/entities/create_service_type_missing_required_field_returns_invalid_request
    """
    set_clock("2026-06-01T09:00:00Z")
    agency = new_agency()
    ori = new_ori(agency["id"])

    payload = create_service_type_payload(ori["id"])
    payload.pop("state_fee_cents")
    response = api.create_service_type(payload, VA)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _rows, meta = validate_paginated(api.list_service_types(VA, {"ori_id": ori["id"]}))
    assert meta["total_count"] == 0, "a rejected definition creates no service type"


def test_place_of_birth_drives_demographics_complete(api):
    """PRD 3.3: "From those four demographic values the server derives `demographics_complete`,
    which is true exactly when `full_name`, `date_of_birth`, `sex` and `place_of_birth` are all
    present and non-empty, and false otherwise; because `place_of_birth` may be omitted, an
    applicant can be registered, booked, captured and transmitted with incomplete demographics — and
    an administrative rejection from a destination is exactly what cites that omission weeks later."

    Design: Corner/entities/applicant_without_place_of_birth_is_demographically_incomplete
    """
    set_clock("2026-06-01T09:00:00Z")

    payload = create_applicant_payload(full_name="Tess Vega")
    payload.pop("place_of_birth")
    applicant = validate_success(api.create_applicant(payload, TECH), 201)

    assert_applicant(applicant)
    assert applicant["demographics_complete"] is False

    corrected = validate_success(api.patch_applicant(applicant["id"], {"place_of_birth": "CA"}, TECH), 200)
    assert corrected["demographics_complete"] is True
    assert corrected["place_of_birth"] == "CA"


def test_correcting_an_applicant_bumps_it_exactly_once(api):
    """PRD 3.3: "either may correct it afterwards by supplying any of `place_of_birth`,
    `id_document_type` or `id_document_expires_on`; a correction recomputes `demographics_complete`."
    PRD 2.5: "**Correcting an applicant** — the applicant row bumps once. No other row."

    Design: Corner/entities/applicant_without_place_of_birth_is_demographically_incomplete
    """
    set_clock("2026-06-01T09:00:00Z")

    payload = create_applicant_payload(full_name="Tess Vega")
    payload.pop("place_of_birth")
    applicant = validate_success(api.create_applicant(payload, TECH), 201)
    assert applicant["version"] == 1

    corrected = validate_success(api.patch_applicant(applicant["id"], {"place_of_birth": "CA"}, TECH), 200)
    assert corrected["version"] == 2


def test_reading_an_ori_that_was_never_minted_is_a_reference_not_found(api):
    """PRD 2.9 rung 3: "A fingerprint card named in a path that does not exist raises
    `ERR_CARD_NOT_FOUND`; a submission named in a path that does not exist raises
    `ERR_SUBMISSION_NOT_FOUND`; every other missing path resource — agency, ORI, service type,
    capture site, device, device assignment, applicant, appointment, position capture,
    criminal-history response, fitness determination, rap-back subscription, rap-back notification,
    fee assessment or invoice — raises `ERR_REFERENCE_NOT_FOUND`. All three carry HTTP 404."

    Design: Corner/entities/get_ori_with_unknown_id_returns_reference_not_found
    """
    set_clock("2026-06-01T09:00:00Z")

    response = api.get_ori(NON_EXISTENT_UUID, VA)

    validate_error(response, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)
    assert response.json()["response_type"] == "error"


def test_appointment_listing_reports_total_count_and_has_more(api):
    """PRD 2.3: "`total_count` counts the rows that match the request's filters before `limit` and
    `offset` are applied, and `has_more` is true exactly when the sum of `offset` and the number of
    rows actually returned is smaller than `total_count`."

    Design: Corner/entities/list_appointments_returns_pagination_envelope
    """
    world = setup_registry(clock_start="2026-06-01T08:00:00Z", with_device=False)
    applicant = new_applicant(full_name="Sam Toll")
    for start in ("2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z", "2026-06-01T12:00:00Z"):
        new_appointment(
            applicant["id"], world["site"]["id"], world["service_type"]["id"], start
        )

    rows, meta = validate_paginated(
        api.list_appointments(TECH, {"site_id": world["site"]["id"], "limit": 2, "offset": 0})
    )

    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True
    assert len(rows) == 2
    assert all(row["site_id"] == world["site"]["id"] for row in rows)


def test_second_page_of_the_appointment_listing_reports_no_more_rows(api):
    """PRD 2.3: "`limit` defaults to 10 when it is not supplied, has a minimum of 1 and a maximum of
    100. `offset` defaults to 0 and has a minimum of 0; it has no upper bound."
    PRD 2.3: "`total_count` counts the rows that match the request's filters before `limit` and
    `offset` are applied, and `has_more` is true exactly when the sum of `offset` and the number of
    rows actually returned is smaller than `total_count`."

    Design: Corner/entities/list_appointments_returns_pagination_envelope
    """
    world = setup_registry(clock_start="2026-06-01T08:00:00Z", with_device=False)
    applicant = new_applicant(full_name="Sam Toll")
    for start in ("2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z", "2026-06-01T12:00:00Z"):
        new_appointment(applicant["id"], world["site"]["id"], world["service_type"]["id"], start)

    rows, meta = validate_paginated(
        api.list_appointments(TECH, {"site_id": world["site"]["id"], "limit": 2, "offset": 2})
    )

    assert meta["total_count"] == 3
    assert meta["offset"] == 2
    assert len(rows) == 1
    assert meta["has_more"] is False
