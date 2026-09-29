"""Round trips across the annexation record — statute and city registration,
parcel exclusion, the plan of services read, the utility-account link and the
referendum branch of ordinance adoption — together with the error surface the
service presents for unknown path identifiers, out-of-range pagination and a
signature offered after a petition's circulation window has closed.
"""
from datetime import datetime

from test_helpers import (
    NON_EXISTENT_UUID,
    assertions,
    constants,
    factories,
    fixtures,
    make_property_owner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import (
    ERR_ANALYSIS_NOT_FOUND,
    ERR_CASE_NOT_FOUND,
    ERR_COMMITMENT_NOT_FOUND,
    ERR_CONSENT_NOT_FOUND,
    ERR_FILING_NOT_FOUND,
    ERR_HEARING_NOT_FOUND,
    ERR_MUNICIPALITY_NOT_FOUND,
    ERR_NOTICE_PUBLICATION_NOT_FOUND,
    ERR_PAGINATION_INVALID,
    ERR_PARCEL_NOT_FOUND,
    ERR_PETITION_NOT_FOUND,
    ERR_PETITION_WINDOW_CLOSED,
    ERR_PLAN_NOT_FOUND,
    ERR_PROPERTY_OWNER_NOT_FOUND,
    ERR_SERVICE_PROVIDER_NOT_FOUND,
    ERR_STATUTE_PROFILE_NOT_FOUND,
    ERR_UTILITY_ACCOUNT_NOT_FOUND,
)

# A commitment window inside both statutory ceilings (60 days for police and
# fire, 730 for water and sewer) whose inclusive length is worth asserting.
_WINDOW_START = "2026-08-01"
_WINDOW_END = "2026-09-15"


def _instant(value: str) -> datetime:
    """Compare timestamps by the instant they denote, so a server that renders
    three fractional digits and one that renders none are both accepted."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _certified_case_with_open_plan(api):
    """A certified single-parcel territory under a statute that requires only
    POLICE and FIRE, one provider offering both with room for two concurrent
    projects, and a DRAFT plan carrying no commitments yet."""
    ctx = fixtures.setup_certified_case(
        api,
        statute={
            "authorized_methods": ["INVOLUNTARY_ORDINANCE"],
            "required_service_types": ["POLICE", "FIRE"],
        },
        provider={
            "service_types": ["POLICE", "FIRE"],
            "concurrent_project_capacity": 2,
        },
        case={"total_lot_count": 1, "developed_lot_count": 1, "dwelling_units": 4},
        parcel_values_cents=[100000000],
    )
    fixtures.open_plan(api, ctx)
    return ctx


def _commit(api, ctx, service_type, cost_cents):
    """Draft a commitment over the shared 46-day window with no accounts to cut
    over, so activation carries it straight through to FULFILLED."""
    return fixtures.add_commitment(
        api,
        ctx,
        service_type,
        cost_cents=cost_cents,
        committed_account_count=0,
        window_start_date=_WINDOW_START,
        window_end_date=_WINDOW_END,
    )


def _case_with_two_parcels_and_two_providers(api):
    """A DRAFT case with two parcels, a WATER provider and a SEWER provider in
    the same city."""
    ctx = fixtures.setup_draft_case(
        api,
        provider={"service_types": ["WATER"]},
        case={"total_lot_count": 2, "developed_lot_count": 2, "dwelling_units": 4},
        parcel_values_cents=[50000000, 50000000],
    )
    ctx["sewer_provider"] = fixtures.create_provider(
        api, ctx["municipality"]["id"], service_types=["SEWER"]
    )
    return ctx


# ==========================================================================
# Statutes and cities: create, read, list
# ==========================================================================
def test_a_published_statute_and_its_city_read_back_exactly_as_created(
    api, state_law_admin, county_assessor
):
    """PRD §3.1: "Before any case can exist, a `StateLawAdmin` publishes the governing
    statute profile for a state, supplying its `state_code` and `authorized_methods` and
    overriding as many of the thresholds catalogued in §2.6 as the state's law requires;
    every omitted flag takes its declared default, so a minimal profile still yields a
    fully specified statute." "A newly registered city starts with
    `taxable_assessed_value_cents` at 0; that running ledger of assessed value on the
    municipal tax roll rises only when a case posts its tax roll and falls only when a
    posting is reversed by de-annexation."

    Design: Corner/endpoints/statute_and_municipality_crud_round_trips_through_read_and_list
    """
    statute_payload = factories.statute_profile_payload(
        authorized_methods=["INVOLUNTARY_ORDINANCE", "PETITION_MAJORITY"],
        required_service_types=["POLICE"],
        notice_min_days=21,
    )
    statute = validate_success(
        api.create_statute_profile(state_law_admin, statute_payload), 201
    )
    assertions.assert_revision_fields(statute, expected_version=1)
    assertions.assert_echoes(statute, statute_payload)

    read_statute = validate_success(api.get_statute_profile(county_assessor, statute["id"]))
    # There is no update endpoint for a statute profile, so the read must return
    # exactly the resource the create returned.
    assert read_statute == statute

    municipality_payload = factories.municipality_payload(
        statute["id"], name="Cedar Grove", state_code=statute_payload["state_code"]
    )
    municipality = validate_success(
        api.create_municipality(state_law_admin, municipality_payload), 201
    )
    assertions.assert_revision_fields(municipality, expected_version=1)
    assertions.assert_echoes(municipality, municipality_payload)
    # The tax-roll ledger only ever moves through tax-roll posting or reversal.
    assert municipality["taxable_assessed_value_cents"] == 0

    read_municipality = validate_success(
        api.get_municipality(county_assessor, municipality["id"])
    )
    assert read_municipality == municipality


def test_the_municipality_listing_partitions_cities_by_statute_and_by_state(
    api, state_law_admin
):
    """PRD §2.3: "Municipalities may be filtered by `statute_profile_id` or `state_code`."
    "Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the
    `meta` object of the envelope, where `total_count` reflects the number of records
    matching the filters before pagination is applied."

    Design: Corner/endpoints/statute_and_municipality_crud_round_trips_through_read_and_list
    """
    home_statute = fixtures.create_statute(
        api, authorized_methods=["INVOLUNTARY_ORDINANCE", "PETITION_MAJORITY"]
    )
    other_statute = fixtures.create_statute(api, authorized_methods=["INVOLUNTARY_ORDINANCE"])

    first = fixtures.create_municipality(
        api, home_statute["id"], name="Cedar Grove", state_code=home_statute["state_code"]
    )
    second = fixtures.create_municipality(
        api, home_statute["id"], name="Ridgeview", state_code=home_statute["state_code"]
    )
    third = fixtures.create_municipality(
        api, other_statute["id"], name="Fort Landing", state_code=other_statute["state_code"]
    )

    under_home, home_meta = validate_paginated(
        api.list_municipalities(state_law_admin, statute_profile_id=home_statute["id"])
    )
    assert home_meta["total_count"] == 2
    assert home_meta["has_more"] is False
    assertions.assert_id_set(under_home, [first["id"], second["id"]])

    under_other, other_meta = validate_paginated(
        api.list_municipalities(state_law_admin, statute_profile_id=other_statute["id"])
    )
    assert other_meta["total_count"] == 1
    assertions.assert_id_set(under_other, [third["id"]])

    by_state, state_meta = validate_paginated(
        api.list_municipalities(state_law_admin, state_code=other_statute["state_code"])
    )
    assert state_meta["total_count"] == 1
    assertions.assert_id_set(by_state, [third["id"]])


# ==========================================================================
# Carving a parcel back out of the territory
# ==========================================================================
def test_excluding_a_parcel_disconnects_its_account_and_shrinks_the_territory(api):
    """PRD §3.2: "The planner may also carve a parcel back out. Excluding it moves
    `parcel_status` to `EXCLUDED`, disconnects each of that parcel's utility accounts still
    in `OUTSIDE_CITY` by moving them to `DISCONNECTED`, and recomputes the case's territory
    aggregates."

    Design: Corner/endpoints/excluding_a_parcel_disconnects_its_account_and_reduces_the_territory
    """
    ctx = fixtures.setup_draft_case(
        api,
        case={"total_lot_count": 2, "developed_lot_count": 2, "dwelling_units": 4},
        parcel_values_cents=[40000000, 60000000],
    )
    municipality_id = ctx["municipality"]["id"]
    kept, carved = ctx["parcels"][0], ctx["parcels"][1]

    account = fixtures.add_utility_account(
        api, municipality_id, carved["id"], ctx["provider"]["id"]
    )
    assert account["account_status"] == "OUTSIDE_CITY"

    before = fixtures.read_case(api, municipality_id, ctx["case"]["id"])
    assert before["parcel_count"] == 2
    assert before["territory_assessed_value_cents"] == 100000000
    assertions.assert_numeric_equals(
        before["territory_acreage"], assertions.acres(10), "territory_acreage"
    )
    # Version 1 on creation plus one increment for each of the two parcels added.
    assert before["version"] == 3

    # Every stamp in the domain reads the logical clock rather than wall time.
    clock = validate_success(
        api.set_clock(ctx["admin_headers"], "2026-08-20T12:00:00Z")
    )
    assert _instant(clock["current_utc"]) == _instant("2026-08-20T12:00:00Z")

    excluded = validate_success(
        api.exclude_parcel(fixtures.planner(ctx), carved["id"]), 200
    )
    assert excluded["parcel_status"] == "EXCLUDED"

    after = fixtures.read_case(api, municipality_id, ctx["case"]["id"])
    assert after["parcel_count"] == 1
    assert after["territory_assessed_value_cents"] == 40000000
    assertions.assert_numeric_equals(
        after["territory_acreage"], assertions.acres(5), "territory_acreage"
    )
    # Excluding a parcel is itself a mutation of the case.
    assert after["version"] == before["version"] + 1

    assert (
        fixtures.read_account(api, municipality_id, account["id"])["account_status"]
        == "DISCONNECTED"
    )
    # The surviving parcel is untouched by its sibling's carve-out.
    assert fixtures.read_parcel(api, municipality_id, kept["id"])["parcel_status"] == "PROPOSED"

    proposed, proposed_meta = validate_paginated(
        api.list_parcels(
            fixtures.planner(ctx),
            annexation_case_id=ctx["case"]["id"],
            parcel_status="PROPOSED",
        )
    )
    assert proposed_meta["total_count"] == 1
    assertions.assert_id_set(proposed, [kept["id"]])

    disconnected, disconnected_meta = validate_paginated(
        api.list_utility_accounts(
            fixtures.planner(ctx), parcel_id=carved["id"], account_status="DISCONNECTED"
        )
    )
    assert disconnected_meta["total_count"] == 1
    assertions.assert_id_set(disconnected, [account["id"]])


# ==========================================================================
# The plan of services read
# ==========================================================================
def test_plan_cost_coverage_and_readiness_are_derived_from_its_commitments(api):
    """PRD §3.5: "Consider only the plan's commitments in `ACTIVE` or `FULFILLED`; those in
    `DRAFT` or `VOIDED` contribute neither cost nor coverage." "`service_readiness` is
    `PENDING` when that set of commitments is empty; it is `READY` when every member of the
    statute's `required_service_types` appears in `covered_service_types` **and** every one
    of those commitments is in `FULFILLED`; and it is `PARTIAL` in every other case."

    Design: Corner/endpoints/plan_read_returns_the_cost_coverage_and_readiness_derived_from_its_commitments
    """
    ctx = _certified_case_with_open_plan(api)
    municipality_id = ctx["municipality"]["id"]
    plan_id = ctx["plan"]["id"]

    opened = fixtures.read_plan(api, municipality_id, plan_id)
    assert opened["committed_cost_cents"] == 0
    assert opened["covered_service_types"] == []
    assert opened["service_readiness"] == "PENDING"

    police = _commit(api, ctx, "POLICE", 500000)
    assert police["timeline_days"] == assertions.inclusive_day_count(
        _WINDOW_START, _WINDOW_END
    )
    activated_police = fixtures.activate_commitment(api, ctx, police["id"])
    # No accounts to cut over, so activation runs straight on to FULFILLED.
    assert activated_police["commitment_status"] == "FULFILLED"

    mid = fixtures.read_plan(api, municipality_id, plan_id)
    assert mid["committed_cost_cents"] == 500000
    assert mid["covered_service_types"] == ["POLICE"]
    # FIRE is still required and still uncovered, so readiness is only partial.
    assert mid["service_readiness"] == "PARTIAL"

    fire = _commit(api, ctx, "FIRE", 300000)
    fixtures.activate_commitment(api, ctx, fire["id"])

    final = fixtures.read_plan(api, municipality_id, plan_id)
    assert final["committed_cost_cents"] == 800000
    assert final["covered_service_types"] == assertions.ordered_service_types(
        ["FIRE", "POLICE"]
    )
    assert final["service_readiness"] == "READY"

    fulfilled, fulfilled_meta = validate_paginated(
        api.list_service_commitments(
            fixtures.planner(ctx),
            plan_of_services_id=plan_id,
            commitment_status="FULFILLED",
        )
    )
    assert fulfilled_meta["total_count"] == 2
    assertions.assert_id_set(fulfilled, [police["id"], fire["id"]])


def test_the_provider_ledger_sums_both_commitment_windows_rather_than_their_union(api):
    """PRD §3.1: "`concurrent_project_capacity` (default 1, at least 1) is the number of
    commitments whose date windows may cover any single calendar day, and
    `encumbered_capacity_days` — a running total starting at 0 — is the sum of the
    closed-window day counts of every commitment of that provider currently in `ACTIVE` or
    `FULFILLED`."

    Design: Corner/endpoints/plan_read_returns_the_cost_coverage_and_readiness_derived_from_its_commitments
    """
    ctx = _certified_case_with_open_plan(api)
    window_days = assertions.inclusive_day_count(_WINDOW_START, _WINDOW_END)

    assert (
        fixtures.read_provider(api, ctx["municipality"]["id"], ctx["provider"]["id"])[
            "encumbered_capacity_days"
        ]
        == 0
    )

    police = _commit(api, ctx, "POLICE", 500000)
    fixtures.activate_commitment(api, ctx, police["id"])
    fire = _commit(api, ctx, "FIRE", 300000)
    fixtures.activate_commitment(api, ctx, fire["id"])

    provider = fixtures.read_provider(
        api, ctx["municipality"]["id"], ctx["provider"]["id"]
    )
    # Both windows cover the identical calendar days, yet the ledger adds their
    # lengths instead of measuring the union.
    assert provider["encumbered_capacity_days"] == 2 * window_days


# ==========================================================================
# The utility-account link
# ==========================================================================
def test_a_registered_account_stores_both_of_its_foreign_keys_and_the_outside_city_rate(api):
    """PRD §3.8: "An account starts with `account_status` `OUTSIDE_CITY` and `rate_schedule`
    `OUTSIDE_CITY_SURCHARGE`." "`effective_monthly_cents` is recomputed on registration and
    on every change of `rate_schedule`: while the schedule is `OUTSIDE_CITY_SURCHARGE` it is
    `monthly_base_cents` multiplied by one plus the municipality's
    `utility_outside_surcharge_pct`, rounded half up to a whole cent; while the schedule is
    `INSIDE_CITY` it is simply `monthly_base_cents` with no surcharge at all."

    Design: Corner/endpoints/a_utility_account_is_discoverable_from_both_its_parcel_and_its_provider
    """
    ctx = _case_with_two_parcels_and_two_providers(api)
    served_parcel = ctx["parcels"][0]
    water_provider = ctx["provider"]

    payload = factories.utility_account_payload(served_parcel["id"], water_provider["id"])
    account = validate_success(
        api.create_utility_account(fixtures.planner(ctx), payload), 201
    )
    assertions.assert_revision_fields(account, expected_version=1)
    assertions.assert_echoes(account, payload)
    assert account["parcel_id"] == served_parcel["id"]
    assert account["service_provider_id"] == water_provider["id"]
    assert account["account_status"] == "OUTSIDE_CITY"
    assert account["rate_schedule"] == "OUTSIDE_CITY_SURCHARGE"
    assert account["effective_monthly_cents"] == assertions.expected_outside_city_monthly_cents(
        payload["monthly_base_cents"], constants.DEFAULT_UTILITY_OUTSIDE_SURCHARGE_PCT
    )

    read_back = validate_success(
        api.get_utility_account(ctx["assessor_headers"], account["id"])
    )
    assert read_back == account


def test_an_account_is_found_from_its_parcel_and_from_its_provider_but_from_no_other(api):
    """PRD §2.3: "Service providers may be filtered by `municipality_id`." "Utility accounts
    accept `parcel_id`, `service_provider_id` and `account_status`."

    Design: Corner/endpoints/a_utility_account_is_discoverable_from_both_its_parcel_and_its_provider
    """
    ctx = _case_with_two_parcels_and_two_providers(api)
    served_parcel, unserved_parcel = ctx["parcels"][0], ctx["parcels"][1]
    water_provider, sewer_provider = ctx["provider"], ctx["sewer_provider"]
    planner = fixtures.planner(ctx)

    account = fixtures.add_utility_account(
        api, ctx["municipality"]["id"], served_parcel["id"], water_provider["id"]
    )

    by_parcel, by_parcel_meta = validate_paginated(
        api.list_utility_accounts(planner, parcel_id=served_parcel["id"])
    )
    assert by_parcel_meta["total_count"] == 1
    assertions.assert_id_set(by_parcel, [account["id"]])

    by_provider, by_provider_meta = validate_paginated(
        api.list_utility_accounts(planner, service_provider_id=water_provider["id"])
    )
    assert by_provider_meta["total_count"] == 1
    assertions.assert_id_set(by_provider, [account["id"]])

    # The sibling parcel and the sewer authority are on the other side of both
    # ends of the link, so neither filter reaches the account.
    _, sibling_meta = validate_paginated(
        api.list_utility_accounts(planner, parcel_id=unserved_parcel["id"])
    )
    assert sibling_meta["total_count"] == 0

    _, sewer_meta = validate_paginated(
        api.list_utility_accounts(planner, service_provider_id=sewer_provider["id"])
    )
    assert sewer_meta["total_count"] == 0

    providers, providers_meta = validate_paginated(
        api.list_service_providers(planner, municipality_id=ctx["municipality"]["id"])
    )
    assert providers_meta["total_count"] == 2
    assertions.assert_id_set(providers, [water_provider["id"], sewer_provider["id"]])


# ==========================================================================
# The referendum branch of ordinance adoption
# ==========================================================================
def test_a_method_requiring_ratification_lands_in_referendum_pending_and_then_effectuates(api):
    """PRD §3.7: "When the case's `method` **is** among them, the case advances
    `HEARING_HELD → REFERENDUM_PENDING` instead and its `referendum_result` stays `NOT_HELD`
    until the vote is recorded." "A `result` of `APPROVED` sets `referendum_result` to
    `APPROVED`, advances the case `REFERENDUM_PENDING → REFERENDUM_APPROVED`, and sets
    `commission_review_status` to `PENDING` when the statute requires commission review."

    Design: Corner/endpoints/the_referendum_branch_of_ordinance_adoption_is_taken_only_for_a_listed_method
    """
    ctx = fixtures.setup_case_ready_for_ordinance(
        api,
        method="INVOLUNTARY_ORDINANCE",
        statute={
            "authorized_methods": ["INVOLUNTARY_ORDINANCE"],
            "referendum_required_methods": ["INVOLUNTARY_ORDINANCE"],
        },
    )
    case_id = ctx["case"]["id"]
    assert ctx["case"]["protest_outcome"] == "FAILED"

    adopted = validate_success(
        api.adopt_ordinance(fixtures.clerk(ctx), case_id), 200
    )
    # The statute, not the request, chooses this destination.
    assert adopted["status"] == "REFERENDUM_PENDING"
    assert adopted["referendum_result"] == "NOT_HELD"
    assert _instant(adopted["ordinance_adopted_at"]) == _instant(
        constants.CLOCK_AFTER_PROTEST_WINDOW
    )

    ratified = validate_success(
        api.record_referendum(fixtures.clerk(ctx), case_id, "APPROVED"), 200
    )
    assert ratified["status"] == "REFERENDUM_APPROVED"
    assert ratified["referendum_result"] == "APPROVED"

    effective = validate_success(
        api.effectuate(
            fixtures.planner(ctx), case_id, constants.EFFECTIVE_DATE_AFTER_PROTEST
        ),
        200,
    )
    assert effective["status"] == "EFFECTIVE"
    assert effective["effective_date"] == constants.EFFECTIVE_DATE_AFTER_PROTEST
    # This statute does not require commission review, so that axis never opened.
    assert effective["commission_review_status"] == "NOT_REQUIRED"

    for parcel in ctx["parcels"]:
        assert (
            fixtures.read_parcel(api, ctx["municipality"]["id"], parcel["id"])[
                "parcel_status"
            ]
            == "INCORPORATED"
        )


def test_a_method_absent_from_the_ratification_list_lands_directly_in_ordinance_adopted(api):
    """PRD §3.7: "When the case's `method` is **not** among the methods requiring
    ratification, the case advances `HEARING_HELD → ORDINANCE_ADOPTED`, and its
    `commission_review_status` becomes `PENDING` if the statute's
    `boundary_commission_required` is true and stays `NOT_REQUIRED` otherwise."

    Design: Corner/endpoints/the_referendum_branch_of_ordinance_adoption_is_taken_only_for_a_listed_method
    """
    # The statute leaves `referendum_required_methods` at its empty default, so the
    # identical chain must take the other branch of the same endpoint.
    ctx = fixtures.setup_case_ready_for_ordinance(
        api,
        method="INVOLUNTARY_ORDINANCE",
        statute={"authorized_methods": ["INVOLUNTARY_ORDINANCE"]},
    )
    assert ctx["statute"]["referendum_required_methods"] == []

    adopted = validate_success(
        api.adopt_ordinance(fixtures.clerk(ctx), ctx["case"]["id"]), 200
    )
    assert adopted["status"] == "ORDINANCE_ADOPTED"
    assert adopted["referendum_result"] == "NOT_HELD"
    assert adopted["commission_review_status"] == "NOT_REQUIRED"
    assert _instant(adopted["ordinance_adopted_at"]) == _instant(
        constants.CLOCK_AFTER_PROTEST_WINDOW
    )


# ==========================================================================
# Per-entity not-found codes
# ==========================================================================
def test_an_unknown_statute_profile_id_reports_the_statute_profile_code(api, state_law_admin):
    """PRD §2.10: "Each identifier has its own not-found code:
    `ERR_STATUTE_PROFILE_NOT_FOUND`, `ERR_MUNICIPALITY_NOT_FOUND`,
    `ERR_SERVICE_PROVIDER_NOT_FOUND`, `ERR_PROPERTY_OWNER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_PARCEL_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`,
    `ERR_ANALYSIS_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_PUBLICATION_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and
    `ERR_UTILITY_ACCOUNT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_error
    """
    validate_error(
        api.get_statute_profile(state_law_admin, NON_EXISTENT_UUID),
        ERR_STATUTE_PROFILE_NOT_FOUND,
    )


def test_an_unknown_municipality_id_reports_the_municipality_code(api, state_law_admin):
    """PRD §2.10: "Each identifier has its own not-found code:
    `ERR_STATUTE_PROFILE_NOT_FOUND`, `ERR_MUNICIPALITY_NOT_FOUND`,
    `ERR_SERVICE_PROVIDER_NOT_FOUND`, `ERR_PROPERTY_OWNER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_PARCEL_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`,
    `ERR_ANALYSIS_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_PUBLICATION_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and
    `ERR_UTILITY_ACCOUNT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_error
    """
    validate_error(
        api.get_municipality(state_law_admin, NON_EXISTENT_UUID), ERR_MUNICIPALITY_NOT_FOUND
    )


def test_an_unknown_service_provider_id_reports_the_service_provider_code(api, state_law_admin):
    """PRD §2.10: "Each identifier has its own not-found code:
    `ERR_STATUTE_PROFILE_NOT_FOUND`, `ERR_MUNICIPALITY_NOT_FOUND`,
    `ERR_SERVICE_PROVIDER_NOT_FOUND`, `ERR_PROPERTY_OWNER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_PARCEL_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`,
    `ERR_ANALYSIS_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_PUBLICATION_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and
    `ERR_UTILITY_ACCOUNT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_error
    """
    validate_error(
        api.get_service_provider(state_law_admin, NON_EXISTENT_UUID),
        ERR_SERVICE_PROVIDER_NOT_FOUND,
    )


def test_an_unknown_property_owner_id_reports_the_property_owner_code(api, state_law_admin):
    """PRD §2.10: "Each identifier has its own not-found code:
    `ERR_STATUTE_PROFILE_NOT_FOUND`, `ERR_MUNICIPALITY_NOT_FOUND`,
    `ERR_SERVICE_PROVIDER_NOT_FOUND`, `ERR_PROPERTY_OWNER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_PARCEL_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`,
    `ERR_ANALYSIS_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_PUBLICATION_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and
    `ERR_UTILITY_ACCOUNT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_error
    """
    validate_error(
        api.get_property_owner(state_law_admin, NON_EXISTENT_UUID),
        ERR_PROPERTY_OWNER_NOT_FOUND,
    )


def test_an_unknown_annexation_case_id_reports_the_case_code(api, state_law_admin):
    """PRD §2.10: "Each identifier has its own not-found code:
    `ERR_STATUTE_PROFILE_NOT_FOUND`, `ERR_MUNICIPALITY_NOT_FOUND`,
    `ERR_SERVICE_PROVIDER_NOT_FOUND`, `ERR_PROPERTY_OWNER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_PARCEL_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`,
    `ERR_ANALYSIS_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_PUBLICATION_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and
    `ERR_UTILITY_ACCOUNT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_error
    """
    validate_error(
        api.get_annexation_case(state_law_admin, NON_EXISTENT_UUID), ERR_CASE_NOT_FOUND
    )


def test_an_unknown_parcel_id_reports_the_parcel_code(api, state_law_admin):
    """PRD §2.10: "Each identifier has its own not-found code:
    `ERR_STATUTE_PROFILE_NOT_FOUND`, `ERR_MUNICIPALITY_NOT_FOUND`,
    `ERR_SERVICE_PROVIDER_NOT_FOUND`, `ERR_PROPERTY_OWNER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_PARCEL_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`,
    `ERR_ANALYSIS_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_PUBLICATION_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and
    `ERR_UTILITY_ACCOUNT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_error
    """
    validate_error(api.get_parcel(state_law_admin, NON_EXISTENT_UUID), ERR_PARCEL_NOT_FOUND)


def test_an_unknown_utility_account_id_reports_the_utility_account_code(api, state_law_admin):
    """PRD §2.10: "Each identifier has its own not-found code:
    `ERR_STATUTE_PROFILE_NOT_FOUND`, `ERR_MUNICIPALITY_NOT_FOUND`,
    `ERR_SERVICE_PROVIDER_NOT_FOUND`, `ERR_PROPERTY_OWNER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_PARCEL_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`,
    `ERR_ANALYSIS_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_PUBLICATION_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and
    `ERR_UTILITY_ACCOUNT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_error
    """
    validate_error(
        api.get_utility_account(state_law_admin, NON_EXISTENT_UUID),
        ERR_UTILITY_ACCOUNT_NOT_FOUND,
    )


def test_an_unknown_petition_id_reports_the_petition_code(api, state_law_admin):
    """PRD §2.10: "Each identifier has its own not-found code:
    `ERR_STATUTE_PROFILE_NOT_FOUND`, `ERR_MUNICIPALITY_NOT_FOUND`,
    `ERR_SERVICE_PROVIDER_NOT_FOUND`, `ERR_PROPERTY_OWNER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_PARCEL_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`,
    `ERR_ANALYSIS_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_PUBLICATION_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and
    `ERR_UTILITY_ACCOUNT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_error
    """
    validate_error(api.get_petition(state_law_admin, NON_EXISTENT_UUID), ERR_PETITION_NOT_FOUND)


def test_an_unknown_consent_id_reports_the_consent_code(api, state_law_admin):
    """PRD §2.10: "Each identifier has its own not-found code:
    `ERR_STATUTE_PROFILE_NOT_FOUND`, `ERR_MUNICIPALITY_NOT_FOUND`,
    `ERR_SERVICE_PROVIDER_NOT_FOUND`, `ERR_PROPERTY_OWNER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_PARCEL_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`,
    `ERR_ANALYSIS_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_PUBLICATION_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and
    `ERR_UTILITY_ACCOUNT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_error
    """
    validate_error(api.get_consent(state_law_admin, NON_EXISTENT_UUID), ERR_CONSENT_NOT_FOUND)


def test_an_unknown_analysis_id_reports_the_analysis_code(api, state_law_admin):
    """PRD §2.10: "Each identifier has its own not-found code:
    `ERR_STATUTE_PROFILE_NOT_FOUND`, `ERR_MUNICIPALITY_NOT_FOUND`,
    `ERR_SERVICE_PROVIDER_NOT_FOUND`, `ERR_PROPERTY_OWNER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_PARCEL_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`,
    `ERR_ANALYSIS_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_PUBLICATION_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and
    `ERR_UTILITY_ACCOUNT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_error
    """
    validate_error(
        api.get_fiscal_impact_analysis(state_law_admin, NON_EXISTENT_UUID),
        ERR_ANALYSIS_NOT_FOUND,
    )


def test_an_unknown_plan_of_services_id_reports_the_plan_code(api, state_law_admin):
    """PRD §2.10: "Each identifier has its own not-found code:
    `ERR_STATUTE_PROFILE_NOT_FOUND`, `ERR_MUNICIPALITY_NOT_FOUND`,
    `ERR_SERVICE_PROVIDER_NOT_FOUND`, `ERR_PROPERTY_OWNER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_PARCEL_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`,
    `ERR_ANALYSIS_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_PUBLICATION_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and
    `ERR_UTILITY_ACCOUNT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_error
    """
    validate_error(
        api.get_plan_of_services(state_law_admin, NON_EXISTENT_UUID), ERR_PLAN_NOT_FOUND
    )


def test_an_unknown_service_commitment_id_reports_the_commitment_code(api, state_law_admin):
    """PRD §2.10: "Each identifier has its own not-found code:
    `ERR_STATUTE_PROFILE_NOT_FOUND`, `ERR_MUNICIPALITY_NOT_FOUND`,
    `ERR_SERVICE_PROVIDER_NOT_FOUND`, `ERR_PROPERTY_OWNER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_PARCEL_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`,
    `ERR_ANALYSIS_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_PUBLICATION_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and
    `ERR_UTILITY_ACCOUNT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_error
    """
    validate_error(
        api.get_service_commitment(state_law_admin, NON_EXISTENT_UUID),
        ERR_COMMITMENT_NOT_FOUND,
    )


def test_an_unknown_public_hearing_id_reports_the_hearing_code(api, state_law_admin):
    """PRD §2.10: "Each identifier has its own not-found code:
    `ERR_STATUTE_PROFILE_NOT_FOUND`, `ERR_MUNICIPALITY_NOT_FOUND`,
    `ERR_SERVICE_PROVIDER_NOT_FOUND`, `ERR_PROPERTY_OWNER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_PARCEL_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`,
    `ERR_ANALYSIS_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_PUBLICATION_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and
    `ERR_UTILITY_ACCOUNT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_error
    """
    validate_error(
        api.get_public_hearing(state_law_admin, NON_EXISTENT_UUID), ERR_HEARING_NOT_FOUND
    )


def test_an_unknown_notice_publication_id_reports_the_notice_publication_code(
    api, state_law_admin
):
    """PRD §2.10: "Each identifier has its own not-found code:
    `ERR_STATUTE_PROFILE_NOT_FOUND`, `ERR_MUNICIPALITY_NOT_FOUND`,
    `ERR_SERVICE_PROVIDER_NOT_FOUND`, `ERR_PROPERTY_OWNER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_PARCEL_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`,
    `ERR_ANALYSIS_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_PUBLICATION_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and
    `ERR_UTILITY_ACCOUNT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_error
    """
    validate_error(
        api.get_notice_publication(state_law_admin, NON_EXISTENT_UUID),
        ERR_NOTICE_PUBLICATION_NOT_FOUND,
    )


def test_an_unknown_protest_filing_id_reports_the_filing_code(api, state_law_admin):
    """PRD §2.10: "Each identifier has its own not-found code:
    `ERR_STATUTE_PROFILE_NOT_FOUND`, `ERR_MUNICIPALITY_NOT_FOUND`,
    `ERR_SERVICE_PROVIDER_NOT_FOUND`, `ERR_PROPERTY_OWNER_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_PARCEL_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`,
    `ERR_ANALYSIS_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`,
    `ERR_HEARING_NOT_FOUND`, `ERR_NOTICE_PUBLICATION_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and
    `ERR_UTILITY_ACCOUNT_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_error
    """
    validate_error(
        api.get_protest_filing(state_law_admin, NON_EXISTENT_UUID), ERR_FILING_NOT_FOUND
    )


def test_the_notices_of_an_unknown_hearing_report_the_hearing_code(api, state_law_admin):
    """PRD §2.10: "A request for the notices of a non-existent hearing therefore yields
    `ERR_HEARING_NOT_FOUND` and never reaches the notice lookup."

    Design: Corner/errors/every_unknown_path_id_returns_its_own_not_found_error
    """
    validate_error(
        api.list_hearing_notices(state_law_admin, NON_EXISTENT_UUID), ERR_HEARING_NOT_FOUND
    )


# ==========================================================================
# Pagination bounds
# ==========================================================================
def test_pagination_parameters_outside_their_declared_bounds_are_refused(api, state_law_admin):
    """PRD §2.3: "`limit` caps the number of records returned; it defaults to 10 when
    omitted, may not be smaller than 1, and may not be larger than 100." "A `limit` outside
    the range 1 through 100 inclusive, or a negative `offset`, is rejected with
    `ERR_PAGINATION_INVALID` (HTTP 400)."

    Design: Corner/errors/pagination_parameters_outside_their_declared_bounds_are_rejected
    """
    statute = fixtures.create_statute(api, authorized_methods=["INVOLUNTARY_ORDINANCE"])
    fixtures.create_municipality(
        api, statute["id"], name="Cedar Grove", state_code=statute["state_code"]
    )

    # One below the minimum limit, one above the maximum limit, and an offset
    # that cannot be a number of records to skip.
    validate_error(
        api.list_municipalities(state_law_admin, limit=constants.MIN_LIMIT - 1),
        ERR_PAGINATION_INVALID,
    )
    validate_error(
        api.list_municipalities(state_law_admin, limit=constants.MAX_LIMIT + 1),
        ERR_PAGINATION_INVALID,
    )
    validate_error(
        api.list_municipalities(state_law_admin, offset=-1), ERR_PAGINATION_INVALID
    )


def test_the_boundary_pagination_values_are_accepted_even_when_the_page_is_empty(
    api, state_law_admin
):
    """PRD §2.3: "`offset` is the number of records to skip and defaults to 0; it may not be
    negative." "Every list response carries `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope, where `total_count` reflects the number of
    records matching the filters before pagination is applied."

    Design: Corner/errors/pagination_parameters_outside_their_declared_bounds_are_rejected
    """
    statute = fixtures.create_statute(api, authorized_methods=["INVOLUNTARY_ORDINANCE"])
    only_city = fixtures.create_municipality(
        api, statute["id"], name="Cedar Grove", state_code=statute["state_code"]
    )

    first_page, first_meta = validate_paginated(
        api.list_municipalities(
            state_law_admin, limit=constants.MIN_LIMIT, offset=constants.DEFAULT_OFFSET
        )
    )
    assert first_meta["limit"] == constants.MIN_LIMIT
    assert first_meta["offset"] == constants.DEFAULT_OFFSET
    assert first_meta["total_count"] == 1
    assert first_meta["has_more"] is False
    assertions.assert_id_set(first_page, [only_city["id"]])

    widest_page, widest_meta = validate_paginated(
        api.list_municipalities(state_law_admin, limit=constants.MAX_LIMIT)
    )
    assert widest_meta["limit"] == constants.MAX_LIMIT
    assert widest_meta["total_count"] == 1
    assertions.assert_id_set(widest_page, [only_city["id"]])

    # An in-bounds offset that lands past the single row is a legal request for
    # an empty page, not a pagination error.
    beyond_page, beyond_meta = validate_paginated(
        api.list_municipalities(state_law_admin, limit=constants.MIN_LIMIT, offset=1)
    )
    assert beyond_meta["total_count"] == 1
    assert beyond_meta["has_more"] is False
    assert beyond_page == []


# ==========================================================================
# The petition circulation window
# ==========================================================================
def test_a_signature_after_the_circulation_deadline_is_refused_while_the_petition_circulates(
    api,
):
    """PRD §3.3: "The logical clock must lie inside the closed interval running from
    `circulation_started_at` through `circulation_deadline_at` inclusive; outside it,
    `ERR_PETITION_WINDOW_CLOSED`."

    Design: Corner/errors/a_consent_signed_after_the_circulation_deadline_is_rejected
    """
    ctx = fixtures.setup_certified_case(
        api,
        statute={"authorized_methods": ["PETITION_MAJORITY"]},
        case={
            "method": "PETITION_MAJORITY",
            "total_lot_count": 2,
            "developed_lot_count": 2,
            "dwelling_units": 4,
        },
        parcel_values_cents=[50000000, 50000000],
    )
    petition = fixtures.open_petition(api, ctx, circulation_days=30)
    assert petition["sufficiency_status"] == "CIRCULATING"
    assert _instant(petition["circulation_started_at"]) == _instant(
        constants.CLOCK_STARTUP_UTC
    )
    assert _instant(petition["circulation_deadline_at"]) == _instant(
        assertions.add_days(constants.CLOCK_STARTUP_UTC, 30)
    )

    # One second inside the closed window: the signature qualifies.
    fixtures.set_clock(api, "2026-08-30T23:59:59Z")
    consent = fixtures.sign_consent(api, ctx, parcel_index=0)
    assert _instant(consent["signed_at"]) == _instant("2026-08-30T23:59:59Z")
    assert consent["qualified_value_cents"] == assertions.expected_share_value_cents(
        50000000, 100.00
    )

    # Five days past the deadline, with nobody having certified the petition, so
    # it is still CIRCULATING rather than EXPIRED.
    fixtures.set_clock(api, "2026-09-05T09:00:00Z")
    late_owner = ctx["owners"][1]
    late = api.create_consent(
        make_property_owner_headers(late_owner["id"]),
        factories.consent_payload(
            petition["id"], ctx["parcels"][1]["id"], late_owner["id"]
        ),
    )
    validate_error(late, ERR_PETITION_WINDOW_CLOSED)

    after = fixtures.read_petition(api, ctx["municipality"]["id"], petition["id"])
    assert after["sufficiency_status"] == "CIRCULATING"
    assert after["qualified_signature_assessed_value_cents"] == 50000000

    recorded, recorded_meta = validate_paginated(
        api.list_consents(fixtures.clerk(ctx), petition_id=petition["id"])
    )
    assert recorded_meta["total_count"] == 1
    assertions.assert_id_set(recorded, [consent["id"]])
