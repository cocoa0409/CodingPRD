"""Which of two simultaneously violated bind guards wins the response."""

from test_helpers import (
    ApiErrorId,
    bind_policy,
    bind_policy_ok,
    patch_agent_ok,
    read_ledger,
    read_policy,
    read_pool,
    read_recommendations,
    reservation_by_peril,
    setup_rated_dwelling_policy,
    setup_suspended_compliance_policy,
    upsert_labor_profile,
    validate_error,
)

CREW_OF_EIGHT = {"full_time_count": 4, "seasonal_count": 4, "migrant_h2a_count": 0}


def test_rebinding_a_bound_policy_reports_the_state_conflict_not_the_authority_gap(api):
    """"The first violated rule determines the response; no later check is
    evaluated, and no side effect of any kind is applied when a check fails."
    A second bind against an already `BOUND` policy whose producer has meanwhile
    been re-authorised down to 100000 cents violates both the state guard at
    priority nine and the fiscal guard at priority fifteen, so the answer is
    `ERR_POLICY_NOT_RATED` and never `ERR_AGENT_AUTHORITY_EXCEEDED`.

    Design: Difficulty/priority_pair_validation_conflict/bind_state_conflict_outranks_authority_limit
    """
    scenario = setup_rated_dwelling_policy()
    bound = bind_policy_ok(scenario.policy_id)
    assert bound["uw_status"] == "BOUND"
    assert bound["total_premium_cents"] == 269_200

    reauthorised = patch_agent_ok(scenario.agent_id, authority_limit_cents=100_000)
    assert reauthorised["authority_limit_cents"] == 100_000

    response = bind_policy(scenario.policy_id)

    validate_error(response, ApiErrorId.ERR_POLICY_NOT_RATED.value, 409)


def test_the_refused_second_bind_applies_no_side_effect_at_all(api):
    """"Finally `total_premium_cents` must not exceed the producer's
    `authority_limit_cents`, or `ERR_AGENT_AUTHORITY_EXCEEDED`." That later
    guard is genuinely violated — 269200 exceeds the re-authorised 100000 — yet
    because the earlier state guard answered first, the policy `version`, the
    two-row ledger and the committed HAIL capacity are all exactly as the
    original bind left them.

    Design: Difficulty/priority_pair_validation_conflict/bind_state_conflict_outranks_authority_limit
    """
    scenario = setup_rated_dwelling_policy()
    bound = bind_policy_ok(scenario.policy_id)
    patch_agent_ok(scenario.agent_id, authority_limit_cents=100_000)

    bind_policy(scenario.policy_id)

    after = read_policy(scenario.policy_id)
    assert after["uw_status"] == "BOUND"
    assert after["version"] == bound["version"]
    assert after["bound_at"] == bound["bound_at"]
    assert after["total_premium_cents"] == 269_200

    assert len(read_ledger(scenario.policy_id)) == 2

    reservations = reservation_by_peril(scenario.policy_id)
    assert reservations["HAIL"]["status"] == "COMMITTED"
    hail = read_pool(scenario.hail_pool["id"])
    assert hail["committed_cents"] == 20_000_000
    assert hail["reserved_cents"] == 0


def test_a_suspended_compliance_axis_outranks_unverified_wc_coordination(api):
    """"Business safety, in this order: `ERR_COMPLIANCE_SUSPENDED` (409), then
    `ERR_CRITICAL_REC_OVERDUE` (422), then `ERR_BUYBACK_INSPECTION_REQUIRED`
    (422), then `ERR_BUYBACK_HAZARD_TOO_HIGH` (422)." A file carrying an overdue
    `CRITICAL` recommendation and a `PENDING_PROOF` labor profile violates three
    bind guards at once, and the safety guard at priority eleven answers ahead of
    both the companion safety check and the referential check at priority
    thirteen.

    Design: Difficulty/priority_pair_validation_conflict/bind_compliance_suspension_outranks_wc_coordination
    """
    scenario = setup_suspended_compliance_policy()
    policy = read_policy(scenario.policy_id)
    assert policy["compliance_status"] == "SUSPENDED"
    assert policy["uw_status"] == "RATED"

    overdue = read_recommendations(scenario.inspection["id"])[0]
    assert overdue["severity"] == "CRITICAL"
    assert overdue["status"] == "OVERDUE"

    unverified = upsert_labor_profile(
        scenario.agent_headers, scenario.policy_id, **CREW_OF_EIGHT
    )
    assert float(unverified["labor_exposure_units"]) == 6.00
    assert unverified["coordination_status"] == "PENDING_PROOF"

    response = bind_policy(scenario.policy_id)

    validate_error(response, ApiErrorId.ERR_COMPLIANCE_SUSPENDED.value, 409)


def test_the_compliance_block_leaves_the_reservations_merely_reserved(api):
    """"A labor profile must exist whose `coordination_status` is `NOT_REQUIRED`
    or `VERIFIED` — a `PENDING_PROOF` or `LAPSED` profile draws
    `ERR_WC_COORDINATION_UNVERIFIED`, and a policy that never had a profile
    submitted at all draws `ERR_WC_PROOF_MISSING`." Neither of those referential
    errors is reachable while the compliance axis is `SUSPENDED`, and the
    refused bind leaves `uw_status` at `RATED` with all three reservations still
    `RESERVED` rather than `COMMITTED`.

    Design: Difficulty/priority_pair_validation_conflict/bind_compliance_suspension_outranks_wc_coordination
    """
    scenario = setup_suspended_compliance_policy()
    upsert_labor_profile(scenario.agent_headers, scenario.policy_id, **CREW_OF_EIGHT)

    bind_policy(scenario.policy_id)

    after = read_policy(scenario.policy_id)
    assert after["uw_status"] == "RATED"
    assert after["bound_at"] is None
    assert after["bound_by_user_id"] is None
    assert after["total_premium_cents"] == 269_200

    reservations = reservation_by_peril(scenario.policy_id)
    assert {row["status"] for row in reservations.values()} == {"RESERVED"}
    still_reserved = {"HAIL": 20_000_000, "WIND": 12_000_000, "WILDFIRE": 8_000_000}
    for peril, amount in still_reserved.items():
        pool = read_pool(scenario.pools[peril]["id"])
        assert pool["committed_cents"] == 0
        assert pool["reserved_cents"] == amount
