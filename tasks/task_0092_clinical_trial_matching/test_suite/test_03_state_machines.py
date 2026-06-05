"""State machines: the IRB-review branching fork, the two independent
enrollment dimensions, and the assorted single-edge precondition checks
(PRD §3.2, §3.4, §3.5, §3.6)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    decide_irb_review_payload, transition_payload, complete_visit_payload,
    assert_irb_review, assert_visit,
    set_clock, create_trial, open_irb_review, decide_irb_review,
    setup_open_trial, create_eligible_screened_enrollment,
    setup_randomized_enrollment, setup_active_enrollment,
    schedule_visit,
    report_adverse_event, triage_adverse_event,
    TEST_USERS, make_irb_reviewer_headers,
)


# ─── Difficulty: non_linear_state_machine / IRB branching fork ──────


def test_irb_protocol_reject_sets_trial_rejected(api):
    """PRD §3.2: "**Reject** moves the review from `PENDING` to `REJECTED`.
    For a `PROTOCOL`-scope review, this sets the trial's `irb_status` to
    `REJECTED` and the `posture` stays `SETUP`."

    Design: Difficulty/non_linear_state_machine/nlsm_irb_review_branching_fork
    """
    set_clock("2026-06-01T00:00:00Z")
    trial = create_trial(target_enrollment=3)
    review = open_irb_review(trial["id"], scope="PROTOCOL")

    res = api.decide_irb_review(
        trial["id"], review["id"], decide_irb_review_payload("REJECT"),
        make_irb_reviewer_headers("irb-1"),
    )
    data = validate_success(res, 200)
    assert_irb_review(data)
    assert data["decision"] == "REJECTED", f"REJECT moves PENDING -> REJECTED, got {data['decision']}"

    trial_after = validate_success(api.get_trial(trial["id"], TEST_USERS["sponsor_headers"]), 200)
    assert trial_after["irb_status"] == "REJECTED", "PROTOCOL reject sets irb_status REJECTED"
    assert trial_after["posture"] == "SETUP", "posture stays SETUP after a protocol reject"


def test_irb_protocol_revise_leaves_status_pending(api):
    """PRD §3.2: "**Revise** moves the review from `PENDING` to
    `REVISE_REQUESTED`. For a `PROTOCOL`-scope review, the `irb_status` stays
    `PENDING`."

    Design: Difficulty/non_linear_state_machine/nlsm_irb_review_branching_fork
    """
    set_clock("2026-06-01T00:00:00Z")
    trial = create_trial(target_enrollment=3)
    review = open_irb_review(trial["id"], scope="PROTOCOL")

    res = api.decide_irb_review(
        trial["id"], review["id"], decide_irb_review_payload("REVISE"),
        make_irb_reviewer_headers("irb-1"),
    )
    data = validate_success(res, 200)
    assert data["decision"] == "REVISE_REQUESTED", \
        f"REVISE moves PENDING -> REVISE_REQUESTED, got {data['decision']}"

    trial_after = validate_success(api.get_trial(trial["id"], TEST_USERS["sponsor_headers"]), 200)
    assert trial_after["irb_status"] == "PENDING", "PROTOCOL revise leaves irb_status PENDING"


def test_irb_protocol_approve_sets_trial_approved(api):
    """PRD §3.2: "**Approve** moves the review from `PENDING` to `APPROVED`.
    For a `PROTOCOL`-scope review, this additionally sets the trial's
    `irb_status` to `APPROVED`"

    Design: Difficulty/non_linear_state_machine/nlsm_irb_review_branching_fork
    """
    set_clock("2026-06-01T00:00:00Z")
    trial = create_trial(target_enrollment=3)
    review = open_irb_review(trial["id"], scope="PROTOCOL")

    res = api.decide_irb_review(
        trial["id"], review["id"], decide_irb_review_payload("APPROVE"),
        make_irb_reviewer_headers("irb-1"),
    )
    data = validate_success(res, 200)
    assert data["decision"] == "APPROVED", f"APPROVE moves PENDING -> APPROVED, got {data['decision']}"

    trial_after = validate_success(api.get_trial(trial["id"], TEST_USERS["sponsor_headers"]), 200)
    assert trial_after["irb_status"] == "APPROVED", "PROTOCOL approve sets irb_status APPROVED"


# ─── Difficulty: parallel dimensions evolve independently ───────────


def test_triage_flags_safety_while_enrollment_stays_randomized(api):
    """PRD §3.5: "**Triage** moves the event `REPORTED → UNDER_REVIEW`; as a
    cascade, if the parent enrollment's `safety_status` is `CLEAR`, the
    enrollment transitions `CLEAR → FLAGGED`."

    Design: Difficulty/non_linear_state_machine/nlsm_enrollment_parallel_dimensions_independent
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_randomized_enrollment()
    ae = report_adverse_event(ctx["enrollment_id"], severity="MODERATE",
                              occurred_at="2026-06-01T09:00:00Z")
    triage_adverse_event(ae["id"])

    enr = validate_success(api.get_enrollment(ctx["enrollment_id"], TEST_USERS["coordinator_headers"]), 200)
    assert enr["enrollment_status"] == "RANDOMIZED", \
        "the lifecycle dimension is untouched by triage"
    assert enr["safety_status"] == "FLAGGED", \
        "the safety dimension moves CLEAR -> FLAGGED independently"


def test_safety_dimension_starts_clear_independent_of_lifecycle(api):
    """PRD §3.4: "The enrollment copies its `trial_id` and `participant_id`
    from the screening and begins with `enrollment_status` `SCREENED` and
    `safety_status` `CLEAR`"
    PRD §3.5: "An enrollment's `safety_status` is a second, fully independent
    dimension that evolves on its own track through `CLEAR`, `FLAGGED`, and
    `HOLD`, driven entirely by adverse events rather than by the lifecycle
    transitions of §3.4."

    Design: Difficulty/non_linear_state_machine/nlsm_enrollment_parallel_dimensions_independent
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_open_trial()
    enr_ctx = create_eligible_screened_enrollment(ctx["trial_id"])

    enr = validate_success(api.get_enrollment(enr_ctx["enrollment_id"], TEST_USERS["coordinator_headers"]), 200)
    assert enr["enrollment_status"] == "SCREENED", "lifecycle dimension starts SCREENED"
    assert enr["safety_status"] == "CLEAR", "safety dimension starts CLEAR, independently"


# ─── Corner: state_machines single-edge precondition checks ─────────


def test_decide_already_decided_review_rejected(api):
    """PRD §3.2: "Because `APPROVED`, `REJECTED`, and `REVISE_REQUESTED` are
    all terminal, any attempt to decide a review that is no longer `PENDING`
    is rejected with `ERR_REVISE_NOT_DECIDABLE` (HTTP 409)."

    Design: Corner/state_machines/irb_decide_already_decided_returns_revise_not_decidable
    """
    set_clock("2026-06-01T00:00:00Z")
    trial = create_trial(target_enrollment=5)
    review = open_irb_review(trial["id"], scope="PROTOCOL")
    decide_irb_review(trial["id"], review["id"], "APPROVE")

    res = api.decide_irb_review(
        trial["id"], review["id"], decide_irb_review_payload("REJECT"),
        make_irb_reviewer_headers("irb-1"),
    )
    validate_error(res, ApiErrorId.ERR_REVISE_NOT_DECIDABLE.value, 409)

    after = validate_success(api.list_irb_reviews(trial["id"], TEST_USERS["sponsor_headers"]), 200)
    decided = next(r for r in after if r["id"] == review["id"])
    assert decided["decision"] == "APPROVED", "the first decision stands"


def test_activate_from_screened_invalid_state(api):
    """PRD §2.8: "then that the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`)."
    PRD §3.4: "**Activate** advances `RANDOMIZED → ACTIVE`. It requires the
    enrollment to be `RANDOMIZED`"

    Design: Corner/state_machines/enrollment_activate_from_screened_invalid_state
    """
    set_clock("2026-06-01T08:00:00Z")
    trial = create_trial(target_enrollment=5)
    enr_ctx = create_eligible_screened_enrollment(trial["id"])

    res = api.transition_enrollment(
        enr_ctx["enrollment_id"], transition_payload("ACTIVATE"),
        TEST_USERS["coordinator_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, 409)

    enr = validate_success(api.get_enrollment(enr_ctx["enrollment_id"], TEST_USERS["coordinator_headers"]), 200)
    assert enr["enrollment_status"] == "SCREENED", "no fields change on the rejected transition"


def test_lift_hold_from_clear_invalid_state(api):
    """PRD §3.5: "Lifting requires the enrollment's `safety_status` to be
    `HOLD` and every adverse event on that enrollment to be in
    `ADJUDICATED_RELATED` or `ADJUDICATED_UNRELATED`"
    PRD §2.8: "then that the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/lift_hold_from_clear_invalid_state
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_randomized_enrollment()  # safety_status CLEAR, no AE

    res = api.lift_hold(ctx["enrollment_id"], TEST_USERS["safety_officer_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, 409)

    enr = validate_success(api.get_enrollment(ctx["enrollment_id"], TEST_USERS["coordinator_headers"]), 200)
    assert enr["safety_status"] == "CLEAR", "the CLEAR enrollment is unchanged"


def test_withdraw_cancels_scheduled_visits(api):
    """PRD §3.4: "it cancels every visit of the enrollment that is still
    `SCHEDULED` (setting their `status` to `CANCELLED`)"

    Design: Corner/state_machines/withdraw_cancels_scheduled_visits
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_active_enrollment()
    visit = schedule_visit(ctx["enrollment_id"], 1, "2026-06-05T10:00:00Z", 30)

    res = api.transition_enrollment(
        ctx["enrollment_id"], transition_payload("WITHDRAW"), TEST_USERS["coordinator_headers"],
    )
    enr = validate_success(res, 200)
    assert enr["enrollment_status"] == "WITHDRAWN"

    visits = validate_success(api.list_visits(ctx["enrollment_id"], TEST_USERS["coordinator_headers"]), 200)
    target = next(v for v in visits if v["id"] == visit["id"])
    assert target["status"] == "CANCELLED", "the SCHEDULED visit is cancelled on withdrawal"


def test_visit_complete_lower_bound_inclusive(api):
    """PRD §3.6: "A draw exactly at the lower bound is in the window"
    PRD §3.6: "computes `draw_deviation_minutes` as the absolute difference
    between `drawn_at` and `scheduled_at` expressed in whole minutes with any
    fraction floored."

    Design: Corner/state_machines/visit_complete_lower_bound_inclusive
    """
    set_clock("2026-06-01T08:00:00Z")
    ctx = setup_active_enrollment()
    visit = schedule_visit(ctx["enrollment_id"], 1, "2026-06-02T10:00:00Z", 30)

    # drawn_at exactly at scheduled_at - 30 minutes (lower bound, inclusive).
    res = api.complete_visit(
        visit["id"], complete_visit_payload("2026-06-02T09:30:00Z"),
        TEST_USERS["coordinator_headers"],
    )
    data = validate_success(res, 200)
    assert_visit(data)
    assert data["status"] == "COMPLETED", "a draw at the inclusive lower bound completes the visit"
    assert data["draw_in_window"] is True
    assert data["draw_deviation_minutes"] == 30, f"deviation is 30 whole minutes, got {data['draw_deviation_minutes']}"
