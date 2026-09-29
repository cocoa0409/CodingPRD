"""The reporting institution: registration, the derived filing profile, profile
amendment and the institution-scoped read surface."""

from test_helpers import (
    ApiErrorId,
    DEFAULT_FILING_DEADLINE,
    TEST_DEFAULTS,
    TEST_USERS,
    assert_institution,
    create_application_payload,
    create_institution,
    create_institution_payload,
    create_second_institution,
    make_institution_admin_headers,
    make_loan_officer_headers,
    make_system_admin_headers,
    read_institution,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_registering_a_bank_derives_the_whole_filing_profile(api):
    """PRD §3.1: "Fourth, `partial_exemption_eligible` is true only when the bank
    is volume-exempt and asset-exempt and is not a quarterly filer. Fifth,
    `required_field_count` is set to 26 for a partially exempt institution and to
    48 otherwise. Sixth, `filing_deadline_at` is set to the first of March of the
    year following `activity_year`, at 23:59:59.000 UTC."
    PRD §3.1: "An institution begins life with `filing_posture` of `OPEN` and with
    every record counter at zero: `total_application_count`,
    `pending_record_count`, `reportable_record_count`, `excluded_record_count`,
    `cleared_record_count`, and `open_register_count`."

    Design: Corner/entities/institution_creation_returns_computed_filing_profile
    """
    resp = api.create_institution(create_institution_payload(), make_system_admin_headers())
    data = validate_success(resp, 201)
    assert_institution(data)

    assert data["partial_exemption_eligible"] is False
    assert data["quarterly_filer"] is False
    assert data["required_field_count"] == 48
    assert data["filing_deadline_at"] == DEFAULT_FILING_DEADLINE
    assert data["filing_posture"] == "OPEN"
    assert data["version"] == 1
    assert data["total_application_count"] == 0
    assert data["pending_record_count"] == 0
    assert data["reportable_record_count"] == 0
    assert data["excluded_record_count"] == 0
    assert data["cleared_record_count"] == 0
    assert data["open_register_count"] == 0

    body = resp.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")


def test_reading_one_institution_returns_the_stored_row(api):
    """PRD §4: "GET | `/hmda/institutions/{id}` | Read one institution with all
    derived counters | SystemAdmin, InstitutionAdmin, ComplianceAnalyst,
    ComplianceOfficer, LoanOfficer, Examiner"
    PRD §2.1: "All six roles may read any institution and any register record;
    the read surface is deliberately wide because compliance work is
    cross-functional."

    Design: Corner/entities/institution_retrieval_returns_stored_row
    """
    institution = create_institution()

    data = validate_success(api.get_institution(institution["id"], TEST_USERS["examiner_headers"]))
    assert_institution(data)
    assert data["id"] == institution["id"]
    assert data["lei"] == TEST_DEFAULTS["PRIMARY_LEI"]
    assert data["activity_year"] == 2026


def test_small_lender_below_every_threshold_is_partially_exempt(api):
    """PRD §3.1: "First, the bank is judged *volume-exempt* when its prior-year
    closed-end originations number fewer than 500 **and** its prior-year open-end
    originations number fewer than 500; the comparison is strict, so a prior-year
    count of exactly 500 on either measure removes volume exemption. Second, the
    bank is judged *asset-exempt* when `asset_size_usd_cents` is at most
    1000000000000 cents, that is, ten billion dollars or less. Third,
    `quarterly_filer` is set true when the sum of the two prior-year origination
    counts is at least 60000."

    Design: Corner/calculations/filing_profile_grants_partial_exemption_below_all_thresholds
    """
    payload = create_institution_payload(
        lei=TEST_DEFAULTS["EXEMPT_LEI"],
        name="Willow Creek Community Bank",
        asset_size_usd_cents=500000000000,
        prior_year_closed_end_originations=100,
        prior_year_open_end_originations=50,
    )
    data = validate_success(api.create_institution(payload, make_system_admin_headers()), 201)

    assert data["partial_exemption_eligible"] is True
    assert data["quarterly_filer"] is False
    assert data["required_field_count"] == 26


def test_reusing_a_legal_entity_identifier_is_rejected(api):
    """PRD §3.1: "An `lei` must be unique across every institution the platform
    holds; a second registration reusing one is rejected with
    `ERR_DUPLICATE_LEI`."

    Design: Corner/validations/duplicate_lei_rejected
    """
    create_institution()

    clone = create_institution_payload(
        name="Clone Bank",
        asset_size_usd_cents=100000000000,
        prior_year_closed_end_originations=10,
        prior_year_open_end_originations=5,
    )
    validate_error(
        api.create_institution(clone, make_system_admin_headers()),
        ApiErrorId.ERR_DUPLICATE_LEI.value,
    )


def test_institution_admin_may_not_amend_another_bank(api):
    """PRD §2.1: "If an `InstitutionAdmin` addresses an institution whose `id`
    differs from `X-User-ID`, the request is rejected with
    `ERR_INSTITUTION_SCOPE_VIOLATION` and HTTP 403."

    Design: Corner/validations/institution_admin_cannot_patch_another_institution
    """
    first = create_institution()
    second = create_second_institution()

    validate_error(
        api.patch_institution(
            second["id"], {"name": "Hijacked Name"}, make_institution_admin_headers(first["id"])
        ),
        ApiErrorId.ERR_INSTITUTION_SCOPE_VIOLATION.value,
    )

    unchanged = read_institution(second["id"])
    assert unchanged["name"] == TEST_DEFAULTS["SECONDARY_NAME"]
    assert unchanged["version"] == 1


def test_institution_admin_amends_its_own_profile(api):
    """PRD §3.1: "A bank-side `InstitutionAdmin` may amend the profile, supplying
    any of `name`, `asset_size_usd_cents`, `prior_year_closed_end_originations`,
    or `prior_year_open_end_originations`. The amendment re-derives the entire
    filing profile over the merged row using the same six pinned steps."
    PRD §3.1: "Because `partial_exemption_eligible` may have flipped, and because
    that flag decides how many fields a register record must carry, the amendment
    also re-evaluates the completeness of every register record the institution
    owns, potentially moving records between `PENDING_FIELDS` and `COMPLETE` in
    either direction. The institution's `version` increments by 1."

    Design: Corner/rbac/institution_admin_patches_its_own_institution_successfully
    """
    institution = create_institution()

    data = validate_success(
        api.patch_institution(
            institution["id"],
            {"name": "First Meridian Bank NA", "asset_size_usd_cents": 260000000000},
            make_institution_admin_headers(institution["id"]),
        )
    )
    assert_institution(data)
    assert data["name"] == "First Meridian Bank NA"
    assert data["asset_size_usd_cents"] == 260000000000
    assert data["partial_exemption_eligible"] is False
    assert data["required_field_count"] == 48
    assert data["version"] == 2


def test_pagination_limit_above_the_maximum_is_malformed(api):
    """PRD §2.3: "When `limit` is omitted it defaults to 10; the smallest accepted
    value is 1 and the largest is 100. When `offset` is omitted it defaults to 0,
    and it may not be negative. A `limit` or an `offset` outside these bounds is a
    malformed request and is rejected with `ERR_INVALID_REQUEST` and HTTP 400
    rather than being silently clamped."

    Design: Corner/validations/pagination_limit_above_max_returns_invalid_request
    """
    institution = create_institution()

    validate_error(
        api.list_institution_applications(
            institution["id"], TEST_USERS["compliance_analyst_headers"],
            params={"limit": 101, "offset": 0},
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


def test_register_listing_pages_with_total_count_and_has_more(api):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` inside `meta`, where `total_count` is the size of the full filtered
    result set before the page window is applied and `has_more` is true exactly
    when records remain beyond the current page."

    Design: Corner/entities/application_listing_is_paginated_with_total_count_and_has_more
    """
    institution = create_institution()
    officer = make_loan_officer_headers()
    for extra in (
        {"application_date": "2026-02-10T00:00:00Z"},
        {"application_date": "2026-02-11T00:00:00Z", "loan_type": "FHA",
         "loan_purpose": "REFINANCING", "occupancy_type": "SECOND",
         "loan_amount_cents": 22000000},
        {"application_date": "2026-02-12T00:00:00Z", "application_channel": "INTERNET",
         "loan_type": "VA", "loan_purpose": "HOME_IMPROVEMENT",
         "occupancy_type": "INVESTMENT", "lien_status": "SUBORDINATE_LIEN",
         "loan_amount_cents": 9000000},
    ):
        validate_success(
            api.create_application(
                create_application_payload(institution["id"], **extra), officer
            ),
            201,
        )

    first_page, meta = validate_paginated(
        api.list_institution_applications(
            institution["id"], TEST_USERS["compliance_analyst_headers"],
            params={"limit": 2, "offset": 0},
        )
    )
    assert len(first_page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    second_page, meta2 = validate_paginated(
        api.list_institution_applications(
            institution["id"], TEST_USERS["compliance_analyst_headers"],
            params={"limit": 2, "offset": 2},
        )
    )
    assert len(second_page) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_499_prior_year_originations_keep_the_partial_exemption(api):
    """PRD §3.1: "First, the bank is judged *volume-exempt* when its prior-year
    closed-end originations number fewer than 500 **and** its prior-year open-end
    originations number fewer than 500; the comparison is strict, so a prior-year
    count of exactly 500 on either measure removes volume exemption."
    PRD §3.1: "Fifth, `required_field_count` is set to 26 for a partially exempt
    institution and to 48 otherwise."

    Design: Difficulty/boundary_precision_check/partial_exemption_threshold_499_versus_500_originations
    """
    institution = create_institution()
    assert institution["required_field_count"] == 48

    data = validate_success(
        api.patch_institution(
            institution["id"], {"prior_year_closed_end_originations": 499},
            make_institution_admin_headers(institution["id"]),
        )
    )
    assert data["partial_exemption_eligible"] is True
    assert data["required_field_count"] == 26
    assert data["quarterly_filer"] is False


def test_exactly_500_prior_year_originations_remove_the_partial_exemption(api):
    """PRD §3.1: "First, the bank is judged *volume-exempt* when its prior-year
    closed-end originations number fewer than 500 **and** its prior-year open-end
    originations number fewer than 500; the comparison is strict, so a prior-year
    count of exactly 500 on either measure removes volume exemption."
    PRD §3.1: "Fifth, `required_field_count` is set to 26 for a partially exempt
    institution and to 48 otherwise."

    Design: Difficulty/boundary_precision_check/partial_exemption_threshold_499_versus_500_originations
    """
    institution = create_institution()
    admin = make_institution_admin_headers(institution["id"])

    at_499 = validate_success(
        api.patch_institution(institution["id"], {"prior_year_closed_end_originations": 499}, admin)
    )
    assert at_499["partial_exemption_eligible"] is True

    at_500 = validate_success(
        api.patch_institution(institution["id"], {"prior_year_closed_end_originations": 500}, admin)
    )
    assert at_500["partial_exemption_eligible"] is False, (
        "a prior-year count of exactly 500 removes the volume exemption"
    )
    assert at_500["required_field_count"] == 48
    assert at_500["quarterly_filer"] is False
