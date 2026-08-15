"""Composite setup helpers for the Contract Redlining Playbook API.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build full preconditions from scratch using
only PRD-declared endpoints. Setup calls use get_success_data() so a broken
precondition surfaces as a clear "Setup failed" message.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK, TIMES, TEST_DEFAULTS
from .factories import (
    create_playbook_payload, create_clause_payload, create_contract_type_payload,
    create_counterparty_payload, create_user_payload, create_intake_request_payload,
    create_open_negotiation_payload, create_round_payload, create_deviation_payload,
    create_decision_payload, create_signature_packet_payload, signatory_entry,
)
from .test_users import TEST_USERS
from .types import PRIMARY_ROLE_TO_HEADER
from prd_bench_local_runner.testing import build_user_headers

OPS = TEST_USERS["ops_admin_headers"]

DEFAULT_CLAUSE_SPEC = {
    "clause_key": "CLAUSE_A",
    "category": "OPERATIONAL",
    "standard_text": "Standard text A",
    "fallback_positions": ["Fallback text A"],
    "approver_role_required": "LEGAL_COUNSEL",
    "deviation_severity_cap": "MEDIUM",
}


class Ctx(dict):
    """Attribute-accessible dict carrying one scenario's created entities."""
    __getattr__ = dict.get


# ---------------------------------------------------------------------------
# Tier 0: clock + user directory
# ---------------------------------------------------------------------------

def set_logical_clock(to_iso=CLOCK["STARTUP_UTC"]):
    """Pin the server logical clock (PRD §2.5). Returns confirmed now_iso8601."""
    resp = api_client.set_clock({"to_iso8601": to_iso}, OPS)
    data = get_success_data(resp)
    return data.get("now_iso8601", to_iso)


def create_user(email, display_name, primary_role, can_sign_above_cents=None):
    payload = create_user_payload(email, display_name, primary_role)
    if can_sign_above_cents is not None:
        payload["can_sign_above_cents"] = can_sign_above_cents
    resp = api_client.create_user(payload, OPS)
    return get_success_data(resp)


def setup_user_directory(with_second_signatory=False, signatory_cap=TEST_DEFAULTS["SIGNATORY_AUTHORITY_CENTS"]):
    """Create one ACTIVE user per role. Returns dict keyed by short name."""
    users = {
        "ca": create_user("ca@example.com", "Casey Analyst", "CONTRACT_ANALYST"),
        "bo": create_user("bo@example.com", "Blair Owner", "BUSINESS_OWNER"),
        "lc": create_user("lc@example.com", "Lee Counsel", "LEGAL_COUNSEL"),
        "fc": create_user("fc@example.com", "Fran Controller", "FINANCE_CONTROLLER"),
        "cc": create_user("cc@example.com", "Chris Chief", "CHIEF_COUNSEL"),
        "sg": create_user("sg@example.com", "Sam Signatory", "SIGNATORY",
                          can_sign_above_cents=signatory_cap),
    }
    if with_second_signatory:
        users["sg2"] = create_user("sg2@example.com", "Sasha Signatory", "SIGNATORY",
                                   can_sign_above_cents=signatory_cap)
    return users


def headers_by_id(users) -> dict:
    """Map each created user's id to auth headers carrying that id and the
    header-role spelling matching the user's persisted primary_role (PRD §2.1)."""
    return {
        u["id"]: build_user_headers(u["id"], PRIMARY_ROLE_TO_HEADER[u["primary_role"]])
        for u in users.values()
    }


# ---------------------------------------------------------------------------
# Tier 1: reference data
# ---------------------------------------------------------------------------

def create_standard_contract_type(users, code="NDA", **overrides):
    payload = create_contract_type_payload(
        users["bo"]["id"], users["lc"]["id"], code=code, **overrides)
    resp = api_client.create_contract_type(payload, OPS)
    return get_success_data(resp)


def create_standard_counterparty(risk_tier="STANDARD", legal_name="Acme Corporation",
                                 jurisdiction="US-DE"):
    payload = create_counterparty_payload(legal_name=legal_name, jurisdiction=jurisdiction)
    if risk_tier is not None:
        payload["risk_tier"] = risk_tier
    resp = api_client.create_counterparty(payload, OPS)
    return get_success_data(resp)


def create_active_playbook(cc_headers, clause_specs=None, name="Standard Playbook"):
    """Create a playbook, add clauses, publish it. Returns (playbook, clauses)."""
    resp = api_client.create_playbook(create_playbook_payload(name=name), cc_headers)
    playbook = get_success_data(resp)
    clauses = []
    for spec in (clause_specs or [DEFAULT_CLAUSE_SPEC]):
        resp = api_client.create_clause(playbook["id"], create_clause_payload(**spec), cc_headers)
        clauses.append(get_success_data(resp))
    resp = api_client.publish_playbook(playbook["id"], cc_headers)
    playbook = get_success_data(resp)
    return playbook, clauses


# ---------------------------------------------------------------------------
# Tier 2: intake → triage → negotiation
# ---------------------------------------------------------------------------

def submit_intake(users, contract_type, counterparty,
                  value_cents=TEST_DEFAULTS["CONTRACT_VALUE_CENTS"],
                  effective_date=TIMES["EFFECTIVE_DATE"]):
    hdrs = headers_by_id(users)
    payload = create_intake_request_payload(
        users["ca"]["id"], contract_type["id"], counterparty["id"],
        contract_value_cents=value_cents, effective_date=effective_date)
    resp = api_client.create_intake_request(payload, hdrs[users["ca"]["id"]])
    return get_success_data(resp)


def triage_intake(intake_id, analyst_headers, override_routing_bucket=None):
    payload = {}
    if override_routing_bucket is not None:
        payload["override_routing_bucket"] = override_routing_bucket
    resp = api_client.triage_intake_request(intake_id, payload, analyst_headers)
    return get_success_data(resp)


def submit_and_triage(users, contract_type, counterparty,
                      value_cents=TEST_DEFAULTS["CONTRACT_VALUE_CENTS"],
                      effective_date=TIMES["EFFECTIVE_DATE"]):
    """Create an intake and run triage. Returns the ROUTED intake (with version)."""
    hdrs = headers_by_id(users)
    intake = submit_intake(users, contract_type, counterparty, value_cents, effective_date)
    return triage_intake(intake["id"], hdrs[users["ca"]["id"]])


def open_negotiation_from_intake(intake, playbook, drafter_user_id, analyst_headers):
    payload = create_open_negotiation_payload(
        playbook["id"], drafter_user_id, intake["version"])
    resp = api_client.open_negotiation(intake["id"], payload, analyst_headers)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: full negotiation contexts
# ---------------------------------------------------------------------------

def setup_negotiation_ctx(value_cents=TEST_DEFAULTS["CONTRACT_VALUE_CENTS"],
                          risk_tier="STANDARD",
                          clause_specs=None,
                          ct_code="NDA",
                          ct_overrides=None,
                          drafter="ca",
                          with_second_signatory=False,
                          signatory_cap=TEST_DEFAULTS["SIGNATORY_AUTHORITY_CENTS"],
                          pin_clock=True):
    """Full chain: users -> contract type -> counterparty -> published playbook
    -> routed intake -> opened negotiation (draft_status OPEN). Returns Ctx."""
    if pin_clock:
        set_logical_clock()
    users = setup_user_directory(with_second_signatory=with_second_signatory,
                                 signatory_cap=signatory_cap)
    hdrs = headers_by_id(users)
    ct = create_standard_contract_type(users, code=ct_code, **(ct_overrides or {}))
    cp = create_standard_counterparty(risk_tier=risk_tier)
    playbook, clauses = create_active_playbook(hdrs[users["cc"]["id"]], clause_specs)
    intake = submit_and_triage(users, ct, cp, value_cents)
    negotiation = open_negotiation_from_intake(
        intake, playbook, users[drafter]["id"], hdrs[users["ca"]["id"]])
    return Ctx(users=users, headers=hdrs, contract_type=ct, counterparty=cp,
               playbook=playbook, clauses=clauses, intake=intake,
               negotiation=negotiation)


def refresh_negotiation(ctx):
    resp = api_client.get_negotiation(ctx.negotiation["id"], ctx.headers[ctx.users["ca"]["id"]])
    ctx["negotiation"] = get_success_data(resp)
    return ctx.negotiation


def open_round(ctx, change_summary="Round opened"):
    resp = api_client.create_round(
        ctx.negotiation["id"], create_round_payload(change_summary=change_summary),
        ctx.headers[ctx.users["ca"]["id"]])
    new_round = get_success_data(resp)
    ctx.setdefault("rounds", []).append(new_round)
    refresh_negotiation(ctx)
    return new_round


def close_round(ctx, round_id):
    resp = api_client.close_round(
        ctx.negotiation["id"], round_id, ctx.headers[ctx.users["ca"]["id"]])
    closed = get_success_data(resp)
    refresh_negotiation(ctx)
    return closed


def setup_redlining_ctx(**kwargs):
    """Negotiation in REDLINING with round 1 OPEN. Returns Ctx."""
    ctx = setup_negotiation_ctx(**kwargs)
    open_round(ctx, "Round 1")
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: deviation lifecycle
# ---------------------------------------------------------------------------

def record_deviation(ctx, clause_index=0, proposed_text="Counterparty proposal",
                     fallback_index=-1, creator="ca"):
    creator_headers = ctx.headers[ctx.users[creator]["id"]]
    payload = create_deviation_payload(
        ctx.clauses[clause_index]["id"], proposed_text=proposed_text,
        fallback_index=fallback_index)
    resp = api_client.create_deviation(ctx.negotiation["id"], payload, creator_headers)
    deviation = get_success_data(resp)
    refresh_negotiation(ctx)
    return deviation


def get_deviation(ctx, deviation_id):
    resp = api_client.get_deviation(
        ctx.negotiation["id"], deviation_id, ctx.headers[ctx.users["ca"]["id"]])
    return get_success_data(resp)


def begin_review(ctx, deviation, actor_id=None):
    """Begin review as the assigned approver (or a supplied actor)."""
    actor = actor_id or deviation["assigned_approver_id"]
    resp = api_client.begin_review(
        ctx.negotiation["id"], deviation["id"], ctx.headers[actor])
    reviewed = get_success_data(resp)
    refresh_negotiation(ctx)
    return reviewed


def decide(ctx, deviation, decision, actor_id=None, rationale=None):
    """Cast a decision as the assigned approver with a fresh OCC version."""
    actor = actor_id or deviation["assigned_approver_id"]
    negotiation = refresh_negotiation(ctx)
    payload = create_decision_payload(decision, negotiation["version"])
    if rationale is not None:
        payload["decision_rationale"] = rationale
    resp = api_client.decide_deviation(
        ctx.negotiation["id"], deviation["id"], payload, ctx.headers[actor])
    return resp  # caller validates success/error


def decide_ok(ctx, deviation, decision, actor_id=None, rationale=None):
    resp = decide(ctx, deviation, decision, actor_id=actor_id, rationale=rationale)
    decided = get_success_data(resp)
    refresh_negotiation(ctx)
    return decided


def approve_deviation(ctx, deviation):
    """Full happy-path: begin-review as assigned approver, then APPROVE."""
    reviewed = begin_review(ctx, deviation)
    return decide_ok(ctx, reviewed, "APPROVE")


def withdraw_deviation(ctx, deviation):
    resp = api_client.withdraw_deviation(
        ctx.negotiation["id"], deviation["id"], ctx.headers[ctx.negotiation["drafter_user_id"]])
    withdrawn = get_success_data(resp)
    refresh_negotiation(ctx)
    return withdrawn


# ---------------------------------------------------------------------------
# Tier 5: finalization, signature packets, execution
# ---------------------------------------------------------------------------

def finalize_redlining(ctx, override=False):
    payload = {}
    if override:
        payload["playbook_staleness_override"] = True
    resp = api_client.finalize_redlining(
        ctx.negotiation["id"], payload, ctx.headers[ctx.users["lc"]["id"]])
    finalized = get_success_data(resp)
    ctx["negotiation"] = finalized
    return finalized


def setup_awaiting_countersign_ctx(**kwargs):
    """Negotiation finalized to AWAITING_COUNTERSIGN with no deviations."""
    ctx = setup_redlining_ctx(**kwargs)
    finalize_redlining(ctx)
    return ctx


def create_packet(ctx, signatory_user_ids, opens_at=TIMES["WINDOW_OPENS"],
                  closes_at=TIMES["WINDOW_CLOSES"]):
    signatories = [
        signatory_entry(uid, i + 1) for i, uid in enumerate(signatory_user_ids)
    ]
    negotiation = refresh_negotiation(ctx)
    payload = create_signature_packet_payload(
        signatories, negotiation["version"], opens_at=opens_at, closes_at=closes_at)
    resp = api_client.create_signature_packet(
        ctx.negotiation["id"], payload, ctx.headers[ctx.users["lc"]["id"]])
    packet = get_success_data(resp)
    refresh_negotiation(ctx)
    return packet


def get_packet(ctx, packet_id):
    resp = api_client.get_signature_packet(
        ctx.negotiation["id"], packet_id, ctx.headers[ctx.users["lc"]["id"]])
    return get_success_data(resp)


def sign_packet(ctx, packet_id, signatory_user_id):
    resp = api_client.sign_packet(
        ctx.negotiation["id"], packet_id, ctx.headers[signatory_user_id])
    return resp


def sign_packet_ok(ctx, packet_id, signatory_user_id):
    packet = get_success_data(sign_packet(ctx, packet_id, signatory_user_id))
    refresh_negotiation(ctx)
    return packet


def setup_fully_signed_ctx(signatory_count=1, **kwargs):
    """AWAITING_COUNTERSIGN negotiation + packet signed by every signatory."""
    ctx = setup_awaiting_countersign_ctx(
        with_second_signatory=signatory_count > 1, **kwargs)
    ids = [ctx.users["sg"]["id"]]
    if signatory_count > 1:
        ids.append(ctx.users["sg2"]["id"])
    packet = create_packet(ctx, ids)
    for uid in ids:
        packet = sign_packet_ok(ctx, packet["id"], uid)
    ctx["packet"] = packet
    return ctx
