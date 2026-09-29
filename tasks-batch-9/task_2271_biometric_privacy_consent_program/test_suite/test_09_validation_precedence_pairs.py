"""Which rule reports first when two independent rules are violated at once.

Every pair here is decided by the numbered precedence of the validation order,
and each pair is checked together with the control that shows the lower-priority
rule really would have fired on its own.
"""

from test_helpers import (
    COMPLIANCE_APPROVER_ALT,
    DUAL_HAT_AS_COMPLIANCE_APPROVER,
    DUAL_HAT_AS_PRIVACY_OFFICER,
    HR_ADMIN,
    PRIVACY_OFFICER,
    ApiErrorId,
    assert_cents,
    assert_is_null,
    assert_pagination,
    assert_program_state,
    baseline_with_active_asset,
    consent_payload,
    create_asset,
    create_consent,
    create_data_subject,
    create_published_notice,
    create_vendor,
    create_vendor_contract,
    draft_exposure_assessment,
    read_asset,
    read_assessment,
    read_program,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

RISKY_LENS = {
    "name": "RiskyLens Vision",
    "sells_biometric_data": True,
    "subprocessor_count": 1,
    "deletion_sla_days": 30,
    "subprocessor_disclosure_complete": False,
}


def _second_point_operated_by_a_risky_processor(api, gate_the_first_point: bool):
    ctx = baseline_with_active_asset(api, activation_clock=None)
    if gate_the_first_point:
        validate_success(api.transition_asset(ctx["asset_id"], {"to_status": "GATED"}, PRIVACY_OFFICER))
    vendor = create_vendor(api, ctx["program_id"], attestation_status="REQUESTED", **RISKY_LENS)
    assert vendor["risk_score"] == 75, "20 base + 30 sale + 5 subprocessor + 10 requested + 10 disclosure"
    create_vendor_contract(api, vendor["id"], target_status="APPROVED", indemnity_cap_cents=1000000)
    second = create_asset(
        api,
        ctx["program_id"],
        ctx["jurisdiction_id"],
        target_status="CLASSIFIED",
        vendor_id=vendor["id"],
        template_storage_location="tk-vault-02",
    )
    ctx["second_asset_id"] = second["id"]
    return ctx


def test_a_restricted_posture_is_reported_instead_of_the_vendor_risk_gate(api):
    """Posture is checked before the regulatory prerequisites.

    PRD §2.5: "The practical consequence is worth stating plainly: a frozen
    program surfaces as `ERR_PROGRAM_POSTURE_BLOCKED` rather than as the
    missing-policy or missing-notice error that would also have applied, because
    posture is checked at step 9 and regulatory prerequisites at step 10."

    The program is `RESTRICTED` because a point is gated, and the point being
    activated is operated by a processor scoring 75 risk points, so both the
    posture gate and the risk gate are violated; the posture gate reports.

    Design: Difficulty/priority_pair_validation_conflict/posture_block_priority_9_outranks_vendor_risk_gate_priority_10
    """
    ctx = _second_point_operated_by_a_risky_processor(api, gate_the_first_point=True)
    assert_program_state(read_program(api, ctx["program_id"]), posture="RESTRICTED", gated_asset_count=1)

    refused = api.transition_asset(ctx["second_asset_id"], {"to_status": "ACTIVE"}, PRIVACY_OFFICER)

    validate_error(refused, ApiErrorId.PROGRAM_POSTURE_BLOCKED)

    unchanged = read_asset(api, ctx["second_asset_id"])
    assert unchanged["status"] == "CLASSIFIED"
    assert_is_null(unchanged["pinned_policy_id"], "pinned_policy_id on a refused activation")
    assert_is_null(unchanged["collection_started_at"], "collection_started_at on a refused activation")


def test_the_vendor_risk_gate_reports_once_the_posture_no_longer_blocks(api):
    """With posture open, the same activation fails on the risk gate.

    PRD §3.5: "If the point names an operating vendor, that vendor's `risk_score`
    must be at most 70, else `ERR_VENDOR_RISK_TOO_HIGH`; and that vendor must have
    a contract whose status is `EXECUTED` and whose `compliance_score` is at least
    82.50, else `ERR_CONTRACT_SCORE_BELOW_FLOOR`."

    The risk gate is a step 10 regulatory prerequisite while the contract-score
    floor is a step 12 threshold constraint, so the risk gate reports first.

    Design: Difficulty/priority_pair_validation_conflict/posture_block_priority_9_outranks_vendor_risk_gate_priority_10
    """
    ctx = _second_point_operated_by_a_risky_processor(api, gate_the_first_point=False)
    assert_program_state(read_program(api, ctx["program_id"]), posture="OPEN", gated_asset_count=0)

    refused = api.transition_asset(ctx["second_asset_id"], {"to_status": "ACTIVE"}, PRIVACY_OFFICER)

    validate_error(refused, ApiErrorId.VENDOR_RISK_TOO_HIGH)
    assert read_asset(api, ctx["second_asset_id"])["status"] == "CLASSIFIED"


def _employee_point_with_a_customer_subject(api):
    ctx = baseline_with_active_asset(api, activation_clock=None)
    create_published_notice(
        api, ctx["program_id"], ctx["jurisdiction_id"], ctx["policy_id"], audience="CUSTOMER"
    )
    subject = create_data_subject(
        api,
        ctx["program_id"],
        ctx["jurisdiction_id"],
        "CUST-0001",
        subject_type="CUSTOMER",
    )
    ctx["subject_id"] = subject["id"]
    return ctx


def test_the_notice_lead_time_is_reported_instead_of_the_subject_class_mismatch(api):
    """A time-window rule outranks cross-entity coherence.

    PRD §3.6: "The current logical clock must be at or after the covering
    published packet's `consent_eligible_from`. Soliciting inside the statutory
    lead time is rejected with `ERR_NOTICE_LEAD_NOT_MET`."

    Illinois imposes a 14-day lead time, so at 2026-08-01 the packet published
    that morning is not yet usable; the shopper being enrolled at a timekeeping
    terminal is also wrong, but that is a step 13 rule against the lead time's
    step 11.

    Design: Difficulty/priority_pair_validation_conflict/notice_lead_priority_11_outranks_subject_class_mismatch_priority_13
    """
    ctx = _employee_point_with_a_customer_subject(api)

    refused = api.create_consent_record(consent_payload(ctx["subject_id"], ctx["asset_id"]), HR_ADMIN)

    validate_error(refused, ApiErrorId.NOTICE_LEAD_NOT_MET)

    _rows, meta = validate_paginated(api.list_consent_records(HR_ADMIN, {"asset_id": ctx["asset_id"]}))
    assert_pagination(meta, total_count=0, has_more=False, limit=10, offset=0)


def test_the_subject_class_mismatch_reports_once_the_lead_time_has_elapsed(api):
    """After the cooling-off boundary, the population rule reports.

    PRD §3.6: "and the subject's `subject_type` must equal the point's
    `subject_class`, else `ERR_SUBJECT_CLASS_MISMATCH`. An employee may not be
    enrolled at a customer-facing lane, and a shopper may not be enrolled at a
    timekeeping terminal."

    Design: Difficulty/priority_pair_validation_conflict/notice_lead_priority_11_outranks_subject_class_mismatch_priority_13
    """
    ctx = _employee_point_with_a_customer_subject(api)
    set_clock(api, "2026-08-15T00:00:00Z")

    refused = api.create_consent_record(consent_payload(ctx["subject_id"], ctx["asset_id"]), HR_ADMIN)

    validate_error(refused, ApiErrorId.SUBJECT_CLASS_MISMATCH)

    _rows, meta = validate_paginated(api.list_consent_records(HR_ADMIN, {"asset_id": ctx["asset_id"]}))
    assert_pagination(meta, total_count=0, has_more=False, limit=10, offset=0)


def _draft_assessment_over_the_ceiling(api):
    ctx = baseline_with_active_asset(
        api,
        activation_clock="2026-08-15T00:00:00Z",
        program_overrides={"exposure_ceiling_cents": 100000},
    )
    for external_ref in ("EMP-0001", "EMP-0002"):
        subject = create_data_subject(api, ctx["program_id"], ctx["jurisdiction_id"], external_ref)
        create_consent(api, subject["id"], ctx["asset_id"])
    assessment = draft_exposure_assessment(api, ctx, creator_headers=DUAL_HAT_AS_PRIVACY_OFFICER)
    assert_cents(assessment["exposure_cents"], 250000, "exposure_cents")
    ctx["assessment_id"] = assessment["id"]
    return ctx


def test_separation_of_duties_is_reported_instead_of_the_exposure_ceiling(api):
    """The duty-separation check runs long before the fiscal ceiling.

    PRD §2.5: "Equally, a separation-of-duties violation is reported even when the
    target row is in the wrong status for the requested move, because step 7
    precedes step 8."

    The estimate of 250,000 cents cannot fit under the program's 100,000-cent
    ceiling, but the approver finalizing it is the same user who drafted it, and
    duty separation is step 7 against the ceiling's step 14.

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_priority_7_outranks_exposure_cap_priority_14
    """
    ctx = _draft_assessment_over_the_ceiling(api)

    refused = api.transition_exposure_assessment(
        ctx["assessment_id"], {"to_status": "FINAL"}, DUAL_HAT_AS_COMPLIANCE_APPROVER
    )

    validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES)

    assessment = read_assessment(api, ctx["assessment_id"])
    assert assessment["status"] == "DRAFT"
    assert_is_null(assessment["finalized_by_user_id"], "finalized_by_user_id on a refused finalization")
    assert_program_state(read_program(api, ctx["program_id"]), pra_exposure_cents=0)


def test_the_exposure_ceiling_reports_when_an_independent_approver_finalizes(api):
    """A second pair of hands reaches the fiscal ceiling instead.

    PRD §3.9: "and the program's existing `pra_exposure_cents` plus this
    assessment's `exposure_cents` must not exceed `exposure_ceiling_cents`, else
    `ERR_EXPOSURE_CAP_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_priority_7_outranks_exposure_cap_priority_14
    """
    ctx = _draft_assessment_over_the_ceiling(api)

    refused = api.transition_exposure_assessment(
        ctx["assessment_id"], {"to_status": "FINAL"}, COMPLIANCE_APPROVER_ALT
    )

    validate_error(refused, ApiErrorId.EXPOSURE_CAP_EXCEEDED)

    assessment = read_assessment(api, ctx["assessment_id"])
    assert assessment["status"] == "DRAFT"
    assert_program_state(read_program(api, ctx["program_id"]), pra_exposure_cents=0)
