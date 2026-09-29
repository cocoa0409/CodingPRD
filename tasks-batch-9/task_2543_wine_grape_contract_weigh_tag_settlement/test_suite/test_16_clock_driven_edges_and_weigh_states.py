"""Two edges nobody calls — a pick call that runs out of answering time and a slot the
truck never came to — and the two-state weight line that refuses being driven backwards
or twice.
"""
from test_helpers import (
    LAB_TECH,
    SCALE_OPERATOR,
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
    create_grading_payload,
    create_lane,
    issue_pick_call,
    move_clock,
    offer_contract,
    read_appointment,
    read_contract,
    read_grower,
    read_pick_call,
    read_weigh_tag,
    record_sampling_visit,
    setup_reference_book,
    single_installment_plan,
    tare_payload,
    validate_error,
    validate_paginated,
)

CLOCK_PINNED_AT = "2026-08-01T00:00:00Z"
SAMPLING_WINDOW = ("2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z")

# Issued at the pinned instant with a 24 h answering window, so the deadline is midnight.
ACK_DEADLINE_AT = "2026-08-02T00:00:00Z"
ONE_SECOND_PAST_THE_DEADLINE = "2026-08-02T00:00:01Z"

TARGET_PICK_AT = "2026-08-06T14:00:00Z"
SLOT = ("2026-08-06T14:00:00Z", "2026-08-06T16:00:00Z")
ONE_SECOND_BEFORE_THE_SLOT_ENDS = "2026-08-06T15:59:59Z"

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
LANE = {
    "lane_code": "L1",
    "daily_capacity_tons": 80.000,
    "turnaround_buffer_minutes": 30,
    "max_load_tons": 40.0,
}
TONNAGE_TERMS = {
    "contract_basis": "TONNAGE",
    "base_price_per_ton_cents": 450000,
    "committed_tons": 40.000,
    "over_delivery_policy": "ACCEPT_AT_CONTRACT",
    "term_start_vintage": 2026,
    "term_end_vintage": 2026,
}


def _a_call_out_on_pick_ready_fruit(contract_code: str, target_pick_at: str) -> dict:
    """An ACTIVE contract whose block has a recorded PICK_READY visit, with one call issued
    at the pinned instant."""
    move_clock(CLOCK_PINNED_AT)
    ctx = setup_reference_book(
        grower_overrides=dict(PRODUCER),
        block_overrides=dict(BLOCK),
        spec_overrides={"spec_code": "CAB-STD-2026"},
    )
    ctx["crew"] = create_crew(crew_code="SC-1", region_code="NAPA-NORTH", max_concurrent_visits=2)
    contract = create_contract(
        ctx["grower"]["id"], ctx["spec"]["id"], contract_code=contract_code,
        installment_plan=single_installment_plan(), **TONNAGE_TERMS,
    )
    create_allocation(contract["id"], ctx["block"]["id"])
    offer_contract(contract["id"])
    ctx["contract"] = accept_contract(contract["id"], ctx["grower"]["id"])

    visit = book_sampling_visit(
        contract["id"], ctx["block"]["id"], ctx["crew"]["id"], SAMPLING_WINDOW[0], SAMPLING_WINDOW[1]
    )
    ctx["visit"] = record_sampling_visit(
        visit["id"], measured_brix=24.5, measured_ta_gl=6.5, measured_ph=3.45, measured_rot_pct=1.0
    )
    ctx["pick_call"] = issue_pick_call(
        contract["id"], ctx["block"]["id"], target_pick_at, 20.000
    )
    return ctx


# --- A call nobody answered in time -----------------------------------------------


def test_issuance_derives_the_answering_deadline_from_the_contracts_window():
    """The call opens live, with the deadline computed off the clock and the contract's
    24-hour answering window rather than off the pick date.

    PRD: "`ack_deadline_at` is `issued_at` plus the contract's `pick_call_ack_window_hours`
    hours. The call starts in status `ISSUED` with `revision_count` 0 and `acknowledged_at`
    null."

    Design: Corner/state_machines/pick_call_auto_expires_when_the_clock_passes_the_ack_deadline
    """
    ctx = _a_call_out_on_pick_ready_fruit("GC-EXPIRE", TARGET_PICK_AT)

    assert ctx["pick_call"]["status"] == "ISSUED"
    assert ctx["pick_call"]["issued_at"] == CLOCK_PINNED_AT
    assert ctx["pick_call"]["ack_deadline_at"] == ACK_DEADLINE_AT
    assert ctx["pick_call"]["acknowledged_at"] is None
    assert ctx["pick_call"]["revision_count"] == 0


def test_at_the_deadline_instant_exactly_the_call_is_still_live():
    """The expiry edge needs the clock strictly past the deadline, so arriving at the
    deadline itself changes nothing — the deliberately narrow gap where the call is still
    `ISSUED` and yet can no longer be answered.

    PRD: "Note the deliberately narrow gap this creates: automatic expiry needs the clock to
    be strictly *past* `ack_deadline_at`, so at the deadline instant exactly the call is still
    `ISSUED` and yet acknowledgement is already refused."

    Design: Corner/state_machines/pick_call_auto_expires_when_the_clock_passes_the_ack_deadline
    """
    ctx = _a_call_out_on_pick_ready_fruit("GC-EXPIRE", TARGET_PICK_AT)

    move_clock(ACK_DEADLINE_AT)
    assert read_pick_call(ctx["pick_call"]["id"])["status"] == "ISSUED"


def test_one_second_past_the_deadline_the_call_expires_on_its_own():
    """No client called anything; the clock moving is the whole trigger.

    PRD: "When the logical clock advances strictly past `ack_deadline_at` while the call is
    still `ISSUED`, it transitions `ISSUED → EXPIRED`, and that expiry counts against the
    producer: `expired_pick_call_count_vintage`, `prior_vintage_penalty_units` and both
    reliability scores are recomputed."

    Design: Corner/state_machines/pick_call_auto_expires_when_the_clock_passes_the_ack_deadline
    """
    ctx = _a_call_out_on_pick_ready_fruit("GC-EXPIRE", TARGET_PICK_AT)

    move_clock(ONE_SECOND_PAST_THE_DEADLINE)
    assert read_pick_call(ctx["pick_call"]["id"])["status"] == "EXPIRED"


def test_the_expiry_is_charged_to_the_expiry_counter_and_to_no_other():
    """Three misbehaviour counters exist and they are not interchangeable: only the
    expired-call one moves.

    PRD: "The counters are populated from weigh tags whose disposition is `REJECTED_QUALITY`
    or `REJECTED_OVER_CAP`, pick calls in `EXPIRED` and appointments in `NO_SHOW`, all reached
    through the producer's contracts and bucketed by each row's own `created_at` UTC calendar
    year"

    Design: Corner/state_machines/pick_call_auto_expires_when_the_clock_passes_the_ack_deadline
    """
    ctx = _a_call_out_on_pick_ready_fruit("GC-EXPIRE", TARGET_PICK_AT)
    move_clock(ONE_SECOND_PAST_THE_DEADLINE)

    grower = read_grower(ctx["grower"]["id"])
    assert grower["expired_pick_call_count_vintage"] == 1
    assert grower["rejected_load_count_vintage"] == 0
    assert grower["no_show_appointment_count_vintage"] == 0


def test_an_expired_call_costs_the_producer_five_reliability_points():
    """One expiry at five units apiece, and — because the penalty is all in the current
    vintage — both scores read the same figure.

    PRD: "A rejected load costs 8 units, an expired pick call costs 5 units, and a no-show
    appointment costs 3 units."

    Design: Corner/state_machines/pick_call_auto_expires_when_the_clock_passes_the_ack_deadline
    """
    ctx = _a_call_out_on_pick_ready_fruit("GC-EXPIRE", TARGET_PICK_AT)
    move_clock(ONE_SECOND_PAST_THE_DEADLINE)

    grower = read_grower(ctx["grower"]["id"])
    assert float(grower["reliability_score_vintage"]) == 95.0
    assert float(grower["reliability_score_lifetime"]) == 95.0


def test_the_expiry_leaves_the_contract_alone():
    """The call is what died; the agreement behind it is untouched and still open for
    tonnage.

    PRD: "`FULFILLED`, `EXPIRED` and `WITHDRAWN` are the three terminal statuses."

    Design: Corner/state_machines/pick_call_auto_expires_when_the_clock_passes_the_ack_deadline
    """
    ctx = _a_call_out_on_pick_ready_fruit("GC-EXPIRE", TARGET_PICK_AT)
    move_clock(ONE_SECOND_PAST_THE_DEADLINE)

    contract = read_contract(ctx["contract"]["id"])
    assert contract["lifecycle_status"] == "ACTIVE"
    assert contract["tonnage_status"] == "OPEN"


# --- A slot the truck never came to ------------------------------------------------


def _a_slot_reserved_and_never_used() -> dict:
    """The call is acknowledged and a two-hour slot is reserved on lane L1 for the target
    pick date. No weigh tag is ever presented against it."""
    ctx = _a_call_out_on_pick_ready_fruit("GC-NOSHOW", TARGET_PICK_AT)
    ctx["lane"] = create_lane(**LANE)
    ctx["pick_call"] = acknowledge_pick_call(ctx["pick_call"]["id"], ctx["grower"]["id"])
    ctx["appointment"] = book_appointment(
        ctx["pick_call"]["id"], ctx["lane"]["id"], SLOT[0], SLOT[1], 20.000
    )
    return ctx


def test_one_second_before_the_window_closes_the_slot_is_still_open():
    """The no-show edge waits for the window to actually end; a second short of that the
    reservation is still live and still expecting a truck.

    PRD: "A successful booking creates the appointment in status `SCHEDULED` and recomputes
    both the lane's `committed_tons` and `scheduled_appointment_count` and the pick call's
    `appointed_tons`."

    Design: Corner/state_machines/appointment_auto_no_show_when_the_window_ends_with_no_weigh_tag
    """
    ctx = _a_slot_reserved_and_never_used()

    move_clock(ONE_SECOND_BEFORE_THE_SLOT_ENDS)
    appointment = read_appointment(ctx["appointment"]["id"])
    assert appointment["status"] == "SCHEDULED"
    assert appointment["weigh_tag_count"] == 0


def test_at_the_window_end_exactly_the_slot_becomes_a_no_show():
    """Unlike the pick-call expiry, this edge fires inclusively — reaching `window_end` is
    enough, because the condition is that no tag was ever presented.

    PRD: "And if the logical clock advances to or past `window_end` while the appointment is
    still `SCHEDULED` with `weigh_tag_count` at 0, it transitions `SCHEDULED → NO_SHOW`"

    Design: Corner/state_machines/appointment_auto_no_show_when_the_window_ends_with_no_weigh_tag
    """
    ctx = _a_slot_reserved_and_never_used()

    move_clock(SLOT[1])
    assert read_appointment(ctx["appointment"]["id"])["status"] == "NO_SHOW"


def test_the_no_show_is_charged_to_its_own_counter_and_not_to_the_answered_call():
    """The call was answered in time, so nothing about it expired; only the slot misbehaved.

    PRD: "that recomputes the lane's two derived figures and the pick call's `appointed_tons`,
    and it counts against the producer, whose `no_show_appointment_count_vintage`,
    `prior_vintage_penalty_units` and both reliability scores are recomputed."

    Design: Corner/state_machines/appointment_auto_no_show_when_the_window_ends_with_no_weigh_tag
    """
    ctx = _a_slot_reserved_and_never_used()
    move_clock(SLOT[1])

    grower = read_grower(ctx["grower"]["id"])
    assert grower["no_show_appointment_count_vintage"] == 1
    assert grower["expired_pick_call_count_vintage"] == 0
    assert grower["rejected_load_count_vintage"] == 0


def test_a_no_show_costs_three_points_not_the_five_an_expiry_costs():
    """The unit weights are what keep the three counters distinct: this producer is on 97.0,
    not the 95.0 an expired call would have left.

    PRD: "The current-vintage penalty is 8 times `rejected_load_count_vintage`, plus 5 times
    `expired_pick_call_count_vintage`, plus 3 times `no_show_appointment_count_vintage`, where
    the vintage is the UTC calendar year of the logical clock."

    Design: Corner/state_machines/appointment_auto_no_show_when_the_window_ends_with_no_weigh_tag
    """
    ctx = _a_slot_reserved_and_never_used()
    move_clock(SLOT[1])

    grower = read_grower(ctx["grower"]["id"])
    assert float(grower["reliability_score_vintage"]) == 97.0
    assert float(grower["reliability_score_lifetime"]) == 97.0


def test_only_the_appointment_moved_and_the_call_stays_acknowledged():
    """The producer never lost the right to deliver against the call; one slot lapsed.

    PRD: "The producer whose identifier matches the contract's `grower_id` acknowledges the
    call, driving `ISSUED → ACKNOWLEDGED` and stamping `acknowledged_at` from the logical
    clock."

    Design: Corner/state_machines/appointment_auto_no_show_when_the_window_ends_with_no_weigh_tag
    """
    ctx = _a_slot_reserved_and_never_used()
    move_clock(SLOT[1])

    call = read_pick_call(ctx["pick_call"]["id"])
    assert call["status"] == "ACKNOWLEDGED"
    assert call["acknowledged_at"] == CLOCK_PINNED_AT


# --- The weight line runs one way, once -------------------------------------------


TRUCK_ARRIVES_AT = "2026-08-25T14:30:00Z"
WEIGH_STATE_TARGET_PICK_AT = "2026-08-25T14:00:00Z"
WEIGH_STATE_SLOT = ("2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z")
GROSS_LBS = 57000
TARE_LBS = 17000
SECOND_TARE_LBS = 16000


def _a_loaded_truck_weighed_in_but_not_out() -> dict:
    """One tag at gross 57000 lbs, captured inside the arrival window and not yet tared."""
    ctx = _a_call_out_on_pick_ready_fruit("GC-WEIGHSTATE", WEIGH_STATE_TARGET_PICK_AT)
    ctx["lane"] = create_lane(**LANE)
    ctx["pick_call"] = acknowledge_pick_call(ctx["pick_call"]["id"], ctx["grower"]["id"])
    ctx["appointment"] = book_appointment(
        ctx["pick_call"]["id"], ctx["lane"]["id"], WEIGH_STATE_SLOT[0], WEIGH_STATE_SLOT[1], 20.000
    )
    move_clock(TRUCK_ARRIVES_AT)
    ctx["tag"] = capture_gross(
        ctx["appointment"]["id"],
        ctx["block"]["id"],
        GROSS_LBS,
        appointment_version(ctx["appointment"]["id"]),
    )
    return ctx


def test_grading_a_load_that_has_not_been_weighed_out_is_refused(api):
    """There is no net weight to price yet, so the lab is turned away on the weight
    dimension — the concurrency guard it supplied was correct.

    PRD: "The tag's weight dimension must already be `NET_FINAL`, else
    `ERR_TAG_WEIGH_STATE_INVALID`; and its disposition must be either `PENDING` (a first
    grading) or `DISPUTED` (a re-grading after a dispute), any already-decided disposition
    being `ERR_TAG_NOT_DISPUTABLE`."

    Design: Corner/state_machines/taring_twice_and_grading_before_tare_are_rejected_409
    """
    ctx = _a_loaded_truck_weighed_in_but_not_out()

    validate_error(
        api.create_grading(
            ctx["tag"]["id"],
            create_grading_payload(
                int(ctx["tag"]["version"]), brix=23.0, ta_gl=6.5, ph=3.40, rot_pct=1.0, mog_pct=0.5
            ),
            LAB_TECH,
        ),
        ApiErrorId.ERR_TAG_WEIGH_STATE_INVALID.value,
        409,
    )


def test_the_refused_grading_wrote_no_lab_record(api):
    """A rejected create leaves the tag's grading history empty and its counter at zero.

    PRD: "A tag also carries `grade_count`, starting at 0, `active_adjustment_pct`, null until
    a grading exists"

    Design: Corner/state_machines/taring_twice_and_grading_before_tare_are_rejected_409
    """
    ctx = _a_loaded_truck_weighed_in_but_not_out()

    api.create_grading(
        ctx["tag"]["id"],
        create_grading_payload(int(ctx["tag"]["version"]), brix=23.0, rot_pct=1.0, mog_pct=0.5),
        LAB_TECH,
    )

    _, meta = validate_paginated(
        api.list_quality_grades(LAB_TECH, params={"weigh_tag_id": ctx["tag"]["id"]})
    )
    assert meta["total_count"] == 0
    assert read_weigh_tag(ctx["tag"]["id"])["grade_count"] == 0


def test_the_outbound_pass_completes_the_weight_line_exactly_once(api):
    """17000 lbs off 57000 leaves 40000 lbs, which is 20.000 tons at 2000 lbs per ton, and
    the dimension has reached its terminal state.

    PRD: "The conversion is then trivial and exact: `net_weight_lbs` is `gross_weight_lbs`
    less `tare_weight_lbs`, a whole number of pounds; and `net_tons` is `net_weight_lbs`
    divided by 2000 pounds per ton, rounded half up to 3 decimals."

    Design: Corner/state_machines/taring_twice_and_grading_before_tare_are_rejected_409
    """
    ctx = _a_loaded_truck_weighed_in_but_not_out()

    tared = capture_tare(ctx["tag"]["id"], TARE_LBS)
    assert tared["weigh_status"] == "NET_FINAL"
    assert tared["net_weight_lbs"] == 40000
    assert float(tared["net_tons"]) == 20.000


def test_a_second_tare_is_refused_rather_than_treated_as_a_correction(api):
    """The scale house does not get to reweigh a settled load; the second pass is a state
    error on the same dimension the first one completed.

    PRD: "It is permitted only while the tag is still `GROSS_CAPTURED`; a second tare attempt
    is `ERR_TAG_WEIGH_STATE_INVALID` with HTTP 409."

    Design: Corner/state_machines/taring_twice_and_grading_before_tare_are_rejected_409
    """
    ctx = _a_loaded_truck_weighed_in_but_not_out()
    capture_tare(ctx["tag"]["id"], TARE_LBS)

    validate_error(
        api.tare_weigh_tag(ctx["tag"]["id"], tare_payload(SECOND_TARE_LBS), SCALE_OPERATOR),
        ApiErrorId.ERR_TAG_WEIGH_STATE_INVALID.value,
        409,
    )


def test_the_refused_second_tare_did_not_leak_its_weight_in(api):
    """A 16000 lb tare would have shown 20.500 tons; the stored row still reports the tare
    and the tonnage the accepted pass produced, at the version that pass left behind.

    PRD: "`version`, an integer that starts at 1 on creation and increments by exactly 1 on
    every mutation of that row."

    Design: Corner/state_machines/taring_twice_and_grading_before_tare_are_rejected_409
    """
    ctx = _a_loaded_truck_weighed_in_but_not_out()
    tared = capture_tare(ctx["tag"]["id"], TARE_LBS)

    api.tare_weigh_tag(ctx["tag"]["id"], tare_payload(SECOND_TARE_LBS), SCALE_OPERATOR)

    tag = read_weigh_tag(ctx["tag"]["id"])
    assert tag["tare_weight_lbs"] == TARE_LBS
    assert float(tag["net_tons"]) == 20.000
    assert tag["version"] == tared["version"]


def test_the_weight_failures_never_touch_the_receipt_decision(api):
    """Two dimensions run in parallel on one tag: everything above happened on the weight
    line and the receipt decision is still waiting for a lab reading.

    PRD: "The tare also recomputes the appointment's `captured_net_tons`, and it leaves the
    receipt-decision dimension untouched at `PENDING`. `NET_FINAL` is the terminal state of
    the weight dimension."

    Design: Corner/state_machines/taring_twice_and_grading_before_tare_are_rejected_409
    """
    ctx = _a_loaded_truck_weighed_in_but_not_out()
    assert ctx["tag"]["disposition"] == "PENDING"

    api.create_grading(
        ctx["tag"]["id"], create_grading_payload(int(ctx["tag"]["version"])), LAB_TECH
    )
    assert read_weigh_tag(ctx["tag"]["id"])["disposition"] == "PENDING"

    capture_tare(ctx["tag"]["id"], TARE_LBS)
    api.tare_weigh_tag(ctx["tag"]["id"], tare_payload(SECOND_TARE_LBS), SCALE_OPERATOR)
    assert read_weigh_tag(ctx["tag"]["id"])["disposition"] == "PENDING"
