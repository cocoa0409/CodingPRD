"""Entity creation/validation, RBAC denials, auth, wellness reminder math,
computed service_area resolution, defaults, listing/pagination.

Queue B — corner-design entities, validations (auth/rbac), calculations
(next_reminder), state_machines (wellness resume), and listing claims.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    make_clinician_headers,
    build_user_headers,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    set_clock,
    create_service_area,
    create_patient,
    create_tech,
    create_van,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
CLINICIAN = TEST_USERS["clinician_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ===========================================================================
# Corner / entities / create_patient_returns_all_fields
# ===========================================================================

def test_create_patient_returns_all_fields(api):
    """PRD §3.1: "A dispatcher records an `owner_name`, a `species` of `DOG`, `CAT`,
    or `OTHER`, a `weight_kg` that must be strictly greater than 0 (this weight
    drives euthanasia dosing), and a `home_zip` that is matched against
    service-area coverage when visits are booked."
    PRD §2.4: "The `version` field is an integer that starts at 1 on creation and
    increases by exactly 1 on every mutation."

    POST /patients -> 201 carrying species, weight_kg, version==1.

    Design: Corner/entities/create_patient_returns_all_fields
    """
    data = validate_success(
        api.create_patient(
            {"owner_name": "Owner P", "species": "DOG", "weight_kg": 14.5, "home_zip": "11201"},
            DISPATCHER,
        ),
        expected_status=201,
    )
    assert data["species"] == "DOG"
    assert data["weight_kg"] == 14.5
    assert data["version"] == 1


# ===========================================================================
# Corner / entities / get_patient_not_found
# ===========================================================================

def test_get_patient_not_found(api):
    """PRD §2.5: "the first identifier that does not resolve to an existing resource
    causes the request to fail immediately with `ERR_NOT_FOUND`."

    GET /patients/{nonexistent-uuid} -> 404 ERR_NOT_FOUND.

    Design: Corner/entities/get_patient_not_found
    """
    resp = api.get_patient("00000000-0000-0000-0000-000000000000", DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Corner / entities / create_patient_missing_required_field
# ===========================================================================

def test_create_patient_missing_weight_rejected(api):
    """PRD §2.6: "Body well-formedness — required fields present, enum values
    legal, and numeric ranges respected (a `weight_kg` greater than 0, an
    `amount_ml` greater than 0, a `requested_end` strictly later than
    `requested_start`, and a `window_end` strictly later than `window_start`) — is
    reported as `ERR_INVALID_REQUEST`."
    PRD §3.1: "A dispatcher records an `owner_name`, a `species` of `DOG`, `CAT`,
    or `OTHER`, a `weight_kg` that must be strictly greater than 0 (this weight
    drives euthanasia dosing), and a `home_zip` that is matched against
    service-area coverage when visits are booked."

    POST /patients omitting weight_kg -> 400 ERR_INVALID_REQUEST.

    Design: Corner/entities/create_patient_missing_required_field
    """
    resp = api.create_patient(
        {"owner_name": "Owner Q", "species": "CAT", "home_zip": "11201"}, DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner / entities / create_patient_invalid_enum_species
# ===========================================================================

def test_create_patient_invalid_species_enum_rejected(api):
    """PRD §2.6: "Body well-formedness — required fields present, enum values
    legal, and numeric ranges respected (a `weight_kg` greater than 0, an
    `amount_ml` greater than 0, a `requested_end` strictly later than
    `requested_start`, and a `window_end` strictly later than `window_start`) — is
    reported as `ERR_INVALID_REQUEST`."
    PRD §3.1: "A dispatcher records an `owner_name`, a `species` of `DOG`, `CAT`,
    or `OTHER`, a `weight_kg` that must be strictly greater than 0 (this weight
    drives euthanasia dosing), and a `home_zip` that is matched against
    service-area coverage when visits are booked."

    POST /patients with species 'HORSE' -> 400 ERR_INVALID_REQUEST.

    Design: Corner/entities/create_patient_invalid_enum_species
    """
    resp = api.create_patient(
        {"owner_name": "Owner R", "species": "HORSE", "weight_kg": 400, "home_zip": "11201"},
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner / entities / create_patient_nonpositive_weight
# ===========================================================================

def test_create_patient_nonpositive_weight_rejected(api):
    """PRD §2.6: "Body well-formedness — required fields present, enum values
    legal, and numeric ranges respected (a `weight_kg` greater than 0, an
    `amount_ml` greater than 0, a `requested_end` strictly later than
    `requested_start`, and a `window_end` strictly later than `window_start`) — is
    reported as `ERR_INVALID_REQUEST`."

    POST /patients with weight_kg == 0 -> 400 ERR_INVALID_REQUEST.

    Design: Corner/entities/create_patient_nonpositive_weight
    """
    resp = api.create_patient(
        {"owner_name": "Owner S", "species": "DOG", "weight_kg": 0, "home_zip": "11201"},
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner / entities / vet_requires_dea_number
# ===========================================================================

def test_vet_without_dea_number_rejected(api):
    """PRD §3.1: "When the role is `VET`, a `dea_number` and a `dea_expires_on` date
    (a UTC-midnight instant) are required; when the role is `TECH`, both must be
    null."

    POST /clinicians clinician_role==VET without dea_number -> 400
    ERR_INVALID_REQUEST.

    Design: Corner/entities/vet_requires_dea_number
    """
    resp = api.create_clinician(
        {"full_name": "Dr NoDEA", "clinician_role": "VET"}, DISPATCHER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner / entities / service_area_defaults_active_and_euthanasia_allowed
# ===========================================================================

def test_service_area_defaults_active_and_euthanasia_allowed(api):
    """PRD §3.1: "The optional `euthanasia_allowed` flag declares whether in-home
    euthanasia is legally permitted in that ZIP; it defaults to true when not
    supplied. A new area begins in `ACTIVE` status."

    POST /service-areas omitting euthanasia_allowed -> status ACTIVE,
    euthanasia_allowed true.

    Design: Corner/entities/service_area_defaults_active_and_euthanasia_allowed
    """
    data = validate_success(
        api.create_service_area(
            {"zip_code": "11201", "name": "BK North", "travel_surcharge_cents": 500},
            DISPATCHER,
        ),
        expected_status=201,
    )
    assert data["status"] == "ACTIVE"
    assert data["euthanasia_allowed"] is True


# ===========================================================================
# Corner / entities / appointment_resolves_service_area_id_computed
# ===========================================================================

def test_appointment_resolves_service_area_id_from_home_zip(api):
    """PRD §3.2: "At creation the appointment's `service_area_id` is resolved by
    matching the patient's `home_zip` to the `zip_code` of an `ACTIVE` service area,
    and the appointment enters `REQUESTED` status."

    POST /appointments resolves service_area_id to the matching area and starts
    REQUESTED.

    Design: Corner/entities/appointment_resolves_service_area_id_computed
    """
    area = create_service_area(zip_code="11201", travel_surcharge_cents=0)
    pat = create_patient(owner_name="Owner T", species="DOG", weight_kg=12, home_zip="11201")
    appt = validate_success(
        api.create_appointment(
            {"patient_id": pat["id"], "visit_type": "EXAM",
             "requested_start": "2026-03-01T09:00:00Z", "requested_end": "2026-03-01T10:00:00Z"},
            DISPATCHER,
        ),
        expected_status=201,
    )
    assert appt["service_area_id"] == area["id"]
    assert appt["status"] == "REQUESTED"


# ===========================================================================
# Corner / entities / list_appointments_pagination_envelope
# ===========================================================================

def test_list_appointments_pagination_envelope(api):
    """PRD §2.3: "Every list response carries the pagination bookkeeping in the
    `meta` object: `limit`, `offset`, `total_count`, and `has_more`."

    With one appointment for a patient, GET /appointments?patient_id=... returns an
    array with total_count 1 and has_more false.

    Design: Corner/entities/list_appointments_pagination_envelope
    """
    create_service_area(zip_code="11201", travel_surcharge_cents=0)
    pat = create_patient(owner_name="Owner W", species="CAT", weight_kg=4, home_zip="11201")
    validate_success(
        api.create_appointment(
            {"patient_id": pat["id"], "visit_type": "EXAM",
             "requested_start": "2026-03-03T09:00:00Z", "requested_end": "2026-03-03T10:00:00Z"},
            DISPATCHER,
        ),
        expected_status=201,
    )
    resp = api.list_appointments(DISPATCHER, params={"patient_id": pat["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


# ===========================================================================
# Corner / errors / error_invalid_request_window_end_before_start
# ===========================================================================

def test_appointment_window_end_before_start_rejected(api):
    """PRD §2.6: "Body well-formedness — required fields present, enum values
    legal, and numeric ranges respected (a `weight_kg` greater than 0, an
    `amount_ml` greater than 0, a `requested_end` strictly later than
    `requested_start`, and a `window_end` strictly later than `window_start`) — is
    reported as `ERR_INVALID_REQUEST`."

    POST /appointments with requested_end <= requested_start -> 400
    ERR_INVALID_REQUEST.

    Design: Corner/errors/error_invalid_request_window_end_before_start
    """
    create_service_area(zip_code="11201", travel_surcharge_cents=0)
    pat = create_patient(owner_name="Owner S3", species="DOG", weight_kg=12, home_zip="11201")
    resp = api.create_appointment(
        {"patient_id": pat["id"], "visit_type": "EXAM",
         "requested_start": "2026-03-23T10:00:00Z", "requested_end": "2026-03-23T09:00:00Z"},
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Corner / rbac / rbac_tech_cannot_reconcile_route
# ===========================================================================

def test_clinician_cannot_reconcile_route(api):
    """PRD §2.1: "A `ComplianceOfficer` provides controlled-substance oversight —
    reconciling and closing routes and acknowledging referrals."
    PRD §2.1: "When the headers are present but the declared role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    POST /route-days/{id}/reconcile by a Clinician -> 403 ERR_FORBIDDEN_ROLE
    (role check precedes state).

    Design: Corner/rbac/rbac_tech_cannot_reconcile_route
    """
    from test_helpers import create_route_day, create_appointment, book_stop
    create_service_area(zip_code="11201", travel_surcharge_cents=0)
    tech = create_tech("Tech Tm")
    van = create_van(controlled_stock_ml=0, vaccine_stock_count=5, plate="VAN-35")
    pat = create_patient(owner_name="Owner T3", species="DOG", weight_kg=14, home_zip="11201")
    appt = create_appointment(pat["id"], visit_type="EXAM",
                              requested_start="2026-03-24T09:00:00Z",
                              requested_end="2026-03-24T10:00:00Z")
    rd = create_route_day(tech["id"], van["id"], service_date="2026-03-24T00:00:00Z")
    book_stop(rd["id"], appt["id"], rd["version"],
              window_start="2026-03-24T09:00:00Z", window_end="2026-03-24T10:00:00Z")
    get_success_data(api.lock_route_day(rd["id"], DISPATCHER))
    resp = api.reconcile_route_day(rd["id"], make_clinician_headers(tech["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ===========================================================================
# Corner / rbac / rbac_clinician_cannot_create_route_day
# ===========================================================================

def test_clinician_cannot_create_route_day(api):
    """PRD §2.1: "A `Dispatcher` runs the back office — booking appointments,
    building and locking route days."
    PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE`."

    POST /route-days by a Clinician (Dispatcher-exclusive) -> 403 ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/rbac_clinician_cannot_create_route_day
    """
    tech = create_tech("Tech Tn")
    van = create_van(controlled_stock_ml=0, vaccine_stock_count=5, plate="VAN-36")
    resp = api.create_route_day(
        {"clinician_id": tech["id"], "rolling_clinic_id": van["id"],
         "service_date": "2026-03-25T00:00:00Z"},
        make_clinician_headers(tech["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ===========================================================================
# Corner / rbac / missing_auth_header_rejected
# ===========================================================================

def test_missing_auth_header_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_MISSING_AUTH`."

    POST /patients with no auth headers -> 401 ERR_MISSING_AUTH.

    Design: Corner/rbac/missing_auth_header_rejected
    """
    resp = api.create_patient(
        {"owner_name": "Owner U3", "species": "DOG", "weight_kg": 10, "home_zip": "11201"},
        {"Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)


# ===========================================================================
# Corner / calculations / next_reminder_fresh_future_anchor_equals_anchor
# ===========================================================================

def test_next_reminder_fresh_future_anchor_equals_anchor(api):
    """PRD §3.8: "a freshly created plan whose anchor lies in the future has a
    `next_reminder_date` equal to its `anchor_date`."
    PRD §2.10: "At server startup the clock reads exactly `2026-01-01T00:00:00Z`,
    and until it is explicitly moved it never falls back to the host's wall clock."

    Default clock 2026-01-01, future anchor 2026-03-01 -> next_reminder_date ==
    anchor (no advancement).

    Design: Corner/calculations/next_reminder_fresh_future_anchor_equals_anchor
    """
    pat = create_patient(owner_name="Owner I1", species="CAT", weight_kg=4, home_zip="11201")
    plan = validate_success(
        api.create_wellness_plan(
            {"patient_id": pat["id"], "interval_days": 30, "anchor_date": "2026-03-01T00:00:00Z"},
            DISPATCHER,
        ),
        expected_status=201,
    )
    assert plan["next_reminder_date"] == "2026-03-01T00:00:00.000Z", \
        f"fresh future anchor should equal next_reminder, got {plan['next_reminder_date']}"


# ===========================================================================
# Corner / state_machines / wellness_resume_recomputes_reminder_strict_future
# ===========================================================================

def test_wellness_resume_recomputes_reminder_strict_future(api):
    """PRD §3.8: "resuming recomputes `next_reminder_date` against the current clock
    by the same forward-stepping rule."
    PRD §3.8: "The comparison is strict — if a candidate date falls exactly on the
    current clock instant, that instant does not count as being in the future, so
    the system advances one more interval."

    Anchor 2026-03-01 interval 30, clock at exactly anchor+30 (2026-03-31) -> next
    == 2026-04-30, not 2026-03-31.

    Design: Corner/state_machines/wellness_resume_recomputes_reminder_strict_future
    """
    pat = create_patient(owner_name="Owner E1", species="DOG", weight_kg=12, home_zip="11201")
    plan = validate_success(
        api.create_wellness_plan(
            {"patient_id": pat["id"], "interval_days": 30, "anchor_date": "2026-03-01T00:00:00Z"},
            DISPATCHER,
        ),
        expected_status=201,
    )
    validate_success(api.pause_wellness_plan(plan["id"], DISPATCHER))
    set_clock("2026-03-31T00:00:00Z")
    resumed = validate_success(api.resume_wellness_plan(plan["id"], DISPATCHER))
    assert resumed["status"] == "ACTIVE"
    assert resumed["next_reminder_date"] == "2026-04-30T00:00:00.000Z", \
        f"strict-future rule should advance past the clock to 2026-04-30, got {resumed['next_reminder_date']}"
