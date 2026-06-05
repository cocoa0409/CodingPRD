"""Corner: state-machine transitions — invalid transitions, preconditions, side
effects, terminal lockdown, idempotency (PRD §3.2-§3.8). Queue B 'state_machines'.
"""
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.fixtures import (
    BILLING,
    COMPLIANCE,
    INTAKE,
    SCHEDULER,
    add_plan,
    book_companion_shift,
    create_oasis,
    schedule_visit,
    setup_active_episode,
    setup_draft_episode,
    setup_finalized_episode,
    set_clock,
)
from test_helpers.test_users import make_clinician_headers

WOUND_RATE = {
    "clinical_group": "WOUND", "base_30day_rate": 2000.00,
    "functional_weight_low": 0.95, "functional_weight_medium": 1.00,
    "functional_weight_high": 1.05, "lupa_threshold": 5,
}
WOUND_OASIS = {"clinical_group": "WOUND", "functional_level": "HIGH", "comorbidity_count": 2}
MMTA_RATE = {
    "clinical_group": "MMTA_OTHER", "base_30day_rate": 1500.00,
    "functional_weight_low": 1.00, "functional_weight_medium": 1.00,
    "functional_weight_high": 1.00, "lupa_threshold": 1,
}
MMTA_OASIS = {"clinical_group": "MMTA_OTHER", "functional_level": "LOW", "comorbidity_count": 0}


def test_cancel_active_episode_invalid_state(api):
    """PRD §3.2: "Cancellation is permitted only while the episode is in DRAFT".
    PRD §3.4: "Any attempt to drive a transition from a state that does not permit
    it is rejected with ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/cancel_active_episode_invalid_state
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 6},
    )
    resp = api.cancel_episode(base["episode"]["id"], INTAKE)
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_activate_without_plan_required(api):
    """PRD §3.2: "It requires that the episode hold exactly one ACTIVE plan of
    care; if no such plan exists, activation fails with ERR_PLAN_REQUIRED (HTTP
    422)."

    Design: Corner/state_machines/activate_without_plan_required
    """
    base = setup_draft_episode(api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS)
    resp = api.activate_episode(base["episode"]["id"], INTAKE)
    validate_error(resp, "ERR_PLAN_REQUIRED", 422)


def test_plan_supersede_marks_prior_superseded(api):
    """PRD §3.3: "only one plan per episode may be ACTIVE at a time; the prior
    active plan, if any, transitions ACTIVE -> SUPERSEDED and a PLAN_SUPERSEDED
    event is appended."

    Design: Corner/state_machines/plan_supersede_marks_prior_superseded
    """
    base = setup_draft_episode(api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS)
    ep_id = base["episode"]["id"]
    plan1 = add_plan(ep_id, base["version"], api, planned_rn_visits=6)
    ep1 = validate_success(api.get_episode(ep_id, INTAKE))
    plan2 = add_plan(ep_id, ep1["version"], api, planned_rn_visits=8)
    plans, _ = validate_paginated(api.list_plans(ep_id, INTAKE))
    by_id = {p["id"]: p for p in plans}
    assert by_id[plan1["id"]]["status"] == "SUPERSEDED"
    assert by_id[plan2["id"]]["status"] == "ACTIVE"


def test_terminal_discharged_finalize_again_rejected(api):
    """PRD §3.4: "Any attempt to drive a transition from a state that does not
    permit it is rejected with ERR_INVALID_STATE (HTTP 409)." PRD §3.2: "Both
    DISCHARGED and CANCELLED are terminal states for an episode."

    Design: Corner/state_machines/terminal_discharged_finalize_again_rejected
    """
    base = setup_finalized_episode(api)
    resp = api.finalize_episode(base["episode"]["id"], BILLING)
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_visit_confirm_double_returns_invalid_state(api):
    """PRD §3.4: "Any attempt to drive a transition from a state that does not
    permit it is rejected with ERR_INVALID_STATE (HTTP 409)." (Confirming an
    already-CONFIRMED visit.)

    Design: Corner/state_machines/visit_confirm_double_returns_invalid_state
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 6},
    )
    rn_id = base["rn"]["id"]
    v = schedule_visit(base["episode"]["id"], rn_id, api,
                       scheduled_start="2026-02-03T09:00:00Z", scheduled_end="2026-02-03T10:00:00Z")
    validate_success(api.confirm_visit(v["id"], make_clinician_headers(rn_id)))
    resp = api.confirm_visit(v["id"], make_clinician_headers(rn_id))
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_recert_approve_extends_cert_end_60_days(api):
    """PRD §3.7: "approval locks that recert OASIS, drives the parent episode
    RECERT_PENDING -> ACTIVE, extends cert_end by 60 days (the new cert_end is the
    old cert_end plus 60 days, with cert_start unchanged)".

    Design: Corner/state_machines/recert_approve_extends_cert_end_60_days
    """
    base = setup_active_episode(
        api, rate_overrides=WOUND_RATE, oasis_overrides=WOUND_OASIS,
        plan_overrides={"planned_rn_visits": 6},
    )
    ep_id = base["episode"]["id"]
    recert_oasis = create_oasis(
        base["patient"]["id"], base["rn"]["id"], api,
        assessment_type="RECERTIFICATION", assessment_date="2026-03-25T08:00:00Z",
        clinical_group="WOUND", functional_level="HIGH", comorbidity_count=2,
    )
    set_clock("2026-03-25T08:00:00Z", api)
    rr = validate_success(api.create_recert_request(ep_id, {"recert_oasis_id": recert_oasis["id"]}, INTAKE), 201)
    approved = validate_success(api.approve_recert_request(rr["id"], COMPLIANCE))
    assert approved["status"] == "APPROVED"
    ep = validate_success(api.get_episode(ep_id, INTAKE))
    assert ep["status"] == "ACTIVE"
    assert ep["cert_end"].startswith("2026-05-31")


def test_companion_deliver_before_window_invalid(api):
    """PRD §3.5: "Delivery is permitted only once the shift window has elapsed
    (shift_end at or before the current server clock)". PRD §3.4: "Any attempt to
    drive a transition from a state that does not permit it is rejected with
    ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/companion_deliver_before_window_invalid
    """
    base = setup_active_episode(
        api, rate_overrides=MMTA_RATE, oasis_overrides=MMTA_OASIS,
        plan_overrides={"planned_rn_visits": 1, "companion_hours_authorized": 8},
        with_hha=True,
    )
    ep_id, hha_id = base["episode"]["id"], base["hha"]["id"]
    cs = book_companion_shift(ep_id, hha_id, api,
                             shift_start="2026-02-03T13:00:00Z", shift_end="2026-02-03T14:00:00Z")
    set_clock("2026-02-03T12:00:00Z", api)  # before shift_end
    resp = api.deliver_companion_shift(cs["id"], SCHEDULER)
    validate_error(resp, "ERR_INVALID_STATE", 409)
    fetched = validate_success(api.get_episode(ep_id, INTAKE))
    assert fetched["companion_hours_used"] == 0
