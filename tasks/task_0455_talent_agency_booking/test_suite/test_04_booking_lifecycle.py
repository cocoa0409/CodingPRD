"""Booking confirm/complete lifecycle and its cross-entity gates.

Covers the parallel booking_status x payment_status dimensions, the confirm
gates (deal accepted, talent rostered), the temporal completion gate, the
auto-fill of the casting call, and the talent-version bump on confirm.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    create_payment_payload,
    confirm_payload,
    setup_pending_booking,
    setup_confirmed_booking,
    talent_version,
    set_clock,
)

AGENT = TEST_USERS["agent_headers"]


# ─── non_linear_state_machine: parallel dimensions independent ───────────────
def test_complete_advances_booking_status_while_payment_status_stays_unpaid(api):
    """PRD §3.6: "A new booking is created in `booking_status` `PENDING` and
    `payment_status` `UNPAID` — two independent dimensions that evolve
    separately."
    PRD §3.6: "A confirmed booking is completed by an agent, moving
    `CONFIRMED → COMPLETED`, but only once the logical clock has reached or
    passed the booking's `end_date`"

    Design: Difficulty/non_linear_state_machine/booking_parallel_dimensions_independent
    """
    base = setup_confirmed_booking(union_status="SAG", media_type="CABLE")
    booking_id = base["booking"]["id"]
    assert base["booking"]["booking_status"] == "CONFIRMED"
    assert base["booking"]["payment_status"] == "UNPAID"

    set_clock("2026-03-20T00:00:00Z")
    completed = validate_success(api.complete_booking(booking_id, AGENT), 200)
    assert completed["booking_status"] == "COMPLETED"
    assert completed["payment_status"] == "UNPAID"


def test_pending_booking_starts_unpaid_and_pending(api):
    """PRD §3.6: "A new booking is created in `booking_status` `PENDING` and
    `payment_status` `UNPAID` — two independent dimensions that evolve
    separately."

    Design: Difficulty/non_linear_state_machine/booking_parallel_dimensions_independent
    """
    base = setup_pending_booking(union_status="SAG", media_type="CABLE")
    assert base["booking"]["booking_status"] == "PENDING"
    assert base["booking"]["payment_status"] == "UNPAID"


# ─── cross_entity_state_dependency: confirm requires deal accepted ───────────
def test_confirm_booking_requires_deal_memo_accepted(api):
    """PRD §3.6: "Confirming a pending booking ... is permitted only when three
    cross-entity gates all hold: the booking's deal memo is in `ACCEPTED`
    (otherwise `ERR_DEAL_NOT_ACCEPTED`)"

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_deal_accepted
    """
    # Build a PENDING booking but leave the deal memo OFFERED (not accepted).
    # setup_pending_booking accepts the deal; instead build the chain with the
    # deal left OFFERED by using a custom setup.
    from test_helpers import (
        setup_rostered_talent, make_casting_director_headers, make_talent_headers,
        create_casting_call, create_submission, create_availability_hold,
        create_deal_memo_payload, offer_payload, create_booking_payload,
        schedule_audition_slot,
    )
    base = setup_rostered_talent(union_status="SAG")
    cd_id, talent_id, cc_id = base["cd"]["id"], base["talent"]["id"], base["comp_card"]["id"]
    cd_headers = make_casting_director_headers(cd_id)
    call = create_casting_call(cd_id, media_type="STREAMING")
    submission = create_submission(call["id"], talent_id, cc_id)
    # Advance submission to AUDITION_SCHEDULED so the deal memo open moves it to
    # OFFER_EXTENDED, making the first offer permitted (PRD §3.5).
    schedule_audition_slot(cd_id, submission["id"])
    dm = get_success_data(
        api.create_deal_memo(
            create_deal_memo_payload(call["id"], talent_id, submission["id"]),
            cd_headers,
        )
    )
    # Offer but do NOT accept -> deal stays OFFERED.
    get_success_data(
        api.offer_deal_memo(dm["id"], offer_payload(200000, 12), cd_headers)
    )
    hold = create_availability_hold(talent_id)
    tv = talent_version(talent_id)
    booking = get_success_data(
        api.create_booking(
            create_booking_payload(dm["id"], talent_id, call["id"], hold["id"], tv),
            AGENT,
        )
    )
    resp = api.confirm_booking(booking["id"], confirm_payload(tv), AGENT)
    validate_error(resp, ApiErrorId.ERR_DEAL_NOT_ACCEPTED.value, 409)


def test_confirm_booking_with_rejected_deal_rejected(api):
    """PRD §3.6: "Confirming a pending booking ... is permitted only when three
    cross-entity gates all hold: the booking's deal memo is in `ACCEPTED`
    (otherwise `ERR_DEAL_NOT_ACCEPTED`)"

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_deal_accepted
    """
    # Build a PENDING booking, then reject the deal so it is in REJECTED (not ACCEPTED).
    from test_helpers import (
        setup_rostered_talent, make_casting_director_headers, make_talent_headers,
        create_casting_call, create_submission, create_availability_hold,
        create_deal_memo_payload, offer_payload, create_booking_payload,
        schedule_audition_slot,
    )
    base = setup_rostered_talent(union_status="SAG")
    cd_id, talent_id, cc_id = base["cd"]["id"], base["talent"]["id"], base["comp_card"]["id"]
    cd_headers = make_casting_director_headers(cd_id)
    talent_headers = make_talent_headers(talent_id)
    call = create_casting_call(cd_id, media_type="STREAMING")
    submission = create_submission(call["id"], talent_id, cc_id)
    # Advance submission to AUDITION_SCHEDULED so the deal memo open moves it to
    # OFFER_EXTENDED, making the first offer permitted (PRD §3.5).
    schedule_audition_slot(cd_id, submission["id"])
    dm = get_success_data(
        api.create_deal_memo(
            create_deal_memo_payload(call["id"], talent_id, submission["id"]),
            cd_headers,
        )
    )
    get_success_data(api.offer_deal_memo(dm["id"], offer_payload(200000, 12), cd_headers))
    hold = create_availability_hold(talent_id)
    tv = talent_version(talent_id)
    booking = get_success_data(
        api.create_booking(
            create_booking_payload(dm["id"], talent_id, call["id"], hold["id"], tv),
            AGENT,
        )
    )
    # Reject the standing OFFERED terms (talent faces them) -> deal REJECTED.
    get_success_data(api.reject_deal_memo(dm["id"], talent_headers))
    resp = api.confirm_booking(booking["id"], confirm_payload(tv), AGENT)
    validate_error(resp, ApiErrorId.ERR_DEAL_NOT_ACCEPTED.value, 409)


# ─── cross_entity_state_dependency: payment requires booking completed ───────
def test_payment_on_non_completed_booking_rejected(api):
    """PRD §3.8: "A payment is permitted only when the booking is in `COMPLETED`;
    against a booking that has not completed, the post is refused with
    `ERR_BOOKING_NOT_COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/payment_requires_booking_completed
    """
    base = setup_confirmed_booking(union_status="SAG", media_type="STREAMING")
    resp = api.create_payment(
        create_payment_payload(base["booking"]["id"], base["talent"]["id"], 1000000),
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_COMPLETED.value, 409)


def test_payment_on_completed_booking_succeeds(api):
    """PRD §3.8: "A payment is permitted only when the booking is in `COMPLETED`;
    against a booking that has not completed, the post is refused with
    `ERR_BOOKING_NOT_COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/payment_requires_booking_completed
    """
    # The positive boundary: once the booking IS COMPLETED, the payment posts.
    base = setup_confirmed_booking(union_status="SAG", media_type="STREAMING")
    set_clock("2026-03-20T00:00:00Z")
    validate_success(api.complete_booking(base["booking"]["id"], AGENT), 200)
    resp = api.create_payment(
        create_payment_payload(base["booking"]["id"], base["talent"]["id"], 1000000),
        AGENT,
    )
    payment = validate_success(resp, 201)
    assert payment["status"] == "POSTED"


# ─── validations: confirm requires rostered talent ──────────────────────────
def test_confirm_booking_requires_rostered_talent(api):
    """PRD §3.6: "the talent is `ROSTERED` (otherwise `ERR_TALENT_NOT_ROSTERED`)."

    Design: Corner/validations/confirm_requires_rostered_talent
    """
    base = setup_pending_booking(union_status="SAG", media_type="STREAMING")
    talent_id = base["talent"]["id"]
    booking_id = base["booking"]["id"]
    # Suspend the talent after the booking was created.
    get_success_data(api.suspend_talent(talent_id, AGENT))
    tv = talent_version(talent_id)
    resp = api.confirm_booking(booking_id, confirm_payload(tv), AGENT)
    validate_error(resp, ApiErrorId.ERR_TALENT_NOT_ROSTERED.value, 409)


# ─── validations: complete before end date rejected ─────────────────────────
def test_complete_booking_before_end_date_rejected(api):
    """PRD §3.6: "A confirmed booking is completed by an agent, moving
    `CONFIRMED → COMPLETED`, but only once the logical clock has reached or
    passed the booking's `end_date`; an early completion is refused with
    `ERR_BOOKING_NOT_ENDED`."

    Design: Corner/validations/booking_complete_before_end_date_rejected
    """
    base = setup_confirmed_booking(union_status="SAG", media_type="STREAMING")
    # Booking ends 2026-03-19; move clock to before that.
    set_clock("2026-03-18T00:00:00Z")
    resp = api.complete_booking(base["booking"]["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_ENDED.value, 409)


# ─── state_machines: casting call fills on booking confirm ───────────────────
def test_confirm_booking_auto_fills_casting_call(api):
    """PRD §3.2: "Independently, a call moves from `OPEN` to the terminal
    `FILLED` state automatically when a booking that references it via
    `casting_call_id` reaches `CONFIRMED`."

    Design: Corner/state_machines/casting_call_fills_on_booking_confirm
    """
    base = setup_confirmed_booking(union_status="SAG", media_type="STREAMING")
    call = validate_success(api.get_casting_call(base["call"]["id"], AGENT), 200)
    assert call["status"] == "FILLED"
    # gross_fee = 200000/day * 5 inclusive days.
    assert base["booking"]["gross_fee_cents"] == 1000000


# ─── cross_cutting: confirm bumps talent version ─────────────────────────────
def test_confirm_booking_bumps_talent_version_and_booked_days(api):
    """PRD §3.6: "The confirm also bumps `Talent.version` (this is the version
    movement that the create-booking OCC check in §2.8 guards against)."
    PRD §2.5: "These counters are reconciled upward on confirm and downward on
    cancel"

    Design: Corner/cross_cutting_complexity_layers/confirm_booking_bumps_talent_version
    """
    base = setup_pending_booking(union_status="SAG", media_type="STREAMING")
    talent_id = base["talent"]["id"]
    booking_id = base["booking"]["id"]
    tv_before = talent_version(talent_id)
    validate_success(
        api.confirm_booking(booking_id, confirm_payload(tv_before), AGENT), 200
    )
    talent = validate_success(api.get_talent(talent_id, AGENT), 200)
    assert talent["version"] > tv_before
    assert talent["booked_day_count"] == 5
