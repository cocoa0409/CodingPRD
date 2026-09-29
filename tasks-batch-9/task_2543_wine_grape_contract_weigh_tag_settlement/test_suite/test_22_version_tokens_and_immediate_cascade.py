"""The two optimistic-concurrency tokens and the fan-out they protect. A cascaded transition
bumps the very version its own client is holding, and one grading leaves every derived figure
across six other rows already correct on the next read.
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
    create_weigh_tag_payload,
    issue_pick_call,
    list_settlement_lines,
    move_clock,
    offer_contract,
    read_appointment,
    read_block,
    read_contract,
    read_lane,
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

FIRST_GROSS_LBS = 57000
SECOND_GROSS_LBS = 61240
TARE_LBS = 17000
LOAD_TONS = 20.000

CLEAN_READING = {"brix": 23.0, "ta_gl": 6.5, "ph": 3.40, "rot_pct": 1.0, "mog_pct": 0.5}

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


def _a_slot_waiting_for_trucks(contract_code: str, slot_tons: float, estimated_tons: float) -> dict:
    """An ACTIVE TONNAGE contract with committed_tons 40.000, one acknowledged call and one
    SCHEDULED slot on lane L1, with the clock inside the slot's window."""
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
        contract_basis="TONNAGE",
        committed_tons=40.000,
        base_price_per_ton_cents=450000,
        over_delivery_policy="ACCEPT_AT_CONTRACT",
        term_start_vintage=2026,
        term_end_vintage=2026,
        installment_plan=single_installment_plan(),
    )
    ctx["allocation"] = create_allocation(contract["id"], ctx["block"]["id"])
    offer_contract(contract["id"])
    ctx["contract"] = accept_contract(contract["id"], ctx["grower"]["id"])

    visit = book_sampling_visit(
        contract["id"], ctx["block"]["id"], ctx["crew"]["id"], SAMPLING_WINDOW[0], SAMPLING_WINDOW[1]
    )
    record_sampling_visit(
        visit["id"], measured_brix=24.5, measured_ta_gl=6.5, measured_ph=3.45, measured_rot_pct=1.0
    )
    call = issue_pick_call(contract["id"], ctx["block"]["id"], TARGET_PICK_AT, estimated_tons)
    ctx["pick_call"] = acknowledge_pick_call(call["id"], ctx["grower"]["id"])
    ctx["appointment"] = book_appointment(
        call["id"], ctx["lane"]["id"], SLOT[0], SLOT[1], slot_tons
    )

    move_clock(TRUCK_ARRIVES_AT)
    return ctx


# --- The token a cascade invalidates -------------------------------------------------


def _the_scale_house_holding_a_token_from_before_the_first_truck(api) -> dict:
    """The slot's version is read once, then the first load is presented against it — which is
    the transition that makes that very token stale."""
    ctx = _a_slot_waiting_for_trucks("GC-OCC", 40.000, 45.000)
    ctx["token_before_any_truck"] = appointment_version(ctx["appointment"]["id"])
    ctx["first_tag"] = capture_gross(
        ctx["appointment"]["id"],
        ctx["block"]["id"],
        FIRST_GROSS_LBS,
        ctx["token_before_any_truck"],
    )
    return ctx


def test_the_first_load_is_accepted_and_drives_the_slot_to_arrived(api):
    """The token was current when it was read, so the create succeeds — and it is the create's
    own cascade that moves the slot on.

    PRD: "The first weigh tag presented against a scheduled appointment drives `SCHEDULED →
    ARRIVED` as the tag's `weigh_tag_count` moves from 0 to 1."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_versions_are_refused_412_on_both_concurrency_rules
    """
    ctx = _the_scale_house_holding_a_token_from_before_the_first_truck(api)

    assert ctx["first_tag"]["weigh_status"] == "GROSS_CAPTURED"
    assert read_appointment(ctx["appointment"]["id"])["status"] == "ARRIVED"


def test_a_second_load_quoting_the_same_slot_token_is_refused_as_stale(api):
    """A second truck against the same slot is a perfectly legal product operation; what makes
    it fail is that the cascaded transition already moved the slot under the token.

    PRD: "If the appointment's version has advanced since the client last read it, the create is
    refused with `ERR_STALE_APPOINTMENT_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_versions_are_refused_412_on_both_concurrency_rules
    """
    ctx = _the_scale_house_holding_a_token_from_before_the_first_truck(api)

    validate_error(
        api.create_weigh_tag(
            create_weigh_tag_payload(
                ctx["appointment"]["id"],
                ctx["block"]["id"],
                SECOND_GROSS_LBS,
                ctx["token_before_any_truck"],
            ),
            SCALE_OPERATOR,
        ),
        ApiErrorId.ERR_STALE_APPOINTMENT_VERSION.value,
        412,
    )


def test_the_refused_second_load_left_no_weigh_tag_behind(api):
    """The 412 is a refusal and not a partial write: the slot still holds exactly the one tag
    that was accepted.

    PRD: "Ranks 12 and 13 are the stale-version guards of §2.8: (12) `expected_appointment_version`
    on weigh-tag create, else `ERR_STALE_APPOINTMENT_VERSION`; (13) `expected_weigh_tag_version` on
    grading create, else `ERR_STALE_WEIGH_TAG_VERSION`. Both are HTTP 412, and both are checked
    before any state legality question — a client holding a stale version learns that first."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_versions_are_refused_412_on_both_concurrency_rules
    """
    ctx = _the_scale_house_holding_a_token_from_before_the_first_truck(api)
    api.create_weigh_tag(
        create_weigh_tag_payload(
            ctx["appointment"]["id"],
            ctx["block"]["id"],
            SECOND_GROSS_LBS,
            ctx["token_before_any_truck"],
        ),
        SCALE_OPERATOR,
    )

    _, meta = validate_paginated(
        api.list_weigh_tags(SCALE_OPERATOR, params={"appointment_id": ctx["appointment"]["id"]})
    )
    assert meta["total_count"] == 1


def test_re_reading_the_slot_yields_a_token_one_higher_that_works(api):
    """The cascade moved the counter by exactly one, and quoting the refreshed figure lets the
    second truck through.

    PRD: "The appointment's `weigh_tag_count` is recomputed and the appointment itself is
    mutated, so its `version` advances — which is precisely why the next tag against the same
    slot must carry the newer `expected_appointment_version`."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_versions_are_refused_412_on_both_concurrency_rules
    """
    ctx = _the_scale_house_holding_a_token_from_before_the_first_truck(api)

    refreshed = appointment_version(ctx["appointment"]["id"])
    assert refreshed == ctx["token_before_any_truck"] + 1

    second = validate_success(
        api.create_weigh_tag(
            create_weigh_tag_payload(
                ctx["appointment"]["id"], ctx["block"]["id"], SECOND_GROSS_LBS, refreshed
            ),
            SCALE_OPERATOR,
        ),
        201,
    )
    assert second["gross_weight_lbs"] == SECOND_GROSS_LBS


def test_the_lab_token_read_before_the_tare_is_refused_as_stale(api):
    """The other concurrency rule, on the other row: settling the net weight advanced the tag,
    so the lab's pre-tare view is out of date even though the grading is otherwise perfectly
    legal.

    PRD: "If the tag's version has advanced since the client last read it — its net weight
    settled, its disposition moved, another grading superseded — the grading is refused with
    `ERR_STALE_WEIGH_TAG_VERSION` and HTTP 412, because the grader's view of the load is out of
    date."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_versions_are_refused_412_on_both_concurrency_rules
    """
    ctx = _the_scale_house_holding_a_token_from_before_the_first_truck(api)
    token_before_the_tare = weigh_tag_version(ctx["first_tag"]["id"])
    tared = capture_tare(ctx["first_tag"]["id"], TARE_LBS)
    assert tared["weigh_status"] == "NET_FINAL"

    validate_error(
        api.create_grading(
            ctx["first_tag"]["id"],
            create_grading_payload(token_before_the_tare, **CLEAN_READING),
            LAB_TECH,
        ),
        ApiErrorId.ERR_STALE_WEIGH_TAG_VERSION.value,
        412,
    )


def test_every_accepted_write_moved_the_tag_counter_by_exactly_one(api):
    """Retried with the token the tare left behind, the same grading is accepted — and the tag
    ends one version above that.

    PRD: "`version`, an integer that starts at 1 on creation and increments by exactly 1 on
    every mutation of that row."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_versions_are_refused_412_on_both_concurrency_rules
    """
    ctx = _the_scale_house_holding_a_token_from_before_the_first_truck(api)
    token_before_the_tare = weigh_tag_version(ctx["first_tag"]["id"])
    capture_tare(ctx["first_tag"]["id"], TARE_LBS)
    token_after_the_tare = weigh_tag_version(ctx["first_tag"]["id"])
    assert token_after_the_tare == token_before_the_tare + 1

    record_grading(
        ctx["first_tag"]["id"], expected_weigh_tag_version=token_after_the_tare, **CLEAN_READING
    )
    graded = read_weigh_tag(ctx["first_tag"]["id"])
    assert graded["version"] == token_after_the_tare + 1
    assert graded["disposition"] == "ACCEPTED"


# --- One grading, six rows, no lag ---------------------------------------------------


SETTLED_GROSS_CENTS = 9000000
PROVISIONAL_SHARE_CENTS = 5400000  # 60 percent of the gross, the house provisional share


def _one_load_graded_and_everything_read_back(api) -> dict:
    """A 20.000-ton load that is its slot's only tag, graded clean, with every row the cascade
    touches read immediately afterwards."""
    ctx = _a_slot_waiting_for_trucks("GC-CASCADE", LOAD_TONS, LOAD_TONS)
    tag = capture_gross(
        ctx["appointment"]["id"],
        ctx["block"]["id"],
        FIRST_GROSS_LBS,
        appointment_version(ctx["appointment"]["id"]),
    )
    ctx["tag"] = capture_tare(tag["id"], TARE_LBS)
    ctx["grading"] = record_grading(tag["id"], **CLEAN_READING)
    return ctx


def test_the_grading_response_already_carries_its_own_derived_grade(api):
    """The reading is turned into a price adjustment and a recommendation inside the same
    response, not fetched from somewhere later.

    PRD: "`recommended_disposition` is decided from the raw readings, not from the adjustment: it
    is `REJECT_QUALITY` when the tenths of `brix` fall below the tenths of `min_brix_accept`, or
    when the tenths of `rot_pct` reach or exceed the tenths of `rot_rejection_pct`; otherwise it
    is `ACCEPT`."

    Design: Corner/consistency_model/every_cascaded_change_is_visible_in_the_same_request_cycle
    """
    ctx = _one_load_graded_and_everything_read_back(api)

    assert float(ctx["grading"]["adjustment_pct"]) == 0.0
    assert ctx["grading"]["recommended_disposition"] == "ACCEPT"


def test_the_settlement_line_exists_and_is_priced_on_the_next_read(api):
    """The whole load fitted inside the soft cap, so one contract-bucket line was written and
    priced immediately, with the house 60 percent advanced against it.

    PRD: "Fourth, `provisional_amount_cents` is `gross_amount_cents` multiplied by the contract's
    `provisional_payment_pct` divided by 100, rounded half up to whole cents."

    Design: Corner/consistency_model/every_cascaded_change_is_visible_in_the_same_request_cycle
    """
    ctx = _one_load_graded_and_everything_read_back(api)

    lines = list_settlement_lines(weigh_tag_id=ctx["tag"]["id"])
    assert len(lines) == 1
    assert lines[0]["status"] == "PROVISIONAL"
    assert lines[0]["bucket"] == "CONTRACT"
    assert float(lines[0]["tons"]) == LOAD_TONS
    assert lines[0]["gross_amount_cents"] == SETTLED_GROSS_CENTS
    assert lines[0]["provisional_amount_cents"] == PROVISIONAL_SHARE_CENTS


def test_the_contract_rollups_are_already_reconciled(api):
    """All four tonnage-and-money rollups on the agreement moved inside the grading request,
    and the cap posture was re-derived from them.

    PRD: "Because settlement lines were created, the contract's `delivered_contract_tons`,
    `delivered_over_tons` and `provisional_settlement_cents` are recomputed — the first two being
    the running sums of `tons` on the contract's lines in each bucket with status `PROVISIONAL` or
    `FINAL`, the third the sum of `provisional_amount_cents` over its `PROVISIONAL` lines."

    Design: Corner/consistency_model/every_cascaded_change_is_visible_in_the_same_request_cycle
    """
    ctx = _one_load_graded_and_everything_read_back(api)

    contract = read_contract(ctx["contract"]["id"])
    assert float(contract["delivered_contract_tons"]) == LOAD_TONS
    assert float(contract["delivered_over_tons"]) == 0.000
    assert float(contract["rejected_tons"]) == 0.000
    assert contract["provisional_settlement_cents"] == PROVISIONAL_SHARE_CENTS
    assert contract["tonnage_status"] == "OPEN"


def test_the_pick_call_was_fulfilled_inside_the_same_request(api):
    """The call asked for 20.000 tons and got them, so the fulfilment check ran on the same
    delivered figure the grading had just recomputed.

    PRD: "An acknowledged pick call whose `delivered_net_tons` has reached its `estimated_tons`
    advances to `FULFILLED` — and that check runs before the suspension check, so a call that has
    just been fulfilled is not also suspended."

    Design: Corner/consistency_model/every_cascaded_change_is_visible_in_the_same_request_cycle
    """
    ctx = _one_load_graded_and_everything_read_back(api)

    call = read_pick_call(ctx["pick_call"]["id"])
    assert call["status"] == "FULFILLED"
    assert float(call["delivered_net_tons"]) == LOAD_TONS
    assert float(call["fulfillment_pct"]) == 100.0


def test_the_slot_closed_because_the_graded_load_was_its_last_open_one(api):
    """The slot had exactly one tag, and deciding it finished the slot in the same breath.

    PRD: "If this was the last open tag of its appointment, the appointment transitions `ARRIVED →
    CLOSED`."

    Design: Corner/consistency_model/every_cascaded_change_is_visible_in_the_same_request_cycle
    """
    ctx = _one_load_graded_and_everything_read_back(api)

    slot = read_appointment(ctx["appointment"]["id"])
    assert slot["status"] == "CLOSED"
    assert float(slot["captured_net_tons"]) == LOAD_TONS


def test_the_lane_ledger_released_the_slot_immediately(api):
    """The ledger spans only the slots still expecting or holding a truck, so closing the
    appointment freed the lane on the very next read.

    PRD: "Two derived figures round out the row: `committed_tons`, the sum of `planned_tons` over
    the lane's appointments in status `SCHEDULED` or `ARRIVED` to 3 decimals, and
    `scheduled_appointment_count`, the count of those same appointments."

    Design: Corner/consistency_model/every_cascaded_change_is_visible_in_the_same_request_cycle
    """
    ctx = _one_load_graded_and_everything_read_back(api)

    lane = read_lane(ctx["lane"]["id"])
    assert float(lane["committed_tons"]) == 0.000
    assert lane["scheduled_appointment_count"] == 0


def test_the_blocks_vintage_tonnage_followed_in_the_same_cycle(api):
    """The fan-out reaches down to the physical block the fruit came off.

    PRD: "The allocation's `delivered_net_tons` and the block's `delivered_net_tons_vintage` are
    recomputed."

    Design: Corner/consistency_model/every_cascaded_change_is_visible_in_the_same_request_cycle
    """
    ctx = _one_load_graded_and_everything_read_back(api)

    assert float(read_block(ctx["block"]["id"])["delivered_net_tons_vintage"]) == LOAD_TONS


def test_the_lab_record_and_the_tag_counters_agree_with_one_another(api):
    """One grading exists, nothing superseded it, and the tag's own counters were written in the
    same request as the row.

    PRD: "The system is immediately consistent: there are no queues and no deferred
    reconciliations. When one write changes a fact that another row's derived fields depend on,
    those rows are updated inside the same request, and each such update is a mutation in the
    sense of §2.4 — `updated_at` refreshed, `version` incremented."

    Design: Corner/consistency_model/every_cascaded_change_is_visible_in_the_same_request_cycle
    """
    ctx = _one_load_graded_and_everything_read_back(api)

    rows, meta = validate_paginated(
        api.list_quality_grades(LAB_TECH, params={"weigh_tag_id": ctx["tag"]["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["superseded_at"] is None

    tag = read_weigh_tag(ctx["tag"]["id"])
    assert tag["grade_count"] == 1
    assert float(tag["active_adjustment_pct"]) == 0.0
