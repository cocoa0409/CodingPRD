"""Exposure assessment review axis, signature fan-out, OCC on the group, and
the APF-adjusted class (PRD §2.7, §2.9, §3.6, §3.7, §3.9)."""
from test_helpers import (
    ApiErrorId,
    assert_decimal,
    assert_instant_equals,
    create_assessment_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS, make_cih_headers

IH = TEST_USERS["ih_headers"]
CIH = TEST_USERS["cih_headers"]
SSM = TEST_USERS["ssm_headers"]


def test_assessment_review_loop_preserves_class(api):
    """PRD §3.6: "The review axis then runs its course, cycling independently
    of the frozen classification. Submitting the assessment moves it `DRAFT →
    UNDER_REVIEW` (from any other status, `ERR_ASSESSMENT_INVALID_STATE`). A
    `CIHDirector` may return it `UNDER_REVIEW → DRAFT` for rework — the loop
    may repeat indefinitely, and the computed `exposure_class` does not change
    across it — or sign it, moving `UNDER_REVIEW → SIGNED`."

    Masses 10/12/40 ug classify UNCERTAIN; the reject loop must not move it.

    Design: Difficulty/non_linear_state_machine/assessment_parallel_review_and_class_axes
    """
    ctx = fx.setup_draft_assessment(masses=(10, 12, 40), member_count=3)
    asm = ctx.assessment
    assert asm["review_status"] == "DRAFT"
    assert asm["exposure_class"] == "UNCERTAIN"

    asm = fx.submit_review(asm["id"])
    assert asm["review_status"] == "UNDER_REVIEW"

    asm = fx.reject_review(asm["id"])
    assert asm["review_status"] == "DRAFT"
    assert asm["exposure_class"] == "UNCERTAIN", (
        "the review loop never touches the classification axis"
    )

    fx.submit_review(asm["id"])
    asm = fx.sign_assessment(asm["id"])
    assert asm["review_status"] == "SIGNED"
    assert asm["exposure_class"] == "UNCERTAIN"
    assert_decimal(asm["ucl95"], 0.0627)
    assert_decimal(asm["lcl95"], 0.0049)


def test_assessment_sign_sets_regulatory_state(api):
    """PRD §3.6: "Second, every regulatory consequence keys off that raw
    class: `signed_at` and `signed_by_user_id` are recorded; `retention_until`
    is set to the signed calendar date advanced by the site's
    `retention_years` whole calendar years, preserving month and day;
    `is_current` becomes true; the group's `current_class` is set to the
    assessment's `exposure_class`; and the group's `next_sample_due_date` is
    set to the signed date plus the re-sampling interval for the class — 30
    days for `ABOVE_PEL`, 90 days for `UNCERTAIN`, 180 days for
    `BELOW_PEL_MONITOR`, and 360 days for `BELOW_ACTION`."
    PRD §3.9: "an assessment signed 2026-08-10 under a thirty-year retention
    may be archived on 2056-08-10 itself, the gate being inclusive."

    Design: Difficulty/non_linear_state_machine/assessment_parallel_review_and_class_axes
    """
    ctx = fx.setup_signed_assessment(masses=(10, 12, 40), member_count=3)
    asm = ctx.assessment

    assert asm["review_status"] == "SIGNED"
    assert asm["is_current"] is True
    assert asm["signed_by_user_id"] == "u_cih_1"
    assert_instant_equals(asm["signed_at"], "2026-08-10T00:00:00Z")
    assert asm["retention_until"] == "2056-08-10"

    assert ctx.seg["current_class"] == "UNCERTAIN"
    assert ctx.seg["next_sample_due_date"] == "2026-11-08"
    assert ctx.plan["status"] == "LAB_COMPLETE", (
        "LAB_COMPLETE is terminal; signing does not move the plan"
    )


def test_occ_assessment_supersede_and_stale_version(api):
    """PRD §2.7: "Creating an exposure assessment (POST
    `/ih/exposure-assessments`) requires the request to carry
    `expected_seg_version`, holding the `version` of the parent
    similar-exposure group as the client last observed it. If the group's
    current `version` no longer matches — because, for example, another writer
    has since created an assessment against the same group (which legitimately
    supersedes the previously signed one) or signed one (which rewrites the
    group's `current_class` and `next_sample_due_date`) — the create is
    rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from
    assessing a group state it has not observed."
    PRD §3.6: "Creation copies the plan's group into the assessment's
    `seg_id`, captures the creator as `prepared_by_user_id`, and supersedes
    the group's prior signed-and-current assessment if one exists: that prior
    assessment moves `SIGNED → SUPERSEDED`, its `is_current` flips to false,
    its own `version` increments, and the new assessment records it in
    `supersedes_assessment_id` (null when there is none)."
    PRD §2.9: "An exposure assessment may not be signed by the operator who
    prepared it: if the signer's `X-User-ID` equals the assessment's
    `prepared_by_user_id`, the signature is rejected with
    `ERR_SOD_ASSESSMENT_SIGNER` (403)."
    PRD §3.6: "or sign it, moving `UNDER_REVIEW → SIGNED`."

    Design: Corner/cross_cutting_complexity_layers/occ_assessment_supersede_and_stale_version
    """
    ctx = fx.setup_lab_complete(masses=(12, 10, 8), member_count=3)
    seg_v1 = fx.get_seg(ctx.seg["id"])["version"]

    asm1 = validate_success(
        api.create_exposure_assessment(
            create_assessment_payload(ctx.plan["id"], seg_v1), IH
        ),
        201,
    )
    assert asm1["review_status"] == "DRAFT"
    assert asm1["is_current"] is False
    assert asm1["supersedes_assessment_id"] is None

    # Signing is defined only from UNDER_REVIEW.
    res = api.sign_assessment(asm1["id"], CIH)
    validate_error(res, ApiErrorId.ERR_ASSESSMENT_INVALID_STATE, 409)

    fx.submit_review(asm1["id"])

    # The preparer (u_ih_1) may not sign, even wearing the CIHDirector role.
    res = api.sign_assessment(asm1["id"], make_cih_headers("u_ih_1"))
    validate_error(res, ApiErrorId.ERR_SOD_ASSESSMENT_SIGNER, 403)

    asm1 = fx.sign_assessment(asm1["id"])
    assert asm1["review_status"] == "SIGNED"
    assert asm1["exposure_class"] == "BELOW_PEL_MONITOR"
    assert_decimal(asm1["geo_mean"], 0.0103)
    assert_decimal(asm1["ucl95"], 0.0144)
    assert_decimal(asm1["lcl95"], 0.0074)
    assert fx.get_plan(ctx.plan["id"])["status"] == "LAB_COMPLETE"

    # A fresh create against the current group version supersedes asm1.
    seg_v2 = fx.get_seg(ctx.seg["id"])["version"]
    asm2 = validate_success(
        api.create_exposure_assessment(
            create_assessment_payload(ctx.plan["id"], seg_v2), IH
        ),
        201,
    )
    assert asm2["supersedes_assessment_id"] == asm1["id"]
    superseded = fx.get_assessment(asm1["id"])
    assert superseded["review_status"] == "SUPERSEDED"
    assert superseded["is_current"] is False

    # Replaying the stale captured version is rejected (OCC runs before the
    # one-open-assessment constraint, per the pipeline order of §2.8).
    res = api.create_exposure_assessment(
        create_assessment_payload(ctx.plan["id"], seg_v2), IH
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, 412)

    # The unsigned successor changes nothing on the group yet.
    assert fx.get_seg(ctx.seg["id"])["current_class"] == "BELOW_PEL_MONITOR"


def test_assessment_open_constraint_and_control_state_errors(api):
    """PRD §3.6: "A group may host at most one assessment whose
    `review_status` is `DRAFT` or `UNDER_REVIEW`; opening a second is rejected
    with `ERR_ASSESSMENT_ALREADY_OPEN` (409)."
    PRD §3.7: "Rejection moves it `PROPOSED → REJECTED`, a terminal status."
    PRD §3.7: "Acting on a control in any status other than `PROPOSED` is
    rejected with `ERR_CONTROL_INVALID_STATE` (409)."
    PRD §3.7: "accepting a `PPE_RESPIRATOR` control requires every employee
    holding a current membership in the parent group to hold at least one fit
    test in `PASSED` status whose `expiry_date` is on or after the current
    date, and at least one medical clearance in `CLEARED` status whose
    `expiry_date` is on or after the current date; if even one member lacks
    either credential, acceptance is rejected with
    `ERR_FIT_TEST_MISSING_FOR_PPE` (422)."

    Design: Corner/state_machines/assessment_open_constraint_and_control_state_errors
    """
    ctx = fx.setup_draft_assessment(masses=(12, 10, 8), member_count=1)
    asm = ctx.assessment

    # A second open assessment for the same group is refused even with a
    # freshly observed group version (OCC passes; the constraint fires).
    fresh_version = fx.get_seg(ctx.seg["id"])["version"]
    res = api.create_exposure_assessment(
        create_assessment_payload(ctx.plan["id"], fresh_version), IH
    )
    validate_error(res, ApiErrorId.ERR_ASSESSMENT_ALREADY_OPEN, 409)

    # REJECTED is terminal for a control.
    control = fx.create_control(
        asm["id"], control_type="ENGINEERING", description="Booth",
        priority="MEDIUM",
    )
    fx.reject_control(control["id"])
    res = api.accept_control(control["id"], SSM)
    validate_error(res, ApiErrorId.ERR_CONTROL_INVALID_STATE, 409)

    # The group's single member holds no fit test or clearance at all.
    ppe = fx.create_control(
        asm["id"],
        control_type="PPE_RESPIRATOR",
        description="P100 half-mask",
        priority="HIGH",
        assigned_protection_factor=10,
    )
    res = api.accept_control(ppe["id"], SSM)
    validate_error(res, ApiErrorId.ERR_FIT_TEST_MISSING_FOR_PPE, 422)

    assert fx.get_assessment(asm["id"])["review_status"] == "DRAFT"


def _setup_accepted_ppe_assessment(api):
    """SEG with one fit-tested + cleared member; UNCERTAIN assessment
    (masses 10/12/40) carrying an ACCEPTED PPE control (APF 10), ready to
    sign."""
    ctx = fx.setup_site_seg(member_count=1)
    fx.qualify_member(ctx.employees[0]["id"])
    fx.drive_ctx_to_lab_complete(ctx, masses=(10, 12, 40))
    assert ctx.plan["status"] == "LAB_COMPLETE"
    asm = fx.create_assessment(ctx.plan["id"], ctx.seg["id"])
    control = fx.create_control(
        asm["id"],
        control_type="PPE_RESPIRATOR",
        description="Half-mask P100 until ventilation fixed",
        priority="HIGH",
        assigned_protection_factor=10,
    )
    fx.accept_control(control["id"])
    fx.submit_review(asm["id"])
    return ctx, asm, control


def test_apf_adjusted_class_computed_after_raw_consequences(api):
    """PRD §3.7: "After the raw class and all its regulatory consequences are
    fixed (§3.6), the system checks whether the assessment being signed
    carries at least one `PPE_RESPIRATOR` control in `ACCEPTED`,
    `IMPLEMENTED`, or `VERIFIED` status. If so, the unrounded `ucl95` and
    `lcl95` are each divided by that control's
    `assigned_protection_factor` — when several controls qualify, the one
    created most recently — each quotient rounded half up to four decimal
    places, and the same strict classification thresholds of §3.6 are applied
    to the adjusted pair to produce the assessment's `adjusted_class`."
    PRD §3.7: "The adjusted class is informational only: it never rewrites the
    group's `current_class`, its due date, or any notification."

    Raw UNCERTAIN (UCL 0.0627 > 0.05); dividing the unrounded limits by APF 10
    gives 0.0063 / 0.0005, which classifies BELOW_PEL_MONITOR.

    Design: Difficulty/combinatorial_formula/apf_adjusted_class_pinned_evaluation_order
    """
    ctx, asm, control = _setup_accepted_ppe_assessment(api)
    signed = fx.sign_assessment(asm["id"])

    assert signed["exposure_class"] == "UNCERTAIN"
    assert signed["adjusted_class"] == "BELOW_PEL_MONITOR"

    seg = fx.get_seg(ctx.seg["id"])
    assert seg["current_class"] == "UNCERTAIN", "raw class drives the group"
    assert seg["next_sample_due_date"] == "2026-11-08"

    assert fx.get_control(control["id"])["status"] == "ACCEPTED"
    assert fx.get_plan(ctx.plan["id"])["status"] == "LAB_COMPLETE"


def test_apf_adjusted_class_notification_fanout_uses_raw_class(api):
    """PRD §3.6: "The fan-out then creates one `PENDING` notification per
    current membership of the group, due fifteen working days after the signed
    date (§3.9)".
    PRD §3.9: "An assessment signed on Monday 2026-08-10 therefore produces
    notifications due Monday 2026-08-31."
    PRD §3.7: "The adjusted class is informational only: it never rewrites the
    group's `current_class`, its due date, or any notification."

    Design: Difficulty/combinatorial_formula/apf_adjusted_class_pinned_evaluation_order
    """
    ctx, asm, control = _setup_accepted_ppe_assessment(api)
    signed = fx.sign_assessment(asm["id"])
    assert signed["adjusted_class"] == "BELOW_PEL_MONITOR"
    assert signed["exposure_class"] == "UNCERTAIN"

    employee = ctx.employees[0]
    rows, meta = validate_paginated(
        api.list_notifications(IH, params={"employee_id": employee["id"]})
    )
    assert meta["total_count"] == 1
    note = rows[0]
    assert note["exposure_assessment_id"] == signed["id"]
    assert note["employee_id"] == employee["id"]
    assert note["status"] == "PENDING"
    assert note["due_date"] == "2026-08-31"
    assert note["sent_at"] is None
