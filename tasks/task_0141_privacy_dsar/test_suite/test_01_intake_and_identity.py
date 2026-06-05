"""Intake, request creation, initial state, RBAC, and the identity-verification loop."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_dsar_request, assert_instant_equals,
    create_dsar_request_payload, create_data_subject_payload,
    TEST_USERS,
    make_intake_agent_headers,
    setup_registry, create_pending_request, create_request,
    create_request_in_discovery,
)

_PO = TEST_USERS["privacy_officer_headers"]
_IA = TEST_USERS["intake_agent_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


def test_create_dsar_request_returns_201_with_all_fields(api):
    """PRD §3.2: "On creation the request enters PENDING_VERIFICATION, its
    deadline_at is computed (Section 3.3), and the owning controller's
    open_request_count rises by one. The request also tracks identity_attempts
    (starting at 0), extension_count (starting at 0), and version (starting at 1)."
    PRD §3.3: "30 calendar days under GDPR".

    Design: Corner/entities/create_dsar_request_returns_201_with_all_fields
    """
    controller, subject, _ = setup_registry("GDPR", with_processor=False)
    payload = create_dsar_request_payload(
        controller["id"], subject["id"], request_type="ACCESS",
        received_at="2026-01-05T09:00:00Z",
    )
    resp = api.create_dsar_request(payload, _IA)
    data = validate_success(resp, 201)
    assert_dsar_request(data)
    assert data["status"] == "PENDING_VERIFICATION"
    assert data["version"] == 1
    assert_instant_equals(data["deadline_at"], "2026-02-04T09:00:00Z", "deadline_at")


def test_new_dsar_request_starts_in_pending_verification(api):
    """PRD §3.2: "On creation the request enters PENDING_VERIFICATION ... The
    request also tracks identity_attempts (starting at 0), extension_count
    (starting at 0), and version (starting at 1)."

    Design: Corner/state_machines/new_dsar_request_starts_in_pending_verification
    """
    controller, subject, _ = setup_registry("GDPR", with_processor=False)
    payload = create_dsar_request_payload(
        controller["id"], subject["id"], request_type="DELETION",
        received_at="2026-01-05T09:00:00Z",
    )
    data = validate_success(api.create_dsar_request(payload, _IA), 201)
    assert data["status"] == "PENDING_VERIFICATION"
    assert data["identity_attempts"] == 0


def test_get_dsar_request_not_found_uuid(api):
    """PRD §2.5: "If any referenced resource in the path or request body does not
    exist, the request fails with ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_dsar_request_not_found_uuid
    """
    resp = api.get_dsar_request(NON_EXISTENT, _PO)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_dsar_request_missing_request_type_returns_invalid_request(api):
    """PRD §2.9: "On any endpoint that accepts a body, the server validates that
    required fields are present and well-typed ... A violation of any of these is
    reported as ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_dsar_request_missing_required_field_returns_invalid_request
    """
    controller, subject, _ = setup_registry("GDPR", with_processor=False)
    payload = {
        "controller_id": controller["id"],
        "data_subject_id": subject["id"],
        "received_at": "2026-01-05T09:00:00Z",
    }
    resp = api.create_dsar_request(payload, _IA)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_create_dsar_request_invalid_enum_returns_invalid_request(api):
    """PRD §2.9: "any enum-valued field carries a member of its declared set ... A
    violation of any of these is reported as ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_dsar_request_invalid_enum_returns_invalid_request
    """
    controller, subject, _ = setup_registry("GDPR", with_processor=False)
    payload = create_dsar_request_payload(
        controller["id"], subject["id"], request_type="RECTIFICATION",
        received_at="2026-01-05T09:00:00Z",
    )
    resp = api.create_dsar_request(payload, _IA)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_dsar_request_list_filtered_by_controller_paginated(api):
    """PRD §2.3: "For any list response, the meta object reports the limit and
    offset in effect together with total_count (the total number of records
    matching the query irrespective of pagination) and has_more."

    Design: Corner/entities/dsar_request_list_filtered_by_controller_paginated
    """
    controller, subject, _ = setup_registry("GDPR", with_processor=False)
    req = create_request(controller["id"], subject["id"], "ACCESS")
    resp = api.list_dsar_requests(_PO, params={"controller_id": controller["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert all(r["controller_id"] == controller["id"] for r in data)
    assert any(r["id"] == req["id"] for r in data)


# --------------------------------------------------------------------------
# RBAC
# --------------------------------------------------------------------------
def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two headers identifying the
    caller: X-User-ID ... and X-User-Role ... If either header is absent, the
    request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    controller, _, _ = setup_registry("GDPR", with_processor=False)
    payload = create_data_subject_payload(controller["id"], email="noauth@x.example",
                                          full_name="NoAuth", jurisdiction_residency="EU")
    # No auth headers at all.
    resp = api.create_data_subject(payload, {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_intake_agent_cannot_dispatch_fulfillment_returns_unauthorized(api):
    """PRD §2.1: "If both headers are present but the named role is not permitted
    to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."
    PRD §4: dispatch-fulfillment is authorized for PrivacyOfficer only.

    Design: Corner/rbac/intake_agent_cannot_dispatch_fulfillment_returns_unauthorized
    """
    ctx = create_request_in_discovery(intake_user_id="intake-rbac1")
    proc_id = ctx["processor"]["id"]
    finding = validate_success(
        api.create_finding(ctx["request"]["id"],
                           {"processor_id": proc_id, "data_category": "IDENTITY",
                            "record_count": 1, "confidence": "EXACT"}, _PO), 201)
    validate_success(api.confirm_finding(finding["id"], _PO), 200)
    review = validate_success(api.complete_discovery(ctx["request"]["id"], _PO), 200)
    headers = make_intake_agent_headers("intake-rbac1")
    resp = api.dispatch_fulfillment(
        ctx["request"]["id"], {"expected_request_version": review["version"]}, headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_processor_agent_cannot_confirm_finding_returns_unauthorized(api):
    """PRD §2.1: "If both headers are present but the named role is not permitted
    to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."
    PRD §4: findings/{id}/confirm is authorized for PrivacyOfficer only.

    Design: Corner/rbac/processor_agent_cannot_confirm_finding_returns_unauthorized
    """
    ctx = create_request_in_discovery(intake_user_id="intake-rbac2")
    proc_id = ctx["processor"]["id"]
    finding = validate_success(
        api.create_finding(ctx["request"]["id"],
                           {"processor_id": proc_id, "data_category": "IDENTITY",
                            "record_count": 1, "confidence": "EXACT"}, _PO), 201)
    pa_headers = TEST_USERS["processor_agent_headers"]
    resp = api.confirm_finding(finding["id"], pa_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


# --------------------------------------------------------------------------
# Identity-verification loop (non-linear state machine)
# --------------------------------------------------------------------------
def test_identity_verification_revision_cycle_attempts_two(api):
    """PRD §3.2: "Rejecting requires only that the request be in
    PENDING_VERIFICATION; it advances PENDING_VERIFICATION → VERIFICATION_REJECTED,
    increments identity_attempts by one, appends an IDENTITY_REJECTED audit entry,
    and bumps version."
    PRD §3.2: "A successful resubmission returns the request VERIFICATION_REJECTED →
    PENDING_VERIFICATION and bumps version, re-opening the loop."

    Design: Difficulty/non_linear_state_machine/dsar_identity_verification_revision_cycle
    """
    ctx = create_pending_request("GDPR", "ACCESS", with_processor=False)
    req_id = ctx["request"]["id"]
    ia = make_intake_agent_headers("intake-cycle")
    validate_success(api.reject_identity(req_id, {"reason": "blurry id"}, ia), 200)
    validate_success(api.resubmit_identity(req_id, ia), 200)
    data = validate_success(api.reject_identity(req_id, {"reason": "still blurry"}, ia), 200)
    assert data["status"] == "VERIFICATION_REJECTED"
    assert data["identity_attempts"] == 2


def test_identity_revision_cycle_returns_to_pending_then_verifies(api):
    """PRD §3.2: "A successful resubmission returns the request VERIFICATION_REJECTED →
    PENDING_VERIFICATION and bumps version, re-opening the loop."
    PRD §3.2: "it advances the request PENDING_VERIFICATION → DISCOVERY, increments
    identity_attempts by one, pins the acting agent's identity into
    verified_by_user_id."

    Design: Difficulty/non_linear_state_machine/dsar_identity_verification_revision_cycle
    """
    ctx = create_pending_request("GDPR", "ACCESS", with_processor=False)
    req_id = ctx["request"]["id"]
    ia = make_intake_agent_headers("intake-cycle2")
    validate_success(api.reject_identity(req_id, {"reason": "r1"}, ia), 200)
    resub = validate_success(api.resubmit_identity(req_id, ia), 200)
    assert resub["status"] == "PENDING_VERIFICATION"
    verified = validate_success(
        api.verify_identity(req_id, {"evidence_reference": "ev"}, ia), 200)
    assert verified["status"] == "DISCOVERY"
    assert verified["identity_attempts"] == 2


def test_resubmit_after_three_attempts_returns_attempts_exhausted(api):
    """PRD §3.2: "an IntakeAgent resubmits, which requires the request to be in
    VERIFICATION_REJECTED and that identity_attempts be fewer than 3. If three
    attempts have already been recorded, resubmission is refused with
    ERR_VERIFICATION_ATTEMPTS_EXHAUSTED and the request can only be closed."

    Design: Corner/validations/resubmit_identity_after_three_attempts_returns_attempts_exhausted
    """
    ctx = create_pending_request("GDPR", "ACCESS", with_processor=False)
    req_id = ctx["request"]["id"]
    ia = make_intake_agent_headers("intake-exh")
    validate_success(api.reject_identity(req_id, {"reason": "r1"}, ia), 200)
    validate_success(api.resubmit_identity(req_id, ia), 200)
    validate_success(api.reject_identity(req_id, {"reason": "r2"}, ia), 200)
    validate_success(api.resubmit_identity(req_id, ia), 200)
    third = validate_success(api.reject_identity(req_id, {"reason": "r3"}, ia), 200)
    assert third["identity_attempts"] == 3
    resp = api.resubmit_identity(req_id, ia)
    validate_error(resp, ApiErrorId.ERR_VERIFICATION_ATTEMPTS_EXHAUSTED.value, 409)
    after = validate_success(api.get_dsar_request(req_id, _PO), 200)
    assert after["identity_attempts"] == 3
