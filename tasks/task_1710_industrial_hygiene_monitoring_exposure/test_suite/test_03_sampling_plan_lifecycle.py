"""Sampling plan lifecycle: creation defaults, approval loop, OCC revision,
field completion gate, and collection windows (PRD §2.7, §2.8, §3.3, §3.4)."""
from test_helpers import (
    ApiErrorId,
    assert_plan,
    create_batch_payload,
    create_plan_payload,
    create_sample_payload,
    revise_plan_payload,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS, make_cih_headers

IH = TEST_USERS["ih_headers"]
TECH = TEST_USERS["tech_headers"]


def test_initial_states_on_create(api):
    """PRD §3.3: "The creator's `X-User-ID` is captured as
    `created_by_user_id`, the `approved_by_user_id` remains null until
    approval, and the plan is born in `DRAFT` status."
    PRD §3.4: "the calibration is born with `result` `PENDING`"
    PRD §3.4: "The collector's `X-User-ID` is captured as
    `collected_by_user_id`, and the sample is born in `COLLECTED` status."
    PRD §3.8: "the clearance is born `REQUESTED`, with `decided_at`,
    `decided_by_user_id`, and `expiry_date` all null."
    PRD §3.8: "The test is born `SCHEDULED`"
    PRD §3.5: "A new batch's `intake_count` is zero and its `contaminated`
    flag is false."

    Design: Corner/state_machines/initial_states_on_create
    """
    ctx = fx.setup_site_seg(member_count=1)
    employee = ctx.employees[0]

    clearance = fx.request_clearance(employee["id"])
    assert clearance["status"] == "REQUESTED"
    assert clearance["decided_at"] is None
    assert clearance["decided_by_user_id"] is None
    assert clearance["expiry_date"] is None

    fit_test = fx.schedule_fit_test(employee["id"], clearance["id"])
    assert fit_test["status"] == "SCHEDULED"
    assert fit_test["recorded_by_user_id"] is None

    plan = fx.create_plan(ctx.seg["id"])
    assert_plan(plan)
    assert plan["status"] == "DRAFT"
    assert plan["created_by_user_id"] == "u_ih_1"
    assert plan["approved_by_user_id"] is None
    fx.submit_plan(plan["id"])
    plan = fx.approve_plan(plan["id"])
    assert plan["status"] == "APPROVED"
    assert plan["approved_by_user_id"] == "u_cih_1"

    pump = fx.create_pump(ctx.site["id"], serial_number="P-001")
    calibration = fx.create_calibration(pump["id"])
    assert calibration["result"] == "PENDING"
    assert calibration["post_flow_lpm"] is None
    assert calibration["drift_pct"] is None
    assert calibration["linked_sample_id"] is None

    sample = fx.create_sample(
        plan["id"],
        employee_id=employee["id"],
        pump_id=pump["id"],
        pre_calibration_id=calibration["id"],
    )
    assert sample["status"] == "COLLECTED"
    assert sample["collected_by_user_id"] == "u_tech_1"

    batch = fx.create_batch(ctx.site["id"])
    assert batch["contaminated"] is False
    assert batch["intake_count"] == 0


def test_plan_submit_after_approve_rejected(api):
    """PRD §3.3: "Submitting the plan moves it `DRAFT → PENDING_APPROVAL`;
    submitting from any other status is rejected with
    `ERR_PLAN_INVALID_STATE`."

    Design: Corner/state_machines/plan_submit_after_approve_rejected
    """
    ctx = fx.setup_approved_plan(member_count=1)
    res = api.submit_plan(ctx.plan["id"], IH)
    validate_error(res, ApiErrorId.ERR_PLAN_INVALID_STATE, 409)
    assert fx.get_plan(ctx.plan["id"])["status"] == "APPROVED"


def test_plan_approve_sod_same_user_rejected(api):
    """PRD §2.9: "A sampling plan may not be approved by the operator who
    created it: if the approver's `X-User-ID` equals the plan's
    `created_by_user_id`, the approval is rejected with
    `ERR_SOD_PLAN_APPROVER` (403)."

    Design: Corner/state_machines/plan_approve_sod_same_user_rejected
    """
    ctx = fx.setup_site_seg(member_count=1)
    plan = fx.create_plan(ctx.seg["id"])
    fx.submit_plan(plan["id"])

    # The CIHDirector role is legitimate; the shared person is not.
    res = api.approve_plan(plan["id"], make_cih_headers("u_ih_1"))
    validate_error(res, ApiErrorId.ERR_SOD_PLAN_APPROVER, 403)

    plan = fx.get_plan(plan["id"])
    assert plan["status"] == "PENDING_APPROVAL"
    assert plan["approved_by_user_id"] is None


def test_occ_plan_revise_stale_version(api):
    """PRD §2.7: "Revising a draft sampling plan (PUT
    `/ih/sampling-plans/{id}`) likewise requires `expected_plan_version`
    carrying the client's last observed `version` of that plan; a mismatch
    with the plan's current `version` is rejected with `ERR_STALE_VERSION`
    (HTTP 412), so that one hygienist's revision cannot silently overwrite
    another's."
    PRD §3.3: "Revision is a `DRAFT`-only privilege: once the plan has moved
    on, the attempt is rejected as `ERR_PLAN_INVALID_STATE` (409)."
    PRD §2.8: "Fifth, optimistic concurrency: the `expected_seg_version` or
    `expected_plan_version` check of §2.7 runs here — after existence, before
    any state or business rule — and a mismatch yields `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/occ_plan_revise_stale_version
    """
    ctx = fx.setup_site_seg(member_count=1)
    plan = fx.create_plan(ctx.seg["id"])
    observed_version = plan["version"]

    revised = validate_success(
        api.revise_sampling_plan(
            plan["id"],
            revise_plan_payload(observed_version, planned_end_date="2026-08-21"),
            IH,
        ),
        200,
    )
    assert revised["version"] == observed_version + 1
    assert revised["planned_end_date"] == "2026-08-21"

    # Replaying the stale version is rejected; the stored row is untouched.
    stale = api.revise_sampling_plan(
        plan["id"],
        revise_plan_payload(observed_version, planned_end_date="2026-08-28"),
        IH,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
    assert fx.get_plan(plan["id"])["planned_end_date"] == "2026-08-21"

    # After submit the plan is no longer DRAFT: a fresh version passes OCC
    # and the state precondition fires instead.
    fx.submit_plan(plan["id"])
    fresh_version = fx.get_plan(plan["id"])["version"]
    state_res = api.revise_sampling_plan(
        plan["id"],
        revise_plan_payload(fresh_version, planned_end_date="2026-09-04"),
        IH,
    )
    validate_error(state_res, ApiErrorId.ERR_PLAN_INVALID_STATE, 409)


def test_plan_reject_loop_returns_to_draft(api):
    """PRD §3.3: "Rejection returns the plan `PENDING_APPROVAL → DRAFT` so the
    hygienist can revise it — the draft-submit-reject loop may repeat as many
    times as needed, and the `required_sample_count` is recomputed on the next
    revision while back in `DRAFT`."

    Design: Difficulty/non_linear_state_machine/plan_reject_and_regress_cycles
    """
    ctx = fx.setup_site_seg(member_count=3)
    plan = fx.create_plan(ctx.seg["id"])
    v0 = plan["version"]

    plan = fx.submit_plan(plan["id"])
    assert plan["status"] == "PENDING_APPROVAL"
    assert plan["version"] == v0 + 1

    plan = fx.reject_plan(plan["id"])
    assert plan["status"] == "DRAFT"
    assert plan["version"] == v0 + 2

    # The loop may repeat: submit again and approve cleanly.
    plan = fx.submit_plan(plan["id"])
    assert plan["status"] == "PENDING_APPROVAL"
    plan = fx.approve_plan(plan["id"])
    assert plan["status"] == "APPROVED"
    assert plan["version"] == v0 + 4


def test_plan_invalidation_regress_and_calibration_reuse(api):
    """PRD §3.3: "If a sample invalidation while the plan is `FIELD_COMPLETE`
    drops `active_sample_count` below `required_sample_count`, the plan falls
    back `FIELD_COMPLETE → APPROVED` so replacement samples can be collected."
    PRD §3.4: "Any invalidation recomputes the plan's counters, releases the
    calibration link by resetting the calibration's `linked_sample_id` to
    null, regresses the plan `FIELD_COMPLETE → APPROVED` or `LAB_COMPLETE →
    APPROVED` if the counters fall below the requirement, and increments the
    sample's `version`."

    Design: Difficulty/non_linear_state_machine/plan_reject_and_regress_cycles
    """
    ctx = fx.setup_approved_plan(member_count=3)
    fx.collect_personal_samples(ctx, 3)
    plan = fx.complete_field(ctx.plan["id"])
    assert plan["status"] == "FIELD_COMPLETE"
    assert plan["active_sample_count"] == 3

    doomed = ctx.samples[2]
    invalidated = fx.invalidate_sample(doomed["id"], reason="wet cassette")
    assert invalidated["status"] == "INVALIDATED"
    assert invalidated["invalidate_reason"] == "MANUAL"

    plan = fx.get_plan(ctx.plan["id"])
    assert plan["status"] == "APPROVED"
    assert plan["active_sample_count"] == 2

    released = fx.get_calibration(ctx.calibrations[2]["id"])
    assert released["linked_sample_id"] is None

    # The released calibration backs the replacement sample without error.
    replacement = fx.create_sample(
        ctx.plan["id"],
        employee_id=ctx.employees[2]["id"],
        pump_id=ctx.pump["id"],
        pre_calibration_id=ctx.calibrations[2]["id"],
        collection_date="2026-08-04",
    )
    fx.seal_sample(replacement["id"])

    plan = fx.complete_field(ctx.plan["id"])
    assert plan["status"] == "FIELD_COMPLETE"
    assert plan["active_sample_count"] == 3


def test_required_count_initial_table_and_verification_flat(api):
    """PRD §3.3: "A `VERIFICATION` plan always requires exactly 3 samples,
    skipping the sizing table and the adjustment below."
    PRD §3.3: "For example, a group of three with class `NONE` drafting an
    `INITIAL` plan requires 3 samples; the same group with class `UNCERTAIN`
    drafting a `FOLLOWUP` plan requires 6; and a group of twenty-five drafting
    a `VERIFICATION` plan requires 3."

    Design: Difficulty/combinatorial_formula/required_count_table_branch_clamp
    """
    ctx = fx.setup_site_seg(member_count=3)

    initial = fx.create_plan(ctx.seg["id"], purpose="INITIAL")
    assert initial["required_sample_count"] == 3

    verification = fx.create_plan(
        ctx.seg["id"],
        purpose="VERIFICATION",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-11",
    )
    assert verification["required_sample_count"] == 3


def test_required_count_followup_adjustment_after_uncertain(api):
    """PRD §3.3: "When the group's `current_class` at computation time is
    `UNCERTAIN` or `ABOVE_PEL`, three samples are added to the base; otherwise
    nothing is added. The final requirement is the larger of 3 and the
    adjusted base."
    PRD §3.3: "For example, a group of three with class `NONE` drafting an
    `INITIAL` plan requires 3 samples; the same group with class `UNCERTAIN`
    drafting a `FOLLOWUP` plan requires 6; and a group of twenty-five drafting
    a `VERIFICATION` plan requires 3."

    Design: Difficulty/combinatorial_formula/required_count_table_branch_clamp
    """
    # Masses 10/12/40 ug drive the raw class to UNCERTAIN (PRD §3.6).
    ctx = fx.setup_signed_assessment(masses=(10, 12, 40), member_count=3)
    assert ctx.assessment["exposure_class"] == "UNCERTAIN"
    assert ctx.seg["current_class"] == "UNCERTAIN"
    assert ctx.plan["required_sample_count"] == 3
    assert ctx.plan["status"] == "LAB_COMPLETE"

    followup = fx.create_plan(
        ctx.seg["id"],
        purpose="FOLLOWUP",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-11",
    )
    assert followup["required_sample_count"] == 6

    verification = fx.create_plan(
        ctx.seg["id"],
        purpose="VERIFICATION",
        planned_start_date="2026-09-01",
        planned_end_date="2026-09-11",
    )
    assert verification["required_sample_count"] == 3


def test_complete_field_at_exact_required_count(api):
    """PRD §3.3: "When the field team believes collection is finished, the
    hygienist completes the field phase, moving `APPROVED → FIELD_COMPLETE` —
    but only if `active_sample_count` is at least `required_sample_count`;
    otherwise the completion is rejected with
    `ERR_INSUFFICIENT_VALID_SAMPLES` (409)."

    Design: Difficulty/boundary_precision_check/valid_count_exactly_required_passes
    """
    ctx = fx.setup_approved_plan(member_count=3)
    fx.collect_personal_samples(ctx, 3)
    plan = fx.complete_field(ctx.plan["id"])
    assert plan["status"] == "FIELD_COMPLETE"
    assert plan["active_sample_count"] == 3
    assert plan["required_sample_count"] == 3


def test_complete_field_below_required_count_rejected(api):
    """PRD §3.3: "When the field team believes collection is finished, the
    hygienist completes the field phase, moving `APPROVED → FIELD_COMPLETE` —
    but only if `active_sample_count` is at least `required_sample_count`;
    otherwise the completion is rejected with
    `ERR_INSUFFICIENT_VALID_SAMPLES` (409)."

    Design: Difficulty/boundary_precision_check/valid_count_exactly_required_passes
    """
    ctx = fx.setup_approved_plan(member_count=3)
    fx.collect_personal_samples(ctx, 2)

    res = api.complete_field(ctx.plan["id"], IH)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_VALID_SAMPLES, 409)

    plan = fx.get_plan(ctx.plan["id"])
    assert plan["status"] == "APPROVED"
    assert plan["active_sample_count"] == 2


def test_sample_create_plan_draft_state_error(api):
    """PRD §3.4: "A `FieldTechnician` logs a sample against an `APPROVED` plan
    via `sampling_plan_id` — collection against a plan in any other status is
    rejected with `ERR_PLAN_NOT_OPEN_FOR_SAMPLING` (409)".

    Design: Corner/validations/sample_create_plan_draft_state_error
    """
    ctx = fx.setup_site_seg(member_count=1)
    plan = fx.create_plan(ctx.seg["id"])  # stays DRAFT
    pump = fx.create_pump(ctx.site["id"], serial_number="P-001")
    cal = fx.create_calibration(pump["id"])

    res = api.create_field_sample(
        create_sample_payload(
            plan["id"],
            employee_id=ctx.employees[0]["id"],
            pump_id=pump["id"],
            pre_calibration_id=cal["id"],
        ),
        TECH,
    )
    validate_error(res, ApiErrorId.ERR_PLAN_NOT_OPEN_FOR_SAMPLING, 409)


def test_plan_window_inclusive_boundaries(api):
    """PRD §3.4: "The `collection_date` must fall within the plan's window
    from `planned_start_date` through `planned_end_date`, inclusive at both
    ends, else `ERR_SAMPLE_OUTSIDE_PLAN_WINDOW` (422)."

    Design: Corner/validations/plan_window_inclusive_boundaries
    """
    ctx = fx.setup_approved_plan(member_count=1)
    pump = fx.create_pump(ctx.site["id"], serial_number="P-001")

    first = fx.create_sample(
        ctx.plan["id"],
        employee_id=ctx.employees[0]["id"],
        pump_id=pump["id"],
        pre_calibration_id=fx.create_calibration(pump["id"])["id"],
        collection_date="2026-08-03",
    )
    assert first["collection_date"] == "2026-08-03"

    last = fx.create_sample(
        ctx.plan["id"],
        employee_id=ctx.employees[0]["id"],
        pump_id=pump["id"],
        pre_calibration_id=fx.create_calibration(pump["id"])["id"],
        collection_date="2026-08-14",
    )
    assert last["collection_date"] == "2026-08-14"

    res = api.create_field_sample(
        create_sample_payload(
            ctx.plan["id"],
            collection_date="2026-08-15",
            employee_id=ctx.employees[0]["id"],
            pump_id=pump["id"],
            pre_calibration_id=fx.create_calibration(pump["id"])["id"],
        ),
        TECH,
    )
    validate_error(res, ApiErrorId.ERR_SAMPLE_OUTSIDE_PLAN_WINDOW, 422)


def test_date_range_and_loq_schema_validation(api):
    """PRD §3.3: "a collection window from `planned_start_date` through
    `planned_end_date`, both inclusive, with the end date no earlier than the
    start date (a reversed window is rejected with `ERR_INVALID_DATE_RANGE`)"
    PRD §3.5: "A `LabAnalyst` opens an analysis batch for a site, naming the
    `analyte_code` the batch will measure, the limit of detection `lod_ug` in
    micrograms (greater than zero), and the limit of quantitation `loq_ug` (no
    smaller than `lod_ug`)."
    PRD §2.8: "numeric ranges must be respected, and an end date may not
    precede its start date on either a plan window or a batch window; failures
    surface as `ERR_INVALID_REQUEST` or `ERR_INVALID_DATE_RANGE`."

    Design: Corner/validations/date_range_and_loq_schema_validation
    """
    ctx = fx.setup_site_seg(member_count=1)

    bad_plan = api.create_sampling_plan(
        create_plan_payload(
            ctx.seg["id"],
            planned_start_date="2026-08-14",
            planned_end_date="2026-08-03",
        ),
        IH,
    )
    validate_error(bad_plan, ApiErrorId.ERR_INVALID_DATE_RANGE, 400)

    bad_batch = api.create_lab_batch(
        create_batch_payload(ctx.site["id"], lod_ug=10, loq_ug=5),
        TEST_USERS["lab_headers"],
    )
    validate_error(bad_batch, ApiErrorId.ERR_INVALID_REQUEST, 400)
