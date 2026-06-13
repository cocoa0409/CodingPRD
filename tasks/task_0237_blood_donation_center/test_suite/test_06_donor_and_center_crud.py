"""Corner tests: center/donor creation, required fields, type constraints, not-found,
computed eligibility, listing/pagination, and validation-rule violations.

Queue B sections: entities, validations, errors, rbac.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated, get_success_data,
    create_center_payload, create_donor_payload, create_slot_payload,
    create_deferral_payload, advance_clock_payload,
    create_center, create_donor,
    NON_EXISTENT_UUID,
    TEST_USERS,
)

ADMIN = TEST_USERS["center_admin_headers"]
NURSE = TEST_USERS["intake_nurse_headers"]


# ─── entities / create_center_returns_201_with_system_fields ──────────────────
def test_create_center_returns_201_with_system_fields(api):
    """PRD §2.4: "It is initialized to 1970-01-01T00:00:00.000Z at center creation and
    only ever moves forward through the dedicated clock-advance capability."
    PRD §2.4: "a version, an integer that begins at its initial value and increments by
    one on every mutation of the resource."

    A new center carries an id, current_utc at the epoch default, and version 1.

    Design: Corner/entities/create_center_returns_201_with_system_fields
    """
    res = api.create_center(create_center_payload(name="Coastal Blood", region_code="US-WA"), ADMIN)
    center = validate_success(res, 201)
    assert center["current_utc"] == "1970-01-01T00:00:00.000Z"
    assert center["version"] == 1


# ─── entities / register_donor_missing_required_blood_type ────────────────────
def test_register_donor_missing_blood_type_returns_invalid_request(api):
    """PRD §2.6: "all required fields must be present, enum-typed fields must carry a
    recognized value, numeric fields must lie in their permitted range, and datetime
    fields must be valid ISO 8601 — any violation yields ERR_INVALID_REQUEST with HTTP 400."

    Omitting the required blood_type on donor registration -> ERR_INVALID_REQUEST (400).

    Design: Corner/entities/register_donor_missing_required_blood_type_returns_invalid_request
    """
    center = create_center(clock=None)
    payload = create_donor_payload(center["id"], full_name="No Type")
    del payload["blood_type"]
    res = api.create_donor(payload, NURSE)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


# ─── entities / register_donor_invalid_blood_type_enum ────────────────────────
def test_register_donor_invalid_blood_type_enum_returns_invalid_request(api):
    """PRD §2.6: "all required fields must be present, enum-typed fields must carry a
    recognized value, numeric fields must lie in their permitted range, and datetime
    fields must be valid ISO 8601 — any violation yields ERR_INVALID_REQUEST with HTTP 400."

    A blood_type of 'Z_POS' is not a recognized enum value -> ERR_INVALID_REQUEST (400).

    Design: Corner/entities/register_donor_invalid_blood_type_enum_returns_invalid_request
    """
    center = create_center(clock=None)
    res = api.create_donor(
        create_donor_payload(center["id"], full_name="Bad Enum", blood_type="Z_POS"), NURSE)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


# ─── entities / get_donor_nonexistent_id ──────────────────────────────────────
def test_get_donor_nonexistent_id_returns_donor_not_found(api):
    """PRD §2.5: "The first identifier that does not resolve to an existing resource
    causes the request to be rejected with the matching not-found error (ERR_NOT_FOUND
    generically, or the resource-specific variant such as ERR_CENTER_NOT_FOUND,
    ERR_DONOR_NOT_FOUND ...), all returned with HTTP 404."

    Design: Corner/entities/get_donor_nonexistent_id_returns_donor_not_found
    """
    res = api.get_donor(NON_EXISTENT_UUID, NURSE)
    validate_error(res, "ERR_DONOR_NOT_FOUND", expected_status=404)


# ─── entities / donor_underage_eligibility_computed_from_dob ──────────────────
def test_donor_under_18_computed_underage(api):
    """PRD §3.2: "At registration the system computes eligibility_status: if the donor's
    age at the center's current_utc is less than 18 years, the status is UNDERAGE;
    otherwise it is ELIGIBLE."

    A donor born 2008-06-01 registered at current_utc 2025-01-01 (age 16) is UNDERAGE.

    Design: Corner/entities/donor_underage_eligibility_computed_from_dob
    """
    center = create_center(clock="2025-01-01T00:00:00.000Z")
    res = api.create_donor(
        create_donor_payload(center["id"], full_name="Teen Tess", date_of_birth="2008-06-01",
                            weight_kg=55, blood_type="O_POS"), NURSE)
    donor = validate_success(res, 201)
    assert donor["eligibility_status"] == "UNDERAGE", "age 16 < 18 at 2025-01-01 -> UNDERAGE"


# ─── entities / list_donors_pagination_envelope ───────────────────────────────
def test_list_donors_pagination_envelope(api):
    """PRD §2.3: "Each list response includes the following fields in the meta object of
    the envelope: limit, offset, total_count, and has_more."

    Listing two donors with limit 1 returns an array envelope with total_count 2 and
    has_more true.

    Design: Corner/entities/list_donors_pagination_envelope
    """
    center = create_center(clock=None)
    create_donor(center["id"], full_name="D One", date_of_birth="1990-01-01", blood_type="O_POS")
    create_donor(center["id"], full_name="D Two", date_of_birth="1991-01-01", blood_type="A_POS")

    data, meta = validate_paginated(
        api.list_donors(NURSE, params={"center_id": center["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ─── validations / permanent_deferral_with_duration_days ──────────────────────
def test_permanent_deferral_with_duration_days_returns_invalid_duration(api):
    """PRD §3.2: "A temporary deferral must carry a duration_days that is an integer of at
    least 1; a permanent deferral must not carry duration_days at all. Violating this — a
    temporary deferral with a missing or sub-1 duration_days, or a permanent deferral that
    includes duration_days — is rejected with ERR_INVALID_DEFERRAL_DURATION at HTTP 422."

    Design: Corner/validations/permanent_deferral_with_duration_days_returns_invalid_duration
    """
    center = create_center(clock=None)
    donor = create_donor(center["id"], full_name="Perm Dur")
    res = api.create_deferral(
        create_deferral_payload(donor["id"], category="INFECTIOUS_RISK", kind="PERMANENT",
                              reason="positive history", duration_days=30), NURSE)
    validate_error(res, "ERR_INVALID_DEFERRAL_DURATION", expected_status=422)


# ─── validations / slot_ends_before_starts ────────────────────────────────────
def test_slot_ends_before_starts_returns_invalid_slot_window(api):
    """PRD §3.3: "The window must be valid: ends_at must be strictly after starts_at,
    otherwise ERR_INVALID_SLOT_WINDOW (HTTP 422) is returned."

    Design: Corner/validations/slot_ends_before_starts_returns_invalid_slot_window
    """
    center = create_center(clock=None)
    res = api.create_slot(
        create_slot_payload(center["id"], donation_type="WHOLE",
                          starts_at="2025-01-02T17:00:00.000Z", ends_at="2025-01-02T09:00:00.000Z",
                          capacity=5), ADMIN)
    validate_error(res, "ERR_INVALID_SLOT_WINDOW", expected_status=422)


# ─── validations / clock_advance_backwards ────────────────────────────────────
def test_clock_advance_backwards_returns_not_monotonic(api):
    """PRD §3.1: "The target must be strictly after the center's existing current_utc; an
    equal or earlier target is rejected with ERR_CLOCK_NOT_MONOTONIC."

    Design: Corner/validations/clock_advance_backwards_returns_not_monotonic
    """
    center = create_center(clock="2025-06-01T00:00:00.000Z")
    res = api.advance_clock(center["id"], advance_clock_payload("2025-05-01T00:00:00.000Z"), ADMIN)
    validate_error(res, "ERR_CLOCK_NOT_MONOTONIC", expected_status=409)


# ─── validations / lift_infectious_risk_deferral ──────────────────────────────
def test_lift_infectious_risk_deferral_returns_not_liftable(api):
    """PRD §3.2: "Critically, a deferral whose category is INFECTIOUS_RISK can never be
    lifted; such an attempt is rejected with ERR_INFECTIOUS_DEFERRAL_NOT_LIFTABLE."

    Design: Corner/validations/lift_infectious_risk_deferral_returns_not_liftable
    """
    center = create_center(clock=None)
    donor = create_donor(center["id"], full_name="Inf Risk")
    # PERMANENT deferral must not carry duration_days, so build the body without it.
    deferral_payload = {
        "donor_id": donor["id"], "category": "INFECTIOUS_RISK", "kind": "PERMANENT",
        "reason": "confirmed positive",
    }
    deferral = get_success_data(api.create_deferral(deferral_payload, NURSE))
    res = api.lift_deferral(deferral["id"], NURSE)
    validate_error(res, "ERR_INFECTIOUS_DEFERRAL_NOT_LIFTABLE", expected_status=409)


# ─── rbac / missing_user_context_header ───────────────────────────────────────
def test_unknown_role_returns_missing_user_context_header(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role is not one of the
    recognized roles, the request is rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."

    A request with an unknown X-User-Role is rejected before any business logic (400).

    Design: Corner/rbac/missing_user_context_header_returns_400
    """
    bad_headers = {"X-User-ID": "u1", "X-User-Role": "NotARole", "Content-Type": "application/json"}
    res = api.create_center(create_center_payload(name="Bad Role", region_code="US-CA"), bad_headers)
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=400)
