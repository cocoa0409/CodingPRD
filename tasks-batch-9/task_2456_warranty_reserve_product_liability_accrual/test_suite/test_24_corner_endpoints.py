"""Endpoint coverage: partial updates, filtered listings, sub-resource scoping and the clock.

PRD §2.3 fixes the listing contract: "`limit` controls page size: its default is 10, its
minimum accepted value is 1, and its maximum accepted value is 100. `offset` controls the
starting position: its default is 0 and its minimum accepted value is 0." The same subsection
pins the metadata: "The `meta` object of a list response carries `limit` and `offset` as
applied to the query, `total_count` as the number of rows matching the filters before
pagination is applied, and `has_more` as a boolean that is true exactly when rows matching the
filters remain beyond the returned page."
"""

from test_helpers import (
    ACTUARY_HEADERS,
    ANALYST_HEADERS,
    CONTROLLER_HEADERS,
    ENGINEER_HEADERS,
    ERR_REMEDY_OPTION_MISMATCH,
    RESERVE_CONTROLLER_USER_ID,
    assert_pagination_meta,
    create_family,
    create_field_action,
    create_period,
    create_remedy_option,
    create_service_contract,
    create_vintage,
    generate_rollforward,
    is_iso8601_timestamp,
    lock_period,
    move_clock,
    patch_family,
    read_family,
    read_field_action,
    read_period,
    read_service_contract,
    read_vintage,
    select_remedy,
    submit_field_action,
    success_data,
    validate_error,
    validate_paginated,
)


def _submitted_action(api, family_id, action_code, start_date, end_date, unit_count):
    """One campaign priced at a single approved option and pushed to SUBMITTED."""
    action = create_field_action(
        api,
        family_id,
        action_code=action_code,
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date=start_date,
        affected_build_end_date=end_date,
        affected_unit_count=unit_count,
    )
    option = create_remedy_option(
        api,
        action["id"],
        option_code=f"OPT-{action_code}",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=1000,
        labor_hours_centi=100,
        admin_cost_cents=200,
        expected_take_rate_bps=10000,
        is_engineering_approved=True,
    )
    select_remedy(
        api,
        action["id"],
        remedy_option_id=option["id"],
        expected_field_action_version=action["version"],
    )
    return submit_field_action(api, action["id"])


def test_a_partial_family_update_rewrites_only_the_keys_it_carries(api):
    """Four untouched attributes keep their registered values across the update.

    PRD §3.2: "An update accepts any of `name`, `base_warranty_months`,
    `standard_cost_per_claim_cents`, `engineering_estimate_rate_ppm`, `analog_family_id` and
    `reserve_cap_cents`; it re-derives the family's history maturity, re-derives its
    `reserve_posture` against whatever ceiling `reserve_cap_cents` now holds, and advances the
    family's `version` by 1." `family_code` is not in that list. PRD §2.4: "`updated_at` is an
    ISO 8601 UTC timestamp in the same format recording the most recent mutation of the row."

    Design: Corner/endpoints/corner_patch_product_family_updates_only_supplied_fields
    """
    family = create_family(
        api,
        family_code="FAM-PT",
        name="Patch Target Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
        engineering_estimate_rate_ppm=5000,
    )

    patched = patch_family(
        api,
        family["id"],
        {"name": "Patch Target Platform Rev B", "reserve_cap_cents": 22000000},
    )

    assert patched["name"] == "Patch Target Platform Rev B"
    assert patched["reserve_cap_cents"] == 22000000
    assert patched["base_warranty_months"] == 24
    assert patched["standard_cost_per_claim_cents"] == 12000
    assert patched["engineering_estimate_rate_ppm"] == 5000
    assert patched["analog_family_id"] is None
    assert patched["family_code"] == "FAM-PT"
    assert patched["version"] == 2
    assert is_iso8601_timestamp(patched["updated_at"])
    assert patched["updated_at"] >= patched["created_at"]
    assert patched["launch_date"] == "2024-01-01"


def test_the_field_action_listing_composes_its_state_filter_with_paging(api):
    """total_count counts the filtered set, and has_more flips on the last page.

    PRD §3.5: "Field actions can be listed filtered by `family_id`, by
    `selected_remedy_option_id`, by `approved_period_id` or by `approval_state`." PRD §2.3:
    "The `meta` object of a list response carries `limit` and `offset` as applied to the query,
    `total_count` as the number of rows matching the filters before pagination is applied, and
    `has_more` as a boolean that is true exactly when rows matching the filters remain beyond
    the returned page."

    Design: Corner/endpoints/corner_list_field_actions_filters_by_approval_state_with_paging
    """
    family = create_family(
        api,
        family_code="FAM-LF",
        name="List Filter Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )
    first = _submitted_action(api, family["id"], "FA-LF-01", "2025-01-01", "2025-01-31", 100)
    second = _submitted_action(api, family["id"], "FA-LF-02", "2025-06-01", "2025-06-30", 200)
    draft = create_field_action(
        api,
        family["id"],
        action_code="FA-LF-03",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-11-01",
        affected_build_end_date="2025-11-30",
        affected_unit_count=300,
    )

    page_one, meta_one = validate_paginated(
        api.list_field_actions(
            CONTROLLER_HEADERS,
            family_id=family["id"],
            approval_state="SUBMITTED",
            limit=1,
            offset=0,
        )
    )
    assert len(page_one) == 1
    assert_pagination_meta(meta_one, limit=1, offset=0, total_count=2, has_more=True)

    page_two, meta_two = validate_paginated(
        api.list_field_actions(
            CONTROLLER_HEADERS,
            family_id=family["id"],
            approval_state="SUBMITTED",
            limit=1,
            offset=1,
        )
    )
    assert len(page_two) == 1
    assert_pagination_meta(meta_two, limit=1, offset=1, total_count=2, has_more=False)
    assert {page_one[0]["id"], page_two[0]["id"]} == {first["id"], second["id"]}

    drafts, meta_draft = validate_paginated(
        api.list_field_actions(
            CONTROLLER_HEADERS, family_id=family["id"], approval_state="DRAFT"
        )
    )
    assert meta_draft["total_count"] == 1
    assert drafts[0]["id"] == draft["id"]


def test_remedy_options_belong_to_the_action_they_were_minted_under(api):
    """The sub-resource listing is scoped, and a sibling's option cannot be selected.

    PRD §3.5: "Each option's `field_action_id` is taken from the parent action it is created
    under, and the candidates of one action can be listed on their own." The same subsection
    adds: "if the candidate's `field_action_id` is not this action, the request answers
    `ERR_REMEDY_OPTION_MISMATCH`", and the cost model gives each option's own figure:
    "multiply `labor_hours_centi` by the standard field labour rate of 9500 cents per hour ...
    divide by 100 ... Add `parts_cost_cents`, that per-unit labour cost, and
    `admin_cost_cents`."

    Design: Corner/endpoints/corner_remedy_options_are_scoped_to_their_field_action
    """
    family = create_family(
        api,
        family_code="FAM-RS",
        name="Remedy Scope Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )
    own_action = create_field_action(
        api,
        family["id"],
        action_code="FA-RS-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-01-31",
        affected_unit_count=100,
    )
    own_permanent = create_remedy_option(
        api,
        own_action["id"],
        option_code="OPT-RS-A",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=1000,
        labor_hours_centi=100,
        admin_cost_cents=200,
        expected_take_rate_bps=10000,
        is_engineering_approved=True,
    )
    own_interim = create_remedy_option(
        api,
        own_action["id"],
        option_code="OPT-RS-B",
        remedy_class="INTERIM_REPAIR",
        parts_cost_cents=0,
        labor_hours_centi=50,
        admin_cost_cents=100,
        expected_take_rate_bps=10000,
        is_engineering_approved=True,
    )
    sibling_action = create_field_action(
        api,
        family["id"],
        action_code="FA-RS-02",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-08-01",
        affected_build_end_date="2025-08-31",
        affected_unit_count=100,
    )
    sibling_option = create_remedy_option(
        api,
        sibling_action["id"],
        option_code="OPT-RS-C",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=5000,
        labor_hours_centi=100,
        admin_cost_cents=200,
        expected_take_rate_bps=10000,
        is_engineering_approved=True,
    )

    options, meta = validate_paginated(
        api.list_remedy_options(ENGINEER_HEADERS, own_action["id"])
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in options} == {own_permanent["id"], own_interim["id"]}
    assert sibling_option["id"] not in {row["id"] for row in options}

    validate_error(
        api.select_remedy(
            ENGINEER_HEADERS,
            own_action["id"],
            expected_field_action_version=own_action["version"],
            remedy_option_id=sibling_option["id"],
        ),
        ERR_REMEDY_OPTION_MISMATCH,
        expected_status=422,
    )

    untouched = read_field_action(api, own_action["id"])
    assert untouched["selected_remedy_option_id"] is None
    assert untouched["version"] == 1

    interim = [row for row in options if row["id"] == own_interim["id"]][0]
    assert interim["field_action_id"] == own_action["id"]
    assert interim["expected_take_rate_bps"] == 10000


def test_an_empty_period_produces_an_all_zero_rollforward(api):
    """With no source rows every movement figure and both balances read zero.

    PRD §3.9: "`beginning_balance_cents` is that prior snapshot's `ending_balance_cents`, or 0
    when no such prior snapshot exists", and the ending balance ties out as
    "`beginning_balance_cents` plus `accruals_cents` plus `campaign_accruals_cents` plus
    `changes_in_estimate_cents`, minus `claims_paid_cents`, plus `supplier_recoveries_cents`."
    The same subsection adds: "Generating a snapshot also flips the period's
    `rollforward_generated` to true and advances the period's `version` by 1."

    Design: Corner/endpoints/corner_get_rollforward_returns_an_all_zero_snapshot_for_an_empty_period
    """
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    lock_period(api, period["id"])
    generated = generate_rollforward(api, period["id"])

    snapshot = success_data(api.get_rollforward(ACTUARY_HEADERS, generated["id"]))

    assert snapshot["id"] == generated["id"]
    assert snapshot["period_id"] == period["id"]
    assert snapshot["beginning_balance_cents"] == 0
    assert snapshot["accruals_cents"] == 0
    assert snapshot["campaign_accruals_cents"] == 0
    assert snapshot["changes_in_estimate_cents"] == 0
    assert snapshot["claims_paid_cents"] == 0
    assert snapshot["supplier_recoveries_cents"] == 0
    assert snapshot["ending_balance_cents"] == 0
    assert snapshot["significant_exposure_count"] == 0
    assert snapshot["generated_by_user_id"] == RESERVE_CONTROLLER_USER_ID

    period_now = read_period(api, period["id"])
    assert period_now["rollforward_generated"] is True
    assert period_now["requires_significant_exposure_disclosure"] is False


def test_moving_the_clock_reclassifies_exposure_and_expires_the_contract(api):
    """One clock call retires a cohort and saturates a contract's recognition.

    PRD §2.5: "Moving the clock is not a passive act — it is the trigger for every
    time-dependent recomputation in the system, evaluated in this order. Each production
    vintage's `exposure_status` is recomputed against the new instant ... Every extended
    service contract still in `ACTIVE` status has its `months_elapsed`,
    `recognized_revenue_cents` and `deferred_revenue_cents` recomputed at the new clock
    position, and any such contract whose recomputed `months_elapsed` has reached or passed
    its `term_months` auto-transitions from `ACTIVE` to `EXPIRED`." PRD §3.6: "Clamp that count
    to be no less than 0 and no greater than `term_months`", and at expiry
    "`recognized_revenue_cents` equals `total_contract_price_cents` in full and
    `deferred_revenue_cents` is 0."

    Design: Corner/endpoints/corner_clock_endpoint_reclassifies_vintage_exposure_and_contract_status
    """
    family = create_family(
        api,
        family_code="FAM-CK",
        name="Clock Platform",
        launch_date="2025-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )
    vintage = create_vintage(
        api,
        family["id"],
        vintage_code="CK-MY2025",
        units_shipped=500,
        ship_period_code="2025-Q1",
        warranty_expiry_date="2026-12-31",
    )
    contract = create_service_contract(
        api,
        family["id"],
        contract_number="SC-CK-01",
        sold_date="2026-01-01",
        term_months=12,
        total_contract_price_cents=120000,
        recognition_method="STRAIGHT_LINE",
    )
    assert vintage["exposure_status"] == "ACTIVE"
    assert contract["status"] == "ACTIVE"
    assert contract["months_elapsed"] == 7
    assert contract["recognized_revenue_cents"] == 70000

    move_clock(api, "2027-03-01T00:00:00Z")

    assert read_vintage(api, vintage["id"])["exposure_status"] == "EXPIRED"

    expired = read_service_contract(api, contract["id"])
    assert expired["status"] == "EXPIRED"
    assert expired["months_elapsed"] == 12
    assert expired["recognized_revenue_cents"] == 120000
    assert expired["deferred_revenue_cents"] == 0

    _, meta = validate_paginated(
        api.list_vintages(ANALYST_HEADERS, exposure_status="ACTIVE")
    )
    assert meta["total_count"] == 0


def test_reselecting_a_remedy_leaves_no_residue_of_the_prior_choice(api):
    """Each selection replaces the link, re-prices the campaign and bumps the token.

    PRD §3.5: "A successful selection writes `selected_remedy_option_id`, recomputes the
    selected option's `per_unit_expected_cents` and the action's `specific_accrual_cents`, and
    advances the action's `version` by 1. A new selection supersedes any prior one outright ...
    From `DRAFT` the action stays in `DRAFT` — a self-loop that lets the engineer re-price
    freely before submitting." PRD §2.10 keeps the ledger out of it: "field actions in
    `DRAFT`, `SUBMITTED` or `REJECTED` contribute nothing to the approved campaign total".

    Design: Corner/endpoints/corner_explicit_reselection_supersedes_the_prior_remedy_choice
    """
    family = create_family(
        api,
        family_code="FAM-RE",
        name="Reselect Platform",
        launch_date="2024-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=12000,
        reserve_cap_cents=15000000,
    )
    action = create_field_action(
        api,
        family["id"],
        action_code="FA-RE-01",
        action_type="SERVICE_CAMPAIGN",
        affected_build_start_date="2025-01-01",
        affected_build_end_date="2025-01-31",
        affected_unit_count=500,
    )
    cheap = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-RE-CHEAP",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=1000,
        labor_hours_centi=100,
        admin_cost_cents=500,
        expected_take_rate_bps=10000,
        is_engineering_approved=True,
    )
    rich = create_remedy_option(
        api,
        action["id"],
        option_code="OPT-RE-RICH",
        remedy_class="PERMANENT_REPAIR",
        parts_cost_cents=4000,
        labor_hours_centi=100,
        admin_cost_cents=500,
        expected_take_rate_bps=10000,
        is_engineering_approved=True,
    )

    expensive_choice = select_remedy(
        api, action["id"], remedy_option_id=rich["id"], expected_field_action_version=1
    )
    assert expensive_choice["selected_remedy_option_id"] == rich["id"]
    assert expensive_choice["specific_accrual_cents"] == 7000000
    assert expensive_choice["version"] == 2
    assert expensive_choice["approval_state"] == "DRAFT"

    cheap_choice = select_remedy(
        api,
        action["id"],
        remedy_option_id=cheap["id"],
        expected_field_action_version=expensive_choice["version"],
    )
    assert cheap_choice["selected_remedy_option_id"] == cheap["id"]
    assert cheap_choice["specific_accrual_cents"] == 5500000
    assert cheap_choice["version"] == 3
    assert cheap_choice["approval_state"] == "DRAFT"

    assert read_family(api, family["id"])["warranty_reserve_balance_cents"] == 0
