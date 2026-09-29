"""One request, every dependent aggregate: no reconciliation pass exists."""

from test_helpers import (
    api_client,
    factories,
    fixtures,
    validate_success,
)
from test_helpers.assertions import assert_posture_matches_ratio
from test_helpers.fixtures import ANALYST, COMMITTEE, UNDERWRITER
from test_helpers.test_users import make_borrower_headers


def test_derived_figures_across_aggregates_land_in_the_triggering_request():
    """The disbursement and the verification each settle every reader at once.

    PRD: "Higher-risk lending is only responsible lending when the losses it
    anticipates are funded, so the institution's reserve adequacy is not a
    periodic report — it is a standing posture re-derived on every event that
    moves a loan balance."
    PRD: "Exactly one request advances both dimensions at once: the first
    disbursement, which performs `APPROVED → CLOSED` and `NOT_DISBURSED →
    CURRENT` together."
    PRD: "On the **first** advance only, `first_disbursed_on` is stamped with
    the logical clock's date, `vintage_year` is set to the calendar year of that
    date, `next_payment_due_on` is set to that date advanced by 30 days, and
    `borrower_in_target_market_at_origination` is frozen from the borrower's
    `in_target_market` value as observed at that instant — this snapshot is the
    only field target-market lending measurement ever reads."
    PRD: "Verification moves it `SUBMITTED → VERIFIED`, stamps `verified_at`
    from the logical clock, and increases each of the institution's four
    counters by this report's corresponding field."

    Design: Corner/consistency_model/cross_aggregate_derived_fields_land_in_the_same_instant_with_no_run_required
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution(
        ein="210000071", reserve_method="MIGRATION_ANALYSIS",
        loss_reserve_balance_cents=0,
    )
    institution_id = institution["id"]
    product = fixtures.create_loan_product(institution_id)
    borrower = fixtures.create_geocoded_borrower(institution_id)
    assert borrower["in_target_market"] is False, (
        "no definition of this lender is approved, so nothing attributes"
    )
    loan = fixtures.file_loan(
        institution_id, borrower["id"], product["id"], 1_000_000
    )
    validate_success(
        api_client.underwrite_loan(
            loan["id"],
            factories.underwrite_payload(1_000_000, 100_000, 740),
            UNDERWRITER,
        )
    )
    validate_success(
        api_client.decide_loan(
            loan["id"],
            {"decision": "APPROVE", "approved_principal_cents": 1_000_000},
            COMMITTEE,
        )
    )

    disbursed = validate_success(
        api_client.disburse_loan(
            loan["id"], {"amount_cents": 1_000_000},
            fixtures.make_institution_officer_headers(institution_id),
        )
    )
    assert disbursed["underwriting_state"] == "CLOSED"
    assert disbursed["servicing_state"] == "CURRENT"
    assert disbursed["first_disbursed_on"] == "2026-09-01"
    assert disbursed["next_payment_due_on"] == "2026-10-01"
    assert disbursed["vintage_year"] == 2026
    assert disbursed["borrower_in_target_market_at_origination"] is False

    lender = fixtures.read_institution(institution_id)
    assert lender["portfolio_principal_outstanding_cents"] == 1_000_000
    assert lender["loss_reserve_required_migration_cents"] == 20_000
    assert lender["loss_reserve_required_static_cents"] == 45_000
    assert float(lender["reserve_coverage_ratio"]) == 0.0000
    assert lender["compliance_posture"] == "PROBATION"
    assert_posture_matches_ratio(lender)

    report = validate_success(
        api_client.create_impact_report(
            loan["id"],
            factories.impact_report_payload(
                disbursed["version"], "2026-08-31T00:00:00Z",
                jobs_created=4, jobs_retained=3, housing_units=2,
                businesses_financed=1,
            ),
            make_borrower_headers(borrower["id"]),
        ),
        201,
    )

    verified = validate_success(
        api_client.verify_impact_report(report["id"], ANALYST)
    )
    assert verified["state"] == "VERIFIED"
    assert verified["verified_at"] == "2026-09-01T00:00:00.000Z"

    counted = fixtures.read_institution(institution_id)
    assert counted["jobs_created_total"] == 4
    assert counted["jobs_retained_total"] == 3
    assert counted["housing_units_total"] == 2
    assert counted["businesses_financed_total"] == 1
