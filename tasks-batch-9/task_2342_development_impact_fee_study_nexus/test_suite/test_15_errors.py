"""Refusals that must name themselves precisely: four uniqueness scopes, the two
limbs of the unit-basis rule, the empty denominator, the missing schedule line, the
componentless study, the strict deferral due date, the unrefundable row and the
security that falls a cent short."""

from test_helpers import PERMIT_1, api_errors as err
from test_helpers import assertions as check
from test_helpers import constants as K
from test_helpers import factories, fixtures, get_success_data, validate_error
from test_helpers import validate_paginated, validate_success
from test_helpers.fixtures import ADMIN, ANALYST, DEVELOPER, FINANCE, PERMIT_OFFICER

RETAIL_CONVERSION_FACTOR = 6.5
DUE_AT_REQUESTED = "2027-05-01T00:00:00Z"
ONE_SECOND_AFTER_ASSESSMENT = "2026-05-01T00:00:01Z"
ONE_SECOND_BEFORE_ASSESSMENT = "2026-04-30T23:59:59Z"


def test_each_uniqueness_scope_answers_with_its_own_conflict_error(api):
    """A second program attempting to reuse an existing `jurisdiction_code` is
    refused with `ERR_DUPLICATE_JURISDICTION_CODE`. Each `FacilityCategory` is
    created against a `fee_program_id` and carries a `code` of 2 to 12 uppercase
    letters and underscores that must be unique inside its program — a collision
    returns `ERR_DUPLICATE_CATEGORY_CODE` — plus a human-readable `name` of 1 to 120
    characters and a `demand_unit_label` of 1 to 40 characters naming the service
    demand unit the category is measured in, such as a resident or a PM peak-hour
    trip. A study may price a given facility category at most once; a second
    component for the same category returns `ERR_DUPLICATE_NEXUS_COMPONENT`.
    `land_use_category` is one of `SINGLE_FAMILY`, `MULTI_FAMILY`, `RETAIL`, `OFFICE`
    or `INDUSTRIAL`, and a component may carry at most one line per land use class —
    a second attempt returns `ERR_DUPLICATE_SCHEDULE_ITEM`.

    Design: Corner/errors/each_uniqueness_rule_returns_its_own_conflict_error
    """
    chain = fixtures.program_with_categories(api, with_roads=False)
    study = fixtures.create_study(api, chain.program_id)
    component = fixtures.create_parks_component(
        api, study["id"], chain.parks_category_id
    )
    fixtures.allocate(api, component["id"])
    line = fixtures.add_schedule_line(
        api, component["id"], K.PARKS_SINGLE_FAMILY_CONVERSION_FACTOR
    )
    program_before = get_success_data(api.get_fee_program(chain.program_id, ADMIN))
    study_before = get_success_data(api.get_fee_study(study["id"], ADMIN))
    component_before = get_success_data(api.get_nexus_component(component["id"], ADMIN))

    duplicate_program = api.create_fee_program(
        factories.fee_program_payload(name="Harbor Impact Fee Program (duplicate filing)"),
        ADMIN,
    )
    duplicate_category = api.create_facility_category(
        factories.parks_category_payload(
            chain.program_id, name="Community Parks", unit_cost_cents=40000000
        ),
        ADMIN,
    )
    duplicate_component = api.create_nexus_component(
        factories.parks_component_payload(
            study["id"],
            chain.parks_category_id,
            horizon_start_year=2031,
            horizon_end_year=2035,
        ),
        ANALYST,
    )
    duplicate_line = api.create_fee_schedule_item(
        component["id"], factories.schedule_item_payload(conversion_factor=3.0), ANALYST
    )

    validate_error(duplicate_program, err.ERR_DUPLICATE_JURISDICTION_CODE, 409)
    validate_error(duplicate_category, err.ERR_DUPLICATE_CATEGORY_CODE, 409)
    validate_error(duplicate_component, err.ERR_DUPLICATE_NEXUS_COMPONENT, 409)
    validate_error(duplicate_line, err.ERR_DUPLICATE_SCHEDULE_ITEM, 409)
    categories, category_meta = validate_paginated(
        api.list_program_facility_categories(chain.program_id, ADMIN)
    )
    check.assert_pagination_meta(category_meta, total_count=1)
    assert categories[0]["unit_cost_cents"] == K.PARKS_UNIT_COST_CENTS
    components, component_meta = validate_paginated(
        api.list_nexus_components(ADMIN, {"fee_study_id": study["id"]})
    )
    check.assert_pagination_meta(component_meta, total_count=1)
    assert components[0]["id"] == component["id"]
    lines, line_meta = validate_paginated(
        api.list_fee_schedule_items(component["id"], ADMIN)
    )
    check.assert_pagination_meta(line_meta, total_count=1)
    check.assert_four_decimal_equals(
        lines[0]["conversion_factor"],
        K.PARKS_SINGLE_FAMILY_CONVERSION_FACTOR,
        "conversion_factor",
    )
    check.assert_money_equals(
        lines[0]["fee_per_unit_cents"], K.PARKS_SINGLE_FAMILY_FEE_PER_UNIT, "fee_per_unit_cents"
    )
    assert lines[0]["id"] == line["id"]
    program = get_success_data(api.get_fee_program(chain.program_id, ADMIN))
    check.assert_version_advanced_by(program_before["version"], program["version"], 0)
    study_after = get_success_data(api.get_fee_study(study["id"], ADMIN))
    check.assert_version_advanced_by(study_before["version"], study_after["version"], 0)
    component_after = get_success_data(api.get_nexus_component(component["id"], ADMIN))
    check.assert_version_advanced_by(
        component_before["version"], component_after["version"], 0
    )


def test_a_non_residential_line_needs_both_the_right_basis_and_a_factor(api):
    """`unit_basis` is either `PER_DWELLING` or `PER_1000_SQFT`, and it is not a free
    choice. Residential classes must be charged per dwelling: `SINGLE_FAMILY` and
    `MULTI_FAMILY` require `PER_DWELLING`. Non-residential classes must be charged
    per thousand square feet: `RETAIL`, `OFFICE` and `INDUSTRIAL` require
    `PER_1000_SQFT`. Beyond that, the parent component must actually carry a demand
    factor for the chosen basis — `demand_units_per_dwelling` strictly greater than
    zero for a per-dwelling line, `demand_units_per_1000_nonres_sqft` strictly
    greater than zero for a per-thousand-square-feet line. A mismatch on either
    count is rejected with `ERR_UNIT_BASIS_MISMATCH` (HTTP 422). A roads component
    adopting 247,197 cents per demand unit stores 249,669 cents for a single-family
    factor of 1.0100 and 1,606,781 cents for a retail factor of 6.5000.

    Design: Corner/errors/unit_basis_must_match_both_land_use_and_component_factor
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
    retail_line = {
        "land_use_category": K.LAND_USE_RETAIL,
        "conversion_factor": RETAIL_CONVERSION_FACTOR,
    }

    wrong_basis_for_land_use = api.create_fee_schedule_item(
        roads_component["id"],
        factories.schedule_item_payload(
            unit_basis=K.UNIT_BASIS_PER_DWELLING, **retail_line
        ),
        ANALYST,
    )
    no_factor_on_the_component = api.create_fee_schedule_item(
        parks_component["id"],
        factories.schedule_item_payload(
            unit_basis=K.UNIT_BASIS_PER_1000_SQFT, **retail_line
        ),
        ANALYST,
    )
    accepted = api.create_fee_schedule_item(
        roads_component["id"],
        factories.schedule_item_payload(
            unit_basis=K.UNIT_BASIS_PER_1000_SQFT, **retail_line
        ),
        ANALYST,
    )

    validate_error(wrong_basis_for_land_use, err.ERR_UNIT_BASIS_MISMATCH, 422)
    validate_error(no_factor_on_the_component, err.ERR_UNIT_BASIS_MISMATCH, 422)
    roads_line = validate_success(accepted, 201)
    assert roads_line["unit_basis"] == K.UNIT_BASIS_PER_1000_SQFT
    assert roads_line["schedule_status"] == K.SCHEDULE_VALID
    check.assert_money_equals(
        roads_line["fee_per_unit_cents"], K.ROADS_RETAIL_FEE_PER_UNIT, "fee_per_unit_cents"
    )
    _, parks_meta = validate_paginated(
        api.list_fee_schedule_items(parks_component["id"], ADMIN)
    )
    check.assert_pagination_meta(parks_meta, total_count=0)


def test_allocation_is_refused_when_either_term_of_the_denominator_is_zero(api):
    """It also requires that there be something to allocate against: if the
    component's `growth_demand_units` is not strictly greater than zero, or if the
    smaller of `growth_demand_units` and `planned_capacity_demand_units` is not
    strictly greater than zero, the request is refused with `ERR_ZERO_DEMAND_UNITS`.
    A component with no projected growth has no rational nexus to allocate cost
    across. Until the component is allocated, its `allocation_status` is `PENDING`,
    `allocated_at` is null, and all four computed cost figures are null. It is
    refused unless the study is in `DRAFT` (`ERR_STUDY_INVALID_STATE`), unless the
    study has at least one component (`ERR_STUDY_HAS_NO_COMPONENTS`), unless every
    component of the study has `allocation_status` `VALID` and carries at least one
    schedule line (`ERR_COMPONENT_ALLOCATION_STALE` in either case), and unless
    every component's `nexus_ratio` is at least 1.0 (`ERR_NEXUS_RATIO_INSUFFICIENT`,
    HTTP 409) — a component whose planned capacity falls short of its projected
    growth demand would be charging new development for capacity the programme never
    buys.

    Design: Corner/errors/allocation_requires_a_positive_demand_denominator
    """
    chain = fixtures.program_with_categories(api)
    study = fixtures.create_study(api, chain.program_id)
    no_growth = fixtures.create_parks_component(
        api,
        study["id"],
        chain.parks_category_id,
        projected_new_dwelling_units=0,
        projected_new_nonres_sqft=0,
    )
    no_capacity = fixtures.create_roads_component(
        api, study["id"], chain.roads_category_id, planned_capacity_demand_units=0
    )
    check.assert_four_decimal_equals(
        no_growth["growth_demand_units"], 0.0, "growth_demand_units"
    )
    check.assert_four_decimal_equals(
        no_capacity["growth_demand_units"],
        K.ROADS_GROWTH_DEMAND_UNITS,
        "growth_demand_units",
    )

    without_growth = api.allocate_nexus_component(no_growth["id"], ANALYST)
    without_capacity = api.allocate_nexus_component(no_capacity["id"], ANALYST)

    validate_error(without_growth, err.ERR_ZERO_DEMAND_UNITS, 422)
    validate_error(without_capacity, err.ERR_ZERO_DEMAND_UNITS, 422)
    for component_id in (no_growth["id"], no_capacity["id"]):
        component = get_success_data(api.get_nexus_component(component_id, ADMIN))
        assert component["allocation_status"] == K.ALLOCATION_PENDING
        check.assert_fields_null(
            component,
            "allocated_at",
            "plan_based_cost_per_unit_cents",
            "standard_based_cost_per_unit_cents",
            "adopted_cost_per_unit_cents",
            "nexus_ratio",
        )

    certification = api.certify_nexus(study["id"], ANALYST)

    validate_error(certification, err.ERR_COMPONENT_ALLOCATION_STALE, 409)


def test_a_land_use_the_schedule_never_priced_cannot_be_assessed(api):
    """And at least one schedule line inside that study must apply to the
    application's `land_use_category`, or the request is refused with
    `ERR_NO_APPLICABLE_FEE_SCHEDULE`. On creation the server records
    `submitted_by_user_id` from the caller's `X-User-ID`, sets `assessment_status` to
    `UNASSESSED` and `collection_status` to `NOT_DUE`, sets `reassessment_required`
    to false, leaves `assessed_lines` empty, and zeroes `gross_assessed_cents`,
    `credit_applied_cents`, `admin_charge_cents`, `net_due_cents`, `paid_cents` and
    `default_penalty_cents`, with `assessed_at`, `reassessed_at` and `co_issued_at`
    all null. `committed_demand_units` is the sum of `demand_units` over the assessed
    lines naming this category on applications whose `assessment_status` is
    `ASSESSED` or `REASSESSED`; and `deferred_receivable_cents` is the sum of
    `line_net_cents` for this category over applications whose `collection_status` is
    `DEFERRED` or `DELINQUENT`.

    Design: Corner/errors/assessment_needs_a_schedule_line_for_the_land_use
    """
    chain = fixtures.effective_program(api)
    retail = fixtures.file_application(
        api,
        chain.program_id,
        permit_number="BP-3001",
        land_use_category=K.LAND_USE_RETAIL,
        dwelling_units=0,
        nonres_sqft=200000,
    )
    residential = fixtures.file_application(api, chain.program_id)
    fixtures.set_clock(api, K.CLOCK_ASSESSMENT)

    unpriceable = api.assess_application(retail["id"], PERMIT_OFFICER)

    validate_error(unpriceable, err.ERR_NO_APPLICABLE_FEE_SCHEDULE, 409)
    untouched = get_success_data(api.get_development_application(retail["id"], ADMIN))
    assert untouched["assessment_status"] == K.ASSESSMENT_UNASSESSED
    assert untouched["collection_status"] == K.COLLECTION_NOT_DUE
    assert untouched["assessed_lines"] == []
    check.assert_application_totals(
        untouched, gross_assessed_cents=0, net_due_cents=0
    )
    check.assert_fields_null(untouched, "pinned_fee_study_id")

    assessed = fixtures.assess(api, residential["id"])

    assert len(assessed["assessed_lines"]) == 2
    check.assert_application_totals(
        assessed,
        gross_assessed_cents=K.BASELINE_GROSS_ASSESSED,
        net_due_cents=K.BASELINE_NET_DUE,
    )
    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(
        parks, committed_demand_units=K.BASELINE_PARKS_DEMAND_UNITS
    )


def test_a_study_with_nothing_in_it_cannot_be_certified(api):
    """It is refused unless the study is in `DRAFT` (`ERR_STUDY_INVALID_STATE`),
    unless the study has at least one component (`ERR_STUDY_HAS_NO_COMPONENTS`),
    unless every component of the study has `allocation_status` `VALID` and carries
    at least one schedule line (`ERR_COMPONENT_ALLOCATION_STALE` in either case),
    and unless every component's `nexus_ratio` is at least 1.0
    (`ERR_NEXUS_RATIO_INSUFFICIENT`, HTTP 409) — a component whose planned capacity
    falls short of its projected growth demand would be charging new development for
    capacity the programme never buys. Certification writes `certified_by_user_id`
    from the caller's `X-User-ID` and `certified_at` from the logical clock, and
    increments the study's `version`.

    Design: Corner/errors/study_with_no_components_cannot_be_certified
    """
    chain = fixtures.program_with_categories(api, with_roads=False)
    study = fixtures.create_study(api, chain.program_id)

    response = api.certify_nexus(study["id"], ANALYST)

    validate_error(response, err.ERR_STUDY_HAS_NO_COMPONENTS, 409)
    unchanged = get_success_data(api.get_fee_study(study["id"], ADMIN))
    assert unchanged["status"] == K.STUDY_DRAFT
    check.assert_fields_null(unchanged, "certified_at", "certified_by_user_id")
    assert unchanged["revision_round"] == 0
    check.assert_version_advanced_by(study["version"], unchanged["version"], 0)


def test_a_deferral_due_the_very_instant_of_the_clock_is_refused(api):
    """A `Developer` requests one on its own application, supplying a
    `requested_security_type` of `CASH_BOND`, `LETTER_OF_CREDIT` or `LIEN`, a
    strictly positive `security_amount_cents` naming the face amount of the offered
    instrument, and a `requested_due_at`. The requested due date must be strictly
    after the logical clock, and otherwise the request is refused with
    `ERR_DEFERRAL_DUE_DATE_INVALID` (HTTP 422). The agreement is born `REQUESTED`
    with `due_at`, `decided_by_user_id`, `decided_at`, `executed_at`, `satisfied_at`
    and `defaulted_at` all null, and the application's `collection_status`
    unchanged.

    Design: Corner/errors/deferral_due_date_must_be_after_the_clock
    """
    chain = fixtures.effective_program(api)
    assessed = fixtures.assessed_application(api, chain)
    assert assessed["collection_status"] == K.COLLECTION_DUE

    at_the_clock = api.create_deferral_agreement(
        chain.application_id,
        factories.deferral_agreement_payload(K.BASELINE_NET_DUE, K.CLOCK_ASSESSMENT),
        DEVELOPER,
    )
    before_the_clock = api.create_deferral_agreement(
        chain.application_id,
        factories.deferral_agreement_payload(
            K.BASELINE_NET_DUE, ONE_SECOND_BEFORE_ASSESSMENT
        ),
        DEVELOPER,
    )
    one_second_later = api.create_deferral_agreement(
        chain.application_id,
        factories.deferral_agreement_payload(
            K.BASELINE_NET_DUE,
            ONE_SECOND_AFTER_ASSESSMENT,
            requested_security_type=K.SECURITY_LETTER_OF_CREDIT,
        ),
        DEVELOPER,
    )

    validate_error(at_the_clock, err.ERR_DEFERRAL_DUE_DATE_INVALID, 422)
    validate_error(before_the_clock, err.ERR_DEFERRAL_DUE_DATE_INVALID, 422)
    agreement = validate_success(one_second_later, 201)
    assert agreement["status"] == K.DEFERRAL_REQUESTED
    assert agreement["requested_security_type"] == K.SECURITY_LETTER_OF_CREDIT
    check.assert_fields_null(
        agreement,
        "due_at",
        "decided_by_user_id",
        "decided_at",
        "executed_at",
        "satisfied_at",
        "defaulted_at",
    )
    agreements, meta = validate_paginated(
        api.list_deferral_agreements(chain.application_id, ADMIN)
    )
    check.assert_pagination_meta(meta, total_count=1)
    assert agreements[0]["id"] == agreement["id"]
    application = get_success_data(
        api.get_development_application(chain.application_id, ADMIN)
    )
    assert application["collection_status"] == K.COLLECTION_DUE


def test_neither_an_expenditure_row_nor_a_part_spent_row_may_be_refunded(api):
    """The row must be a `COLLECTION` row in a refundable state, and otherwise the
    request is refused with `ERR_LEDGER_ENTRY_INVALID_STATE`. A row whose
    `entry_status` is `REFUND_DUE` is always a statutory deadline refund: the
    refunded amount is that row's full remaining `unexpended_cents`. A row whose
    `entry_status` is `OPEN` is only ever an overpayment refund, and it requires the
    row's application to have `paid_cents` strictly greater than `net_due_cents`;
    without that surplus the request is refused with `ERR_REFUND_NOT_ELIGIBLE` (HTTP
    422).

    Design: Corner/errors/refund_is_refused_on_rows_that_are_not_refundable_collections
    """
    chain = fixtures.effective_program_with_paid_application(api)
    collection_row = fixtures.collection_rows_for(api, chain.parks_category_id)[0]
    expenditure_row = fixtures.spend(api, chain.parks_category_id, 2000000)
    part_spent = get_success_data(api.get_fund_ledger_entry(collection_row["id"], ADMIN))
    assert part_spent["entry_status"] == K.ENTRY_PARTIALLY_EXPENDED

    wrong_kind = api.refund_ledger_entry(
        expenditure_row["id"], FINANCE, factories.refund_payload(reason="wrong project")
    )
    wrong_status = api.refund_ledger_entry(
        collection_row["id"], FINANCE, factories.refund_payload(reason="developer asked")
    )

    validate_error(wrong_kind, err.ERR_LEDGER_ENTRY_INVALID_STATE, 409)
    validate_error(wrong_status, err.ERR_LEDGER_ENTRY_INVALID_STATE, 409)
    _, refund_meta = validate_paginated(
        api.list_fund_ledger_entries(
            ADMIN,
            {
                "facility_category_id": chain.parks_category_id,
                "kind": K.LEDGER_KIND_REFUND,
            },
        )
    )
    check.assert_pagination_meta(refund_meta, total_count=0)
    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(
        parks, fund_balance_cents=617930, fund_posture=K.FUND_POSTURE_COMPLIANT
    )


def test_security_one_cent_short_of_the_whole_fee_cannot_execute(api):
    """`EXECUTE` additionally requires `security_amount_cents` to be at least the
    application's `net_due_cents`; a shortfall is refused with
    `ERR_INSUFFICIENT_SECURITY` (HTTP 422). Both require the agreement to be
    `REQUESTED` and the application to be `PERMIT`-triggered with `collection_status`
    `DUE`, failures returning `ERR_DEFERRAL_INVALID_STATE`, and both stamp
    `decided_by_user_id` and `decided_at` and increment the agreement's `version`.
    `DENY` moves the agreement `REQUESTED → DENIED` and touches nothing else at all:
    the application's `collection_status` stays `DUE`, no receivable is booked, and
    the application's `version` does not move. The application's `collection_status`
    moves `DUE → DEFERRED`, and for every assessed line that line's `line_net_cents`
    is added to the owning facility category's `deferred_receivable_cents` with each
    such category's `version` incremented.

    Design: Corner/errors/deferral_execution_requires_security_covering_the_whole_fee
    """
    chain = fixtures.effective_program(api)
    fixtures.assessed_application(api, chain)
    short = fixtures.request_deferral(
        api, chain.application_id, K.BASELINE_NET_DUE - 1, DUE_AT_REQUESTED
    )

    refused = api.decide_deferral_agreement(
        short["id"], factories.deferral_decision_payload(K.DEFERRAL_DECISION_EXECUTE), PERMIT_OFFICER
    )

    validate_error(refused, err.ERR_INSUFFICIENT_SECURITY, 422)
    agreements = get_success_data(
        api.list_deferral_agreements(chain.application_id, ADMIN)
    )
    still_requested = [row for row in agreements if row["id"] == short["id"]][0]
    assert still_requested["status"] == K.DEFERRAL_REQUESTED
    check.assert_fields_null(still_requested, "executed_at")
    application = get_success_data(
        api.get_development_application(chain.application_id, ADMIN)
    )
    assert application["collection_status"] == K.COLLECTION_DUE

    denied = fixtures.decide_deferral(api, short["id"], K.DEFERRAL_DECISION_DENY)

    assert denied["status"] == K.DEFERRAL_DENIED
    assert denied["decided_by_user_id"] == PERMIT_1
    check.assert_timestamp_equals(denied["decided_at"], K.CLOCK_ASSESSMENT, "decided_at")
    assert (
        get_success_data(api.get_development_application(chain.application_id, ADMIN))[
            "collection_status"
        ]
        == K.COLLECTION_DUE
    )

    exact = fixtures.request_deferral(
        api, chain.application_id, K.BASELINE_NET_DUE, DUE_AT_REQUESTED
    )
    executed = fixtures.decide_deferral(api, exact["id"], K.DEFERRAL_DECISION_EXECUTE)

    assert executed["status"] == K.DEFERRAL_EXECUTED
    deferred = get_success_data(
        api.get_development_application(chain.application_id, ADMIN)
    )
    assert deferred["collection_status"] == K.COLLECTION_DEFERRED
    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    roads = get_success_data(api.get_facility_category(chain.roads_category_id, ADMIN))
    check.assert_category_fund(
        parks, deferred_receivable_cents=K.BASELINE_PARKS_LINE_NET
    )
    check.assert_category_fund(
        roads, deferred_receivable_cents=K.BASELINE_ROADS_LINE_NET
    )

    replay = api.decide_deferral_agreement(
        exact["id"], factories.deferral_decision_payload(K.DEFERRAL_DECISION_EXECUTE), PERMIT_OFFICER
    )

    validate_error(replay, err.ERR_DEFERRAL_INVALID_STATE, 409)
    assert fixtures.ledger_rows(api) == [], "deferral moves the receivable, not cash"
