"""Medication orders: two independent state dimensions, the derived dispensable flag,
consent withdrawal cascades and system-driven expiry."""

import pytest

from test_helpers import *  # noqa: F401,F403


def _verified_prn_order():
    school = create_school(name="Carver Elementary", building_code="CAR04")
    nurse = create_nurse(full_name="Rita Nolan", credential="RN", weekly_contracted_minutes=2400)
    create_coverage(nurse["id"], school["id"], weekday="MON", start_minute=480, end_minute=960)
    student = create_student(school["id"], full_name="Fay Lin", grade_level=2,
                             date_of_birth="2018-03-14T00:00:00Z")
    order = create_ready_order(student["id"], nurse["id"], medication_code="ALBUTEROL",
                               schedule_type="PRN", prn_min_interval_minutes=240,
                               max_doses_per_day=3)
    return school, nurse, student, order


def test_consent_can_cycle_while_the_clinical_dimension_holds_at_verified(api, admin_headers):
    """PRD §3.4: "`WITHDRAW` moves `CONSENT_GRANTED` to `CONSENT_WITHDRAWN`, sets `dispensable`
    false, and cascades: every administration record on this order still in `PREPARED` moves to
    `VOIDED`, releasing its reservation by returning its `units` from `quantity_reserved` to
    `quantity_on_hand` on the lot, after which the `epinephrine_days_of_supply`,
    `albuterol_days_of_supply` and `stock_protocol_status` of each touched lot's building are
    recomputed."
    PRD §3.4: "`GRANT` moves `CONSENT_PENDING` to `CONSENT_GRANTED` — and it also moves
    `CONSENT_WITHDRAWN` back to `CONSENT_GRANTED`, so a withdrawn consent can be re-granted without
    touching the clinical dimension — and recomputes `dispensable`."

    Design: Difficulty/non_linear_state_machine/authorization_consent_and_clinical_dimensions_move_independently
    """
    _, _, student, order = _verified_prn_order()
    assert order["dispensable"] is True

    withdrawn = validate_success(api.consent_medication_authorization(
        order["id"], {"decision": "WITHDRAW"}, make_guardian_headers(student["id"])))
    assert withdrawn["consent_status"] == "CONSENT_WITHDRAWN"
    assert withdrawn["clinical_status"] == "VERIFIED", "the clinical dimension does not move"
    assert withdrawn["dispensable"] is False

    regranted = validate_success(api.consent_medication_authorization(
        order["id"], {"decision": "GRANT"}, make_guardian_headers(student["id"])))
    assert regranted["consent_status"] == "CONSENT_GRANTED"
    assert regranted["clinical_status"] == "VERIFIED"
    assert regranted["dispensable"] is True


def test_suspension_moves_only_the_clinical_dimension_leaving_a_legal_resting_pair(api, admin_headers):
    """PRD §3.4: "A row may legitimately sit at `CONSENT_WITHDRAWN` paired with `VERIFIED`, or at
    `CONSENT_GRANTED` paired with `SUSPENDED`; both combinations are legal and both make the order
    undispensable."
    PRD §3.4: "A `decision` of `SUSPEND`, recorded by a physician, moves `VERIFIED` to
    `SUSPENDED`, sets `dispensable` false, voids every `PREPARED` administration record on the
    order — releasing each reservation — and recomputes the protocol status for each touched lot's
    building."

    Design: Difficulty/non_linear_state_machine/authorization_consent_and_clinical_dimensions_move_independently
    """
    _, _, student, order = _verified_prn_order()

    suspended = validate_success(api.clinical_review_medication_authorization(
        order["id"], {"decision": "SUSPEND"}, TEST_USERS["physician_headers"]))
    assert suspended["consent_status"] == "CONSENT_GRANTED", "the consent dimension is untouched"
    assert suspended["clinical_status"] == "SUSPENDED"
    assert suspended["dispensable"] is False

    stored = validate_success(api.get_medication_authorization(order["id"], admin_headers))
    assert_medication_authorization(stored)
    assert (stored["consent_status"], stored["clinical_status"]) == ("CONSENT_GRANTED", "SUSPENDED")


def test_order_creation_without_dose_unit_is_refused(api, admin_headers):
    """PRD §3.4: "A medication order is created by a school nurse and records the `student_id` it
    authorises medication for, an optional `action_plan_id` naming the plan the order hangs off
    (null for a standalone order), a `medication_code` drawn from `EPINEPHRINE`, `ALBUTEROL`,
    `INSULIN`, `METHYLPHENIDATE` and `ACETAMINOPHEN`, a `route` of `IM`, `INHALED`, `ORAL` or
    `SUBQ`, a strictly positive `dose_amount` with a `dose_unit` of `MG`, `MCG`, `ML`, `PUFF` or
    `UNIT`, a `schedule_type` of `SCHEDULED` or `PRN`, a `max_doses_per_day` between 1 and 12
    inclusive, and a validity window given by `valid_from` and a strictly later `valid_until`."
    PRD §2.7: "Every non-optional input field is present and non-null, else
    `ERR_MISSING_REQUIRED_FIELD` (position 5, HTTP 400)."

    Design: Corner/entities/medication_authorization_missing_required_field_dose_unit_rejected
    """
    school = create_school(name="Tucker Elementary", building_code="TUC23")
    nurse = create_nurse(full_name="Rita Nolan", credential="RN", weekly_contracted_minutes=2400)
    student = create_student(school["id"], full_name="Tess Marek", grade_level=4,
                             date_of_birth="2016-03-03T00:00:00Z")

    resp = api.create_medication_authorization(
        {"student_id": student["id"], "medication_code": "ALBUTEROL", "route": "INHALED",
         "dose_amount": 2, "schedule_type": "SCHEDULED", "max_doses_per_day": 2,
         "valid_from": "2026-07-01T00:00:00Z", "valid_until": "2027-06-30T00:00:00Z"},
        make_nurse_headers(nurse["id"]))
    validate_error(resp, ApiErrorId.ERR_MISSING_REQUIRED_FIELD.value, 400)

    _, meta = validate_paginated(api.list_medication_authorizations(
        admin_headers, {"student_id": student["id"]}))
    assert meta["total_count"] == 0


def test_verifying_an_already_verified_order_is_refused(api, admin_headers):
    """PRD §3.4: "A `decision` of `VERIFY` moves `UNVERIFIED` to `VERIFIED`, and equally moves
    `SUSPENDED` back to `VERIFIED`; either way the acting nurse's `credential` must be `RN`, and
    either the order's `action_plan_id` must be null or the referenced plan must be `ACTIVE`."
    PRD §2.7: "The authorisation check guards the consent and clinical-review steps."

    Design: Corner/errors/error_authorization_invalid_state_on_verifying_an_already_verified_order
    """
    school = create_school(name="Pelham Elementary", building_code="PLH80")
    nurse = create_nurse(full_name="Rita Nolan", credential="RN", weekly_contracted_minutes=2400)
    student = create_student(school["id"], full_name="Pia Andersen", grade_level=3,
                             date_of_birth="2017-08-28T00:00:00Z", chronic_condition_codes=["ASTHMA"])
    order = create_order(student["id"], nurse["id"])
    first = verify_order(order["id"], nurse["id"])
    assert first["clinical_status"] == "VERIFIED"

    resp = api.clinical_review_medication_authorization(
        order["id"], {"decision": "VERIFY"}, make_nurse_headers(nurse["id"]))
    validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_INVALID_STATE.value, 409)

    stored = validate_success(api.get_medication_authorization(order["id"], admin_headers))
    assert stored["clinical_status"] == "VERIFIED"
    assert stored["consent_status"] == "CONSENT_PENDING"
    assert stored["dispensable"] is False


def test_withdrawing_consent_voids_a_prepared_dose_and_returns_its_units(api, admin_headers):
    """PRD §3.4: "`WITHDRAW` moves `CONSENT_GRANTED` to `CONSENT_WITHDRAWN`, sets `dispensable`
    false, and cascades: every administration record on this order still in `PREPARED` moves to
    `VOIDED`, releasing its reservation by returning its `units` from `quantity_reserved` to
    `quantity_on_hand` on the lot, after which the `epinephrine_days_of_supply`,
    `albuterol_days_of_supply` and `stock_protocol_status` of each touched lot's building are
    recomputed."

    Design: Corner/state_machines/consent_withdrawal_voids_prepared_record_and_releases_reservation
    """
    ctx = setup_dose_prepared(
        units=2,
        school_overrides={"name": "Iris Elementary", "building_code": "IRS37"},
        student_overrides={"full_name": "Ivy Sandoval", "grade_level": 6,
                           "date_of_birth": "2014-04-24T00:00:00Z",
                           "chronic_condition_codes": ["ASTHMA"]},
        lot_overrides={"medication_code": "ALBUTEROL", "lot_number": "ALB-IRS-1",
                       "initial_quantity": 8})

    assert ctx["lot"]["quantity_on_hand"] == 6
    assert ctx["lot"]["quantity_reserved"] == 2
    assert ctx["visit"]["pending_administration_count"] == 1

    withdrawn = validate_success(api.consent_medication_authorization(
        ctx["order"]["id"], {"decision": "WITHDRAW"}, make_guardian_headers(ctx["student"]["id"])))
    assert withdrawn["consent_status"] == "CONSENT_WITHDRAWN"
    assert withdrawn["clinical_status"] == "VERIFIED"
    assert withdrawn["dispensable"] is False

    record = validate_success(api.get_administration_record(ctx["record"]["id"], admin_headers))
    assert record["status"] == "VOIDED"

    lot = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert lot["quantity_on_hand"] == 8
    assert lot["quantity_reserved"] == 0
    assert lot["received_total"] == 8
    assert lot["days_of_supply"] == pytest.approx(6.67, abs=0.001)
    assert_lot_unit_conservation(lot)

    visit = validate_success(api.get_health_visit(ctx["visit"]["id"], admin_headers))
    assert visit["pending_administration_count"] == 0


def test_the_daily_checkpoint_expires_a_lapsed_order_and_voids_its_prepared_dose(api, admin_headers):
    """PRD §3.4: "During the daily checkpoint, an order whose `clinical_status` is `UNVERIFIED`,
    `VERIFIED` or `SUSPENDED` and whose `valid_until` the logical clock has reached moves to
    `clinical_status` `EXPIRED`, `dispensable` is set false, and every `PREPARED` record on the
    order is voided with its reservation released."
    PRD §2.5: "It optionally narrows to one building via `school_id`, and it reports `epoch`
    together with seven identifier arrays: `expired_action_plan_ids`, `expired_authorization_ids`,
    `expired_lot_ids`, `expired_disclosure_ids`, `promoted_screening_ids`,
    `voided_administration_ids` and `recomputed_school_ids`."

    Design: Corner/cross_cutting_complexity_layers/ops_checkpoint_expires_authorization_and_voids_its_prepared_record
    """
    ctx = setup_dose_prepared(
        units=2,
        school_overrides={"name": "Mire Elementary", "building_code": "MIR73"},
        student_overrides={"full_name": "Mel Ruiz", "grade_level": 7,
                           "date_of_birth": "2013-12-12T00:00:00Z",
                           "chronic_condition_codes": ["ASTHMA"]},
        lot_overrides={"medication_code": "ALBUTEROL", "lot_number": "ALB-MIR-1",
                       "initial_quantity": 5},
        order_overrides={"valid_until": "2026-08-04T00:00:00Z"})

    assert ctx["lot"]["quantity_on_hand"] == 3
    assert ctx["lot"]["quantity_reserved"] == 2

    set_clock("2026-08-04T00:00:00Z")
    result = validate_success(api.run_daily_checkpoint({"school_id": ctx["school"]["id"]}, admin_headers))

    assert ctx["order"]["id"] in result["expired_authorization_ids"]
    assert ctx["record"]["id"] in result["voided_administration_ids"]

    order = validate_success(api.get_medication_authorization(ctx["order"]["id"], admin_headers))
    assert order["clinical_status"] == "EXPIRED"
    assert order["consent_status"] == "CONSENT_GRANTED"
    assert order["dispensable"] is False

    record = validate_success(api.get_administration_record(ctx["record"]["id"], admin_headers))
    assert record["status"] == "VOIDED"

    lot = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert lot["quantity_on_hand"] == 5
    assert lot["quantity_reserved"] == 0
    assert lot["received_total"] == 5
    assert validate_success(api.get_health_visit(
        ctx["visit"]["id"], admin_headers))["pending_administration_count"] == 0
