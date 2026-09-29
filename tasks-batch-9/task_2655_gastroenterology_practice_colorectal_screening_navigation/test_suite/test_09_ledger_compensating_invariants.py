"""Exact compensations: a claim dispute that reverses the patient ledgers and a booking
cancellation that returns precisely the room minutes it consumed."""
from test_helpers import (
    apply_block_action,
    book_slot,
    cancel_slot,
    check_in,
    claim_for_booking,
    complete_exam,
    confirm_prep,
    create_block,
    dispute_claim,
    finalize_claim,
    finalize_report,
    move_clock,
    open_episode,
    read_block,
    read_booking,
    read_claim,
    read_episode,
    read_patient,
    receive_report,
    register_anesthesia_clinician,
    register_endoscopist,
    register_patient,
    register_plan,
    reprice_claim,
    specimen,
    staff_block,
    start_exam,
)

PLAN_P1 = {
    "plan_code": "P1",
    "payer_name": "Meridian Health",
    "preventive_coverage_pct": 1.00,
    "diagnostic_coinsurance_pct": 0.20,
    "deductible_cents": 150000,
    "out_of_pocket_max_cents": 400000,
    "polypectomy_carveout": "DIAGNOSTIC_CONVERTED",
    "modifier_33_honored": True,
    "anesthesia_bundled": False,
}


def _repriced_claim_awaiting_finalization():
    """Run a MAC colonoscopy with two adenomas through pathology finalization so the claim
    has already been repriced under the final pass."""
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan(**PLAN_P1)
    endoscopist = register_endoscopist()
    anesthetist = register_anesthesia_clinician()
    patient = register_patient(plan["id"], birth_date="1975-04-10")
    episode = open_episode(patient["id"], "SCREENING_AVERAGE_RISK")
    block = create_block(endoscopist["id"], anesthesia_mode="MAC")
    apply_block_action(block["id"], "PUBLISH")
    staff_block(block["id"], anesthetist["id"])
    booking = book_slot(block["id"], episode["id"], endoscopist["id"],
                        slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)
    claim = claim_for_booking(booking["id"])
    confirm_prep(episode["id"], patient["id"])
    check_in(booking["id"])
    start_exam(booking["id"], endoscopist["id"])
    complete_exam(booking["id"], endoscopist["id"], prep_quality_bbps=7,
                  polyps_removed_count=2, largest_polyp_mm=6, specimen_count=2)
    report = receive_report(booking["id"], [
        specimen("A", "TUBULAR_ADENOMA", 6),
        specimen("B", "TUBULAR_ADENOMA", 4),
    ])
    finalize_report(report["id"])
    return {
        "patient_id": patient["id"],
        "claim_id": claim["id"],
        "patient_before": read_patient(patient["id"]),
        "repriced": read_claim(claim["id"]),
    }


def test_finalizing_the_repriced_claim_commits_both_patient_ledgers():
    """A `BillingSpecialist` then finalizes a repriced claim, moving `REPRICED → FINALIZED`,
    which is the moment the claim touches the patient's ledgers: the claim's
    `deductible_applied_cents` is added to the patient's `deductible_applied_cents`, and the
    claim's `patient_responsibility_cents` is added to the patient's `oop_applied_cents`.

    `deductible_applied_cents` and `oop_applied_cents` are the patient's two running ledgers
    — the deductible consumed and the patient responsibility committed by claims that have
    reached a finalized state — and both start at 0.

    Design: Difficulty/compensating_invariant/claim_dispute_restores_patient_deductible_ledger
    """
    scenario = _repriced_claim_awaiting_finalization()

    assert scenario["patient_before"]["deductible_applied_cents"] == 0
    assert scenario["patient_before"]["oop_applied_cents"] == 0
    assert scenario["repriced"]["status"] == "REPRICED"
    assert scenario["repriced"]["deductible_applied_cents"] == 150000
    assert scenario["repriced"]["patient_responsibility_cents"] == 167740
    assert scenario["repriced"]["reprice_count"] == 1

    finalized = finalize_claim(scenario["claim_id"])
    patient = read_patient(scenario["patient_id"])

    assert finalized["status"] == "FINALIZED"
    assert patient["deductible_applied_cents"] == 150000
    assert patient["oop_applied_cents"] == 167740


def test_disputing_the_claim_reverses_the_ledgers_and_leaves_the_money_fields_alone():
    """Disputing a finalized claim moves `FINALIZED → DISPUTED`, requires a `dispute_reason` —
    omitting it is `ERR_INVALID_REQUEST` — and is the exact compensation of the finalize: the
    claim's `deductible_applied_cents` is subtracted from the patient's
    `deductible_applied_cents` and the claim's `patient_responsibility_cents` is subtracted
    from the patient's `oop_applied_cents`, while **every money field on the claim itself is
    left unchanged** so that the reversal is exact and the two patient ledgers return to
    precisely the values they held before the finalize.

    Design: Difficulty/compensating_invariant/claim_dispute_restores_patient_deductible_ledger
    """
    scenario = _repriced_claim_awaiting_finalization()
    finalize_claim(scenario["claim_id"])
    disputed = dispute_claim(scenario["claim_id"], "Patient appealed the preventive coding")
    patient = read_patient(scenario["patient_id"])

    assert disputed["status"] == "DISPUTED"
    assert disputed["deductible_applied_cents"] == 150000
    assert disputed["patient_responsibility_cents"] == 167740
    assert patient["deductible_applied_cents"] == 0
    assert patient["oop_applied_cents"] == 0


def test_repricing_a_disputed_claim_recomputes_the_same_share_and_counts_the_pass():
    """Repricing a disputed claim moves `DISPUTED → REPRICED` and re-runs the final pass
    against current booking and pathology state, incrementing `reprice_count`.

    Pricing reads the patient's `deductible_applied_cents` and `oop_applied_cents` ledgers as
    they stand at pricing time, and only claims that have reached `FINALIZED` have
    contributed to those ledgers.

    Design: Difficulty/compensating_invariant/claim_dispute_restores_patient_deductible_ledger
    """
    scenario = _repriced_claim_awaiting_finalization()
    finalize_claim(scenario["claim_id"])
    dispute_claim(scenario["claim_id"], "Patient appealed the preventive coding")
    repriced = reprice_claim(scenario["claim_id"])
    patient = read_patient(scenario["patient_id"])

    assert repriced["status"] == "REPRICED"
    assert repriced["reprice_count"] == 2
    assert repriced["deductible_applied_cents"] == 150000
    assert repriced["patient_responsibility_cents"] == 167740
    assert patient["deductible_applied_cents"] == 0
    assert patient["oop_applied_cents"] == 0


def _block_holding_two_bookings():
    """A moderate-sedation block with two 45-minute bookings, at 13:00Z and 15:00Z."""
    move_clock("2026-09-01T00:00:00Z")
    plan = register_plan()
    endoscopist = register_endoscopist()
    episodes = []
    for mrn, birth_date in (("MRN-0001", "1975-04-10"),
                            ("MRN-0002", "1972-06-22"),
                            ("MRN-0003", "1970-02-14")):
        patient = register_patient(plan["id"], mrn=mrn, birth_date=birth_date)
        episodes.append(open_episode(patient["id"], "SCREENING_AVERAGE_RISK"))
    block = create_block(endoscopist["id"], turnover_minutes=15, max_procedures=8)
    published = apply_block_action(block["id"], "PUBLISH")
    booking_a = book_slot(block["id"], episodes[0]["id"], endoscopist["id"],
                          slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)
    book_slot(block["id"], episodes[1]["id"], endoscopist["id"],
              slot_start_utc="2026-09-15T15:00:00Z", duration_minutes=45)
    return {
        "block_id": block["id"],
        "endoscopist_id": endoscopist["id"],
        "published": published,
        "booking_a_id": booking_a["id"],
        "claim_a_id": claim_for_booking(booking_a["id"])["id"],
        "episode_a": episodes[0],
        "episode_b": episodes[1],
        "episode_c": episodes[2],
    }


def test_publish_opens_the_full_capacity_and_two_bookings_consume_their_buffered_minutes():
    """`PUBLISH` moves `DRAFT → PUBLISHED` and sets `remaining_minutes` equal to
    `capacity_minutes`, opening the block for booking.

    Step three selects `complexity_tier` **from `base_allowed_cents` alone**: `TIER_3` when
    the base is 250000 cents or more, `TIER_2` when it is 150000 cents or more but below
    that, and `TIER_1` otherwise.

    Design: Difficulty/compensating_invariant/booking_cancel_restores_session_minute_ledger
    """
    scenario = _block_holding_two_bookings()

    assert scenario["published"]["capacity_minutes"] == 480
    assert scenario["published"]["remaining_minutes"] == 480

    block = read_block(scenario["block_id"])
    assert block["booked_minutes"] == 120
    assert block["remaining_minutes"] == 360
    assert read_claim(scenario["claim_a_id"])["allowed_amount_cents"] == 170750


def test_cancellation_returns_exactly_the_minutes_consumed_and_voids_the_claim():
    """A `ReferralCoordinator` or `PracticeAdmin` cancels a booking that is still in `BOOKED`,
    supplying a `cancellation_reason`; the booking moves `BOOKED → CANCELLED`,
    `released_minutes` is set to that booking's `duration_minutes` plus the block's
    `turnover_minutes` — exactly the quantity the booking had consumed, and zero for every
    booking in any other status — and the block's ledger is recomputed so that booked and
    remaining minutes again sum to capacity. Cancelling the underlying booking voids the claim
    from either `PROVISIONAL_PRICED → VOIDED` or `REPRICED → VOIDED`, zeroing
    `base_allowed_cents`, `allowed_amount_cents`, `deductible_applied_cents`,
    `coinsurance_cents`, `patient_responsibility_cents`, and `plan_paid_cents` and emptying
    `line_items`.

    Design: Difficulty/compensating_invariant/booking_cancel_restores_session_minute_ledger
    """
    scenario = _block_holding_two_bookings()
    cancelled = cancel_slot(scenario["booking_a_id"], "PATIENT_RESCHEDULED")
    block = read_block(scenario["block_id"])
    claim = read_claim(scenario["claim_a_id"])

    assert cancelled["status"] == "CANCELLED"
    assert cancelled["released_minutes"] == 60
    assert block["booked_minutes"] == 60
    assert block["remaining_minutes"] == 420
    assert claim["status"] == "VOIDED"
    assert claim["base_allowed_cents"] == 0
    assert claim["allowed_amount_cents"] == 0
    assert claim["patient_responsibility_cents"] == 0
    assert claim["plan_paid_cents"] == 0
    assert claim["line_items"] == []
    assert read_episode(scenario["episode_a"]["id"])["clinical_status"] == "OPEN"


def test_the_released_slot_can_be_rebooked_at_the_same_start_instant():
    """The episode reverts `PROCEDURE_SCHEDULED → OPEN`, the claim is voided as described in
    Section 3.9, and the block's `version` increments by 1.

    The invariant that booked and remaining minutes sum to capacity holds at every observable
    instant.

    Design: Difficulty/compensating_invariant/booking_cancel_restores_session_minute_ledger
    """
    scenario = _block_holding_two_bookings()
    cancel_slot(scenario["booking_a_id"], "PATIENT_RESCHEDULED")

    booking_c = book_slot(scenario["block_id"], scenario["episode_c"]["id"],
                          scenario["endoscopist_id"],
                          slot_start_utc="2026-09-15T13:00:00Z", duration_minutes=45)
    block = read_block(scenario["block_id"])

    assert booking_c["status"] == "BOOKED"
    assert block["booked_minutes"] == 120
    assert block["remaining_minutes"] == 360
    assert read_episode(scenario["episode_c"]["id"])["clinical_status"] == "PROCEDURE_SCHEDULED"
    assert read_episode(scenario["episode_b"]["id"])["clinical_status"] == "PROCEDURE_SCHEDULED"
    assert read_booking(scenario["booking_a_id"])["status"] == "CANCELLED"
