"""Control recommendations: disposition gates, implementation side effects,
and the verification sampling loop (PRD §3.6, §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_decimal,
    assert_plan,
    validate_error,
    validate_paginated,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

IH = TEST_USERS["ih_headers"]
CIH = TEST_USERS["cih_headers"]
SSM = TEST_USERS["ssm_headers"]


def test_control_implement_requires_signed_assessment(api):
    """PRD §3.7: "Implementation moves `ACCEPTED → IMPLEMENTED` and requires
    the parent assessment to stand at `SIGNED`, else
    `ERR_ASSESSMENT_NOT_SIGNED` (409); acting from any status other than
    `ACCEPTED` is `ERR_CONTROL_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/control_implement_requires_signed_assessment
    """
    ctx = fx.setup_draft_assessment(masses=(12, 10, 8), member_count=3)
    fx.submit_review(ctx.assessment["id"])  # UNDER_REVIEW, not signed
    control = fx.create_control(
        ctx.assessment["id"], control_type="ENGINEERING",
        description="Downdraft booth", priority="HIGH",
    )
    fx.accept_control(control["id"])

    res = api.implement_control(control["id"], SSM)
    validate_error(res, ApiErrorId.ERR_ASSESSMENT_NOT_SIGNED, 409)

    control = fx.get_control(control["id"])
    assert control["status"] == "ACCEPTED"
    assert control["verification_plan_id"] is None


def test_control_implement_after_sign_succeeds(api):
    """PRD §3.7: "Implementation moves `ACCEPTED → IMPLEMENTED` and requires
    the parent assessment to stand at `SIGNED`, else
    `ERR_ASSESSMENT_NOT_SIGNED` (409)".
    PRD §3.7: "Implementation stamps `implemented_at` with the logical now and
    auto-creates a verification sampling plan for the same group".

    Design: Difficulty/cross_entity_state_dependency/control_implement_requires_signed_assessment
    """
    ctx = fx.setup_draft_assessment(masses=(12, 10, 8), member_count=3)
    fx.submit_review(ctx.assessment["id"])
    control = fx.create_control(
        ctx.assessment["id"], control_type="ENGINEERING",
        description="Downdraft booth", priority="HIGH",
    )
    fx.accept_control(control["id"])

    # Rejected while the parent is only UNDER_REVIEW...
    validate_error(
        api.implement_control(control["id"], SSM),
        ApiErrorId.ERR_ASSESSMENT_NOT_SIGNED,
    )

    # ...and accepted once the assessment is signed.
    fx.sign_assessment(ctx.assessment["id"])
    implemented = fx.implement_control(control["id"])
    assert implemented["status"] == "IMPLEMENTED"
    assert implemented["verification_plan_id"] is not None
    assert implemented["implemented_at"] is not None


def test_control_implement_spawns_verification_and_due_date(api):
    """PRD §3.7: "Implementation stamps `implemented_at` with the logical now
    and auto-creates a verification sampling plan for the same group:
    `purpose` `VERIFICATION`, a window opening the calendar day after the
    implementation date and closing thirty days after it, status `DRAFT`, the
    implementer's `X-User-ID` as its creator, and — per the flat rule of §3.3
    — a `required_sample_count` of 3. The new plan's identifier is recorded in
    the control's `verification_plan_id`. Implementation also pulls the
    group's `next_sample_due_date` forward: it becomes the earlier of its
    existing value and the date fourteen days after implementation; if no due
    date exists yet, the fourteen-day candidate wins."

    The UNCERTAIN signature set the due date to 2026-11-08; implementing at
    2026-08-17 pulls it to min(2026-11-08, 2026-08-31).

    Design: Difficulty/transitive_cascade/control_implement_spawns_verification_and_due_date
    """
    ctx = fx.setup_signed_assessment(masses=(10, 12, 40), member_count=3)
    assert ctx.seg["next_sample_due_date"] == "2026-11-08"

    control = fx.create_control(
        ctx.assessment["id"], control_type="ENGINEERING",
        description="Install downdraft booth", priority="HIGH",
    )
    fx.accept_control(control["id"])
    fx.set_clock("2026-08-17T00:00:00Z")

    implemented = fx.implement_control(control["id"])
    assert implemented["status"] == "IMPLEMENTED"
    vplan_id = implemented["verification_plan_id"]
    assert vplan_id is not None

    vplan = fx.get_plan(vplan_id)
    assert_plan(vplan)
    assert vplan["seg_id"] == ctx.seg["id"]
    assert vplan["purpose"] == "VERIFICATION"
    assert vplan["status"] == "DRAFT"
    assert vplan["required_sample_count"] == 3
    assert vplan["planned_start_date"] == "2026-08-18"
    assert vplan["planned_end_date"] == "2026-09-16"
    assert vplan["created_by_user_id"] == "u_ssm_1"

    seg = fx.get_seg(ctx.seg["id"])
    assert seg["next_sample_due_date"] == "2026-08-31"
    assert seg["current_class"] == "UNCERTAIN", "implement does not reclassify"


def test_uncertain_sign_does_not_auto_create_control(api):
    """PRD §3.6: "and — when the class is `ABOVE_PEL` — auto-drafts a control
    recommendation on the assessment being signed: an `ENGINEERING` control of
    `HIGH` priority, born `PROPOSED`, with `auto_created` true."
    PRD §3.7: "Manually drafted controls are born `PROPOSED` with
    `auto_created` false; the auto-drafted `ABOVE_PEL` control of §3.6 arrives
    with `auto_created` true."

    Design: Difficulty/transitive_cascade/control_implement_spawns_verification_and_due_date
    """
    ctx = fx.setup_signed_assessment(masses=(10, 12, 40), member_count=3)
    assert ctx.assessment["exposure_class"] == "UNCERTAIN"

    rows, meta = validate_paginated(
        api.list_controls(
            IH, params={"exposure_assessment_id": ctx.assessment["id"]}
        )
    )
    assert meta["total_count"] == 0, "auto-drafting is conditional on ABOVE_PEL"

    manual = fx.create_control(
        ctx.assessment["id"], control_type="ENGINEERING",
        description="Install downdraft booth", priority="HIGH",
    )
    assert manual["status"] == "PROPOSED"
    assert manual["auto_created"] is False

    rows, meta = validate_paginated(
        api.list_controls(
            IH, params={"exposure_assessment_id": ctx.assessment["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == manual["id"]


def test_control_verify_full_loop_clean(api):
    """PRD §3.6: "and — when the class is `ABOVE_PEL` — auto-drafts a control
    recommendation on the assessment being signed: an `ENGINEERING` control of
    `HIGH` priority, born `PROPOSED`, with `auto_created` true."
    PRD §3.7: "A `CIHDirector` verifies an `IMPLEMENTED` control — any other
    status is `ERR_CONTROL_INVALID_STATE` — and the verification succeeds only
    when the control's verification plan holds an assessment that is current
    (`is_current` true), `SIGNED`, and classified `BELOW_ACTION` or
    `BELOW_PEL_MONITOR`; anything short of that is rejected with
    `ERR_VERIFICATION_NOT_CLEAN` (409). Success moves the control `IMPLEMENTED
    → VERIFIED`, its terminal success status."
    PRD §3.6: "Creation copies the plan's group into the assessment's
    `seg_id`, captures the creator as `prepared_by_user_id`, and supersedes
    the group's prior signed-and-current assessment if one exists: that prior
    assessment moves `SIGNED → SUPERSEDED`, its `is_current` flips to false,
    its own `version` increments, and the new assessment records it in
    `supersedes_assessment_id` (null when there is none)."

    Masses 60/58/56 ug classify ABOVE_PEL (LCL 0.0571 > 0.05); the
    verification campaign (2/2/4 ug) classifies BELOW_PEL_MONITOR.

    Design: Corner/state_machines/control_verify_full_loop_clean
    """
    ctx = fx.setup_signed_assessment(masses=(60, 58, 56), member_count=3)
    asm1 = ctx.assessment
    assert asm1["exposure_class"] == "ABOVE_PEL"
    assert_decimal(asm1["ucl95"], 0.064)
    assert_decimal(asm1["lcl95"], 0.0571)
    assert asm1["retention_until"] == "2056-08-10"
    assert ctx.seg["current_class"] == "ABOVE_PEL"
    assert ctx.seg["next_sample_due_date"] == "2026-09-09"

    # Exactly one auto-drafted control appears at signature.
    rows, meta = validate_paginated(
        api.list_controls(IH, params={"exposure_assessment_id": asm1["id"]})
    )
    assert meta["total_count"] == 1
    control = rows[0]
    assert control["status"] == "PROPOSED"
    assert control["control_type"] == "ENGINEERING"
    assert control["priority"] == "HIGH"
    assert control["auto_created"] is True

    fx.accept_control(control["id"])
    fx.set_clock("2026-08-17T00:00:00Z")
    implemented = fx.implement_control(control["id"])
    vplan_id = implemented["verification_plan_id"]

    vplan = fx.get_plan(vplan_id)
    assert vplan["purpose"] == "VERIFICATION"
    assert vplan["required_sample_count"] == 3
    assert vplan["planned_start_date"] == "2026-08-18"
    assert vplan["planned_end_date"] == "2026-09-16"
    assert fx.get_seg(ctx.seg["id"])["next_sample_due_date"] == "2026-08-31"

    # The verification plan holds no signed assessment yet.
    res = api.verify_control(control["id"], CIH)
    validate_error(res, ApiErrorId.ERR_VERIFICATION_NOT_CLEAN, 409)

    # Drive the verification campaign to a clean signed assessment.
    fx.drive_plan_to_lab_complete(
        ctx,
        vplan,
        masses=(2, 2, 4),
        lod=1,
        loq=2,
        batch_window=("2026-08-24", "2026-08-28"),
        clock_at="2026-08-24T00:00:00Z",
    )
    assert ctx.plan["status"] == "LAB_COMPLETE"
    asm2 = fx.create_assessment(vplan_id, ctx.seg["id"])
    fx.submit_review(asm2["id"])
    asm2 = fx.sign_assessment(asm2["id"])
    assert asm2["exposure_class"] == "BELOW_PEL_MONITOR"
    assert_decimal(asm2["ucl95"], 0.0052)
    assert_decimal(asm2["lcl95"], 0.0013)
    assert asm2["is_current"] is True
    assert asm2["supersedes_assessment_id"] == asm1["id"]

    superseded = fx.get_assessment(asm1["id"])
    assert superseded["review_status"] == "SUPERSEDED"
    assert superseded["is_current"] is False

    seg = fx.get_seg(ctx.seg["id"])
    assert seg["current_class"] == "BELOW_PEL_MONITOR"
    assert seg["next_sample_due_date"] == "2027-02-20"

    verified = fx.verify_control(control["id"])
    assert verified["status"] == "VERIFIED"

    # VERIFIED is terminal.
    res = api.accept_control(control["id"], SSM)
    validate_error(res, ApiErrorId.ERR_CONTROL_INVALID_STATE, 409)
