"""Optimistic concurrency (stale bind / stale lapse) and immediate consistency.
Queue B — sections cross_cutting_complexity_layers and consistency_model.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_underwriter_headers,
    ApiErrorId,
    factories as f,
    fixtures as fx,
)

AGENT = TEST_USERS["agent_headers"]
UW = TEST_USERS["underwriter_headers"]


def test_occ_bind_stale_application_version(api):
    """PRD §2.9: "If that value does not match the application's current `version` —
    which happens when another writer has advanced the application since the binder
    last read it, for instance through a return-to-queue and re-take cycle ... the
    bind is rejected with `ERR_STALE_APPLICATION_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_bind_stale_application_version
    """
    uw = fx.create_underwriter()
    prop, ra = fx.setup_estimated_property(prop_overrides={"street_address": "38 Stale St"})
    fx.setup_passed_inspection(prop["id"])
    app = fx.create_application(prop["id"], 300000, wind_hail_deductible_pct=2)
    app = fx.submit_application(app["id"])
    app = fx.take_review(app["id"], uw["id"])
    stale_v = app["version"]
    # Advance the application via a return-to-queue + take-review cycle.
    validate_success(api.return_to_queue_application(app["id"], make_underwriter_headers(uw["id"])))
    validate_success(api.take_review_application(app["id"], make_underwriter_headers(uw["id"])))
    # Bind with the now-stale version.
    resp = api.bind_application(
        app["id"],
        f.bind_application_payload(1751000000, 1782536000, stale_v),
        make_underwriter_headers(uw["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_APPLICATION_VERSION.value)


def test_occ_lapse_stale_policy_version(api):
    """PRD §2.9: "If that value does not match the policy's current `version` — which
    happens when another writer has already advanced the policy, for instance by
    lapsing and reinstating it — the lapse is rejected with `ERR_STALE_POLICY_VERSION`
    at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_lapse_stale_policy_version
    """
    ctx = fx.setup_active_policy(binding_amount=997.50)
    policy, uw = ctx["policy"], ctx["underwriter"]
    pol_id = policy["id"]
    stale_pol_v = fx.get_policy(pol_id)["version"]
    # Advance the policy through a lapse + reinstate cycle.
    fx.lapse_policy(pol_id, stale_pol_v, uw["id"])
    fx.pay_reinstatement(pol_id, 1247.50)
    # Lapse again with the stale (pre-lapse) version.
    resp = api.lapse_policy(
        pol_id, {"expected_policy_version": stale_pol_v}, make_underwriter_headers(uw["id"])
    )
    validate_error(resp, ApiErrorId.ERR_STALE_POLICY_VERSION.value)


def test_immediate_visibility_of_premium_balance_after_payment(api):
    """PRD §2.8: "The ledger is the single source of truth for the balance, and the
    balance is recomputed from it after every posting."
    PRD §3.7: "On success the policy becomes `ACTIVE` and the system posts a DEBIT to
    the ledger for the `annual_premium` as the binding premium, recomputing
    `premium_balance`."

    Design: Corner/consistency_model/immediate_visibility_of_premium_balance_after_payment
    """
    ctx = fx.setup_bound_policy(requested_coverage_a=300000, wind_hail_deductible_pct=2)
    policy = ctx["policy"]
    assert policy["annual_premium"] == 997.50
    fx.pay_binding(policy["id"], 997.50)
    after = validate_success(api.get_policy(policy["id"], UW))
    assert after["status"] == "ACTIVE"
    assert after["premium_balance"] == 997.50, (
        f"premium_balance must read 997.50 immediately on the post-payment GET, "
        f"got {after['premium_balance']}"
    )
