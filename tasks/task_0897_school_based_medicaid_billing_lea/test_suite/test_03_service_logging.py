"""Service-log lifecycle: verification units/charge, the document/return cycle,
the billing-consent gate, half-open double-booking, and the create-time guards.
"""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    make_service_provider_headers,
    setup_billing_context, create_logged_log, create_documented_log,
    document_log, create_consent,
    api_client,
)

MC = TEST_USERS["medicaid_coordinator_headers"]
BC = TEST_USERS["billing_coordinator_headers"]


# --- dual_variant_calc / authorized_vs_delivered_billable_units --------------
def test_verify_computes_delivered_units_and_charge(api):
    """PRD §3.4: "delivered_units is delivered_minutes divided by the
    authorization's unit_minutes, rounded half-up to the nearest whole number,
    and charge_cents is delivered_units multiplied by the authorization's
    unit_rate_cents."

    Design: Difficulty/dual_variant_calc/authorized_vs_delivered_billable_units
    """
    ctx = setup_billing_context()
    log = create_documented_log(ctx["authorization"]["id"], ctx["provider"]["id"],
                                ctx["student"]["id"], delivered_minutes=40)
    verified = validate_success(api.verify_service_log(log["id"], BC))
    assert verified["delivered_units"] == 3
    assert verified["charge_cents"] == 9000


def test_provisional_units_differ_from_delivered_units(api):
    """PRD §3.3: "The provisional figure is authorized_minutes_per_session divided
    by unit_minutes, rounded half-up to the nearest whole number. This provisional
    variant uses the authorized minutes rather than the minutes actually
    delivered, is derivable at any time from the authorization alone, and is never
    persisted; only the delivered figure computed at verification (Section 3.4) is
    stored on a service log."

    Design: Difficulty/dual_variant_calc/authorized_vs_delivered_billable_units
    """
    ctx = setup_billing_context(auth_overrides={"authorized_minutes_per_session": 30, "unit_minutes": 15})
    auth = ctx["authorization"]
    log = create_documented_log(auth["id"], ctx["provider"]["id"], ctx["student"]["id"],
                                delivered_minutes=40)
    verified = validate_success(api.verify_service_log(log["id"], BC))
    # Provisional (authorized) variant derives from the authorization alone.
    provisional = round(auth["authorized_minutes_per_session"] / auth["unit_minutes"])
    assert provisional == 2
    assert verified["delivered_units"] == 3
    assert provisional != verified["delivered_units"]


# --- non_linear_state_machine / service_log_document_return_cycle ------------
def test_return_documented_log_clears_note_and_records_reason(api):
    """PRD §3.4: "the coordinator may instead return the documented log for
    correction, which moves it from DOCUMENTED back to LOGGED, records the
    return_reason, and clears the documentation_note to null so the provider must
    re-document."

    Design: Difficulty/non_linear_state_machine/service_log_document_return_cycle
    """
    ctx = setup_billing_context()
    log = create_documented_log(ctx["authorization"]["id"], ctx["provider"]["id"],
                                ctx["student"]["id"], note="first draft")
    returned = validate_success(api.return_service_log(log["id"], {"return_reason": "missing goals"}, BC))
    assert returned["status"] == "LOGGED"
    assert returned["documentation_note"] is None
    assert returned["return_reason"] == "missing goals"


def test_redocument_after_return_moves_back_to_documented(api):
    """PRD §3.4: "The same provider then documents the log, attaching the
    documentation_note; this moves the log from LOGGED to DOCUMENTED".

    Design: Difficulty/non_linear_state_machine/service_log_document_return_cycle
    """
    ctx = setup_billing_context()
    log = create_documented_log(ctx["authorization"]["id"], ctx["provider"]["id"],
                                ctx["student"]["id"], note="first draft")
    get_success_data(api.return_service_log(log["id"], {"return_reason": "missing goals"}, BC))
    redoc = validate_success(api.document_service_log(
        log["id"], {"documentation_note": "corrected"},
        make_service_provider_headers(ctx["provider"]["id"])))
    assert redoc["status"] == "DOCUMENTED"
    assert redoc["documentation_note"] == "corrected"


# --- cross_entity_state_dependency / service_log_requires_granted_consent ----
def test_service_log_rejected_when_billing_consent_revoked(api):
    """PRD §3.4: "the student must have a BILLING consent in status GRANTED, else
    ERR_CONSENT_NOT_GRANTED (HTTP 422)".

    Design: Difficulty/cross_entity_state_dependency/service_log_requires_granted_consent
    """
    ctx = setup_billing_context(grant_consent=True)
    consent = ctx["consent"]
    revoked = get_success_data(api.revoke_consent(consent["id"], MC))
    assert revoked["status"] == "REVOKED"

    resp = api.create_service_log({
        "iep_authorization_id": ctx["authorization"]["id"], "provider_id": ctx["provider"]["id"],
        "student_id": ctx["student"]["id"], "service_date": "2026-03-01",
        "start_time": "2026-03-01T09:00:00Z", "end_time": "2026-03-01T09:40:00Z",
        "delivered_minutes": 40}, make_service_provider_headers(ctx["provider"]["id"]))
    validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_GRANTED)


def test_service_log_succeeds_after_reconsent(api):
    """PRD §3.1: "A revoked consent can be re-granted, which returns it to GRANTED,
    re-stamps granted_date, and clears revoked_date back to null — the consent
    record cycles through re-consent rather than being recreated."

    Design: Difficulty/cross_entity_state_dependency/service_log_requires_granted_consent
    """
    ctx = setup_billing_context(grant_consent=True)
    consent = ctx["consent"]
    get_success_data(api.revoke_consent(consent["id"], MC))
    regranted = get_success_data(api.grant_consent(consent["id"], MC))
    assert regranted["status"] == "GRANTED"

    created = validate_success(api.create_service_log({
        "iep_authorization_id": ctx["authorization"]["id"], "provider_id": ctx["provider"]["id"],
        "student_id": ctx["student"]["id"], "service_date": "2026-03-01",
        "start_time": "2026-03-01T09:00:00Z", "end_time": "2026-03-01T09:40:00Z",
        "delivered_minutes": 40}, make_service_provider_headers(ctx["provider"]["id"])), expected_status=201)
    assert created["status"] == "LOGGED"


# --- resource_temporal_overlap / provider_service_log_halfopen_overlap -------
def test_overlapping_service_log_rejected(api):
    """PRD §3.4: "Overlap is judged on the half-open [start_time, end_time)
    interval, so two sessions that merely abut — one ending exactly when the next
    begins — do not conflict, whereas any shared interior instant does; a conflict
    yields ERR_PROVIDER_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/provider_service_log_halfopen_overlap
    """
    ctx = setup_billing_context()
    create_logged_log(ctx["authorization"]["id"], ctx["provider"]["id"], ctx["student"]["id"],
                      start_time="2026-03-01T09:00:00Z", end_time="2026-03-01T09:40:00Z",
                      delivered_minutes=40)
    resp = api.create_service_log({
        "iep_authorization_id": ctx["authorization"]["id"], "provider_id": ctx["provider"]["id"],
        "student_id": ctx["student"]["id"], "service_date": "2026-03-01",
        "start_time": "2026-03-01T09:20:00Z", "end_time": "2026-03-01T09:50:00Z",
        "delivered_minutes": 30}, make_service_provider_headers(ctx["provider"]["id"]))
    validate_error(resp, ApiErrorId.ERR_PROVIDER_DOUBLE_BOOKED)


def test_adjacent_service_log_allowed(api):
    """PRD §3.4: "two sessions that merely abut — one ending exactly when the next
    begins — do not conflict, whereas any shared interior instant does".

    Design: Difficulty/resource_temporal_overlap/provider_service_log_halfopen_overlap
    """
    ctx = setup_billing_context()
    create_logged_log(ctx["authorization"]["id"], ctx["provider"]["id"], ctx["student"]["id"],
                      start_time="2026-03-01T09:00:00Z", end_time="2026-03-01T09:40:00Z",
                      delivered_minutes=40)
    created = validate_success(api.create_service_log({
        "iep_authorization_id": ctx["authorization"]["id"], "provider_id": ctx["provider"]["id"],
        "student_id": ctx["student"]["id"], "service_date": "2026-03-01",
        "start_time": "2026-03-01T09:40:00Z", "end_time": "2026-03-01T10:10:00Z",
        "delivered_minutes": 30}, make_service_provider_headers(ctx["provider"]["id"])), expected_status=201)
    assert created["status"] == "LOGGED"


# --- validations corners -----------------------------------------------------
def test_verify_zero_billable_units_returns_error(api):
    """PRD §3.4: "Verification is refused with ERR_ZERO_BILLABLE_UNITS (HTTP 422)
    when the computed delivered_units would be 0 — that is, the delivered minutes
    must round to at least one unit."

    Design: Corner/validations/verify_zero_billable_units_returns_error
    """
    ctx = setup_billing_context()
    log = create_documented_log(
        ctx["authorization"]["id"], ctx["provider"]["id"], ctx["student"]["id"],
        start_time="2026-03-01T09:00:00Z", end_time="2026-03-01T09:03:00Z", delivered_minutes=3)
    resp = api.verify_service_log(log["id"], BC)
    validate_error(resp, ApiErrorId.ERR_ZERO_BILLABLE_UNITS)
    assert get_success_data(api.get_service_log(log["id"], MC))["status"] == "DOCUMENTED"


def test_service_log_outside_auth_window_returns_error(api):
    """PRD §3.4: "the service_date must fall within the authorization's closed
    [effective_date, expiration_date] window, else ERR_SERVICE_OUTSIDE_AUTH_WINDOW
    (HTTP 422)".

    Design: Corner/validations/service_log_outside_auth_window_returns_error
    """
    # Auth window is valid at the 2026-03-15 clock (not strictly past its
    # expiration, so it is not lazily expired and stays ACTIVE), but the
    # service_date falls before the window's effective_date. The service_date
    # remains inside the default credential window [2026-01-01, 2026-12-31] so
    # the credential guard (precedence 9) passes and the service-window guard
    # (precedence 12) is the one that fires.
    ctx = setup_billing_context(auth_overrides={"effective_date": "2026-04-01", "expiration_date": "2026-06-30"})
    resp = api.create_service_log({
        "iep_authorization_id": ctx["authorization"]["id"], "provider_id": ctx["provider"]["id"],
        "student_id": ctx["student"]["id"], "service_date": "2026-03-01",
        "start_time": "2026-03-01T09:00:00Z", "end_time": "2026-03-01T09:40:00Z",
        "delivered_minutes": 40}, make_service_provider_headers(ctx["provider"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SERVICE_OUTSIDE_AUTH_WINDOW)


def test_service_log_authorization_not_active_returns_error(api):
    """PRD §3.4: "the authorization must be in status ACTIVE, else
    ERR_AUTHORIZATION_NOT_ACTIVE (HTTP 422)".

    Design: Corner/validations/service_log_authorization_not_active_returns_error
    """
    ctx = setup_billing_context(auth_overrides={"activate": False})
    resp = api.create_service_log({
        "iep_authorization_id": ctx["authorization"]["id"], "provider_id": ctx["provider"]["id"],
        "student_id": ctx["student"]["id"], "service_date": "2026-01-15",
        "start_time": "2026-01-15T09:00:00Z", "end_time": "2026-01-15T09:40:00Z",
        "delivered_minutes": 40}, make_service_provider_headers(ctx["provider"]["id"]))
    validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_NOT_ACTIVE)
