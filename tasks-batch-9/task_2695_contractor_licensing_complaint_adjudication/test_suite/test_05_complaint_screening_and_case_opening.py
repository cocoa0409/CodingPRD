"""Screening forks a complaint, and a citation waits on its own case.

Two byte-identical screening requests send two complaints to different states,
because the branch is chosen by the accused party's licensure situation. Later,
the citation endpoint reads a different entity's status before it will write.
"""

from test_helpers import (
    INVESTIGATOR_USER_ID,
    LICENSING_ANALYST_HEADERS,
    ApiErrorId,
    CitationStatus,
    ComplaintStatus,
    InvestigationFinding,
    InvestigationStatus,
    JurisdictionBasis,
    Severity,
    SubjectType,
    assert_citation,
    assert_complaint,
    assert_fields,
    assert_investigation,
    constants as K,
    factories as F,
    fixtures as FX,
    make_investigator_headers,
    validate_error,
    validate_success,
)


def _two_complaints_awaiting_screening(api):
    """One grievance against a mediating licensee and one against a ghost operator."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    ctx = FX.mint_active_license(api)
    consumer_one = FX.register_consumer(
        api, full_name="Mia Homeowner", contact_email="mia@home.test"
    )
    consumer_two = FX.register_consumer(
        api, full_name="Rae Homeowner", contact_email="rae@home.test"
    )
    FX.set_clock(api, "2026-09-01T00:00:00Z")
    licensed = FX.file_complaint(
        api,
        consumer_one["id"],
        ctx.license_id,
        alleged_loss_cents=800000,
        contract_date="2026-08-10",
        work_completed_on="2026-08-20",
        description="Panel upgrade left unfinished",
    )
    unlicensed = FX.file_unlicensed_complaint(
        api,
        consumer_two["id"],
        "Ghost Plumbing Co",
        alleged_loss_cents=600000,
        contract_date="2026-08-12",
        work_completed_on="2026-08-25",
        description="Repipe by an operator with no licence number",
    )
    return ctx, licensed, unlicensed


def test_01_an_accepted_complaint_against_a_mediating_licensee_opens_mediation(api):
    """The licensed subject takes the mediation branch with a thirty-day window.

    PRD: "The complaint moves `RECEIVED → MEDIATION`, its `jurisdiction_basis` is
    stamped `LICENSED_SUBJECT`, its `mediation_round_count` is set to 1, and its
    `mediation_deadline` is set to the clock date advanced by thirty days — the
    window in which the current mediation attempt must produce something."

    Design: Difficulty/non_linear_state_machine/complaint_screening_forks_into_mediation_or_direct_investigation
    """
    _ctx, licensed, _unlicensed = _two_complaints_awaiting_screening(api)

    screened = FX.screen_accepted(api, licensed["id"])

    assert_complaint(
        screened,
        status=ComplaintStatus.MEDIATION,
        jurisdiction_basis=JurisdictionBasis.LICENSED_SUBJECT,
        mediation_round_count=1,
        mediation_deadline="2026-10-01",
    )


def test_02_the_same_request_body_sends_an_unlicensed_grievance_to_investigation(api):
    """No licence named means direct enforcement and no mediation window at all.

    PRD: "The complaint moves `RECEIVED → INVESTIGATION`. Its
    `jurisdiction_basis` is stamped `UNLICENSED_PRACTICE` when no `license_id` was
    supplied, and `LICENSED_SUBJECT` otherwise."

    Design: Difficulty/non_linear_state_machine/complaint_screening_forks_into_mediation_or_direct_investigation
    """
    _ctx, _licensed, unlicensed = _two_complaints_awaiting_screening(api)

    screened = FX.screen_accepted(api, unlicensed["id"])

    assert_complaint(
        screened,
        status=ComplaintStatus.INVESTIGATION,
        jurisdiction_basis=JurisdictionBasis.UNLICENSED_PRACTICE,
        license_id=None,
    )


def test_03_the_direct_enforcement_branch_never_opens_a_mediation_window(api):
    """Round count stays at zero and the deadline stays null on that branch.

    PRD: "Critically, `mediation_round_count` stays at zero and
    `mediation_deadline` stays null: **this branch never opens a mediation
    window**, which matters later because the remand rule counts rounds."

    Design: Difficulty/non_linear_state_machine/complaint_screening_forks_into_mediation_or_direct_investigation
    """
    _ctx, licensed, unlicensed = _two_complaints_awaiting_screening(api)

    FX.screen_accepted(api, licensed["id"])
    FX.screen_accepted(api, unlicensed["id"])

    direct = validate_success(
        api.get_complaint(unlicensed["id"], LICENSING_ANALYST_HEADERS)
    )
    assert_fields(
        direct,
        {
            "status": ComplaintStatus.INVESTIGATION,
            "mediation_round_count": 0,
            "mediation_deadline": None,
        },
    )
    mediating = validate_success(
        api.get_complaint(licensed["id"], LICENSING_ANALYST_HEADERS)
    )
    assert_fields(
        mediating,
        {"status": ComplaintStatus.MEDIATION, "mediation_round_count": 1},
    )


def _one_open_and_one_dead_case(api):
    """A live case and a case closed with no violation found, on one HVAC licence."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    classification = FX.create_c20_classification(api)
    ctx = FX.mint_active_license(
        api,
        classification,
        legal_name="Gable HVAC LLC",
        contact_email="ops@gable.test",
        full_name="Gus Gable",
    )
    consumer_open = FX.register_consumer(
        api, full_name="Owen Open", contact_email="owen@home.test"
    )
    consumer_dead = FX.register_consumer(
        api, full_name="Dina Dead", contact_email="dina@home.test"
    )
    FX.set_clock(api, "2026-09-01T00:00:00Z")
    complaint_open = FX.complaint_in_investigation(
        api, consumer_open["id"], ctx.license_id, description="Flue vented into attic"
    )
    complaint_dead = FX.complaint_in_investigation(
        api, consumer_dead["id"], ctx.license_id, description="Wiring gauge disputed"
    )
    case_open = FX.open_investigation(
        api, complaint_id=complaint_open["id"], subject_license_id=ctx.license_id
    )
    case_dead = FX.open_investigation(
        api, complaint_id=complaint_dead["id"], subject_license_id=ctx.license_id
    )
    validate_success(
        api.close_investigation(
            case_dead["id"],
            F.close_investigation_payload(
                InvestigationFinding.UNSUBSTANTIATED,
                evidence_summary="Wiring gauge measured to code",
            ),
            make_investigator_headers(INVESTIGATOR_USER_ID),
        )
    )
    return ctx, classification, case_open, case_dead, complaint_open, complaint_dead


def test_04_a_citation_cannot_be_raised_while_its_case_is_still_open(api):
    """The write target is the citation but the gate reads the case's own status.

    PRD: "The case must be `SUBSTANTIATED` — a case still `OPEN` or closed
    `UNSUBSTANTIATED` draws `ERR_INVESTIGATION_NOT_SUBSTANTIATED`."

    Design: Difficulty/cross_entity_state_dependency/citation_issuance_blocked_until_its_investigation_is_substantiated
    """
    _ctx, classification, case_open, _case_dead, complaint_open, _cd = (
        _one_open_and_one_dead_case(api)
    )

    validate_error(
        api.create_citation(
            F.citation_payload(
                case_open["id"],
                classification["id"],
                violation_code="B-7090",
                correction_due_date="2026-10-15",
            ),
            make_investigator_headers(INVESTIGATOR_USER_ID),
        ),
        ApiErrorId.INVESTIGATION_NOT_SUBSTANTIATED,
    )

    assert_investigation(
        validate_success(
            api.get_investigation(case_open["id"], LICENSING_ANALYST_HEADERS)
        ),
        status=InvestigationStatus.OPEN,
        finding_severity=None,
    )
    assert_fields(
        validate_success(
            api.get_complaint(complaint_open["id"], LICENSING_ANALYST_HEADERS)
        ),
        {"status": ComplaintStatus.INVESTIGATION},
    )


def test_05_a_case_closed_with_no_violation_found_is_refused_a_citation_too(api):
    """Reaching a terminal state is not enough; the finding itself must sanction.

    PRD: "An `UNSUBSTANTIATED` closure stores `evidence_summary` and `closed_on`,
    leaves `finding_severity` null, and cascades: when the origin was `COMPLAINT`
    and the linked complaint sits in `INVESTIGATION`, that complaint moves
    `INVESTIGATION → CLOSED_UNFOUNDED`."

    Design: Difficulty/cross_entity_state_dependency/citation_issuance_blocked_until_its_investigation_is_substantiated
    """
    _ctx, classification, _case_open, case_dead, _co, complaint_dead = (
        _one_open_and_one_dead_case(api)
    )

    validate_error(
        api.create_citation(
            F.citation_payload(
                case_dead["id"],
                classification["id"],
                violation_code="B-7090",
                correction_due_date="2026-10-15",
            ),
            make_investigator_headers(INVESTIGATOR_USER_ID),
        ),
        ApiErrorId.INVESTIGATION_NOT_SUBSTANTIATED,
    )

    assert_investigation(
        validate_success(
            api.get_investigation(case_dead["id"], LICENSING_ANALYST_HEADERS)
        ),
        status=InvestigationStatus.UNSUBSTANTIATED,
        finding_severity=None,
        closed_on="2026-09-01",
    )
    assert_fields(
        validate_success(
            api.get_complaint(complaint_dead["id"], LICENSING_ANALYST_HEADERS)
        ),
        {"status": ComplaintStatus.CLOSED_UNFOUNDED},
    )


def test_06_the_identical_request_succeeds_once_the_case_is_substantiated(api):
    """Substantiating with a severity unblocks the very same citation request.

    PRD: "Issuance lands the citation in `ISSUED` with `issued_on` set to the clock
    date and `appeal_deadline` set to `issued_on` advanced by fifteen days."

    Design: Difficulty/cross_entity_state_dependency/citation_issuance_blocked_until_its_investigation_is_substantiated
    """
    ctx, classification, case_open, _case_dead, complaint_open, _cd = (
        _one_open_and_one_dead_case(api)
    )
    closed = FX.substantiate(
        api,
        case_open["id"],
        severity=Severity.SERIOUS,
        evidence_summary="Flue terminates inside the attic space",
    )
    assert_fields(
        closed,
        {
            "status": InvestigationStatus.SUBSTANTIATED,
            "finding_severity": Severity.SERIOUS,
        },
    )

    citation = FX.issue_citation(
        api,
        case_open["id"],
        classification["id"],
        violation_code="B-7090",
        correction_due_date="2026-10-15",
    )

    assert_citation(
        citation,
        status=CitationStatus.ISSUED,
        issued_on="2026-09-01",
        appeal_deadline="2026-09-16",
        subject_type=SubjectType.LICENSED,
        license_id=ctx.license_id,
        severity=Severity.SERIOUS,
    )
    assert_fields(
        validate_success(
            api.get_complaint(complaint_open["id"], LICENSING_ANALYST_HEADERS)
        ),
        {"status": ComplaintStatus.CITATION_ISSUED},
    )
