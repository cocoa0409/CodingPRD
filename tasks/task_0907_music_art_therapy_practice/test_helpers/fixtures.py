"""Composite setup helpers.

Every test runs against a freshly-restarted, empty server, so each fixture
builds all of its preconditions from scratch using only PRD-declared endpoints.
Setup calls use get_success_data() (lenient) so any setup failure surfaces as a
clear "Setup failed" rather than a confusing assertion mismatch.

Therapist is entity_backed: ownership-gated calls (schedule/complete/cancel/
enroll/progress-note) always carry the acting therapist's own id via
make_therapist_headers(therapist_id).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated
from .api_client import api_client
from .test_users import TEST_USERS, make_therapist_headers
from . import factories as F


# --------------------------------------------------------------------- primitives
def set_clock(api, iso, headers=None):
    return get_success_data(api.set_clock(iso, headers or TEST_USERS["intake_headers"]))


def new_therapist(api, **overrides):
    return get_success_data(api.create_therapist(F.create_therapist_payload(**overrides),
                                                 TEST_USERS["intake_headers"]))


def new_insurance_client(api, **overrides):
    return get_success_data(api.create_client(F.create_insurance_client_payload(**overrides),
                                              TEST_USERS["intake_headers"]))


def new_self_pay_client(api, **overrides):
    return get_success_data(api.create_client(F.create_self_pay_client_payload(**overrides),
                                             TEST_USERS["intake_headers"]))


def new_referral(api, client_id, **overrides):
    return get_success_data(api.create_referral(F.create_referral_payload(client_id, **overrides),
                                               TEST_USERS["intake_headers"]))


def assess(api, referral_id, therapist_id, **overrides):
    return get_success_data(api.assess_referral(referral_id, F.assess_payload(**overrides),
                                               make_therapist_headers(therapist_id)))


def get_client_version(api, client_id):
    return get_success_data(api.get_client(client_id, TEST_USERS["intake_headers"]))["version"]


def new_plan(api, client_id, referral_id, expected_client_version, **overrides):
    return get_success_data(api.create_treatment_plan(
        client_id, F.create_plan_payload(referral_id, expected_client_version, **overrides),
        TEST_USERS["clinical_headers"]))


def activate_plan(api, plan_id):
    return get_success_data(api.activate_plan(plan_id, TEST_USERS["clinical_headers"]))


def new_goal(api, plan_id, **overrides):
    return get_success_data(api.create_goal(plan_id, F.create_goal_payload(**overrides),
                                           TEST_USERS["clinical_headers"]))


def new_room(api, **overrides):
    return get_success_data(api.create_room(F.create_room_payload(**overrides),
                                           TEST_USERS["intake_headers"]))


def new_material(api, **overrides):
    return get_success_data(api.create_material(F.create_material_payload(**overrides),
                                               TEST_USERS["intake_headers"]))


def new_contract(api, **overrides):
    return get_success_data(api.create_contract(F.create_contract_payload(**overrides),
                                               TEST_USERS["intake_headers"]))


def schedule_session(api, therapist_id, room_id, plan_id, goal_id, **overrides):
    return get_success_data(api.create_session(
        F.create_session_payload(therapist_id, room_id, plan_id, goal_id, **overrides),
        make_therapist_headers(therapist_id)))


def enroll(api, session_id, client_id, therapist_id):
    return get_success_data(api.enroll_client(session_id, {"client_id": client_id},
                                             make_therapist_headers(therapist_id)))


def complete_session(api, session_id, therapist_id, attended_client_ids):
    return get_success_data(api.complete_session(
        session_id, {"attended_client_ids": attended_client_ids},
        make_therapist_headers(therapist_id)))


def create_superbill(api, session_id, client_id):
    return get_success_data(api.create_superbill({"session_id": session_id, "client_id": client_id},
                                                TEST_USERS["billing_headers"]))


def fetch_goal(api, plan_id, goal_id, headers=None):
    """There is no direct GET goal endpoint; goals are read through their plan's
    goal listing (PRD §3.3). Returns the goal dict with live progress fields."""
    resp = api.list_goals(plan_id, headers or TEST_USERS["intake_headers"])
    data, _ = validate_paginated(resp)
    for g in data:
        if g["id"] == goal_id:
            return g
    return None


# ------------------------------------------------------------------- composites
def setup_active_plan(api, *, payer="INSURANCE", discipline="MUSIC",
                      client_overrides=None, goal_target_sessions=6, goal_weight=1.0,
                      room_capacity=3, clock=None, therapist_discipline="MUSIC"):
    """Active plan with one OPEN goal, plus a therapist and a room.

    Returns a context dict with all captured ids and the therapist's ownership
    headers. The named client's referral is ASSESSED+recommended and CONVERTED,
    the plan is ACTIVE, and (being the client's first plan activation) the client
    is promoted from INTAKE to ACTIVE.
    """
    if clock is not None:
        set_clock(api, clock)
    ther = new_therapist(api, discipline=therapist_discipline)
    if payer == "INSURANCE":
        client = new_insurance_client(api, **(client_overrides or {}))
    else:
        client = new_self_pay_client(api, **(client_overrides or {}))
    cv0 = client["version"]
    ref = new_referral(api, client["id"], referred_discipline=discipline)
    assess(api, ref["id"], ther["id"])
    plan = new_plan(api, client["id"], ref["id"], cv0, discipline=discipline)
    activate_plan(api, plan["id"])
    goal = new_goal(api, plan["id"], target_sessions=goal_target_sessions, weight=goal_weight)
    room = new_room(api, capacity=room_capacity)
    return {
        "ther_id": ther["id"],
        "ther_headers": make_therapist_headers(ther["id"]),
        "client_id": client["id"],
        "client": client,
        "cv0": cv0,
        "ref_id": ref["id"],
        "plan": plan,
        "plan_id": plan["id"],
        "goal": goal,
        "goal_id": goal["id"],
        "room_id": room["id"],
    }


def setup_completed_session(api, *, payer="INSURANCE", modality="INDIVIDUAL",
                            client_overrides=None, goal_target_sessions=6,
                            material_item_id=None, material_qty=0,
                            start_utc="2026-06-01T09:00:00Z",
                            end_utc="2026-06-01T10:00:00Z",
                            complete_clock="2026-06-01T09:30:00Z",
                            setup_clock="2026-06-01T00:00:00Z"):
    """Full chain through a COMPLETED session with the named client attended.

    Returns the setup_active_plan context extended with session_id and
    enrollment_id. The logical clock is advanced past start_utc before
    completion so the completion gate (PRD §2.5/§3.6) is satisfied.
    """
    ctx = setup_active_plan(api, payer=payer, client_overrides=client_overrides,
                            goal_target_sessions=goal_target_sessions, clock=setup_clock)
    extra = {"modality": modality, "start_utc": start_utc, "end_utc": end_utc}
    if material_item_id is not None:
        extra["material_item_id"] = material_item_id
        extra["material_qty"] = material_qty
    session = schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"], **extra)
    enrollment = enroll(api, session["id"], ctx["client_id"], ctx["ther_id"])
    set_clock(api, complete_clock)
    complete_session(api, session["id"], ctx["ther_id"], [ctx["client_id"]])
    ctx["session_id"] = session["id"]
    ctx["session"] = session
    ctx["enrollment_id"] = enrollment["id"]
    return ctx


def setup_billed_session(api, *, visits_authorized=3, modality="INDIVIDUAL",
                         contracted_rate_cents=12503, coinsurance_pct=0.20):
    """A COMPLETED insurance session that has been superbilled (session BILLED,
    superbill SUBMITTED, one insurance visit consumed). Returns the completed
    context extended with superbill_id."""
    ctx = setup_completed_session(
        api, payer="INSURANCE", modality=modality,
        client_overrides={
            "insurance_visits_authorized": visits_authorized,
            "insurance_contracted_rate_cents": contracted_rate_cents,
            "insurance_coinsurance_pct": coinsurance_pct,
        })
    sb = create_superbill(api, ctx["session_id"], ctx["client_id"])
    ctx["superbill_id"] = sb["id"]
    ctx["superbill"] = sb
    return ctx
