"""Cascades: discharge (depth-3 session cancel + visit release) and home-safety
finalize (depth-2 auto device referral), plus the no-cascade MODERATE case."""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS,
    setup_plan_with_approved_auth, schedule_session,
    setup_active_plan_with_draft_home_safety,
)

INTAKE = TEST_USERS["intake_headers"]
SUPER = TEST_USERS["supervisor_headers"]


# --- A7: transitive_cascade / discharge_plan_cancels_sessions_releases_visits -

def _plan_with_attended_and_scheduled(api):
    ctx = setup_plan_with_approved_auth(
        api, auth_overrides={"visits_authorized": 5, "allowed_amount_cents": 15000,
                             "coinsurance_pct": 0.20})
    s1 = schedule_session(api, ctx, scheduled_start="2026-06-01T10:00:00Z",
                          scheduled_end="2026-06-01T11:00:00Z")
    validate_success(api.attend_session(s1["id"], ctx["clinician_headers"]), 200)  # BILLED
    s2 = schedule_session(api, ctx, scheduled_start="2026-06-01T11:15:00Z",
                          scheduled_end="2026-06-01T12:15:00Z")  # SCHEDULED
    return ctx, s1, s2


def test_discharge_cancels_scheduled_and_releases_visit(api):
    """PRD §3.9: "Every session on the plan whose attendance_status is SCHEDULED is
    moved to CANCELLED; sessions already ATTENDED or NO_SHOW are left intact. For
    each session cancelled this way, its authorization's visits_used is recomputed
    downward, releasing the reservation."

    Design: Difficulty/transitive_cascade/discharge_plan_cancels_sessions_releases_visits
    """
    ctx, s1, s2 = _plan_with_attended_and_scheduled(api)
    plan = validate_success(api.discharge_care_plan(ctx["care_plan"]["id"], SUPER), 200)
    assert plan["status"] == "DISCHARGED"
    s2_after = get_success_data(api.get_session(s2["id"], INTAKE))
    assert s2_after["attendance_status"] == "CANCELLED"
    auth = get_success_data(api.get_authorization(ctx["authorization"]["id"], INTAKE))
    assert auth["visits_used"] == 1  # only the ATTENDED s1 still counts


def test_discharge_leaves_attended_session_and_responsibility_intact(api):
    """PRD §3.9: "sessions already ATTENDED or NO_SHOW are left intact ... Because
    the sessions cancelled here were SCHEDULED and therefore unbilled, no billing
    reversal occurs in this cascade."

    Design: Difficulty/transitive_cascade/discharge_plan_cancels_sessions_releases_visits
    """
    ctx, s1, s2 = _plan_with_attended_and_scheduled(api)
    validate_success(api.discharge_care_plan(ctx["care_plan"]["id"], SUPER), 200)
    s1_after = get_success_data(api.get_session(s1["id"], INTAKE))
    assert s1_after["attendance_status"] == "ATTENDED"
    plan = get_success_data(api.get_care_plan(ctx["care_plan"]["id"], INTAKE))
    assert plan["patient_responsibility_cents"] == 3000  # unchanged by discharge


# --- A8: transitive_cascade / home_safety_finalize_creates_device_referral ----

def test_high_hazard_finalize_creates_auto_device_referral(api):
    """PRD §3.7: "When and only when hazard_tier resolves to HIGH, the system
    automatically creates an assistive-device referral in the same operation ...
    The evaluation's generated_device_referral_id is set to the new referral's id".

    Design: Difficulty/transitive_cascade/home_safety_finalize_creates_device_referral
    """
    ctx = setup_active_plan_with_draft_home_safety(
        api, hazard_overrides={"missing_grab_bars": 4})  # score 20 -> HIGH
    finalized = validate_success(
        api.finalize_home_safety_evaluation(ctx["evaluation"]["id"], ctx["clinician_headers"]), 200)
    assert finalized["home_hazard_score"] == 20
    assert finalized["hazard_tier"] == "HIGH"
    assert finalized["generated_device_referral_id"] is not None


def test_auto_device_referral_attributes(api):
    """PRD §3.7: "its `source` is `AUTO_HAZARD`, its `status` opens at `PENDING`,
    its `home_safety_evaluation_id` points back to this evaluation, and its
    `device_type` is `GRAB_BAR` when the evaluation recorded one or more
    `missing_grab_bars` and `ROLLATOR` otherwise."

    Design: Difficulty/transitive_cascade/home_safety_finalize_creates_device_referral
    """
    ctx = setup_active_plan_with_draft_home_safety(
        api, hazard_overrides={"missing_grab_bars": 4})
    finalized = validate_success(
        api.finalize_home_safety_evaluation(ctx["evaluation"]["id"], ctx["clinician_headers"]), 200)
    dr = get_success_data(api.get_device_referral(finalized["generated_device_referral_id"], INTAKE))
    assert dr["source"] == "AUTO_HAZARD"
    assert dr["device_type"] == "GRAB_BAR"
    assert dr["status"] == "PENDING"
    assert dr["home_safety_evaluation_id"] == ctx["evaluation"]["id"]


# --- B: corner_home_hazard_moderate_tier_no_cascade --------------------------

def test_moderate_hazard_finalize_no_device_referral(api):
    """PRD §3.7: "From that total the system derives hazard_tier: HIGH when the
    score is at least 20, otherwise MODERATE when the score is at least 10,
    otherwise LOW." PRD §3.7: "for evaluations whose tier is LOW or MODERATE, no
    referral is created and generated_device_referral_id stays null."

    Design: Corner/calculations/corner_home_hazard_moderate_tier_no_cascade
    """
    ctx = setup_active_plan_with_draft_home_safety(
        api, hazard_overrides={"loose_rugs": 4})  # 4*3 = 12 -> MODERATE
    finalized = validate_success(
        api.finalize_home_safety_evaluation(ctx["evaluation"]["id"], ctx["clinician_headers"]), 200)
    assert finalized["home_hazard_score"] == 12
    assert finalized["hazard_tier"] == "MODERATE"
    assert finalized["generated_device_referral_id"] is None
