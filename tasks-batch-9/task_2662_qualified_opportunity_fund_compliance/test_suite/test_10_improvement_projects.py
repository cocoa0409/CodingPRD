"""Substantial improvement: the aggregation variant and the closed-window geometry."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_fund_aggregates,
    assert_ledger_fields,
    assert_money,
    assert_percent,
)
from test_helpers.factories import (
    create_improvement_project_payload,
    create_project_expenditure_payload,
)
from test_helpers.fixtures import (
    add_project_expenditure,
    evaluate_improvement_project,
    make_fund_asset,
    make_improvement_project,
    make_self_certified_fund,
    read_fund,
    read_fund_asset,
    read_improvement_project,
    set_clock,
)
from test_helpers.test_users import (
    MANAGER_HEADERS,
    OTHER_FUND_MANAGER_USER_ID,
    OTHER_MANAGER_HEADERS,
)


def _four_asset_group_fund(api):
    """Four used-property assets: two improved alone, two pooled under one key."""
    fund = make_self_certified_fund(api)
    assets = [
        make_fund_asset(
            api,
            fund["id"],
            acquisition_date="2026-01-01T00:00:00Z",
            unadjusted_cost_basis=500000.00,
            afs_fair_value=500000.00,
            original_use_in_zone=False,
        )
        for _ in range(4)
    ]
    solo_high = make_improvement_project(
        api,
        assets[0]["id"],
        window_start="2026-01-01T00:00:00Z",
        aggregation_method="ASSET_BY_ASSET",
    )
    solo_low = make_improvement_project(
        api,
        assets[1]["id"],
        window_start="2026-01-01T00:00:00Z",
        aggregation_method="ASSET_BY_ASSET",
    )
    pooled_high = make_improvement_project(
        api,
        assets[2]["id"],
        window_start="2026-01-01T00:00:00Z",
        aggregation_method="AGGREGATED_GROUP",
        group_key="GRP-NORTH",
    )
    pooled_low = make_improvement_project(
        api,
        assets[3]["id"],
        window_start="2026-01-01T00:00:00Z",
        aggregation_method="AGGREGATED_GROUP",
        group_key="GRP-NORTH",
    )
    for project, amount in (
        (solo_high, 600000.00),
        (solo_low, 450000.00),
        (pooled_high, 600000.00),
        (pooled_low, 450000.00),
    ):
        add_project_expenditure(
            api,
            project["id"],
            project["version"],
            amount=amount,
            expenditure_kind="CAPITALIZED_IMPROVEMENT",
        )
    return {
        "fund": fund,
        "assets": assets,
        "solo_high": solo_high,
        "solo_low": solo_low,
        "pooled_high": pooled_high,
        "pooled_low": pooled_low,
    }


def test_the_asset_by_asset_variant_leaves_the_thinner_project_short(api):
    """
    "Under `ASSET_BY_ASSET`, `qualified_additions_total` is just that figure and the
    denominator is the project's own `basis_at_acquisition`." "project B with a
    `basis_at_acquisition` of 500000.00 and additions of 450000.00 reaches only
    90.0000 percent and lapses when its window closes."

    Design: Difficulty/dual_variant_calc/substantial_improvement_aggregation_variant_divergence
    """
    context = _four_asset_group_fund(api)

    evaluated = evaluate_improvement_project(api, context["solo_low"]["id"])

    assert evaluated["status"] == "OPEN"
    assert_money(
        evaluated["qualified_additions_total"], 450000.00, "qualified_additions_total"
    )
    assert_money(evaluated["basis_at_acquisition"], 500000.00, "basis_at_acquisition")
    assert_percent(evaluated["improvement_ratio_pct"], 90.0000, "improvement_ratio_pct")
    assert evaluated["evaluated_at"].startswith("2026-08-01T00:00:00")
    asset_after = read_fund_asset(api, context["assets"][1]["id"])
    assert asset_after["status"] == "IMPROVING"
    assert asset_after["qualification"] == "IMPROVEMENT_PENDING"


def test_pooling_the_identical_rows_under_one_group_key_satisfies_both(api):
    """
    "Pool the identical expenditure rows under one `group_key` and both projects read
    1050000.00 over 1000000.00, or 105.0000 percent, so project B is satisfied
    instead of lapsed." "Under `AGGREGATED_GROUP`, satisfaction is collective: every
    sibling project sharing the `group_key` that is still `OPEN` is also set to
    `SATISFIED`, and each of their assets is promoted the same way."

    Design: Difficulty/dual_variant_calc/substantial_improvement_aggregation_variant_divergence
    """
    context = _four_asset_group_fund(api)

    evaluated = evaluate_improvement_project(api, context["pooled_low"]["id"])

    assert evaluated["status"] == "SATISFIED"
    assert_money(
        evaluated["qualified_additions_total"], 1050000.00, "qualified_additions_total"
    )
    assert_percent(evaluated["improvement_ratio_pct"], 105.0000, "improvement_ratio_pct")
    sibling = read_improvement_project(api, context["pooled_high"]["id"])
    assert sibling["status"] == "SATISFIED"
    for index in (2, 3):
        asset_after = read_fund_asset(api, context["assets"][index]["id"])
        assert asset_after["status"] == "HELD"
        assert asset_after["qualification"] == "QUALIFIED"
    fund_after = read_fund(api, context["fund"]["id"])
    assert_fund_aggregates(
        fund_after,
        aggregate_asset_basis=2000000.00,
        aggregate_qualified_basis=1000000.00,
    )


def _satisfied_project_asset(api):
    """One used-property asset carried through a satisfied 30-month window."""
    fund = make_self_certified_fund(api)
    asset = make_fund_asset(
        api,
        fund["id"],
        acquisition_date="2026-01-01T00:00:00Z",
        unadjusted_cost_basis=500000.00,
        afs_fair_value=500000.00,
        original_use_in_zone=False,
    )
    project = make_improvement_project(
        api,
        asset["id"],
        window_start="2026-01-01T00:00:00Z",
        aggregation_method="ASSET_BY_ASSET",
    )
    add_project_expenditure(
        api,
        project["id"],
        project["version"],
        amount=600000.00,
        expenditure_kind="CAPITALIZED_IMPROVEMENT",
    )
    return fund, asset, project


def test_a_window_starting_on_the_previous_window_s_last_day_collides(api):
    """
    "`window_end` is computed as `window_start` advanced by exactly 30 calendar months
    and is an exclusive upper bound." "Because both endpoints are inclusive, adjacency
    is **rejected**: a new window whose `window_start` equals an existing window's last
    day collides. Any such collision yields `ERR_IMPROVEMENT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/improvement_window_closed_interval_adjacency_collides
    """
    _fund, asset, project = _satisfied_project_asset(api)
    assert project["window_end"].startswith("2028-07-01T00:00:00")

    evaluated = evaluate_improvement_project(api, project["id"])
    assert evaluated["status"] == "SATISFIED"
    assert_money(
        evaluated["qualified_additions_total"], 600000.00, "qualified_additions_total"
    )
    assert_money(evaluated["basis_at_acquisition"], 500000.00, "basis_at_acquisition")
    assert_percent(evaluated["improvement_ratio_pct"], 120.0000, "improvement_ratio_pct")
    asset_after = read_fund_asset(api, asset["id"])
    assert asset_after["status"] == "HELD"
    assert asset_after["qualification"] == "QUALIFIED"

    response = api.create_improvement_project(
        create_improvement_project_payload(
            asset["id"],
            window_start="2028-06-30T00:00:00Z",
            aggregation_method="ASSET_BY_ASSET",
        ),
        MANAGER_HEADERS,
    )
    validate_error(response, ApiErrorId.IMPROVEMENT_WINDOW_OVERLAP.value, 409)


def test_a_window_starting_on_the_exclusive_upper_bound_is_accepted(api):
    """
    "The new project's closed window runs from `window_start` through `window_end`
    minus one day, inclusive at both ends, and it must not intersect the equally
    closed window of any existing project on the same `fund_asset_id` whose `status`
    is `OPEN` or `SATISFIED`." "Opening the project snapshots `basis_at_acquisition`
    from the asset's current `unadjusted_cost_basis`, creates the project `OPEN` with
    `qualified_additions_total` at 0.00, `improvement_ratio_pct` at 0.0000 and
    `evaluated_at` empty, and moves the owning asset `HELD → IMPROVING` with
    `qualification` `IMPROVEMENT_PENDING`."

    Design: Difficulty/resource_temporal_overlap/improvement_window_closed_interval_adjacency_collides
    """
    _fund, asset, project = _satisfied_project_asset(api)
    evaluate_improvement_project(api, project["id"])

    response = api.create_improvement_project(
        create_improvement_project_payload(
            asset["id"],
            window_start="2028-07-01T00:00:00Z",
            aggregation_method="ASSET_BY_ASSET",
        ),
        MANAGER_HEADERS,
    )
    successor = validate_success(response, 201)

    assert successor["status"] == "OPEN"
    assert successor["window_end"].startswith("2031-01-01T00:00:00")
    assert_percent(successor["improvement_ratio_pct"], 0.0000, "improvement_ratio_pct")
    assert_money(
        successor["qualified_additions_total"], 0.00, "qualified_additions_total"
    )
    assert not successor["evaluated_at"]
    asset_after = read_fund_asset(api, asset["id"])
    assert asset_after["status"] == "IMPROVING"
    assert asset_after["qualification"] == "IMPROVEMENT_PENDING"


def _used_property_project(api, name, basis=400000.00):
    """One used-property asset under a certified fund, with an open project."""
    fund = make_self_certified_fund(api, name=name)
    asset = make_fund_asset(
        api,
        fund["id"],
        asset_class="QOZ_BUSINESS_PROPERTY",
        acquisition_date="2026-01-05T00:00:00Z",
        unadjusted_cost_basis=basis,
        afs_fair_value=basis,
        original_use_in_zone=False,
    )
    project = make_improvement_project(
        api,
        asset["id"],
        window_start="2026-01-01T00:00:00Z",
        aggregation_method="ASSET_BY_ASSET",
    )
    return fund, asset, project


def test_a_capital_expenditure_is_written_once_and_never_versioned(api):
    """
    "Capital expenditures are the one exception. A `CapitalExpenditure` row is immutable
    once written and therefore carries only `id` and `created_at`: it has **no**
    `updated_at` and **no** `version` field." "The server stamps `spend_date` from the
    logical clock, sets the expenditure's `improvement_project_id` from the project it
    was filed against and leaves its `wcsh_plan_id` empty".

    Design: Corner/entities/capital_expenditure_is_immutable_ledger_row
    """
    _fund, _asset, project = _used_property_project(api, "Ledger Row Fund")

    response = api.create_project_expenditure(
        project["id"],
        create_project_expenditure_payload(
            project["version"],
            amount=125000.50,
            expenditure_kind="CAPITALIZED_IMPROVEMENT",
        ),
        MANAGER_HEADERS,
    )
    expenditure = validate_success(response, 201)

    assert_ledger_fields(expenditure, "CapitalExpenditure")
    assert_money(expenditure["amount"], 125000.50, "amount")
    assert expenditure["expenditure_kind"] == "CAPITALIZED_IMPROVEMENT"
    assert expenditure["counts_toward_basis"] is True
    assert expenditure["spend_date"].startswith("2026-08-01T00:00:00")
    assert expenditure["improvement_project_id"] == project["id"]
    assert not expenditure["wcsh_plan_id"]
    assert read_improvement_project(api, project["id"])["version"] == 2


def test_the_running_total_is_correct_after_each_expenditure(api):
    """
    "Recording the spend recomputes the project's `qualified_additions_total` and
    `improvement_ratio_pct` and the asset's `adjusted_basis`, and increments the
    project's `version` by 1." "An asset's `adjusted_basis` is its
    `unadjusted_cost_basis` plus the sum of `amount` over every capital expenditure
    booked to an improvement project on that asset whose `counts_toward_basis` flag is
    true, to two decimal places."

    Design: Corner/calculations/improvement_project_running_total_after_second_expenditure
    """
    fund, asset, project = _used_property_project(
        api, "Running Total Fund", basis=500000.00
    )
    assert_money(project["basis_at_acquisition"], 500000.00, "basis_at_acquisition")
    assert project["version"] == 1

    add_project_expenditure(
        api,
        project["id"],
        project["version"],
        amount=200000.00,
        expenditure_kind="CAPITALIZED_IMPROVEMENT",
    )
    midway = read_improvement_project(api, project["id"])
    assert_money(
        midway["qualified_additions_total"], 200000.00, "qualified_additions_total"
    )
    assert_percent(midway["improvement_ratio_pct"], 40.0000, "improvement_ratio_pct")
    assert midway["status"] == "OPEN"
    assert midway["version"] == 2

    add_project_expenditure(
        api,
        project["id"],
        midway["version"],
        amount=300000.00,
        expenditure_kind="CAPITALIZED_IMPROVEMENT",
    )
    evaluated = evaluate_improvement_project(api, project["id"])

    assert_money(
        evaluated["qualified_additions_total"], 500000.00, "qualified_additions_total"
    )
    assert_percent(evaluated["improvement_ratio_pct"], 100.0000, "improvement_ratio_pct")
    assert evaluated["status"] == "SATISFIED"
    asset_after = read_fund_asset(api, asset["id"])
    assert asset_after["status"] == "HELD"
    assert asset_after["qualification"] == "QUALIFIED"
    assert_money(asset_after["adjusted_basis"], 1000000.00, "adjusted_basis")
    assert_fund_aggregates(
        read_fund(api, fund["id"]),
        aggregate_asset_basis=500000.00,
        aggregate_qualified_basis=500000.00,
    )


def test_the_same_expenditure_body_is_refused_once_the_window_has_closed(api):
    """
    "The logical clock must itself be inside the project's window — at or after
    `window_start` and strictly before `window_end` — or the request is rejected with
    `ERR_EXPENDITURE_OUTSIDE_WINDOW`."

    Design: Corner/validations/improvement_expenditure_after_window_close_rejected
    """
    _fund, asset, project = _used_property_project(
        api, "Window Close Fund", basis=500000.00
    )
    assert project["window_end"].startswith("2028-07-01T00:00:00")
    accepted = add_project_expenditure(
        api,
        project["id"],
        project["version"],
        amount=200000.00,
        expenditure_kind="CAPITALIZED_IMPROVEMENT",
    )
    assert accepted["counts_toward_basis"] is True
    assert accepted["spend_date"].startswith("2026-08-01T00:00:00")
    version_before = read_improvement_project(api, project["id"])["version"]

    set_clock(api, "2028-08-01T00:00:00Z")
    response = api.create_project_expenditure(
        project["id"],
        create_project_expenditure_payload(
            version_before,
            amount=200000.00,
            expenditure_kind="CAPITALIZED_IMPROVEMENT",
        ),
        MANAGER_HEADERS,
    )

    validate_error(response, ApiErrorId.EXPENDITURE_OUTSIDE_WINDOW.value, 422)
    after = read_improvement_project(api, project["id"])
    assert_money(
        after["qualified_additions_total"], 200000.00, "qualified_additions_total"
    )
    assert_percent(after["improvement_ratio_pct"], 40.0000, "improvement_ratio_pct")
    assert after["status"] == "OPEN"
    assert after["version"] == version_before
    assert_money(
        read_fund_asset(api, asset["id"])["adjusted_basis"], 700000.00, "adjusted_basis"
    )


def test_the_group_key_is_required_forbidden_and_confined_to_one_fund(api):
    """
    "The `group_key` is a self-referential handle that links sibling projects into one
    aggregation group, and it is 1 to 40 characters when present. It is **required** when
    `aggregation_method` is `AGGREGATED_GROUP` and **forbidden** when it is
    `ASSET_BY_ASSET`; furthermore, every project sharing a `group_key` must sit on assets
    belonging to the same fund. A missing key, a key on an asset-by-asset project, or a
    key shared across funds yields `ERR_AGGREGATION_GROUP_INVALID`."

    Design: Corner/errors/improvement_aggregation_group_key_invalid_rejected
    """
    fund_a = make_self_certified_fund(api, name="Group Fund A", entity_type="PARTNERSHIP")
    asset_a1 = make_fund_asset(
        api,
        fund_a["id"],
        acquisition_date="2026-01-05T00:00:00Z",
        unadjusted_cost_basis=400000.00,
        afs_fair_value=400000.00,
        original_use_in_zone=False,
    )
    asset_a2 = make_fund_asset(
        api,
        fund_a["id"],
        acquisition_date="2026-01-06T00:00:00Z",
        unadjusted_cost_basis=600000.00,
        afs_fair_value=600000.00,
        original_use_in_zone=False,
    )
    fund_b = make_self_certified_fund(
        api,
        name="Group Fund B",
        entity_type="CORPORATION",
        manager_user_id=OTHER_FUND_MANAGER_USER_ID,
    )
    asset_b1 = make_fund_asset(
        api,
        fund_b["id"],
        acquisition_date="2026-01-07T00:00:00Z",
        unadjusted_cost_basis=500000.00,
        afs_fair_value=500000.00,
        original_use_in_zone=False,
        headers=OTHER_MANAGER_HEADERS,
    )

    missing = api.create_improvement_project(
        create_improvement_project_payload(
            asset_a1["id"],
            window_start="2026-02-01T00:00:00Z",
            aggregation_method="AGGREGATED_GROUP",
        ),
        MANAGER_HEADERS,
    )
    forbidden = api.create_improvement_project(
        create_improvement_project_payload(
            asset_a1["id"],
            window_start="2026-02-01T00:00:00Z",
            aggregation_method="ASSET_BY_ASSET",
            group_key="GRP-2662-A",
        ),
        MANAGER_HEADERS,
    )
    validate_error(missing, ApiErrorId.AGGREGATION_GROUP_INVALID.value, 422)
    validate_error(forbidden, ApiErrorId.AGGREGATION_GROUP_INVALID.value, 422)

    first = validate_success(
        api.create_improvement_project(
            create_improvement_project_payload(
                asset_a1["id"],
                window_start="2026-02-01T00:00:00Z",
                aggregation_method="AGGREGATED_GROUP",
                group_key="GRP-2662-A",
            ),
            MANAGER_HEADERS,
        ),
        201,
    )
    assert_money(first["basis_at_acquisition"], 400000.00, "basis_at_acquisition")
    assert read_fund_asset(api, asset_a1["id"])["status"] == "IMPROVING"

    cross_fund = api.create_improvement_project(
        create_improvement_project_payload(
            asset_b1["id"],
            window_start="2026-02-01T00:00:00Z",
            aggregation_method="AGGREGATED_GROUP",
            group_key="GRP-2662-A",
        ),
        OTHER_MANAGER_HEADERS,
    )
    validate_error(cross_fund, ApiErrorId.AGGREGATION_GROUP_INVALID.value, 422)
    assert read_fund_asset(api, asset_b1["id"])["status"] == "HELD"

    sibling = validate_success(
        api.create_improvement_project(
            create_improvement_project_payload(
                asset_a2["id"],
                window_start="2026-02-01T00:00:00Z",
                aggregation_method="AGGREGATED_GROUP",
                group_key="GRP-2662-A",
            ),
            MANAGER_HEADERS,
        ),
        201,
    )
    assert sibling["group_key"] == "GRP-2662-A"
    assert_money(sibling["basis_at_acquisition"], 600000.00, "basis_at_acquisition")


def test_a_stale_expected_project_version_leaves_the_running_total_alone(api):
    """
    "Recording a capital expenditure against a substantial-improvement project requires
    `expected_project_version`, again as a mandatory body field, carrying the `version`
    the client last observed on that project." "A mismatch with the project's current
    `version` is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), and no
    expenditure is written."

    Design: Corner/complexity_layers/improvement_expenditure_stale_project_version_rejected
    """
    fund = make_self_certified_fund(api, name="OCC Project QOF")
    asset = make_fund_asset(
        api,
        fund["id"],
        acquisition_date="2026-01-05T00:00:00Z",
        unadjusted_cost_basis=500000.00,
        afs_fair_value=500000.00,
        original_use_in_zone=False,
    )
    project = make_improvement_project(
        api,
        asset["id"],
        window_start="2026-08-01T00:00:00Z",
        aggregation_method="ASSET_BY_ASSET",
    )
    assert_money(project["basis_at_acquisition"], 500000.00, "basis_at_acquisition")
    assert project["window_end"].startswith("2029-02-01T00:00:00")
    assert project["version"] == 1
    add_project_expenditure(
        api,
        project["id"],
        project["version"],
        amount=100000.00,
        expenditure_kind="CAPITALIZED_IMPROVEMENT",
    )

    stale = api.create_project_expenditure(
        project["id"],
        create_project_expenditure_payload(
            project["version"],
            amount=100000.00,
            expenditure_kind="CAPITALIZED_IMPROVEMENT",
        ),
        MANAGER_HEADERS,
    )

    validate_error(stale, ApiErrorId.STALE_PROJECT_VERSION.value, 412)
    midway = read_improvement_project(api, project["id"])
    assert midway["version"] == 2
    assert_money(
        midway["qualified_additions_total"], 100000.00, "qualified_additions_total"
    )
    assert_percent(midway["improvement_ratio_pct"], 20.0000, "improvement_ratio_pct")

    add_project_expenditure(
        api,
        project["id"],
        midway["version"],
        amount=100000.00,
        expenditure_kind="CAPITALIZED_IMPROVEMENT",
    )
    after = read_improvement_project(api, project["id"])
    assert after["version"] == 3
    assert_money(
        after["qualified_additions_total"], 200000.00, "qualified_additions_total"
    )
    assert_percent(after["improvement_ratio_pct"], 40.0000, "improvement_ratio_pct")
    assert after["status"] == "OPEN"
