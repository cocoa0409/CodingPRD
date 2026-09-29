"""Who may act: assigned-actor bindings, shared endpoints and peer isolation.

Holding the right role is only the first half of authority in this domain. The
enforcement offices are bound to the individual operator recorded on the case or
the hearing, continuing-education banking is deliberately shared between two
roles, and an entity-backed actor is confined to its own rows. These tests take
each of those bindings from the wrong side and then from the right side.
"""

from test_helpers import (
    BOARD_ADMIN_HEADERS,
    LICENSING_ANALYST_HEADERS,
    ApiErrorId,
    ApplicationDecision,
    CitationStatus,
    HearingDecision,
    HearingStatus,
    InvestigationFinding,
    InvestigationOrigin,
    InvestigationStatus,
    PenaltyVariant,
    Severity,
    factories as F,
    fixtures as FX,
    make_consumer_headers,
    make_hearing_officer_headers,
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


def _mint_c10_license(api, *, legal_name, contact_email, full_name, licensee=None):
    """Mints an ACTIVE C-10 licence the only way one comes into existence.

    Returns the classification, the contracting entity, the qualifying
    individual, the application and the licence the approval cascade minted.
    """
    classification = FX.create_c10_classification(api)
    if licensee is None:
        licensee = FX.register_licensee(
            api, legal_name=legal_name, contact_email=contact_email
        )
    individual = FX.register_exam_qualified_individual(
        api,
        classification["code"],
        verified_experience_months=60,
        taken_on="2025-03-01",
        law_score=88,
        trade_score=84,
        full_name=full_name,
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
    validate_success(
        api.decide_application(
            application["id"],
            F.decision_payload(ApplicationDecision.APPROVED),
            LICENSING_ANALYST_HEADERS,
        )
    )
    rows, _ = _list_rows(
        api,
        "/licensing/licenses",
        LICENSING_ANALYST_HEADERS,
        {"application_id": application["id"]},
    )
    assert rows, "approving the application must mint a licence"
    return classification, licensee, individual, application, rows[0]


def test_an_unassigned_investigator_cannot_close_the_case(api):
    """Closure is bound to the operator recorded when the case was opened.

    "And only the investigator who opened a case may close it or issue its
    citation: an actor whose `X-User-ID` differs from the case's
    `assigned_investigator_user_id` is refused with
    `ERR_NOT_ASSIGNED_INVESTIGATOR` (HTTP 403)."

    Design: Corner/rbac/corner_an_unassigned_investigator_cannot_close_the_case
    """
    FX.set_clock(api, CLOCK)
    investigation = FX.open_investigation(
        api,
        origin=InvestigationOrigin.STING,
        subject_business_name="Handoff Handyman",
        investigator_user_id="inv-40",
    )
    closure = F.close_investigation_payload(
        InvestigationFinding.SUBSTANTIATED,
        finding_severity=Severity.SERIOUS,
        evidence_summary="Colleague attempts to close the file",
    )

    response = api.close_investigation(
        investigation["id"], closure, make_investigator_headers("inv-41")
    )

    validate_error(response, ApiErrorId.NOT_ASSIGNED_INVESTIGATOR, 403)
    stored = validate_success(
        api.get_investigation(investigation["id"], BOARD_ADMIN_HEADERS)
    )
    assert stored["status"] == InvestigationStatus.OPEN
    assert stored["assigned_investigator_user_id"] == "inv-40"
    assert stored["closed_on"] is None

    closed = validate_success(
        api.close_investigation(
            investigation["id"], closure, make_investigator_headers("inv-40")
        )
    )
    assert closed["status"] == InvestigationStatus.SUBSTANTIATED


def test_licensee_and_analyst_share_the_ce_credit_endpoint(api):
    """Two roles bank against one licence and the hours accumulate; a third cannot.

    "Banking hours is available to the contracting entity and to a
    `LicensingAnalyst`, and each credit supplies the `ce_hours` earned, the
    `completed_on` date the coursework finished, and the `provider_name` that
    delivered it."

    Design: Corner/rbac/corner_licensee_and_analyst_share_the_ce_credit_endpoint
    """
    FX.set_clock(api, CLOCK)
    _, licensee, _, _, license_row = _mint_c10_license(
        api,
        legal_name="Shared CE Electric LLC",
        contact_email="shared@x.test",
        full_name="Sharon Shared",
    )
    licensee_headers = make_licensee_headers(licensee["id"])

    after_self = validate_success(
        api.bank_ce_credits(
            license_row["id"],
            F.ce_credit_payload(5, "2026-09-01", "Statewide CE Institute"),
            licensee_headers,
        )
    )
    after_analyst = validate_success(
        api.bank_ce_credits(
            license_row["id"],
            F.ce_credit_payload(3, "2026-09-10", "Board Sponsored Workshop"),
            LICENSING_ANALYST_HEADERS,
        )
    )

    assert after_self["ce_hours_completed"] == 5
    assert after_analyst["ce_hours_completed"] == 8
    assert FX.read_license(api, license_row["id"])["ce_hours_completed"] == 8

    consumer = FX.register_consumer(
        api,
        full_name="Curious Consumer",
        contact_email="curious@home.test",
        mailing_state="CA",
    )
    refused = api.bank_ce_credits(
        license_row["id"],
        F.ce_credit_payload(3, "2026-09-10", "Board Sponsored Workshop"),
        make_consumer_headers(consumer["id"]),
    )
    validate_error(refused, ApiErrorId.ROLE_NOT_PERMITTED, 403)
    assert FX.read_license(api, license_row["id"])["ce_hours_completed"] == 8


def test_investigator_cannot_preside_over_the_case_it_built(api):
    """The bar is on the payload, not the caller: the scheduler is the registrar.

    "The investigator who built a case may not preside over its hearing: when a
    hearing is calendared, the supplied `presiding_officer_user_id` must differ
    from the `assigned_investigator_user_id` recorded on the `Investigation`
    behind the citation, or the request is refused with
    `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/corner_investigator_cannot_preside_over_the_case_it_built
    """
    FX.set_clock(api, CLOCK)
    classification, licensee, _, _, license_row = _mint_c10_license(
        api,
        legal_name="Duties Split Electric LLC",
        contact_email="duties@x.test",
        full_name="Duncan Duties",
    )
    investigation = FX.open_investigation(
        api,
        origin=InvestigationOrigin.STING,
        subject_license_id=license_row["id"],
        investigator_user_id="inv-50",
    )
    FX.substantiate(
        api,
        investigation["id"],
        severity=Severity.SERIOUS,
        evidence_summary="Sting confirmed unpermitted service work",
        investigator_user_id="inv-50",
    )
    citation = FX.issue_citation(
        api,
        investigation["id"],
        classification["id"],
        investigator_user_id="inv-50",
        violation_code="B-7113",
        correction_due_date="2026-09-15",
    )
    validate_success(
        api.appeal_citation(
            citation["id"],
            F.appeal_payload(appeal_grounds="The work was inspected and passed"),
            make_licensee_headers(licensee["id"]),
        )
    )

    response = api.create_hearing(
        F.hearing_payload(
            citation["id"],
            "inv-50",
            "2026-08-25T10:00:00Z",
            "2026-08-25T12:00:00Z",
        ),
        BOARD_ADMIN_HEADERS,
    )

    validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES_VIOLATION, 403)
    stored = validate_success(api.get_citation(citation["id"], BOARD_ADMIN_HEADERS))
    assert stored["status"] == CitationStatus.APPEAL_REQUESTED
    _, meta = _list_rows(
        api,
        "/licensing/disciplinary-hearings",
        BOARD_ADMIN_HEADERS,
        {"citation_id": citation["id"]},
    )
    assert meta["total_count"] == 0

    validate_success(
        api.create_hearing(
            F.hearing_payload(
                citation["id"],
                "ho-7",
                "2026-08-25T10:00:00Z",
                "2026-08-25T12:00:00Z",
            ),
            BOARD_ADMIN_HEADERS,
        ),
        201,
    )
    rescheduled = validate_success(
        api.get_citation(citation["id"], BOARD_ADMIN_HEADERS)
    )
    assert rescheduled["status"] == CitationStatus.HEARING_SCHEDULED


def test_a_non_presiding_hearing_officer_cannot_decide(api):
    """A peer officer of the same rank still cannot dispose of the appeal.

    "Only the officer the hearing was calendared against may render its
    decision: an `X-User-ID` other than the hearing's
    `presiding_officer_user_id` is refused with `ERR_NOT_PRESIDING_OFFICER`
    (HTTP 403)."

    Design: Corner/rbac/corner_a_non_presiding_hearing_officer_cannot_decide
    """
    FX.set_clock(api, CLOCK)
    classification, licensee, _, _, license_row = _mint_c10_license(
        api,
        legal_name="Wrong Officer Electric LLC",
        contact_email="wrongho@x.test",
        full_name="Owen Officer",
    )
    investigation = FX.open_investigation(
        api,
        origin=InvestigationOrigin.STING,
        subject_license_id=license_row["id"],
        investigator_user_id="inv-51",
    )
    FX.substantiate(
        api,
        investigation["id"],
        severity=Severity.SERIOUS,
        evidence_summary="Sting confirmed unpermitted service work",
        investigator_user_id="inv-51",
    )
    citation = FX.issue_citation(
        api,
        investigation["id"],
        classification["id"],
        investigator_user_id="inv-51",
        violation_code="B-7113",
        correction_due_date="2026-09-15",
    )
    validate_success(
        api.appeal_citation(
            citation["id"],
            F.appeal_payload(
                appeal_grounds="The permit was applied for before the work"
            ),
            make_licensee_headers(licensee["id"]),
        )
    )
    hearing = FX.calendar_hearing(
        api,
        citation["id"],
        "2026-08-25T10:00:00Z",
        "2026-08-25T12:00:00Z",
        presiding_officer_user_id="ho-7",
    )
    FX.set_clock(api, "2026-08-25T10:30:00Z")
    decision = F.hearing_decision_payload(
        HearingDecision.AFFIRM,
        findings_summary="Substitute officer attempts the disposition",
    )

    response = api.decide_hearing(
        hearing["id"], decision, make_hearing_officer_headers("ho-8")
    )

    validate_error(response, ApiErrorId.NOT_PRESIDING_OFFICER, 403)
    stored = validate_success(api.get_hearing(hearing["id"], BOARD_ADMIN_HEADERS))
    assert stored["status"] == HearingStatus.SCHEDULED
    assert stored["sanction_tier"] is None
    cited = validate_success(api.get_citation(citation["id"], BOARD_ADMIN_HEADERS))
    assert cited["penalty_variant"] == PenaltyVariant.INITIAL_ASSESSMENT

    validate_success(
        api.decide_hearing(
            hearing["id"], decision, make_hearing_officer_headers("ho-7")
        )
    )
    decided = validate_success(api.get_citation(citation["id"], BOARD_ADMIN_HEADERS))
    assert decided["status"] == CitationStatus.AFFIRMED


def test_a_licensee_cannot_bank_ce_on_another_licensees_license(api):
    """Carrying the contracting-entity role is not the same as owning the row.

    "Ownership is checked on application submission, cure and withdrawal; on
    licence renewal, continuing-education banking and recovery repayment; on
    citation appeal and compliance; and on complaint withdrawal."

    Design: Corner/rbac/corner_a_licensee_cannot_bank_ce_on_another_licensees_license
    """
    FX.set_clock(api, CLOCK)
    owner = FX.register_licensee(
        api, legal_name="Owner A Electric LLC", contact_email="ownera@x.test"
    )
    outsider = FX.register_licensee(
        api, legal_name="Outsider B Electric LLC", contact_email="outsiderb@x.test"
    )
    _, _, _, _, license_row = _mint_c10_license(
        api,
        legal_name="Owner A Electric LLC",
        contact_email="ownera@x.test",
        full_name="Anna Owner",
        licensee=owner,
    )
    credit = F.ce_credit_payload(8, "2026-09-01", "Borrowed Credit Seminars")

    response = api.bank_ce_credits(
        license_row["id"], credit, make_licensee_headers(outsider["id"])
    )

    validate_error(response, ApiErrorId.NOT_RESOURCE_OWNER, 403)
    stored = FX.read_license(api, license_row["id"])
    assert stored["ce_hours_completed"] == 0
    assert stored["licensee_id"] == owner["id"]

    banked = validate_success(
        api.bank_ce_credits(
            license_row["id"], credit, make_licensee_headers(owner["id"])
        )
    )
    assert banked["ce_hours_completed"] == 8
