"""Invalid transitions, terminal-state lockdown, preconditions, and the risk gate
(queue B: Corner / state_machines).
"""
from test_helpers import (
    api_client, TEST_USERS, validate_success, validate_error, get_success_data,
    ApiErrorId, fixtures,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["center_admin_headers"]
MIDWIFE = TEST_USERS["midwife_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ---- activate_episode_from_active_invalid_state ----
def test_activate_already_active_episode_invalid_state(api):
    """PRD §3.2: "An activation attempt from any state other than PLANNING is refused with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/activate_episode_from_active_invalid_state
    """
    ctx = fixtures.setup_active_episode()
    ep_id = ctx["episode"]["id"]
    resp = api.activate_episode(ep_id, MIDWIFE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    ep = validate_success(api.get_episode(ep_id, MIDWIFE))
    assert ep["clinical_status"] == "ACTIVE"


# ---- complete_care_from_planning_invalid_state ----
def test_complete_care_from_planning_invalid_state(api):
    """PRD §3.2: "Completing care advances clinical_status from BORN to COMPLETED." ...
    "from any state other than BORN it is refused with ERR_INVALID_STATE."

    Design: Corner/state_machines/complete_care_from_planning_invalid_state
    """
    ctx = fixtures.setup_episode()
    ep_id = ctx["episode"]["id"]
    resp = api.complete_care(ep_id, MIDWIFE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---- write_off_from_written_off_invalid_state ----
def test_second_write_off_invalid_state(api):
    """PRD §3.11: "A write-off attempted from a financial state other than UNBILLED or
    PLAN_ACTIVE is refused with ERR_INVALID_STATE."

    Design: Corner/state_machines/write_off_from_written_off_invalid_state
    """
    ctx = fixtures.setup_episode()
    ep_id = ctx["episode"]["id"]
    validate_success(api.write_off_episode(ep_id, BILLING))
    resp = api.write_off_episode(ep_id, BILLING)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    ep = validate_success(api.get_episode(ep_id, BILLING))
    assert ep["financial_status"] == "WRITTEN_OFF"


# ---- mark_no_show_before_scheduled_time_invalid_state ----
def test_mark_no_show_before_scheduled_time_invalid_state(api):
    """PRD §3.3: "A scheduled visit that the client misses can be marked a no-show by a
    Midwife, moving status from SCHEDULED to NO_SHOW; this is allowed only once the logical
    clock has reached or passed the visit's scheduled_at"

    Design: Corner/state_machines/mark_no_show_before_scheduled_time_invalid_state
    """
    # Clock at startup default 2026-01-01; visit scheduled 2026-04-01.
    ctx = fixtures.setup_episode()
    ep_id = ctx["episode"]["id"]
    visit = fixtures.schedule_visit(ep_id, scheduled_at="2026-04-01T10:00:00Z")
    resp = api.mark_no_show(visit["id"], MIDWIFE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---- cancel_visit_then_complete_invalid_state ----
def test_complete_cancelled_visit_invalid_state(api):
    """PRD §3.3: "Completion is barred when the owning episode's clinical_status is
    already TRANSFERRED or COMPLETED; in that case the request is refused with
    ERR_INVALID_STATE, as it is for any visit not currently SCHEDULED."

    Design: Corner/state_machines/cancel_visit_then_complete_invalid_state
    """
    ctx = fixtures.setup_episode()
    ep_id = ctx["episode"]["id"]
    visit = fixtures.schedule_visit(ep_id, scheduled_at="2026-04-01T10:00:00Z")
    validate_success(api.cancel_prenatal_visit(visit["id"], MIDWIFE))

    resp = api.complete_prenatal_visit(visit["id"], f.complete_visit_payload("NONE"), MIDWIFE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    v = validate_success(api.get_prenatal_visit(visit["id"], MIDWIFE))
    assert v["status"] == "CANCELLED"


# ---- activate_blocked_by_transfer_required_risk ----
def test_activate_blocked_by_transfer_required_risk(api):
    """PRD §3.2: "The risk gate is a clinical-safety check: an episode whose latest
    screening demands a hospital transfer cannot be activated, and the attempt is refused
    with ERR_RISK_TRANSFER_REQUIRED (HTTP 409)."

    Design: Corner/state_machines/activate_blocked_by_transfer_required_risk
    """
    ctx = fixtures.setup_episode_with_completed_visit(risk_flag="TRANSFER", blood_pressure_systolic=130)
    ep_id = ctx["episode"]["id"]
    assert ctx["episode"]["risk_tier"] == "TRANSFER_REQUIRED"

    resp = api.activate_episode(ep_id, MIDWIFE)
    validate_error(resp, ApiErrorId.ERR_RISK_TRANSFER_REQUIRED.value)
    ep = validate_success(api.get_episode(ep_id, MIDWIFE))
    assert ep["clinical_status"] == "PLANNING", "episode unchanged"
