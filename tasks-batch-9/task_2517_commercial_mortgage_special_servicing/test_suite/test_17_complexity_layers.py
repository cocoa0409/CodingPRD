"""The two optimistic-concurrency gates on their own write endpoints, and the
cumulative timely-payment counter that a single missed payment sends back to
zero.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ASSET_MANAGER,
    COMMITTEE_OFFICER,
    MASTER_SERVICER,
    TRUSTEE,
)


# ==========================================================================
# One trust and one master-serviced loan carrying an unconsumed petition
# ==========================================================================
def _a_trust_and_a_loan_awaiting_transfer(api):
    """No advances and no appraisals, so nothing but the transfer can move a
    version."""
    trust = fx.create_trust(
        api,
        deal_name="CMBS 2026-V46",
        closing_date="2026-01-15T00:00:00Z",
        original_controlling_class_balance_usd=40000000,
    )
    loan = fx.create_mid_size_loan(
        api,
        trust["id"],
        loan_number="L-V46",
        maturity_date="2029-06-01T00:00:00Z",
    )
    fx.record_bankruptcy_event(
        api, loan["id"], occurred_on="2026-07-01T00:00:00Z", evidence_note="chapter 11 petition"
    )
    return trust, loan


def test_neither_repeated_read_advances_the_version_it_reports(api):
    """Two consecutive reads of each row report one and the same version.

    The PRD: "Note that a loan's `version` advances on *every* write touching the
    loan row, including writes driven from other aggregates — an appraisal
    reduction becoming effective, an advance being reversed, a fee being collected
    — so any such cascade invalidates a previously observed `expected_loan_version`."

    Design: Corner/complexity_layers/both_declared_version_gates_reject_a_stale_read
    """
    trust, loan = _a_trust_and_a_loan_awaiting_transfer(api)

    trust_read_a = fx.read_trust(api, trust["id"], TRUSTEE)
    trust_read_b = fx.read_trust(api, trust["id"], TRUSTEE)
    loan_read_a = fx.read_loan(api, loan["id"], MASTER_SERVICER)
    loan_read_b = fx.read_loan(api, loan["id"], MASTER_SERVICER)

    a.assert_version_is(trust_read_b, trust_read_a["version"], "trust")
    a.assert_version_is(loan_read_b, loan_read_a["version"], "loan")
    assert trust_read_a == trust_read_b, "reading a trust twice returns the same row"
    assert loan_read_a == loan_read_b, "reading a loan twice returns the same row"

    third_trust_read = fx.read_trust(api, trust["id"], TRUSTEE)
    a.assert_version_is(third_trust_read, trust_read_a["version"], "trust")


def test_the_transfer_makes_both_captured_versions_stale_at_once(api):
    """One transfer bumps the loan and the trust, so both gates fire.

    The PRD: "The service compares it to the loan row's current `version`; a
    mismatch is refused with `ERR_STALE_LOAN_VERSION` and HTTP status 412, and no
    plan row is created."

    Design: Corner/complexity_layers/both_declared_version_gates_reject_a_stale_read
    """
    trust, loan = _a_trust_and_a_loan_awaiting_transfer(api)
    trust_version_0 = fx.read_trust(api, trust["id"], TRUSTEE)["version"]
    loan_version_0 = fx.read_loan(api, loan["id"], MASTER_SERVICER)["version"]

    transferred = fx.transfer_to_special_servicing(api, loan["id"])
    a.assert_status(transferred, "SPECIAL_SERVICING", "servicing_status")
    loan_version_1 = transferred["version"]
    assert loan_version_1 != loan_version_0, "the transfer advanced the loan's version"

    stale_plan = api.create_workout_plan(
        f.workout_plan_payload(loan["id"], loan_version_0, discount_rate_pct=8.0),
        ASSET_MANAGER,
    )
    validate_error(stale_plan, e.ERR_STALE_LOAN_VERSION, 412)
    plans, plan_meta = validate_paginated(
        api.list_workout_plans(ASSET_MANAGER, {"loan_id": loan["id"]})
    )
    assert plan_meta["total_count"] == 0, "a refused plan creation leaves no plan row"
    assert plans == []

    stale_report = api.create_distribution_report(
        f.distribution_report_payload(
            trust["id"],
            trust_version_0,
            report_type="DELINQUENT_LOAN_STATUS",
            period_end="2026-07-31T00:00:00Z",
        ),
        TRUSTEE,
    )
    validate_error(stale_report, e.ERR_STALE_TRUST_VERSION, 412)
    reports, report_meta = validate_paginated(
        api.list_distribution_reports(TRUSTEE, {"trust_id": trust["id"]})
    )
    assert report_meta["total_count"] == 0, "a refused report creation leaves no report row"
    assert reports == []

    still_transferred = fx.read_loan(api, loan["id"], MASTER_SERVICER)
    a.assert_status(still_transferred, "SPECIAL_SERVICING", "servicing_status")
    a.assert_version_is(still_transferred, loan_version_1, "loan")

    trust_after = fx.read_trust(api, trust["id"], TRUSTEE)
    trust_version_1 = trust_after["version"]
    assert trust_version_1 != trust_version_0, (
        "the transfer recomputed the trust's count of loans in special servicing"
    )
    assert trust_after["loans_in_special_servicing_count"] == 1

    report = validate_success(
        api.create_distribution_report(
            f.distribution_report_payload(
                trust["id"],
                trust_version_1,
                report_type="DELINQUENT_LOAN_STATUS",
                period_end="2026-07-31T00:00:00Z",
            ),
            TRUSTEE,
        ),
        201,
    )
    a.assert_status(report, "DRAFT")
    assert report["loans_in_special_count"] == 1

    plan = validate_success(
        api.create_workout_plan(
            f.workout_plan_payload(loan["id"], loan_version_1, discount_rate_pct=8.0),
            ASSET_MANAGER,
        ),
        201,
    )
    a.assert_status(plan, "DRAFT")


def test_a_captured_loan_version_is_good_for_exactly_one_write(api):
    """The write that consumed the version invalidated it for the next one.

    The PRD: "A caller that re-reads the loan and resubmits with the fresh version
    succeeds."

    Design: Corner/complexity_layers/both_declared_version_gates_reject_a_stale_read
    """
    _, loan = _a_trust_and_a_loan_awaiting_transfer(api)
    transferred = fx.transfer_to_special_servicing(api, loan["id"])
    loan_version_1 = transferred["version"]

    first_plan = validate_success(
        api.create_workout_plan(
            f.workout_plan_payload(loan["id"], loan_version_1, discount_rate_pct=8.0),
            ASSET_MANAGER,
        ),
        201,
    )

    after_the_plan = fx.read_loan(api, loan["id"], MASTER_SERVICER)
    a.assert_version_is(after_the_plan, loan_version_1 + 1, "loan")
    a.assert_status(after_the_plan, "IN_WORKOUT", "servicing_status")
    assert after_the_plan["active_workout_plan_id"] == first_plan["id"]

    replay = api.create_workout_plan(
        f.workout_plan_payload(loan["id"], loan_version_1, discount_rate_pct=9.0),
        ASSET_MANAGER,
    )
    validate_error(replay, e.ERR_STALE_LOAN_VERSION, 412)

    plans, meta = validate_paginated(
        api.list_workout_plans(ASSET_MANAGER, {"loan_id": loan["id"]})
    )
    assert meta["total_count"] == 1, "the refused replay created no second plan"
    a.assert_status(plans[0], "DRAFT")
    assert plans[0]["id"] == first_plan["id"], (
        "the surviving plan was not superseded by a call that never happened"
    )
    a.assert_version_is(
        fx.read_loan(api, loan["id"], MASTER_SERVICER), loan_version_1 + 1, "loan"
    )


# ==========================================================================
# A corrected loan accumulating the three payments that hand it back
# ==========================================================================
def _certified_imminent_default(api, loan_id):
    """The one event code whose qualification depends on a certification."""
    return fx.record_transfer_event(
        api,
        loan_id,
        event_code="IMMINENT_DEFAULT",
        occurred_on="2026-07-01T00:00:00Z",
        evidence_note="borrower notice of imminent monetary default",
        days_delinquent_at_event=None,
        imminent_default_certified=True,
    )


def _the_modification_route(api, plan_id):
    return fx.add_modification_alternative(
        api,
        plan_id,
        projected_cash_flows=[
            {"period_index": 1, "amount_usd": 1000000},
            {"period_index": 2, "amount_usd": 8500000},
        ],
        upfront_cost_usd=100000,
    )


def _a_corrected_loan_under_an_executed_modification(api):
    """A 10,000,000.00 loan carried all the way round to CORRECTED."""
    built = fx.loan_in_special_servicing(
        api,
        trust_overrides={
            "deal_name": "CMBS 2026-V47",
            "closing_date": "2026-01-15T00:00:00Z",
            "original_controlling_class_balance_usd": 40000000,
        },
        loan_factory=fx.create_mid_size_loan,
        loan_overrides={"loan_number": "L-V47", "maturity_date": "2029-06-01T00:00:00Z"},
        event_factory=_certified_imminent_default,
    )
    fx.accepted_appraisal(
        api,
        built["loan_id"],
        value_usd=9000000,
        as_of_date="2026-07-01T00:00:00Z",
        ordered_on="2026-06-20T00:00:00Z",
        appraiser_firm="Meridian Valuation",
    )
    executed = fx.executed_plan(
        api,
        built["trust_id"],
        built["loan_id"],
        alternative_builders=[_the_modification_route],
        discount_rate_pct=8.0,
    )
    corrected = validate_success(
        api.set_loan_servicing_status(
            built["loan_id"], f.status_payload("CORRECTED"), COMMITTEE_OFFICER
        )
    )
    return built["loan_id"], executed["plan_id"], corrected


def _record_payment(api, loan_id, to_status, as_of_date, **extra):
    return validate_success(
        api.set_loan_payment_status(
            loan_id,
            f.status_payload(to_status, as_of_date=as_of_date, **extra),
            MASTER_SERVICER,
        )
    )


def test_a_single_missed_payment_returns_the_counter_to_zero(api):
    """Two accumulated payments are wiped out by one step down the ladder.

    The PRD: "`CURRENT → DELINQUENT_30`, `DELINQUENT_30 → DELINQUENT_60` and
    `DELINQUENT_60 → DELINQUENT_90_PLUS` walk the delinquency ladder one rung at a
    time; each resets `consecutive_timely_payments` to zero."

    Design: Corner/complexity_layers/the_timely_payment_counter_resets_on_a_missed_payment
    """
    loan_id, plan_id, corrected = _a_corrected_loan_under_an_executed_modification(api)
    a.assert_status(corrected, "CORRECTED", "servicing_status")
    assert corrected["consecutive_timely_payments"] == 0, (
        "a loan reaching CORRECTED has accumulated no timely payments yet"
    )
    assert corrected["correction_source_plan_id"] == plan_id
    a.assert_fields_null(corrected, "active_workout_plan_id")

    first = _record_payment(
        api, loan_id, "CURRENT", "2026-08-01T00:00:00Z", timely_payment_recorded=True
    )
    assert first["consecutive_timely_payments"] == 1
    second = _record_payment(
        api, loan_id, "CURRENT", "2026-09-01T00:00:00Z", timely_payment_recorded=True
    )
    assert second["consecutive_timely_payments"] == 2

    missed = _record_payment(api, loan_id, "DELINQUENT_30", "2026-10-01T00:00:00Z")
    a.assert_status(missed, "DELINQUENT_30", "payment_status")
    assert missed["consecutive_timely_payments"] == 0, (
        "a counter of total rather than consecutive payments would have stayed at 2"
    )
    a.assert_status(missed, "CORRECTED", "servicing_status")

    events, meta = validate_paginated(
        api.list_loan_transfer_events(loan_id, MASTER_SERVICER)
    )
    assert meta["total_count"] == 1, (
        "a thirty-day delinquency auto-records no servicing transfer event"
    )
    assert events[0]["event_code"] == "IMMINENT_DEFAULT"


def test_the_handback_opens_only_on_the_third_consecutive_payment(api):
    """Four timely payments in total but two in a row is not enough.

    The PRD: "Handing the asset back — `CORRECTED → MASTER_SERVICING` — belongs to
    the `SpecialServicerAssetManager` and requires proof that the modification
    actually worked: the loan's `consecutive_timely_payments` must be at least
    three. Exactly three succeeds and two does not; a shortfall is refused with
    `ERR_INSUFFICIENT_TIMELY_PAYMENTS`."

    Design: Corner/complexity_layers/the_timely_payment_counter_resets_on_a_missed_payment
    """
    loan_id, _, _ = _a_corrected_loan_under_an_executed_modification(api)
    _record_payment(
        api, loan_id, "CURRENT", "2026-08-01T00:00:00Z", timely_payment_recorded=True
    )
    _record_payment(
        api, loan_id, "CURRENT", "2026-09-01T00:00:00Z", timely_payment_recorded=True
    )
    _record_payment(api, loan_id, "DELINQUENT_30", "2026-10-01T00:00:00Z")

    cured = _record_payment(
        api, loan_id, "CURRENT", "2026-11-01T00:00:00Z", timely_payment_recorded=True
    )
    assert cured["consecutive_timely_payments"] == 1, (
        "the cure edge to CURRENT increases the counter by one when the payment was timely"
    )
    fourth = _record_payment(
        api, loan_id, "CURRENT", "2026-12-01T00:00:00Z", timely_payment_recorded=True
    )
    assert fourth["consecutive_timely_payments"] == 2, (
        "four timely payments have been recorded in total but only two consecutively"
    )

    short = api.set_loan_servicing_status(
        loan_id, f.status_payload("MASTER_SERVICING"), ASSET_MANAGER
    )
    validate_error(short, e.ERR_INSUFFICIENT_TIMELY_PAYMENTS, 422)
    still_corrected = fx.read_loan(api, loan_id, MASTER_SERVICER)
    a.assert_status(still_corrected, "CORRECTED", "servicing_status")
    assert still_corrected["consecutive_timely_payments"] == 2

    fifth = _record_payment(
        api, loan_id, "CURRENT", "2027-01-01T00:00:00Z", timely_payment_recorded=True
    )
    assert fifth["consecutive_timely_payments"] == 3

    handed_back = validate_success(
        api.set_loan_servicing_status(
            loan_id, f.status_payload("MASTER_SERVICING"), ASSET_MANAGER
        )
    )
    a.assert_status(handed_back, "MASTER_SERVICING", "servicing_status")
    assert handed_back["consecutive_timely_payments"] == 3, (
        "the comparison is at least three, inclusive at the boundary"
    )
