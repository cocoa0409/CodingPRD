"""The three-rung step ladder, its deadlines and the derived timeliness posture."""

from test_helpers import (
    ApiErrorId,
    appeal_grievance,
    assert_grievance_step,
    assert_instant,
    draft_offer,
    grievance_step_payload,
    hold_open_step,
    hold_step,
    read_grievance,
    respond_step,
    run_step,
    schedule_step,
    set_clock,
    setup_grievance,
    step_response_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_step_ladder_traverses_the_same_statuses_on_the_second_round(api):
    """PRD §3.3: "Concretely, the procedural status of a grievance runs `ANSWERED` →
    `APPEALED` → `STEP_MEETING_SCHEDULED` → `AWAITING_RESPONSE` → `ANSWERED`, with the
    loop bounded by `current_step` never exceeding 3."
    PRD §3.3: "Either route increments `current_step` by 1 and leaves the grievance at
    `APPEALED`, ready for the next meeting to be scheduled."

    Design: Difficulty/non_linear_state_machine/grievance_step_ladder_cycle_two_rounds
    """
    ctx = setup_grievance(statement="Written warning issued without cause")
    run_step(ctx, "2026-08-05T00:00:00Z", "DENIED")
    appeal_grievance(ctx, "Appealed to step 2")
    run_step(
        ctx, "2026-08-10T00:00:00Z", "PARTIAL",
        response_overrides={"granted_amount_cents": 5_000},
    )

    appealed = appeal_grievance(ctx, "Appealed to step 3")
    assert appealed["status"] == "APPEALED"
    assert appealed["current_step"] == 3

    third_step = schedule_step(ctx["grievance"]["id"], "2026-08-14T00:00:00Z")
    assert third_step["status"] == "SCHEDULED"
    assert third_step["step_number"] == 3

    grievance = read_grievance(ctx["grievance"]["id"])
    assert grievance["status"] == "STEP_MEETING_SCHEDULED"
    assert grievance["current_step"] == 3
    assert grievance["timeliness_state"] == "TIMELY"


def test_partial_step_answer_adds_to_the_settled_amount_and_the_ladder_lists_in_order(api):
    """PRD §3.3: "Where the answer goes next depends on the disposition: a `DENIED` or
    `PARTIAL` answer moves the grievance from `AWAITING_RESPONSE` to `ANSWERED`, with a
    `PARTIAL` answer **adding** its granted amount to the grievance's
    `settled_amount_cents`; a `GRANTED` answer settles the case outright, moving the
    grievance from `AWAITING_RESPONSE` straight to `SETTLED`, **setting**
    `settled_amount_cents` to the granted amount, transitioning every settlement offer on
    that grievance still in `DRAFT` or `AUTHORIZED` to `VOIDED`, and freezing the
    timeliness posture at whatever value it held at that instant."
    PRD §2.3: "- Step records of one grievance: ascending `step_number`, then ascending
    `created_at`."

    Design: Difficulty/non_linear_state_machine/grievance_step_ladder_cycle_two_rounds
    """
    ctx = setup_grievance(statement="Written warning issued without cause")
    first = run_step(ctx, "2026-08-05T00:00:00Z", "DENIED")
    appeal_grievance(ctx, "Appealed to step 2")
    second = run_step(
        ctx, "2026-08-10T00:00:00Z", "PARTIAL",
        response_overrides={"granted_amount_cents": 5_000},
    )
    appeal_grievance(ctx, "Appealed to step 3")
    schedule_step(ctx["grievance"]["id"], "2026-08-14T00:00:00Z")

    grievance = read_grievance(ctx["grievance"]["id"])
    assert grievance["settled_amount_cents"] == 5_000
    assert grievance["status"] == "STEP_MEETING_SCHEDULED"

    rows, meta = validate_paginated(
        api.list_grievance_steps(ctx["grievance"]["id"], ctx["steward_headers"])
    )
    assert meta["total_count"] == 3
    assert [row["step_number"] for row in rows] == [1, 2, 3]
    assert rows[2]["status"] == "SCHEDULED"
    for row in rows:
        assert_grievance_step(row)

    assert first["status"] == "ANSWERED"
    assert_instant(first["response_due_at"], "2026-08-15T00:00:00Z", "response_due_at")
    assert second["disposition"] == "PARTIAL"
    assert second["late_by_days"] == 0


def test_holding_the_same_step_twice_is_refused(api, analyst_headers):
    """PRD §3.3: "The step must be `SCHEDULED` and its grievance must be at
    `STEP_MEETING_SCHEDULED`; the step moves to `HELD`, the grievance moves to
    `AWAITING_RESPONSE`, and `meeting_held_at` is stamped with the clock's current
    instant."
    PRD §2.10: "The target resource is in a state from which the requested transition is
    declared — otherwise the state error for that resource type, all at HTTP 409:
    `ERR_INVALID_GRIEVANCE_STATE`, `ERR_INVALID_STEP_STATE`, `ERR_OFFER_NOT_DRAFT`,
    `ERR_OFFER_NOT_AUTHORIZED`, `ERR_DEMAND_STATE_INVALID`, `ERR_AWARD_STATE_INVALID` or
    `ERR_COST_ENTRY_ALREADY_VOIDED`."

    Design: Corner/state_machines/holding_the_same_step_twice_returns_invalid_step_state
    """
    ctx = setup_grievance()
    step = hold_open_step(ctx, "2026-08-05T00:00:00Z")
    set_clock("2026-08-06T00:00:00Z")

    validate_error(
        api.hold_grievance_step(step["id"], analyst_headers),
        ApiErrorId.ERR_INVALID_STEP_STATE.value,
    )

    rows, _ = validate_paginated(
        api.list_grievance_steps(ctx["grievance"]["id"], analyst_headers)
    )
    unchanged = rows[0]
    assert_instant(unchanged["meeting_held_at"], "2026-08-05T00:00:00Z", "meeting_held_at")
    assert_instant(unchanged["response_due_at"], "2026-08-15T00:00:00Z", "response_due_at")
    assert read_grievance(ctx["grievance"]["id"])["status"] == "AWAITING_RESPONSE"


def test_answering_a_step_that_was_never_held_is_refused(api, analyst_headers):
    """PRD §3.3: "The employer's answer is recorded against a `HELD` step by the analyst,
    who supplies a `disposition` of `GRANTED`, `PARTIAL` or `DENIED`, a narrative
    `response_summary`, and — only when the disposition is `GRANTED` or `PARTIAL` — a
    `granted_amount_cents` figure of zero or more."

    Design: Corner/state_machines/responding_before_the_meeting_is_held_returns_invalid_step_state
    """
    ctx = setup_grievance()
    step = schedule_step(ctx["grievance"]["id"], "2026-08-05T00:00:00Z")

    validate_error(
        api.respond_grievance_step(
            step["id"], step_response_payload("DENIED", response_summary="Answer before the meeting"),
            analyst_headers,
        ),
        ApiErrorId.ERR_INVALID_STEP_STATE.value,
    )

    rows, _ = validate_paginated(
        api.list_grievance_steps(ctx["grievance"]["id"], analyst_headers)
    )
    assert rows[0]["status"] == "SCHEDULED"
    assert rows[0]["disposition"] is None
    assert rows[0]["responded_by_user_id"] is None
    assert read_grievance(ctx["grievance"]["id"])["status"] == "STEP_MEETING_SCHEDULED"


def test_granted_step_answer_settles_the_case_and_voids_open_offers(api, analyst_headers):
    """PRD §3.3: "Where the answer goes next depends on the disposition: a `DENIED` or
    `PARTIAL` answer moves the grievance from `AWAITING_RESPONSE` to `ANSWERED`, with a
    `PARTIAL` answer **adding** its granted amount to the grievance's
    `settled_amount_cents`; a `GRANTED` answer settles the case outright, moving the
    grievance from `AWAITING_RESPONSE` straight to `SETTLED`, **setting**
    `settled_amount_cents` to the granted amount, transitioning every settlement offer on
    that grievance still in `DRAFT` or `AUTHORIZED` to `VOIDED`, and freezing the
    timeliness posture at whatever value it held at that instant."

    Design: Corner/state_machines/granted_step_answer_settles_the_grievance_and_voids_open_offers
    """
    ctx = setup_grievance()
    offer = draft_offer(ctx["grievance"]["id"], monetary_cents=40_000)
    step = hold_open_step(ctx, "2026-08-05T00:00:00Z")

    answered = respond_step(
        step["id"], "GRANTED",
        response_summary="Discipline rescinded in full",
        granted_amount_cents=120_000,
    )

    assert answered["status"] == "ANSWERED"
    assert answered["disposition"] == "GRANTED"
    assert answered["granted_amount_cents"] == 120_000

    grievance = read_grievance(ctx["grievance"]["id"])
    assert grievance["status"] == "SETTLED"
    assert grievance["settled_amount_cents"] == 120_000

    voided = validate_success(api.get_settlement_offer(offer["id"], analyst_headers), 200)
    assert voided["status"] == "VOIDED"


def test_granted_step_answer_moves_the_supervisor_and_clause_scorecards(api, analyst_headers):
    """PRD §3.9: "A grievance meets that predicate, counted once however many of the
    following are true, when an award exists on its arbitration demand with an `outcome` of
    `SUSTAINED` or `SPLIT`; or when its status is `SETTLED` or `CLOSED` and its
    `settled_amount_cents` is greater than 0; or when any of its steps carries a
    `disposition` of `GRANTED` or `PARTIAL`."
    PRD §3.9: "`closed_grievance_count` counts those whose status is `SETTLED`,
    `WITHDRAWN` or `CLOSED` — note that `CONSOLIDATED` grievances are excluded from both
    the numerator and the denominator, so a consolidated case never scores against
    anybody."

    Design: Corner/state_machines/granted_step_answer_settles_the_grievance_and_voids_open_offers
    """
    ctx = setup_grievance()
    step = hold_open_step(ctx, "2026-08-05T00:00:00Z")
    respond_step(
        step["id"], "GRANTED",
        response_summary="Discipline rescinded in full",
        granted_amount_cents=120_000,
    )

    supervisor = validate_success(
        api.get_employee(ctx["supervisor"]["id"], analyst_headers), 200
    )
    assert supervisor["closed_grievance_count"] == 1
    assert supervisor["sustained_against_count"] == 1
    assert supervisor["adverse_rate_bps"] == 10_000

    clauses, _ = validate_paginated(
        api.list_contract_clauses(ctx["unit"]["id"], analyst_headers)
    )
    assert clauses[0]["sustained_count"] == 1
    assert clauses[0]["denied_count"] == 0


def test_agreed_extension_tolls_the_posture_and_extends_the_response_deadline(api):
    """PRD §3.3: "A step scheduled with positive extension days immediately re-derives the
    grievance's posture to `TOLLED`."
    PRD §3.3: "The step's own `extension_days` are then added. The order is normative: the
    halving and its upward rounding happen first, and the extension is added to the
    already-rounded figure, never before it."

    Design: Corner/calculations/tolled_extension_moves_response_deadline_and_posture
    """
    ctx = setup_grievance(unit_overrides={"tolling_enabled": True})

    step = schedule_step(ctx["grievance"]["id"], "2026-08-05T00:00:00Z", extension_days=3)
    assert step["extension_days"] == 3
    assert step["status"] == "SCHEDULED"
    assert read_grievance(ctx["grievance"]["id"])["timeliness_state"] == "TOLLED"

    set_clock("2026-08-05T00:00:00Z")
    held = hold_step(step["id"])
    assert_instant(held["response_due_at"], "2026-08-18T00:00:00Z", "response_due_at")
    assert held["late_by_days"] == 0


def test_holding_the_meeting_lifts_a_tolled_posture_back_to_timely(api):
    """PRD §3.3: "Holding a meeting also lifts a `TOLLED` posture back to `TIMELY`."

    Design: Corner/calculations/tolled_extension_moves_response_deadline_and_posture
    """
    ctx = setup_grievance(unit_overrides={"tolling_enabled": True})
    step = schedule_step(ctx["grievance"]["id"], "2026-08-05T00:00:00Z", extension_days=3)
    assert read_grievance(ctx["grievance"]["id"])["timeliness_state"] == "TOLLED"

    set_clock("2026-08-05T00:00:00Z")
    hold_step(step["id"])

    assert read_grievance(ctx["grievance"]["id"])["timeliness_state"] == "TIMELY"


def test_late_employer_answer_counts_the_late_days_and_defaults_the_employer(api):
    """PRD §3.3: "`late_by_days` is then computed as the whole calendar days from
    `response_due_at` to `responded_at`, floored at 0, so an answer delivered early or
    exactly on time reads 0. "
    PRD §3.3: "A late answer — one where `late_by_days` is greater than 0 — re-derives the
    posture to `EMPLOYER_DEFAULT`."

    Design: Corner/calculations/late_employer_answer_sets_employer_default_and_late_days
    """
    ctx = setup_grievance()
    step = hold_open_step(ctx, "2026-08-05T00:00:00Z")

    set_clock("2026-08-17T00:00:00Z")
    answered = respond_step(step["id"], "DENIED", response_summary="Late answer")

    assert answered["status"] == "ANSWERED"
    assert_instant(answered["responded_at"], "2026-08-17T00:00:00Z", "responded_at")
    assert answered["late_by_days"] == 2

    grievance = read_grievance(ctx["grievance"]["id"])
    assert grievance["status"] == "ANSWERED"
    assert grievance["timeliness_state"] == "EMPLOYER_DEFAULT"


def test_appeal_deadline_anchors_on_the_answer_instant(api):
    """PRD §3.3: "From those, `appeal_deadline_at` is the latest step's resolution instant
    plus the agreement's `appeal_window_days`, and is null while no step is resolved;
    `arbitration_deadline_at` is the step-3 record's resolution instant plus the
    agreement's `arbitration_demand_days`, and is null unless `current_step` is 3 and that
    step is resolved."
    PRD §3.3: "A step's **resolution instant** is its `responded_at` when it stands at
    `ANSWERED`, its `response_due_at` when it stands at `DEEMED_DENIED`, and undefined
    otherwise."

    Design: Corner/calculations/late_employer_answer_sets_employer_default_and_late_days
    """
    ctx = setup_grievance()
    step = hold_open_step(ctx, "2026-08-05T00:00:00Z")
    set_clock("2026-08-17T00:00:00Z")
    respond_step(step["id"], "DENIED", response_summary="Late answer")

    grievance = read_grievance(ctx["grievance"]["id"], ctx["steward_headers"])
    assert_instant(grievance["appeal_deadline_at"], "2026-08-24T00:00:00Z", "appeal_deadline_at")
    assert grievance["arbitration_deadline_at"] is None
    assert grievance["current_step"] == 1


def test_posture_reads_union_default_once_only_the_appeal_window_has_run(api):
    """PRD §3.3: "Otherwise, if the latest step has a resolution instant, the grievance
    stands at `ANSWERED`, and the clock is strictly past `appeal_deadline_at`, the posture
    is `UNION_DEFAULT`."

    Design: Corner/calculations/timeliness_posture_barred_outranks_union_default
    """
    ctx = setup_grievance(statement="Discharge without just cause")
    run_step(ctx, "2026-08-05T00:00:00Z", "DENIED")
    appeal_grievance(ctx, "Appealed to step 2")
    run_step(ctx, "2026-08-10T00:00:00Z", "DENIED")
    appeal_grievance(ctx, "Appealed to step 3")
    run_step(ctx, "2026-08-14T00:00:00Z", "DENIED")

    at_answer = read_grievance(ctx["grievance"]["id"], ctx["steward_headers"])
    assert at_answer["timeliness_state"] == "TIMELY"
    assert_instant(at_answer["appeal_deadline_at"], "2026-08-21T00:00:00Z", "appeal_deadline_at")
    assert_instant(
        at_answer["arbitration_deadline_at"], "2026-09-04T00:00:00Z", "arbitration_deadline_at"
    )

    set_clock("2026-08-25T00:00:00Z")
    assert read_grievance(ctx["grievance"]["id"])["timeliness_state"] == "UNION_DEFAULT"


def test_barred_outranks_union_default_once_the_arbitration_window_also_runs(api):
    """PRD §3.3: "Otherwise, if `current_step` is 3, the latest step has a resolution
    instant, no arbitration demand exists for the grievance, and the clock is strictly past
    `arbitration_deadline_at`, the posture is `BARRED`."
    PRD §3.3: "A case sitting at step 3 past both the appeal window and the arbitration
    window satisfies branches 3 and 4 simultaneously, and `BARRED` must win."

    Design: Corner/calculations/timeliness_posture_barred_outranks_union_default
    """
    ctx = setup_grievance(statement="Discharge without just cause")
    run_step(ctx, "2026-08-05T00:00:00Z", "DENIED")
    appeal_grievance(ctx, "Appealed to step 2")
    run_step(ctx, "2026-08-10T00:00:00Z", "DENIED")
    appeal_grievance(ctx, "Appealed to step 3")
    run_step(ctx, "2026-08-14T00:00:00Z", "DENIED")

    set_clock("2026-09-10T00:00:00Z")
    grievance = read_grievance(ctx["grievance"]["id"], ctx["steward_headers"])

    assert grievance["timeliness_state"] == "BARRED"
    assert grievance["status"] == "ANSWERED", "the posture is a dimension of its own"
    assert grievance["current_step"] == 3


def test_meeting_booked_at_or_before_the_clock_is_refused(api, analyst_headers):
    """PRD §3.3: "The payload carries `meeting_scheduled_at`, which must be strictly after
    the logical clock's current instant or the request is rejected with
    `ERR_MEETING_DATE_IN_PAST`, and an optional `extension_days` defaulting to 0 and never
    negative."

    Design: Corner/validations/step_meeting_scheduled_in_the_past_rejected
    """
    ctx = setup_grievance()

    at_the_clock = api.create_grievance_step(
        ctx["grievance"]["id"], grievance_step_payload("2026-08-01T00:00:00Z"), analyst_headers
    )
    validate_error(at_the_clock, ApiErrorId.ERR_MEETING_DATE_IN_PAST.value)

    before_the_clock = api.create_grievance_step(
        ctx["grievance"]["id"], grievance_step_payload("2026-07-30T00:00:00Z"), analyst_headers
    )
    validate_error(before_the_clock, ApiErrorId.ERR_MEETING_DATE_IN_PAST.value)

    assert read_grievance(ctx["grievance"]["id"])["status"] == "FILED"
    _, meta = validate_paginated(
        api.list_grievance_steps(ctx["grievance"]["id"], analyst_headers)
    )
    assert meta["total_count"] == 0


def test_appeal_after_the_appeal_deadline_is_refused(api):
    """PRD §3.3: "The ordinary route runs from `ANSWERED`: the employer has answered, and
    the union appeals no later than the grievance's `appeal_deadline_at`, an appeal after
    that instant being rejected with `ERR_APPEAL_WINDOW_EXPIRED`."

    Design: Corner/validations/appeal_after_the_appeal_window_is_rejected
    """
    ctx = setup_grievance()
    run_step(ctx, "2026-08-05T00:00:00Z", "DENIED")
    set_clock("2026-08-13T00:00:00Z")

    response = api.appeal_grievance(
        ctx["grievance"]["id"], {"appeal_statement": "Late appeal"}, ctx["steward_headers"]
    )
    validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED.value)

    grievance = read_grievance(ctx["grievance"]["id"], ctx["steward_headers"])
    assert_instant(grievance["appeal_deadline_at"], "2026-08-12T00:00:00Z", "appeal_deadline_at")
    assert grievance["current_step"] == 1
    assert grievance["status"] == "ANSWERED"
    assert grievance["timeliness_state"] == "UNION_DEFAULT"


def test_money_alongside_a_denied_disposition_is_refused(api, analyst_headers):
    """PRD §3.3: "Supplying money alongside a `DENIED` disposition is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/granted_amount_supplied_with_denied_disposition_rejected
    """
    ctx = setup_grievance()
    step = hold_open_step(ctx, "2026-08-05T00:00:00Z")

    refused = api.respond_grievance_step(
        step["id"],
        step_response_payload(
            "DENIED", response_summary="Denied but money offered", granted_amount_cents=5_000
        ),
        analyst_headers,
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_REQUEST.value)

    rows, _ = validate_paginated(
        api.list_grievance_steps(ctx["grievance"]["id"], analyst_headers)
    )
    assert rows[0]["status"] == "HELD"

    accepted = respond_step(
        step["id"], "PARTIAL", response_summary="Partially granted", granted_amount_cents=5_000
    )
    assert accepted["disposition"] == "PARTIAL"
    assert accepted["granted_amount_cents"] == 5_000

    grievance = read_grievance(ctx["grievance"]["id"])
    assert grievance["settled_amount_cents"] == 5_000
    assert grievance["status"] == "ANSWERED"


def test_extension_days_require_the_agreement_to_permit_tolling(api, analyst_headers):
    """PRD §3.3: "Extension days are the parties' mutually agreed padding on the employer's
    response window, and they are a privilege of the agreement: any positive value requires
    the agreement's `tolling_enabled` to be true, and otherwise the request is rejected with
    `ERR_TOLLING_NOT_PERMITTED`."

    Design: Corner/validations/extension_days_without_tolling_enabled_rejected
    """
    ctx = setup_grievance()

    refused = api.create_grievance_step(
        ctx["grievance"]["id"],
        grievance_step_payload("2026-08-05T00:00:00Z", extension_days=3),
        analyst_headers,
    )
    validate_error(refused, ApiErrorId.ERR_TOLLING_NOT_PERMITTED.value)

    accepted = validate_success(
        api.create_grievance_step(
            ctx["grievance"]["id"],
            grievance_step_payload("2026-08-05T00:00:00Z", extension_days=0),
            analyst_headers,
        ),
        201,
    )
    assert accepted["extension_days"] == 0

    grievance = read_grievance(ctx["grievance"]["id"])
    assert grievance["status"] == "STEP_MEETING_SCHEDULED"
    assert grievance["timeliness_state"] == "TIMELY"


def test_appeal_from_step_three_is_refused(api, analyst_headers):
    """PRD §3.3: "It carries an `appeal_statement`, requires the agreement to still be
    `ACTIVE`, and requires `current_step` to be below 3 — an appeal attempted from step 3
    is rejected with `ERR_STEP_LADDER_EXHAUSTED`."

    Design: Corner/validations/appeal_from_step_three_is_refused
    """
    ctx = setup_grievance(statement="Discharge without just cause")
    run_step(ctx, "2026-08-05T00:00:00Z", "DENIED")
    appeal_grievance(ctx, "Appealed to step 2")
    run_step(ctx, "2026-08-10T00:00:00Z", "DENIED")
    appeal_grievance(ctx, "Appealed to step 3")
    run_step(ctx, "2026-08-14T00:00:00Z", "DENIED")

    response = api.appeal_grievance(
        ctx["grievance"]["id"], {"appeal_statement": "Appealed to step 4"}, ctx["steward_headers"]
    )
    validate_error(response, ApiErrorId.ERR_STEP_LADDER_EXHAUSTED.value)

    grievance = read_grievance(ctx["grievance"]["id"])
    assert grievance["current_step"] == 3
    assert grievance["status"] == "ANSWERED"
    _, meta = validate_paginated(
        api.list_grievance_steps(ctx["grievance"]["id"], analyst_headers)
    )
    assert meta["total_count"] == 3


def test_employer_silence_lets_the_union_appeal_on_a_deemed_denial(api):
    """PRD §3.3: "The second route runs from `AWAITING_RESPONSE` and exists for the case
    where the employer simply never answered: when the latest step is still `HELD` and the
    clock has passed its `response_due_at`, the union may appeal anyway. In that case the
    overdue step is first transitioned from `HELD` to `DEEMED_DENIED`, the grievance's
    `appeal_deadline_at` is recomputed from that step's `response_due_at` rather than from
    a non-existent `responded_at`, and the grievance's `timeliness_state` is set to
    `EMPLOYER_DEFAULT`."

    Design: Corner/validations/employer_silence_lets_the_union_appeal_on_a_deemed_denial
    """
    ctx = setup_grievance()
    hold_open_step(ctx, "2026-08-05T00:00:00Z")
    set_clock("2026-08-16T00:00:00Z")

    appealed = validate_success(
        api.appeal_grievance(
            ctx["grievance"]["id"],
            {"appeal_statement": "No answer received"},
            ctx["steward_headers"],
        ),
        200,
    )

    assert appealed["status"] == "APPEALED"
    assert appealed["current_step"] == 2

    rows, meta = validate_paginated(
        api.list_grievance_steps(ctx["grievance"]["id"], ctx["steward_headers"])
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "DEEMED_DENIED"
    assert rows[0]["responded_at"] is None
    assert rows[0]["late_by_days"] == 0

    grievance = read_grievance(ctx["grievance"]["id"], ctx["steward_headers"])
    assert grievance["timeliness_state"] == "EMPLOYER_DEFAULT"
    assert_instant(grievance["appeal_deadline_at"], "2026-08-22T00:00:00Z", "appeal_deadline_at")
