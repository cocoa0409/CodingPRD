"""Optimistic concurrency control on premium settlement (§2.9).

Covers the corner cross-cutting OCC instances: correct-version success with version bump,
and stale-version rejection.
"""
from test_helpers import (
    validate_success, validate_error,
    create_plan, create_traveler, create_quoted_policy, add_insured,
    record_payment_payload, make_traveler_headers,
)


def test_record_payment_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §2.9: "The server compares `expected_policy_version` against the target policy's
    current `version`."
    PRD §3.3: "When the version check of §2.9 passes, `payment_status` advances to `PAID`,
    `net_premium_collected_cents` is set equal to `premium_cents`, and the policy's `version`
    increments."

    record-payment carrying the policy's current version succeeds (payment PAID) and increments
    Policy.version by exactly one.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_record_payment_succeeds_and_bumps_version
    """
    plan = create_plan(tier="BASIC", base_rate_bps=400)
    traveler = create_traveler()
    policy = create_quoted_policy(plan["id"], traveler["id"], trip_cost_cents=500000)
    add_insured(policy["id"], traveler["id"], covered_trip_cost_cents=500000)
    headers = make_traveler_headers(traveler["id"])
    live = validate_success(api.get_policy(policy["id"], headers), 200)
    observed_version = live["version"]
    res = api.record_payment(policy["id"], record_payment_payload(observed_version), headers)
    updated = validate_success(res, 200)
    assert updated["payment_status"] == "PAID"
    assert updated["version"] == observed_version + 1, \
        f"version must increment by 1 on record-payment, got {updated['version']} from {observed_version}"


def test_record_payment_with_stale_version_rejected(api):
    """PRD §2.9: "If another writer has advanced the policy's `version` since the client last
    read it, the values no longer match and the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."
    PRD §3.2: "triggers a full recomputation of the policy's premium (so that adding an insured
    at or above the senior age threshold raises `premium_cents`), incrementing the policy's
    `version`."

    The client captures the version after one insured; a second insured then advances the
    version, making the held value stale; record-payment carrying it is rejected with
    ERR_STALE_VERSION (412).

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_record_payment_returns_412
    """
    plan = create_plan(tier="BASIC", base_rate_bps=400)
    owner = create_traveler()
    other = create_traveler()
    policy = create_quoted_policy(plan["id"], owner["id"], trip_cost_cents=500000)
    add_insured(policy["id"], owner["id"], covered_trip_cost_cents=300000)
    headers = make_traveler_headers(owner["id"])
    stale = validate_success(api.get_policy(policy["id"], headers), 200)["version"]
    # Second insured bumps the policy version, making `stale` out of date.
    add_insured(policy["id"], other["id"], owner_traveler_id=owner["id"],
                covered_trip_cost_cents=200000)
    res = api.record_payment(policy["id"], record_payment_payload(stale), headers)
    validate_error(res, "ERR_STALE_VERSION")
