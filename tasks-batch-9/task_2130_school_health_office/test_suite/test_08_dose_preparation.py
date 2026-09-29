"""Reserving a dose: the encounter and order preconditions, the dose gate,
credential and witness rules, lot selection and the stale-order guard."""

import pytest

from test_helpers import *  # noqa: F401,F403


def _open_encounter_with_unconsented_order():
    """A verified but unconsented order, and an encounter still sitting at OPEN."""
    base = setup_basic_scenario(
        school_overrides={"name": "Grant Elementary", "building_code": "GRA08"},
        student_overrides={"full_name": "Jo Meads", "grade_level": 4,
                           "date_of_birth": "2016-01-16T00:00:00Z"})
    base["lot"] = create_lot(base["school"]["id"], medication_code="ALBUTEROL",
                             lot_number="ALB-GRA-1", initial_quantity=5)
    order = create_order(base["student"]["id"], base["nurse"]["id"])
    base["order"] = verify_order(order["id"], base["nurse"]["id"])
    set_clock(MONDAY_0900)
    base["visit"] = open_visit(base["student"]["id"], base["school"]["id"], base["nurse"]["id"],
                               complaint_code="MEDICATION")
    return base


def test_preparing_against_an_open_encounter_reports_the_encounter_state(api, admin_headers):
    """PRD §2.7: "**Consent versus encounter state.** On dose preparation, the `HealthVisit`
    from-state check at position 9 outranks the consent check at position 23. Preparing a dose
    against an `OPEN` encounter for an order whose consent is still `CONSENT_PENDING` returns
    `ERR_VISIT_INVALID_STATE`, not `ERR_CONSENT_NOT_GRANTED`."

    Design: Difficulty/priority_pair_validation_conflict/conflict_a_visit_state_outranks_consent_not_granted
    """
    ctx = _open_encounter_with_unconsented_order()
    assert ctx["order"]["consent_status"] == "CONSENT_PENDING"
    assert ctx["order"]["clinical_status"] == "VERIFIED"
    assert ctx["visit"]["status"] == "OPEN"

    resp = api.create_administration_record(
        {"visit_id": ctx["visit"]["id"], "authorization_id": ctx["order"]["id"], "units": 1,
         "expected_authorization_version": order_version(ctx["order"]["id"])},
        make_nurse_headers(ctx["nurse"]["id"]))
    validate_error(resp, ApiErrorId.ERR_VISIT_INVALID_STATE.value, 409)


def test_a_preparation_refused_on_encounter_state_reserves_no_units(api, admin_headers):
    """PRD §3.7: "`units` move on the lot from `quantity_on_hand` to `quantity_reserved` with
    `received_total` unchanged; the encounter's `pending_administration_count` is incremented by
    one; the order's `version` is incremented by one; and the lot's own days of supply, the
    building's two days-of-supply figures, the protocol status and the posture are recomputed."
    PRD §2.7: "**Consent versus encounter state.** On dose preparation, the `HealthVisit`
    from-state check at position 9 outranks the consent check at position 23. Preparing a dose
    against an `OPEN` encounter for an order whose consent is still `CONSENT_PENDING` returns
    `ERR_VISIT_INVALID_STATE`, not `ERR_CONSENT_NOT_GRANTED`."

    Design: Difficulty/priority_pair_validation_conflict/conflict_a_visit_state_outranks_consent_not_granted
    """
    ctx = _open_encounter_with_unconsented_order()

    api.create_administration_record(
        {"visit_id": ctx["visit"]["id"], "authorization_id": ctx["order"]["id"], "units": 1,
         "expected_authorization_version": order_version(ctx["order"]["id"])},
        make_nurse_headers(ctx["nurse"]["id"]))

    order = validate_success(api.get_medication_authorization(ctx["order"]["id"], admin_headers))
    assert order["consent_status"] == "CONSENT_PENDING"
    assert order["clinical_status"] == "VERIFIED"
    visit = validate_success(api.get_health_visit(ctx["visit"]["id"], admin_headers))
    assert visit["status"] == "OPEN"
    assert visit["pending_administration_count"] == 0
    lot = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert lot["quantity_on_hand"] == 5
    assert lot["quantity_reserved"] == 0


def _emergency_pool_is_empty():
    """A building holding only a student-specific epinephrine lot."""
    ctx = setup_visit_in_assessment(
        school_overrides={"name": "Irving Elementary", "building_code": "IRV10"},
        student_overrides={"full_name": "Mia Duarte", "grade_level": 3,
                           "date_of_birth": "2017-02-02T00:00:00Z"},
        visit_overrides={"complaint_code": "ILLNESS", "acuity": "URGENT"})
    ctx["lot"] = create_lot(ctx["school"]["id"], medication_code="EPINEPHRINE",
                            lot_number="EPI-IRV-1", is_stock_protocol=False, initial_quantity=5)
    return ctx


def test_an_emergency_dose_cannot_draw_on_a_student_specific_lot(api, admin_headers):
    """PRD §3.5: "When a dose is prepared, the candidate pool is every lot at the encounter's
    building whose `medication_code` equals the required medication, whose `status` is `AVAILABLE`,
    whose `expiration_date` is strictly later than the logical clock, whose `quantity_available` is
    at least the requested `units`, and whose `is_stock_protocol` flag matches the mode of the
    request — true for an emergency-stock dose, false for an order-backed dose."
    PRD §3.5: "If the candidate pool is empty the request is refused with `ERR_NO_ELIGIBLE_LOT`
    (HTTP 409) at ladder position 48; if a winning lot exists but its available units fall short of
    the request, the refusal is `ERR_INSUFFICIENT_STOCK` (HTTP 409) at position 49."

    Design: Difficulty/boundary_precision_check/stock_emergency_empty_candidate_pool_zero_eligible_lots
    """
    ctx = _emergency_pool_is_empty()

    resp = api.create_stock_emergency_record(
        {"visit_id": ctx["visit"]["id"], "medication_code": "EPINEPHRINE", "units": 1},
        make_nurse_headers(ctx["nurse"]["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_LOT.value, 409)


def test_the_refused_emergency_dose_leaves_the_designated_supply_untouched(api, admin_headers):
    """PRD §3.5: "That equality makes the two pools disjoint: an authorised dose never draws on
    undesignated emergency stock, and an emergency dose never draws on a child's own supply."
    PRD §3.5: "**Readiness of the emergency stock.** The building's `stock_protocol_status` looks
    only at undesignated stock: the epinephrine unit total is the sum of `quantity_available` over
    the building's epinephrine lots that are `AVAILABLE`, unexpired against the clock and flagged
    `is_stock_protocol`, and the albuterol unit total is the same sum for albuterol."

    Design: Difficulty/boundary_precision_check/stock_emergency_empty_candidate_pool_zero_eligible_lots
    """
    ctx = _emergency_pool_is_empty()

    api.create_stock_emergency_record(
        {"visit_id": ctx["visit"]["id"], "medication_code": "EPINEPHRINE", "units": 1},
        make_nurse_headers(ctx["nurse"]["id"]))

    lot = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert lot["quantity_on_hand"] == 5
    assert lot["quantity_reserved"] == 0
    assert lot["status"] == "AVAILABLE"
    assert validate_success(api.get_health_visit(
        ctx["visit"]["id"], admin_headers))["pending_administration_count"] == 0

    building = validate_success(api.get_school(ctx["school"]["id"], admin_headers))
    assert building["epinephrine_days_of_supply"] == pytest.approx(16.67, abs=0.001), \
        "the student-specific lot still counts toward days of supply"
    assert building["stock_protocol_status"] == "DEPLETED", \
        "no undesignated epinephrine unit is held"


def test_a_prn_dose_at_exactly_the_minimum_interval_is_accepted(api, admin_headers):
    """PRD §3.7: "For an order whose `schedule_type` is `PRN` and whose `last_administered_at` is
    not null, the elapsed time from that instant to the clock is floored to whole minutes and must
    be at least `prn_min_interval_minutes`; a dose at exactly the interval is allowed, and anything
    shorter is refused with `ERR_PRN_INTERVAL_NOT_ELAPSED` (HTTP 409) at ladder position 32."

    Design: Corner/calculations/prn_interval_exactly_at_minimum_elapsed_is_allowed
    """
    ctx = setup_dose_ready(
        school_overrides={"name": "Nova Elementary", "building_code": "NOV42"},
        student_overrides={"full_name": "Noel Frey", "grade_level": 4,
                           "date_of_birth": "2016-05-05T00:00:00Z",
                           "chronic_condition_codes": ["ASTHMA"]},
        lot_overrides={"medication_code": "ALBUTEROL", "lot_number": "ALB-NOV-1",
                       "initial_quantity": 10},
        order_overrides={"schedule_type": "PRN", "prn_min_interval_minutes": 240,
                         "max_doses_per_day": 3})
    nurse_id = ctx["nurse"]["id"]
    first = prepare_dose(ctx["visit"]["id"], ctx["order"]["id"], nurse_id, units=1)
    record_outcome(first["id"], "ADMINISTERED", nurse_id)

    set_clock("2026-08-03T13:00:00Z")
    order = validate_success(api.get_medication_authorization(ctx["order"]["id"], admin_headers))
    assert order["last_administered_at"].startswith("2026-08-03T09:00:00")
    assert order["doses_administered_today"] == 1

    resp = api.create_administration_record(
        {"visit_id": ctx["visit"]["id"], "authorization_id": ctx["order"]["id"], "units": 1,
         "expected_authorization_version": order["version"]}, make_nurse_headers(nurse_id))
    second = validate_success(resp, 201)
    assert second["status"] == "PREPARED"
    assert second["prepared_at"].startswith("2026-08-03T13:00:00")
    assert second["lot_id"] == ctx["lot"]["id"]

    lot = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert lot["quantity_on_hand"] == 8
    assert lot["quantity_reserved"] == 1
    assert lot["quantity_administered"] == 1
    assert lot["received_total"] == 10
    assert_lot_unit_conservation(lot)
    assert validate_success(api.get_health_visit(
        ctx["visit"]["id"], admin_headers))["pending_administration_count"] == 1


def test_a_request_breaching_both_frequency_limits_reports_the_interval(api, admin_headers):
    """PRD §2.7: "**PRN interval versus daily cap.** On dose preparation, the PRN interval check at
    position 32 outranks the daily-cap check at position 35. A request that is both too soon after
    the last dose and over the day's cap returns `ERR_PRN_INTERVAL_NOT_ELAPSED`, not
    `ERR_DAILY_DOSE_CAP_REACHED`."

    Design: Corner/validations/conflict_b_prn_interval_outranks_daily_dose_cap
    """
    ctx = setup_dose_ready(
        school_overrides={"name": "Ursa Elementary", "building_code": "URS49"},
        student_overrides={"full_name": "Uri Nakamura", "grade_level": 6,
                           "date_of_birth": "2014-02-08T00:00:00Z",
                           "chronic_condition_codes": ["ASTHMA"]},
        lot_overrides={"medication_code": "ALBUTEROL", "lot_number": "ALB-URS-1",
                       "initial_quantity": 10},
        order_overrides={"schedule_type": "PRN", "prn_min_interval_minutes": 240,
                         "max_doses_per_day": 1})
    nurse_id = ctx["nurse"]["id"]
    first = prepare_dose(ctx["visit"]["id"], ctx["order"]["id"], nurse_id, units=1)
    record_outcome(first["id"], "ADMINISTERED", nurse_id)

    set_clock("2026-08-03T10:00:00Z")
    order = validate_success(api.get_medication_authorization(ctx["order"]["id"], admin_headers))
    assert order["doses_administered_today"] == 1
    assert order["max_doses_per_day"] == 1

    resp = api.create_administration_record(
        {"visit_id": ctx["visit"]["id"], "authorization_id": ctx["order"]["id"], "units": 1,
         "expected_authorization_version": order["version"]}, make_nurse_headers(nurse_id))
    validate_error(resp, ApiErrorId.ERR_PRN_INTERVAL_NOT_ELAPSED.value, 409)

    lot = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert lot["quantity_on_hand"] == 9
    assert lot["quantity_reserved"] == 0
    assert lot["quantity_administered"] == 1
    assert validate_success(api.get_health_visit(
        ctx["visit"]["id"], admin_headers))["pending_administration_count"] == 0


def test_the_daily_cap_refuses_the_dose_after_the_count_reaches_it(api, admin_headers):
    """PRD §3.7: "Separately, `doses_administered_today` must be strictly less than
    `max_doses_per_day`, so the dose that brings the count level with the cap is the last one
    allowed and the next is refused with `ERR_DAILY_DOSE_CAP_REACHED` (HTTP 409) at position 35."
    PRD §3.7: "An order whose `schedule_type` is `SCHEDULED`, or a PRN order with no prior
    administered dose, passes the interval arm unconditionally."

    Design: Corner/errors/error_daily_dose_cap_reached_on_a_scheduled_order
    """
    ctx = setup_dose_ready(
        school_overrides={"name": "Zinnia Elementary", "building_code": "ZNA90"},
        student_overrides={"full_name": "Zeb Fontaine", "grade_level": 7,
                           "date_of_birth": "2013-01-09T00:00:00Z",
                           "chronic_condition_codes": ["ASTHMA"]},
        lot_overrides={"medication_code": "ALBUTEROL", "lot_number": "ALB-ZNA-1",
                       "initial_quantity": 8},
        order_overrides={"max_doses_per_day": 1})
    nurse_id = ctx["nurse"]["id"]
    first = prepare_dose(ctx["visit"]["id"], ctx["order"]["id"], nurse_id, units=1)
    record_outcome(first["id"], "ADMINISTERED", nurse_id)

    order = validate_success(api.get_medication_authorization(ctx["order"]["id"], admin_headers))
    assert order["doses_administered_today"] == 1
    assert order["last_administered_at"].startswith("2026-08-03T09:00:00")

    resp = api.create_administration_record(
        {"visit_id": ctx["visit"]["id"], "authorization_id": ctx["order"]["id"], "units": 1,
         "expected_authorization_version": order["version"]}, make_nurse_headers(nurse_id))
    validate_error(resp, ApiErrorId.ERR_DAILY_DOSE_CAP_REACHED.value, 409)

    lot = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert lot["quantity_on_hand"] == 7
    assert lot["quantity_administered"] == 1
    assert lot["quantity_reserved"] == 0
    assert lot["received_total"] == 8
    assert validate_success(api.get_health_visit(
        ctx["visit"]["id"], admin_headers))["pending_administration_count"] == 0


def test_a_witness_is_required_only_for_a_controlled_medication(api, admin_headers):
    """PRD §2.9: "Where a controlled step is attempted with no witness named at all, the failure is
    the separate `ERR_WITNESS_REQUIRED` (HTTP 422) at position 21, which guards dose preparation
    and the dose outcome step — witness *absence* is a payload problem, witness *identity* is a
    duties problem, and the ladder reaches absence first."
    PRD §2.9: "A medication is controlled exactly when its `medication_code` is `METHYLPHENIDATE`;
    that fact is stored on each order as the derived boolean `is_controlled`."

    Design: Corner/validations/witness_required_only_when_the_medication_is_controlled
    """
    ctx = setup_dose_ready(
        school_overrides={"name": "Zephyr Elementary", "building_code": "ZEP54"},
        student_overrides={"full_name": "Zia Farrow", "grade_level": 9,
                           "date_of_birth": "2011-11-19T00:00:00Z",
                           "chronic_condition_codes": ["MENTAL_HEALTH", "ASTHMA"]},
        lot_overrides={"medication_code": "ALBUTEROL", "lot_number": "ALB-ZEP-1",
                       "initial_quantity": 6})
    nurse_id, nurse_headers = ctx["nurse"]["id"], make_nurse_headers(ctx["nurse"]["id"])
    controlled_lot = create_lot(ctx["school"]["id"], medication_code="METHYLPHENIDATE",
                                lot_number="MPH-ZEP-1", initial_quantity=6)
    controlled_order = create_ready_order(ctx["student"]["id"], nurse_id,
                                          medication_code="METHYLPHENIDATE", route="ORAL",
                                          dose_amount=10, dose_unit="MG", max_doses_per_day=1)
    assert controlled_order["is_controlled"] is True
    assert ctx["order"]["is_controlled"] is False

    plain = validate_success(api.create_administration_record(
        {"visit_id": ctx["visit"]["id"], "authorization_id": ctx["order"]["id"], "units": 1,
         "expected_authorization_version": order_version(ctx["order"]["id"])}, nurse_headers), 201)
    assert plain["status"] == "PREPARED"
    assert plain.get("witness_nurse_id") is None

    refused = api.create_administration_record(
        {"visit_id": ctx["visit"]["id"], "authorization_id": controlled_order["id"], "units": 1,
         "expected_authorization_version": order_version(controlled_order["id"])}, nurse_headers)
    validate_error(refused, ApiErrorId.ERR_WITNESS_REQUIRED.value, 422)

    mph = validate_success(api.get_stock_lot(controlled_lot["id"], admin_headers))
    assert mph["quantity_on_hand"] == 6
    assert mph["quantity_reserved"] == 0
    albuterol = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert albuterol["quantity_on_hand"] == 5
    assert albuterol["quantity_reserved"] == 1
    assert validate_success(api.get_health_visit(
        ctx["visit"]["id"], admin_headers))["pending_administration_count"] == 1


def test_emergency_stock_is_limited_to_the_two_protocol_medications(api, admin_headers):
    """PRD §3.7: "The encounter must be `IN_ASSESSMENT` or `DISPOSITIONED`; the building's
    `emergency_protocol_enabled` must be true and the medication must be `EPINEPHRINE` or
    `ALBUTEROL`, failing either of which the request is refused with `ERR_STOCK_PROTOCOL_DISABLED`
    (HTTP 409) at ladder position 30; the acting nurse must clear the credential and delegation
    rule; and the selection policy, restricted to lots flagged `is_stock_protocol`, must yield a
    candidate."

    Design: Corner/endpoints/stock_emergency_conditional_on_medication_family
    """
    ctx = setup_visit_in_assessment(
        school_overrides={"name": "Elmswood Elementary", "building_code": "ELM59"},
        student_overrides={"full_name": "Ena Wolfe", "grade_level": 7,
                           "date_of_birth": "2013-03-03T00:00:00Z",
                           "chronic_condition_codes": ["T1DM"]},
        visit_overrides={"complaint_code": "CHRONIC_CARE"})
    insulin_lot = create_lot(ctx["school"]["id"], medication_code="INSULIN",
                             lot_number="INS-ELM-1", is_stock_protocol=True, initial_quantity=10)

    resp = api.create_stock_emergency_record(
        {"visit_id": ctx["visit"]["id"], "medication_code": "INSULIN", "units": 1},
        make_nurse_headers(ctx["nurse"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STOCK_PROTOCOL_DISABLED.value, 409)

    lot = validate_success(api.get_stock_lot(insulin_lot["id"], admin_headers))
    assert lot["quantity_on_hand"] == 10
    assert lot["quantity_reserved"] == 0
    assert validate_success(api.get_health_visit(
        ctx["visit"]["id"], admin_headers))["pending_administration_count"] == 0


def test_an_unconsented_order_cannot_be_drawn_from(api, admin_headers):
    """PRD §3.7: "The order's `consent_status` must be `CONSENT_GRANTED`, failing which the refusal
    is `ERR_CONSENT_NOT_GRANTED` (HTTP 409) at ladder position 23, and its `clinical_status` must
    be `VERIFIED`, failing which the refusal is `ERR_AUTHORIZATION_NOT_VERIFIED` (HTTP 409) at
    position 24."

    Design: Corner/errors/error_consent_not_granted_on_dose_prepare
    """
    base = setup_basic_scenario(
        school_overrides={"name": "Wharf Elementary", "building_code": "WHF87"},
        student_overrides={"full_name": "Wes Antoun", "grade_level": 4,
                           "date_of_birth": "2016-02-29T00:00:00Z",
                           "chronic_condition_codes": ["ASTHMA"]})
    lot = create_lot(base["school"]["id"], medication_code="ALBUTEROL",
                     lot_number="ALB-WHF-1", initial_quantity=5)
    order = create_order(base["student"]["id"], base["nurse"]["id"])
    verify_order(order["id"], base["nurse"]["id"])
    set_clock(MONDAY_0900)
    visit = open_visit(base["student"]["id"], base["school"]["id"], base["nurse"]["id"],
                       complaint_code="MEDICATION")
    assess_visit(visit["id"], base["nurse"]["id"], "Awaiting guardian consent")

    resp = api.create_administration_record(
        {"visit_id": visit["id"], "authorization_id": order["id"], "units": 1,
         "expected_authorization_version": order_version(order["id"])},
        make_nurse_headers(base["nurse"]["id"]))
    validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_GRANTED.value, 409)

    stock = validate_success(api.get_stock_lot(lot["id"], admin_headers))
    assert stock["quantity_on_hand"] == 5
    assert stock["quantity_reserved"] == 0
    refreshed = validate_success(api.get_health_visit(visit["id"], admin_headers))
    assert refreshed["status"] == "IN_ASSESSMENT"
    assert refreshed["pending_administration_count"] == 0


def test_an_unverified_order_cannot_be_drawn_from(api, admin_headers):
    """PRD §3.7: "The order's `consent_status` must be `CONSENT_GRANTED`, failing which the refusal
    is `ERR_CONSENT_NOT_GRANTED` (HTTP 409) at ladder position 23, and its `clinical_status` must
    be `VERIFIED`, failing which the refusal is `ERR_AUTHORIZATION_NOT_VERIFIED` (HTTP 409) at
    position 24."
    PRD §3.4: "`clinical_status` is the nurse- and physician-owned dimension, starting at
    `UNVERIFIED`."

    Design: Corner/errors/error_authorization_not_verified_on_dose_prepare
    """
    base = setup_basic_scenario(
        school_overrides={"name": "Xylem Elementary", "building_code": "XYL88"},
        student_overrides={"full_name": "Xia Prentice", "grade_level": 5,
                           "date_of_birth": "2015-03-08T00:00:00Z",
                           "chronic_condition_codes": ["ASTHMA"]})
    lot = create_lot(base["school"]["id"], medication_code="ALBUTEROL",
                     lot_number="ALB-XYL-1", initial_quantity=5)
    order = create_order(base["student"]["id"], base["nurse"]["id"])
    grant_order_consent(order["id"], base["student"]["id"])
    set_clock(MONDAY_0900)
    visit = open_visit(base["student"]["id"], base["school"]["id"], base["nurse"]["id"],
                       complaint_code="MEDICATION")
    assess_visit(visit["id"], base["nurse"]["id"], "Order not yet verified by an RN")

    resp = api.create_administration_record(
        {"visit_id": visit["id"], "authorization_id": order["id"], "units": 1,
         "expected_authorization_version": order_version(order["id"])},
        make_nurse_headers(base["nurse"]["id"]))
    validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_NOT_VERIFIED.value, 409)

    stored = validate_success(api.get_medication_authorization(order["id"], admin_headers))
    assert stored["consent_status"] == "CONSENT_GRANTED"
    assert stored["clinical_status"] == "UNVERIFIED"
    assert stored["dispensable"] is False
    stock = validate_success(api.get_stock_lot(lot["id"], admin_headers))
    assert stock["quantity_on_hand"] == 5
    assert stock["quantity_reserved"] == 0


def test_an_order_whose_window_has_not_opened_cannot_be_drawn_from(api, admin_headers):
    """PRD §3.7: "The logical clock must sit at or after `valid_from` and strictly before
    `valid_until`, or the refusal is `ERR_AUTHORIZATION_WINDOW_CLOSED` (HTTP 409) at position 31."
    PRD §3.4: "Only the derived flag `dispensable` reads both, and it is true only when
    `consent_status` is `CONSENT_GRANTED`, `clinical_status` is `VERIFIED`, and the logical clock
    is at or after `valid_from` and strictly before `valid_until`."

    Design: Corner/errors/error_authorization_window_closed_before_valid_from
    """
    ctx = setup_dose_ready(
        school_overrides={"name": "Yarrow Elementary", "building_code": "YRW89"},
        student_overrides={"full_name": "Yara Bristow", "grade_level": 3,
                           "date_of_birth": "2017-12-13T00:00:00Z",
                           "chronic_condition_codes": ["ASTHMA"]},
        lot_overrides={"medication_code": "ALBUTEROL", "lot_number": "ALB-YRW-1",
                       "initial_quantity": 5},
        order_overrides={"valid_from": "2026-09-01T00:00:00Z"})

    order = validate_success(api.get_medication_authorization(ctx["order"]["id"], admin_headers))
    assert order["consent_status"] == "CONSENT_GRANTED"
    assert order["clinical_status"] == "VERIFIED"
    assert order["dispensable"] is False, "the clock is outside the validity window"

    resp = api.create_administration_record(
        {"visit_id": ctx["visit"]["id"], "authorization_id": ctx["order"]["id"], "units": 1,
         "expected_authorization_version": order["version"]},
        make_nurse_headers(ctx["nurse"]["id"]))
    validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_WINDOW_CLOSED.value, 409)

    lot = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert lot["quantity_on_hand"] == 5
    assert lot["quantity_reserved"] == 0


def test_an_order_belonging_to_another_child_cannot_back_this_encounter(api, admin_headers):
    """PRD §3.7: "The order's `student_id` must equal the encounter's `student_id`, or the request
    is refused with `ERR_LOT_MEDICATION_MISMATCH`."

    Design: Corner/errors/error_lot_medication_mismatch_when_order_belongs_to_another_student
    """
    base = setup_school_with_coverage(
        school_overrides={"name": "Alder Elementary", "building_code": "ALD91"})
    student_a = create_student(base["school"]["id"], full_name="Ana Delgado", grade_level=4,
                               date_of_birth="2016-01-11T00:00:00Z")
    student_b = create_student(base["school"]["id"], full_name="Ben Delgado", grade_level=6,
                               date_of_birth="2014-01-11T00:00:00Z",
                               chronic_condition_codes=["ASTHMA"])
    lot = create_lot(base["school"]["id"], medication_code="ALBUTEROL",
                     lot_number="ALB-ALD-1", initial_quantity=5)
    order_b = create_ready_order(student_b["id"], base["nurse"]["id"])
    set_clock(MONDAY_0900)
    visit_a = open_visit(student_a["id"], base["school"]["id"], base["nurse"]["id"],
                         complaint_code="MEDICATION")
    assess_visit(visit_a["id"], base["nurse"]["id"], "Wrong sibling's order pulled up")

    resp = api.create_administration_record(
        {"visit_id": visit_a["id"], "authorization_id": order_b["id"], "units": 1,
         "expected_authorization_version": order_version(order_b["id"])},
        make_nurse_headers(base["nurse"]["id"]))
    validate_error(resp, ApiErrorId.ERR_LOT_MEDICATION_MISMATCH.value, 409)

    stock = validate_success(api.get_stock_lot(lot["id"], admin_headers))
    assert stock["quantity_on_hand"] == 5
    assert stock["quantity_reserved"] == 0
    assert validate_success(api.get_health_visit(
        visit_a["id"], admin_headers))["pending_administration_count"] == 0
    _, meta = validate_paginated(api.list_administration_records(
        admin_headers, {"visit_id": visit_a["id"]}))
    assert meta["total_count"] == 0


def test_an_undelegated_aide_cannot_reserve_a_dose_the_nurse_can(api, admin_headers):
    """PRD §2.9: "A nurse whose `credential` is `LPN`, and any `HEALTH_AIDE`, may perform an
    administration step only when that person's `delegation_authorized` flag is true **and** the
    medication is not controlled. Anything else is `ERR_CREDENTIAL_NOT_DELEGATED` (HTTP 403), and
    it applies to dose preparation, emergency-stock preparation and the dose outcome step."
    PRD §2.9: "A nurse whose `credential` is `RN` may perform any administration step."

    Design: Corner/errors/error_credential_not_delegated_for_an_undelegated_aide
    """
    ctx = setup_dose_ready(
        school_overrides={"name": "Birchwood Elementary", "building_code": "BRC92"},
        student_overrides={"full_name": "Bea Ronson", "grade_level": 5,
                           "date_of_birth": "2015-04-04T00:00:00Z",
                           "chronic_condition_codes": ["ASTHMA"]},
        lot_overrides={"medication_code": "ALBUTEROL", "lot_number": "ALB-BRC-1",
                       "initial_quantity": 5})
    aide = create_nurse(full_name="Bo Achterberg", credential="HEALTH_AIDE",
                        weekly_contracted_minutes=900, delegation_authorized=False)
    version_before = order_version(ctx["order"]["id"])
    body = {"visit_id": ctx["visit"]["id"], "authorization_id": ctx["order"]["id"], "units": 1,
            "expected_authorization_version": version_before}

    refused = api.create_administration_record(body, make_aide_headers(aide["id"]))
    validate_error(refused, ApiErrorId.ERR_CREDENTIAL_NOT_DELEGATED.value, 403)

    lot = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert lot["quantity_on_hand"] == 5
    assert lot["quantity_reserved"] == 0
    assert order_version(ctx["order"]["id"]) == version_before, \
        "a refused preparation does not bump the order"

    accepted = validate_success(api.create_administration_record(
        body, make_nurse_headers(ctx["nurse"]["id"])), 201)
    assert accepted["administering_nurse_id"] == ctx["nurse"]["id"]
    after = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert after["quantity_on_hand"] == 4
    assert after["quantity_reserved"] == 1


def test_a_stale_order_version_is_refused_on_the_second_reservation(api, admin_headers):
    """PRD §2.6: "A `POST /health-office/administration-records` request must carry
    `expected_authorization_version`, holding the client's last observed `version` of the target
    `MedicationAuthorization`. If the order's current `version` differs, the preparation is
    rejected with `ERR_STALE_AUTHORIZATION_VERSION` (HTTP 412)."
    PRD §3.7: "`units` move on the lot from `quantity_on_hand` to `quantity_reserved` with
    `received_total` unchanged; the encounter's `pending_administration_count` is incremented by
    one; the order's `version` is incremented by one; and the lot's own days of supply, the
    building's two days-of-supply figures, the protocol status and the posture are recomputed."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_authorization_version_rejects_second_dose_prepare
    """
    ctx = setup_dose_ready(
        school_overrides={"name": "Keel Elementary", "building_code": "KEL71"},
        student_overrides={"full_name": "Kit Marlow", "grade_level": 6,
                           "date_of_birth": "2014-05-05T00:00:00Z",
                           "chronic_condition_codes": ["ASTHMA"]},
        lot_overrides={"medication_code": "ALBUTEROL", "lot_number": "ALB-KEL-1",
                       "initial_quantity": 10},
        order_overrides={"max_doses_per_day": 3})
    nurse_headers = make_nurse_headers(ctx["nurse"]["id"])
    stale_version = order_version(ctx["order"]["id"])
    body = {"visit_id": ctx["visit"]["id"], "authorization_id": ctx["order"]["id"], "units": 1,
            "expected_authorization_version": stale_version}
    validate_success(api.create_administration_record(body, nurse_headers), 201)

    refused = api.create_administration_record(body, nurse_headers)
    validate_error(refused, ApiErrorId.ERR_STALE_AUTHORIZATION_VERSION.value, 412)

    lot = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert lot["quantity_on_hand"] == 9
    assert lot["quantity_reserved"] == 1
    assert validate_success(api.get_health_visit(
        ctx["visit"]["id"], admin_headers))["pending_administration_count"] == 1

    body["expected_authorization_version"] = order_version(ctx["order"]["id"])
    second = validate_success(api.create_administration_record(body, nurse_headers), 201)
    assert second["status"] == "PREPARED"
    after = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert after["quantity_on_hand"] == 8
    assert after["quantity_reserved"] == 2
    assert after["received_total"] == 10
    assert validate_success(api.get_health_visit(
        ctx["visit"]["id"], admin_headers))["pending_administration_count"] == 2
