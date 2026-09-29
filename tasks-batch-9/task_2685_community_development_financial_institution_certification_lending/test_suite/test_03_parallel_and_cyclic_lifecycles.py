"""Lifecycles that are not a single straight line.

The certification docket loops through one state pair twice under a bounded
counter; a loan row advances two independent dimensions, one of which reaches
its terminal value while the other keeps cycling.
"""

from test_helpers import api_client, fixtures, validate_success
from test_helpers.fixtures import ANALYST, REVIEWER


def test_the_third_pass_through_the_information_cycle_denies_the_docket():
    """Two revisions are allowed; answering a third request settles at denial.

    PRD: "The review cycle is bounded at two revisions, and both boundaries are
    enforced. A reviewer returning an application for more information supplies
    `info_requested_reason`; while `revision_round` is below 2 this moves the
    docket `UNDER_REVIEW → INFO_REQUESTED`, increments `revision_round` by 1
    and records the reason."
    PRD: "While `revision_round` is at most 1 the answer returns the docket
    `INFO_REQUESTED → UNDER_REVIEW` and clears `info_requested_reason` to null;
    when `revision_round` has already reached 2 the answer instead settles the
    docket at `DENIED` with `decided_at` stamped."

    Design: Difficulty/non_linear_state_machine/certification_review_cycle_exhausts_at_second_revision
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario = fixtures.setup_application_under_review()
    institution_id = scenario["institution"]["id"]
    application_id = scenario["application"]["id"]
    officer = fixtures.make_institution_officer_headers(institution_id)

    fixtures.request_certification_info(
        application_id, "MISSION_EVIDENCE_INCOMPLETE"
    )
    fixtures.answer_certification_info(
        institution_id, application_id,
        development_services_description=(
            "Credit counseling, homebuyer education, business coaching and "
            "post-purchase support."
        ),
    )
    fixtures.request_certification_info(
        application_id, "DEVELOPMENT_SERVICES_EVIDENCE_INCOMPLETE"
    )

    denied = validate_success(
        api_client.resubmit_certification_application(
            application_id,
            {
                "development_services_description": (
                    "Credit counseling, homebuyer education, business coaching, "
                    "post-purchase support and savings match."
                )
            },
            officer,
        )
    )

    assert denied["revision_round"] == 2
    assert denied["state"] == "DENIED"
    assert denied["decided_at"] == "2026-09-01T00:00:00.000Z"
    assert denied["info_requested_reason"] == "DEVELOPMENT_SERVICES_EVIDENCE_INCOMPLETE"

    institution = validate_success(
        api_client.get_institution(institution_id, ANALYST)
    )
    assert institution["certification_state"] == "UNCERTIFIED"
    assert float(institution["accountability_score"]) == 1.0000


def test_the_first_answer_returns_the_docket_to_review_with_the_counter_advanced():
    """The first traversal of the pair is a loop, not an exit.

    PRD: "A reviewer returning an application for more information supplies
    `info_requested_reason`; while `revision_round` is below 2 this moves the
    docket `UNDER_REVIEW → INFO_REQUESTED`, increments `revision_round` by 1
    and records the reason."
    PRD: "Returning to review also partially clears the slate: every test
    verdict currently sitting at `FAILED` is reset to `PENDING`, while `PASSED`
    and `WAIVED` verdicts are retained untouched."

    Design: Difficulty/non_linear_state_machine/certification_review_cycle_exhausts_at_second_revision
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario = fixtures.setup_application_under_review()
    institution_id = scenario["institution"]["id"]
    application_id = scenario["application"]["id"]

    fixtures.record_certification_verdict(
        application_id, "PRIMARY_MISSION", "PASSED"
    )
    fixtures.record_certification_verdict(
        application_id, "DEVELOPMENT_SERVICES", "FAILED"
    )

    returned = validate_success(
        api_client.request_certification_info(
            application_id,
            {"info_requested_reason": "DEVELOPMENT_SERVICES_EVIDENCE_INCOMPLETE"},
            REVIEWER,
        )
    )
    assert returned["state"] == "INFO_REQUESTED"
    assert returned["revision_round"] == 1
    assert returned["info_requested_reason"] == "DEVELOPMENT_SERVICES_EVIDENCE_INCOMPLETE"

    back_under_review = validate_success(
        api_client.resubmit_certification_application(
            application_id,
            {"financing_activity_pct_claimed": 81.25},
            fixtures.make_institution_officer_headers(institution_id),
        )
    )
    assert back_under_review["state"] == "UNDER_REVIEW"
    assert back_under_review["revision_round"] == 1
    assert back_under_review["info_requested_reason"] is None
    assert back_under_review["test_primary_mission_state"] == "PASSED"
    assert back_under_review["test_development_services_state"] == "PENDING"
    assert float(back_under_review["financing_activity_pct_claimed"]) == 81.25


def _funded_loan_aged_two_buckets():
    """A funded loan whose installment fell due 61 days before the clock."""
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution()
    product = fixtures.create_loan_product(institution["id"])
    borrower = fixtures.create_geocoded_borrower(institution["id"])
    scenario = {
        "institution": institution, "product": product, "borrower": borrower,
    }
    scenario["loan"] = fixtures.create_disbursed_loan(scenario, 2_000_000)
    fixtures.set_clock("2026-12-01T00:00:00Z")
    return scenario


def test_the_servicing_dimension_ages_while_the_underwriting_dimension_stays_closed():
    """The checkpoint skips two buckets without touching the closed dimension.

    PRD: "A loan row carries **two independent state dimensions** that advance
    on disjoint trigger sets."
    PRD: "A `CLOSED` loan is still actively servicing, and a `PAID_OFF` loan
    keeps `underwriting_state` at `CLOSED` permanently."
    PRD: "A recomputed value of 90 days or more assigns `DELINQUENT_90`; at
    least 60 but under 90 assigns `DELINQUENT_60`; at least 30 but under 60
    assigns `DELINQUENT_30`; and under 30 days leaves `servicing_state`
    unchanged."

    Design: Difficulty/non_linear_state_machine/loan_servicing_dimension_cycles_while_underwriting_dimension_is_terminal
    """
    scenario = _funded_loan_aged_two_buckets()

    fixtures.run_servicing(scenario["institution"]["id"])

    aged = validate_success(
        api_client.get_loan(scenario["loan"]["id"], ANALYST)
    )
    assert aged["servicing_state"] == "DELINQUENT_60"
    assert aged["days_past_due"] == 61
    assert aged["underwriting_state"] == "CLOSED"
    assert aged["monthly_payment_cents"] == 48_333


def test_one_full_installment_cures_the_bucket_and_leaves_the_loan_closed():
    """The servicing dimension returns to current; the other never moves.

    PRD: "A payment of at least one full installment — that is, `amount_cents`
    at or above the loan's `monthly_payment_cents` — cures a loan sitting at
    `DELINQUENT_30`, `DELINQUENT_60` or `DELINQUENT_90` outright and
    identically from all three: `servicing_state` returns to `CURRENT`,
    `days_past_due` is reset to 0, and `next_payment_due_on` is re-dated to the
    logical clock's date advanced by 30 days."
    PRD: "Every payment subtracts its amount from the institution's
    `portfolio_principal_outstanding_cents`, re-derives the reserve variants,
    `reserve_coverage_ratio` and `compliance_posture`, and advances both the
    loan's `version` and the institution's `version` by 1."

    Design: Difficulty/non_linear_state_machine/loan_servicing_dimension_cycles_while_underwriting_dimension_is_terminal
    """
    scenario = _funded_loan_aged_two_buckets()
    institution_id = scenario["institution"]["id"]
    fixtures.run_servicing(institution_id)

    cured = validate_success(
        api_client.pay_loan(
            scenario["loan"]["id"],
            {"amount_cents": 500_000},
            fixtures.make_institution_officer_headers(institution_id),
        )
    )

    assert cured["underwriting_state"] == "CLOSED"
    assert cured["servicing_state"] == "CURRENT"
    assert cured["days_past_due"] == 0
    assert cured["next_payment_due_on"] == "2026-12-31"
    assert cured["principal_repaid_cents"] == 500_000
    assert cured["principal_outstanding_cents"] == 1_500_000

    institution = validate_success(
        api_client.get_institution(institution_id, ANALYST)
    )
    assert institution["portfolio_principal_outstanding_cents"] == 1_500_000
    assert institution["loss_reserve_required_migration_cents"] == 30_000
