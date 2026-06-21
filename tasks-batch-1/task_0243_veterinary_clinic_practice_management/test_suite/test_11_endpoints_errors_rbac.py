"""Filtered/paginated listing, reverse-reachability, FK-not-found on surgery booking,
and role-based access control (forbidden ops, unknown role).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, build_user_headers,
    create_household, create_patient, create_operatory,
    create_estimate, present_estimate, approve_estimate, create_appointment_in_exam,
    book_surgery, create_appointment,
    TEST_USERS,
)

RECEPTIONIST = TEST_USERS["receptionist_headers"]
VETERINARIAN = TEST_USERS["veterinarian_headers"]
PRACTICE_MANAGER = TEST_USERS["practice_manager_headers"]

NON_EXISTENT = "00000000-0000-4000-8000-0000000000aa"


def test_list_patients_filtered_by_household_pagination(api):
    """PRD 2.8: "owners and patients filter by `household_id`" and "A filter that names a
    foreign key restricts the returned collection to rows whose corresponding field
    matches." PRD 2.3: "Each list response surfaces the pagination bookkeeping in the
    `meta` object via the fields `limit`, `offset`, `total_count`, and `has_more`."

    Two patients in a household; limit=1 returns one row, total_count 2, has_more true.

    Design: Corner/endpoints/list_patients_filtered_by_household_pagination
    """
    hh = create_household("Phi")
    create_patient(household_id=hh["id"], name="P-A", species="DOG", weight_kg=10)
    create_patient(household_id=hh["id"], name="P-B", species="CAT", weight_kg=4)
    data, meta = validate_paginated(api.list_patients(
        RECEPTIONIST, params={"household_id": hh["id"], "limit": 1, "offset": 0}))
    assert len(data) == 1, f"Expected 1 row, got {len(data)}"
    assert meta["total_count"] == 2, f"Expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"Expected has_more True, got {meta['has_more']}"


def test_surgeries_reverse_reachable_by_appointment(api):
    """PRD 2.8: "surgeries filter by `appointment_id`, `operatory_id`, or `estimate_id`"
    and "A filter that names a foreign key restricts the returned collection to rows whose
    corresponding field matches."

    A surgery created under an appointment is discoverable via
    GET /clinic/surgeries?appointment_id=.

    Design: Corner/endpoints/surgeries_reverse_reachable_after_cascade_create
    """
    operatory = create_operatory(cleanup_buffer_minutes=30, name="OR-R")
    hh = create_household("Chi")
    _, pat = create_patient(household_id=hh["id"], name="RevPet",
                            species="DOG", weight_kg=10)
    est = create_estimate(pat["id"], line_items=[
        {"service_code": "S", "qty": 1, "unit_price_cents": 30000, "eligible_for_plan_discount": False}],
        deposit_required_cents=0)
    present_estimate(est["id"])
    approve_estimate(est["id"])
    appt = create_appointment_in_exam(pat["id"],
                                      scheduled_start="2026-08-07T09:00:00Z",
                                      scheduled_end="2026-08-07T12:00:00Z")
    surgery = book_surgery(appt["id"], operatory["id"], est["id"],
                           window_start="2026-08-07T09:00:00Z",
                           window_end="2026-08-07T10:00:00Z", procedure_name="Disc")
    data, _ = validate_paginated(api.list_surgeries(
        VETERINARIAN, params={"appointment_id": appt["id"]}))
    ids = [row["id"] for row in data]
    assert surgery["id"] in ids, f"Expected surgery {surgery['id']} in {ids}"


def test_operatory_not_found_on_surgery_booking(api):
    """PRD 2.8: "a surgery booking whose `operatory_id`, `estimate_id`, or `appointment_id`
    does not exist ... are each rejected with that resource type's not-found error" — here
    ERR_OPERATORY_NOT_FOUND.

    Design: Corner/errors/operatory_not_found_on_surgery_booking
    """
    hh = create_household("Psi")
    _, pat = create_patient(household_id=hh["id"], name="NoOR",
                            species="DOG", weight_kg=10)
    est = create_estimate(pat["id"], line_items=[
        {"service_code": "S", "qty": 1, "unit_price_cents": 30000, "eligible_for_plan_discount": False}],
        deposit_required_cents=0)
    present_estimate(est["id"])
    approve_estimate(est["id"])
    appt = create_appointment_in_exam(pat["id"],
                                      scheduled_start="2026-08-08T09:00:00Z",
                                      scheduled_end="2026-08-08T12:00:00Z")
    res = api.create_surgery({
        "appointment_id": appt["id"], "operatory_id": NON_EXISTENT,
        "estimate_id": est["id"], "procedure_name": "Ghost",
        "window_start": "2026-08-08T09:00:00Z",
        "window_end": "2026-08-08T10:00:00Z",
    }, VETERINARIAN)
    validate_error(res, "ERR_OPERATORY_NOT_FOUND", expected_status=404)


def test_receptionist_cannot_finalize_invoice(api):
    """PRD 3.11: "The **Invoice** is the immutable, finalized household bill, and only a
    practice manager may finalize one." PRD 2.1: a role not permitted for the operation is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

    A Receptionist calling POST /clinic/invoices is forbidden.

    Design: Corner/rbac/receptionist_cannot_finalize_invoice
    """
    hh = validate_success(api.create_household({"account_name": "Aud"}, RECEPTIONIST), 201)
    v0 = hh["version"]
    _, pat = create_patient(household_id=hh["id"], name="RbacPet",
                            species="DOG", weight_kg=10)
    appt = create_appointment(pat["id"], scheduled_start="2026-08-09T09:00:00Z",
                              scheduled_end="2026-08-09T10:00:00Z", visit_reason="Wellness")
    res = api.create_invoice({
        "household_id": hh["id"], "appointment_id": appt["id"],
        "expected_household_version": v0,
    }, RECEPTIONIST)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_veterinarian_cannot_create_operatory(api):
    """PRD 4 (endpoint table): POST /clinic/operatories is authorized for PracticeManager
    only. PRD 2.1: a role not permitted is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

    A Veterinarian calling POST /clinic/operatories is forbidden.

    Design: Corner/rbac/veterinarian_cannot_create_operatory
    """
    res = api.create_operatory({"name": "Sneaky OR"}, VETERINARIAN)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_unknown_role_rejected_with_missing_user_context(api):
    """PRD 2.1: "if `X-User-Role` is not one of these three known roles, the request is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401)."

    A request with an unknown role is rejected before any business logic.

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    ghost_headers = build_user_headers("ghost-1", "Ghost")
    res = api.create_household({"account_name": "NoAuth"}, ghost_headers)
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT", expected_status=401)
