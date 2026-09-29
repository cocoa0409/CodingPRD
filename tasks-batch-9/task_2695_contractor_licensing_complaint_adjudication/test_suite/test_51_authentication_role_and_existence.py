"""Request-plumbing refusals: identity, role and foreign-key existence.

These tests exercise the front of the validation order, where a request is
turned away before any business rule is consulted: a call carrying no identity
headers, a body naming a row that does not exist, and calls made by a role the
endpoint does not admit. Each one also checks that nothing was written.
"""

from test_helpers import (
    BOARD_ADMIN_HEADERS,
    LICENSING_ANALYST_HEADERS,
    ApiErrorId,
    ApplicationDecision,
    ApplicationStatus,
    ComplaintStatus,
    InvestigationOrigin,
    JurisdictionFinding,
    Severity,
    factories as F,
    fixtures as FX,
    get_success_data,
    make_consumer_headers,
    make_investigator_headers,
    make_licensee_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"


def _list_rows(api, path, headers, params):
    """Reads a collection endpoint and returns its rows plus pagination meta."""
    return validate_paginated(api.get(path, headers=headers, params=params))


def test_missing_identity_headers_are_unauthenticated(api):
    """A well-formed body cannot buy its way past the identity check.

    "If either header is absent or present-but-empty, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401) before any other consideration."

    Design: Corner/errors/corner_missing_identity_headers_are_unauthenticated
    """
    response = api.post(
        "/licensing/trade-classifications",
        json={
            "code": "C-10",
            "name": "Electrical",
            "hazard_tier": 3,
            "min_experience_months": 48,
            "min_net_worth_cents": 250000,
            "required_bond_amount_cents": 1500000,
            "required_ce_hours": 8,
            "renewal_base_fee_cents": 45000,
        },
    )

    validate_error(response, ApiErrorId.UNAUTHENTICATED, 401)


def test_citation_on_an_unknown_investigation_is_not_found(api):
    """The missing foreign key, not the substantiation rule, names the error.

    "The same precedence applies to foreign keys in a request body: the entity a
    missing identifier names determines which not-found error is returned."

    Design: Corner/errors/corner_citation_on_an_unknown_investigation_is_not_found
    """
    FX.set_clock(api, CLOCK)
    classification = FX.create_c10_classification(api)

    response = api.create_citation(
        F.citation_payload(
            "00000000-0000-0000-0000-0000000000ff",
            classification["id"],
            violation_code="B-7028",
            correction_due_date="2026-09-15",
        ),
        make_investigator_headers("inv-12"),
    )

    validate_error(response, ApiErrorId.INVESTIGATION_NOT_FOUND, 404)
    _, meta = _list_rows(
        api,
        "/licensing/citations",
        LICENSING_ANALYST_HEADERS,
        {"classification_id": classification["id"]},
    )
    assert meta["total_count"] == 0


def test_complaint_with_an_unknown_consumer_is_not_found(api):
    """Intake resolves the consumer before it weighs the pleaded loss.

    "Within request plumbing the sequence is authentication, then role, then
    request-body schema, then existence of the row named by the `{id}` path
    parameter, then existence of every foreign key carried in the body, then
    ownership, then pagination arguments."

    Design: Corner/errors/corner_complaint_with_an_unknown_consumer_is_not_found
    """
    FX.set_clock(api, CLOCK)

    response = api.create_complaint(
        {
            "consumer_id": "00000000-0000-0000-0000-0000000000aa",
            "subject_business_name": "Phantom Consumer Job",
            "alleged_loss_cents": 10000,
            "contract_date": "2026-07-01",
            "description": "Filed on behalf of an unknown consumer",
        },
        LICENSING_ANALYST_HEADERS,
    )

    validate_error(response, ApiErrorId.CONSUMER_NOT_FOUND, 404)
    _, meta = _list_rows(api, "/licensing/complaints", LICENSING_ANALYST_HEADERS, {})
    assert meta["total_count"] == 0


def test_consumer_cannot_screen_a_complaint(api):
    """Filing a complaint confers no authority to screen it.

    "If both headers are present but the declared role is not among the roles the
    called endpoint admits, the request is rejected with `ERR_ROLE_NOT_PERMITTED`
    (HTTP 403)."

    Design: Corner/rbac/corner_consumer_cannot_screen_a_complaint
    """
    FX.set_clock(api, CLOCK)
    consumer = FX.register_consumer(
        api,
        full_name="Cody Consumer",
        contact_email="cody@home.test",
        mailing_state="CA",
    )
    consumer_headers = make_consumer_headers(consumer["id"])
    complaint = get_success_data(
        api.create_complaint(
            {
                "consumer_id": consumer["id"],
                "subject_business_name": "Self Screen Builders",
                "alleged_loss_cents": 400000,
                "contract_date": "2026-07-01",
                "description": "Retaining wall failed inspection",
            },
            consumer_headers,
        )
    )
    screening = F.screening_payload(JurisdictionFinding.ACCEPTED)

    response = api.screen_complaint(complaint["id"], screening, consumer_headers)

    validate_error(response, ApiErrorId.ROLE_NOT_PERMITTED, 403)
    stored = validate_success(
        api.get_complaint(complaint["id"], LICENSING_ANALYST_HEADERS)
    )
    assert stored["status"] == ComplaintStatus.RECEIVED

    screened = validate_success(
        api.screen_complaint(complaint["id"], screening, LICENSING_ANALYST_HEADERS)
    )
    assert screened["status"] != ComplaintStatus.RECEIVED


def test_licensing_analyst_cannot_issue_a_citation(api):
    """A substantiated case in hand does not let the licensing desk cite.

    "Opens complaint-driven and sting cases, closes them with a severity finding,
    issues citations, and may remand a complaint for a second mediation attempt."

    Design: Corner/rbac/corner_licensing_analyst_cannot_issue_a_citation
    """
    FX.set_clock(api, CLOCK)
    classification = FX.create_c10_classification(api)
    investigation = FX.open_investigation(
        api,
        origin=InvestigationOrigin.STING,
        subject_business_name="Analyst Reach Wiring",
        investigator_user_id="inv-30",
    )
    FX.substantiate(
        api,
        investigation["id"],
        severity=Severity.MINOR,
        evidence_summary="Unlicensed bid documented",
        investigator_user_id="inv-30",
    )
    citation_body = F.citation_payload(
        investigation["id"],
        classification["id"],
        violation_code="B-7028",
        correction_due_date="2026-09-15",
    )

    response = api.create_citation(citation_body, LICENSING_ANALYST_HEADERS)

    validate_error(response, ApiErrorId.ROLE_NOT_PERMITTED, 403)
    _, meta = _list_rows(
        api,
        "/licensing/citations",
        LICENSING_ANALYST_HEADERS,
        {"investigation_id": investigation["id"]},
    )
    assert meta["total_count"] == 0

    validate_success(
        api.create_citation(citation_body, make_investigator_headers("inv-30")), 201
    )


def test_board_admin_cannot_decide_a_license_application(api):
    """The registrar owns reference data, not licensing decisions.

    "Decides applications, verifies and cancels coverage instruments, designates
    and withdraws qualifiers, reinstates suspended licences, screens complaints,
    records mediation outcomes, and defaults unappealed citations to final."

    Design: Corner/rbac/corner_board_admin_cannot_decide_a_license_application
    """
    FX.set_clock(api, CLOCK)
    classification = FX.create_c10_classification(api)
    licensee = FX.register_licensee(
        api, legal_name="Peer Roles Electric LLC", contact_email="peer@x.test"
    )
    individual = FX.register_exam_qualified_individual(
        api,
        classification["code"],
        verified_experience_months=60,
        taken_on="2025-03-01",
        law_score=88,
        trade_score=84,
        full_name="Perry Peer",
    )
    application = FX.open_application(
        api,
        licensee["id"],
        classification["id"],
        individual["id"],
        declared_net_worth_cents=400000,
    )
    licensee_headers = make_licensee_headers(licensee["id"])
    validate_success(api.submit_application(application["id"], licensee_headers))

    response = api.decide_application(
        application["id"],
        F.decision_payload(ApplicationDecision.APPROVED),
        BOARD_ADMIN_HEADERS,
    )

    validate_error(response, ApiErrorId.ROLE_NOT_PERMITTED, 403)
    stored = validate_success(
        api.get_application(application["id"], LICENSING_ANALYST_HEADERS)
    )
    assert stored["status"] == ApplicationStatus.SUBMITTED
    _, meta = _list_rows(
        api,
        "/licensing/licenses",
        LICENSING_ANALYST_HEADERS,
        {"application_id": application["id"]},
    )
    assert meta["total_count"] == 0
