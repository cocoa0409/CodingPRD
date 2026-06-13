"""Officer/supervisee creation, required-field and enum validation, defaults,
reference resolution, listing, and uniqueness.

Corner queue: entities (create officer, not found, missing field, default,
invalid enum, unknown-officer reference, listing pagination), validations
(officer role mismatch, duplicate docket).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    make_officer_headers,
    create_officer_payload, create_supervisee_payload,
    create_officer, open_supervisee,
)


# ─── Corner: entities / create_officer_returns_201_with_fields ───
def test_create_officer_returns_201_with_echoed_fields(api, compact_admin_headers):
    """PRD §3.1: "A CompactAdministrator registers an officer by supplying the
    officer's full_name, a badge_number, and a role_type that is one of PROBATION
    or PAROLE"
    PRD §2.4: "version is an integer that begins at the resource's initial value
    and increments by one on each mutation."

    Creating an officer returns 201; role_type echoes input and version is 1.

    Design: Corner/entities/create_officer_returns_201_with_fields
    """
    res = api.create_officer(
        create_officer_payload(full_name="Jane Officer", badge_number="B-EXACT-1",
                               role_type="PAROLE", active=True),
        compact_admin_headers,
    )
    officer = validate_success(res, 201)
    assert officer["role_type"] == "PAROLE"
    assert officer["version"] == 1


# ─── Corner: entities / get_supervisee_not_found_returns_404 ───
def test_get_supervisee_not_found(api, officer_headers):
    """PRD §2.5: "The first identifier in the path that does not resolve to an
    existing resource causes the request to be rejected with ERR_NOT_FOUND (HTTP
    404), before any deeper identifier or any business rule is evaluated."

    Design: Corner/entities/get_supervisee_not_found_returns_404
    """
    res = api.get_supervisee(NON_EXISTENT_UUID, officer_headers)
    validate_error(res, "ERR_NOT_FOUND")


# ─── Corner: entities / create_supervisee_missing_required_field ───
def test_create_supervisee_missing_docket_rejected(api):
    """PRD §2.11: "then request well-formedness — required fields present and
    well-typed, enum members valid, integer cents and months at or above their
    declared minimums (ERR_INVALID_REQUEST)"
    PRD §3.1: "The opening payload provides the supervisee's full_name, a
    docket_number, a supervision_type ..."

    Omitting docket_number returns ERR_INVALID_REQUEST.

    Design: Corner/entities/create_supervisee_missing_required_field_returns_invalid_request
    """
    officer = create_officer(role_type="PROBATION")
    oh = make_officer_headers(officer["id"])
    payload = create_supervisee_payload(officer["id"])
    del payload["docket_number"]
    res = api.create_supervisee(payload, oh)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── Corner: entities / officer_active_default_applied ───
def test_officer_active_defaults_true(api, compact_admin_headers):
    """PRD §3.1: "an optional active flag defaults to true when omitted and governs
    whether the officer may be assigned new cases."

    Design: Corner/entities/officer_active_default_applied
    """
    payload = create_officer_payload(full_name="Def Officer", badge_number="B-DEF-1",
                                     role_type="PROBATION")
    payload.pop("active", None)
    res = api.create_officer(payload, compact_admin_headers)
    officer = validate_success(res, 201)
    assert officer["active"] is True


# ─── Corner: entities / create_supervisee_invalid_enum_supervision_type ───
def test_create_supervisee_invalid_supervision_type_rejected(api):
    """PRD §2.11: "request well-formedness — required fields present and well-typed,
    enum members valid ... (ERR_INVALID_REQUEST)"
    PRD §3.1: "a supervision_type of either PROBATION or PAROLE"

    supervision_type="HOUSE_ARREST" (not in the enum) returns ERR_INVALID_REQUEST.

    Design: Corner/entities/create_supervisee_invalid_enum_supervision_type
    """
    officer = create_officer(role_type="PROBATION")
    oh = make_officer_headers(officer["id"])
    payload = create_supervisee_payload(officer["id"], supervision_type="HOUSE_ARREST")
    res = api.create_supervisee(payload, oh)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── Corner: entities / create_supervisee_unknown_officer_reference ───
def test_create_supervisee_unknown_officer_reference(api, officer_headers):
    """PRD §2.5: "When a create request names a related resource — for instance an
    assigned_officer_id ... — and that reference does not point to an existing
    record, the request is rejected with ERR_REFERENCE_NOT_FOUND (HTTP 422)."

    Design: Corner/entities/create_supervisee_unknown_officer_reference_not_found
    """
    payload = create_supervisee_payload(NON_EXISTENT_UUID, docket_number="DK-ORPH-1")
    res = api.create_supervisee(payload, officer_headers)
    validate_error(res, "ERR_REFERENCE_NOT_FOUND")


# ─── Corner: entities / list_supervisees_pagination_envelope ───
def test_list_supervisees_pagination(api):
    """PRD §2.3: "Each list response carries the pagination bookkeeping inside the
    meta object of the envelope, namely limit, offset, total_count, and has_more,
    where total_count is the number of records matching the query before
    pagination and has_more indicates whether records remain beyond the current
    page."

    Two supervisees, limit=1: total_count >= 2, has_more true, one item returned.

    Design: Corner/entities/list_supervisees_pagination_envelope
    """
    officer = create_officer(role_type="PROBATION")
    oh = make_officer_headers(officer["id"])
    open_supervisee(officer["id"], full_name="L1")
    open_supervisee(officer["id"], full_name="L2")
    data, meta = validate_paginated(
        api.list_supervisees(oh, params={"limit": 1, "offset": 0})
    )
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ─── Corner: validations / officer_role_mismatch_rejected ───
def test_officer_role_mismatch_rejected(api):
    """PRD §3.1: "At case-open time the system verifies that the officer named by
    assigned_officer_id has a role_type equal to the supervisee's supervision_type
    and is currently active; if the officer's role does not match the supervision
    track or the officer is not active, the request is rejected with
    ERR_OFFICER_ROLE_MISMATCH (HTTP 422)."

    A PAROLE supervisee assigned to a PROBATION officer is rejected.

    Design: Corner/validations/officer_role_mismatch_rejected
    """
    officer = create_officer(role_type="PROBATION")
    oh = make_officer_headers(officer["id"])
    payload = create_supervisee_payload(officer["id"], supervision_type="PAROLE",
                                        docket_number="DK-MIS-1")
    res = api.create_supervisee(payload, oh)
    validate_error(res, "ERR_OFFICER_ROLE_MISMATCH")


# ─── Corner: validations / duplicate_docket_number_rejected ───
def test_duplicate_docket_number_rejected(api):
    """PRD §3.1: "Docket numbers are unique across all supervisees; a duplicate
    docket_number is rejected with ERR_DUPLICATE_KEY (HTTP 409)."

    Design: Corner/validations/duplicate_docket_number_rejected
    """
    officer = create_officer(role_type="PROBATION")
    oh = make_officer_headers(officer["id"])
    open_supervisee(officer["id"], docket_number="DK-DUP-XYZ")
    payload = create_supervisee_payload(officer["id"], docket_number="DK-DUP-XYZ",
                                        full_name="Dup2")
    res = api.create_supervisee(payload, oh)
    validate_error(res, "ERR_DUPLICATE_KEY")
