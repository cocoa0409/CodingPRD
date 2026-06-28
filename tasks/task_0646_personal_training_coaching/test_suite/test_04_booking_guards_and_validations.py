"""Booking guards and validation rules: trainer-buffer vs client-touching
calendar geometry, the two priority-pair conflicts, the 24h cutoff boundary,
the empty-window adherence floor, cross-entity gates (assessed client, published
program), and direct validation-to-error mappings.

Depth (queue A): priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, resource_temporal_overlap.
Breadth (queue B): validations section.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID, api_client,
    set_clock, create_trainer, create_client, submit_intake, assess_client,
    create_assessed_client, create_engagement,
    setup_session_pack_engagement, setup_subscription_engagement,
    setup_pack_engagement,
    create_pack, get_pack, book_pack_session, book_subscription_session,
    create_program,
    create_engagement_payload, create_booking_payload, create_macro_plan_payload,
    create_habit_log_payload, create_check_in_payload,
    make_trainer_headers, make_client_headers,
)


# ─── resource_temporal_overlap / trainer_buffer_blocks_back_to_back ──────────

def test_trainer_buffer_rejects_gap_under_900s(api):
    """PRD §3.4: "it pads each existing booking by a fifteen-minute buffer (900
    seconds) on both ends. The proposed session is rejected with
    `ERR_BOOKING_OVERLAP` if it intrudes into any padded interval — equivalently,
    two of a trainer's sessions must be separated by a gap of at least the buffer,
    so back-to-back sessions, including ones that merely touch end-to-start, are
    rejected."

    A second booking on the same trainer starting only 600s after the first ends
    (gap < 900s) is rejected ERR_BOOKING_OVERLAP even though the raw intervals do
    not intersect.

    Design: Difficulty/resource_temporal_overlap/trainer_buffer_blocks_back_to_back
    """
    set_clock("2026-06-01T00:00:00Z")
    trainer = create_trainer()
    t_id = trainer["id"]
    c1 = create_assessed_client(t_id)
    e1 = create_engagement(t_id, c1["id"], c1["version"],
                           billing_model="ONLINE_SUBSCRIPTION",
                           monthly_fee_cents=6000, cycle_start_utc="2026-06-01T00:00:00Z")
    book_subscription_session(t_id, e1["id"], "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z")
    c2 = create_assessed_client(t_id)
    e2 = create_engagement(t_id, c2["id"], c2["version"],
                           billing_model="ONLINE_SUBSCRIPTION",
                           monthly_fee_cents=6000, cycle_start_utc="2026-06-01T00:00:00Z")
    resp = api.create_booking(
        create_booking_payload(e2["id"], "2026-06-10T11:10:00Z", "2026-06-10T12:00:00Z"),
        make_trainer_headers(t_id))
    validate_error(resp, ApiErrorId.ERR_BOOKING_OVERLAP.value)


def test_trainer_buffer_rejects_touching_back_to_back(api):
    """PRD §3.4: "back-to-back sessions, including ones that merely touch
    end-to-start, are rejected."

    A booking starting exactly when the trainer's prior booking ends (11:00 ==
    11:00, gap 0 < 900s) is rejected ERR_BOOKING_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/trainer_buffer_blocks_back_to_back
    """
    set_clock("2026-06-01T00:00:00Z")
    trainer = create_trainer()
    t_id = trainer["id"]
    c1 = create_assessed_client(t_id)
    e1 = create_engagement(t_id, c1["id"], c1["version"],
                           billing_model="ONLINE_SUBSCRIPTION",
                           monthly_fee_cents=6000, cycle_start_utc="2026-06-01T00:00:00Z")
    book_subscription_session(t_id, e1["id"], "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z")
    c2 = create_assessed_client(t_id)
    e2 = create_engagement(t_id, c2["id"], c2["version"],
                           billing_model="ONLINE_SUBSCRIPTION",
                           monthly_fee_cents=6000, cycle_start_utc="2026-06-01T00:00:00Z")
    resp = api.create_booking(
        create_booking_payload(e2["id"], "2026-06-10T11:00:00Z", "2026-06-10T12:00:00Z"),
        make_trainer_headers(t_id))
    validate_error(resp, ApiErrorId.ERR_BOOKING_OVERLAP.value)


# NOTE: the design instance
# resource_temporal_overlap/client_touching_booking_allowed_no_buffer is SKIPPED.
# Its setup requires one client enrolled with two different trainers so the client
# calendar can be exercised independently of the trainer buffer. PRD §2.1 binds a
# Client to a single coaching trainer ("a trainer may act only on clients ... whose
# owning engagement (or client) carries that trainer's identifier"), so a second
# trainer cannot create an engagement for another trainer's client (it is correctly
# rejected ERR_FORBIDDEN_ROLE). With only one trainer per client, any two of a
# client's bookings share that trainer's calendar, where the higher-priority trainer
# buffer (§3.4, priority 11a) pre-empts ERR_CLIENT_DOUBLE_BOOKED (11b). The
# zero-buffer client geometry is therefore not uniquely derivable / not reachable
# from a PRD-faithful setup, so no test is emitted (gap stays a gap).


# ─── priority_pair_validation_conflict / state_vs_temporal ───────────────────

def test_paused_engagement_overlap_returns_engagement_not_active(api):
    """PRD §3.4: "The engagement must be `ACTIVE`; a booking attempt against a
    paused or ended engagement is rejected with `ERR_ENGAGEMENT_NOT_ACTIVE`."
    PRD §3.4: "Two calendar-geometry checks then apply (detailed below)."

    A booking that both targets a PAUSED engagement and overlaps a live trainer
    booking returns the earlier-evaluated state error ERR_ENGAGEMENT_NOT_ACTIVE,
    not ERR_BOOKING_OVERLAP.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_engagement_not_active_wins_over_overlap
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=5, price_cents=50000)
    t_id, e_id, pack = ctx["trainer"]["id"], ctx["engagement"]["id"], ctx["pack"]
    th = make_trainer_headers(t_id)
    book_pack_session(t_id, e_id, pack["id"], pack["version"],
                      "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z")
    pv = get_pack(t_id, pack["id"])["version"]
    validate_success(api.pause_engagement(e_id, th))
    resp = api.create_booking(
        create_booking_payload(e_id, "2026-06-10T10:30:00Z", "2026-06-10T11:30:00Z",
                               session_pack_id=pack["id"],
                               expected_session_pack_version=pv),
        th)
    validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_ACTIVE.value)


def test_ended_engagement_overlap_returns_engagement_not_active(api):
    """PRD §3.4: "The engagement must be `ACTIVE`; a booking attempt against a
    paused or ended engagement is rejected with `ERR_ENGAGEMENT_NOT_ACTIVE`."
    PRD §3.4: "Two calendar-geometry checks then apply (detailed below)."

    With the engagement ENDED (also not ACTIVE) and the proposed slot overlapping a
    live trainer booking, the earlier state gate wins: ERR_ENGAGEMENT_NOT_ACTIVE,
    never ERR_BOOKING_OVERLAP.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_engagement_not_active_wins_over_overlap
    """
    set_clock("2026-06-01T00:00:00Z")
    trainer = create_trainer()
    t_id = trainer["id"]
    th = make_trainer_headers(t_id)
    # A live booking on a still-ACTIVE engagement of THIS trainer occupies the slot.
    c_live = create_assessed_client(t_id)
    e_live = create_engagement(t_id, c_live["id"], c_live["version"],
                               billing_model="ONLINE_SUBSCRIPTION",
                               monthly_fee_cents=6000, cycle_start_utc="2026-06-01T00:00:00Z")
    book_subscription_session(t_id, e_live["id"], "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z")
    # A second SESSION_PACK engagement of the SAME trainer, then ENDED.
    c_target = create_assessed_client(t_id)
    e_target = create_engagement(t_id, c_target["id"], c_target["version"],
                                 billing_model="SESSION_PACK")
    pack = create_pack(t_id, e_target["id"], total_sessions=5, price_cents=50000)
    validate_success(api.end_engagement(e_target["id"], th))
    # Proposed slot overlaps the live trainer booking AND the engagement is ENDED.
    resp = api.create_booking(
        create_booking_payload(e_target["id"], "2026-06-10T10:30:00Z", "2026-06-10T11:30:00Z",
                               session_pack_id=pack["id"],
                               expected_session_pack_version=pack["version"]),
        th)
    validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_NOT_ACTIVE.value)


# ─── priority_pair_validation_conflict / privilege_vs_no_sessions ────────────

def test_suspended_client_on_depleted_pack_returns_privilege_suspended(api):
    """PRD §3.4: "The acting client must currently be allowed to book: if the
    client's `booking_privilege` is `SUSPENDED`, the create is rejected with
    `ERR_BOOKING_PRIVILEGE_SUSPENDED`."
    PRD §3.4: "Finally, for a `SESSION_PACK` booking the referenced pack must have
    `sessions_remaining` greater than zero ... a booking attempted against a pack
    with no seats left is rejected with `ERR_NO_SESSIONS_REMAINING`"

    A SUSPENDED client booking against a depleted pack of an ACTIVE engagement gets
    the earlier-evaluated privilege error ERR_BOOKING_PRIVILEGE_SUSPENDED, not
    ERR_NO_SESSIONS_REMAINING.

    Design: Difficulty/priority_pair_validation_conflict/privilege_vs_no_sessions_safety_wins_over_constraint
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=3, price_cents=30000)
    t_id, c_id, e_id, pack = (ctx["trainer"]["id"], ctx["client"]["id"],
                              ctx["engagement"]["id"], ctx["pack"])
    th = make_trainer_headers(t_id)
    # Commit all three seats with future bookings; mark each a no-show to suspend.
    starts = ["2026-06-02T08:00:00Z", "2026-06-02T11:00:00Z", "2026-06-02T14:00:00Z"]
    ends = ["2026-06-02T09:00:00Z", "2026-06-02T12:00:00Z", "2026-06-02T15:00:00Z"]
    booking_ids = []
    pv = pack["version"]
    for s, e in zip(starts, ends):
        b = book_pack_session(t_id, e_id, pack["id"], pv, s, e)
        booking_ids.append(b["id"])
        pv = get_pack(t_id, pack["id"])["version"]
    set_clock("2026-06-02T20:00:00Z")
    for b_id in booking_ids:
        validate_success(api.mark_no_show(b_id, th))
    # The depleting third booking paused the engagement (PACK_DEPLETED). Add a fresh
    # pack with a seat and resume so the engagement is ACTIVE again, isolating the
    # privilege-vs-seat-availability conflict from the engagement-state gate.
    create_pack(t_id, e_id, total_sessions=1, price_cents=10000)
    validate_success(api.resume_engagement(e_id, th))
    client = validate_success(api.get_client(c_id, th))
    assert client["booking_privilege"] == "SUSPENDED"
    pack_now = get_pack(t_id, pack["id"])
    assert pack_now["sessions_remaining"] == 0
    pv_now = pack_now["version"]

    resp = api.create_booking(
        create_booking_payload(e_id, "2026-06-09T10:00:00Z", "2026-06-09T11:00:00Z",
                               session_pack_id=pack["id"],
                               expected_session_pack_version=pv_now),
        make_client_headers(c_id))
    validate_error(resp, ApiErrorId.ERR_BOOKING_PRIVILEGE_SUSPENDED.value)


def test_suspended_client_depleted_pack_does_not_report_no_sessions(api):
    """PRD §3.4: "The acting client must currently be allowed to book: if the
    client's `booking_privilege` is `SUSPENDED`, the create is rejected with
    `ERR_BOOKING_PRIVILEGE_SUSPENDED`."
    PRD §3.4: "Finally, for a `SESSION_PACK` booking the referenced pack must have
    `sessions_remaining` greater than zero"

    Because the privilege gate is evaluated before the "Finally" seat-availability
    gate, the suppressed lower-priority ERR_NO_SESSIONS_REMAINING never surfaces —
    the rejection is the higher-priority privilege error.

    Design: Difficulty/priority_pair_validation_conflict/privilege_vs_no_sessions_safety_wins_over_constraint
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=3, price_cents=30000)
    t_id, c_id, e_id, pack = (ctx["trainer"]["id"], ctx["client"]["id"],
                              ctx["engagement"]["id"], ctx["pack"])
    th = make_trainer_headers(t_id)
    starts = ["2026-06-02T08:00:00Z", "2026-06-02T11:00:00Z", "2026-06-02T14:00:00Z"]
    ends = ["2026-06-02T09:00:00Z", "2026-06-02T12:00:00Z", "2026-06-02T15:00:00Z"]
    booking_ids = []
    pv = pack["version"]
    for s, e in zip(starts, ends):
        b = book_pack_session(t_id, e_id, pack["id"], pv, s, e)
        booking_ids.append(b["id"])
        pv = get_pack(t_id, pack["id"])["version"]
    set_clock("2026-06-02T20:00:00Z")
    for b_id in booking_ids:
        validate_success(api.mark_no_show(b_id, th))
    # Restore the engagement to ACTIVE (fresh pack + resume) so the only remaining
    # rejections in contention are the privilege gate and the seat-availability gate.
    create_pack(t_id, e_id, total_sessions=1, price_cents=10000)
    validate_success(api.resume_engagement(e_id, th))
    pv_now = get_pack(t_id, pack["id"])["version"]
    resp = api.create_booking(
        create_booking_payload(e_id, "2026-06-09T10:00:00Z", "2026-06-09T11:00:00Z",
                               session_pack_id=pack["id"],
                               expected_session_pack_version=pv_now),
        make_client_headers(c_id))
    error = validate_error(resp, ApiErrorId.ERR_BOOKING_PRIVILEGE_SUSPENDED.value)
    assert error["error_id"] != ApiErrorId.ERR_NO_SESSIONS_REMAINING.value


# ─── boundary_precision_check / no_show_cutoff_exactly_24h_is_free_cancel ────

def test_cancel_exactly_24h_ahead_is_free(api):
    """PRD §3.5: "If the cancellation arrives at least twenty-four hours before the
    session starts — that is, the gap from the logical clock to `start_utc` is at
    least 86,400 seconds — the booking moves to `CANCELLED` free of charge: for a
    `SESSION_PACK` booking its seat is released (the committed count drops by one),
    a `DEPLETED` pack returns to `ACTIVE`, and `fee_charged_cents` stays 0."

    A booking starting exactly 24h (86,400s) after the clock cancels free
    (CANCELLED, fee 0, seat released to 5).

    Design: Difficulty/boundary_precision_check/no_show_cutoff_exactly_24h_is_free_cancel
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:00Z",
                                total_sessions=5, price_cents=50000)
    t_id, c_id, e_id, pack = (ctx["trainer"]["id"], ctx["client"]["id"],
                              ctx["engagement"]["id"], ctx["pack"])
    b = book_pack_session(t_id, e_id, pack["id"], pack["version"],
                          "2026-06-02T00:00:00Z", "2026-06-02T01:00:00Z")
    cancelled = validate_success(api.cancel_booking(b["id"], make_client_headers(c_id)))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["fee_charged_cents"] == 0
    refreshed = get_pack(t_id, pack["id"])
    assert refreshed["sessions_remaining"] == 5


def test_cancel_one_second_under_24h_is_late_cancelled(api):
    """PRD §3.5: "If instead the cancellation arrives within that twenty-four-hour
    window — the gap is strictly less than 86,400 seconds — the booking is routed
    to `LATE_CANCELLED` instead: the seat stays committed (the session is treated
    as consumed), and a fee is charged."

    A booking starting one second under 24h away (clock 00:00:01) routes to
    LATE_CANCELLED with the half-fee 5000 — the X+1 side of the cutoff boundary.

    Design: Difficulty/boundary_precision_check/no_show_cutoff_exactly_24h_is_free_cancel
    """
    ctx = setup_pack_engagement(clock_utc="2026-06-01T00:00:01Z",
                                total_sessions=5, price_cents=50000)
    t_id, c_id, e_id, pack = (ctx["trainer"]["id"], ctx["client"]["id"],
                              ctx["engagement"]["id"], ctx["pack"])
    # start is 2026-06-02T00:00:00Z; gap = 86399s < 86400s -> late.
    b = book_pack_session(t_id, e_id, pack["id"], pack["version"],
                          "2026-06-02T00:00:00Z", "2026-06-02T01:00:00Z")
    cancelled = validate_success(api.cancel_booking(b["id"], make_client_headers(c_id)))
    assert cancelled["status"] == "LATE_CANCELLED"
    assert cancelled["fee_charged_cents"] == 5000


# ─── boundary_precision_check / adherence_zero_when_window_has_no_logs ───────

def test_adherence_zero_when_window_has_no_logs(api):
    """PRD §3.6: "These three ratios are kept at full precision and combined with
    weights of 0.50 for workouts, 0.30 for nutrition, and 0.20 for habits; the
    weighted blend is multiplied by 100 and rounded half-up to a single integer
    exactly once at the very end."

    A check-in whose window contains zero habit logs scores 0 (all three ratios
    are 0/denominator), with no divide-by-zero error; status SUBMITTED.

    Design: Difficulty/boundary_precision_check/adherence_zero_when_window_has_no_logs
    """
    ctx = setup_subscription_engagement(clock_utc="2026-06-01T00:00:00Z",
                                        client_overrides={"sex": "FEMALE",
                                                          "birth_year": 1995,
                                                          "height_cm": 165})
    c_id, e_id = ctx["client"]["id"], ctx["engagement"]["id"]
    ci = validate_success(api.create_check_in(
        e_id,
        create_check_in_payload("2026-06-08T08:00:00Z", 64,
                                "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z"),
        make_client_headers(c_id)), 201)
    assert ci["adherence_score"] == 0
    assert ci["status"] == "SUBMITTED"


def test_adherence_zero_when_all_logs_fall_before_window(api):
    """PRD §3.6: "The window is half-open, from `window_start_utc` up to but not
    including `window_end_utc`"
    PRD §3.8: "it is this classification that the adherence score of §3.6 bins into
    its three ratios according to where `logged_at` falls among the check-in
    windows."

    Habit logs whose logged_at is strictly before window_start_utc fall outside the
    half-open window, so the check-in's adherence_score is exactly 0.

    Design: Difficulty/boundary_precision_check/adherence_zero_when_window_has_no_logs
    """
    from test_helpers import create_published_program, log_habit
    ctx = setup_subscription_engagement(clock_utc="2026-06-01T00:00:00Z")
    t_id, c_id, e_id = ctx["trainer"]["id"], ctx["client"]["id"], ctx["engagement"]["id"]
    prog = create_published_program(t_id, e_id, planned_workouts_per_week=4,
                                    habit_checks_target=10)
    # Logs before the window start at 2026-06-10.
    log_habit(c_id, e_id, prog["id"], "WORKOUT_COMPLETED", "2026-06-05T07:00:00Z")
    log_habit(c_id, e_id, prog["id"], "NUTRITION_LOGGED", "2026-06-05T12:00:00Z")
    log_habit(c_id, e_id, prog["id"], "HABIT_CHECK", "2026-06-05T20:00:00Z")
    ci = validate_success(api.create_check_in(
        e_id,
        create_check_in_payload("2026-06-18T08:00:00Z", 64,
                                "2026-06-10T00:00:00Z", "2026-06-17T00:00:00Z"),
        make_client_headers(c_id)), 201)
    assert ci["adherence_score"] == 0
    assert ci["status"] == "SUBMITTED"


# ─── cross_entity_state_dependency / engagement_create_requires_client_assessed ─

def test_engagement_create_requires_assessed_client(api):
    """PRD §3.2: "Creation requires the named client to be in `intake_status`
    `ASSESSED`; if it is not, the request is rejected with `ERR_INTAKE_NOT_ASSESSED`."

    Creating an engagement against a SUBMITTED (not-yet-assessed) client returns
    ERR_INTAKE_NOT_ASSESSED.

    Design: Difficulty/cross_entity_state_dependency/engagement_create_requires_client_assessed
    """
    set_clock("2026-06-01T00:00:00Z")
    trainer = create_trainer()
    t_id = trainer["id"]
    client = create_client(t_id)
    submitted = validate_success(api.submit_intake(client["id"], make_client_headers(client["id"])))
    resp = api.create_engagement(
        create_engagement_payload(client["id"], submitted["version"],
                                  billing_model="SESSION_PACK"),
        make_trainer_headers(t_id))
    validate_error(resp, ApiErrorId.ERR_INTAKE_NOT_ASSESSED.value)


def test_engagement_create_against_draft_client_rejected(api):
    """PRD §3.2: "Creation requires the named client to be in `intake_status`
    `ASSESSED`; if it is not, the request is rejected with `ERR_INTAKE_NOT_ASSESSED`."

    A freshly created DRAFT client (never submitted) is also "not ASSESSED", so
    engagement creation is rejected with ERR_INTAKE_NOT_ASSESSED.

    Design: Difficulty/cross_entity_state_dependency/engagement_create_requires_client_assessed
    """
    set_clock("2026-06-01T00:00:00Z")
    trainer = create_trainer()
    t_id = trainer["id"]
    client = create_client(t_id)  # DRAFT
    resp = api.create_engagement(
        create_engagement_payload(client["id"], client["version"],
                                  billing_model="SESSION_PACK"),
        make_trainer_headers(t_id))
    validate_error(resp, ApiErrorId.ERR_INTAKE_NOT_ASSESSED.value)


# ─── cross_entity_state_dependency / habit_log_requires_published_program ────

def test_habit_log_against_draft_program_returns_not_published(api):
    """PRD §3.8: "A habit log may only be written against a program that is
    currently `PUBLISHED` within the same engagement; an attempt to log against a
    program that is not published is rejected with `ERR_PROGRAM_NOT_PUBLISHED`."

    A HabitLog referencing a DRAFT (unpublished) program returns
    ERR_PROGRAM_NOT_PUBLISHED.

    Design: Difficulty/cross_entity_state_dependency/habit_log_requires_published_program
    """
    ctx = setup_subscription_engagement(clock_utc="2026-06-01T00:00:00Z")
    t_id, c_id, e_id = ctx["trainer"]["id"], ctx["client"]["id"], ctx["engagement"]["id"]
    program = create_program(t_id, e_id)  # left in DRAFT
    resp = api.create_habit_log(
        create_habit_log_payload(e_id, program["id"], "WORKOUT_COMPLETED",
                                 "2026-06-02T07:00:00Z"),
        make_client_headers(c_id))
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_PUBLISHED.value)


def test_habit_log_against_published_program_succeeds(api):
    """PRD §3.7: "Only once a program is `PUBLISHED` may habit logs reference it."
    PRD §3.8: "A habit log may only be written against a program that is currently
    `PUBLISHED` within the same engagement"

    Once the program reaches PUBLISHED, the same HabitLog write that a DRAFT program
    rejected is accepted (201), confirming PUBLISHED is the enabling state.

    Design: Difficulty/cross_entity_state_dependency/habit_log_requires_published_program
    """
    ctx = setup_subscription_engagement(clock_utc="2026-06-01T00:00:00Z")
    t_id, c_id, e_id = ctx["trainer"]["id"], ctx["client"]["id"], ctx["engagement"]["id"]
    program = create_program(t_id, e_id)
    validate_success(api.publish_program(program["id"], make_trainer_headers(t_id)))
    resp = api.create_habit_log(
        create_habit_log_payload(e_id, program["id"], "WORKOUT_COMPLETED",
                                 "2026-06-02T07:00:00Z"),
        make_client_headers(c_id))
    hl = validate_success(resp, 201)
    assert hl["kind"] == "WORKOUT_COMPLETED"


# ─── Corner: validations / subscription_booking_with_pack_id_returns_model_mismatch ─

def test_subscription_booking_with_pack_id_returns_model_mismatch(api):
    """PRD §3.4: "an `ONLINE_SUBSCRIPTION` booking must omit `session_pack_id`; a
    violation of this billing-model fit or pack ownership — independent of whether
    seats remain — is rejected with `ERR_PACK_MODEL_MISMATCH`."

    An ONLINE_SUBSCRIPTION booking carrying a real (existing) session_pack_id
    returns ERR_PACK_MODEL_MISMATCH — the billing-model-fit check, isolated from
    the body-FK existence check by using a pack that genuinely exists.

    Design: Corner/validations/subscription_booking_with_pack_id_returns_model_mismatch
    """
    set_clock("2026-06-01T00:00:00Z")
    trainer = create_trainer()
    t_id = trainer["id"]
    # A SESSION_PACK engagement whose pack genuinely exists.
    pack_client = create_assessed_client(t_id)
    pack_eng = create_engagement(t_id, pack_client["id"], pack_client["version"],
                                 billing_model="SESSION_PACK")
    pack = create_pack(t_id, pack_eng["id"], total_sessions=5, price_cents=50000)
    # A separate ONLINE_SUBSCRIPTION engagement; booking it with the real pack id
    # violates billing-model fit.
    sub_client = create_assessed_client(t_id)
    sub_eng = create_engagement(t_id, sub_client["id"], sub_client["version"],
                                billing_model="ONLINE_SUBSCRIPTION",
                                monthly_fee_cents=6000, cycle_start_utc="2026-06-01T00:00:00Z")
    resp = api.create_booking(
        create_booking_payload(sub_eng["id"], "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z",
                               session_pack_id=pack["id"]),
        make_client_headers(sub_client["id"]))
    validate_error(resp, ApiErrorId.ERR_PACK_MODEL_MISMATCH.value)


# ─── Corner: validations / macro_plan_without_weight_returns_no_weight ───────

def test_macro_plan_without_weight_returns_no_weight(api):
    """PRD §3.7: "Creation requires that the client already has a non-null
    `latest_weight_kg` (that is, at least one assessed check-in carrying a weight)
    and that no macro plan — provisional or locked — already exists for the
    engagement; a violation of either condition is rejected with
    `ERR_NO_WEIGHT_FOR_MACROS`."

    Creating a macro plan with no assessed check-in (latest_weight_kg null) returns
    ERR_NO_WEIGHT_FOR_MACROS.

    Design: Corner/validations/macro_plan_without_weight_returns_no_weight
    """
    ctx = setup_subscription_engagement(clock_utc="2026-06-01T00:00:00Z")
    t_id, e_id = ctx["trainer"]["id"], ctx["engagement"]["id"]
    resp = api.create_macro_plan(
        e_id, create_macro_plan_payload(goal="FAT_LOSS", activity_level="MODERATE"),
        make_trainer_headers(t_id))
    validate_error(resp, ApiErrorId.ERR_NO_WEIGHT_FOR_MACROS.value)


# ─── Corner: validations / missing_auth_headers_returns_401 ──────────────────

def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value,
    is rejected with `ERR_MISSING_AUTH` (HTTP 401)."

    A request with no X-User-ID / X-User-Role headers is rejected ERR_MISSING_AUTH.

    Design: Corner/validations/missing_auth_headers_returns_401
    """
    resp = api.get_client(NON_EXISTENT_UUID, {})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)
