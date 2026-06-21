"""Business validation violations, not-found / auth errors, and a filtered list.
Queue B — sections validations, errors, endpoints.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    make_underwriter_headers,
    ApiErrorId,
    build_user_headers,
    factories as f,
    fixtures as fx,
)

AGENT = TEST_USERS["agent_headers"]
UW = TEST_USERS["underwriter_headers"]


# --- validations section ---
def test_submit_coverage_below_replacement_cost(api):
    """PRD §3.4: "The requested Coverage A must be at least the property's committed
    replacement cost, otherwise `ERR_COVERAGE_BELOW_REPLACEMENT_COST`."

    Design: Corner/validations/submit_coverage_below_replacement_cost
    """
    prop = fx.create_property(street_address="28 Below St")
    fx.commit_estimate(prop["id"], "COMPONENT")  # replacement_cost 274200
    fx.create_risk_assessment(prop["id"])
    app = fx.create_application(prop["id"], 250000)  # < 274200
    resp = api.submit_application(app["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_COVERAGE_BELOW_REPLACEMENT_COST.value)


def test_submit_without_replacement_cost_estimate(api):
    """PRD §3.4: "The property must have a committed estimate — its `replacement_cost`
    must be greater than 0 — otherwise `ERR_REPLACEMENT_COST_MISSING`."

    Design: Corner/validations/submit_without_replacement_cost_estimate
    """
    prop = fx.create_property(street_address="29 NoEst St")
    fx.create_risk_assessment(prop["id"])
    app = fx.create_application(prop["id"], 300000)
    resp = api.submit_application(app["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_REPLACEMENT_COST_MISSING.value)


def test_binding_payment_amount_mismatch(api):
    """PRD §3.7: "the tendered `amount` must equal the policy's `annual_premium`,
    otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Corner/validations/binding_payment_amount_mismatch
    """
    ctx = fx.setup_bound_policy(requested_coverage_a=300000, wind_hail_deductible_pct=2)
    policy = ctx["policy"]
    assert policy["annual_premium"] == 997.50
    resp = api.create_payment(
        f.create_payment_payload(policy["id"], "BINDING", 900.00), AGENT
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value)
    assert fx.get_policy(policy["id"])["status"] == "PENDING_PAYMENT"


def test_reinstatement_limit_exceeded(api):
    """PRD §3.7: "the policy's `lapse_count` must be at most 2, otherwise
    `ERR_REINSTATEMENT_LIMIT_EXCEEDED`, so that a third lapse can never be reinstated."

    Design: Corner/validations/reinstatement_limit_exceeded
    """
    ctx = fx.setup_active_policy(binding_amount=997.50)
    policy, uw = ctx["policy"], ctx["underwriter"]
    pol_id = policy["id"]
    # Lapse #1 -> reinstate
    p = fx.get_policy(pol_id)
    fx.lapse_policy(pol_id, p["version"], uw["id"])
    fx.pay_reinstatement(pol_id, 1247.50)
    # Lapse #2 -> reinstate
    p = fx.get_policy(pol_id)
    fx.lapse_policy(pol_id, p["version"], uw["id"])
    fx.pay_reinstatement(pol_id, 1247.50)
    # Lapse #3 (lapse_count == 3) -> reinstatement must be blocked
    p = fx.get_policy(pol_id)
    fx.lapse_policy(pol_id, p["version"], uw["id"])
    assert fx.get_policy(pol_id)["lapse_count"] == 3
    resp = api.create_payment(
        f.create_payment_payload(pol_id, "REINSTATEMENT", 1247.50), AGENT
    )
    validate_error(resp, ApiErrorId.ERR_REINSTATEMENT_LIMIT_EXCEEDED.value)


# --- errors section ---
def test_create_risk_assessment_property_not_found(api):
    """PRD §2.5: "the server validates their existence left to right ... and returns
    the not-found error for the first identifier that fails to resolve. Each persisted
    resource has its own not-found code: `ERR_PROPERTY_NOT_FOUND`, ..."

    Design: Corner/errors/create_risk_assessment_property_not_found
    """
    resp = api.create_risk_assessment(
        f.create_risk_assessment_payload("00000000-0000-4000-8000-0000000000bb"), UW
    )
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND.value)


def test_missing_user_context_header(api):
    """PRD §2.1: "A request that omits either header, or supplies a value that is not
    recognized, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/errors/missing_user_context_header
    """
    resp = api.list_properties({"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


# --- endpoints section: filtered list ---
def test_list_endorsements_filtered_by_application(api):
    """PRD §3.5: "Alongside the base application, an agent can attach riders called
    endorsements, each naming the `application_id` it modifies."
    PRD §4: "List Endorsements (filter by application_id)".

    Design: Corner/endpoints/list_endorsements_filtered_by_application
    """
    prop = fx.create_property(street_address="33 Filter St")
    app = fx.create_application(prop["id"], 300000)
    e1 = fx.create_endorsement(app["id"], "PERIL_ADD", "WATER_BACKUP", 10000)
    e2 = fx.create_endorsement(app["id"], "EXCLUSION", "MOLD")
    resp = api.list_endorsements(AGENT, params={"application_id": app["id"]})
    data, meta = validate_paginated(resp)
    ids = {e["id"] for e in data}
    assert e1["id"] in ids and e2["id"] in ids
    assert meta["total_count"] == 2
    for e in data:
        assert e["application_id"] == app["id"]
