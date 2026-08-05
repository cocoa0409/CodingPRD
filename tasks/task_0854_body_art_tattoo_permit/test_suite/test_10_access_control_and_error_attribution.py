"""Header authentication, role authorization, ownership and error attribution."""

from test_helpers import (
    ApiErrorId,
    NO_AUTH_HEADERS,
    TEST_USERS,
    cite_violation,
    create_active_artist,
    create_permitted_establishment,
    create_plan_review_payload,
    create_procedure_log_payload,
    create_verified_minor_consent,
    file_complaint,
    file_infection_report,
    file_procedure_log,
    make_artist_headers,
    make_operator_headers,
    pass_preopening_inspection,
    create_establishment_pending_inspection,
    read_establishment,
    register_establishment,
    set_clock,
    start_inspection_at,
    validate_error,
    validate_paginated,
    validate_success,
)

HO = TEST_USERS["health_officer_headers"]
INSP = TEST_USERS["inspector_headers"]
CLERK = TEST_USERS["records_clerk_headers"]
PUBLIC = TEST_USERS["public_user_headers"]

UNKNOWN_UUID = "aaaaaaaa-1111-4111-8111-111111111111"


def test_request_without_auth_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request must present both an `X-User-ID` header and an
    `X-User-Role` header. If either header is absent, or if `X-User-Role` carries a
    string that is not one of the seven declared roles, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "Authentication is always evaluated before authorization, and both are
    evaluated before anything else in the request is examined."

    Design: Corner/rbac/read_establishment_with_missing_auth_headers_returns_unauthenticated
    """
    establishment = register_establishment(
        name="Header Ink", street_address="47 Fortyseventh St"
    )

    response = api.get_establishment(establishment["id"], NO_AUTH_HEADERS)
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert response.status_code == 401, (
        "Authentication precedes existence and authorization checks"
    )


def test_inspector_may_not_issue_the_permit(api):
    """PRD §2.1: "If the headers are well formed but the named role does not appear on
    the role list of the route being called, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.2: "Issuance is a `HealthOfficer` act."

    Design: Corner/rbac/inspector_cannot_activate_establishment
    """
    establishment = create_establishment_pending_inspection(
        name="Role Gate Ink", street_address="48 Fortyeighth St"
    )
    pass_preopening_inspection(establishment["id"])

    response = api.activate_establishment(establishment["id"], INSP)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert response.status_code == 403

    stored = read_establishment(establishment["id"])
    assert stored["permit_status"] == "PENDING_INSPECTION"
    assert stored["permit_issued_on"] is None


def test_public_user_can_complain_but_cannot_read_departmental_records(api):
    """PRD §2.1: "A `PublicUser` is a member of the public with no read access
    whatsoever to departmental records — their only capabilities are filing a complaint
    and filing a reportable infection report."
    PRD §2.1: "If the headers are well formed but the named role does not appear on the
    role list of the route being called, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/public_user_cannot_read_departmental_records
    """
    establishment = register_establishment(
        name="Public Gate Ink", street_address="49 Fortyninth St"
    )

    denied = api.list_establishments(PUBLIC)
    validate_error(denied, ApiErrorId.ERR_UNAUTHORIZED.value)
    assert denied.status_code == 403

    complaint = validate_success(
        api.create_complaint(
            {
                "establishment_id": establishment["id"],
                "complainant_contact": "pub@example.com",
                "category": "SANITATION",
                "narrative": "Concerned about cleanliness.",
            },
            PUBLIC,
        ),
        201,
    )
    assert complaint["status"] == "RECEIVED"


def test_operator_cannot_file_plans_for_another_premises(api):
    """PRD §2.1: "When `X-User-Role` is `EstablishmentOperator`, `X-User-ID` is the `id`
    of the acting establishment; ownership checks on any resource that references an
    establishment compare the resource's establishment reference to `X-User-ID`."
    PRD §2.1: "Whenever an entity-backed caller acts on a resource that is not theirs,
    the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership
    rule applies to every write route whose role list includes `EstablishmentOperator`
    or `Artist`."

    Design: Corner/rbac/operator_cannot_file_plan_review_for_another_establishment
    """
    est_a = register_establishment(name="Owner A", street_address="50 Fiftieth St")
    est_b = register_establishment(name="Owner B", street_address="51 Fiftyfirst St")

    response = api.create_plan_review(
        create_plan_review_payload(est_a["id"], floor_plan_reference="FP-XX"),
        make_operator_headers(est_b["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert response.status_code == 403

    _, meta = validate_paginated(
        api.list_plan_reviews(HO, params={"establishment_id": est_a["id"]})
    )
    assert meta["total_count"] == 0


def test_artist_cannot_log_a_session_under_another_practitioner(api):
    """PRD §2.1: "When `X-User-Role` is `Artist`, `X-User-ID` is the `id` of the acting
    artist; ownership checks compare either the target artist's own `id` or the
    `artist_id` carried in the request body to `X-User-ID`."
    PRD §2.1: "Whenever an entity-backed caller acts on a resource that is not theirs,
    the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership
    rule applies to every write route whose role list includes `EstablishmentOperator`
    or `Artist`."

    Design: Corner/rbac/artist_cannot_file_procedure_log_for_another_artist
    """
    establishment = create_permitted_establishment(
        name="Two Artist Ink", street_address="52 Fiftysecond St"
    )
    alpha = create_active_artist(establishment["id"], "Artist Alpha")
    beta = create_active_artist(establishment["id"], "Artist Beta")

    response = api.create_procedure_log(
        create_procedure_log_payload(
            establishment["id"], alpha["id"], client_age=33,
            started_at="2026-05-01T09:00:00Z", ended_at="2026-05-01T10:00:00Z",
        ),
        make_artist_headers(beta["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert response.status_code == 403

    _, meta = validate_paginated(
        api.list_procedure_logs(HO, params={"artist_id": alpha["id"]})
    )
    assert meta["total_count"] == 0


def test_every_collection_resolves_its_own_not_found_code(api):
    """PRD §2.6: "An unresolved establishment segment yields
    `ERR_ESTABLISHMENT_NOT_FOUND`, an artist segment yields `ERR_ARTIST_NOT_FOUND`, a
    plan-review segment yields `ERR_PLAN_REVIEW_NOT_FOUND`, an inspection segment
    yields `ERR_INSPECTION_NOT_FOUND`, a violation segment yields
    `ERR_VIOLATION_NOT_FOUND`, a sterilization-record segment yields
    `ERR_STERILIZATION_RECORD_NOT_FOUND`, a minor-consent segment yields
    `ERR_MINOR_CONSENT_NOT_FOUND`, a procedure-log segment yields
    `ERR_PROCEDURE_LOG_NOT_FOUND`, a complaint segment yields
    `ERR_COMPLAINT_NOT_FOUND`, an infection-report segment yields
    `ERR_INFECTION_REPORT_NOT_FOUND`, an enforcement-action segment yields
    `ERR_ENFORCEMENT_ACTION_NOT_FOUND` and a renewal-application segment yields
    `ERR_RENEWAL_APPLICATION_NOT_FOUND`. All of these carry HTTP 404."

    Design: Corner/errors/not_found_family_across_every_path_resource
    """
    probes = [
        (api.get_artist, ApiErrorId.ERR_ARTIST_NOT_FOUND),
        (api.get_plan_review, ApiErrorId.ERR_PLAN_REVIEW_NOT_FOUND),
        (api.get_inspection, ApiErrorId.ERR_INSPECTION_NOT_FOUND),
        (api.get_violation, ApiErrorId.ERR_VIOLATION_NOT_FOUND),
        (api.get_sterilization_record, ApiErrorId.ERR_STERILIZATION_RECORD_NOT_FOUND),
        (api.get_minor_consent, ApiErrorId.ERR_MINOR_CONSENT_NOT_FOUND),
        (api.get_procedure_log, ApiErrorId.ERR_PROCEDURE_LOG_NOT_FOUND),
        (api.get_complaint, ApiErrorId.ERR_COMPLAINT_NOT_FOUND),
        (api.get_infection_report, ApiErrorId.ERR_INFECTION_REPORT_NOT_FOUND),
        (api.get_enforcement_action, ApiErrorId.ERR_ENFORCEMENT_ACTION_NOT_FOUND),
        (api.get_renewal_application, ApiErrorId.ERR_RENEWAL_APPLICATION_NOT_FOUND),
    ]
    for reader, expected in probes:
        response = reader(UNKNOWN_UUID, HO)
        validate_error(response, expected.value)
        assert response.status_code == 404, (
            f"{expected.value} must carry HTTP 404, got {response.status_code}"
        )


def test_each_entity_reports_its_own_state_invalid_code(api):
    """PRD §2.9: "When it does not, the error identifier is chosen by the entity that
    owns the state machine, not by the action: establishments yield
    `ERR_ESTABLISHMENT_STATE_INVALID`, artists `ERR_ARTIST_STATE_INVALID`, plan reviews
    `ERR_PLAN_REVIEW_STATE_INVALID`, inspections `ERR_INSPECTION_STATE_INVALID`,
    violations `ERR_VIOLATION_STATE_INVALID`, minor consents
    `ERR_CONSENT_STATE_INVALID`, procedure logs `ERR_PROCEDURE_LOG_STATE_INVALID`,
    complaints `ERR_COMPLAINT_STATE_INVALID`, infection reports
    `ERR_INFECTION_STATE_INVALID`, enforcement actions
    `ERR_ENFORCEMENT_STATE_INVALID` and renewal applications
    `ERR_RENEWAL_STATE_INVALID`. All eleven carry HTTP 409."
    PRD §3.6: "Both decisions are admissible only from `PENDING`, and both stamp
    `verified_by_user_id` with the clerk's identifier; the rejection additionally
    stores the supplied reason."
    PRD §3.4: "Adjudicating the correction belongs to an `Inspector`, who supplies a
    `decision` of either `VERIFY` or `REJECT`. Both are admissible only from
    `CORRECTION_SUBMITTED`."
    PRD §3.6: "Clearing is admissible only from `FLAGGED`, drives `FLAGGED → CLEARED`
    and resets `audit_finding_code` back to null; `CLEARED` is terminal."

    Design: Corner/errors/state_invalid_family_across_artist_consent_violation_complaint_and_report
    """
    establishment = create_permitted_establishment(
        name="State Family Ink", street_address="45 Fortyfifth St",
        establishment_type="COMBINED",
    )
    artist = create_active_artist(establishment["id"], "Fam Ily")
    log = file_procedure_log(
        establishment["id"], artist["id"], client_age=28,
        started_at="2026-05-01T09:00:00Z", ended_at="2026-05-01T10:00:00Z",
    )
    consent = create_verified_minor_consent(
        establishment["id"], minor_full_name="Min Or", guardian_full_name="Gar Dian",
        guardian_id_document_type="STATE_ID", guardian_id_document_number="SI-8",
    )
    complaint = file_complaint(
        establishment["id"], complainant_contact="cx@example.com",
        category="OTHER", narrative="General concern.",
    )
    report = file_infection_report(
        establishment["id"], reporter_contact="ir@example.com", infection_type="OTHER",
        procedure_date="2026-04-12T00:00:00Z", symptom_onset_at="2026-04-15T00:00:00Z",
    )
    inspection = start_inspection_at(
        establishment["id"], "2026-05-06T00:00:00Z", "2026-05-06T02:00:00Z"
    )
    violation = cite_violation(
        inspection["id"], "SIGN_001", "NONCRITICAL", "Permit not posted."
    )

    reactivate = api.activate_artist(artist["id"], HO)
    validate_error(reactivate, ApiErrorId.ERR_ARTIST_STATE_INVALID.value)
    assert reactivate.status_code == 409

    reverify = api.verify_minor_consent(
        consent["id"], {"decision": "REJECT", "rejection_reason": "Second look"}, CLERK
    )
    validate_error(reverify, ApiErrorId.ERR_CONSENT_STATE_INVALID.value)
    assert reverify.status_code == 409

    premature = api.decide_violation_correction(
        violation["id"], {"decision": "VERIFY"}, INSP
    )
    validate_error(premature, ApiErrorId.ERR_VIOLATION_STATE_INVALID.value)
    assert premature.status_code == 409

    substantiate = api.transition_complaint(
        complaint["id"], {"action": "SUBSTANTIATE"}, HO
    )
    validate_error(substantiate, ApiErrorId.ERR_COMPLAINT_STATE_INVALID.value)
    assert substantiate.status_code == 409

    confirm = api.advance_infection_investigation(report["id"], {"action": "CONFIRM"}, HO)
    validate_error(confirm, ApiErrorId.ERR_INFECTION_STATE_INVALID.value)
    assert confirm.status_code == 409

    clear = api.audit_procedure_log(log["id"], {"decision": "CLEAR"}, HO)
    validate_error(clear, ApiErrorId.ERR_PROCEDURE_LOG_STATE_INVALID.value)
    assert clear.status_code == 409

    assert validate_success(api.get_violation(violation["id"], HO))["status"] == "ISSUED"
    assert validate_success(api.get_complaint(complaint["id"], HO))["status"] == "RECEIVED"
    stored_report = validate_success(api.get_infection_report(report["id"], HO))
    assert stored_report["investigation_status"] == "RECEIVED"
    assert validate_success(api.get_procedure_log(log["id"], HO))["audit_status"] == "RECORDED"
