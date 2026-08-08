"""Authentication, authorization, and ownership boundaries.

Translates the corner `validations` auth/ownership instances and the `rbac`
instance `university_partner_cannot_terminate_a_lease` (queue B).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    build_user_headers,
)
from test_helpers import fixtures as fx
from test_helpers import make_student_headers, make_manager_headers, make_partner_headers

ADMIN = TEST_USERS["admin_headers"]
MGR = TEST_USERS["manager_headers"]
MGR2 = TEST_USERS["manager2_headers"]


def test_missing_auth_headers_return_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if X-User-Role is not one of
    these four names, the request is rejected with ERR_UNAUTHENTICATED (HTTP
    401)."

    Design: Corner/validations/missing_auth_headers_return_unauthenticated
    """
    uni = fx.create_university(api)
    bad = build_user_headers("who-1", "Wizard")  # role is not one of the four
    validate_error(api.get_university(uni["id"], bad), ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_role_without_endpoint_permission_returns_unauthorized(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not
    permitted to reach the target endpoint, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/validations/role_without_endpoint_permission_returns_unauthorized
    """
    uni = fx.create_university(api)
    s1 = fx.create_student(api, uni["id"], "ava@su.edu", full_name="Ava Lead")
    resp = api.create_university({"name": "Rogue U", "code": "RG", "partner_tier": "STANDARD",
                                  "verification_required": False,
                                  "academic_year_start_date": "2026-08-15",
                                  "academic_year_end_date": "2027-05-15",
                                  "partner_admin_user_id": "x"}, make_student_headers(s1["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_property_manager_cannot_act_on_another_managers_property(api):
    """PRD §2.1: "every PropertyManager mutation on that property - and on its
    units, amenities, leases, guarantor applications and sublets - requires
    X-User-ID to equal that stored manager_user_id." PRD §2.9: ownership else
    ERR_NOT_RESOURCE_OWNER.

    Design: Corner/validations/property_manager_cannot_act_on_another_managers_property
    """
    uni = fx.create_university(api)
    prop = fx.create_property(api, uni["id"], manager_id="mgr-1")
    resp = api.create_unit({"property_id": prop["id"], "unit_number": "101",
                            "floorplan_code": "4x2", "bedroom_count": 4, "bathroom_count": 2,
                            "bed_labels": ["A", "B", "C", "D"],
                            "base_rent_cents_per_bed_monthly": 90000}, MGR2)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert fx.get_property(api, prop["id"])["unit_count"] == 0


def test_student_cannot_pay_another_students_installment(api):
    """PRD §2.1: "ownership checks on any resource that references a student
    compare that resource's student foreign key to X-User-ID." PRD §3.6: "The
    owning student pays a charge".

    Design: Corner/validations/student_cannot_pay_another_students_installment
    """
    sc = fx.setup_active_lease(api, installment_count=10)
    s2 = fx.verified_student(api, sc["uni"]["id"], "ben@su.edu", full_name="Ben Two",
                             cleanliness_level=3, noise_tolerance=4)
    fx.set_clock(api, "2026-08-16T00:00:00Z")
    i1 = fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])[0]
    validate_error(api.pay_installment(i1["id"], {"amount_cents": 98667},
                   make_student_headers(s2["id"])), ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert fx.rent_installments(api, sc["lease"]["id"], sc["student_id"])[0]["status"] == "SCHEDULED"
    ok = validate_success(api.pay_installment(i1["id"], {"amount_cents": 98667},
                          make_student_headers(sc["student_id"])), 200)
    assert ok["status"] == "PAID"
    assert fx.get_property(api, sc["prop"]["id"])["escrow_balance_cents"] == 98667


def test_university_partner_cannot_decide_other_universitys_student(api):
    """PRD §2.1: "a partner may decide an enrollment verification only for
    students whose university names their X-User-ID as its
    partner_admin_user_id."

    Design: Corner/validations/university_partner_cannot_decide_other_universitys_student
    """
    uni_a = fx.create_university(api, name="Alpha U", code="ALPHA", partner_admin_user_id="admin-alpha")
    uni_b = fx.create_university(api, name="Beta U", code="BETA", partner_admin_user_id="admin-beta")
    sa = fx.create_student(api, uni_a["id"], "ava@alpha.edu", full_name="Ava Alpha")
    api.request_verification(sa["id"], make_student_headers(sa["id"]))
    validate_error(api.decide_verification(sa["id"], {"decision": "APPROVE"},
                   make_partner_headers("admin-beta")), ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert fx.get_student(api, sa["id"])["verification_status"] == "PENDING"
    ok = validate_success(api.decide_verification(sa["id"], {"decision": "APPROVE"},
                          make_partner_headers("admin-alpha")), 200)
    assert ok["verification_status"] == "VERIFIED"
    assert api.get_university(uni_a["id"], ADMIN).json()["data"]["verified_student_count"] == 1
    assert api.get_university(uni_b["id"], ADMIN).json()["data"]["verified_student_count"] == 0


def test_university_partner_cannot_terminate_a_lease(api):
    """PRD §2.1: "UniversityPartner is campus housing-office staff whose sole
    write capability is deciding enrollment verifications." PRD §4: /leases/{id}/
    terminate is authorized for PropertyManager only.

    Design: Corner/rbac/university_partner_cannot_terminate_a_lease
    """
    sc = fx.setup_active_lease(api, installment_count=10)
    resp = api.terminate_lease(sc["lease"]["id"], make_partner_headers("uni-admin-su"),
                               {"reason": "not my job"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert fx.get_lease(api, sc["lease"]["id"])["lease_status"] == "ACTIVE"
