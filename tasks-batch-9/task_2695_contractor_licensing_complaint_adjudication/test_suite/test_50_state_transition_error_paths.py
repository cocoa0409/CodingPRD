"""Wrong-state actions across the licensing, coverage and enforcement lifecycles.

Every transition in this domain is defined from a named set of source states.
The tests here drive each row into a state the action is not defined from and
check that the refusal carries the entity's own state error, at the status the
error catalog registers, and that the rejected call rewrites nothing.
"""

from test_helpers import (
    BOARD_ADMIN_HEADERS,
    LICENSING_ANALYST_HEADERS,
    ApiErrorId,
    ApplicationDecision,
    ApplicationStatus,
    AssignmentStatus,
    CitationStatus,
    ComplaintStatus,
    CoverageStatus,
    CoverageType,
    InvestigationFinding,
    InvestigationOrigin,
    InvestigationStatus,
    LicenseStatus,
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


def _mint_c10_license(api, *, legal_name, contact_email, full_name):
    """Mints an ACTIVE C-10 licence the only way one comes into existence.

    Returns the classification, the contracting entity, the qualifying
    individual, the application and the licence the approval cascade minted.
    """
    classification = FX.create_c10_classification(api)
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


def test_closing_an_already_closed_investigation_is_rejected(api):
    """A second closure of a terminal case is refused and rewrites nothing.

    "Only an `OPEN` case may be closed, and anything else draws
    `ERR_INVESTIGATION_STATE_INVALID`; an actor other than the assigned
    investigator draws `ERR_NOT_ASSIGNED_INVESTIGATOR`."

    Design: Corner/errors/corner_closing_an_already_closed_investigation_is_rejected
    """
    FX.set_clock(api, CLOCK)
    investigator_headers = make_investigator_headers("inv-11")
    investigation = get_success_data(
        api.create_investigation(
            F.investigation_payload(
                InvestigationOrigin.STING,
                subject_business_name="Twice Closed Trades",
            ),
            investigator_headers,
        )
    )
    validate_success(
        api.close_investigation(
            investigation["id"],
            F.close_investigation_payload(
                InvestigationFinding.SUBSTANTIATED,
                finding_severity=Severity.MINOR,
                evidence_summary="First closure on the sting file",
            ),
            investigator_headers,
        )
    )

    response = api.close_investigation(
        investigation["id"],
        F.close_investigation_payload(
            InvestigationFinding.UNSUBSTANTIATED,
            evidence_summary="Second look says otherwise",
        ),
        investigator_headers,
    )

    validate_error(response, ApiErrorId.INVESTIGATION_STATE_INVALID, 409)
    stored = validate_success(
        api.get_investigation(investigation["id"], investigator_headers)
    )
    assert stored["status"] == InvestigationStatus.SUBSTANTIATED
    assert stored["finding_severity"] == Severity.MINOR
    assert stored["evidence_summary"] == "First closure on the sting file"


def test_investigating_an_unscreened_complaint_is_rejected(api):
    """A complaint still in RECEIVED cannot carry a complaint-driven case.

    "A complaint-driven case names the `complaint_id` it arises from and must
    not be opened unless that complaint sits in `INVESTIGATION`; a sting case —
    the board's own operation against an unlicensed operator — must not name a
    `complaint_id` at all."

    Design: Corner/errors/corner_investigating_an_unscreened_complaint_is_rejected
    """
    FX.set_clock(api, CLOCK)
    consumer = FX.register_consumer(
        api,
        full_name="Ida Unscreened",
        contact_email="ida@home.test",
        mailing_state="CA",
    )
    complaint = get_success_data(
        api.create_complaint(
            {
                "consumer_id": consumer["id"],
                "subject_business_name": "Premature Probe Builders",
                "alleged_loss_cents": 400000,
                "contract_date": "2026-07-01",
                "description": "Deposit taken, no work started",
            },
            make_consumer_headers(consumer["id"]),
        )
    )

    response = api.create_investigation(
        F.investigation_payload(
            InvestigationOrigin.COMPLAINT, complaint_id=complaint["id"]
        ),
        make_investigator_headers("inv-13"),
    )

    validate_error(response, ApiErrorId.COMPLAINT_STATE_INVALID, 409)
    stored = validate_success(
        api.get_complaint(complaint["id"], LICENSING_ANALYST_HEADERS)
    )
    assert stored["status"] == ComplaintStatus.RECEIVED
    _, meta = _list_rows(
        api,
        "/licensing/investigations",
        LICENSING_ANALYST_HEADERS,
        {"complaint_id": complaint["id"]},
    )
    assert meta["total_count"] == 0


def test_submitting_an_already_submitted_application_is_rejected(api):
    """The second submit is refused and the original submitted_at survives.

    "Attempting an action from the wrong state — submitting an
    already-`SUBMITTED` application, curing one that is not `DEFICIENT`,
    deciding a `WITHDRAWN` one, or withdrawing a decided one — draws
    `ERR_APPLICATION_STATE_INVALID`."

    Design: Corner/errors/corner_submitting_an_already_submitted_application_is_rejected
    """
    FX.set_clock(api, CLOCK)
    classification = FX.create_c10_classification(api)
    licensee = FX.register_licensee(
        api, legal_name="Double Submit Electric LLC", contact_email="double@x.test"
    )
    individual = FX.register_exam_qualified_individual(
        api,
        classification["code"],
        verified_experience_months=60,
        taken_on="2025-03-01",
        law_score=88,
        trade_score=84,
        full_name="Dee Double",
    )
    application = FX.open_application(
        api,
        licensee["id"],
        classification["id"],
        individual["id"],
        declared_net_worth_cents=400000,
    )
    licensee_headers = make_licensee_headers(licensee["id"])
    submitted = validate_success(
        api.submit_application(application["id"], licensee_headers)
    )
    first_submitted_at = submitted["submitted_at"]

    response = api.submit_application(application["id"], licensee_headers)

    validate_error(response, ApiErrorId.APPLICATION_STATE_INVALID, 409)
    stored = validate_success(
        api.get_application(application["id"], licensee_headers)
    )
    assert stored["status"] == ApplicationStatus.SUBMITTED
    assert stored["submitted_at"] == first_submitted_at


def test_scheduling_a_hearing_on_an_unappealed_citation_is_rejected(api):
    """A hearing exists only on the appeal branch, never against an ISSUED citation.

    "The citation must sit in `APPEAL_REQUESTED`, or the request draws
    `ERR_CITATION_STATE_INVALID`."

    Design: Corner/errors/corner_scheduling_a_hearing_on_an_unappealed_citation_is_rejected
    """
    FX.set_clock(api, CLOCK)
    classification = FX.create_c10_classification(api)
    investigation = FX.open_investigation(
        api,
        origin=InvestigationOrigin.STING,
        subject_business_name="No Appeal Wiring",
        investigator_user_id="inv-14",
    )
    FX.substantiate(
        api,
        investigation["id"],
        severity=Severity.SERIOUS,
        evidence_summary="Sting purchase of unlicensed electrical work",
        investigator_user_id="inv-14",
    )
    citation = FX.issue_citation(
        api,
        investigation["id"],
        classification["id"],
        investigator_user_id="inv-14",
        violation_code="B-7028",
        correction_due_date="2026-09-15",
    )

    response = api.create_hearing(
        F.hearing_payload(
            citation["id"],
            "ho-3",
            "2026-08-20T10:00:00Z",
            "2026-08-20T12:00:00Z",
        ),
        BOARD_ADMIN_HEADERS,
    )

    validate_error(response, ApiErrorId.CITATION_STATE_INVALID, 409)
    stored = validate_success(api.get_citation(citation["id"], BOARD_ADMIN_HEADERS))
    assert stored["status"] == CitationStatus.ISSUED
    _, meta = _list_rows(
        api,
        "/licensing/disciplinary-hearings",
        BOARD_ADMIN_HEADERS,
        {"citation_id": citation["id"]},
    )
    assert meta["total_count"] == 0


def test_reinstating_an_active_license_is_rejected(api):
    """Reinstatement is defined only from SUSPENDED and never resets the CE bank.

    "Reinstating a licence that is not suspended draws
    `ERR_LICENSE_STATE_INVALID`."

    Design: Corner/errors/corner_reinstating_an_active_license_is_rejected
    """
    FX.set_clock(api, CLOCK)
    _, licensee, _, _, license_row = _mint_c10_license(
        api,
        legal_name="Already Active Electric LLC",
        contact_email="active@x.test",
        full_name="Ada Active",
    )
    validate_success(
        api.bank_ce_credits(
            license_row["id"],
            F.ce_credit_payload(8, "2026-08-15", "Statewide CE Institute"),
            make_licensee_headers(licensee["id"]),
        )
    )

    response = api.reinstate_license(license_row["id"], LICENSING_ANALYST_HEADERS)

    validate_error(response, ApiErrorId.LICENSE_STATE_INVALID, 409)
    stored = FX.read_license(api, license_row["id"])
    assert stored["status"] == LicenseStatus.ACTIVE
    assert stored["ce_hours_completed"] == 8


def test_cancelling_an_unverified_coverage_record_is_rejected(api):
    """Only a confirmed instrument can be carrier-cancelled.

    "A `LicensingAnalyst` supplies a `cancellation_date`, which must be on or
    after the record's `effective_date`; only a record in `VERIFIED` may be
    cancelled."

    Design: Corner/errors/corner_cancelling_an_unverified_coverage_record_is_rejected
    """
    FX.set_clock(api, CLOCK)
    _, _, _, _, license_row = _mint_c10_license(
        api,
        legal_name="Unverified Bond Electric LLC",
        contact_email="unver@x.test",
        full_name="Uma Unverified",
    )
    coverage = FX.file_coverage(
        api,
        license_row["id"],
        coverage_type=CoverageType.BOND,
        carrier_name="Pending Surety",
        policy_number="BND-PEND",
        amount_cents=1500000,
        effective_date="2026-08-01",
        expiration_date="2028-09-01",
    )

    response = api.cancel_coverage_record(
        coverage["id"],
        F.cancellation_payload("2026-09-01"),
        LICENSING_ANALYST_HEADERS,
    )

    validate_error(response, ApiErrorId.COVERAGE_STATE_INVALID, 409)
    stored = validate_success(
        api.get_coverage_record(coverage["id"], LICENSING_ANALYST_HEADERS)
    )
    assert stored["status"] == CoverageStatus.PENDING_VERIFICATION
    assert stored["expiration_date"] == "2028-09-01"
    assert stored["cancellation_date"] is None
    assert FX.read_license(api, license_row["id"])["status"] == LicenseStatus.ACTIVE


def test_withdrawing_an_already_withdrawn_designation_is_rejected(api):
    """A second withdrawal is refused and the qualification count stays at zero.

    "Only a designation in `ACTIVE` may be withdrawn — one already `WITHDRAWN`,
    `SUSPENDED_BY_LICENSE` or `TERMINATED_BY_REVOCATION` draws
    `ERR_ASSIGNMENT_STATE_INVALID` — and the supplied `withdrawn_on` must be on
    or after the designation's own `effective_from`."

    Design: Corner/errors/corner_withdrawing_an_already_withdrawn_designation_is_rejected
    """
    FX.set_clock(api, CLOCK)
    _, _, individual, _, license_row = _mint_c10_license(
        api,
        legal_name="Twice Withdrawn Electric LLC",
        contact_email="tw@x.test",
        full_name="Wes Withdrawn",
    )
    assignments, _ = _list_rows(
        api,
        "/licensing/qualifier-assignments",
        LICENSING_ANALYST_HEADERS,
        {"license_id": license_row["id"]},
    )
    assert assignments, "the approval cascade must mint a designation"
    assignment_id = assignments[0]["id"]
    validate_success(
        api.withdraw_qualifier_assignment(
            assignment_id, {"withdrawn_on": "2026-08-10"}, LICENSING_ANALYST_HEADERS
        )
    )

    response = api.withdraw_qualifier_assignment(
        assignment_id, {"withdrawn_on": "2026-08-20"}, LICENSING_ANALYST_HEADERS
    )

    validate_error(response, ApiErrorId.ASSIGNMENT_STATE_INVALID, 409)
    stored = validate_success(
        api.get_qualifier_assignment(assignment_id, LICENSING_ANALYST_HEADERS)
    )
    assert stored["status"] == AssignmentStatus.WITHDRAWN
    assert stored["withdrawn_on"] == "2026-08-10"
    qualifier = validate_success(
        api.get_qualifying_individual(individual["id"], LICENSING_ANALYST_HEADERS)
    )
    assert qualifier["active_qualification_count"] == 0
