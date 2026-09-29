"""The catalogue's concurrency, companion-state, uniqueness and separation codes."""
from test_helpers import (
    add_operating_room,
    add_segment,
    add_staff_member,
    book_theatre,
    create_active_recipient,
    create_approved_donor,
    create_chain,
    create_donor,
    create_improvement_plan_payload,
    create_medical_evaluation_payload,
    create_offer_payload,
    create_outcome_review,
    create_program,
    create_psychosocial_evaluation_payload,
    create_recipient,
    determine_evaluation,
    file_claim,
    file_improvement_plan,
    finalize_review,
    follow_up_by_interval,
    follow_up_fields,
    get_chain,
    get_donor,
    get_segment,
    make_program_admin_headers,
    refresh_program,
    setup_donated_donor,
    setup_paired_loop_participants,
    setup_program_with_staff,
    submit_medical_evaluation,
    validate_chain,
    validate_error,
    validate_paginated,
    validate_success,
    waive_follow_up,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId


def _three_pair_participants():
    """Three ACTIVE recipients and three APPROVED directed donors, ready to loop."""
    env = setup_program_with_staff()
    env["recipient_one"] = create_active_recipient(
        env, mrn="R-001", abo_blood_type="A", age_years=44, cpra=0.85
    )
    env["recipient_two"] = create_active_recipient(
        env, mrn="R-002", abo_blood_type="B", age_years=51, cpra=0.1
    )
    env["recipient_three"] = create_active_recipient(
        env, mrn="R-003", abo_blood_type="AB", age_years=39, cpra=0.4
    )
    env["donor_one"] = create_approved_donor(
        env, intended_recipient_id=env["recipient_one"]["id"], mrn="D-001", age_years=41
    )
    env["donor_two"] = create_approved_donor(
        env, intended_recipient_id=env["recipient_two"]["id"], mrn="D-002", age_years=38
    )
    env["donor_three"] = create_approved_donor(
        env, intended_recipient_id=env["recipient_three"]["id"], mrn="D-003", age_years=45
    )
    return env


def _three_segment_loop(env):
    """D-001 gives to R-002, D-002 to R-003, D-003 back to R-001 — a closed loop."""
    chain = create_chain(env, "PAIRED_LOOP")
    first = add_segment(
        env, chain["id"], 1, env["donor_one"]["id"], env["recipient_two"]["id"]
    )
    second = add_segment(
        env,
        chain["id"],
        2,
        env["donor_two"]["id"],
        env["recipient_three"]["id"],
        predecessor_segment_id=first["id"],
    )
    third = add_segment(
        env,
        chain["id"],
        3,
        env["donor_three"]["id"],
        env["recipient_one"]["id"],
        predecessor_segment_id=second["id"],
    )
    env.update(
        {
            "chain": chain,
            "segment_one": first,
            "segment_two": second,
            "segment_three": third,
        }
    )
    return env


def test_err_stale_chain_version_returns_412():
    """PRD §2.7: "Inserting a segment into a chain — `POST /exchange-chains/{id}/segments`
    — requires a non-optional `expected_chain_version` field carrying the client's last
    observed `version` of the target `ExchangeChain`."
    PRD §2.7: "If the value does not match the chain's current `version`, the insertion is
    rejected with `ERR_STALE_CHAIN_VERSION` (HTTP 412), because the writer validated its
    position and predecessor against a topology that no longer exists."
    PRD §2.7: "Both checks run **before** any state or business rule on the request, so a
    client holding an out-of-date view learns that fact rather than being told about a state
    it may never have observed."
    PRD §3.5: "Insertion recomputes the chain's `segment_count` and `is_closed_loop` and
    increments the chain's `version`, so any other client holding the previous value is
    immediately stale."

    Design: Corner/errors/err_stale_chain_version_returns_412
    """
    env = setup_paired_loop_participants()
    chain = create_chain(env, "PAIRED_LOOP")
    version_zero = chain["version"]
    first = add_segment(
        env, chain["id"], 1, env["donor_one"]["id"], env["recipient_two"]["id"]
    )

    response = api_client.create_chain_segment(
        chain["id"],
        {
            "expected_chain_version": version_zero,
            "position": 2,
            "donor_candidate_id": env["donor_two"]["id"],
            "recipient_candidate_id": env["recipient_one"]["id"],
            "predecessor_segment_id": first["id"],
        },
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_STALE_CHAIN_VERSION.value, expected_status=412
    )

    assert get_chain(env, chain["id"])["segment_count"] == 1
    _rows, meta = validate_paginated(
        api_client.list_chain_segments(
            env["coordinator_headers"], params={"exchange_chain_id": chain["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_err_stale_review_version_returns_412():
    """PRD §2.7: "Creating an improvement plan — `POST /improvement-plans` — requires a
    non-optional `expected_review_version` field carrying the client's last observed
    `version` of the target `ProgramOutcomeReview`."
    PRD §2.7: "A mismatch is rejected with `ERR_STALE_REVIEW_VERSION` (HTTP 412)."
    PRD §3.8: "Creation puts the new plan in `SUBMITTED` with `decision_reason_code`,
    `decided_at` and `closed_at` all null, moves any existing plan of the same review whose
    status is `SUBMITTED` or `REJECTED` to `SUPERSEDED` — which the system will only do
    while no plan of that review has already reached `ACCEPTED` or `CLOSED` — and increments
    the parent review's `version` so that a competing writer holding the old value is now
    stale."
    PRD §2.8: "Then: if an unanswered flagged review exists, the posture is `FROZEN`.
    Otherwise, if `follow_up_compliance_pct` is strictly below the program's
    `follow_up_compliance_threshold_pct`, or an open watch exists, or `cit_breach_count` is
    at least 2, the posture is `RESTRICTED`. Otherwise the posture is `OPEN`."

    Design: Corner/errors/err_stale_review_version_returns_412
    """
    env = setup_program_with_staff()
    review = create_outcome_review(env, cohort_size=25, observed_survivor_count=16)
    version_zero = review["version"]
    finalized = finalize_review(env, review["id"])
    assert finalized["flag_level"] == "FLAGGED"
    assert finalized["version"] > version_zero, "finalization moved the parent on"

    response = api_client.create_improvement_plan(
        create_improvement_plan_payload(
            review["id"],
            version_zero,
            title="Donor selection review",
            milestone_count=4,
            target_completion_on="2026-12-31",
        ),
        env["quality_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_STALE_REVIEW_VERSION.value, expected_status=412
    )

    rows, meta = validate_paginated(
        api_client.list_review_improvement_plans(review["id"], env["quality_headers"])
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert refresh_program(env)["compliance_posture"] == "FROZEN", (
        "the refused plan did not answer the flag"
    )


def test_err_chain_not_committed_returns_409():
    """PRD §3.6: "The parent chain's status must be `COMMITTED` or `EXECUTING`, or the
    request is refused with `ERR_CHAIN_NOT_COMMITTED` — a chain broken by an earlier decline
    can never be re-offered."
    PRD §2.10: "Companion-entity state gates about the request's own target —
    `ERR_CHAIN_NOT_COMMITTED`, `ERR_REVIEW_NOT_FINALIZED`, `ERR_CLAIM_NOT_ADJUDICATED`,
    `ERR_BOOKING_NOT_ACTIVE` or `ERR_FOLLOW_UP_TERMINAL`, 409."
    PRD §3.5: "A new chain starts in `DRAFT` with `segment_count` 0, `is_closed_loop`
    false, `total_planned_cit_minutes` 0 and `committed_donor_count` 0, and with
    `validated_at`, `committed_at` and `break_reason_code` all null."
    PRD §3.5: "The new segment starts in `PLANNED` with every offer and planning field
    null."

    Design: Corner/errors/err_chain_not_committed_returns_409
    """
    env = setup_paired_loop_participants()
    chain = create_chain(env, "PAIRED_LOOP")
    segment = add_segment(
        env, chain["id"], 1, env["donor_one"]["id"], env["recipient_two"]["id"]
    )
    assert get_chain(env, chain["id"])["status"] == "DRAFT"

    response = api_client.send_segment_offer(
        segment["id"],
        create_offer_payload("2026-08-09T07:00:00Z", "2026-08-09T13:00:00Z"),
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_CHAIN_NOT_COMMITTED.value, expected_status=409
    )

    after = get_segment(env, segment["id"])
    assert after["status"] == "PLANNED"
    assert after["offer_sent_at"] is None
    assert after["planned_cit_minutes"] is None
    assert get_chain(env, chain["id"])["total_planned_cit_minutes"] == 0


def test_err_review_not_finalized_returns_409():
    """PRD §3.8: "Accepting a plan requires that the parent review's `status` is
    `FINALIZED`; acting on a plan whose review is still `DRAFT` is refused with
    `ERR_REVIEW_NOT_FINALIZED`."
    PRD §2.10: "Companion-entity state gates about the request's own target —
    `ERR_CHAIN_NOT_COMMITTED`, `ERR_REVIEW_NOT_FINALIZED`, `ERR_CLAIM_NOT_ADJUDICATED`,
    `ERR_BOOKING_NOT_ACTIVE` or `ERR_FOLLOW_UP_TERMINAL`, 409."
    PRD §3.8: "Creation puts the new plan in `SUBMITTED` with `decision_reason_code`,
    `decided_at` and `closed_at` all null, moves any existing plan of the same review whose
    status is `SUBMITTED` or `REJECTED` to `SUPERSEDED` — which the system will only do
    while no plan of that review has already reached `ACCEPTED` or `CLOSED` — and increments
    the parent review's `version` so that a competing writer holding the old value is now
    stale."
    PRD §3.8: "A new review's `status` is `DRAFT` and `finalized_at` is null; a draft
    review does not yet affect the program's posture at all."

    Design: Corner/errors/err_review_not_finalized_returns_409
    """
    env = setup_program_with_staff()
    review = create_outcome_review(env, cohort_size=25, observed_survivor_count=16)
    assert review["status"] == "DRAFT"
    plan = file_improvement_plan(env, review["id"])
    assert plan["status"] == "SUBMITTED"

    response = api_client.transition_improvement_plan(
        plan["id"],
        {"action": "ACCEPT", "decision_reason_code": "PLAN_SATISFACTORY"},
        env["admin_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_REVIEW_NOT_FINALIZED.value, expected_status=409
    )

    rows, _meta = validate_paginated(
        api_client.list_review_improvement_plans(review["id"], env["quality_headers"])
    )
    assert rows[0]["status"] == "SUBMITTED"
    assert rows[0]["decided_at"] is None
    assert refresh_program(env)["compliance_posture"] == "OPEN", (
        "a DRAFT review never froze the program"
    )


def test_err_claim_not_adjudicated_returns_409():
    """PRD §3.9: "Reversal is only accepted against a claim whose `status` is
    `ADJUDICATED`; a claim in any other state is refused with
    `ERR_CLAIM_NOT_ADJUDICATED`."
    PRD §2.10: "First, the terminal-state rule at priority 8 is **exempted** for four
    operations, because priority 9 declares a domain-specific code for exactly the same
    question about exactly the same target, and the specific code must win: reversing a
    donor cost claim reports `ERR_CLAIM_NOT_ADJUDICATED`, cancelling a procedure booking
    reports `ERR_BOOKING_NOT_ACTIVE`, and both submitting and waiving a donor follow-up
    report `ERR_FOLLOW_UP_TERMINAL`."
    PRD §3.9: "A new claim starts in `SUBMITTED` with `insurance_part_cents`,
    `grant_part_cents` and `fund_part_cents` all 0 and with
    `adjudicated_reimbursement_cents`, `unfunded_cents`, `adjudicated_at`,
    `adjudicated_by_user_id` and `reversal_reason_code` all null."
    PRD §3.9: "`estimated_reimbursement_cents` is written once, at filing, and is never
    revised."
    PRD §2.9: "A program's `donor_fund_committed_cents` is the sum of `fund_part_cents`
    over every donor cost claim whose donor belongs to that program and whose `status` is
    `ADJUDICATED`."

    Design: Corner/errors/err_claim_not_adjudicated_returns_409
    """
    env = setup_donated_donor()
    donor_id = env["donor_one"]["id"]
    claim = file_claim(
        env, donor_id, claim_type="MEDICAL", submitted_amount_cents=450000
    )
    assert claim["status"] == "SUBMITTED"

    response = api_client.reverse_claim(
        claim["id"], {"reversal_reason_code": "CLERICAL_ERROR"}, env["finance_headers"]
    )

    validate_error(
        response, ApiErrorId.ERR_CLAIM_NOT_ADJUDICATED.value, expected_status=409
    )

    rows, _meta = validate_paginated(
        api_client.list_donor_cost_claims(donor_id, env["coordinator_headers"])
    )
    assert rows[0]["status"] == "SUBMITTED"
    assert rows[0]["adjudicated_reimbursement_cents"] is None
    assert rows[0]["estimated_reimbursement_cents"] == 450000
    assert refresh_program(env)["donor_fund_committed_cents"] == 0


def test_err_booking_not_active_returns_409():
    """PRD §3.6: "It is only accepted while the booking is `ACTIVE` — a booking already
    `CANCELLED` or `COMPLETED` is refused with `ERR_BOOKING_NOT_ACTIVE` — and only while the
    segment has not reached `TRANSPLANTED`."
    PRD §3.6: "Cancellation sets `status` to `CANCELLED`, records the reason, decrements
    the room's `reserved_minutes_total` by exactly this booking's `duration_minutes` once,
    and increments the booking's `version`."
    PRD §2.10: "First, the terminal-state rule at priority 8 is **exempted** for four
    operations, because priority 9 declares a domain-specific code for exactly the same
    question about exactly the same target, and the specific code must win: reversing a
    donor cost claim reports `ERR_CLAIM_NOT_ADJUDICATED`, cancelling a procedure booking
    reports `ERR_BOOKING_NOT_ACTIVE`, and both submitting and waiving a donor follow-up
    report `ERR_FOLLOW_UP_TERMINAL`."
    PRD §3.6: "The booking starts in `ACTIVE`, its `duration_minutes` is the whole minutes
    between `start_at` and `end_at`, its `cancel_reason_code` is null, and the room's
    `reserved_minutes_total` is incremented by that duration."

    Design: Corner/errors/err_booking_not_active_returns_409
    """
    env = setup_paired_loop_participants()
    chain = create_chain(env, "PAIRED_LOOP")
    segment = add_segment(
        env, chain["id"], 1, env["donor_one"]["id"], env["recipient_two"]["id"]
    )
    room = add_operating_room(env, "OR-1")
    booking = book_theatre(
        env,
        room["id"],
        segment["id"],
        "DONOR_RECOVERY",
        "2026-08-09T06:00:00Z",
        "2026-08-09T10:00:00Z",
    )
    assert booking["duration_minutes"] == 240
    cancelled = validate_success(
        api_client.cancel_procedure_booking(
            booking["id"],
            {"cancel_reason_code": "SCHEDULE_CHANGE"},
            env["coordinator_headers"],
        )
    )
    assert cancelled["status"] == "CANCELLED"
    rooms = validate_success(
        api_client.list_program_operating_rooms(env["program_id"], env["admin_headers"])
    )
    assert rooms[0]["reserved_minutes_total"] == 0

    response = api_client.cancel_procedure_booking(
        booking["id"],
        {"cancel_reason_code": "SCHEDULE_CHANGE"},
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_BOOKING_NOT_ACTIVE.value, expected_status=409
    )

    reread = validate_success(
        api_client.get_procedure_booking(booking["id"], env["coordinator_headers"])
    )
    assert reread["status"] == "CANCELLED"
    assert reread["duration_minutes"] == 240
    rooms_after = validate_success(
        api_client.list_program_operating_rooms(env["program_id"], env["admin_headers"])
    )
    assert rooms_after[0]["reserved_minutes_total"] == 0, "not -240, released once"


def test_err_follow_up_terminal_returns_409():
    """PRD §3.7: "Submission is refused before the interval's `due_on` with
    `ERR_FOLLOW_UP_NOT_DUE`, and is refused entirely against a row whose status is already
    `WAIVED` or `SUBMITTED_COMPLETE` with `ERR_FOLLOW_UP_TERMINAL`; submission is accepted
    while the row is `DUE`, `INCOMPLETE` or `DELINQUENT`."
    PRD §3.7: "A `ProgramAdmin` may instead waive an interval by supplying a
    `waiver_reason_code`; waiver is reachable from `DUE`, `INCOMPLETE` and `DELINQUENT`,
    sets the row to `WAIVED` — a terminal state — records the reason, recomputes the
    program's compliance figure, re-derives posture, and increments the row's `version`."
    PRD §3.7: "The denominator is the count of follow-up rows whose donor belongs to this
    program, whose `status` is one of `DUE`, `SUBMITTED_COMPLETE`, `INCOMPLETE` or
    `DELINQUENT`, and whose `due_on` is at or before the current logical clock."
    PRD §3.7: "When the denominator is zero the figure is 100.00 — a brand-new program
    with three future-dated rows reports the vacuous 100.00 rather than 0.00."

    Design: Corner/errors/err_follow_up_terminal_returns_409
    """
    env = setup_donated_donor()
    donor_id = env["donor_one"]["id"]
    six_month = follow_up_by_interval(env, donor_id, "SIX_MONTH")
    waived = waive_follow_up(env, six_month["id"], "DONOR_UNREACHABLE")
    assert waived["status"] == "WAIVED"

    response = api_client.submit_follow_up(
        six_month["id"],
        {"submitted_fields": follow_up_fields(12)},
        env["coordinator_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_FOLLOW_UP_TERMINAL.value, expected_status=409
    )

    reread = follow_up_by_interval(env, donor_id, "SIX_MONTH")
    assert reread["status"] == "WAIVED"
    assert reread["submitted_at"] is None
    assert reread["waiver_reason_code"] == "DONOR_UNREACHABLE"
    assert refresh_program(env)["follow_up_compliance_pct"] == 100.0, (
        "the waived row left both numerator and denominator"
    )


def test_err_program_restricted_returns_409():
    """PRD §2.8: "While a program is `RESTRICTED`, committing a chain whose `segment_count`
    is greater than 2 is refused with `ERR_PROGRAM_RESTRICTED` (HTTP 409), while
    two-segment chains remain committable."
    PRD §3.5: "The program's posture must not be `FROZEN`, or the request is refused with
    `ERR_PROGRAM_FROZEN`; and if the posture is `RESTRICTED`, the chain's `segment_count`
    must be at most 2, or the request is refused with `ERR_PROGRAM_RESTRICTED`."
    PRD §3.5: "On success the chain moves to `COMMITTED`, `committed_at` is set to the
    current logical clock, `committed_donor_count` becomes the number of distinct donors on
    non-withdrawn segments, every one of those donors moves from `APPROVED` to
    `CHAIN_COMMITTED`, and the chain's `version` increments."
    PRD §3.8: "Otherwise `oe_ratio` is `observed_survivor_count` divided by
    `expected_survivor_count`, rounded half up to **four** decimal places, and `flag_level`
    is `FLAGGED` when `oe_ratio` is strictly below 0.85, `WATCH` when it is strictly below
    0.95 but not below 0.85, and `NONE` otherwise."
    PRD §3.8: "The cascade then runs in three further hops: because the review is now
    finalized, the program's `compliance_posture` is re-derived, where a `FLAGGED` level
    drives `FROZEN` and a `WATCH` level drives `RESTRICTED`; because the posture entered
    `FROZEN`, every chain of the program whose status is `DRAFT` or `VALIDATED` moves to
    `SUSPENDED`; and because those chains are suspended, each of their `OFFER_SENT` segments
    reverts to `PLANNED` with the offer fields cleared and every `ACTIVE` procedure booking
    of *any* of their segments moves to `CANCELLED` with a `cancel_reason_code` of
    `POSTURE_FROZEN`, decrementing each room's `reserved_minutes_total`."

    Design: Corner/errors/err_program_restricted_returns_409
    """
    env = _three_pair_participants()
    _three_segment_loop(env)
    validated = validate_chain(env, env["chain"]["id"])
    assert validated["status"] == "VALIDATED"
    assert validated["segment_count"] == 3
    review = create_outcome_review(env, cohort_size=25, observed_survivor_count=17)
    finalized = finalize_review(env, review["id"])

    response = api_client.commit_chain(env["chain"]["id"], env["coordinator_headers"])

    validate_error(
        response, ApiErrorId.ERR_PROGRAM_RESTRICTED.value, expected_status=409
    )

    assert finalized["oe_ratio"] == 0.85
    assert finalized["flag_level"] == "WATCH"
    assert finalized["requires_improvement_plan"] is False
    assert refresh_program(env)["compliance_posture"] == "RESTRICTED"

    chain = get_chain(env, env["chain"]["id"])
    assert chain["status"] == "VALIDATED", "RESTRICTED does not suspend"
    assert chain["segment_count"] == 3
    assert chain["committed_at"] is None
    assert chain["committed_donor_count"] == 0
    assert get_donor(env, env["donor_one"]["id"])["overall_status"] == "APPROVED"


def test_err_duplicate_center_code_returns_409():
    """PRD §3.1: "Registering one requires a display `name` and a `center_code`; the code
    must be unique across all programs, and a collision is reported as
    `ERR_DUPLICATE_CENTER_CODE`."
    PRD §2.10: "Uniqueness — `ERR_DUPLICATE_CENTER_CODE`, `ERR_DUPLICATE_NPI`,
    `ERR_DUPLICATE_ROOM_CODE`, `ERR_POSITION_TAKEN`, `ERR_DUPLICATE_OPEN_EVALUATION` or
    `ERR_DUPLICATE_REVIEW_PERIOD`, 409."

    Design: Corner/errors/err_duplicate_center_code_returns_409
    """
    program = create_program(name="Northlake Transplant Center", center_code="NLT-01")

    response = api_client.create_program(
        {
            "name": "Rival Transplant Center",
            "center_code": "NLT-01",
            "organ_type": "LIVER",
            "cooling_off_days": 3,
        },
        make_program_admin_headers(),
    )

    validate_error(
        response, ApiErrorId.ERR_DUPLICATE_CENTER_CODE.value, expected_status=409
    )

    reread = validate_success(
        api_client.get_program(program["id"], make_program_admin_headers())
    )
    assert reread["name"] == "Northlake Transplant Center"
    assert reread["center_code"] == "NLT-01"
    assert reread["organ_type"] == "KIDNEY", "the rival's LIVER never landed"


def test_err_duplicate_npi_returns_409():
    """PRD §3.1: "An `npi` must be unique within its program, and a repeat is
    `ERR_DUPLICATE_NPI`."
    PRD §3.1: "Adding a person to the center requires the owning `program_id`, a
    `full_name`, a `staff_role` drawn from the five credentialed duties, and an `npi`
    national provider identifier; `is_active` is optional and defaults to true."
    PRD §2.10: "Uniqueness — `ERR_DUPLICATE_CENTER_CODE`, `ERR_DUPLICATE_NPI`,
    `ERR_DUPLICATE_ROOM_CODE`, `ERR_POSITION_TAKEN`, `ERR_DUPLICATE_OPEN_EVALUATION` or
    `ERR_DUPLICATE_REVIEW_PERIOD`, 409."

    Design: Corner/errors/err_duplicate_npi_returns_409
    """
    program = create_program(name="Northlake Transplant Center", center_code="NLT-01")
    add_staff_member(
        program["id"], "TRANSPLANT_COORDINATOR", "1000000001", "Coordinator One"
    )

    response = api_client.create_staff_member(
        {
            "program_id": program["id"],
            "full_name": "Surgeon Nine",
            "staff_role": "SURGEON",
            "npi": "1000000001",
        },
        make_program_admin_headers(),
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_NPI.value, expected_status=409)

    surgeons, surgeon_meta = validate_paginated(
        api_client.list_program_staff_members(
            program["id"], make_program_admin_headers(), params={"staff_role": "SURGEON"}
        )
    )
    assert surgeons == []
    assert surgeon_meta["total_count"] == 0
    _rows, meta = validate_paginated(
        api_client.list_program_staff_members(
            program["id"], make_program_admin_headers()
        )
    )
    assert meta["total_count"] == 1, "only the coordinator holds that npi"


def test_err_duplicate_room_code_returns_409():
    """PRD §3.1: "Registering a theatre requires `program_id` and a `room_code` that is
    unique within the program — a repeat is `ERR_DUPLICATE_ROOM_CODE` — plus an optional
    `turnover_buffer_minutes` that defaults to 45 and may not be negative; the room's
    `reserved_minutes_total` starts at 0."
    PRD §2.10: "Uniqueness — `ERR_DUPLICATE_CENTER_CODE`, `ERR_DUPLICATE_NPI`,
    `ERR_DUPLICATE_ROOM_CODE`, `ERR_POSITION_TAKEN`, `ERR_DUPLICATE_OPEN_EVALUATION` or
    `ERR_DUPLICATE_REVIEW_PERIOD`, 409."

    Design: Corner/errors/err_duplicate_room_code_returns_409
    """
    env = setup_program_with_staff()
    room = add_operating_room(env, "OR-1")
    assert room["turnover_buffer_minutes"] == 45

    response = api_client.create_operating_room(
        {
            "program_id": env["program_id"],
            "room_code": "OR-1",
            "turnover_buffer_minutes": 30,
        },
        env["admin_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_DUPLICATE_ROOM_CODE.value, expected_status=409
    )

    rooms, meta = validate_paginated(
        api_client.list_program_operating_rooms(env["program_id"], env["admin_headers"])
    )
    assert meta["total_count"] == 1
    assert rooms[0]["turnover_buffer_minutes"] == 45, "the key is room_code alone"


def test_err_position_taken_returns_409():
    """PRD §3.5: "A chain may hold at most one non-withdrawn segment per position, and a
    second attempt at an occupied position is `ERR_POSITION_TAKEN`."
    PRD §2.10: "Uniqueness — `ERR_DUPLICATE_CENTER_CODE`, `ERR_DUPLICATE_NPI`,
    `ERR_DUPLICATE_ROOM_CODE`, `ERR_POSITION_TAKEN`, `ERR_DUPLICATE_OPEN_EVALUATION` or
    `ERR_DUPLICATE_REVIEW_PERIOD`, 409."
    PRD §3.5: "Each insertion supplies the `expected_chain_version` described in §2.7, a
    1-based `position` of at least 1, the `donor_candidate_id` giving in this segment, the
    `recipient_candidate_id` receiving in it, and an optional `predecessor_segment_id`
    naming the same chain's segment at the previous position — which must be null for the
    segment at position 1."

    Design: Corner/errors/err_position_taken_returns_409
    """
    env = setup_paired_loop_participants()
    chain = create_chain(env, "PAIRED_LOOP")
    add_segment(env, chain["id"], 1, env["donor_one"]["id"], env["recipient_two"]["id"])
    fresh_version = get_chain(env, chain["id"])["version"]

    response = api_client.create_chain_segment(
        chain["id"],
        {
            "expected_chain_version": fresh_version,
            "position": 1,
            "donor_candidate_id": env["donor_two"]["id"],
            "recipient_candidate_id": env["recipient_one"]["id"],
        },
        env["coordinator_headers"],
    )

    validate_error(response, ApiErrorId.ERR_POSITION_TAKEN.value, expected_status=409)

    assert get_chain(env, chain["id"])["segment_count"] == 1
    rows, meta = validate_paginated(
        api_client.list_chain_segments(
            env["coordinator_headers"], params={"exchange_chain_id": chain["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["donor_candidate_id"] == env["donor_one"]["id"]


def test_err_duplicate_open_evaluation_returns_409():
    """PRD §3.4: "And a donor may hold at most one evaluation per domain in `SUBMITTED`
    status, so a second open evaluation in the same domain is
    `ERR_DUPLICATE_OPEN_EVALUATION`."
    PRD §2.10: "Uniqueness — `ERR_DUPLICATE_CENTER_CODE`, `ERR_DUPLICATE_NPI`,
    `ERR_DUPLICATE_ROOM_CODE`, `ERR_POSITION_TAKEN`, `ERR_DUPLICATE_OPEN_EVALUATION` or
    `ERR_DUPLICATE_REVIEW_PERIOD`, 409."
    PRD §3.4: "A new evaluation row starts at `SUBMITTED` with `submission_count` 1 and
    `determined_at` null, and the first evaluation row ever created for a donor moves that
    donor's `overall_status` from `REFERRED` to `EVAL_IN_PROGRESS`."

    Design: Corner/errors/err_duplicate_open_evaluation_returns_409
    """
    env = setup_program_with_staff()
    donor = create_donor(env, mrn="D-001", age_years=41)
    first = submit_medical_evaluation(env, donor["id"])
    assert first["status"] == "SUBMITTED"

    response = api_client.create_donor_evaluation(
        create_medical_evaluation_payload(donor["id"]), env["reviewer_med_headers"]
    )

    validate_error(
        response, ApiErrorId.ERR_DUPLICATE_OPEN_EVALUATION.value, expected_status=409
    )

    _rows, meta = validate_paginated(
        api_client.list_donor_evaluations(
            env["coordinator_headers"], params={"donor_candidate_id": donor["id"]}
        )
    )
    assert meta["total_count"] == 1
    reread = validate_success(
        api_client.get_donor_evaluation(first["id"], env["reviewer_med_headers"])
    )
    assert reread["submission_count"] == 1


def test_err_duplicate_review_period_returns_409():
    """PRD §3.8: "A program may hold at most one `FINALIZED` review per identical
    `period_start_on` and `period_end_on` pair, and a second attempt is
    `ERR_DUPLICATE_REVIEW_PERIOD`."
    PRD §2.10: "Uniqueness — `ERR_DUPLICATE_CENTER_CODE`, `ERR_DUPLICATE_NPI`,
    `ERR_DUPLICATE_ROOM_CODE`, `ERR_POSITION_TAKEN`, `ERR_DUPLICATE_OPEN_EVALUATION` or
    `ERR_DUPLICATE_REVIEW_PERIOD`, 409."
    PRD §3.8: "On success `status` becomes `FINALIZED` — terminal — and `finalized_at` is
    stamped with the current logical clock."
    PRD §3.8: "Otherwise `oe_ratio` is `observed_survivor_count` divided by
    `expected_survivor_count`, rounded half up to **four** decimal places, and `flag_level`
    is `FLAGGED` when `oe_ratio` is strictly below 0.85, `WATCH` when it is strictly below
    0.95 but not below 0.85, and `NONE` otherwise."

    Design: Corner/errors/err_duplicate_review_period_returns_409
    """
    env = setup_program_with_staff()
    period = {"period_start_on": "2025-01-01", "period_end_on": "2025-12-31"}
    review_a = create_outcome_review(
        env, cohort_size=25, observed_survivor_count=20, **period
    )
    review_b = create_outcome_review(
        env, cohort_size=25, observed_survivor_count=20, **period
    )
    assert review_b["status"] == "DRAFT", "a second draft may exist for the same window"
    finalized_a = finalize_review(env, review_a["id"])

    response = api_client.finalize_outcome_review(review_b["id"], env["quality_headers"])

    validate_error(
        response, ApiErrorId.ERR_DUPLICATE_REVIEW_PERIOD.value, expected_status=409
    )

    reread_b = validate_success(
        api_client.get_outcome_review(review_b["id"], env["quality_headers"])
    )
    assert reread_b["status"] == "DRAFT"
    assert reread_b["finalized_at"] is None
    assert finalized_a["status"] == "FINALIZED"
    assert finalized_a["oe_ratio"] == 1.0
    assert finalized_a["flag_level"] == "NONE"
    assert refresh_program(env)["compliance_posture"] == "OPEN"


def test_err_staff_role_invalid_returns_422():
    """PRD §3.3: "The named staff member must exist, have `is_active` true, have
    `staff_role` equal to `LIVING_DONOR_ADVOCATE`, and belong to the same program as the
    donor; a wrong duty or an inactive person is `ERR_STAFF_ROLE_INVALID`."
    PRD §2.10: "Role-type fitness of a referenced staff member — `ERR_STAFF_ROLE_INVALID`,
    422."
    PRD §3.3: "A `ProgramAdmin` assigns the advocate by supplying an `advocate_staff_id`,
    moving `advocacy_status` from `UNASSIGNED` to `ASSIGNED` and recording the staff member
    on the donor."

    Design: Corner/errors/err_staff_role_invalid_returns_422
    """
    env = setup_program_with_staff()
    donor = create_donor(env, assign_advocate=False, mrn="D-001", age_years=41)

    response = api_client.assign_advocate(
        donor["id"],
        {"advocate_staff_id": env["coordinator"]["id"]},
        env["admin_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_STAFF_ROLE_INVALID.value, expected_status=422
    )

    after = get_donor(env, donor["id"])
    assert after["advocacy_status"] == "UNASSIGNED"
    assert after["advocate_staff_id"] is None


def test_err_advocate_conflict_of_interest_returns_422():
    """PRD §3.3: "When the donor has an `intended_recipient_id`, the proposed advocate must
    not already be the `advocate_staff_id` of a *different* donor candidate pointing at that
    same intended recipient, because one advocate cannot independently represent two donors
    competing for the same recipient; a violation is
    `ERR_ADVOCATE_CONFLICT_OF_INTEREST`."
    PRD §2.10: "Segregation of duties — `ERR_ADVOCATE_CONFLICT_OF_INTEREST` or
    `ERR_REVIEWER_SOD_CONFLICT`, 422."
    PRD §2.10: "Priority 11 guards two: advocate assignment and evaluation creation."

    Design: Corner/errors/err_advocate_conflict_of_interest_returns_422
    """
    env = setup_program_with_staff()
    recipient = create_recipient(env, mrn="R-001")
    donor_one = create_donor(
        env, intended_recipient_id=recipient["id"], mrn="D-001", age_years=41
    )
    assert donor_one["advocate_staff_id"] == env["advocate"]["id"]
    donor_two = create_donor(
        env,
        intended_recipient_id=recipient["id"],
        assign_advocate=False,
        mrn="D-002",
        age_years=38,
    )

    response = api_client.assign_advocate(
        donor_two["id"],
        {"advocate_staff_id": env["advocate"]["id"]},
        env["admin_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_ADVOCATE_CONFLICT_OF_INTEREST.value, expected_status=422
    )

    after_two = get_donor(env, donor_two["id"])
    assert after_two["advocacy_status"] == "UNASSIGNED"
    assert after_two["advocate_staff_id"] is None
    assert get_donor(env, donor_one["id"])["advocate_staff_id"] == env["advocate"]["id"]


def test_err_reviewer_sod_conflict_returns_422():
    """PRD §3.4: "The reviewer of a donor's psychosocial evaluation may not be the reviewer
    of that same donor's medical evaluation — a single person may not certify both halves of
    one donor's fitness — and a violation is `ERR_REVIEWER_SOD_CONFLICT`."
    PRD §2.10: "Segregation of duties — `ERR_ADVOCATE_CONFLICT_OF_INTEREST` or
    `ERR_REVIEWER_SOD_CONFLICT`, 422."
    PRD §3.4: "A new evaluation row starts at `SUBMITTED` with `submission_count` 1 and
    `determined_at` null, and the first evaluation row ever created for a donor moves that
    donor's `overall_status` from `REFERRED` to `EVAL_IN_PROGRESS`."
    PRD §3.4: "A `CLEARED` determination sets that donor dimension to `CLEARED`, copies
    the evaluation's `risk_points` into the donor's `medical_risk_points` or
    `psychosocial_risk_points` as the domain dictates, recomputes the donor's
    `screening_risk_index` and re-derives `overall_status`."

    Design: Corner/errors/err_reviewer_sod_conflict_returns_422
    """
    env = setup_program_with_staff()
    donor = create_donor(env, mrn="D-001", age_years=41)
    medical = submit_medical_evaluation(env, donor["id"])
    determine_evaluation(env, medical["id"], "CLEARED", env["reviewer_med_headers"])

    response = api_client.create_donor_evaluation(
        create_psychosocial_evaluation_payload(donor["id"]),
        env["reviewer_med_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_REVIEWER_SOD_CONFLICT.value, expected_status=422
    )

    _rows, meta = validate_paginated(
        api_client.list_donor_evaluations(
            env["coordinator_headers"], params={"donor_candidate_id": donor["id"]}
        )
    )
    assert meta["total_count"] == 1

    after = get_donor(env, donor["id"])
    assert after["psychosocial_status"] == "PENDING"
    assert after["overall_status"] == "EVAL_IN_PROGRESS"
