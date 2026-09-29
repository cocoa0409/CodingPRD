"""Exact-boundary behaviour of the two integer metrics the PRD pins.

The first metric is the basis-point coverage ratio of PRD 3.7, read off
``GET /licensees/{id}/coverage-summary``: one cent of extra cash moves the
floored ratio from 9999 (`WATCH`) to exactly 10000 (`COMPLIANT`). The second is
the nought-to-one-hundred weighted delegate oversight score of PRD 3.6, read at
the activation gate: components that floor to 69 are refused while components
that floor to exactly 70 are admitted.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import MoneyTransmitterApiClient
from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_OVERSIGHT_SCORE_INSUFFICIENT
from test_helpers.test_users import CHIEF_HEADERS, MANAGER_HEADERS

# The obligation figure every coverage test below owes its customers, and the
# cash holding one cent short of covering it.
OBLIGATIONS_CENTS = 85_000_000
CASH_ONE_CENT_SHORT_CENTS = 84_999_999

# The authorization period the delegate tests use.
AUTH_EFFECTIVE_DATE = "2026-09-01T00:00:00Z"
AUTH_EXPIRY_DATE = "2027-08-31T00:00:00Z"


def _coverage_summary(api: MoneyTransmitterApiClient, licensee_id: str) -> dict:
    """Read the licensee-level coverage summary as the chief officer."""
    return validate_success(api.get_coverage_summary(licensee_id, CHIEF_HEADERS))


def _scored_delegate_awaiting_activation(
    api: MoneyTransmitterApiClient,
    scenario: fx.Scenario,
    legal_name: str,
    training_score: int,
    aml_test_score: int,
    recordkeeping_score: int,
) -> tuple:
    """Appoint an agent, score it once, and park an authorization on the licence."""
    delegate = fx.create_delegate(api, scenario.licensee_id, legal_name=legal_name)
    delegate = fx.review_delegate(
        api,
        delegate["id"],
        training_score=training_score,
        aml_test_score=aml_test_score,
        recordkeeping_score=recordkeeping_score,
    )
    authorization = fx.create_authorization(
        api,
        delegate["id"],
        scenario.license_id,
        AUTH_EFFECTIVE_DATE,
        AUTH_EXPIRY_DATE,
    )
    assert authorization["status"] == "PENDING_OVERSIGHT"
    return delegate, authorization


def test_cash_one_cent_short_of_the_obligations_floors_the_ratio_to_9999_and_watches(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A ratio one basis point short of full coverage is WATCH, not COMPLIANT.

    PRD 2.5: "**Floor** (round down toward zero) governs every division inside the permissible-investment coverage computation, every hop of the ownership attribution chain, the class-multiplier step of the surety bond computation, and the weighted delegate oversight score."
    PRD 3.7: "The haircuts, in basis points, are: `CASH` none, `US_TREASURY` 200, `MONEY_MARKET_FUND` 300, `AGENCY_BOND` 500 and `RECEIVABLE_FROM_DELEGATE` 1000."
    PRD 3.7: "Holdings in the uncapped classes — `CASH` and `US_TREASURY` — accumulate into a single uncapped total."
    PRD 3.7: "A coverage ratio in basis points is derived from an investment value the same way for both variants: it is exactly 10000 when the licensee's `aggregate_outstanding_obligations_cents` is zero, and otherwise the investment value multiplied by 10000, divided by the obligations, rounded down."
    PRD 3.7: "The boundaries are exact: 10000 is `COMPLIANT`, 9999 is `WATCH`, 9500 is `WATCH`, 9499 is `DEFICIENT`."
    PRD 3.7: "First, the concentration cap is fixed for this licensee as its `aggregate_outstanding_obligations_cents` multiplied by 1000 basis points — ten percent — divided by 10000 and rounded down; that figure is exposed as `concentration_cap_cents`."

    Design: Difficulty/boundary_precision_check/coverage_ratio_at_exactly_ten_thousand_bps_is_compliant
    """
    fx.adjust_obligations(api, active_license.license_id, OBLIGATIONS_CENTS)
    fx.record_holding(
        api,
        active_license.licensee_id,
        "CASH",
        "BankA",
        CASH_ONE_CENT_SHORT_CENTS,
        CASH_ONE_CENT_SHORT_CENTS,
    )

    summary = _coverage_summary(api, active_license.licensee_id)

    assert summary["obligations_cents"] == 85_000_000
    # CASH takes no haircut and sits in the uncapped bucket, so the eligible
    # value is the market value untouched.
    assert summary["eligible_investment_value_cents"] == 84_999_999
    # floor(84999999 * 10000 / 85000000) = floor(9999.99988...) = 9999
    assert summary["coverage_ratio_bps"] == 9999
    assert summary["coverage_posture"] == "WATCH"
    # floor(85000000 * 1000 / 10000) = 8500000
    assert summary["concentration_cap_cents"] == 8_500_000

    licensee = fx.get_licensee(api, active_license.licensee_id)
    assert licensee["coverage_ratio_bps"] == 9999
    assert licensee["coverage_posture"] == "WATCH"


def test_one_extra_cent_of_cash_lifts_the_ratio_to_exactly_10000_and_compliant(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Exactly 10000 basis points clears the compliance band.

    PRD 3.7: "The `BOOK_VALUE` variant is the generous one: `book_investment_value_cents` is simply the sum of `book_value_cents` over the candidate set."
    PRD 3.7: "A coverage ratio in basis points is derived from an investment value the same way for both variants: it is exactly 10000 when the licensee's `aggregate_outstanding_obligations_cents` is zero, and otherwise the investment value multiplied by 10000, divided by the obligations, rounded down."
    PRD 3.7: "From it, and from `consecutive_failed_test_count`, the licensee's `coverage_posture` is determined by a strictly ordered test: the posture is `FROZEN` if `consecutive_failed_test_count` is at least 2, regardless of the ratio; otherwise `COMPLIANT` if `coverage_ratio_bps` is at least 10000; otherwise `WATCH` if `coverage_ratio_bps` is at least 9500; otherwise `DEFICIENT`."
    PRD 3.7: "The boundaries are exact: 10000 is `COMPLIANT`, 9999 is `WATCH`, 9500 is `WATCH`, 9499 is `DEFICIENT`."
    PRD 3.7: "A licensee-level coverage read exposes both variants side by side over identical holdings — `obligations_cents`, `book_investment_value_cents`, `book_coverage_ratio_bps`, `eligible_investment_value_cents`, `coverage_ratio_bps`, `concentration_cap_cents`, `coverage_posture` and `consecutive_failed_test_count` — so that the divergence is observable in a single response."

    Design: Difficulty/boundary_precision_check/coverage_ratio_at_exactly_ten_thousand_bps_is_compliant
    """
    fx.adjust_obligations(api, active_license.license_id, OBLIGATIONS_CENTS)
    fx.record_holding(
        api,
        active_license.licensee_id,
        "CASH",
        "BankA",
        CASH_ONE_CENT_SHORT_CENTS,
        CASH_ONE_CENT_SHORT_CENTS,
    )
    short_of_cover = _coverage_summary(api, active_license.licensee_id)
    assert short_of_cover["coverage_ratio_bps"] == 9999
    assert short_of_cover["coverage_posture"] == "WATCH"

    # One more cent of unhaircut cash at the same counterparty.
    fx.record_holding(api, active_license.licensee_id, "CASH", "BankA", 1, 1)

    summary = _coverage_summary(api, active_license.licensee_id)

    # 84999999 + 1 = 85000000, exactly the obligation figure.
    assert summary["eligible_investment_value_cents"] == 85_000_000
    # floor(85000000 * 10000 / 85000000) = 10000
    assert summary["coverage_ratio_bps"] == 10000
    assert summary["coverage_posture"] == "COMPLIANT"
    # Every holding is unhaircut CASH, so the generous variant coincides here.
    assert summary["book_investment_value_cents"] == 85_000_000
    assert summary["book_coverage_ratio_bps"] == 10000
    assert summary["consecutive_failed_test_count"] == 0
    # The ratio is an integer count of basis points, never a fraction.
    assert isinstance(summary["coverage_ratio_bps"], int)
    assert not isinstance(summary["coverage_ratio_bps"], bool)

    licensee = fx.get_licensee(api, active_license.licensee_id)
    assert licensee["coverage_ratio_bps"] == 10000
    assert licensee["coverage_posture"] == "COMPLIANT"


def test_one_cent_of_excess_cover_still_floors_the_ratio_to_exactly_10000(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Coverage a cent above the obligations reads 10000, never 10001.

    PRD 2.5: "All monetary amounts are integers denominated in cents; all rates, ratios and ownership stakes are integers denominated in basis points, where 10,000 basis points is one hundred percent."
    PRD 2.5: "**Floor** (round down toward zero) governs every division inside the permissible-investment coverage computation, every hop of the ownership attribution chain, the class-multiplier step of the surety bond computation, and the weighted delegate oversight score."
    PRD 3.7: "A coverage ratio in basis points is derived from an investment value the same way for both variants: it is exactly 10000 when the licensee's `aggregate_outstanding_obligations_cents` is zero, and otherwise the investment value multiplied by 10000, divided by the obligations, rounded down."
    PRD 3.7: "The boundaries are exact: 10000 is `COMPLIANT`, 9999 is `WATCH`, 9500 is `WATCH`, 9499 is `DEFICIENT`."

    Design: Difficulty/boundary_precision_check/coverage_ratio_at_exactly_ten_thousand_bps_is_compliant
    """
    fx.adjust_obligations(api, active_license.license_id, OBLIGATIONS_CENTS)
    # One cent more cash than the licensee owes.
    fx.record_holding(
        api, active_license.licensee_id, "CASH", "BankA", 85_000_001, 85_000_001
    )

    summary = _coverage_summary(api, active_license.licensee_id)

    assert summary["obligations_cents"] == 85_000_000
    assert summary["eligible_investment_value_cents"] == 85_000_001
    # floor(85000001 * 10000 / 85000000) = floor(10000.000117...) = 10000
    assert summary["coverage_ratio_bps"] == 10000
    assert summary["coverage_posture"] == "COMPLIANT"


def test_components_that_floor_to_69_are_refused_at_the_activation_gate(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A weighted oversight score of 69 blocks activation and moves no counter.

    PRD 3.6: "The resulting `oversight_score` is the training score weighted at 4000 basis points, plus the anti-money-laundering test score weighted at 3500 basis points, plus the recordkeeping score weighted at 2500 basis points, that sum divided by 10000 and rounded down to a whole number."
    PRD 3.6: "The underlying licence's `license_status` must be `ACTIVE` (`ERR_LICENSE_NOT_ACTIVE`), its `expansion_gate` must be `OPEN` (`ERR_EXPANSION_GATE_BLOCKED`), the delegate's `oversight_score` must be non-null and at least 70 (`ERR_OVERSIGHT_SCORE_INSUFFICIENT`) — a score of exactly 70 satisfies the gate, 69 does not — and the delegate and licence must share a licensee."
    PRD 3.6: "A new authorization starts in `PENDING_OVERSIGHT` and moves no counter — only activation makes a delegate count against the bond."
    PRD 3.6: "The row starts in `ONBOARDING`, the other statuses being `ACTIVE`, `SUSPENDED` and the terminal `TERMINATED`."

    Design: Difficulty/boundary_precision_check/oversight_score_of_exactly_seventy_admits_activation
    """
    delegate, authorization = _scored_delegate_awaiting_activation(
        api, active_license, C.SEED_DELEGATE_NAME, 80, 65, 60
    )

    # floor((80 * 4000 + 65 * 3500 + 60 * 2500) / 10000)
    #   = floor((320000 + 227500 + 150000) / 10000) = floor(69.75) = 69
    assert delegate["oversight_score"] == 69

    # The gate's other four conditions hold, so the score is the only failure.
    license_before = fx.get_license(api, active_license.license_id)
    assert license_before["license_status"] == "ACTIVE"
    assert license_before["expansion_gate"] == "OPEN"
    assert license_before["active_delegate_count"] == 0

    response = api.activate_authorization(authorization["id"], MANAGER_HEADERS)
    validate_error(response, ERR_OVERSIGHT_SCORE_INSUFFICIENT, 409)

    parked = validate_success(
        api.get_delegate_authorization(authorization["id"], MANAGER_HEADERS)
    )
    assert parked["status"] == "PENDING_OVERSIGHT"
    assert parked["activated_at"] is None
    assert parked["oversight_score_at_activation"] is None

    unchanged_delegate = validate_success(api.get_delegate(delegate["id"], MANAGER_HEADERS))
    assert unchanged_delegate["status"] == "ONBOARDING"
    assert unchanged_delegate["authorized_state_count"] == 0

    license_after = fx.get_license(api, active_license.license_id)
    assert license_after["active_delegate_count"] == 0
    # max(base 5000000, tier-one 2500000 + 0 * 100000) = 5000000, times the
    # MONEY_TRANSMISSION multiplier of 10000 bps, capped at 40000000.
    assert license_after["bond_requirement_cents"] == 5_000_000


def test_components_that_floor_to_exactly_70_admit_activation_and_pin_the_score(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A weighted oversight score of exactly 70 clears the gate.

    PRD 3.6: "The resulting `oversight_score` is the training score weighted at 4000 basis points, plus the anti-money-laundering test score weighted at 3500 basis points, plus the recordkeeping score weighted at 2500 basis points, that sum divided by 10000 and rounded down to a whole number."
    PRD 3.6: "The underlying licence's `license_status` must be `ACTIVE` (`ERR_LICENSE_NOT_ACTIVE`), its `expansion_gate` must be `OPEN` (`ERR_EXPANSION_GATE_BLOCKED`), the delegate's `oversight_score` must be non-null and at least 70 (`ERR_OVERSIGHT_SCORE_INSUFFICIENT`) — a score of exactly 70 satisfies the gate, 69 does not — and the delegate and licence must share a licensee."
    PRD 3.6: "On success, and identically for both admissible source statuses, the authorization moves to `ACTIVE`, `activated_at` is stamped from the logical clock, and `oversight_score_at_activation` pins the delegate's `oversight_score` as it stood at that instant."
    PRD 3.6: "The licence's `active_delegate_count` increases by one and its `bond_requirement_cents` is recomputed with the new delegate count — which is how onboarding an agent can raise a bond requirement above the posted bond."
    PRD 3.6: "The delegate's `authorized_state_count` increases by one."
    PRD 3.6: "The first successful activation moves the delegate `ONBOARDING → ACTIVE`; an activation out of `SUSPENDED_BY_POSTURE` for a delegate that had been parked moves it `SUSPENDED → ACTIVE` and clears `oversight_hold` to false."

    Design: Difficulty/boundary_precision_check/oversight_score_of_exactly_seventy_admits_activation
    """
    delegate, authorization = _scored_delegate_awaiting_activation(
        api, active_license, C.SEED_SECOND_DELEGATE_NAME, 70, 70, 70
    )

    # floor((70 * 4000 + 70 * 3500 + 70 * 2500) / 10000)
    #   = floor((280000 + 245000 + 175000) / 10000) = floor(70.0) = 70
    assert delegate["oversight_score"] == 70

    activated = validate_success(
        api.activate_authorization(authorization["id"], MANAGER_HEADERS)
    )

    assert activated["status"] == "ACTIVE"
    assert activated["oversight_score_at_activation"] == 70
    assert activated["activated_at"] is not None

    active_delegate = validate_success(api.get_delegate(delegate["id"], MANAGER_HEADERS))
    assert active_delegate["status"] == "ACTIVE"
    assert active_delegate["authorized_state_count"] == 1
    assert active_delegate["oversight_hold"] is False

    license_after = fx.get_license(api, active_license.license_id)
    assert license_after["active_delegate_count"] == 1
    # max(base 5000000, tier-one 2500000 + 1 * 100000 = 2600000) = 5000000, times
    # the MONEY_TRANSMISSION multiplier of 10000 bps, capped at 40000000: the
    # statutory floor still dominates one delegate.
    assert license_after["bond_requirement_cents"] == 5_000_000


def test_the_oversight_gate_separates_69_from_70_in_one_and_the_same_estate(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Side by side on one licence, only the delegate scoring 70 is admitted.

    PRD 3.6: "The resulting `oversight_score` is the training score weighted at 4000 basis points, plus the anti-money-laundering test score weighted at 3500 basis points, plus the recordkeeping score weighted at 2500 basis points, that sum divided by 10000 and rounded down to a whole number."
    PRD 3.6: "Only the most recent review counts: the new score **replaces** the old one outright and earlier reviews are not averaged in."
    PRD 3.6: "The underlying licence's `license_status` must be `ACTIVE` (`ERR_LICENSE_NOT_ACTIVE`), its `expansion_gate` must be `OPEN` (`ERR_EXPANSION_GATE_BLOCKED`), the delegate's `oversight_score` must be non-null and at least 70 (`ERR_OVERSIGHT_SCORE_INSUFFICIENT`) — a score of exactly 70 satisfies the gate, 69 does not — and the delegate and licence must share a licensee."
    PRD 3.6: "On success, and identically for both admissible source statuses, the authorization moves to `ACTIVE`, `activated_at` is stamped from the logical clock, and `oversight_score_at_activation` pins the delegate's `oversight_score` as it stood at that instant."

    Design: Difficulty/boundary_precision_check/oversight_score_of_exactly_seventy_admits_activation
    """
    refused_delegate, refused_authorization = _scored_delegate_awaiting_activation(
        api, active_license, C.SEED_DELEGATE_NAME, 80, 65, 60
    )
    admitted_delegate, admitted_authorization = _scored_delegate_awaiting_activation(
        api, active_license, C.SEED_SECOND_DELEGATE_NAME, 70, 70, 70
    )

    # 697500 / 10000 floors to 69; 700000 / 10000 is exactly 70.
    assert refused_delegate["oversight_score"] == 69
    assert admitted_delegate["oversight_score"] == 70

    validate_error(
        api.activate_authorization(refused_authorization["id"], MANAGER_HEADERS),
        ERR_OVERSIGHT_SCORE_INSUFFICIENT,
        409,
    )
    admitted = validate_success(
        api.activate_authorization(admitted_authorization["id"], MANAGER_HEADERS)
    )
    assert admitted["status"] == "ACTIVE"
    assert admitted["oversight_score_at_activation"] == 70

    still_parked = validate_success(
        api.get_delegate_authorization(refused_authorization["id"], MANAGER_HEADERS)
    )
    assert still_parked["status"] == "PENDING_OVERSIGHT"

    license_after = fx.get_license(api, active_license.license_id)
    # Only the boundary-passing delegate counts against the licence.
    assert license_after["active_delegate_count"] == 1
