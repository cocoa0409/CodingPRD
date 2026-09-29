"""Compensating invariants: excursion, compensation, and exact restoration.

Two conserved quantities are exercised here. The first is money: the licensee's
``aggregate_outstanding_obligations_cents`` together with the coverage ratio and
posture it drives, walked up by obligation adjustments and walked back down by
the exact opposite deltas. The second is the counter triple
``(active_delegate_count, authorized_state_count, bond_requirement_cents)``,
raised by activating a delegate authorization and restored by terminating it.

Every test captures the pre-state, walks the excursion, walks the compensating
action, and then asserts the restored figures exactly — while also asserting
that the ``version`` of each row the cascade touched advanced, so a restored
value can never be confused with an event that never happened.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import MoneyTransmitterApiClient
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_NEGATIVE_OBLIGATIONS
from test_helpers.test_users import MANAGER_HEADERS

# ---------------------------------------------------------------------------
# obligation_aggregate_and_posture_reconcile_after_full_reversal
# ---------------------------------------------------------------------------


def test_obligation_aggregate_returns_to_zero_after_both_deltas_are_reversed(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Two licences take on obligations and give them back; the aggregate lands on 0.

    PRD 3.4: "The aggregate itself is the exact sum, in integer cents with no rounding, of `outstanding_obligations_cents` over the licensee's licences whose `license_status` is `PENDING_BOND`, `ACTIVE`, `SUSPENDED` or `SURRENDER_REQUESTED`."
    PRD 3.4: "There is no time window and the sum is order-insensitive."
    PRD 3.4: "The delta is added to the licence's `outstanding_obligations_cents`, and the resulting balance may never go below zero — an adjustment that would drive it negative is rejected with `ERR_NEGATIVE_OBLIGATIONS` (HTTP 422)."
    PRD 3.4: "Both the licence's `version` and the licensee's `version` are bumped."
    PRD 2.9: "Compensating actions restore counters to the exact values that held before the action they compensate."

    Design: Difficulty/compensating_invariant/obligation_aggregate_and_posture_reconcile_after_full_reversal
    """
    licensee_id = active_license.licensee_id
    ca_license_id = active_license.license_id
    tx = fx.add_license_in_jurisdiction(api, licensee_id, C.TX_CONFIG)
    tx_license_id = tx["license"]["id"]

    # Pre-state: a two-licence estate that owes nothing at all.
    licensee_before = fx.get_licensee(api, licensee_id)
    ca_before = fx.get_license(api, ca_license_id)
    tx_before = fx.get_license(api, tx_license_id)
    assert licensee_before["aggregate_outstanding_obligations_cents"] == 0
    assert ca_before["outstanding_obligations_cents"] == 0
    assert tx_before["outstanding_obligations_cents"] == 0

    # Excursion, call 1: the CA licence takes on settlement float.
    ca_up = validate_success(
        api.adjust_obligations(
            ca_license_id,
            F.obligations_payload(6_024_000, memo="CA settlement float"),
            MANAGER_HEADERS,
        )
    )
    assert ca_up["outstanding_obligations_cents"] == 6_024_000  # 0 + 6024000
    after_one = fx.get_licensee(api, licensee_id)
    # 6024000 (CA) + 0 (TX)
    assert after_one["aggregate_outstanding_obligations_cents"] == 6_024_000

    # Excursion, call 2: the TX licence takes on its own float.
    tx_up = validate_success(
        api.adjust_obligations(
            tx_license_id,
            F.obligations_payload(2_515_000, memo="TX settlement float"),
            MANAGER_HEADERS,
        )
    )
    assert tx_up["outstanding_obligations_cents"] == 2_515_000  # 0 + 2515000
    after_two = fx.get_licensee(api, licensee_id)
    # 6024000 (CA) + 2515000 (TX)
    assert after_two["aggregate_outstanding_obligations_cents"] == 8_539_000

    # Compensation, call 3: the CA float settles at exactly the amount taken on.
    ca_down = validate_success(
        api.adjust_obligations(
            ca_license_id,
            F.obligations_payload(-6_024_000, memo="CA float settled"),
            MANAGER_HEADERS,
        )
    )
    assert ca_down["outstanding_obligations_cents"] == 0  # 6024000 - 6024000
    after_three = fx.get_licensee(api, licensee_id)
    # 0 (CA) + 2515000 (TX) — the TX residue is still counted, nothing else is
    assert after_three["aggregate_outstanding_obligations_cents"] == 2_515_000

    # Compensation, call 4: the TX float settles too.
    tx_down = validate_success(
        api.adjust_obligations(
            tx_license_id,
            F.obligations_payload(-2_515_000, memo="TX float settled"),
            MANAGER_HEADERS,
        )
    )
    assert tx_down["outstanding_obligations_cents"] == 0  # 2515000 - 2515000

    # Restored exactly: aggregate 0, the vacuous ratio, and COMPLIANT again.
    licensee_after = fx.get_licensee(api, licensee_id)
    assert licensee_after["aggregate_outstanding_obligations_cents"] == 0  # 0 + 0
    assert licensee_after["coverage_ratio_bps"] == 10_000
    assert licensee_after["coverage_posture"] == "COMPLIANT"
    assert fx.get_license(api, ca_license_id)["outstanding_obligations_cents"] == 0
    assert fx.get_license(api, tx_license_id)["outstanding_obligations_cents"] == 0

    # The restoration is the product of four real mutations, not of inaction.
    assert licensee_after["version"] > licensee_before["version"]
    assert ca_down["version"] > ca_before["version"]
    assert tx_down["version"] > tx_before["version"]


def test_posture_and_expansion_gates_recover_when_the_float_is_fully_settled(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A DEFICIENT excursion with both gates BLOCKED unwinds to COMPLIANT with both gates OPEN.

    PRD 3.4: "The adjustment then re-derives, in order: the licensee's `aggregate_outstanding_obligations_cents`, both permissible-investment values, `coverage_ratio_bps` and `coverage_posture`."
    PRD 3.4: "If the posture recovers to `COMPLIANT` or `WATCH`, `expansion_gate` is re-derived on every `ACTIVE` licence of the licensee against the five conditions of §2.8 — and that recovery is precisely what makes a `SUSPENDED_BY_POSTURE` authorization activatable again."
    PRD 2.9: "The **posture cascade** begins whenever a licensee's `coverage_posture` becomes `DEFICIENT` or `FROZEN`."
    PRD 2.9: "Every `StateLicense` of that licensee whose `license_status` is `ACTIVE` has `expansion_gate` set to `BLOCKED`."
    PRD 3.7: "A coverage ratio in basis points is derived from an investment value the same way for both variants: it is exactly 10000 when the licensee's `aggregate_outstanding_obligations_cents` is zero, and otherwise the investment value multiplied by 10000, divided by the obligations, rounded down."
    PRD 3.7: "From it, and from `consecutive_failed_test_count`, the licensee's `coverage_posture` is determined by a strictly ordered test: the posture is `FROZEN` if `consecutive_failed_test_count` is at least 2, regardless of the ratio; otherwise `COMPLIANT` if `coverage_ratio_bps` is at least 10000; otherwise `WATCH` if `coverage_ratio_bps` is at least 9500; otherwise `DEFICIENT`."

    Design: Difficulty/compensating_invariant/obligation_aggregate_and_posture_reconcile_after_full_reversal
    """
    licensee_id = active_license.licensee_id
    ca_license_id = active_license.license_id
    tx = fx.add_license_in_jurisdiction(api, licensee_id, C.TX_CONFIG)
    tx_license_id = tx["license"]["id"]

    # Pre-state: no obligations, no holdings, a vacuously perfect ratio and
    # both bonded licences open for growth.
    licensee_before = fx.get_licensee(api, licensee_id)
    ca_before = fx.get_license(api, ca_license_id)
    tx_before = fx.get_license(api, tx_license_id)
    assert licensee_before["coverage_ratio_bps"] == 10_000
    assert licensee_before["coverage_posture"] == "COMPLIANT"
    assert ca_before["expansion_gate"] == "OPEN"
    assert tx_before["expansion_gate"] == "OPEN"

    # Excursion: obligations with no permissible investments behind them.
    fx.adjust_obligations(api, ca_license_id, 6_024_000, memo="CA settlement float")
    fx.adjust_obligations(api, tx_license_id, 2_515_000, memo="TX settlement float")

    licensee_deficient = fx.get_licensee(api, licensee_id)
    # 6024000 + 2515000
    assert licensee_deficient["aggregate_outstanding_obligations_cents"] == 8_539_000
    # floor(0 * 10000 / 8539000) — no holdings, so no eligible value at all
    assert licensee_deficient["coverage_ratio_bps"] == 0
    # 0 bps is below the 9500 WATCH floor
    assert licensee_deficient["coverage_posture"] == "DEFICIENT"
    assert fx.get_license(api, ca_license_id)["expansion_gate"] == "BLOCKED"
    assert fx.get_license(api, tx_license_id)["expansion_gate"] == "BLOCKED"

    summary_deficient = fx.get_coverage_summary(api, licensee_id)
    assert summary_deficient["obligations_cents"] == 8_539_000
    assert summary_deficient["eligible_investment_value_cents"] == 0
    assert summary_deficient["book_investment_value_cents"] == 0
    # floor(8539000 * 1000 / 10000)
    assert summary_deficient["concentration_cap_cents"] == 853_900
    assert summary_deficient["coverage_ratio_bps"] == 0
    assert summary_deficient["coverage_posture"] == "DEFICIENT"

    # Compensation: the two exact opposite deltas.
    fx.adjust_obligations(api, ca_license_id, -6_024_000, memo="CA float settled")
    fx.adjust_obligations(api, tx_license_id, -2_515_000, memo="TX float settled")

    licensee_after = fx.get_licensee(api, licensee_id)
    assert licensee_after["aggregate_outstanding_obligations_cents"] == 0  # 0 + 0
    assert licensee_after["coverage_ratio_bps"] == 10_000
    assert licensee_after["coverage_posture"] == "COMPLIANT"
    assert licensee_after["consecutive_failed_test_count"] == 0

    ca_after = fx.get_license(api, ca_license_id)
    tx_after = fx.get_license(api, tx_license_id)
    assert ca_after["expansion_gate"] == "OPEN"
    assert tx_after["expansion_gate"] == "OPEN"
    assert ca_after["license_status"] == "ACTIVE"
    assert tx_after["license_status"] == "ACTIVE"

    summary_after = fx.get_coverage_summary(api, licensee_id)
    assert summary_after["obligations_cents"] == 0
    assert summary_after["coverage_ratio_bps"] == 10_000
    # floor(0 * 1000 / 10000)
    assert summary_after["concentration_cap_cents"] == 0
    assert summary_after["coverage_posture"] == "COMPLIANT"

    # Four adjustments and one posture cascade really did move these rows.
    assert licensee_after["version"] > licensee_before["version"]
    assert ca_after["version"] > ca_before["version"]
    assert tx_after["version"] > tx_before["version"]


def test_a_refused_over_reversal_leaves_no_residue_before_the_exact_reversal_lands(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """An adjustment that would drive one licence negative changes nothing; the exact reversal still restores 0.

    PRD 3.4: "The delta is added to the licence's `outstanding_obligations_cents`, and the resulting balance may never go below zero — an adjustment that would drive it negative is rejected with `ERR_NEGATIVE_OBLIGATIONS` (HTTP 422)."
    PRD 3.4: "The aggregate itself is the exact sum, in integer cents with no rounding, of `outstanding_obligations_cents` over the licensee's licences whose `license_status` is `PENDING_BOND`, `ACTIVE`, `SUSPENDED` or `SURRENDER_REQUESTED`."
    PRD 2.9: "Compensating actions restore counters to the exact values that held before the action they compensate."
    PRD 3.4: "Both the licence's `version` and the licensee's `version` are bumped."

    Design: Difficulty/compensating_invariant/obligation_aggregate_and_posture_reconcile_after_full_reversal
    """
    licensee_id = active_license.licensee_id
    ca_license_id = active_license.license_id
    tx = fx.add_license_in_jurisdiction(api, licensee_id, C.TX_CONFIG)
    tx_license_id = tx["license"]["id"]

    licensee_before = fx.get_licensee(api, licensee_id)
    assert licensee_before["aggregate_outstanding_obligations_cents"] == 0

    # Excursion: 6024000 on CA, 2515000 on TX.
    fx.adjust_obligations(api, ca_license_id, 6_024_000, memo="CA settlement float")
    fx.adjust_obligations(api, tx_license_id, 2_515_000, memo="TX settlement float")
    ca_excursion = fx.get_license(api, ca_license_id)
    assert ca_excursion["outstanding_obligations_cents"] == 6_024_000

    # The whole aggregate may not be settled against one licence: the per-licence
    # balance, not the estate-wide total, is what may never go below zero.
    validate_error(
        api.adjust_obligations(
            ca_license_id,
            F.obligations_payload(-8_539_000, memo="Settle the whole estate on CA"),
            MANAGER_HEADERS,
        ),
        ERR_NEGATIVE_OBLIGATIONS,
    )
    ca_refused = fx.get_license(api, ca_license_id)
    assert ca_refused["outstanding_obligations_cents"] == 6_024_000  # untouched
    assert ca_refused["version"] == ca_excursion["version"]
    licensee_refused = fx.get_licensee(api, licensee_id)
    # 6024000 + 2515000 — the rejected call left no residue in the aggregate
    assert licensee_refused["aggregate_outstanding_obligations_cents"] == 8_539_000

    # Compensation: each licence gives back exactly what it took on.
    fx.adjust_obligations(api, ca_license_id, -6_024_000, memo="CA float settled")
    fx.adjust_obligations(api, tx_license_id, -2_515_000, memo="TX float settled")

    licensee_after = fx.get_licensee(api, licensee_id)
    assert licensee_after["aggregate_outstanding_obligations_cents"] == 0  # 0 + 0
    assert licensee_after["coverage_ratio_bps"] == 10_000
    assert licensee_after["coverage_posture"] == "COMPLIANT"

    ca_after = fx.get_license(api, ca_license_id)
    tx_after = fx.get_license(api, tx_license_id)
    assert ca_after["outstanding_obligations_cents"] == 0
    assert tx_after["outstanding_obligations_cents"] == 0
    assert licensee_after["version"] > licensee_before["version"]
    assert ca_after["version"] > ca_excursion["version"]
    assert tx_after["version"] > tx["license"]["version"]


# ---------------------------------------------------------------------------
# delegate_counters_and_bond_requirement_restore_after_termination
# ---------------------------------------------------------------------------


def _tier_two_ca_license(api: MoneyTransmitterApiClient) -> fx.Scenario:
    """A bonded CA licence whose licence-context bond tier is the 10000000 band.

    The bond is posted at 10000000 cents while the requirement is still the
    tier-one figure, and a timely quarterly call report of 1500000000 cents then
    lifts ``annual_volume_cents`` above one billion so the licence-context
    requirement becomes the tier-two figure. Filing 2026Q2 at the seed clock is
    on time: its period ends 2026-06-30 and it is due forty-five days later, on
    2026-08-14.
    """
    scenario = fx.setup_active_license(api, bond_amount_cents=10_000_000)
    report = fx.file_call_report(api, scenario.license_id, "2026Q2", 1_500_000_000, 1_200)
    scenario.extra["call_report"] = report
    return scenario


def test_terminating_an_active_authorization_restores_the_counter_triple(
    api: MoneyTransmitterApiClient
) -> None:
    """Activation lifts the CA bond requirement to 10100000 and both counters to 1; termination puts all three back.

    PRD 3.4: "Step two takes the greater of the jurisdiction's `base_bond_cents` and the sum of the tier bond plus the delegate count multiplied by the jurisdiction's `per_delegate_bond_cents`; the delegate count is zero in an application context and the licence's `active_delegate_count` otherwise."
    PRD 3.5: "Regardless of status, every filing adds its `transmission_volume_cents` to the licence's `annual_volume_cents` and recomputes `bond_requirement_cents`, since the volume tier may have moved."
    PRD 3.6: "The licence's `active_delegate_count` increases by one and its `bond_requirement_cents` is recomputed with the new delegate count — which is how onboarding an agent can raise a bond requirement above the posted bond."
    PRD 3.6: "The delegate's `authorized_state_count` increases by one."
    PRD 3.6: "If it had been `ACTIVE`, the licence's `active_delegate_count` and the delegate's `authorized_state_count` each drop by one and `bond_requirement_cents` is recomputed with the reduced count, restoring exactly the values that held before activation; and a delegate left with no non-`TERMINATED` authorization at all moves to the terminal `TERMINATED`."
    PRD 2.9: "Terminating an authorization that was `ACTIVE` reduces both `active_delegate_count` and `authorized_state_count` by one and recomputes `bond_requirement_cents`, returning all three to their pre-activation values."

    Design: Difficulty/compensating_invariant/delegate_counters_and_bond_requirement_restore_after_termination
    """
    scenario = _tier_two_ca_license(api)
    report = scenario.extra["call_report"]
    assert report["status"] == "FILED"  # clock 2026-08-01 is before due_at 2026-08-14
    # round_half_up(1500000000 * 25 / 10000) with CA's assessment_rate_bps of 25
    assert report["assessment_fee_cents"] == 3_750_000

    delegate = fx.create_delegate(api, scenario.licensee_id)
    # floor((90 * 4000 + 90 * 3500 + 70 * 2500) / 10000) = floor(850000 / 10000)
    delegate = fx.review_delegate(api, delegate["id"], 90, 90, 70)
    assert delegate["oversight_score"] == 85
    authorization = fx.create_authorization(
        api, delegate["id"], scenario.license_id, "2026-09-01T00:00:00Z", "2027-08-31T00:00:00Z"
    )
    assert authorization["status"] == "PENDING_OVERSIGHT"

    # Pre-state: the whole triple before any delegate counts against the bond.
    license_before = fx.get_license(api, scenario.license_id)
    assert license_before["active_delegate_count"] == 0
    # max(5000000, 10000000 + 0 * 100000) = 10000000, times 10000/10000, capped at 40000000
    assert license_before["bond_requirement_cents"] == 10_000_000
    assert license_before["bond_posted_cents"] == 10_000_000
    assert license_before["bond_status"] == "POSTED"
    assert license_before["reporting_status"] == "CURRENT"
    assert license_before["expansion_gate"] == "OPEN"
    delegate_before = validate_success(api.get_delegate(delegate["id"], MANAGER_HEADERS))
    assert delegate_before["authorized_state_count"] == 0
    assert delegate_before["status"] == "ONBOARDING"

    # Excursion: activation.
    activated = validate_success(
        api.activate_authorization(authorization["id"], MANAGER_HEADERS)
    )
    assert activated["status"] == "ACTIVE"
    assert activated["activated_at"] is not None
    assert activated["oversight_score_at_activation"] == 85

    license_active = fx.get_license(api, scenario.license_id)
    assert license_active["active_delegate_count"] == 1  # 0 + 1
    # max(5000000, 10000000 + 1 * 100000) = 10100000, times 10000/10000, under the cap
    assert license_active["bond_requirement_cents"] == 10_100_000
    assert license_active["bond_posted_cents"] == 10_000_000  # the posted bond never moves
    delegate_active = validate_success(api.get_delegate(delegate["id"], MANAGER_HEADERS))
    assert delegate_active["authorized_state_count"] == 1  # 0 + 1
    assert delegate_active["status"] == "ACTIVE"

    # Compensation: termination of the very authorization that was activated.
    terminated = validate_success(
        api.terminate_authorization(
            authorization["id"],
            MANAGER_HEADERS,
            F.terminate_authorization_payload(reason="Agent contract wound down."),
        )
    )
    assert terminated["status"] == "TERMINATED"
    # The audit trail is not rewound even though the counters are.
    assert terminated["activated_at"] == activated["activated_at"]
    assert terminated["oversight_score_at_activation"] == 85

    license_after = fx.get_license(api, scenario.license_id)
    assert license_after["active_delegate_count"] == 0  # 1 - 1, the pre-activation value
    # max(5000000, 10000000 + 0 * 100000) = 10000000 again
    assert license_after["bond_requirement_cents"] == 10_000_000
    assert license_after["bond_posted_cents"] == 10_000_000
    assert license_after["bond_status"] == "POSTED"
    assert license_after["license_status"] == "ACTIVE"

    delegate_after = validate_success(api.get_delegate(delegate["id"], MANAGER_HEADERS))
    assert delegate_after["authorized_state_count"] == 0  # 1 - 1
    # No non-TERMINATED authorization is left anywhere for this agent.
    assert delegate_after["status"] == "TERMINATED"

    # Every row the chain touched advanced: this is restoration, not inaction.
    assert license_after["version"] > license_before["version"]
    assert delegate_after["version"] > delegate_before["version"]
    assert terminated["version"] > activated["version"]
    assert activated["version"] > authorization["version"]


def test_terminating_a_pending_oversight_authorization_moves_no_counter(
    api: MoneyTransmitterApiClient
) -> None:
    """A never-activated authorization terminates without disturbing the triple the activated one owns.

    PRD 3.6: "A new authorization starts in `PENDING_OVERSIGHT` and moves no counter — only activation makes a delegate count against the bond."
    PRD 3.6: "If it had only been `PENDING_OVERSIGHT`, no counter moves, because the row was never counted."
    PRD 2.9: "Terminating an authorization that was only `PENDING_OVERSIGHT` moves no counter at all, because the row never counted."
    PRD 2.9: "Terminating an authorization that was `ACTIVE` reduces both `active_delegate_count` and `authorized_state_count` by one and recomputes `bond_requirement_cents`, returning all three to their pre-activation values."
    PRD 3.4: "Step two takes the greater of the jurisdiction's `base_bond_cents` and the sum of the tier bond plus the delegate count multiplied by the jurisdiction's `per_delegate_bond_cents`; the delegate count is zero in an application context and the licence's `active_delegate_count` otherwise."

    Design: Difficulty/compensating_invariant/delegate_counters_and_bond_requirement_restore_after_termination
    """
    scenario = _tier_two_ca_license(api)
    delegate = fx.create_delegate(api, scenario.licensee_id)
    fx.review_delegate(api, delegate["id"], 90, 90, 70)  # oversight_score 85

    license_before = fx.get_license(api, scenario.license_id)
    assert license_before["active_delegate_count"] == 0
    assert license_before["bond_requirement_cents"] == 10_000_000  # max(5000000, 10000000)

    # Excursion: one activated authorization for the 2026-09-01 .. 2027-08-31 period.
    activated_auth = fx.create_authorization(
        api, delegate["id"], scenario.license_id, "2026-09-01T00:00:00Z", "2027-08-31T00:00:00Z"
    )
    activated_auth = fx.activate_authorization(api, activated_auth["id"])
    assert activated_auth["status"] == "ACTIVE"
    license_active = fx.get_license(api, scenario.license_id)
    assert license_active["active_delegate_count"] == 1  # 0 + 1
    # max(5000000, 10000000 + 1 * 100000)
    assert license_active["bond_requirement_cents"] == 10_100_000

    # A second authorization for a later, non-touching period is left parked.
    parked_auth = fx.create_authorization(
        api, delegate["id"], scenario.license_id, "2027-09-02T00:00:00Z", "2027-12-31T00:00:00Z"
    )
    assert parked_auth["status"] == "PENDING_OVERSIGHT"
    assert parked_auth["activated_at"] is None
    assert parked_auth["oversight_score_at_activation"] is None
    license_parked = fx.get_license(api, scenario.license_id)
    assert license_parked["active_delegate_count"] == 1  # creation moved no counter
    assert license_parked["bond_requirement_cents"] == 10_100_000

    # Terminating the parked row compensates nothing, because nothing counted.
    parked_terminated = validate_success(
        api.terminate_authorization(
            parked_auth["id"],
            MANAGER_HEADERS,
            F.terminate_authorization_payload(reason="Period never opened."),
        )
    )
    assert parked_terminated["status"] == "TERMINATED"
    assert parked_terminated["activated_at"] is None
    assert parked_terminated["version"] > parked_auth["version"]

    license_still_active = fx.get_license(api, scenario.license_id)
    assert license_still_active["active_delegate_count"] == 1  # unchanged
    assert license_still_active["bond_requirement_cents"] == 10_100_000  # unchanged
    delegate_still_active = validate_success(api.get_delegate(delegate["id"], MANAGER_HEADERS))
    assert delegate_still_active["authorized_state_count"] == 1  # unchanged
    # One ACTIVE authorization remains, so the agent keeps working.
    assert delegate_still_active["status"] == "ACTIVE"

    # Compensation: terminating the authorization that really was ACTIVE.
    activated_terminated = validate_success(
        api.terminate_authorization(
            activated_auth["id"],
            MANAGER_HEADERS,
            F.terminate_authorization_payload(reason="Agent contract wound down."),
        )
    )
    assert activated_terminated["status"] == "TERMINATED"

    license_after = fx.get_license(api, scenario.license_id)
    assert license_after["active_delegate_count"] == 0  # 1 - 1
    # max(5000000, 10000000 + 0 * 100000) — exactly the pre-activation figure
    assert license_after["bond_requirement_cents"] == 10_000_000
    assert license_after["bond_posted_cents"] == 10_000_000
    assert license_after["bond_status"] == "POSTED"
    delegate_after = validate_success(api.get_delegate(delegate["id"], MANAGER_HEADERS))
    assert delegate_after["authorized_state_count"] == 0  # 1 - 1
    assert delegate_after["status"] == "TERMINATED"

    assert license_after["version"] > license_before["version"]
    assert delegate_after["version"] > delegate_still_active["version"]
    assert activated_terminated["version"] > activated_auth["version"]


def test_two_activations_unwind_one_delegate_at_a_time_to_the_pre_activation_bond(
    api: MoneyTransmitterApiClient
) -> None:
    """Two agents lift the requirement to 10200000; terminating them one by one steps it back to 10000000.

    PRD 3.4: "Step two takes the greater of the jurisdiction's `base_bond_cents` and the sum of the tier bond plus the delegate count multiplied by the jurisdiction's `per_delegate_bond_cents`; the delegate count is zero in an application context and the licence's `active_delegate_count` otherwise."
    PRD 3.4: "Step four takes the lesser of that result and the jurisdiction's `bond_cap_cents`."
    PRD 3.6: "The licence's `active_delegate_count` increases by one and its `bond_requirement_cents` is recomputed with the new delegate count — which is how onboarding an agent can raise a bond requirement above the posted bond."
    PRD 3.6: "If it had been `ACTIVE`, the licence's `active_delegate_count` and the delegate's `authorized_state_count` each drop by one and `bond_requirement_cents` is recomputed with the reduced count, restoring exactly the values that held before activation; and a delegate left with no non-`TERMINATED` authorization at all moves to the terminal `TERMINATED`."
    PRD 2.9: "Compensating actions restore counters to the exact values that held before the action they compensate."

    Design: Difficulty/compensating_invariant/delegate_counters_and_bond_requirement_restore_after_termination
    """
    scenario = _tier_two_ca_license(api)

    license_before = fx.get_license(api, scenario.license_id)
    assert license_before["active_delegate_count"] == 0
    # max(5000000, 10000000 + 0 * 100000) = 10000000, under the 40000000 cap
    assert license_before["bond_requirement_cents"] == 10_000_000

    first = fx.create_delegate(api, scenario.licensee_id)
    fx.review_delegate(api, first["id"], 90, 90, 70)  # oversight_score 85
    second = fx.create_delegate(
        api, scenario.licensee_id, legal_name=C.SEED_SECOND_DELEGATE_NAME
    )
    fx.review_delegate(api, second["id"], 90, 90, 70)  # oversight_score 85

    first_auth = fx.create_authorization(
        api, first["id"], scenario.license_id, "2026-09-01T00:00:00Z", "2027-08-31T00:00:00Z"
    )
    second_auth = fx.create_authorization(
        api, second["id"], scenario.license_id, "2026-09-01T00:00:00Z", "2027-08-31T00:00:00Z"
    )

    # Excursion, first activation.
    first_auth = fx.activate_authorization(api, first_auth["id"])
    license_one = fx.get_license(api, scenario.license_id)
    assert license_one["active_delegate_count"] == 1  # 0 + 1
    # max(5000000, 10000000 + 1 * 100000)
    assert license_one["bond_requirement_cents"] == 10_100_000

    # Excursion, second activation.
    second_auth = fx.activate_authorization(api, second_auth["id"])
    license_two = fx.get_license(api, scenario.license_id)
    assert license_two["active_delegate_count"] == 2  # 1 + 1
    # max(5000000, 10000000 + 2 * 100000)
    assert license_two["bond_requirement_cents"] == 10_200_000

    # Compensation, in reverse order: each termination steps back exactly one delegate.
    second_terminated = validate_success(
        api.terminate_authorization(
            second_auth["id"],
            MANAGER_HEADERS,
            F.terminate_authorization_payload(reason="Second agent released."),
        )
    )
    assert second_terminated["status"] == "TERMINATED"
    license_back_to_one = fx.get_license(api, scenario.license_id)
    assert license_back_to_one["active_delegate_count"] == 1  # 2 - 1
    # max(5000000, 10000000 + 1 * 100000) — exactly the one-delegate figure again
    assert license_back_to_one["bond_requirement_cents"] == 10_100_000
    second_after = validate_success(api.get_delegate(second["id"], MANAGER_HEADERS))
    assert second_after["authorized_state_count"] == 0  # 1 - 1
    assert second_after["status"] == "TERMINATED"
    first_still = validate_success(api.get_delegate(first["id"], MANAGER_HEADERS))
    assert first_still["authorized_state_count"] == 1  # untouched by the other agent
    assert first_still["status"] == "ACTIVE"

    first_terminated = validate_success(
        api.terminate_authorization(
            first_auth["id"],
            MANAGER_HEADERS,
            F.terminate_authorization_payload(reason="First agent released."),
        )
    )
    assert first_terminated["status"] == "TERMINATED"
    license_after = fx.get_license(api, scenario.license_id)
    assert license_after["active_delegate_count"] == 0  # 1 - 1
    # max(5000000, 10000000 + 0 * 100000) — the pre-activation requirement exactly
    assert license_after["bond_requirement_cents"] == 10_000_000
    assert license_after["bond_posted_cents"] == 10_000_000
    assert license_after["bond_status"] == "POSTED"
    assert license_after["license_status"] == "ACTIVE"
    first_after = validate_success(api.get_delegate(first["id"], MANAGER_HEADERS))
    assert first_after["authorized_state_count"] == 0  # 1 - 1
    assert first_after["status"] == "TERMINATED"

    # Four counter-moving events touched the licence and both agents.
    assert license_after["version"] > license_before["version"]
    assert first_after["version"] > first_still["version"]
    assert second_after["version"] > second["version"]
    assert first_terminated["version"] > first_auth["version"]
    assert second_terminated["version"] > second_auth["version"]
