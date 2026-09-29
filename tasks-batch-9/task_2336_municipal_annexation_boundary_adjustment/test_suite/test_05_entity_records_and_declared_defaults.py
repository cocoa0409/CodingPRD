"""Record shape across the annexation registry: what a registration echoes
back, what a statute profile materialises when the state's law leaves a
threshold unstated, which timestamps the server stamps from its own logical
clock, how a filtered parcel listing reports its page arithmetic, and which
identifiers a read or a nested create refuses to resolve.

These tests read the persisted rows rather than the request bodies, so they pin
the boundary between client input and server-owned state: the municipal tax
ledger that only a tax-roll posting may move, the statutory defaults a minimal
profile still yields, the immutable notice that carries no revision stamps at
all, and the payload-shape and identifier-resolution gates that keep malformed
or orphan rows out of the record entirely.
"""
from datetime import datetime

from test_helpers import (
    NON_EXISTENT_UUID,
    assertions,
    constants,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.api_errors import (
    ERR_CASE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_REFERENCE_NOT_FOUND,
)

# A four-parcel territory summing to 100,000,000 cents of assessed value and
# 20.00 acres, which is what the case-level aggregates must read back.
_TERRITORY_PARCEL_VALUES_CENTS = [40000000, 30000000, 20000000, 10000000]
_TERRITORY_ASSESSED_VALUE_CENTS = 100000000
_TERRITORY_ACREAGE = 20.00
_TERRITORY_PARCEL_COUNT = 4

# A clock reading well away from the startup default, so that a petition's
# circulation window can only have come from the clock and not from a constant.
_PETITION_CLOCK = "2026-08-15T12:00:00Z"
_PETITION_CIRCULATION_DAYS = 30
# 30 whole days added to the instant above.
_PETITION_DEADLINE = "2026-09-14T12:00:00Z"

# A back-dated instant and a cascade-only status a client may not choose.
_CLIENT_SUPPLIED_PUBLISHED_AT = "2020-01-01T00:00:00Z"
_CASCADE_ONLY_NOTICE_STATUS = "SUPERSEDED"


def _instant(value: str) -> datetime:
    """Compare timestamps by the instant they denote, so a server rendering
    three fractional digits and one rendering none are both accepted."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _matched_jurisdiction(statute_overrides=None, municipality_overrides=None):
    """A statute payload and a municipality payload whose `state_code` values
    agree, as §3.1 requires of a city registered against a profile."""
    statute = dict(statute_overrides or {})
    statute.setdefault("state_code", factories.unique_state_code())
    municipality = dict(municipality_overrides or {})
    municipality["state_code"] = statute["state_code"]
    return statute, municipality


def _draft_territory(api, parcel_values_cents=None, case_overrides=None):
    """A `DRAFT` case whose territory aggregates have already been refreshed by
    the parcel additions."""
    statute, municipality = _matched_jurisdiction(
        {"authorized_methods": ["INVOLUNTARY_ORDINANCE"], "required_service_types": ["POLICE"]}
    )
    return fixtures.setup_draft_case(
        api,
        statute=statute,
        municipality=municipality,
        case=case_overrides,
        parcel_values_cents=parcel_values_cents or _TERRITORY_PARCEL_VALUES_CENTS,
    )


def _scheduled_hearing_with_adopted_plan(api):
    """A certified territory whose plan of services is `ADOPTED` and whose
    hearing is `SCHEDULED` but not yet noticed — the one state from which a
    clerk may publish statutory notice."""
    statute, municipality = _matched_jurisdiction(
        {"authorized_methods": ["INVOLUNTARY_ORDINANCE"], "required_service_types": ["POLICE"]}
    )
    ctx = fixtures.setup_certified_case(
        api,
        statute=statute,
        municipality=municipality,
        parcel_values_cents=_TERRITORY_PARCEL_VALUES_CENTS,
    )
    fixtures.setup_adopted_plan(api, ctx)
    fixtures.schedule_hearing(api, ctx)
    return ctx


# ==========================================================================
# Registration echoes and the municipal tax ledger
# ==========================================================================
def test_municipality_registration_echoes_its_inputs_and_seeds_a_zero_tax_base(
    api, state_law_admin
):
    """PRD §3.1: "A newly registered city starts with
    `taxable_assessed_value_cents` at 0; that running ledger of assessed value
    on the municipal tax roll rises only when a case posts its tax roll and
    falls only when a posting is reversed by de-annexation."

    Design: Corner/entities/municipality_creation_echoes_inputs_and_starts_with_a_zero_tax_base
    """
    statute, municipality_overrides = _matched_jurisdiction(
        {"authorized_methods": ["INVOLUNTARY_ORDINANCE"]}
    )
    statute_record = fixtures.create_statute(api, **statute)
    payload = factories.municipality_payload(
        statute_record["id"],
        name="Cedar Grove",
        population=40000,
        citywide_annual_service_cost_cents=800000000,
        citywide_population=40000,
        general_fund_millage_rate=10.0,
        corporate_boundary_perimeter_feet=80000,
        **municipality_overrides,
    )

    municipality = get_success_data(api.create_municipality(state_law_admin, payload), 201)

    # §2.5: a fresh resource carries a UUID id, a created_at, an updated_at and
    # a version of exactly 1.
    assertions.assert_revision_fields(municipality, expected_version=1)
    # Every non-monetary input is echoed verbatim.
    assertions.assert_echoes(
        municipality,
        {
            "statute_profile_id": payload["statute_profile_id"],
            "name": payload["name"],
            "state_code": payload["state_code"],
            "population": payload["population"],
            "citywide_annual_service_cost_cents": payload[
                "citywide_annual_service_cost_cents"
            ],
            "citywide_population": payload["citywide_population"],
            "corporate_boundary_perimeter_feet": payload[
                "corporate_boundary_perimeter_feet"
            ],
        },
    )
    # The levy is carried to four decimal places, so compare it numerically.
    assertions.assert_numeric_equals(
        municipality["general_fund_millage_rate"],
        payload["general_fund_millage_rate"],
        "general_fund_millage_rate",
        places=4,
    )
    assert municipality["taxable_assessed_value_cents"] == 0, (
        "a newly registered city's assessed-value ledger starts at 0"
    )
    # The ledger is persisted at 0, not merely absent from the create response.
    stored = fixtures.read_municipality(api, municipality["id"])
    assert stored["taxable_assessed_value_cents"] == 0


def test_municipality_registration_without_a_population_is_rejected(api, state_law_admin):
    """PRD §2.10: "Payload shape: required inputs present, enum values inside
    their declared member sets, numbers inside their declared ranges, dates and
    datetimes well formed ISO 8601, a commitment's `window_end_date` not earlier
    than its `window_start_date`, a hearing's `scheduled_end_at` strictly later
    than its `scheduled_start_at`, and any `ownership_share_pct` greater than 0
    and at most 100 — `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/municipality_creation_missing_required_population_is_rejected
    """
    statute, municipality_overrides = _matched_jurisdiction(
        {"authorized_methods": ["INVOLUNTARY_ORDINANCE"]}
    )
    statute_record = fixtures.create_statute(api, **statute)
    payload = factories.municipality_payload(
        statute_record["id"], name="Cedar Grove", **municipality_overrides
    )
    # `population` is a required input of §3.1 with no declared default, so the
    # city may not be registered without it.
    payload.pop("population")

    validate_error(api.create_municipality(state_law_admin, payload), ERR_INVALID_REQUEST)

    # A rejected registration persists nothing.
    _, meta = validate_paginated(api.list_municipalities(state_law_admin))
    assert meta["total_count"] == 0


# ==========================================================================
# The statute profile's declared defaults
# ==========================================================================
def test_statute_profile_omitted_optionals_take_every_declared_default(
    api, state_law_admin
):
    """PRD §2.6: "The remaining fields are thresholds and windows, all optional
    on creation with the declared default applied when omitted."

    Design: Corner/entities/statute_profile_omitted_optionals_apply_every_declared_default
    """
    payload = {
        "state_code": factories.unique_state_code(),
        "authorized_methods": ["PETITION_MAJORITY", "INVOLUNTARY_ORDINANCE"],
    }

    statute = get_success_data(api.create_statute_profile(state_law_admin, payload), 201)

    # The two required inputs are stored as submitted.
    assertions.assert_echoes(statute, payload)

    # The four flags that switch whole branches of the lifecycle.
    assert statute["boundary_commission_required"] is False
    assert statute["referendum_required_methods"] == []
    assert statute["de_annexation_allowed"] is True
    assert statute["msd_alternative_allowed"] is True

    # Petition support.
    assert statute["signature_basis"] == "ASSESSED_VALUE"
    assertions.assert_numeric_equals(
        statute["signature_threshold_pct"],
        constants.DEFAULT_SIGNATURE_THRESHOLD_PCT,
        "signature_threshold_pct",
        places=2,
    )

    # Written objections.
    assert statute["protest_basis"] == "ASSESSED_VALUE"
    assertions.assert_numeric_equals(
        statute["protest_threshold_pct"],
        constants.DEFAULT_PROTEST_THRESHOLD_PCT,
        "protest_threshold_pct",
        places=2,
    )

    # Territory certification: the contiguity ratio is one of the three ratios
    # carried to four decimal places.
    assertions.assert_numeric_equals(
        statute["contiguity_min_ratio"],
        constants.DEFAULT_CONTIGUITY_MIN_RATIO,
        "contiguity_min_ratio",
        places=4,
    )
    assertions.assert_numeric_equals(
        statute["urban_density_min_units_per_acre"],
        constants.DEFAULT_URBAN_DENSITY_MIN_UNITS_PER_ACRE,
        "urban_density_min_units_per_acre",
        places=2,
    )
    assertions.assert_numeric_equals(
        statute["subdivision_test_min_developed_ratio"],
        constants.DEFAULT_SUBDIVISION_TEST_MIN_DEVELOPED_RATIO,
        "subdivision_test_min_developed_ratio",
        places=2,
    )
    assertions.assert_numeric_equals(
        statute["min_qualification_index"],
        constants.DEFAULT_MIN_QUALIFICATION_INDEX,
        "min_qualification_index",
        places=2,
    )

    # The notice and cooling-off windows.
    assert statute["notice_min_days"] == constants.DEFAULT_NOTICE_MIN_DAYS
    assert (
        statute["hearing_to_ordinance_min_days"]
        == constants.DEFAULT_HEARING_TO_ORDINANCE_MIN_DAYS
    )

    # The plan of services.
    assert statute["required_service_types"] == constants.DEFAULT_REQUIRED_SERVICE_TYPES
    assert (
        statute["police_fire_timeline_max_days"]
        == constants.DEFAULT_POLICE_FIRE_TIMELINE_MAX_DAYS
    )
    assert (
        statute["water_sewer_timeline_max_days"]
        == constants.DEFAULT_WATER_SEWER_TIMELINE_MAX_DAYS
    )

    # The fiscal methodology and the shared-revenue rate.
    assert statute["fiscal_method"] == constants.DEFAULT_FISCAL_METHOD
    assert (
        statute["per_capita_shared_revenue_cents"]
        == constants.DEFAULT_PER_CAPITA_SHARED_REVENUE_CENTS
    )

    # Unwinding: the refund basis, the district's recovery fraction, the
    # admissible effective date and the proration horizon.
    assert statute["de_annexation_refund_basis"] == "DAILY_PRORATION"
    assertions.assert_numeric_equals(
        statute["msd_cost_recovery_pct"],
        constants.DEFAULT_MSD_COST_RECOVERY_PCT,
        "msd_cost_recovery_pct",
        places=2,
    )
    assert statute["effective_date_rule"] == "IMMEDIATE"
    assert statute["fiscal_year_end_month_day"] == "12-31"


# ==========================================================================
# Reading the case back and paging its parcels
# ==========================================================================
def test_annexation_case_read_returns_the_persisted_territory_aggregates(
    api, county_assessor
):
    """PRD §3.2: "`parcel_count` is the number of such parcels,
    `territory_acreage` is the sum of their `acreage` values rounded half up to
    two decimal places, and `territory_assessed_value_cents` is the exact
    integer sum of their `assessed_value_cents`."

    Design: Corner/entities/annexation_case_retrieval_returns_the_stored_case_with_its_aggregates
    """
    ctx = _draft_territory(api)

    # Reads are open to all seven roles, so the county assessor may read the
    # case the planner built.
    case = get_success_data(api.get_annexation_case(county_assessor, ctx["case"]["id"]))

    assert case["status"] == "DRAFT"
    assert case["parcel_count"] == _TERRITORY_PARCEL_COUNT
    assert case["territory_assessed_value_cents"] == _TERRITORY_ASSESSED_VALUE_CENTS
    assertions.assert_numeric_equals(
        case["territory_acreage"], _TERRITORY_ACREAGE, "territory_acreage", places=2
    )
    assert case["municipality_id"] == ctx["municipality"]["id"]
    assert case["case_type"] == "ANNEXATION"


def test_parcel_listing_pages_report_the_whole_filtered_set(api, county_assessor):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`
    and `has_more` inside the `meta` object of the envelope, where `total_count`
    reflects the number of records matching the filters before pagination is
    applied."

    Design: Corner/entities/parcel_listing_paginates_with_total_count_and_has_more
    """
    ctx = _draft_territory(api)
    municipality_id = ctx["municipality"]["id"]
    case_id = ctx["case"]["id"]

    # A second case in the same city whose single parcel must not leak into the
    # filtered pages.
    other_case = fixtures.create_case(
        api,
        municipality_id,
        total_lot_count=1,
        developed_lot_count=1,
        dwelling_units=2,
    )
    other_parcel = fixtures.add_parcel(
        api,
        municipality_id,
        other_case["id"],
        ctx["owners"][0]["id"],
        assessed_value_cents=5000000,
    )

    first_page, first_meta = validate_paginated(
        api.list_parcels(county_assessor, annexation_case_id=case_id, limit=2, offset=0)
    )
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == _TERRITORY_PARCEL_COUNT
    assert first_meta["has_more"] is True
    assert len(first_page) == 2

    second_page, second_meta = validate_paginated(
        api.list_parcels(county_assessor, annexation_case_id=case_id, limit=2, offset=2)
    )
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == _TERRITORY_PARCEL_COUNT
    assert second_meta["has_more"] is False
    assert len(second_page) == 2

    # The two pages together are the whole filtered set, with no repetition and
    # no parcel of the sibling case.
    assertions.assert_id_set(
        list(first_page) + list(second_page), [p["id"] for p in ctx["parcels"]]
    )

    # The filter is what `total_count` counts: one parcel for the sibling case.
    sibling, sibling_meta = validate_paginated(
        api.list_parcels(county_assessor, annexation_case_id=other_case["id"])
    )
    assert sibling_meta["total_count"] == 1
    assertions.assert_id_set(sibling, [other_parcel["id"]])

    # Unfiltered, every parcel of both cases is counted.
    _, all_meta = validate_paginated(api.list_parcels(county_assessor))
    assert all_meta["total_count"] == _TERRITORY_PARCEL_COUNT + 1


# ==========================================================================
# System-stamped timestamps and the immutable notice
# ==========================================================================
def test_petition_circulation_window_is_derived_from_the_clock(api):
    """PRD §3.3: "The petition is created with `sufficiency_status`
    `CIRCULATING`, `circulation_started_at` set to the current logical clock
    reading, and `circulation_deadline_at` set to `circulation_started_at`
    advanced by `circulation_days` days; the case moves to
    `PETITION_CIRCULATING` and its `version` increments."

    Design: Corner/entities/petition_circulation_deadline_is_computed_from_the_clock_and_circulation_days
    """
    statute, municipality = _matched_jurisdiction(
        {"authorized_methods": ["PETITION_MAJORITY"], "required_service_types": ["POLICE"]}
    )
    ctx = fixtures.setup_certified_case(
        api,
        statute=statute,
        municipality=municipality,
        case={"method": "PETITION_MAJORITY"},
        parcel_values_cents=_TERRITORY_PARCEL_VALUES_CENTS,
    )
    # Nothing in the domain reads wall-clock time, so the window can only come
    # from this reading.
    fixtures.set_clock(api, _PETITION_CLOCK)

    petition = fixtures.open_petition(
        api, ctx, circulation_days=_PETITION_CIRCULATION_DAYS
    )

    assert petition["sufficiency_status"] == "CIRCULATING"
    assert _instant(petition["circulation_started_at"]) == _instant(_PETITION_CLOCK)
    assert _instant(petition["circulation_deadline_at"]) == _instant(_PETITION_DEADLINE)
    # The deadline is the start advanced by whole days, not by a month name.
    assert _instant(petition["circulation_deadline_at"]) == _instant(
        assertions.add_days(
            petition["circulation_started_at"], _PETITION_CIRCULATION_DAYS
        )
    )
    assert fixtures.refresh_case(api, ctx)["status"] == "PETITION_CIRCULATING"


def test_notice_publication_stamps_published_at_from_the_clock(api):
    """PRD §3.6: "The notice is created with `notice_status` `PUBLISHED` and
    `published_at` set to the logical clock, and the hearing's
    `notice_published_at` is set to that instant."

    Design: Corner/entities/notice_publication_published_at_is_system_stamped_and_input_ignored
    """
    ctx = _scheduled_hearing_with_adopted_plan(api)
    hearing_id = ctx["hearing"]["id"]

    # A client offering its own `published_at` and the cascade-only
    # `SUPERSEDED` status changes nothing: both fields are the server's.
    notice = get_success_data(
        api.raw_post(
            f"/public-hearings/{hearing_id}/notice-publications",
            {
                "publication_type": "NEWSPAPER",
                "published_at": _CLIENT_SUPPLIED_PUBLISHED_AT,
                "notice_status": _CASCADE_ONLY_NOTICE_STATUS,
            },
            headers=fixtures.clerk(ctx),
        ),
        201,
    )

    assert notice["notice_status"] == "PUBLISHED"
    assert notice["publication_type"] == "NEWSPAPER"
    assert notice["public_hearing_id"] == hearing_id
    # The clock has not been moved, so it still reads its startup value.
    assert _instant(notice["published_at"]) == _instant(constants.CLOCK_STARTUP_UTC)
    assert _instant(notice["published_at"]) != _instant(_CLIENT_SUPPLIED_PUBLISHED_AT)

    hearing = fixtures.read_hearing(api, ctx["municipality"]["id"], hearing_id)
    assert _instant(hearing["notice_published_at"]) == _instant(notice["published_at"])
    assert fixtures.refresh_case(api, ctx)["status"] == "HEARING_NOTICED"


def test_published_notice_carries_no_revision_stamps_on_any_read_channel(api):
    """PRD §2.5: "A published notice is an immutable statutory artifact: it
    carries only `id` and `created_at`. It has no `updated_at` field and no
    `version` field, and there is no update endpoint for it."

    Design: Corner/entities/notice_publication_is_immutable_with_no_update_endpoint_or_version
    """
    ctx = _scheduled_hearing_with_adopted_plan(api)
    hearing_id = ctx["hearing"]["id"]
    clerk = fixtures.clerk(ctx)

    notice = fixtures.publish_notice(api, ctx)

    assert notice["notice_status"] == "PUBLISHED"
    assertions.assert_immutable_notice_shape(notice)

    # The per-hearing listing is how an operator discovers a superseded notice,
    # and it serves the same stamp-free record.
    hearing_notices, hearing_meta = validate_paginated(
        api.list_hearing_notices(clerk, hearing_id)
    )
    assert hearing_meta["total_count"] == 1
    assertions.assert_id_set(hearing_notices, [notice["id"]])
    assertions.assert_immutable_notice_shape(hearing_notices[0])

    # The by-id read is the only other way to reach a notice; there is no write
    # path back to it at all.
    read_back = get_success_data(api.get_notice_publication(clerk, notice["id"]))
    assertions.assert_immutable_notice_shape(read_back)
    assert read_back["notice_status"] == "PUBLISHED"
    assert read_back["public_hearing_id"] == hearing_id

    cross_hearing, cross_meta = validate_paginated(
        api.list_notice_publications(
            clerk, public_hearing_id=hearing_id, notice_status="PUBLISHED"
        )
    )
    assert cross_meta["total_count"] == 1
    assertions.assert_id_set(cross_hearing, [notice["id"]])
    assertions.assert_immutable_notice_shape(cross_hearing[0])


# ==========================================================================
# Payload shape and identifier resolution
# ==========================================================================
def test_case_with_more_developed_lots_than_total_lots_is_rejected(api):
    """PRD §3.2: "Four measurements of the proposed territory are supplied at
    the same time: `shared_boundary_feet`, the length in feet of territory
    boundary shared with the existing corporate boundary (at least 0);
    `total_lot_count`, the number of subdivision lots (at least 0);
    `developed_lot_count`, how many of those carry a permanent structure (at
    least 0 and not more than `total_lot_count`); and `dwelling_units`, the
    number of dwelling units in the territory (at least 0)."

    Design: Corner/entities/annexation_case_with_developed_lots_above_total_lots_is_rejected
    """
    statute, municipality = _matched_jurisdiction(
        {"authorized_methods": ["INVOLUNTARY_ORDINANCE"], "required_service_types": ["POLICE"]}
    )
    ctx = fixtures.setup_jurisdiction(api, statute=statute, municipality=municipality)
    municipality_id = ctx["municipality"]["id"]
    planner = fixtures.planner(ctx)

    # Five developed lots out of four total is outside the declared range, so
    # the subdivision limb could never see a developed-lot ratio above 1.
    payload = factories.annexation_case_payload(
        municipality_id, total_lot_count=4, developed_lot_count=5
    )
    validate_error(api.create_annexation_case(planner, payload), ERR_INVALID_REQUEST)

    _, meta = validate_paginated(
        api.list_annexation_cases(planner, municipality_id=municipality_id)
    )
    assert meta["total_count"] == 0


def test_case_with_a_method_outside_the_declared_member_set_is_rejected(api):
    """PRD §2.10: "Payload shape: required inputs present, enum values inside
    their declared member sets, numbers inside their declared ranges, dates and
    datetimes well formed ISO 8601, a commitment's `window_end_date` not earlier
    than its `window_start_date`, a hearing's `scheduled_end_at` strictly later
    than its `scheduled_start_at`, and any `ownership_share_pct` greater than 0
    and at most 100 — `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/annexation_case_with_developed_lots_above_total_lots_is_rejected
    """
    statute, municipality = _matched_jurisdiction(
        {"authorized_methods": ["INVOLUNTARY_ORDINANCE"], "required_service_types": ["POLICE"]}
    )
    ctx = fixtures.setup_jurisdiction(api, statute=statute, municipality=municipality)
    municipality_id = ctx["municipality"]["id"]
    planner = fixtures.planner(ctx)

    # `TOWNSHIP_MERGER` is not one of the four methods §3.2 declares, so payload
    # shape refuses it at 400 rather than reaching the statute's authorization
    # check at 422.
    payload = factories.annexation_case_payload(municipality_id, method="TOWNSHIP_MERGER")
    validate_error(api.create_annexation_case(planner, payload), ERR_INVALID_REQUEST)

    _, meta = validate_paginated(
        api.list_annexation_cases(planner, municipality_id=municipality_id)
    )
    assert meta["total_count"] == 0


def test_reading_an_unknown_case_id_returns_the_case_specific_not_found(
    api, state_law_admin
):
    """PRD §2.10: "Each identifier has its own not-found code:
    `ERR_STATUTE_PROFILE_NOT_FOUND`, `ERR_MUNICIPALITY_NOT_FOUND`,
    `ERR_SERVICE_PROVIDER_NOT_FOUND`, `ERR_PROPERTY_OWNER_NOT_FOUND`,
    `ERR_CASE_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`,
    `ERR_CONSENT_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
    `ERR_COMMITMENT_NOT_FOUND`, `ERR_HEARING_NOT_FOUND`,
    `ERR_NOTICE_PUBLICATION_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and
    `ERR_UTILITY_ACCOUNT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/entities/get_annexation_case_with_an_unknown_id_returns_case_not_found
    """
    # A syntactically valid UUID that names no case in an empty register.
    validate_error(
        api.get_annexation_case(state_law_admin, NON_EXISTENT_UUID), ERR_CASE_NOT_FOUND
    )

    _, meta = validate_paginated(api.list_annexation_cases(state_law_admin))
    assert meta["total_count"] == 0


def test_adding_a_parcel_under_an_unknown_case_resolves_the_path_first(
    api, state_law_admin
):
    """PRD §2.10: "Foreign keys carried in a request body are resolved after the
    path, in the order the endpoint declares its inputs, and an unresolvable one
    yields `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/parcel_creation_under_an_unknown_case_is_rejected_with_case_not_found
    """
    statute, municipality = _matched_jurisdiction(
        {"authorized_methods": ["INVOLUNTARY_ORDINANCE"], "required_service_types": ["POLICE"]}
    )
    ctx = fixtures.setup_jurisdiction(api, statute=statute, municipality=municipality)
    owner = fixtures.create_owner(api)

    # The body is well formed and its `primary_owner_id` resolves, so only the
    # unresolvable path identifier can decide the error.
    payload = factories.parcel_payload(owner["id"])
    validate_error(
        api.create_parcel(fixtures.planner(ctx), NON_EXISTENT_UUID, payload),
        ERR_CASE_NOT_FOUND,
    )

    # No orphan parcel is written.
    _, meta = validate_paginated(api.list_parcels(state_law_admin))
    assert meta["total_count"] == 0


def test_utility_account_naming_an_unknown_provider_is_rejected(api):
    """PRD §2.10: "Foreign keys carried in a request body are resolved after the
    path, in the order the endpoint declares its inputs, and an unresolvable one
    yields `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/utility_account_with_an_unknown_provider_fk_is_rejected
    """
    ctx = _draft_territory(
        api,
        parcel_values_cents=[40000000],
        case_overrides={"total_lot_count": 1, "developed_lot_count": 1, "dwelling_units": 2},
    )
    parcel = ctx["parcels"][0]
    planner = fixtures.planner(ctx)

    # The account's parcel resolves; its provider does not, and the missing
    # provider is what the body-foreign-key gate reports.
    payload = factories.utility_account_payload(parcel["id"], NON_EXISTENT_UUID)
    validate_error(api.create_utility_account(planner, payload), ERR_REFERENCE_NOT_FOUND)

    _, meta = validate_paginated(
        api.list_utility_accounts(planner, parcel_id=parcel["id"])
    )
    assert meta["total_count"] == 0
