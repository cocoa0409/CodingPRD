"""Transitive cascades: one write, several rows moved along a declared chain.

Two chains are exercised. An obligations adjustment runs the posture cascade —
aggregate obligations, coverage ratio, posture, expansion gate, parked
authorization, suspended delegate — with the request payload naming none of the
downstream links. A bond cancellation notice runs the licence-suspension cascade
along a different axis, suspending the licence, its ACTIVE authorization and the
delegate that is left with no authorised state, without passing through coverage
posture at all.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import MoneyTransmitterApiClient
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.test_users import MANAGER_HEADERS

# A cancellation notice must be at least thirty days out; sixty days from the
# seed clock is 2026-09-30T00:00:00Z.
BOND_CANCELLATION_DATE = C.iso_add_days(C.SEED_CLOCK, 60)

AUTHORIZATION_START = "2026-09-01T00:00:00Z"
AUTHORIZATION_END = "2026-09-30T00:00:00Z"


def _delegate(api, delegate_id):
    # Read a delegate row back through its own GET endpoint.
    return get_success_data(api.get_delegate(delegate_id, MANAGER_HEADERS))


def _authorization(api, authorization_id):
    # Read a delegate authorization row back through its own GET endpoint.
    return get_success_data(
        api.get_delegate_authorization(authorization_id, MANAGER_HEADERS)
    )


def _file_cancellation_notice(api, license_id):
    # File the surety's cancellation notice on an ACTIVE, bonded licence.
    return validate_success(
        api.file_bond_cancellation_notice(
            license_id,
            F.bond_cancellation_payload(BOND_CANCELLATION_DATE),
            MANAGER_HEADERS,
        )
    )


# ---------------------------------------------------------------------------
# The posture cascade out of an obligations adjustment
# ---------------------------------------------------------------------------


def test_obligation_spike_cascades_to_gate_authorization_and_delegate(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """One obligations delta drops the posture, blocks the gate, parks the authorization and suspends the delegate.

    PRD 3.4: "The adjustment then re-derives, in order: the licensee's `aggregate_outstanding_obligations_cents`, both permissible-investment values, `coverage_ratio_bps` and `coverage_posture`."
    PRD 3.4: "If the posture drops to `DEFICIENT` or `FROZEN`, the posture cascade of §2.9 runs."
    PRD 3.7: "Every other holding contributes an adjusted amount equal to its `market_value_cents` multiplied by 10000 minus its class haircut, divided by 10000 and rounded down at that step."
    PRD 3.7: "A coverage ratio in basis points is derived from an investment value the same way for both variants: it is exactly 10000 when the licensee's `aggregate_outstanding_obligations_cents` is zero, and otherwise the investment value multiplied by 10000, divided by the obligations, rounded down."
    PRD 3.7: "From it, and from `consecutive_failed_test_count`, the licensee's `coverage_posture` is determined by a strictly ordered test: the posture is `FROZEN` if `consecutive_failed_test_count` is at least 2, regardless of the ratio; otherwise `COMPLIANT` if `coverage_ratio_bps` is at least 10000; otherwise `WATCH` if `coverage_ratio_bps` is at least 9500; otherwise `DEFICIENT`."
    PRD 2.9: "The **posture cascade** begins whenever a licensee's `coverage_posture` becomes `DEFICIENT` or `FROZEN`."
    PRD 2.9: "Every `StateLicense` of that licensee whose `license_status` is `ACTIVE` has `expansion_gate` set to `BLOCKED`."
    PRD 2.9: "Every `DelegateAuthorization` of those licences whose `status` is `PENDING_OVERSIGHT` moves to `SUSPENDED_BY_POSTURE`."
    PRD 2.9: "Every `Delegate` that is left with no `ACTIVE` authorization has its `status` set to `SUSPENDED` and its `oversight_hold` set to true."
    PRD 3.6: "A new authorization starts in `PENDING_OVERSIGHT` and moves no counter — only activation makes a delegate count against the bond."

    Design: Difficulty/transitive_cascade/obligation_spike_cascades_posture_gate_authorization_and_delegate
    """
    fx.record_holding(
        api, active_license.licensee_id, "CASH", "First Coast Bank", 10_000_000, 10_000_000
    )
    delegate = fx.create_delegate(api, active_license.licensee_id)
    authorization = fx.create_authorization(
        api,
        delegate["id"],
        active_license.license_id,
        AUTHORIZATION_START,
        AUTHORIZATION_END,
    )
    assert authorization["status"] == "PENDING_OVERSIGHT"
    assert _delegate(api, delegate["id"])["status"] == "ONBOARDING"
    assert fx.get_license(api, active_license.license_id)["expansion_gate"] == "OPEN"

    licence = fx.adjust_obligations(
        api,
        active_license.license_id,
        85_000_000,
        memo="Quarter-end outstanding transmission liability",
    )
    assert licence["outstanding_obligations_cents"] == 85_000_000

    licensee = fx.get_licensee(api, active_license.licensee_id)
    # The single CA licence is the whole aggregate set.
    assert licensee["aggregate_outstanding_obligations_cents"] == 85_000_000
    # CASH carries no haircut, so the one holding contributes its full market value.
    assert licensee["eligible_investment_value_cents"] == 10_000_000
    # floor(10,000,000 * 10000 / 85,000,000) = 1176.
    assert licensee["coverage_ratio_bps"] == 1176
    # 1176 is below the 9500 WATCH floor.
    assert licensee["coverage_posture"] == "DEFICIENT"
    # The posture cascade moves no licence counter.
    assert licensee["active_license_count"] == 1

    licence = fx.get_license(api, active_license.license_id)
    assert licence["license_status"] == "ACTIVE"
    assert licence["expansion_gate"] == "BLOCKED"
    assert licence["active_delegate_count"] == 0

    parked = _authorization(api, authorization["id"])
    assert parked["status"] == "SUSPENDED_BY_POSTURE"
    assert parked["activated_at"] is None

    suspended_delegate = _delegate(api, delegate["id"])
    assert suspended_delegate["status"] == "SUSPENDED"
    assert suspended_delegate["oversight_hold"] is True
    # The authorization was never ACTIVE, so no state counter had been raised.
    assert suspended_delegate["authorized_state_count"] == 0


def test_obligation_move_into_the_watch_band_starts_no_cascade(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A move that only reaches WATCH leaves the gate open, the authorization pending and the delegate onboarding.

    PRD 3.7: "From it, and from `consecutive_failed_test_count`, the licensee's `coverage_posture` is determined by a strictly ordered test: the posture is `FROZEN` if `consecutive_failed_test_count` is at least 2, regardless of the ratio; otherwise `COMPLIANT` if `coverage_ratio_bps` is at least 10000; otherwise `WATCH` if `coverage_ratio_bps` is at least 9500; otherwise `DEFICIENT`."
    PRD 3.7: "The boundaries are exact: 10000 is `COMPLIANT`, 9999 is `WATCH`, 9500 is `WATCH`, 9499 is `DEFICIENT`."
    PRD 2.9: "The **posture cascade** begins whenever a licensee's `coverage_posture` becomes `DEFICIENT` or `FROZEN`."
    PRD 2.8: "It is `OPEN` exactly when all five of the following hold: `license_status` is `ACTIVE`, `bond_status` is `POSTED`, `reporting_status` is `CURRENT`, `exam_findings_open` is false, and the owning licensee's `coverage_posture` is either `COMPLIANT` or `WATCH`."
    PRD 3.4: "If the posture recovers to `COMPLIANT` or `WATCH`, `expansion_gate` is re-derived on every `ACTIVE` licence of the licensee against the five conditions of §2.8 — and that recovery is precisely what makes a `SUSPENDED_BY_POSTURE` authorization activatable again."

    Design: Difficulty/transitive_cascade/obligation_spike_cascades_posture_gate_authorization_and_delegate
    """
    fx.record_holding(
        api, active_license.licensee_id, "CASH", "First Coast Bank", 10_000_000, 10_000_000
    )
    delegate = fx.create_delegate(api, active_license.licensee_id)
    authorization = fx.create_authorization(
        api,
        delegate["id"],
        active_license.license_id,
        AUTHORIZATION_START,
        AUTHORIZATION_END,
    )

    fx.adjust_obligations(
        api,
        active_license.license_id,
        10_500_000,
        memo="Modest quarter-end transmission liability",
    )

    licensee = fx.get_licensee(api, active_license.licensee_id)
    assert licensee["aggregate_outstanding_obligations_cents"] == 10_500_000
    # floor(10,000,000 * 10000 / 10,500,000) = 9523, at or above the WATCH floor.
    assert licensee["coverage_ratio_bps"] == 9523
    assert licensee["coverage_posture"] == "WATCH"

    licence = fx.get_license(api, active_license.license_id)
    assert licence["license_status"] == "ACTIVE"
    assert licence["expansion_gate"] == "OPEN"

    untouched = _authorization(api, authorization["id"])
    assert untouched["status"] == "PENDING_OVERSIGHT"

    onboarding = _delegate(api, delegate["id"])
    assert onboarding["status"] == "ONBOARDING"
    assert onboarding["oversight_hold"] is False
    assert onboarding["authorized_state_count"] == 0


def test_posture_recovery_reopens_the_gate_and_makes_the_parked_authorization_activatable(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Recovery re-derives the gate and leaves the parked row activatable, which then un-suspends the delegate.

    PRD 3.4: "If the posture recovers to `COMPLIANT` or `WATCH`, `expansion_gate` is re-derived on every `ACTIVE` licence of the licensee against the five conditions of §2.8 — and that recovery is precisely what makes a `SUSPENDED_BY_POSTURE` authorization activatable again."
    PRD 3.6: "It is admissible from `PENDING_OVERSIGHT` or from `SUSPENDED_BY_POSTURE`, and from nothing else — an attempt from `ACTIVE`, `SUSPENDED` or `TERMINATED` is rejected with `ERR_AUTHORIZATION_INVALID_STATE`."
    PRD 3.6: "On success, and identically for both admissible source statuses, the authorization moves to `ACTIVE`, `activated_at` is stamped from the logical clock, and `oversight_score_at_activation` pins the delegate's `oversight_score` as it stood at that instant."
    PRD 3.6: "The licence's `active_delegate_count` increases by one and its `bond_requirement_cents` is recomputed with the new delegate count — which is how onboarding an agent can raise a bond requirement above the posted bond."
    PRD 3.6: "The first successful activation moves the delegate `ONBOARDING → ACTIVE`; an activation out of `SUSPENDED_BY_POSTURE` for a delegate that had been parked moves it `SUSPENDED → ACTIVE` and clears `oversight_hold` to false."
    PRD 3.6: "The resulting `oversight_score` is the training score weighted at 4000 basis points, plus the anti-money-laundering test score weighted at 3500 basis points, plus the recordkeeping score weighted at 2500 basis points, that sum divided by 10000 and rounded down to a whole number."

    Design: Difficulty/transitive_cascade/obligation_spike_cascades_posture_gate_authorization_and_delegate
    """
    fx.record_holding(
        api, active_license.licensee_id, "CASH", "First Coast Bank", 10_000_000, 10_000_000
    )
    delegate = fx.create_delegate(api, active_license.licensee_id)
    scored = fx.review_delegate(api, delegate["id"], 90, 85, 80)
    # (90*4000 + 85*3500 + 80*2500) / 10000 = 857500 / 10000, rounded down to 85.
    assert scored["oversight_score"] == 85
    authorization = fx.create_authorization(
        api,
        delegate["id"],
        active_license.license_id,
        AUTHORIZATION_START,
        AUTHORIZATION_END,
    )

    fx.adjust_obligations(
        api, active_license.license_id, 85_000_000, memo="Quarter-end liability"
    )
    assert (
        fx.get_licensee(api, active_license.licensee_id)["coverage_posture"]
        == "DEFICIENT"
    )
    assert _authorization(api, authorization["id"])["status"] == "SUSPENDED_BY_POSTURE"
    assert _delegate(api, delegate["id"])["status"] == "SUSPENDED"

    fx.adjust_obligations(
        api, active_license.license_id, -80_000_000, memo="Customer balances settled"
    )
    licensee = fx.get_licensee(api, active_license.licensee_id)
    assert licensee["aggregate_outstanding_obligations_cents"] == 5_000_000
    # floor(10,000,000 * 10000 / 5,000,000) = 20000, at or above 10000.
    assert licensee["coverage_ratio_bps"] == 20_000
    assert licensee["coverage_posture"] == "COMPLIANT"

    recovered = fx.get_license(api, active_license.license_id)
    assert recovered["expansion_gate"] == "OPEN"
    # Recovery re-derives the gate but does not itself reactivate the row.
    assert _authorization(api, authorization["id"])["status"] == "SUSPENDED_BY_POSTURE"
    still_parked = _delegate(api, delegate["id"])
    assert still_parked["status"] == "SUSPENDED"
    assert still_parked["oversight_hold"] is True

    activated = fx.activate_authorization(api, authorization["id"])
    assert activated["status"] == "ACTIVE"
    assert activated["oversight_score_at_activation"] == 85

    licence = fx.get_license(api, active_license.license_id)
    assert licence["active_delegate_count"] == 1
    # Volume is still zero, so tier one gives 2,500,000; one delegate at 100,000
    # makes 2,600,000, and the CA base floor of 5,000,000 is still greater.
    assert licence["bond_requirement_cents"] == 5_000_000

    working = _delegate(api, delegate["id"])
    assert working["status"] == "ACTIVE"
    assert working["oversight_hold"] is False
    assert working["authorized_state_count"] == 1


# ---------------------------------------------------------------------------
# The licence-suspension cascade out of a bond cancellation notice
# ---------------------------------------------------------------------------


def test_bond_cancellation_cascades_through_the_authorization_to_the_delegate(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """The notice suspends the licence, its ACTIVE authorization and the delegate left with no authorised state.

    PRD 3.4: "On acceptance, `bond_status` becomes `CANCELLATION_NOTICED`, the effective date is stored, and the licence moves `ACTIVE → SUSPENDED`, triggering the licence-suspension cascade of §2.9 in full."
    PRD 2.9: "The **licence-suspension cascade** begins whenever a licence moves from `ACTIVE` to `SUSPENDED`."
    PRD 2.9: "The licence's `expansion_gate` becomes `BLOCKED` and the licensee's `active_license_count` is reduced by one."
    PRD 2.9: "Every `DelegateAuthorization` of that licence whose `status` is `ACTIVE` moves to `SUSPENDED`, the licence's `active_delegate_count` is set to zero, and `bond_requirement_cents` is recomputed with a delegate count of zero."
    PRD 2.9: "For each suspended authorization, the owning `Delegate` has `authorized_state_count` reduced by one, and a delegate whose count reaches zero moves from `ACTIVE` to `SUSPENDED` with `oversight_hold` set to true."
    PRD 3.6: "When a licence is suspended by a bond cancellation notice or a consent order, every `ACTIVE` authorization of that licence moves to `SUSPENDED`, decrementing both counters and recomputing the bond requirement, and a delegate whose `authorized_state_count` reaches zero moves `ACTIVE → SUSPENDED` with `oversight_hold` true."

    Design: Difficulty/transitive_cascade/bond_cancellation_cascades_license_authorization_and_delegate
    """
    appointed = fx.setup_active_authorization(
        api, active_license, AUTHORIZATION_START, AUTHORIZATION_END
    )
    delegate_id = appointed["delegate"]["id"]
    authorization_id = appointed["authorization"]["id"]

    before_licence = fx.get_license(api, active_license.license_id)
    assert before_licence["license_status"] == "ACTIVE"
    assert before_licence["active_delegate_count"] == 1
    before_delegate = _delegate(api, delegate_id)
    assert before_delegate["status"] == "ACTIVE"
    assert before_delegate["authorized_state_count"] == 1
    assert before_delegate["oversight_hold"] is False
    assert fx.get_licensee(api, active_license.licensee_id)["active_license_count"] == 1

    notified = _file_cancellation_notice(api, active_license.license_id)
    assert notified["license_status"] == "SUSPENDED"
    assert notified["bond_status"] == "CANCELLATION_NOTICED"

    licence = fx.get_license(api, active_license.license_id)
    assert licence["license_status"] == "SUSPENDED"
    assert licence["bond_status"] == "CANCELLATION_NOTICED"
    assert licence["expansion_gate"] == "BLOCKED"
    assert licence["active_delegate_count"] == 0
    # Recomputed with a delegate count of zero: tier one 2,500,000 against the
    # CA base floor of 5,000,000, capped at 40,000,000.
    assert licence["bond_requirement_cents"] == 5_000_000

    licensee = fx.get_licensee(api, active_license.licensee_id)
    assert licensee["active_license_count"] == 0

    suspended_authorization = _authorization(api, authorization_id)
    assert suspended_authorization["status"] == "SUSPENDED"

    delegate = _delegate(api, delegate_id)
    assert delegate["status"] == "SUSPENDED"
    assert delegate["oversight_hold"] is True
    assert delegate["authorized_state_count"] == 0
    # The cascade suspends; it does not re-score the agent.
    assert delegate["oversight_score"] == 85


def test_bond_cancellation_stops_at_the_authorization_when_another_state_still_holds_the_delegate(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """With a second authorised state the delegate keeps working, and only the cancelled licence's chain moves.

    PRD 2.9: "Every `DelegateAuthorization` of that licence whose `status` is `ACTIVE` moves to `SUSPENDED`, the licence's `active_delegate_count` is set to zero, and `bond_requirement_cents` is recomputed with a delegate count of zero."
    PRD 2.9: "For each suspended authorization, the owning `Delegate` has `authorized_state_count` reduced by one, and a delegate whose count reaches zero moves from `ACTIVE` to `SUSPENDED` with `oversight_hold` set to true."
    PRD 2.9: "This cascade is three levels deep."
    PRD 3.4: "On acceptance, `bond_status` becomes `CANCELLATION_NOTICED`, the effective date is stored, and the licence moves `ACTIVE → SUSPENDED`, triggering the licence-suspension cascade of §2.9 in full."
    PRD 3.6: "The delegate's `authorized_state_count` increases by one."

    Design: Difficulty/transitive_cascade/bond_cancellation_cascades_license_authorization_and_delegate
    """
    second = fx.add_license_in_jurisdiction(
        api, active_license.licensee_id, C.TX_CONFIG
    )
    texas_license_id = second["license"]["id"]

    delegate = fx.create_delegate(api, active_license.licensee_id)
    fx.review_delegate(api, delegate["id"], 90, 85, 80)
    california_authorization = fx.create_authorization(
        api,
        delegate["id"],
        active_license.license_id,
        AUTHORIZATION_START,
        AUTHORIZATION_END,
    )
    fx.activate_authorization(api, california_authorization["id"])
    texas_authorization = fx.create_authorization(
        api, delegate["id"], texas_license_id, AUTHORIZATION_START, AUTHORIZATION_END
    )
    fx.activate_authorization(api, texas_authorization["id"])

    before = _delegate(api, delegate["id"])
    assert before["status"] == "ACTIVE"
    # One activation in California and one in Texas.
    assert before["authorized_state_count"] == 2
    assert fx.get_licensee(api, active_license.licensee_id)["active_license_count"] == 2

    _file_cancellation_notice(api, active_license.license_id)

    california = fx.get_license(api, active_license.license_id)
    assert california["license_status"] == "SUSPENDED"
    assert california["bond_status"] == "CANCELLATION_NOTICED"
    assert california["expansion_gate"] == "BLOCKED"
    assert california["active_delegate_count"] == 0
    assert _authorization(api, california_authorization["id"])["status"] == "SUSPENDED"

    delegate_row = _delegate(api, delegate["id"])
    # 2 authorised states less the one that was suspended.
    assert delegate_row["authorized_state_count"] == 1
    assert delegate_row["status"] == "ACTIVE"
    assert delegate_row["oversight_hold"] is False

    texas = fx.get_license(api, texas_license_id)
    assert texas["license_status"] == "ACTIVE"
    assert texas["bond_status"] == "POSTED"
    assert texas["expansion_gate"] == "OPEN"
    assert texas["active_delegate_count"] == 1
    # Texas keeps its own count: tier one 2,500,000 plus 250,000 for one
    # delegate is under the 30,000,000 Texas base floor.
    assert texas["bond_requirement_cents"] == 30_000_000
    assert _authorization(api, texas_authorization["id"])["status"] == "ACTIVE"

    licensee = fx.get_licensee(api, active_license.licensee_id)
    assert licensee["active_license_count"] == 1
