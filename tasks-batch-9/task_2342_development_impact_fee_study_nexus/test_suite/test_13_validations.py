"""Preconditions that are scoped, ordered or boundary-inclusive: program-scoped
permit numbers, the affordable expenditure, the fiscal year that has just closed,
the certificate-triggered payment, and the category a claim may name."""

from test_helpers import DEVELOPER_1, FINANCE_1, api_errors as err
from test_helpers import assertions as check
from test_helpers import constants as K
from test_helpers import factories, fixtures, get_success_data, validate_error
from test_helpers import validate_paginated, validate_success
from test_helpers.fixtures import ADMIN, DEVELOPER, FINANCE, PERMIT_OFFICER

JUST_BEFORE_FISCAL_YEAR_END = "2026-06-30T23:59:59Z"
FISCAL_YEAR_END = "2026-07-01T00:00:00Z"
CO_DEADLINE = "2031-05-01T00:00:00Z"
PARKS_ONLY_ADMIN = 76250
PARKS_ONLY_NET = 2617930


def test_a_permit_number_is_unique_only_inside_its_own_program(api):
    """A `Developer` files a `DevelopmentApplication` against a `fee_program_id`,
    supplying a `permit_number` of 1 to 40 characters that must be unique inside
    its program — a collision returns `ERR_DUPLICATE_PERMIT_NUMBER` — and the
    project's `land_use_category`, again one of `SINGLE_FAMILY`, `MULTI_FAMILY`,
    `RETAIL`, `OFFICE` or `INDUSTRIAL`. On creation the server records
    `submitted_by_user_id` from the caller's `X-User-ID`, sets `assessment_status`
    to `UNASSESSED` and `collection_status` to `NOT_DUE`, sets
    `reassessment_required` to false, leaves `assessed_lines` empty, and zeroes
    `gross_assessed_cents`, `credit_applied_cents`, `admin_charge_cents`,
    `net_due_cents`, `paid_cents` and `default_penalty_cents`, with `assessed_at`,
    `reassessed_at` and `co_issued_at` all null.

    Design: Corner/validations/permit_number_uniqueness_is_scoped_to_one_program
    """
    fixtures.set_clock(api, K.CLOCK_PROGRAM_SETUP)
    harbor = fixtures.create_program(api)
    seagate = fixtures.create_program(api, factories.second_fee_program_payload())
    fixtures.file_application(api, harbor["id"])

    collision = api.create_development_application(
        factories.development_application_payload(harbor["id"]), DEVELOPER
    )
    reused_elsewhere = api.create_development_application(
        factories.development_application_payload(seagate["id"]), DEVELOPER
    )

    validate_error(collision, err.ERR_DUPLICATE_PERMIT_NUMBER, 409)
    accepted = validate_success(reused_elsewhere, 201)
    assert accepted["permit_number"] == "BP-1001"
    for program_id in (harbor["id"], seagate["id"]):
        rows, meta = validate_paginated(
            api.list_development_applications(ADMIN, {"fee_program_id": program_id})
        )
        check.assert_pagination_meta(meta, total_count=1)
        assert rows[0]["submitted_by_user_id"] == DEVELOPER_1
        assert rows[0]["assessment_status"] == K.ASSESSMENT_UNASSESSED
        assert rows[0]["collection_status"] == K.COLLECTION_NOT_DUE


def test_an_expenditure_inside_the_eligible_balance_is_booked(api):
    """Second, the amount must be affordable, which is deliberately narrower than
    the fund's balance. A row taken down to a positive remainder moves
    `OPEN → PARTIALLY_EXPENDED`. The expenditure then creates its own `EXPENDITURE`
    row `POSTED`, reduces the category's `fund_balance_cents` by the full
    `amount_cents`, recomputes `oldest_unexpended_vintage_at` over the rows that
    remain eligible (null when none do), recomputes `fund_posture`, and increments
    the category's `version`. After that, the derived money figures are recomputed
    from the ledger as described in §2.11, and `fund_posture` is decided in exactly
    this order: it is `REFUND_DUE` when `refund_due_cents` is greater than zero;
    otherwise it is `AT_RISK` when `refund_due_cents` is zero and at least one
    `COLLECTION` row with `entry_status` `OPEN` or `PARTIALLY_EXPENDED` has a
    `deadline_at` at or before the logical clock plus the program's
    `at_risk_window_days` days; otherwise it is `COMPLIANT`.

    Design: Corner/validations/expenditure_inside_the_available_balance_succeeds
    """
    chain = fixtures.effective_program_with_paid_application(api)
    before = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    source_row = fixtures.collection_rows_for(api, chain.parks_category_id)[0]

    expenditure = fixtures.spend(
        api, chain.parks_category_id, 2000000, project_name="Harbor Greenway Design"
    )

    assert expenditure["kind"] == K.LEDGER_KIND_EXPENDITURE
    check.assert_money_equals(expenditure["amount_cents"], 2000000, "amount_cents")
    assert expenditure["entry_status"] == K.ENTRY_POSTED
    check.assert_money_equals(expenditure["unexpended_cents"], 0, "unexpended_cents")
    check.assert_fields_null(expenditure, "deadline_at")
    assert expenditure["authorized_by_user_id"] == FINANCE_1
    consumed = get_success_data(api.get_fund_ledger_entry(source_row["id"], ADMIN))
    assert consumed["entry_status"] == K.ENTRY_PARTIALLY_EXPENDED
    check.assert_money_equals(consumed["unexpended_cents"], 617930, "unexpended_cents")
    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(
        parks,
        fund_balance_cents=617930,
        refund_due_cents=0,
        fund_posture=K.FUND_POSTURE_COMPLIANT,
        oldest_unexpended_vintage_at=K.CLOCK_PAYMENT,
    )
    check.assert_version_advanced_by(before["version"], parks["version"], 1)
    roads = get_success_data(api.get_facility_category(chain.roads_category_id, ADMIN))
    check.assert_category_fund(roads, fund_balance_cents=K.BASELINE_ROADS_LINE_NET)


def test_the_annual_report_may_be_filed_the_instant_the_year_closes(api):
    """The year's window must have closed — the logical clock must have reached
    `window_end` — or the filing is refused with `ERR_FISCAL_YEAR_NOT_COMPLETE`. No
    report may already exist for that program and year, or the filing is refused
    with `ERR_REPORT_ALREADY_FILED`. `filed_late` is decided by a strict
    comparison: the filing is late only when the logical clock is strictly past
    `window_end` plus the program's `report_grace_days` days, so filing exactly on
    the grace deadline is on time. The filing writes `last_report_fiscal_year`,
    `last_report_filed_at`, `last_report_filed_by_user_id` and
    `last_report_status` — `FILED_ON_TIME` or `FILED_LATE` — onto the program and
    increments the program's `version`.

    Design: Corner/validations/annual_report_cannot_be_filed_until_the_fiscal_year_closes
    """
    chain = fixtures.effective_program_with_paid_application(api)
    fixtures.set_clock(api, JUST_BEFORE_FISCAL_YEAR_END)

    too_early = api.file_annual_report(
        chain.program_id, factories.annual_report_filing_payload(2025), FINANCE
    )

    validate_error(too_early, err.ERR_FISCAL_YEAR_NOT_COMPLETE, 409)
    unfiled_program = get_success_data(api.get_fee_program(chain.program_id, ADMIN))
    assert unfiled_program["last_report_status"] == K.REPORT_NOT_FILED
    check.assert_fields_null(
        unfiled_program,
        "last_report_fiscal_year",
        "last_report_filed_at",
        "last_report_filed_by_user_id",
    )

    fixtures.set_clock(api, FISCAL_YEAR_END)
    filed = validate_success(
        api.file_annual_report(
            chain.program_id, factories.annual_report_filing_payload(2025), FINANCE
        ),
        201,
    )

    assert filed["fiscal_year"] == 2025
    check.assert_timestamp_equals(filed["filed_at"], FISCAL_YEAR_END, "filed_at")
    assert filed["filed_late"] is False
    assert filed["report_status"] == K.REPORT_FILED_ON_TIME
    check.assert_money_equals(
        filed["collections_cents"], K.BASELINE_NET_DUE, "collections_cents"
    )
    check.assert_money_equals(filed["expenditures_cents"], 0, "expenditures_cents")
    check.assert_money_equals(filed["refunds_cents"], 0, "refunds_cents")
    check.assert_money_equals(filed["unexpended_cents"], K.BASELINE_NET_DUE, "unexpended_cents")
    check.assert_money_equals(filed["refund_obligation_cents"], 0, "refund_obligation_cents")
    program = get_success_data(api.get_fee_program(chain.program_id, ADMIN))
    assert program["last_report_fiscal_year"] == 2025
    check.assert_timestamp_equals(
        program["last_report_filed_at"], FISCAL_YEAR_END, "last_report_filed_at"
    )
    assert program["last_report_status"] == K.REPORT_FILED_ON_TIME
    assert program["last_report_filed_by_user_id"] == FINANCE_1

    replay = api.file_annual_report(
        chain.program_id, factories.annual_report_filing_payload(2025), FINANCE
    )
    validate_error(replay, err.ERR_REPORT_ALREADY_FILED, 409)


def test_a_certificate_triggered_project_pays_straight_out_of_not_due(api):
    """Four state preconditions guard the payment: `assessment_status` must be
    `ASSESSED` or `REASSESSED`; `reassessment_required` must be false, or the
    payment is refused with `ERR_REASSESSMENT_REQUIRED` because the pinned schedule
    has been retired under the project's feet; `collection_status` must not already
    be `PAID`; and `collection_status` must not be `NOT_DUE` unless
    `collection_trigger` is `CERTIFICATE_OF_OCCUPANCY`, which is the one trigger
    under which a fee is paid straight out of `NOT_DUE`. An unpaid fee or an open
    deferral obligation both surface as `ERR_CO_BLOCKED_UNPAID`; an already-issued certificate
    surfaces as `ERR_APPLICATION_INVALID_STATE`. One `COLLECTION`
    row is created per assessed line whose `line_net_cents` is greater than zero,
    each carrying that line's `facility_category_id`, the application's id as its
    `development_application_id`, an `amount_cents` equal to the line's
    `line_net_cents`, a `vintage_at` stamped from the logical clock, a `deadline_at`
    set to that instant plus the program's `statutory_expenditure_deadline_years`
    years, an `unexpended_cents` equal to its full `amount_cents`, and an
    `entry_status` of `OPEN`.

    Design: Corner/validations/certificate_of_occupancy_triggered_application_pays_from_not_due
    """
    chain = fixtures.effective_program(api)
    application = fixtures.file_application(
        api,
        chain.program_id,
        permit_number="BP-2001",
        collection_trigger=K.TRIGGER_CERTIFICATE_OF_OCCUPANCY,
    )
    chain.application_id = application["id"]
    fixtures.set_clock(api, K.CLOCK_ASSESSMENT)
    assessed = fixtures.assess(api, chain.application_id)
    assert assessed["collection_status"] == K.COLLECTION_NOT_DUE

    blocked = api.issue_co(chain.application_id, PERMIT_OFFICER)

    validate_error(blocked, err.ERR_CO_BLOCKED_UNPAID, 409)
    unpaid = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    check.assert_fields_null(unpaid, "co_issued_at")

    paid = fixtures.pay(api, chain.application_id, K.BASELINE_NET_DUE)

    assert paid["collection_status"] == K.COLLECTION_PAID
    check.assert_application_totals(paid, paid_cents=K.BASELINE_NET_DUE)
    assert paid["assessment_status"] == K.ASSESSMENT_ASSESSED

    issued = validate_success(api.issue_co(chain.application_id, PERMIT_OFFICER))

    check.assert_timestamp_equals(issued["co_issued_at"], K.CLOCK_ASSESSMENT, "co_issued_at")
    assert issued["assessment_status"] == K.ASSESSMENT_ASSESSED
    rows = fixtures.ledger_rows(api, {"development_application_id": chain.application_id})
    assert len(rows) == 2
    amounts = sorted(row["amount_cents"] for row in rows)
    assert amounts == sorted([K.BASELINE_PARKS_LINE_NET, K.BASELINE_ROADS_LINE_NET])
    for row in rows:
        assert row["kind"] == K.LEDGER_KIND_COLLECTION
        assert row["entry_status"] == K.ENTRY_OPEN
        check.assert_timestamp_equals(row["vintage_at"], K.CLOCK_ASSESSMENT, "vintage_at")
        check.assert_timestamp_equals(row["deadline_at"], CO_DEADLINE, "deadline_at")
        check.assert_money_equals(
            row["unexpended_cents"], row["amount_cents"], "unexpended_cents"
        )


def test_a_second_payment_reports_the_state_failure_not_the_amount_failure(api):
    """Checks run in the following order, and the first violated check is the only
    error reported. `amount_cents` must equal `net_due_cents` minus `paid_cents` to
    the cent; anything else is refused with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP
    422). The three state failures other than the reassessment block all surface as
    `ERR_APPLICATION_INVALID_STATE`.

    Design: Corner/validations/payment_state_check_runs_before_the_payment_amount_check
    """
    chain = fixtures.effective_program(api)
    first = fixtures.file_application(api, chain.program_id)
    second = fixtures.file_application(api, chain.program_id, permit_number="BP-1002")
    fixtures.set_clock(api, K.CLOCK_ASSESSMENT)
    fixtures.assess(api, first["id"])
    fixtures.assess(api, second["id"])
    fixtures.set_clock(api, K.CLOCK_PAYMENT)
    fixtures.pay(api, first["id"], K.BASELINE_NET_DUE)

    replay = api.create_payment(first["id"], factories.payment_payload(100), PERMIT_OFFICER)

    validate_error(replay, err.ERR_APPLICATION_INVALID_STATE, 409)
    settled = get_success_data(api.get_development_application(first["id"], ADMIN))
    assert settled["collection_status"] == K.COLLECTION_PAID
    check.assert_application_totals(settled, paid_cents=K.BASELINE_NET_DUE)
    rows = fixtures.ledger_rows(api, {"development_application_id": first["id"]})
    assert len(rows) == 2, "no extra collection row may be booked"

    short = api.create_payment(
        second["id"], factories.payment_payload(K.BASELINE_NET_DUE - 1), PERMIT_OFFICER
    )

    validate_error(short, err.ERR_PAYMENT_AMOUNT_MISMATCH, 422)
    unpaid = get_success_data(api.get_development_application(second["id"], ADMIN))
    assert unpaid["collection_status"] == K.COLLECTION_DUE
    check.assert_application_totals(unpaid, paid_cents=0)
    assert fixtures.ledger_rows(api, {"development_application_id": second["id"]}) == []


def test_a_claim_may_only_name_a_category_the_effective_study_prices(api):
    """The claim names a `facility_category_code`, 2 to 12 uppercase letters and
    underscores, which is resolved to the facility category of the application's
    program bearing that code; the resolved category must be priced by a component
    of the application's effective study, and otherwise the claim is refused with
    `ERR_CREDIT_CATEGORY_NOT_IN_STUDY` (HTTP 422). A claim is born `SUBMITTED` with
    `approved_cents` at 0, `decided_by_user_id` and `decided_at` null, and no effect
    whatsoever on the application's money fields.

    Design: Corner/validations/credit_claim_category_must_be_priced_by_the_effective_study
    """
    chain = fixtures.effective_program(api, with_roads=False)
    roads = fixtures.create_roads_category(api, chain.program_id)
    chain.roads_category_id = roads["id"]
    fixtures.assessed_application(api, chain)
    def claim_body(facility_category_code):
        return {
            "facility_category_code": facility_category_code,
            "credit_type": K.CREDIT_TYPE_DEVELOPER_IMPROVEMENT,
            "valuation_method": K.VALUATION_NOMINAL,
            "improvement_value_cents": 500000,
        }

    unpriced = api.create_credit_claim(
        chain.application_id, claim_body(K.ROADS_CODE), DEVELOPER
    )
    unknown_code = api.create_credit_claim(
        chain.application_id, claim_body("TRAILS"), DEVELOPER
    )
    priced = api.create_credit_claim(
        chain.application_id, claim_body(K.PARKS_CODE), DEVELOPER
    )

    validate_error(unpriced, err.ERR_CREDIT_CATEGORY_NOT_IN_STUDY, 422)
    validate_error(unknown_code, err.ERR_CREDIT_CATEGORY_NOT_IN_STUDY, 422)
    accepted = validate_success(priced, 201)
    assert accepted["status"] == K.CLAIM_SUBMITTED
    check.assert_money_equals(
        accepted["claimed_credit_cents"], 500000, "claimed_credit_cents"
    )
    check.assert_money_equals(accepted["approved_cents"], 0, "approved_cents")
    check.assert_fields_null(accepted, "decided_by_user_id", "decided_at")
    claims = get_success_data(api.list_credit_claims(chain.application_id, ADMIN))
    assert len(claims) == 1
    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    check.assert_application_totals(
        application,
        gross_assessed_cents=K.BASELINE_PARKS_LINE_GROSS,
        credit_applied_cents=0,
        admin_charge_cents=PARKS_ONLY_ADMIN,
        net_due_cents=PARKS_ONLY_NET,
    )
    assert [line["facility_category_code"] for line in application["assessed_lines"]] == [
        K.PARKS_CODE
    ]
