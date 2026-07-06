"""Cascading transitions: churn depth-3 chain, dispute-upheld depth-3, pause, bubble-up.

Covers queue A transitive_cascade instances and the queue B state_machines
cascade/bubble-up corner instances.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    factories,
    fixtures,
)

ADMIN = TEST_USERS["agency_admin_headers"]
AM = TEST_USERS["account_manager_headers"]


def test_client_churn_cascades_close_and_cancel(api):
    """PRD §3.1: "When churn proceeds from `ACTIVE`, it cascades every one of the
    client's retainers to `CLOSED`; each newly `CLOSED` retainer in turn cancels its
    own non-terminal deliverables, releasing their committed credits (a depth-three
    chain from client to retainer to deliverable)".

    Churn an ACTIVE client holding one ASSIGNED deliverable (3 credits reserved):
    Client CHURNED, Retainer CLOSED, Deliverable CANCELLED, credits_committed 0.

    Design: Difficulty/transitive_cascade/client_churn_to_retainer_close_to_deliverable_cancel_releases_credits
    """
    client, retainer, sprint = fixtures.setup_client_retainer_active_sprint(
        retainer_overrides={"monthly_credits": 20},
    )
    deliverable, _ = fixtures.create_assigned_deliverable(
        client["id"], retainer["id"], sprint["id"],
        deliverable_overrides={"kind": "CONTENT", "complexity": "STANDARD"},
    )
    churned = validate_success(api.churn_client(client["id"], AM))
    assert churned["status"] == "CHURNED"

    retainer_after = validate_success(api.get_retainer(retainer["id"], ADMIN))
    assert retainer_after["status"] == "CLOSED", (
        f"retainer should cascade to CLOSED, got {retainer_after['status']}"
    )
    deliverable_after = validate_success(api.get_deliverable(deliverable["id"], ADMIN))
    assert deliverable_after["status"] == "CANCELLED", (
        f"deliverable should cascade to CANCELLED, got {deliverable_after['status']}"
    )
    assert retainer_after["credits_committed"] == 0, (
        f"cascaded cancel must release reserved credits, "
        f"got committed {retainer_after['credits_committed']}"
    )


def test_client_churn_ends_ad_campaigns(api):
    """PRD §3.1: "every ad campaign whose `lifecycle_status` is `DRAFT`, `LIVE`, or
    `PAUSED` is moved to `ENDED`; and the client's `version` increments."

    A LIVE campaign on a churning ACTIVE client cascades to ENDED.

    Design: Difficulty/transitive_cascade/client_churn_to_retainer_close_to_deliverable_cancel_releases_credits
    """
    client, retainer = fixtures.create_active_client_with_active_retainer(
        retainer_overrides={"monthly_credits": 20},
    )
    campaign = fixtures.create_live_campaign(
        client["id"], retainer["id"], channel="GOOGLE_ADS", budget_cents=500000
    )
    validate_success(api.churn_client(client["id"], AM))
    campaign_after = validate_success(api.get_ad_campaign(campaign["id"], ADMIN))
    assert campaign_after["lifecycle_status"] == "ENDED", (
        f"LIVE campaign should cascade to ENDED on churn, "
        f"got {campaign_after['lifecycle_status']}"
    )


def test_dispute_upheld_reduces_spend_and_fee(api):
    """PRD §3.8: "on success it sets `credited_cents` equal to `disputed_cents`,
    subtracts `disputed_cents` from the campaign's `spent_cents` and recomputes the
    campaign's `management_fee_cents`, recomputes the parent client's
    `open_dispute_count` and `health_score` (a depth-three cascade from dispute to
    campaign and to client), and increments the dispute's `version`."

    Spend 800000c (live fee 151000c), uphold a 300000c dispute: credited 300000,
    spent_cents 500000, fee floor(500000*0.20) = 100000.

    Design: Difficulty/transitive_cascade/dispute_upheld_to_spend_reduction_to_fee_and_health_recompute
    """
    client, retainer, campaign, dispute = fixtures.setup_dispute_under_review(
        disputed_cents=300000, spend_cents=800000,
        campaign_overrides={"channel": "GOOGLE_ADS", "budget_cents": 1000000},
    )
    resolved = validate_success(
        api.resolve_dispute(dispute["id"], {"outcome": "UPHELD"}, AM)
    )
    assert resolved["status"] == "UPHELD"
    assert resolved["credited_cents"] == 300000

    campaign_after = validate_success(api.get_ad_campaign(campaign["id"], ADMIN))
    assert campaign_after["spent_cents"] == 500000, (
        f"spent_cents should drop to 500000, got {campaign_after['spent_cents']}"
    )
    assert campaign_after["management_fee_cents"] == 100000, (
        f"fee should recompute to floor(500000*0.20)=100000, "
        f"got {campaign_after['management_fee_cents']}"
    )


def test_dispute_upheld_recomputes_client_health_and_dispute_count(api):
    """PRD §3.8: "recomputes the parent client's `open_dispute_count` and
    `health_score` (a depth-three cascade from dispute to campaign and to client)".
    PRD §3.3: "Subtract a dispute penalty of ten for each unit of the client's
    `open_dispute_count`."
    PRD §3.8: "The `open_dispute_count` always reflects the count of the client's
    disputes currently `OPEN` or `UNDER_REVIEW`."

    After uphold, the only dispute leaves OPEN/UNDER_REVIEW so open_dispute_count 0;
    no report, no overdue work -> health_score 100.

    Design: Difficulty/transitive_cascade/dispute_upheld_to_spend_reduction_to_fee_and_health_recompute
    """
    client, retainer, campaign, dispute = fixtures.setup_dispute_under_review(
        disputed_cents=300000, spend_cents=800000,
        campaign_overrides={"channel": "GOOGLE_ADS", "budget_cents": 1000000},
    )
    validate_success(api.resolve_dispute(dispute["id"], {"outcome": "UPHELD"}, AM))
    client_after = validate_success(api.get_client(client["id"], ADMIN))
    assert client_after["open_dispute_count"] == 0, (
        f"open_dispute_count should be 0 after uphold, "
        f"got {client_after['open_dispute_count']}"
    )
    assert client_after["health_score"] == 100, (
        f"health_score should recompute to 100, got {client_after['health_score']}"
    )


def test_retainer_activation_bubbles_client_to_active(api):
    """PRD §3.1: "A client moves to `ACTIVE` as a bubble-up: when the client is
    `AUDITED` and its first retainer becomes `ACTIVE`, the platform promotes the
    client from `AUDITED` to `ACTIVE`, recomputes its `health_score`, and increments
    the client's `version`."

    Design: Corner/state_machines/retainer_activate_bubbles_client_audited_to_active
    """
    client, retainer = fixtures.create_audited_client_with_draft_retainer(
        retainer_overrides={"monthly_credits": 20},
    )
    activated = validate_success(api.activate_retainer(retainer["id"], ADMIN))
    assert activated["status"] == "ACTIVE"
    client_after = validate_success(api.get_client(client["id"], ADMIN))
    assert client_after["status"] == "ACTIVE", (
        f"client should bubble up to ACTIVE, got {client_after['status']}"
    )


def test_client_pause_suspends_retainer_and_pauses_campaign(api):
    """PRD §3.1: "Pausing an `ACTIVE` client is an account-manager action that drives
    several cascades at once: it moves the client `ACTIVE → PAUSED`, conditionally
    cascades each of the client's retainers that is currently `ACTIVE` to `SUSPENDED`
    (retainers in any other status are left alone), moves each of the client's ad
    campaigns whose `lifecycle_status` is `LIVE` to `PAUSED`, and increments the
    client's `version`."

    Design: Corner/state_machines/client_pause_cascades_retainer_and_campaign
    """
    client, retainer = fixtures.create_active_client_with_active_retainer(
        retainer_overrides={"monthly_credits": 20},
    )
    campaign = fixtures.create_live_campaign(
        client["id"], retainer["id"], channel="GOOGLE_ADS", budget_cents=500000
    )
    paused = validate_success(api.pause_client(client["id"], AM))
    assert paused["status"] == "PAUSED"

    retainer_after = validate_success(api.get_retainer(retainer["id"], ADMIN))
    assert retainer_after["status"] == "SUSPENDED", (
        f"ACTIVE retainer should cascade to SUSPENDED, got {retainer_after['status']}"
    )
    campaign_after = validate_success(api.get_ad_campaign(campaign["id"], ADMIN))
    assert campaign_after["lifecycle_status"] == "PAUSED", (
        f"LIVE campaign should cascade to PAUSED, got {campaign_after['lifecycle_status']}"
    )
