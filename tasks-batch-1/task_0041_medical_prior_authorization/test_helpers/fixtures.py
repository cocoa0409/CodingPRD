"""Composite setup helpers for the medical prior-authorization workflow.

Every fixture builds its preconditions from scratch (the server DB is empty at
the start of every test) using only PRD-declared endpoints. Setup calls use the
lenient get_success_data() so a broken precondition surfaces as a clear failure.

Identity threading: Provider and Payer are entity_backed roles, so ownership-gated
calls use make_provider_headers(provider["id"]) / make_payer_headers(payer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_provider_headers,
    make_payer_headers,
    make_external_reviewer_headers,
)
from .factories import (
    create_provider_payload,
    create_payer_payload,
    create_member_payload,
    create_reviewer_payload,
    create_authorization_request_payload,
    create_clinical_evidence_payload,
    create_review_decision_payload,
    create_peer_to_peer_session_payload,
    create_appeal_payload,
)

ANON = TEST_USERS["anonymous_headers"]


# --------------------------------------------------------------------------
# Tier 0: actor registration + clock
# --------------------------------------------------------------------------

def register_actors(payer_overrides=None, member_overrides=None,
                     provider_overrides=None, reviewer_overrides=None,
                     with_reviewer=True):
    """Register payer, member, provider, (optionally) reviewer. Returns dict of entities."""
    payer = get_success_data(
        api_client.create_payer(create_payer_payload(**(payer_overrides or {})), ANON)
    )
    member = get_success_data(
        api_client.create_member(
            create_member_payload(payer["id"], **(member_overrides or {})), ANON
        )
    )
    provider = get_success_data(
        api_client.create_provider(create_provider_payload(**(provider_overrides or {})), ANON)
    )
    out = {"payer": payer, "member": member, "provider": provider}
    if with_reviewer:
        rev_over = dict(reviewer_overrides or {})
        rev_over.setdefault("specialty", provider.get("specialty", "ONCOLOGY"))
        reviewer = get_success_data(
            api_client.create_reviewer(create_reviewer_payload(payer["id"], **rev_over), ANON)
        )
        out["reviewer"] = reviewer
    return out


def set_clock(iso, actor_headers=None):
    """Pin the server clock. Provider/Payer/ExternalReviewer may all do this."""
    headers = actor_headers or TEST_USERS["provider_headers"]
    return get_success_data(api_client.set_clock(iso, headers))


# --------------------------------------------------------------------------
# Tier 1: state progression for AuthorizationRequest
# --------------------------------------------------------------------------

def create_draft_request(actors, request_overrides=None):
    """Create a DRAFT AuthorizationRequest owned by the provider."""
    prov = actors["provider"]
    payload = create_authorization_request_payload(
        actors["member"]["id"], prov["id"], **(request_overrides or {})
    )
    return get_success_data(
        api_client.create_authorization_request(payload, make_provider_headers(prov["id"]))
    )


def add_evidence(actors, request_id, evidence_overrides=None):
    """Upload one ClinicalEvidence row for a request (Provider-owned)."""
    prov = actors["provider"]
    payload = create_clinical_evidence_payload(request_id, **(evidence_overrides or {}))
    return get_success_data(
        api_client.create_clinical_evidence(payload, make_provider_headers(prov["id"]))
    )


def create_submitted_request(actors, request_overrides=None, evidence_overrides=None):
    """DRAFT -> SUBMITTED: create request, add one evidence row, submit."""
    prov = actors["provider"]
    req = create_draft_request(actors, request_overrides)
    add_evidence(actors, req["id"], evidence_overrides)
    submitted = get_success_data(
        api_client.submit_request(req["id"], make_provider_headers(prov["id"]))
    )
    return submitted


def create_under_review_request(actors, request_overrides=None, evidence_overrides=None):
    """DRAFT -> SUBMITTED -> UNDER_REVIEW."""
    payer = actors["payer"]
    submitted = create_submitted_request(actors, request_overrides, evidence_overrides)
    ur = get_success_data(
        api_client.start_review(submitted["id"], make_payer_headers(payer["id"]))
    )
    return ur


# --------------------------------------------------------------------------
# Tier 3: decision shortcuts (drive to APPROVED / DENIED / PENDED)
# --------------------------------------------------------------------------

def render_decision(actors, request_id, outcome, **decision_overrides):
    """POST a ReviewDecision driving the request out of UNDER_REVIEW."""
    payer = actors["payer"]
    payload = create_review_decision_payload(
        request_id, actors["reviewer"]["id"], outcome, **decision_overrides
    )
    return api_client.create_review_decision(payload, make_payer_headers(payer["id"]))


def create_approved_request(actors, request_overrides=None, approved_units=1,
                            evidence_overrides=None, outcome="APPROVE"):
    """Full chain to APPROVED via APPROVE (or PARTIAL) decision."""
    req = create_under_review_request(actors, request_overrides, evidence_overrides)
    dec_kwargs = {"approved_units": approved_units, "rationale": "OK"}
    get_success_data(render_decision(actors, req["id"], outcome, **dec_kwargs))
    return get_success_data(
        api_client.get_authorization_request(
            req["id"], make_provider_headers(actors["provider"]["id"])
        )
    )


def create_denied_request(actors, request_overrides=None, evidence_overrides=None):
    """Full chain to DENIED via DENY decision."""
    req = create_under_review_request(actors, request_overrides, evidence_overrides)
    get_success_data(render_decision(actors, req["id"], "DENY", rationale="Not indicated"))
    return get_success_data(
        api_client.get_authorization_request(
            req["id"], make_provider_headers(actors["provider"]["id"])
        )
    )


def create_pended_request(actors, request_overrides=None, evidence_overrides=None,
                          pend_reason="INSUFFICIENT_EVIDENCE"):
    """Full chain to PENDED via PEND decision."""
    req = create_under_review_request(actors, request_overrides, evidence_overrides)
    get_success_data(render_decision(actors, req["id"], "PEND", pend_reason=pend_reason))
    return get_success_data(
        api_client.get_authorization_request(
            req["id"], make_provider_headers(actors["provider"]["id"])
        )
    )


def create_expired_request(actors, request_overrides=None, approved_units=1,
                           expire_clock="2027-06-02T00:00:00Z"):
    """APPROVED -> EXPIRED: approve, advance clock past expiry, expire."""
    payer = actors["payer"]
    approved = create_approved_request(actors, request_overrides, approved_units)
    set_clock(expire_clock, make_payer_headers(payer["id"]))
    expired = get_success_data(
        api_client.expire_request(approved["id"], make_payer_headers(payer["id"]))
    )
    return expired


# --------------------------------------------------------------------------
# Tier 4: P2P sessions
# --------------------------------------------------------------------------

def schedule_p2p(actors, request_id, slot_start, slot_end):
    """Schedule a P2P session on the reviewer for a request (Payer-owned)."""
    payer = actors["payer"]
    payload = create_peer_to_peer_session_payload(
        request_id, actors["reviewer"]["id"], slot_start, slot_end
    )
    return api_client.create_peer_to_peer_session(payload, make_payer_headers(payer["id"]))


# --------------------------------------------------------------------------
# Tier 5: appeals
# --------------------------------------------------------------------------

def file_appeal(actors, request_id):
    """File / escalate an appeal (Provider-owned)."""
    prov = actors["provider"]
    return api_client.create_appeal(create_appeal_payload(request_id), make_provider_headers(prov["id"]))


def create_open_tier1_appeal(actors, request_overrides=None):
    """DENIED request with an OPEN tier-1 appeal. Returns (denied_request, appeal)."""
    denied = create_denied_request(actors, request_overrides)
    appeal = get_success_data(file_appeal(actors, denied["id"]))
    return denied, appeal


def decide_appeal(actors, appeal_id, decision, rationale="Decided"):
    """Tier-1/2 payer appeal decision."""
    payer = actors["payer"]
    payload = {"decision": decision, "decision_rationale": rationale}
    return api_client.decide_appeal(appeal_id, payload, make_payer_headers(payer["id"]))


def escalate_to_tier(actors, request_id, target_tier):
    """Escalate a DENIED request's appeal chain up to target_tier (2 or 3) by
    UPHELDing each prior tier and re-filing. Returns the OPEN appeal at target_tier."""
    prov = actors["provider"]
    # tier 1
    appeal = get_success_data(file_appeal(actors, request_id))
    current_tier = 1
    while current_tier < target_tier:
        get_success_data(decide_appeal(actors, appeal["id"], "UPHELD", "Stands"))
        appeal = get_success_data(file_appeal(actors, request_id))
        current_tier += 1
    return appeal


def create_tier3_open_appeal(actors, request_overrides=None):
    """DENIED request escalated to a tier-3 OPEN appeal. Returns (denied_request, tier3_appeal)."""
    denied = create_denied_request(actors, request_overrides)
    appeal_t3 = escalate_to_tier(actors, denied["id"], 3)
    return denied, appeal_t3


def external_decide(actors, appeal_id, decision, rationale="IRO decision"):
    """Tier-3 external (IRO) appeal decision."""
    payload = {"decision": decision, "decision_rationale": rationale}
    return api_client.external_decide_appeal(
        appeal_id, payload, make_external_reviewer_headers()
    )
