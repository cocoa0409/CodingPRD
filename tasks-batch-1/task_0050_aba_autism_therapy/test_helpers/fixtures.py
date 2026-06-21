"""Composite setup helpers.

The dominant precondition across the suite is an ACTIVE Authorization funding an
APPROVED plan for an ACTIVE client, reachable only through a long chain:

    payer -> BCBA (+ RBT) -> client -> evaluation -> submit -> finalize ->
    plan -> submit -> approve -> authorization

These helpers encapsulate that chain and the session/claim lifecycles built on
top of it, so each test focuses purely on the behavior under assertion.

Every helper uses get_success_data() (lenient) for setup steps, so a broken
precondition surfaces as a clear "Setup step failed" rather than a confusing
downstream assertion error. Identity is threaded correctly: BCBA/RBT calls use
make_bcba_headers(provider_id) / make_rbt_headers(provider_id) with the real
Provider id so ownership checks resolve.

The test harness restarts the server (empty DB) before every test, so every
helper builds its preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_bcba_headers,
    make_rbt_headers,
)
from . import factories as f


# ─── Primitive onboarding helpers ─────────────────────────────

def create_payer(api=api_client, **overrides):
    headers = TEST_USERS["billing_headers"]
    resp = api.create_payer(f.create_payer_payload(**overrides), headers)
    return get_success_data(resp)


def create_bcba(api=api_client, **overrides):
    headers = TEST_USERS["intake_headers"]
    resp = api.create_provider(
        f.create_provider_payload(credential="BCBA", **overrides), headers
    )
    return get_success_data(resp)


def create_rbt(api=api_client, supervising_bcba_id=None, **overrides):
    headers = TEST_USERS["intake_headers"]
    payload = f.create_provider_payload(credential="RBT", **overrides)
    if supervising_bcba_id is not None:
        payload["supervising_bcba_id"] = supervising_bcba_id
    resp = api.create_provider(payload, headers)
    return get_success_data(resp)


def create_client(api=api_client, insurance_payer_id=None, **overrides):
    headers = TEST_USERS["intake_headers"]
    resp = api.create_client(
        f.create_client_payload(insurance_payer_id, **overrides), headers
    )
    return get_success_data(resp)


# ─── Evaluation lifecycle ─────────────────────────────────────

def create_finalized_evaluation(api, client_id, bcba_id, assessment_score=70):
    """DRAFT -> SUBMITTED -> FINALIZED. Returns the finalized evaluation data."""
    bcba_h = make_bcba_headers(bcba_id)
    intake_h = TEST_USERS["intake_headers"]
    ev = get_success_data(
        api.create_evaluation(
            f.create_evaluation_payload(client_id, bcba_id, assessment_score), bcba_h
        )
    )
    get_success_data(api.submit_evaluation(ev["id"], bcba_h))
    return get_success_data(api.review_evaluation(ev["id"], "FINALIZE", intake_h))


# ─── Treatment-plan lifecycle ─────────────────────────────────

def create_approved_plan(api, client_id, evaluation_id, bcba_id,
                         requested_direct_units=100,
                         requested_supervision_units=20,
                         requested_parent_training_units=8):
    """DRAFT -> SUBMITTED -> APPROVED. Returns the approved plan data."""
    bcba_h = make_bcba_headers(bcba_id)
    intake_h = TEST_USERS["intake_headers"]
    plan = get_success_data(
        api.create_plan(
            f.create_plan_payload(
                client_id, evaluation_id, bcba_id,
                requested_direct_units=requested_direct_units,
                requested_supervision_units=requested_supervision_units,
                requested_parent_training_units=requested_parent_training_units,
            ),
            bcba_h,
        )
    )
    get_success_data(api.submit_plan(plan["id"], bcba_h))
    return get_success_data(api.review_plan(plan["id"], "APPROVE", intake_h))


# ─── Full pre-authorization scenario ──────────────────────────

def setup_active_authorization(api,
                               assessment_score=70,
                               authorized_direct_units=100,
                               authorized_supervision_units=20,
                               authorized_parent_training_units=8,
                               period_start="2026-01-01",
                               period_end="2026-12-31",
                               with_rbt=True,
                               payer_overrides=None):
    """Build the full chain through an ACTIVE Authorization.

    Returns a dict with keys: payer, bcba, rbt (or None), client, evaluation,
    plan, authorization. The plan's requested pools match the authorized pools
    (so plan validation is never the binding constraint in pool tests).
    """
    payer = create_payer(api, **(payer_overrides or {}))
    bcba = create_bcba(api)
    rbt = create_rbt(api, supervising_bcba_id=bcba["id"]) if with_rbt else None
    client = create_client(api, insurance_payer_id=payer["id"])
    evaluation = create_finalized_evaluation(api, client["id"], bcba["id"],
                                             assessment_score)
    plan = create_approved_plan(
        api, client["id"], evaluation["id"], bcba["id"],
        requested_direct_units=max(authorized_direct_units, 1),
        requested_supervision_units=authorized_supervision_units,
        requested_parent_training_units=authorized_parent_training_units,
    )
    auth = get_success_data(
        api.create_authorization(
            f.create_authorization_payload(
                plan["id"], payer["id"],
                authorized_direct_units=authorized_direct_units,
                authorized_supervision_units=authorized_supervision_units,
                authorized_parent_training_units=authorized_parent_training_units,
                period_start=period_start,
                period_end=period_end,
            ),
            TEST_USERS["billing_headers"],
        )
    )
    return {
        "payer": payer,
        "bcba": bcba,
        "rbt": rbt,
        "client": client,
        "evaluation": evaluation,
        "plan": plan,
        "authorization": auth,
    }


# ─── Session-level helpers ────────────────────────────────────

def schedule_session(api, authorization_id, provider_id, provider_role,
                     service_line="DIRECT_THERAPY",
                     scheduled_start="2026-02-02T09:00:00Z",
                     scheduled_end="2026-02-02T11:00:00Z",
                     scheduled_units=8):
    """Schedule a session. provider_role is 'RBT' or 'BCBA' (sets identity)."""
    headers = (make_rbt_headers(provider_id) if provider_role == "RBT"
               else make_bcba_headers(provider_id))
    resp = api.create_session(
        f.create_session_payload(
            authorization_id, provider_id, service_line=service_line,
            scheduled_start=scheduled_start, scheduled_end=scheduled_end,
            scheduled_units=scheduled_units,
        ),
        headers,
    )
    return get_success_data(resp)


def deliver_session(api, session_id, provider_id, provider_role, delivered_units):
    headers = (make_rbt_headers(provider_id) if provider_role == "RBT"
               else make_bcba_headers(provider_id))
    return get_success_data(api.deliver_session(session_id, delivered_units, headers))


def setup_delivered_direct_session(api,
                                   scheduled_units=8,
                                   delivered_units=8,
                                   authorized_direct_units=100,
                                   assessment_score=70):
    """Active auth + one DIRECT session scheduled then delivered.

    Returns the scenario dict (from setup_active_authorization) extended with
    'session' (the delivered session data).
    """
    sc = setup_active_authorization(
        api,
        assessment_score=assessment_score,
        authorized_direct_units=authorized_direct_units,
    )
    session = schedule_session(
        api, sc["authorization"]["id"], sc["rbt"]["id"], "RBT",
        service_line="DIRECT_THERAPY", scheduled_units=scheduled_units,
    )
    delivered = deliver_session(api, session["id"], sc["rbt"]["id"], "RBT",
                                delivered_units)
    sc["session"] = delivered
    return sc


def deliver_supervision_units(api, scenario, scheduled_units, delivered_units,
                              scheduled_start="2026-02-03T09:00:00Z",
                              scheduled_end="2026-02-03T11:00:00Z"):
    """Schedule + deliver a SUPERVISION session by the scenario's BCBA.

    Used to bring an authorization's supervision posture to COMPLIANT or to a
    chosen deficient level. Returns the delivered supervision session.
    """
    bcba_id = scenario["bcba"]["id"]
    sup = schedule_session(
        api, scenario["authorization"]["id"], bcba_id, "BCBA",
        service_line="SUPERVISION",
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
        scheduled_units=scheduled_units,
    )
    return deliver_session(api, sup["id"], bcba_id, "BCBA", delivered_units)


# ─── Claim-level helpers ──────────────────────────────────────

def create_draft_claim(api, session_id):
    return get_success_data(
        api.create_claim(f.create_claim_payload(session_id),
                         TEST_USERS["billing_headers"])
    )


def create_submitted_claim(api, session_id):
    claim = create_draft_claim(api, session_id)
    return get_success_data(
        api.submit_claim(claim["id"], TEST_USERS["billing_headers"])
    )


def get_authorization(api, auth_id):
    return get_success_data(
        api.get_authorization(auth_id, TEST_USERS["billing_headers"])
    )
