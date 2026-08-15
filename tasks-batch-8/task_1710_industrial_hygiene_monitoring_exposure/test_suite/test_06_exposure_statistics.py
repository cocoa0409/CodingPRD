"""Exposure assessment statistics: censored substitution, lognormal
confidence limits, classification order, CEILING branch (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_assessment,
    assert_decimal,
    validate_error,
    validate_paginated,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

IH = TEST_USERS["ih_headers"]


def test_censored_substitution_sqrt2_statistics(api):
    """PRD §3.6: "The stored `substitution_rule` is `SQRT2` when the set holds
    at least 3 samples and at least half of them are detects (their
    `is_detect` true); otherwise it is `HALF`."
    PRD §3.6: "Otherwise, if `ucl95` is strictly greater than A, the class is
    `BELOW_PEL_MONITOR` — controlled, with periodic monitoring."

    Masses 12/10/3 ug against LOD 5: two detects of three, so SQRT2 applies
    and the non-detect enters at its LOD-equivalent TWA divided by sqrt(2).

    Design: Difficulty/dual_variant_calc/censored_substitution_sqrt2_over_half
    """
    ctx = fx.setup_lab_complete(masses=(12, 10, 3), member_count=3)
    assessment = fx.create_assessment(ctx.plan["id"], ctx.seg["id"])
    assert_assessment(assessment)

    assert assessment["substitution_rule"] == "SQRT2"
    assert assessment["n_valid"] == 3
    assert_decimal(assessment["geo_mean"], 0.0078)
    assert_decimal(assessment["gsd"], 1.9275)
    assert_decimal(assessment["ucl95"], 0.0237)
    assert_decimal(assessment["lcl95"], 0.0026)
    assert assessment["exposure_class"] == "BELOW_PEL_MONITOR"


def test_censored_substitution_detect_flags_feed_rule_selection(api):
    """PRD §3.5: "The sample's own `is_detect` flag is set from the same
    mass-versus-`lod_ug` comparison as the result's."
    PRD §3.6: "The stored `substitution_rule` is `SQRT2` when the set holds at
    least 3 samples and at least half of them are detects (their `is_detect`
    true); otherwise it is `HALF`."
    PRD §3.6: "Detected samples enter with their stored `sample_twa_mg_m3`
    exactly as recorded."

    Design: Difficulty/dual_variant_calc/censored_substitution_sqrt2_over_half
    """
    ctx = fx.setup_lab_complete(masses=(12, 10, 3), member_count=3)

    flags = [fx.get_sample(s["id"])["is_detect"] for s in ctx.samples]
    assert flags == [True, True, False], "detects are 12 and 10 ug at LOD 5"

    # Stored per-sample values (volume 480.0 L each): detects carry their
    # recorded TWA into the statistic set.
    twas = [fx.get_sample(s["id"])["sample_twa_mg_m3"] for s in ctx.samples]
    assert_decimal(twas[0], 0.0125)
    assert_decimal(twas[1], 0.0104)
    assert_decimal(twas[2], 0.0032)

    assessment = fx.create_assessment(ctx.plan["id"], ctx.seg["id"])
    assert assessment["substitution_rule"] == "SQRT2"
    assert assessment["n_valid"] == 3
    assert_decimal(assessment["ucl95"], 0.0237)
    assert_decimal(assessment["lcl95"], 0.0026)


def test_censored_substitution_half_branch(api):
    """PRD §3.6: "The stored `substitution_rule` is `SQRT2` when the set holds
    at least 3 samples and at least half of them are detects (their
    `is_detect` true); otherwise it is `HALF`."
    PRD §3.6: "the group's `next_sample_due_date` is set to the signed date
    plus the re-sampling interval for the class — 30 days for `ABOVE_PEL`, 90
    days for `UNCERTAIN`, 180 days for `BELOW_PEL_MONITOR`, and 360 days for
    `BELOW_ACTION`."
    PRD §3.7: "Without a qualifying control, `adjusted_class` is null."

    One detect of three (12/3/3 ug at LOD 5) forces HALF.

    Design: Corner/calculations/censored_substitution_half_branch
    """
    ctx = fx.setup_signed_assessment(masses=(12, 3, 3), member_count=3)
    assessment = fx.get_assessment(ctx.assessment["id"])

    assert assessment["substitution_rule"] == "HALF"
    assert_decimal(assessment["geo_mean"], 0.0044)
    assert_decimal(assessment["gsd"], 2.4758)
    assert_decimal(assessment["ucl95"], 0.0202)
    assert_decimal(assessment["lcl95"], 0.0010)
    assert assessment["exposure_class"] == "BELOW_PEL_MONITOR"
    assert assessment["adjusted_class"] is None

    assert ctx.seg["current_class"] == "BELOW_PEL_MONITOR"
    assert ctx.seg["next_sample_due_date"] == "2027-02-06"


def test_ceiling_limit_classifies_on_max_concentration(api):
    """PRD §3.6: "For a limit of `limit_type` `CEILING`, no statistics are
    computed at all: `geo_mean`, `gsd`, `ucl95`, and `lcl95` are null.
    Classification instead uses the largest `concentration_mg_m3` among the
    input samples: `ABOVE_PEL` when that maximum is strictly greater than L;
    `BELOW_PEL_MONITOR` when it is strictly greater than A but not greater
    than L; and `BELOW_ACTION` otherwise."

    Masses 30/12/60 ug over 480.0 L give concentrations 0.0625/0.025/0.125
    mg/m3, so the 0.125 maximum exceeds the 0.1 ceiling.

    Design: Corner/calculations/ceiling_limit_classifies_on_max_concentration
    """
    ctx = fx.setup_lab_complete(
        masses=(30, 12, 60),
        member_count=3,
        limit_kwargs={"limit_type": "CEILING", "limit_mg_m3": 0.1},
    )
    assert_decimal(
        fx.get_sample(ctx.samples[2]["id"])["concentration_mg_m3"], 0.125
    )

    assessment = fx.create_assessment(ctx.plan["id"], ctx.seg["id"])
    assert assessment["geo_mean"] is None
    assert assessment["gsd"] is None
    assert assessment["ucl95"] is None
    assert assessment["lcl95"] is None
    assert assessment["exposure_class"] == "ABOVE_PEL"


def test_lcl_certain_above_pel_four_samples(api):
    """PRD §3.6: "If `lcl95` is strictly greater than L, the `exposure_class`
    is `ABOVE_PEL` — a statistically certain exceedance."
    PRD §3.6: "The degrees of freedom are the lesser of one-less-than-the-count
    and ten, and the 95th-percentile Student t factor for that degree of
    freedom is taken from a fixed table: 6.314 for one degree of freedom,
    2.920 for two, 2.353 for three, 2.132 for four, 2.015 for five, 1.943 for
    six, 1.895 for seven, 1.860 for eight, 1.833 for nine, and 1.812 for ten."
    PRD §3.6: "The statistical input set is the plan's `PERSONAL` samples in
    `ANALYZED` status; `FIELD_BLANK` and `INVALIDATED` samples never enter,
    and the set's size is recorded as `n_valid`."

    Four tight high results (62/60/58/56 ug) at df 3 lift the lower
    confidence limit above the 0.05 mg/m3 limit.

    Design: Corner/calculations/lcl_certain_above_pel_four_samples
    """
    ctx = fx.setup_lab_complete(masses=(62, 60, 58, 56), member_count=3)
    assessment = fx.create_assessment(ctx.plan["id"], ctx.seg["id"])

    assert assessment["n_valid"] == 4
    assert_decimal(assessment["geo_mean"], 0.0614)
    assert_decimal(assessment["gsd"], 1.0445)
    assert_decimal(assessment["ucl95"], 0.0647)
    assert_decimal(assessment["lcl95"], 0.0584)
    assert assessment["exposure_class"] == "ABOVE_PEL"


def test_below_action_zero_variance_edge(api):
    """PRD §3.6: "When the set holds a single value, the standard deviation is
    undefined and is pinned to zero, so both confidence limits equal the
    geometric mean; the same collapse occurs whenever all substituted values
    are identical."
    PRD §3.6: "Otherwise the class is `BELOW_ACTION`."
    PRD §3.6: "and — when the class is `ABOVE_PEL` — auto-drafts a control
    recommendation on the assessment being signed: an `ENGINEERING` control of
    `HIGH` priority, born `PROPOSED`, with `auto_created` true."

    Three identical TWAs (mass 1 ug each) collapse the interval onto the
    geometric mean, below the 0.005 action level.

    Design: Corner/calculations/below_action_zero_variance_edge
    """
    ctx = fx.setup_signed_assessment(masses=(1, 1, 1), member_count=3, lod=1, loq=2)
    assessment = fx.get_assessment(ctx.assessment["id"])

    assert_decimal(assessment["geo_mean"], 0.0011)
    assert_decimal(assessment["ucl95"], 0.0011)
    assert_decimal(assessment["lcl95"], 0.0011)
    assert_decimal(assessment["gsd"], 1.0)
    assert assessment["exposure_class"] == "BELOW_ACTION"
    assert ctx.seg["current_class"] == "BELOW_ACTION"
    assert ctx.seg["next_sample_due_date"] == "2027-08-05"

    controls, meta = validate_paginated(
        api.list_controls(IH, params={"exposure_assessment_id": assessment["id"]})
    )
    assert meta["total_count"] == 0, "no auto-control below ABOVE_PEL"
    assert controls == []


def test_assessment_create_requires_lab_complete(api):
    """PRD §3.6: "The request names the `sampling_plan_id` — a plan not yet
    `LAB_COMPLETE` is rejected with `ERR_PLAN_NOT_READY_FOR_ASSESSMENT` (409)
    — and must carry `expected_seg_version` per §2.7, rejecting a stale view
    of the group with `ERR_STALE_VERSION` (412)."

    Design: Corner/state_machines/assessment_create_requires_lab_complete
    """
    ctx = fx.setup_field_complete(n_samples=3, member_count=1)
    seg_version = fx.get_seg(ctx.seg["id"])["version"]

    res = api.create_exposure_assessment(
        {
            "sampling_plan_id": ctx.plan["id"],
            "expected_seg_version": seg_version,
        },
        IH,
    )
    validate_error(res, ApiErrorId.ERR_PLAN_NOT_READY_FOR_ASSESSMENT, 409)

    rows, meta = validate_paginated(
        api.list_exposure_assessments(IH, params={"seg_id": ctx.seg["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []
