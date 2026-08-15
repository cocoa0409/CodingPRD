"""Role authorization and entity-backed identity checks (PRD §2.1, §4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_agent,
    create_lead_source,
    create_partner,
    create_team,
    ctx_pending_deal,
    ctx_routing,
    get_deal,
    get_lead,
    intake_lead,
    lead_payload,
    make_agent_headers,
    make_referral_partner_headers,
    make_team_leader_headers,
    routing_policy_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["team_admin_headers"]


def test_agent_cannot_create_routing_policy_returns_403(api):
    """PRD §2.1: "A request whose role is not among those permitted on the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/crm/routing-policies` | Create a `DRAFT` routing policy | TeamAdmin |"

    Design: Corner/rbac/agent_cannot_create_routing_policy_returns_403
    """
    team = create_team()
    agent = create_agent(team["id"], "LIC-A")

    res = api.create_routing_policy(
        routing_policy_payload(team["id"], "ROUND_ROBIN"), make_agent_headers(agent["id"])
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)

    policies, _meta = validate_paginated(
        api.list_routing_policies(ADMIN, params={"team_id": team["id"]})
    )
    assert policies == [], "No policy may be created by the rejected call"


def test_claim_by_non_offered_agent_returns_403(api):
    """PRD §3.4: "Only the offered agent may claim: the caller's identity must equal the current `OFFERED` assignment's `agent_id`, and an `ACTIVE` agent who is not the offered agent is rejected with `ERR_NOT_OFFERED_TO_AGENT`."

    Design: Corner/rbac/claim_by_non_offered_agent_returns_403
    """
    ctx = ctx_routing(
        agents=(
            {"display_name": "Agent A", "license_number": "LIC-A", "max_active_leads": 5},
            {"display_name": "Agent B", "license_number": "LIC-B", "max_active_leads": 5},
        )
    )
    a, b = ctx["agents"]
    lead = intake_lead(ctx["team"]["id"], ctx["source"]["id"], "+15125550140")
    assert lead["assigned_agent_id"] == a["id"], "First-created agent wins the round robin"

    res = api.claim_lead(lead["id"], make_agent_headers(b["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_OFFERED_TO_AGENT, expected_status=403)

    after = get_lead(lead["id"])
    assert after["status"] == "OFFERED"
    assert after["assigned_agent_id"] == a["id"]


def test_partner_identity_mismatch_on_referral_intake(api):
    """PRD §3.3: "A `ReferralPartner` caller must pass their own id as `referral_partner_id` (a mismatch is `ERR_PARTNER_IDENTITY_MISMATCH`), which confines partner intake to referral-type sources."
    PRD §2.1: "When `X-User-Role` is `ReferralPartner`, `X-User-ID` is the `id` of the acting referral partner, and lead intake compares the payload's `referral_partner_id` against `X-User-ID`."

    Design: Corner/rbac/partner_identity_mismatch_on_referral_intake
    """
    team = create_team()
    source = create_lead_source(
        team["id"], name="Referrals", type="REFERRAL_PARTNER", auto_route=False
    )
    p1 = create_partner(team["id"], name="Pat One", fee_bps=2500)
    p2 = create_partner(team["id"], name="Pat Two", fee_bps=3000)

    stolen = api.create_lead(
        lead_payload(
            team["id"], source["id"], "+15125550141",
            contact_name="Stolen", contact_email="s@x.com",
            referral_partner_id=p2["id"],
        ),
        make_referral_partner_headers(p1["id"]),
    )
    validate_error(stolen, ApiErrorId.ERR_PARTNER_IDENTITY_MISMATCH, expected_status=403)

    own = validate_success(
        api.create_lead(
            lead_payload(
                team["id"], source["id"], "+15125550142",
                contact_name="Own", contact_email="o@x.com",
                referral_partner_id=p1["id"],
            ),
            make_referral_partner_headers(p1["id"]),
        ),
        201,
    )
    assert own["referral_partner_id"] == p1["id"]


def test_teamleader_role_requires_leader_identity(api):
    """PRD §3.6: "Only a `TeamLeader` approves deals, and that caller must resolve to an agent with `role_on_team` `LEADER` on the deal's team, else `ERR_AGENT_IDENTITY_MISMATCH`."
    PRD §2.1: "When `X-User-Role` is `TeamLeader`, `X-User-ID` is the `id` of the acting agent — specifically an agent whose `role_on_team` is `LEADER` on the relevant team — and a caller who does not resolve to such an agent fails identity-scoped operations with `ERR_AGENT_IDENTITY_MISMATCH`."

    Design: Corner/rbac/teamleader_role_requires_leader_identity
    """
    ctx = ctx_pending_deal(500_000)
    member = create_agent(ctx["team"]["id"], "LIC-M", display_name="Member M")

    res = api.approve_deal(
        ctx["deal"]["id"], {}, make_team_leader_headers(member["id"])
    )
    validate_error(res, ApiErrorId.ERR_AGENT_IDENTITY_MISMATCH, expected_status=403)
    assert get_deal(ctx["deal"]["id"])["status"] == "PENDING"


def test_agent_role_cannot_approve_deal_returns_403(api):
    """PRD §2.1: "A request whose role is not among those permitted on the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §4: "| POST | `/crm/deals/{dealId}/approve` | Approve a `PENDING` or `DISPUTED` deal, cascading the lead to `CLOSED_WON` | TeamLeader |"

    Design: Corner/rbac/agent_role_cannot_approve_deal_returns_403
    """
    ctx = ctx_pending_deal(500_000)

    res = api.approve_deal(
        ctx["deal"]["id"], {}, make_agent_headers(ctx["closer"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)
    assert get_deal(ctx["deal"]["id"])["status"] == "PENDING"
