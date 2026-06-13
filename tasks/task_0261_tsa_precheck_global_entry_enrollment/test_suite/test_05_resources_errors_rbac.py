"""Resource CRUD, defaults, computed fields, error handling, RBAC, endpoints,
optimistic concurrency, and immediate consistency.

Translates corner queue B instances for the entities, errors, rbac, endpoints,
cross_cutting_complexity_layers (OCC), and consistency_model sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    make_applicant_headers, make_appeals_officer_headers,
    make_vetting_officer_headers, TEST_USERS, ApiErrorId,
    pay_payload, background_check_payload, appointment_payload, biometric_payload,
    appeal_payload, decide_payload, withdraw_payload,
    setup_confirmed_appointment, setup_approved_application,
    setup_appeal_pending,
    get_application, app_version,
    create_program, create_applicant, create_center, create_slot,
    create_draft_application, set_clock,
)

ADMIN = TEST_USERS["scheduling_admin_headers"]
VETTING = TEST_USERS["vetting_officer_headers"]
ENROLLMENT = TEST_USERS["enrollment_officer_headers"]
APPEALS = TEST_USERS["appeals_officer_headers"]

GENERIC_UUID = "00000000-0000-4000-8000-000000000000"


# ---------------------------------------------------------------------------
# Queue B — entities section
# ---------------------------------------------------------------------------

def test_create_application_returns_201_draft(api):
    """PRD §3.2: "A new application is born in `DRAFT` with `fee_due_cents` and
    `fee_paid_cents` both at 0, `adverse_reason` null, and `appeal_count` at 0."
    PRD §2.4: "The `version` is an integer that begins at the initial creation
    value and increments by one on every mutation of the resource."

    Design: Corner/entities/create_application_returns_201_with_draft_status
    """
    program = create_program()
    applicant = create_applicant(full_name="Alice Create")
    headers = make_applicant_headers(applicant["id"])
    app = validate_success(
        api.create_application(
            {"applicant_id": applicant["id"], "program_code": "PRECHECK"}, headers
        ),
        expected_status=201,
    )
    assert app["status"] == "DRAFT"
    assert app["version"] == 1
    assert app["fee_due_cents"] == 0


def test_get_application_returns_stored_entity(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data field."

    Design: Corner/entities/get_application_returns_stored_entity
    """
    program = create_program()
    applicant = create_applicant(full_name="Bob Get")
    app = create_draft_application(applicant["id"])
    got = validate_success(api.get_application(app["id"], ADMIN), expected_status=200)
    assert got["id"] == app["id"]
    assert got["applicant_id"] == applicant["id"]


def test_list_applications_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_applications_paginated_envelope
    """
    program = create_program()
    applicant = create_applicant(full_name="Cara List")
    headers = make_applicant_headers(applicant["id"])
    create_draft_application(applicant["id"])
    create_draft_application(applicant["id"])
    resp = api.list_applications(ADMIN, params={"applicant_id": applicant["id"],
                                                "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_get_nonexistent_application_returns_not_found(api):
    """PRD §2.5: "the system validates each identifier in the path from left to
    right and rejects the request with `ERR_NOT_FOUND` at the first identifier that
    does not resolve to an existing resource."

    Design: Corner/entities/get_application_nonexistent_returns_not_found
    """
    resp = api.get_application(GENERIC_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_application_missing_program_code_rejected(api):
    """PRD §2.9: "request-body schema validation - required fields present,
    enumerated values in range, integers within their declared bounds - which fails
    with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_application_missing_required_field_returns_invalid_request
    """
    applicant = create_applicant(full_name="Dev Missing")
    headers = make_applicant_headers(applicant["id"])
    resp = api.create_application({"applicant_id": applicant["id"]}, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_applicant_disqualifying_flag_defaults_false(api):
    """PRD §3.2: "an optional `disqualifying_flag` that defaults to false and
    records whether the applicant has self-declared a permanently disqualifying
    conviction."

    Design: Corner/entities/applicant_disqualifying_flag_defaults_false
    """
    headers = TEST_USERS["applicant_headers"]
    applicant = validate_success(
        api.create_applicant(
            {"full_name": "Eli Default", "date_of_birth": "1990-01-05",
             "citizenship": "US_CITIZEN"},
            headers,
        ),
        expected_status=201,
    )
    assert applicant["disqualifying_flag"] is False


def test_biometric_status_computed_accepted(api):
    """PRD §3.5: "Its `status` is `ACCEPTED` when the `fingerprint_quality` is at
    most 3 and a compliant photo was captured; otherwise it is `REJECTED`."

    Design: Corner/entities/biometric_status_computed_from_quality_input_ignored
    """
    program, applicant, app, center, slot, appt = setup_confirmed_appointment()
    bio = validate_success(
        api.create_biometric_capture(
            biometric_payload(appt["id"], fingerprint_quality=2, photo_captured=True),
            ENROLLMENT,
        ),
        expected_status=201,
    )
    assert bio["status"] == "ACCEPTED"


def test_program_invalid_code_enum_rejected(api):
    """PRD §3.1: "A `Program` is created with a `code` - exactly one of `PRECHECK`
    or `GLOBAL_ENTRY`, and unique across all programs."

    Design: Corner/entities/program_code_invalid_enum_returns_invalid_request
    """
    resp = api.create_program(
        {"code": "NEXUS", "name": "Nexus", "base_fee_cents": 5000,
         "validity_years": 5, "vetting_risk_threshold": 40,
         "vetting_deny_threshold": 70, "redress_min_score": 30},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_fee_transaction_immutable_no_version(api):
    """PRD §2.4: "A `FeeTransaction` and an `AuditEvent` are immutable event-log
    records: each carries only an `id` and a `created_at`, and neither has an
    `updated_at` nor a `version`."

    Design: Corner/entities/fee_transaction_immutable_no_version_field
    """
    program = create_program(base_fee_cents=7800)
    applicant = create_applicant(full_name="Gil Fee")
    headers = make_applicant_headers(applicant["id"])
    app = create_draft_application(applicant["id"])
    tx = validate_success(
        api.pay_application(app["id"], pay_payload(7800), headers),
        expected_status=201,
    )
    assert tx["kind"] == "PAYMENT"
    assert tx["amount_cents"] == 7800
    assert "version" not in tx, "FeeTransaction must not expose a version field"


# ---------------------------------------------------------------------------
# Queue B — errors section
# ---------------------------------------------------------------------------

def test_referenced_applicant_not_found_on_application_create(api):
    """PRD §2.5: "The one specialization is application creation: an `Application`
    that names an `applicant_id` with no matching applicant is rejected with
    `ERR_APPLICANT_NOT_FOUND`."

    Design: Corner/errors/referenced_applicant_not_found_on_application_create
    """
    program = create_program()
    headers = make_applicant_headers("00000000-0000-4000-8000-000000000001")
    resp = api.create_application(
        {"applicant_id": "00000000-0000-4000-8000-000000000001",
         "program_code": "PRECHECK"},
        headers,
    )
    # PRD §2.5 uniquely specializes application creation to ERR_APPLICANT_NOT_FOUND.
    validate_error(resp, ApiErrorId.ERR_APPLICANT_NOT_FOUND.value)


def test_pagination_limit_out_of_range_rejected(api):
    """PRD §2.3: "A `limit` outside the inclusive range of 1 to 100, or a negative
    `offset`, is rejected with `ERR_VALIDATION_OUT_OF_RANGE`."

    Design: Corner/errors/pagination_limit_out_of_range_rejected
    """
    resp = api.list_applications(ADMIN, params={"limit": 500})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_OUT_OF_RANGE.value)


def test_clock_invalid_iso_rejected(api):
    """PRD §2.10: "that instant must be a valid ISO 8601 UTC datetime, and a
    malformed value is rejected with `ERR_CLOCK_INVALID`."

    Design: Corner/errors/clock_invalid_iso_rejected
    """
    resp = api.set_clock("not-a-date", ADMIN)
    validate_error(resp, ApiErrorId.ERR_CLOCK_INVALID.value)


# ---------------------------------------------------------------------------
# Queue B — rbac section
# ---------------------------------------------------------------------------

def test_applicant_cannot_adjudicate(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to invoke the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/applicant_cannot_adjudicate_background_check
    """
    program = create_program()
    applicant = create_applicant(full_name="Yan Role")
    headers = make_applicant_headers(applicant["id"])
    app = create_draft_application(applicant["id"])
    get_success_data(api.pay_application(app["id"], pay_payload(7800), headers))
    get_success_data(api.submit_application(app["id"], headers))
    get_success_data(
        api.create_background_check(app["id"], background_check_payload(criminal_hits=1), VETTING)
    )
    resp = api.adjudicate(app["id"], headers)  # Applicant calling a VettingOfficer op
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "If either header is absent or malformed, the request is rejected
    with `ERR_MISSING_AUTH_HEADERS`."

    Design: Corner/rbac/missing_auth_headers_rejected
    """
    resp = api.create_applicant(
        {"full_name": "Zoe NoAuth", "date_of_birth": "1990-01-25",
         "citizenship": "US_CITIZEN"},
        {"Content-Type": "application/json"},  # no X-User-ID / X-User-Role
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)


def test_segregation_of_duties_blocks_shared_officer(api):
    """PRD §3.7: "Segregation of duties is enforced: the deciding officer's
    `X-User-ID` must differ from the identifier of the `VettingOfficer` who
    adjudicated the application's background check, or the decision is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_of_duties_appeal_decider_blocked
    """
    program, applicant, app, bc, appeal = setup_appeal_pending(
        vetting_user_id="officer-shared"
    )
    # Same operator id decides the appeal -> blocked.
    decider = make_appeals_officer_headers("officer-shared")
    resp = api.decide_appeal(appeal["id"], decide_payload("UPHELD"), decider)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ---------------------------------------------------------------------------
# Queue B — endpoints section
# ---------------------------------------------------------------------------

def test_fee_transactions_reverse_reachability(api):
    """PRD §3.2: "each payment names an `amount_cents` of at least 1 and writes a
    `FeeTransaction` whose `kind` is `PAYMENT`, with the application's
    `fee_paid_cents` increased by that amount."

    Design: Corner/endpoints/fee_transactions_reverse_reachability_lists_payment
    """
    program = create_program(base_fee_cents=7800)
    applicant = create_applicant(full_name="Bea Ledger")
    headers = make_applicant_headers(applicant["id"])
    app = create_draft_application(applicant["id"])
    get_success_data(api.pay_application(app["id"], pay_payload(7800), headers))
    resp = api.list_fee_transactions(app["id"], ADMIN)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1


def test_ktn_revoke_action_succeeds(api):
    """PRD §3.6: "A `VettingOfficer` may revoke an `ACTIVE` credential, moving it to
    the terminal `REVOKED` state and writing an audit record."

    Design: Corner/endpoints/ktn_revoke_action_endpoint_succeeds
    """
    program, applicant, app, _center, _slot, _appt, ktn = setup_approved_application()
    revoked = validate_success(api.revoke_ktn(ktn["id"], VETTING), expected_status=200)
    assert revoked["status"] == "REVOKED"


# ---------------------------------------------------------------------------
# Queue B — cross_cutting: optimistic concurrency
# ---------------------------------------------------------------------------

def test_stale_version_on_booking_rejected(api):
    """PRD §2.6: "When the submitted value does not equal the application's current
    `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_appointment_booking
    """
    set_clock()
    program = create_program()
    center = create_center()
    slot = create_slot(center["id"])
    applicant = create_applicant(full_name="Dot Occ")
    headers = make_applicant_headers(applicant["id"])
    app = create_draft_application(applicant["id"])
    get_success_data(api.pay_application(app["id"], pay_payload(4000), headers))
    get_success_data(api.submit_application(app["id"], headers))
    get_success_data(api.pay_application(app["id"], pay_payload(3800), headers))
    get_success_data(
        api.create_background_check(app["id"], background_check_payload(criminal_hits=1), VETTING)
    )
    get_success_data(api.adjudicate(app["id"], VETTING))
    live = app_version(app["id"])
    # Book with a version one behind the live one.
    resp = api.create_appointment(
        appointment_payload(app["id"], slot["id"], live - 1), headers
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_withdraw_with_correct_version_succeeds(api):
    """PRD §2.6: "The second guarded operation is application withdrawal... it too
    is rejected when the submitted `expected_application_version` no longer matches
    the live `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_on_withdraw_succeeds
    """
    program = create_program()
    applicant = create_applicant(full_name="Eli OccOk")
    headers = make_applicant_headers(applicant["id"])
    app = create_draft_application(applicant["id"])
    version = app_version(app["id"])
    withdrawn = validate_success(
        api.withdraw_application(app["id"], withdraw_payload(version), headers),
        expected_status=200,
    )
    assert withdrawn["status"] == "WITHDRAWN"


# ---------------------------------------------------------------------------
# Queue B — consistency_model
# ---------------------------------------------------------------------------

def test_approve_issues_ktn_immediately_discoverable(api):
    """PRD §3.6: "On approval the system creates a `KnownTravelerNumber` in
    `ACTIVE`."

    Design: Corner/consistency_model/approve_issues_ktn_in_same_response_chain
    """
    program, applicant, app, _center, _slot, _appt, _ktn = setup_approved_application()
    resp = api.list_application_ktns(app["id"], ADMIN)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
