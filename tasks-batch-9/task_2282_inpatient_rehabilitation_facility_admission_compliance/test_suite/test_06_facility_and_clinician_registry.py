"""Facility and clinician registration: defaults, uniqueness, listing, retirement."""

from test_helpers import (
    NON_EXISTENT_UUID,
    OFFICER_HEADERS,
    ApiErrorId,
    api_client,
    assert_clinician,
    assert_facility,
    create_clinician_payload,
    create_facility_payload,
    read_facility,
    register_facility,
    set_clock,
    setup_facility_with_staff,
    validate_error,
    validate_paginated,
    validate_success,
)

SETUP_CLOCK = "2026-08-03T08:00:00Z"


def test_facility_registration_starts_derived_clean_with_declared_defaults():
    """Only the four required inputs are supplied, so every default is exercised.

    PRD §3.1: "A newly registered facility starts fully derived-clean: `posture`
    is `OPEN`, `cohort_total_count` and `cohort_qualifying_count` are 0,
    `provisional_compliance_pct` is 0.00, `certified_compliance_pct` is null,
    `settled_payment_cents` is 0, `active_qrp_penalty_pct` is 0.00 with
    `qrp_penalty_effective_at` null, and `version` is 1."

    Design: Corner/entities/facility_create_applies_declared_defaults_and_zeroed_computeds
    """
    set_clock(SETUP_CLOCK)

    response = api_client.create_facility(create_facility_payload(),
                                         OFFICER_HEADERS)

    facility = validate_success(response, expected_status=201)
    assert_facility(facility)
    assert float(facility["compliance_threshold_pct"]) == 60.00
    assert facility["daily_therapy_cap_minutes"] == 300
    assert facility["settled_payment_cents"] == 0
    assert facility["cohort_total_count"] == 0
    assert facility["cohort_qualifying_count"] == 0
    assert float(facility["provisional_compliance_pct"]) == 0.00
    assert facility["certified_compliance_pct"] is None
    assert float(facility["active_qrp_penalty_pct"]) == 0.00
    assert facility["qrp_penalty_effective_at"] is None
    assert facility["posture"] == "OPEN"
    assert facility["version"] == 1


def test_facility_registration_without_a_certification_number_is_rejected():
    """A missing required body field is a malformed request, and nothing persists.

    PRD §2.5: "required body fields present; enum values recognised; timestamps
    ISO 8601 UTC; dates written as `YYYY-MM-DD`"

    Design: Corner/entities/facility_create_without_cms_ccn_rejected
    """
    set_clock(SETUP_CLOCK)
    payload = create_facility_payload()
    payload.pop("cms_ccn")

    response = api_client.create_facility(payload, OFFICER_HEADERS)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    accepted = validate_success(
        api_client.create_facility(create_facility_payload(), OFFICER_HEADERS),
        expected_status=201,
    )
    assert accepted["cms_ccn"] == "100001"


def test_facility_registration_with_an_inverted_review_period_is_rejected():
    """A review period whose end precedes its start is refused as a bad period.

    PRD §3.1: "Both dates are inclusive calendar dates written as `YYYY-MM-DD`,
    and the end may not precede the start; a reversed pair is
    `ERR_INVALID_PERIOD`."

    Design: Corner/entities/facility_create_with_inverted_review_period_rejected
    """
    set_clock(SETUP_CLOCK)

    response = api_client.create_facility(
        create_facility_payload(review_period_start="2026-08-31",
                                review_period_end="2026-08-01"),
        OFFICER_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_PERIOD)


def test_second_facility_reusing_a_certification_number_is_rejected():
    """The six-digit certification number is unique across all facilities.

    PRD §3.1: "its CMS certification number as `cms_ccn` (exactly six digits,
    and unique across all facilities — a repeat is `ERR_CCN_DUPLICATE`)"

    Design: Corner/validations/duplicate_cms_ccn_rejected
    """
    set_clock(SETUP_CLOCK)
    first = register_facility()

    response = api_client.create_facility(
        create_facility_payload(name="Copycat IRF",
                                review_period_start="2026-09-01",
                                review_period_end="2026-09-30"),
        OFFICER_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_CCN_DUPLICATE)
    assert read_facility(first["id"])["name"] == first["name"]


def test_clinician_read_returns_the_stored_registration_record():
    """A registered clinician reads back with its credential, npi and status.

    PRD §3.1: "Clinicians are registered by the same officer against a
    `facility_id`, with a `full_name`, a `credential`, and an `npi` — the
    ten-digit national provider identifier, unique across all clinicians."

    Design: Corner/entities/clinician_get_by_id_returns_stored_record
    """
    env = setup_facility_with_staff(staff=("nurse",))

    response = api_client.get_clinician(env["nurse"]["id"], OFFICER_HEADERS)

    clinician = validate_success(response)
    assert_clinician(clinician)
    assert clinician["full_name"] == "Dana Whitfield"
    assert clinician["credential"] == "NURSE"
    assert clinician["npi"] == "1000000001"
    assert clinician["status"] == "ACTIVE"
    assert clinician["facility_id"] == env["facility_id"]
    assert clinician["version"] == 1


def test_clinician_list_page_reports_the_unpaginated_total_and_more_to_come():
    """Two of three clinicians come back, with the full match count in meta.

    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` is
    the number of records matching the filters before pagination is applied and
    `has_more` indicates whether records remain beyond the returned page."

    Design: Corner/entities/clinician_list_reports_total_count_and_has_more_under_limit
    """
    env = setup_facility_with_staff(staff=("nurse", "physician", "pt"))

    response = api_client.list_clinicians(
        OFFICER_HEADERS,
        params={"facility_id": env["facility_id"], "limit": 2, "offset": 0},
    )

    items, meta = validate_paginated(response)
    assert len(items) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0


def test_clinician_registration_against_an_unknown_facility_is_rejected():
    """An unresolvable body identifier is a not-found, not a validation error.

    PRD §2.10: "Only once every path identifier resolves are body identifiers
    resolved, and any unresolvable body identifier produces the same
    `ERR_NOT_FOUND`."

    Design: Corner/entities/clinician_create_with_unknown_facility_id_rejected
    """
    set_clock(SETUP_CLOCK)
    register_facility()

    response = api_client.create_clinician(
        create_clinician_payload(NON_EXISTENT_UUID), OFFICER_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_NOT_FOUND)


def test_deactivating_a_clinician_retires_them_and_advances_the_version():
    """Retirement is a mutation: the status flips and the version increments.

    PRD §3.1: "The officer may retire a clinician, moving `status` from `ACTIVE`
    to `INACTIVE`, after which the clinician can neither act (§2.1) nor be named
    on new records."

    Design: Corner/state_machines/clinician_deactivate_moves_active_to_inactive
    """
    env = setup_facility_with_staff(staff=("nurse",))

    response = api_client.deactivate_clinician(env["nurse"]["id"],
                                               OFFICER_HEADERS)

    retired = validate_success(response, expected_status=200)
    assert_clinician(retired)
    assert retired["status"] == "INACTIVE"
    assert retired["version"] == 2


def test_nurse_deactivating_an_unknown_clinician_is_refused_on_the_role_first():
    """Role authorisation outranks path resolution, so the role error wins.

    PRD §2.5: "Implementations must evaluate checks in the following fixed
    order, so that an early failure masks every later one; a request that
    violates three rules reports only the highest-ranked violation."

    Design: Corner/validations/deactivate_unknown_clinician_as_nurse_returns_forbidden_role
    """
    env = setup_facility_with_staff(staff=("nurse", "physician"))

    response = api_client.deactivate_clinician(NON_EXISTENT_UUID,
                                               env["nurse_headers"])

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
    _, meta = validate_paginated(api_client.list_clinicians(
        OFFICER_HEADERS, params={"facility_id": env["facility_id"]}
    ))
    assert meta["total_count"] == 2
    nurse = validate_success(
        api_client.get_clinician(env["nurse"]["id"], OFFICER_HEADERS)
    )
    assert nurse["status"] == "ACTIVE"


def test_clinician_list_with_a_limit_above_the_maximum_is_rejected():
    """A limit of 101 falls outside the accepted pagination range.

    PRD §2.3: "A `limit` outside the range 1 through 100, or a negative
    `offset`, is a malformed request and is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/errors/pagination_limit_above_maximum_rejected
    """
    env = setup_facility_with_staff(staff=("nurse",))

    response = api_client.list_clinicians(
        OFFICER_HEADERS, params={"facility_id": env["facility_id"], "limit": 101}
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
