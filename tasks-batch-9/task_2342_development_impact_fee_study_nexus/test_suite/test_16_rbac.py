"""Authority checks that run before anything else: the two mandatory headers, the
exclusive write matrix, the owner comparison inside the developer role, and the two
duty-separation rules that compare acting identities rather than role names."""

from test_helpers import ANALYST_1, CLERK_1, DEVELOPER_2, DUAL_1, FINANCE_1, FINANCE_2, NO_HEADERS
from test_helpers import api_errors as err
from test_helpers import assertions as check
from test_helpers import constants as K
from test_helpers import factories, fixtures, get_success_data, headers_with_blank_user_id
from test_helpers import make_analyst_headers, make_clerk_headers, make_developer_headers
from test_helpers import make_finance_headers, make_undeclared_role_headers
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.fixtures import ADMIN, CLERK, DEVELOPER, FINANCE, PERMIT_OFFICER

SECOND_DEVELOPER = make_developer_headers(DEVELOPER_2)
SECOND_FINANCE = make_finance_headers(FINANCE_2)
DUAL_ANALYST = make_analyst_headers(DUAL_1)
DUAL_CLERK = make_clerk_headers(DUAL_1)
UNDECLARED_ROLE = make_undeclared_role_headers()
CLOCK_AFTER_UNAUTHENTICATED_CALLS = "2026-01-06T00:00:00Z"
FISCAL_YEAR_END = "2026-07-01T00:00:00Z"
EXPENDITURE_INSIDE_FY2025 = 2000000
UNEXPENDED_AFTER_SPEND = K.BASELINE_NET_DUE - EXPENDITURE_INSIDE_FY2025


def test_a_request_without_the_two_mandatory_headers_is_unauthenticated(api):
    """Every request carries two mandatory headers: `X-User-ID`, identifying the
    acting user, and `X-User-Role`, declaring the capacity in which that user is
    acting. A request missing either header, or carrying a blank value for either, is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The sole exception is the
    logical-clock control endpoint described in §2.4, which is reachable without
    authentication headers. A test-only control capability at
    `POST /_clock/set_current_utc` accepts a `current_utc` instant and moves the
    clock to it; it echoes back `current_utc` and is the only endpoint exempt from
    the authentication headers.

    Design: Corner/rbac/calls_with_missing_x_user_headers_are_unauthenticated
    """
    fixtures.set_clock(api, K.CLOCK_PROGRAM_SETUP)
    program = fixtures.create_program(api)
    assert program["version"] == 1

    anonymous_read = api.get_fee_program(program["id"], NO_HEADERS)
    anonymous_create = api.create_fee_program(
        {"name": "Ghost Program", "jurisdiction_code": "GHOST"}, NO_HEADERS
    )
    blank_user_create = api.create_fee_program(
        {"name": "Ghost Program", "jurisdiction_code": "GHOST"},
        headers_with_blank_user_id(),
    )
    clock = api.set_clock(CLOCK_AFTER_UNAUTHENTICATED_CALLS, NO_HEADERS)

    validate_error(anonymous_read, err.ERR_UNAUTHENTICATED, 401)
    validate_error(anonymous_create, err.ERR_UNAUTHENTICATED, 401)
    validate_error(blank_user_create, err.ERR_UNAUTHENTICATED, 401)
    moved = validate_success(clock)
    check.assert_timestamp_equals(
        moved["current_utc"], CLOCK_AFTER_UNAUTHENTICATED_CALLS, "current_utc"
    )
    ghost = validate_success(
        api.create_fee_program(
            {"name": "Ghost Program", "jurisdiction_code": "GHOST"}, ADMIN
        ),
        201,
    )
    assert ghost["jurisdiction_code"] == "GHOST", "no unauthenticated call created it first"
    unchanged = get_success_data(api.get_fee_program(program["id"], ADMIN))
    check.assert_version_advanced_by(program["version"], unchanged["version"], 0)


def test_no_role_may_perform_another_roles_exclusive_write(api):
    """A value of `X-User-Role` that is not one of these six, or that is one of these
    six but is not authorized for the requested operation per the table in §4, is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403). A `ProgramAdministrator` owns the
    program's statutory constants and its facility standards and drives the statutory
    clock — effective-date activation and the deadline sweep are exclusively theirs. A
    `NexusAnalyst` builds the technical study: opening a study, adding and revising
    components, running allocations, adopting schedule lines, certifying the nexus
    findings, and reviewing credit claims. A `CouncilClerk` runs the legislative
    process: notice publication, the protest record, closing the protest window, and
    adoption. A `FinanceOfficer` is custodian of the fee funds: expenditures,
    statutory refunds and the annual report.

    Design: Corner/rbac/roles_cannot_perform_another_roles_exclusive_operations
    """
    chain = fixtures.certified_program(api)
    parks_version = fixtures.category_version(api, chain.parks_category_id)

    certification_by_officer = api.certify_nexus(chain.study_id, PERMIT_OFFICER)
    adoption_by_developer = api.adopt_fee_study(chain.study_id, DEVELOPER)
    expenditure_by_administrator = api.create_expenditure(
        chain.parks_category_id,
        factories.expenditure_payload(
            100000, parks_version, project_name="Unauthorised spend"
        ),
        ADMIN,
    )
    read_by_undeclared_role = api.get_fee_program(chain.program_id, UNDECLARED_ROLE)

    validate_error(certification_by_officer, err.ERR_UNAUTHORIZED, 403)
    validate_error(adoption_by_developer, err.ERR_UNAUTHORIZED, 403)
    validate_error(expenditure_by_administrator, err.ERR_UNAUTHORIZED, 403)
    validate_error(read_by_undeclared_role, err.ERR_UNAUTHORIZED, 403)
    assert fixtures.ledger_rows(api) == [], "the role check fired before any money moved"
    study = get_success_data(api.get_fee_study(chain.study_id, ADMIN))
    assert study["status"] == K.STUDY_NEXUS_CERTIFIED
    assert study["certified_by_user_id"] == ANALYST_1
    check.assert_fields_null(study, "adopted_at")
    assert fixtures.category_version(api, chain.parks_category_id) == parks_version


def test_a_developer_may_not_act_on_another_developers_application(api):
    """When `X-User-Role` is `Developer`, `X-User-ID` is the opaque identifier of the
    fee payer and it is persisted as `submitted_by_user_id` on the
    `DevelopmentApplication` the developer files; on the two application sub-resource
    writes — filing a credit claim and requesting a deferral agreement — the server
    compares that application's `submitted_by_user_id` to the caller's `X-User-ID`
    and rejects a mismatch with `ERR_NOT_APPLICATION_OWNER` (HTTP 403). A claim is
    born `SUBMITTED` with `approved_cents` at 0, `decided_by_user_id` and `decided_at`
    null, and no effect whatsoever on the application's money fields.

    Design: Corner/rbac/credit_and_deferral_requests_by_a_non_owner_developer_are_rejected
    """
    chain = fixtures.effective_program(api)
    fixtures.assessed_application(api, chain)
    claim_body = {
        "facility_category_code": K.PARKS_CODE,
        "credit_type": K.CREDIT_TYPE_DEVELOPER_IMPROVEMENT,
        "valuation_method": K.VALUATION_NOMINAL,
        "improvement_value_cents": 1000000,
    }

    claim_by_stranger = api.create_credit_claim(
        chain.application_id, claim_body, SECOND_DEVELOPER
    )
    deferral_by_stranger = api.create_deferral_agreement(
        chain.application_id,
        factories.deferral_agreement_payload(K.BASELINE_NET_DUE, "2027-05-01T00:00:00Z"),
        SECOND_DEVELOPER,
    )
    claim_by_owner = api.create_credit_claim(chain.application_id, claim_body, DEVELOPER)

    validate_error(claim_by_stranger, err.ERR_NOT_APPLICATION_OWNER, 403)
    validate_error(deferral_by_stranger, err.ERR_NOT_APPLICATION_OWNER, 403)
    claim = validate_success(claim_by_owner, 201)
    assert claim["status"] == K.CLAIM_SUBMITTED
    check.assert_money_equals(
        claim["claimed_credit_cents"], 1000000, "claimed_credit_cents"
    )
    _, claim_meta = validate_paginated(
        api.list_credit_claims(chain.application_id, ADMIN)
    )
    check.assert_pagination_meta(claim_meta, total_count=1)
    _, deferral_meta = validate_paginated(
        api.list_deferral_agreements(chain.application_id, ADMIN)
    )
    check.assert_pagination_meta(deferral_meta, total_count=0)
    application = get_success_data(
        api.get_development_application(chain.application_id, ADMIN)
    )
    check.assert_application_totals(application, net_due_cents=K.BASELINE_NET_DUE)


def test_the_user_who_certified_a_study_may_not_adopt_it(api):
    """The user identity that certified a study's nexus findings may not adopt that
    study. At adoption, the caller's `X-User-ID` is compared to the study's
    `certified_by_user_id`, and an equal value is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). Because certification belongs to
    `NexusAnalyst` and adoption to `CouncilClerk`, this bites only when one human
    holds both roles — which is precisely the case the statute is worried about.

    Design: Corner/rbac/one_user_cannot_certify_and_then_adopt_the_same_study
    """
    chain = fixtures.program_with_categories(api, with_roads=False)
    study = fixtures.create_study(api, chain.program_id)
    chain.study_id = study["id"]
    component = fixtures.create_parks_component(
        api, chain.study_id, chain.parks_category_id
    )
    fixtures.allocate(api, component["id"])
    fixtures.add_schedule_line(
        api, component["id"], K.PARKS_SINGLE_FAMILY_CONVERSION_FACTOR
    )
    certified = fixtures.certify(api, chain.study_id, headers=DUAL_ANALYST)
    assert certified["certified_by_user_id"] == DUAL_1
    fixtures.set_clock(api, K.CLOCK_NOTICE_PUBLISHED)
    fixtures.publish_notice(api, chain.study_id)
    fixtures.set_clock(api, K.CLOCK_PROTEST_WINDOW_END)
    fixtures.close_protest_window(api, chain.study_id)
    fixtures.set_clock(api, K.CLOCK_ADOPTION)

    conflicted = api.adopt_fee_study(chain.study_id, DUAL_CLERK)

    validate_error(conflicted, err.ERR_SEGREGATION_OF_DUTIES, 409)
    still_cleared = get_success_data(api.get_fee_study(chain.study_id, ADMIN))
    assert still_cleared["status"] == K.STUDY_PROTEST_CLEARED
    check.assert_fields_null(
        still_cleared, "adopted_at", "adopted_by_user_id", "effective_at"
    )

    adopted = validate_success(api.adopt_fee_study(chain.study_id, CLERK))

    assert adopted["status"] == K.STUDY_ADOPTED
    assert adopted["adopted_by_user_id"] == CLERK_1
    check.assert_timestamp_equals(adopted["adopted_at"], K.CLOCK_ADOPTION, "adopted_at")
    check.assert_timestamp_equals(
        adopted["effective_at"], K.CLOCK_EFFECTIVE_DATE, "effective_at"
    )
    assert adopted["certified_by_user_id"] == DUAL_1, "adoption does not rewrite the certifier"


def test_the_officer_who_authorized_a_years_spending_may_not_report_it(api):
    """The user identity that authorized any expenditure inside a fiscal year may
    not file that fiscal year's annual report. At filing, the caller's `X-User-ID` is
    compared to the `authorized_by_user_id` of every `EXPENDITURE` ledger row created
    inside the reported year's window, and a match anywhere in that set is rejected
    with `ERR_REPORT_PREPARER_CONFLICT` (HTTP 409). Both operations belong to
    `FinanceOfficer`, so the role matrix cannot enforce this at all: the same finance
    officer may spend or report for a given year, never both. `expenditures_cents`
    sums `amount_cents` over `EXPENDITURE` rows whose `created_at` falls inside the
    window, and `refunds_cents` does the same over `REFUND` rows — outflows are dated
    by when they were recorded, not by the vintage they consumed. The remaining three
    are cumulative, not windowed, because the statutory disclosure is the balance at
    the close of the year including money collected in earlier years:
    `unexpended_cents` sums `unexpended_cents` over every `COLLECTION` row whose
    `vintage_at` is before `window_end`, `refund_obligation_cents` sums
    `unexpended_cents` over those same rows restricted to `entry_status` `REFUND_DUE`,
    and `earliest_deadline_at` is the earliest `deadline_at` among those same rows
    restricted to `entry_status` `OPEN` or `PARTIALLY_EXPENDED`.

    Design: Corner/rbac/the_officer_who_spent_the_fund_cannot_file_that_years_report
    """
    chain = fixtures.effective_program_with_paid_application(api)
    spent = fixtures.spend(api, chain.parks_category_id, EXPENDITURE_INSIDE_FY2025)
    assert spent["authorized_by_user_id"] == FINANCE_1
    fixtures.set_clock(api, FISCAL_YEAR_END)

    conflicted = api.file_annual_report(
        chain.program_id, factories.annual_report_filing_payload(2025), FINANCE
    )

    validate_error(conflicted, err.ERR_REPORT_PREPARER_CONFLICT, 409)
    unfiled = get_success_data(api.get_fee_program(chain.program_id, ADMIN))
    assert unfiled["last_report_status"] == K.REPORT_NOT_FILED

    filed = validate_success(
        api.file_annual_report(
            chain.program_id, factories.annual_report_filing_payload(2025), SECOND_FINANCE
        ),
        201,
    )

    assert filed["fiscal_year"] == 2025
    assert filed["filed_late"] is False
    assert filed["report_status"] == K.REPORT_FILED_ON_TIME
    check.assert_money_equals(
        filed["collections_cents"], K.BASELINE_NET_DUE, "collections_cents"
    )
    check.assert_money_equals(
        filed["expenditures_cents"], EXPENDITURE_INSIDE_FY2025, "expenditures_cents"
    )
    check.assert_money_equals(filed["refunds_cents"], 0, "refunds_cents")
    check.assert_money_equals(
        filed["unexpended_cents"], UNEXPENDED_AFTER_SPEND, "unexpended_cents"
    )
    check.assert_money_equals(
        filed["refund_obligation_cents"], 0, "refund_obligation_cents"
    )
    program = get_success_data(api.get_fee_program(chain.program_id, ADMIN))
    assert program["last_report_fiscal_year"] == 2025
    assert program["last_report_status"] == K.REPORT_FILED_ON_TIME
    assert program["last_report_filed_by_user_id"] == FINANCE_2

    replay = api.file_annual_report(
        chain.program_id, factories.annual_report_filing_payload(2025), SECOND_FINANCE
    )
    validate_error(replay, err.ERR_REPORT_ALREADY_FILED, 409)
