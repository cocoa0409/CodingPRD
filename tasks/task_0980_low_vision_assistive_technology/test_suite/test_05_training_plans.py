"""Training plans and sessions: no-show suspension cascade, completion boundary,
scheduling guards (overlap, cap, suspended), and priority ordering."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_client_payload, create_referral_payload, create_evaluation_payload,
    create_device_model_payload, create_device_unit_payload, create_device_order_payload,
    create_training_plan_payload, create_training_session_payload,
    setup_allocated_purchase, setup_training_plan, schedule_session,
    TEST_USERS,
)

INTAKE = TEST_USERS["intake_coordinator_headers"]
SPECIALIST = TEST_USERS["vision_specialist_headers"]
ADMIN = TEST_USERS["clinic_admin_headers"]


def _setup_plan_with_three_sessions(api):
    """Fay Ito scenario: plan total_sessions=3, sessions s1/s2/s3 for inst-1."""
    ctx = setup_allocated_purchase(category="MAGNIFIER")
    c, o = ctx["client"], ctx["order"]
    plan = get_success_data(api.create_training_plan(create_training_plan_payload(
        c["id"], o["id"], total_sessions=3), SPECIALIST))
    s1 = schedule_session(plan["id"], "inst-1", "2026-05-04T10:00:00Z", "2026-05-04T11:00:00Z")
    s2 = schedule_session(plan["id"], "inst-1", "2026-05-04T11:00:00Z", "2026-05-04T12:00:00Z")
    s3 = schedule_session(plan["id"], "inst-1", "2026-05-04T13:00:00Z", "2026-05-04T14:00:00Z")
    return plan, s1, s2, s3


def test_no_show_increments_counter_without_suspension_at_one(api):
    """PRD §3.6: "Resolving `NO_SHOW` increments `no_show_count` by 1, and when
    the count reaches 2 or more the plan transitions `ACTIVE → SUSPENDED`".

    Design: Difficulty/transitive_cascade/tc_no_show_suspension_cascade
    """
    plan, s1, s2, s3 = _setup_plan_with_three_sessions(api)
    get_success_data(api.resolve_training_session(s1["id"], {"outcome": "NO_SHOW"}, SPECIALIST))
    mid = get_success_data(api.get_training_plan(plan["id"], SPECIALIST))
    assert mid["status"] == "ACTIVE"
    assert mid["no_show_count"] == 1, "link 1 only: the counter moved, the threshold not yet hit"


def test_second_no_show_suspends_and_cancels_remaining(api):
    """PRD §3.6: "when the count reaches 2 or more the plan transitions
    `ACTIVE → SUSPENDED`, which cascades: every remaining `SCHEDULED` session of
    the plan is moved to `CANCELLED` as part of the same suspension."

    Design: Difficulty/transitive_cascade/tc_no_show_suspension_cascade
    """
    plan, s1, s2, s3 = _setup_plan_with_three_sessions(api)
    get_success_data(api.resolve_training_session(s1["id"], {"outcome": "NO_SHOW"}, SPECIALIST))
    get_success_data(api.resolve_training_session(s2["id"], {"outcome": "NO_SHOW"}, SPECIALIST))
    end = get_success_data(api.get_training_plan(plan["id"], SPECIALIST))
    assert end["status"] == "SUSPENDED"
    assert end["no_show_count"] == 2
    sessions = get_success_data(api.list_plan_sessions(plan["id"], SPECIALIST))
    by_id = {s["id"]: s for s in sessions}
    assert by_id[s3["id"]]["status"] == "CANCELLED", "cascade cancels remaining SCHEDULED sessions"


def _setup_plan_with_two_sessions(api):
    """Jae Min scenario: plan total_sessions=2, sessions s1/s2 SCHEDULED."""
    ctx = setup_allocated_purchase(category="MAGNIFIER")
    c, o = ctx["client"], ctx["order"]
    plan = get_success_data(api.create_training_plan(create_training_plan_payload(
        c["id"], o["id"], total_sessions=2), SPECIALIST))
    s1 = schedule_session(plan["id"], "inst-1", "2026-05-04T10:00:00Z", "2026-05-04T11:00:00Z")
    s2 = schedule_session(plan["id"], "inst-1", "2026-05-04T11:00:00Z", "2026-05-04T12:00:00Z")
    return plan, s1, s2


def test_plan_stays_active_below_completion_count(api):
    """PRD §3.6: "Resolving `COMPLETED` increments the plan's
    `completed_sessions` by 1, and if that brings the count equal to
    `total_sessions` the plan transitions `ACTIVE → COMPLETED`."

    Design: Difficulty/boundary_precision_check/bp_plan_completion_exact_count
    """
    plan, s1, s2 = _setup_plan_with_two_sessions(api)
    get_success_data(api.resolve_training_session(s1["id"], {"outcome": "COMPLETED"}, SPECIALIST))
    mid = get_success_data(api.get_training_plan(plan["id"], SPECIALIST))
    assert mid["status"] == "ACTIVE"
    assert mid["completed_sessions"] == 1, "1 < 2: boundary not yet crossed"


def test_plan_completes_exactly_at_total_sessions(api):
    """PRD §3.6: "if that brings the count equal to `total_sessions` the plan
    transitions `ACTIVE → COMPLETED`."

    Design: Difficulty/boundary_precision_check/bp_plan_completion_exact_count
    """
    plan, s1, s2 = _setup_plan_with_two_sessions(api)
    get_success_data(api.resolve_training_session(s1["id"], {"outcome": "COMPLETED"}, SPECIALIST))
    get_success_data(api.resolve_training_session(s2["id"], {"outcome": "COMPLETED"}, SPECIALIST))
    end = get_success_data(api.get_training_plan(plan["id"], SPECIALIST))
    assert end["status"] == "COMPLETED"
    assert end["completed_sessions"] == 2, "exactly == total_sessions triggers completion"


def _setup_capped_plan_with_session(api):
    """Hana Su scenario: plan total_sessions=1 with one SCHEDULED session for
    inst-1 at 10:00-11:00."""
    ctx = setup_allocated_purchase(category="CCTV")
    c, o = ctx["client"], ctx["order"]
    plan = get_success_data(api.create_training_plan(create_training_plan_payload(
        c["id"], o["id"], total_sessions=1), SPECIALIST))
    schedule_session(plan["id"], "inst-1", "2026-05-04T10:00:00Z", "2026-05-04T11:00:00Z")
    return plan


def test_temporal_overlap_error_beats_session_cap(api):
    """PRD §2.7: "9. **Temporal windows and overlaps** — claim service date
    inside the funding window, trial conversion within the trial window,
    instructor session overlap, subscription overlap".
    PRD §2.7: "10. **Domain constraints** — category match, unit availability,
    eligible-unit pools, plan session caps, completeness of scores at finalize".
    PRD §2.7: "every request passes through a fixed validation funnel, and the
    **first** failing check determines the error returned".

    Design: Difficulty/priority_pair_validation_conflict/pp_temporal_beats_constraint_on_session_schedule
    """
    plan = _setup_capped_plan_with_session(api)
    resp = api.create_training_session(plan["id"], create_training_session_payload(
        instructor_user_id="inst-1",
        scheduled_start="2026-05-04T10:30:00Z",
        scheduled_end="2026-05-04T11:30:00Z"), SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP)


def test_overlap_rejection_writes_no_partial_session(api):
    """PRD §3.6: "A genuine conflict is rejected with `ERR_SESSION_OVERLAP`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/pp_temporal_beats_constraint_on_session_schedule
    """
    plan = _setup_capped_plan_with_session(api)
    api.create_training_session(plan["id"], create_training_session_payload(
        instructor_user_id="inst-1",
        scheduled_start="2026-05-04T10:30:00Z",
        scheduled_end="2026-05-04T11:30:00Z"), SPECIALIST)
    sessions = get_success_data(api.list_plan_sessions(plan["id"], SPECIALIST))
    assert len(sessions) == 1, "rejected schedule leaves no partial write"


def _setup_overlap_plan(api, total=5):
    """Mia Kos scenario: plan with one SCHEDULED session for inst-1 at
    10:00-11:00."""
    ctx = setup_allocated_purchase(category="MAGNIFIER")
    c, o = ctx["client"], ctx["order"]
    plan = get_success_data(api.create_training_plan(create_training_plan_payload(
        c["id"], o["id"], total_sessions=total), SPECIALIST))
    schedule_session(plan["id"], "inst-1", "2026-05-04T10:00:00Z", "2026-05-04T11:00:00Z")
    return plan


def test_session_adjacency_allowed_half_open(api):
    """PRD §3.6: "because intervals are half-open — start inclusive, end
    exclusive — a new session starting exactly when another ends is allowed."

    Design: Difficulty/resource_temporal_overlap/rto_session_instructor_half_open
    """
    plan = _setup_overlap_plan(api)
    adj = get_success_data(api.create_training_session(plan["id"], create_training_session_payload(
        instructor_user_id="inst-1",
        scheduled_start="2026-05-04T11:00:00Z",
        scheduled_end="2026-05-04T12:00:00Z"), SPECIALIST))
    assert adj["status"] == "SCHEDULED", "11:00 start == 11:00 end touches but does not overlap"


def test_session_strict_intersection_rejected(api):
    """PRD §3.6: "the new session conflicts with any existing `SCHEDULED` or
    `COMPLETED` session of the same instructor whose interval overlaps the new
    one".

    Design: Difficulty/resource_temporal_overlap/rto_session_instructor_half_open
    """
    plan = _setup_overlap_plan(api)
    resp = api.create_training_session(plan["id"], create_training_session_payload(
        instructor_user_id="inst-1",
        scheduled_start="2026-05-04T10:30:00Z",
        scheduled_end="2026-05-04T11:30:00Z"), SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP)


def _setup_suspended_plan(api):
    """Plan (total 5) SUSPENDED by two NO_SHOW resolutions."""
    ctx = setup_allocated_purchase(category="MAGNIFIER")
    c, o = ctx["client"], ctx["order"]
    plan = get_success_data(api.create_training_plan(create_training_plan_payload(
        c["id"], o["id"], total_sessions=5), SPECIALIST))
    s1 = schedule_session(plan["id"], "inst-1", "2026-05-04T10:00:00Z", "2026-05-04T11:00:00Z")
    s2 = schedule_session(plan["id"], "inst-1", "2026-05-04T11:00:00Z", "2026-05-04T12:00:00Z")
    get_success_data(api.resolve_training_session(s1["id"], {"outcome": "NO_SHOW"}, SPECIALIST))
    get_success_data(api.resolve_training_session(s2["id"], {"outcome": "NO_SHOW"}, SPECIALIST))
    return plan


def test_schedule_on_suspended_plan_rejected(api):
    """PRD §3.6: "scheduling against a `SUSPENDED` plan — or a `COMPLETED` one —
    is rejected with `ERR_PLAN_SUSPENDED` (HTTP 409)."

    Design: Corner/validations/val_plan_suspended_blocks_new_session
    """
    plan = _setup_suspended_plan(api)
    resp = api.create_training_session(plan["id"], create_training_session_payload(
        instructor_user_id="inst-2",
        scheduled_start="2026-05-05T10:00:00Z",
        scheduled_end="2026-05-05T11:00:00Z"), SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_PLAN_SUSPENDED)


def test_session_cap_reached_rejected(api):
    """PRD §3.6: "the number of non-cancelled sessions already on the plan must
    be below `total_sessions`; a plan at capacity rejects further scheduling with
    `ERR_PLAN_SESSION_CAP` (HTTP 422)."

    Design: Corner/validations/val_plan_session_cap_alone
    """
    ctx = setup_allocated_purchase(category="MAGNIFIER")
    c, o = ctx["client"], ctx["order"]
    plan = get_success_data(api.create_training_plan(create_training_plan_payload(
        c["id"], o["id"], total_sessions=1), SPECIALIST))
    schedule_session(plan["id"], "inst-1", "2026-05-04T10:00:00Z", "2026-05-04T11:00:00Z")
    resp = api.create_training_session(plan["id"], create_training_session_payload(
        instructor_user_id="inst-2",
        scheduled_start="2026-05-05T10:00:00Z",
        scheduled_end="2026-05-05T11:00:00Z"), SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_PLAN_SESSION_CAP)


def test_training_plan_requires_active_order(api):
    """PRD §3.6: "The referenced order must be `ACTIVE` or `CONVERTED` — an
    order in any other state triggers `ERR_ORDER_NOT_ACTIVE`".

    Design: Corner/validations/val_order_not_active_blocks_training_plan
    """
    from test_helpers import (
        create_client_with_accepted_referral, create_finalized_evaluation,
        create_device_model, place_order,
    )
    c, r = create_client_with_accepted_referral()
    ev = create_finalized_evaluation(c["id"], r["id"], recommended_category="MAGNIFIER")
    m = create_device_model(name="Magna 5x", category="MAGNIFIER", list_price_cents=25000)
    order = place_order(c["id"], ev["id"], m["id"], fulfillment_type="PURCHASE")
    resp = api.create_training_plan(create_training_plan_payload(
        c["id"], order["id"], total_sessions=3), SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_ACTIVE)
