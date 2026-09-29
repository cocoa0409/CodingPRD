"""The three parent-version preconditions, each proved the same way: a write made
from a stale observation is refused and changes nothing, and the identical write made
from a fresh observation succeeds, so the retry is the only difference."""

from test_helpers import ANALYST_2, api_errors as err
from test_helpers import assertions as check
from test_helpers import constants as K
from test_helpers import factories, fixtures, get_success_data, make_analyst_headers
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.fixtures import ADMIN, ANALYST, DEVELOPER, FINANCE

REVIEWER = make_analyst_headers(ANALYST_2)
PARKS_CLAIM_CENTS = 1000000
ROADS_CLAIM_CENTS = 500000
ADMIN_AFTER_PARKS_CREDIT = 121151
NET_AFTER_PARKS_CREDIT = 4159521
CREDIT_AFTER_BOTH = 1500000
PARKS_LINE_ADMIN_AFTER_CREDIT = 46250
ROADS_LINE_ADMIN_AFTER_CREDIT = 59901
ADMIN_AFTER_BOTH_CREDITS = 106151
NET_AFTER_BOTH_CREDITS = 3644521
FIRST_EXPENDITURE_CENTS = 1000000
BALANCE_AFTER_FIRST_EXPENDITURE = 1617930
BALANCE_AFTER_BOTH_EXPENDITURES = 617930


def test_a_study_opened_against_a_stale_program_version_is_refused(api):
    """Opening a fee study at `POST /fee-studies` requires
    `expected_fee_program_version` carrying the client's last observed `version` of
    the target `FeeProgram`. If that value does not equal the program's current
    `version`, the create is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412). A
    study prices the program's whole facility-standard roster and its statutory
    constants, and multiple `DRAFT` studies per program are perfectly legitimate, so
    nothing in the lifecycle would otherwise stop an analyst from drafting against a
    roster or a constant set that has since been replaced. In all three cases the
    version field is a required input, not an optional one, and its absence is a
    schema violation reported as `ERR_INVALID_REQUEST`. A new study is born in status
    `DRAFT` with `revision_round` 0, a protest tally of zero on both counters, and
    every notice, adoption and activation timestamp null; the create additionally
    increments the parent program's `version`, because the program's roster of
    studies has changed.

    Design: Corner/cross_cutting_complexity_layers/stale_program_version_blocks_a_second_study_create
    """
    chain = fixtures.program_with_categories(api, with_roads=False)
    stale_version = fixtures.program_version(api, chain.program_id)
    first_study = fixtures.create_study(api, chain.program_id)
    assert first_study["status"] == K.STUDY_DRAFT
    assert fixtures.program_version(api, chain.program_id) == stale_version + 1

    rival = api.create_fee_study(
        factories.fee_study_payload(chain.program_id, stale_version, title="Rival 2026 Study"),
        ANALYST,
    )

    validate_error(rival, err.ERR_STALE_PROGRAM_VERSION, 412)
    assert (
        fixtures.program_version(api, chain.program_id) == stale_version + 1
    ), "the rejected write did not bump the program any further"
    rows, meta = validate_paginated(
        api.list_fee_studies(ANALYST, {"fee_program_id": chain.program_id})
    )
    check.assert_pagination_meta(meta, total_count=1)
    assert [row["id"] for row in rows] == [first_study["id"]]

    fresh_version = fixtures.program_version(api, chain.program_id)
    retried = validate_success(
        api.create_fee_study(
            factories.fee_study_payload(
                chain.program_id, fresh_version, title="Rival 2026 Study"
            ),
            ANALYST,
        ),
        201,
    )

    assert retried["status"] == K.STUDY_DRAFT
    assert retried["revision_round"] == 0
    assert fixtures.program_version(api, chain.program_id) == stale_version + 2
    rows, meta = validate_paginated(
        api.list_fee_studies(ANALYST, {"fee_program_id": chain.program_id})
    )
    check.assert_pagination_meta(meta, total_count=2)
    assert sorted(row["id"] for row in rows) == sorted([first_study["id"], retried["id"]])


def test_a_second_credit_decision_made_from_the_pre_approval_version_is_refused(api):
    """Deciding a credit claim at `POST /credit-claims/{id}/decide` requires
    `expected_development_application_version` carrying the client's last observed
    `version` of the claim's `DevelopmentApplication`. A mismatch against the
    application's current `version` is rejected with `ERR_STALE_APPLICATION_VERSION`
    (HTTP 412). Every approval legitimately re-prices the application and moves
    `credit_applied_cents` against the program's credit cap, so a reviewer working
    from a `net_due_cents` that has since changed would allow a credit the cap no
    longer has room for. The credit cap is `gross_assessed_cents` multiplied by the
    program's `credit_cap_bp` divided by ten thousand, rounded half up to whole
    cents. `credit_applied_cents` is the smaller of the total raw approved credit
    across all lines and that cap. For each line, subtract `line_credit_cents` from
    `line_gross_cents` to get that line's net before administration.
    `line_admin_cents` is that net multiplied by the program's `admin_charge_bp`
    divided by ten thousand, rounded half up to whole cents once, per line.
    `line_net_cents` is the line's net before administration plus its
    `line_admin_cents`. `admin_charge_cents` on the application is the sum of the
    per-line `line_admin_cents` values.

    Design: Corner/cross_cutting_complexity_layers/stale_application_version_blocks_a_second_credit_decision
    """
    chain = fixtures.effective_program(api)
    assessed = fixtures.assessed_application(api, chain)
    stale_version = assessed["version"]
    parks_claim = validate_success(
        api.create_credit_claim(
            chain.application_id,
            {
                "facility_category_code": K.PARKS_CODE,
                "credit_type": K.CREDIT_TYPE_DEVELOPER_IMPROVEMENT,
                "valuation_method": K.VALUATION_NOMINAL,
                "improvement_value_cents": PARKS_CLAIM_CENTS,
            },
            DEVELOPER,
        ),
        201,
    )
    roads_claim = validate_success(
        api.create_credit_claim(
            chain.application_id,
            {
                "facility_category_code": K.ROADS_CODE,
                "credit_type": K.CREDIT_TYPE_DEVELOPER_IMPROVEMENT,
                "valuation_method": K.VALUATION_NOMINAL,
                "improvement_value_cents": ROADS_CLAIM_CENTS,
            },
            DEVELOPER,
        ),
        201,
    )
    first_decision = validate_success(
        api.decide_credit_claim(
            parks_claim["id"], factories.credit_decision_payload(stale_version), REVIEWER
        )
    )
    assert first_decision["status"] == K.CLAIM_APPROVED_FULL

    stale_decision = api.decide_credit_claim(
        roads_claim["id"], factories.credit_decision_payload(stale_version), REVIEWER
    )

    validate_error(stale_decision, err.ERR_STALE_APPLICATION_VERSION, 412)
    claims = get_success_data(api.list_credit_claims(chain.application_id, ANALYST))
    undecided = [row for row in claims if row["id"] == roads_claim["id"]][0]
    assert undecided["status"] == K.CLAIM_SUBMITTED
    check.assert_money_equals(undecided["approved_cents"], 0, "approved_cents")
    midway = get_success_data(
        api.get_development_application(chain.application_id, ANALYST)
    )
    check.assert_application_totals(
        midway,
        gross_assessed_cents=K.BASELINE_GROSS_ASSESSED,
        credit_applied_cents=PARKS_CLAIM_CENTS,
        admin_charge_cents=ADMIN_AFTER_PARKS_CREDIT,
        net_due_cents=NET_AFTER_PARKS_CREDIT,
    )

    retried = validate_success(
        api.decide_credit_claim(
            roads_claim["id"],
            factories.credit_decision_payload(midway["version"]),
            REVIEWER,
        )
    )

    assert retried["status"] == K.CLAIM_APPROVED_FULL
    check.assert_money_equals(
        retried["approved_cents"], ROADS_CLAIM_CENTS, "approved_cents"
    )
    application = get_success_data(
        api.get_development_application(chain.application_id, ANALYST)
    )
    check.assert_application_totals(
        application,
        gross_assessed_cents=K.BASELINE_GROSS_ASSESSED,
        credit_applied_cents=CREDIT_AFTER_BOTH,
        admin_charge_cents=ADMIN_AFTER_BOTH_CREDITS,
        net_due_cents=NET_AFTER_BOTH_CREDITS,
    )
    check.assert_net_due_identity(application)
    assert (
        CREDIT_AFTER_BOTH < K.BASELINE_CREDIT_CAP
    ), "the aggregate credit stays under the cap, so no clipping occurred"
    parks_line = check.line_for_code(application["assessed_lines"], K.PARKS_CODE)
    roads_line = check.line_for_code(application["assessed_lines"], K.ROADS_CODE)
    check.assert_assessed_line(
        parks_line,
        demand_units=K.BASELINE_PARKS_DEMAND_UNITS,
        line_gross_cents=K.BASELINE_PARKS_LINE_GROSS,
        line_credit_cents=PARKS_CLAIM_CENTS,
        line_admin_cents=PARKS_LINE_ADMIN_AFTER_CREDIT,
        line_net_cents=K.BASELINE_PARKS_LINE_GROSS
        - PARKS_CLAIM_CENTS
        + PARKS_LINE_ADMIN_AFTER_CREDIT,
    )
    check.assert_assessed_line(
        roads_line,
        demand_units=K.BASELINE_ROADS_DEMAND_UNITS,
        line_gross_cents=K.BASELINE_ROADS_LINE_GROSS,
        line_credit_cents=ROADS_CLAIM_CENTS,
        line_admin_cents=ROADS_LINE_ADMIN_AFTER_CREDIT,
        line_net_cents=K.BASELINE_ROADS_LINE_GROSS
        - ROADS_CLAIM_CENTS
        + ROADS_LINE_ADMIN_AFTER_CREDIT,
    )


def test_a_second_expenditure_made_from_the_pre_spend_version_is_refused(api):
    """Recording an expenditure at `POST /facility-categories/{id}/expenditures`
    requires `expected_facility_category_version` carrying the client's last observed
    `version` of the target `FacilityCategory`. A mismatch against the category's
    current `version` is rejected with `ERR_STALE_CATEGORY_VERSION` (HTTP 412). Two
    expenditures are each individually valid while the balance covers them, so the
    fund's own state cannot distinguish a finance officer who has seen the current
    balance, posture and vintage list from one who has not. A row taken down to a
    positive remainder moves `OPEN → PARTIALLY_EXPENDED`. The expenditure then
    creates its own `EXPENDITURE` row `POSTED`, reduces the category's
    `fund_balance_cents` by the full `amount_cents`, recomputes
    `oldest_unexpended_vintage_at` over the rows that remain eligible (null when none
    do), recomputes `fund_posture`, and increments the category's `version`.

    Design: Corner/cross_cutting_complexity_layers/stale_category_version_blocks_a_second_expenditure
    """
    chain = fixtures.effective_program_with_paid_application(api)
    stale_version = fixtures.category_version(api, chain.parks_category_id)
    collection_row = fixtures.collection_rows_for(api, chain.parks_category_id)[0]

    first = validate_success(
        api.create_expenditure(
            chain.parks_category_id,
            factories.expenditure_payload(
                FIRST_EXPENDITURE_CENTS, stale_version, project_name="Greenway Phase A"
            ),
            FINANCE,
        ),
        201,
    )

    assert first["entry_status"] == K.ENTRY_POSTED
    after_first = get_success_data(
        api.get_facility_category(chain.parks_category_id, FINANCE)
    )
    check.assert_category_fund(
        after_first, fund_balance_cents=BALANCE_AFTER_FIRST_EXPENDITURE
    )
    check.assert_version_advanced_by(stale_version, after_first["version"], 1)

    replay = api.create_expenditure(
        chain.parks_category_id,
        factories.expenditure_payload(
            FIRST_EXPENDITURE_CENTS, stale_version, project_name="Greenway Phase B"
        ),
        FINANCE,
    )

    validate_error(replay, err.ERR_STALE_CATEGORY_VERSION, 412)
    unchanged = get_success_data(
        api.get_facility_category(chain.parks_category_id, FINANCE)
    )
    check.assert_category_fund(
        unchanged, fund_balance_cents=BALANCE_AFTER_FIRST_EXPENDITURE
    )
    check.assert_version_advanced_by(after_first["version"], unchanged["version"], 0)
    assert (
        len(fixtures.rows_of_kind(api, K.LEDGER_KIND_EXPENDITURE)) == 1
    ), "no second expenditure row exists"

    retried = validate_success(
        api.create_expenditure(
            chain.parks_category_id,
            factories.expenditure_payload(
                FIRST_EXPENDITURE_CENTS,
                unchanged["version"],
                project_name="Greenway Phase B",
            ),
            FINANCE,
        ),
        201,
    )

    assert retried["entry_status"] == K.ENTRY_POSTED
    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(
        parks,
        fund_balance_cents=BALANCE_AFTER_BOTH_EXPENDITURES,
        refund_due_cents=0,
        fund_posture=K.FUND_POSTURE_COMPLIANT,
        oldest_unexpended_vintage_at=K.CLOCK_PAYMENT,
    )
    check.assert_version_advanced_by(stale_version, parks["version"], 2)
    consumed = get_success_data(api.get_fund_ledger_entry(collection_row["id"], ADMIN))
    assert consumed["entry_status"] == K.ENTRY_PARTIALLY_EXPENDED
    check.assert_money_equals(
        consumed["unexpended_cents"], BALANCE_AFTER_BOTH_EXPENDITURES, "unexpended_cents"
    )
    expenditures = fixtures.rows_of_kind(api, K.LEDGER_KIND_EXPENDITURE)
    assert len(expenditures) == 2
    for row in expenditures:
        check.assert_money_equals(
            row["amount_cents"], FIRST_EXPENDITURE_CENTS, "amount_cents"
        )
