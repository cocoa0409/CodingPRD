"""Dispensing gates (state/dose/expiry/window/sequence), returns, and the
accountability conservation invariant (PRD §2.6, §2.10, §3.6)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId,
    setup_pharmacy, setup_randomized_subject, setup_subject_with_allocated_kit,
    setup_dispensed_subject, setup_returned_kit, upload_slots, slot_spec,
    register_subject, randomize_subject, allocate_next_kit, set_clock,
    dispense_kit, record_return, get_kit, create_dispensing_payload,
)
from test_helpers import TEST_USERS

SPONSOR = TEST_USERS["sponsor_admin_headers"]


def test_dose_at_exact_cap_allowed_and_one_above_rejected():
    """PRD §3.6: "The dose cap: `quantity_dispensed` multiplied by the lot's
    `strength_mg` must not exceed the study's `max_dose_per_visit_mg`, else
    `ERR_DOSE_EXCEEDS_PROTOCOL_MAX`."

    Design: Corner/validations/dose_at_exact_cap_allowed_and_one_above_rejected
    """
    world = setup_pharmacy(protocol_number="P-VAL-5", kit_numbers=("K-DC1", "K-DC2"),
                           pharmacist_license="L-VAL-5")
    p_id = world["pharmacist"]["id"]
    upload_slots(world["study"]["id"], world["study_version"], [
        slot_spec(1, "K-DC1", arm_code="TRT-A"), slot_spec(2, "K-DC2", arm_code="PBO"),
    ])
    sub1 = randomize_subject(register_subject(world["site"]["id"], "SUB-DC1", p_id)["id"], p_id)
    sub2 = randomize_subject(register_subject(world["site"]["id"], "SUB-DC2", p_id)["id"], p_id)
    kits = {k["kit_number"]: k for k in world["kits"]}
    ok = validate_success(api_client.create_dispensing_record(
        create_dispensing_payload(sub1["id"], kits["K-DC1"]["id"], 1, 4),
        world["pharmacist_headers"]), expected_status=201)
    assert ok["dose_mg"] == 200, "4 x 50mg == the 200mg cap, allowed exactly"
    resp = api_client.create_dispensing_record(
        create_dispensing_payload(sub2["id"], kits["K-DC2"]["id"], 1, 5),
        world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_DOSE_EXCEEDS_PROTOCOL_MAX.value, expected_status=422)


def test_visit_window_edge_day_allowed_next_day_rejected():
    """PRD §3.6: "the nominal date of a subject's first visit is their
    `randomized_at`, and each later visit's nominal date falls exactly
    twenty-eight days after the previous one; dispensing for a visit is
    permitted only within the closed interval from three days before its nominal
    date through three days after it, and a dispensing outside that window is
    rejected with `ERR_VISIT_WINDOW_VIOLATION`."

    Design: Corner/validations/visit_window_edge_day_allowed_next_day_rejected
    """
    world = setup_pharmacy(protocol_number="P-VAL-6", kit_numbers=("K-VW1", "K-VW2"),
                           pharmacist_license="L-VAL-6")
    p_id = world["pharmacist"]["id"]
    upload_slots(world["study"]["id"], world["study_version"], [
        slot_spec(1, "K-VW1", arm_code="TRT-A"), slot_spec(2, "K-VW2", arm_code="PBO"),
    ])
    subject = randomize_subject(register_subject(world["site"]["id"], "SUB-VW", p_id)["id"], p_id)
    kits = {k["kit_number"]: k for k in world["kits"]}
    # Randomized at the default clock 2026-08-01; visit-1 window is
    # [2026-07-29, 2026-08-04] closed — dispense on the +3d edge succeeds.
    set_clock("2026-08-04T00:00:00Z")
    ok = validate_success(api_client.create_dispensing_record(
        create_dispensing_payload(subject["id"], kits["K-VW1"]["id"], 1, 1),
        world["pharmacist_headers"]), expected_status=201)
    assert ok["id"]
    # Visit-2 window is [2026-08-26, 2026-09-01]; at 2026-08-05 it fails.
    allocate_next_kit(subject["id"], p_id)
    set_clock("2026-08-05T00:00:00Z")
    resp = api_client.create_dispensing_record(
        create_dispensing_payload(subject["id"], kits["K-VW2"]["id"], 2, 1),
        world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_VISIT_WINDOW_VIOLATION.value, expected_status=422)


def test_visit_number_out_of_sequence_rejected():
    """PRD §3.6: "The sequence rule: `visit_number` must equal the count of the
    subject's existing dispensing records plus one, else
    `ERR_VISIT_OUT_OF_SEQUENCE`."

    Design: Corner/validations/visit_number_out_of_sequence_rejected
    """
    world = setup_pharmacy(protocol_number="P-VAL-7", kit_numbers=("K-SQ",),
                           pharmacist_license="L-VAL-7")
    disp_world = setup_subject_with_allocated_kit(world, subject_number="SUB-SQ")
    subject, kit = disp_world["subject"], disp_world["kit"]
    # Clock inside the visit-2 window [2026-08-26, 2026-09-01], but the subject
    # has zero prior records, so visit_number 2 is out of sequence.
    set_clock("2026-08-29T00:00:00Z")
    resp = api_client.create_dispensing_record(
        create_dispensing_payload(subject["id"], kit["id"], 2, 1),
        world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_VISIT_OUT_OF_SEQUENCE.value, expected_status=422)


def test_return_quantity_above_dispensed_rejected():
    """PRD §3.6: "The quantity must lie between one and the dispensing record's
    `quantity_dispensed`, inclusive, and each dispensing record supports at most
    one return — an out-of-range quantity or a second return against the same
    record is rejected with `ERR_QUANTITY_MISMATCH`."

    Design: Corner/validations/return_quantity_above_dispensed_rejected
    """
    world = setup_pharmacy(protocol_number="P-VAL-8", kit_numbers=("K-RQ",),
                           pharmacist_license="L-VAL-8")
    disp = setup_dispensed_subject(world, subject_number="SUB-RQ", quantity=4)
    resp = api_client.create_return(
        {"dispensing_record_id": disp["record"]["id"], "quantity_returned": 5},
        world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_QUANTITY_MISMATCH.value, expected_status=422)
    record = get_success_data(api_client.get_dispensing_record(disp["record"]["id"], SPONSOR))
    assert record["status"] == "ACTIVE"
    assert get_kit(disp["kit"]["id"])["status"] == "DISPENSED"


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / dispense_state_error_beats_dose_safety_error
# ---------------------------------------------------------------------------

def _world_with_already_dispensed_kit():
    """Kit dispensed once (visit 1, qty 4); a second dispense attempt would
    violate both the kit-state gate and the dose cap (5 x 50 = 250 > 200)."""
    world = setup_pharmacy(protocol_number="P-PRI-1", kit_numbers=("K-V",),
                           pharmacist_license="L-PRI-1")
    disp = setup_dispensed_subject(world, subject_number="SUB-V", quantity=4)
    return {**world, **disp}


def test_dispense_state_error_beats_dose_safety_error():
    """PRD §2.6: "When several checks could reject the same request, the server
    evaluates them in a fixed priority order, and the earliest failing check is
    the one whose error is returned — later checks are masked by it:" with
    "5. State admissibility" ahead of "7. Pharmaceutical safety gates — dose
    cap, lot expiry, excursion quarantine, stability budget, and open-label
    unblinding". PRD §3.6: "The kit must be `ALLOCATED` to this very subject; a
    kit in the wrong state, or allocated to a different subject, is rejected
    with `ERR_KIT_NOT_DISPENSABLE`."

    Design: Difficulty/priority_pair_validation_conflict/dispense_state_error_beats_dose_safety_error
    """
    world = _world_with_already_dispensed_kit()
    resp = api_client.create_dispensing_record(
        create_dispensing_payload(world["subject"]["id"], world["kit"]["id"], 2, 5),
        world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_KIT_NOT_DISPENSABLE.value, expected_status=409)


def test_dispense_state_error_beats_dose_safety_error_no_state_drift():
    """PRD §3.6: "The dispensed kit moves `ALLOCATED` → `DISPENSED`, its
    `units_dispensed` increases by `quantity_dispensed`". A rejected dispensing
    mutates nothing.

    Design: Difficulty/priority_pair_validation_conflict/dispense_state_error_beats_dose_safety_error
    """
    world = _world_with_already_dispensed_kit()
    api_client.create_dispensing_record(
        create_dispensing_payload(world["subject"]["id"], world["kit"]["id"], 2, 5),
        world["pharmacist_headers"])
    kit = get_kit(world["kit"]["id"])
    assert kit["status"] == "DISPENSED"
    assert kit["units_dispensed"] == 4, "the rejected second dispense must not accumulate"
    data, meta = validate_paginated(api_client.list_dispensing_records(
        SPONSOR, params={"subject_id": world["subject"]["id"]}))
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / dispense_expired_lot_safety_beats_visit_window_temporal
# ---------------------------------------------------------------------------

def _world_with_expired_lot_past_visit_window():
    """Kit ALLOCATED to a randomized subject; lot expiry 2026-09-01; the clock
    is advanced to 2026-11-09 — beyond both the lot expiry and the visit-1
    window [2026-07-29, 2026-08-04]."""
    world = setup_pharmacy(protocol_number="P-PRI-2", kit_numbers=("K-W",),
                           pharmacist_license="L-PRI2-1",
                           lot_overrides={"lot_number": "LOT-PRI-2",
                                          "expiry_date": "2026-09-01T00:00:00Z"})
    alloc = setup_subject_with_allocated_kit(world, subject_number="SUB-W")
    set_clock("2026-11-09T00:00:00Z")
    return {**world, **alloc}


def test_dispense_expired_lot_safety_beats_visit_window_temporal():
    """PRD §2.6: "the earliest failing check is the one whose error is returned"
    with "7. Pharmaceutical safety gates — dose cap, lot expiry, excursion
    quarantine, stability budget, and open-label unblinding" ahead of
    "8. Temporal gates — dispensing visit windows, monitor-visit windows and
    overlaps, and destruction-facility window conflicts". PRD §3.6: "The kit's
    lot must not have reached expiry at the logical clock (`ERR_LOT_EXPIRED`)."

    Design: Difficulty/priority_pair_validation_conflict/dispense_expired_lot_safety_beats_visit_window_temporal
    """
    world = _world_with_expired_lot_past_visit_window()
    resp = api_client.create_dispensing_record(
        create_dispensing_payload(world["subject"]["id"], world["kit"]["id"], 1, 1),
        world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_LOT_EXPIRED.value, expected_status=422)


def test_dispense_expired_lot_rejection_mutates_nothing():
    """PRD §3.6: "The kit must be `ALLOCATED` to this very subject" — on the
    rejected dispense the kit remains ALLOCATED and no record is created.

    Design: Difficulty/priority_pair_validation_conflict/dispense_expired_lot_safety_beats_visit_window_temporal
    """
    world = _world_with_expired_lot_past_visit_window()
    api_client.create_dispensing_record(
        create_dispensing_payload(world["subject"]["id"], world["kit"]["id"], 1, 1),
        world["pharmacist_headers"])
    assert get_kit(world["kit"]["id"])["status"] == "ALLOCATED"
    data, meta = validate_paginated(api_client.list_dispensing_records(
        SPONSOR, params={"subject_id": world["subject"]["id"]}))
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / dispense_then_full_return_restores_on_hand
# ---------------------------------------------------------------------------

def test_dispense_then_full_return_restores_on_hand():
    """PRD §2.10: "The ledger has a conservation invariant worth relying on:
    dispensing some quantity and later returning the same quantity leaves the
    book balance unchanged, because the increment to `units_dispensed` and the
    equal increment to `units_returned` cancel exactly."

    Design: Difficulty/compensating_invariant/dispense_then_full_return_restores_on_hand
    """
    world = setup_pharmacy(protocol_number="P-INV-2", kit_numbers=("K-I1",),
                           pharmacist_license="L-INV2-1")
    alloc = setup_subject_with_allocated_kit(world, subject_number="SUB-I")
    record = dispense_kit(alloc["subject"]["id"], alloc["kit"]["id"], 1, 4,
                          world["pharmacist"]["id"])
    after_dispense = get_kit(alloc["kit"]["id"])
    assert after_dispense["on_hand_units"] == 6, "10 - 4 after the forward dispense"
    record_return(record["id"], 4, world["pharmacist"]["id"])
    after_return = get_kit(alloc["kit"]["id"])
    assert after_return["on_hand_units"] == 10, "the compensating return restores 10"


def test_dispense_then_full_return_leaves_counters_without_drift():
    """PRD §2.10: "`on_hand_units` equals `units_received`, minus
    `units_dispensed`, plus `units_returned`, minus `units_destroyed`, minus
    `units_lost`."

    Design: Difficulty/compensating_invariant/dispense_then_full_return_restores_on_hand
    """
    world = setup_pharmacy(protocol_number="P-INV-2B", kit_numbers=("K-I1",),
                           pharmacist_license="L-INV2-1")
    alloc = setup_subject_with_allocated_kit(world, subject_number="SUB-I")
    record = dispense_kit(alloc["subject"]["id"], alloc["kit"]["id"], 1, 4,
                          world["pharmacist"]["id"])
    record_return(record["id"], 4, world["pharmacist"]["id"])
    kit = get_kit(alloc["kit"]["id"])
    assert kit["units_dispensed"] == 4
    assert kit["units_returned"] == 4
    assert kit["units_destroyed"] == 0
    assert kit["units_lost"] == 0
    assert kit["on_hand_units"] == 10 - 4 + 4 - 0 - 0
