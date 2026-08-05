"""Needs-assessment review cycle, recommended care level, and VA / benefit
guidance estimates with supersession and optimistic concurrency.
"""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated, get_success_data,
    create_advisor, create_family, create_inquiry, assign_advisor, set_clock,
    make_advisor_headers,
    build_scenario, setup_guidance_ready,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _run_revision_cycle(api):
    """DRAFT -> SUBMITTED -> REVISION_REQUESTED -> DRAFT -> SUBMITTED -> APPROVED."""
    set_clock(api, "2026-06-01T00:00:00Z")
    ann = create_advisor(api, full_name="Ann Reyes")
    family = create_family(api)
    inquiry = create_inquiry(api, family["id"])
    assign_advisor(api, inquiry["id"], ann["id"])
    ahdr = make_advisor_headers(ann["id"])
    s = get_success_data(api.create_assessment(
        {"inquiry_id": inquiry["id"], "adl_score": 6, "cognitive_score": 4,
         "mobility_score": 5, "budget_monthly_cents": 520000,
         "gross_monthly_income_cents": 320000, "va_eligible": True,
         "marital_status": "MARRIED"}, ahdr))
    api.submit_assessment(s["id"], ahdr)
    api.review_assessment(s["id"], {"decision": "REQUEST_REVISION",
                                    "revision_note": "Confirm the mobility score."}, ADMIN)
    api.update_assessment(s["id"], {"adl_score": 7}, ahdr)
    api.submit_assessment(s["id"], ahdr)
    api.review_assessment(s["id"], {"decision": "APPROVE"}, ADMIN)
    return ann, inquiry, s["id"]


def test_revision_cycle_records_one_revision_and_clears_note(api):
    """PRD §3.4: "A `REQUEST_REVISION` decision moves the assessment `SUBMITTED →
    REVISION_REQUESTED`, stores the `revision_note`, and increments `revision_count`
    by 1."
    PRD §3.4: "when the row was in `REVISION_REQUESTED` — returns it to `DRAFT` and
    clears `revision_note`."

    Design: Difficulty/non_linear_state_machine/assessment_revision_cycle_draft_submitted_revision_requested_draft
    """
    ann, inquiry, sid = _run_revision_cycle(api)
    s = validate_success(api.get_assessment(sid, ADMIN))
    assert s["revision_count"] == 1
    assert s["status"] == "APPROVED"
    assert s["revision_note"] is None


def test_revision_cycle_ends_approved_with_ceiling_and_inquiry_assessed(api):
    """PRD §3.4: "An `APPROVE` decision moves the assessment `SUBMITTED → APPROVED`,
    sets its `affordability_ceiling_cents` (see below), and moves the linked inquiry
    `ASSIGNED → ASSESSED` (bumping the inquiry's `version`)."
    PRD §3.4: "It is the assessment's `budget_monthly_cents` multiplied by a stretch
    factor of 1.10, rounded half up to whole cents, plus the current
    `benefit_offset_cents`."

    Design: Difficulty/non_linear_state_machine/assessment_revision_cycle_draft_submitted_revision_requested_draft
    """
    ann, inquiry, sid = _run_revision_cycle(api)
    s = validate_success(api.get_assessment(sid, ADMIN))
    assert s["recommended_care_level"] == "ASSISTED_LIVING"
    assert s["affordability_ceiling_cents"] == 572000
    inq = validate_success(api.get_inquiry(inquiry["id"], ADMIN))
    assert inq["status"] == "ASSESSED"


def test_recommended_care_level_cognitive_override_outranks_acuity_band(api):
    """PRD §3.4: "the branches are evaluated in this pinned order, first match wins:
    if the acuity total is at least 25 the recommendation is `SKILLED_NURSING`;
    otherwise if `cognitive_score` is at least 8 it is `MEMORY_CARE`".

    Design: Corner/calculations/recommended_care_level_cognitive_override_outranks_the_acuity_band
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    ann = create_advisor(api, full_name="Ann Reyes")
    family = create_family(api)
    inquiry = create_inquiry(api, family["id"])
    assign_advisor(api, inquiry["id"], ann["id"])
    resp = api.create_assessment(
        {"inquiry_id": inquiry["id"], "adl_score": 4, "cognitive_score": 8,
         "mobility_score": 4, "budget_monthly_cents": 520000,
         "gross_monthly_income_cents": 320000, "va_eligible": False,
         "marital_status": "SINGLE"}, make_advisor_headers(ann["id"]))
    s = validate_success(resp, 201)
    assert s["recommended_care_level"] == "MEMORY_CARE"
    assert s["status"] == "DRAFT"
    assert s["author_advisor_id"] == ann["id"]
    assert s["affordability_ceiling_cents"] == 0
    assert s["revision_count"] == 0


def test_patching_an_approved_assessment_returns_invalid_state(api):
    """PRD §3.4: "A draft assessment may be edited only by its author (`X-User-ID`
    equal to `author_advisor_id`) and only while it is in `DRAFT` or
    `REVISION_REQUESTED`; a non-author editor or any other state yields the
    respective ownership or state error."

    Design: Corner/state_machines/patching_an_approved_assessment_returns_assessment_invalid_state
    """
    sc = build_scenario(api, "approved")
    sid = sc["assessment"]["id"]
    resp = api.update_assessment(sid, {"budget_monthly_cents": 900000}, sc["advisor_headers"])
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_INVALID_STATE)
    s = validate_success(api.get_assessment(sid, ADMIN))
    assert s["budget_monthly_cents"] == 520000
    assert s["affordability_ceiling_cents"] == 572000
    assert s["status"] == "APPROVED"


def test_va_aid_attendance_married_estimate_follows_pinned_steps(api):
    """PRD §3.5: "sets `unreimbursed_medical_cents` to the larger of 0 and that
    projected care cost minus 5% of `gross_monthly_income_cents` (the 5% figure
    rounded half up to whole cents before subtraction)."
    PRD §3.5: "for `VA_AID_ATTENDANCE` with `marital_status` `MARRIED` the cap is
    276000 cents".

    Design: Corner/calculations/va_aid_attendance_married_estimate_follows_pinned_step_order
    """
    out = setup_guidance_ready(api, va_eligible=True, marital_status="MARRIED",
                               budget_monthly_cents=520000,
                               gross_monthly_income_cents=320000, with_match=True)
    g = validate_success(api.create_guidance(
        {"inquiry_id": out["inquiry"]["id"], "benefit_type": "VA_AID_ATTENDANCE",
         "expected_assessment_version": out["assessment_version"]},
        out["counselor_headers"]), 201)
    assert g["unreimbursed_medical_cents"] == 504000
    assert g["countable_income_cents"] == 0
    assert g["estimated_monthly_benefit_cents"] == 276000
    assert g["status"] == "ISSUED"
    assert g["counselor_advisor_id"] == out["counselor"]["id"]
    assert g["assessment_id"] == out["assessment"]["id"]
    s = validate_success(api.get_assessment(out["assessment"]["id"], ADMIN))
    assert s["benefit_offset_cents"] == 276000
    assert s["affordability_ceiling_cents"] == 848000
    m = validate_success(api.get_match(out["match"]["id"], ADMIN))
    assert m["fit_score"] == 97.00
    assert m["quoted_monthly_rate_cents"] == 500000


def test_va_survivor_pension_reduced_by_positive_countable_income(api):
    """PRD §3.5: "**Step 2** sets `countable_income_cents` to the larger of 0 and
    `gross_monthly_income_cents` minus `unreimbursed_medical_cents`."
    PRD §3.5: "for `VA_SURVIVOR_PENSION` it is 149800".

    Design: Corner/calculations/va_survivor_pension_estimate_reduced_by_positive_countable_income
    """
    out = setup_guidance_ready(api, va_eligible=True, marital_status="WIDOWED",
                               budget_monthly_cents=300000,
                               gross_monthly_income_cents=400000)
    g = validate_success(api.create_guidance(
        {"inquiry_id": out["inquiry"]["id"], "benefit_type": "VA_SURVIVOR_PENSION",
         "expected_assessment_version": out["assessment_version"]},
        out["counselor_headers"]), 201)
    assert g["unreimbursed_medical_cents"] == 280000
    assert g["countable_income_cents"] == 120000
    assert g["estimated_monthly_benefit_cents"] == 29800
    s = validate_success(api.get_assessment(out["assessment"]["id"], ADMIN))
    assert s["affordability_ceiling_cents"] == 359800


def test_second_guidance_supersedes_first_and_reissues_ceiling(api):
    """PRD §3.5: "At level 1 the new guidance is created `ISSUED`, and any prior
    guidance for the same `assessment_id` that was `ISSUED` moves to `SUPERSEDED`.
    At level 2 the assessment's `benefit_offset_cents` becomes the new estimate, its
    `affordability_ceiling_cents` is recomputed, and its `version` is incremented by
    1."

    Design: Corner/calculations/second_benefit_guidance_supersedes_the_first_and_reissues_the_ceiling
    """
    out = setup_guidance_ready(api, va_eligible=True, marital_status="MARRIED",
                               budget_monthly_cents=520000,
                               gross_monthly_income_cents=320000)
    inquiry_id = out["inquiry"]["id"]
    g1 = validate_success(api.create_guidance(
        {"inquiry_id": inquiry_id, "benefit_type": "VA_AID_ATTENDANCE",
         "expected_assessment_version": out["assessment_version"]},
        out["counselor_headers"]), 201)
    s_after = validate_success(api.get_assessment(out["assessment"]["id"], ADMIN))
    g2 = validate_success(api.create_guidance(
        {"inquiry_id": inquiry_id, "benefit_type": "LTC_INSURANCE",
         "expected_assessment_version": s_after["version"]},
        out["counselor_headers"]), 201)
    assert validate_success(api.get_guidance(g1["id"], ADMIN))["status"] == "SUPERSEDED"
    assert g2["status"] == "ISSUED"
    assert g2["estimated_monthly_benefit_cents"] == 200000
    s = validate_success(api.get_assessment(out["assessment"]["id"], ADMIN))
    assert s["benefit_offset_cents"] == 200000
    assert s["affordability_ceiling_cents"] == 772000
    rows, _ = validate_paginated(api.list_guidances(ADMIN, params={"inquiry_id": inquiry_id}))
    assert len(rows) == 2


def test_guidance_create_with_stale_assessment_version_rejected(api):
    """PRD §2.8: "Issuing a benefit guidance — the benefit-guidance-creation
    endpoint — requires an `expected_assessment_version` field carrying the client's
    last observed `version` of the target `NeedsAssessment`. If that value does not
    equal the assessment's current `version`, the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/guidance_create_with_stale_assessment_version_returns_stale_version
    """
    out = setup_guidance_ready(api, va_eligible=True, marital_status="MARRIED",
                               budget_monthly_cents=520000,
                               gross_monthly_income_cents=320000)
    inquiry_id = out["inquiry"]["id"]
    stale_version = out["assessment_version"]
    g1 = validate_success(api.create_guidance(
        {"inquiry_id": inquiry_id, "benefit_type": "VA_AID_ATTENDANCE",
         "expected_assessment_version": stale_version}, out["counselor_headers"]), 201)
    resp = api.create_guidance(
        {"inquiry_id": inquiry_id, "benefit_type": "LTC_INSURANCE",
         "expected_assessment_version": stale_version}, out["counselor_headers"])
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert validate_success(api.get_guidance(g1["id"], ADMIN))["status"] == "ISSUED"
    s = validate_success(api.get_assessment(out["assessment"]["id"], ADMIN))
    assert s["benefit_offset_cents"] == 276000
    assert s["affordability_ceiling_cents"] == 848000
    rows, _ = validate_paginated(api.list_guidances(ADMIN, params={"inquiry_id": inquiry_id}))
    assert len(rows) == 1


def test_guidance_for_non_va_eligible_assessment_rejected(api):
    """PRD §3.5: "the assessment's `va_eligible` must be true, else
    `ERR_GUIDANCE_NOT_ELIGIBLE`."

    Design: Corner/validations/benefit_guidance_for_non_va_eligible_assessment_returns_guidance_not_eligible
    """
    out = setup_guidance_ready(api, va_eligible=False, marital_status="MARRIED",
                               budget_monthly_cents=520000,
                               gross_monthly_income_cents=320000)
    resp = api.create_guidance(
        {"inquiry_id": out["inquiry"]["id"], "benefit_type": "VA_AID_ATTENDANCE",
         "expected_assessment_version": out["assessment_version"]},
        out["counselor_headers"])
    validate_error(resp, ApiErrorId.ERR_GUIDANCE_NOT_ELIGIBLE)
    s = validate_success(api.get_assessment(out["assessment"]["id"], ADMIN))
    assert s["benefit_offset_cents"] == 0
    assert s["affordability_ceiling_cents"] == 572000
    rows, _ = validate_paginated(api.list_guidances(ADMIN, params={"inquiry_id": out["inquiry"]["id"]}))
    assert rows == []
