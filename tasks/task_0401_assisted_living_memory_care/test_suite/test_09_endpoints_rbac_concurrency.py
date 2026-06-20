"""Endpoint actions and reverse-reachability filters, RBAC enforcement, and the optimistic
concurrency control surface (stale-resident-version finalize, license-action version increment).

Citations are verbatim from PRD.md §2.1, §2.6, §2.9, §3.1, §3.11.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    create_facility, create_resident, create_unit,
    setup_discharged_resident, setup_resident_with_med_order,
    build_user_headers, TEST_USERS,
)

REGISTRAR = TEST_USERS["registrar_headers"]
CLINICAL = TEST_USERS["clinical_director_headers"]
NURSE = TEST_USERS["nurse_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
STAFF = TEST_USERS["staff_headers"]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
def test_mark_clean_returns_unit_to_available(api):
    """PRD §3.1: "A `Registrar` returns a clean bed to service by marking it clean, which
    advances `CLEANING → AVAILABLE`."

    Design: Corner/endpoints/mark_clean_returns_unit_to_available
    """
    ctx = setup_discharged_resident(disposition="OTHER", care_point_rate_cents=2000,
                                    base_rent_cents=400000, move_in_date="2026-06-01")
    # The unit is CLEANING after finalize-discharge.
    before = validate_success(api.get_unit(ctx["unit"]["id"], STAFF), 200)
    assert before["status"] == "CLEANING"
    cleaned = validate_success(api.mark_clean_unit(ctx["facility"]["id"], ctx["unit"]["id"], REGISTRAR), 200)
    assert cleaned["status"] == "AVAILABLE"
    assert cleaned["current_resident_id"] is None


def test_emar_list_by_order_reverse_reachability(api):
    """PRD §3.11: "Administrations may be filtered by `resident_id` and by `medication_order_id`."

    Design: Corner/endpoints/emar_list_by_order_reverse_reachability
    """
    ctx = setup_resident_with_med_order(schedule_times=["08:00"], is_controlled=False)
    get_success_data(api.record_administration(
        ctx["order"]["id"], {"scheduled_time": "08:00", "outcome": "GIVEN"}, NURSE))
    data, meta = validate_paginated(api.list_administrations(STAFF, params={"medication_order_id": ctx["order"]["id"]}))
    assert meta["total_count"] == 1
    assert all(r["medication_order_id"] == ctx["order"]["id"] for r in data)


def test_residents_filtered_by_facility_reverse_reachability(api):
    """PRD §3.11: "Residents may be filtered by `facility_id` and by `assigned_unit_id`, and by
    `status`."

    Design: Corner/endpoints/residents_filtered_by_facility_reverse_reachability
    """
    fac_a = create_facility()
    fac_b = create_facility()
    create_resident(fac_a["id"], full_name="Res A", date_of_birth="1940-01-01")
    create_resident(fac_b["id"], full_name="Res B", date_of_birth="1941-01-01")
    data, meta = validate_paginated(api.list_residents(STAFF, params={"facility_id": fac_a["id"]}))
    assert meta["total_count"] == 1
    assert all(r["facility_id"] == fac_a["id"] for r in data)


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def test_nurse_cannot_create_assessment(api):
    """PRD §2.1: "The `ClinicalDirector` owns acuity assessments and care plans and may also
    place and discontinue medication orders."
    PRD §2.1: "When an authenticated caller invokes an operation their role is not permitted to
    perform, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/nurse_cannot_create_assessment
    """
    fac = create_facility()
    res = create_resident(fac["id"], full_name="Rbac Rita", date_of_birth="1940-01-01")
    resp = api.create_assessment(
        {"resident_id": res["id"], "adl_bathing": 1, "adl_dressing": 1, "adl_toileting": 1,
         "adl_transferring": 1, "adl_eating": 1, "cognition_score": 0, "behavior_flags": 0}, NURSE)
    validate_error(resp, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_registrar_cannot_issue_statement(api):
    """PRD §2.1: "The `BillingClerk` owns billing statements and payments."
    PRD §2.1: "When an authenticated caller invokes an operation their role is not permitted to
    perform, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/registrar_cannot_issue_statement
    """
    fac = create_facility()
    res = create_resident(fac["id"], full_name="Rbac Ron", date_of_birth="1940-01-01")
    stmt = get_success_data(api.create_billing_statement(
        {"resident_id": res["id"], "period_year": 2026, "period_month": 5, "is_first_statement": False}, BILLING))
    resp = api.issue_billing_statement(stmt["id"], REGISTRAR)
    validate_error(resp, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_missing_role_header_returns_context_error(api):
    """PRD §2.1: "If either header is absent, or if the value of `X-User-Role` is not one of the
    recognized role names, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_role_header_returns_context_error
    """
    intruder = build_user_headers("test-intruder-1", "Intruder")
    resp = api.create_facility(
        {"name": "NoRole", "state_code": "CA", "license_number": "CA-502", "care_point_rate_cents": 2000},
        intruder)
    validate_error(resp, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=400)


# ---------------------------------------------------------------------------
# Optimistic concurrency control
# ---------------------------------------------------------------------------
def test_occ_stale_resident_version_on_finalize(api):
    """PRD §2.6: "If the resident's version has advanced since the client read it — most commonly
    because another assessment for the same resident was finalized, which supersedes the prior
    care data and bumps the resident — the finalize is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_resident_version_on_finalize
    """
    fac = create_facility()
    res = get_success_data(api.create_resident(
        {"facility_id": fac["id"], "full_name": "Occ Otto", "date_of_birth": "1940-01-01"}, REGISTRAR))
    res_v0 = res["version"]
    asmt1 = get_success_data(api.create_assessment(
        {"resident_id": res["id"], "adl_bathing": 2, "adl_dressing": 2, "adl_toileting": 2,
         "adl_transferring": 2, "adl_eating": 2, "cognition_score": 0, "behavior_flags": 0}, CLINICAL))
    asmt2 = get_success_data(api.create_assessment(
        {"resident_id": res["id"], "adl_bathing": 3, "adl_dressing": 3, "adl_toileting": 3,
         "adl_transferring": 3, "adl_eating": 3, "cognition_score": 1, "behavior_flags": 0}, CLINICAL))
    # First finalize bumps the resident's version.
    validate_success(api.finalize_assessment(asmt1["id"], {"expected_resident_version": res_v0}, CLINICAL), 200)
    # Second finalize carries the stale pre-bump version.
    resp = api.finalize_assessment(asmt2["id"], {"expected_resident_version": res_v0}, CLINICAL)
    validate_error(resp, "ERR_STALE_VERSION", expected_status=412)
    asmt2_after = validate_success(api.get_assessment(asmt2["id"], STAFF), 200)
    assert asmt2_after["status"] == "DRAFT"


def test_occ_version_increments_on_facility_license_action(api):
    """PRD §2.9: "suspending it advances either `ACTIVE` or `CONDITIONAL` to `SUSPENDED`"
    PRD §2.9: "Each such action increments the facility's `version` by one."
    PRD §2.4: "The `version` is an integer that starts at its initial value and increments by one
    on every mutation of the resource"

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_facility_license_action
    """
    fac = create_facility(creator=COMPLIANCE)
    assert fac["version"] == 1
    suspended = validate_success(api.license_action(
        fac["id"], {"action": "SUSPEND", "expected_facility_version": fac["version"]}, COMPLIANCE), 200)
    assert suspended["license_status"] == "SUSPENDED"
    assert suspended["version"] == 2
