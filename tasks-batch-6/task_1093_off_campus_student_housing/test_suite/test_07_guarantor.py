"""Guarantor underwriting: negotiation cycle, income-multiple gate boundary,
decline cascade, max-rounds, and the not-required / already-open guard.

Translates corner instances (decline cascade, max-rounds, not-required) and two
difficulty instances: `guarantor_application_info_requested_negotiation_cycle`
and `guarantor_income_multiple_exactly_at_gate_is_approvable` (queue A).
"""
from test_helpers import validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS
from test_helpers import fixtures as fx
from test_helpers import make_student_headers

ADMIN = TEST_USERS["admin_headers"]
MGR = TEST_USERS["manager_headers"]


def _guarantor_base(api, rent=130000):
    """University SU + Oak Lofts + one 2-bed unit at `rent` (so
    guarantor_required is true), LISTED. Returns base dict."""
    return fx.base_property(api, rent=rent, bed_labels=("A", "B"),
                            unit_over={"unit_number": "202", "floorplan_code": "2x1",
                                       "bathroom_count": 1})


def _pending_guarantor_lease(api, base, email, income, name="Ava Lead"):
    student = fx.verified_student(api, base["uni"]["id"], email, full_name=name)
    lease = fx.draft_lease(api, student["id"], base["unit"]["id"], "A")
    fx.submit_lease(api, lease["id"], student["id"])
    app = validate_success(api.create_guarantor_application(
        {"lease_id": lease["id"], "guarantor_full_name": "Pat Lead",
         "guarantor_annual_income_cents": income, "relationship": "PARENT"},
        make_student_headers(student["id"])), 201)
    return student, lease, app


def test_guarantor_negotiation_cycle_recomputes_income_multiple(api):
    """PRD §3.5: "The student answers an INFO_REQUESTED round by resubmitting
    revised guarantor_full_name and guarantor_annual_income_cents; this replaces
    those values, recomputes income_multiple_bps, increments round_count by 1,
    and returns the application to SUBMITTED".

    Design: Difficulty/non_linear_state_machine/guarantor_application_info_requested_negotiation_cycle
    """
    base = _guarantor_base(api)
    student, lease, app = _pending_guarantor_lease(api, base, "ava@su.edu", 4679844)
    assert app["income_multiple_bps"] == 29999
    api.review_guarantor_application(app["id"], {"decision": "START_REVIEW"}, MGR)
    ri = validate_success(api.review_guarantor_application(app["id"],
                          {"decision": "REQUEST_INFO", "note": "Send two recent pay stubs"}, MGR), 200)
    assert ri["status"] == "INFO_REQUESTED"
    rs = validate_success(api.resubmit_guarantor_application(app["id"],
                          {"guarantor_full_name": "Pat Lead", "guarantor_annual_income_cents": 4680000},
                          make_student_headers(student["id"])), 200)
    assert rs["status"] == "SUBMITTED" and rs["round_count"] == 2 and rs["income_multiple_bps"] == 30000


def test_guarantor_cycle_second_lap_approves_and_cascades_lease(api):
    """PRD §3.5: "APPROVE requires the lease still PENDING_GUARANTOR and requires
    the application's income_multiple_bps to be at least 30000 ... Approval sets
    the application APPROVED ... and cascades the lease PENDING_GUARANTOR ->
    PENDING_SIGNATURE."

    Design: Difficulty/non_linear_state_machine/guarantor_application_info_requested_negotiation_cycle
    """
    base = _guarantor_base(api)
    student, lease, app = _pending_guarantor_lease(api, base, "ava@su.edu", 4679844)
    api.review_guarantor_application(app["id"], {"decision": "START_REVIEW"}, MGR)
    api.review_guarantor_application(app["id"], {"decision": "REQUEST_INFO", "note": "stubs"}, MGR)
    api.resubmit_guarantor_application(app["id"],
        {"guarantor_full_name": "Pat Lead", "guarantor_annual_income_cents": 4680000},
        make_student_headers(student["id"]))
    sr = validate_success(api.review_guarantor_application(app["id"], {"decision": "START_REVIEW"}, MGR), 200)
    assert sr["status"] == "UNDER_REVIEW"
    ap = validate_success(api.review_guarantor_application(app["id"], {"decision": "APPROVE"}, MGR), 200)
    assert ap["status"] == "APPROVED"
    lease_after = fx.get_lease(api, lease["id"])
    assert lease_after["lease_status"] == "PENDING_SIGNATURE"
    assert lease_after["guarantor_required"] is True and lease_after["monthly_rent_cents"] == 130000


def test_guarantor_income_exactly_at_gate_is_approvable(api):
    """PRD §3.5: "requires the application's income_multiple_bps to be at least
    30000 - an exact 3.0000x multiple passes". PRD §3.5: "taking the floor -
    this basis-point multiple is never rounded up."

    Design: Difficulty/boundary_precision_check/guarantor_income_multiple_exactly_at_gate_is_approvable
    """
    base = _guarantor_base(api)
    s1, la, ga_exact = _pending_guarantor_lease(api, base, "ava@su.edu", 4680000)
    assert ga_exact["income_multiple_bps"] == 30000
    api.review_guarantor_application(ga_exact["id"], {"decision": "START_REVIEW"}, MGR)
    ap = validate_success(api.review_guarantor_application(ga_exact["id"], {"decision": "APPROVE"}, MGR), 200)
    assert ap["status"] == "APPROVED"
    assert fx.get_lease(api, la["id"])["lease_status"] == "PENDING_SIGNATURE"


def test_guarantor_income_one_bp_short_is_refused(api):
    """PRD §3.5: "one basis point short is refused with
    ERR_GUARANTOR_INCOME_INSUFFICIENT."

    Design: Difficulty/boundary_precision_check/guarantor_income_multiple_exactly_at_gate_is_approvable
    """
    base = _guarantor_base(api)
    s1, la, ga_low = _pending_guarantor_lease(api, base, "ava@su.edu", 4679844)
    assert ga_low["income_multiple_bps"] == 29999
    api.review_guarantor_application(ga_low["id"], {"decision": "START_REVIEW"}, MGR)
    validate_error(api.review_guarantor_application(ga_low["id"], {"decision": "APPROVE"}, MGR),
                   ApiErrorId.ERR_GUARANTOR_INCOME_INSUFFICIENT.value)
    app = api.get_guarantor_application(ga_low["id"], ADMIN).json()["data"]
    assert app["status"] == "UNDER_REVIEW"
    assert fx.get_lease(api, la["id"])["lease_status"] == "PENDING_GUARANTOR"


def test_guarantor_decline_cascades_lease_to_cancelled_and_frees_bed(api):
    """PRD §3.5: "DECLINE sets the application DECLINED, stamps decided_at and
    reviewer_user_id, and cascades the lease PENDING_GUARANTOR -> CANCELLED,
    which releases the bed slot and re-runs the unit and property rollups."

    Design: Corner/state_machines/guarantor_decline_cascades_lease_to_cancelled_and_frees_bed
    """
    base = _guarantor_base(api)
    student, lease, app = _pending_guarantor_lease(api, base, "ava@su.edu", 2000000)
    api.review_guarantor_application(app["id"], {"decision": "START_REVIEW"}, MGR)
    dec = validate_success(api.review_guarantor_application(app["id"],
                           {"decision": "DECLINE", "note": "Income too low"}, MGR), 200)
    assert dec["status"] == "DECLINED" and dec["reviewer_user_id"] == "mgr-1" and dec["decided_at"] is not None
    assert dec["income_multiple_bps"] == 12820
    lease_after = fx.get_lease(api, lease["id"])
    assert lease_after["lease_status"] == "CANCELLED" and lease_after["terminated_at"] is not None
    unit = fx.get_unit(api, base["unit"]["id"])
    assert unit["leased_bed_count"] == 0 and unit["available_bed_count"] == 2
    assert unit["occupancy_status"] == "AVAILABLE"
    prop = fx.get_property(api, base["prop"]["id"])
    assert prop["available_bed_count"] == 2 and prop["status"] == "LISTED"


def test_guarantor_resubmit_beyond_max_rounds_rejected(api):
    """PRD §3.5: "A resubmit is refused with ERR_GUARANTOR_MAX_ROUNDS_EXCEEDED
    once round_count has already reached 3."

    Design: Corner/state_machines/guarantor_resubmit_beyond_max_rounds_rejected
    """
    base = _guarantor_base(api)
    student, lease, app = _pending_guarantor_lease(api, base, "ava@su.edu", 2000000)
    sid = make_student_headers(student["id"])
    api.review_guarantor_application(app["id"], {"decision": "START_REVIEW"}, MGR)
    api.review_guarantor_application(app["id"], {"decision": "REQUEST_INFO", "note": "Round one"}, MGR)
    api.resubmit_guarantor_application(app["id"],
        {"guarantor_full_name": "Pat Lead", "guarantor_annual_income_cents": 3000000}, sid)
    api.review_guarantor_application(app["id"], {"decision": "START_REVIEW"}, MGR)
    api.review_guarantor_application(app["id"], {"decision": "REQUEST_INFO", "note": "Round two"}, MGR)
    third = validate_success(api.resubmit_guarantor_application(app["id"],
            {"guarantor_full_name": "Pat Lead", "guarantor_annual_income_cents": 4000000}, sid), 200)
    assert third["round_count"] == 3 and third["status"] == "SUBMITTED" and third["income_multiple_bps"] == 25641
    api.review_guarantor_application(app["id"], {"decision": "START_REVIEW"}, MGR)
    api.review_guarantor_application(app["id"], {"decision": "REQUEST_INFO", "note": "Round three"}, MGR)
    validate_error(api.resubmit_guarantor_application(app["id"],
                   {"guarantor_full_name": "Pat Lead", "guarantor_annual_income_cents": 5000000}, sid),
                   ApiErrorId.ERR_GUARANTOR_MAX_ROUNDS_EXCEEDED.value)
    after = api.get_guarantor_application(app["id"], ADMIN).json()["data"]
    assert after["status"] == "INFO_REQUESTED" and after["round_count"] == 3
    assert after["guarantor_annual_income_cents"] == 4000000
    assert fx.get_lease(api, lease["id"])["lease_status"] == "PENDING_GUARANTOR"


def test_guarantor_application_not_required_or_already_open_rejected(api):
    """PRD §3.5: "The application may only be filed against a lease whose
    guarantor_required is true and which does not already hold an application in
    SUBMITTED, UNDER_REVIEW, INFO_REQUESTED, or APPROVED; otherwise it is
    refused with ERR_GUARANTOR_NOT_REQUIRED."

    Design: Corner/state_machines/guarantor_application_not_required_or_already_open_rejected
    """
    uni = fx.create_university(api)
    prop1 = fx.create_property(api, uni["id"], name="Maple Commons")
    unit1 = fx.create_unit(api, prop1["id"], bedroom_count=4, bed_labels=["A", "B", "C", "D"],
                           base_rent_cents_per_bed_monthly=90000)
    fx.list_property(api, prop1["id"])
    prop2 = fx.create_property(api, uni["id"], name="Oak Lofts")
    unit2 = fx.create_unit(api, prop2["id"], unit_number="202", floorplan_code="2x1",
                           bedroom_count=2, bathroom_count=1, bed_labels=["A", "B"],
                           base_rent_cents_per_bed_monthly=130000)
    fx.list_property(api, prop2["id"])
    s1 = fx.verified_student(api, uni["id"], "ava@su.edu", full_name="Ava Lead")
    s2 = fx.verified_student(api, uni["id"], "ben@su.edu", full_name="Ben Two",
                             cleanliness_level=3, noise_tolerance=4)
    l_low = fx.draft_lease(api, s1["id"], unit1["id"], "A")
    fx.submit_lease(api, l_low["id"], s1["id"])
    l_high = fx.draft_lease(api, s2["id"], unit2["id"], "A")
    fx.submit_lease(api, l_high["id"], s2["id"])
    ga_open = validate_success(api.create_guarantor_application(
        {"lease_id": l_high["id"], "guarantor_full_name": "Robin Two",
         "guarantor_annual_income_cents": 5000000, "relationship": "GUARDIAN"},
        make_student_headers(s2["id"])), 201)
    # guarantor_required == false
    validate_error(api.create_guarantor_application(
        {"lease_id": l_low["id"], "guarantor_full_name": "Pat Lead",
         "guarantor_annual_income_cents": 6000000, "relationship": "PARENT"},
        make_student_headers(s1["id"])), ApiErrorId.ERR_GUARANTOR_NOT_REQUIRED.value)
    # already holds an open application
    validate_error(api.create_guarantor_application(
        {"lease_id": l_high["id"], "guarantor_full_name": "Second Robin",
         "guarantor_annual_income_cents": 7000000, "relationship": "OTHER"},
        make_student_headers(s2["id"])), ApiErrorId.ERR_GUARANTOR_NOT_REQUIRED.value)
    assert fx.get_lease(api, l_low["id"])["guarantor_required"] is False
    assert fx.get_lease(api, l_low["id"])["lease_status"] == "PENDING_SIGNATURE"
    assert fx.get_lease(api, l_high["id"])["guarantor_required"] is True
    assert fx.get_lease(api, l_high["id"])["lease_status"] == "PENDING_GUARANTOR"
    _, low_meta = validate_paginated(api.list_guarantor_applications(ADMIN, params={"lease_id": l_low["id"]}))
    assert low_meta["total_count"] == 0
    high, high_meta = validate_paginated(api.list_guarantor_applications(ADMIN, params={"lease_id": l_high["id"]}))
    assert high_meta["total_count"] == 1 and high[0]["id"] == ga_open["id"]
