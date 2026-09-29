"""Two deadlines whose inclusive edges point in opposite directions. Acknowledgement must land
strictly before its instant while the acknowledgement-expiry needs the clock strictly past it,
which leaves a one-second window where a call is live and yet unacknowledgeable; and a dispute
may be filed at its deadline exactly, on a window that a re-grade never extends.
"""
from test_helpers import (
    ApiErrorId,
    accept_contract,
    acknowledge_pick_call,
    appointment_version,
    book_appointment,
    book_sampling_visit,
    capture_gross,
    capture_tare,
    create_allocation,
    create_contract,
    create_crew,
    create_lane,
    dispute_grading,
    issue_pick_call,
    make_grower_headers,
    move_clock,
    offer_contract,
    read_grower,
    read_pick_call,
    read_weigh_tag,
    record_grading,
    record_sampling_visit,
    setup_reference_book,
    single_installment_plan,
    validate_error,
)

SETUP_AT = "2026-08-20T08:00:00Z"
SAMPLING_WINDOW = ("2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z")

PRODUCER = {
    "name": "Ridgeline Vineyards",
    "license_number": "PL-44821",
    "region_code": "NAPA-NORTH",
}
BLOCK = {
    "block_code": "B-12",
    "varietal": "CABERNET_SAUVIGNON",
    "acres": 20.000,
    "expected_yield_tons_per_acre": 2.000,
    "ava_code": "NAPA-VALLEY",
}
SPEC = {
    "spec_code": "CAB-STD-2026",
    "min_brix_accept": 20.0,
    "brix_bonus_start": 24.0,
    "brix_penalty_start": 22.0,
    "rot_rejection_pct": 8.0,
    "min_brix_pick_call": 21.0,
}
RIPE_SAMPLE = {
    "measured_brix": 24.5,
    "measured_ta_gl": 6.5,
    "measured_ph": 3.40,
    "measured_rot_pct": 1.0,
}


def _an_active_contract_with_ripe_fruit(contract_code: str) -> dict:
    """An ACTIVE 80.000-ton contract whose only block has a COMPLETED PICK_READY visit, with the
    clock parked at the setup instant."""
    move_clock(SETUP_AT)
    ctx = setup_reference_book(
        grower_overrides=dict(PRODUCER),
        block_overrides=dict(BLOCK),
        spec_overrides=dict(SPEC),
    )
    ctx["crew"] = create_crew(crew_code="SC-1", region_code="NAPA-NORTH", max_concurrent_visits=2)

    contract = create_contract(
        ctx["grower"]["id"],
        ctx["spec"]["id"],
        contract_code=contract_code,
        contract_basis="TONNAGE",
        committed_tons=80.000,
        base_price_per_ton_cents=450000,
        over_delivery_policy="ACCEPT_AT_CONTRACT",
        term_start_vintage=2026,
        term_end_vintage=2027,
        installment_plan=single_installment_plan(),
    )
    create_allocation(contract["id"], ctx["block"]["id"])
    offer_contract(contract["id"])
    ctx["contract"] = accept_contract(contract["id"], ctx["grower"]["id"])

    visit = book_sampling_visit(
        contract["id"],
        ctx["block"]["id"],
        ctx["crew"]["id"],
        SAMPLING_WINDOW[0],
        SAMPLING_WINDOW[1],
    )
    record_sampling_visit(visit["id"], **RIPE_SAMPLE)
    return ctx


# --- The narrow gap the acknowledgement window leaves ---------------------------------


FIRST_TARGET_PICK_AT = "2026-08-25T14:00:00Z"
SECOND_TARGET_PICK_AT = "2026-08-26T14:00:00Z"
SHARED_ACK_DEADLINE_AT = "2026-08-21T08:00:00Z"
ONE_SECOND_BEFORE_THE_DEADLINE = "2026-08-21T07:59:59Z"
THE_DEADLINE_INSTANT = "2026-08-21T08:00:00Z"
ONE_SECOND_AFTER_THE_DEADLINE = "2026-08-21T08:00:01Z"

CALLED_TONS = 20.000
ONE_EXPIRED_CALL_SCORE = 95.0


def _two_calls_sharing_one_deadline() -> dict:
    """Two calls issued in the same instant, so their acknowledgement windows close together —
    one will be answered in time and one will not."""
    ctx = _an_active_contract_with_ripe_fruit("GC-ACKWIN")
    ctx["answered_call"] = issue_pick_call(
        ctx["contract"]["id"], ctx["block"]["id"], FIRST_TARGET_PICK_AT, CALLED_TONS
    )
    ctx["ignored_call"] = issue_pick_call(
        ctx["contract"]["id"], ctx["block"]["id"], SECOND_TARGET_PICK_AT, CALLED_TONS
    )
    assert ctx["answered_call"]["ack_deadline_at"] == SHARED_ACK_DEADLINE_AT
    assert ctx["ignored_call"]["ack_deadline_at"] == SHARED_ACK_DEADLINE_AT
    return ctx


def test_one_second_before_the_deadline_the_acknowledgement_still_lands():
    """The window is open right up to its final second, so the producer who answers late but in
    time is admitted.

    PRD: "Acknowledgement requires that the logical clock be **strictly before**
    `ack_deadline_at`; at or after that instant it is refused with `ERR_ACK_WINDOW_CLOSED` and
    HTTP 409."

    Design: Corner/validations/acknowledging_exactly_at_the_ack_deadline_is_refused_409
    """
    ctx = _two_calls_sharing_one_deadline()

    move_clock(ONE_SECOND_BEFORE_THE_DEADLINE)
    answered = acknowledge_pick_call(ctx["answered_call"]["id"], ctx["grower"]["id"])
    assert answered["status"] == "ACKNOWLEDGED"
    assert answered["acknowledged_at"] == ONE_SECOND_BEFORE_THE_DEADLINE


def test_at_the_deadline_instant_the_unanswered_call_has_not_expired():
    """Moving the clock onto the deadline does not expire the call, because expiry wants the
    clock strictly past it — the call is still live.

    PRD: "Note the deliberately narrow gap this creates: automatic expiry needs the clock to be
    strictly *past* `ack_deadline_at`, so at the deadline instant exactly the call is still
    `ISSUED` and yet acknowledgement is already refused."

    Design: Corner/validations/acknowledging_exactly_at_the_ack_deadline_is_refused_409
    """
    ctx = _two_calls_sharing_one_deadline()
    move_clock(ONE_SECOND_BEFORE_THE_DEADLINE)
    acknowledge_pick_call(ctx["answered_call"]["id"], ctx["grower"]["id"])

    move_clock(THE_DEADLINE_INSTANT)
    assert read_pick_call(ctx["ignored_call"]["id"])["status"] == "ISSUED"


def test_acknowledging_at_the_deadline_instant_exactly_is_refused(api):
    """The live call cannot be acknowledged: the refusal is the temporal one and not a state
    complaint, because the call has not left the issued state.

    PRD: "Ranks 35 through 40 are the temporal envelopes: (35) the appointment window sits inside
    the pick call's delivery envelope, else `ERR_APPOINTMENT_OUTSIDE_PICK_WINDOW` with HTTP 422;
    (36) the truck presents inside the arrival envelope, else `ERR_OUTSIDE_APPOINTMENT_WINDOW`
    with HTTP 409; (37) sufficient pick notice, else `ERR_INSUFFICIENT_PICK_NOTICE` with HTTP
    422; (38) the acknowledgement window is still open, else `ERR_ACK_WINDOW_CLOSED` with HTTP
    409."

    Design: Corner/validations/acknowledging_exactly_at_the_ack_deadline_is_refused_409
    """
    ctx = _two_calls_sharing_one_deadline()
    move_clock(THE_DEADLINE_INSTANT)

    validate_error(
        api.acknowledge_pick_call(
            ctx["ignored_call"]["id"], make_grower_headers(ctx["grower"]["id"])
        ),
        ApiErrorId.ERR_ACK_WINDOW_CLOSED.value,
        409,
    )


def test_one_second_later_the_state_guard_answers_instead(api):
    """A second past the deadline the call has expired of its own accord, and the higher-ranked
    state question now decides the same request.

    PRD: "When the logical clock advances strictly past `ack_deadline_at` while the call is still
    `ISSUED`, it transitions `ISSUED → EXPIRED`, and that expiry counts against the producer:
    `expired_pick_call_count_vintage`, `prior_vintage_penalty_units` and both reliability scores
    are recomputed."

    Design: Corner/validations/acknowledging_exactly_at_the_ack_deadline_is_refused_409
    """
    ctx = _two_calls_sharing_one_deadline()
    move_clock(ONE_SECOND_AFTER_THE_DEADLINE)

    validate_error(
        api.acknowledge_pick_call(
            ctx["ignored_call"]["id"], make_grower_headers(ctx["grower"]["id"])
        ),
        ApiErrorId.ERR_PICK_CALL_STATE_INVALID.value,
        409,
    )
    assert read_pick_call(ctx["ignored_call"]["id"])["status"] == "EXPIRED"


def test_the_expiry_cost_five_units_and_left_the_answered_call_alone():
    """One unanswered call is five reliability units, and the call that was acknowledged in time
    is untouched by its sibling's fate.

    PRD: "Three kinds of misbehaviour carry weights. A rejected load costs 8 units, an expired
    pick call costs 5 units, and a no-show appointment costs 3 units."

    Design: Corner/validations/acknowledging_exactly_at_the_ack_deadline_is_refused_409
    """
    ctx = _two_calls_sharing_one_deadline()
    move_clock(ONE_SECOND_BEFORE_THE_DEADLINE)
    acknowledge_pick_call(ctx["answered_call"]["id"], ctx["grower"]["id"])

    move_clock(ONE_SECOND_AFTER_THE_DEADLINE)
    grower = read_grower(ctx["grower"]["id"])
    assert grower["expired_pick_call_count_vintage"] == 1
    assert float(grower["reliability_score_vintage"]) == ONE_EXPIRED_CALL_SCORE
    assert read_pick_call(ctx["answered_call"]["id"])["status"] == "ACKNOWLEDGED"


# --- Seventy-two hours from the first grading, and only from the first ------------------


TARGET_PICK_AT = "2026-08-25T14:00:00Z"
SLOT = ("2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z")
SLOT_TONS = 40.000
ESTIMATED_TONS = 45.000  # more than the two loads together, so nothing reaches FULFILLED

FIRST_GRADED_AT = "2026-08-25T15:00:00Z"
DISPUTE_DEADLINE_AT = "2026-08-28T15:00:00Z"
WELL_INSIDE_THE_WINDOW = "2026-08-26T10:00:00Z"
ONE_SECOND_PAST_THE_DISPUTE_DEADLINE = "2026-08-28T15:00:01Z"

FIRST_GROSS_LBS = 57000
FIRST_TARE_LBS = 17000
SECOND_GROSS_LBS = 61240
SECOND_TARE_LBS = 17240

CLEAN_READING = {"brix": 23.0, "ta_gl": 6.5, "ph": 3.40, "rot_pct": 1.0, "mog_pct": 0.5}

LANE = {
    "lane_code": "L1",
    "daily_capacity_tons": 80.000,
    "turnaround_buffer_minutes": 30,
    "max_load_tons": 40.000,
}


def _two_loads_graded_in_the_same_instant() -> dict:
    """Two trucks against one slot, both tared and both graded clean at the same instant, so the
    dispute window of each is anchored to that instant."""
    ctx = _an_active_contract_with_ripe_fruit("GC-DISPUTE-WIN")
    ctx["lane"] = create_lane(**LANE)

    call = issue_pick_call(
        ctx["contract"]["id"], ctx["block"]["id"], TARGET_PICK_AT, ESTIMATED_TONS
    )
    acknowledge_pick_call(call["id"], ctx["grower"]["id"])
    appointment = book_appointment(call["id"], ctx["lane"]["id"], SLOT[0], SLOT[1], SLOT_TONS)

    move_clock(FIRST_GRADED_AT)
    first = capture_gross(
        appointment["id"],
        ctx["block"]["id"],
        FIRST_GROSS_LBS,
        appointment_version(appointment["id"]),
    )
    second = capture_gross(
        appointment["id"],
        ctx["block"]["id"],
        SECOND_GROSS_LBS,
        appointment_version(appointment["id"]),
    )
    capture_tare(first["id"], FIRST_TARE_LBS)
    capture_tare(second["id"], SECOND_TARE_LBS)
    record_grading(first["id"], **CLEAN_READING)
    record_grading(second["id"], **CLEAN_READING)

    ctx["tag_a"] = first
    ctx["tag_b"] = second
    return ctx


def test_both_loads_take_their_window_from_the_grading_instant():
    """The window is 72 hours wide and anchored on the grading, not on the arrival or the tare,
    so two loads graded together share one deadline.

    PRD: "`dispute_deadline_at` is stamped only when it is still null, at the first grading
    instant plus 72 hours, and a re-grade never re-stamps it."

    Design: Corner/validations/dispute_window_is_seventy_two_hours_from_the_first_grading_only
    """
    ctx = _two_loads_graded_in_the_same_instant()

    assert read_weigh_tag(ctx["tag_a"]["id"])["dispute_deadline_at"] == DISPUTE_DEADLINE_AT
    assert read_weigh_tag(ctx["tag_b"]["id"])["dispute_deadline_at"] == DISPUTE_DEADLINE_AT


def test_a_dispute_inside_the_window_returns_the_load_to_the_lab():
    """Filed a day into the window, the dispute is admitted and the load's receipt decision goes
    back to being undecided.

    PRD: "The tag's `contract_slice_tons`, `over_slice_tons`, `over_rejected_tons` and
    `excess_rejected_tons` all reset to 0.000, `active_adjustment_pct` is cleared, and the
    disposition moves to `DISPUTED`, where it waits for a re-grade."

    Design: Corner/validations/dispute_window_is_seventy_two_hours_from_the_first_grading_only
    """
    ctx = _two_loads_graded_in_the_same_instant()

    move_clock(WELL_INSIDE_THE_WINDOW)
    disputed = dispute_grading(
        ctx["tag_b"]["id"], ctx["grower"]["id"], reason="Rot call disputed by the ranch"
    )
    assert disputed["disposition"] == "DISPUTED"
    assert float(disputed["contract_slice_tons"]) == 0.000


def test_the_re_grade_decides_the_load_again_and_counts_as_a_second_reading():
    """The re-grade runs the whole pipeline afresh, and the readings that accepted the load the
    first time accept it again — with both gradings counted.

    PRD: "The re-grade increments `grade_count` again and stamps `superseded_at` on the grading
    the dispute already superseded only if it has not been stamped — in practice the dispute has
    already stamped it, and the newly written grading becomes the sole row with a null
    `superseded_at`."

    Design: Corner/validations/dispute_window_is_seventy_two_hours_from_the_first_grading_only
    """
    ctx = _two_loads_graded_in_the_same_instant()
    move_clock(WELL_INSIDE_THE_WINDOW)
    dispute_grading(ctx["tag_b"]["id"], ctx["grower"]["id"])

    record_grading(ctx["tag_b"]["id"], **CLEAN_READING)
    tag = read_weigh_tag(ctx["tag_b"]["id"])
    assert tag["disposition"] == "ACCEPTED"
    assert tag["grade_count"] == 2


def test_the_dispute_and_re_grade_cycle_bought_no_extra_window():
    """This is the whole point of stamping the deadline only once: a producer cannot walk the
    window forward by disputing and being re-graded.

    PRD: "The logical clock must be at or before the tag's `dispute_deadline_at`, later attempts
    being `ERR_DISPUTE_WINDOW_CLOSED` with HTTP 409 — and since that deadline was stamped at the
    *first* grading and is never extended by a re-grade, a load that has been graded twice still
    has only the original window."

    Design: Corner/validations/dispute_window_is_seventy_two_hours_from_the_first_grading_only
    """
    ctx = _two_loads_graded_in_the_same_instant()
    move_clock(WELL_INSIDE_THE_WINDOW)
    dispute_grading(ctx["tag_b"]["id"], ctx["grower"]["id"])
    record_grading(ctx["tag_b"]["id"], **CLEAN_READING)

    assert read_weigh_tag(ctx["tag_b"]["id"])["dispute_deadline_at"] == DISPUTE_DEADLINE_AT


def test_a_dispute_filed_on_the_deadline_instant_exactly_is_admitted():
    """The boundary is inclusive on this side: at the deadline itself the producer may still
    contest the load.

    PRD: "A producer who believes the lab got it wrong has 72 hours from the first grading of the
    load to say so."

    Design: Corner/validations/dispute_window_is_seventy_two_hours_from_the_first_grading_only
    """
    ctx = _two_loads_graded_in_the_same_instant()

    move_clock(DISPUTE_DEADLINE_AT)
    disputed = dispute_grading(
        ctx["tag_a"]["id"], ctx["grower"]["id"], reason="Filed on the last legal instant"
    )
    assert disputed["disposition"] == "DISPUTED"


def test_one_second_later_the_window_has_closed(api):
    """The other load is in an entirely disputable state, so only the clock can be the reason it
    is refused.

    PRD: "The tag's disposition must be `ACCEPTED`, `PARTIALLY_ACCEPTED` or `REJECTED_QUALITY`; a
    tag that is still `PENDING`, that was refused as `REJECTED_OVER_CAP`, or that is already
    `DISPUTED` cannot be contested and yields `ERR_TAG_NOT_DISPUTABLE` with HTTP 409."

    Design: Corner/validations/dispute_window_is_seventy_two_hours_from_the_first_grading_only
    """
    ctx = _two_loads_graded_in_the_same_instant()
    assert read_weigh_tag(ctx["tag_b"]["id"])["disposition"] == "ACCEPTED"

    move_clock(ONE_SECOND_PAST_THE_DISPUTE_DEADLINE)
    validate_error(
        api.create_grade_dispute(
            ctx["tag_b"]["id"],
            make_grower_headers(ctx["grower"]["id"]),
            {"reason": "One second too late"},
        ),
        ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED.value,
        409,
    )
