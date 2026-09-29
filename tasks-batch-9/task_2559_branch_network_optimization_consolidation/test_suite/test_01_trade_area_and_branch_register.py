"""Trade-area registration, the branch register and their derived counters."""

from test_helpers import (
    APPROVER,
    NON_EXISTENT_UUID,
    OPS_ADMIN,
    STRATEGIST,
    ApiErrorId,
    api_client,
    assert_branch,
    assert_market_area,
    branch_payload,
    consolidation_case_payload,
    is_valid_uuid,
    market_area_payload,
    performance_snapshot_payload,
    read_branch,
    read_market,
    receiving_branch_payload,
    setup_market,
    setup_market_with_branches,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_01_registering_a_trade_area_derives_its_competitive_intensity():
    """A trade area with 60 rival branches over 240000 residents reports density 25 and
    the saturated tier, with every ledger counter still at its opening value.

    PRD: "`competitor_density_index` is the `competitor_branch_count` multiplied by 100000 and divided by the `population`, rounded half up to a whole number — that is, rival branches per hundred thousand residents."
    PRD: "A `branch_density_per_100k` of 30 or more makes the market `OVER_BRANCHED`; from 15 up to but not including 30 it is `SATURATED`; below 15 it is `UNDER_BRANCHED`."
    Design: Corner/entities/market_area_creation_returns_computed_density_and_saturation_tier
    """
    response = api_client.create_market_area(market_area_payload(), STRATEGIST)
    market = validate_success(response, expected_status=201)

    assert_market_area(market)
    assert market["competitor_density_index"] == 25
    assert market["own_branch_count"] == 0
    assert market["branch_density_per_100k"] == 25
    assert market["saturation_tier"] == "SATURATED"
    assert market["absorbed_deposits_cents"] == 0
    assert market["cumulative_runoff_deposits_cents"] == 0
    assert market["flagged_case_count"] == 0
    assert market["remediation_case_count"] == 0
    assert market["de_novo_hold"] is False
    assert market["version"] == 1
    assert is_valid_uuid(market["id"])
    assert "market_area" not in market["id"]


def test_02_a_branch_with_no_reporting_history_reads_back_unscored():
    """A freshly registered branch echoes its stored inputs and reports an unscored band
    with a null score, because no reporting period has been recorded against it.

    PRD: "A newly registered branch opens in `ACTIVE` status with `performance_band` set to `UNSCORED`, `snapshot_count` at zero, `transferred_in_deposits_cents` at zero, and `absorbing_branch_id`, `pre_close_deposits_cents` and `pre_close_fte_count` all null."
    PRD: "A branch with no snapshots at all is a fifth case — its `performance_band` reads `UNSCORED` and its `performance_score_bps` is null, because both variants are undefined over an empty history."
    Design: Corner/entities/branch_retrieval_returns_stored_inputs_and_unscored_band
    """
    market = setup_market()
    created = validate_success(
        api_client.create_branch(branch_payload(market["id"]), STRATEGIST),
        expected_status=201,
    )

    branch = validate_success(api_client.get_branch(created["id"], OPS_ADMIN))

    assert_branch(branch)
    assert branch["branch_code"] == "RB-101"
    assert branch["market_area_id"] == market["id"]
    assert branch["deposit_balance_cents"] == 4800000000
    assert branch["fte_count"] == 9
    assert branch["status"] == "ACTIVE"
    assert branch["absorbing_branch_id"] is None
    assert branch["performance_band"] == "UNSCORED"
    assert branch["performance_score_bps"] is None
    assert branch["snapshot_count"] == 0
    assert branch["transferred_in_deposits_cents"] == 0
    assert branch["pre_close_deposits_cents"] is None
    assert branch["pre_close_fte_count"] is None
    assert branch["version"] == 1


def test_03_the_branch_register_windows_in_creation_order():
    """Three branches in one trade area page two at a time: the first window carries the
    two oldest rows and flags more to come, the second carries the remaining row.

    PRD: "Unless a specific listing states otherwise, collections are ordered by `created_at` ascending."
    PRD: "For list responses the `meta` block carries `limit`, `offset`, `total_count` (the number of records matching the filter before the window is applied) and `has_more` (true when records remain beyond the current window)."
    Design: Corner/entities/branch_listing_paginates_with_total_count_and_has_more
    """
    ctx = setup_market_with_branches()
    validate_success(
        api_client.create_branch(
            branch_payload(
                ctx["market"]["id"],
                branch_code="RB-103",
                branch_type="LIMITED_SERVICE",
                tenure_class="LEASED",
                deposit_balance_cents=3200000000,
                monthly_transaction_count=2700,
                digital_adoption_bps=4900,
                annual_noninterest_expense_cents=26000000,
                annual_revenue_cents=30000000,
                fte_count=6,
                atm_count=1,
                opened_on="2011-05-20",
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )

    first_page, first_meta = validate_paginated(
        api_client.list_branches(
            OPS_ADMIN, {"market_area_id": ctx["market"]["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert [row["branch_code"] for row in first_page] == ["RB-101", "RB-102"]

    second_page, second_meta = validate_paginated(
        api_client.list_branches(
            OPS_ADMIN, {"market_area_id": ctx["market"]["id"], "limit": 2, "offset": 2}
        )
    )
    assert [row["branch_code"] for row in second_page] == ["RB-103"]
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2


def test_04_reading_a_branch_that_was_never_registered_is_a_not_found():
    """A well-formed identifier that names no branch is refused rather than answered with
    an empty body.

    PRD: "Nested paths are resolved strictly left to right."
    PRD: "The `message` provides a human-readable explanation of what went wrong."
    Design: Corner/entities/get_branch_with_unknown_id_returns_not_found
    """
    error = validate_error(
        api_client.get_branch(NON_EXISTENT_UUID, OPS_ADMIN),
        ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
    )

    assert error["message"]
    assert "branch_code" not in error


def test_05_registering_a_branch_without_a_tenure_form_is_malformed():
    """Tenure is a required input with no declared default, so omitting it is refused and
    the trade area's footprint counters do not move.

    PRD: "Required fields must be present, enum fields must carry a declared member, integers must satisfy their declared ranges, dates must be ISO 8601, distance and mileage values must carry at most one decimal place, and `limit` must fall in 1 through 100."
    PRD: "Two further inputs are optional: `scoring_variant`, which defaults to `TRAILING_BLEND`, and `onboarding_capacity_households_per_day`, which defaults to 40 and must be at least 1."
    Design: Corner/entities/branch_creation_missing_tenure_class_returns_invalid_request
    """
    market = setup_market()
    payload = branch_payload(market["id"])
    payload.pop("tenure_class")

    validate_error(
        api_client.create_branch(payload, STRATEGIST),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    after = read_market(market["id"])
    assert after["own_branch_count"] == 0
    assert after["branch_density_per_100k"] == 25


def test_06_registering_a_branch_applies_the_two_declared_optional_defaults():
    """Leaving the scoring instrument and the onboarding capacity unspecified yields the
    declared defaults rather than nulls.

    PRD: "Two further inputs are optional: `scoring_variant`, which defaults to `TRAILING_BLEND`, and `onboarding_capacity_households_per_day`, which defaults to 40 and must be at least 1."
    Design: Corner/entities/branch_creation_omitting_optional_inputs_applies_declared_defaults
    """
    market = setup_market()

    branch = validate_success(
        api_client.create_branch(branch_payload(market["id"]), STRATEGIST),
        expected_status=201,
    )

    assert branch["scoring_variant"] == "TRAILING_BLEND"
    assert branch["onboarding_capacity_households_per_day"] == 40
    assert branch["status"] == "ACTIVE"


def test_07_a_client_supplied_composite_score_does_not_survive_the_formula():
    """A reporting period that smuggles its own composite score still stores the four-factor
    result, and the branch takes that computed figure as its score.

    PRD: "Concretely: multiply the deposit factor by 3500, the transaction factor by 2000, the digital factor by 1500 and the profitability factor by 3000, add the four products, divide the sum by 10000, and round half up."
    PRD: "It increments the branch's `snapshot_count` by one, refreshes the branch's `performance_score_bps` and `performance_band`, and increments the branch's `version` by one."
    Design: Corner/entities/performance_snapshot_composite_score_extra_field_input_ignored
    """
    market = setup_market()
    branch = validate_success(
        api_client.create_branch(branch_payload(market["id"]), STRATEGIST),
        expected_status=201,
    )

    snapshot = validate_success(
        api_client.create_performance_snapshot(
            branch["id"],
            performance_snapshot_payload(composite_score_bps=9900),
            STRATEGIST,
        ),
        expected_status=201,
    )

    assert snapshot["composite_score_bps"] == 4535
    assert snapshot["band"] == "STABLE"

    scored = read_branch(branch["id"])
    assert scored["performance_score_bps"] == 4535
    assert scored["performance_band"] == "STABLE"
    assert scored["snapshot_count"] == 1


def test_08_opening_a_case_stamps_its_author_from_the_acting_identity():
    """The case records the acting strategist as its author, leaves the decider unset and
    opens on every declared governance default.

    PRD: "The case is created in `DRAFT` status with `created_by_user_id` stamped from the acting strategist's `X-User-ID`, `decided_by_user_id` null, `returned_count` at zero, `governance_flag` at `NONE`, `impact_tier` at `UNASSESSED`, `notice_required_days` at zero, `monitoring_posture` at `NOT_STARTED`, `last_observed_month_index` at zero, `cumulative_variance_bps` at zero, and every savings, forecast and staffing counter at zero."
    PRD: "Two inputs are optional: `retention_model_variant`, which defaults to `DISTANCE_DECAY`, and `receiving_branch_id`."
    Design: Corner/entities/case_creation_stamps_created_by_user_id_from_header
    """
    ctx = setup_market_with_branches()

    case = validate_success(
        api_client.create_consolidation_case(
            consolidation_case_payload(
                ctx["closing_branch"]["id"],
                ctx["closing_branch"]["version"],
                receiving_branch_id=ctx["receiving_branch"]["id"],
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )

    assert case["created_by_user_id"] == STRATEGIST["X-User-ID"]
    assert case["decided_by_user_id"] is None
    assert case["status"] == "DRAFT"
    assert case["version"] == 1
    assert case["retention_model_variant"] == "DISTANCE_DECAY"
    assert case["governance_flag"] == "NONE"
    assert case["impact_tier"] == "UNASSESSED"
    assert case["monitoring_posture"] == "NOT_STARTED"
    assert case["notice_required_days"] == 0
    assert case["returned_count"] == 0


def test_09_a_region_code_that_breaks_the_declared_pattern_is_malformed():
    """A region code carrying one digit instead of two is refused and no trade area is
    persisted.

    PRD: "A `NetworkStrategist` or a `NetworkOpsAdmin` registers a **MarketArea** by supplying its `name`, a `region_code` matching two uppercase letters, a hyphen and two digits, the resident `population` (at least 1000), the `median_household_income_cents`, the total addressable `deposit_market_total_cents`, the `competitor_branch_count` of rival-bank branches inside the area, the projected five-year `household_growth_pct_bps` (from -2000 through 5000 basis points), and the `digital_penetration_bps` share of area households using digital banking (0 through 10000 basis points)."
    Design: Corner/entities/market_area_region_code_pattern_violation_returns_invalid_request
    """
    validate_error(
        api_client.create_market_area(
            market_area_payload(region_code="MD-1"), STRATEGIST
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _, meta = validate_paginated(api_client.list_market_areas(STRATEGIST))
    assert meta["total_count"] == 0


def test_10_an_undeclared_rationale_code_is_malformed_and_leaves_the_branch_active():
    """A rationale outside the declared set is refused, and the closing branch never takes
    the under-review side effect.

    PRD: "The creator names the `closing_branch_id`, a `rationale_code` of `LOW_PERFORMANCE`, `LEASE_EXPIRY`, `MARKET_OVERLAP` or `DIGITAL_MIGRATION`, a `planned_closure_date` in year-month-day form, and the `expected_branch_version` described in section 2.6."
    PRD: "Required fields must be present, enum fields must carry a declared member, integers must satisfy their declared ranges, dates must be ISO 8601, distance and mileage values must carry at most one decimal place, and `limit` must fall in 1 through 100."
    Design: Corner/entities/case_creation_with_unknown_rationale_code_returns_invalid_enum
    """
    ctx = setup_market_with_branches()

    validate_error(
        api_client.create_consolidation_case(
            consolidation_case_payload(
                ctx["closing_branch"]["id"],
                ctx["closing_branch"]["version"],
                rationale_code="PERFORMANCE",
                receiving_branch_id=ctx["receiving_branch"]["id"],
            ),
            STRATEGIST,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    branch = read_branch(ctx["closing_branch"]["id"])
    assert branch["status"] == "ACTIVE"
    assert branch["version"] == ctx["closing_branch"]["version"]


def test_11_a_recorded_reporting_period_carries_no_version_or_update_stamp():
    """A branch's performance history is an append-only record: each period exposes its
    identifier and creation stamp and nothing that implies it can be rewritten.

    PRD: "A `PerformanceSnapshot` and a `DepositObservation` each expose only `id` and `created_at`; both `updated_at` and `version` are absent from their representations, because neither resource is ever modified after it is written."
    PRD: "The resulting **PerformanceSnapshot** is immutable: it records the scored branch in its `branch_id`, is never edited or deleted, and never drops out of the branch's scoring history."
    Design: Corner/entities/performance_snapshot_is_immutable_with_no_version_field
    """
    market = setup_market()
    branch = validate_success(
        api_client.create_branch(branch_payload(market["id"]), STRATEGIST),
        expected_status=201,
    )
    snapshot = validate_success(
        api_client.create_performance_snapshot(
            branch["id"], performance_snapshot_payload(), STRATEGIST
        ),
        expected_status=201,
    )

    rows, meta = validate_paginated(
        api_client.list_branch_performance_snapshots(
            branch["id"], APPROVER, {"limit": 10, "offset": 0}
        )
    )

    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(rows) == 1
    assert rows[0]["id"] == snapshot["id"]
    assert rows[0]["created_at"]
    assert "version" not in rows[0]
    assert "updated_at" not in rows[0]
    assert "version" not in snapshot
    assert "updated_at" not in snapshot


def test_12_registering_a_branch_under_an_unknown_trade_area_is_a_referenced_not_found():
    """The trade area is a body foreign key, so an unresolvable value reports the referenced
    failure rather than the path-parameter one.

    PRD: "Foreign keys supplied in a request body are a separate concern: a body identifier such as `market_area_id`, `closing_branch_id`, `receiving_branch_id`, `target_branch_id`, `consolidation_case_id` or `de_novo_plan_id` that does not resolve to a stored resource yields `ERR_REFERENCED_RESOURCE_NOT_FOUND` (HTTP 404), which is a distinct code from the path-parameter failure."
    Design: Corner/entities/branch_creation_with_unknown_market_area_returns_referenced_not_found
    """
    validate_error(
        api_client.create_branch(branch_payload(NON_EXISTENT_UUID), OPS_ADMIN),
        ApiErrorId.ERR_REFERENCED_RESOURCE_NOT_FOUND.value,
    )

    _, meta = validate_paginated(api_client.list_branches(OPS_ADMIN))
    assert meta["total_count"] == 0


def test_13_naming_a_survivor_from_another_trade_area_is_an_illegal_pairing():
    """Both branches resolve, but the named survivor sits in a different trade area, so the
    pairing is refused and no case is opened.

    PRD: "When `receiving_branch_id` is supplied it must be a legal pairing: it may not equal `closing_branch_id`, and the named branch must belong to the closing branch's trade area."
    PRD: "A violation of either condition is `ERR_RECEIVING_BRANCH_INVALID`."
    Design: Corner/entities/case_receiving_branch_from_another_market_rejected
    """
    home = setup_market()
    away = setup_market(
        name="Northgate",
        region_code="VA-03",
        population=100000,
        median_household_income_cents=6000000,
        deposit_market_total_cents=400000000000,
        competitor_branch_count=28,
        household_growth_pct_bps=150,
        digital_penetration_bps=4800,
    )
    closing = validate_success(
        api_client.create_branch(branch_payload(home["id"]), STRATEGIST),
        expected_status=201,
    )
    outsider = validate_success(
        api_client.create_branch(
            receiving_branch_payload(away["id"], branch_code="NG-201"), STRATEGIST
        ),
        expected_status=201,
    )

    validate_error(
        api_client.create_consolidation_case(
            consolidation_case_payload(
                closing["id"],
                closing["version"],
                rationale_code="MARKET_OVERLAP",
                receiving_branch_id=outsider["id"],
            ),
            STRATEGIST,
        ),
        ApiErrorId.ERR_RECEIVING_BRANCH_INVALID.value,
    )

    unchanged = read_branch(closing["id"])
    assert unchanged["status"] == "ACTIVE"
    assert unchanged["version"] == closing["version"]
    _, meta = validate_paginated(api_client.list_consolidation_cases(STRATEGIST))
    assert meta["total_count"] == 0


def test_14_a_branch_code_is_unique_across_the_whole_network():
    """Re-using a branch code in a second trade area is still a uniqueness violation, and
    the rejected registration runs no footprint side effect.

    PRD: "The creator supplies the `market_area_id`, a `branch_code` matching two uppercase letters, a hyphen and three digits and unique across the entire network, a `branch_type` of `FULL_SERVICE`, `LIMITED_SERVICE` or `DRIVE_UP`, a `tenure_class` of `LEASED` or `OWNED`, the current `deposit_balance_cents` on book, the `monthly_transaction_count` covering teller plus drive-up activity, the `digital_adoption_bps` share of the branch's households active in digital channels, the `annual_noninterest_expense_cents`, the `annual_revenue_cents` attributed to the branch, the staffed `fte_count`, the installed `atm_count`, and the `opened_on` date in year-month-day form."
    PRD: "The `name` must be unique within its `region_code`; a repeat is rejected with `ERR_DUPLICATE_KEY`."
    Design: Corner/validations/duplicate_branch_code_rejected_with_duplicate_key
    """
    first = setup_market()
    second = setup_market(
        name="Crown Heights",
        region_code="MD-02",
        population=100000,
        median_household_income_cents=12000000,
        deposit_market_total_cents=435000000000,
        competitor_branch_count=28,
        household_growth_pct_bps=500,
        digital_penetration_bps=6000,
    )
    validate_success(
        api_client.create_branch(branch_payload(first["id"]), STRATEGIST),
        expected_status=201,
    )

    validate_error(
        api_client.create_branch(
            branch_payload(
                second["id"],
                branch_type="LIMITED_SERVICE",
                tenure_class="OWNED",
                deposit_balance_cents=2000000000,
                monthly_transaction_count=3000,
                digital_adoption_bps=5000,
                annual_noninterest_expense_cents=20000000,
                annual_revenue_cents=25000000,
                fte_count=5,
                atm_count=1,
                opened_on="2016-01-04",
            ),
            STRATEGIST,
        ),
        ApiErrorId.ERR_DUPLICATE_KEY.value,
    )

    untouched = read_market(second["id"])
    assert untouched["own_branch_count"] == 0
    assert untouched["branch_density_per_100k"] == 28

    validate_error(
        api_client.create_market_area(market_area_payload(), STRATEGIST),
        ApiErrorId.ERR_DUPLICATE_KEY.value,
    )
    validate_success(
        api_client.create_market_area(
            market_area_payload(region_code="MD-02"), STRATEGIST
        ),
        expected_status=201,
    )


def test_15_a_request_without_an_acting_identity_is_unauthenticated():
    """Both headers are required together, so a valid role with no acting identity — and an
    identity carrying a role the API does not declare — both fail authentication.

    PRD: "1. **Header presence and role validity** — `ERR_UNAUTHENTICATED`."
    PRD: "The server evaluates guards in one fixed global order and returns the first failure it encounters; it never masks an earlier-ranked failure behind a later-ranked one."
    Design: Corner/validations/list_market_areas_missing_x_user_id_header_returns_unauthenticated
    """
    validate_error(
        api_client.list_market_areas({"X-User-Role": "NetworkStrategist"}),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    validate_error(
        api_client.list_market_areas(
            {"X-User-ID": STRATEGIST["X-User-ID"], "X-User-Role": "Auditor"}
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )


def test_16_a_page_size_outside_the_inclusive_range_is_malformed():
    """The window size is bounded at both ends: 100 is accepted, 101 and 0 are refused
    rather than silently clamped.

    PRD: "`limit` defaults to 10, accepts a minimum of 1 and a maximum of 100, and a value outside that inclusive range is a malformed request."
    Design: Corner/validations/list_market_areas_with_limit_above_maximum_returns_invalid_request
    """
    validate_error(
        api_client.list_market_areas(STRATEGIST, {"limit": 101}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )
    validate_error(
        api_client.list_market_areas(STRATEGIST, {"limit": 0}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    _, meta = validate_paginated(api_client.list_market_areas(STRATEGIST, {"limit": 100}))
    assert meta["limit"] == 100


def test_17_the_footprint_counters_resync_as_each_branch_is_registered():
    """In a thin market the density walks 28 to 29 to 30 as two branches are registered, and
    the tier flips over-branched exactly at the inclusive boundary of 30.

    PRD: "The tier is re-derived, together with `own_branch_count` and `branch_density_per_100k`, on every event that moves a branch into or out of those four counted statuses — branch registration, de novo opening, closure execution and closure unwind alike."
    PRD: "Both boundaries are inclusive at their lower edge, so a density of exactly 30 is `OVER_BRANCHED` and a density of exactly 15 is `SATURATED`."
    Design: Corner/state_machines/market_own_branch_count_and_tier_resync_on_branch_creation
    """
    market = validate_success(
        api_client.create_market_area(
            market_area_payload(
                name="Northgate",
                region_code="VA-03",
                population=100000,
                median_household_income_cents=6000000,
                deposit_market_total_cents=400000000000,
                competitor_branch_count=28,
                household_growth_pct_bps=150,
                digital_penetration_bps=4800,
            ),
            OPS_ADMIN,
        ),
        expected_status=201,
    )
    assert market["competitor_density_index"] == 28

    validate_success(
        api_client.create_branch(
            branch_payload(market["id"], branch_code="NG-201"), OPS_ADMIN
        ),
        expected_status=201,
    )
    after_first = validate_success(api_client.get_market_area(market["id"], OPS_ADMIN))
    assert after_first["own_branch_count"] == 1
    assert after_first["branch_density_per_100k"] == 29
    assert after_first["saturation_tier"] == "SATURATED"
    assert after_first["competitor_density_index"] == 28
    assert after_first["de_novo_hold"] is False

    validate_success(
        api_client.create_branch(
            branch_payload(
                market["id"],
                branch_code="NG-202",
                branch_type="LIMITED_SERVICE",
                tenure_class="OWNED",
                deposit_balance_cents=3200000000,
                monthly_transaction_count=2700,
                digital_adoption_bps=4900,
                annual_noninterest_expense_cents=26000000,
                annual_revenue_cents=30000000,
                fte_count=6,
                atm_count=1,
                opened_on="2011-05-20",
            ),
            OPS_ADMIN,
        ),
        expected_status=201,
    )
    after_second = validate_success(api_client.get_market_area(market["id"], OPS_ADMIN))
    assert after_second["own_branch_count"] == 2
    assert after_second["branch_density_per_100k"] == 30
    assert after_second["saturation_tier"] == "OVER_BRANCHED"
    assert after_second["competitor_density_index"] == 28
    assert after_second["de_novo_hold"] is False


def test_18_every_derived_counter_is_current_on_the_very_next_read():
    """No polling and no second write: the read taken immediately after each registration
    already reports the new footprint, and the read after a reporting period already
    reports the branch's refreshed score.

    PRD: "Cascades are applied within the request that triggers them — this system has no deferred or eventual settlement — and a cascade that recomputes a figure recomputes it in full rather than adjusting it incrementally."
    PRD: "Registration increments the owning market's `own_branch_count` by one and re-derives `branch_density_per_100k` and `saturation_tier`."
    Design: Corner/consistency model/derived_market_counters_are_current_on_the_next_read_after_every_branch_write
    """
    market = setup_market()
    assert market["own_branch_count"] == 0
    assert market["branch_density_per_100k"] == 25
    assert market["saturation_tier"] == "SATURATED"

    closing = validate_success(
        api_client.create_branch(branch_payload(market["id"]), STRATEGIST),
        expected_status=201,
    )
    assert closing["performance_band"] == "UNSCORED"
    assert closing["performance_score_bps"] is None

    after_first = read_market(market["id"])
    assert after_first["own_branch_count"] == 1
    assert after_first["branch_density_per_100k"] == 25
    assert after_first["saturation_tier"] == "SATURATED"

    validate_success(
        api_client.create_branch(
            receiving_branch_payload(market["id"]), STRATEGIST
        ),
        expected_status=201,
    )
    after_second = read_market(market["id"])
    assert after_second["own_branch_count"] == 2
    assert after_second["branch_density_per_100k"] == 26
    assert after_second["saturation_tier"] == "SATURATED"

    snapshot = validate_success(
        api_client.create_performance_snapshot(
            closing["id"],
            performance_snapshot_payload(
                period_label="2026-Q2", period_end_date="2026-06-30"
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    assert snapshot["composite_score_bps"] == 4535

    scored = read_branch(closing["id"])
    assert scored["performance_score_bps"] == 4535
    assert scored["performance_band"] == "STABLE"
    assert scored["snapshot_count"] == 1
