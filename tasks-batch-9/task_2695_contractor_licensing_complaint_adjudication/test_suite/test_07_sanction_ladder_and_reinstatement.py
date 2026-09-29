"""The points ladder is graded on posture, and reinstatement walks three gates.

Two identical minor citations differ only in the pre-decision posture of the
licence behind them, which is enough to cross a rung boundary. The second half
takes a disciplinary suspension and repairs its three neighbours one at a time,
watching the unchanged reinstatement request report a different gate each time.
"""

from test_helpers import (
    HEARING_OFFICER_USER_ID,
    LICENSING_ANALYST_HEADERS,
    SECOND_HEARING_OFFICER_USER_ID,
    ApiErrorId,
    CitationStatus,
    CompliancePosture,
    CoverageType,
    HearingDecision,
    LicenseStatus,
    SanctionTier,
    Severity,
    SuspensionReason,
    assert_fields,
    assert_qualification_count,
    constants as K,
    factories as F,
    fixtures as FX,
    validate_error,
    validate_success,
)

HEARING_START = "2026-09-10T14:00:00Z"
HEARING_END = "2026-09-10T16:00:00Z"


def _two_minor_appeals_awaiting_decision(api):
    """One CONDITIONAL and one NON_COMPLIANT licence, each with a minor appeal."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    classification = FX.create_c20_classification(api)
    bonded = FX.mint_active_license(
        api,
        classification,
        legal_name="Bonded Air LLC",
        contact_email="ops@bonded.test",
        full_name="Bo Bonded",
    )
    bare = FX.mint_active_license(
        api,
        classification,
        legal_name="Bare Air LLC",
        contact_email="ops@bare.test",
        full_name="Bea Bare",
    )
    bond = FX.file_coverage(
        api,
        bonded.license_id,
        coverage_type=CoverageType.BOND,
        carrier_name="Surety Two",
        policy_number="BND-2001",
        amount_cents=K.C20["required_bond_amount_cents"],
        effective_date="2026-08-01",
        expiration_date="2027-08-01",
    )
    FX.verify_coverage(api, bond["id"])
    consumer_one = FX.register_consumer(
        api, full_name="Cass Owner", contact_email="cass@home.test"
    )
    consumer_two = FX.register_consumer(
        api, full_name="Dev Owner", contact_email="dev@home.test"
    )
    FX.set_clock(api, "2026-09-01T00:00:00Z")
    _cb, _ib, citation_bonded = FX.substantiated_citation(
        api,
        bonded,
        consumer_one["id"],
        severity=Severity.MINOR,
        violation_code="B-7031",
        correction_due_date="2026-10-15",
    )
    _cr, _ir, citation_bare = FX.substantiated_citation(
        api,
        bare,
        consumer_two["id"],
        severity=Severity.MINOR,
        violation_code="B-7031",
        correction_due_date="2026-10-15",
    )
    hearing_bonded = FX.appealed_citation_with_hearing(
        api,
        citation_bonded["id"],
        bonded.licensee_id,
        HEARING_START,
        HEARING_END,
        HEARING_OFFICER_USER_ID,
    )
    hearing_bare = FX.appealed_citation_with_hearing(
        api,
        citation_bare["id"],
        bare.licensee_id,
        HEARING_START,
        HEARING_END,
        SECOND_HEARING_OFFICER_USER_ID,
    )
    FX.set_clock(api, HEARING_START)
    return {
        "bonded": (bonded, citation_bonded, hearing_bonded),
        "bare": (bare, citation_bare, hearing_bare),
    }


def test_01_a_conditional_licence_scores_two_points_and_draws_a_reprimand(api):
    """One point for the minor violation and one for the conditional posture.

    PRD: "The licence's `compliance_posture` contributes nothing when `COMPLIANT`,
    one point when `CONDITIONAL`, and two points when `NON_COMPLIANT` — and
    contributes nothing at all when the subject is unlicensed and there is no
    licence to read."

    Design: Difficulty/boundary_precision_check/sanction_ladder_one_point_apart_gives_reprimand_versus_probation
    """
    world = _two_minor_appeals_awaiting_decision(api)
    bonded, citation, hearing = world["bonded"]

    decided = FX.decide_hearing(
        api,
        hearing["id"],
        HearingDecision.AFFIRM,
        HEARING_OFFICER_USER_ID,
        findings_summary="Permit violation proven",
    )

    assert_fields(
        decided,
        {
            "sanction_points": 2,
            "sanction_tier": SanctionTier.LETTER_OF_REPRIMAND,
        },
    )
    assert_fields(
        FX.read_license(api, bonded.license_id),
        {
            "status": LicenseStatus.ACTIVE,
            "compliance_posture": CompliancePosture.CONDITIONAL,
            "suspension_reason": None,
        },
    )
    assert_fields(
        validate_success(api.get_citation(citation["id"], LICENSING_ANALYST_HEADERS)),
        {"status": CitationStatus.AFFIRMED, "civil_penalty_cents": 62500},
    )


def test_02_a_non_compliant_licence_scores_three_points_and_lands_on_probation(api):
    """The second posture point crosses the rung boundary into probation.

    PRD: "The total is stamped as `sanction_points`, and the `sanction_tier` is then
    read off the ladder: `LETTER_OF_REPRIMAND` at two points or fewer, `PROBATION`
    from three through five, `SUSPENSION_30` from six through eight, `SUSPENSION_90`
    from nine through eleven, and `REVOCATION` at twelve points or more."

    Design: Difficulty/boundary_precision_check/sanction_ladder_one_point_apart_gives_reprimand_versus_probation
    """
    world = _two_minor_appeals_awaiting_decision(api)
    bare, citation, hearing = world["bare"]

    decided = FX.decide_hearing(
        api,
        hearing["id"],
        HearingDecision.AFFIRM,
        SECOND_HEARING_OFFICER_USER_ID,
        findings_summary="Permit violation proven",
    )

    assert_fields(
        decided, {"sanction_points": 3, "sanction_tier": SanctionTier.PROBATION}
    )
    assert_fields(
        FX.read_license(api, bare.license_id),
        {
            "status": LicenseStatus.ACTIVE,
            "compliance_posture": CompliancePosture.NON_COMPLIANT,
            "suspension_until": None,
        },
    )
    assert_fields(
        validate_success(api.get_citation(citation["id"], LICENSING_ANALYST_HEADERS)),
        {"status": CitationStatus.AFFIRMED, "civil_penalty_cents": 62500},
    )


def test_03_the_single_point_gap_comes_from_posture_alone(api):
    """Identical citations, identical penalties, adjacent rungs one point apart.

    PRD: "**The posture is read as it stood immediately before this decision's own
    cascades**, so the penalty this very decision affirms can never feed back into
    its own sanction tier."

    Design: Difficulty/boundary_precision_check/sanction_ladder_one_point_apart_gives_reprimand_versus_probation
    """
    world = _two_minor_appeals_awaiting_decision(api)
    _bonded, citation_bonded, hearing_bonded = world["bonded"]
    _bare, citation_bare, hearing_bare = world["bare"]

    reprimanded = FX.decide_hearing(
        api,
        hearing_bonded["id"],
        HearingDecision.AFFIRM,
        HEARING_OFFICER_USER_ID,
        findings_summary="Permit violation proven",
    )
    on_probation = FX.decide_hearing(
        api,
        hearing_bare["id"],
        HearingDecision.AFFIRM,
        SECOND_HEARING_OFFICER_USER_ID,
        findings_summary="Permit violation proven",
    )

    assert on_probation["sanction_points"] - reprimanded["sanction_points"] == 1, (
        "the two gradings must sit exactly one point apart"
    )
    priced_bonded = validate_success(
        api.get_citation(citation_bonded["id"], LICENSING_ANALYST_HEADERS)
    )
    priced_bare = validate_success(
        api.get_citation(citation_bare["id"], LICENSING_ANALYST_HEADERS)
    )
    assert (
        priced_bonded["civil_penalty_cents"] == priced_bare["civil_penalty_cents"]
    ), "the money must be identical so only the points differ"


def _disciplinarily_suspended_licence(api):
    """A tier-three fire-protection licence suspended by an affirmed egregious citation."""
    FX.set_clock(api, K.DEFAULT_CLOCK_UTC)
    classification = FX.create_c30_classification(api)
    ctx = FX.mint_active_license(
        api,
        classification,
        legal_name="Riser Fire LLC",
        contact_email="ops@riser.test",
        full_name="Rhea Riser",
    )
    consumer = FX.register_consumer(
        api, full_name="Sal Sprinkler", contact_email="sal@home.test"
    )
    FX.set_clock(api, "2026-08-10T00:00:00Z")
    _complaint, _investigation, citation = FX.substantiated_citation(
        api,
        ctx,
        consumer["id"],
        severity=Severity.EGREGIOUS,
        violation_code="B-7160",
        correction_due_date="2026-09-30",
        contract_date="2026-08-02",
        work_completed_on="2026-08-05",
    )
    hearing = FX.appealed_citation_with_hearing(
        api,
        citation["id"],
        ctx.licensee_id,
        "2026-08-20T09:00:00Z",
        "2026-08-20T11:00:00Z",
    )
    FX.set_clock(api, "2026-08-20T09:00:00Z")
    decided = FX.decide_hearing(
        api,
        hearing["id"],
        HearingDecision.AFFIRM,
        HEARING_OFFICER_USER_ID,
        findings_summary="Standpipe left unpressurised in an occupied tower",
    )
    assert_fields(
        decided,
        {"sanction_points": 8, "sanction_tier": SanctionTier.SUSPENSION_30},
    )
    FX.set_clock(api, "2026-09-20T00:00:00Z")
    return ctx, citation


def _live_bond_for(api, ctx):
    """Files and verifies a conforming bond whose period contains the clock date."""
    bond = FX.file_coverage(
        api,
        ctx.license_id,
        coverage_type=CoverageType.BOND,
        carrier_name="Surety Three",
        policy_number="BND-3001",
        amount_cents=K.C30["required_bond_amount_cents"],
        effective_date="2026-09-01",
        expiration_date="2027-09-01",
    )
    return FX.verify_coverage(api, bond["id"])


def test_04_reinstatement_reports_the_missing_bond_before_anything_else(api):
    """The first gate reads the coverage neighbour, not the money or the classroom.

    PRD: "First, live bond coverage: a coverage record with `coverage_type` of
    `BOND`, `status` of `VERIFIED`, and a period containing the clock date must
    exist, or the request draws `ERR_BOND_COVERAGE_MISSING`."

    Design: Difficulty/cross_entity_state_dependency/reinstatement_gated_on_bond_then_penalty_then_ce_states_in_priority_order
    """
    ctx, _citation = _disciplinarily_suspended_licence(api)

    validate_error(
        api.reinstate_license(ctx.license_id, LICENSING_ANALYST_HEADERS),
        ApiErrorId.BOND_COVERAGE_MISSING,
    )

    assert_fields(
        FX.read_license(api, ctx.license_id),
        {
            "status": LicenseStatus.SUSPENDED,
            "suspension_reason": SuspensionReason.DISCIPLINARY,
            "suspension_until": "2026-09-19",
        },
    )


def test_05_with_the_bond_live_the_same_request_reports_the_unpaid_penalty(api):
    """Repairing the coverage neighbour advances the chain to the money gate.

    PRD: "Second, outstanding obligations: every citation on the licence whose
    `status` is `FINAL`, `AFFIRMED` or `MODIFIED` must be fully paid — the sum of
    `civil_penalty_cents` less `penalty_paid_cents` across them must come to zero"

    Design: Difficulty/cross_entity_state_dependency/reinstatement_gated_on_bond_then_penalty_then_ce_states_in_priority_order
    """
    ctx, citation = _disciplinarily_suspended_licence(api)
    _live_bond_for(api, ctx)

    validate_error(
        api.reinstate_license(ctx.license_id, LICENSING_ANALYST_HEADERS),
        ApiErrorId.OUTSTANDING_OBLIGATIONS,
    )

    assert_fields(
        validate_success(api.get_citation(citation["id"], LICENSING_ANALYST_HEADERS)),
        {
            "status": CitationStatus.AFFIRMED,
            "civil_penalty_cents": 1125000,
            "penalty_paid_cents": 0,
        },
    )
    assert_fields(
        FX.read_license(api, ctx.license_id), {"status": LicenseStatus.SUSPENDED}
    )


def test_06_with_the_penalty_paid_the_same_request_reports_the_education_shortfall(api):
    """Only after the money clears does the fourth gate become the reported one.

    PRD: "Fourth, continuing education: **reinstatement demands the
    classification's full `required_ce_hours` with no grace band whatsoever** — the
    four-hour indulgence renewal offers does not exist here — and a shortfall draws
    `ERR_CE_HOURS_INSUFFICIENT`."

    Design: Difficulty/cross_entity_state_dependency/reinstatement_gated_on_bond_then_penalty_then_ce_states_in_priority_order
    """
    ctx, citation = _disciplinarily_suspended_licence(api)
    _live_bond_for(api, ctx)
    satisfied = validate_success(
        api.comply_with_citation(
            citation["id"],
            F.comply_payload(1125000, "2026-09-18"),
            ctx.licensee_headers,
        )
    )
    assert_fields(
        satisfied,
        {
            "status": CitationStatus.SATISFIED,
            "penalty_paid_cents": 1125000,
        },
    )

    validate_error(
        api.reinstate_license(ctx.license_id, LICENSING_ANALYST_HEADERS),
        ApiErrorId.CE_HOURS_INSUFFICIENT,
    )

    assert_fields(
        FX.read_license(api, ctx.license_id), {"status": LicenseStatus.SUSPENDED}
    )


def test_07_the_repaired_licence_reinstates_and_revives_its_designation(api):
    """The last neighbour repaired, the unchanged request finally succeeds.

    PRD: "A successful reinstatement moves the licence `SUSPENDED → ACTIVE`, clears
    both `suspension_reason` and `suspension_until` to null, resets
    `ce_hours_completed` to zero, returns every designation on the licence sitting
    in `SUSPENDED_BY_LICENSE` to `ACTIVE` — each such return raising that
    qualifier's `active_qualification_count` by one — and recomputes the licence's
    `compliance_posture`."

    Design: Difficulty/cross_entity_state_dependency/reinstatement_gated_on_bond_then_penalty_then_ce_states_in_priority_order
    """
    ctx, citation = _disciplinarily_suspended_licence(api)
    _live_bond_for(api, ctx)
    validate_success(
        api.comply_with_citation(
            citation["id"],
            F.comply_payload(1125000, "2026-09-18"),
            ctx.licensee_headers,
        )
    )
    FX.bank_ce_hours(api, ctx, K.C30["required_ce_hours"], "2026-09-15")

    reinstated = validate_success(
        api.reinstate_license(ctx.license_id, LICENSING_ANALYST_HEADERS)
    )

    assert_fields(
        reinstated,
        {
            "status": LicenseStatus.ACTIVE,
            "ce_hours_completed": 0,
            "suspension_reason": None,
            "suspension_until": None,
            "compliance_posture": CompliancePosture.CONDITIONAL,
        },
    )
    assignment = FX.find_assignment_for_license(api, ctx.license_id)
    assert_fields(assignment, {"status": "ACTIVE"})
    assert_qualification_count(
        validate_success(
            api.get_qualifying_individual(
                ctx.individual_id, LICENSING_ANALYST_HEADERS
            )
        ),
        1,
    )
