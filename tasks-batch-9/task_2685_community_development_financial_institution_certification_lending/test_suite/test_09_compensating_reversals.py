"""Reversals that must be recomputed from the surviving rows, not decremented.

Disputing one verified impact report has to leave the institution's four
counters equal to the other report's figures. Withdrawing one verified pledge
has to make a shortfall that was clamped at zero re-emerge as a positive
figure.
"""

from test_helpers import (
    api_client,
    fixtures,
    validate_success,
)
from test_helpers.assertions import assert_match_shortfall_invariant
from test_helpers.fixtures import ADMINISTRATOR, ANALYST


def _two_verified_reports():
    """Two funded loans to one borrower, each carrying a verified report.

    The institution's counters read 19 / 9 / 4 / 3 once both are verified.
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario = fixtures.setup_lending_ready_institution()
    institution_id = scenario["institution"]["id"]
    borrower_id = scenario["borrower"]["id"]

    loan_a = fixtures.create_disbursed_loan(scenario, 1_000_000)
    loan_b = fixtures.create_disbursed_loan(scenario, 1_200_000)

    first = fixtures.create_verified_impact_report(
        loan_a["id"], borrower_id,
        jobs_created=12, jobs_retained=5, housing_units=3,
        businesses_financed=2,
    )
    second = fixtures.create_verified_impact_report(
        loan_b["id"], borrower_id,
        jobs_created=7, jobs_retained=4, housing_units=1,
        businesses_financed=1,
    )

    ledger = validate_success(
        api_client.get_institution(institution_id, ANALYST)
    )
    assert ledger["jobs_created_total"] == 19
    assert ledger["jobs_retained_total"] == 9
    assert ledger["housing_units_total"] == 4
    assert ledger["businesses_financed_total"] == 3
    return institution_id, borrower_id, first, second


def test_disputing_one_verified_report_leaves_the_other_report_s_figures():
    """The reversal subtracts exactly the disputed entry and nothing else.

    PRD: "A dispute records the analyst's `dispute_reason`, clears `verified_at`
    back to null, and is permitted from two positions with deliberately
    different ledger consequences: `VERIFIED → DISPUTED` subtracts exactly the
    same four values that verification added, reversing the entry precisely,
    while `SUBMITTED → DISPUTED` leaves the counters untouched because an
    unverified report never entered them."
    PRD: "each of the institution's four totals equals the sum of the
    corresponding field over the reports in `state` `VERIFIED` whose loan
    belongs to that institution."

    Design: Difficulty/compensating_invariant/impact_dispute_reverses_one_report_without_disturbing_the_other
    """
    institution_id, _borrower_id, first, second = _two_verified_reports()

    disputed = validate_success(
        api_client.dispute_impact_report(
            first["id"], {"dispute_reason": "PAYROLL_EVIDENCE_MISSING"}, ANALYST
        )
    )
    assert disputed["state"] == "DISPUTED"
    assert disputed["dispute_reason"] == "PAYROLL_EVIDENCE_MISSING"
    assert disputed["verified_at"] is None
    assert disputed["jobs_created"] == 12, (
        "a dispute challenges the figures without overwriting them"
    )
    assert disputed["revision_count"] == 0

    untouched = validate_success(
        api_client.get_impact_report(second["id"], ANALYST)
    )
    assert untouched["state"] == "VERIFIED"
    assert untouched["verified_at"] == "2026-09-01T00:00:00.000Z"

    ledger = validate_success(
        api_client.get_institution(institution_id, ANALYST)
    )
    assert ledger["jobs_created_total"] == 7
    assert ledger["jobs_retained_total"] == 4
    assert ledger["housing_units_total"] == 1
    assert ledger["businesses_financed_total"] == 1


def test_correcting_and_reverifying_the_disputed_report_restores_the_ledger():
    """The verify/dispute/correct loop closes with no drift in the counters.

    PRD: "A disputed report is corrected by the borrower, who supplies fresh
    `jobs_created`, `jobs_retained`, `housing_units` and `businesses_financed`
    values that overwrite the stored ones; the correction moves the report
    `DISPUTED → SUBMITTED`, increments `revision_count` by 1 and clears
    `dispute_reason` to null."
    PRD: "Because verification and dispute are exact compensating actions, the
    loop `SUBMITTED → VERIFIED → DISPUTED → SUBMITTED → VERIFIED` may run any
    number of times without drift, and the following invariant must hold after
    every single request: each of the institution's four totals equals the sum
    of the corresponding field over the reports in `state` `VERIFIED` whose loan
    belongs to that institution."

    Design: Difficulty/compensating_invariant/impact_dispute_reverses_one_report_without_disturbing_the_other
    """
    institution_id, borrower_id, first, _second = _two_verified_reports()

    validate_success(
        api_client.dispute_impact_report(
            first["id"], {"dispute_reason": "PAYROLL_EVIDENCE_MISSING"}, ANALYST
        )
    )

    corrected = validate_success(
        api_client.resubmit_impact_report(
            first["id"],
            {
                "jobs_created": 12,
                "jobs_retained": 5,
                "housing_units": 3,
                "businesses_financed": 2,
            },
            fixtures.make_borrower_headers(borrower_id),
        )
    )
    assert corrected["state"] == "SUBMITTED"
    assert corrected["revision_count"] == 1
    assert corrected["dispute_reason"] is None

    still_reversed = validate_success(
        api_client.get_institution(institution_id, ANALYST)
    )
    assert still_reversed["jobs_created_total"] == 7, (
        "a correction re-files the report but does not re-enter the counters"
    )
    assert still_reversed["housing_units_total"] == 1

    reverified = validate_success(
        api_client.verify_impact_report(first["id"], ANALYST)
    )
    assert reverified["state"] == "VERIFIED"
    assert reverified["verified_at"] == "2026-09-01T00:00:00.000Z"

    ledger = validate_success(
        api_client.get_institution(institution_id, ANALYST)
    )
    assert ledger["jobs_created_total"] == 19
    assert ledger["jobs_retained_total"] == 9
    assert ledger["housing_units_total"] == 4
    assert ledger["businesses_financed_total"] == 3


def _award_over_covered_by_two_verified_pledges():
    """A 4,000,000 request at 25.00 percent, over-covered to 1,050,000.

    Cash counts in full and the in-kind services at half, so the requirement of
    1,000,000 is covered and the shortfall is clamped at zero.
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution()
    award = fixtures.open_award_application(
        institution["id"], requested_amount_cents=4_000_000, match_ratio_pct=25.00
    )
    assert award["required_match_cents"] == 1_000_000
    assert award["match_shortfall_cents"] == 1_000_000

    cash = fixtures.pledge_commitment(
        award["id"], source_type="CASH_PRIVATE", amount_cents=600_000,
        source_name="Kellerman Family Foundation",
    )
    in_kind = fixtures.pledge_commitment(
        award["id"], source_type="IN_KIND", amount_cents=900_000,
        source_name="Bronx Legal Aid In-Kind Services",
        committed_on="2026-08-20T00:00:00Z",
    )
    cash = fixtures.verify_commitment(cash["id"])
    in_kind = fixtures.verify_commitment(in_kind["id"])
    assert cash["eligible_cents"] == 600_000
    assert in_kind["eligible_cents"] == 450_000

    covered = validate_success(
        api_client.get_award_application(award["id"], ADMINISTRATOR)
    )
    assert covered["match_eligible_cents"] == 1_050_000
    assert covered["match_shortfall_cents"] == 0
    assert_match_shortfall_invariant(covered)
    return award, cash, in_kind, covered


def test_withdrawing_a_verified_pledge_re_exposes_the_clamped_shortfall():
    """The shortfall is recomputed from the surviving verified rows.

    PRD: "Withdrawing a `VERIFIED` source reverses its contribution exactly:
    `eligible_cents` on the commitment is set back to 0, the award's
    `match_eligible_cents` is reduced by what that commitment had contributed,
    and `match_shortfall_cents` is recomputed."
    PRD: "`match_shortfall_cents` is then the greater of zero and
    `required_match_cents` less `match_eligible_cents`."

    Design: Difficulty/compensating_invariant/match_ledger_withdrawal_re_exposes_a_shortfall_clamped_at_zero
    """
    award, cash, in_kind, covered = _award_over_covered_by_two_verified_pledges()

    withdrawn = validate_success(
        api_client.withdraw_matching_fund_commitment(
            in_kind["id"], {"withdraw_reason": "IN_KIND_VALUATION_REJECTED"},
            ADMINISTRATOR,
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["eligible_cents"] == 0
    assert withdrawn["withdraw_reason"] == "IN_KIND_VALUATION_REJECTED"
    assert withdrawn["version"] == in_kind["version"] + 1

    surviving = validate_success(
        api_client.get_matching_fund_commitment(cash["id"], ADMINISTRATOR)
    )
    assert surviving["status"] == "VERIFIED"
    assert surviving["eligible_cents"] == 600_000

    reread = validate_success(
        api_client.get_award_application(award["id"], ADMINISTRATOR)
    )
    assert reread["state"] == "DRAFT"
    assert reread["required_match_cents"] == 1_000_000
    assert reread["match_eligible_cents"] == 600_000
    assert reread["match_shortfall_cents"] == 400_000, (
        "a figure clamped at zero must re-emerge as a positive shortfall"
    )
    assert_match_shortfall_invariant(reread)
    assert reread["version"] == covered["version"] + 1


def test_withdrawing_a_merely_pledged_source_leaves_the_ledger_untouched():
    """Only verified rows ever entered the ledger, so only they reverse out.

    PRD: "Withdrawing a merely `PLEDGED` source leaves `match_eligible_cents`
    untouched, because an unverified pledge never entered the ledger."
    PRD: "`match_eligible_cents`, which counts commitments in `status`
    `VERIFIED` only — `PLEDGED`, `HELD` and `WITHDRAWN` commitments contribute
    zero."

    Design: Difficulty/compensating_invariant/match_ledger_withdrawal_re_exposes_a_shortfall_clamped_at_zero
    """
    award, cash, in_kind, covered = _award_over_covered_by_two_verified_pledges()

    unsettled = fixtures.pledge_commitment(
        award["id"], source_type="DEFERRED_PLEDGE", amount_cents=800_000,
        source_name="Harlow Trust Deferred Pledge",
    )
    assert unsettled["status"] == "PLEDGED"
    assert unsettled["eligible_cents"] == 0

    withdrawn = validate_success(
        api_client.withdraw_matching_fund_commitment(
            unsettled["id"], {"withdraw_reason": "SOURCE_RETRACTED"},
            ADMINISTRATOR,
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["eligible_cents"] == 0
    assert withdrawn["withdraw_reason"] == "SOURCE_RETRACTED"

    reread = validate_success(
        api_client.get_award_application(award["id"], ADMINISTRATOR)
    )
    assert reread["match_eligible_cents"] == 1_050_000
    assert reread["match_shortfall_cents"] == 0
    assert_match_shortfall_invariant(reread)

    for commitment_id, expected in (
        (cash["id"], 600_000), (in_kind["id"], 450_000)
    ):
        sibling = validate_success(
            api_client.get_matching_fund_commitment(commitment_id, ADMINISTRATOR)
        )
        assert sibling["status"] == "VERIFIED"
        assert sibling["eligible_cents"] == expected
    assert covered["match_eligible_cents"] == 1_050_000
