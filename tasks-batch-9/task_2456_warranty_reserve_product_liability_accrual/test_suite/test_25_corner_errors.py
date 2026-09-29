"""Error-catalogue coverage: path-id 404s, body foreign-key 404s and the authentication rung.

PRD §2.9: "When a request violates more than one rule, the response is determined by the first
violated rule in the ordering below, and no later rule is evaluated. Implementations must
honour this ladder exactly."
"""

from test_helpers import (
    ACTUARY_HEADERS,
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    ENGINEER_HEADERS,
    ERR_ACCRUAL_NOT_FOUND,
    ERR_ADEQUACY_REVIEW_NOT_FOUND,
    ERR_CLAIM_OBSERVATION_NOT_FOUND,
    ERR_FAILURE_MODE_NOT_FOUND,
    ERR_FAMILY_NOT_FOUND,
    ERR_FIELD_ACTION_NOT_FOUND,
    ERR_LIABILITY_RESERVE_NOT_FOUND,
    ERR_PERIOD_NOT_FOUND,
    ERR_RECOVERY_NOT_FOUND,
    ERR_REMEDY_OPTION_NOT_FOUND,
    ERR_ROLLFORWARD_NOT_FOUND,
    ERR_SERVICE_CONTRACT_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_VINTAGE_NOT_FOUND,
    create_family,
    create_field_action,
    create_vintage,
    headers_with_unknown_role,
    headers_without_user_id,
    read_field_action,
    validate_error,
    validate_paginated,
)

# A syntactically well-formed UUID that is the id of no row in any table.
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


def test_each_read_route_answers_with_its_own_not_found_code(api):
    """Eleven single-resource reads of the same unknown id give eleven distinct error ids.

    PRD §2.9 rung 4: "Every identifier embedded in the request path resolves to an existing
    row, validated strictly left to right ... The error is the one belonging to the first
    unresolvable segment: `ERR_PERIOD_NOT_FOUND`, `ERR_FAMILY_NOT_FOUND`,
    `ERR_VINTAGE_NOT_FOUND`, `ERR_FAILURE_MODE_NOT_FOUND`, `ERR_CLAIM_OBSERVATION_NOT_FOUND`,
    `ERR_ACCRUAL_NOT_FOUND`, `ERR_ADEQUACY_REVIEW_NOT_FOUND`, `ERR_FIELD_ACTION_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`, `ERR_RECOVERY_NOT_FOUND`,
    `ERR_LIABILITY_RESERVE_NOT_FOUND` or `ERR_ROLLFORWARD_NOT_FOUND` (all HTTP 404)." Each
    caller below holds a role in its endpoint's authorised list, so rungs 1 and 2 pass.

    Design: Corner/errors/corner_every_path_id_lookup_with_an_unknown_uuid_not_found
    """
    validate_error(
        api.get_period(CONTROLLER_HEADERS, UNKNOWN_ID), ERR_PERIOD_NOT_FOUND, expected_status=404
    )
    validate_error(
        api.get_vintage(ANALYST_HEADERS, UNKNOWN_ID), ERR_VINTAGE_NOT_FOUND, expected_status=404
    )
    validate_error(
        api.get_failure_mode(ANALYST_HEADERS, UNKNOWN_ID),
        ERR_FAILURE_MODE_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.get_claim_observation(ANALYST_HEADERS, UNKNOWN_ID),
        ERR_CLAIM_OBSERVATION_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.get_accrual(ANALYST_HEADERS, UNKNOWN_ID), ERR_ACCRUAL_NOT_FOUND, expected_status=404
    )
    validate_error(
        api.get_adequacy_review(ANALYST_HEADERS, UNKNOWN_ID),
        ERR_ADEQUACY_REVIEW_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.get_field_action(ENGINEER_HEADERS, UNKNOWN_ID),
        ERR_FIELD_ACTION_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.get_service_contract(ANALYST_HEADERS, UNKNOWN_ID),
        ERR_SERVICE_CONTRACT_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.get_supplier_recovery(ANALYST_HEADERS, UNKNOWN_ID),
        ERR_RECOVERY_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.get_liability_reserve(ACTUARY_HEADERS, UNKNOWN_ID),
        ERR_LIABILITY_RESERVE_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.get_rollforward(ACTUARY_HEADERS, UNKNOWN_ID),
        ERR_ROLLFORWARD_NOT_FOUND,
        expected_status=404,
    )


def test_a_phantom_body_reference_outranks_the_rules_that_would_follow_it(api):
    """The body foreign key is resolved before the version guard and the eligibility filter.

    PRD §2.9 rung 6: "Every foreign-key identifier supplied in the request body resolves to an
    existing row ... The error is `ERR_PERIOD_NOT_FOUND`, `ERR_FAMILY_NOT_FOUND`,
    `ERR_VINTAGE_NOT_FOUND`, `ERR_FAILURE_MODE_NOT_FOUND`, `ERR_FIELD_ACTION_NOT_FOUND`,
    `ERR_SUPPLIER_NOT_FOUND` or `ERR_REMEDY_OPTION_NOT_FOUND` according to which reference
    failed (all HTTP 404)." That rung precedes rung 9, "`expected_period_version` equals the
    current period `version` ... otherwise `ERR_STALE_PERIOD_VERSION` (HTTP 412)", and rung 29,
    "When `remedy_option_id` is omitted, the server-side selector's eligibility filter yields
    at least one candidate ... otherwise `ERR_NO_ELIGIBLE_REMEDY_OPTION` (HTTP 422)".

    Design: Corner/errors/corner_body_foreign_keys_are_resolved_before_business_rules_not_found
    """
    family = create_family(
        api,
        family_code="FAM-FK",
        name="Foreign Key Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code="FK-MY2024",
        units_shipped=400,
        ship_period_code="2024-Q1",
        warranty_expiry_date="2028-12-31",
    )
    action = create_field_action(
        api,
        family["id"],
        action_code="FA-FK-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-01-31",
        affected_unit_count=400,
    )

    validate_error(
        api.create_accrual_raw(
            ANALYST_HEADERS,
            {
                "period_id": UNKNOWN_ID,
                "vintage_id": vintage["id"],
                "method": "HISTORICAL_RATE",
                "elapsed_exposure_bps": 5000,
                "expected_period_version": 99,
            },
        ),
        ERR_PERIOD_NOT_FOUND,
        expected_status=404,
    )

    validate_error(
        api.create_vintage_raw(
            ANALYST_HEADERS,
            {
                "family_id": UNKNOWN_ID,
                "vintage_code": "FK-PHANTOM",
                "units_shipped": 100,
                "ship_period_code": "2024-Q1",
                "warranty_expiry_date": "2028-12-31",
            },
        ),
        ERR_FAMILY_NOT_FOUND,
        expected_status=404,
    )
    cohorts, _ = validate_paginated(api.list_vintages(ANALYST_HEADERS))
    assert [row["vintage_code"] for row in cohorts] == ["FK-MY2024"]

    validate_error(
        api.select_remedy(
            ENGINEER_HEADERS,
            action["id"],
            expected_field_action_version=action["version"],
            remedy_option_id=UNKNOWN_ID,
        ),
        ERR_REMEDY_OPTION_NOT_FOUND,
        expected_status=404,
    )

    untouched = read_field_action(api, action["id"])
    assert untouched["version"] == 1
    assert untouched["selected_remedy_option_id"] is None
    assert untouched["specific_accrual_cents"] == 0


def test_authentication_is_refused_before_anything_else_is_looked_at(api):
    """An unknown role and a missing principal both stop at 401, writing nothing.

    PRD §2.1: "Every request to the service must carry two headers: `X-User-ID`, identifying
    the acting principal, and `X-User-Role`, naming the role that principal is acting as. If
    either header is absent, or if the value of `X-User-Role` is not one of the six declared
    role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)." The same
    subsection pins the ordering: "These two checks precede every other form of validation in
    the system."

    Design: Corner/errors/corner_missing_or_unknown_role_header_returns_4XX
    """
    creation_payload = {
        "family_code": "FAM-NOAUTH",
        "name": "No Auth Platform",
        "launch_date": "2024-01-01",
        "base_warranty_months": 24,
        "standard_cost_per_claim_cents": 12000,
        "reserve_cap_cents": 15000000,
    }

    validate_error(
        api.get_period(headers_with_unknown_role(), UNKNOWN_ID),
        ERR_UNAUTHENTICATED,
        expected_status=401,
    )
    validate_error(
        api.create_product_family_raw(headers_with_unknown_role(), creation_payload),
        ERR_UNAUTHENTICATED,
        expected_status=401,
    )

    validate_error(
        api.get_period(headers_without_user_id(), UNKNOWN_ID),
        ERR_UNAUTHENTICATED,
        expected_status=401,
    )
    validate_error(
        api.create_product_family_raw(headers_without_user_id(), creation_payload),
        ERR_UNAUTHENTICATED,
        expected_status=401,
    )

    families, meta = validate_paginated(api.list_product_families(ANALYST_HEADERS))
    assert meta["total_count"] == 0
    assert families == []
