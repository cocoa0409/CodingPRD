"""Arithmetic contracts: the obligation aggregate, the two coverage variants,
the surety bond ladder, the renewal fee and the annual assessment invoice.

Every expected integer below is computed by hand from PRD sections 3.4, 3.5 and
3.7 and written out as a literal, with the arithmetic shown in a comment beside
it. No formula is re-implemented in Python.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import MoneyTransmitterApiClient
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_RENEWAL_FEE_MISMATCH
from test_helpers.test_users import MANAGER_HEADERS

# ---------------------------------------------------------------------------
# Local setup helpers (no helper for a bespoke jurisdiction exists upstream)
# ---------------------------------------------------------------------------


def _active_license_for(
    api: MoneyTransmitterApiClient,
    licensee_id: str,
    jurisdiction_id: str,
    **application_overrides,
) -> dict:
    """Carry one application to an authorised licence in a bespoke state.

    Drives only PRD-declared endpoints: open, submit, START_REVIEW, APPROVE,
    discover the minted licence by ``application_id``, then post the bond at the
    licence's own ``bond_requirement_cents``.
    """
    application = fx.create_application(
        api, licensee_id, jurisdiction_id, **application_overrides
    )
    fx.submit_application(api, application["id"])
    fx.review_application(api, application["id"], jurisdiction_id, "START_REVIEW")
    fx.review_application(api, application["id"], jurisdiction_id, "APPROVE")
    license_row = fx.find_license_by_application(api, application["id"])
    return fx.post_bond(api, license_row["id"])


def _submit_for_bond(
    api: MoneyTransmitterApiClient,
    licensee_id: str,
    jurisdiction_id: str,
    **application_overrides,
) -> dict:
    """Open and submit one application, returning the submitted application."""
    application = fx.create_application(
        api, licensee_id, jurisdiction_id, **application_overrides
    )
    return fx.submit_application(api, application["id"])


# ---------------------------------------------------------------------------
# The obligation aggregate input set
# ---------------------------------------------------------------------------


def test_obligation_aggregate_keeps_a_bond_suspended_licence(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A licence suspended by a bond-cancellation notice still contributes its obligations.

    PRD 3.4: "The aggregate itself is the exact sum, in integer cents with no rounding, of `outstanding_obligations_cents` over the licensee's licences whose `license_status` is `PENDING_BOND`, `ACTIVE`, `SUSPENDED` or `SURRENDER_REQUESTED`."
    PRD 3.4: "On acceptance, `bond_status` becomes `CANCELLATION_NOTICED`, the effective date is stored, and the licence moves `ACTIVE → SUSPENDED`, triggering the licence-suspension cascade of §2.9 in full."
    PRD 2.9: "The licence's `expansion_gate` becomes `BLOCKED` and the licensee's `active_license_count` is reduced by one."

    Design: Corner/calculations/obligation_aggregate_still_counts_a_suspended_license
    """
    fx.adjust_obligations(api, active_license.license_id, 3_000_000, memo="Settlement float")

    # The bond-cancellation effective date sits sixty days past the seed clock of
    # 2026-08-01T00:00:00Z, comfortably beyond the thirty-day notice floor.
    suspended = validate_success(
        api.file_bond_cancellation_notice(
            active_license.license_id,
            F.bond_cancellation_payload("2026-09-30T00:00:00Z"),
            MANAGER_HEADERS,
        )
    )
    assert suspended["license_status"] == "SUSPENDED"
    assert suspended["bond_status"] == "CANCELLATION_NOTICED"
    assert suspended["expansion_gate"] == "BLOCKED"
    # The licence keeps its own balance across the suspension.
    assert suspended["outstanding_obligations_cents"] == 3_000_000

    summary = fx.get_coverage_summary(api, active_license.licensee_id)
    # SUSPENDED is inside the aggregate set, so the sum is still 3000000 + nothing.
    assert summary["obligations_cents"] == 3_000_000

    licensee = fx.get_licensee(api, active_license.licensee_id)
    assert licensee["aggregate_outstanding_obligations_cents"] == 3_000_000
    # active_license_count tracks ACTIVE licences only, a strictly narrower set.
    assert licensee["active_license_count"] == 0


# ---------------------------------------------------------------------------
# The ELIGIBLE_MARKET haircuts
# ---------------------------------------------------------------------------


def test_coverage_applies_the_declared_per_class_haircuts(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """CASH is untouched while US_TREASURY loses 200 bps, floored at the per-holding step.

    PRD 3.7: "The `BOOK_VALUE` variant is the generous one: `book_investment_value_cents` is simply the sum of `book_value_cents` over the candidate set."
    PRD 3.7: "Every other holding contributes an adjusted amount equal to its `market_value_cents` multiplied by 10000 minus its class haircut, divided by 10000 and rounded down at that step."
    PRD 3.7: "The haircuts, in basis points, are: `CASH` none, `US_TREASURY` 200, `MONEY_MARKET_FUND` 300, `AGENCY_BOND` 500 and `RECEIVABLE_FROM_DELEGATE` 1000."
    PRD 3.7: "First, the concentration cap is fixed for this licensee as its `aggregate_outstanding_obligations_cents` multiplied by 1000 basis points — ten percent — divided by 10000 and rounded down; that figure is exposed as `concentration_cap_cents`."
    PRD 3.7: "A coverage ratio in basis points is derived from an investment value the same way for both variants: it is exactly 10000 when the licensee's `aggregate_outstanding_obligations_cents` is zero, and otherwise the investment value multiplied by 10000, divided by the obligations, rounded down."

    Design: Corner/calculations/coverage_applies_the_declared_per_class_haircuts
    """
    fx.adjust_obligations(api, active_license.license_id, 4_000_000, memo="Settlement float")
    fx.record_holding(
        api, active_license.licensee_id, "CASH", "First Republic Trust", 1_000_000, 1_000_000
    )
    fx.record_holding(
        api,
        active_license.licensee_id,
        "US_TREASURY",
        "US Treasury Direct",
        1_000_001,
        1_000_001,
    )

    summary = fx.get_coverage_summary(api, active_license.licensee_id)

    assert summary["obligations_cents"] == 4_000_000
    # book = 1000000 + 1000001
    assert summary["book_investment_value_cents"] == 2_000_001
    # floor(2000001 * 10000 / 4000000) = floor(5000.0025) = 5000
    assert summary["book_coverage_ratio_bps"] == 5_000
    # 1000000 * (10000 - 0) / 10000 = 1000000
    # floor(1000001 * (10000 - 200) / 10000) = floor(980000.98) = 980000
    assert summary["eligible_investment_value_cents"] == 1_980_000
    # floor(1980000 * 10000 / 4000000) = 4950
    assert summary["coverage_ratio_bps"] == 4_950
    # floor(4000000 * 1000 / 10000) = 400000
    assert summary["concentration_cap_cents"] == 400_000
    # 4950 is below the 9500 WATCH floor.
    assert summary["coverage_posture"] == "DEFICIENT"


# ---------------------------------------------------------------------------
# Non-permissible and disposed rows
# ---------------------------------------------------------------------------


def test_corporate_debt_is_excluded_from_both_coverage_variants(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """CORPORATE_DEBT is stored but drops out before the variant split, so neither value moves.

    PRD 3.7: "The candidate set for both is the licensee's holdings whose `status` is `HELD` and whose `asset_class` is not among the non-permissible classes — and `CORPORATE_DEBT` is the sole non-permissible class, so corporate debt is excluded from both variants outright, as are all disposed rows."
    PRD 3.7: "The row starts with `status` `HELD`; disposing of it moves it to `DISPOSED`, and only `HELD` rows enter any coverage computation."
    PRD 3.7: "The boundaries are exact: 10000 is `COMPLIANT`, 9999 is `WATCH`, 9500 is `WATCH`, 9499 is `DEFICIENT`."

    Design: Corner/calculations/corporate_debt_is_excluded_from_both_coverage_variants
    """
    fx.adjust_obligations(api, active_license.license_id, 4_000_000, memo="Settlement float")
    fx.record_holding(
        api, active_license.licensee_id, "CASH", "First Republic Trust", 4_000_000, 4_000_000
    )

    corporate_debt = fx.record_holding(
        api,
        active_license.licensee_id,
        "CORPORATE_DEBT",
        "Northline Industrials",
        9_000_000,
        9_000_000,
    )
    # The row is persisted and HELD; it is simply not a permissible investment.
    assert corporate_debt["status"] == "HELD"

    summary = fx.get_coverage_summary(api, active_license.licensee_id)
    # Only the CASH row is a candidate: book = 4000000, eligible = 4000000 (no haircut).
    assert summary["book_investment_value_cents"] == 4_000_000
    assert summary["eligible_investment_value_cents"] == 4_000_000
    # floor(4000000 * 10000 / 4000000) = 10000
    assert summary["coverage_ratio_bps"] == 10_000
    assert summary["book_coverage_ratio_bps"] == 10_000
    assert summary["coverage_posture"] == "COMPLIANT"


def test_disposing_a_holding_removes_it_from_both_variants(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Disposal takes the row out of the HELD candidate set of both variants at once.

    PRD 3.7: "The row starts with `status` `HELD`; disposing of it moves it to `DISPOSED`, and only `HELD` rows enter any coverage computation."
    PRD 3.7: "Both recording a holding and disposing of one recompute the licensee's coverage figures and posture and bump `Licensee.version`."
    PRD 3.7: "A coverage ratio in basis points is derived from an investment value the same way for both variants: it is exactly 10000 when the licensee's `aggregate_outstanding_obligations_cents` is zero, and otherwise the investment value multiplied by 10000, divided by the obligations, rounded down."

    Design: Corner/calculations/disposing_a_holding_removes_it_from_both_variants
    """
    fx.adjust_obligations(api, active_license.license_id, 6_000_000, memo="Settlement float")
    fx.record_holding(
        api, active_license.licensee_id, "CASH", "First Republic Trust", 4_000_000, 4_000_000
    )
    second = fx.record_holding(
        api, active_license.licensee_id, "CASH", "Second Federal Trust", 2_000_000, 2_000_000
    )

    before = fx.get_coverage_summary(api, active_license.licensee_id)
    # 4000000 + 2000000 CASH against 6000000 of obligations: floor(6000000*10000/6000000)
    assert before["eligible_investment_value_cents"] == 6_000_000
    assert before["coverage_ratio_bps"] == 10_000
    assert before["coverage_posture"] == "COMPLIANT"

    disposed = fx.dispose_holding(api, second["id"])
    assert disposed["status"] == "DISPOSED"

    after = fx.get_coverage_summary(api, active_license.licensee_id)
    assert after["book_investment_value_cents"] == 4_000_000
    assert after["eligible_investment_value_cents"] == 4_000_000
    # floor(4000000 * 10000 / 6000000) = floor(6666.66...) = 6666
    assert after["coverage_ratio_bps"] == 6_666
    assert after["coverage_posture"] == "DEFICIENT"


# ---------------------------------------------------------------------------
# Receivable ageing
# ---------------------------------------------------------------------------


def test_delegate_receivable_older_than_five_days_drops_out_of_eligible_only(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """An age-5 receivable survives with a 1000 bps haircut; an age-6 one is skipped entirely.

    PRD 3.7: "A `RECEIVABLE_FROM_DELEGATE` holding whose `age_days` exceeds five is skipped entirely: a receivable older than five days is not a permissible investment at all."
    PRD 3.7: "The haircuts, in basis points, are: `CASH` none, `US_TREASURY` 200, `MONEY_MARKET_FUND` 300, `AGENCY_BOND` 500 and `RECEIVABLE_FROM_DELEGATE` 1000."
    PRD 3.7: "No haircut is applied, no receivable is aged out, and no counterparty concentration cap is imposed."
    PRD 3.7: "A licensee-level coverage read exposes both variants side by side over identical holdings — `obligations_cents`, `book_investment_value_cents`, `book_coverage_ratio_bps`, `eligible_investment_value_cents`, `coverage_ratio_bps`, `concentration_cap_cents`, `coverage_posture` and `consecutive_failed_test_count` — so that the divergence is observable in a single response."

    Design: Corner/calculations/delegate_receivable_older_than_five_days_drops_out_of_eligible_only
    """
    fx.adjust_obligations(api, active_license.license_id, 10_000_000, memo="Settlement float")
    fx.record_holding(
        api, active_license.licensee_id, "CASH", "First Republic Trust", 5_000_000, 5_000_000
    )
    fx.record_holding(
        api,
        active_license.licensee_id,
        "RECEIVABLE_FROM_DELEGATE",
        "Sunrise Checks Inc",
        1_000_000,
        1_000_000,
        age_days=5,
    )
    fx.record_holding(
        api,
        active_license.licensee_id,
        "RECEIVABLE_FROM_DELEGATE",
        "Harbor Checks LLC",
        1_000_000,
        1_000_000,
        age_days=6,
    )

    summary = fx.get_coverage_summary(api, active_license.licensee_id)

    # book = 5000000 + 1000000 + 1000000; the ageing test never touches book value.
    assert summary["book_investment_value_cents"] == 7_000_000
    # floor(7000000 * 10000 / 10000000) = 7000
    assert summary["book_coverage_ratio_bps"] == 7_000
    # 5000000 CASH + floor(1000000 * (10000 - 1000) / 10000) = 5000000 + 900000
    # and the age-6 receivable contributes nothing at all.
    assert summary["eligible_investment_value_cents"] == 5_900_000
    # floor(5900000 * 10000 / 10000000) = 5900
    assert summary["coverage_ratio_bps"] == 5_900
    # floor(10000000 * 1000 / 10000) = 1000000, and the 900000 group sits under it.
    assert summary["concentration_cap_cents"] == 1_000_000
    assert summary["coverage_posture"] == "DEFICIENT"


def test_book_value_test_snapshots_the_ungroomed_holding_set(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A BOOK_VALUE test freezes the full holding set, ageing and haircuts ignored.

    PRD 3.7: "The `BOOK_VALUE` variant is the generous one: `book_investment_value_cents` is simply the sum of `book_value_cents` over the candidate set."
    PRD 3.7: "No haircut is applied, no receivable is aged out, and no counterparty concentration cap is imposed."
    PRD 3.7: "`obligations_cents` snapshots the licensee's `aggregate_outstanding_obligations_cents`; `investment_value_cents` snapshots the permissible investment value computed under this row's own `method`; `coverage_ratio_bps` is that value multiplied by 10000 divided by `obligations_cents` and rounded down, or exactly 10000 when `obligations_cents` is zero; `shortfall_cents` is `obligations_cents` minus `investment_value_cents`, or zero when that difference would be negative — never a negative number; and `result` becomes `PASS` when `coverage_ratio_bps` is at least 10000 and `SHORTFALL` otherwise, having been null until preparation."

    Design: Corner/calculations/delegate_receivable_older_than_five_days_drops_out_of_eligible_only
    """
    fx.adjust_obligations(api, active_license.license_id, 10_000_000, memo="Settlement float")
    fx.record_holding(
        api, active_license.licensee_id, "CASH", "First Republic Trust", 5_000_000, 5_000_000
    )
    fx.record_holding(
        api,
        active_license.licensee_id,
        "RECEIVABLE_FROM_DELEGATE",
        "Sunrise Checks Inc",
        1_000_000,
        1_000_000,
        age_days=5,
    )
    fx.record_holding(
        api,
        active_license.licensee_id,
        "RECEIVABLE_FROM_DELEGATE",
        "Harbor Checks LLC",
        1_000_000,
        1_000_000,
        age_days=6,
    )

    test_row = fx.open_investment_test(api, active_license.licensee_id, "BOOK_VALUE")
    prepared = fx.prepare_investment_test(api, test_row["id"])

    assert prepared["status"] == "PREPARED"
    assert prepared["obligations_cents"] == 10_000_000
    # Both receivables count in full under BOOK_VALUE: 5000000 + 1000000 + 1000000
    assert prepared["investment_value_cents"] == 7_000_000
    # floor(7000000 * 10000 / 10000000) = 7000
    assert prepared["coverage_ratio_bps"] == 7_000
    # 10000000 - 7000000
    assert prepared["shortfall_cents"] == 3_000_000
    assert prepared["result"] == "SHORTFALL"


# ---------------------------------------------------------------------------
# The concentration cap
# ---------------------------------------------------------------------------


def test_concentration_cap_limits_one_counterparty_to_ten_percent(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Two AGENCY_BOND rows from one counterparty are haircut, then capped as a single group.

    PRD 3.7: "First, the concentration cap is fixed for this licensee as its `aggregate_outstanding_obligations_cents` multiplied by 1000 basis points — ten percent — divided by 10000 and rounded down; that figure is exposed as `concentration_cap_cents`."
    PRD 3.7: "Holdings in the concentration-capped classes — `AGENCY_BOND`, `MONEY_MARKET_FUND` and `RECEIVABLE_FROM_DELEGATE` — accumulate into a running total per `counterparty_name`."
    PRD 3.7: "Finally, `eligible_investment_value_cents` is the uncapped total plus, for each counterparty group, the lesser of that group's running total and the concentration cap."
    PRD 3.7: "The order is normative: haircut each holding first, then group by counterparty, then cap each group, then take one final sum."
    PRD 3.7: "No haircut is applied, no receivable is aged out, and no counterparty concentration cap is imposed."

    Design: Corner/calculations/concentration_cap_limits_one_counterparty_to_ten_percent
    """
    fx.adjust_obligations(api, active_license.license_id, 10_000_000, memo="Settlement float")
    for _ in range(2):
        fx.record_holding(
            api,
            active_license.licensee_id,
            "AGENCY_BOND",
            "Atlas Agency Desk",
            5_000_000,
            5_000_000,
        )

    summary = fx.get_coverage_summary(api, active_license.licensee_id)

    # floor(10000000 * 1000 / 10000) = 1000000
    assert summary["concentration_cap_cents"] == 1_000_000
    # Each row haircuts to floor(5000000 * (10000 - 500) / 10000) = 4750000; the
    # Atlas group totals 9500000 and is then clipped to min(9500000, 1000000).
    assert summary["eligible_investment_value_cents"] == 1_000_000
    # floor(1000000 * 10000 / 10000000) = 1000
    assert summary["coverage_ratio_bps"] == 1_000
    # BOOK_VALUE ignores both the haircut and the cap: 5000000 + 5000000
    assert summary["book_investment_value_cents"] == 10_000_000
    # floor(10000000 * 10000 / 10000000) = 10000
    assert summary["book_coverage_ratio_bps"] == 10_000
    assert summary["coverage_posture"] == "DEFICIENT"


def test_concentration_cap_is_taken_per_counterparty_group(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Each counterparty group is capped on its own, and a group under the cap keeps its total.

    PRD 3.7: "Holdings in the concentration-capped classes — `AGENCY_BOND`, `MONEY_MARKET_FUND` and `RECEIVABLE_FROM_DELEGATE` — accumulate into a running total per `counterparty_name`."
    PRD 3.7: "Finally, `eligible_investment_value_cents` is the uncapped total plus, for each counterparty group, the lesser of that group's running total and the concentration cap."
    PRD 3.7: "Capping before the haircut, or summing the groups before capping them, yields a different number and is wrong."

    Design: Corner/calculations/concentration_cap_limits_one_counterparty_to_ten_percent
    """
    fx.adjust_obligations(api, active_license.license_id, 10_000_000, memo="Settlement float")
    for _ in range(2):
        fx.record_holding(
            api,
            active_license.licensee_id,
            "AGENCY_BOND",
            "Atlas Agency Desk",
            5_000_000,
            5_000_000,
        )
    fx.record_holding(
        api,
        active_license.licensee_id,
        "AGENCY_BOND",
        "Beacon Agency Desk",
        1_000_000,
        1_000_000,
    )

    summary = fx.get_coverage_summary(api, active_license.licensee_id)

    # floor(10000000 * 1000 / 10000) = 1000000
    assert summary["concentration_cap_cents"] == 1_000_000
    # Atlas group: 4750000 + 4750000 = 9500000 -> min(9500000, 1000000) = 1000000.
    # Beacon group: floor(1000000 * 9500 / 10000) = 950000 -> min(950000, 1000000) = 950000.
    # 1000000 + 950000
    assert summary["eligible_investment_value_cents"] == 1_950_000
    # floor(1950000 * 10000 / 10000000) = 1950
    assert summary["coverage_ratio_bps"] == 1_950
    # book = 5000000 + 5000000 + 1000000
    assert summary["book_investment_value_cents"] == 11_000_000
    # floor(11000000 * 10000 / 10000000) = 11000
    assert summary["book_coverage_ratio_bps"] == 11_000


# ---------------------------------------------------------------------------
# The WATCH floor
# ---------------------------------------------------------------------------


def test_coverage_posture_splits_at_the_watch_floor_on_a_single_cent(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """One extra cent of obligations floors the ratio from 9500 to 9499 and flips WATCH to DEFICIENT.

    PRD 3.7: "A coverage ratio in basis points is derived from an investment value the same way for both variants: it is exactly 10000 when the licensee's `aggregate_outstanding_obligations_cents` is zero, and otherwise the investment value multiplied by 10000, divided by the obligations, rounded down."
    PRD 3.7: "From it, and from `consecutive_failed_test_count`, the licensee's `coverage_posture` is determined by a strictly ordered test: the posture is `FROZEN` if `consecutive_failed_test_count` is at least 2, regardless of the ratio; otherwise `COMPLIANT` if `coverage_ratio_bps` is at least 10000; otherwise `WATCH` if `coverage_ratio_bps` is at least 9500; otherwise `DEFICIENT`."
    PRD 3.7: "The boundaries are exact: 10000 is `COMPLIANT`, 9999 is `WATCH`, 9500 is `WATCH`, 9499 is `DEFICIENT`."
    PRD 2.8: "It is `OPEN` exactly when all five of the following hold: `license_status` is `ACTIVE`, `bond_status` is `POSTED`, `reporting_status` is `CURRENT`, `exam_findings_open` is false, and the owning licensee's `coverage_posture` is either `COMPLIANT` or `WATCH`."
    PRD 3.4: "The adjustment then re-derives, in order: the licensee's `aggregate_outstanding_obligations_cents`, both permissible-investment values, `coverage_ratio_bps` and `coverage_posture`."

    Design: Corner/calculations/coverage_posture_splits_at_the_watch_floor_on_a_single_cent
    """
    fx.record_holding(
        api, active_license.licensee_id, "CASH", "First Republic Trust", 9_500_000, 9_500_000
    )
    fx.adjust_obligations(api, active_license.license_id, 10_000_000, memo="Settlement float")

    at_floor = fx.get_coverage_summary(api, active_license.licensee_id)
    assert at_floor["obligations_cents"] == 10_000_000
    assert at_floor["eligible_investment_value_cents"] == 9_500_000
    # floor(9500000 * 10000 / 10000000) = 9500 exactly, which is inclusive of WATCH
    assert at_floor["coverage_ratio_bps"] == 9_500
    assert at_floor["coverage_posture"] == "WATCH"

    at_floor_license = fx.get_license(api, active_license.license_id)
    assert at_floor_license["expansion_gate"] == "OPEN"

    fx.adjust_obligations(api, active_license.license_id, 1, memo="One cent more float")

    below_floor = fx.get_coverage_summary(api, active_license.licensee_id)
    assert below_floor["obligations_cents"] == 10_000_001
    # floor(9500000 * 10000 / 10000001) = floor(9499.99905...) = 9499
    assert below_floor["coverage_ratio_bps"] == 9_499
    assert below_floor["coverage_posture"] == "DEFICIENT"

    licensee = fx.get_licensee(api, active_license.licensee_id)
    assert licensee["aggregate_outstanding_obligations_cents"] == 10_000_001
    assert licensee["coverage_ratio_bps"] == 9_499

    below_floor_license = fx.get_license(api, active_license.license_id)
    assert below_floor_license["expansion_gate"] == "BLOCKED"


# ---------------------------------------------------------------------------
# The surety bond volume tiers
# ---------------------------------------------------------------------------


def test_bond_volume_tier_one_holds_at_exactly_one_billion_cents(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """A volume of exactly one billion cents is still tier one; one cent more is tier two.

    PRD 3.4: "Step one selects a tier bond from the relevant volume figure: the application's `projected_annual_volume_cents` in an application context, or the licence's `annual_volume_cents` in a licence context."
    PRD 3.4: "A volume of at most one billion cents — that is, ten million dollars — is tier one at a tier bond of two and a half million cents; a volume above one billion cents but at most ten billion cents is tier two at ten million cents; a volume above ten billion cents is tier three at twenty-five million cents."
    PRD 3.4: "Step two takes the greater of the jurisdiction's `base_bond_cents` and the sum of the tier bond plus the delegate count multiplied by the jurisdiction's `per_delegate_bond_cents`; the delegate count is zero in an application context and the licence's `active_delegate_count` otherwise."
    PRD 3.3: "On success the application moves `DRAFT → SUBMITTED`, `submitted_at` is stamped from the logical clock, `required_net_worth_cents` is pinned as a copy of the jurisdiction's `min_net_worth_cents`, and `required_bond_cents` is pinned to the surety bond figure computed as described in §3.4, using the jurisdiction configuration, the submitted `projected_annual_volume_cents`, the declared `license_class`, and a delegate count of zero — an applicant has no active delegates yet by definition."

    Design: Corner/calculations/bond_volume_tier_boundary_holds_the_low_tier_at_exactly_the_cap
    """
    # Both states carry base_bond_cents 1000000, well under either tier bond, so
    # the statutory floor of step two cannot mask the tier selection.
    nevada = fx.create_jurisdiction(api, C.NV_CONFIG)
    arizona = fx.create_jurisdiction(
        api, C.NV_CONFIG, state_code="AZ", name="Arizona DIFI"
    )

    at_boundary = _submit_for_bond(
        api,
        licensee["id"],
        nevada["id"],
        license_class="MONEY_TRANSMISSION",
        projected_annual_volume_cents=1_000_000_000,
    )
    above_boundary = _submit_for_bond(
        api,
        licensee["id"],
        arizona["id"],
        license_class="MONEY_TRANSMISSION",
        projected_annual_volume_cents=1_000_000_001,
    )

    assert at_boundary["status"] == "SUBMITTED"
    assert above_boundary["status"] == "SUBMITTED"
    # tier 1 = 2500000; max(1000000, 2500000 + 0) = 2500000; * 10000/10000; cap 20000000
    assert at_boundary["required_bond_cents"] == 2_500_000
    # tier 2 = 10000000; max(1000000, 10000000 + 0) = 10000000; * 10000/10000; cap 20000000
    assert above_boundary["required_bond_cents"] == 10_000_000
    assert at_boundary["required_net_worth_cents"] == 10_000_000
    assert above_boundary["required_net_worth_cents"] == 10_000_000


def test_bond_volume_tier_two_holds_at_exactly_ten_billion_cents(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """A volume of exactly ten billion cents is still tier two; one cent more is tier three.

    PRD 3.4: "A volume of at most one billion cents — that is, ten million dollars — is tier one at a tier bond of two and a half million cents; a volume above one billion cents but at most ten billion cents is tier two at ten million cents; a volume above ten billion cents is tier three at twenty-five million cents."
    PRD 3.4: "Step four takes the lesser of that result and the jurisdiction's `bond_cap_cents`."

    Design: Corner/calculations/bond_volume_tier_boundary_holds_the_low_tier_at_exactly_the_cap
    """
    # bond_cap_cents 60000000 keeps the cap of step four clear of the tier-three
    # figure, and base_bond_cents 1000000 keeps the statutory floor clear too.
    nevada = fx.create_jurisdiction(api, C.NV_CONFIG, bond_cap_cents=60_000_000)
    arizona = fx.create_jurisdiction(
        api,
        C.NV_CONFIG,
        state_code="AZ",
        name="Arizona DIFI",
        bond_cap_cents=60_000_000,
    )

    at_boundary = _submit_for_bond(
        api,
        licensee["id"],
        nevada["id"],
        license_class="MONEY_TRANSMISSION",
        projected_annual_volume_cents=10_000_000_000,
    )
    above_boundary = _submit_for_bond(
        api,
        licensee["id"],
        arizona["id"],
        license_class="MONEY_TRANSMISSION",
        projected_annual_volume_cents=10_000_000_001,
    )

    # tier 2 = 10000000; max(1000000, 10000000) = 10000000; * 10000/10000; cap 60000000
    assert at_boundary["required_bond_cents"] == 10_000_000
    # tier 3 = 25000000; max(1000000, 25000000) = 25000000; * 10000/10000; cap 60000000
    assert above_boundary["required_bond_cents"] == 25_000_000


def test_virtual_currency_bond_is_clipped_by_the_jurisdiction_cap(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """The class multiplier runs before the cap, so 37500000 is clipped to a 30000000 ceiling.

    PRD 3.4: "Step three multiplies that figure by the class multiplier for the `license_class` and divides by 10000, rounding down: `MONEY_TRANSMISSION` carries a multiplier of 10000 basis points and therefore leaves the figure unchanged, `PAYMENT_INSTRUMENTS` carries 12000 basis points, and `VIRTUAL_CURRENCY` carries 15000 basis points."
    PRD 3.4: "Step four takes the lesser of that result and the jurisdiction's `bond_cap_cents`."
    PRD 3.4: "Applying the statutory floor after the multiplier, or the cap before it, produces a different figure and is wrong."
    PRD 3.4: "A volume of at most one billion cents — that is, ten million dollars — is tier one at a tier bond of two and a half million cents; a volume above one billion cents but at most ten billion cents is tier two at ten million cents; a volume above ten billion cents is tier three at twenty-five million cents."

    Design: Corner/calculations/virtual_currency_bond_is_clipped_by_the_jurisdiction_cap
    """
    new_york = fx.create_jurisdiction(
        api,
        C.CA_CONFIG,
        state_code="NY",
        name="New York DFS",
        min_net_worth_cents=20_000_000,
        base_bond_cents=20_000_000,
        per_delegate_bond_cents=500_000,
        bond_cap_cents=30_000_000,
        response_window_days=20,
        renewal_fee_cents=1_200_000,
        assessment_rate_bps=60,
        call_report_frequency="ANNUAL",
        participates_in_multistate=False,
    )

    submitted = _submit_for_bond(
        api,
        licensee["id"],
        new_york["id"],
        license_class="VIRTUAL_CURRENCY",
        projected_annual_volume_cents=10_000_000_001,
        new_product_narrative="Custodial stablecoin transfers.",
    )

    assert submitted["status"] == "SUBMITTED"
    # tier 3 = 25000000 (volume above ten billion cents);
    # max(20000000, 25000000 + 0) = 25000000;
    # floor(25000000 * 15000 / 10000) = 37500000;
    # min(37500000, 30000000) = 30000000. Capping first would have left 25000000
    # and then multiplied back up to 37500000.
    assert submitted["required_bond_cents"] == 30_000_000
    assert submitted["required_net_worth_cents"] == 20_000_000


def test_payment_instruments_multiplier_floors_the_adjusted_bond(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """The 12000 bps class multiplier rounds down, so 3000003.6 lands on 3000003.

    PRD 3.4: "Step two takes the greater of the jurisdiction's `base_bond_cents` and the sum of the tier bond plus the delegate count multiplied by the jurisdiction's `per_delegate_bond_cents`; the delegate count is zero in an application context and the licence's `active_delegate_count` otherwise."
    PRD 3.4: "Step three multiplies that figure by the class multiplier for the `license_class` and divides by 10000, rounding down: `MONEY_TRANSMISSION` carries a multiplier of 10000 basis points and therefore leaves the figure unchanged, `PAYMENT_INSTRUMENTS` carries 12000 basis points, and `VIRTUAL_CURRENCY` carries 15000 basis points."
    PRD 3.4: "Step four takes the lesser of that result and the jurisdiction's `bond_cap_cents`."

    Design: Corner/calculations/payment_instruments_multiplier_floors_the_adjusted_bond
    """
    colorado = fx.create_jurisdiction(
        api,
        C.NV_CONFIG,
        state_code="CO",
        name="Colorado DOB",
        base_bond_cents=2_500_003,
        bond_cap_cents=20_000_000,
        renewal_fee_cents=300_000,
        assessment_rate_bps=20,
    )

    submitted = _submit_for_bond(
        api,
        licensee["id"],
        colorado["id"],
        license_class="PAYMENT_INSTRUMENTS",
        projected_annual_volume_cents=90_000_000,
        new_product_narrative="Money orders sold through retail agents.",
    )

    # tier 1 = 2500000 (volume at most one billion cents);
    # max(2500003, 2500000 + 0) = 2500003;
    # floor(2500003 * 12000 / 10000) = floor(3000003.6) = 3000003;
    # min(3000003, 20000000) = 3000003, so the cap step is a no-op here.
    assert submitted["required_bond_cents"] == 3_000_003


# ---------------------------------------------------------------------------
# The renewal fee
# ---------------------------------------------------------------------------


def test_renewal_assessment_rounds_half_up_on_an_exact_half_cent(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """A subtotal of 99990 at 500 bps gives exactly 4999.5, which rounds half up to 5000.

    PRD 3.5: "First the subtotal: the jurisdiction's `renewal_fee_cents` plus the licence's current `active_delegate_count` multiplied by twenty-five thousand cents — two hundred and fifty dollars per active delegate."
    PRD 3.5: "Second, a tier rate is selected **from that pre-assessment subtotal and never from the final total**: 500 basis points when the subtotal is at most one hundred thousand cents, 350 basis points when the subtotal is above one hundred thousand cents but at most two hundred and fifty thousand cents, and 200 basis points when the subtotal exceeds two hundred and fifty thousand cents."
    PRD 3.5: "Third, the assessment is the subtotal multiplied by the tier rate divided by 10000, rounded half up to whole cents."
    PRD 3.5: "Fourth, the total is the subtotal plus that assessment."
    PRD 3.5: "On a match, `renewal_status` moves from `NOT_RENEWED` to `RENEWED`, `renewal_year` records the year renewed, `renewal_total_fee_cents` records the computed total, and the licence's `version` is bumped."

    Design: Corner/calculations/renewal_assessment_rounds_half_up_on_an_exact_half_cent
    """
    arizona = fx.create_jurisdiction(
        api, C.NV_CONFIG, state_code="AZ", name="Arizona DIFI", renewal_fee_cents=99_990
    )
    license_row = _active_license_for(api, licensee["id"], arizona["id"])
    assert license_row["license_status"] == "ACTIVE"
    assert license_row["reporting_status"] == "CURRENT"
    assert license_row["active_delegate_count"] == 0

    # subtotal = 99990 + 0 * 25000 = 99990; the subtotal is at most 100000 so the
    # tier is 500 bps; assessment = round_half_up(99990 * 500 / 10000)
    #                             = round_half_up(4999.5) = 5000;
    # total = 99990 + 5000 = 104990.
    renewed = validate_success(
        api.renew_license(
            license_row["id"], F.renewal_payload(2027, 104_990), MANAGER_HEADERS
        )
    )

    assert renewed["renewal_total_fee_cents"] == 104_990
    assert renewed["renewal_status"] == "RENEWED"
    assert renewed["renewal_year"] == 2027


def test_renewal_rejects_the_floored_assessment_total(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """Paying 104989 — the total a floored assessment would produce — is a fee mismatch.

    PRD 3.5: "Third, the assessment is the subtotal multiplied by the tier rate divided by 10000, rounded half up to whole cents."
    PRD 3.5: "Fourth, the total is the subtotal plus that assessment."
    PRD 3.5: "The supplied `payment_amount_cents` must equal that total exactly; any other figure is rejected with `ERR_RENEWAL_FEE_MISMATCH` (HTTP 422)."

    Design: Corner/calculations/renewal_assessment_rounds_half_up_on_an_exact_half_cent
    """
    arizona = fx.create_jurisdiction(
        api, C.NV_CONFIG, state_code="AZ", name="Arizona DIFI", renewal_fee_cents=99_990
    )
    license_row = _active_license_for(api, licensee["id"], arizona["id"])

    # A floor at step three would give 4999 and a total of 99990 + 4999 = 104989.
    validate_error(
        api.renew_license(
            license_row["id"], F.renewal_payload(2027, 104_989), MANAGER_HEADERS
        ),
        ERR_RENEWAL_FEE_MISMATCH,
    )

    unchanged = fx.get_license(api, license_row["id"])
    assert unchanged["renewal_status"] == "NOT_RENEWED"


# ---------------------------------------------------------------------------
# The annual assessment invoice
# ---------------------------------------------------------------------------


def test_assessment_invoice_counts_only_active_license_lines(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """A SUSPENDED licence still owes obligations but produces no invoice line.

    PRD 3.5: "Only licences whose `license_status` is `ACTIVE` produce a line; `PENDING_BOND`, `SUSPENDED`, `SURRENDER_REQUESTED`, `SURRENDERED` and `REVOKED` licences contribute nothing at all."
    PRD 3.5: "Lines are taken in `created_at` ascending order, which affects no value but is pinned for reproducibility, and `line_item_count` reports how many there were."
    PRD 3.5: "Each line's raw amount is that licence's `outstanding_obligations_cents` multiplied by its jurisdiction's `assessment_rate_bps` divided by 10000, kept exact in cents; `unrounded_sum_cents` reports the sum of those exact raw amounts."
    PRD 3.5: "Each line is then rounded to a whole dollar — divide the raw cents by one hundred, round half up, and multiply by one hundred again — and `annual_assessment_total_cents` is the sum of the rounded lines."
    PRD 3.4: "The aggregate itself is the exact sum, in integer cents with no rounding, of `outstanding_obligations_cents` over the licensee's licences whose `license_status` is `PENDING_BOND`, `ACTIVE`, `SUSPENDED` or `SURRENDER_REQUESTED`."

    Design: Corner/calculations/assessment_invoice_counts_only_active_license_lines
    """
    california = fx.create_jurisdiction(api, C.CA_CONFIG)
    texas = fx.create_jurisdiction(api, C.TX_CONFIG)
    fx.record_holding(api, licensee["id"], "CASH", "First Republic Trust", 9_000_000, 9_000_000)

    ca_license = _active_license_for(api, licensee["id"], california["id"])
    fx.adjust_obligations(api, ca_license["id"], 6_024_000, memo="CA settlement float")

    tx_license = _active_license_for(api, licensee["id"], texas["id"])
    fx.adjust_obligations(api, tx_license["id"], 2_515_000, memo="TX settlement float")
    suspended = validate_success(
        api.file_bond_cancellation_notice(
            tx_license["id"],
            F.bond_cancellation_payload("2026-09-30T00:00:00Z"),
            MANAGER_HEADERS,
        )
    )
    assert suspended["license_status"] == "SUSPENDED"

    invoice = get_success_data(api.get_assessment_summary(licensee["id"], MANAGER_HEADERS))

    # Only the ACTIVE California licence produces a line.
    assert invoice["line_item_count"] == 1
    # 6024000 * 25 / 10000 = 15060 exactly, and that is the whole unrounded sum.
    assert invoice["unrounded_sum_cents"] == 15_060
    # round_half_up(15060 / 100) = round_half_up(150.6) = 151, then 151 * 100
    assert invoice["annual_assessment_total_cents"] == 15_100

    licensee_row = fx.get_licensee(api, licensee["id"])
    # 6024000 + 2515000: the SUSPENDED Texas licence is still inside the
    # obligation aggregate set even though it produced no invoice line.
    assert licensee_row["aggregate_outstanding_obligations_cents"] == 8_539_000
