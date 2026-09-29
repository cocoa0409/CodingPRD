"""Requests that break two rules at once, where the reply must name the
higher-priority failure and not the cheaper one."""

from test_helpers import api_errors as err
from test_helpers import assertions as check
from test_helpers import constants as K
from test_helpers import factories, fixtures, get_success_data, validate_error
from test_helpers.fixtures import ADMIN, CLERK, DEVELOPER, FINANCE

OVER_BUDGET_CENTS = 9999999


def _expenditure_attempt(api, category_id, amount_cents):
    payload = factories.expenditure_payload(
        amount_cents,
        fixtures.category_version(api, category_id),
        project_name="Harbor Green Playfield",
    )
    return api.create_expenditure(category_id, payload, FINANCE)


def _fund_in_refund_due(api):
    """A parks fund whose only collection has breached its statutory deadline."""
    chain = fixtures.effective_program_with_paid_application(api)
    fixtures.set_clock(api, "2031-05-10T00:00:00Z")
    swept = fixtures.sweep(api, chain.program_id)
    return chain, swept


def test_the_refund_obligation_is_reported_before_the_shortfall(api):
    """Two guards precede the arithmetic, in this order. First, the category's
    `fund_posture` must not be `REFUND_DUE`: an outstanding statutory refund
    obligation must be discharged before any further expenditure from that fund,
    and the attempt is otherwise refused with
    `ERR_FUND_REFUND_OBLIGATION_PENDING`.

    Design: Difficulty/priority_pair_validation_conflict/refund_obligation_outranks_insufficient_fund_balance
    """
    chain, swept = _fund_in_refund_due(api)
    assert swept["refund_due_entry_count"] == 2
    parks_before = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(
        parks_before,
        fund_balance_cents=K.BASELINE_PARKS_LINE_NET,
        refund_due_cents=K.BASELINE_PARKS_LINE_NET,
        fund_posture=K.FUND_POSTURE_REFUND_DUE,
    )

    response = _expenditure_attempt(api, chain.parks_category_id, OVER_BUDGET_CENTS)

    body = validate_error(response, err.ERR_FUND_REFUND_OBLIGATION_PENDING, 409)
    assert body["error_id"] != err.ERR_INSUFFICIENT_FUND_BALANCE
    assert fixtures.rows_of_kind(api, K.LEDGER_KIND_EXPENDITURE) == []
    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(
        parks,
        fund_balance_cents=K.BASELINE_PARKS_LINE_NET,
        refund_due_cents=K.BASELINE_PARKS_LINE_NET,
        fund_posture=K.FUND_POSTURE_REFUND_DUE,
    )


def test_the_shortfall_is_reported_once_no_obligation_stands_in_the_way(api):
    """Second, the amount must be affordable, which is deliberately narrower than
    the fund's balance. A fund carrying an outstanding statutory refund
    obligation reports `ERR_FUND_REFUND_OBLIGATION_PENDING` even when the
    requested expenditure would also have exceeded its expendable balance — the
    refund obligation is checked well above the fiscal test, so
    `ERR_INSUFFICIENT_FUND_BALANCE` never surfaces in that situation.

    Design: Difficulty/priority_pair_validation_conflict/refund_obligation_outranks_insufficient_fund_balance
    """
    chain = fixtures.effective_program_with_paid_application(api)
    parks_before = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(
        parks_before,
        fund_balance_cents=K.BASELINE_PARKS_LINE_NET,
        refund_due_cents=0,
        fund_posture=K.FUND_POSTURE_COMPLIANT,
    )

    response = _expenditure_attempt(api, chain.parks_category_id, OVER_BUDGET_CENTS)

    validate_error(response, err.ERR_INSUFFICIENT_FUND_BALANCE, 422)
    assert fixtures.rows_of_kind(api, K.LEDGER_KIND_EXPENDITURE) == []
    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(
        parks,
        fund_balance_cents=K.BASELINE_PARKS_LINE_NET,
        fund_posture=K.FUND_POSTURE_COMPLIANT,
    )
    assert parks["version"] == parks_before["version"], "a rejected expenditure writes nothing"


def _two_certified_parks_studies(api):
    chain = fixtures.program_with_categories(api, with_roads=False)
    study_a = fixtures.create_study(api, chain.program_id)
    study_b = fixtures.create_study(
        api, chain.program_id, title="2026 Impact Fee Study - Alternate"
    )
    for study in (study_a, study_b):
        component = fixtures.create_parks_component(
            api, study["id"], chain.parks_category_id
        )
        fixtures.allocate(api, component["id"])
        fixtures.add_schedule_line(
            api, component["id"], K.PARKS_SINGLE_FAMILY_CONVERSION_FACTOR
        )
        fixtures.certify(api, study["id"])
    chain.study_id = study_a["id"]
    return chain, study_a, study_b


def test_the_occupied_notice_window_is_reported_before_the_short_period(api):
    """Two guards apply, and their relative order matters. Likewise, a notice
    published while another study of the same program still occupies its notice
    window reports `ERR_NOTICE_WINDOW_OVERLAP` even when the submitted notice
    period is also below the statutory minimum; `ERR_NOTICE_PERIOD_TOO_SHORT` is
    only reachable once no window conflict exists.

    Design: Difficulty/priority_pair_validation_conflict/notice_window_overlap_outranks_notice_period_too_short
    """
    chain, study_a, study_b = _two_certified_parks_studies(api)
    fixtures.set_clock(api, K.CLOCK_NOTICE_PUBLISHED)
    fixtures.publish_notice(api, study_a["id"], notice_days=30)
    fixtures.set_clock(api, "2026-02-01T00:00:00Z")

    response = api.publish_notice(
        study_b["id"], {"notice_method": K.NOTICE_MAILED, "notice_days": 7}, CLERK
    )

    body = validate_error(response, err.ERR_NOTICE_WINDOW_OVERLAP, 409)
    assert body["error_id"] != err.ERR_NOTICE_PERIOD_TOO_SHORT
    blocked = get_success_data(api.get_fee_study(study_b["id"], ADMIN))
    assert blocked["status"] == K.STUDY_NEXUS_CERTIFIED
    check.assert_fields_null(
        blocked, "notice_method", "notice_days", "notice_published_at", "protest_window_ends_at"
    )
    occupant = get_success_data(api.get_fee_study(study_a["id"], ADMIN))
    assert occupant["status"] == K.STUDY_NOTICE_PUBLISHED
    check.assert_timestamp_equals(
        occupant["protest_window_ends_at"], K.CLOCK_PROTEST_WINDOW_END, "protest_window_ends_at"
    )


def test_the_short_notice_period_surfaces_once_the_window_is_free(api):
    """Second, and only once no window conflict exists, `notice_days` must be at
    least the program's `notice_min_days`; a shorter period returns
    `ERR_NOTICE_PERIOD_TOO_SHORT` (HTTP 422). Publishing exactly at another
    study's `protest_window_ends_at` is therefore accepted — for timestamps,
    adjacency is not overlap — while publishing anywhere strictly inside returns
    `ERR_NOTICE_WINDOW_OVERLAP`.

    Design: Difficulty/priority_pair_validation_conflict/notice_window_overlap_outranks_notice_period_too_short
    """
    chain, study_a, study_b = _two_certified_parks_studies(api)
    fixtures.set_clock(api, K.CLOCK_NOTICE_PUBLISHED)
    fixtures.publish_notice(api, study_a["id"], notice_days=30)
    fixtures.set_clock(api, K.CLOCK_PROTEST_WINDOW_END)

    response = api.publish_notice(
        study_b["id"], {"notice_method": K.NOTICE_MAILED, "notice_days": 7}, CLERK
    )

    validate_error(response, err.ERR_NOTICE_PERIOD_TOO_SHORT, 422)
    blocked = get_success_data(api.get_fee_study(study_b["id"], ADMIN))
    assert blocked["status"] == K.STUDY_NEXUS_CERTIFIED
    check.assert_fields_null(blocked, "notice_published_at", "protest_window_ends_at")


MALFORMED_CLAIM = {
    "facility_category_code": K.PARKS_CODE,
    "credit_type": K.CREDIT_TYPE_DEVELOPER_IMPROVEMENT,
    "valuation_method": "MARKET",
    "improvement_value_cents": -5,
}


def test_the_unknown_application_is_reported_before_the_malformed_body(api):
    """When a request violates more than one rule, exactly one error is returned,
    and which one is fully determined. Where a path does carry an identifier,
    that identifier is resolved before any body or business rule is examined, and
    the 404 that comes back names the resource type that failed to resolve:
    `ERR_FEE_PROGRAM_NOT_FOUND`, `ERR_FACILITY_CATEGORY_NOT_FOUND`,
    `ERR_FEE_STUDY_NOT_FOUND`, `ERR_NEXUS_COMPONENT_NOT_FOUND`,
    `ERR_DEVELOPMENT_APPLICATION_NOT_FOUND`, `ERR_CREDIT_CLAIM_NOT_FOUND`,
    `ERR_DEFERRAL_AGREEMENT_NOT_FOUND`, `ERR_PROTEST_FILING_NOT_FOUND` or
    `ERR_FUND_LEDGER_ENTRY_NOT_FOUND`.

    Design: Difficulty/priority_pair_validation_conflict/application_not_found_outranks_invalid_request
    """
    fixtures.program_with_categories(api, with_roads=False)

    response = api.create_credit_claim(K.UNKNOWN_ID_9, dict(MALFORMED_CLAIM), DEVELOPER)

    body = validate_error(response, err.ERR_DEVELOPMENT_APPLICATION_NOT_FOUND, 404)
    assert body["error_id"] != err.ERR_INVALID_REQUEST
    assert body["message"], "the error envelope must carry a non-empty message"


def test_the_malformed_body_surfaces_once_the_application_resolves(api):
    """Checks run in the following order, and the first violated check is the only
    error reported. Schema — required fields present, types correct, enum values
    inside their declared sets, integers inside their declared ranges, decimals
    within their declared scale, timestamps ISO-8601 UTC, `limit` between 1 and 100,
    `offset` at least 0, `dwelling_units` and `nonres_sqft` each at least 0 and not
    both zero, `conversion_factor` greater than 0, and a partial credit approval
    carrying an `approved_cents` strictly greater than 0 and strictly less than the
    claim's `claimed_credit_cents` (`ERR_INVALID_REQUEST`, 422).

    Design: Difficulty/priority_pair_validation_conflict/application_not_found_outranks_invalid_request
    """
    chain = fixtures.effective_program(api)
    fixtures.assessed_application(api, chain)

    response = api.create_credit_claim(chain.application_id, dict(MALFORMED_CLAIM), DEVELOPER)

    validate_error(response, err.ERR_INVALID_REQUEST, 422)
    claims = get_success_data(api.list_credit_claims(chain.application_id, ADMIN))
    assert claims == [], "a rejected claim body must not create a row"
    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    check.assert_application_totals(
        application, credit_applied_cents=0, net_due_cents=K.BASELINE_NET_DUE
    )
