"""Three different pairs of rows where one entity's own state decides whether a write
against another entity is allowed at all."""
from test_helpers import (
    COORDINATOR,
    ApiErrorId,
    accept_contract,
    acknowledge_pick_call,
    book_sampling_visit,
    create_allocation,
    create_crew,
    create_contract,
    create_delivery_appointment_payload,
    create_pick_call_payload,
    get_success_data,
    list_installments,
    move_clock,
    offer_contract,
    read_block,
    read_contract,
    read_grower,
    read_lane,
    read_pick_call,
    read_sampling_visit,
    reinstate_grower,
    record_sampling_visit,
    setup_active_contract,
    setup_crush_pad,
    setup_issued_pick_call,
    setup_reference_book,
    single_installment_plan,
    suspend_grower,
    validate_error,
    validate_success,
)

SETUP_AT = "2026-08-20T08:00:00Z"
TARGET_PICK_AT = "2026-08-25T14:00:00Z"
ACK_DEADLINE_AT = "2026-08-21T08:00:00Z"
FIRST_SLOT = ("2026-08-25T14:00:00Z", "2026-08-25T16:00:00Z")


# --- Pair 1: a pick call depends on a completed, pick-ready sampling visit -------


def _contract_awaiting_a_field_sample() -> dict:
    """An ACTIVE contract with an allocated block, a crew, and no sampling visit yet."""
    move_clock(SETUP_AT)
    ctx = setup_active_contract(
        contract_overrides={
            "base_price_per_ton_cents": 450000,
            "committed_tons": 40.000,
            "over_delivery_policy": "ACCEPT_AT_SPOT",
            "installment_plan": single_installment_plan(),
        }
    )
    ctx["crew"] = create_crew(region_code=ctx["grower"]["region_code"], max_concurrent_visits=2)
    return ctx


def _call_payload(ctx: dict) -> dict:
    return create_pick_call_payload(ctx["contract"]["id"], ctx["block"]["id"], TARGET_PICK_AT, 40.000)


def test_a_block_with_no_field_sample_at_all_cannot_be_called(api):
    """The maturity gate is evaluated before anything else, and a block that has never
    been sampled fails it.

    PRD: "The **maturity gate** comes first, before scheduling is considered in any way:
    the called block must have at least one sampling visit for that same contract in
    status `COMPLETED` with `maturity_flag` `PICK_READY`, and that visit's
    `measured_rot_pct` must be strictly below the contract specification's
    `rot_rejection_pct`."

    Design: Difficulty/cross_entity_state_dependency/pick_call_issuance_requires_completed_pick_ready_sampling_visit
    """
    ctx = _contract_awaiting_a_field_sample()

    response = api.create_pick_call(_call_payload(ctx), COORDINATOR)
    validate_error(response, ApiErrorId.ERR_BLOCK_NOT_PICK_READY.value, 422)


def test_a_visit_that_exists_but_is_still_scheduled_does_not_open_the_gate(api):
    """Booking the crew is not evidence of maturity: the gate demands a `COMPLETED`
    visit, and a merely `SCHEDULED` one still fails.

    PRD: "Recording the readings is likewise a `HarvestCoordinator` action and drives
    the visit `SCHEDULED → COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/pick_call_issuance_requires_completed_pick_ready_sampling_visit
    """
    ctx = _contract_awaiting_a_field_sample()
    visit = book_sampling_visit(
        ctx["contract"]["id"], ctx["block"]["id"], ctx["crew"]["id"],
        "2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z",
    )
    assert visit["status"] == "SCHEDULED"

    response = api.create_pick_call(_call_payload(ctx), COORDINATOR)
    validate_error(response, ApiErrorId.ERR_BLOCK_NOT_PICK_READY.value, 422)


def test_a_completed_visit_below_the_pick_call_threshold_is_immature(api):
    """A Brix 20.0 reading against a 21.0 pick-call threshold completes the visit but
    flags it `IMMATURE`, and the gate stays shut.

    PRD: "Recording stamps `sampled_at` from the logical clock and derives
    `maturity_flag`: `PICK_READY` when `measured_brix` is greater than or equal to the
    contract specification's `min_brix_pick_call`, and `IMMATURE` otherwise."

    Design: Difficulty/cross_entity_state_dependency/pick_call_issuance_requires_completed_pick_ready_sampling_visit
    """
    ctx = _contract_awaiting_a_field_sample()
    visit = book_sampling_visit(
        ctx["contract"]["id"], ctx["block"]["id"], ctx["crew"]["id"],
        "2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z",
    )
    record_sampling_visit(visit["id"], measured_brix=20.0, measured_ph=3.20, measured_rot_pct=1.0)

    immature = read_sampling_visit(visit["id"])
    assert immature["status"] == "COMPLETED"
    assert immature["maturity_flag"] == "IMMATURE"
    assert immature["sampled_at"] == SETUP_AT

    response = api.create_pick_call(_call_payload(ctx), COORDINATOR)
    validate_error(response, ApiErrorId.ERR_BLOCK_NOT_PICK_READY.value, 422)


def test_a_pick_ready_visit_finally_lets_the_call_out(api):
    """A second visit read at Brix 24.5 is `PICK_READY` and opens the gate; the call's
    notice figures come from the clock.  Both visits were recorded at the same logical
    instant, so the block's mirrored reading is decided by the documented tie-break and
    stays with the first-created visit's Brix 20.0.

    PRD: "`latest_sampling_brix` and `latest_sampling_rot_pct` take the `measured_brix`
    and `measured_rot_pct` of that block's completed visit with the greatest `sampled_at`,
    ties broken by the earlier `created_at`."

    PRD: "`notice_hours` is the number of whole hours between `issued_at` and
    `target_pick_at` — the elapsed seconds between the two instants divided by 3600 and
    rounded down to a whole number. `ack_deadline_at` is `issued_at` plus the contract's
    `pick_call_ack_window_hours` hours."

    Design: Difficulty/cross_entity_state_dependency/pick_call_issuance_requires_completed_pick_ready_sampling_visit
    """
    ctx = _contract_awaiting_a_field_sample()
    immature_visit = book_sampling_visit(
        ctx["contract"]["id"], ctx["block"]["id"], ctx["crew"]["id"],
        "2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z",
    )
    record_sampling_visit(immature_visit["id"], measured_brix=20.0, measured_ph=3.20, measured_rot_pct=1.0)
    ripe_visit = book_sampling_visit(
        ctx["contract"]["id"], ctx["block"]["id"], ctx["crew"]["id"],
        "2026-08-20T12:00:00Z", "2026-08-20T14:00:00Z",
    )
    record_sampling_visit(ripe_visit["id"], measured_brix=24.5, measured_ph=3.45, measured_rot_pct=1.0)

    assert read_sampling_visit(ripe_visit["id"])["maturity_flag"] == "PICK_READY"
    # Equal `sampled_at` on both completed visits, so the earlier `created_at` wins.
    assert float(read_block(ctx["block"]["id"])["latest_sampling_brix"]) == 20.0

    pick_call = validate_success(api.create_pick_call(_call_payload(ctx), COORDINATOR), 201)
    assert pick_call["status"] == "ISSUED"
    assert pick_call["notice_hours"] == 126
    assert pick_call["ack_deadline_at"] == ACK_DEADLINE_AT


def test_the_three_refused_calls_created_nothing(api):
    """Only the call that cleared the gate exists; the refusals left no rows behind.

    PRD: "Calling immature or rotten fruit to the crush pad is refused with
    `ERR_BLOCK_NOT_PICK_READY` and HTTP 422."

    Design: Difficulty/cross_entity_state_dependency/pick_call_issuance_requires_completed_pick_ready_sampling_visit
    """
    ctx = _contract_awaiting_a_field_sample()
    api.create_pick_call(_call_payload(ctx), COORDINATOR)
    visit = book_sampling_visit(
        ctx["contract"]["id"], ctx["block"]["id"], ctx["crew"]["id"],
        "2026-08-20T09:00:00Z", "2026-08-20T11:00:00Z",
    )
    api.create_pick_call(_call_payload(ctx), COORDINATOR)
    record_sampling_visit(visit["id"], measured_brix=20.0, measured_ph=3.20, measured_rot_pct=1.0)
    api.create_pick_call(_call_payload(ctx), COORDINATOR)

    calls = get_success_data(
        api.list_pick_calls(COORDINATOR, params={"contract_id": ctx["contract"]["id"]})
    )
    assert calls == []

    ripe_visit = book_sampling_visit(
        ctx["contract"]["id"], ctx["block"]["id"], ctx["crew"]["id"],
        "2026-08-20T12:00:00Z", "2026-08-20T14:00:00Z",
    )
    record_sampling_visit(ripe_visit["id"], measured_brix=24.5, measured_ph=3.45, measured_rot_pct=1.0)
    validate_success(api.create_pick_call(_call_payload(ctx), COORDINATOR), 201)
    calls = get_success_data(
        api.list_pick_calls(COORDINATOR, params={"contract_id": ctx["contract"]["id"]})
    )
    assert len(calls) == 1


# --- Pair 2: a crush-pad slot depends on the pick call being acknowledged --------


def _unacknowledged_call_and_an_open_lane() -> dict:
    """An ISSUED — deliberately unacknowledged — call on a contract with an open lane."""
    move_clock(SETUP_AT)
    ctx = setup_active_contract(
        contract_overrides={
            "base_price_per_ton_cents": 450000,
            "committed_tons": 40.000,
            "over_delivery_policy": "ACCEPT_AT_SPOT",
            "pick_call_ack_window_hours": 24,
            "installment_plan": single_installment_plan(),
        }
    )
    setup_crush_pad(
        ctx,
        {
            "lane_code": "L1",
            "daily_capacity_tons": 80.000,
            "turnaround_buffer_minutes": 30,
            "max_load_tons": 40.0,
        },
    )
    setup_issued_pick_call(ctx, target_pick_at=TARGET_PICK_AT, estimated_tons=40.000)
    return ctx


def _slot_payload(ctx: dict) -> dict:
    return create_delivery_appointment_payload(
        ctx["pick_call"]["id"], ctx["lane"]["id"], FIRST_SLOT[0], FIRST_SLOT[1], 22.000
    )


def test_a_slot_cannot_be_reserved_against_a_merely_issued_call(api):
    """The winery cannot commit crush-pad capacity before the producer has answered the
    call, and the refusal names the pick call's state.

    PRD: "The pick call must be in status `ACKNOWLEDGED` — a call that is merely
    `ISSUED`, or has been suspended, expired, fulfilled or withdrawn, yields
    `ERR_PICK_CALL_STATE_INVALID`"

    Design: Difficulty/cross_entity_state_dependency/delivery_appointment_requires_acknowledged_pick_call
    """
    ctx = _unacknowledged_call_and_an_open_lane()

    response = api.create_delivery_appointment(_slot_payload(ctx), COORDINATOR)
    validate_error(response, ApiErrorId.ERR_PICK_CALL_STATE_INVALID.value, 409)
    assert read_pick_call(ctx["pick_call"]["id"])["status"] == "ISSUED"


def test_the_refused_booking_left_the_lane_empty(api):
    """Nothing was reserved, so the lane still carries no appointments at all.

    PRD: "A successful booking creates the appointment in status `SCHEDULED` and
    recomputes both the lane's `committed_tons` and `scheduled_appointment_count` and the
    pick call's `appointed_tons`."

    Design: Difficulty/cross_entity_state_dependency/delivery_appointment_requires_acknowledged_pick_call
    """
    ctx = _unacknowledged_call_and_an_open_lane()
    api.create_delivery_appointment(_slot_payload(ctx), COORDINATOR)

    lane = read_lane(ctx["lane"]["id"])
    assert lane["scheduled_appointment_count"] == 0
    assert float(lane["committed_tons"]) == 0.000


def test_the_identical_request_succeeds_the_moment_the_producer_answers(api):
    """Not one field of the booking changes; only the other entity's state does, and
    the same request flips from refused to created.

    PRD: "The producer whose identifier matches the contract's `grower_id` acknowledges
    the call, driving `ISSUED → ACKNOWLEDGED` and stamping `acknowledged_at` from the
    logical clock."

    Design: Difficulty/cross_entity_state_dependency/delivery_appointment_requires_acknowledged_pick_call
    """
    ctx = _unacknowledged_call_and_an_open_lane()
    api.create_delivery_appointment(_slot_payload(ctx), COORDINATOR)

    acknowledged = acknowledge_pick_call(ctx["pick_call"]["id"], ctx["grower"]["id"])
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["acknowledged_at"] == SETUP_AT

    appointment = validate_success(
        api.create_delivery_appointment(_slot_payload(ctx), COORDINATOR), 201
    )
    assert appointment["status"] == "SCHEDULED"
    assert float(read_pick_call(ctx["pick_call"]["id"])["appointed_tons"]) == 22.000
    assert float(read_lane(ctx["lane"]["id"])["committed_tons"]) == 22.000


# --- Pair 3: acceptance depends on the counterparty producer's own status --------


def _two_offers_and_a_suspended_producer() -> dict:
    """One producer with two OFFERED contracts — one allocated, one not — and the
    producer suspended after both offers went out."""
    move_clock(SETUP_AT)
    ctx = setup_reference_book()
    grower_id, spec_id, block_id = ctx["grower"]["id"], ctx["spec"]["id"], ctx["block"]["id"]

    allocated = create_contract(
        grower_id,
        spec_id,
        contract_basis="TONNAGE",
        base_price_per_ton_cents=450000,
        committed_tons=40.000,
        over_delivery_policy="ACCEPT_AT_SPOT",
        term_start_vintage=2026,
        term_end_vintage=2028,
        installment_plan=[
            {"installment_no": 1, "pct_of_settlement": 60.0, "due_offset_days": 30, "lien_protected": True},
            {"installment_no": 2, "pct_of_settlement": 40.0, "due_offset_days": 60, "lien_protected": False},
        ],
    )
    create_allocation(allocated["id"], block_id)
    offer_contract(allocated["id"])

    unallocated = create_contract(
        grower_id,
        spec_id,
        contract_basis="TONNAGE",
        base_price_per_ton_cents=450000,
        committed_tons=10.000,
        over_delivery_policy="REJECT",
        term_start_vintage=2026,
        term_end_vintage=2028,
        installment_plan=single_installment_plan(),
    )
    offer_contract(unallocated["id"])

    suspend_grower(grower_id, reason="unpaid state assessment")
    ctx["allocated"] = allocated
    ctx["unallocated"] = unallocated
    return ctx


def test_a_suspended_producer_cannot_accept_an_offer_already_on_the_table(api):
    """The offer is perfectly valid and the allocation exists, but the counterparty's
    own status flag closes the door.

    PRD: "it requires two preconditions beyond the lifecycle state: at least one block
    allocation must already exist for the contract, else `ERR_NO_ALLOCATIONS`, and the
    accepting producer's `status` must be `ACTIVE`, else `ERR_GROWER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/contract_accept_requires_active_grower
    """
    ctx = _two_offers_and_a_suspended_producer()

    response = api.accept_contract(ctx["allocated"]["id"], ctx["grower_headers"])
    validate_error(response, ApiErrorId.ERR_GROWER_SUSPENDED.value, 403)
    assert read_grower(ctx["grower"]["id"])["status"] == "SUSPENDED"


def test_the_refused_acceptance_derived_nothing(api):
    """Acceptance is the pivot that derives the caps and materialises the schedule, so
    a refused acceptance must leave both untouched.

    PRD: "And the payment schedule is materialised: one installment row is created for
    each element of `installment_plan`, copying `installment_no`, `pct_of_settlement`,
    `due_offset_days` and `lien_protected` verbatim, each starting in status
    `PENDING_SETTLEMENT` with `planned_amount_cents` 0 and `paid_amount_cents` 0."

    Design: Difficulty/cross_entity_state_dependency/contract_accept_requires_active_grower
    """
    ctx = _two_offers_and_a_suspended_producer()
    api.accept_contract(ctx["allocated"]["id"], ctx["grower_headers"])

    contract = read_contract(ctx["allocated"]["id"])
    assert contract["lifecycle_status"] == "OFFERED"
    assert contract["contract_cap_tons"] is None
    assert list_installments(contract_id=contract["id"]) == []


def test_the_other_accept_precondition_is_independently_live(api):
    """On the reinstated producer the same endpoint refuses a different contract for a
    different reason, so the two preconditions are genuinely separate.

    PRD: "(29) at least one block allocation exists before a contract can be accepted,
    else `ERR_NO_ALLOCATIONS`"

    Design: Difficulty/cross_entity_state_dependency/contract_accept_requires_active_grower
    """
    ctx = _two_offers_and_a_suspended_producer()
    api.accept_contract(ctx["allocated"]["id"], ctx["grower_headers"])
    reinstate_grower(ctx["grower"]["id"])

    response = api.accept_contract(ctx["unallocated"]["id"], ctx["grower_headers"])
    validate_error(response, ApiErrorId.ERR_NO_ALLOCATIONS.value, 409)
    assert read_contract(ctx["unallocated"]["id"])["lifecycle_status"] == "OFFERED"


def test_reinstatement_lets_the_allocated_offer_through_and_derives_everything(api):
    """With standing restored, the previously refused acceptance succeeds and both the
    tonnage envelope and the two-row payment schedule appear.

    PRD: "In every case, `hard_cap_tons` is `contract_cap_tons` multiplied by one plus
    `over_delivery_tolerance_pct` divided by 100, rounded half up to 3 decimals."

    Design: Difficulty/cross_entity_state_dependency/contract_accept_requires_active_grower
    """
    ctx = _two_offers_and_a_suspended_producer()
    api.accept_contract(ctx["allocated"]["id"], ctx["grower_headers"])
    reinstate_grower(ctx["grower"]["id"])

    contract = accept_contract(ctx["allocated"]["id"], ctx["grower"]["id"])
    assert contract["lifecycle_status"] == "ACTIVE"
    assert float(contract["contract_cap_tons"]) == 40.000
    assert float(contract["hard_cap_tons"]) == 44.000

    installments = sorted(
        list_installments(contract_id=contract["id"]), key=lambda row: row["installment_no"]
    )
    assert [row["installment_no"] for row in installments] == [1, 2]
    for row in installments:
        assert row["status"] == "PENDING_SETTLEMENT"
        assert row["planned_amount_cents"] == 0
        assert row["paid_amount_cents"] == 0
