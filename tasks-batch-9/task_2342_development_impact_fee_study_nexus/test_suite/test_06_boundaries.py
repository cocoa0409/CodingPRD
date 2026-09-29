"""Inclusive boundaries walked to the second and to the basis point."""

from test_helpers import ANALYST_1, api_errors as err
from test_helpers import assertions as check
from test_helpers import constants as K
from test_helpers import fixtures, get_success_data, validate_error
from test_helpers.fixtures import ADMIN

STUDY_B_WINDOW_END = "2026-03-22T00:00:00Z"


def _two_noticed_studies_on_either_side_of_the_threshold(api):
    """Study A tallies 4999 basis points and study B tallies exactly 5000."""
    chain = fixtures.program_with_categories(api, with_roads=False)
    study_a = fixtures.create_study(api, chain.program_id)
    study_b = fixtures.create_study(
        api, chain.program_id, title="2026 Impact Fee Study - Alternate"
    )
    for study in (study_a, study_b):
        component = fixtures.create_parks_component(api, study["id"], chain.parks_category_id)
        fixtures.allocate(api, component["id"])
        fixtures.add_schedule_line(
            api, component["id"], K.PARKS_SINGLE_FAMILY_CONVERSION_FACTOR
        )
        fixtures.certify(api, study["id"])
    chain.study_id = study_a["id"]

    fixtures.set_clock(api, K.CLOCK_NOTICE_PUBLISHED)
    fixtures.publish_notice(api, study_a["id"], notice_days=30)
    fixtures.record_protest(
        api, study_a["id"], protester_name="Harbor Heights Owners", parcel_count=12, weight_bp=3000
    )
    fixtures.record_protest(
        api, study_a["id"], protester_name="Bayside Builders Council", parcel_count=8, weight_bp=1999
    )
    fixtures.set_clock(api, K.CLOCK_PROTEST_WINDOW_END)
    fixtures.close_protest_window(api, study_a["id"])

    fixtures.set_clock(api, "2026-02-20T00:00:00Z")
    fixtures.publish_notice(api, study_b["id"], notice_days=30)
    fixtures.record_protest(
        api, study_b["id"], protester_name="Harbor Heights Owners", parcel_count=12, weight_bp=3000
    )
    fixtures.record_protest(
        api, study_b["id"], protester_name="Downtown Merchants Group", parcel_count=9, weight_bp=2000
    )
    fixtures.set_clock(api, STUDY_B_WINDOW_END)
    return chain, study_a, study_b


def test_a_tally_exactly_at_the_threshold_sustains_the_protest(api):
    """`revision_round` increments by one. `certified_by_user_id` and
    `certified_at` are both cleared to null. Every filing of that study whose
    `status` was `RECORDED` moves to `VOIDED`, and `protest_weight_bp` and
    `protest_count` are both reset to 0, because the next notice starts a fresh
    protest period and the old filings may not be carried forward.

    Design: Difficulty/boundary_precision_check/protest_weight_exactly_at_threshold_sustains_the_protest
    """
    _, _, study_b = _two_noticed_studies_on_either_side_of_the_threshold(api)
    noticed_b = get_success_data(api.get_fee_study(study_b["id"], ADMIN))
    assert noticed_b["protest_weight_bp"] == K.DEFAULT_PROTEST_THRESHOLD_BP
    check.assert_timestamp_equals(
        noticed_b["protest_window_ends_at"], STUDY_B_WINDOW_END, "protest_window_ends_at"
    )

    remanded = fixtures.close_protest_window(api, study_b["id"])

    assert remanded["status"] == K.STUDY_DRAFT
    assert remanded["revision_round"] == 1
    assert remanded["protest_weight_bp"] == 0
    assert remanded["protest_count"] == 0
    check.assert_fields_null(remanded, "notice_published_at", "protest_window_ends_at")
    filings = get_success_data(api.list_protest_filings(study_b["id"], ADMIN))
    assert {filing["status"] for filing in filings} == {K.PROTEST_VOIDED}


def test_a_tally_one_basis_point_short_clears_the_window(api):
    """The study's `version` increments. Every `RECORDED` filing is left exactly
    as it is, so the tally that the council relied on stays on the record. Each
    filing is born with `status` `RECORDED` and `filed_at` from the logical clock,
    adds its `weight_bp` to the study's `protest_weight_bp`, adds one to
    `protest_count`, and increments the study's `version`.

    Design: Difficulty/boundary_precision_check/protest_weight_exactly_at_threshold_sustains_the_protest
    """
    _, study_a, study_b = _two_noticed_studies_on_either_side_of_the_threshold(api)

    fixtures.close_protest_window(api, study_b["id"])

    cleared = get_success_data(api.get_fee_study(study_a["id"], ADMIN))
    assert cleared["status"] == K.STUDY_PROTEST_CLEARED
    assert cleared["protest_weight_bp"] == K.DEFAULT_PROTEST_THRESHOLD_BP - 1
    assert cleared["protest_count"] == 2
    assert cleared["certified_by_user_id"] == ANALYST_1
    filings = get_success_data(api.list_protest_filings(study_a["id"], ADMIN))
    assert {filing["status"] for filing in filings} == {K.PROTEST_RECORDED}
    assert sum(filing["weight_bp"] for filing in filings) == K.DEFAULT_PROTEST_THRESHOLD_BP - 1


def test_activation_one_second_early_is_refused(api):
    """The study must be in `ADOPTED` (`ERR_STUDY_INVALID_STATE`) and the logical
    clock must have reached `effective_at`, inclusively — activating exactly at
    that instant is allowed, and activating earlier returns
    `ERR_EFFECTIVE_DATE_NOT_REACHED`.

    Design: Difficulty/boundary_precision_check/activation_exactly_on_the_effective_date_is_permitted
    """
    chain = fixtures.adopted_program(api, with_roads=False)
    adopted = get_success_data(api.get_fee_study(chain.study_id, ADMIN))
    check.assert_timestamp_equals(
        adopted["effective_at"], K.CLOCK_EFFECTIVE_DATE, "effective_at"
    )

    fixtures.set_clock(api, "2026-04-15T23:59:59Z")
    response = api.activate_fee_study(chain.study_id, ADMIN)

    validate_error(response, err.ERR_EFFECTIVE_DATE_NOT_REACHED, 409)
    study = get_success_data(api.get_fee_study(chain.study_id, ADMIN))
    assert study["status"] == K.STUDY_ADOPTED
    check.assert_fields_null(study, "activated_at")


def test_activation_exactly_on_the_effective_instant_succeeds(api):
    """Activation stamps `activated_at` from the logical clock and increments the
    study's `version`, and then cascades in two further hops. Finally the
    program's own `version` increments, because its derived
    `effective_fee_study_id` now resolves to a different study.

    Design: Difficulty/boundary_precision_check/activation_exactly_on_the_effective_date_is_permitted
    """
    chain = fixtures.adopted_program(api, with_roads=False)
    fixtures.set_clock(api, "2026-04-15T23:59:59Z")
    api.activate_fee_study(chain.study_id, ADMIN)

    fixtures.set_clock(api, K.CLOCK_EFFECTIVE_DATE)
    activated = get_success_data(api.activate_fee_study(chain.study_id, ADMIN))

    assert activated["status"] == K.STUDY_EFFECTIVE
    check.assert_timestamp_equals(
        activated["activated_at"], K.CLOCK_EFFECTIVE_DATE, "activated_at"
    )
    program = get_success_data(api.get_fee_program(chain.program_id, ADMIN))
    assert program["effective_fee_study_id"] == chain.study_id


def test_the_at_risk_window_opens_inclusively_and_stays_open(api):
    """Both comparisons are inclusive at the boundary, and that boundary is
    pinned: with a five-year deadline and a 365-day at-risk window, a collection
    vintaged 10 May 2026 has a deadline of 10 May 2031, so a sweep on 9 May 2030
    leaves the fund `COMPLIANT`, a sweep on 10 May 2030 makes it `AT_RISK`
    because the deadline falls exactly one window out, a sweep on 9 May 2031
    leaves it `AT_RISK`, and a sweep on 10 May 2031 breaches the row exactly on
    its deadline, turning it `REFUND_DUE` and blocking further expenditure from
    that fund.

    Design: Difficulty/boundary_precision_check/collection_becomes_refund_due_exactly_on_the_statutory_deadline
    """
    chain = fixtures.effective_program_with_paid_application(api)
    parks_row = fixtures.collection_rows_for(api, chain.parks_category_id)[0]
    check.assert_timestamp_equals(parks_row["vintage_at"], K.CLOCK_PAYMENT, "vintage_at")
    check.assert_timestamp_equals(
        parks_row["deadline_at"], "2031-05-10T00:00:00Z", "deadline_at"
    )

    for instant, posture in (
        ("2030-05-09T00:00:00Z", K.FUND_POSTURE_COMPLIANT),
        ("2030-05-10T00:00:00Z", K.FUND_POSTURE_AT_RISK),
        ("2031-05-09T00:00:00Z", K.FUND_POSTURE_AT_RISK),
    ):
        fixtures.set_clock(api, instant)
        swept = fixtures.sweep(api, chain.program_id)
        assert swept["refund_due_entry_count"] == 0, f"nothing may breach at {instant}"
        parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
        check.assert_category_fund(parks, refund_due_cents=0, fund_posture=posture)


def test_a_collection_breaches_on_its_deadline_and_owes_a_refund(api):
    """Only the sweep may convert a breach into an obligation: for every
    `COLLECTION` row of the category whose `entry_status` is `OPEN` or
    `PARTIALLY_EXPENDED`, the sweep sets `entry_status` to `REFUND_DUE` when the
    logical clock has reached that row's `deadline_at`, incrementing the row's
    `version`. It reports what it did as `refund_due_entry_ids` and
    `refund_due_entry_count`, `defaulted_agreement_ids`,
    `delinquent_application_ids`, `at_risk_category_ids` and
    `refund_due_category_ids`.

    Design: Difficulty/boundary_precision_check/collection_becomes_refund_due_exactly_on_the_statutory_deadline
    """
    chain = fixtures.effective_program_with_paid_application(api)
    parks_row = fixtures.collection_rows_for(api, chain.parks_category_id)[0]
    fixtures.set_clock(api, "2031-05-09T00:00:00Z")
    fixtures.sweep(api, chain.program_id)

    fixtures.set_clock(api, "2031-05-10T00:00:00Z")
    swept = fixtures.sweep(api, chain.program_id)

    assert swept["refund_due_entry_count"] == 2
    assert parks_row["id"] in swept["refund_due_entry_ids"]
    assert chain.parks_category_id in swept["refund_due_category_ids"]
    breached = get_success_data(api.get_fund_ledger_entry(parks_row["id"], ADMIN))
    assert breached["entry_status"] == K.ENTRY_REFUND_DUE
    check.assert_money_equals(
        breached["unexpended_cents"], K.BASELINE_PARKS_LINE_NET, "unexpended_cents"
    )
    parks = get_success_data(api.get_facility_category(chain.parks_category_id, ADMIN))
    check.assert_category_fund(
        parks,
        fund_balance_cents=K.BASELINE_PARKS_LINE_NET,
        refund_due_cents=K.BASELINE_PARKS_LINE_NET,
        fund_posture=K.FUND_POSTURE_REFUND_DUE,
    )
