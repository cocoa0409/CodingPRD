"""Registering operators, mine sites and permits, and filing cost estimates."""
import pytest

from test_helpers import (
    PERMIT_REVIEWER,
    PROGRAM_DIRECTOR,
    PUBLIC_PARTICIPANT,
    ApiErrorId,
    api_client as api,
    assert_envelope_meta,
    assert_mine_site,
    assert_money,
    assert_operator,
    assert_permit,
    chain_applied,
    create_estimate_payload,
    create_permit_payload,
    is_valid_uuid,
    make_operator_headers,
    register_mine_site,
    register_operator,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_operator_registration_returns_declared_fields_with_zeroed_ledgers():
    """A newly registered operator begins with `registry_status` of `ACTIVE`,
    `self_bond_status` of `UNTESTED`, and every derived ledger at zero:
    `self_bond_capacity_amount`, `self_bond_exposure_amount`,
    `outstanding_penalty_balance`, and `refund_due_amount` all start at 0, while
    `violation_points_total` and `forfeiture_count` start at 0 as integers.

    Design: Corner/entities/operator_creation_returns_declared_fields_with_zeroed_ledgers
    """
    payload = {
        "legal_name": "Ashfall Mining Corporation",
        "tangible_net_worth": 15000000.00,
        "fixed_assets_in_state": 7000000.00,
        "total_liabilities": 5000000.00,
        "net_income_prior_year": 600000.00,
        "elected_financial_test": "NET_WORTH_TEST",
    }
    response = api.create_operator(payload, PROGRAM_DIRECTOR)
    data = validate_success(response, 201)
    assert_operator(data)

    assert data["legal_name"] == "Ashfall Mining Corporation"
    assert_money(data["tangible_net_worth"], 15000000.00, "tangible_net_worth")
    assert_money(data["fixed_assets_in_state"], 7000000.00, "fixed_assets_in_state")
    assert_money(data["total_liabilities"], 5000000.00, "total_liabilities")
    assert_money(data["net_income_prior_year"], 600000.00, "net_income_prior_year")
    assert data["elected_financial_test"] == "NET_WORTH_TEST"

    assert data["registry_status"] == "ACTIVE", "a new operator is ACTIVE"
    assert data["self_bond_status"] == "UNTESTED", "a new operator is UNTESTED"
    for field in (
        "self_bond_capacity_amount", "self_bond_exposure_amount",
        "outstanding_penalty_balance", "refund_due_amount",
    ):
        assert_money(data[field], 0.00, field)
    assert data["violation_points_total"] == 0, "points start at zero"
    assert data["forfeiture_count"] == 0, "forfeiture count starts at zero"
    assert data["version"] == 1, "version begins at 1 when the row is created"


def test_mine_site_retrieval_returns_stored_and_defaulted_fields():
    """An optional `site_class` may be supplied at creation, choosing between
    `ACTIVE_PERMITTED` and `ABANDONED_LEGACY`; when omitted it defaults to
    `ACTIVE_PERMITTED`. Everything else on a new site starts at its floor:
    `hazard_class` defaults to `H3_MODERATE`.

    Design: Corner/entities/mine_site_retrieval_returns_stored_and_defaulted_fields
    """
    created = validate_success(
        api.create_mine_site(
            {"name": "Ashfall North Pit", "county": "Rosebud", "total_acres": 310.00},
            PROGRAM_DIRECTOR,
        ),
        201,
    )

    data = validate_success(api.get_mine_site(created["id"], PUBLIC_PARTICIPANT))
    assert_mine_site(data)

    assert data["name"] == "Ashfall North Pit"
    assert data["county"] == "Rosebud"
    assert_money(data["total_acres"], 310.00, "total_acres")
    assert data["site_class"] == "ACTIVE_PERMITTED", "site_class defaults to ACTIVE_PERMITTED"
    assert data["hazard_class"] == "H3_MODERATE", "hazard_class defaults to H3_MODERATE"
    assert data["public_safety_score"] == 0
    assert data["water_quality_score"] == 0
    assert_money(data["acres_affected"], 0.00, "acres_affected")
    assert data["funding_status"] == "NOT_APPLICABLE", "funding begins NOT_APPLICABLE"
    assert_money(data["legacy_priority_score"], 0.00, "legacy_priority_score")
    assert_money(data["awarded_funding_amount"], 0.00, "awarded_funding_amount")
    assert_money(data["unfunded_reclamation_need"], 0.00, "unfunded_reclamation_need")


def test_permit_starts_in_application_submitted_with_compliant_posture():
    """A new permit begins with `status` of `APPLICATION_SUBMITTED`,
    `compliance_posture` of `COMPLIANT`, and `bond_basis` of `FULL_PLAN`. The
    three nullable stamps `issued_at`, `denial_reason`, and
    `last_notice_end_date` start as null.

    Design: Corner/state_machines/permit_starts_in_application_submitted_with_compliant_posture
    """
    operator = register_operator(
        legal_name="Fresh Start Mining",
        tangible_net_worth=12000000.00,
        fixed_assets_in_state=6000000.00,
        total_liabilities=4300000.00,
        net_income_prior_year=350000.00,
    )
    site = register_mine_site(name="Fresh Start Pit", county="Grant", total_acres=150.00)

    data = validate_success(
        api.create_permit(
            create_permit_payload(
                site["id"], operator["id"],
                mining_plan_acres=45.00, post_mining_land_use="WILDLIFE_HABITAT",
            ),
            make_operator_headers(operator["id"]),
        ),
        201,
    )
    assert_permit(data)

    assert data["status"] == "APPLICATION_SUBMITTED", "the declared initial status"
    assert data["compliance_posture"] == "COMPLIANT", "the declared initial posture"
    assert data["bond_basis"] == "FULL_PLAN", "bond_basis begins at FULL_PLAN"
    assert data["issued_at"] is None, "issued_at starts null"
    assert data["denial_reason"] is None, "denial_reason starts null"
    assert data["last_notice_end_date"] is None, "last_notice_end_date starts null"
    for field in (
        "disturbed_acres", "reclaimed_acres_credited",
        "phase1_released_acres", "phase2_released_acres", "phase3_released_acres",
    ):
        assert_money(data[field], 0.00, field)


def test_permit_system_fields_are_server_generated_and_client_input_ignored():
    """`id` is a server-minted UUID with no type prefix; clients never supply it.
    `version` is an integer that begins at 1 when the row is created.

    Design: Corner/entities/permit_system_fields_server_generated_client_input_ignored
    """
    operator = register_operator(
        legal_name="Spoofed Fields Mining",
        tangible_net_worth=11000000.00,
        fixed_assets_in_state=5500000.00,
        total_liabilities=4000000.00,
        net_income_prior_year=300000.00,
    )
    site = register_mine_site(
        name="Spoofed Fields Pit", county="Dunn", total_acres=180.00
    )
    spoofed_id = "11111111-1111-1111-1111-111111111111"

    data = validate_success(
        api.create_permit(
            {
                "mine_site_id": site["id"],
                "operator_id": operator["id"],
                "mining_plan_acres": 90.00,
                "post_mining_land_use": "INDUSTRIAL",
                "proposed_start_date": "2026-09-01",
                "id": spoofed_id,
                "version": 47,
                "created_at": "2020-01-01T00:00:00Z",
                "status": "ISSUED",
            },
            make_operator_headers(operator["id"]),
        ),
        201,
    )
    assert_permit(data)

    assert is_valid_uuid(data["id"]), "the server mints the identifier"
    assert data["id"] != spoofed_id, "the client-supplied id must be ignored"
    assert data["version"] == 1, "version begins at 1 regardless of client input"
    assert data["created_at"].startswith("2026-08-01T00:00:00"), (
        f"created_at comes from the logical clock, got {data['created_at']}"
    )
    assert data["status"] == "APPLICATION_SUBMITTED", "status is server-controlled"
    assert data["issued_at"] is None
    assert data["compliance_posture"] == "COMPLIANT"
    assert_money(data["bond_required_amount"], 0.00, "bond_required_amount")
    assert_money(data["bond_held_amount"], 0.00, "bond_held_amount")


def test_permit_listing_paginates_with_total_count_and_has_more():
    """`total_count` is the number of rows matching the filter before pagination
    is applied, and `has_more` is true exactly when rows matching the filter
    remain beyond the returned page.

    Design: Corner/entities/permit_listing_paginates_with_total_count_and_has_more
    """
    operator = register_operator(
        legal_name="Threefold Quarries",
        tangible_net_worth=14000000.00,
        fixed_assets_in_state=7000000.00,
        total_liabilities=5000000.00,
        net_income_prior_year=500000.00,
    )
    headers = make_operator_headers(operator["id"])
    for name, acres in (
        ("Threefold Site One", 40.00),
        ("Threefold Site Two", 50.00),
        ("Threefold Site Three", 60.00),
    ):
        site = register_mine_site(name=name, county="Gallatin", total_acres=200.00)
        validate_success(
            api.create_permit(
                create_permit_payload(
                    site["id"], operator["id"],
                    mining_plan_acres=acres, post_mining_land_use="CROPLAND",
                ),
                headers,
            ),
            201,
        )

    rows, meta = validate_paginated(
        api.list_permits(
            PERMIT_REVIEWER,
            params={"operator_id": operator["id"], "limit": 2, "offset": 0},
        )
    )
    assert len(rows) == 2, f"limit 2 caps the page at two rows, got {len(rows)}"
    assert meta["total_count"] == 3, "three permits match the filter"
    assert meta["has_more"] is True, "one row remains beyond the first page"
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    rows, meta = validate_paginated(
        api.list_permits(
            PERMIT_REVIEWER,
            params={"operator_id": operator["id"], "limit": 2, "offset": 2},
        )
    )
    assert len(rows) == 1, f"the second page holds the remaining row, got {len(rows)}"
    assert meta["total_count"] == 3, "total_count ignores pagination"
    assert meta["has_more"] is False, "nothing remains beyond the last page"
    assert meta["offset"] == 2


def test_permit_read_with_unknown_id_rejected():
    """**Path-id existence.** Any `{id}` in the URL must resolve to a stored row
    of the addressed collection, else that collection's not-found code:
    `ERR_OPERATOR_NOT_FOUND`, `ERR_MINE_SITE_NOT_FOUND`,
    `ERR_INSPECTOR_PROFILE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
    `ERR_ESTIMATE_NOT_FOUND`, `ERR_INSTRUMENT_NOT_FOUND`,
    `ERR_RELEASE_APPLICATION_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`,
    `ERR_VIOLATION_NOTICE_NOT_FOUND`, `ERR_REVISION_NOT_FOUND`, or
    `ERR_PROCEEDING_NOT_FOUND`.

    Design: Corner/entities/permit_get_with_unknown_id_rejected
    """
    unknown = "00000000-0000-0000-0000-0000000000ff"
    response = api.get_permit(unknown, PERMIT_REVIEWER)
    error = validate_error(response, ApiErrorId.ERR_PERMIT_NOT_FOUND, 404)

    body = response.json()
    assert "meta" in body and isinstance(body["meta"].get("api_request_id"), str), (
        "an error response still carries meta.api_request_id"
    )
    assert error["message"].strip(), "the error carries a human-readable message"


def test_permit_creation_with_invalid_post_mining_land_use_rejected():
    """The payload names the `mine_site_id` of the land to be disturbed and the
    `operator_id` of the intended permit holder, and describes the plan through
    `mining_plan_acres` — the approved plan acreage, which must be strictly
    greater than zero — a `post_mining_land_use` designation chosen from
    `CROPLAND`, `FORESTLAND`, `RANGELAND`, `INDUSTRIAL`, `WATER_IMPOUNDMENT`, and
    `WILDLIFE_HABITAT`, and a `proposed_start_date` giving the intended start of
    disturbance as an ISO 8601 UTC instant. **Schema and constraint validity** of
    the request body and query string, else `ERR_INVALID_REQUEST`.

    Design: Corner/entities/permit_creation_invalid_post_mining_land_use_enum_rejected
    """
    operator = register_operator(legal_name="Bad Enum Mining")
    site = register_mine_site(name="Bad Enum Pit", county="Ward", total_acres=170.00)

    response = api.create_permit(
        create_permit_payload(
            site["id"], operator["id"],
            mining_plan_acres=60.00, post_mining_land_use="GOLF_COURSE",
        ),
        make_operator_headers(operator["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 422)

    _, meta = validate_paginated(
        api.list_permits(PERMIT_REVIEWER, params={"operator_id": operator["id"]})
    )
    assert meta["total_count"] == 0, "a rejected application stores no permit row"


def test_permit_creation_with_unknown_mine_site_id_rejected():
    """**Body reference existence.** Every reference carried in a request body
    must resolve to a stored row — `permit_id`, `operator_id`, `mine_site_id`,
    `inspector_id`, `inspection_id`, and `replaces_instrument_id` — and an
    unresolvable reference returns the not-found code of the collection it points
    at, so an unknown `permit_id` yields `ERR_PERMIT_NOT_FOUND` and an unknown
    `replaces_instrument_id` yields `ERR_INSTRUMENT_NOT_FOUND`.

    Design: Corner/entities/permit_creation_with_unknown_mine_site_id_rejected
    """
    operator = register_operator(legal_name="Dangling Reference Mining")

    response = api.create_permit(
        create_permit_payload(
            "00000000-0000-0000-0000-0000000000aa", operator["id"],
            mining_plan_acres=60.00, post_mining_land_use="CROPLAND",
        ),
        make_operator_headers(operator["id"]),
    )
    validate_error(response, ApiErrorId.ERR_MINE_SITE_NOT_FOUND, 404)

    _, meta = validate_paginated(
        api.list_operator_permits(operator["id"], PROGRAM_DIRECTOR)
    )
    assert meta["total_count"] == 0, "the dangling reference created no permit"


def test_estimate_creation_without_direct_cost_per_acre_rejected():
    """The operator files a **reclamation cost estimate** whose payload names the
    `permit_id` it prices, identifies the firm through `estimator_firm` and
    `estimator_license_no`, and supplies the cost basis as
    `estimate_effective_date` — the ISO 8601 UTC date the pricing is effective as
    of, which drives inflation escalation — together with `direct_cost_per_acre`,
    the third-party direct reclamation cost per acre in dollars, which must be
    strictly greater than zero.

    Design: Corner/entities/estimate_creation_missing_direct_cost_per_acre_rejected
    """
    ctx = chain_applied(
        operator_overrides={"legal_name": "Halfform Estimating Client"},
        site_overrides={"name": "Halfform Pit", "county": "Carbon", "total_acres": 250.00},
        mining_plan_acres=120.00,
        permit_overrides={"post_mining_land_use": "RANGELAND"},
    )
    payload = create_estimate_payload(ctx["permit"]["id"])
    payload.pop("direct_cost_per_acre")

    response = api.create_estimate(payload, ctx["operator_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 422)

    _, meta = validate_paginated(
        api.list_permit_estimates(ctx["permit"]["id"], PERMIT_REVIEWER)
    )
    assert meta["total_count"] == 0, "the incomplete filing stored no estimate"

    permit = validate_success(api.get_permit(ctx["permit"]["id"], PERMIT_REVIEWER))
    assert_money(permit["bond_required_amount"], 0.00, "bond_required_amount")
    assert permit["status"] == "APPLICATION_SUBMITTED"


def test_estimate_effective_date_later_than_the_clock_rejected():
    """An `estimate_effective_date` later than the logical clock's current
    instant is nonsense and is rejected with `ERR_ESTIMATE_DATE_IN_FUTURE`.

    Design: Corner/validations/estimate_effective_date_in_future_rejected
    """
    ctx = chain_applied(
        operator_overrides={"legal_name": "Postdated Estimate Mining"},
        site_overrides={"name": "Postdated Pit", "county": "Uinta", "total_acres": 246.00},
    )

    response = api.create_estimate(
        create_estimate_payload(
            ctx["permit"]["id"], estimate_effective_date="2026-09-15"
        ),
        ctx["operator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_ESTIMATE_DATE_IN_FUTURE, 422)

    boundary = validate_success(
        api.create_estimate(
            create_estimate_payload(
                ctx["permit"]["id"], estimate_effective_date="2026-08-01"
            ),
            ctx["operator_headers"],
        ),
        201,
    )
    assert boundary["status"] == "SUBMITTED", (
        "a date equal to the clock is not later than the clock"
    )

    _, meta = validate_paginated(
        api.list_permit_estimates(ctx["permit"]["id"], PERMIT_REVIEWER)
    )
    assert meta["total_count"] == 1, "only the admissible estimate was stored"


@pytest.mark.parametrize(
    "suffix,reader,expected_error",
    [
        ("0001", "operators", ApiErrorId.ERR_OPERATOR_NOT_FOUND),
        ("0002", "inspector-profiles", ApiErrorId.ERR_INSPECTOR_PROFILE_NOT_FOUND),
        ("0003", "reclamation-cost-estimates", ApiErrorId.ERR_ESTIMATE_NOT_FOUND),
        ("0004", "bond-instruments", ApiErrorId.ERR_INSTRUMENT_NOT_FOUND),
        ("0005", "bond-release-applications", ApiErrorId.ERR_RELEASE_APPLICATION_NOT_FOUND),
        ("0006", "inspections", ApiErrorId.ERR_INSPECTION_NOT_FOUND),
        ("0007", "violation-notices", ApiErrorId.ERR_VIOLATION_NOTICE_NOT_FOUND),
        ("0008", "permit-revisions", ApiErrorId.ERR_REVISION_NOT_FOUND),
        ("0009", "forfeiture-proceedings", ApiErrorId.ERR_PROCEEDING_NOT_FOUND),
    ],
)
def test_not_found_codes_are_specific_to_the_addressed_entity(
    suffix, reader, expected_error
):
    """**Path-id existence.** Any `{id}` in the URL must resolve to a stored row
    of the addressed collection, else that collection's not-found code:
    `ERR_OPERATOR_NOT_FOUND`, `ERR_MINE_SITE_NOT_FOUND`,
    `ERR_INSPECTOR_PROFILE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
    `ERR_ESTIMATE_NOT_FOUND`, `ERR_INSTRUMENT_NOT_FOUND`,
    `ERR_RELEASE_APPLICATION_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`,
    `ERR_VIOLATION_NOTICE_NOT_FOUND`, `ERR_REVISION_NOT_FOUND`, or
    `ERR_PROCEEDING_NOT_FOUND`.

    Design: Corner/errors/entity_not_found_codes_are_specific_to_the_addressed_entity
    """
    unknown = f"00000000-0000-0000-0000-00000000{suffix}"
    response = api._request(
        "GET", f"/mining/{reader}/{unknown}", headers=PROGRAM_DIRECTOR
    )
    validate_error(response, expected_error, 404)


def test_request_without_auth_headers_rejected_before_anything_else():
    """If either header is absent or present but empty, the request is rejected
    with `ERR_MISSING_AUTH_HEADERS` (HTTP 401) before anything else about the
    request is examined.

    Design: Corner/errors/request_without_auth_headers_rejected_before_anything_else
    """
    response = api.create_operator({"legal_name": "Headerless Mining"}, {})
    validate_error(response, ApiErrorId.ERR_MISSING_AUTH_HEADERS, 401)

    listing = api.list_operators(PROGRAM_DIRECTOR)
    _, meta = validate_paginated(listing)
    assert meta["total_count"] == 0, (
        "the incomplete body never reached validation, so nothing was stored"
    )
    assert_envelope_meta(listing.json())
