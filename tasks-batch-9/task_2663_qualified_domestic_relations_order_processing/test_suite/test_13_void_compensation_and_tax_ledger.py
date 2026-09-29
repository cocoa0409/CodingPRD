"""A void is a compensation, not an edit — and the ledger proves the difference.

Undoing a payment touches three kinds of state in three different ways: the
distribution row keeps every figure it ever reported, the payee account's totals
are re-derived from the surviving payments, and the 1099-R ledger grows a negated
line that points back at the one it cancels. Nothing is overwritten anywhere.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import api_errors, constants, fixtures
from test_helpers.assertions import (
    assert_append_only_resource,
    assert_error_envelope,
    assert_plan_account_figures,
    assert_settlement,
    assert_tax_line,
    assert_tax_ledger_nets_to_zero,
    assert_tax_ledger_totals,
)
from test_helpers.test_users import ADMIN_HEADERS
from test_helpers.types import (
    AP_ACCOUNT_ESTABLISHED,
    APPROACH_SEPARATE_INTEREST,
    DISTRIBUTION_CODE_2,
    DISTRIBUTION_ISSUED,
    DISTRIBUTION_VOIDED,
    EARNINGS_PERIOD_END,
    FORM_CODE_1099R,
    FORMULA_PERCENTAGE_OF_ACCOUNT,
    SOURCE_AFTER_TAX,
    SOURCE_EMPLOYER_MATCH,
    SOURCE_LOAN_RECEIVABLE,
    SOURCE_PRE_TAX_DEFERRAL,
)

LEDGER_PLAN = {
    "acceptable_formula_codes": [FORMULA_PERCENTAGE_OF_ACCOUNT],
    "allowed_approaches": [APPROACH_SEPARATE_INTEREST],
    "earnings_adjustment_method": EARNINGS_PERIOD_END,
    "requires_model_language": True,
    "permits_benefit_not_otherwise_available": False,
    "review_period_days": 45,
    "segregation_period_days": 548,
    "resubmission_window_days": 60,
    "max_revisions": 3,
    "max_assignable_pct_bps": 5000,
    "max_assignable_amount_cents": 2000000,
}

# What the four sources hold once the determination has debited them.
SOURCES_AFTER_CONVERSION = {
    SOURCE_AFTER_TAX: 58800,
    SOURCE_EMPLOYER_MATCH: 876193,
    SOURCE_PRE_TAX_DEFERRAL: 1417006,
    SOURCE_LOAN_RECEIVABLE: 300000,
}


def _one_payment_to_undo(client, plan_name, reference="DRO-2663-V1"):
    """A single CASH payment of 1050000 standing against a funded payee account."""
    setup = fixtures.setup_qualified_separate_interest(
        client,
        plan_name,
        sources=fixtures.FOUR_SOURCE_MIX,
        snapshots=(("2026-06-30", 4000000), ("2026-12-31", 4120000)),
        qualify_clock=constants.CLOCK_2026_09_15,
        plan_overrides=LEDGER_PLAN,
        participant_overrides={
            "full_name": "Dana Reyes",
            "ssn_last4": "4417",
            "date_of_birth": "1979-04-12",
            "participation_start_date": "1999-01-01",
        },
        case_overrides={
            "alternate_payee_name": "Morgan Reyes",
            "alternate_payee_dob": "1981-07-05",
            "marital_period_start": "2012-03-01",
            "marital_period_end": "2026-02-01",
        },
        draft_overrides={"document_reference": reference},
    )
    payee = setup["ap_account"]
    assert payee["balance_cents"] == 1648001
    assert payee["after_tax_basis_cents"] == 24000
    assert payee["total_distributed_gross_cents"] == 0
    assert payee["version"] == 1

    setup["distribution"] = fixtures.issue_distribution(
        client,
        payee["id"],
        payee["version"],
        1050000,
        headers=fixtures.payee_headers(payee),
    )
    assert_settlement(
        setup["distribution"],
        gross_amount_cents=1050000,
        basis_recovery_cents=15291,
        taxable_amount_cents=1034709,
        federal_withheld_cents=206942,
        net_before_fee_cents=843058,
        admin_fee_cents=5000,
        net_amount_cents=838058,
        distribution_code=DISTRIBUTION_CODE_2,
        tax_year=2026,
    )
    assert setup["distribution"]["status"] == DISTRIBUTION_ISSUED
    setup["original_line"] = fixtures.read_tax_reports(
        client, distribution_id=setup["distribution"]["id"]
    )[0]
    mid = fixtures.read_ap_account(client, payee["id"])
    assert mid["balance_cents"] == 598001
    assert mid["after_tax_basis_cents"] == 8709
    assert mid["total_distributed_gross_cents"] == 1050000
    assert mid["version"] == 2
    return setup


def test_the_void_recomputes_the_payee_totals_instead_of_subtracting(client):
    """The totals return to their pre-payment values, and the row keeps its figures.

    PRD: "The payee account's `total_distributed_gross_cents` is then recomputed
    from the `ISSUED` set alone, so the voided row contributes 0."

    Design: Difficulty/transitive_cascade/distribution_void_three_level_compensating_cascade
    """
    setup = _one_payment_to_undo(client, "Compensation Plan")
    payee_id = setup["ap_account"]["id"]
    distribution = setup["distribution"]

    voided = fixtures.void_distribution(client, distribution["id"])
    assert voided["status"] == DISTRIBUTION_VOIDED
    assert voided["voided_at"] == constants.CLOCK_2026_09_15

    # The void does not rewrite history: every money field is preserved.
    assert_settlement(
        voided,
        gross_amount_cents=1050000,
        basis_recovery_cents=15291,
        taxable_amount_cents=1034709,
        federal_withheld_cents=206942,
        net_before_fee_cents=843058,
        admin_fee_cents=5000,
        net_amount_cents=838058,
        distribution_code=DISTRIBUTION_CODE_2,
        tax_year=2026,
    )

    restored = fixtures.read_ap_account(client, payee_id)
    assert restored["balance_cents"] == 1648001
    assert restored["after_tax_basis_cents"] == 24000
    assert restored["total_distributed_gross_cents"] == 0
    assert restored["version"] == 3
    assert restored["status"] == AP_ACCOUNT_ESTABLISHED

    # A separate-interest void restores the payee's own pool and never reaches
    # back into the participant's sources.
    account_id = setup["account"]["id"]
    assert fixtures.money_source_balances(client, account_id) == (
        SOURCES_AFTER_CONVERSION
    )
    assert_plan_account_figures(
        fixtures.read_plan_account(client, account_id),
        vested_balance_cents=2651999,
        assignable_base_cents=2351999,
        after_tax_basis_cents=36000,
        held_amount_cents=0,
        available_balance_cents=2651999,
    )

    # The row is still discoverable; it has simply left the ISSUED set.
    assert fixtures.read_distributions(
        client, payee_id, status=DISTRIBUTION_ISSUED
    ) == []
    all_rows = fixtures.read_distributions(client, payee_id)
    assert len(all_rows) == 1
    assert all_rows[0]["id"] == distribution["id"]
    assert all_rows[0]["status"] == DISTRIBUTION_VOIDED


def test_the_corrective_line_points_back_at_the_row_it_negates(client):
    """The ledger gains a second line whose self-reference is navigable both ways.

    PRD: "Because the reported amounts no longer reflect a payment, a corrective
    reporting line is appended whose `reportable_gross_cents`,
    `reportable_taxable_cents`, and `federal_withheld_cents` are the negations of
    the original line's, whose `distribution_code` and `tax_year` are copied from
    the original, and whose `correction_of_tax_report_id` is the original line's
    `id`."

    Design: Difficulty/transitive_cascade/distribution_void_three_level_compensating_cascade
    """
    setup = _one_payment_to_undo(client, "Compensation Plan B", "DRO-2663-V2")
    payee_id = setup["ap_account"]["id"]
    original = setup["original_line"]

    fixtures.void_distribution(client, setup["distribution"]["id"])

    corrections = fixtures.read_tax_reports(
        client, correction_of_tax_report_id=original["id"]
    )
    assert len(corrections) == 1
    corrective = corrections[0]
    assert_tax_line(
        corrective,
        reportable_gross_cents=-1050000,
        reportable_taxable_cents=-1034709,
        federal_withheld_cents=-206942,
        distribution_code=DISTRIBUTION_CODE_2,
        tax_year=2026,
        correction_of_tax_report_id=original["id"],
    )
    assert corrective["id"] != original["id"]
    assert corrective["distribution_id"] == setup["distribution"]["id"]
    assert corrective["alternate_payee_account_id"] == payee_id
    assert corrective["form_code"] == FORM_CODE_1099R
    assert_append_only_resource(corrective, "TaxReport")

    # Both edges resolve: the corrective line reads back by its own id.
    fetched = validate_success(client.get_tax_report(corrective["id"], ADMIN_HEADERS))
    assert fetched["id"] == corrective["id"]
    assert fetched["correction_of_tax_report_id"] == original["id"]

    # A second void is refused, and refusals append nothing.
    assert_error_envelope(
        client.void_distribution(setup["distribution"]["id"], ADMIN_HEADERS),
        api_errors.ERR_DISTRIBUTION_ALREADY_VOIDED,
        409,
    )
    assert len(
        fixtures.read_tax_reports(client, alternate_payee_account_id=payee_id)
    ) == 2
    assert fixtures.read_ap_account(client, payee_id)["version"] == 3


def test_the_original_line_survives_the_void_and_the_pair_nets_to_zero(client):
    """Two non-zero rows whose signed columns sum to nothing at all.

    PRD: "After an issue followed by a void, all three of the account's net
    figures for that year are 0 while the ledger holds two rows, never zero rows —
    the history of the mistake is part of the record."

    Design: Difficulty/compensating_invariant/append_only_tax_ledger_nets_to_zero_after_void
    """
    setup = _one_payment_to_undo(client, "Ledger Plan")
    payee_id = setup["ap_account"]["id"]
    original = setup["original_line"]
    assert_tax_line(
        original,
        reportable_gross_cents=1050000,
        reportable_taxable_cents=1034709,
        federal_withheld_cents=206942,
        distribution_code=DISTRIBUTION_CODE_2,
        tax_year=2026,
        correction_of_tax_report_id=None,
    )
    assert original["form_code"] == FORM_CODE_1099R

    fixtures.void_distribution(client, setup["distribution"]["id"])

    # The original line was neither mutated nor deleted.
    reread = validate_success(client.get_tax_report(original["id"], ADMIN_HEADERS))
    assert_tax_line(
        reread,
        reportable_gross_cents=1050000,
        reportable_taxable_cents=1034709,
        federal_withheld_cents=206942,
        correction_of_tax_report_id=None,
    )
    assert reread["written_at"] == original["written_at"]

    ledger = fixtures.read_tax_reports(client, alternate_payee_account_id=payee_id)
    assert len(ledger) == 2, "the record of the mistake is kept, not erased"
    assert ledger[0]["id"] == original["id"]
    assert_tax_ledger_nets_to_zero(ledger)
    assert_tax_ledger_totals(
        fixtures.read_tax_reports(client, tax_year=2026), 0, 0, 0
    )


def test_the_replay_after_the_void_reproduces_the_figures_cent_for_cent(client):
    """Both pools were restored, so the identical election settles identically.

    PRD: "A payee account's net reported position for a given year is the sum of
    `reportable_gross_cents`, the sum of `reportable_taxable_cents`, and the sum of
    `federal_withheld_cents` over every line whose `alternate_payee_account_id` is
    that account and whose `tax_year` is that year — original and corrective lines
    alike, since correction is expressed by sign rather than by deletion."

    Design: Difficulty/compensating_invariant/append_only_tax_ledger_nets_to_zero_after_void
    """
    setup = _one_payment_to_undo(client, "Ledger Plan B", "DRO-2663-L2")
    payee = setup["ap_account"]
    payee_id = payee["id"]
    voided = setup["distribution"]

    fixtures.void_distribution(client, voided["id"])
    restored = fixtures.read_ap_account(client, payee_id)
    assert restored["version"] == 3

    # A basis pool left at 8709 would have priced the recovery at 5548 instead.
    replay = fixtures.issue_distribution(
        client,
        payee_id,
        restored["version"],
        1050000,
        headers=fixtures.payee_headers(payee),
    )
    assert_settlement(
        replay,
        gross_amount_cents=1050000,
        basis_recovery_cents=15291,
        taxable_amount_cents=1034709,
        federal_withheld_cents=206942,
        net_before_fee_cents=843058,
        admin_fee_cents=5000,
        net_amount_cents=838058,
        distribution_code=DISTRIBUTION_CODE_2,
        tax_year=2026,
    )
    assert replay["id"] != voided["id"]
    assert replay["status"] == DISTRIBUTION_ISSUED
    assert replay["voided_at"] is None

    rows = fixtures.read_distributions(client, payee_id)
    assert len(rows) == 2
    assert sorted(row["status"] for row in rows) == [
        DISTRIBUTION_ISSUED,
        DISTRIBUTION_VOIDED,
    ]
    issued_only = fixtures.read_distributions(
        client, payee_id, status=DISTRIBUTION_ISSUED
    )
    assert len(issued_only) == 1
    assert issued_only[0]["id"] == replay["id"]

    final = fixtures.read_ap_account(client, payee_id)
    assert final["balance_cents"] == 598001
    assert final["after_tax_basis_cents"] == 8709
    assert final["total_distributed_gross_cents"] == 1050000
    assert final["version"] == 4
    assert final["status"] == AP_ACCOUNT_ESTABLISHED

    # The ledger grew from one row to two to three and never shrank; its net
    # position is now exactly the one payment that still stands.
    ledger = fixtures.read_tax_reports(client, alternate_payee_account_id=payee_id)
    assert len(ledger) == 3
    assert_tax_ledger_totals(ledger, 1050000, 1034709, 206942)

    # None of it reached the participant's account.
    assert_plan_account_figures(
        fixtures.read_plan_account(client, setup["account"]["id"]),
        vested_balance_cents=2651999,
        held_amount_cents=0,
        available_balance_cents=2651999,
    )
    assert fixtures.money_source_balances(client, setup["account"]["id"]) == (
        SOURCES_AFTER_CONVERSION
    )
