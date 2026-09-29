"""Dual-variant computations: the two coverage variants and the two ownership figures.

Both families compute two deliberately different answers over one identical input
set. The coverage pair (PRD 3.7) reads a licensee's holdings twice — once at book
value and once through the regulatory haircut/aging/concentration filter. The
ownership pair (PRD 3.2) reads one holding-company link twice — once economically
and once under the regulatory attribution convention.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import MoneyTransmitterApiClient
from test_helpers import fixtures as fx
from test_helpers.test_users import CHIEF_HEADERS, MANAGER_HEADERS

# ---------------------------------------------------------------------------
# The one holding set both coverage variants read.
#
# CASH / US_TREASURY are the uncapped classes; the two RECEIVABLE_FROM_DELEGATE
# rows sit in different counterparty groups and differ only in age; the
# CORPORATE_DEBT row is the sole non-permissible class.
# ---------------------------------------------------------------------------

DIVERGING_HOLDINGS = [
    {
        "asset_class": "CASH",
        "counterparty_name": "BankA",
        "book_value_cents": 40_000_000,
        "market_value_cents": 40_000_000,
    },
    {
        "asset_class": "US_TREASURY",
        "counterparty_name": "CustodianB",
        "book_value_cents": 30_000_000,
        "market_value_cents": 29_000_000,
    },
    {
        "asset_class": "RECEIVABLE_FROM_DELEGATE",
        "counterparty_name": "DelegX",
        "book_value_cents": 12_000_000,
        "market_value_cents": 12_000_000,
        "age_days": 4,
    },
    {
        "asset_class": "RECEIVABLE_FROM_DELEGATE",
        "counterparty_name": "DelegY",
        "book_value_cents": 8_000_000,
        "market_value_cents": 8_000_000,
        "age_days": 9,
    },
    {
        "asset_class": "CORPORATE_DEBT",
        "counterparty_name": "IssuerZ",
        "book_value_cents": 15_000_000,
        "market_value_cents": 15_000_000,
    },
]

OBLIGATIONS_CENTS = 85_000_000


def _seed_diverging_coverage(api: MoneyTransmitterApiClient, scenario: fx.Scenario) -> None:
    """Put 85,000,000 cents of obligations and the five holdings on the licensee."""
    fx.adjust_obligations(
        api,
        scenario.license_id,
        OBLIGATIONS_CENTS,
        memo="Q3 outstanding transmission liability",
    )
    fx.record_holdings(api, scenario.licensee_id, DIVERGING_HOLDINGS)


# ===========================================================================
# Instance: the two coverage variants over one identical holding set
# ===========================================================================


def test_coverage_summary_reports_both_variants_over_one_holding_set(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """The coverage read exposes book value and eligible market value side by side.

    PRD 3.7: "A licensee-level coverage read exposes both variants side by side over identical holdings — `obligations_cents`, `book_investment_value_cents`, `book_coverage_ratio_bps`, `eligible_investment_value_cents`, `coverage_ratio_bps`, `concentration_cap_cents`, `coverage_posture` and `consecutive_failed_test_count` — so that the divergence is observable in a single response."
    PRD 3.7: "The candidate set for both is the licensee's holdings whose `status` is `HELD` and whose `asset_class` is not among the non-permissible classes — and `CORPORATE_DEBT` is the sole non-permissible class, so corporate debt is excluded from both variants outright, as are all disposed rows."
    PRD 3.7: "The `BOOK_VALUE` variant is the generous one: `book_investment_value_cents` is simply the sum of `book_value_cents` over the candidate set."
    PRD 3.7: "No haircut is applied, no receivable is aged out, and no counterparty concentration cap is imposed."
    PRD 3.7: "First, the concentration cap is fixed for this licensee as its `aggregate_outstanding_obligations_cents` multiplied by 1000 basis points — ten percent — divided by 10000 and rounded down; that figure is exposed as `concentration_cap_cents`."
    PRD 3.7: "A `RECEIVABLE_FROM_DELEGATE` holding whose `age_days` exceeds five is skipped entirely: a receivable older than five days is not a permissible investment at all."
    PRD 3.7: "Every other holding contributes an adjusted amount equal to its `market_value_cents` multiplied by 10000 minus its class haircut, divided by 10000 and rounded down at that step."
    PRD 3.7: "The haircuts, in basis points, are: `CASH` none, `US_TREASURY` 200, `MONEY_MARKET_FUND` 300, `AGENCY_BOND` 500 and `RECEIVABLE_FROM_DELEGATE` 1000."
    PRD 3.7: "Holdings in the concentration-capped classes — `AGENCY_BOND`, `MONEY_MARKET_FUND` and `RECEIVABLE_FROM_DELEGATE` — accumulate into a running total per `counterparty_name`."
    PRD 3.7: "Holdings in the uncapped classes — `CASH` and `US_TREASURY` — accumulate into a single uncapped total."
    PRD 3.7: "Finally, `eligible_investment_value_cents` is the uncapped total plus, for each counterparty group, the lesser of that group's running total and the concentration cap."
    PRD 3.7: "A coverage ratio in basis points is derived from an investment value the same way for both variants: it is exactly 10000 when the licensee's `aggregate_outstanding_obligations_cents` is zero, and otherwise the investment value multiplied by 10000, divided by the obligations, rounded down."
    PRD 3.4: "The aggregate itself is the exact sum, in integer cents with no rounding, of `outstanding_obligations_cents` over the licensee's licences whose `license_status` is `PENDING_BOND`, `ACTIVE`, `SUSPENDED` or `SURRENDER_REQUESTED`."

    Design: Difficulty/dual_variant_calc/coverage_variants_diverge_on_identical_holdings
    """
    _seed_diverging_coverage(api, active_license)

    summary = validate_success(
        api.get_coverage_summary(active_license.licensee_id, CHIEF_HEADERS)
    )

    # Exact sum over the one ACTIVE licence: 0 + 85,000,000 = 85,000,000.
    assert summary["obligations_cents"] == 85_000_000

    # BOOK_VALUE: plain sum of book_value_cents over the HELD non-CORPORATE_DEBT
    # rows = 40,000,000 + 30,000,000 + 12,000,000 + 8,000,000 = 90,000,000.
    assert summary["book_investment_value_cents"] == 90_000_000
    # floor(90,000,000 * 10000 / 85,000,000) = floor(10588.23...) = 10588.
    assert summary["book_coverage_ratio_bps"] == 10_588

    # concentration cap = floor(85,000,000 * 1000 / 10000) = 8,500,000.
    assert summary["concentration_cap_cents"] == 8_500_000
    # ELIGIBLE_MARKET, in the pinned order:
    #   CASH BankA        floor(40,000,000 * 10000 / 10000) = 40,000,000  (uncapped)
    #   US_TREASURY       floor(29,000,000 *  9800 / 10000) = 28,420,000  (uncapped)
    #   RECEIVABLE DelegX floor(12,000,000 *  9000 / 10000) = 10,800,000  (group DelegX)
    #   RECEIVABLE DelegY age 9 > 5                          skipped
    #   CORPORATE_DEBT                                       not permissible
    #   uncapped total = 40,000,000 + 28,420,000            = 68,420,000
    #   group DelegX capped = min(10,800,000, 8,500,000)    =  8,500,000
    #   total = 68,420,000 + 8,500,000                      = 76,920,000
    assert summary["eligible_investment_value_cents"] == 76_920_000
    # floor(76,920,000 * 10000 / 85,000,000) = floor(9049.41...) = 9049.
    assert summary["coverage_ratio_bps"] == 9_049

    # 90,000,000 - 76,920,000 = 13,080,000 of divergence over identical holdings.
    assert (
        summary["book_investment_value_cents"] - summary["eligible_investment_value_cents"]
        == 13_080_000
    )


def test_posture_follows_the_eligible_market_variant_not_the_book_one(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """The licensee row publishes both values but derives ratio and posture from the eligible one.

    PRD 3.7: "The licensee's `coverage_ratio_bps` is always the `ELIGIBLE_MARKET` ratio and never the book-value one; its default is 10000."
    PRD 3.7: "From it, and from `consecutive_failed_test_count`, the licensee's `coverage_posture` is determined by a strictly ordered test: the posture is `FROZEN` if `consecutive_failed_test_count` is at least 2, regardless of the ratio; otherwise `COMPLIANT` if `coverage_ratio_bps` is at least 10000; otherwise `WATCH` if `coverage_ratio_bps` is at least 9500; otherwise `DEFICIENT`."
    PRD 3.7: "The boundaries are exact: 10000 is `COMPLIANT`, 9999 is `WATCH`, 9500 is `WATCH`, 9499 is `DEFICIENT`."
    PRD 3.7: "The `BOOK_VALUE` variant is the generous one: `book_investment_value_cents` is simply the sum of `book_value_cents` over the candidate set."
    PRD 3.7: "Finally, `eligible_investment_value_cents` is the uncapped total plus, for each counterparty group, the lesser of that group's running total and the concentration cap."
    PRD 3.7: "A coverage ratio in basis points is derived from an investment value the same way for both variants: it is exactly 10000 when the licensee's `aggregate_outstanding_obligations_cents` is zero, and otherwise the investment value multiplied by 10000, divided by the obligations, rounded down."
    PRD 3.1: "A freshly created licensee starts with `version` at 1, `coverage_posture` at `COMPLIANT`, `coverage_ratio_bps` at 10000 — vacuously perfect, since there are no obligations yet — `control_chain_status` at `VERIFIED`, and every counter at zero: `aggregate_outstanding_obligations_cents`, `eligible_investment_value_cents`, `book_investment_value_cents`, `consecutive_failed_test_count` and `active_license_count`."

    Design: Difficulty/dual_variant_calc/coverage_variants_diverge_on_identical_holdings
    """
    _seed_diverging_coverage(api, active_license)

    licensee = fx.get_licensee(api, active_license.licensee_id)

    assert licensee["aggregate_outstanding_obligations_cents"] == 85_000_000
    # Both variants are published on the row: 90,000,000 book, 76,920,000 eligible.
    assert licensee["book_investment_value_cents"] == 90_000_000
    assert licensee["eligible_investment_value_cents"] == 76_920_000

    # No test has been certified, so the FROZEN branch of the ladder is not taken.
    assert licensee["consecutive_failed_test_count"] == 0
    # coverage_ratio_bps is the eligible ratio 9049, not the book ratio 10588.
    assert licensee["coverage_ratio_bps"] == 9_049
    # 9049 < 9500, so the posture is DEFICIENT even though the book ratio clears 10000.
    assert licensee["coverage_posture"] == "DEFICIENT"


def test_the_two_test_methods_freeze_opposite_verdicts_on_the_same_holdings(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A BOOK_VALUE filing passes and an ELIGIBLE_MARKET filing shortfalls over one holding set.

    PRD 3.7: "`obligations_cents` snapshots the licensee's `aggregate_outstanding_obligations_cents`; `investment_value_cents` snapshots the permissible investment value computed under this row's own `method`; `coverage_ratio_bps` is that value multiplied by 10000 divided by `obligations_cents` and rounded down, or exactly 10000 when `obligations_cents` is zero; `shortfall_cents` is `obligations_cents` minus `investment_value_cents`, or zero when that difference would be negative — never a negative number; and `result` becomes `PASS` when `coverage_ratio_bps` is at least 10000 and `SHORTFALL` otherwise, having been null until preparation."
    PRD 3.7: "The `BOOK_VALUE` variant is the generous one: `book_investment_value_cents` is simply the sum of `book_value_cents` over the candidate set."
    PRD 3.7: "For the same holdings it is therefore always at least as large as the other variant."
    PRD 3.7: "Finally, `eligible_investment_value_cents` is the uncapped total plus, for each counterparty group, the lesser of that group's running total and the concentration cap."
    PRD 3.7: "Creating a new test supersedes the old work: any existing test of the same licensee whose status is `DRAFT` or `PREPARED` moves to the terminal `SUPERSEDED`, and the create bumps `Licensee.version`."

    Design: Difficulty/dual_variant_calc/coverage_variants_diverge_on_identical_holdings
    """
    _seed_diverging_coverage(api, active_license)

    book_test = fx.open_investment_test(api, active_license.licensee_id, "BOOK_VALUE")
    book_prepared = fx.prepare_investment_test(api, book_test["id"])

    assert book_prepared["obligations_cents"] == 85_000_000
    # BOOK_VALUE: 40,000,000 + 30,000,000 + 12,000,000 + 8,000,000 = 90,000,000.
    assert book_prepared["investment_value_cents"] == 90_000_000
    # floor(90,000,000 * 10000 / 85,000,000) = 10588.
    assert book_prepared["coverage_ratio_bps"] == 10_588
    # 85,000,000 - 90,000,000 is negative, so the shortfall floors at zero.
    assert book_prepared["shortfall_cents"] == 0
    assert book_prepared["result"] == "PASS"

    market_test = fx.open_investment_test(
        api, active_license.licensee_id, "ELIGIBLE_MARKET"
    )
    market_prepared = fx.prepare_investment_test(api, market_test["id"])

    assert market_prepared["obligations_cents"] == 85_000_000
    # ELIGIBLE_MARKET: 40,000,000 + 28,420,000 + min(10,800,000, 8,500,000) = 76,920,000.
    assert market_prepared["investment_value_cents"] == 76_920_000
    # floor(76,920,000 * 10000 / 85,000,000) = 9049.
    assert market_prepared["coverage_ratio_bps"] == 9_049
    # 85,000,000 - 76,920,000 = 8,080,000.
    assert market_prepared["shortfall_cents"] == 8_080_000
    assert market_prepared["result"] == "SHORTFALL"

    # The generous variant read 90,000,000 where the regulatory one read 76,920,000.
    assert (
        book_prepared["investment_value_cents"] > market_prepared["investment_value_cents"]
    )


# ===========================================================================
# Instance: the two ownership figures over one holding-company link
# ===========================================================================


def test_holdco_link_reads_2400_economically_and_4000_on_attribution(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """Forty percent of a sixty-percent holdco dilutes economically but attributes at full value.

    PRD 3.2: "The **economic** figure, `effective_ownership_bps`, multiplies the chain: for a direct holder it is simply `direct_ownership_bps`; otherwise it is the row's `direct_ownership_bps` multiplied by the parent's `effective_ownership_bps`, divided by 10000 with the result rounded down at that hop."
    PRD 3.2: "The **attributed** figure, `attributed_ownership_bps`, applies the regulatory attribution convention instead: for a direct holder it is again `direct_ownership_bps`; if the parent's own `direct_ownership_bps` is at least 2500 basis points, the parent link is treated as controlling and the row's stake is attributed at full value, so `attributed_ownership_bps` equals the row's `direct_ownership_bps` unchanged; only when the parent's direct stake is below 2500 basis points does the row's stake get diluted, becoming the row's `direct_ownership_bps` multiplied by the parent's `attributed_ownership_bps` divided by 10000 and rounded down."
    PRD 3.2: "The divergence is deliberate and observable: a holder owning forty percent of a holding company that itself owns sixty percent of the licensee reads 2400 basis points economically — below the control threshold — but 4000 basis points on attribution, and is therefore a control person."
    PRD 3.2: "The control test uses the attributed figure, never the economic one."
    PRD 3.2: "`control_determination` is `CONTROL` when `attributed_ownership_bps` is at least 2500 basis points **or** the holder's `role_title` is one of the four officer titles `CEO`, `CFO`, `COO` or `CCO`; otherwise it is `NON_CONTROL`."
    PRD 3.2: "A `DIRECTOR`, an `ENTITY_HOLDER` and a `PASSIVE_INVESTOR` are officers for no purpose here — they reach `CONTROL` only through the attributed stake."
    PRD 3.2: "`background_check_status` is set to `PENDING` for a control person and to `NOT_REQUIRED` otherwise; its full value set is `NOT_REQUIRED`, `PENDING`, `CLEARED` and `ADVERSE`, and it defaults to `NOT_REQUIRED`."

    Design: Difficulty/dual_variant_calc/ownership_variants_diverge_on_holdco_chain
    """
    root = fx.create_control_person(
        api,
        licensee["id"],
        full_name="Northgate HoldCo",
        role_title="ENTITY_HOLDER",
        direct_ownership_bps=6000,
    )

    child = fx.create_control_person(
        api,
        licensee["id"],
        full_name="Priya Raman",
        role_title="ENTITY_HOLDER",
        direct_ownership_bps=4000,
        parent_control_person_id=root["id"],
    )

    # Economic hop: floor(4000 * 6000 / 10000) = floor(2400) = 2400.
    assert child["effective_ownership_bps"] == 2_400
    # Attribution: the parent's own direct stake 6000 >= 2500, so the row's
    # 4000 is attributed at full value and is not diluted at all.
    assert child["attributed_ownership_bps"] == 4_000

    # 4000 >= 2500 on the attributed figure, so CONTROL — even though the
    # economic 2400 sits below the threshold and ENTITY_HOLDER is no officer.
    assert child["control_determination"] == "CONTROL"
    assert child["background_check_status"] == "PENDING"


def test_root_link_agrees_across_variants_and_pins_a_zero_quorum(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """A direct holder reads the same under both variants, and with no licences no approvals are owed.

    PRD 3.2: "The **economic** figure, `effective_ownership_bps`, multiplies the chain: for a direct holder it is simply `direct_ownership_bps`; otherwise it is the row's `direct_ownership_bps` multiplied by the parent's `effective_ownership_bps`, divided by 10000 with the result rounded down at that hop."
    PRD 3.2: "The **attributed** figure, `attributed_ownership_bps`, applies the regulatory attribution convention instead: for a direct holder it is again `direct_ownership_bps`; if the parent's own `direct_ownership_bps` is at least 2500 basis points, the parent link is treated as controlling and the row's stake is attributed at full value, so `attributed_ownership_bps` equals the row's `direct_ownership_bps` unchanged; only when the parent's direct stake is below 2500 basis points does the row's stake get diluted, becoming the row's `direct_ownership_bps` multiplied by the parent's `attributed_ownership_bps` divided by 10000 and rounded down."
    PRD 3.2: "`change_of_control_status` is set to `PENDING_APPROVAL` when the holder is a control person **and** the licensee's `active_license_count` is greater than zero, and to `NOT_REQUIRED` in every other case; its value set is `NOT_REQUIRED`, `PENDING_APPROVAL`, `APPROVED` and `DENIED`."
    PRD 3.2: "At the same moment the server pins `required_approval_count` to the licensee's `active_license_count` as it stands at creation time — the quorum is frozen then and does not move as licences come and go."
    PRD 3.2: "`approving_jurisdiction_ids` starts as an empty array, `disqualifying_finding` starts false, and the row's own `status` starts at `PROPOSED`, the other values being `SEATED` and `REMOVED`."
    PRD 3.2: "Above the individual holders sits the licensee's `control_chain_status`, an aggregate over the non-`REMOVED` holders whose `control_determination` is `CONTROL`, with values `VERIFIED`, `PENDING_CHECKS` and `BLOCKED` and a default of `VERIFIED`."
    PRD 3.2: "It is recomputed on every control-person creation, every background-check adjudication and every change-of-control decision, by this precedence: `BLOCKED` if any such holder has `background_check_status` of `ADVERSE` or `change_of_control_status` of `DENIED`; otherwise `PENDING_CHECKS` if any such holder has `background_check_status` of `PENDING` or `change_of_control_status` of `PENDING_APPROVAL`; otherwise `VERIFIED`."

    Design: Difficulty/dual_variant_calc/ownership_variants_diverge_on_holdco_chain
    """
    root = fx.create_control_person(
        api,
        licensee["id"],
        full_name="Northgate HoldCo",
        role_title="ENTITY_HOLDER",
        direct_ownership_bps=6000,
    )

    # A direct holder is the one place the two variants must agree: both are
    # simply direct_ownership_bps = 6000, with no hop to multiply or attribute.
    assert root["effective_ownership_bps"] == 6_000
    assert root["attributed_ownership_bps"] == 6_000
    assert root["control_determination"] == "CONTROL"
    assert root["status"] == "PROPOSED"

    # active_license_count is 0 on a licensee with no licences, so no change of
    # control is owed and the frozen quorum is 0.
    assert root["change_of_control_status"] == "NOT_REQUIRED"
    assert root["required_approval_count"] == 0
    assert root["approving_jurisdiction_ids"] == []

    child = fx.create_control_person(
        api,
        licensee["id"],
        full_name="Priya Raman",
        role_title="ENTITY_HOLDER",
        direct_ownership_bps=4000,
        parent_control_person_id=root["id"],
    )
    assert child["change_of_control_status"] == "NOT_REQUIRED"
    assert child["required_approval_count"] == 0

    # Both holders are CONTROL with a PENDING background check, and neither is
    # ADVERSE or DENIED, so the aggregate lands on PENDING_CHECKS.
    refreshed = get_success_data(api.get_licensee(licensee["id"], MANAGER_HEADERS))
    assert refreshed["control_chain_status"] == "PENDING_CHECKS"


def test_variants_converge_when_the_parent_direct_stake_is_below_the_threshold(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """Under a non-controlling parent the attributed figure dilutes too and both variants agree.

    PRD 3.2: "The **economic** figure, `effective_ownership_bps`, multiplies the chain: for a direct holder it is simply `direct_ownership_bps`; otherwise it is the row's `direct_ownership_bps` multiplied by the parent's `effective_ownership_bps`, divided by 10000 with the result rounded down at that hop."
    PRD 3.2: "The **attributed** figure, `attributed_ownership_bps`, applies the regulatory attribution convention instead: for a direct holder it is again `direct_ownership_bps`; if the parent's own `direct_ownership_bps` is at least 2500 basis points, the parent link is treated as controlling and the row's stake is attributed at full value, so `attributed_ownership_bps` equals the row's `direct_ownership_bps` unchanged; only when the parent's direct stake is below 2500 basis points does the row's stake get diluted, becoming the row's `direct_ownership_bps` multiplied by the parent's `attributed_ownership_bps` divided by 10000 and rounded down."
    PRD 3.2: "`control_determination` is `CONTROL` when `attributed_ownership_bps` is at least 2500 basis points **or** the holder's `role_title` is one of the four officer titles `CEO`, `CFO`, `COO` or `CCO`; otherwise it is `NON_CONTROL`."
    PRD 3.2: "Exactly 2500 basis points is `CONTROL`; 2499 is `NON_CONTROL`."
    PRD 3.2: "`background_check_status` is set to `PENDING` for a control person and to `NOT_REQUIRED` otherwise; its full value set is `NOT_REQUIRED`, `PENDING`, `CLEARED` and `ADVERSE`, and it defaults to `NOT_REQUIRED`."
    PRD 3.2: "Above the individual holders sits the licensee's `control_chain_status`, an aggregate over the non-`REMOVED` holders whose `control_determination` is `CONTROL`, with values `VERIFIED`, `PENDING_CHECKS` and `BLOCKED` and a default of `VERIFIED`."

    Design: Difficulty/dual_variant_calc/ownership_variants_diverge_on_holdco_chain
    """
    root = fx.create_control_person(
        api,
        licensee["id"],
        full_name="Southbank Nominees",
        role_title="ENTITY_HOLDER",
        direct_ownership_bps=2000,
    )

    # A direct holder: both figures are the raw 2000, and 2000 < 2500 with a
    # non-officer title, so NON_CONTROL and no background check is required.
    assert root["effective_ownership_bps"] == 2_000
    assert root["attributed_ownership_bps"] == 2_000
    assert root["control_determination"] == "NON_CONTROL"
    assert root["background_check_status"] == "NOT_REQUIRED"

    child = fx.create_control_person(
        api,
        licensee["id"],
        full_name="Priya Raman",
        role_title="ENTITY_HOLDER",
        direct_ownership_bps=4000,
        parent_control_person_id=root["id"],
    )

    # Economic hop: floor(4000 * 2000 / 10000) = 800.
    assert child["effective_ownership_bps"] == 800
    # The parent's direct stake 2000 is below 2500, so attribution dilutes as
    # well: floor(4000 * 2000 / 10000) = 800. The two variants coincide here.
    assert child["attributed_ownership_bps"] == 800
    assert child["effective_ownership_bps"] == child["attributed_ownership_bps"]

    # 800 < 2500 on the attributed figure, so NON_CONTROL.
    assert child["control_determination"] == "NON_CONTROL"
    assert child["background_check_status"] == "NOT_REQUIRED"

    # No non-REMOVED holder is CONTROL at all, so the aggregate stays VERIFIED.
    refreshed = get_success_data(api.get_licensee(licensee["id"], MANAGER_HEADERS))
    assert refreshed["control_chain_status"] == "VERIFIED"
