"""Composite setup helpers.

Each helper builds its preconditions from scratch via the PRD-declared
endpoints (the runner restarts the server before every test, so every test
starts against an empty database). Setup calls use get_success_data() so a
failed precondition raises a clear "Setup step failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC, TEST_DEFAULTS
from .factories import (
    create_budget_line_payload,
    create_cost_share_payload,
    create_fa_rate_agreement_payload,
    create_offer_payload,
    create_opportunity_payload,
    create_pi_payload,
    create_proposal_payload,
    create_review_payload,
    create_sub_commitment_payload,
    create_subrecipient_org_payload,
)
from .test_users import (
    TEST_USERS,
    make_analyst_headers,
    make_chair_headers,
    make_director_headers,
    make_pi_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
CHAIR = TEST_USERS["chair_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
SUBMGR = TEST_USERS["sub_manager_headers"]
DIRECTOR = TEST_USERS["director_headers"]


# ---------------------------------------------------------------------------
# Tier 0: base entities
# ---------------------------------------------------------------------------

def reset_clock(to_iso8601=DEFAULT_CLOCK_UTC):
    """Pin the logical clock to an exact instant (PRD §2.4)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    )


def make_opportunity(**overrides):
    """Intake a funding opportunity. Returns the opportunity dict."""
    return get_success_data(
        api_client.create_funding_opportunity(create_opportunity_payload(**overrides), ADMIN)
    )


def make_pi(**overrides):
    """Register a principal investigator. Returns the PI dict."""
    return get_success_data(
        api_client.create_principal_investigator(create_pi_payload(**overrides), ADMIN)
    )


def make_rate_agreement(**overrides):
    """Create an F&A rate agreement (PROVISIONAL unless initial_status given)."""
    return get_success_data(
        api_client.create_fa_rate_agreement(
            create_fa_rate_agreement_payload(**overrides), DIRECTOR
        )
    )


def make_org(**overrides):
    """Register a subrecipient org; risk score/tier computed on the spot."""
    return get_success_data(
        api_client.create_subrecipient_org(
            create_subrecipient_org_payload(**overrides), SUBMGR
        )
    )


def make_proposal(opportunity_id, pi_id, **overrides):
    """Create a proposal as its owning PI (identity threading, PRD §2.1)."""
    return get_success_data(
        api_client.create_proposal(
            create_proposal_payload(opportunity_id, pi_id, **overrides),
            make_pi_headers(pi_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 1: standard context + state progression
# ---------------------------------------------------------------------------

def make_context(**opp_overrides):
    """Opportunity + eligible PI + 54% ON_CAMPUS rate agreement.

    Returns dict(ctx=..., opp, pi, rate).
    """
    opp = make_opportunity(**opp_overrides)
    pi = make_pi()
    rate = make_rate_agreement()
    return {"opp": opp, "pi": pi, "rate": rate}


def get_proposal(proposal_id):
    return get_success_data(api_client.get_proposal(proposal_id, DIRECTOR))


def get_version(proposal_id) -> int:
    return get_proposal(proposal_id)["version"]


def add_budget_line(proposal_id, **overrides):
    return get_success_data(
        api_client.create_budget_line(
            proposal_id, create_budget_line_payload(**overrides), ANALYST
        )
    )


def finalize_budget(proposal_id, expected_version=None):
    """Finalize the proposal's budget; returns the new CURRENT snapshot."""
    if expected_version is None:
        expected_version = get_version(proposal_id)
    return get_success_data(
        api_client.create_budget_finalization(
            proposal_id, {"expected_proposal_version": expected_version}, ANALYST
        )
    )


def route_proposal(proposal_id, router_user_id="analyst-1"):
    return get_success_data(
        api_client.route_proposal(proposal_id, make_analyst_headers(router_user_id))
    )


def approve_institutional(proposal_id, approver_user_id="director-1"):
    return get_success_data(
        api_client.approve_institutional(
            proposal_id, make_director_headers(approver_user_id)
        )
    )


def submit_proposal(proposal_id, idempotency_key):
    return get_success_data(
        api_client.submit_proposal(proposal_id, {"idempotency_key": idempotency_key}, DIRECTOR)
    )


def make_locked_proposal(ctx=None, line_amount=10_000_000, fa_base_type="TDC",
                         proposal_overrides=None, **opp_overrides):
    """Proposal with one PERSONNEL line, finalized -> BUDGET_LOCKED.

    Returns dict(ctx, proposal, snapshot).
    """
    if ctx is None:
        ctx = make_context(**opp_overrides)
    overrides = dict(proposal_overrides or {})
    overrides.setdefault("fa_base_type", fa_base_type)
    proposal = make_proposal(ctx["opp"]["id"], ctx["pi"]["id"], **overrides)
    add_budget_line(proposal["id"], amount_cents=line_amount)
    snapshot = finalize_budget(proposal["id"])
    return {"ctx": ctx, "proposal": get_proposal(proposal["id"]), "snapshot": snapshot}


def make_routed_proposal(ctx=None, router_user_id="analyst-1", **kwargs):
    """BUDGET_LOCKED proposal routed for institutional approval."""
    env = make_locked_proposal(ctx=ctx, **kwargs)
    route_proposal(env["proposal"]["id"], router_user_id)
    env["proposal"] = get_proposal(env["proposal"]["id"])
    env["router_user_id"] = router_user_id
    return env


def make_approved_proposal(ctx=None, approver_user_id="director-1", **kwargs):
    """Routed proposal institutionally approved (snapshot pinned)."""
    env = make_routed_proposal(ctx=ctx, **kwargs)
    approve_institutional(env["proposal"]["id"], approver_user_id)
    env["proposal"] = get_proposal(env["proposal"]["id"])
    env["approver_user_id"] = approver_user_id
    return env


def make_submitted_proposal(ctx=None, idempotency_key=None, **kwargs):
    """INSTITUTIONALLY_APPROVED proposal submitted to the sponsor portal."""
    env = make_approved_proposal(ctx=ctx, **kwargs)
    key = idempotency_key or f"sub-{env['proposal']['id'][:8]}"
    env["package"] = submit_proposal(env["proposal"]["id"], key)
    env["proposal"] = get_proposal(env["proposal"]["id"])
    return env


def make_negotiating_proposal(ctx=None, offered_total_cents=14_000_000, **kwargs):
    """SUBMITTED proposal with an open negotiation round (-> NEGOTIATING)."""
    env = make_submitted_proposal(ctx=ctx, **kwargs)
    offer = get_success_data(
        api_client.create_negotiation_offer(
            env["proposal"]["id"],
            create_offer_payload(
                env["proposal"]["version"], offered_total_cents=offered_total_cents
            ),
            DIRECTOR,
        )
    )
    env["offer"] = offer
    env["proposal"] = get_proposal(env["proposal"]["id"])
    return env


def make_awarded_proposal(ctx=None, offered_total_cents=14_000_000, **kwargs):
    """NEGOTIATING proposal whose open offer is accepted -> AWARDED.

    The award auto-creates the proposal's AwardHandoff (DRAFT).
    Returns env with keys: ctx, proposal, offer, handoff.
    """
    env = make_negotiating_proposal(
        ctx=ctx, offered_total_cents=offered_total_cents, **kwargs
    )
    get_success_data(api_client.accept_negotiation_offer(env["offer"]["id"], DIRECTOR))
    env["proposal"] = get_proposal(env["proposal"]["id"])
    handoffs, _meta = _list_handoff_entries(env["proposal"]["id"])
    env["handoff"] = handoffs[0]
    return env


def _list_handoff_entries(proposal_id):
    resp = api_client.list_award_handoffs(proposal_id, DIRECTOR)
    data = get_success_data(resp)
    return data, None


def get_handoff(proposal_id):
    """The proposal's single handoff entry, or None."""
    data = get_success_data(api_client.list_award_handoffs(proposal_id, DIRECTOR))
    return data[0] if data else None


# ---------------------------------------------------------------------------
# Tier 2: domain children
# ---------------------------------------------------------------------------

def pledge_cost_share(proposal_id, amount_cents, source_type="DEPARTMENT",
                      committed_by="analyst-1"):
    return get_success_data(
        api_client.create_cost_share_commitment(
            proposal_id,
            create_cost_share_payload(source_type=source_type, amount_cents=amount_cents),
            make_analyst_headers(committed_by),
        )
    )


def approve_cost_share(commitment_id, approver="chair-1"):
    return get_success_data(
        api_client.approve_cost_share_commitment(
            commitment_id, make_chair_headers(approver)
        )
    )


def pledge_and_approve_cost_share(proposal_id, amount_cents, source_type="DEPARTMENT",
                                  committed_by="analyst-1", approver="chair-1"):
    commitment = pledge_cost_share(
        proposal_id, amount_cents, source_type=source_type, committed_by=committed_by
    )
    return approve_cost_share(commitment["id"], approver)


def make_sub_commitment(proposal_id, org_id, **overrides):
    return get_success_data(
        api_client.create_subrecipient_commitment(
            proposal_id, create_sub_commitment_payload(org_id, **overrides), ANALYST
        )
    )


def verify_sub_commitment(commitment_id):
    return get_success_data(api_client.verify_subrecipient_commitment(commitment_id, SUBMGR))


def open_review(proposal_id, review_type="IRB", **overrides):
    return get_success_data(
        api_client.create_compliance_review(
            proposal_id, create_review_payload(review_type=review_type, **overrides),
            COMPLIANCE,
        )
    )


def approve_review(review_id, validity_days=None):
    payload = {} if validity_days is None else {"validity_days": validity_days}
    return get_success_data(api_client.approve_review(review_id, payload, COMPLIANCE))


def open_offer(proposal_id, offered_total_cents=14_000_000, origin="SPONSOR"):
    """Open a negotiation round with the proposal's live version (OCC)."""
    version = get_version(proposal_id)
    return get_success_data(
        api_client.create_negotiation_offer(
            proposal_id,
            create_offer_payload(version, origin=origin,
                                 offered_total_cents=offered_total_cents),
            DIRECTOR,
        )
    )
