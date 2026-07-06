"""Incident liability exposure: the estimated reserve at escalation vs the settled
payout at resolution, and the reserve's effect on the liability policy ledger."""
from test_helpers import make_coordinator_headers
from test_helpers import factories as f
from test_helpers import fixtures as fx

COORD = make_coordinator_headers()


def _escalated_major_incident(api):
    return fx.setup_escalated_incident(api, severity="MAJOR", liability_coverage=150000)


def test_escalation_reserves_severity_capped_exposure(api):
    """PRD 3.7: "Escalation computes the estimated exposure and reserves it: the reserve, stored in
    the incident's estimated_exposure_cents, is the lesser of the liability policy's
    coverage_amount_cents and the severity reserve — 50000 cents for MINOR, 200000 cents for MAJOR,
    and 500000 cents for EMERGENCY."

    Design: Difficulty/dual_variant_calc/exposure_estimated_vs_settled_liability
    """
    ctx = _escalated_major_incident(api)
    assert ctx["incident"]["estimated_exposure_cents"] == 150000, ctx["incident"]


def test_resolution_settles_and_pays_lesser_of_damage_and_cap(api):
    """PRD 3.7: "In both cases the settled payout, stored in settled_payout_cents, is the lesser of
    the assessed damage and the policy's coverage_amount_cents."
    PRD 3.7: "Resolving from ESCALATED computes settled_payout_cents, releases the previously placed
    reserve by subtracting the incident's estimated_exposure_cents from the policy's
    reserved_exposure_cents, and adds the settled payout to the policy's paid_out_cents."

    Design: Difficulty/dual_variant_calc/exposure_estimated_vs_settled_liability
    """
    ctx = _escalated_major_incident(api)
    fx.get_success_data(api.resolve_incident(ctx["incident"]["id"], f.resolve_payload(90000), COORD))
    incident = fx.get_incident(api, ctx["incident"]["id"])
    policy = fx.get_coverage_policy(api, ctx["liability_policy"]["id"])
    assert incident["settled_payout_cents"] == 90000, incident
    assert incident["settled_payout_cents"] != incident["estimated_exposure_cents"], incident
    assert policy["paid_out_cents"] == 90000, policy
