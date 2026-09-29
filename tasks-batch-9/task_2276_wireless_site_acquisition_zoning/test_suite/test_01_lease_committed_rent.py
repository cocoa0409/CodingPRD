"""Committed rent: the two variants and the pinned per-year rounding order."""

from test_helpers import constants as C
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_fields,
    assert_instant,
    assert_instant_is_none,
    assert_money,
    assert_money_not,
    ok,
)

PROVISIONAL_TOTAL = 160070.45
FINAL_TOTAL = 588795.12
DELTA = 428724.67
FIRST_YEAR_RENT = 30150.00
LAST_YEAR_RENT = 45604.58
COUNTERED_RENT = 2512.50
SUM_THEN_ROUND_TOTAL = 160070.44


def _countered_lease(api: ApiClient):
    """A lease countered to 2512.50 and left in `COUNTERED`."""
    chain = S.engaged_candidate(api)
    lease = S.create_lease(api, chain["cand_id"], chain["ll_id"])
    S.lease_round(api, lease["id"], "SUBMIT", C.LEASE_BASE_RENT_USD)
    S.lease_round(api, lease["id"], "COUNTER", COUNTERED_RENT)
    chain["lease_id"] = lease["id"]
    return chain


def test_accept_prices_only_the_initial_term_and_execute_prices_all_renewals(
    api: ApiClient,
) -> None:
    """Both committed-rent variants are produced from the same per-year series.

    PRD: "On acceptance the agreed figure becomes the lease's economics —
    `base_monthly_rent_usd` is overwritten with `last_counter_rent_usd` — and the
    provisional variant of the committed rent is computed and stored in
    `committed_rent_provisional_usd`."

    PRD: "The **final** variant, written to `committed_rent_final_usd` at
    execution, assumes every renewal option is exercised: its horizon is
    `initial_term_years` plus `renewal_option_count` multiplied by
    `renewal_term_years`, it sums the rounded years 1 through that horizon and
    rounds the sum to two decimal places to obtain a base total, then computes a
    revenue-share uplift as that base total multiplied by `revenue_share_pct`
    rounded half up to two decimal places, and finally stores the base total plus
    the uplift, again rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/lease_committed_rent_provisional_vs_final_diverge
    """
    chain = _countered_lease(api)
    lease_id = chain["lease_id"]

    accepted = ok(api.add_lease_round(lease_id, {"action": "ACCEPT"}, headers=S.agent()))
    assert_money(accepted["base_monthly_rent_usd"], COUNTERED_RENT, "base_monthly_rent_usd")
    assert_money(
        accepted["committed_rent_provisional_usd"],
        PROVISIONAL_TOTAL,
        "committed_rent_provisional_usd",
    )

    executed = ok(
        api.execute_lease(
            lease_id,
            {"execution_date": C.CLOCK_DEFAULT},
            headers=S.director(),
        )
    )
    assert_money(
        executed["committed_rent_final_usd"], FINAL_TOTAL, "committed_rent_final_usd"
    )
    assert executed["status"] == "EXECUTED"

    final = float(executed["committed_rent_final_usd"])
    provisional = float(executed["committed_rent_provisional_usd"])
    assert_money(final - provisional, DELTA, "final minus provisional")

    schedule = ok(api.get_rent_schedule(lease_id, headers=S.director()))
    assert_money(schedule["provisional_total_usd"], PROVISIONAL_TOTAL, "provisional_total_usd")
    assert_money(schedule["final_total_usd"], FINAL_TOTAL, "final_total_usd")
    assert_money(schedule["delta_usd"], DELTA, "delta_usd")
    assert schedule["priced_years"] == 15
    assert_money(schedule["first_year_rent_usd"], FIRST_YEAR_RENT, "first_year_rent_usd")
    assert_money(schedule["last_year_rent_usd"], LAST_YEAR_RENT, "last_year_rent_usd")


def test_acceptance_leaves_the_final_variant_null_until_execution(
    api: ApiClient,
) -> None:
    """The provisional variant ignores the renewals the final variant prices.

    PRD: "The **provisional** variant, written to
    `committed_rent_provisional_usd` at acceptance, sums the rounded years 1
    through `initial_term_years` and rounds the sum half up to two decimal places;
    renewal options are ignored and `revenue_share_pct` is not applied."

    PRD: "On success the supplied `execution_date` is stored, the final
    committed-rent variant is computed into `committed_rent_final_usd`, the lease
    moves `ACCEPTED → EXECUTED`, the candidate's `acquisition_status` advances
    `LANDLORD_ENGAGED → LEASE_EXECUTED`, and the landlord's
    `executed_lease_count` is recomputed."

    Design: Difficulty/dual_variant_calc/lease_committed_rent_provisional_vs_final_diverge
    """
    chain = _countered_lease(api)
    lease_id = chain["lease_id"]

    accepted = ok(api.add_lease_round(lease_id, {"action": "ACCEPT"}, headers=S.agent()))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["committed_rent_final_usd"] is None, (
        "the final variant is written at execution, not at acceptance"
    )
    assert_money_not(
        accepted["committed_rent_provisional_usd"],
        FINAL_TOTAL,
        "committed_rent_provisional_usd",
    )
    assert_instant_is_none(accepted["execution_date"], "execution_date")

    executed = ok(
        api.execute_lease(
            lease_id, {"execution_date": C.CLOCK_DEFAULT}, headers=S.director()
        )
    )
    assert_instant(executed["execution_date"], C.CLOCK_DEFAULT, "execution_date")
    assert_money(
        executed["committed_rent_provisional_usd"],
        PROVISIONAL_TOTAL,
        "committed_rent_provisional_usd",
    )
    assert float(executed["committed_rent_final_usd"]) > float(
        executed["committed_rent_provisional_usd"]
    )

    candidate = ok(api.get_candidate(chain["cand_id"], headers=S.director()))
    assert_fields(candidate, acquisition_status="LEASE_EXECUTED")
    landlord = ok(api.get_landlord(chain["ll_id"], headers=S.director()))
    assert_fields(landlord, executed_lease_count=1)


def test_committed_rent_rounds_each_year_before_summing(api: ApiClient) -> None:
    """Per-year rounding first, then the sum — one cent apart from the naive order.

    PRD: "Summing unrounded annual figures and rounding once at the end is
    explicitly incorrect."

    Design: Difficulty/combinatorial_formula/lease_rent_rounding_order_pinned_per_year_then_sum
    """
    chain = _countered_lease(api)
    accepted = ok(
        api.add_lease_round(chain["lease_id"], {"action": "ACCEPT"}, headers=S.agent())
    )

    assert_money(
        accepted["committed_rent_provisional_usd"],
        PROVISIONAL_TOTAL,
        "committed_rent_provisional_usd",
    )
    assert_money_not(
        accepted["committed_rent_provisional_usd"],
        SUM_THEN_ROUND_TOTAL,
        "committed_rent_provisional_usd",
    )


def test_accept_does_not_count_as_a_negotiation_round(api: ApiClient) -> None:
    """The per-year series the schedule exposes is the one the totals are built from.

    PRD: "`ACCEPT` does not increment `round_count`."

    PRD: "It reports `provisional_total_usd` and `final_total_usd` as just
    defined, `delta_usd` as the final total minus the provisional total rounded
    half up to two decimal places, `priced_years` as the full final-variant
    horizon in years, and the two ends of the per-year series —
    `first_year_rent_usd`, the rounded annual rent for year 1, and
    `last_year_rent_usd`, the rounded annual rent for the final year of that
    horizon."

    Design: Difficulty/combinatorial_formula/lease_rent_rounding_order_pinned_per_year_then_sum
    """
    chain = _countered_lease(api)
    accepted = ok(
        api.add_lease_round(chain["lease_id"], {"action": "ACCEPT"}, headers=S.agent())
    )
    assert_fields(accepted, round_count=2)

    schedule = ok(api.get_rent_schedule(chain["lease_id"], headers=S.agent()))
    assert_money(schedule["first_year_rent_usd"], FIRST_YEAR_RENT, "first_year_rent_usd")
    assert schedule["priced_years"] == 15
