"""Composite setup helpers.

Every test starts against an empty database with the logical clock at its
default instant, so each helper builds its preconditions from scratch using
only endpoints the PRD declares. Setup calls use the lenient validator so a
broken precondition surfaces as a setup failure rather than a confusing
assertion inside the test body.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import MONDAY_0900, TEST_DEFAULTS
from .factories import (
    action_plan_payload,
    coverage_assignment_payload,
    disclosure_request_payload,
    health_visit_payload,
    medication_authorization_payload,
    nurse_payload,
    school_payload,
    screening_payload,
    stock_lot_payload,
    student_payload,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_aide_headers,
    make_guardian_headers,
    make_nurse_headers,
    make_physician_headers,
    make_records_officer_headers,
)

ADMIN = TEST_USERS["admin_headers"]


def _actor_headers(user_id, role):
    if role == "HealthAide":
        return make_aide_headers(user_id)
    return make_nurse_headers(user_id)


# --------------------------------------------------------------------------
# Clock and operations
# --------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def run_checkpoint(school_id: str = None) -> dict:
    payload = {"school_id": school_id} if school_id else {}
    return get_success_data(api_client.run_daily_checkpoint(payload, ADMIN))


# --------------------------------------------------------------------------
# Tier 1 — single-record creation
# --------------------------------------------------------------------------
def create_school(**overrides) -> dict:
    return get_success_data(api_client.create_school(school_payload(**overrides), ADMIN))


def read_school(school_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_school(school_id, headers or ADMIN))


def create_nurse(**overrides) -> dict:
    return get_success_data(api_client.create_nurse(nurse_payload(**overrides), ADMIN))


def read_nurse(nurse_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_nurse(nurse_id, headers or ADMIN))


def patch_nurse(nurse_id: str, payload: dict) -> dict:
    return get_success_data(api_client.patch_nurse(nurse_id, payload, ADMIN))


def create_coverage(nurse_id: str, school_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_coverage_assignment(
        coverage_assignment_payload(nurse_id, school_id, **overrides), ADMIN))


def end_coverage(coverage_id: str, effective_to: str) -> dict:
    return get_success_data(api_client.end_coverage_assignment(
        coverage_id, {"effective_to": effective_to}, ADMIN))


def create_student(school_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_student(student_payload(school_id, **overrides), ADMIN))


def read_student(student_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_student(student_id, headers or ADMIN))


def student_version(student_id: str) -> int:
    return read_student(student_id)["version"]


def amend_student(student_id: str, payload: dict, headers=None) -> dict:
    return get_success_data(api_client.patch_student(student_id, payload, headers or ADMIN))


def create_lot(school_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_stock_lot(stock_lot_payload(school_id, **overrides), ADMIN))


def read_lot(lot_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_stock_lot(lot_id, headers or ADMIN))


def inventory_action(lot_id: str, action: str, units: int = None,
                     reason_code: str = None, expected_lot_version: int = None) -> dict:
    if expected_lot_version is None:
        expected_lot_version = read_lot(lot_id)["version"]
    payload = {"action": action, "expected_lot_version": expected_lot_version}
    if units is not None:
        payload["units"] = units
    if reason_code is not None:
        payload["reason_code"] = reason_code
    return get_success_data(api_client.lot_inventory_action(lot_id, payload, ADMIN))


# --------------------------------------------------------------------------
# Tier 2 — action plans
# --------------------------------------------------------------------------
def create_plan(student_id: str, nurse_id: str, expected_student_version: int = None, **overrides) -> dict:
    if expected_student_version is None:
        expected_student_version = student_version(student_id)
    payload = action_plan_payload(student_id, expected_student_version, **overrides)
    return get_success_data(api_client.create_action_plan(payload, make_nurse_headers(nurse_id)))


def read_plan(plan_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_action_plan(plan_id, headers or ADMIN))


def submit_plan(plan_id: str, nurse_id: str) -> dict:
    return get_success_data(api_client.submit_action_plan(plan_id, make_nurse_headers(nurse_id)))


def guardian_consent_plan(plan_id: str, student_id: str) -> dict:
    return get_success_data(api_client.guardian_consent_action_plan(plan_id, make_guardian_headers(student_id)))


def decide_plan(plan_id: str, decision: str, note: str = None, physician_user_id: str = None) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    headers = make_physician_headers(physician_user_id) if physician_user_id else TEST_USERS["physician_headers"]
    return get_success_data(api_client.decide_action_plan(plan_id, payload, headers))


def create_active_plan(student_id: str, nurse_id: str, **overrides) -> dict:
    """Draft -> submit -> guardian consent -> physician approval. Returns the ACTIVE plan."""
    plan = create_plan(student_id, nurse_id, **overrides)
    submit_plan(plan["id"], nurse_id)
    guardian_consent_plan(plan["id"], student_id)
    return decide_plan(plan["id"], "APPROVE", note="Plan signed")


# --------------------------------------------------------------------------
# Tier 2 — medication orders
# --------------------------------------------------------------------------
def create_order(student_id: str, nurse_id: str, **overrides) -> dict:
    payload = medication_authorization_payload(student_id, **overrides)
    return get_success_data(api_client.create_medication_authorization(payload, make_nurse_headers(nurse_id)))


def read_order(auth_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_medication_authorization(auth_id, headers or ADMIN))


def order_version(auth_id: str) -> int:
    return read_order(auth_id)["version"]


def grant_order_consent(auth_id: str, student_id: str) -> dict:
    return get_success_data(api_client.consent_medication_authorization(
        auth_id, {"decision": "GRANT"}, make_guardian_headers(student_id)))


def withdraw_order_consent(auth_id: str, student_id: str) -> dict:
    return get_success_data(api_client.consent_medication_authorization(
        auth_id, {"decision": "WITHDRAW"}, make_guardian_headers(student_id)))


def verify_order(auth_id: str, nurse_id: str) -> dict:
    return get_success_data(api_client.clinical_review_medication_authorization(
        auth_id, {"decision": "VERIFY"}, make_nurse_headers(nurse_id)))


def suspend_order(auth_id: str, physician_user_id: str = None) -> dict:
    headers = make_physician_headers(physician_user_id) if physician_user_id else TEST_USERS["physician_headers"]
    return get_success_data(api_client.clinical_review_medication_authorization(
        auth_id, {"decision": "SUSPEND"}, headers))


def create_ready_order(student_id: str, nurse_id: str, **overrides) -> dict:
    """Create an order, record guardian consent and clinically verify it."""
    order = create_order(student_id, nurse_id, **overrides)
    grant_order_consent(order["id"], student_id)
    return verify_order(order["id"], nurse_id)


# --------------------------------------------------------------------------
# Tier 3 — encounters
# --------------------------------------------------------------------------
def open_visit(student_id: str, school_id: str, nurse_id: str, role: str = "SchoolNurse", **overrides) -> dict:
    payload = health_visit_payload(student_id, school_id, nurse_id, **overrides)
    return get_success_data(api_client.create_health_visit(payload, _actor_headers(nurse_id, role)))


def read_visit(visit_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_health_visit(visit_id, headers or ADMIN))


def assess_visit(visit_id: str, nurse_id: str, assessment_note: str = "Assessment recorded",
                 role: str = "SchoolNurse") -> dict:
    return get_success_data(api_client.assess_health_visit(
        visit_id, {"assessment_note": assessment_note}, _actor_headers(nurse_id, role)))


def dispose_visit(visit_id: str, nurse_id: str, disposition: str = "RETURN_TO_CLASS",
                  role: str = "SchoolNurse", **extra) -> dict:
    payload = {"disposition": disposition}
    payload.update(extra)
    return get_success_data(api_client.dispose_health_visit(visit_id, payload, _actor_headers(nurse_id, role)))


def close_visit(visit_id: str, nurse_id: str, role: str = "SchoolNurse") -> dict:
    return get_success_data(api_client.close_health_visit(visit_id, _actor_headers(nurse_id, role)))


def reopen_visit(visit_id: str, nurse_id: str, reason_code: str = None) -> dict:
    payload = {"reason_code": reason_code} if reason_code else {}
    return get_success_data(api_client.reopen_health_visit(visit_id, make_nurse_headers(nurse_id), payload))


# --------------------------------------------------------------------------
# Tier 3 — doses
# --------------------------------------------------------------------------
def prepare_dose(visit_id: str, auth_id: str, nurse_id: str, units: int = 1,
                 witness_nurse_id: str = None, role: str = "SchoolNurse",
                 expected_authorization_version: int = None) -> dict:
    if expected_authorization_version is None:
        expected_authorization_version = order_version(auth_id)
    payload = {
        "visit_id": visit_id,
        "authorization_id": auth_id,
        "units": units,
        "expected_authorization_version": expected_authorization_version,
    }
    if witness_nurse_id is not None:
        payload["witness_nurse_id"] = witness_nurse_id
    return get_success_data(api_client.create_administration_record(payload, _actor_headers(nurse_id, role)))


def prepare_stock_dose(visit_id: str, medication_code: str, nurse_id: str, units: int = 1,
                       witness_nurse_id: str = None, role: str = "SchoolNurse") -> dict:
    payload = {"visit_id": visit_id, "medication_code": medication_code, "units": units}
    if witness_nurse_id is not None:
        payload["witness_nurse_id"] = witness_nurse_id
    return get_success_data(api_client.create_stock_emergency_record(payload, _actor_headers(nurse_id, role)))


def read_record(record_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_administration_record(record_id, headers or ADMIN))


def record_outcome(record_id: str, outcome: str, nurse_id: str, role: str = "SchoolNurse", **extra) -> dict:
    payload = {"outcome": outcome}
    payload.update(extra)
    return get_success_data(api_client.record_administration_outcome(
        record_id, payload, _actor_headers(nurse_id, role)))


def void_record(record_id: str, nurse_id: str, reason_code: str = "Charted in error") -> dict:
    return get_success_data(api_client.void_administration_record(
        record_id, {"reason_code": reason_code}, make_nurse_headers(nurse_id)))


# --------------------------------------------------------------------------
# Tier 3 — screenings
# --------------------------------------------------------------------------
def create_screening(student_id: str, school_id: str, nurse_id: str, **overrides) -> dict:
    payload = screening_payload(student_id, school_id, **overrides)
    return get_success_data(api_client.create_screening(payload, make_nurse_headers(nurse_id)))


def read_screening(screening_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_screening(screening_id, headers or ADMIN))


def record_screening_result(screening_id: str, result_value, nurse_id: str,
                            screened_by_nurse_id: str = None) -> dict:
    payload = {"result_value": result_value,
               "screened_by_nurse_id": screened_by_nurse_id or nurse_id}
    return get_success_data(api_client.record_screening_result(
        screening_id, payload, make_nurse_headers(nurse_id)))


def screening_follow_up(screening_id: str, nurse_id: str, action: str, **extra) -> dict:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(api_client.screening_follow_up(
        screening_id, payload, make_nurse_headers(nurse_id)))


# --------------------------------------------------------------------------
# Tier 3 — records release
# --------------------------------------------------------------------------
def create_disclosure(student_id: str, officer_user_id: str = None, **overrides) -> dict:
    payload = disclosure_request_payload(student_id, **overrides)
    headers = make_records_officer_headers(officer_user_id) if officer_user_id else TEST_USERS["records_officer_headers"]
    return get_success_data(api_client.create_disclosure_request(payload, headers))


def read_disclosure(request_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_disclosure_request(
        request_id, headers or TEST_USERS["records_officer_headers"]))


def submit_disclosure(request_id: str, officer_user_id: str = None) -> dict:
    headers = make_records_officer_headers(officer_user_id) if officer_user_id else TEST_USERS["records_officer_headers"]
    return get_success_data(api_client.submit_disclosure_request(request_id, headers))


def consent_disclosure(request_id: str, student_id: str, decision: str = "GRANT") -> dict:
    return get_success_data(api_client.guardian_consent_disclosure_request(
        request_id, {"decision": decision}, make_guardian_headers(student_id)))


def decide_disclosure(request_id: str, decision: str = "APPROVE",
                      physician_user_id: str = None, **extra) -> dict:
    payload = {"decision": decision}
    payload.update(extra)
    headers = make_physician_headers(physician_user_id) if physician_user_id else TEST_USERS["physician_headers"]
    return get_success_data(api_client.decide_disclosure_request(request_id, payload, headers))


def release_disclosure(request_id: str, officer_user_id: str = None) -> dict:
    headers = make_records_officer_headers(officer_user_id) if officer_user_id else TEST_USERS["records_officer_alt_headers"]
    return get_success_data(api_client.release_disclosure_request(request_id, headers))


def create_approved_disclosure(student_id: str, officer_user_id: str = None,
                               physician_user_id: str = None, **overrides) -> dict:
    """Open -> submit -> guardian consent -> physician approval. Returns the APPROVED request."""
    request = create_disclosure(student_id, officer_user_id=officer_user_id, **overrides)
    submit_disclosure(request["id"], officer_user_id)
    consent_disclosure(request["id"], student_id)
    return decide_disclosure(request["id"], "APPROVE", physician_user_id=physician_user_id)


# --------------------------------------------------------------------------
# Tier 4 — composite scenarios
# --------------------------------------------------------------------------
def setup_school_with_coverage(school_overrides=None, nurse_overrides=None, coverage_overrides=None) -> dict:
    """One building plus one nurse holding a Monday block, which lifts the posture off UNCOVERED."""
    school = create_school(**(school_overrides or {}))
    nurse = create_nurse(**(nurse_overrides or {}))
    coverage = create_coverage(nurse["id"], school["id"], **(coverage_overrides or {}))
    return {"school": school, "nurse": nurse, "coverage": coverage}


def setup_basic_scenario(school_overrides=None, nurse_overrides=None,
                         coverage_overrides=None, student_overrides=None) -> dict:
    """Building + nurse on coverage + one enrolled student."""
    base = setup_school_with_coverage(school_overrides, nurse_overrides, coverage_overrides)
    base["student"] = create_student(base["school"]["id"], **(student_overrides or {}))
    return base


def setup_visit_in_assessment(school_overrides=None, nurse_overrides=None,
                              coverage_overrides=None, student_overrides=None,
                              visit_overrides=None, clock: str = MONDAY_0900) -> dict:
    """Building, nurse on an ACTIVE Monday block, student, and one IN_ASSESSMENT encounter."""
    base = setup_basic_scenario(school_overrides, nurse_overrides, coverage_overrides, student_overrides)
    set_clock(clock)
    visit = open_visit(base["student"]["id"], base["school"]["id"], base["nurse"]["id"],
                       **(visit_overrides or {}))
    assess_visit(visit["id"], base["nurse"]["id"])
    base["visit"] = read_visit(visit["id"])
    return base


def setup_dose_ready(lot_overrides=None, order_overrides=None, school_overrides=None,
                     nurse_overrides=None, coverage_overrides=None, student_overrides=None,
                     visit_overrides=None, clock: str = MONDAY_0900, assess: bool = True) -> dict:
    """Everything a dose reservation needs.

    Building + nurse on an ACTIVE Monday block + enrolled student + one student-specific
    stock lot + one order at (CONSENT_GRANTED, VERIFIED) + one encounter, assessed by default.
    """
    base = setup_basic_scenario(school_overrides, nurse_overrides, coverage_overrides, student_overrides)
    school_id, nurse_id, student_id = base["school"]["id"], base["nurse"]["id"], base["student"]["id"]
    base["lot"] = create_lot(school_id, **(lot_overrides or {}))
    base["order"] = create_ready_order(student_id, nurse_id, **(order_overrides or {}))
    set_clock(clock)
    visit = open_visit(student_id, school_id, nurse_id,
                       **({"complaint_code": "MEDICATION"} | (visit_overrides or {})))
    if assess:
        assess_visit(visit["id"], nurse_id)
    base["visit"] = read_visit(visit["id"])
    return base


def setup_dose_prepared(units: int = 1, **kwargs) -> dict:
    """setup_dose_ready plus one PREPARED administration record for `units`."""
    base = setup_dose_ready(**kwargs)
    base["record"] = prepare_dose(base["visit"]["id"], base["order"]["id"], base["nurse"]["id"], units=units)
    base["visit"] = read_visit(base["visit"]["id"])
    base["lot"] = read_lot(base["lot"]["id"])
    return base


def setup_closed_visit(clock_open: str = MONDAY_0900, clock_close: str = "2026-08-03T09:30:00Z",
                       disposition: str = "RETURN_TO_CLASS", **kwargs) -> dict:
    """An encounter driven all the way to CLOSED, ready for a reopen test."""
    base = setup_visit_in_assessment(clock=clock_open, **kwargs)
    dispose_visit(base["visit"]["id"], base["nurse"]["id"], disposition)
    set_clock(clock_close)
    base["visit"] = close_visit(base["visit"]["id"], base["nurse"]["id"])
    return base


def setup_stock_school(epinephrine_units: int = 10, albuterol_units: int = 36,
                       student_overrides=None, school_overrides=None,
                       nurse_overrides=None, coverage_overrides=None) -> dict:
    """A building whose undesignated stock is in place, so the protocol status can read READY."""
    base = setup_basic_scenario(school_overrides, nurse_overrides, coverage_overrides, student_overrides)
    school_id = base["school"]["id"]
    base["epinephrine_lot"] = create_lot(
        school_id, medication_code="EPINEPHRINE", lot_number="EPI-STOCK-1",
        is_stock_protocol=True, initial_quantity=epinephrine_units)
    base["albuterol_lot"] = create_lot(
        school_id, medication_code="ALBUTEROL", lot_number="ALB-STOCK-1",
        is_stock_protocol=True, initial_quantity=albuterol_units)
    base["school"] = read_school(school_id)
    return base
