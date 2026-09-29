"""The receipt-decision dimension guards both directions — nothing decided cannot be
contested, and something decided cannot be re-read — and the vintage close refuses to run
while a single load on the pad is still unfinished.
"""
from test_helpers import (
    CLERK,
    LAB_TECH,
    MANAGER,
    ApiErrorId,
    accept_contract,
    acknowledge_pick_call,
    appointment_version,
    book_appointment,
    book_sampling_visit,
    capture_gross,
    capture_tare,
    close_settlement,
    create_allocation,
    create_contract,
    create_crew,
    create_grading_payload,
    create_lane,
    dispute_grading,
    issue_pick_call,
    list_installments,
    list_settlement_lines,
    make_grower_headers,
    move_clock,
    offer_contract,
    read_contract,
    read_pick_call,
    read_weigh_tag,
    record_grading,
    record_sampling_visit,
    setup_reference_book,
    single_installment_plan,
    validate_error,
    validate_paginated,
    validate_success,
    weigh_tag_version,
)

SETUP_AT = "2026-08-20T08:00:00Z"
SAMPLING_WINDOW = ("2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z")
TARGET_PICK_AT = "2026-08-25T14:00:00Z"
SLOT = ("2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z")
TRUCK_ARRIVES_AT = "2026-08-25T14:30:00Z"
CLOSED_AT = "2026-08-28T09:00:00Z"
FIRST_DUE_AT = "2026-09-27T09:00:00Z"

GROSS_LBS = 57000
TARE_LBS = 17000
LOAD_TONS = 20.000

# Brix 23.0 sits between the specification's penalty start (22.0) and bonus start (24.0),
# with acid, rot and MOG all inside their allowances, so every component is 0.0.
CLEAN_READING = {"brix": 23.0, "ta_gl": 6.5, "ph": 3.40, "rot_pct": 1.0, "mog_pct": 0.5}
SECOND_OPINION = {"brix": 26.0, "ta_gl": 6.5, "ph": 3.40, "rot_pct": 1.0, "mog_pct": 0.5}

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


def _a_truck_weighed_in_on_an_active_vintage(contract_code: str) -> dict:
    """An ACTIVE TONNAGE contract with one acknowledged call, one reserved slot and one
    load whose inbound pass is captured at 57000 lbs and not yet tared."""
    move_clock(SETUP_AT)
    ctx = setup_reference_book(
        grower_overrides=dict(PRODUCER),
        block_overrides=dict(BLOCK),
        spec_overrides={"spec_code": "CAB-STD-2026"},
    )
    ctx["lane"] = create_lane(**LANE)
    ctx["crew"] = create_crew(crew_code="SC-1", region_code="NAPA-NORTH", max_concurrent_visits=2)

    contract = create_contract(
        ctx["grower"]["id"],
        ctx["spec"]["id"],
        contract_code=contract_code,
        installment_plan=single_installment_plan(),
        **TONNAGE_TERMS,
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
    call = issue_pick_call(contract["id"], ctx["block"]["id"], TARGET_PICK_AT, LOAD_TONS)
    ctx["pick_call"] = acknowledge_pick_call(call["id"], ctx["grower"]["id"])
    ctx["appointment"] = book_appointment(
        call["id"], ctx["lane"]["id"], SLOT[0], SLOT[1], LOAD_TONS
    )

    move_clock(TRUCK_ARRIVES_AT)
    ctx["tag"] = capture_gross(
        ctx["appointment"]["id"],
        ctx["block"]["id"],
        GROSS_LBS,
        appointment_version(ctx["appointment"]["id"]),
    )
    return ctx


def _a_finished_load_waiting_for_the_lab(contract_code: str) -> dict:
    """The same load taken to NET_FINAL — 40000 lbs, 20.000 tons — with its receipt
    decision still PENDING."""
    ctx = _a_truck_weighed_in_on_an_active_vintage(contract_code)
    ctx["tag"] = capture_tare(ctx["tag"]["id"], TARE_LBS)
    return ctx


# --- Nothing decided cannot be contested; something decided cannot be re-read ------


def test_disputing_a_load_the_lab_has_not_looked_at_is_refused(api):
    """The producer objects before any reading exists, and there is no decision on the
    record to object to.

    PRD: "The tag's disposition must be `ACCEPTED`, `PARTIALLY_ACCEPTED` or
    `REJECTED_QUALITY`; a tag that is still `PENDING`, that was refused as
    `REJECTED_OVER_CAP`, or that is already `DISPUTED` cannot be contested and yields
    `ERR_TAG_NOT_DISPUTABLE` with HTTP 409."

    Design: Corner/state_machines/disputing_a_pending_tag_and_regrading_a_decided_tag_are_rejected_409
    """
    ctx = _a_finished_load_waiting_for_the_lab("GC-DISPOSITION")
    assert ctx["tag"]["disposition"] == "PENDING"

    validate_error(
        api.create_grade_dispute(
            ctx["tag"]["id"],
            make_grower_headers(ctx["grower"]["id"]),
            {"reason": "premature dispute, nothing graded yet"},
        ),
        ApiErrorId.ERR_TAG_NOT_DISPUTABLE.value,
        409,
    )


def test_the_first_reading_decides_the_load_and_takes_all_of_it(api):
    """Brix 23.0 sits in the dead band, so no component moves the price and the whole
    20.000 tons fits inside the 40.000-ton soft cap.

    PRD: "Otherwise the whole load was taken and the tag moves `PENDING → ACCEPTED`."

    Design: Corner/state_machines/disputing_a_pending_tag_and_regrading_a_decided_tag_are_rejected_409
    """
    ctx = _a_finished_load_waiting_for_the_lab("GC-DISPOSITION")

    grading = record_grading(ctx["tag"]["id"], **CLEAN_READING)
    assert float(grading["adjustment_pct"]) == 0.0

    tag = read_weigh_tag(ctx["tag"]["id"])
    assert tag["disposition"] == "ACCEPTED"
    assert float(tag["contract_slice_tons"]) == 20.000
    assert tag["grade_count"] == 1


def test_a_second_reading_on_a_decided_load_is_refused(api):
    """The lab wants another look at an accepted load; the disposition guard turns it away
    even though the weight dimension and the concurrency token are both in order.

    PRD: "and its disposition must be either `PENDING` (a first grading) or `DISPUTED` (a
    re-grading after a dispute), any already-decided disposition being
    `ERR_TAG_NOT_DISPUTABLE`."

    Design: Corner/state_machines/disputing_a_pending_tag_and_regrading_a_decided_tag_are_rejected_409
    """
    ctx = _a_finished_load_waiting_for_the_lab("GC-DISPOSITION")
    record_grading(ctx["tag"]["id"], **CLEAN_READING)

    validate_error(
        api.create_grading(
            ctx["tag"]["id"],
            create_grading_payload(weigh_tag_version(ctx["tag"]["id"]), **SECOND_OPINION),
            LAB_TECH,
        ),
        ApiErrorId.ERR_TAG_NOT_DISPUTABLE.value,
        409,
    )


def test_the_dispute_edge_is_the_only_way_the_load_becomes_readable_again(api):
    """The same call that was refused against a `PENDING` tag succeeds against a decided
    one, and it puts the disposition back into a state a re-grade accepts.

    PRD: "The tag's `contract_slice_tons`, `over_slice_tons`, `over_rejected_tons` and
    `excess_rejected_tons` all reset to 0.000, `active_adjustment_pct` is cleared, and the
    disposition moves to `DISPUTED`, where it waits for a re-grade."

    Design: Corner/state_machines/disputing_a_pending_tag_and_regrading_a_decided_tag_are_rejected_409
    """
    ctx = _a_finished_load_waiting_for_the_lab("GC-DISPOSITION")
    record_grading(ctx["tag"]["id"], **CLEAN_READING)

    disputed = dispute_grading(
        ctx["tag"]["id"], ctx["grower"]["id"], reason="grower contests the sugar reading"
    )
    assert disputed["disposition"] == "DISPUTED"
    assert float(disputed["contract_slice_tons"]) == 0.000
    assert disputed["active_adjustment_pct"] is None


def test_the_reopened_load_answers_the_stale_token_and_not_the_disposition(api):
    """The re-grade is legal on disposition grounds now, so the refusal the lab sees is the
    concurrency guard: the dispute moved the tag under the token it was holding.

    PRD: "If the tag's version has advanced since the client last read it — its net weight
    settled, its disposition moved, another grading superseded — the grading is refused with
    `ERR_STALE_WEIGH_TAG_VERSION` and HTTP 412, because the grader's view of the load is out
    of date."

    Design: Corner/state_machines/disputing_a_pending_tag_and_regrading_a_decided_tag_are_rejected_409
    """
    ctx = _a_finished_load_waiting_for_the_lab("GC-DISPOSITION")
    record_grading(ctx["tag"]["id"], **CLEAN_READING)
    token_read_before_the_dispute = weigh_tag_version(ctx["tag"]["id"])
    dispute_grading(ctx["tag"]["id"], ctx["grower"]["id"])

    validate_error(
        api.create_grading(
            ctx["tag"]["id"],
            create_grading_payload(token_read_before_the_dispute, **SECOND_OPINION),
            LAB_TECH,
        ),
        ApiErrorId.ERR_STALE_WEIGH_TAG_VERSION.value,
        412,
    )


def test_the_three_refusals_left_exactly_one_lab_record_behind(api):
    """A refused dispute, a refused re-read and a refused re-grade wrote nothing: the load
    still carries the single reading that was accepted.

    PRD: "Recording a grading also writes the grading row itself, stamping `superseded_at` on
    any earlier grading of the same tag, incrementing the tag's `grade_count` by 1 —
    superseded rows still count — and setting `active_adjustment_pct` to the new grading's
    `adjustment_pct`."

    Design: Corner/state_machines/disputing_a_pending_tag_and_regrading_a_decided_tag_are_rejected_409
    """
    ctx = _a_finished_load_waiting_for_the_lab("GC-DISPOSITION")
    grower_headers = make_grower_headers(ctx["grower"]["id"])

    api.create_grade_dispute(ctx["tag"]["id"], grower_headers, {"reason": "too early"})
    record_grading(ctx["tag"]["id"], **CLEAN_READING)
    token_read_before_the_dispute = weigh_tag_version(ctx["tag"]["id"])
    api.create_grading(
        ctx["tag"]["id"],
        create_grading_payload(token_read_before_the_dispute, **SECOND_OPINION),
        LAB_TECH,
    )
    dispute_grading(ctx["tag"]["id"], ctx["grower"]["id"])
    api.create_grading(
        ctx["tag"]["id"],
        create_grading_payload(token_read_before_the_dispute, **SECOND_OPINION),
        LAB_TECH,
    )

    assert read_weigh_tag(ctx["tag"]["id"])["grade_count"] == 1
    _, meta = validate_paginated(
        api.list_quality_grades(LAB_TECH, params={"weigh_tag_id": ctx["tag"]["id"]})
    )
    assert meta["total_count"] == 1


# --- The vintage does not close over an unfinished load ----------------------------


def test_an_untared_load_on_the_pad_blocks_the_close(api):
    """The truck is on the scale with only its inbound pass recorded, and the close refuses
    on the weight dimension before it looks at anything financial.

    PRD: "No weigh tag reachable through the contract may still sit in `GROSS_CAPTURED` — an
    untared load on the pad blocks the close with `ERR_TAG_WEIGH_STATE_INVALID`."

    Design: Corner/state_machines/settlement_close_is_blocked_until_every_load_is_tared_and_graded
    """
    ctx = _a_truck_weighed_in_on_an_active_vintage("GC-CLOSEGATE")
    assert ctx["tag"]["weigh_status"] == "GROSS_CAPTURED"

    validate_error(
        api.close_settlement(ctx["contract"]["id"], MANAGER),
        ApiErrorId.ERR_TAG_WEIGH_STATE_INVALID.value,
        409,
    )


def test_a_weighed_but_ungraded_load_blocks_the_close_on_the_next_gate(api):
    """The tare answers the first objection and the close moves straight to the second: the
    load has a settled weight but no receipt decision.

    PRD: "No weigh tag reachable through the contract may sit in `PENDING` or `DISPUTED` — an
    ungraded or contested load blocks the close with `ERR_TAG_NOT_DISPUTABLE`."

    Design: Corner/state_machines/settlement_close_is_blocked_until_every_load_is_tared_and_graded
    """
    ctx = _a_truck_weighed_in_on_an_active_vintage("GC-CLOSEGATE")
    api.close_settlement(ctx["contract"]["id"], MANAGER)

    tared = capture_tare(ctx["tag"]["id"], TARE_LBS)
    assert tared["weigh_status"] == "NET_FINAL"
    assert tared["disposition"] == "PENDING"

    validate_error(
        api.close_settlement(ctx["contract"]["id"], MANAGER),
        ApiErrorId.ERR_TAG_NOT_DISPUTABLE.value,
        409,
    )


def test_the_two_refused_closes_left_the_money_side_untouched(api):
    """Neither refusal half-closed the vintage: the contract is still live and the
    installment shell created at acceptance is still empty.

    PRD: "Until a close happens, `final_settlement_cents`, `prompt_pay_credit_cents`,
    `lien_holdback_cents` and `net_payable_cents` are all 0, `settlement_closed_at` is null,
    and every installment's `planned_amount_cents` and `due_at` are 0 and null respectively."

    Design: Corner/state_machines/settlement_close_is_blocked_until_every_load_is_tared_and_graded
    """
    ctx = _a_truck_weighed_in_on_an_active_vintage("GC-CLOSEGATE")
    api.close_settlement(ctx["contract"]["id"], MANAGER)
    capture_tare(ctx["tag"]["id"], TARE_LBS)
    api.close_settlement(ctx["contract"]["id"], MANAGER)

    contract = read_contract(ctx["contract"]["id"])
    assert contract["lifecycle_status"] == "ACTIVE"
    assert contract["settlement_closed_at"] is None
    assert contract["final_settlement_cents"] == 0
    assert contract["net_payable_cents"] == 0

    installments = list_installments(contract_id=ctx["contract"]["id"])
    assert [row["status"] for row in installments] == ["PENDING_SETTLEMENT"]
    assert installments[0]["planned_amount_cents"] == 0
    assert installments[0]["due_at"] is None


def _a_vintage_taken_all_the_way_to_the_close(api) -> dict:
    """Both refusals, then the tare and the grading that answer them, then a close three
    days later at 2026-08-28T09:00:00Z."""
    ctx = _a_truck_weighed_in_on_an_active_vintage("GC-CLOSEGATE")
    api.close_settlement(ctx["contract"]["id"], MANAGER)
    capture_tare(ctx["tag"]["id"], TARE_LBS)
    api.close_settlement(ctx["contract"]["id"], MANAGER)
    ctx["grading"] = record_grading(ctx["tag"]["id"], **CLEAN_READING)
    move_clock(CLOSED_AT)
    ctx["contract"] = close_settlement(ctx["contract"]["id"])
    return ctx


def test_once_the_load_is_finished_the_same_close_succeeds(api):
    """Nothing about the request changed — only the state of the load did — and the vintage
    closes on the third attempt, stamped from the logical clock.

    PRD: "When the last truck has been weighed and graded, the `GrowerRelationsManager`
    closes the vintage, driving the contract `ACTIVE → SETTLED`."

    Design: Corner/state_machines/settlement_close_is_blocked_until_every_load_is_tared_and_graded
    """
    ctx = _a_vintage_taken_all_the_way_to_the_close(api)

    assert ctx["contract"]["lifecycle_status"] == "SETTLED"
    assert ctx["contract"]["settlement_closed_at"] == CLOSED_AT


def test_the_close_finalises_the_line_and_prices_the_vintage(api):
    """One clean 20.000-ton load at 450000 cents per ton with no adjustment: the provisional
    line becomes final at the price it was struck at, and that is the settled gross.

    PRD: "Under `LOAD_BY_LOAD`, every line keeps the price it was struck at: each line's
    `final_amount_cents` becomes its own `gross_amount_cents`, and the settlement total is the
    sum of those amounts."

    Design: Corner/state_machines/settlement_close_is_blocked_until_every_load_is_tared_and_graded
    """
    ctx = _a_vintage_taken_all_the_way_to_the_close(api)

    lines = list_settlement_lines(contract_id=ctx["contract"]["id"])
    assert [line["status"] for line in lines] == ["FINAL"]
    assert lines[0]["final_amount_cents"] == 9000000
    assert lines[0]["final_amount_cents"] == lines[0]["gross_amount_cents"]
    assert ctx["contract"]["final_settlement_cents"] == 9000000


def test_the_close_schedules_the_installment_thirty_days_out(api):
    """The installment shell fills in at the close: the whole net payable on the single row,
    due the offset the plan asked for counted from the close instant.

    PRD: "Each receives a `planned_amount_cents` of `net_payable_cents` multiplied by its own
    `pct_of_settlement` divided by 100, rounded half up to whole cents, and a `due_at` of
    `settlement_closed_at` plus its own `due_offset_days` days."

    Design: Corner/state_machines/settlement_close_is_blocked_until_every_load_is_tared_and_graded
    """
    ctx = _a_vintage_taken_all_the_way_to_the_close(api)

    installments = list_installments(contract_id=ctx["contract"]["id"])
    assert [row["status"] for row in installments] == ["SCHEDULED"]
    assert installments[0]["due_at"] == FIRST_DUE_AT
    assert installments[0]["planned_amount_cents"] == ctx["contract"]["net_payable_cents"]
    assert installments[0]["paid_amount_cents"] == 0


def test_the_call_the_load_satisfied_is_left_alone_by_the_close(api):
    """The 20.000-ton load met the call's own estimate, so the call had already closed
    happily before the vintage did; the close's withdrawal cascade reaches only live calls.

    PRD: "Fulfilment closes a call happily: when an accepted or partially accepted load
    brings the call's derived `delivered_net_tons` to at least its `estimated_tons`, an
    acknowledged call transitions `ACKNOWLEDGED → FULFILLED` and `fulfillment_pct` is
    recomputed."

    Design: Corner/state_machines/settlement_close_is_blocked_until_every_load_is_tared_and_graded
    """
    ctx = _a_truck_weighed_in_on_an_active_vintage("GC-CLOSEGATE")
    capture_tare(ctx["tag"]["id"], TARE_LBS)
    record_grading(ctx["tag"]["id"], **CLEAN_READING)

    call_after_grading = read_pick_call(ctx["pick_call"]["id"])
    assert call_after_grading["status"] == "FULFILLED"
    assert float(call_after_grading["delivered_net_tons"]) == 20.000

    move_clock(CLOSED_AT)
    close_settlement(ctx["contract"]["id"])
    assert read_pick_call(ctx["pick_call"]["id"])["status"] == "FULFILLED"


def test_the_settlement_summary_reads_the_same_figures_the_close_wrote(api):
    """The reconciliation read is the clerk's view of the close, and it reports the tonnage
    and the money the contract itself now carries.

    PRD: "A dedicated computed read reconciles tonnage against money for a contract in one
    payload, available to the `GrowerRelationsManager`, the `AccountsPayableClerk` and the
    owning `Grower`."

    Design: Corner/state_machines/settlement_close_is_blocked_until_every_load_is_tared_and_graded
    """
    ctx = _a_vintage_taken_all_the_way_to_the_close(api)

    summary = validate_success(api.get_settlement_summary(ctx["contract"]["id"], CLERK))
    assert summary["final_settlement_cents"] == 9000000
    assert float(summary["delivered_contract_tons"]) == 20.000
    assert summary["net_payable_cents"] == ctx["contract"]["net_payable_cents"]
    assert summary["installment_planned_total_cents"] == ctx["contract"]["net_payable_cents"]
    assert summary["installment_paid_total_cents"] == 0
