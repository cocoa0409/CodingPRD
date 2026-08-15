"""Laboratory analysis: intake gates, blank contamination, batch windows, and
the pinned volume/concentration/TWA calculation chain (PRD §2.8, §3.3, §3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_decimal,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS, make_lab_headers

LAB = TEST_USERS["lab_headers"]


def _setup_guard_scenario(api):
    """FIELD_COMPLETE plan with 3 SEALED samples; calibration 1 left PENDING,
    calibrations 2 and 3 record-posted VALID; batch open at 2026-08-10."""
    ctx = fx.setup_approved_plan(member_count=1)
    fx.collect_personal_samples(ctx, 3, record_post_flows=False)
    fx.record_post(ctx.calibrations[1]["id"])
    fx.record_post(ctx.calibrations[2]["id"])
    fx.complete_field(ctx.plan["id"])
    ctx.batch = fx.create_batch(ctx.site["id"])
    fx.set_clock("2026-08-10T00:00:00Z")
    return ctx


def test_lab_result_requires_valid_calibration(api):
    """PRD §3.5: "Finally, the two safety gates of §2.9 apply: the entering
    analyst must not be the sample's collector (`ERR_SOD_CHAIN_OF_CUSTODY`),
    and the sample's calibration must stand at `VALID` — post-flow recorded
    and drift within limit — else `ERR_CALIBRATION_NOT_VALID` (409)."

    Design: Corner/validations/lab_result_entry_guards
    """
    ctx = _setup_guard_scenario(api)

    res = api.create_lab_result(
        {
            "field_sample_id": ctx.samples[0]["id"],
            "lab_batch_id": ctx.batch["id"],
            "mass_ug": 12,
        },
        LAB,
    )
    validate_error(res, ApiErrorId.ERR_CALIBRATION_NOT_VALID, 409)
    assert fx.get_sample(ctx.samples[0]["id"])["status"] == "SEALED"
    assert fx.get_batch(ctx.batch["id"])["intake_count"] == 0


def test_lab_result_chain_of_custody_sod(api):
    """PRD §2.9: "A laboratory result may not be entered by the operator who
    collected the sample: if the entering analyst's `X-User-ID` equals the
    sample's `collected_by_user_id`, the entry is rejected with
    `ERR_SOD_CHAIN_OF_CUSTODY` (403), preserving an unbroken chain of custody
    between field and laboratory."

    Design: Corner/validations/lab_result_entry_guards
    """
    ctx = _setup_guard_scenario(api)

    # The LabAnalyst role is legitimate; u_tech_1 collected this sample.
    res = api.create_lab_result(
        {
            "field_sample_id": ctx.samples[1]["id"],
            "lab_batch_id": ctx.batch["id"],
            "mass_ug": 12,
        },
        make_lab_headers("u_tech_1"),
    )
    validate_error(res, ApiErrorId.ERR_SOD_CHAIN_OF_CUSTODY, 403)
    assert fx.get_sample(ctx.samples[1]["id"])["status"] == "SEALED"
    assert fx.get_batch(ctx.batch["id"])["intake_count"] == 0


def test_batch_analyte_mismatch_rejected(api):
    """PRD §3.5: "The batch's `analyte_code` must equal the analyte of the
    group the sample's plan belongs to, else `ERR_ANALYTE_MISMATCH`."

    Design: Corner/validations/batch_analyte_mismatch_rejected
    """
    ctx = fx.setup_field_complete(n_samples=3, member_count=1)
    batch = fx.create_batch(ctx.site["id"], analyte_code="CR")
    fx.set_clock("2026-08-10T00:00:00Z")

    res = api.create_lab_result(
        {
            "field_sample_id": ctx.samples[0]["id"],
            "lab_batch_id": batch["id"],
            "mass_ug": 12,
        },
        LAB,
    )
    validate_error(res, ApiErrorId.ERR_ANALYTE_MISMATCH, 422)
    assert fx.get_sample(ctx.samples[0]["id"])["status"] == "SEALED"
    assert fx.get_batch(batch["id"])["intake_count"] == 0


def test_contaminated_batch_rejects_intake(api):
    """PRD §3.5: "If the analyzed sample is a `FIELD_BLANK` whose `mass_ug`
    reaches or exceeds the batch's `lod_ug`, the batch's `contaminated` flag
    is set to true and intake closes at once."
    PRD §3.5: "a batch whose `contaminated` flag is set rejects all further
    intake with `ERR_BATCH_NOT_ACCEPTING` (409)."

    Design: Corner/validations/contaminated_batch_rejects_intake
    """
    ctx = fx.setup_approved_plan(member_count=1)
    fx.collect_personal_samples(ctx, 3)
    blank = fx.create_sample(
        ctx.plan["id"], sample_type="FIELD_BLANK", start_minute=0
    )
    blank = fx.seal_sample(blank["id"])
    fx.complete_field(ctx.plan["id"])
    batch = fx.create_batch(ctx.site["id"])
    fx.set_clock("2026-08-10T00:00:00Z")

    # The contaminating blank result lands first and is accepted.
    blank_result = validate_success(
        api.create_lab_result(
            {
                "field_sample_id": blank["id"],
                "lab_batch_id": batch["id"],
                "mass_ug": 6,
            },
            LAB,
        ),
        201,
    )
    assert blank_result["is_detect"] is True
    assert fx.get_batch(batch["id"])["contaminated"] is True
    assert fx.get_sample(blank["id"])["status"] == "ANALYZED"

    # All further intake is refused; nothing existed to invalidate, so the
    # plan does not regress.
    res = api.create_lab_result(
        {
            "field_sample_id": ctx.samples[0]["id"],
            "lab_batch_id": batch["id"],
            "mass_ug": 12,
        },
        LAB,
    )
    validate_error(res, ApiErrorId.ERR_BATCH_NOT_ACCEPTING, 409)
    assert fx.get_sample(ctx.samples[0]["id"])["status"] == "SEALED"
    assert fx.get_plan(ctx.plan["id"])["status"] == "FIELD_COMPLETE"


def test_batch_inclusive_window_end_and_capacity(api):
    """PRD §3.5: "The current logical date must fall within the batch's intake
    window, inclusive at both ends, else `ERR_BATCH_WINDOW_CLOSED` (422). A
    batch whose `intake_count` has reached `max_capacity` rejects further
    intake with `ERR_BATCH_CAPACITY_FULL` (409)".

    Design: Difficulty/resource_temporal_overlap/batch_inclusive_window_and_capacity
    """
    ctx = fx.setup_field_complete(n_samples=3, member_count=3)
    batch = fx.create_batch(
        ctx.site["id"],
        lod_ug=1,
        loq_ug=2,
        window_start_date="2026-08-10",
        window_end_date="2026-08-12",
        max_capacity=2,
    )
    fx.set_clock("2026-08-12T00:00:00Z")  # the inclusive last intake day

    fx.enter_result(ctx.samples[0]["id"], batch["id"], 9)
    fx.enter_result(ctx.samples[1]["id"], batch["id"], 9)

    res = api.create_lab_result(
        {
            "field_sample_id": ctx.samples[2]["id"],
            "lab_batch_id": batch["id"],
            "mass_ug": 9,
        },
        LAB,
    )
    validate_error(res, ApiErrorId.ERR_BATCH_CAPACITY_FULL, 409)
    assert fx.get_batch(batch["id"])["intake_count"] == 2
    assert fx.get_sample(ctx.samples[2]["id"])["status"] == "SEALED"


def test_batch_temporal_window_masks_capacity(api):
    """PRD §2.8: "Ninth, temporal windows: the plan collection window, the
    batch intake window, and the retention gate."
    PRD §2.8: "Tenth and last, uniqueness and capacity constraints: duplicate
    limits, pump serials, and memberships; pump double-booking; calibration
    reuse; batch capacity and contamination; the one-result-per-sample rule;
    the one-open-assessment-per-group rule; and the complete-field
    sample-count gate."
    PRD §3.5: "The current logical date must fall within the batch's intake
    window, inclusive at both ends, else `ERR_BATCH_WINDOW_CLOSED` (422)."

    Design: Difficulty/resource_temporal_overlap/batch_inclusive_window_and_capacity
    """
    ctx = fx.setup_field_complete(n_samples=3, member_count=3)
    batch = fx.create_batch(
        ctx.site["id"],
        lod_ug=1,
        loq_ug=2,
        window_start_date="2026-08-10",
        window_end_date="2026-08-12",
        max_capacity=2,
    )
    fx.set_clock("2026-08-12T00:00:00Z")
    fx.enter_result(ctx.samples[0]["id"], batch["id"], 9)
    fx.enter_result(ctx.samples[1]["id"], batch["id"], 9)

    # One day past the inclusive end; capacity is still exhausted, and the
    # earlier pipeline stage (temporal) is the one reported.
    fx.set_clock("2026-08-13T00:00:00Z")
    res = api.create_lab_result(
        {
            "field_sample_id": ctx.samples[2]["id"],
            "lab_batch_id": batch["id"],
            "mass_ug": 9,
        },
        LAB,
    )
    validate_error(res, ApiErrorId.ERR_BATCH_WINDOW_CLOSED, 422)
    assert fx.get_batch(batch["id"])["intake_count"] == 2
    assert fx.get_sample(ctx.samples[2]["id"])["status"] == "SEALED"


def test_twa_per_step_rounding_order(api):
    """PRD §3.5: "Consider a calibration of 1.5 liters per minute both before
    and after, a sixty-minute sample, and a measured mass of 5 micrograms: the
    flow used is 1.5, the volume 90.0 liters, and the concentration 0.0556
    milligrams per cubic meter, and continuing this example into the
    time-weighted average below yields 0.0070 — whereas deferring all rounding
    to the end would wrongly yield 0.0069."
    PRD §2.6: "Where a calculation is specified as a chain of steps — most
    importantly the air-volume-and-concentration chain of §3.5 — rounding is
    applied at every step and each rounded result feeds the next step".

    Design: Difficulty/combinatorial_formula/twa_per_step_rounding_order
    """
    ctx = fx.setup_lab_complete(
        masses=(5, 5, 5),
        member_count=1,
        lod=1,
        loq=2,
        pre_flow=1.5,
        post_flow=1.5,
        duration=60,
        start_minutes=[480, 600, 720],
    )
    sample = fx.get_sample(ctx.samples[0]["id"])
    assert_decimal(sample["air_volume_liters"], 90.0)
    assert_decimal(sample["concentration_mg_m3"], 0.0556)
    # Per-step rounding pins 0.0070; end-to-end rounding would give 0.0069.
    assert_decimal(sample["sample_twa_mg_m3"], 0.0070)
    assert sample["is_detect"] is True


def test_volume_basis_mean_flow_vs_pre_flow(api):
    """PRD §3.5: "The choice of basis matters too: with a pre-flow of 2.000, a
    post-flow of 1.900, a 200-minute sample, and a mass of 25 micrograms,
    `MEAN_FLOW` produces a time-weighted average of 0.0267 while `PRE_FLOW`
    produces 0.0260."
    PRD §3.5: "First, the flow used: when the plan's `volume_basis` is
    `MEAN_FLOW`, the arithmetic mean of `pre_flow_lpm` and `post_flow_lpm`,
    rounded half up to three decimal places; when `PRE_FLOW`, the
    `pre_flow_lpm` value exactly as entered, with no averaging and no
    rounding."

    Design: Difficulty/combinatorial_formula/twa_per_step_rounding_order
    """
    ctx = fx.setup_approved_plan(member_count=1)
    plan_pre = fx.create_plan(ctx.seg["id"], volume_basis="PRE_FLOW")
    fx.submit_plan(plan_pre["id"])
    plan_pre = fx.approve_plan(plan_pre["id"])

    fx.collect_personal_samples(
        ctx, 3, duration=200, post_flow=1.9, start_minutes=[480, 680, 880]
    )
    mean_samples = list(ctx.samples)
    fx.complete_field(ctx.plan["id"])

    fx.collect_personal_samples(
        ctx,
        3,
        plan=plan_pre,
        duration=200,
        post_flow=1.9,
        collection_dates=["2026-08-04", "2026-08-04", "2026-08-04"],
        start_minutes=[480, 680, 880],
    )
    pre_samples = list(ctx.samples)
    fx.complete_field(plan_pre["id"])

    batch = fx.create_batch(ctx.site["id"], lod_ug=1, loq_ug=2)
    fx.set_clock("2026-08-10T00:00:00Z")
    for s in mean_samples + pre_samples:
        fx.enter_result(s["id"], batch["id"], 25)

    mean_sample = fx.get_sample(mean_samples[0]["id"])
    assert_decimal(mean_sample["air_volume_liters"], 390.0)
    assert_decimal(mean_sample["concentration_mg_m3"], 0.0641)
    assert_decimal(mean_sample["sample_twa_mg_m3"], 0.0267)

    pre_sample = fx.get_sample(pre_samples[0]["id"])
    assert_decimal(pre_sample["air_volume_liters"], 400.0)
    assert_decimal(pre_sample["concentration_mg_m3"], 0.0625)
    assert_decimal(pre_sample["sample_twa_mg_m3"], 0.0260)


def test_unsampled_time_zero_fill_dilutes_short_sample(api):
    """PRD §3.5: "For a short sample under 420 minutes, the plan's
    `unsampled_time_rule` decides: under `ZERO_FILL` the same formula applies,
    so unsampled minutes contribute zero exposure; under `WORST_CASE` the
    sample is assigned the full measured concentration as its average,
    treating the entire shift as spent at that level. The two rules diverge
    sharply: a concentration of 0.0833 measured over 120 minutes yields 0.0208
    under `ZERO_FILL` but 0.0833 under `WORST_CASE`."
    PRD §3.3: "after each laboratory result is entered, once every active
    `PERSONAL` sample of the plan has reached `ANALYZED` and
    `analyzed_valid_count` is at least `required_sample_count`, the plan
    transitions `FIELD_COMPLETE → LAB_COMPLETE` automatically."

    Design: Difficulty/dual_variant_calc/unsampled_time_zero_fill_vs_worst_case
    """
    ctx = fx.setup_lab_complete(
        masses=(20, 20, 20),
        member_count=1,
        lod=1,
        loq=2,
        plan_overrides={"unsampled_time_rule": "ZERO_FILL"},
        duration=120,
        start_minutes=[480, 620, 760],
    )
    sample = fx.get_sample(ctx.samples[0]["id"])
    assert_decimal(sample["air_volume_liters"], 240.0)
    assert_decimal(sample["concentration_mg_m3"], 0.0833)
    assert_decimal(sample["sample_twa_mg_m3"], 0.0208)  # 0.0833 * 120/480
    assert ctx.plan["status"] == "LAB_COMPLETE"


def test_unsampled_time_worst_case_assigns_full_shift(api):
    """PRD §3.5: "under `WORST_CASE` the sample is assigned the full measured
    concentration as its average, treating the entire shift as spent at that
    level. The two rules diverge sharply: a concentration of 0.0833 measured
    over 120 minutes yields 0.0208 under `ZERO_FILL` but 0.0833 under
    `WORST_CASE`."
    PRD §3.3: "after each laboratory result is entered, once every active
    `PERSONAL` sample of the plan has reached `ANALYZED` and
    `analyzed_valid_count` is at least `required_sample_count`, the plan
    transitions `FIELD_COMPLETE → LAB_COMPLETE` automatically."

    Design: Difficulty/dual_variant_calc/unsampled_time_zero_fill_vs_worst_case
    """
    ctx = fx.setup_lab_complete(
        masses=(20, 20, 20),
        member_count=1,
        lod=1,
        loq=2,
        plan_overrides={"unsampled_time_rule": "WORST_CASE"},
        duration=120,
        start_minutes=[480, 620, 760],
    )
    sample = fx.get_sample(ctx.samples[0]["id"])
    assert_decimal(sample["air_volume_liters"], 240.0)
    assert_decimal(sample["concentration_mg_m3"], 0.0833)
    assert_decimal(sample["sample_twa_mg_m3"], 0.0833)
    assert ctx.plan["status"] == "LAB_COMPLETE"


def _setup_contamination_scenario():
    """LAB_COMPLETE plan with 3 ANALYZED PERSONAL samples (12/10/8 ug), one
    SEALED FIELD_BLANK in the same open batch, and a DRAFT assessment."""
    ctx = fx.setup_approved_plan(member_count=3)
    fx.collect_personal_samples(ctx, 3)
    blank = fx.create_sample(
        ctx.plan["id"], sample_type="FIELD_BLANK", start_minute=0
    )
    ctx.blank = fx.seal_sample(blank["id"])
    fx.complete_field(ctx.plan["id"])
    ctx.batch = fx.create_batch(ctx.site["id"])
    fx.set_clock("2026-08-10T00:00:00Z")
    for sample, mass in zip(ctx.samples, (12, 10, 8)):
        fx.enter_result(sample["id"], ctx.batch["id"], mass)
    assert fx.get_plan(ctx.plan["id"])["status"] == "LAB_COMPLETE"
    ctx.assessment = fx.create_assessment(ctx.plan["id"], ctx.seg["id"])
    return ctx


def test_blank_contamination_four_hop_cascade(api):
    """PRD §3.5: "If the analyzed sample is a `FIELD_BLANK` whose `mass_ug`
    reaches or exceeds the batch's `lod_ug`, the batch's `contaminated` flag
    is set to true and intake closes at once. Worse, every sibling sample
    already `ANALYZED` in that batch is invalidated with `invalidate_reason`
    `BLANK_CONTAMINATION` — the only path that invalidates an `ANALYZED`
    sample. Each such invalidation recomputes its plan's counters, and a plan
    that drops below its requirement regresses `LAB_COMPLETE → APPROVED` as
    §3.3 describes, voiding any of the plan's assessments still in `DRAFT` or
    `UNDER_REVIEW` (their `review_status` becomes `VOID`) while leaving
    `SIGNED` assessments untouched."

    Design: Difficulty/transitive_cascade/blank_contamination_four_hop_cascade
    """
    ctx = _setup_contamination_scenario()

    res = api.create_lab_result(
        {
            "field_sample_id": ctx.blank["id"],
            "lab_batch_id": ctx.batch["id"],
            "mass_ug": 6,
        },
        LAB,
    )
    validate_success(res, 201)

    assert fx.get_batch(ctx.batch["id"])["contaminated"] is True
    for sample in ctx.samples:
        after = fx.get_sample(sample["id"])
        assert after["status"] == "INVALIDATED"
        assert after["invalidate_reason"] == "BLANK_CONTAMINATION"

    plan = fx.get_plan(ctx.plan["id"])
    assert plan["status"] == "APPROVED"
    assert plan["analyzed_valid_count"] == 0
    assert plan["active_sample_count"] == 0

    assessment = fx.get_assessment(ctx.assessment["id"])
    assert assessment["review_status"] == "VOID"

    blank = fx.get_sample(ctx.blank["id"])
    assert blank["status"] == "ANALYZED", "the blank itself is resulted"


def test_blank_contamination_regress_reopens_field_work(api):
    """PRD §3.3: "If blank contamination (§3.5) invalidates already-analyzed
    samples while the plan is `LAB_COMPLETE`, dropping `analyzed_valid_count`
    below the requirement, the plan falls back `LAB_COMPLETE → APPROVED` — and
    any exposure assessment of that plan still in `DRAFT` or `UNDER_REVIEW` is
    voided with it, moving to `VOID`."
    PRD §3.3: "Two regression loops keep the counters honest."

    Design: Difficulty/transitive_cascade/blank_contamination_four_hop_cascade
    """
    ctx = _setup_contamination_scenario()
    fx.enter_result(ctx.blank["id"], ctx.batch["id"], 6)
    assert fx.get_plan(ctx.plan["id"])["status"] == "APPROVED"

    # Field work reopens: replacement samples reuse the released calibrations.
    # The shared pump needs non-overlapping half-open intervals on the single
    # collection date (PRD §3.4 double-booking rule), so stagger start_minute.
    replacements = []
    for i, cal in enumerate(ctx.calibrations):
        assert fx.get_calibration(cal["id"])["linked_sample_id"] is None
        sample = fx.create_sample(
            ctx.plan["id"],
            employee_id=ctx.employees[i]["id"],
            pump_id=ctx.pump["id"],
            pre_calibration_id=cal["id"],
            collection_date="2026-08-04",
            start_minute=480 + i * 240,
        )
        replacements.append(fx.seal_sample(sample["id"]))

    plan = fx.complete_field(ctx.plan["id"])
    assert plan["status"] == "FIELD_COMPLETE"
    assert plan["active_sample_count"] == 3

    # Results must go to a fresh batch (the first is contaminated).
    batch2 = fx.create_batch(ctx.site["id"], lod_ug=5, loq_ug=10)
    for sample, mass in zip(replacements, (12, 10, 8)):
        fx.enter_result(sample["id"], batch2["id"], mass)

    plan = fx.get_plan(ctx.plan["id"])
    assert plan["status"] == "LAB_COMPLETE"
    assert plan["analyzed_valid_count"] == 3

    # The voided assessment is terminal and stays void.
    assert fx.get_assessment(ctx.assessment["id"])["review_status"] == "VOID"
