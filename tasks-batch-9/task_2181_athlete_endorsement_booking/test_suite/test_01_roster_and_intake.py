"""Roster registration, brand registration and opportunity intake."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    UNKNOWN_UUIDS,
    assert_athlete,
    assert_opportunity,
    build_deal,
    create_athlete_payload,
    create_opportunity_payload,
    create_term_sheet_payload,
    file_opportunity,
    make_athlete_headers,
    make_brand_rep_headers,
    register_athlete,
    register_brand,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

AGENT = TEST_USERS["talent_agent_headers"]


def test_new_athlete_opens_with_system_defaults(api):
    """PRD 3.1: "A newly rostered athlete opens with roster `status` `ACTIVE`,
    `active_exclusivity_count` 0, `exposure_risk_snapshot_score` 0 and `no_show_count` 0."
    PRD 2.4: "`version` is an integer that starts at 1 when the resource is created
    and increments by 1 on every mutation of that resource; `updated_at` is refreshed
    on the same occasions."

    Design: Corner/entities/athlete_creation_sets_system_defaults
    """
    set_clock()
    response = api.create_athlete(
        create_athlete_payload(home_market="US"), AGENT
    )
    athlete = validate_success(response, 201)
    assert_athlete(athlete)

    assert athlete["status"] == "ACTIVE"
    assert athlete["active_exclusivity_count"] == 0
    assert athlete["exposure_risk_snapshot_score"] == 0
    assert athlete["no_show_count"] == 0
    assert athlete["version"] == 1

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_"), (
        "api_request_id is a server-generated identifier that starts with req_"
    )
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_home_market_defaults_to_us_when_omitted(api):
    """PRD 3.1: "An optional `home_market` code may be supplied; when it is omitted
    the athlete is recorded as belonging to the `US` market, and the value is purely
    informational."

    Design: Corner/entities/athlete_home_market_default_applied_when_omitted
    """
    set_clock()
    athlete = validate_success(
        api.create_athlete(
            create_athlete_payload(
                full_name="Dana Osei",
                sport="TRACK",
                market_tier="NATIONAL",
                base_appearance_rate_cents=250_000,
                commission_pct=0.2,
            ),
            AGENT,
        ),
        201,
    )
    assert athlete["home_market"] == "US"
    assert athlete["market_tier"] == "NATIONAL"


def test_athlete_read_echoes_the_registered_card_rate(api):
    """PRD 3.1: "Registration takes the athlete's `full_name`, their `sport` as free
    text (for example `BASKETBALL`), a `market_tier` of `GLOBAL`, `NATIONAL` or
    `REGIONAL` describing commercial reach, a `base_appearance_rate_cents` card rate
    for a single appearance day expressed in cents and required to be at least 1, and
    a `commission_pct` giving the agency's cut as a fraction — strictly greater than 0
    and at most 0.50."

    Design: Corner/entities/athlete_get_by_id_returns_stored_row
    """
    athlete = register_athlete()

    response = api.get_athlete(athlete["id"], TEST_USERS["compliance_officer_headers"])
    stored = validate_success(response, 200)
    assert response.json()["response_type"] == "object"
    assert_athlete(stored)

    assert stored["id"] == athlete["id"]
    assert stored["base_appearance_rate_cents"] == 400_000
    assert stored["commission_pct"] == pytest.approx(0.15)
    assert stored["sport"] == "BASKETBALL"


def test_unknown_athlete_id_reports_athlete_not_found(api):
    """PRD 2.8: "an athlete id reports `ERR_ATHLETE_NOT_FOUND`, a brand id
    `ERR_BRAND_NOT_FOUND`, an opportunity id `ERR_OPPORTUNITY_NOT_FOUND`, a term-sheet
    id `ERR_TERM_SHEET_NOT_FOUND`, an engagement id `ERR_ENGAGEMENT_NOT_FOUND`, a
    booking id `ERR_BOOKING_NOT_FOUND`, a deliverable id `ERR_DELIVERABLE_NOT_FOUND`,
    a disclosure-record id `ERR_DISCLOSURE_NOT_FOUND`, a production-slot id
    `ERR_SLOT_NOT_FOUND`, a payout-statement id `ERR_PAYOUT_NOT_FOUND` and a
    renewal-option id `ERR_RENEWAL_NOT_FOUND` — all HTTP 404."

    Design: Corner/entities/athlete_get_unknown_id_returns_not_found
    """
    set_clock()
    response = api.get_athlete(UNKNOWN_UUIDS["generic"], AGENT)
    validate_error(response, ApiErrorId.ERR_ATHLETE_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"


def test_every_path_entity_reports_its_own_not_found_code(api):
    """PRD 2.8: "an athlete id reports `ERR_ATHLETE_NOT_FOUND`, a brand id
    `ERR_BRAND_NOT_FOUND`, an opportunity id `ERR_OPPORTUNITY_NOT_FOUND`, a term-sheet
    id `ERR_TERM_SHEET_NOT_FOUND`, an engagement id `ERR_ENGAGEMENT_NOT_FOUND`, a
    booking id `ERR_BOOKING_NOT_FOUND`, a deliverable id `ERR_DELIVERABLE_NOT_FOUND`,
    a disclosure-record id `ERR_DISCLOSURE_NOT_FOUND`, a production-slot id
    `ERR_SLOT_NOT_FOUND`, a payout-statement id `ERR_PAYOUT_NOT_FOUND` and a
    renewal-option id `ERR_RENEWAL_NOT_FOUND` — all HTTP 404."

    Design: Corner/errors/unknown_ids_return_entity_specific_not_found_codes
    """
    athlete = register_athlete()
    athlete_headers = make_athlete_headers(athlete["id"])

    checks = [
        (api.get_brand(UNKNOWN_UUIDS["brand"], AGENT), ApiErrorId.ERR_BRAND_NOT_FOUND),
        (api.get_term_sheet(UNKNOWN_UUIDS["term_sheet"], AGENT), ApiErrorId.ERR_TERM_SHEET_NOT_FOUND),
        (api.get_engagement(UNKNOWN_UUIDS["engagement"], AGENT), ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND),
        (api.get_appearance_booking(UNKNOWN_UUIDS["booking"], AGENT), ApiErrorId.ERR_BOOKING_NOT_FOUND),
        (api.get_deliverable(UNKNOWN_UUIDS["deliverable"], AGENT), ApiErrorId.ERR_DELIVERABLE_NOT_FOUND),
        (
            api.remediate_disclosure_record(
                UNKNOWN_UUIDS["disclosure"],
                {"disclosure_tag": "#ad", "posted_at": "2026-09-19T12:00:00Z"},
                athlete_headers,
            ),
            ApiErrorId.ERR_DISCLOSURE_NOT_FOUND,
        ),
        (api.get_production_slot(UNKNOWN_UUIDS["slot"], AGENT), ApiErrorId.ERR_SLOT_NOT_FOUND),
        (
            api.disburse_payout_statement(
                UNKNOWN_UUIDS["payout"], TEST_USERS["finance_manager_headers"]
            ),
            ApiErrorId.ERR_PAYOUT_NOT_FOUND,
        ),
        (
            api.decide_renewal_option(
                UNKNOWN_UUIDS["renewal"], {"decision": "DECLINE"},
                make_brand_rep_headers(athlete["id"]),
            ),
            ApiErrorId.ERR_RENEWAL_NOT_FOUND,
        ),
    ]
    for response, expected in checks:
        validate_error(response, expected.value, 404)
        assert response.json()["response_type"] == "error"


def test_opportunity_without_planned_shoots_is_invalid(api):
    """PRD 2.8: "Only then is the request body checked for schema validity: required
    fields present, enum values inside their declared member sets, integers
    non-negative where constrained, end instants strictly after start instants, ISO
    dates and datetimes well formed, and `limit` inside 1 to 100. Any of those
    failures yields `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD 3.1: "it declares the planned workload as three counts, each of which may be
    zero: `planned_posts` for social posts, `planned_appearances` for appearance days,
    and `planned_shoots` for studio shoots."

    Design: Corner/entities/opportunity_missing_required_field_returns_invalid_request
    """
    athlete = register_athlete()
    brand = register_brand()

    payload = create_opportunity_payload(athlete["id"], brand["id"])
    payload.pop("planned_shoots")

    response = api.create_opportunity(payload, make_brand_rep_headers(brand["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    rows, _meta = validate_paginated(
        api.list_opportunities(AGENT, params={"athlete_id": athlete["id"]})
    )
    assert rows == [], "a rejected filing creates no opportunity"


def test_opportunity_with_unknown_territory_is_invalid(api):
    """PRD 3.1: "`territory` is `DOMESTIC`, `NORTH_AMERICA` or `GLOBAL`, and
    `usage_rights_tier` is `SOCIAL_ONLY`, `BROADCAST` or `PERPETUAL`."
    PRD 2.8: "Only then is the request body checked for schema validity: required
    fields present, enum values inside their declared member sets, integers
    non-negative where constrained, end instants strictly after start instants, ISO
    dates and datetimes well formed, and `limit` inside 1 to 100. Any of those
    failures yields `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/opportunity_invalid_enum_territory_returns_invalid_request
    """
    athlete = register_athlete()
    brand = register_brand()

    response = api.create_opportunity(
        create_opportunity_payload(athlete["id"], brand["id"], territory="MOON"),
        make_brand_rep_headers(brand["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_opportunity_list_reports_total_count_and_has_more(api):
    """PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside `meta`, where `total_count` is the number of rows matching the filters
    before pagination is applied and `has_more` is true when rows remain beyond the
    current page."
    PRD 3.1: "Opportunities can be listed and filtered by `athlete_id`, by `brand_id`
    and by `status`."

    Design: Corner/entities/opportunity_list_pagination_reports_total_count_and_has_more
    """
    athlete = register_athlete()
    for name, category in (
        ("Volt Hydration", "BEVERAGE"),
        ("Kite Footwear", "FOOTWEAR"),
        ("Gridiron Gaming", "GAMING"),
    ):
        brand = register_brand(name=name, category=category, legal_entity_name=f"{name} Ltd")
        file_opportunity(athlete["id"], brand["id"], exclusivity_category=category)

    first = api.list_opportunities(AGENT, params={"athlete_id": athlete["id"], "limit": 2, "offset": 0})
    rows, meta = validate_paginated(first)
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert first.json()["response_type"] == "array"

    second = api.list_opportunities(AGENT, params={"athlete_id": athlete["id"], "limit": 2, "offset": 2})
    rows, meta = validate_paginated(second)
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert second.json()["response_type"] == "array"


def test_term_sheet_against_unknown_opportunity_is_not_found(api):
    """PRD 2.8: "After the schema check, foreign keys carried *in the request body*
    are resolved — `athlete_id`, `brand_id`, `opportunity_id`, `engagement_id`,
    `booking_id`, `production_slot_id` and `deliverable_id` — checked left to right in
    the order the fields are listed for that endpoint, each reporting its own entity's
    not-found code."

    Design: Corner/entities/term_sheet_requires_existing_opportunity
    """
    set_clock()
    response = api.create_term_sheet(
        create_term_sheet_payload(UNKNOWN_UUIDS["opportunity"]), AGENT
    )
    validate_error(response, ApiErrorId.ERR_OPPORTUNITY_NOT_FOUND.value, 404)


def test_opportunity_body_foreign_keys_resolve_athlete_before_brand(api):
    """PRD 2.8: "After the schema check, foreign keys carried *in the request body*
    are resolved — `athlete_id`, `brand_id`, `opportunity_id`, `engagement_id`,
    `booking_id`, `production_slot_id` and `deliverable_id` — checked left to right in
    the order the fields are listed for that endpoint, each reporting its own entity's
    not-found code."

    Design: Corner/entities/opportunity_body_fk_checked_left_to_right_athlete_first
    """
    set_clock()
    unknown_athlete = UNKNOWN_UUIDS["athlete"]
    unknown_brand = "00000000-0000-4000-8000-000000000003"

    response = api.create_opportunity(
        create_opportunity_payload(unknown_athlete, unknown_brand),
        make_brand_rep_headers(unknown_brand),
    )
    validate_error(response, ApiErrorId.ERR_ATHLETE_NOT_FOUND.value, 404)


def test_term_sheet_on_unscreened_opportunity_is_refused(api):
    """PRD 3.3: "Drafting against an opportunity in any other state — still `INTAKE`,
    already `REJECTED_FIT`, `CONTRACTED` or `CLOSED_LOST` — is refused with
    `ERR_OPPORTUNITY_NOT_SCREENED`."
    PRD 3.1: "A freshly filed opportunity enters `INTAKE`, and its `expected_fee_cents`
    and `brand_fit_score` both remain null until screening runs."

    Design: Corner/validations/term_sheet_on_unscreened_opportunity_returns_not_screened
    """
    deal = build_deal(stage="filed")

    response = api.create_term_sheet(create_term_sheet_payload(deal["opportunity_id"]), AGENT)
    validate_error(response, ApiErrorId.ERR_OPPORTUNITY_NOT_SCREENED.value, 409)

    opportunity = validate_success(api.get_opportunity(deal["opportunity_id"], AGENT))
    assert_opportunity(opportunity)
    assert opportunity["status"] == "INTAKE"
    assert opportunity["brand_fit_score"] is None

    rows, _meta = validate_paginated(
        api.list_term_sheets(AGENT, params={"opportunity_id": deal["opportunity_id"]})
    )
    assert rows == []


def test_request_without_caller_headers_is_unauthenticated(api):
    """PRD 2.1: "If either header is missing, blank, or if `X-User-Role` names a role
    outside the declared set, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."
    PRD 3.1: "A `ComplianceOfficer` replaces an athlete's `status` with `ACTIVE`,
    `SUSPENDED` or `RETIRED`, optionally recording a free-text `reason` alongside the
    change."

    Design: Corner/validations/missing_x_user_role_header_returns_unauthenticated
    """
    athlete = register_athlete()

    response = api.set_athlete_status(
        athlete["id"], {"status": "SUSPENDED"}, TEST_USERS["no_auth_headers"]
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    unchanged = validate_success(api.get_athlete(athlete["id"], AGENT))
    assert unchanged["status"] == "ACTIVE"
