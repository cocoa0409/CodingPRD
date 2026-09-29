"""The working capital safe harbour: pacing tolerance, aggregate capacity, blowout."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_business_test_prongs,
    assert_fund_aggregates,
    assert_money,
)
from test_helpers.factories import (
    create_wcsh_plan_payload,
    evaluate_checkpoint_payload,
    spend_schedule,
)
from test_helpers.fixtures import (
    activate_wcsh_plan,
    add_wcsh_expenditure,
    certify_business_test,
    evaluate_wcsh_checkpoint,
    list_plan_expenditures,
    make_active_wcsh_plan,
    make_business_test,
    make_fund_asset,
    make_qoz_business,
    make_self_certified_fund,
    make_wcsh_plan,
    measure_business_test,
    read_business_test,
    read_fund,
    read_fund_asset,
    read_qoz_business,
    read_wcsh_plan,
    set_clock,
)
from test_helpers.test_users import ADMIN_HEADERS, CERTIFIER_HEADERS, MANAGER_HEADERS, MEASURER_HEADERS


def _sheltered_business(api, fund_id, zone_tract_code, written_plan_reference):
    """A business with one ACTIVE plan covering 300000.00 over three months."""
    business = make_qoz_business(
        api,
        fund_id,
        zone_tract_code=zone_tract_code,
        declared_nqfp_amount=0.00,
        total_asset_value=1000000.00,
        total_tangible_property_basis=900000.00,
    )
    plan = make_active_wcsh_plan(
        api,
        business["id"],
        window_start="2026-01-01T00:00:00Z",
        covered_amount=300000.00,
        written_plan_reference=written_plan_reference,
        schedule_month_count=3,
        spend_schedule=spend_schedule(100000.00, 100000.00, 100000.00),
    )
    return business, plan


def test_a_pacing_shortfall_exactly_on_the_tolerance_survives(api):
    """
    "The tolerance is 10 percent of `required_cumulative`, rounded half up to two
    decimal places, and the comparison is **strictly greater than**: a plan whose
    shortfall lands exactly on the tolerance survives, and only a shortfall above it
    fails."

    Design: Difficulty/boundary_precision_check/wcsh_pacing_shortfall_exactly_at_tolerance_survives
    """
    fund = make_self_certified_fund(api)
    business, plan = _sheltered_business(api, fund["id"], "12345678904", "WCSH-TOL-A")
    add_wcsh_expenditure(
        api,
        plan["id"],
        amount=90000.00,
        expenditure_kind="OPERATING_WORKING_CAPITAL",
    )

    evaluated = evaluate_wcsh_checkpoint(api, plan["id"], 1)

    assert evaluated["status"] == "ACTIVE"
    assert_money(evaluated["pacing_shortfall"], 10000.00, "pacing_shortfall")
    assert_money(evaluated["spent_total"], 90000.00, "spent_total")
    assert_money(evaluated["unspent_amount"], 210000.00, "unspent_amount")
    assert evaluated["last_checkpoint_month_index"] == 1
    business_after = read_qoz_business(api, business["id"])
    assert_money(
        business_after["wcsh_protected_amount"], 210000.00, "wcsh_protected_amount"
    )
    assert_money(business_after["blown_unspent_amount"], 0.00, "blown_unspent_amount")
    assert_money(business_after["nqfp_amount"], 0.00, "nqfp_amount")


def test_a_pacing_shortfall_one_cent_above_the_tolerance_blows_the_plan(api):
    """
    "When `pacing_shortfall` exceeds the tolerance, the plan moves `ACTIVE → BLOWN`
    and a three-link cascade runs. First, the business's `wcsh_protected_amount` falls
    to exclude this plan while its `blown_unspent_amount` rises by the plan's
    `unspent_amount`, so `nqfp_amount` is recomputed upward."

    Design: Difficulty/boundary_precision_check/wcsh_pacing_shortfall_exactly_at_tolerance_survives
    """
    fund = make_self_certified_fund(api)
    business, plan = _sheltered_business(api, fund["id"], "12345678905", "WCSH-TOL-B")
    add_wcsh_expenditure(
        api,
        plan["id"],
        amount=89999.99,
        expenditure_kind="OPERATING_WORKING_CAPITAL",
    )

    evaluated = evaluate_wcsh_checkpoint(api, plan["id"], 1)

    assert evaluated["status"] == "BLOWN"
    assert_money(evaluated["pacing_shortfall"], 10000.01, "pacing_shortfall")
    assert_money(evaluated["spent_total"], 89999.99, "spent_total")
    assert_money(evaluated["unspent_amount"], 210000.01, "unspent_amount")
    assert evaluated["last_checkpoint_month_index"] == 1
    business_after = read_qoz_business(api, business["id"])
    assert_money(business_after["wcsh_protected_amount"], 0.00, "wcsh_protected_amount")
    assert_money(
        business_after["blown_unspent_amount"], 210000.01, "blown_unspent_amount"
    )
    assert_money(business_after["nqfp_amount"], 210000.01, "nqfp_amount")


def _capacity_business(api):
    """A business whose 0.31 aggregate shelter capacity is 310000.00."""
    fund = make_self_certified_fund(api)
    business = make_qoz_business(
        api,
        fund["id"],
        zone_tract_code="12345678906",
        declared_nqfp_amount=0.00,
        total_asset_value=1000000.00,
        total_tangible_property_basis=900000.00,
    )
    first = make_wcsh_plan(
        api,
        business["id"],
        window_start="2026-01-01T00:00:00Z",
        covered_amount=150000.00,
        written_plan_reference="WCSH-CAP-1",
        schedule_month_count=3,
        spend_schedule=spend_schedule(50000.00, 50000.00, 50000.00),
    )
    second = make_wcsh_plan(
        api,
        business["id"],
        window_start="2026-02-01T00:00:00Z",
        covered_amount=150000.00,
        written_plan_reference="WCSH-CAP-2",
        schedule_month_count=3,
        spend_schedule=spend_schedule(50000.00, 50000.00, 50000.00),
    )
    assert first["status"] == "DRAFT"
    assert second["status"] == "DRAFT"
    return business


def _list_business_plans(api, business_id):
    response = api.list_wcsh_plans(ADMIN_HEADERS, {"qoz_business_id": business_id, "limit": 100})
    return get_success_data(response)


def test_a_third_overlapping_plan_breaching_the_month_capacity_is_refused(api):
    """
    "It is an **aggregate-capacity** rule rather than a pairwise one: for every month
    covered by the new plan's window, the sum of `covered_amount` over that business's
    plans whose `status` is `DRAFT` or `ACTIVE` and whose window covers that same
    month, plus the new plan's own `covered_amount`, must be no greater than the
    business's `total_asset_value` multiplied by 0.31 and rounded half up to two
    decimal places. A breach in any covered month yields
    `ERR_WCSH_AGGREGATE_CAP_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/wcsh_aggregate_capacity_over_overlapping_plans
    """
    business = _capacity_business(api)

    response = api.create_wcsh_plan(
        create_wcsh_plan_payload(
            business["id"],
            window_start="2026-03-01T00:00:00Z",
            covered_amount=20000.00,
            written_plan_reference="WCSH-CAP-3-TOO-BIG",
            schedule_month_count=1,
            spend_schedule=spend_schedule(20000.00),
        ),
        MANAGER_HEADERS,
    )

    validate_error(response, ApiErrorId.WCSH_AGGREGATE_CAP_EXCEEDED.value, 422)
    assert len(_list_business_plans(api, business["id"])) == 2


def test_a_third_plan_landing_exactly_on_the_capacity_is_accepted(api):
    """
    "Because the test is a per-month sum rather than a pair test, a single overlapping
    pair can be perfectly legal while the addition of a third overlapping plan breaches
    the cap" "The plan is created `DRAFT` with `spent_total` at 0.00,
    `unspent_amount` equal to `covered_amount`, `last_checkpoint_month_index` at 0,
    `pacing_shortfall` at 0.00 and `overspill_amount` at 0.00."

    Design: Difficulty/resource_temporal_overlap/wcsh_aggregate_capacity_over_overlapping_plans
    """
    business = _capacity_business(api)
    api.create_wcsh_plan(
        create_wcsh_plan_payload(
            business["id"],
            window_start="2026-03-01T00:00:00Z",
            covered_amount=20000.00,
            written_plan_reference="WCSH-CAP-3-TOO-BIG",
            schedule_month_count=1,
            spend_schedule=spend_schedule(20000.00),
        ),
        MANAGER_HEADERS,
    )

    response = api.create_wcsh_plan(
        create_wcsh_plan_payload(
            business["id"],
            window_start="2026-03-01T00:00:00Z",
            covered_amount=10000.00,
            written_plan_reference="WCSH-CAP-4-EXACT",
            schedule_month_count=1,
            spend_schedule=spend_schedule(10000.00),
        ),
        MANAGER_HEADERS,
    )
    accepted = validate_success(response, 201)

    assert accepted["status"] == "DRAFT"
    assert accepted["schedule_month_count"] == 1
    assert accepted["documentation_complete"] is True
    assert_money(accepted["unspent_amount"], 10000.00, "unspent_amount")
    assert_money(accepted["spent_total"], 0.00, "spent_total")
    assert_money(accepted["pacing_shortfall"], 0.00, "pacing_shortfall")
    assert_money(accepted["overspill_amount"], 0.00, "overspill_amount")
    assert accepted["last_checkpoint_month_index"] == 0
    assert len(_list_business_plans(api, business["id"])) == 3
    business_after = read_qoz_business(api, business["id"])
    assert_money(business_after["wcsh_protected_amount"], 0.00, "wcsh_protected_amount")
    assert_money(business_after["nqfp_amount"], 0.00, "nqfp_amount")


def _measure_business_test_at(api, business_id, testing_date):
    """Open and measure a business test on the actual-gross-income branch."""
    test = make_business_test(api, business_id, testing_date=testing_date)
    measure_business_test(
        api,
        test["id"],
        MEASURER_HEADERS,
        safe_harbor_used="GROSS_INCOME_ACTUAL",
        gross_income_zone_amount=600000.00,
        gross_income_total_amount=1000000.00,
        intangibles_zone_use_amount=50000.00,
        intangibles_total_amount=100000.00,
        total_asset_value_measured=1000000.00,
    )
    return test


def _qualified_business_with_shelter(api):
    """A QUALIFIED business, an ACTIVE plan, and a later test left in MEASURED."""
    fund = make_self_certified_fund(api)
    business = make_qoz_business(
        api,
        fund["id"],
        zone_tract_code="12345678903",
        declared_nqfp_amount=0.00,
        total_asset_value=1000000.00,
        total_tangible_property_basis=900000.00,
    )
    equity = make_fund_asset(
        api,
        fund["id"],
        asset_class="QOZB_EQUITY",
        qoz_business_id=business["id"],
        acquisition_date="2026-01-15T00:00:00Z",
        unadjusted_cost_basis=900000.00,
        afs_fair_value=900000.00,
    )
    plan = make_active_wcsh_plan(
        api,
        business["id"],
        window_start="2026-01-01T00:00:00Z",
        covered_amount=300000.00,
        written_plan_reference="WCSH-PLAN-2026-A",
        schedule_month_count=3,
        spend_schedule=spend_schedule(100000.00, 100000.00, 100000.00),
    )
    passed_test = _measure_business_test_at(api, business["id"], "2026-03-31T00:00:00Z")
    certify_business_test(api, passed_test["id"], CERTIFIER_HEADERS)
    measured_test = _measure_business_test_at(
        api, business["id"], "2026-06-30T00:00:00Z"
    )
    return {
        "fund": fund,
        "business": business,
        "equity": equity,
        "plan": plan,
        "passed_test": passed_test,
        "measured_test": measured_test,
    }


def test_a_blown_plan_throws_the_sheltered_dollars_back_into_nqfp(api):
    """
    "`nqfp_amount` is the figure the test actually measures, and it is never the raw
    declaration. It is `declared_nqfp_amount`, plus `blown_unspent_amount`, minus
    `wcsh_protected_amount`, rounded half up to two decimal places and floored at 0.00
    so it can never go negative." "Sheltered dollars are therefore netted out while the
    shelter holds and thrown back in the moment it fails."

    Design: Difficulty/transitive_cascade/wcsh_blowout_disqualifies_business_chain
    """
    context = _qualified_business_with_shelter(api)
    assert read_qoz_business(api, context["business"]["id"])[
        "qualification_status"
    ] == "QUALIFIED"
    add_wcsh_expenditure(
        api,
        context["plan"]["id"],
        amount=20000.00,
        expenditure_kind="OPERATING_WORKING_CAPITAL",
    )

    evaluated = evaluate_wcsh_checkpoint(api, context["plan"]["id"], 3)

    assert evaluated["status"] == "BLOWN"
    assert_money(evaluated["spent_total"], 20000.00, "spent_total")
    assert_money(evaluated["unspent_amount"], 280000.00, "unspent_amount")
    assert_money(evaluated["pacing_shortfall"], 280000.00, "pacing_shortfall")
    assert evaluated["last_checkpoint_month_index"] == 3
    business_after = read_qoz_business(api, context["business"]["id"])
    assert_money(business_after["wcsh_protected_amount"], 0.00, "wcsh_protected_amount")
    assert_money(
        business_after["blown_unspent_amount"], 280000.00, "blown_unspent_amount"
    )
    assert_money(business_after["nqfp_amount"], 280000.00, "nqfp_amount")
    assert business_after["qualification_status"] == "DISQUALIFIED"


def test_the_blowout_re_derives_only_the_latest_measured_business_test(api):
    """
    "Second, because `nqfp_amount` rose, the business's latest `MEASURED` business
    test has its `nqfp_amount_measured`, `nqfp_pct` and `nqfp_prong` re-derived; if the
    recomputed `nqfp_pct` exceeds 5.0000 the business moves `QUALIFIED → DISQUALIFIED`".
    "Third, on the disqualifying branch only, every asset pointing at that business
    whose `status` is `HELD` or `IMPROVING` gets `qualification` `NONQUALIFIED` and the
    fund's `aggregate_qualified_basis` and `aggregate_qualified_afs_value` are
    recomputed."

    Design: Difficulty/transitive_cascade/wcsh_blowout_disqualifies_business_chain
    """
    context = _qualified_business_with_shelter(api)
    add_wcsh_expenditure(
        api,
        context["plan"]["id"],
        amount=20000.00,
        expenditure_kind="OPERATING_WORKING_CAPITAL",
    )

    evaluate_wcsh_checkpoint(api, context["plan"]["id"], 3)

    re_derived = read_business_test(api, context["measured_test"]["id"])
    assert re_derived["status"] == "MEASURED"
    assert_money(
        re_derived["nqfp_amount_measured"], 280000.00, "nqfp_amount_measured"
    )
    assert_business_test_prongs(re_derived, nqfp_pct=28.0000, nqfp_prong="FAIL")
    # The already-certified test is not rewritten.
    settled = read_business_test(api, context["passed_test"]["id"])
    assert settled["status"] == "PASSED"
    assert_business_test_prongs(settled, nqfp_pct=0.0000, nqfp_prong="PASS")
    equity_after = read_fund_asset(api, context["equity"]["id"])
    assert equity_after["qualification"] == "NONQUALIFIED"
    assert_fund_aggregates(
        read_fund(api, context["fund"]["id"]),
        aggregate_asset_basis=900000.00,
        aggregate_qualified_basis=0.00,
    )


def _declaring_business(api, fund_name, legal_name):
    """A business declaring 300000.00 of nonqualified financial property."""
    fund = make_self_certified_fund(api, name=fund_name, entity_type="PARTNERSHIP")
    business = make_qoz_business(
        api,
        fund["id"],
        legal_name=legal_name,
        zone_tract_code="12345678910",
        declared_nqfp_amount=300000.00,
        total_asset_value=1000000.00,
        total_tangible_property_basis=700000.00,
    )
    return fund, business


def _three_bucket_plan_payload_kwargs(written_plan_reference):
    return {
        "window_start": "2026-01-01T00:00:00Z",
        "covered_amount": 300000.00,
        "written_plan_reference": written_plan_reference,
        "schedule_month_count": 3,
        "spend_schedule": spend_schedule(100000.00, 100000.00, 100000.00),
    }


def test_activation_shelters_the_covered_dollars_and_sinks_the_nqfp_figure(api):
    """
    "The plan is created `DRAFT` with `spent_total` at 0.00, `unspent_amount` equal to
    `covered_amount`, `last_checkpoint_month_index` at 0, `pacing_shortfall` at 0.00 and
    `overspill_amount` at 0.00. No shelter is granted yet, because only `ACTIVE` plans
    count toward `wcsh_protected_amount`." "It moves the plan `DRAFT → ACTIVE`".
    "Activation raises the business's `wcsh_protected_amount` by `covered_amount` less
    `spent_total` and therefore recomputes `nqfp_amount` downward, which is the whole
    point of the harbor." "`window_end` is `window_start` advanced by exactly 31
    calendar months and is an exclusive upper bound."

    Design: Corner/state_machines/wcsh_plan_activate_moves_draft_to_active
    """
    _fund, business = _declaring_business(api, "Shelter Fund", "Shelter Operating LLC")
    assert_money(business["nqfp_amount"], 300000.00, "nqfp_amount")
    draft = make_wcsh_plan(
        api, business["id"], **_three_bucket_plan_payload_kwargs("WP-2662-SHELTER-1")
    )
    assert draft["documentation_complete"] is True
    assert draft["status"] == "DRAFT"
    assert_money(
        read_qoz_business(api, business["id"])["wcsh_protected_amount"],
        0.00,
        "wcsh_protected_amount",
    )

    activated = activate_wcsh_plan(api, draft["id"])

    assert activated["status"] == "ACTIVE"
    assert activated["version"] == 2
    assert activated["window_end"].startswith("2028-08-01T00:00:00")
    assert_money(activated["spent_total"], 0.00, "spent_total")
    assert_money(activated["unspent_amount"], 300000.00, "unspent_amount")
    assert activated["last_checkpoint_month_index"] == 0
    assert_money(activated["pacing_shortfall"], 0.00, "pacing_shortfall")
    after = read_qoz_business(api, business["id"])
    assert_money(after["wcsh_protected_amount"], 300000.00, "wcsh_protected_amount")
    assert_money(after["nqfp_amount"], 0.00, "nqfp_amount")
    assert_money(after["blown_unspent_amount"], 0.00, "blown_unspent_amount")
    assert after["qualification_status"] == "UNTESTED"


def test_a_land_acquisition_spend_never_enters_the_pacing_waterfall(api):
    """
    "The eligible spends are the plan's expenditures whose `expenditure_kind` is
    `OPERATING_WORKING_CAPITAL` or `CAPITALIZED_IMPROVEMENT` and whose `spend_date` lies
    at or after `window_start` and strictly before `window_end`; `LAND_ACQUISITION`
    spends and out-of-window spends are excluded from both `spent_total` and the
    waterfall entirely." "The expenditure's `wcsh_plan_id` is set from the plan it was
    filed against and its `improvement_project_id` is left empty."
    "`counts_toward_basis` is set true exactly when `expenditure_kind` is
    `CAPITALIZED_IMPROVEMENT` **and** `spend_date` falls inside the container's window;
    every other combination leaves it false."

    Design: Corner/calculations/wcsh_land_acquisition_expenditure_excluded_from_spent_total
    """
    _fund, business = _declaring_business(
        api, "Kind Filter Fund", "Kind Filter Operating LLC"
    )
    plan = make_active_wcsh_plan(
        api, business["id"], **_three_bucket_plan_payload_kwargs("WP-2662-KIND-1")
    )

    land = add_wcsh_expenditure(
        api, plan["id"], amount=50000.00, expenditure_kind="LAND_ACQUISITION"
    )

    assert not land["schedule_month_index"]
    assert land["counts_toward_basis"] is False
    after_land = read_wcsh_plan(api, plan["id"])
    assert_money(after_land["spent_total"], 0.00, "spent_total")
    assert_money(after_land["unspent_amount"], 300000.00, "unspent_amount")

    ops = add_wcsh_expenditure(
        api, plan["id"], amount=50000.00, expenditure_kind="OPERATING_WORKING_CAPITAL"
    )

    assert ops["schedule_month_index"] == 1
    final_plan = read_wcsh_plan(api, plan["id"])
    assert_money(final_plan["spent_total"], 50000.00, "spent_total")
    assert_money(final_plan["unspent_amount"], 250000.00, "unspent_amount")
    assert_money(final_plan["overspill_amount"], 0.00, "overspill_amount")
    assert final_plan["status"] == "ACTIVE"
    final_business = read_qoz_business(api, business["id"])
    assert_money(
        final_business["wcsh_protected_amount"], 250000.00, "wcsh_protected_amount"
    )
    assert_money(final_business["nqfp_amount"], 50000.00, "nqfp_amount")
    rows = {row["id"]: row for row in list_plan_expenditures(api, plan["id"])}
    assert set(rows) == {land["id"], ops["id"]}
    for row in rows.values():
        assert row["wcsh_plan_id"] == plan["id"]
        assert not row["improvement_project_id"]


def test_one_spend_fills_the_first_bucket_before_spilling_into_the_second(api):
    """
    "Each spend is poured into the earliest bucket that still has room — room being
    that bucket's `planned_amount` less what has already been filled into it, at two
    decimal places — and continues into successive buckets until the spend is exhausted
    or the buckets run out. The `schedule_month_index` recorded on the expenditure is
    the highest `month_index` its dollars actually reached. Whatever cannot be absorbed
    by any bucket accumulates into the plan's `overspill_amount` at two decimal places."
    "`pacing_shortfall` is `required_cumulative` less `actual_cumulative`, rounded half
    up to two decimal places and floored at 0.00."

    Design: Corner/calculations/wcsh_expenditure_fills_earliest_bucket_first
    """
    _fund, business = _declaring_business(
        api, "Waterfall Fund", "Waterfall Operating LLC"
    )
    plan = make_active_wcsh_plan(
        api, business["id"], **_three_bucket_plan_payload_kwargs("WP-2662-WATERFALL-1")
    )

    spend = add_wcsh_expenditure(
        api, plan["id"], amount=120000.00, expenditure_kind="OPERATING_WORKING_CAPITAL"
    )

    assert spend["schedule_month_index"] == 2
    assert spend["counts_toward_basis"] is False
    filled = read_wcsh_plan(api, plan["id"])
    assert_money(filled["overspill_amount"], 0.00, "overspill_amount")
    assert_money(filled["spent_total"], 120000.00, "spent_total")
    assert_money(filled["unspent_amount"], 180000.00, "unspent_amount")

    checkpoint = evaluate_wcsh_checkpoint(api, plan["id"], 1)

    assert_money(checkpoint["pacing_shortfall"], 0.00, "pacing_shortfall")
    assert checkpoint["status"] == "ACTIVE"
    assert checkpoint["last_checkpoint_month_index"] == 1
    after = read_qoz_business(api, business["id"])
    assert_money(after["wcsh_protected_amount"], 180000.00, "wcsh_protected_amount")
    assert_money(after["nqfp_amount"], 120000.00, "nqfp_amount")


def test_a_checkpoint_may_not_walk_backwards_or_past_the_last_bucket(api):
    """
    "The checkpoint is evaluated by the owning `FundManager` or a `ComplianceOfficer`
    at a `checkpoint_month_index`, which must be an integer from 1 through
    `schedule_month_count` and must be at least the plan's current
    `last_checkpoint_month_index` — checkpoints may repeat an index but may never walk
    backwards, and a violation yields `ERR_CHECKPOINT_INDEX_INVALID`."
    "a request that fails any check in §2.11 mutates nothing."

    Design: Corner/validations/checkpoint_month_index_must_not_regress_or_exceed_bound
    """
    _fund, business = _declaring_business(
        api, "Checkpoint Order Fund", "Checkpoint Operating LLC"
    )
    plan = make_active_wcsh_plan(
        api, business["id"], **_three_bucket_plan_payload_kwargs("WP-2662-CHECKPOINT-1")
    )
    spend = add_wcsh_expenditure(
        api, plan["id"], amount=300000.00, expenditure_kind="OPERATING_WORKING_CAPITAL"
    )
    assert spend["schedule_month_index"] == 3
    second = evaluate_wcsh_checkpoint(api, plan["id"], 2)
    assert_money(second["pacing_shortfall"], 0.00, "pacing_shortfall")
    assert second["status"] == "ACTIVE"
    assert second["last_checkpoint_month_index"] == 2

    regress = api.evaluate_wcsh_checkpoint(
        plan["id"], evaluate_checkpoint_payload(checkpoint_month_index=1), MANAGER_HEADERS
    )
    beyond = api.evaluate_wcsh_checkpoint(
        plan["id"], evaluate_checkpoint_payload(checkpoint_month_index=4), MANAGER_HEADERS
    )

    validate_error(regress, ApiErrorId.CHECKPOINT_INDEX_INVALID.value, 422)
    validate_error(beyond, ApiErrorId.CHECKPOINT_INDEX_INVALID.value, 422)
    after = read_wcsh_plan(api, plan["id"])
    assert after["last_checkpoint_month_index"] == 2
    assert_money(after["pacing_shortfall"], 0.00, "pacing_shortfall")
    assert after["status"] == "ACTIVE"
    assert_money(after["unspent_amount"], 0.00, "unspent_amount")


def test_a_short_schedule_is_refused_and_a_late_activation_finds_the_window_shut(api):
    """
    "That last equality is separately enforced at filing time: a schedule whose planned
    amounts do not sum to the covered amount is rejected with
    `ERR_WCSH_SCHEDULE_MISMATCH`." "`window_end` is `window_start` advanced by exactly 31
    calendar months and is an exclusive upper bound." "It moves the plan `DRAFT →
    ACTIVE`, requires `documentation_complete` to be true — otherwise
    `ERR_WCSH_PLAN_INCOMPLETE` — and requires the logical clock to sit at or after
    `window_start` and strictly before `window_end`, otherwise
    `ERR_WCSH_WINDOW_CLOSED`."

    Design: Corner/errors/wcsh_schedule_mismatch_and_closed_window_rejected
    """
    fund = make_self_certified_fund(
        api, name="WCSH Guard Fund", entity_type="PARTNERSHIP"
    )
    business = make_qoz_business(
        api,
        fund["id"],
        legal_name="Guard Operating LLC",
        zone_tract_code="12345678910",
        declared_nqfp_amount=100000.00,
        total_asset_value=2000000.00,
        total_tangible_property_basis=1500000.00,
    )

    mismatch = api.create_wcsh_plan(
        create_wcsh_plan_payload(
            business["id"],
            window_start="2026-01-01T00:00:00Z",
            covered_amount=300000.00,
            written_plan_reference="WP-2662-MISMATCH",
            schedule_month_count=3,
            spend_schedule=spend_schedule(100000.00, 100000.00, 50000.00),
        ),
        MANAGER_HEADERS,
    )

    validate_error(mismatch, ApiErrorId.WCSH_SCHEDULE_MISMATCH.value, 422)
    rows, meta = validate_paginated(
        api.list_wcsh_plans(
            ADMIN_HEADERS, {"limit": 100, "qoz_business_id": business["id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0, "the refused filing wrote no plan row"

    plan = validate_success(
        api.create_wcsh_plan(
            create_wcsh_plan_payload(
                business["id"],
                window_start="2026-01-01T00:00:00Z",
                covered_amount=300000.00,
                written_plan_reference="WP-2662-LATE",
                schedule_month_count=3,
                spend_schedule=spend_schedule(100000.00, 100000.00, 100000.00),
            ),
            MANAGER_HEADERS,
        ),
        201,
    )

    assert plan["documentation_complete"] is True
    assert plan["window_end"].startswith("2028-08-01T00:00:00")
    assert plan["status"] == "DRAFT"

    set_clock(api, "2028-09-01T00:00:00Z")
    closed = api.activate_wcsh_plan(plan["id"], {}, MANAGER_HEADERS)

    validate_error(closed, ApiErrorId.WCSH_WINDOW_CLOSED.value, 422)
    assert read_wcsh_plan(api, plan["id"])["status"] == "DRAFT"
    assert_money(
        read_qoz_business(api, business["id"])["wcsh_protected_amount"],
        0.00,
        "wcsh_protected_amount",
    )
