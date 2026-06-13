"""Resource creation, defaults, not-found handling, pagination, demographics
sync idempotency, and auth (PRD §2.1, §2.3, §2.5, §3.1, §3.2, §3.9).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    build_user_headers,
    TEST_USERS,
    fixtures,
)

FRONT = TEST_USERS["front_desk_headers"]
ADMIN = TEST_USERS["clinic_admin_headers"]


def test_create_clinic_minimal_applies_defaults(api):
    """PRD §3.1: "A clinic is created with a `name` and a set of operational knobs, each of which has a default."
    PRD §3.1: "`copay_rounding`, an enum that is either `PER_LINE_THEN_SUM` (the default) or `SUM_THEN_ROUND`"
    PRD §2.9: "Both totals start at zero when the clinic is created."

    Design: Corner/entities/create_clinic_minimal_required_fields
    """
    data = validate_success(api.create_clinic({"name": "Solo Clinic"}, ADMIN), expected_status=201)
    assert data["form_expiration_hours"] == 72
    assert data["copay_rounding"] == "PER_LINE_THEN_SUM"
    assert data["collected_copay_cents"] == 0
    assert data["active_queue_count"] == 0
    assert data["version"] == 1


def test_create_appointment_missing_start_utc_rejected(api):
    """PRD §3.2: "fixes the visit window with `start_utc` and `end_utc` (the end must be strictly after the start)."

    Design: Corner/entities/create_appointment_missing_required_field
    """
    clinic = fixtures.create_clinic(name="CE1")
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])

    resp = api.create_appointment(
        {"clinic_id": clinic["id"], "provider_id": provider["id"],
         "patient_id": patient["id"], "end_utc": "2026-07-01T10:30:00.000Z"},
        FRONT,
    )
    validate_error(resp, "ERR_INVALID_REQUEST")


def test_get_nonexistent_intake_session_404(api):
    """PRD §2.5: "the system validates them left-to-right and rejects on the first
    identifier that does not resolve, returning the not-found error specific to
    that resource type."
    PRD §2.5: "`ERR_SESSION_NOT_FOUND` for an intake session"

    Design: Corner/entities/get_nonexistent_intake_session_404
    """
    resp = api.get_intake_session("00000000-0000-4000-8000-000000000000", FRONT)
    validate_error(resp, "ERR_SESSION_NOT_FOUND")


def test_appointment_provisional_copay_is_computed_estimate(api):
    """PRD §3.2: "the estimate deliberately ignores deductible and coinsurance and simply uses the posted office-visit copay, `plan_default_copay_cents`, as the provisional figure."

    Design: Corner/entities/appointment_provisional_copay_computed_input_ignored
    """
    clinic = fixtures.create_clinic(name="CE2")
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])
    data = validate_success(api.create_appointment(
        {"clinic_id": clinic["id"], "provider_id": provider["id"], "patient_id": patient["id"],
         "start_utc": "2026-07-02T10:00:00.000Z", "end_utc": "2026-07-02T10:30:00.000Z",
         "plan_default_copay_cents": 2500},
        FRONT,
    ), expected_status=201)
    assert data["provisional_copay_cents"] == 2500
    assert data["status"] == "SCHEDULED"


def test_list_appointments_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return."
    PRD §2.3: "Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_appointments_pagination_envelope
    """
    clinic = fixtures.create_clinic(name="CE16")
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])
    fixtures.create_appointment(
        clinic["id"], provider["id"], patient["id"],
        start_utc="2026-07-14T09:00:00.000Z", end_utc="2026-07-14T09:30:00.000Z",
    )
    fixtures.create_appointment(
        clinic["id"], provider["id"], patient["id"],
        start_utc="2026-07-14T11:00:00.000Z", end_utc="2026-07-14T11:30:00.000Z",
    )
    resp = api.list_appointments(FRONT, params={"clinic_id": clinic["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_demographics_sync_idempotent_duplicate(api):
    """PRD §3.9: "When the `idempotency_key` has not been used on this session, the job commits: its `status` becomes `COMMITTED`, the patient's `legal_name` and `phone` are overwritten with the synced snapshot, and the patient's `demographics_revision` is incremented by one. When the `idempotency_key` has already been used on this session, the job is a duplicate: its `status` becomes `SKIPPED_DUPLICATE`, no patient mutation occurs, and the original job is returned instead of creating a new one."

    Design: Corner/cross_cutting_complexity_layers/demographics_sync_idempotent_duplicate
    """
    clinic = fixtures.create_clinic(name="CE21")
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])

    job1 = validate_success(api.create_demographics_sync_job(
        {"intake_session_id": session["id"], "idempotency_key": "K-1",
         "synced_legal_name": "Pat F2 Updated", "synced_phone": "555-2020"},
        FRONT,
    ), expected_status=201)
    assert job1["status"] == "COMMITTED"

    job2 = validate_success(api.create_demographics_sync_job(
        {"intake_session_id": session["id"], "idempotency_key": "K-1",
         "synced_legal_name": "Pat F2 Updated", "synced_phone": "555-2020"},
        FRONT,
    ), expected_status=201)
    assert job2["status"] == "SKIPPED_DUPLICATE"

    patient_after = validate_success(api.get_patient(patient["id"], FRONT))
    assert patient_after["demographics_revision"] == 2, "revision bumped only once"
    assert patient_after["legal_name"] == "Pat F2 Updated"


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header
    """
    bad_headers = build_user_headers("nobody", "NoSuchRole")
    resp = api.list_clinics(bad_headers)
    validate_error(resp, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


def test_reminder_in_quiet_hours_rejected(api):
    """PRD §3.12: "quiet hours: `scheduled_local_min` must not fall inside the clinic's wrap-around quiet window, which runs from `reminder_quiet_start_min` inclusive up to `reminder_quiet_end_min` exclusive and wraps past midnight. A scheduled local minute inside that window is rejected with `ERR_REMINDER_IN_QUIET_HOURS`."

    Design: Corner/validations/reminder_quiet_hours_rejected
    """
    clinic = fixtures.create_clinic(
        name="CE14", reminder_quiet_start_min=1320, reminder_quiet_end_min=420,
        reminder_min_gap_minutes=240, form_expiration_hours=72,
    )
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])

    # 1380 (23:00) is inside the wrap-around quiet window [1320, 420).
    resp = api.create_reminder(
        {"intake_session_id": session["id"], "target_kind": "GENERIC",
         "scheduled_utc": "2026-07-12T23:00:00.000Z", "scheduled_local_min": 1380},
        FRONT,
    )
    validate_error(resp, "ERR_REMINDER_IN_QUIET_HOURS")


def test_reminder_too_close_rejected(api):
    """PRD §3.12: "minimum gap: the `scheduled_utc` must be at least the clinic's `reminder_min_gap_minutes` away from every other non-cancelled reminder on the same session; a reminder too close to an existing one is rejected with `ERR_REMINDER_TOO_CLOSE`."

    Design: Corner/validations/reminder_min_gap_rejected
    """
    clinic = fixtures.create_clinic(
        name="CE15", reminder_min_gap_minutes=240, reminder_quiet_start_min=1320,
        reminder_quiet_end_min=420, form_expiration_hours=72,
    )
    provider = fixtures.create_provider(clinic["id"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])

    fixtures.create_reminder(session["id"], "GENERIC", "2026-07-13T12:00:00.000Z", 720)
    # Second reminder only 60 minutes later, gap < 240.
    resp = api.create_reminder(
        {"intake_session_id": session["id"], "target_kind": "COPAY",
         "scheduled_utc": "2026-07-13T13:00:00.000Z", "scheduled_local_min": 780},
        FRONT,
    )
    validate_error(resp, "ERR_REMINDER_TOO_CLOSE")
