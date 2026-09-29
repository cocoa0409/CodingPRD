"""Forward operation, then the compensation that has to undo it exactly: block
minutes, cabinet units, and claim money."""
import pytest

from test_helpers import (
    SCHEDULER,
    api_client,
    assert_money_identity,
    cancel_case,
    confirm_case,
    create_block,
    create_evaluation_for,
    create_lot,
    create_patient,
    dispose_reservation,
    draft_case,
    fetch_block,
    fetch_case,
    fetch_determination,
    fetch_evaluation,
    fetch_lot,
    fetch_practice,
    fetch_reservation,
    hold_case_on_block,
    open_determination,
    record_payer_response,
    reserve_from_lot,
    service_line,
    set_env_clock,
    setup_practice_with_roster,
    sign_evaluation_as,
    submit_determination,
    validate_success,
    verify_evaluation_as,
)

CLOCK = "2026-09-11T10:00:00Z"
DAY_OF = "2026-09-14T12:00:00Z"

# --- block_minute_conservation_on_cancel ----------------------------------------


def _confirmed_local_only_case_on_a_240_minute_block():
    """A LOCAL_ONLY case needs no permit at all, so a bare practice can carry it all
    the way to CONFIRMED. Returns (env, block, case, evaluation)."""
    env = setup_practice_with_roster(
        clock=CLOCK, recovery_bay_count=2, turnover_buffer_minutes=15
    )
    block = create_block(
        env["practice_id"], env["surgeon"]["id"],
        "2026-09-14T13:00:00Z", "2026-09-14T17:00:00Z", room_code="OR-1",
        release_deadline_hours=48,
    )
    case = draft_case(
        env,
        planned_anesthesia_level="LOCAL_ONLY",
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T14:00:00Z",
        with_monitor=False,
        procedure_category="THIRD_MOLAR",
        total_charge_cents=50000,
    )
    hold_case_on_block(case["id"], block["id"])

    set_env_clock(env, DAY_OF)
    evaluation = create_evaluation_for(env, case["id"], env["monitor"]["id"])
    sign_evaluation_as(evaluation["id"], env["monitor"]["id"])
    evaluation = verify_evaluation_as(
        env, evaluation["id"], intent="CLEAR",
        solids_minutes_ago=480, clears_minutes_ago=60,
    )
    case = confirm_case(case["id"], block["id"])
    return env, fetch_block(block["id"]), case, evaluation


def test_cancelling_returns_minutes_to_the_open_pool_not_to_released(api):
    """PRD 3.6: "Cancelling from `BLOCK_HELD` runs a four-hop chain: hop one subtracts the
    case's `duration_minutes` from the block's `committed_minutes`, recomputes
    `open_minutes` and `utilization_pct`, and increments the block's `version`".
    PRD 3.3: "The invariant that holds after every write is that `committed_minutes`,
    `released_minutes`, and `open_minutes` sum to exactly `block_duration_minutes`".

    Design: Difficulty/compensating_invariant/block_minute_conservation_on_cancel
    """
    env, block, case, evaluation = _confirmed_local_only_case_on_a_240_minute_block()

    assert block["block_duration_minutes"] == 240
    assert block["committed_minutes"] == 60
    assert block["released_minutes"] == 0
    assert block["open_minutes"] == 180
    assert float(block["utilization_pct"]) == pytest.approx(25.00, abs=0.001)

    cancel_case(case["id"], "PATIENT_REQUEST")

    after = fetch_block(block["id"])
    assert after["committed_minutes"] == 0
    assert after["released_minutes"] == 0
    assert after["open_minutes"] == 240
    assert float(after["utilization_pct"]) == pytest.approx(0.00, abs=0.001)
    assert (
        after["committed_minutes"] + after["released_minutes"] + after["open_minutes"]
        == after["block_duration_minutes"]
    )
    assert after["version"] == block["version"] + 1


def test_the_cancelled_case_keeps_its_clearance_and_its_voided_scores(api):
    """PRD 3.6: "In all three origins the case's `clearance_status` is deliberately left
    untouched, and cancelling an already-`CANCELLED` or `COMPLETED` case is an
    `ERR_INVALID_STATE_TRANSITION`."
    PRD 3.5: "One in `VERIFIED` moves to `VOIDED` with both scores retained."

    Design: Difficulty/compensating_invariant/block_minute_conservation_on_cancel
    """
    env, block, case, evaluation = _confirmed_local_only_case_on_a_240_minute_block()
    assert case["scheduling_status"] == "CONFIRMED"
    assert case["clearance_status"] == "CLEARED"
    assert float(evaluation["final_risk_score"]) == pytest.approx(10.0, abs=0.001)

    cancelled = cancel_case(case["id"], "PATIENT_REQUEST")
    assert cancelled["scheduling_status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "PATIENT_REQUEST"
    assert fetch_case(case["id"])["clearance_status"] == "CLEARED"

    voided = fetch_evaluation(evaluation["id"])
    assert voided["status"] == "VOIDED"
    assert float(voided["final_risk_score"]) == pytest.approx(10.0, abs=0.001)
    assert float(voided["provisional_risk_score"]) == pytest.approx(10.0, abs=0.001)
    assert voided["risk_band"] == "LOW"


# --- implant_unit_conservation_on_release ---------------------------------------


def _two_reservations_on_one_consignment_lot():
    """Five units on the shelf, two reserved on line A and one on line B."""
    env = setup_practice_with_roster(clock=CLOCK, consignment_credit_limit_cents=500000)
    lot = create_lot(
        env["practice_id"],
        manufacturer_code="NOBEL",
        catalog_reference="NB-4310",
        diameter_mm=4.3,
        length_mm=10.0,
        unit_cost_cents=30000,
        quantity_on_hand=5,
        expiry_date="2027-01-31T00:00:00Z",
        is_consignment=True,
    )
    case = draft_case(
        env,
        planned_anesthesia_level="LOCAL_ONLY",
        planned_start="2026-09-20T13:00:00Z",
        planned_end="2026-09-20T14:00:00Z",
        with_monitor=False,
        procedure_category="IMPLANT",
        total_charge_cents=90000,
    )
    reservation_a = reserve_from_lot(case["id"], lot["id"], 2)
    reservation_b = reserve_from_lot(case["id"], lot["id"], 1)
    return env, lot, case, reservation_a, reservation_b


def test_releasing_a_reservation_returns_units_and_collapses_the_liability(api):
    """PRD 3.7: "On `RELEASED` the fixtures come back to the shelf: `quantity_on_hand` is
    deliberately unchanged while `quantity_reserved` is decremented by the reservation's
    `quantity`, the tiered `restocking_fee_cents` is charged, `consignment_credit_cents`
    drops to 0, and `consignment_liability_cents` becomes the restocking fee."
    PRD 3.7: "The practice's rolling `consignment_committed_cents` is the sum of
    `consignment_liability_cents` over the practice's reservations whose `status` is `HELD`
    or `CONSUMED`; released and shorted rows drop out."

    Design: Difficulty/compensating_invariant/implant_unit_conservation_on_release
    """
    env, lot, case, reservation_a, reservation_b = _two_reservations_on_one_consignment_lot()

    before = fetch_lot(lot["id"])
    assert before["quantity_on_hand"] == 5
    assert before["quantity_reserved"] == 3
    assert before["available_quantity"] == 2
    assert reservation_a["line_subtotal_cents"] == 60000
    assert reservation_a["restocking_fee_cents"] == 6000
    assert reservation_a["consignment_credit_cents"] == 12000
    assert reservation_a["consignment_liability_cents"] == 48000
    assert fetch_practice(env["practice_id"])["consignment_committed_cents"] == 72000

    released = dispose_reservation(reservation_a["id"], "RELEASED")
    assert released["status"] == "RELEASED"
    assert released["consignment_credit_cents"] == 0
    assert released["consignment_liability_cents"] == 6000

    after = fetch_lot(lot["id"])
    assert after["quantity_on_hand"] == 5
    assert after["quantity_reserved"] == 1
    assert after["available_quantity"] == 4
    assert after["quantity_on_hand"] == after["available_quantity"] + after["quantity_reserved"]
    assert fetch_practice(env["practice_id"])["consignment_committed_cents"] == 24000


def test_shorting_a_reservation_is_the_only_branch_that_destroys_a_unit(api):
    """PRD 3.7: "On `SHORTED` the fixtures are physically unaccounted for, so both
    `quantity_on_hand` and `quantity_reserved` are decremented, `restocking_fee_cents` and
    `consignment_credit_cents` are both 0, and `consignment_liability_cents` becomes the
    full `line_subtotal_cents`."

    Design: Difficulty/compensating_invariant/implant_unit_conservation_on_release
    """
    env, lot, case, reservation_a, reservation_b = _two_reservations_on_one_consignment_lot()
    assert reservation_b["line_subtotal_cents"] == 30000
    assert reservation_b["restocking_fee_cents"] == 4500
    assert reservation_b["consignment_credit_cents"] == 6000
    assert reservation_b["consignment_liability_cents"] == 24000

    dispose_reservation(reservation_a["id"], "RELEASED")
    assert fetch_lot(lot["id"])["quantity_on_hand"] == 5

    shorted = dispose_reservation(reservation_b["id"], "SHORTED")
    assert shorted["status"] == "SHORTED"
    assert shorted["restocking_fee_cents"] == 0
    assert shorted["consignment_credit_cents"] == 0
    assert shorted["consignment_liability_cents"] == 30000

    after = fetch_lot(lot["id"])
    assert after["quantity_on_hand"] == 4
    assert after["quantity_reserved"] == 0
    assert after["available_quantity"] == 4
    assert after["quantity_on_hand"] == after["available_quantity"] + after["quantity_reserved"]
    assert fetch_practice(env["practice_id"])["consignment_committed_cents"] == 0
    assert fetch_reservation(reservation_b["id"])["consignment_liability_cents"] == 30000


# --- benefit_money_conservation_across_revision_loop -----------------------------

TOTAL_CHARGE_CENTS = 111110


def _pended_split_determination():
    """A SPLIT, medical-first claim on two equal lines, bounced back by the payer."""
    env = setup_practice_with_roster(clock=CLOCK)
    patient = create_patient(
        env["practice_id"],
        full_name="Pat Money",
        medical_plan_active=True,
        dental_plan_active=True,
        dental_annual_remaining_cents=150000,
    )
    case = draft_case(
        env,
        planned_anesthesia_level="LOCAL_ONLY",
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T14:00:00Z",
        with_monitor=False,
        patient_id=patient["id"],
        procedure_category="TRAUMA",
        total_charge_cents=TOTAL_CHARGE_CENTS,
    )
    set_env_clock(env, DAY_OF)
    evaluation = create_evaluation_for(env, case["id"], env["monitor"]["id"])
    sign_evaluation_as(evaluation["id"], env["monitor"]["id"])
    verify_evaluation_as(
        env, evaluation["id"], intent="CLEAR",
        solids_minutes_ago=480, clears_minutes_ago=60,
    )
    determination = open_determination(
        case["id"],
        [
            service_line("D7140", 55555, "DENTAL"),
            service_line("21445", 55555, "MEDICAL"),
        ],
    )
    submit_determination(determination["id"])
    pended = record_payer_response(
        determination["id"], "PENDED", pend_reason="MEDICAL_NECESSITY_REVIEW"
    )
    return env, patient, case, pended


def _patient_dental_remaining(patient_id):
    return validate_success(api_client.get_patient(patient_id, SCHEDULER))[
        "dental_annual_remaining_cents"
    ]


def test_resubmitting_reprices_against_a_fresh_snapshot_and_reproduces_it(api):
    """PRD 3.8: "Submission then moves `status` to `SUBMITTED`, increases
    `submission_count` by 1, clears `pend_reason` to null, refreshes
    `dental_annual_remaining_snapshot_cents` from the patient's current
    `dental_annual_remaining_cents`, and recomputes the route, the payer, and the whole
    allocation against that fresh snapshot."
    PRD 3.8: "An `APPROVED` outcome is terminal and settles the annual maximum: the
    patient's `dental_annual_remaining_cents` is reduced by `dental_allowed_cents`, never
    below 0, and the patient's `version` increments."

    Design: Difficulty/compensating_invariant/benefit_money_conservation_across_revision_loop
    """
    env, patient, case, pended = _pended_split_determination()
    assert pended["route"] == "SPLIT"
    assert pended["primary_payer"] == "MEDICAL"
    assert pended["status"] == "PENDED"
    assert pended["submission_count"] == 1
    assert pended["pend_reason"] == "MEDICAL_NECESSITY_REVIEW"
    assert pended["medical_allowed_cents"] == 88888
    assert pended["dental_allowed_cents"] == 11112
    assert pended["patient_responsibility_cents"] == 11110
    assert_money_identity(pended, TOTAL_CHARGE_CENTS)
    assert pended["dental_annual_remaining_snapshot_cents"] == 150000
    assert _patient_dental_remaining(patient["id"]) == 150000

    resubmitted = submit_determination(pended["id"])
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["submission_count"] == 2
    assert resubmitted["pend_reason"] is None
    assert resubmitted["dental_annual_remaining_snapshot_cents"] == 150000
    assert resubmitted["medical_allowed_cents"] == 88888
    assert resubmitted["dental_allowed_cents"] == 11112
    assert resubmitted["patient_responsibility_cents"] == 11110
    assert_money_identity(resubmitted, TOTAL_CHARGE_CENTS)
    assert _patient_dental_remaining(patient["id"]) == 150000


def test_a_denial_moves_the_whole_charge_onto_the_patient_and_spends_nothing(api):
    """PRD 3.8: "A `DENIED` outcome must carry a `denial_reason` of `NOT_COVERED_BENEFIT`,
    `EXCEEDS_ANNUAL_MAX`, or `NO_MEDICAL_NECESSITY`; it is also terminal, and it zeroes both
    `medical_allowed_cents` and `dental_allowed_cents` while setting
    `patient_responsibility_cents` to the case's full `total_charge_cents`, so the money
    identity survives the denial."
    PRD 3.8: "On a denial the patient's `dental_annual_remaining_cents` is **not**
    decremented — nothing was allowed, so nothing was consumed."

    Design: Difficulty/compensating_invariant/benefit_money_conservation_across_revision_loop
    """
    env, patient, case, pended = _pended_split_determination()
    submit_determination(pended["id"])

    denied = record_payer_response(
        pended["id"], "DENIED", denial_reason="NO_MEDICAL_NECESSITY"
    )
    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "NO_MEDICAL_NECESSITY"
    assert denied["medical_allowed_cents"] == 0
    assert denied["dental_allowed_cents"] == 0
    assert denied["patient_responsibility_cents"] == TOTAL_CHARGE_CENTS
    assert_money_identity(denied, TOTAL_CHARGE_CENTS)
    assert denied["submission_count"] == 2

    assert _patient_dental_remaining(patient["id"]) == 150000
    assert fetch_determination(pended["id"])["patient_responsibility_cents"] == TOTAL_CHARGE_CENTS
