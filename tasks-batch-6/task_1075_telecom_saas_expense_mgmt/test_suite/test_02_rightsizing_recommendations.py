"""Rightsizing: projected vs realized savings, the implement cascade, the utilization
eligibility boundary, supersession, and optimistic concurrency."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_service, setup_proposed_recommendation,
    create_recommendation_payload,
    TEST_USERS, get_success_data,
)

_ANALYST = TEST_USERS["analyst_headers"]
_FA = TEST_USERS["finance_approver_headers"]


# ---------------------------------------------------------------------------
# dual_variant_calc / rightsizing_projected_vs_realized
# ---------------------------------------------------------------------------

def test_projected_savings_annualized_over_twelve_months(api):
    """PRD §3.3: "The projected_savings_cents is that seat count multiplied by the service's
    unit_rate_cents and then multiplied by 12 months."

    seats_cut = 60-45 = 15; 15 * 2000 * 12 = 360000.

    Design: Difficulty/dual_variant_calc/rightsizing_projected_vs_realized
    """
    scen = setup_proposed_recommendation(
        api, rec_type="DOWNGRADE_SEATS", target_quantity=45,
        service_overrides={"unit_rate_cents": 2000, "contracted_quantity": 60, "active_quantity": 42},
        clock_iso="2026-06-01T00:00:00Z",
    )
    assert scen["recommendation"]["projected_savings_cents"] == 360000, \
        f"projected should be 360000, got {scen['recommendation']['projected_savings_cents']}"


def test_realized_savings_prorated_over_months_remaining(api):
    """PRD §3.3: "the number of months remaining is twelve times the difference in years between
    term_end and now, plus the difference in their month numbers, plus one (so a term ending in
    the same month as implementation yields one month)."
    PRD §3.3: "The realized_savings_cents is the seats cut multiplied by the service's
    unit_rate_cents multiplied by that months-remaining count, computed exactly with no rounding."

    Clock 2026-06-01, term_end 2026-12-31 -> months_remaining = 0*12 + (12-6) + 1 = 7;
    15 * 2000 * 7 = 210000.

    Design: Difficulty/dual_variant_calc/rightsizing_projected_vs_realized
    """
    scen = setup_proposed_recommendation(
        api, rec_type="DOWNGRADE_SEATS", target_quantity=45,
        service_overrides={"unit_rate_cents": 2000, "contracted_quantity": 60, "active_quantity": 42},
        clock_iso="2026-06-01T00:00:00Z",
    )
    rec = validate_success(api.implement_recommendation(scen["recommendation"]["id"], _FA))
    assert rec["realized_savings_cents"] == 210000, \
        f"realized should be 210000, got {rec['realized_savings_cents']}"


# ---------------------------------------------------------------------------
# transitive_cascade / implement_recommendation_cascade_depth2
# ---------------------------------------------------------------------------

def test_implement_downgrade_updates_service_quantity_and_status(api):
    """PRD §3.3: "For a DOWNGRADE_SEATS, the service's contracted_quantity is set to the
    target_quantity and its status becomes RIGHTSIZED; for a TERMINATE, the contracted_quantity
    is set to 0 and the service's status becomes RETIRED."

    Design: Difficulty/transitive_cascade/implement_recommendation_cascade_depth2
    """
    scen = setup_proposed_recommendation(
        api, rec_type="DOWNGRADE_SEATS", target_quantity=45,
        service_overrides={"unit_rate_cents": 2000, "contracted_quantity": 60, "active_quantity": 42},
        clock_iso="2026-06-01T00:00:00Z",
    )
    validate_success(api.implement_recommendation(scen["recommendation"]["id"], _FA))
    service = validate_success(api.get_service(scen["service"]["id"], _ANALYST))
    assert service["contracted_quantity"] == 45, f"contracted_quantity should be 45, got {service['contracted_quantity']}"
    assert service["status"] == "RIGHTSIZED", f"service status should be RIGHTSIZED, got {service['status']}"


def test_implement_downgrade_recomputes_contract_committed_cost(api):
    """PRD §3.3: "Implementation first computes the recommendation's realized_savings_cents, then
    applies the change to the service, then recomputes the parent contract's
    monthly_committed_cost_cents."
    PRD §3.2: "That committed cost is the sum, across all services of the contract whose status
    is either ACTIVE or RIGHTSIZED, of each service's unit_rate_cents multiplied by its
    contracted_quantity."

    Committed 2000*60=120000 before; after downgrade to 45, 2000*45 = 90000.

    Design: Difficulty/transitive_cascade/implement_recommendation_cascade_depth2
    """
    scen = setup_proposed_recommendation(
        api, rec_type="DOWNGRADE_SEATS", target_quantity=45,
        service_overrides={"unit_rate_cents": 2000, "contracted_quantity": 60, "active_quantity": 42},
        clock_iso="2026-06-01T00:00:00Z",
    )
    assert scen["contract"]["monthly_committed_cost_cents"] == 120000, "precondition: committed 120000"
    validate_success(api.implement_recommendation(scen["recommendation"]["id"], _FA))
    contract = validate_success(api.get_contract(scen["contract"]["id"], _ANALYST))
    assert contract["monthly_committed_cost_cents"] == 90000, \
        f"committed should be 90000 after downgrade, got {contract['monthly_committed_cost_cents']}"


# ---------------------------------------------------------------------------
# boundary_precision_check / utilization_threshold_inclusive_boundary
# ---------------------------------------------------------------------------

def test_downgrade_accepted_at_utilization_exactly_threshold(api):
    """PRD §3.3: "the service's utilization_pct must be at or below 70.00 percent; a downgrade
    proposed on a service utilized above that threshold is rejected with
    ERR_UTILIZATION_ABOVE_THRESHOLD (the boundary value of exactly 70.00 is eligible)."

    active 42 / contracted 60 -> utilization 70.00 (inclusive); downgrade is accepted.

    Design: Difficulty/boundary_precision_check/utilization_threshold_inclusive_boundary
    """
    scen = setup_proposed_recommendation(
        api, rec_type="DOWNGRADE_SEATS", target_quantity=45,
        service_overrides={"unit_rate_cents": 2000, "contracted_quantity": 60, "active_quantity": 42},
    )
    assert scen["service"]["utilization_pct"] == 70.00, \
        f"utilization should be 70.00, got {scen['service']['utilization_pct']}"
    assert scen["recommendation"]["status"] == "PROPOSED", \
        f"rec should be PROPOSED at boundary, got {scen['recommendation']['status']}"
    assert scen["recommendation"]["projected_savings_cents"] == 360000


def test_downgrade_rejected_just_above_utilization_threshold(api):
    """PRD §3.3: "the service's utilization_pct must be at or below 70.00 percent; a downgrade
    proposed on a service utilized above that threshold is rejected with
    ERR_UTILIZATION_ABOVE_THRESHOLD (the boundary value of exactly 70.00 is eligible)."

    active 43 / contracted 60 -> utilization 71.67 (just above 70.00) -> rejected.

    Design: Difficulty/boundary_precision_check/utilization_threshold_inclusive_boundary
    """
    scen = setup_service(api, service_overrides={"unit_rate_cents": 2000, "contracted_quantity": 60,
                                                 "active_quantity": 43})
    assert scen["service"]["utilization_pct"] == 71.67, \
        f"utilization should be 71.67, got {scen['service']['utilization_pct']}"
    resp = api.create_recommendation(
        scen["service"]["id"],
        create_recommendation_payload("DOWNGRADE_SEATS", 45, scen["service"]["version"]),
        _ANALYST)
    validate_error(resp, ApiErrorId.ERR_UTILIZATION_ABOVE_THRESHOLD.value)


# ---------------------------------------------------------------------------
# Corner: validations / downgrade_above_utilization_returns_error
# ---------------------------------------------------------------------------

def test_downgrade_above_utilization_returns_error(api):
    """PRD §3.3: "a downgrade proposed on a service utilized above that threshold is rejected
    with ERR_UTILIZATION_ABOVE_THRESHOLD"

    active 43 / contracted 60 -> utilization 71.67 > 70.00.

    Design: Corner/validations/downgrade_above_utilization_returns_error
    """
    scen = setup_service(api, service_overrides={"unit_rate_cents": 2000, "contracted_quantity": 60,
                                                 "active_quantity": 43})
    resp = api.create_recommendation(
        scen["service"]["id"],
        create_recommendation_payload("DOWNGRADE_SEATS", 45, scen["service"]["version"]),
        _ANALYST)
    validate_error(resp, ApiErrorId.ERR_UTILIZATION_ABOVE_THRESHOLD.value)


# ---------------------------------------------------------------------------
# Corner: state_machines / reject_recommendation_sets_rejected
# ---------------------------------------------------------------------------

def test_reject_recommendation_sets_rejected(api):
    """PRD §3.3: "rejecting a PROPOSED recommendation simply moves it to REJECTED with no effect
    on the service."

    Design: Corner/state_machines/reject_recommendation_sets_rejected
    """
    scen = setup_proposed_recommendation(
        api, rec_type="DOWNGRADE_SEATS", target_quantity=45,
        service_overrides={"unit_rate_cents": 2000, "contracted_quantity": 60, "active_quantity": 42},
    )
    rec = validate_success(api.reject_recommendation(scen["recommendation"]["id"], _FA))
    assert rec["status"] == "REJECTED", f"rec status should be REJECTED, got {rec['status']}"


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers / recommendation_create_stale_version_returns_412
# ---------------------------------------------------------------------------

def test_recommendation_create_stale_version_returns_412(api):
    """PRD §2.6: "The server compares expected_service_version against the service's current
    version; if they do not match, the request is rejected with ERR_STALE_VERSION (HTTP 412)
    and no recommendation is created."
    PRD §2.6: "creating a new PROPOSED recommendation legitimately supersedes any prior PROPOSED
    recommendation on the same service and bumps the service's version"

    First create bumps version 1->2; a second create still carrying version 1 is stale.

    Design: Corner/cross_cutting_complexity_layers/recommendation_create_stale_version_returns_412
    """
    scen = setup_proposed_recommendation(
        api, rec_type="DOWNGRADE_SEATS", target_quantity=45,
        service_overrides={"unit_rate_cents": 2000, "contracted_quantity": 60, "active_quantity": 42},
    )
    stale_version = scen["service_version"]  # version observed before the first create
    resp = api.create_recommendation(
        scen["service"]["id"],
        create_recommendation_payload("DOWNGRADE_SEATS", 50, stale_version),
        _ANALYST)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers / recommendation_create_supersedes_prior_proposed
# ---------------------------------------------------------------------------

def test_recommendation_create_supersedes_prior_proposed(api):
    """PRD §3.3: "any prior PROPOSED recommendation on the same service is moved to SUPERSEDED."

    Re-reading the service version after the first create lets a second create succeed and
    supersede the first (-> SUPERSEDED).

    Design: Corner/cross_cutting_complexity_layers/recommendation_create_supersedes_prior_proposed
    """
    scen = setup_proposed_recommendation(
        api, rec_type="DOWNGRADE_SEATS", target_quantity=45,
        service_overrides={"unit_rate_cents": 2000, "contracted_quantity": 60, "active_quantity": 42},
    )
    r1_id = scen["recommendation"]["id"]
    current_version = get_success_data(api.get_service(scen["service"]["id"], _ANALYST))["version"]
    r2 = validate_success(api.create_recommendation(
        scen["service"]["id"],
        create_recommendation_payload("DOWNGRADE_SEATS", 50, current_version),
        _ANALYST), 201)
    assert r2["status"] == "PROPOSED", f"second rec should be PROPOSED, got {r2['status']}"
    r1_fetched = _find_recommendation(api, scen["service"]["id"], r1_id)
    assert r1_fetched["status"] == "SUPERSEDED", \
        f"prior rec should be SUPERSEDED, got {r1_fetched['status']}"


def _find_recommendation(api, service_id, rec_id):
    from test_helpers import validate_paginated
    resp = api.list_service_recommendations(service_id, _ANALYST, params={"limit": 100})
    data, _meta = validate_paginated(resp)
    for rec in data:
        if rec["id"] == rec_id:
            return rec
    raise AssertionError(f"recommendation {rec_id} not found in listing")
