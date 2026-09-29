"""Concurrency tokens, running totals and the posture that rides on them."""

from test_helpers import (
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import (
    assert_loan_ledger_invariant,
    assert_posture_matches_ratio,
)
from test_helpers.fixtures import ANALYST, COMMITTEE, REVIEWER, UNDERWRITER
from test_helpers.test_users import make_borrower_headers


def test_a_stale_institution_token_is_refused_while_the_version_climbs():
    """Every write on the lender moves the token the docket must quote.

    PRD: "The create snapshots the institution's accountability representation
    score onto the new application, and that snapshot would be dishonest if
    taken from a view the client never saw: approving a target market, seating a
    board member or retiring one all move the score and all bump the
    institution's `version`."
    PRD: "If `expected_institution_version` does not equal the institution's
    current `version`, the create is rejected with
    `ERR_STALE_INSTITUTION_VERSION` (HTTP 412)."
    PRD: "Approval stamps `approved_at` with the logical clock, and because
    seats pointing at that definition now begin to count, it also recomputes the
    institution's accountability figures and advances the institution's
    `version` by 1."
    PRD: "On success the application is created in `state` `DRAFT` with
    `revision_round` 0, all six per-test verdict fields at `PENDING`,
    `accountability_score_snapshot` copied from the institution's current
    `accountability_score` and carried to four decimal places,
    `submitted_by_user_id`, `reviewed_by_user_id`, `info_requested_reason` and
    `decided_at` all null; the institution's `version` advances by 1."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_institution_version_rejected_and_the_parent_version_climbs_per_write
    """
    institution = fixtures.create_institution(ein="210000067")
    institution_id = institution["id"]
    stale_token = institution["version"]
    assert stale_token == 1

    market = fixtures.create_target_market(institution_id)
    validate_success(api_client.approve_target_market(market["id"], REVIEWER))
    after_approval = fixtures.read_institution(institution_id)
    assert after_approval["version"] == 2, (
        "approving the definition recomputed the accountability figures"
    )

    fixtures.create_board_seat(
        institution_id, structure="GOVERNING_BOARD", holder_name="R. Alvarez",
        represents_target_market=True, target_market_id=market["id"],
    )

    validate_error(
        api_client.create_certification_application(
            institution_id,
            factories.certification_application_payload(stale_token),
            fixtures.make_institution_officer_headers(institution_id),
        ),
        ApiErrorId.ERR_STALE_INSTITUTION_VERSION,
    )

    current = fixtures.read_institution(institution_id)
    assert current["version"] == 3
    assert float(current["accountability_score"]) == 1.0000
    assert current["accountability_satisfied"] is True

    opened = validate_success(
        api_client.create_certification_application(
            institution_id,
            factories.certification_application_payload(current["version"]),
            fixtures.make_institution_officer_headers(institution_id),
        ),
        201,
    )
    assert float(opened["accountability_score_snapshot"]) == 1.0000
    assert opened["state"] == "DRAFT"
    assert opened["revision_round"] == 0
    assert opened["submitted_by_user_id"] is None
    assert opened["reviewed_by_user_id"] is None
    assert opened["decided_at"] is None

    final = fixtures.read_institution(institution_id)
    assert final["version"] == 4, (
        "the accepted create consumed the token and moved it once more"
    )

    _rows, meta = validate_paginated(
        api_client.list_institution_certification_applications(
            institution_id, ANALYST
        )
    )
    assert meta["total_count"] == 1


def test_a_stale_loan_token_is_refused_before_the_prior_report_is_superseded():
    """The refused filing leaves the earlier report standing and current.

    PRD: "Filing a report supersedes the loan's prior report for the same period
    and, when that prior report had been verified, removes its counts from the
    institution's impact totals; a filer whose reading of the loan is stale does
    not know which report is current or where the loan's servicing position now
    stands."
    PRD: "If `expected_loan_version` does not equal the loan's current
    `version`, the create is rejected with `ERR_STALE_LOAN_VERSION` (HTTP 412)."
    PRD: "When an earlier report of the same loan carries the same
    `reporting_period_end` and sits in `state` `SUBMITTED`, `VERIFIED` or
    `DISPUTED`, that earlier report moves to `SUPERSEDED`."
    PRD: "Filing a report advances the loan's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_loan_version_rejected_before_the_prior_report_is_superseded
    """
    institution = fixtures.create_institution(ein="210000068")
    institution_id = institution["id"]
    product = fixtures.create_loan_product(institution_id)
    borrower = fixtures.create_borrower(institution_id)
    obligor = make_borrower_headers(borrower["id"])
    loan = fixtures.file_loan(
        institution_id, borrower["id"], product["id"], 1_000_000
    )
    stale_token = loan["version"]
    assert stale_token == 1

    first = validate_success(
        api_client.create_impact_report(
            loan["id"],
            factories.impact_report_payload(
                stale_token, "2026-07-31T00:00:00Z",
                jobs_created=2, jobs_retained=1, housing_units=0,
                businesses_financed=1,
            ),
            obligor,
        ),
        201,
    )

    revised = factories.impact_report_payload(
        stale_token, "2026-07-31T00:00:00Z",
        jobs_created=5, jobs_retained=4, housing_units=1, businesses_financed=2,
    )
    validate_error(
        api_client.create_impact_report(loan["id"], revised, obligor),
        ApiErrorId.ERR_STALE_LOAN_VERSION,
    )

    moved = validate_success(api_client.get_loan(loan["id"], ANALYST))
    assert moved["version"] == 2

    revised["expected_loan_version"] = moved["version"]
    second = validate_success(
        api_client.create_impact_report(loan["id"], revised, obligor),
        201,
    )
    assert second["state"] == "SUBMITTED"
    assert second["jobs_created"] == 5
    assert second["revision_count"] == 0

    superseded = validate_success(
        api_client.get_impact_report(first["id"], ANALYST)
    )
    assert superseded["state"] == "SUPERSEDED"

    settled = validate_success(api_client.get_loan(loan["id"], ANALYST))
    assert settled["version"] == 3, (
        "the refused filing never touched the token"
    )

    _rows, meta = validate_paginated(
        api_client.list_impact_reports(ANALYST, {"loan_id": loan["id"]})
    )
    assert meta["total_count"] == 2


def test_the_posture_bands_are_walked_at_exactly_one_and_exactly_eight_tenths():
    """A balance of 16,000 sits on both band edges as the book moves.

    PRD: "Under the migration-analysis basis, roll rates are applied to
    *current* outstanding principal: 2 percent for a `CURRENT` loan, 10 percent
    for `DELINQUENT_30`, 35 percent for `DELINQUENT_60` and 75 percent for
    `DELINQUENT_90`."
    PRD: "`loss_reserve_required_cents` then takes whichever variant the
    institution's `reserve_method` names, `reserve_coverage_ratio` is
    `loss_reserve_balance_cents` divided by `loss_reserve_required_cents`
    rounded half up to four decimal places — pinned to 1.0000 when the required
    figure is 0 — and `compliance_posture` falls out of the bands in §2.11."
    PRD: "Under the static-pool basis, vintage cumulative loss rates are applied
    to *originally disbursed* principal and the cohort never shrinks: a loan
    whose `vintage_year` equals the calendar year of the current logical clock
    carries a rate of 4.5 percent, and every older vintage carries 3 percent."
    PRD: "The disbursement also adds the amount to the institution's
    `portfolio_principal_disbursed_cents` and
    `portfolio_principal_outstanding_cents`, then re-derives both reserve
    variants, `loss_reserve_required_cents`, `reserve_coverage_ratio` and
    `compliance_posture`, and advances both the loan's `version` and the
    institution's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/posture_bands_walked_at_exactly_one_point_zero_and_exactly_eight_tenths
    """
    institution = fixtures.create_institution(
        ein="210000069", reserve_method="MIGRATION_ANALYSIS",
        loss_reserve_balance_cents=16_000,
    )
    institution_id = institution["id"]
    assert float(institution["reserve_coverage_ratio"]) == 1.0000
    assert institution["compliance_posture"] == "COMPLIANT"

    product = fixtures.create_loan_product(
        institution_id, product_cap_cents=5_000_000
    )
    borrower = fixtures.create_geocoded_borrower(institution_id)
    loan = fixtures.file_loan(
        institution_id, borrower["id"], product["id"], 2_000_000
    )
    priced = validate_success(
        api_client.underwrite_loan(
            loan["id"],
            factories.underwrite_payload(1_000_000, 100_000, 740),
            UNDERWRITER,
        )
    )
    assert priced["monthly_payment_cents"] == 48_333
    assert float(priced["dti_pct"]) == 14.83
    validate_success(
        api_client.decide_loan(
            loan["id"],
            {"decision": "APPROVE", "approved_principal_cents": 2_000_000},
            COMMITTEE,
        )
    )

    fixtures.disburse_loan(institution_id, loan["id"], 1_000_000)
    watch = fixtures.read_institution(institution_id)
    assert watch["loss_reserve_required_cents"] == 20_000
    assert float(watch["reserve_coverage_ratio"]) == 0.8000
    assert watch["compliance_posture"] == "WATCH"
    assert_posture_matches_ratio(watch)

    fixtures.pay_loan(institution_id, loan["id"], 200_000)
    recovered = fixtures.read_institution(institution_id)
    assert recovered["loss_reserve_required_cents"] == 16_000
    assert float(recovered["reserve_coverage_ratio"]) == 1.0000
    assert recovered["compliance_posture"] == "COMPLIANT"
    assert_posture_matches_ratio(recovered)

    fixtures.disburse_loan(institution_id, loan["id"], 1_000_000)
    serviced = validate_success(api_client.get_loan(loan["id"], ANALYST))
    assert serviced["principal_disbursed_cents"] == 2_000_000
    assert serviced["principal_repaid_cents"] == 200_000
    assert serviced["principal_outstanding_cents"] == 1_800_000
    assert serviced["servicing_state"] == "CURRENT"
    assert_loan_ledger_invariant(serviced)

    probation = fixtures.read_institution(institution_id)
    assert probation["portfolio_principal_outstanding_cents"] == 1_800_000
    assert probation["loss_reserve_balance_cents"] == 16_000
    assert probation["loss_reserve_required_migration_cents"] == 36_000
    assert probation["loss_reserve_required_static_cents"] == 90_000
    assert probation["loss_reserve_required_cents"] == 36_000
    assert float(probation["reserve_coverage_ratio"]) == 0.4444
    assert probation["reserve_deficit_cents"] == 0, (
        "only a write-off records a deficit, and none has happened"
    )
    assert probation["compliance_posture"] == "PROBATION"
    assert_posture_matches_ratio(probation)


def test_committed_principal_counts_approvals_only_and_never_unwinds():
    """A decline never adds and a payoff never subtracts.

    PRD: "Finally `product_cap_cents`, which must be strictly positive, is a
    hard ceiling on committed principal across the product, and
    `committed_principal_cents` — which starts at 0 — is the running total of
    approved principal across the product's loans whose `underwriting_state` is
    `APPROVED` or `CLOSED`."
    PRD: "A decline moves the loan `UNDERWRITING → DECLINED`, records the
    supplied `decline_reason` and `decided_by_user_id`, and leaves
    `committed_principal_cents` untouched."
    PRD: "A payment that brings `principal_outstanding_cents` exactly to zero
    retires the loan: `servicing_state` becomes `PAID_OFF`,
    `underwriting_state` becomes `CLOSED`, `next_payment_due_on` is cleared and
    `days_past_due` is set to 0."

    Design: Corner/cross_cutting_complexity_layers/product_committed_principal_records_approvals_only_and_never_unwinds
    """
    institution = fixtures.create_institution(ein="210000070")
    institution_id = institution["id"]
    product = fixtures.create_loan_product(
        institution_id, product_cap_cents=5_000_000
    )
    assert product["committed_principal_cents"] == 0
    first_borrower = fixtures.create_geocoded_borrower(
        institution_id, full_name="Maria Ortiz"
    )
    second_borrower = fixtures.create_geocoded_borrower(
        institution_id, full_name="Dana Whitfield"
    )

    approved_loan = fixtures.file_loan(
        institution_id, first_borrower["id"], product["id"], 1_000_000
    )
    fixtures.underwrite_loan(approved_loan["id"])
    declined_loan = fixtures.file_loan(
        institution_id, second_borrower["id"], product["id"], 1_000_000
    )
    validate_success(
        api_client.underwrite_loan(
            declined_loan["id"],
            factories.underwrite_payload(800_000, 90_000, 690),
            UNDERWRITER,
        )
    )

    validate_success(
        api_client.decide_loan(
            approved_loan["id"],
            {"decision": "APPROVE", "approved_principal_cents": 1_000_000},
            COMMITTEE,
        )
    )
    after_approval, _meta = validate_paginated(
        api_client.list_institution_loan_products(institution_id, ANALYST)
    )
    assert after_approval[0]["committed_principal_cents"] == 1_000_000

    declined = validate_success(
        api_client.decide_loan(
            declined_loan["id"],
            {
                "decision": "DECLINE",
                "decline_reason": "INSUFFICIENT_REPAYMENT_CAPACITY",
            },
            COMMITTEE,
        )
    )
    assert declined["underwriting_state"] == "DECLINED"
    assert declined["decline_reason"] == "INSUFFICIENT_REPAYMENT_CAPACITY"
    assert declined["approved_principal_cents"] is None
    after_decline, _meta = validate_paginated(
        api_client.list_institution_loan_products(institution_id, ANALYST)
    )
    assert after_decline[0]["committed_principal_cents"] == 1_000_000

    fixtures.disburse_loan(institution_id, approved_loan["id"], 1_000_000)
    retired = fixtures.pay_loan(institution_id, approved_loan["id"], 1_000_000)
    assert retired["servicing_state"] == "PAID_OFF"
    assert retired["underwriting_state"] == "CLOSED"
    assert retired["principal_repaid_cents"] == 1_000_000
    assert retired["principal_outstanding_cents"] == 0

    unchanged = validate_success(
        api_client.get_loan_product(product["id"], ANALYST)
    )
    assert unchanged["committed_principal_cents"] == 1_000_000, (
        "a retired loan stays CLOSED and stays counted"
    )

    lender = fixtures.read_institution(institution_id)
    assert lender["portfolio_principal_outstanding_cents"] == 0
    assert lender["portfolio_principal_disbursed_cents"] == 1_000_000
    assert lender["loss_reserve_required_cents"] == 0
    assert float(lender["reserve_coverage_ratio"]) == 1.0000
    assert lender["compliance_posture"] == "COMPLIANT"


def test_the_servicing_run_flips_recertification_only_once_the_instant_arrives():
    """One day early the state holds; on the due instant the run moves it once.

    PRD: "`recertification_due_at` is set to the logical clock plus 1,095 days —
    three years, the interval at which target-market performance must be
    re-proved — and the institution's `version` advances by 1."
    PRD: "The same run also evaluates the certification clock: when the
    institution's `certification_state` is `CERTIFIED`, its
    `recertification_due_at` is not null, and the logical clock has reached or
    passed that instant, the institution moves `CERTIFIED → RECERT_DUE`."
    PRD: "The run finishes by recomputing both reserve variants, then
    `reserve_coverage_ratio` and `compliance_posture`, in that order, and
    advances the institution's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/servicing_run_checkpoint_flips_recertification_only_once_the_due_instant_arrives
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario = fixtures.create_certified_institution()
    institution = scenario["institution"]
    institution_id = institution["id"]
    assert institution["certification_state"] == "CERTIFIED"
    assert institution["certified_at"] == "2026-09-01T00:00:00.000Z"
    assert institution["recertification_due_at"] == "2029-08-31T00:00:00.000Z"
    assert scenario["application"]["decided_at"] == "2026-09-01T00:00:00.000Z"
    certified_version = institution["version"]

    fixtures.set_clock("2029-08-30T00:00:00Z")
    day_before = validate_success(
        api_client.run_servicing(institution_id, ANALYST)
    )
    assert day_before["certification_state"] == "CERTIFIED", (
        "the due instant has not been reached, so nothing flips"
    )
    assert float(day_before["reserve_coverage_ratio"]) == 1.0000
    assert day_before["version"] == certified_version + 1

    fixtures.set_clock("2029-08-31T00:00:00Z")
    on_the_instant = validate_success(
        api_client.run_servicing(institution_id, ANALYST)
    )
    assert on_the_instant["certification_state"] == "RECERT_DUE"
    assert on_the_instant["compliance_posture"] == "COMPLIANT"
    assert on_the_instant["version"] == certified_version + 2

    again = validate_success(api_client.run_servicing(institution_id, ANALYST))
    assert again["certification_state"] == "RECERT_DUE", (
        "the flip is not repeatable, and the run is still accepted"
    )
    assert again["version"] == certified_version + 3

    settled = fixtures.read_institution(institution_id)
    assert settled["certified_at"] == "2026-09-01T00:00:00.000Z"
    assert settled["recertification_due_at"] == "2029-08-31T00:00:00.000Z"
    assert settled["loss_reserve_required_cents"] == 0
    assert float(settled["reserve_coverage_ratio"]) == 1.0000

    docket = validate_success(
        api_client.get_certification_application(
            scenario["application"]["id"], ANALYST
        )
    )
    assert docket["state"] == "CERTIFIED"
