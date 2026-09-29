"""Corner queue - section cross_cutting_complexity_layers, part C: the triage contagion."""
from test_helpers import (
    ANALYST_ID,
    CONTROL_DOMAIN_ORDER,
    add_verified_owner,
    assert_instant_equals,
    assessed_questionnaire,
    licensed_respondent,
    log_media,
    new_jurisdiction,
    read_refresh,
    read_respondent,
    schedule_refresh,
    score_respondent,
    set_clock,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, COMMITTEE


def test_a_confirmed_tier_one_sanctions_evasion_story_propagates_five_ways(api):
    """One triage reaches the media row, the ownership graph, both respondent state dimensions,
    the score ledger and the refresh calendar - and pins what does not move, since the inherent
    score is not in the endpoint's side-effect list so the residual rises by exactly the uplift.

    Design: Corner/cross_cutting_complexity_layers/a_confirmed_tier_one_sanctions_evasion_story_propagates_five_ways
    """
    new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )
    respondent = licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = respondent["id"]
    owner = add_verified_owner(rid, "DE", owner_name="Anna Weber", ownership_pct=80.00)
    assessed_questionnaire(
        rid, "ONBOARDING_PROVISIONAL",
        self_ratings={domain: 4 for domain in CONTROL_DOMAIN_ORDER},
    )
    scored = score_respondent(rid, "ONBOARDING_PROVISIONAL")
    assert scored["inherent_risk_score"] == 10.00
    assert scored["control_score"] == 80.00
    assert scored["residual_risk_score"] == 6.63
    assert scored["risk_rating"] == "LOW"

    approved = validate_success(api.decide_committee(rid, {"action": "APPROVE"}, COMMITTEE))
    assert approved["dd_state"] == "APPROVED"
    assert approved["approved_risk_rating"] == "LOW"
    assert approved["payment_posture"] == "OPEN"
    assert_instant_equals(approved["last_approved_at"], "2026-08-01T00:00:00Z")
    assert_instant_equals(approved["refresh_due_date"], "2029-08-01T00:00:00Z")

    cadence_cycle = schedule_refresh(rid, "2026-08-01T00:00:00Z", "2029-08-01T00:00:00Z")
    assert cadence_cycle["state"] == "SCHEDULED"
    assert cadence_cycle["trigger_reason"] == "CADENCE"
    before = read_respondent(rid)
    assert before["dd_state"] == "REFRESH_DUE"
    assert before["ownership_verified"] is True
    assert before["verified_ownership_pct"] == 80.00

    set_clock("2026-09-01T00:00:00Z")
    event = log_media(
        rid, headline="Sanctions evasion network named", category="SANCTIONS_EVASION",
        severity_tier="TIER_1", source_reliability="A", event_date="2026-08-15T00:00:00Z",
    )
    assert event["adjudication_state"] == "NEW"
    assert event["uplift_points"] == 0.00

    triaged = validate_success(api.triage_media(event["id"], {"action": "CONFIRM"}, ANALYST))
    assert triaged["adjudication_state"] == "CONFIRMED"
    assert triaged["uplift_points"] == 12.00
    assert triaged["triaged_by_user_id"] == ANALYST_ID
    assert_instant_equals(triaged["triaged_at"], "2026-09-01T00:00:00Z")

    reverted = validate_success(api.get_beneficial_owner(owner["id"], ANALYST))
    assert reverted["verification_status"] == "PENDING"

    after = read_respondent(rid)
    assert after["verified_ownership_pct"] == 0.00
    assert after["ownership_verified"] is False
    assert after["dd_state"] == "RESTRICTED"
    assert after["restriction_reason"] == "ADVERSE_MEDIA"
    assert after["payment_posture"] == "BLOCKED"
    assert after["adverse_media_uplift"] == 12.00
    assert after["residual_risk_score"] == 18.63
    assert after["risk_rating"] == "LOW"
    assert after["inherent_risk_score"] == 10.00
    assert after["approved_risk_rating"] == "LOW"
    assert_instant_equals(after["refresh_due_date"], "2026-10-01T00:00:00Z")

    superseded = read_refresh(cadence_cycle["id"])
    assert superseded["state"] == "CANCELLED"
    assert superseded["cancelled_reason"] == "SUPERSEDED_BY_ACCELERATION"

    rows, meta = validate_paginated(
        api.list_periodic_refreshes(ANALYST, params={"respondent_bank_id": rid})
    )
    assert meta["total_count"] == 2
    accelerated = rows[1]
    assert accelerated["trigger_reason"] == "ADVERSE_MEDIA"
    assert accelerated["state"] == "SCHEDULED"
    assert_instant_equals(accelerated["window_start"], "2026-09-01T00:00:00Z")
    assert_instant_equals(accelerated["scheduled_due_date"], "2026-10-01T00:00:00Z")
