"""Community development qualification: allocation variants, LMI threshold,
segregation of duties, budget cap, validation ordering, and the
disqualify/resubmit cycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_active_area,
    create_submitted_activity,
    get_area,
    get_cd_activity,
    make_compliance_analyst_headers,
    make_qualification_reviewer_headers,
    qualify_activity,
    review_decision_payload,
    validate_error,
    validate_success,
)


def _review(api, activity_id, payload, reviewer_user_id):
    return api.review_cd_activity(
        activity_id, payload, make_qualification_reviewer_headers(reviewer_user_id)
    )


# ---------------------------------------------------------------------------
# Queue B — Corner/validations
# ---------------------------------------------------------------------------

def test_qualify_exceeds_cd_budget(api):
    """PRD §3.4: "the sum of `qualified_amount_cents` over the area's
    `QUALIFIED` activities whose `activity_date` falls in that same calendar
    year, plus this activity's `qualified_amount_cents`, must not exceed the
    area's `annual_cd_budget_cents` (`ERR_CD_BUDGET_EXCEEDED`)."

    Design: Corner/validations/qualify_exceeds_cd_budget
    """
    area = create_active_area(
        area_code="AA-V5", msa_code="16980", state_code="IL",
        census_tracts=["T1"], annual_cd_budget_cents=100000,
    )
    activity = create_submitted_activity(
        area["id"], submitter_user_id="analyst-1",
        activity_type="QUALIFIED_INVESTMENT", amount_cents=200000,
        primary_purpose_category="AFFORDABLE_HOUSING", lmi_benefit_pct=0.60,
        activity_date="2026-02-01",
    )
    resp = _review(
        api, activity["id"],
        review_decision_payload("QUALIFY", allocation_method="PRO_RATA"),
        "reviewer-1",
    )
    validate_error(resp, ApiErrorId.ERR_CD_BUDGET_EXCEEDED)
    current = get_cd_activity(area["id"], activity["id"])
    assert current["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Queue A — Difficulty/dual_variant_calc/cd_activity_full_count_vs_pro_rata_diverge
# ---------------------------------------------------------------------------

def test_cd_activity_full_count_vs_pro_rata_diverge(api):
    """PRD §3.4: "Under `FULL_COUNT`, permitted only when `lmi_benefit_pct` is
    at least 0.51 (otherwise `ERR_LMI_THRESHOLD_NOT_MET`), the entire
    `amount_cents` counts as qualified. Under `PRO_RATA`, always permitted, only
    the LMI-benefit share counts: `qualified_amount_cents` is `amount_cents`
    multiplied by `lmi_benefit_pct`, rounded half up to whole cents — so
    identical inputs yield a strictly smaller qualified amount under `PRO_RATA`
    whenever `lmi_benefit_pct` lies strictly between 0 and 1."
    PRD §3.4: "A successful qualification records `reviewed_by_user_id` and the
    `allocation_method`, computes `qualified_amount_cents`, recomputes the
    area's `qualified_cd_total_cents` — the all-years sum of qualified amounts
    over the area's `QUALIFIED` activities".

    Design: Difficulty/dual_variant_calc/cd_activity_full_count_vs_pro_rata_diverge
    """
    area = create_active_area(
        area_code="AA-DV1", census_tracts=["T1", "T2"], annual_cd_budget_cents=10000000,
    )
    act_full = create_submitted_activity(
        area["id"], submitter_user_id="analyst-1", amount_cents=1000000,
        primary_purpose_category="AFFORDABLE_HOUSING", lmi_benefit_pct=0.60,
        activity_date="2026-01-15",
    )
    act_pro = create_submitted_activity(
        area["id"], submitter_user_id="analyst-1", amount_cents=1000000,
        primary_purpose_category="AFFORDABLE_HOUSING", lmi_benefit_pct=0.60,
        activity_date="2026-01-16",
    )

    full = validate_success(_review(
        api, act_full["id"],
        review_decision_payload("QUALIFY", allocation_method="FULL_COUNT"),
        "reviewer-1",
    ))
    pro = validate_success(_review(
        api, act_pro["id"],
        review_decision_payload("QUALIFY", allocation_method="PRO_RATA"),
        "reviewer-1",
    ))

    assert full["status"] == "QUALIFIED"
    assert full["qualified_amount_cents"] == 1000000
    assert pro["status"] == "QUALIFIED"
    assert pro["qualified_amount_cents"] == 600000
    assert get_area(area["id"])["qualified_cd_total_cents"] == 1600000


def test_cd_activity_pro_rata_rounding_and_full_benefit_equality(api):
    """PRD §3.4: "Under `PRO_RATA`, always permitted, only the LMI-benefit share
    counts: `qualified_amount_cents` is `amount_cents` multiplied by
    `lmi_benefit_pct`, rounded half up to whole cents — so identical inputs
    yield a strictly smaller qualified amount under `PRO_RATA` whenever
    `lmi_benefit_pct` lies strictly between 0 and 1."

    Design: Difficulty/dual_variant_calc/cd_activity_full_count_vs_pro_rata_diverge
    """
    area = create_active_area(
        area_code="AA-DV1B", census_tracts=["T1"], annual_cd_budget_cents=10000000,
    )
    # Half-cent rounding: 101 * 0.5 = 50.5 -> round half up -> 51 whole cents.
    act_round = create_submitted_activity(
        area["id"], submitter_user_id="analyst-1", amount_cents=101,
        lmi_benefit_pct=0.5, activity_date="2026-01-15",
    )
    rounded = qualify_activity(act_round["id"], "PRO_RATA", "reviewer-1")
    assert rounded["qualified_amount_cents"] == 51

    # At lmi_benefit_pct == 1 the PRO_RATA share equals the full amount (the
    # strict-smaller clause covers only 0 < pct < 1).
    act_full_benefit = create_submitted_activity(
        area["id"], submitter_user_id="analyst-1", amount_cents=1000000,
        lmi_benefit_pct=1.0, activity_date="2026-01-16",
    )
    full_benefit = qualify_activity(act_full_benefit["id"], "PRO_RATA", "reviewer-1")
    assert full_benefit["qualified_amount_cents"] == 1000000


# ---------------------------------------------------------------------------
# Queue A — Difficulty/non_linear_state_machine/cd_activity_disqualify_resubmit_cycle
# ---------------------------------------------------------------------------

def test_cd_activity_disqualify_resubmit_cycle(api):
    """PRD §3.4: "a `ComplianceAnalyst` may resubmit a `DISQUALIFIED` activity,
    provided the referenced area is `ACTIVE` (`ERR_AREA_NOT_ACTIVE`), which
    returns it to `SUBMITTED` while clearing `disqualify_reason`,
    `reviewed_by_user_id`, and `allocation_method` to null and resetting
    `qualified_amount_cents` to 0."
    PRD §3.4: "A successful qualification records `reviewed_by_user_id` and the
    `allocation_method`, computes `qualified_amount_cents`".

    Design: Difficulty/non_linear_state_machine/cd_activity_disqualify_resubmit_cycle
    """
    area = create_active_area(
        area_code="AA-NL2", census_tracts=["T1"], annual_cd_budget_cents=10000000,
    )
    activity = create_submitted_activity(
        area["id"], submitter_user_id="analyst-1",
        activity_type="QUALIFIED_INVESTMENT", amount_cents=1000000,
        primary_purpose_category="ECONOMIC_DEVELOPMENT", lmi_benefit_pct=0.60,
        activity_date="2026-02-01",
    )
    validate_success(_review(
        api, activity["id"],
        review_decision_payload("DISQUALIFY", disqualify_reason="insufficient documentation"),
        "reviewer-1",
    ))
    resubmitted = validate_success(
        api.resubmit_cd_activity(
            activity["id"], make_compliance_analyst_headers("analyst-1")
        )
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["disqualify_reason"] is None
    assert resubmitted["reviewed_by_user_id"] is None
    assert resubmitted["allocation_method"] is None
    assert resubmitted["qualified_amount_cents"] == 0

    qualified = validate_success(_review(
        api, activity["id"],
        review_decision_payload("QUALIFY", allocation_method="PRO_RATA"),
        "reviewer-2",
    ))
    assert qualified["status"] == "QUALIFIED"
    assert qualified["qualified_amount_cents"] == 600000
    assert qualified["disqualify_reason"] is None
    assert qualified["reviewed_by_user_id"] == "reviewer-2"


def test_cd_activity_resubmission_loop_may_repeat(api):
    """PRD §3.4: "The resubmission loop `DISQUALIFIED → SUBMITTED → QUALIFIED`
    or `DISQUALIFIED` may repeat indefinitely — the activity has no terminal
    state."
    PRD §3.4: "A disqualifying decision instead records the reviewer's
    `disqualify_reason` and `reviewed_by_user_id` and moves the activity to
    `DISQUALIFIED`; segregation of duties still applies."

    Design: Difficulty/non_linear_state_machine/cd_activity_disqualify_resubmit_cycle
    """
    area = create_active_area(
        area_code="AA-NL2B", census_tracts=["T1"], annual_cd_budget_cents=10000000,
    )
    activity = create_submitted_activity(
        area["id"], submitter_user_id="analyst-1", amount_cents=100000,
        activity_date="2026-02-01",
    )
    for round_no, reason in enumerate(
        ["insufficient documentation", "still insufficient"], start=1
    ):
        validate_success(_review(
            api, activity["id"],
            review_decision_payload("DISQUALIFY", disqualify_reason=reason),
            "reviewer-1",
        ))
        current = get_cd_activity(area["id"], activity["id"])
        assert current["status"] == "DISQUALIFIED"
        assert current["disqualify_reason"] == reason
        assert current["reviewed_by_user_id"] == "reviewer-1"
        if round_no < 2:
            resubmitted = validate_success(
                api.resubmit_cd_activity(
                    activity["id"], make_compliance_analyst_headers("analyst-1")
                )
            )
            assert resubmitted["status"] == "SUBMITTED"
            assert resubmitted["disqualify_reason"] is None


# ---------------------------------------------------------------------------
# Queue A — Difficulty/boundary_precision_check/full_count_lmi_threshold_boundary_051
# ---------------------------------------------------------------------------

def test_full_count_lmi_threshold_boundary_051(api):
    """PRD §3.4: "Under `FULL_COUNT`, permitted only when `lmi_benefit_pct` is
    at least 0.51 (otherwise `ERR_LMI_THRESHOLD_NOT_MET`), the entire
    `amount_cents` counts as qualified."

    Design: Difficulty/boundary_precision_check/full_count_lmi_threshold_boundary_051
    """
    area = create_active_area(
        area_code="AA-BP2", msa_code="16980", state_code="IL",
        census_tracts=["T1"], annual_cd_budget_cents=10000000,
    )
    act_hi = create_submitted_activity(
        area["id"], submitter_user_id="analyst-1",
        activity_type="QUALIFIED_INVESTMENT", amount_cents=2000000,
        primary_purpose_category="AFFORDABLE_HOUSING", lmi_benefit_pct=0.51,
        activity_date="2026-01-10",
    )
    act_lo = create_submitted_activity(
        area["id"], submitter_user_id="analyst-1",
        activity_type="QUALIFIED_INVESTMENT", amount_cents=2000000,
        primary_purpose_category="AFFORDABLE_HOUSING", lmi_benefit_pct=0.50,
        activity_date="2026-01-11",
    )

    qualified = validate_success(_review(
        api, act_hi["id"],
        review_decision_payload("QUALIFY", allocation_method="FULL_COUNT"),
        "reviewer-1",
    ))
    assert qualified["status"] == "QUALIFIED"
    assert qualified["qualified_amount_cents"] == 2000000

    rejected = _review(
        api, act_lo["id"],
        review_decision_payload("QUALIFY", allocation_method="FULL_COUNT"),
        "reviewer-1",
    )
    validate_error(rejected, ApiErrorId.ERR_LMI_THRESHOLD_NOT_MET)
    current = get_cd_activity(area["id"], act_lo["id"])
    assert current["status"] == "SUBMITTED"
    assert current["qualified_amount_cents"] == 0


def test_full_count_threshold_failure_still_allows_pro_rata(api):
    """PRD §3.4: "Under `FULL_COUNT`, permitted only when `lmi_benefit_pct` is
    at least 0.51 (otherwise `ERR_LMI_THRESHOLD_NOT_MET`), the entire
    `amount_cents` counts as qualified. Under `PRO_RATA`, always permitted, only
    the LMI-benefit share counts".

    Design: Difficulty/boundary_precision_check/full_count_lmi_threshold_boundary_051
    """
    area = create_active_area(
        area_code="AA-BP2B", msa_code="16980", state_code="IL",
        census_tracts=["T1"], annual_cd_budget_cents=10000000,
    )
    activity = create_submitted_activity(
        area["id"], submitter_user_id="analyst-1",
        activity_type="QUALIFIED_INVESTMENT", amount_cents=2000000,
        primary_purpose_category="AFFORDABLE_HOUSING", lmi_benefit_pct=0.50,
        activity_date="2026-01-10",
    )
    rejected = _review(
        api, activity["id"],
        review_decision_payload("QUALIFY", allocation_method="FULL_COUNT"),
        "reviewer-1",
    )
    validate_error(rejected, ApiErrorId.ERR_LMI_THRESHOLD_NOT_MET)

    # PRO_RATA is always permitted; the failed FULL_COUNT attempt left the
    # activity SUBMITTED, so the same activity can be decided again.
    qualified = validate_success(_review(
        api, activity["id"],
        review_decision_payload("QUALIFY", allocation_method="PRO_RATA"),
        "reviewer-1",
    ))
    assert qualified["status"] == "QUALIFIED"
    assert qualified["qualified_amount_cents"] == 1000000


# ---------------------------------------------------------------------------
# Queue A — Difficulty/priority_pair_validation_conflict/review_decision_conflict_sod_beats_budget
# ---------------------------------------------------------------------------

def test_review_decision_conflict_sod_beats_budget(api):
    """PRD §2.11: "on a qualification review, segregation of duties is evaluated
    before the LMI benefit threshold, which precedes the area-active
    requirement, which in turn precedes the budget headroom check — a reviewer
    who submitted the activity themselves will always see
    `ERR_SEGREGATION_OF_DUTIES` rather than a later check's error."

    Design: Difficulty/priority_pair_validation_conflict/review_decision_conflict_sod_beats_budget
    """
    area = create_active_area(
        area_code="AA-PC2", msa_code="19100", state_code="TX",
        census_tracts=["T1"], annual_cd_budget_cents=100000,
    )
    # PRO_RATA would qualify 600000 against a 100000 budget: the fiscal check
    # would fail too, but segregation of duties surfaces first.
    activity = create_submitted_activity(
        area["id"], submitter_user_id="analyst-1", amount_cents=1000000,
        primary_purpose_category="REVITALIZATION_STABILIZATION",
        lmi_benefit_pct=0.60, activity_date="2026-03-01",
    )
    resp = api.review_cd_activity(
        activity["id"],
        review_decision_payload("QUALIFY", allocation_method="PRO_RATA"),
        # The "reviewer" here is the same operator who submitted the activity.
        make_qualification_reviewer_headers("analyst-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    current = get_cd_activity(area["id"], activity["id"])
    assert current["status"] == "SUBMITTED"
    assert current["qualified_amount_cents"] == 0


def test_review_decision_sod_beats_lmi_threshold(api):
    """PRD §3.4: "The guards run in the fixed order of §2.11 — segregation of
    duties first (a reviewer whose `X-User-ID` equals the activity's
    `submitted_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`), then
    the full-count benefit threshold, then the area-active requirement, and
    finally the budget check — so a self-review attempt surfaces before any
    substantive defect".

    Design: Difficulty/priority_pair_validation_conflict/review_decision_conflict_sod_beats_budget
    """
    area = create_active_area(
        area_code="AA-PC2C", msa_code="19100", state_code="TX",
        census_tracts=["T1"], annual_cd_budget_cents=10000000,
    )
    # FULL_COUNT with pct 0.50 would trip the LMI threshold, but the
    # self-review attempt surfaces first.
    activity = create_submitted_activity(
        area["id"], submitter_user_id="analyst-1", amount_cents=100000,
        lmi_benefit_pct=0.50, activity_date="2026-03-01",
    )
    resp = api.review_cd_activity(
        activity["id"],
        review_decision_payload("QUALIFY", allocation_method="FULL_COUNT"),
        make_qualification_reviewer_headers("analyst-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert get_cd_activity(area["id"], activity["id"])["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Queue A — Difficulty/priority_pair_validation_conflict/resubmit_conflict_state_beats_referential
# ---------------------------------------------------------------------------

def test_resubmit_conflict_state_beats_referential(api, cra_officer_headers):
    """PRD §2.11: "State legality — a trigger that does not match the resource's
    current state, or any action on a terminal-state resource, yields
    `ERR_INVALID_STATE`." (tier 4)
    PRD §2.11: "Business referential — the referenced area must be `ACTIVE`, the
    loan's tract must belong to the area, and a staged branch's application must
    be `APPROVED`." (tier 8)
    PRD §2.11: "When several rules could reject the same request, the server
    evaluates them in a fixed tier order so that the surfaced error is
    deterministic".

    Design: Difficulty/priority_pair_validation_conflict/resubmit_conflict_state_beats_referential
    """
    area = create_active_area(
        area_code="AA-PC1", census_tracts=["T1"], annual_cd_budget_cents=10000000,
    )
    activity = create_submitted_activity(
        area["id"], submitter_user_id="analyst-1", activity_type="CD_SERVICE",
        amount_cents=100000, primary_purpose_category="COMMUNITY_SERVICES_LMI",
        lmi_benefit_pct=0.60, activity_date="2026-01-15",
    )
    qualify_activity(activity["id"], "PRO_RATA", "reviewer-1")
    validate_success(api.retire_assessment_area(area["id"], cra_officer_headers))

    # QUALIFIED is not a from-state for resubmit (tier 4) and the area is
    # RETIRED (tier 8): the state error must surface.
    resp = api.resubmit_cd_activity(
        activity["id"], make_compliance_analyst_headers("analyst-1")
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_cd_activity(area["id"], activity["id"])
    assert current["status"] == "QUALIFIED"


def test_resubmit_disqualified_activity_with_retired_area_fails_referential(
    api, cra_officer_headers,
):
    """PRD §3.4: "a `ComplianceAnalyst` may resubmit a `DISQUALIFIED` activity,
    provided the referenced area is `ACTIVE` (`ERR_AREA_NOT_ACTIVE`)".

    Design: Difficulty/priority_pair_validation_conflict/resubmit_conflict_state_beats_referential
    """
    area = create_active_area(
        area_code="AA-PC1B", census_tracts=["T1"], annual_cd_budget_cents=10000000,
    )
    activity = create_submitted_activity(
        area["id"], submitter_user_id="analyst-1", amount_cents=100000,
        activity_date="2026-01-15",
    )
    validate_success(_review(
        api, activity["id"],
        review_decision_payload("DISQUALIFY", disqualify_reason="insufficient documentation"),
        "reviewer-1",
    ))
    validate_success(api.retire_assessment_area(area["id"], cra_officer_headers))

    # DISQUALIFIED is a legal from-state for resubmit, so only the
    # area-active referential check can fail.
    resp = api.resubmit_cd_activity(
        activity["id"], make_compliance_analyst_headers("analyst-1")
    )
    validate_error(resp, ApiErrorId.ERR_AREA_NOT_ACTIVE)
    assert get_cd_activity(area["id"], activity["id"])["status"] == "DISQUALIFIED"
