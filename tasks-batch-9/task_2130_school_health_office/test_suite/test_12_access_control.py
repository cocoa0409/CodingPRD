"""Authentication, role permission, resource ownership and the two-person rules."""

import pytest

from test_helpers import *  # noqa: F401,F403

JSON_ONLY_HEADERS = {"Content-Type": "application/json"}


def test_a_request_without_the_role_header_is_unauthenticated(api, admin_headers):
    """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`, identifying the
    acting principal, and `X-User-Role`, naming the role that principal is acting in. If either
    header is absent, or if `X-User-Role` is not one of the six declared role names, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about the request is
    inspected."

    Design: Corner/rbac/request_without_role_header_returns_unauthenticated
    """
    create_school(name="Anchor Elementary", building_code="ANC61")

    resp = api.create_school(
        {"name": "Ghost Elementary", "building_code": "GST61", "cot_capacity": 2,
         "emergency_protocol_enabled": True}, JSON_ONLY_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_a_guardian_may_not_register_a_building(api, admin_headers):
    """PRD §2.1: "If the headers are well formed but the named role does not appear in the target
    endpoint's authorised-role list, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §2.1: "A **`Guardian`** is a parent or guardian acting for exactly one student. Guardians
    grant or withdraw consent on action plans, on medication orders and on records-release
    requests, and may read that one child's student row, action plans, medication orders,
    encounters, screenings and disclosure requests."

    Design: Corner/rbac/guardian_cannot_create_a_school_returns_forbidden
    """
    school = create_school(name="Beacon Elementary", building_code="BCN62")
    student = create_student(school["id"], full_name="Bo Iversen", grade_level=3,
                             date_of_birth="2017-05-05T00:00:00Z")

    resp = api.create_school(
        {"name": "Guardian Annex", "building_code": "GRD62", "cot_capacity": 2,
         "emergency_protocol_enabled": True}, make_guardian_headers(student["id"]))
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)


def test_a_guardian_may_not_consent_for_another_familys_child(api, admin_headers):
    """PRD §2.1: "When `X-User-Role` is `Guardian`, `X-User-ID` is the `id` of the acting
    `Student`; ownership checks on any resource that references a `Student` compare the resource's
    `student_id` to `X-User-ID`."
    PRD §2.1: "Any write by an entity-backed role against a row it does not own is refused with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/guardian_cannot_consent_on_another_students_order
    """
    school = create_school(name="Candlewood Elementary", building_code="CDL63")
    nurse = create_nurse(full_name="Rita Nolan", credential="RN", weekly_contracted_minutes=2400)
    student_a = create_student(school["id"], full_name="Cass Ahmed", grade_level=4,
                               date_of_birth="2016-06-06T00:00:00Z")
    student_b = create_student(school["id"], full_name="Cleo Ahmed", grade_level=6,
                               date_of_birth="2014-06-06T00:00:00Z",
                               chronic_condition_codes=["ASTHMA"])
    order_b = create_order(student_b["id"], nurse["id"])

    resp = api.consent_medication_authorization(
        order_b["id"], {"decision": "GRANT"}, make_guardian_headers(student_a["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    unchanged = validate_success(api.get_medication_authorization(order_b["id"], admin_headers))
    assert unchanged["consent_status"] == "CONSENT_PENDING"
    assert unchanged["clinical_status"] == "UNVERIFIED"
    assert unchanged["dispensable"] is False


def test_a_health_aide_may_not_reopen_a_closed_encounter(api, admin_headers):
    """PRD §2.1: "An aide has no exclusive operations, cannot reopen an encounter, cannot verify a
    medication order, cannot void a record, and cannot touch action plans or screenings."
    PRD §3.6: "Only a school nurse may reopen, and only within 120 minutes of closure: a reopen at
    or after that deadline is refused with `ERR_REOPEN_WINDOW_CLOSED` (HTTP 409) at ladder position
    36."

    Design: Corner/rbac/health_aide_cannot_reopen_a_closed_encounter
    """
    ctx = setup_closed_visit(
        school_overrides={"name": "Driftwood Elementary", "building_code": "DRF64"},
        student_overrides={"full_name": "Dax Miller", "grade_level": 2,
                           "date_of_birth": "2018-07-07T00:00:00Z"},
        visit_overrides={"complaint_code": "INJURY"})
    aide = create_nurse(full_name="Dee Aponte", credential="HEALTH_AIDE",
                        weekly_contracted_minutes=900, delegation_authorized=True)

    resp = api.reopen_health_visit(ctx["visit"]["id"], make_aide_headers(aide["id"]),
                                   {"reason_code": "Aide attempt"})
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    unchanged = validate_success(api.get_health_visit(ctx["visit"]["id"], admin_headers))
    assert unchanged["status"] == "CLOSED"
    assert unchanged["reopen_count"] == 0
    assert unchanged["closed_at"].startswith("2026-08-03T09:30:00")
    assert validate_success(api.get_school(ctx["school"]["id"], admin_headers))["occupied_cot_count"] == 0


def test_a_nurse_may_not_assess_an_encounter_owned_by_a_colleague(api, admin_headers):
    """PRD §2.1: "When `X-User-Role` is `SchoolNurse` or `HealthAide`, `X-User-ID` is the `id` of
    the acting `Nurse`; ownership checks compare `HealthVisit.nurse_id` to `X-User-ID` on the
    assess, dispose, close and reopen steps, and compare `AdministrationRecord.administering_nurse_id`
    to `X-User-ID` on the outcome and void steps."
    PRD §2.7: "Position 3 guards every `Guardian` endpoint, the four encounter steps just named,
    and the two administration-record steps just named."

    Design: Corner/rbac/nurse_cannot_assess_another_nurses_encounter
    """
    school = create_school(name="Ember Elementary", building_code="EMB65")
    nurse_one = create_nurse(full_name="Rita Nolan", credential="RN", weekly_contracted_minutes=2400)
    nurse_two = create_nurse(full_name="Eve Salgado", credential="RN", weekly_contracted_minutes=2400)
    create_coverage(nurse_one["id"], school["id"], weekday="MON", start_minute=480, end_minute=960)
    create_coverage(nurse_two["id"], school["id"], weekday="MON", start_minute=480, end_minute=780)
    student = create_student(school["id"], full_name="Etta Brook", grade_level=5,
                             date_of_birth="2015-11-11T00:00:00Z")
    set_clock(MONDAY_0900)
    visit = open_visit(student["id"], school["id"], nurse_one["id"], complaint_code="ILLNESS")

    resp = api.assess_health_visit(
        visit["id"], {"assessment_note": "Second nurse attempting the assessment"},
        make_nurse_headers(nurse_two["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    unchanged = validate_success(api.get_health_visit(visit["id"], admin_headers))
    assert unchanged["status"] == "OPEN"
    assert unchanged.get("assessment_note") is None
    assert unchanged["nurse_id"] == nurse_one["id"]


def test_a_controlled_dose_needs_a_witness_other_than_the_administering_nurse(api, admin_headers):
    """PRD §2.9: "On a controlled dose, the supplied `witness_nurse_id` must differ from the
    administering nurse."
    PRD §2.9: "All three violations return the same code, `ERR_SEGREGATION_OF_DUTIES` (HTTP 403),
    and that check sits at ladder position 22 — guarding dose preparation, the dose outcome step,
    screening follow-up and disclosure release."

    Design: Corner/rbac/witness_cannot_equal_the_administering_nurse_on_a_controlled_dose
    """
    ctx = setup_dose_ready(
        school_overrides={"name": "Forge Elementary", "building_code": "FRG66"},
        student_overrides={"full_name": "Fio Larkin", "grade_level": 8,
                           "date_of_birth": "2012-08-18T00:00:00Z",
                           "chronic_condition_codes": ["MENTAL_HEALTH"]},
        lot_overrides={"medication_code": "METHYLPHENIDATE", "lot_number": "MPH-FRG-1",
                       "initial_quantity": 5},
        order_overrides={"medication_code": "METHYLPHENIDATE", "route": "ORAL",
                         "dose_amount": 10, "dose_unit": "MG", "max_doses_per_day": 1})
    nurse_one = ctx["nurse"]
    nurse_two = create_nurse(full_name="Fay Osborn", credential="RN", weekly_contracted_minutes=2400)
    nurse_headers = make_nurse_headers(nurse_one["id"])

    self_witnessed = api.create_administration_record(
        {"visit_id": ctx["visit"]["id"], "authorization_id": ctx["order"]["id"], "units": 1,
         "expected_authorization_version": order_version(ctx["order"]["id"]),
         "witness_nurse_id": nurse_one["id"]}, nurse_headers)
    validate_error(self_witnessed, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    lot = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert lot["quantity_on_hand"] == 5
    assert lot["quantity_reserved"] == 0

    accepted = validate_success(api.create_administration_record(
        {"visit_id": ctx["visit"]["id"], "authorization_id": ctx["order"]["id"], "units": 1,
         "expected_authorization_version": order_version(ctx["order"]["id"]),
         "witness_nurse_id": nurse_two["id"]}, nurse_headers), 201)
    assert accepted["status"] == "PREPARED"
    assert accepted["witness_nurse_id"] == nurse_two["id"]
    assert accepted["administering_nurse_id"] == nurse_one["id"]
    after = validate_success(api.get_stock_lot(ctx["lot"]["id"], admin_headers))
    assert after["quantity_on_hand"] == 4
    assert after["quantity_reserved"] == 1


def test_a_delegated_aide_can_run_a_whole_encounter(api, admin_headers):
    """PRD §2.1: "Encounter creation, assessment, disposition and closure, and the three
    administration steps, are shared with `HealthAide`."
    PRD §3.6: "On closure `closed_at` is stamped with the clock, `status` becomes `CLOSED`,
    `minutes_in_office` is set to the whole minutes between `arrival_at` and `closed_at` with any
    fraction discarded, and the student's observed score, effective score and tier are recomputed."

    Design: Corner/rbac/health_aide_performs_shared_encounter_operations_end_to_end
    """
    school = create_school(name="Inlet Elementary", building_code="INL69")
    aide = create_nurse(full_name="Ida Petit", credential="HEALTH_AIDE",
                        weekly_contracted_minutes=1200, delegation_authorized=True)
    create_coverage(aide["id"], school["id"], weekday="MON", start_minute=480, end_minute=960)
    student = create_student(school["id"], full_name="Ike Danko", grade_level=1,
                             date_of_birth="2019-03-03T00:00:00Z")
    building = validate_success(api.get_school(school["id"], admin_headers))
    assert building["delivered_weekly_minutes"] == pytest.approx(144.0, abs=0.01)
    assert building["coverage_posture"] == "LIMITED"
    set_clock(MONDAY_0900)
    aide_headers = make_aide_headers(aide["id"])

    created = validate_success(api.create_health_visit(
        {"student_id": student["id"], "school_id": school["id"], "nurse_id": aide["id"],
         "complaint_code": "INJURY", "acuity": "ROUTINE"}, aide_headers), 201)
    assert created["nurse_id"] == aide["id"]
    assert created["triage_score"] == 28
    assert created["requires_ems_review"] is False

    assessed = validate_success(api.assess_health_visit(
        created["id"], {"assessment_note": "Grazed elbow cleaned"}, aide_headers))
    assert assessed["status"] == "IN_ASSESSMENT"

    disposed = validate_success(api.dispose_health_visit(
        created["id"], {"disposition": "RETURN_TO_CLASS"}, aide_headers))
    assert disposed["disposition"] == "RETURN_TO_CLASS"

    set_clock("2026-08-03T09:30:00Z")
    closed = validate_success(api.close_health_visit(created["id"], aide_headers))
    assert closed["status"] == "CLOSED"
    assert closed["minutes_in_office"] == 30
    assert validate_success(api.get_school(school["id"], admin_headers))["occupied_cot_count"] == 0
