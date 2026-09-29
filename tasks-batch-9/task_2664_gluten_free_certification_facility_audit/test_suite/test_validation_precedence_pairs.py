"""Requests that break two rules at once, where only the reported error_id proves
which rung of the fixed ladder was reached first.
"""

from test_helpers import (
    ApiErrorId,
    IngredientSpec,
    NcCategory,
    NcSeverity,
    NcSourceType,
    RiskClass,
    make_applicant_contact_headers,
    make_decision_maker_headers,
    raise_nonconformance,
    read_applicant,
    read_certificate,
    read_nonconformance,
    read_product,
    revoke_certificate,
    set_clock,
    setup_issued_certificate,
    validate_error,
)

SANITATION_DAY = "2026-08-03T00:00:00Z"
ISSUE_DAY = "2026-08-11T00:00:00Z"
PAST_DUE_DAY = "2026-09-15T00:00:00Z"

SOLE_LINE = IngredientSpec(
    name="Brown Rice Flour",
    risk_class=RiskClass.INHERENTLY_GF,
    inclusion_pct=40,
    doc_issued_on="2026-07-01T00:00:00Z",
    doc_expires_on="2028-07-01T00:00:00Z",
)


def _revoked_certificate_with_an_open_critical_finding(api):
    """A certificate that first suspends under an OPEN CRITICAL finding and is then
    revoked for that unresolved finding, so reinstatement breaks two rules at once.
    """
    context = setup_issued_certificate(
        api,
        clock=SANITATION_DAY,
        sanitation_validated_on=SANITATION_DAY,
        ingredients=(SOLE_LINE,),
        issue_clock=ISSUE_DAY,
    )
    finding = raise_nonconformance(
        api,
        context.applicant_id,
        source_type=NcSourceType.SURVEILLANCE_RUN,
        certificate_id=context.certificate_id,
        category=NcCategory.AIR_HANDLING,
        severity=NcSeverity.CRITICAL,
        description="Positive-pressure interlock on the GF room defeated during production.",
    )
    revoked = revoke_certificate(
        api, context.certificate_id, revocation_reason="UNRESOLVED_NONCONFORMANCE"
    )
    assert revoked["status"] == "REVOKED"
    return context, finding


def test_reinstating_a_revoked_certificate_reports_the_state_rung_not_the_finding(api):
    """Rule 13 sits above rule 21, so the answer is the 409 state refusal and never
    the 422 about the still-open critical finding.

    PRD: "The service therefore evaluates checks in one fixed ladder and returns the
    **first** failure it reaches, never a later one."
    PRD: "**Certificate suspended.** Reinstatement requires `status` of exactly
    `SUSPENDED`; every other value, including the terminal `REVOKED` and `EXPIRED`,
    fails with `ERR_CERTIFICATE_NOT_SUSPENDED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/reinstatement_not_suspended_409_beats_open_critical_nonconformance_422
    """
    context, _finding = _revoked_certificate_with_an_open_critical_finding(api)

    response = api.reinstate_certificate(
        context.certificate_id, make_decision_maker_headers("dm-1")
    )
    validate_error(response, ApiErrorId.CERTIFICATE_NOT_SUSPENDED, 409)
    assert response.json()["data"]["error_id"] != ApiErrorId.OPEN_CRITICAL_NONCONFORMANCE


def test_the_refused_reinstatement_leaves_the_certificate_and_finding_untouched(api):
    """The certificate keeps its revocation, its locked mark and its single earlier
    suspension, and the critical finding is still OPEN.

    PRD: "This rule deliberately does not cover reinstatement: a terminal
    certificate offered for reinstatement is judged by the next rule instead, so the
    two never both fire on one request."
    PRD: "Whenever a mutation changes a resource, that resource's `updated_at` is
    refreshed and its `version` increases by 1 — and the same is true of every
    *other* resource the mutation touches as a consequence."

    Design: Difficulty/priority_pair_validation_conflict/reinstatement_not_suspended_409_beats_open_critical_nonconformance_422
    """
    context, finding = _revoked_certificate_with_an_open_critical_finding(api)

    api.reinstate_certificate(context.certificate_id, make_decision_maker_headers("dm-1"))

    certificate = read_certificate(api, context.certificate_id)
    assert certificate["status"] == "REVOKED"
    assert certificate["revocation_reason"] == "UNRESOLVED_NONCONFORMANCE"
    assert certificate["mark_usage_locked"] is True
    assert certificate["fee_refunded"] is False
    assert certificate["suspension_count"] == 1

    row = read_nonconformance(api, finding["id"])
    assert row["status"] == "OPEN"
    assert row["severity"] == NcSeverity.CRITICAL
    assert read_product(api, context.product_id)["label_status"] == "FROZEN"


def test_a_revocation_that_is_not_fraud_leaves_the_posture_band_on_the_score(api):
    """With the certificate revoked rather than suspended the only posture term left
    is the critical finding's 25 points, giving 75 and WATCH.

    PRD: "After that band lookup, and independent of the score, one override
    applies: if at least one certificate of this applicant has `status` of `REVOKED`
    with a `revocation_reason` of `FRAUD` or `REPEAT_FAILURE`, `compliance_posture`
    becomes `SUSPENDED` regardless of how high the score is."

    Design: Difficulty/priority_pair_validation_conflict/reinstatement_not_suspended_409_beats_open_critical_nonconformance_422
    """
    context, _finding = _revoked_certificate_with_an_open_critical_finding(api)

    api.reinstate_certificate(context.certificate_id, make_decision_maker_headers("dm-1"))

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["active_certified_product_count"] == 0
    assert applicant["suspended_certificate_count"] == 0
    assert applicant["revoked_certificate_count"] == 1
    assert applicant["fee_balance_cents"] == 178800
    assert applicant["posture_score_cycle"] == 75
    assert applicant["compliance_posture"] == "WATCH"


def _overdue_finding_against_a_revoked_certificate(api):
    """A MAJOR finding whose certificate is revoked and whose corrective-action
    deadline has also passed, with no sweep run so the record is still OPEN.
    """
    context = setup_issued_certificate(
        api,
        clock=SANITATION_DAY,
        sanitation_validated_on=SANITATION_DAY,
        ingredients=(SOLE_LINE,),
        issue_clock=ISSUE_DAY,
    )
    finding = raise_nonconformance(
        api,
        context.applicant_id,
        source_type=NcSourceType.SURVEILLANCE_RUN,
        certificate_id=context.certificate_id,
        category=NcCategory.SANITATION,
        severity=NcSeverity.MAJOR,
        description="Master sanitation schedule not followed on the packaging line.",
    )
    assert finding["ca_due_on"] == "2026-09-10T00:00:00Z"
    revoke_certificate(
        api, context.certificate_id, revocation_reason="UNRESOLVED_NONCONFORMANCE"
    )
    set_clock(api, PAST_DUE_DAY)
    return context, finding


def test_the_referential_rung_wins_a_pair_of_rules_that_share_one_status(api):
    """Both candidate refusals are 422, so only the error_id distinguishes them: the
    terminal-certificate rung at 30 answers, not the overdue rung at 39.

    PRD: "**Corrective action against a live certificate.** When a nonconformance
    carries a `certificate_id`, that certificate's `status` is neither `REVOKED` nor
    `EXPIRED` at the moment a corrective-action plan is submitted — otherwise
    `ERR_CERTIFICATE_TERMINAL_NO_CA` (422)."
    PRD: "**Corrective action on time.** The logical clock is at or before the
    nonconformance's `ca_due_on` when a plan is submitted — otherwise
    `ERR_CORRECTIVE_ACTION_OVERDUE` (422)."

    Design: Difficulty/priority_pair_validation_conflict/ca_plan_terminal_certificate_422_beats_overdue_422
    """
    context, finding = _overdue_finding_against_a_revoked_certificate(api)

    response = api.submit_corrective_action_plan(
        finding["id"],
        make_applicant_contact_headers(context.applicant_id),
        expected_nonconformance_version=finding["version"],
        ca_plan_text="Reinstate the master sanitation schedule with shift-lead sign-off.",
    )
    validate_error(response, ApiErrorId.CERTIFICATE_TERMINAL_NO_CA, 422)
    assert response.json()["data"]["error_id"] != ApiErrorId.CORRECTIVE_ACTION_OVERDUE


def test_the_refused_plan_leaves_the_finding_at_its_original_version(api):
    """The record is untouched: no plan text, no revision, and the same version the
    request itself supplied.

    PRD: "Creation records `status` of `OPEN`, `raised_by_user_id` as the acting
    `X-User-ID`, `ca_revision_count` of 0, `ca_verified` of false, `ca_plan_text`
    null and `ca_decided_by_user_id`, `ca_rejection_reason` and `closed_on` null."

    Design: Difficulty/priority_pair_validation_conflict/ca_plan_terminal_certificate_422_beats_overdue_422
    """
    context, finding = _overdue_finding_against_a_revoked_certificate(api)

    api.submit_corrective_action_plan(
        finding["id"],
        make_applicant_contact_headers(context.applicant_id),
        expected_nonconformance_version=finding["version"],
        ca_plan_text="Reinstate the master sanitation schedule with shift-lead sign-off.",
    )

    row = read_nonconformance(api, finding["id"])
    assert row["status"] == "OPEN"
    assert row["ca_plan_text"] is None
    assert row["ca_revision_count"] == 0
    assert row["ca_due_on"] == "2026-09-10T00:00:00Z"
    assert row["version"] == finding["version"]

    assert read_certificate(api, context.certificate_id)["status"] == "REVOKED"

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["open_nc_penalty_points"] == 8
    assert applicant["posture_score_cycle"] == 92
