"""Dual-variant calculations: the same stored state, two selectors, two answers.

Two independent calculation domains are exercised -- the association-level
reserve funding report and the certificate-level payoff quote.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers.assertions import assert_instant_equals
from test_helpers.api_client import ApiClient
from test_helpers.fixtures import (
    add_element,
    add_owner,
    add_unit,
    adopt_budget,
    create_association,
    issue_certificate,
    patch_association,
    request_certificate,
    set_clock,
)
from test_helpers.test_users import MANAGER_HEADERS


# ======================================================================
# Reserve funding adequacy: STRAIGHT_LINE versus COMPONENT
# ======================================================================
def _reserve_association(api: ApiClient):
    """A roster whose two components diverge sharply between the two methods."""
    ctx = create_association(api)
    add_element(
        ctx,
        "roof",
        name="Main Roof",
        element_class="ROOF",
        replacement_cost_cents=10_000_000,
        useful_life_years=25,
        effective_age_years=20,
    )
    add_element(
        ctx,
        "landscape",
        name="Courtyard Landscape",
        element_class="LANDSCAPE",
        replacement_cost_cents=6_000_000,
        useful_life_years=50,
        effective_age_years=5,
    )
    patch_association(ctx, reserve_balance_cents=6_000_000)
    return ctx


def test_reserve_adequacy_straight_line_basis_accrues_with_effective_age(
    api: ApiClient,
) -> None:
    """Straight-line charges every non-decommissioned component something.

    PRD 3.6: "Under the default **straight-line** method -- selected when
    `method` is omitted or is `STRAIGHT_LINE` -- each component's fully-funded
    basis is its `replacement_cost_cents` multiplied by the lesser of
    `effective_age_years` and `useful_life_years`, divided by
    `useful_life_years`, and rounded half up; the target accrues linearly with
    effective age over the whole useful life, so every non-decommissioned
    component contributes something."

    The roof contributes 10000000 * 20 / 25 == 8000000 and the 45-years-of-life
    landscape still contributes 6000000 * 5 / 50 == 600000, for 8600000.

    Design: Difficulty/dual_variant_calc/reserve_adequacy_straight_line_vs_component_flips_association_posture
    """
    ctx = _reserve_association(api)

    report = validate_success(
        api.get_reserve_adequacy(
            ctx.association_id, MANAGER_HEADERS, params={"method": "STRAIGHT_LINE"}
        )
    )

    assert report["fully_funded_cents"] == 8_600_000
    assert report["spendable_cents"] == 6_000_000
    assert report["percent_funded_bp"] == 6976
    assert report["posture"] == "DEFICIENT"


def test_reserve_adequacy_component_basis_zeroes_a_component_beyond_the_horizon(
    api: ApiClient,
) -> None:
    """The component method drops anything further out than thirty years.

    PRD 3.6: "Under the **component** method -- selected when `method` is
    `COMPONENT` -- the component's remaining life is `useful_life_years` minus
    `effective_age_years` but never less than 0, and the fully-funded basis is 0
    when that remaining life exceeds a thirty-year cash-flow horizon and is
    otherwise `replacement_cost_cents` multiplied by thirty minus the remaining
    life, divided by thirty, and rounded half up."

    The landscape's 45 remaining years exceed the horizon so it contributes 0,
    while the roof contributes round_half_up(10000000 * 25 / 30) == 8333333.

    Design: Difficulty/dual_variant_calc/reserve_adequacy_straight_line_vs_component_flips_association_posture
    """
    ctx = _reserve_association(api)

    report = validate_success(
        api.get_reserve_adequacy(
            ctx.association_id, MANAGER_HEADERS, params={"method": "COMPONENT"}
        )
    )

    assert report["fully_funded_cents"] == 8_333_333
    assert report["spendable_cents"] == 6_000_000
    assert report["percent_funded_bp"] == 7200
    assert report["posture"] == "ADEQUATE"


def test_reserve_adequacy_posture_flips_between_methods_without_persisting(
    api: ApiClient,
) -> None:
    """One roster, one balance, opposite postures -- and nothing written.

    PRD 3.6: "Nothing is persisted by this report. Because the two methods
    weight near-term components very differently, the same reserve balance and
    the same component roster can report `ADEQUATE` under one method and
    `DEFICIENT` under the other."

    Design: Difficulty/dual_variant_calc/reserve_adequacy_straight_line_vs_component_flips_association_posture
    """
    ctx = _reserve_association(api)
    version_before = ctx.association_version()

    straight_line = validate_success(
        api.get_reserve_adequacy(
            ctx.association_id, MANAGER_HEADERS, params={"method": "STRAIGHT_LINE"}
        )
    )
    component = validate_success(
        api.get_reserve_adequacy(
            ctx.association_id, MANAGER_HEADERS, params={"method": "COMPONENT"}
        )
    )

    assert straight_line["percent_funded_bp"] != component["percent_funded_bp"]
    assert straight_line["posture"] == "DEFICIENT"
    assert component["posture"] == "ADEQUATE"
    assert ctx.association_version() == version_before


def test_reserve_adequacy_defaults_to_the_straight_line_method(api: ApiClient) -> None:
    """Omitting the selector must behave exactly like asking for STRAIGHT_LINE.

    PRD 3.6: "Under the default **straight-line** method -- selected when
    `method` is omitted or is `STRAIGHT_LINE` -- each component's fully-funded
    basis is its `replacement_cost_cents` multiplied by the lesser of
    `effective_age_years` and `useful_life_years`, divided by
    `useful_life_years`, and rounded half up; the target accrues linearly with
    effective age over the whole useful life, so every non-decommissioned
    component contributes something."

    Design: Difficulty/dual_variant_calc/reserve_adequacy_straight_line_vs_component_flips_association_posture
    """
    ctx = _reserve_association(api)

    defaulted = validate_success(
        api.get_reserve_adequacy(ctx.association_id, MANAGER_HEADERS)
    )
    explicit = validate_success(
        api.get_reserve_adequacy(
            ctx.association_id, MANAGER_HEADERS, params={"method": "STRAIGHT_LINE"}
        )
    )

    assert defaulted["fully_funded_cents"] == explicit["fully_funded_cents"] == 8_600_000
    assert defaulted["percent_funded_bp"] == explicit["percent_funded_bp"] == 6976
    assert defaulted["posture"] == "DEFICIENT"


# ======================================================================
# Resale payoff: LEDGER_BALANCE versus ESTIMATED_PAYOFF
# ======================================================================
def _twin_unit_association(api: ApiClient):
    """Two 5000 bp units under an adopted FY2026 budget, clock at 2026-09-15."""
    ctx = create_association(api)
    add_owner(ctx, "d1", full_name="Dana Reyes", board_role="PRESIDENT", is_seated=True)
    add_owner(ctx, "d2", full_name="Elliot Shaw", board_role="DIRECTOR", is_seated=True)
    add_owner(ctx, "tr", full_name="Priya Nandan", board_role="TREASURER", is_seated=True)
    add_owner(ctx, "o1", full_name="Owner One")
    add_owner(ctx, "o2", full_name="Owner Two")
    add_unit(ctx, "101", "o1", 5000, 1200)
    add_unit(ctx, "102", "o2", 5000, 1200)
    budget = adopt_budget(
        ctx,
        fiscal_year=2026,
        operating_total_cents=12_000_000,
        reserve_contribution_cents=1_200_000,
        meeting_start="2026-09-05T18:00:00Z",
        meeting_end="2026-09-05T21:00:00Z",
    )
    set_clock(api, "2026-09-15T00:00:00Z")
    return ctx, budget


def test_resale_payoff_ledger_balance_basis_quotes_todays_ledger_only(
    api: ApiClient,
) -> None:
    """LEDGER_BALANCE quotes the ledger with no projection and no seller credit.

    PRD 3.9: "Under `LEDGER_BALANCE`, `ledger_balance_cents` and
    `projected_payoff_cents` are both the unit's `balance_due_cents` and
    `proration_credit_cents` is 0: today's ledger only, with no forward
    projection and no seller credit."

    The unit's only ledger row is the certificate fee the issuance itself
    posted, so all three figures follow from 35000.

    Design: Difficulty/dual_variant_calc/resale_payoff_ledger_balance_vs_estimated_payoff_on_twin_units
    """
    ctx, budget = _twin_unit_association(api)
    assert budget["monthly_assessable_cents"] == 1_100_000
    assert ctx.unit("101")["monthly_assessment_cents"] == 550_000

    certificate = issue_certificate(
        ctx,
        "101",
        closing_date="2026-11-08T00:00:00Z",
        payoff_basis="LEDGER_BALANCE",
        requesting_agent_id="TA-DUAL-A",
    )

    assert certificate["ledger_balance_cents"] == 35_000
    assert certificate["proration_credit_cents"] == 0
    assert certificate["projected_payoff_cents"] == 35_000
    assert_instant_equals(certificate["expires_at"], "2026-10-15T00:00:00Z")
    assert ctx.unit("101")["transfer_blocked"] is False


def test_resale_payoff_estimated_basis_projects_periods_and_prorates_once(
    api: ApiClient,
) -> None:
    """ESTIMATED_PAYOFF adds the unbilled periods and subtracts one proration.

    PRD 3.9: "Under `ESTIMATED_PAYOFF`, `ledger_balance_cents` is still the
    unit's `balance_due_cents`, the count of future periods is the number of
    whole billing periods whose first day falls strictly after the logical clock
    and strictly before `closing_date` and for which the unit has no `POSTED`
    `ASSESSMENT` row yet, the gross figure is the unit's `balance_due_cents`
    plus that count multiplied by the unit's `monthly_assessment_cents` plus the
    unbilled special-assessment disclosure, `proration_credit_cents` is the
    unit's `monthly_assessment_cents` multiplied by the buyer's days, divided by
    the month length, and rounded half up **once at the end** -- prorating each
    future period separately and summing is explicitly not the pinned order --
    and `projected_payoff_cents` is the gross figure minus
    `proration_credit_cents`."

    November 2026 has 30 days; the half-open seller interval
    [2026-11-01, 2026-11-08) is 7 days so the buyer holds 23, giving
    round_half_up(550000 * 23 / 30) == 421667, and 2026-10-01 plus 2026-11-01
    are the two unbilled periods, so 35000 + 2 * 550000 - 421667 == 713333.

    Design: Difficulty/dual_variant_calc/resale_payoff_ledger_balance_vs_estimated_payoff_on_twin_units
    """
    ctx, _ = _twin_unit_association(api)

    certificate = issue_certificate(
        ctx,
        "102",
        closing_date="2026-11-08T00:00:00Z",
        payoff_basis="ESTIMATED_PAYOFF",
        requesting_agent_id="TA-DUAL-B",
    )

    assert certificate["ledger_balance_cents"] == 35_000
    assert certificate["proration_credit_cents"] == 421_667
    assert certificate["projected_payoff_cents"] == 713_333


def test_resale_payoff_bases_diverge_on_identical_twin_units(api: ApiClient) -> None:
    """Identical ledgers and assessments still quote different payoffs.

    PRD 3.9: "Because `LEDGER_BALANCE` omits both the forward periods and the
    seller credit, it reports a lower figure than `ESTIMATED_PAYOFF` whenever
    any unbilled period or approved assessment exists."

    Design: Difficulty/dual_variant_calc/resale_payoff_ledger_balance_vs_estimated_payoff_on_twin_units
    """
    ctx, _ = _twin_unit_association(api)

    cert_a = issue_certificate(
        ctx,
        "101",
        closing_date="2026-11-08T00:00:00Z",
        payoff_basis="LEDGER_BALANCE",
        requesting_agent_id="TA-DUAL-A",
    )
    cert_b = issue_certificate(
        ctx,
        "102",
        closing_date="2026-11-08T00:00:00Z",
        payoff_basis="ESTIMATED_PAYOFF",
        requesting_agent_id="TA-DUAL-B",
    )

    assert cert_a["ledger_balance_cents"] == cert_b["ledger_balance_cents"] == 35_000
    assert (
        cert_b["projected_payoff_cents"] - cert_a["projected_payoff_cents"] == 678_333
    )


def test_resale_payoff_basis_defaults_to_ledger_balance(api: ApiClient) -> None:
    """Omitting payoff_basis must quote the ledger-only variant.

    PRD 3.9: "A `TitleAgent` or a `CommunityManager` requests a resale
    certificate for a unit by supplying the `closing_date` used for proration
    and forward projection, an optional `payoff_basis` of `LEDGER_BALANCE` or
    `ESTIMATED_PAYOFF` defaulting to `LEDGER_BALANCE`, the
    `requesting_agent_id` opaque identifier of the closing agent, and the
    mandatory `expected_unit_version`."

    Design: Difficulty/dual_variant_calc/resale_payoff_ledger_balance_vs_estimated_payoff_on_twin_units
    """
    ctx, _ = _twin_unit_association(api)

    requested = request_certificate(
        ctx,
        "101",
        closing_date="2026-11-08T00:00:00Z",
        payoff_basis="LEDGER_BALANCE",
        requesting_agent_id="TA-DUAL-DEFAULT",
    )
    assert requested["payoff_basis"] == "LEDGER_BALANCE"

    issued = get_success_data(
        api.issue_resale_certificate(requested["id"], MANAGER_HEADERS)
    )
    assert issued["proration_credit_cents"] == 0
    assert issued["projected_payoff_cents"] == issued["ledger_balance_cents"] == 35_000
