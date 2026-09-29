"""Writes gated on another entity's live state: practice privilege at confirmation,
lot status at reservation, and evaluation status at submission."""
import pytest

from test_helpers import (
    assert_instant_equals,
    ADMIN,
    BENEFITS,
    INVENTORY,
    SCHEDULER,
    api_client,
    clear_case,
    confirm_case,
    create_block,
    create_evaluation_for,
    create_lot,
    draft_case,
    fetch_block,
    fetch_case,
    fetch_evaluation,
    fetch_lot,
    fetch_permit,
    fetch_practice,
    get_success_data,
    hold_case_on_block,
    open_determination,
    quarantine_lot,
    record_inspection_result,
    reserve_from_lot,
    schedule_inspection,
    service_line,
    set_env_clock,
    setup_practice_with_roster,
    setup_permitted_practice,
    sign_evaluation_as,
    submit_determination,
    validate_error,
    validate_paginated,
    verify_evaluation_as,
)

CLOCK = "2026-09-11T10:00:00Z"

# --- case_confirmation_depends_on_practice_privilege_state ---------------------


def _faultless_case_under_a_suspended_practice():
    """A CLEARED, staffed, block-holding MODERATE_SEDATION case whose only problem is
    that the office's permit was suspended after the block was held."""
    env = setup_permitted_practice("MODERATE_SEDATION", clock=CLOCK)
    block = create_block(
        env["practice_id"], env["surgeon"]["id"],
        "2026-09-14T13:00:00Z", "2026-09-14T17:00:00Z", room_code="OR-1",
    )
    case = draft_case(
        env,
        planned_anesthesia_level="MODERATE_SEDATION",
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T14:00:00Z",
        procedure_category="IMPLANT",
    )
    hold_case_on_block(case["id"], block["id"])
    second = schedule_inspection(env["permit"]["id"], "2026-09-13T10:00:00Z")
    set_env_clock(env, "2026-09-13T10:00:00Z")
    record_inspection_result(second["id"], 0, 0, 1)
    set_env_clock(env, "2026-09-14T12:00:00Z")
    clear_case(env, case["id"])
    return env, case, block


def test_confirmation_reads_the_practice_privilege_live_and_refuses(api):
    """PRD 3.4: "Fourth is the sedation privilege test. The practice's
    `sedation_privilege_state` must admit the case's `planned_anesthesia_level`:
    `UNPERMITTED` and `SUSPENDED` both block every level above `LOCAL_ONLY`,
    `RESTRICTED` blocks `DEEP_SEDATION_GENERAL` while admitting `MINIMAL_SEDATION` and
    `MODERATE_SEDATION`, and `PERMITTED` admits all four."
    PRD 2.10: "`sedation_privilege_state` follows the permit mapping of §2.10 and takes
    one of `UNPERMITTED`, `PERMITTED`, `RESTRICTED`, or `SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/case_confirmation_depends_on_practice_privilege_state
    """
    env, case, block = _faultless_case_under_a_suspended_practice()

    faultless = fetch_case(case["id"])
    assert faultless["clearance_status"] == "CLEARED"
    assert faultless["scheduling_status"] == "BLOCK_HELD"
    assert fetch_practice(env["practice_id"])["sedation_privilege_state"] == "SUSPENDED"

    before = fetch_block(block["id"])
    response = api_client.confirm_case(
        case["id"], {"expected_block_version": before["version"]}, SCHEDULER
    )
    validate_error(response, "ERR_SEDATION_PRIVILEGE_UNAVAILABLE", 409)

    assert fetch_case(case["id"])["scheduling_status"] == "BLOCK_HELD"
    after = fetch_block(block["id"])
    assert after["committed_minutes"] == 60
    assert float(after["utilization_pct"]) == pytest.approx(25.00, abs=0.001)
    assert after["version"] == before["version"], (
        "the refused confirmation wrote nothing to the ledger"
    )


def test_reinstating_the_permit_lets_the_identical_confirmation_through(api):
    """PRD 3.2: "And a `PASSED` result against a `SUSPENDED` permit whose
    `drill_compliance_ratio` is at or above 0.75 reinstates it to `ACTIVE`, clearing
    `last_enforcement_reason` to null, restoring the privilege to `PERMITTED`, and
    incrementing the permit's `version` — but `expires_at` is not extended, so a permit
    suspended late in its term returns with whatever time remained."
    PRD 3.4: "A confirmation that survives all eleven gates advances the case's
    `scheduling_status` from `BLOCK_HELD` to `CONFIRMED` and increments the case's
    `version`."

    Design: Difficulty/cross_entity_state_dependency/case_confirmation_depends_on_practice_privilege_state
    """
    env, case, block = _faultless_case_under_a_suspended_practice()

    third = schedule_inspection(env["permit"]["id"], "2026-09-14T12:30:00Z")
    set_env_clock(env, "2026-09-14T12:30:00Z")
    result = record_inspection_result(third["id"], 1, 1, 0)
    assert result["inspection_score"] == 91, (
        f"one minor and one major cost 9 points, got {result['inspection_score']}"
    )
    assert result["status"] == "PASSED"

    permit = fetch_permit(env["permit"]["id"])
    assert permit["status"] == "ACTIVE"
    assert permit["last_enforcement_reason"] is None
    assert_instant_equals(permit["expires_at"], "2028-09-12T10:00:00Z")
    assert fetch_practice(env["practice_id"])["sedation_privilege_state"] == "PERMITTED"

    confirmed = confirm_case(case["id"], block["id"])
    assert confirmed["scheduling_status"] == "CONFIRMED"
    assert confirmed["clearance_status"] == "CLEARED"
    ledger = fetch_block(block["id"])
    assert ledger["committed_minutes"] == 60
    assert float(ledger["utilization_pct"]) == pytest.approx(25.00, abs=0.001)


# --- reservation_creation_depends_on_lot_status --------------------------------

def _recalled_and_healthy_sibling_lots():
    """Two identical lots, one quarantined on a recall and one left AVAILABLE."""
    env = setup_practice_with_roster(clock=CLOCK, consignment_credit_limit_cents=500000)
    case = draft_case(
        env,
        planned_anesthesia_level="LOCAL_ONLY",
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T14:00:00Z",
        procedure_category="IMPLANT",
        total_charge_cents=200000,
        with_monitor=False,
    )
    lot_r = create_lot(
        env["practice_id"], diameter_mm=4.3, length_mm=10.0, unit_cost_cents=20000,
        quantity_on_hand=5, expiry_date="2027-06-30T00:00:00Z",
    )
    lot_s = create_lot(
        env["practice_id"], diameter_mm=4.3, length_mm=10.0, unit_cost_cents=20000,
        quantity_on_hand=5, expiry_date="2027-06-30T00:00:00Z",
    )
    quarantine_lot(lot_r["id"], "Manufacturer recall of sterility barrier")
    return env, case, lot_r, lot_s


def test_a_quarantined_parent_lot_answers_before_the_stock_gate(api):
    """PRD 3.7: "Quarantine moves the lot's `status` from `AVAILABLE` to `QUARANTINED`
    and forces its `available_quantity` to 0 so nothing further can be drawn from it."
    PRD 3.7: "Four gates run in ascending order: the stale-lot check of §2.7 answering
    `ERR_STALE_LOT_VERSION`; then the lot's `status` must not be `QUARANTINED`, or the
    answer is `ERR_LOT_UNAVAILABLE` (HTTP 409); then the lot's `available_quantity` must
    be at least the requested `quantity` and the lot's `expiry_date` must fall after the
    case's `planned_start`, or the answer is `ERR_IMPLANT_STOCK_INSUFFICIENT` (HTTP 409)
    — stock that expires before the operation is no stock at all; then the consignment
    credit test described below."

    Design: Difficulty/cross_entity_state_dependency/reservation_creation_depends_on_lot_status
    """
    env, case, lot_r, lot_s = _recalled_and_healthy_sibling_lots()

    recalled = fetch_lot(lot_r["id"])
    assert recalled["status"] == "QUARANTINED"
    assert recalled["available_quantity"] == 0
    assert recalled["quantity_on_hand"] == 5

    response = api_client.create_reservation(
        {
            "case_id": case["id"],
            "lot_id": lot_r["id"],
            "quantity": 2,
            "expected_lot_version": recalled["version"],
        },
        INVENTORY,
    )
    validate_error(response, "ERR_LOT_UNAVAILABLE", 409)

    assert fetch_lot(lot_r["id"])["quantity_reserved"] == 0
    rows, _meta = validate_paginated(
        api_client.list_reservations(INVENTORY, {"lot_id": lot_r["id"]})
    )
    assert rows == [], "the refused reservation created no row"


def test_the_identical_request_succeeds_against_the_available_sibling(api):
    """PRD 3.7: "Creating a reservation in either path stamps its `status` `HELD`,
    computes all four money fields, adds the `quantity` to the lot's
    `quantity_reserved`, recomputes the lot's `available_quantity`, increments the lot's
    `version`, recomputes and re-checks the practice's `consignment_committed_cents`,
    and increments the practice's `version`."
    PRD 3.7: "an owned — that is, non-consignment — lot still contributes its full
    subtotal, because the consignment flag suppresses only the credit, never the
    exposure."

    Lot status is the only differing input between the two calls.

    Design: Difficulty/cross_entity_state_dependency/reservation_creation_depends_on_lot_status
    """
    env, case, lot_r, lot_s = _recalled_and_healthy_sibling_lots()

    reservation = reserve_from_lot(case["id"], lot_s["id"], quantity=2)

    assert reservation["status"] == "HELD"
    assert reservation["line_subtotal_cents"] == 40000
    assert reservation["restocking_fee_cents"] == 6000, (
        f"a 40000 subtotal sits in the fifteen percent tier, got {reservation['restocking_fee_cents']}"
    )
    assert reservation["consignment_credit_cents"] == 0, "lot S is owned, not consignment"
    assert reservation["consignment_liability_cents"] == 40000

    healthy = fetch_lot(lot_s["id"])
    assert healthy["quantity_reserved"] == 2
    assert healthy["available_quantity"] == 3
    assert fetch_practice(env["practice_id"])["consignment_committed_cents"] == 40000


# --- determination_submission_depends_on_evaluation_status ---------------------

SPLIT_DENTAL_PATIENT = {
    "medical_plan_active": True,
    "dental_plan_active": True,
    "dental_annual_remaining_cents": 150000,
}


def _draft_determination_over_a_merely_signed_evaluation():
    """A DRAFT dental-first determination on a case whose evaluation has been signed
    but not yet verified."""
    env = setup_practice_with_roster(clock=CLOCK, patient_overrides=SPLIT_DENTAL_PATIENT)
    case = draft_case(
        env,
        planned_anesthesia_level="LOCAL_ONLY",
        planned_start="2026-09-14T13:00:00Z",
        planned_end="2026-09-14T14:00:00Z",
        procedure_category="THIRD_MOLAR",
        total_charge_cents=100000,
    )
    evaluation = create_evaluation_for(env, case["id"], env["monitor"]["id"])
    sign_evaluation_as(evaluation["id"], env["monitor"]["id"])
    set_env_clock(env, "2026-09-14T12:00:00Z")
    determination = open_determination(
        case["id"], [service_line("D7240", 100000, "DENTAL")]
    )
    return env, case, evaluation, determination


def test_submission_is_refused_while_the_evaluation_is_only_signed(api):
    """PRD 3.8: "A determination may be submitted from `DRAFT` or resubmitted from
    `PENDED`, and either way the case must already carry a pre-anesthesia evaluation
    whose `status` is `VERIFIED` — a claim cannot precede documented clearance — or the
    answer is `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."
    PRD 3.8: "Routing reads only the patient's two coverage flags. When both
    `medical_plan_active` and `dental_plan_active` are true the `route` is `SPLIT`"

    Design: Difficulty/cross_entity_state_dependency/determination_submission_depends_on_evaluation_status
    """
    env, case, evaluation, determination = (
        _draft_determination_over_a_merely_signed_evaluation()
    )

    assert determination["status"] == "DRAFT"
    assert determination["route"] == "SPLIT"
    assert determination["primary_payer"] == "DENTAL"
    assert determination["submission_count"] == 0
    assert fetch_evaluation(evaluation["id"])["status"] == "SIGNED"

    response = api_client.submit_determination(determination["id"], {}, BENEFITS)
    validate_error(response, "ERR_INVALID_STATE_TRANSITION", 409)

    unchanged = get_success_data(api_client.get_determination(determination["id"], ADMIN))
    assert unchanged["status"] == "DRAFT"
    assert unchanged["submission_count"] == 0


def test_verification_unblocks_submission_and_the_dental_first_waterfall(api):
    """PRD 3.8: "Submission then moves `status` to `SUBMITTED`, increases
    `submission_count` by 1, clears `pend_reason` to null, refreshes
    `dental_annual_remaining_snapshot_cents` from the patient's current
    `dental_annual_remaining_cents`, and recomputes the route, the payer, and the whole
    allocation against that fresh snapshot."
    PRD 3.8: "An `APPROVED` outcome is terminal and settles the annual maximum: the
    patient's `dental_annual_remaining_cents` is reduced by `dental_allowed_cents`, never
    below 0, and the patient's `version` increments."

    Dental takes half the gross line, medical then eighty percent of what is left, and
    the patient's own annual maximum is untouched because no payer has approved yet.

    Design: Difficulty/cross_entity_state_dependency/determination_submission_depends_on_evaluation_status
    """
    env, case, evaluation, determination = (
        _draft_determination_over_a_merely_signed_evaluation()
    )

    verify_evaluation_as(env, evaluation["id"], intent="CLEAR")
    assert fetch_evaluation(evaluation["id"])["status"] == "VERIFIED"
    assert fetch_case(case["id"])["clearance_status"] == "CLEARED"

    submitted = submit_determination(determination["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submission_count"] == 1
    assert submitted["dental_annual_remaining_snapshot_cents"] == 150000
    assert submitted["dental_allowed_cents"] == 50000
    assert submitted["medical_allowed_cents"] == 40000
    assert submitted["patient_responsibility_cents"] == 10000

    patient = get_success_data(api_client.get_patient(env["patient"]["id"], ADMIN))
    assert patient["dental_annual_remaining_cents"] == 150000, (
        "only an APPROVED payer response draws the annual maximum down"
    )
