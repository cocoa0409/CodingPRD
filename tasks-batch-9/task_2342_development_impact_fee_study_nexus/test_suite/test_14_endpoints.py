"""Reads and writes whose contract is their shape: the derived category read, the
honest sweep report, the partial component patch, and the schedule sub-resource
that answers only for the component it was addressed to."""

from test_helpers import assertions as check
from test_helpers import constants as K
from test_helpers import factories, fixtures, get_success_data, validate_paginated
from test_helpers import validate_success
from test_helpers.fixtures import ADMIN, ANALYST, CLERK

SWEEP_BEFORE_ANY_DEADLINE = "2026-06-01T00:00:00Z"
SWEEP_ONE_WINDOW_BEFORE_DEADLINE = "2030-05-10T00:00:00Z"
PATCHED_GROWTH_SHARE_BP = 7000
PATCHED_ROADS_COST_PER_UNIT = 270133


def test_the_category_read_reports_its_derived_fund_and_demand_totals(api):
    """On a `FacilityCategory`, `fund_balance_cents` is the sum of `amount_cents`
    over its `COLLECTION` ledger rows less the sum over its `EXPENDITURE` rows less
    the sum over its `REFUND` rows; `refund_due_cents` is the sum of
    `unexpended_cents` over its rows whose `entry_status` is `REFUND_DUE`;
    `oldest_unexpended_vintage_at` is the earliest `vintage_at` among its
    `COLLECTION` rows whose `entry_status` is `OPEN`, `PARTIALLY_EXPENDED` or
    `REFUND_DUE`, and is null when no such row exists; `committed_demand_units` is
    the sum of `demand_units` over the assessed lines naming this category on
    applications whose `assessment_status` is `ASSESSED` or `REASSESSED`; and
    `deferred_receivable_cents` is the sum of `line_net_cents` for this category
    over applications whose `collection_status` is `DEFERRED` or `DELINQUENT`.
    `unit_cost_cents` is the cost of one facility unit — one acre of park, one lane
    mile of arterial — and must be strictly positive. Three collections
    deliberately depart from that default and their ordering is part of their
    contract: the program's facility standards come back ordered by `code`
    ascending, a component's fee schedule lines come back ordered by
    `land_use_category` ascending, and the fund ledger comes back ordered by
    `vintage_at` ascending with `created_at` ascending as the tie-break — the same
    order the expenditure sweep consumes money in.

    Design: Corner/endpoints/category_read_reports_derived_fund_and_demand_totals
    """
    chain = fixtures.effective_program_with_paid_application(api)

    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ANALYST))

    check.assert_category_fund(
        parks,
        fund_balance_cents=K.BASELINE_PARKS_LINE_NET,
        refund_due_cents=0,
        fund_posture=K.FUND_POSTURE_COMPLIANT,
        committed_demand_units=K.BASELINE_PARKS_DEMAND_UNITS,
        deferred_receivable_cents=0,
        oldest_unexpended_vintage_at=K.CLOCK_PAYMENT,
    )
    check.assert_four_decimal_equals(
        parks["existing_los_per_demand_unit"], K.PARKS_EXISTING_LOS, "existing_los_per_demand_unit"
    )
    check.assert_four_decimal_equals(
        parks["planned_los_per_demand_unit"], K.PARKS_PLANNED_LOS, "planned_los_per_demand_unit"
    )
    assert parks["unit_cost_cents"] == K.PARKS_UNIT_COST_CENTS
    check.assert_four_decimal_equals(
        parks["existing_deficiency_demand_units"], 0.0, "existing_deficiency_demand_units"
    )

    rows, meta = validate_paginated(
        api.list_program_facility_categories(
            chain.program_id,
            ANALYST,
            {"fund_posture": K.FUND_POSTURE_COMPLIANT, "limit": 10, "offset": 0},
        )
    )

    check.assert_pagination_meta(meta, limit=10, offset=0, total_count=2, has_more=False)
    assert [row["code"] for row in rows] == [K.PARKS_CODE, K.ROADS_CODE]
    roads = rows[1]
    check.assert_category_fund(
        roads,
        fund_balance_cents=K.BASELINE_ROADS_LINE_NET,
        fund_posture=K.FUND_POSTURE_COMPLIANT,
        committed_demand_units=K.BASELINE_ROADS_DEMAND_UNITS,
    )
    reread = get_success_data(api.get_facility_category(chain.parks_category_id, ANALYST))
    check.assert_version_advanced_by(parks["version"], reread["version"], 0)
    roads_reread = get_success_data(api.get_facility_category(chain.roads_category_id, ANALYST))
    check.assert_version_advanced_by(roads["version"], roads_reread["version"], 0)


def test_the_sweep_reports_nothing_until_a_deadline_comes_into_view(api):
    """The deadline sweep is the `ProgramAdministrator`'s statutory clock run over
    an entire program, and it does three things in one pass: it converts every
    `COLLECTION` row whose `deadline_at` the clock has reached into `REFUND_DUE`; it
    defaults every `EXECUTED` deferral agreement whose `due_at` the clock has
    reached, moving its application to `DELINQUENT` and adding the default penalty
    to `net_due_cents` as described in §3.8; and it recomputes every category's
    `refund_due_cents` and `fund_posture`. It reports what it did as
    `refund_due_entry_ids` and `refund_due_entry_count`, `defaulted_agreement_ids`,
    `delinquent_application_ids`, `at_risk_category_ids` and
    `refund_due_category_ids`. Both comparisons are inclusive at the boundary, and
    that boundary is pinned: with a five-year deadline and a 365-day at-risk window,
    a collection vintaged 10 May 2026 has a deadline of 10 May 2031, so a sweep on 9
    May 2030 leaves the fund `COMPLIANT`, a sweep on 10 May 2030 makes it `AT_RISK`
    because the deadline falls exactly one window out, a sweep on 9 May 2031 leaves
    it `AT_RISK`, and a sweep on 10 May 2031 breaches the row exactly on its
    deadline, turning it `REFUND_DUE` and blocking further expenditure from that
    fund.

    Design: Corner/endpoints/deadline_sweep_returns_empty_arrays_when_nothing_is_due
    """
    chain = fixtures.effective_program_with_paid_application(api)
    fixtures.set_clock(api, SWEEP_BEFORE_ANY_DEADLINE)

    quiet = fixtures.sweep(api, chain.program_id)

    assert quiet["refund_due_entry_ids"] == []
    assert quiet["refund_due_entry_count"] == 0
    assert quiet["defaulted_agreement_ids"] == []
    assert quiet["delinquent_application_ids"] == []
    assert quiet["at_risk_category_ids"] == []
    assert quiet["refund_due_category_ids"] == []
    for category_id in (chain.parks_category_id, chain.roads_category_id):
        category = get_success_data(api.get_facility_category(category_id, ADMIN))
        assert category["fund_posture"] == K.FUND_POSTURE_COMPLIANT
        row = fixtures.collection_rows_for(api, category_id)[0]
        assert row["entry_status"] == K.ENTRY_OPEN
        check.assert_money_equals(
            row["unexpended_cents"], row["amount_cents"], "unexpended_cents"
        )

    fixtures.set_clock(api, SWEEP_ONE_WINDOW_BEFORE_DEADLINE)
    at_risk = fixtures.sweep(api, chain.program_id)

    assert sorted(at_risk["at_risk_category_ids"]) == sorted(
        [chain.parks_category_id, chain.roads_category_id]
    )
    assert at_risk["refund_due_entry_count"] == 0
    assert at_risk["refund_due_entry_ids"] == []
    assert at_risk["defaulted_agreement_ids"] == []
    assert at_risk["delinquent_application_ids"] == []
    assert at_risk["refund_due_category_ids"] == [], "being at risk is not a refund obligation"
    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(
        parks, refund_due_cents=0, fund_posture=K.FUND_POSTURE_AT_RISK
    )
    parks_row = fixtures.collection_rows_for(api, chain.parks_category_id)[0]
    assert parks_row["entry_status"] == K.ENTRY_OPEN
    check.assert_money_equals(
        parks_row["unexpended_cents"], K.BASELINE_PARKS_LINE_NET, "unexpended_cents"
    )


def test_patching_one_input_leaves_the_other_ten_exactly_as_they_were(api):
    """A `NexusAnalyst` may patch any of a component's projection or cost inputs —
    `horizon_start_year`, `horizon_end_year`, `projected_new_dwelling_units`,
    `projected_new_nonres_sqft`, `demand_units_per_dwelling`,
    `demand_units_per_1000_nonres_sqft`, `planned_facility_cost_cents`,
    `planned_growth_share_bp`, `planned_capacity_demand_units`,
    `planned_other_funding_cents` and `existing_tax_credit_per_unit_cents` — and at
    least one of them must be present in the body, or the request is a schema
    violation. On a component that has never been allocated — `allocation_status`
    `PENDING` — the revision is quiet. The patched inputs are stored,
    `growth_demand_units` is recomputed, the component's `version` increments, and
    the state re-enters `PENDING`. Multiply `planned_facility_cost_cents` by
    `planned_growth_share_bp` divided by ten thousand and round that product half up
    to whole cents; subtract `planned_other_funding_cents` from it to get the net
    growth cost. Divide that net growth cost by the smaller of `growth_demand_units`
    and `planned_capacity_demand_units`, and round the quotient half up to whole
    cents.

    Design: Corner/endpoints/component_patch_updates_only_the_supplied_field
    """
    fixtures.set_clock(api, K.CLOCK_PROGRAM_SETUP)
    program = fixtures.create_program(api)
    roads_category = fixtures.create_roads_category(api, program["id"])
    study = fixtures.create_study(api, program["id"])
    component = fixtures.create_roads_component(api, study["id"], roads_category["id"])
    assert component["allocation_status"] == K.ALLOCATION_PENDING

    patched = validate_success(
        api.patch_nexus_component(
            component["id"], {"planned_growth_share_bp": PATCHED_GROWTH_SHARE_BP}, ANALYST
        )
    )

    assert patched["planned_growth_share_bp"] == PATCHED_GROWTH_SHARE_BP
    assert patched["horizon_start_year"] == 2026
    assert patched["horizon_end_year"] == 2030
    assert patched["projected_new_dwelling_units"] == 1200
    assert patched["projected_new_nonres_sqft"] == 200000
    check.assert_four_decimal_equals(
        patched["demand_units_per_dwelling"], 1.01, "demand_units_per_dwelling"
    )
    check.assert_four_decimal_equals(
        patched["demand_units_per_1000_nonres_sqft"],
        3.75,
        "demand_units_per_1000_nonres_sqft",
    )
    assert patched["planned_facility_cost_cents"] == 900000000
    assert patched["planned_other_funding_cents"] == 100000000
    check.assert_four_decimal_equals(
        patched["planned_capacity_demand_units"], 2000.0, "planned_capacity_demand_units"
    )
    assert patched["existing_tax_credit_per_unit_cents"] == 0
    check.assert_four_decimal_equals(
        patched["growth_demand_units"], K.ROADS_GROWTH_DEMAND_UNITS, "growth_demand_units"
    )
    assert patched["allocation_status"] == K.ALLOCATION_PENDING, "a quiet revision, not a cascade"
    check.assert_fields_null(patched, "allocated_at")
    check.assert_version_advanced_by(component["version"], patched["version"], 1)

    allocated = fixtures.allocate(api, component["id"])

    check.assert_money_equals(
        allocated["plan_based_cost_per_unit_cents"],
        PATCHED_ROADS_COST_PER_UNIT,
        "plan_based_cost_per_unit_cents",
    )
    check.assert_money_equals(
        allocated["adopted_cost_per_unit_cents"],
        PATCHED_ROADS_COST_PER_UNIT,
        "adopted_cost_per_unit_cents",
    )
    check.assert_money_equals(
        allocated["standard_based_cost_per_unit_cents"],
        K.ROADS_STANDARD_BASED_COST_PER_UNIT,
        "standard_based_cost_per_unit_cents",
    )
    check.assert_four_decimal_equals(
        allocated["nexus_ratio"], K.ROADS_NEXUS_RATIO, "nexus_ratio"
    )


def test_each_component_answers_only_for_its_own_schedule_line(api):
    """A `NexusAnalyst` adopts one `FeeScheduleItem` per land use class on each
    component, supplying the `land_use_category`, the `unit_basis` and the
    `conversion_factor`; the line records the component it prices for as
    `nexus_component_id`. `land_use_category` is one of `SINGLE_FAMILY`,
    `MULTI_FAMILY`, `RETAIL`, `OFFICE` or `INDUSTRIAL`, and a component may carry at
    most one line per land use class — a second attempt returns
    `ERR_DUPLICATE_SCHEDULE_ITEM`. The line's `fee_per_unit_cents` is the
    component's `adopted_cost_per_unit_cents` multiplied by the `conversion_factor`,
    rounded half up to whole cents, and rounded exactly once. A parks component
    adopting 101,667 cents per demand unit with a single-family conversion factor of
    2.5000 stores 254,168 cents per dwelling — the unrounded 254,167.5 rounds up —
    and with a multi-family factor of 1.8000 stores 183,001 cents. A roads component
    adopting 247,197 cents per demand unit stores 249,669 cents for a single-family
    factor of 1.0100 and 1,606,781 cents for a retail factor of 6.5000.

    Design: Corner/endpoints/schedule_items_are_scoped_to_their_own_component
    """
    chain = fixtures.program_with_categories(api)
    study = fixtures.create_study(api, chain.program_id)
    parks_component = fixtures.create_parks_component(
        api, study["id"], chain.parks_category_id
    )
    roads_component = fixtures.create_roads_component(
        api, study["id"], chain.roads_category_id
    )
    fixtures.allocate(api, parks_component["id"])
    fixtures.allocate(api, roads_component["id"])

    parks_line = validate_success(
        api.create_fee_schedule_item(
            parks_component["id"],
            factories.schedule_item_payload(
                conversion_factor=K.PARKS_SINGLE_FAMILY_CONVERSION_FACTOR
            ),
            ANALYST,
        ),
        201,
    )
    roads_line = validate_success(
        api.create_fee_schedule_item(
            roads_component["id"],
            factories.schedule_item_payload(
                conversion_factor=K.ROADS_SINGLE_FAMILY_CONVERSION_FACTOR
            ),
            ANALYST,
        ),
        201,
    )

    assert parks_line["nexus_component_id"] == parks_component["id"]
    check.assert_money_equals(
        parks_line["fee_per_unit_cents"],
        K.PARKS_SINGLE_FAMILY_FEE_PER_UNIT,
        "fee_per_unit_cents",
    )
    assert roads_line["nexus_component_id"] == roads_component["id"]
    check.assert_money_equals(
        roads_line["fee_per_unit_cents"],
        K.ROADS_SINGLE_FAMILY_FEE_PER_UNIT,
        "fee_per_unit_cents",
    )
    assert parks_line["schedule_status"] == K.SCHEDULE_VALID
    assert roads_line["schedule_status"] == K.SCHEDULE_VALID

    parks_rows, parks_meta = validate_paginated(
        api.list_fee_schedule_items(
            parks_component["id"],
            CLERK,
            {"schedule_status": K.SCHEDULE_VALID, "limit": 10, "offset": 0},
        )
    )
    roads_rows, roads_meta = validate_paginated(
        api.list_fee_schedule_items(roads_component["id"], CLERK, {"limit": 10, "offset": 0})
    )

    check.assert_pagination_meta(parks_meta, total_count=1, has_more=False)
    assert [row["id"] for row in parks_rows] == [parks_line["id"]]
    check.assert_pagination_meta(roads_meta, total_count=1, has_more=False)
    assert [row["id"] for row in roads_rows] == [roads_line["id"]]
    for component_id in (parks_component["id"], roads_component["id"]):
        component = get_success_data(api.get_nexus_component(component_id, CLERK))
        assert component["allocation_status"] == K.ALLOCATION_VALID
