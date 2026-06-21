"""Role-based access control and generic error surfaces (authentication,
forbidden role, leaf not-found, and field-validation ERR_VALIDATION).
"""
import pytest

from test_helpers import (
    validate_error,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_provider_headers,
    make_anonymous_headers,
    setup_base_practice,
    create_cash_patient,
    create_checked_in_with_signed_soap,
    setup_attended_insurance_visit,
    setup_active_plan,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]
BILLING = TEST_USERS["billing_headers"]


# ===========================================================================
# Corner: rbac / frontdesk_cannot_complete_appointment
# ===========================================================================
def test_frontdesk_cannot_complete_appointment(api):
    """PRD §2.1: "A `Provider` is a licensed chiropractor who owns all clinical
    authorship — ... and completing appointments."
    PRD §2.1: "When the headers are well-formed but the named role is not
    permitted to perform the requested operation ... the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/frontdesk_cannot_complete_appointment
    """
    base = setup_base_practice()
    patient = create_cash_patient("RBAC Rae")
    pid = patient["id"]
    appt = create_checked_in_with_signed_soap(
        pid, base["provider"]["id"], base["room"]["id"], scheduled_start="2026-03-03T17:00:00Z"
    )
    res = api.complete_appointment(pid, appt["id"], FRONTDESK)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


# ===========================================================================
# Corner: rbac / provider_cannot_adjudicate
# ===========================================================================
def test_provider_cannot_adjudicate(api):
    """PRD §2.1: "A `BillingClerk` owns the money flow downstream of attendance —
    adjudicating insurance and writing off charges."
    PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/provider_cannot_adjudicate
    """
    ctx = setup_attended_insurance_visit()
    pid = ctx["patient"]["id"]
    appt = ctx["appointment"]
    res = api.adjudicate_appointment(pid, appt["id"], make_provider_headers(ctx["provider"]["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


# ===========================================================================
# Corner: rbac / missing_auth_header_unauthenticated
# ===========================================================================
def test_missing_auth_header_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` does not name one
    of these four known roles, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_header_unauthenticated
    """
    res = api.list_patients(make_anonymous_headers())
    validate_error(res, "ERR_UNAUTHENTICATED")


# ===========================================================================
# Corner: errors / resource_not_found_leaf_appointment
# ===========================================================================
def test_resource_not_found_leaf_appointment(api):
    """PRD §2.6: "only then does it look up the nested leaf resource, rejecting
    with `ERR_RESOURCE_NOT_FOUND` if the leaf (an appointment, exam, plan, phase,
    series, SOAP note, provider, or room named in the path) does not resolve."

    Design: Corner/errors/resource_not_found_leaf_appointment
    """
    patient = create_cash_patient("Leaf Liz")
    res = api.get_appointment(patient["id"], NON_EXISTENT_UUID, FRONTDESK)
    validate_error(res, "ERR_RESOURCE_NOT_FOUND")


# ===========================================================================
# Corner: errors / validation_error_empty_weekday_pattern
# ===========================================================================
def test_validation_error_empty_weekday_pattern(api):
    """PRD §3.9: "Other semantic body validations ... likewise surface as
    `ERR_VALIDATION`: a series `weekday_pattern` must be non-empty with every
    entry in the range 0 through 6".

    Design: Corner/errors/validation_error_empty_weekday_pattern
    """
    ctx = setup_active_plan(
        payer_mode="CASH",
        phases=[{"phase_type": "ACUTE", "sequence_index": 0, "visits_per_week": 3, "planned_visit_count": 2}],
    )
    pid = ctx["patient"]["id"]
    prov_id = ctx["provider"]["id"]
    res = api.create_series(
        pid,
        ctx["plan"]["id"],
        {
            "plan_phase_id": ctx["phases"][0]["id"],
            "provider_id": prov_id,
            "treatment_room_id": ctx["room"]["id"],
            "start_date": "2026-03-09",
            "weekday_pattern": [],
            "start_time_minutes": 540,
            "duration_minutes": 15,
        },
        FRONTDESK,
    )
    validate_error(res, "ERR_VALIDATION")
