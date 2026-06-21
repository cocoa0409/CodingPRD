"""Service-job intake, listing, append-only authorization records, and access control.

Corner queue: entities (create defaults, missing field, invalid enum, not found,
listing envelope, key-authorization immutability), rbac (technician cannot intake,
missing auth context).
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    assert_key_authorization_record,
    create_service_job_payload,
    create_key_authorization_payload,
    create_job,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
TECHNICIAN = TEST_USERS["technician_headers"]


# ─── Corner: entities / create_service_job_returns_201_with_defaults ───────────
def test_create_service_job_returns_201_with_defaults(api):
    """PRD §3.1: "A freshly intaken job starts with job_status of INTAKE,
    payment_status of UNPAID, amount_due_cents of 0, and net_paid_cents of 0."
    PRD §3.1: "The is_emergency flag defaults to false when omitted and marks the call
    as an after-hours emergency call-out."

    Design: Corner/entities/create_service_job_returns_201_with_defaults
    """
    res = api.create_service_job(
        create_service_job_payload(
            customer_user_id="cust-new", service_type="LOCKOUT", requested_at_minute=600
        ),
        DISPATCHER,
    )
    job = validate_success(res, 201)
    assert job["job_status"] == "INTAKE"
    assert job["payment_status"] == "UNPAID"
    assert job["amount_due_cents"] == 0
    assert job["net_paid_cents"] == 0
    assert job["is_emergency"] is False


# ─── Corner: entities / create_service_job_missing_required_field ──────────────
def test_create_service_job_missing_service_type_rejected(api):
    """PRD §3.15: "a request whose body is missing a required field or carries a value
    of the wrong type is rejected with ERR_INVALID_REQUEST before domain rules are
    considered."

    Design: Corner/entities/create_service_job_missing_required_field_returns_invalid_request
    """
    payload = create_service_job_payload(customer_user_id="cust-mf", service_type="LOCKOUT")
    del payload["service_type"]
    res = api.create_service_job(payload, DISPATCHER)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


# ─── Corner: entities / create_service_job_invalid_enum_service_type ───────────
def test_create_service_job_invalid_enum_service_type_rejected(api):
    """PRD §3.1: "The service_type is one of LOCKOUT, REKEY, INSTALL, or SAFE; a value
    outside that set is rejected with ERR_INVALID_ENUM."

    Design: Corner/entities/create_service_job_invalid_enum_service_type
    """
    payload = create_service_job_payload(customer_user_id="cust-en", service_type="PICK")
    res = api.create_service_job(payload, DISPATCHER)
    validate_error(res, "ERR_INVALID_ENUM", expected_status=422)


# ─── Corner: entities / get_service_job_not_found ──────────────────────────────
def test_get_service_job_not_found(api):
    """PRD §2.5: "The parent job's existence is checked first; if the job id does not
    resolve, the request fails with ERR_JOB_NOT_FOUND before any child is consulted."

    Design: Corner/entities/get_service_job_not_found
    """
    res = api.get_service_job("00000000-0000-4000-8000-000000000000", DISPATCHER)
    validate_error(res, "ERR_JOB_NOT_FOUND", expected_status=404)


# ─── Corner: entities / list_service_jobs_paginated_envelope ───────────────────
def test_list_service_jobs_paginated_envelope(api):
    """PRD §2.3: "Every list response carries limit, offset, total_count, and has_more
    inside the meta object of the envelope."

    Design: Corner/entities/list_service_jobs_paginated_envelope
    """
    create_job(customer_user_id="cust-list", service_type="SAFE", requested_at_minute=600)
    data, meta = validate_paginated(api.list_service_jobs(DISPATCHER))
    assert isinstance(data, list)
    assert "total_count" in meta
    assert "has_more" in meta
    assert meta["total_count"] >= 1


# ─── Corner: entities / key_authorization_record_immutable_no_version ──────────
def test_key_authorization_record_is_append_only_no_version(api):
    """PRD §2.4: "The KeyAuthorizationRecord is the sole exception: it is an
    append-only compliance record that is never updated after creation. It carries only
    id and created_at; it has no updated_at field and no version field, and there is no
    endpoint that mutates it once filed."

    Design: Corner/entities/key_authorization_record_immutable_no_version
    """
    job = create_job(customer_user_id="cust-ka", service_type="REKEY", requested_at_minute=600)
    res = api.file_key_authorization(
        job["id"],
        create_key_authorization_payload(auth_kind="KEY_DUPLICATION"),
        TECHNICIAN,
    )
    record = validate_success(res, 201)
    assert record["auth_kind"] == "KEY_DUPLICATION"
    assert_key_authorization_record(record)


# ─── Corner: rbac / technician_cannot_intake_job ───────────────────────────────
def test_technician_cannot_intake_job(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE."
    PRD §2.1: "The operations desk role Dispatcher intakes jobs, dispatches technicians,
    manages bays and bay bookings, closes and cancels jobs, and adjudicates warranty
    claims."

    Design: Corner/rbac/technician_cannot_intake_job
    """
    res = api.create_service_job(
        create_service_job_payload(
            customer_user_id="cust-rb", service_type="LOCKOUT", requested_at_minute=600
        ),
        TECHNICIAN,
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


# ─── Corner: rbac / missing_auth_context_rejected ──────────────────────────────
def test_missing_auth_context_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed one, is
    rejected with ERR_MISSING_AUTH_CONTEXT."

    Design: Corner/rbac/missing_auth_context_rejected
    """
    res = api.list_service_jobs({})
    validate_error(res, "ERR_MISSING_AUTH_CONTEXT", expected_status=401)
