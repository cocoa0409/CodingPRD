"""
General average: the average adjustment arithmetic and the release of security.

Covers the adjustment run when security is called — the average adjuster's fee,
the total allowance, the contribution rate and the residual-cent waterfall that
makes the contributions balance — and the closing of that adjustment, which
releases every posting, returns the held cash deposit to the open cover and
lets the hull out of its hold.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    CLAIMS_ADJUSTER,
    UNDERWRITER,
    ApiClient,
    JsonDict,
    assert_money,
    assert_rate,
    assert_ratio,
    read_certificate,
    read_ga_event,
    read_ga_posting,
    read_policy,
    read_vessel,
)

# The average act declared over the two-contributor conveyance: a sacrifice of
# 120000.00 and a salvage award of 30000.00, both pre-fee.
SACRIFICE_AMOUNT = 120000.00
SALVAGE_AWARD_AMOUNT = 30000.00

# 0.05 x (120000.00 + 30000.00) — the fee is charged on the pre-fee base only.
EXPECTED_FEE = 7500.00
# 120000.00 + 30000.00 + 7500.00
EXPECTED_ALLOWANCE = 157500.00
# 1155000.00 (CERT-A, CIF) + 800000.00 (CERT-D, declared value)
EXPECTED_CONTRIBUTORY_VALUE = 1955000.00
# 157500.00 / 1955000.00 = 0.08056265..., rounded half up to 6 decimals.
EXPECTED_RATE = 0.080563
# Raw contributions 93050.27 and 64450.40 sum to 157500.67, so the residual of
# -0.67 lands on the largest contributory value.
EXPECTED_RAW_LARGEST = 93050.27
EXPECTED_CONTRIBUTION_LARGEST = 93049.60
EXPECTED_CONTRIBUTION_SMALLER = 64450.40
# Twenty percent of each contribution, both being over the 25000 cash trigger.
EXPECTED_DEPOSIT_LARGEST = 18609.92
EXPECTED_DEPOSIT_SMALLER = 12890.08
EXPECTED_DEPOSIT_TOTAL = 31500.00


def _posting_pair(api: ApiClient, env: JsonDict) -> tuple:
    """Read back the two security postings raised by the call, largest first."""
    largest = read_ga_posting(api, env["posting_a_id"], CLAIMS_ADJUSTER)
    smaller = read_ga_posting(api, env["posting_d_id"], CLAIMS_ADJUSTER)
    return largest, smaller


def test_general_average_fee_is_charged_on_the_pre_fee_allowance(
        api: ApiClient, ga_called_env: JsonDict) -> None:
    """
    The adjuster's fee is five percent of sacrifice plus salvage award alone, so
    it is 7500.00 and not the 7894.74 a self-charging reading would produce.

    First the average adjuster's fee: it is five percent of the **pre-fee** allowance only — the sum of `sacrifice_amount` and `salvage_award_amount` — rounded half up to 2 decimals, so the fee is never charged on itself.

    Design: Difficulty/combinatorial_formula/ga_adjuster_fee_self_reference_evaluation_order
    """
    event = read_ga_event(api, ga_called_env["ga_event_id"], CLAIMS_ADJUSTER)

    assert_money(event["sacrifice_amount"], SACRIFICE_AMOUNT, "sacrifice_amount")
    assert_money(event["salvage_award_amount"], SALVAGE_AWARD_AMOUNT,
                 "salvage_award_amount")
    assert_money(event["adjuster_fee_amount"], EXPECTED_FEE,
                 "adjuster_fee_amount")
    assert_money(
        event["adjuster_fee_amount"],
        round(0.05 * (SACRIFICE_AMOUNT + SALVAGE_AWARD_AMOUNT), 2),
        "adjuster_fee_amount re-derived from the pre-fee base")


def test_total_allowance_adds_the_fee_to_the_pre_fee_base(
        api: ApiClient, ga_called_env: JsonDict) -> None:
    """
    The allowance the contributors are asked to fund is 157500.00: the sacrifice,
    the salvage award and the 7500.00 fee.

    Then `total_allowance_amount` is the sacrifice plus the salvage award plus that fee.

    Design: Difficulty/combinatorial_formula/ga_adjuster_fee_self_reference_evaluation_order
    """
    event = read_ga_event(api, ga_called_env["ga_event_id"], CLAIMS_ADJUSTER)

    assert_money(event["total_allowance_amount"], EXPECTED_ALLOWANCE,
                 "total_allowance_amount")
    assert_money(
        event["total_allowance_amount"],
        SACRIFICE_AMOUNT + SALVAGE_AWARD_AMOUNT + EXPECTED_FEE,
        "total_allowance_amount re-derived")


def test_contribution_rate_is_rounded_to_six_decimals_before_it_is_applied(
        api: ApiClient, ga_called_env: JsonDict) -> None:
    """
    157500.00 over a contributory value of 1955000.00 is stored as 0.080563, the
    rate every contributor is then charged at.

    Then `contribution_rate` is the total allowance divided by the total contributory value, rounded half up to 6 decimals before it is applied to anybody.

    Design: Difficulty/combinatorial_formula/ga_adjuster_fee_self_reference_evaluation_order
    """
    event = read_ga_event(api, ga_called_env["ga_event_id"], CLAIMS_ADJUSTER)

    assert_money(event["total_contributory_value"], EXPECTED_CONTRIBUTORY_VALUE,
                 "total_contributory_value")
    assert_ratio(event["contribution_rate"], EXPECTED_RATE,
                 label="contribution_rate")

    largest, smaller = _posting_pair(api, ga_called_env)
    assert_money(largest["contributory_value"], 1155000.00,
                 "largest posting contributory_value")
    assert_money(smaller["contributory_value"], 800000.00,
                 "smaller posting contributory_value")


def test_residual_cent_lands_on_the_largest_contributory_value(
        api: ApiClient, ga_called_env: JsonDict) -> None:
    """
    The raw contributions 93050.27 and 64450.40 overshoot the allowance by 0.67,
    so the largest contributor is called for 93049.60 while the smaller keeps its
    raw 64450.40.

    The contributors are ordered by contributory value descending, ties broken by `created_at` ascending, and the whole residual — the total allowance minus the sum of the raw contributions, which may be positive or negative — is applied to the **first** bucket of that ordering.

    Design: Difficulty/combinatorial_formula/ga_adjuster_fee_self_reference_evaluation_order
    """
    largest, smaller = _posting_pair(api, ga_called_env)

    assert_money(largest["contribution_amount"], EXPECTED_CONTRIBUTION_LARGEST,
                 "largest contribution_amount")
    assert_money(smaller["contribution_amount"], EXPECTED_CONTRIBUTION_SMALLER,
                 "smaller contribution_amount")
    assert_money(
        EXPECTED_RAW_LARGEST - float(largest["contribution_amount"]),
        0.67,
        "residual absorbed by the largest contributory value")


def test_the_called_contributions_balance_the_allowance_to_the_cent(
        api: ApiClient, ga_called_env: JsonDict) -> None:
    """
    93049.60 plus 64450.40 is exactly the 157500.00 allowance, so no cent of the
    adjustment is lost to the rounding of the rate.

    The result is that the sum of all `contribution_amount` values equals the total allowance to the cent.

    Design: Difficulty/combinatorial_formula/ga_adjuster_fee_self_reference_evaluation_order
    """
    event = read_ga_event(api, ga_called_env["ga_event_id"], CLAIMS_ADJUSTER)
    largest, smaller = _posting_pair(api, ga_called_env)

    assert_money(
        float(largest["contribution_amount"])
        + float(smaller["contribution_amount"]),
        EXPECTED_ALLOWANCE,
        "sum of the called contributions")
    assert_money(event["total_allowance_amount"], EXPECTED_ALLOWANCE,
                 "total_allowance_amount")


def test_cash_deposit_expected_is_a_fifth_of_each_called_contribution(
        api: ApiClient, ga_called_env: JsonDict) -> None:
    """
    Both contributions clear the 25000 cash trigger, so each posting also calls a
    twenty percent deposit: 18609.92 and 12890.08, totalling 31500.00.

    Whether cash is wanted as well as a guarantee is then decided per posting: `cash_deposit_required` is true when the contribution amount exceeds 25000, and where it is true, `cash_deposit_expected_amount` is twenty percent of the contribution amount rounded half up to 2 decimals, while a posting that needs no cash carries an expected deposit of 0.00.

    Design: Difficulty/combinatorial_formula/ga_adjuster_fee_self_reference_evaluation_order
    """
    largest, smaller = _posting_pair(api, ga_called_env)

    assert largest["cash_deposit_required"] is True
    assert smaller["cash_deposit_required"] is True
    assert_money(largest["cash_deposit_expected_amount"],
                 EXPECTED_DEPOSIT_LARGEST, "largest cash_deposit_expected_amount")
    assert_money(smaller["cash_deposit_expected_amount"],
                 EXPECTED_DEPOSIT_SMALLER, "smaller cash_deposit_expected_amount")
    assert_money(
        float(largest["cash_deposit_expected_amount"])
        + float(smaller["cash_deposit_expected_amount"]),
        EXPECTED_DEPOSIT_TOTAL,
        "total expected cash deposit")


def test_each_contributing_certificate_records_its_own_contribution(
        api: ApiClient, ga_called_env: JsonDict) -> None:
    """
    The allocation is written back onto the contributing certificates: 93049.60
    onto the CIF interest and 64450.40 onto the declared-value one.

    Each contributing certificate's `ga_contribution_amount` is written with its posting's contribution amount.

    Design: Difficulty/combinatorial_formula/ga_adjuster_fee_self_reference_evaluation_order
    """
    largest_certificate = read_certificate(api, ga_called_env["certificate_a_id"])
    smaller_certificate = read_certificate(api, ga_called_env["certificate_d_id"])

    assert_money(largest_certificate["ga_contribution_amount"],
                 EXPECTED_CONTRIBUTION_LARGEST,
                 "CIF certificate ga_contribution_amount")
    assert_money(smaller_certificate["ga_contribution_amount"],
                 EXPECTED_CONTRIBUTION_SMALLER,
                 "declared-value certificate ga_contribution_amount")


def test_the_security_call_records_two_required_postings_and_none_posted(
        api: ApiClient, ga_called_env: JsonDict) -> None:
    """
    Two contributors mean two postings required, none of them posted yet, and the
    event collecting its security.

    The event records `postings_required_count` as the number of postings created, sets `postings_posted_count` to 0, moves `DECLARED → SECURITY_COLLECTING` and increments its `version`.

    Design: Difficulty/combinatorial_formula/ga_adjuster_fee_self_reference_evaluation_order
    """
    event = read_ga_event(api, ga_called_env["ga_event_id"], CLAIMS_ADJUSTER)

    assert event["postings_required_count"] == 2
    assert event["postings_posted_count"] == 0
    assert event["status"] == "SECURITY_COLLECTING"

    largest, smaller = _posting_pair(api, ga_called_env)
    assert largest["status"] == "REQUIRED"
    assert smaller["status"] == "REQUIRED"


def test_finalising_the_adjustment_closes_the_average_event(
        api: ApiClient, ga_secured_env: JsonDict) -> None:
    """
    A fully secured event is closed by the adjuster and reaches its terminal
    adjusted state.

    A `ClaimsAdjuster` finalises a `SECURITY_COMPLETE` event, moving it to the terminal `ADJUSTED`, and that single action fires three further links.

    Design: Difficulty/transitive_cascade/ga_finalize_adjustment_security_release_cascade
    """
    before = read_ga_event(api, ga_secured_env["ga_event_id"], CLAIMS_ADJUSTER)
    assert before["status"] == "SECURITY_COMPLETE"
    assert before["postings_posted_count"] == before["postings_required_count"] == 2

    finalised = validate_success(api.finalize_ga_adjustment(
        ga_secured_env["ga_event_id"], CLAIMS_ADJUSTER))

    assert finalised["status"] == "ADJUSTED"
    assert finalised["version"] == before["version"] + 1
    assert read_ga_event(api, ga_secured_env["ga_event_id"],
                         CLAIMS_ADJUSTER)["status"] == "ADJUSTED"


def test_closing_the_event_releases_every_posted_security(
        api: ApiClient, ga_secured_env: JsonDict) -> None:
    """
    Both postings leave their posted state for the terminal released one, and the
    contributions they were called for are untouched by the release.

    Every security posting on the event moves `POSTED → RELEASED`, which is terminal for a posting.

    Design: Difficulty/transitive_cascade/ga_finalize_adjustment_security_release_cascade
    """
    largest_before, smaller_before = _posting_pair(api, ga_secured_env)
    assert largest_before["status"] == "POSTED"
    assert smaller_before["status"] == "POSTED"

    validate_success(api.finalize_ga_adjustment(
        ga_secured_env["ga_event_id"], CLAIMS_ADJUSTER))

    largest, smaller = _posting_pair(api, ga_secured_env)
    assert largest["status"] == "RELEASED"
    assert smaller["status"] == "RELEASED"
    assert_money(largest["contribution_amount"], EXPECTED_CONTRIBUTION_LARGEST,
                 "largest contribution_amount after release")
    assert_money(smaller["contribution_amount"], EXPECTED_CONTRIBUTION_SMALLER,
                 "smaller contribution_amount after release")


def test_releasing_the_postings_returns_the_held_deposit_ledger_to_zero(
        api: ApiClient, ga_secured_env: JsonDict) -> None:
    """
    The open cover held 31500.00 of cash deposits while security was lodged; each
    released posting gives its own deposit back, leaving 0.00.

    Each released posting's `cash_deposit_amount` is deducted from the holding policy's `security_deposit_held_amount`, returning that ledger to exactly its pre-posting value.

    Design: Difficulty/transitive_cascade/ga_finalize_adjustment_security_release_cascade
    """
    policy_before = read_policy(api, ga_secured_env["policy_id"])
    assert_money(policy_before["security_deposit_held_amount"],
                 EXPECTED_DEPOSIT_TOTAL,
                 "security_deposit_held_amount before the release")

    largest, smaller = _posting_pair(api, ga_secured_env)
    assert_money(largest["cash_deposit_amount"], EXPECTED_DEPOSIT_LARGEST,
                 "largest cash_deposit_amount")
    assert_money(smaller["cash_deposit_amount"], EXPECTED_DEPOSIT_SMALLER,
                 "smaller cash_deposit_amount")

    validate_success(api.finalize_ga_adjustment(
        ga_secured_env["ga_event_id"], CLAIMS_ADJUSTER))

    policy_after = read_policy(api, ga_secured_env["policy_id"])
    assert_money(policy_after["security_deposit_held_amount"], 0.00,
                 "security_deposit_held_amount after the release")


def test_closing_the_last_average_event_lifts_the_hold_on_the_hull(
        api: ApiClient, ga_secured_env: JsonDict) -> None:
    """
    With no other average event open, the hull's counter falls to zero and it
    returns to the approved state it was screened into, its surcharge still nil.

    And the vessel's `open_ga_event_count` decrements; when it reaches zero the hull comes out of hold, going `GA_HOLD → APPROVED` if its preserved `overage_surcharge_pct` is zero and `GA_HOLD → OVERAGE_SURCHARGED` if it is greater than zero — which is precisely why the surcharge was preserved through the hold rather than cleared.

    Design: Difficulty/transitive_cascade/ga_finalize_adjustment_security_release_cascade
    """
    held = read_vessel(api, ga_secured_env["vessel_id"])
    assert held["status"] == "GA_HOLD"
    assert held["open_ga_event_count"] == 1

    validate_success(api.finalize_ga_adjustment(
        ga_secured_env["ga_event_id"], CLAIMS_ADJUSTER))

    released = validate_success(
        api.get_vessel(ga_secured_env["vessel_id"], UNDERWRITER))
    assert released["open_ga_event_count"] == 0
    assert released["status"] == "APPROVED"
    assert_rate(released["overage_surcharge_pct"], 0.00, places=2,
                label="overage_surcharge_pct preserved through the hold")
