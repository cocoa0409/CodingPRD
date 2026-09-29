"""Recording and undoing a dose: outcome branches, the void compensation and
the conserved unit invariant on the lot."""

import pytest

from test_helpers import *  # noqa: F401,F403


def _administered_dose():
    """Two units prepared and then administered against a four-unit lot."""
    ctx = setup_dose_ready(
        school_overrides={"name": "Owens Elementary", "building_code": "OWE16"},
        student_overrides={"full_name": "Sana Weber", "grade_level": 7,
                           "date_of_birth": "2013-09-17T00:00:00Z"},
        lot_overrides={"medication_code": "ALBUTEROL", "lot_number": "ALB-OWE-1",
                       "initial_quantity": 4})
    ctx["record"] = prepare_dose(ctx["visit"]["id"], ctx["order"]["id"], ctx["nurse"]["id"], units=2)
    record_outcome(ctx["record"]["id"], "ADMINISTERED", ctx["nurse"]["id"])
    return ctx


def test_voiding_an_administered_dose_restores_every_unit_bucket(api, admin_headers):
    """PRD §2.10: "For every `MedicationStockLot`, `received_total` always equals the sum of
    `quantity_on_hand`, `quantity_reserved`, `quantity_administered` and `quantity_wasted`."
    PRD §2.10: "Preparing and then voiding, or preparing, administering and then voiding, both
    restore `quantity_on_hand` to exactly its prior value and leave `received_total` untouched.
    Zero drift is required; approximate restoration is a defect."
    PRD §3.7: "The lot is compensated exactly according to the state the record came from: from
    `PREPARED`, `units` move from `quantity_reserved` back to `quantity_on_hand`; from
    `ADMINISTERED`, from `quantity_administered` back to `quantity_on_hand`; from `WASTED`, from
    `quantity_wasted` back to `quantity_on_hand`."

    Design: Difficulty/compensating_invariant/lot_unit_conservation_prepare_administer_then_void
    """
    ctx = _administered_dose()
    before = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert before["quantity_on_hand"] == 2
    assert before["quantity_administered"] == 2
    assert_lot_unit_conservation(before)

    voided = validate_success(api.void_administration_record(
        ctx["record"]["id"], {"reason_code": "Charted against the wrong encounter"},
        make_nurse_headers(ctx["nurse"]["id"])))
    assert voided["status"] == "VOIDED"
    assert voided["voided_at"].startswith("2026-08-03T09:00:00")

    lot = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert lot["received_total"] == 4
    assert lot["quantity_on_hand"] == 4
    assert lot["quantity_reserved"] == 0
    assert lot["quantity_administered"] == 0
    assert lot["quantity_wasted"] == 0
    assert_lot_unit_conservation(lot)
    assert lot["days_of_supply"] == pytest.approx(3.33, abs=0.001)
    assert lot["status"] == "AVAILABLE"


def test_voiding_an_administered_dose_erases_it_from_the_daily_count(api, admin_headers):
    """PRD §3.7: "Only records still in `ADMINISTERED` status count toward either figure — records
    that are `PREPARED`, `REFUSED` or `WASTED` never count, and a voided record leaves both the
    daily count and the maximum, which is exactly how a mis-entered dose is undone."
    PRD §3.2: "The second is administration records still in `ADMINISTERED` status whose
    `protocol_mode` is `STOCK_EMERGENCY`, whose `administered_at` falls in the window, and whose
    encounter belongs to this student."

    Design: Difficulty/compensating_invariant/lot_unit_conservation_prepare_administer_then_void
    """
    ctx = _administered_dose()
    charged = validate_success(api.get_medication_authorization(ctx["order"]["id"], admin_headers))
    assert charged["doses_administered_today"] == 1

    void_record(ctx["record"]["id"], ctx["nurse"]["id"], "Charted against the wrong encounter")

    order = validate_success(api.get_medication_authorization(ctx["order"]["id"], admin_headers))
    assert order["doses_administered_today"] == 0
    assert order.get("last_administered_at") is None

    student = validate_success(api.get_student(ctx["student"]["id"], admin_headers))
    assert student["observed_risk_score"] == 0, "an order-backed dose never enters the observed set"


def test_a_refused_record_is_terminal(api, admin_headers):
    """PRD §3.7: "An `outcome` of `REFUSED` stores the `reason_code`, returns `units` from
    `quantity_reserved` to `quantity_on_hand`, decrements the encounter's pending count by one, and
    recomputes the lot's days of supply and the building's protocol status."
    PRD §3.7: "`REFUSED` and `VOIDED` are terminal."
    PRD §2.7: "The administration check guards the outcome and void steps."

    Design: Corner/state_machines/administration_record_refused_is_terminal_for_further_outcomes
    """
    ctx = setup_dose_ready(
        school_overrides={"name": "Gale Elementary", "building_code": "GAL35"},
        student_overrides={"full_name": "Gus Renard", "grade_level": 5,
                           "date_of_birth": "2015-05-15T00:00:00Z"},
        lot_overrides={"medication_code": "ALBUTEROL", "lot_number": "ALB-GAL-1",
                       "initial_quantity": 3})
    nurse_id = ctx["nurse"]["id"]
    record = prepare_dose(ctx["visit"]["id"], ctx["order"]["id"], nurse_id, units=1)

    refused = validate_success(api.record_administration_outcome(
        record["id"], {"outcome": "REFUSED", "reason_code": "Student declined the dose"},
        make_nurse_headers(nurse_id)))
    assert refused["status"] == "REFUSED"
    assert refused["reason_code"] == "Student declined the dose"
    lot = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert lot["quantity_on_hand"] == 3
    assert lot["quantity_reserved"] == 0
    assert validate_success(api.get_health_visit(
        ctx["visit"]["id"], admin_headers))["pending_administration_count"] == 0

    resp = api.record_administration_outcome(
        record["id"], {"outcome": "ADMINISTERED"}, make_nurse_headers(nurse_id))
    validate_error(resp, ApiErrorId.ERR_ADMINISTRATION_INVALID_STATE.value, 409)

    unchanged = validate_success(api.get_administration_record(record["id"], admin_headers))
    assert unchanged["status"] == "REFUSED"
    assert unchanged.get("administered_at") is None
    final_lot = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert final_lot["received_total"] == 3
    assert final_lot["quantity_administered"] == 0


def test_a_manual_void_exactly_at_the_deadline_is_refused(api, admin_headers):
    """PRD §3.7: "A manual void must happen within 1440 minutes of `prepared_at`; at or after that
    deadline it is refused with `ERR_VOID_WINDOW_CLOSED` (HTTP 409) at ladder position 37."

    Design: Corner/validations/manual_void_at_exactly_1440_minutes_is_refused
    """
    ctx = setup_dose_prepared(
        units=1,
        school_overrides={"name": "Yucca Elementary", "building_code": "YUC53"},
        student_overrides={"full_name": "Yuki Moreau", "grade_level": 5,
                           "date_of_birth": "2015-01-25T00:00:00Z",
                           "chronic_condition_codes": ["ASTHMA"]},
        lot_overrides={"medication_code": "ALBUTEROL", "lot_number": "ALB-YUC-1",
                       "initial_quantity": 6})
    assert ctx["record"]["prepared_at"].startswith("2026-08-03T09:00:00")

    set_clock("2026-08-04T09:00:00Z")
    resp = api.void_administration_record(
        ctx["record"]["id"], {"reason_code": "Late correction attempt"},
        make_nurse_headers(ctx["nurse"]["id"]))
    validate_error(resp, ApiErrorId.ERR_VOID_WINDOW_CLOSED.value, 409)

    record = validate_success(api.get_administration_record(ctx["record"]["id"], admin_headers))
    assert record["status"] == "PREPARED"
    assert record.get("voided_at") is None
    lot = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert lot["quantity_on_hand"] == 5
    assert lot["quantity_reserved"] == 1
    assert lot["received_total"] == 6
    assert validate_success(api.get_health_visit(
        ctx["visit"]["id"], admin_headers))["pending_administration_count"] == 1


def test_a_prepared_record_is_reachable_from_every_declared_filter(api, admin_headers):
    """PRD §3.7: "Records may be listed filtered by `visit_id`, `authorization_id`, `lot_id`,
    `administering_nurse_id`, `witness_nurse_id`, `status` and `protocol_mode`."
    PRD §3.7: "On success the lot is chosen by the selection policy, `medication_code` and
    `dose_amount` are copied from the order, `protocol_mode` is recorded as `AUTHORIZED`, `status`
    is `PREPARED`, `prepared_at` is stamped with the clock, and `administering_nurse_id` is copied
    from the acting `X-User-ID`."

    Design: Corner/endpoints/administration_record_is_reachable_from_visit_authorization_and_lot
    """
    ctx = setup_dose_prepared(
        units=1,
        school_overrides={"name": "Fernbank Elementary", "building_code": "FRN60"},
        student_overrides={"full_name": "Finn Waller", "grade_level": 5,
                           "date_of_birth": "2015-10-10T00:00:00Z",
                           "chronic_condition_codes": ["ASTHMA"]},
        lot_overrides={"medication_code": "ALBUTEROL", "lot_number": "ALB-FRN-1",
                       "initial_quantity": 6})
    record = validate_success(api.get_administration_record(ctx["record"]["id"], admin_headers))
    assert_administration_record(record)
    assert record["lot_id"] == ctx["lot"]["id"]
    assert record["administering_nurse_id"] == ctx["nurse"]["id"]
    assert record["protocol_mode"] == "AUTHORIZED"
    assert record["medication_code"] == "ALBUTEROL"
    assert record["dose_amount"] == pytest.approx(2, abs=0.001)

    for params in ({"visit_id": ctx["visit"]["id"]},
                   {"authorization_id": ctx["order"]["id"]},
                   {"lot_id": ctx["lot"]["id"]},
                   {"administering_nurse_id": ctx["nurse"]["id"]}):
        rows, meta = validate_paginated(api.list_administration_records(admin_headers, params))
        assert meta["total_count"] == 1, f"filter {params} should match exactly one record"
        assert rows[0]["id"] == ctx["record"]["id"]
