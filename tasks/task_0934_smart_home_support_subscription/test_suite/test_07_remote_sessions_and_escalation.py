"""Remote troubleshooting sessions and the five-hop escalation cascade."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    complete_session,
    fetch_campaign,
    fetch_device,
    fetch_rollout,
    fetch_session,
    fetch_ticket,
    first_response,
    new_ticket,
    open_session,
    set_clock,
    setup_ring,
    validate_error,
    validate_success,
)

AGENT = TEST_USERS["support_agent_headers"]


def test_remote_session_read_with_unknown_id_reports_session_not_found(api):
    """PRD 2.9 rung 11: "Every `RemoteSession` id named in the path exists — otherwise
    `ERR_SESSION_NOT_FOUND`. Applies to session completion and the single-session
    read."

    Design: Corner/entities/remote_session_get_with_unknown_id_returns_not_found
    """
    set_clock("2026-05-01T00:00:00Z")
    response = api.get_remote_session("00000000-0000-4000-8000-000000000000", AGENT)
    validate_error(response, ApiErrorId.ERR_SESSION_NOT_FOUND.value, 404)


# ==========================================================================
# Difficulty: one completing request propagates through five entities
# ==========================================================================
def _third_failure_world():
    """A ring-enrolled HUB whose ticket has already taken two FAILED verdicts."""
    world = setup_ring(
        device_count=1,
        kind="SECURITY_MANDATORY",
        halt_failure_rate_pct=0.5,
        plan_kind="PRO",
        allow_overage=False,
        name="Cascade House",
        email_prefix="casc",
    )
    device = world["devices"][0]
    ticket = new_ticket(
        world["household"]["id"],
        AGENT,
        severity="P1",
        summary="Hub unresponsive",
        device_id=device["id"],
    )
    first_response(ticket["id"], "Triaged immediately.")

    session_one = open_session(ticket["id"])
    complete_session(session_one["id"], "FAILED", "No link.")
    session_two = open_session(ticket["id"])
    complete_session(session_two["id"], "FAILED", "Still no link.")
    session_three = open_session(ticket["id"])

    world["ticket"] = ticket
    world["session_three"] = session_three
    return world


def test_third_failed_verdict_escalates_the_session_and_the_ticket(api):
    """PRD 3.7: "When the `outcome` is `FAILED`, the ticket's
    `remote_session_failure_count` is incremented by one and escalation occurs when
    the **post-increment** value has reached 3; the escalation reason is
    `FAILURE_THRESHOLD`."
    PRD 3.7: "**Hop 1 — the session.** `outcome` is recorded, `ended_at` is stamped
    with the logical-clock instant, and `status` becomes `COMPLETED`."
    PRD 3.7: "**Hop 2 — the ticket.** On a failing verdict
    `remote_session_failure_count` is incremented; when the incremented count has
    reached 3, or whenever the verdict is `HARDWARE_FAULT`, `workflow_status` moves
    `REMOTE_DIAG → DISPATCH_PENDING`, `dispatch_status` moves `NOT_REQUIRED →
    REQUIRED`, and `escalation_reason` is set to `FAILURE_THRESHOLD` or
    `HARDWARE_FAULT` accordingly."

    Design: Difficulty/transitive_cascade/third_failed_remote_session_cascades_five_hops_to_campaign_completion
    """
    world = _third_failure_world()

    validate_success(
        api.complete_remote_session(
            world["session_three"]["id"],
            {"outcome": "FAILED", "diagnostic_notes": "Third strike."},
            AGENT,
        ),
        200,
    )

    session = fetch_session(world["session_three"]["id"])
    assert session["status"] == "COMPLETED"
    assert session["outcome"] == "FAILED"

    ticket = fetch_ticket(world["ticket"]["id"])
    assert ticket["remote_session_failure_count"] == 3
    assert ticket["workflow_status"] == "DISPATCH_PENDING"
    assert ticket["dispatch_status"] == "REQUIRED"
    assert ticket["escalation_reason"] == "FAILURE_THRESHOLD"


def test_escalation_cascades_on_to_the_device_rollout_and_campaign(api):
    """PRD 3.7: "**Hop 3 — the device.** When the ticket's `device_id` is not null and
    that device's `lifecycle_status` is `ACTIVE`, the device moves `ACTIVE →
    SERVICE_HOLD`."
    PRD 3.7: "**Hop 4 — the rollouts.** Every `FirmwareRollout` targeting that device
    whose `status` is `PENDING` moves to `BLOCKED_BY_SERVICE`, and the device's
    `firmware_status` moves to `BLOCKED` where it stood at `UPDATE_PENDING`."
    PRD 3.7: "**Hop 5 — the campaign.** The ring counters of each affected
    `FirmwareCampaign` are recomputed, and a campaign in `RING_ACTIVE` whose current
    ring is left with no `PENDING` rollouts, while its ring failure rate is below its
    halt threshold, becomes `COMPLETED`."

    Design: Difficulty/transitive_cascade/third_failed_remote_session_cascades_five_hops_to_campaign_completion
    """
    world = _third_failure_world()

    validate_success(
        api.complete_remote_session(
            world["session_three"]["id"],
            {"outcome": "FAILED", "diagnostic_notes": "Third strike."},
            AGENT,
        ),
        200,
    )

    device = fetch_device(world["devices"][0]["id"])
    assert device["lifecycle_status"] == "SERVICE_HOLD"
    assert device["firmware_status"] == "BLOCKED"

    rollout = fetch_rollout(world["rollouts"][0]["id"])
    assert rollout["status"] == "BLOCKED_BY_SERVICE"

    campaign = fetch_campaign(world["campaign_id"])
    assert campaign["status"] == "COMPLETED"
    assert campaign["ring_device_count"] == 1
    assert campaign["ring_failed_count"] == 0
    assert campaign["ring_failure_rate"] == 0
