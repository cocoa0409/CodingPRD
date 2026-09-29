"""Row shapes as the contract declares them: what a create echoes, what a read
returns, which defaults appear, which figures are derived, and which identifier
a missing row resolves to."""

from test_helpers import (
    ADMIN,
    COMPLIANCE,
    UW,
    ApiErrorId,
    add_scheduled_item,
    assert_common_fields,
    assert_farm_account,
    assert_new_draft_policy,
    assert_premium_transaction,
    get_success_data,
    is_valid_uuid,
    make_agent_headers,
    open_account,
    open_pool,
    open_policy,
    open_zone_pools,
    read_ledger,
    read_policy,
    register_agent,
    set_clock,
    setup_rated_dwelling_policy,
    validate_error,
    validate_paginated,
    validate_success,
)

MISSING_AGENT_ID = "00000000-0000-4000-8000-000000000001"
MISSING_INSPECTOR_ID = "00000000-0000-4000-8000-000000000002"
MISSING_POOL_ID = "00000000-0000-4000-8000-000000000003"
MISSING_ITEM_ID = "00000000-0000-4000-8000-000000000011"
MISSING_LABOR_PROFILE_ID = "00000000-0000-4000-8000-000000000012"
MISSING_ENDORSEMENT_ID = "00000000-0000-4000-8000-000000000013"
MISSING_ACCOUNT_ID = "00000000-0000-4000-8000-000000000014"
MISSING_INSPECTION_ID = "00000000-0000-4000-8000-000000000021"
MISSING_RECOMMENDATION_ID = "00000000-0000-4000-8000-000000000022"
MISSING_RESERVATION_ID = "00000000-0000-4000-8000-000000000023"
MISSING_POLICY_ID = "00000000-0000-4000-8000-000000000024"


def test_registering_a_producer_echoes_every_supplied_field(api):
    """"Registering a producer captures `agency_name`, a non-blank string of 1 to
    120 characters, and `license_state`, exactly two uppercase letters naming the
    state the producer holds a licence in." The create returns 201 — "Creating a
    new resource returns HTTP 201" — inside the standard object envelope, whose
    `api_request_id` "is a server-generated unique identifier for the request that
    starts with `req_`".

    Design: Corner/entities/corner_agent_creation_returns_envelope_and_all_fields
    """
    set_clock()

    response = api.create_agent(
        {
            "agency_name": "Prairie Risk Partners",
            "license_state": "KS",
            "appointment_status": "ACTIVE",
            "authority_limit_cents": 5_000_000,
        },
        ADMIN,
    )

    data = validate_success(response, 201)
    assert data["agency_name"] == "Prairie Risk Partners"
    assert data["license_state"] == "KS"
    assert data["appointment_status"] == "ACTIVE"
    assert data["authority_limit_cents"] == 5_000_000
    assert data["version"] == 1
    assert_common_fields(data, "Agent")

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_reading_a_new_package_returns_exactly_what_was_opened(api):
    """"A newly opened policy has `uw_status` `DRAFT`, `compliance_status`
    `NOT_INSPECTED`, `version` 1, every premium field and `exposed_tiv_cents` at
    0, and `rating_valuation_date`, `quote_expires_at`, `referred_at`,
    `referred_by_user_id`, `referral_reason_code`, `bound_at`, `bound_by_user_id`
    and `closure_reason` all null." The read hands back the account it hangs from
    and both inclusive term endpoints exactly as submitted.

    Design: Corner/entities/corner_farm_policy_retrieval_returns_stored_row
    """
    set_clock()
    agent = register_agent()
    agent_headers = make_agent_headers(agent["id"])
    account = open_account(agent_headers, cat_zone_code="ZN-1")
    created = open_policy(agent_headers, account["id"])

    stored = get_success_data(api.get_farm_policy(created["id"], UW))

    assert stored["id"] == created["id"]
    assert stored["account_id"] == account["id"]
    assert stored["term_start_date"] == "2026-09-01"
    assert stored["term_end_date"] == "2027-08-31"
    assert stored["deductible_cents"] == 500_000
    assert_new_draft_policy(stored)


def test_the_pool_list_windows_one_zone_and_leaves_the_other_zone_out(api):
    """"the four pagination fields `limit`, `offset`, `total_count` and `has_more`
    are echoed in `meta`, where `total_count` counts the rows matching the filters
    before the window is applied and `has_more` indicates whether rows remain
    beyond it." Three pools stand in ZN-1 and one in ZN-9, so a window of two over
    the ZN-1 filter reports a total of three across two pages and never shows the
    ZN-9 row.

    Design: Corner/entities/corner_cat_pool_listing_paginates_and_filters_by_zone
    """
    set_clock()
    open_zone_pools("ZN-1")
    elsewhere = open_pool("ZN-9", "HAIL")

    first_response = api.list_cat_capacity_pools(
        UW, params={"zone_code": "ZN-1", "limit": 2, "offset": 0}
    )
    second_response = api.list_cat_capacity_pools(
        UW, params={"zone_code": "ZN-1", "limit": 2, "offset": 2}
    )

    first_page, first_meta = validate_paginated(first_response)
    second_page, second_meta = validate_paginated(second_response)

    assert len(first_page) == 2
    assert (first_meta["total_count"], first_meta["limit"], first_meta["offset"]) == (3, 2, 0)
    assert first_meta["has_more"] is True

    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["offset"] == 2
    assert second_meta["has_more"] is False

    assert first_response.json()["response_type"] == "array"
    assert second_response.json()["response_type"] == "array"

    returned = first_page + second_page
    assert elsewhere["id"] not in [row["id"] for row in returned]
    for row in returned:
        assert row["zone_code"] == "ZN-1"
        assert row["available_cents"] == 200_000_000


def test_each_reference_registry_resolves_its_own_not_found_identifier(api):
    """"Each resource has its own not-found identifier, and all of them carry HTTP
    404" — concretely, "an unresolvable producer `id` yields `ERR_AGENT_NOT_FOUND`,
    an inspector `ERR_INSPECTOR_NOT_FOUND`, a capacity pool
    `ERR_CAT_POOL_NOT_FOUND`". The three reference reads therefore never collapse
    into one generic code, and each error body carries "a human-readable
    explanation of what went wrong".

    Design: Corner/entities/corner_reference_data_not_found_on_agent_inspector_pool_routes
    """
    set_clock()

    validate_error(
        api.get_agent(MISSING_AGENT_ID, ADMIN), ApiErrorId.ERR_AGENT_NOT_FOUND.value, 404
    )
    validate_error(
        api.get_inspector(MISSING_INSPECTOR_ID, ADMIN),
        ApiErrorId.ERR_INSPECTOR_NOT_FOUND.value,
        404,
    )
    pool_response = api.get_cat_capacity_pool(MISSING_POOL_ID, ADMIN)
    error = validate_error(pool_response, ApiErrorId.ERR_CAT_POOL_NOT_FOUND.value, 404)

    assert pool_response.json()["response_type"] == "error"
    assert error["message"].strip() != ""


def test_each_package_child_resolves_its_own_not_found_identifier(api):
    """The package-child reads each answer with their own identifier at HTTP 404:
    "a farm account `ERR_FARM_ACCOUNT_NOT_FOUND`, a policy
    `ERR_FARM_POLICY_NOT_FOUND`, a scheduled item `ERR_SCHEDULED_ITEM_NOT_FOUND`,
    a labor profile `ERR_LABOR_PROFILE_NOT_FOUND`, an endorsement
    `ERR_ENDORSEMENT_NOT_FOUND`".

    Design: Corner/entities/corner_policy_child_not_found_on_item_labor_endorsement_routes
    """
    set_clock()

    validate_error(
        api.get_scheduled_item(MISSING_ITEM_ID, UW),
        ApiErrorId.ERR_SCHEDULED_ITEM_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_labor_profile(MISSING_LABOR_PROFILE_ID, UW),
        ApiErrorId.ERR_LABOR_PROFILE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_endorsement(MISSING_ENDORSEMENT_ID, UW),
        ApiErrorId.ERR_ENDORSEMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_farm_account(MISSING_ACCOUNT_ID, UW),
        ApiErrorId.ERR_FARM_ACCOUNT_NOT_FOUND.value,
        404,
    )


def test_each_loss_control_row_resolves_its_own_not_found_identifier(api):
    """The loss-control chain is no different: "a catastrophe reservation
    `ERR_CAT_RESERVATION_NOT_FOUND`, an inspection `ERR_INSPECTION_NOT_FOUND` and a
    recommendation `ERR_RECOMMENDATION_NOT_FOUND`". Read by a compliance officer, the inspection,
    recommendation, reservation and policy routes each answer with their own 404
    and leave an empty database empty.

    Design: Corner/entities/corner_inspection_chain_not_found_on_inspection_rec_reservation_routes
    """
    set_clock()

    validate_error(
        api.get_inspection(MISSING_INSPECTION_ID, COMPLIANCE),
        ApiErrorId.ERR_INSPECTION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_recommendation(MISSING_RECOMMENDATION_ID, COMPLIANCE),
        ApiErrorId.ERR_RECOMMENDATION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_cat_reservation(MISSING_RESERVATION_ID, COMPLIANCE),
        ApiErrorId.ERR_CAT_RESERVATION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_farm_policy(MISSING_POLICY_ID, COMPLIANCE),
        ApiErrorId.ERR_FARM_POLICY_NOT_FOUND.value,
        404,
    )

    _, policies_meta = validate_paginated(api.list_farm_policies(COMPLIANCE))
    assert policies_meta["total_count"] == 0
    _, inspections_meta = validate_paginated(api.list_inspections(COMPLIANCE))
    assert inspections_meta["total_count"] == 0


def test_opening_a_package_without_a_deductible_is_refused(api):
    """"The submission names the account through `account_id` and supplies
    `term_start_date` and `term_end_date`, both plain calendar dates in
    `YYYY-MM-DD` form and both inclusive endpoints of the annual term, plus
    `deductible_cents`, the flat property deductible, which must not be negative."
    Omitting it hits the schema rung — "`ERR_INVALID_REQUEST` (400) for a missing
    or null required field" — and "no side effect of any kind is applied when a
    check fails", so the account still holds no packages.

    Design: Corner/entities/corner_farm_policy_creation_missing_deductible_rejected
    """
    set_clock()
    agent = register_agent()
    agent_headers = make_agent_headers(agent["id"])
    account = open_account(agent_headers)

    response = api.create_farm_policy(
        {
            "account_id": account["id"],
            "term_start_date": "2026-09-01",
            "term_end_date": "2027-08-31",
        },
        agent_headers,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    rows, meta = validate_paginated(
        api.list_farm_policies(UW, params={"account_id": account["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_omitted_optional_fields_fall_back_to_the_declared_defaults(api):
    """"`appointment_status`, which is either `ACTIVE` or `SUSPENDED` and defaults
    to `ACTIVE`, and `authority_limit_cents`, the largest `total_premium_cents`
    this producer may have bound on its accounts, which must not be negative and
    defaults to 5000000 cents." An inspector's "`daily_capacity_minutes` is the
    number of inspection minutes the inspector may hold on a single UTC calendar
    date; it must be at least 30 and defaults to 480 minutes, a standard
    eight-hour day", and its `status` "defaults to `ACTIVE`".

    Design: Corner/entities/corner_agent_and_inspector_defaults_applied_on_omission
    """
    set_clock()

    agent = validate_success(
        api.create_agent({"agency_name": "Default Producer LLC", "license_state": "NE"}, ADMIN),
        201,
    )
    inspector = validate_success(
        api.create_inspector({"full_name": "Sam Ortiz", "region_code": "NE-WEST"}, ADMIN),
        201,
    )

    assert agent["appointment_status"] == "ACTIVE"
    assert agent["authority_limit_cents"] == 5_000_000
    assert agent["version"] == 1

    assert inspector["status"] == "ACTIVE"
    assert inspector["daily_capacity_minutes"] == 480
    assert inspector["version"] == 1


def test_an_actual_cash_value_row_is_stored_at_its_derived_insured_value(api):
    """"Second the depreciated value: the effective value multiplied by one minus
    that depreciation fraction, then multiplied by the condition factor for the
    item's `condition_grade`, which is 1.00 for `A`, 0.92 for `B`, 0.80 for `C`
    and 0.45 for `D`. Third the salvage floor: 20 percent of the effective value."
    A machine shed stated at 12000000 cents, aged 18 years at grade C, depreciates
    by 0.45 to 5280000 cents, which clears the 2400000-cent floor and sits far
    under the 60000000-cent structure cap; the client supplied neither that figure
    nor `valued_at`.

    Design: Corner/entities/corner_scheduled_item_computed_insured_value_on_acv_row
    """
    set_clock()
    agent = register_agent()
    agent_headers = make_agent_headers(agent["id"])
    account = open_account(agent_headers)
    policy = open_policy(agent_headers, account["id"])

    row = add_scheduled_item(
        agent_headers,
        policy["id"],
        item_class="FARM_STRUCTURE",
        description="Machine shed",
        valuation_basis="ACV",
        stated_value_cents=12_000_000,
        age_years=18,
        condition_grade="C",
    )

    assert row["insured_value_cents"] == 5_280_000
    assert row["valued_at"].startswith("2026-08-15T00:00:00")
    assert row["stated_value_cents"] == 12_000_000
    assert row["status"] == "ACTIVE"
    assert row["age_years"] == 18
    assert row["condition_grade"] == "C"


def test_an_account_is_stamped_with_the_calling_producer(api):
    """"The account's `agent_id` is stamped by the server from the caller's
    `X-User-ID`; a client that tries to supply `agent_id` in the body has supplied
    an unknown field and is rejected with `ERR_INVALID_REQUEST`." The identifier,
    both timestamps and the opening version all arrive from the server, because
    "Every persisted row carries an `id` that is a server-minted UUID with no type
    prefix, and a `created_at` that is an ISO 8601 UTC timestamp with three
    fractional digits".

    Design: Corner/entities/corner_system_fields_generated_on_farm_account_create
    """
    set_clock()
    agent = register_agent()
    agent_headers = make_agent_headers(agent["id"])

    account = validate_success(
        api.create_farm_account(
            {
                "legal_name": "Willow Bend Dairy",
                "state_code": "KS",
                "county_name": "Sedgwick",
                "cat_zone_code": "ZN-1",
                "acreage": 640,
                "operation_type": "DAIRY",
            },
            agent_headers,
        ),
        201,
    )

    assert is_valid_uuid(account["id"])
    assert account["agent_id"] == agent["id"]
    assert account["created_at"] == account["updated_at"]
    assert account["created_at"].startswith("2026-08-15T00:00:00")
    assert account["version"] == 1
    assert account["acreage"] == 640
    assert account["cat_zone_code"] == "ZN-1"
    assert_farm_account(account)


def test_an_unlisted_species_and_an_empty_herd_are_both_refused(api):
    """"A livestock group names its `species` — one of `CATTLE`, `SWINE`,
    `POULTRY`, `SHEEP` or `EQUINE` — a `head_count` of at least 1, a
    `per_head_value_cents` greater than zero, a `limit_basis` of `PER_HEAD` or
    `BLANKET`, and a `peril_scope` of `FULL_PERIL`, `NAMED_PERIL` or
    `CATASTROPHE_ONLY`." An out-of-set species and a zero head count are both
    schema violations, so neither group is written and the package it was aimed at
    is untouched.

    Design: Corner/entities/corner_livestock_group_invalid_species_enum_rejected
    """
    set_clock()
    agent = register_agent()
    agent_headers = make_agent_headers(agent["id"])
    account = open_account(agent_headers)
    policy = open_policy(agent_headers, account["id"])

    unlisted_species = api.create_livestock_group(
        policy["id"],
        {
            "species": "ALPACA",
            "head_count": 40,
            "per_head_value_cents": 150_000,
            "limit_basis": "PER_HEAD",
            "peril_scope": "FULL_PERIL",
        },
        agent_headers,
    )
    empty_herd = api.create_livestock_group(
        policy["id"],
        {
            "species": "CATTLE",
            "head_count": 0,
            "per_head_value_cents": 150_000,
            "limit_basis": "PER_HEAD",
            "peril_scope": "FULL_PERIL",
        },
        agent_headers,
    )

    validate_error(unlisted_species, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    validate_error(empty_herd, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    groups, meta = validate_paginated(api.list_livestock_groups(policy["id"], UW))
    assert groups == []
    assert meta["total_count"] == 0

    untouched = read_policy(policy["id"])
    assert untouched["uw_status"] == "DRAFT"
    assert untouched["version"] == policy["version"]


def test_a_reversed_term_and_a_sixty_day_term_are_both_refused(api):
    """"The term is checked immediately: `term_end_date` must fall strictly after
    `term_start_date`, and the interval they span must be at least 90 days, or the
    request is rejected with `ERR_INVALID_TERM_DATES`." September through October
    is a perfectly ordered term and still too short by a month, so both
    submissions draw the same identifier and the account keeps no package.

    Design: Corner/entities/corner_invalid_term_dates_rejected_on_short_and_reversed_terms
    """
    set_clock()
    agent = register_agent()
    agent_headers = make_agent_headers(agent["id"])
    account = open_account(agent_headers)

    reversed_term = api.create_farm_policy(
        {
            "account_id": account["id"],
            "term_start_date": "2027-08-31",
            "term_end_date": "2026-09-01",
            "deductible_cents": 500_000,
        },
        agent_headers,
    )
    short_term = api.create_farm_policy(
        {
            "account_id": account["id"],
            "term_start_date": "2026-09-01",
            "term_end_date": "2026-10-31",
            "deductible_cents": 500_000,
        },
        agent_headers,
    )

    validate_error(reversed_term, ApiErrorId.ERR_INVALID_TERM_DATES.value, 400)
    validate_error(short_term, ApiErrorId.ERR_INVALID_TERM_DATES.value, 400)

    rows, meta = validate_paginated(
        api.list_farm_policies(UW, params={"account_id": account["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_the_ledger_of_a_quoted_package_is_an_append_only_pair_of_entries(api):
    """"one entry is appended per non-zero component in the fixed order
    `BASE_PROPERTY`, `BASE_LIVESTOCK`, `BASE_LIABILITY`, `CAT_LOAD`, each with
    `reason_code` `RATING`, each with a positive `amount_cents`; a component worth
    zero is skipped and consumes no `sequence_no`." A single-dwelling package
    therefore writes two rows, and "a ledger entry is immutable, so it carries
    only `id` and `created_at` — both `updated_at` and `version` are absent from a
    premium-transaction representation".

    Design: Corner/entities/corner_premium_transaction_is_append_only_ledger
    """
    scenario = setup_rated_dwelling_policy()

    entries = read_ledger(scenario.policy_id, scenario.agent_headers)

    assert [row["sequence_no"] for row in entries] == [1, 2]
    assert [row["txn_type"] for row in entries] == ["BASE_PROPERTY", "CAT_LOAD"]
    assert [row["amount_cents"] for row in entries] == [144_000, 125_200]
    for row in entries:
        assert row["reason_code"] == "RATING"
        assert_premium_transaction(row)

    written_types = {row["txn_type"] for row in entries}
    assert "BASE_LIVESTOCK" not in written_types
    assert "BASE_LIABILITY" not in written_types

    assert sum(row["amount_cents"] for row in entries) == 269_200
    assert read_policy(scenario.policy_id)["total_premium_cents"] == 269_200


def test_scheduling_an_article_under_an_unknown_package_resolves_the_path_first(api):
    """"Where a route nests a child collection under a parent — a policy's
    scheduled items, a policy's endorsements, an inspection's recommendations —
    the parent `id` is resolved first, and the leftmost `id` that fails to resolve
    determines the 404 that comes back. Only once every path segment resolves does
    the server consider the body." The body here is a flawless dwelling row, and
    it is never looked at.

    Design: Corner/entities/corner_scheduled_item_requires_existing_parent_policy
    """
    set_clock()
    agent = register_agent()
    agent_headers = make_agent_headers(agent["id"])
    account = open_account(agent_headers)
    real_policy = open_policy(agent_headers, account["id"])

    response = api.create_scheduled_item(
        "00000000-0000-4000-8000-000000000031",
        {
            "item_class": "DWELLING",
            "description": "Ranch house",
            "valuation_basis": "RC",
            "stated_value_cents": 40_000_000,
            "age_years": 22,
            "condition_grade": "B",
        },
        agent_headers,
    )

    validate_error(response, ApiErrorId.ERR_FARM_POLICY_NOT_FOUND.value, 404)

    items, meta = validate_paginated(api.list_scheduled_items(real_policy["id"], UW))
    assert items == []
    assert meta["total_count"] == 0


def test_body_borne_references_are_resolved_in_declared_field_order(api):
    """"Ids referenced from the request body are resolved as well: the account
    named by `account_id` when a policy is opened, and the policy and inspector
    named by `policy_id` and `inspector_id` when an inspection is scheduled, must
    all exist. Body ids are checked in the order the fields are declared for the
    route." The inspection names a real policy first and an unknown inspector
    second, so the inspector is the one reported.

    Design: Corner/entities/corner_flat_topology_policy_rejects_unknown_account_id
    """
    set_clock()
    agent = register_agent()
    agent_headers = make_agent_headers(agent["id"])
    account = open_account(agent_headers)
    policy = open_policy(agent_headers, account["id"])

    unknown_account = api.create_farm_policy(
        {
            "account_id": "00000000-0000-4000-8000-000000000041",
            "term_start_date": "2026-09-01",
            "term_end_date": "2027-08-31",
            "deductible_cents": 500_000,
        },
        agent_headers,
    )
    unknown_inspector = api.create_inspection(
        {
            "policy_id": policy["id"],
            "inspector_id": "00000000-0000-4000-8000-000000000042",
            "inspection_type": "INITIAL",
            "scheduled_for": "2026-08-16T09:00:00Z",
            "duration_minutes": 120,
        },
        UW,
    )

    validate_error(unknown_account, ApiErrorId.ERR_FARM_ACCOUNT_NOT_FOUND.value, 404)
    validate_error(unknown_inspector, ApiErrorId.ERR_INSPECTOR_NOT_FOUND.value, 404)

    _, policies_meta = validate_paginated(api.list_farm_policies(UW))
    assert policies_meta["total_count"] == 1
    _, inspections_meta = validate_paginated(api.list_inspections(UW))
    assert inspections_meta["total_count"] == 0
