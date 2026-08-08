"""Session completion, goal progress (attendance vs rubric), auto-MET, the
completion clock gate, cancellation lockdown, and material conservation.

Queue A: dual_variant_calc (goal progress), compensating_invariant (instrument).
Queue B: goal auto-MET, complete-before-start, cancel-completed.
"""
from test_helpers import validate_success, validate_error, ApiErrorId, TEST_USERS
from test_helpers import fixtures as fx


# ================================ goal progress dual variant (queue A)
def _two_completed_sessions_with_notes(api):
    """Goal target_sessions=4 with TWO COMPLETED attended sessions and one signed
    progress note per session (rubric 40 then 80). Returns (ctx, goal_id)."""
    ctx = fx.setup_active_plan(api, payer="INSURANCE", discipline="ART",
                               goal_target_sessions=4, clock="2026-06-01T00:00:00Z")
    s1 = fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"],
                             start_utc="2026-06-01T09:00:00Z", end_utc="2026-06-01T10:00:00Z")
    e1 = fx.enroll(api, s1["id"], ctx["client_id"], ctx["ther_id"])
    s2 = fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"],
                             start_utc="2026-06-01T11:00:00Z", end_utc="2026-06-01T12:00:00Z")
    e2 = fx.enroll(api, s2["id"], ctx["client_id"], ctx["ther_id"])
    fx.set_clock(api, "2026-06-01T13:00:00Z")
    fx.complete_session(api, s1["id"], ctx["ther_id"], [ctx["client_id"]])
    fx.complete_session(api, s2["id"], ctx["ther_id"], [ctx["client_id"]])
    n1 = fx.get_success_data(api.create_progress_note(
        e1["id"], {"narrative": "Session 1", "rubric_score": 40, "outcome_rating": "IMPROVED"},
        ctx["ther_headers"]))
    api.sign_progress_note(n1["id"], ctx["ther_headers"])
    n2 = fx.get_success_data(api.create_progress_note(
        e2["id"], {"narrative": "Session 2", "rubric_score": 80, "outcome_rating": "IMPROVED"},
        ctx["ther_headers"]))
    api.sign_progress_note(n2["id"], ctx["ther_headers"])
    return ctx


def test_goal_attendance_progress_two_of_four(api):
    """PRD §3.3: "`progress_attendance` is that attended-session count divided by
    `target_sessions`, capped at 1.0, and rounded half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/goal_progress_attendance_vs_rubric_divergence
    """
    ctx = _two_completed_sessions_with_notes(api)
    goal = fx.fetch_goal(api, ctx["plan_id"], ctx["goal_id"])
    assert goal["progress_attendance"] == 0.50, "2 completed of target 4 -> 0.50"


def test_goal_rubric_progress_diverges_from_attendance(api):
    """PRD §3.3: "averages their `rubric_score` values, divides the mean by 100, and
    rounds half-up to two decimal places; when there are no signed notes,
    `progress_rubric` is 0.0."
    PRD §3.3: "Progress is measured two independent ways, and the two can diverge for
    identical session history — this is intentional."

    Design: Difficulty/dual_variant_calc/goal_progress_attendance_vs_rubric_divergence
    """
    ctx = _two_completed_sessions_with_notes(api)
    goal = fx.fetch_goal(api, ctx["plan_id"], ctx["goal_id"])
    assert goal["progress_rubric"] == 0.60, "mean(40,80)/100 -> 0.60"
    assert goal["status"] == "OPEN", "0.50 attendance < 1.0, not auto-MET"


# ================================ instrument conservation (queue A)
def test_material_reserved_on_schedule(api):
    """PRD §3.5: "the item's `reserved_quantity` rises by `material_qty` (and its
    `available_quantity` falls correspondingly)."
    PRD §3.4: "reserved plus available always equals on-hand, and available never
    goes negative."

    Design: Difficulty/compensating_invariant/instrument_reserve_release_conserves_on_hand
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY")
    mat = fx.new_material(api, name="Xylophone", on_hand_quantity=5, unit_charge_cents=300)
    fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"],
                        start_utc="2026-06-05T09:00:00Z", end_utc="2026-06-05T10:00:00Z",
                        material_item_id=mat["id"], material_qty=2)
    live = validate_success(api.get_material(mat["id"], TEST_USERS["intake_headers"]),
                            expected_status=200)
    assert live["reserved_quantity"] == 2
    assert live["available_quantity"] == 3
    assert live["reserved_quantity"] + live["available_quantity"] == live["on_hand_quantity"] == 5


def test_material_released_on_cancel_conserves(api):
    """PRD §3.6: "Cancellation advances the session `SCHEDULED → CANCELLED`, moves all
    its non-terminal enrollments to `CANCELLED`, releases the material reservation
    (dropping `reserved_quantity` by `material_qty`)".
    PRD §3.4: "reserved plus available always equals on-hand, and available never
    goes negative."

    Design: Difficulty/compensating_invariant/instrument_reserve_release_conserves_on_hand
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY")
    mat = fx.new_material(api, name="Xylophone", on_hand_quantity=5, unit_charge_cents=300)
    session = fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"],
                                  start_utc="2026-06-05T09:00:00Z", end_utc="2026-06-05T10:00:00Z",
                                  material_item_id=mat["id"], material_qty=2)
    before = validate_success(api.get_material(mat["id"], TEST_USERS["intake_headers"]),
                              expected_status=200)
    assert before["reserved_quantity"] == 2 and before["available_quantity"] == 3
    api.cancel_session(session["id"], {"cancel_reason": "client withdrew"}, ctx["ther_headers"])
    after = validate_success(api.get_material(mat["id"], TEST_USERS["intake_headers"]),
                             expected_status=200)
    assert after["reserved_quantity"] == 0
    assert after["available_quantity"] == 5
    assert after["reserved_quantity"] + after["available_quantity"] == after["on_hand_quantity"] == 5


# ================================ auto-MET + completion gates (queue B)
def test_goal_auto_met_at_attendance_boundary(api):
    """PRD §3.3: "This measure is recomputed each time a session for the goal is
    completed, and if it reaches 1.0 while the goal is still `OPEN`, the goal
    transitions `OPEN → MET`."

    Design: Corner/state_machines/goal_auto_met_at_attendance_boundary
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY", goal_target_sessions=1,
                               clock="2026-06-01T00:00:00Z")
    session = fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"],
                                  start_utc="2026-06-01T09:00:00Z", end_utc="2026-06-01T10:00:00Z")
    fx.enroll(api, session["id"], ctx["client_id"], ctx["ther_id"])
    fx.set_clock(api, "2026-06-01T09:30:00Z")
    fx.complete_session(api, session["id"], ctx["ther_id"], [ctx["client_id"]])
    goal = fx.fetch_goal(api, ctx["plan_id"], ctx["goal_id"])
    assert goal["progress_attendance"] == 1.00
    assert goal["status"] == "MET"


def test_complete_before_start_utc_rejected(api):
    """PRD §3.6: "a session can only be completed once `current_utc` has reached or
    passed its `start_utc`, and only while it is still `SCHEDULED`; a premature or
    wrongly-stated attempt is rejected with `ERR_SESSION_INVALID_STATE`."

    Design: Corner/state_machines/complete_before_start_utc_rejected
    """
    ctx = fx.setup_active_plan(api, payer="SELF_PAY", clock="2026-06-01T08:00:00Z")
    session = fx.schedule_session(api, ctx["ther_id"], ctx["room_id"], ctx["plan_id"], ctx["goal_id"],
                                  start_utc="2026-06-01T09:00:00Z", end_utc="2026-06-01T10:00:00Z")
    fx.enroll(api, session["id"], ctx["client_id"], ctx["ther_id"])
    # Clock is still 08:00, before start 09:00.
    resp = api.complete_session(session["id"], {"attended_client_ids": [ctx["client_id"]]},
                                ctx["ther_headers"])
    validate_error(resp, ApiErrorId.ERR_SESSION_INVALID_STATE.value)


def test_cancel_completed_session_rejected(api):
    """PRD §3.6: "Cancelling anything not in `SCHEDULED` raises
    `ERR_SESSION_INVALID_STATE`."

    Design: Corner/state_machines/cancel_completed_session_rejected
    """
    ctx = fx.setup_completed_session(api, payer="SELF_PAY")
    resp = api.cancel_session(ctx["session_id"], {}, ctx["ther_headers"])
    validate_error(resp, ApiErrorId.ERR_SESSION_INVALID_STATE.value)
