"""Stored shape: echoed inputs, declared defaults, ignored computed fields and reads."""

from test_helpers import *  # noqa: F401,F403


def test_creating_a_category_echoes_its_fields_and_mints_the_common_ones(api, ops_headers):
    """PRD §2.4: "Every resource carries a server-minted `id`, formatted as a UUID with no
    type prefix, and a `created_at` timestamp expressed as an ISO 8601 UTC instant with three
    fractional digits. Most resources additionally carry `updated_at`, an ISO 8601 UTC
    timestamp refreshed on every change to the resource, and `version`, a system-managed
    integer that starts at 1 and increments by exactly 1 on every mutation of that row"

    Design: Corner/entities/category_created_with_all_declared_fields
    """
    response = api.create_product_category(jersey_category_payload(), ops_headers)
    category = validate_success(response, 201)
    assert response.json()["response_type"] == "object"

    assert category["category_code"] == "JERSEY"
    assert category["display_name"] == "Authentic Jerseys"
    assert category["base_royalty_rate_bps"] == 1200
    assert category["closeout_rate_bps"] == 500
    assert category["mark_usage_class"] == "LEAGUE_CLUB_AND_PLAYER"
    assert category["minimum_guarantee_floor_cents"] == 1000000
    assert category["exclusivity_allowed"] is True
    assert len(category["tier_schedule"]) == 3
    assert category["tier_schedule"][-1]["to_cents"] is None
    assert category["tier_schedule"][-1]["rate_bps"] == 800

    assert_common_fields(category)
    assert category["version"] == 1
    assert category["created_at"] == category["updated_at"]


def test_a_new_licensee_defaults_to_prospect_with_zero_counters(api, ops_headers):
    """PRD §3.2: "On creation `status` is `PROSPECT`, `vendor_compliance_certified` is false,
    `compliance_risk_index` is 0, `risk_index_as_of_quarter` is null,
    `outstanding_recovery_cents` is 0, `agreement_count` is 0 and `suspension_reason` is
    null."

    Design: Corner/entities/licensee_defaults_prospect_status_and_zero_counters
    """
    payload = licensee_payload(
        legal_name="Aperture Sport Group",
        contact_email="ops@aperture.example",
        home_country_code="CA",
    )
    licensee = validate_success(api.create_licensee(payload, ops_headers), 201)

    assert licensee["status"] == "PROSPECT"
    assert licensee["vendor_compliance_certified"] is False
    assert licensee["compliance_risk_index"] == 0
    assert licensee["risk_index_as_of_quarter"] is None
    assert licensee["outstanding_recovery_cents"] == 0
    assert licensee["agreement_count"] == 0
    assert licensee["suspension_reason"] is None
    assert licensee["home_country_code"] == "CA"
    assert licensee["version"] == 1


def test_omitted_category_caps_fall_back_to_their_declared_defaults(api, ops_headers):
    """PRD §3.1: "`closeout_hard_limit_bps` defaults to 4000 and must be at least
    `closeout_cap_pct_bps` and at most 10000; it is the hard limit, and a line reporting
    closeout volume above it is rejected outright." And: "`advance_floor_bps_of_mg`,
    defaulting to 2500 basis points and ranging from 0 to 10000, expresses the minimum
    advance as a share of the agreement's guarantee."

    Design: Corner/entities/category_optional_caps_fall_back_to_declared_defaults
    """
    payload = minimal_category_payload(
        category_code="HEADWEAR",
        display_name="Sideline Headwear",
        mark_usage_class="LEAGUE_ONLY",
    )
    # None of the six optional knobs is supplied.
    for omitted in (
        "closeout_cap_pct_bps",
        "closeout_hard_limit_bps",
        "deduction_cap_pct_bps",
        "deduction_hard_limit_bps",
        "advance_floor_bps_of_mg",
        "central_licensing_default",
    ):
        assert omitted not in payload

    category = validate_success(api.create_product_category(payload, ops_headers), 201)

    assert category["closeout_cap_pct_bps"] == 1500
    assert category["closeout_hard_limit_bps"] == 4000
    assert category["deduction_cap_pct_bps"] == 500
    assert category["deduction_hard_limit_bps"] == 2000
    assert category["advance_floor_bps_of_mg"] == 2500
    assert category["central_licensing_default"] is True
    # The explicitly supplied value still wins over the field's own default.
    assert category["exclusivity_allowed"] is False


def test_money_fields_supplied_on_a_report_creation_are_ignored(api):
    """PRD §2.4: "Fields whose values the server computes or manages are never accepted from
    a client. If a request body carries such a field it is silently ignored and never echoed
    back, and unknown extra fields are likewise ignored rather than rejected."

    Design: Corner/entities/royalty_report_money_fields_input_ignored
    """
    context = setup_licensed_operation(central_licensing_flag=False)
    agreement_id = context["agreement"]["id"]
    lines = simple_report_lines(context["authorization"]["id"], 2500000, units=5000)

    payload = royalty_report_payload(
        agreement_id,
        "2026Q2",
        lines,
        agreement_version(agreement_id),
        royalty_due_cents=999999,
        status="ACCEPTED",
        total_payable_cents=1,
        return_count=7,
    )
    report = validate_success(
        api.create_royalty_report(payload, make_licensee_headers(context["licensee"]["id"])),
        201,
    )

    assert report["status"] == "DRAFT"
    for field in (
        "net_regular_total_cents",
        "closeout_eligible_total_cents",
        "applied_tier_rate_bps",
        "royalty_due_cents",
        "recoupment_applied_cents",
        "cash_due_pre_fee_cents",
        "late_days",
        "late_filing_interest_cents",
        "admin_fee_cents",
        "total_payable_cents",
    ):
        assert report[field] == 0, field
    assert report["return_count"] == 0
    assert report["filed_at"] is None
    assert report["accepted_by_user_id"] is None
    assert report["adjusted_royalty_due_cents"] is None
    # Input fields are still honoured.
    assert report["channel_lines"][0]["gross_sales_cents"] == 2500000


def test_a_supplied_licensee_status_and_risk_index_are_ignored(api, ops_headers):
    """PRD §3.2: "A prospective licensee is created with its registered `legal_name` — between
    1 and 200 characters and unique case-insensitively across licensees — a `contact_email`
    that must contain an at-sign and serves as the royalty-correspondence mailbox, a
    `home_country_code` of exactly two uppercase letters naming the country of incorporation,
    and optionally `vendor_compliance_certified`."

    Design: Corner/entities/licensee_status_and_risk_index_input_ignored
    """
    supplied_id = "11111111-1111-4111-8111-111111111111"
    payload = licensee_payload(
        legal_name="Beacon Merch Works",
        contact_email="ops@beacon.example",
        status="ACTIVE",
        compliance_risk_index=80,
        suspension_reason="none",
        id=supplied_id,
        version=99,
    )
    licensee = validate_success(api.create_licensee(payload, ops_headers), 201)

    assert licensee["status"] == "PROSPECT"
    assert licensee["compliance_risk_index"] == 0
    assert licensee["suspension_reason"] is None
    assert licensee["id"] != supplied_id
    assert is_valid_uuid(licensee["id"])
    assert licensee["version"] == 1
    assert licensee["legal_name"] == "Beacon Merch Works"


def test_reading_an_agreement_that_does_not_exist_returns_not_found(api, finance_headers):
    """PRD §2.8: "Every identifier in the request path resolves to an existing row. Path
    segments are resolved left to right, so a bad parent identifier wins over a bad child
    identifier."

    Design: Corner/entities/get_agreement_with_unknown_id_returns_not_found
    """
    response = api.get_agreement(NON_EXISTENT_UUID, finance_headers)
    validate_error(response, ApiErrorId.AGREEMENT_NOT_FOUND.value, 404)

    body = response.json()
    assert body["response_type"] == "error"
    assert body["meta"]["api_request_id"].startswith("req_")


def test_creating_a_submission_under_an_unknown_agreement_returns_not_found(api, ops_headers):
    """PRD §2.8: "The error is the one matching the unresolved resource:
    `ERR_LICENSEE_NOT_FOUND`, `ERR_CATEGORY_NOT_FOUND`, `ERR_CLUB_NOT_FOUND`,
    `ERR_PLAYER_NOT_FOUND`, `ERR_MARK_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`,
    `ERR_GRANT_NOT_FOUND`, `ERR_SUBMISSION_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`,
    `ERR_REPORT_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_ENFORCEMENT_NOT_FOUND` or
    `ERR_RUN_NOT_FOUND`."

    Design: Corner/entities/create_submission_under_unknown_agreement_returns_not_found
    """
    create_jersey_category()
    mark = create_league_mark()
    licensee = create_active_licensee(legal_name="Dockside Goods")

    payload = product_submission_payload([mark["id"]], product_name="Ghost Jersey")
    response = api.create_product_submission(
        NON_EXISTENT_UUID, payload, make_licensee_headers(licensee["id"])
    )
    validate_error(response, ApiErrorId.AGREEMENT_NOT_FOUND.value, 404)

    _, meta = validate_paginated(api.list_product_submissions(ops_headers))
    assert meta["total_count"] == 0


def test_paging_licensees_reports_the_whole_total_count(api, ops_headers):
    """PRD §2.3: "`limit` is the maximum number of rows to return; it defaults to 10, its
    minimum accepted value is 1 and its maximum is 100." And: "The `meta` object of a list
    response carries `limit`, `offset`, `total_count` and `has_more`."

    Design: Corner/entities/list_licensees_pagination_reports_total_count_and_has_more
    """
    for name in ("Aster Apparel", "Basil Brands", "Cedar Sportswear"):
        create_prospect_licensee(legal_name=name)

    first_rows, first_meta = validate_paginated(
        api.list_licensees(ops_headers, {"limit": 2, "offset": 0})
    )
    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_rows, second_meta = validate_paginated(
        api.list_licensees(ops_headers, {"limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2

    first_ids = {row["id"] for row in first_rows}
    second_ids = {row["id"] for row in second_rows}
    assert not first_ids & second_ids
    assert len(first_ids | second_ids) == 3


def test_reading_a_report_returns_its_channel_lines_as_stored(api):
    """PRD §3.7: "`channel_lines` holds between one and six entries, one per distribution
    channel with no repeated `channel_class`, and each entry carries the line's
    `channel_class`, the `retailer_authorization_id` the sales were booked through,
    `gross_sales_cents`, a `units` count of at least 1, `closeout_sales_cents` and
    `deductions_cents`."

    Design: Corner/entities/get_royalty_report_returns_stored_channel_lines
    """
    context = setup_licensed_operation(closeout_allowed=True, central_licensing_flag=False)
    licensee_id = context["licensee"]["id"]
    lines = simple_report_lines(
        context["authorization"]["id"],
        2000000,
        units=4000,
        closeout_sales_cents=200000,
        deductions_cents=50000,
    )
    created = create_report(context["agreement"]["id"], "2026Q2", lines, licensee_id)

    fetched = validate_success(
        api.get_royalty_report(created["id"], make_licensee_headers(licensee_id)), 200
    )

    assert fetched["id"] == created["id"]
    assert fetched["status"] == "DRAFT"
    assert fetched["period_quarter"] == "2026Q2"
    assert fetched["agreement_id"] == context["agreement"]["id"]
    assert len(fetched["channel_lines"]) == 1
    stored = fetched["channel_lines"][0]
    assert stored["channel_class"] == "DEPARTMENT"
    assert stored["gross_sales_cents"] == 2000000
    assert stored["closeout_sales_cents"] == 200000
    assert stored["deductions_cents"] == 50000
    assert stored["units"] == 4000
    assert fetched["royalty_due_cents"] == 0
    assert fetched["version"] == 1


def test_drafting_an_agreement_without_a_guarantee_is_a_shape_error(api, ops_headers):
    """PRD §2.8: "Every field the endpoint declares as required is present and carries the
    declared JSON type — otherwise `ERR_VALIDATION`."

    Design: Corner/entities/create_agreement_missing_minimum_guarantee_rejected
    """
    category = create_jersey_category()
    licensee = create_active_licensee(legal_name="Gateway Brands")

    payload = agreement_payload(licensee["id"], category["id"], required_advance_cents=250000)
    del payload["minimum_guarantee_cents"]

    response = api.create_agreement(payload, ops_headers)
    # The shape rule answers first, not the guarantee-floor rule.
    validate_error(response, ApiErrorId.VALIDATION.value, 422)

    _, meta = validate_paginated(
        api.list_agreements(ops_headers, {"licensee_id": licensee["id"]})
    )
    assert meta["total_count"] == 0
    assert get_licensee(licensee["id"])["agreement_count"] == 0


def test_a_category_with_an_unknown_mark_usage_class_is_rejected(api, ops_headers):
    """PRD §2.8: "Every enumeration-typed field carries a value from its declared set, with
    casing significant — otherwise `ERR_VALIDATION`."

    Design: Corner/entities/create_category_with_unknown_mark_usage_class_rejected
    """
    payload = minimal_category_payload(
        base_royalty_rate_bps=900,
        tier_schedule=[{"from_cents": 0, "to_cents": None, "rate_bps": 900}],
        closeout_rate_bps=300,
        exclusivity_allowed=True,
        minimum_guarantee_floor_cents=200000,
        mark_usage_class="EVERYTHING",
    )
    response = api.create_product_category(payload, ops_headers)
    validate_error(response, ApiErrorId.VALIDATION.value, 422)

    _, meta = validate_paginated(api.list_product_categories(ops_headers))
    assert meta["total_count"] == 0


def test_a_sample_review_is_immutable_and_exposes_no_version(api, compliance_headers):
    """PRD §2.4: "Two record types are immutable once written and therefore carry only `id`
    and `created_at`: a `SampleReview`, which is the permanent evidence of one physical
    inspection, and a `ClubDistribution`, which is the permanent evidence of one club's
    allocation from one distribution run."

    Design: Corner/entities/sample_review_is_immutable_with_no_version_field
    """
    context = setup_submission_awaiting_sample()
    submission_id = context["submission"]["id"]

    created = validate_success(
        api.create_sample_review(
            submission_id,
            sample_review_payload("FAIL", ["MARK_DISTORTION"], note="Shield outline stretched"),
            compliance_headers,
        ),
        201,
    )
    assert created["sample_round"] == 1
    assert created["verdict"] == "FAIL"
    assert created["reviewer_user_id"] == "u_mco_1"
    assert created["occurrence_quarter"] == "2026Q3"
    assert created["submission_id"] == submission_id

    fetched = validate_success(api.get_sample_review(created["id"], compliance_headers), 200)
    assert_immutable_record_fields(fetched)

    _, meta = validate_paginated(
        api.list_sample_reviews(compliance_headers, {"submission_id": submission_id})
    )
    assert meta["total_count"] == 1
