"""One error in the catalogue that no other scenario reaches: the terminal-state refusal
raised when a revoked certificate is offered for suspension.
"""

from test_helpers import (
    ApiErrorId,
    GlutenContainingOperations,
    IngredientSpec,
    RiskClass,
    make_decision_maker_headers,
    read_applicant,
    read_certificate,
    revoke_certificate,
    setup_issued_certificate,
    validate_error,
)

CLOCK_START = "2026-08-01T00:00:00Z"
DOC_EXPIRES = "2028-07-01T00:00:00Z"
AUDIT_OPENS = "2026-08-05T09:00:00Z"
AUDIT_CLOSES = "2026-08-05T17:00:00Z"
ISSUE_DAY = "2026-08-06T00:00:00Z"

CLEAN_SITE = {
    "site_name": "Plant 9",
    "shared_equipment_present": False,
    "gluten_containing_operations": GlutenContainingOperations.NONE,
}
ONE_CLEAN_LINE = (
    IngredientSpec(
        name="Brown Rice Flour",
        risk_class=RiskClass.INHERENTLY_GF,
        inclusion_pct=55,
        doc_expires_on=DOC_EXPIRES,
    ),
)


def test_a_revoked_certificate_can_no_longer_be_suspended(api):
    """Revocation for an unresolved nonconformance is not refund-eligible and does not
    drive the posture band, which leaves the terminal state as the only reason a later
    suspension is refused.

    PRD: "**Suspension.** A `CertificationDecisionMaker` may suspend an `ISSUED`
    certificate directly, supplying a `suspension_reason` from `FAILED_UNANNOUNCED_TEST`,
    `CRITICAL_NONCONFORMANCE`, `SURVEILLANCE_OVERDUE`, `INGREDIENT_BLOCKED`,
    `SUBSTANTIATED_COMPLAINT` and `CHANGE_REQUIRES_RECERT`; a certificate that is not
    `ISSUED`, or that is `REVOKED` or `EXPIRED`, is refused with
    `ERR_CERTIFICATE_TERMINAL`."
    PRD: "The applicant's counters are then adjusted according to where the certificate
    came from: revoking an `ISSUED` certificate decreases `active_certified_product_count`,
    whereas revoking a `SUSPENDED` one — whose active count was already decreased at
    suspension — decreases `suspended_certificate_count` instead; in both cases
    `revoked_certificate_count` increases by 1 and the posture fields are recomputed,
    applying the override that forces `compliance_posture` to `SUSPENDED` when the reason
    was `FRAUD` or `REPEAT_FAILURE`."

    Design: Corner/errors/suspending_a_revoked_certificate_is_rejected_as_terminal
    """
    context = setup_issued_certificate(
        api,
        clock=CLOCK_START,
        sanitation_validated_on=CLOCK_START,
        swab_ppm=2.0,
        facility_overrides=dict(CLEAN_SITE),
        ingredients=ONE_CLEAN_LINE,
        product_overrides={"name": "Rice Sandwich Loaf", "sku": "RSL-001"},
        onsite_start_at=AUDIT_OPENS,
        onsite_end_at=AUDIT_CLOSES,
        audit_start_clock=AUDIT_OPENS,
        audit_close_clock=AUDIT_CLOSES,
        issue_clock=ISSUE_DAY,
    )
    revoked = revoke_certificate(
        api,
        context.certificate_id,
        revocation_reason="UNRESOLVED_NONCONFORMANCE",
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["revoked_on"] == ISSUE_DAY
    assert revoked["fee_refunded"] is False

    response = api.suspend_certificate(
        context.certificate_id,
        make_decision_maker_headers("dm-1"),
        suspension_reason="CRITICAL_NONCONFORMANCE",
    )
    validate_error(response, ApiErrorId.CERTIFICATE_TERMINAL, 409)

    row = read_certificate(api, context.certificate_id)
    assert row["status"] == "REVOKED"
    assert row["suspension_count"] == 0
    assert row["suspension_reason"] is None
    assert row["revocation_reason"] == "UNRESOLVED_NONCONFORMANCE"

    applicant = read_applicant(api, context.applicant_id)
    assert applicant["revoked_certificate_count"] == 1
    assert applicant["active_certified_product_count"] == 0
    assert applicant["suspended_certificate_count"] == 0
    assert applicant["compliance_posture"] == "GOOD_STANDING"
