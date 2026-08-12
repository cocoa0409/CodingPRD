"""Outreach campaigns: launch budget gate and the pause/resume cycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_outreach_campaign,
    create_campaign,
    validate_error,
    validate_success,
)


def test_campaign_pause_resume_cycle(api, coordinator_headers):
    """PRD section 3.9: "An `ACTIVE` campaign may be paused and resumed by
    status updates (`ACTIVE` to `PAUSED` and back, each requiring the matching
    current state under `ERR_INVALID_STATE`)" and "Launching a `DRAFT` campaign
    (any other status is `ERR_INVALID_STATE`) computes the spend as
    `audience_size` multiplied by `cost_per_impression_cents` and records it as
    `spent_cents`".

    Design: Corner/state_machines/campaign_pause_resume_cycle
    """
    campaign = create_campaign(zone_id=None, channel="MAIL", topic="ACCEPTABLE_MATERIALS",
                               budget_cents=100000, audience_size=1000,
                               cost_per_impression_cents=100, end_date="2026-12-31")
    assert_outreach_campaign(campaign)
    assert campaign["status"] == "DRAFT"

    launched = validate_success(api.launch_outreach_campaign(campaign["id"], coordinator_headers), 200)
    assert launched["status"] == "ACTIVE"
    assert launched["spent_cents"] == 100000

    paused = validate_success(
        api.update_outreach_campaign(campaign["id"], {"status": "PAUSED"}, coordinator_headers), 200)
    assert paused["status"] == "PAUSED"
    assert paused["spent_cents"] == 100000

    resumed = validate_success(
        api.update_outreach_campaign(campaign["id"], {"status": "ACTIVE"}, coordinator_headers), 200)
    assert resumed["status"] == "ACTIVE"
    assert resumed["spent_cents"] == 100000


def test_campaign_spend_equals_budget_allowed(api, coordinator_headers):
    """PRD section 3.9: "the fiscal gate requires this spend to fit within
    `budget_cents` — a spend exactly equal to the budget is allowed, one cent
    over is rejected with `ERR_CAMPAIGN_BUDGET_EXCEEDED`."

    Design: Corner/calculations/campaign_spend_equals_budget_allowed
    """
    c1 = create_campaign(channel="MAIL", topic="SEASON_START", budget_cents=100000,
                         audience_size=1000, cost_per_impression_cents=100,
                         end_date="2026-12-31")
    c2 = create_campaign(channel="EMAIL", topic="COMPOST_GIVEBACK", budget_cents=100000,
                         audience_size=1001, cost_per_impression_cents=100,
                         end_date="2026-12-31")

    launched = validate_success(api.launch_outreach_campaign(c1["id"], coordinator_headers), 200)
    assert launched["status"] == "ACTIVE"
    assert launched["spent_cents"] == 100000

    # 1001 x 100 = 100100 cents is one hundred cents over the 100000 budget.
    res = api.launch_outreach_campaign(c2["id"], coordinator_headers)
    validate_error(res, ApiErrorId.ERR_CAMPAIGN_BUDGET_EXCEEDED)

    c2_after = validate_success(api.get_outreach_campaign(c2["id"], coordinator_headers), 200)
    assert c2_after["status"] == "DRAFT"
