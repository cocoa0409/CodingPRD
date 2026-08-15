"""Clinic onboarding, provider roster, and SLA policy configuration rules."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_clinic, add_sla_policy, setup_provider, setup_editor,
    create_clinic_account_payload, create_sla_policy_payload,
    create_provider_payload, create_dictation_job_payload,
    make_provider_headers, TEST_USERS,
    assert_clinic_account,
)

VENDOR = TEST_USERS["vendor_admin_headers"]
CLIENT = TEST_USERS["client_admin_headers"]


def test_clinic_create_applies_config_defaults(api):
    """PRD §3.1: "The `unsigned_report_threshold` — how many aged unsigned
    transcripts a single provider may accumulate before suspension — defaults
    to 3 and must be at least 1. The two aging boundaries, `aging_tier1_hours`
    and `aging_tier2_hours`, default to 24 and 72 hours respectively; the first
    must be at least 1 and strictly less than the second. The
    `payment_grace_days` knob, the number of days a finalized invoice may sit
    unpaid before the clinic is cut off from new dictation uploads, defaults to
    14. A freshly created clinic has `billing_hold` false and a
    `suspended_provider_count` of zero."

    Design: Corner/entities/clinic_create_applies_config_defaults
    """
    resp = api.create_clinic_account(create_clinic_account_payload(name="C"), VENDOR)
    clinic = validate_success(resp, 201)
    assert_clinic_account(clinic)
    assert clinic["unsigned_report_threshold"] == 3
    assert clinic["aging_tier1_hours"] == 24
    assert clinic["aging_tier2_hours"] == 72
    assert clinic["payment_grace_days"] == 14
    assert clinic["billing_hold"] is False
    assert clinic["suspended_provider_count"] == 0


def test_provider_create_missing_clinic_returns_invalid_request(api):
    """PRD §2.6: "Immediately after role authorization — and before any
    existence lookup — the request body schema is validated: required fields
    must be present, types must match, enum members must be valid, and numeric
    ranges must be respected (for example, `audio_duration_seconds` must be
    greater than zero, error counts must be non-negative, `tat_minutes` must be
    greater than zero, `breach_credit_pct` must lie within zero to one hundred
    inclusive, a dispute-resolution `outcome` must be `UPHELD` or `REVERSED`,
    and interval bounds must be parseable). Any schema failure yields
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/provider_create_missing_required_clinic_returns_invalid_request
    """
    resp = api.create_provider(
        {"full_name": "P", "specialty": "GENERAL"}, CLIENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_provider_get_nonexistent_returns_404(api):
    """PRD §2.6: "Each missing resource raises its own not-found error —
    `ERR_CLINIC_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_EDITOR_NOT_FOUND`,
    `ERR_JOB_NOT_FOUND`, `ERR_TRANSCRIPT_NOT_FOUND`, `ERR_TEMPLATE_NOT_FOUND`,
    `ERR_MACRO_NOT_FOUND`, or `ERR_BILLING_PERIOD_NOT_FOUND`."

    Design: Corner/entities/provider_get_nonexistent_returns_404
    """
    resp = api.get_provider("00000000-0000-4000-8000-000000000000", VENDOR)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_FOUND)


def test_job_create_invalid_priority_enum_returns_invalid_request(api):
    """PRD §2.6: "Immediately after role authorization — and before any
    existence lookup — the request body schema is validated: required fields
    must be present, types must match, enum members must be valid, and numeric
    ranges must be respected (for example, `audio_duration_seconds` must be
    greater than zero, error counts must be non-negative, `tat_minutes` must be
    greater than zero, `breach_credit_pct` must lie within zero to one hundred
    inclusive, a dispute-resolution `outcome` must be `UPHELD` or `REVERSED`,
    and interval bounds must be parseable). Any schema failure yields
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/job_create_invalid_priority_enum_returns_invalid_request
    """
    clinic = setup_clinic()
    add_sla_policy(clinic["id"])
    provider = setup_provider(clinic["id"])
    headers = make_provider_headers(provider["id"])

    bad_enum = api.create_dictation_job(
        create_dictation_job_payload(provider["id"], priority="MEGA"), headers)
    validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST)

    bad_duration = api.create_dictation_job(
        create_dictation_job_payload(provider["id"], audio_duration_seconds=0),
        headers)
    validate_error(bad_duration, ApiErrorId.ERR_INVALID_REQUEST)


def test_job_create_system_field_input_ignored(api):
    """PRD §3.3: "A job that passes the guards is created with its
    `clinic_account_id` copied from the provider's record, `workflow_status`
    `QUEUED`, and `escalation_level` `NONE`."

    Design: Corner/entities/job_create_system_field_input_ignored
    """
    clinic = setup_clinic()
    add_sla_policy(clinic["id"], priority="STAT", tat_minutes=120,
                   rate_per_line_cents=20, breach_credit_pct=25)
    provider = setup_provider(clinic["id"])
    payload = create_dictation_job_payload(
        provider["id"], priority="STAT", audio_duration_seconds=90)
    payload["workflow_status"] = "DELIVERED"
    payload["escalation_level"] = "CRITICAL"
    resp = api.create_dictation_job(payload, make_provider_headers(provider["id"]))
    job = validate_success(resp, 201)
    assert job["workflow_status"] == "QUEUED", (
        f"system-managed workflow_status must be QUEUED, got {job['workflow_status']}")
    assert job["escalation_level"] == "NONE", (
        f"system-managed escalation_level must be NONE, got {job['escalation_level']}")


def test_duplicate_sla_policy_returns_conflict(api):
    """PRD §3.1: "At most one policy may exist for a given clinic-and-priority
    pair; a duplicate create is rejected with `ERR_DUPLICATE_SLA_POLICY`."

    Design: Corner/validations/duplicate_sla_policy_returns_conflict
    """
    c1 = setup_clinic(name="C1")
    c2 = setup_clinic(name="C2")
    add_sla_policy(c1["id"], priority="STAT", tat_minutes=120,
                   rate_per_line_cents=20, breach_credit_pct=25)

    dup = api.create_sla_policy(
        create_sla_policy_payload(
            c1["id"], priority="STAT", tat_minutes=60,
            rate_per_line_cents=30, breach_credit_pct=50,
            measurement_basis="PRODUCTION_WINDOW"),
        VENDOR)
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_SLA_POLICY)

    other_clinic = api.create_sla_policy(
        create_sla_policy_payload(
            c2["id"], priority="STAT", tat_minutes=60,
            rate_per_line_cents=30, breach_credit_pct=50,
            measurement_basis="PRODUCTION_WINDOW"),
        VENDOR)
    created = validate_success(other_clinic, 201)
    assert created["clinic_account_id"] == c2["id"]


def test_upload_without_sla_policy_returns_referential_error(api):
    """PRD §3.3: "An SLA policy must exist for the job's clinic-and-priority
    combination, or the upload fails with `ERR_SLA_POLICY_MISSING`."

    Design: Corner/validations/upload_without_sla_policy_returns_referential_error
    """
    clinic = setup_clinic()
    add_sla_policy(clinic["id"], priority="STAT", tat_minutes=120,
                   rate_per_line_cents=20, breach_credit_pct=25)
    provider = setup_provider(clinic["id"])
    resp = api.create_dictation_job(
        create_dictation_job_payload(provider["id"], priority="ROUTINE"),
        make_provider_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_SLA_POLICY_MISSING)
