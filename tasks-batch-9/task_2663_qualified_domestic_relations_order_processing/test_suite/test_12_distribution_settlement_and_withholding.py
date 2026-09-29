"""Seven pinned steps, and the two places where one input changes all of them.

The election is not a label on an otherwise fixed payment: it decides the
withholding, which decides the intermediate net, which decides the fee tier,
which decides the money the payee actually receives. The withholding floor is
read on the taxable amount, so a smaller payment can arrive larger than a bigger
one.
"""

from test_helpers import constants, fixtures
from test_helpers.assertions import (
    assert_ap_account_totals,
    assert_append_only_resource,
    assert_settlement,
    assert_tax_line,
    assert_tax_ledger_totals,
)
from test_helpers.types import (
    AP_ACCOUNT_ESTABLISHED,
    APPROACH_SEPARATE_INTEREST,
    DISTRIBUTION_CODE_2,
    DISTRIBUTION_CODE_G,
    DISTRIBUTION_ISSUED,
    DISTRIBUTION_VOIDED,
    EARNINGS_PERIOD_END,
    ELECTION_CASH,
    ELECTION_DIRECT_ROLLOVER,
    FORMULA_PERCENTAGE_OF_ACCOUNT,
)

SETTLEMENT_PLAN = {
    "acceptable_formula_codes": [FORMULA_PERCENTAGE_OF_ACCOUNT],
    "allowed_approaches": [APPROACH_SEPARATE_INTEREST],
    "earnings_adjustment_method": EARNINGS_PERIOD_END,
    "requires_model_language": True,
    "permits_benefit_not_otherwise_available": False,
    "max_assignable_pct_bps": 5000,
    "max_assignable_amount_cents": 2000000,
}

ROLLOVER_TRUSTEE = "Fidelity IRA 8831"
IRA_TRUSTEE = "Vanguard IRA 4410"


def _funded_payee(client, plan_name, reference="DRO-2663-T1"):
    """A payee account carrying 1648001 cents of principal over 24000 of basis."""
    setup = fixtures.setup_qualified_separate_interest(
        client,
        plan_name,
        sources=fixtures.FOUR_SOURCE_MIX,
        snapshots=(("2026-06-30", 4000000), ("2026-12-31", 4120000)),
        qualify_clock=constants.CLOCK_2026_09_15,
        plan_overrides=SETTLEMENT_PLAN,
        participant_overrides={
            "full_name": "Dana Reyes",
            "ssn_last4": "4417",
            "date_of_birth": "1979-04-12",
            "participation_start_date": "2010-01-01",
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
    assert payee["status"] == AP_ACCOUNT_ESTABLISHED
    return setup


def _zero_basis_payee(client, plan_name):
    """A payee account with no basis at all, so taxable always equals gross."""
    setup = fixtures.setup_qualified_separate_interest(
        client,
        plan_name,
        snapshots=(("2026-06-30", 1000000),),
        qualify_clock=constants.CLOCK_2026_09_15,
        plan_overrides=SETTLEMENT_PLAN,
        participant_overrides={
            "full_name": "Sanne Delacroix",
            "ssn_last4": "3031",
            "date_of_birth": "1973-07-07",
            "participation_start_date": "2010-01-01",
        },
        case_overrides={
            "alternate_payee_name": "Yves Delacroix",
            "alternate_payee_dob": "1982-04-04",
            "marital_period_start": "2012-03-01",
            "marital_period_end": "2026-02-01",
        },
        draft_overrides={"document_reference": "DRO-2663-F1"},
    )
    payee = setup["ap_account"]
    assert payee["balance_cents"] == 400000
    assert payee["after_tax_basis_cents"] == 0
    assert payee["version"] == 1
    return setup


def test_a_rollover_withholds_nothing_and_draws_the_top_fee_tier(client):
    """The rollover's intermediate net is the whole gross, so the fee is 7500.

    PRD: "For a `DIRECT_ROLLOVER`, `federal_withheld_cents` is always 0 no matter
    how large the taxable amount."

    Design: Difficulty/dual_variant_calc/cash_versus_direct_rollover_settlement_divergence
    """
    setup = _funded_payee(client, "Divergence Plan")
    payee = setup["ap_account"]

    rollover = fixtures.issue_distribution(
        client,
        payee["id"],
        payee["version"],
        1050000,
        headers=fixtures.payee_headers(payee),
        election=ELECTION_DIRECT_ROLLOVER,
        rollover_institution=ROLLOVER_TRUSTEE,
    )
    assert_settlement(
        rollover,
        gross_amount_cents=1050000,
        basis_recovery_cents=15291,
        taxable_amount_cents=1034709,
        federal_withheld_cents=0,
        net_before_fee_cents=1050000,
        admin_fee_cents=7500,
        net_amount_cents=1042500,
        distribution_code=DISTRIBUTION_CODE_G,
        tax_year=2026,
    )
    assert rollover["election"] == ELECTION_DIRECT_ROLLOVER
    assert rollover["rollover_institution"] == ROLLOVER_TRUSTEE
    assert rollover["status"] == DISTRIBUTION_ISSUED
    assert rollover["issued_at"] == constants.CLOCK_2026_09_15
    assert rollover["voided_at"] is None

    after = fixtures.read_ap_account(client, payee["id"])
    assert after["balance_cents"] == 598001
    assert after["after_tax_basis_cents"] == 8709
    assert after["total_distributed_gross_cents"] == 1050000
    assert after["version"] == 2
    assert after["status"] == AP_ACCOUNT_ESTABLISHED

    ledger = fixtures.read_tax_reports(client, alternate_payee_account_id=payee["id"])
    assert len(ledger) == 1
    assert_append_only_resource(ledger[0], "TaxReport")
    assert_tax_line(
        ledger[0],
        reportable_gross_cents=1050000,
        reportable_taxable_cents=1034709,
        federal_withheld_cents=0,
        distribution_code=DISTRIBUTION_CODE_G,
        tax_year=2026,
        correction_of_tax_report_id=None,
    )
    assert ledger[0]["distribution_id"] == rollover["id"]


def test_the_identical_gross_taken_as_cash_diverges_at_every_later_step(client):
    """Same gross, same basis recovery, same taxable — and a different net.

    PRD: "Because the fee tier keys on the net after withholding, the election
    alone can change the fee on an identical gross. Take a gross of 1050000 cents
    whose basis recovery leaves a taxable amount of 1034710 cents: the cash
    election withholds 206942, lands at a `net_before_fee_cents` of 843058, and
    draws the middle fee of 5000; the direct rollover of the very same gross
    withholds nothing, lands at a `net_before_fee_cents` of 1050000, and draws the
    top fee of 7500."

    Design: Difficulty/dual_variant_calc/cash_versus_direct_rollover_settlement_divergence
    """
    setup = _funded_payee(client, "Divergence Plan B", "DRO-2663-T2")
    payee = setup["ap_account"]
    payee_id = payee["id"]

    rollover = fixtures.issue_distribution(
        client,
        payee_id,
        payee["version"],
        1050000,
        headers=fixtures.payee_headers(payee),
        election=ELECTION_DIRECT_ROLLOVER,
        rollover_institution=ROLLOVER_TRUSTEE,
    )

    # The void restores the funding side exactly, so the cash election that
    # follows starts from the same pools the rollover started from.
    voided = fixtures.void_distribution(client, rollover["id"])
    assert voided["status"] == DISTRIBUTION_VOIDED
    restored = fixtures.read_ap_account(client, payee_id)
    assert restored["balance_cents"] == 1648001
    assert restored["after_tax_basis_cents"] == 24000
    assert restored["total_distributed_gross_cents"] == 0
    assert restored["version"] == 3

    cash = fixtures.issue_distribution(
        client,
        payee_id,
        restored["version"],
        1050000,
        headers=fixtures.payee_headers(payee),
    )
    assert_settlement(
        cash,
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
    assert cash["election"] == ELECTION_CASH
    assert cash["rollover_institution"] is None

    # The first three steps are election-blind; the last four are not.
    assert cash["basis_recovery_cents"] == rollover["basis_recovery_cents"]
    assert cash["taxable_amount_cents"] == rollover["taxable_amount_cents"]
    assert cash["federal_withheld_cents"] > rollover["federal_withheld_cents"]
    assert cash["net_before_fee_cents"] < rollover["net_before_fee_cents"]
    assert cash["admin_fee_cents"] < rollover["admin_fee_cents"]
    assert cash["net_amount_cents"] < rollover["net_amount_cents"]

    final = fixtures.read_ap_account(client, payee_id)
    assert final["balance_cents"] == 598001
    assert final["after_tax_basis_cents"] == 8709
    assert final["total_distributed_gross_cents"] == 1050000
    assert final["version"] == 4
    assert final["status"] == AP_ACCOUNT_ESTABLISHED

    # Three lines: the rollover original, its negation, and the cash original.
    ledger = fixtures.read_tax_reports(client, alternate_payee_account_id=payee_id)
    assert len(ledger) == 3
    assert_tax_ledger_totals(ledger, 1050000, 1034709, 206942)


def _walk_the_first_two_tiers(client, setup):
    """A 1000000 rollover then a 600000 cash payment on the same payee account."""
    payee = setup["ap_account"]
    headers = fixtures.payee_headers(payee)
    top = fixtures.issue_distribution(
        client,
        payee["id"],
        payee["version"],
        1000000,
        headers=headers,
        election=ELECTION_DIRECT_ROLLOVER,
        rollover_institution=IRA_TRUSTEE,
    )
    after_top = fixtures.read_ap_account(client, payee["id"])
    middle = fixtures.issue_distribution(
        client,
        payee["id"],
        after_top["version"],
        600000,
        headers=headers,
    )
    return top, after_top, middle


def test_the_fee_tier_walks_down_as_the_intermediate_net_falls(client):
    """A 600000 payment draws the middle tier while 1000000 draws the top one.

    PRD: "The tier is keyed on `net_before_fee_cents` and never on the gross or on
    the final net. A `net_before_fee_cents` below 100000 cents draws an
    `admin_fee_cents` of 2500; from 100000 up to and including 999999 cents it
    draws 5000; at 1000000 cents or above it draws 7500."

    Design: Difficulty/combinatorial_formula/admin_fee_tier_keyed_on_net_after_withholding
    """
    setup = _funded_payee(client, "Tier Walk Plan")
    payee_id = setup["ap_account"]["id"]
    top, after_top, middle = _walk_the_first_two_tiers(client, setup)

    assert_settlement(
        top,
        gross_amount_cents=1000000,
        basis_recovery_cents=14563,
        taxable_amount_cents=985437,
        federal_withheld_cents=0,
        net_before_fee_cents=1000000,
        admin_fee_cents=7500,
        net_amount_cents=992500,
        distribution_code=DISTRIBUTION_CODE_G,
        tax_year=2026,
    )
    assert after_top["balance_cents"] == 648001
    assert after_top["after_tax_basis_cents"] == 9437
    assert after_top["total_distributed_gross_cents"] == 1000000
    assert after_top["version"] == 2

    # 600000 gross, but the tier reads 481747 — the net after withholding.
    assert_settlement(
        middle,
        gross_amount_cents=600000,
        basis_recovery_cents=8737,
        taxable_amount_cents=591263,
        federal_withheld_cents=118253,
        net_before_fee_cents=481747,
        admin_fee_cents=5000,
        net_amount_cents=476747,
        distribution_code=DISTRIBUTION_CODE_2,
        tax_year=2026,
    )
    after_middle = fixtures.read_ap_account(client, payee_id)
    assert after_middle["balance_cents"] == 48001
    assert after_middle["after_tax_basis_cents"] == 700
    assert after_middle["total_distributed_gross_cents"] == 1600000
    assert after_middle["version"] == 3
    assert after_middle["status"] == AP_ACCOUNT_ESTABLISHED


def test_the_bottom_tier_is_reached_both_with_and_without_withholding(client):
    """Two payments draw the same 2500 fee though only one of them is withheld on.

    PRD: "A `net_before_fee_cents` below 100000 cents draws an `admin_fee_cents`
    of 2500; from 100000 up to and including 999999 cents it draws 5000; at
    1000000 cents or above it draws 7500."

    Design: Difficulty/combinatorial_formula/admin_fee_tier_keyed_on_net_after_withholding
    """
    setup = _funded_payee(client, "Tier Floor Plan", "DRO-2663-T3")
    payee = setup["ap_account"]
    payee_id = payee["id"]
    headers = fixtures.payee_headers(payee)
    _walk_the_first_two_tiers(client, setup)

    small = fixtures.issue_distribution(
        client, payee_id, 3, 24000, headers=headers
    )
    assert_settlement(
        small,
        gross_amount_cents=24000,
        basis_recovery_cents=349,
        taxable_amount_cents=23651,
        federal_withheld_cents=4730,
        net_before_fee_cents=19270,
        admin_fee_cents=2500,
        net_amount_cents=16770,
        distribution_code=DISTRIBUTION_CODE_2,
        tax_year=2026,
    )

    # The taxable amount now falls below the floor, so nothing is withheld and
    # the intermediate net is the whole gross — yet the tier is the same 2500.
    smaller = fixtures.issue_distribution(
        client, payee_id, 4, 19000, headers=headers
    )
    assert_settlement(
        smaller,
        gross_amount_cents=19000,
        basis_recovery_cents=277,
        taxable_amount_cents=18723,
        federal_withheld_cents=0,
        net_before_fee_cents=19000,
        admin_fee_cents=2500,
        net_amount_cents=16500,
        distribution_code=DISTRIBUTION_CODE_2,
        tax_year=2026,
    )

    final = fixtures.read_ap_account(client, payee_id)
    assert final["balance_cents"] == 5001
    assert final["after_tax_basis_cents"] == 74
    assert final["total_distributed_gross_cents"] == 1643000
    assert final["version"] == 5
    assert final["status"] == AP_ACCOUNT_ESTABLISHED
    assert_ap_account_totals(final, fixtures.read_distributions(client, payee_id))

    ledger = fixtures.read_tax_reports(client, alternate_payee_account_id=payee_id)
    assert len(ledger) == 4
    for row in ledger:
        assert row["tax_year"] == 2026
        assert row["correction_of_tax_report_id"] is None
    assert_tax_ledger_totals(ledger, 1643000, 1619074, 122983)


def test_withholding_starts_at_exactly_twenty_thousand_taxable_cents(client):
    """At the floor itself the twenty percent applies, not one cent below it.

    PRD: "For a `CASH` election, withholding applies only once
    `taxable_amount_cents` reaches at least 20000 cents, at which point
    `federal_withheld_cents` is `taxable_amount_cents` multiplied by 2000 basis
    points — twenty percent — divided by 10000 and rounded **half up** to whole
    cents; below that floor it is 0."

    Design: Difficulty/boundary_precision_check/withholding_triggers_at_exactly_twenty_thousand_taxable_cents
    """
    setup = _zero_basis_payee(client, "Threshold Plan")
    payee = setup["ap_account"]

    at_the_floor = fixtures.issue_distribution(
        client,
        payee["id"],
        payee["version"],
        20000,
        headers=fixtures.payee_headers(payee),
    )
    assert_settlement(
        at_the_floor,
        gross_amount_cents=20000,
        basis_recovery_cents=0,
        taxable_amount_cents=20000,
        federal_withheld_cents=4000,
        net_before_fee_cents=16000,
        admin_fee_cents=2500,
        net_amount_cents=13500,
        distribution_code=DISTRIBUTION_CODE_2,
        tax_year=2026,
    )
    after = fixtures.read_ap_account(client, payee["id"])
    assert after["balance_cents"] == 380000
    assert after["after_tax_basis_cents"] == 0
    assert after["total_distributed_gross_cents"] == 20000
    assert after["version"] == 2


def test_one_cent_below_the_floor_the_smaller_payment_arrives_larger(client):
    """19999 nets 17499 while 20000 nets 13500 — the ordering of the two inverts.

    PRD: "The threshold is on the **taxable** amount and not on the gross: with no
    basis at all, a gross of 20000 withholds 4000 while a gross of 19999 withholds
    nothing."

    Design: Difficulty/boundary_precision_check/withholding_triggers_at_exactly_twenty_thousand_taxable_cents
    """
    setup = _zero_basis_payee(client, "Threshold Plan B")
    payee = setup["ap_account"]
    payee_id = payee["id"]
    headers = fixtures.payee_headers(payee)

    larger = fixtures.issue_distribution(
        client, payee_id, payee["version"], 20000, headers=headers
    )
    smaller = fixtures.issue_distribution(
        client, payee_id, 2, 19999, headers=headers
    )
    assert_settlement(
        smaller,
        gross_amount_cents=19999,
        basis_recovery_cents=0,
        taxable_amount_cents=19999,
        federal_withheld_cents=0,
        net_before_fee_cents=19999,
        admin_fee_cents=2500,
        net_amount_cents=17499,
        distribution_code=DISTRIBUTION_CODE_2,
        tax_year=2026,
    )
    assert smaller["gross_amount_cents"] < larger["gross_amount_cents"]
    assert smaller["net_amount_cents"] > larger["net_amount_cents"], (
        "one cent of taxable amount is worth 4000 cents of withholding"
    )
    assert smaller["admin_fee_cents"] == larger["admin_fee_cents"]

    final = fixtures.read_ap_account(client, payee_id)
    assert final["balance_cents"] == 360001
    assert final["total_distributed_gross_cents"] == 39999
    assert final["version"] == 3
    assert final["status"] == AP_ACCOUNT_ESTABLISHED

    ledger = fixtures.read_tax_reports(client, alternate_payee_account_id=payee_id)
    assert len(ledger) == 2
    assert_tax_ledger_totals(ledger, 39999, 39999, 4000)
