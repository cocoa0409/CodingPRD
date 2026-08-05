"""Sample results: advisory grading, the nitrate MCL boundary, the parallel
well status dimensions, and the confirmed-UNSAFE contamination cascade.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_applicant_headers,
    factories as f, fixtures as fx,
)

OFFICER = TEST_USERS["health_officer_headers"]
LAB = TEST_USERS["lab_analyst_headers"]


# --------------------------------------------------------------------------
# dual_variant_calc / nitrate_provisional_vs_confirmed_diverge
# --------------------------------------------------------------------------
def test_nitrate_provisional_advisory_confirmed_unsafe(api):
    """PRD §3.5: "The provisional level, advisory_level_provisional, applies the
    grading rule to this sample's own nitrate value, ignoring history."
    PRD §3.5: "Because the confirmed level blends in an elevated prior sample, it
    can reach UNSAFE while the provisional level for the same sample remains only
    ADVISORY."

    Design: Difficulty/dual_variant_calc/nitrate_provisional_vs_confirmed_diverge
    """
    ctx = fx.setup_active_well(api)
    fx.resulted_sample(api, ctx.well_id, ctx.applicant_id,
                       result_overrides={"nitrate_mg_l": 12.0, "analyzed_on": "2026-05-03T00:00:00Z"},
                       collected_on="2026-05-02T00:00:00Z")
    second = fx.submit_sample_in_analysis(api, ctx.well_id, ctx.applicant_id,
                                          collected_on="2026-05-05T00:00:00Z")
    resp = api.create_sample_result(
        f.sample_result_payload(second["id"], nitrate_mg_l=8.0,
                                analyzed_on="2026-05-06T00:00:00Z"), LAB)
    result = validate_success(resp, 201)
    assert result["advisory_level_provisional"] == "ADVISORY"
    assert result["advisory_level_confirmed"] == "UNSAFE"


def test_nitrate_confirmed_unsafe_average_sets_well_unsafe(api):
    """PRD §3.5: "The confirmed level drives the well's health dimension. The
    system recomputes potability_status from the confirmed grade of this newly
    recorded result: a SAFE confirmed grade sets potability to POTABLE, an
    ADVISORY grade sets it to ADVISORY, and an UNSAFE grade sets it to UNSAFE."

    Design: Difficulty/dual_variant_calc/nitrate_provisional_vs_confirmed_diverge
    """
    ctx = fx.setup_active_well(api)
    fx.resulted_sample(api, ctx.well_id, ctx.applicant_id,
                       result_overrides={"nitrate_mg_l": 12.0, "analyzed_on": "2026-05-03T00:00:00Z"},
                       collected_on="2026-05-02T00:00:00Z")
    second = fx.submit_sample_in_analysis(api, ctx.well_id, ctx.applicant_id,
                                          collected_on="2026-05-05T00:00:00Z")
    get_success_data(api.create_sample_result(
        f.sample_result_payload(second["id"], nitrate_mg_l=8.0,
                                analyzed_on="2026-05-06T00:00:00Z"), LAB))
    well = get_success_data(api.get_well(ctx.well_id, OFFICER))
    assert well["potability_status"] == "UNSAFE"


# --------------------------------------------------------------------------
# boundary_precision_check / nitrate_exactly_at_mcl_is_unsafe
# --------------------------------------------------------------------------
def test_nitrate_exactly_at_mcl_is_unsafe(api):
    """PRD §3.5: "the grade is UNSAFE if either bacterial reading is PRESENT, or
    the lead value is at least the lead action level of 15.0 parts per billion,
    or the nitrate value is at least the nitrate maximum contaminant level of
    10.0 milligrams per liter".

    Design: Difficulty/boundary_precision_check/nitrate_exactly_at_mcl_is_unsafe
    """
    ctx = fx.setup_active_well(api)
    _, result = fx.resulted_sample(
        api, ctx.well_id, ctx.applicant_id,
        result_overrides={"nitrate_mg_l": 10.0})
    assert result["advisory_level_provisional"] == "UNSAFE"
    assert result["advisory_level_confirmed"] == "UNSAFE"


def test_nitrate_just_below_mcl_is_advisory(api):
    """PRD §3.5: "otherwise the grade is ADVISORY if the nitrate value is at
    least the nitrate advisory level of 5.0 milligrams per liter; otherwise the
    grade is SAFE."

    Design: Difficulty/boundary_precision_check/nitrate_exactly_at_mcl_is_unsafe
    """
    ctx = fx.setup_active_well(api)
    _, result = fx.resulted_sample(
        api, ctx.well_id, ctx.applicant_id,
        result_overrides={"nitrate_mg_l": 9.99})
    assert result["advisory_level_provisional"] == "ADVISORY"
    assert result["advisory_level_confirmed"] == "ADVISORY"


# --------------------------------------------------------------------------
# non_linear_state_machine / well_registry_and_potability_evolve_independently
# --------------------------------------------------------------------------
def test_safe_result_sets_potable_while_registry_stays_active(api):
    """PRD §2.6: "Neither dimension constrains the other: a well can be ACTIVE
    while UNSAFE, or INACTIVE while POTABLE."
    PRD §3.5: "a SAFE confirmed grade sets potability to POTABLE".

    Design: Difficulty/non_linear_state_machine/well_registry_and_potability_evolve_independently
    """
    ctx = fx.setup_active_well(api)
    _, result = fx.resulted_sample(api, ctx.well_id, ctx.applicant_id,
                                   result_overrides={"nitrate_mg_l": 2.0})
    assert result["advisory_level_confirmed"] == "SAFE"
    well = get_success_data(api.get_well(ctx.well_id, OFFICER))
    assert well["registry_status"] == "ACTIVE"
    assert well["potability_status"] == "POTABLE"


def test_deactivate_leaves_potability_untouched(api):
    """PRD §2.6: "Neither dimension constrains the other: a well can be ACTIVE
    while UNSAFE, or INACTIVE while POTABLE."
    PRD §3.5: "a SAFE confirmed grade sets potability to POTABLE".

    Design: Difficulty/non_linear_state_machine/well_registry_and_potability_evolve_independently
    """
    ctx = fx.setup_active_well(api)
    fx.resulted_sample(api, ctx.well_id, ctx.applicant_id,
                       result_overrides={"nitrate_mg_l": 2.0})
    deactivated = get_success_data(api.deactivate_well(ctx.well_id, OFFICER))
    assert deactivated["registry_status"] == "INACTIVE"
    assert deactivated["potability_status"] == "POTABLE"


# --------------------------------------------------------------------------
# transitive_cascade / unsafe_result_cascade_result_sample_case_well_advisory
# --------------------------------------------------------------------------
def test_unsafe_result_opens_case_and_bumps_well_counts(api):
    """PRD §3.5: "the system auto-opens a contamination case on the well in
    status OPEN with its source_sample_id pointing at the triggering sample, and
    as that case's own entry side effects it sets the well's potability_status to
    UNSAFE, auto-issues an active advisory whose source_case_id is the new case,
    and increments the well's active_advisory_count by one."

    Design: Difficulty/transitive_cascade/unsafe_result_cascade_result_sample_case_well_advisory
    """
    ctx = fx.setup_well_with_cascade_case(api)
    assert ctx.sample["status"] == "RESULTED"
    assert ctx.well["potability_status"] == "UNSAFE"
    assert ctx.well["active_advisory_count"] == 1
    cases_resp = api.list_contamination_cases(OFFICER, params={"well_id": ctx.well_id})
    open_cases = [c for c in cases_resp.json()["data"] if c["status"] == "OPEN"]
    assert len(open_cases) == 1


def test_unsafe_cascade_auto_issues_advisory_from_case(api):
    """PRD §3.5: "auto-issues an active advisory whose source_case_id is the new
    case, and increments the well's active_advisory_count by one."

    Design: Difficulty/transitive_cascade/unsafe_result_cascade_result_sample_case_well_advisory
    """
    ctx = fx.setup_well_with_cascade_case(api)
    assert ctx.advisory is not None
    assert ctx.advisory["status"] == "ACTIVE"
    assert ctx.advisory["source_case_id"] == ctx.case["id"]


# --------------------------------------------------------------------------
# Corner: validations
# --------------------------------------------------------------------------
def test_negative_nitrate_result_rejected(api):
    """PRD §2.9: "then, specifically for a sample result, the non-negativity of
    concentrations (ERR_ANALYTE_OUT_OF_RANGE)".
    PRD §3.5: "Both concentrations must be non-negative; a negative nitrate_mg_l
    or lead_ppb is rejected with ERR_ANALYTE_OUT_OF_RANGE (HTTP 400)."

    Design: Corner/validations/sample_result_negative_nitrate_returns_out_of_range
    """
    ctx = fx.setup_active_well(api)
    sample = fx.submit_sample_in_analysis(api, ctx.well_id, ctx.applicant_id)
    resp = api.create_sample_result(
        f.sample_result_payload(sample["id"], nitrate_mg_l=-1.0), LAB)
    validate_error(resp, ApiErrorId.ERR_ANALYTE_OUT_OF_RANGE)


def test_water_sample_on_proposed_well_rejected(api):
    """PRD §3.4: "A well owner submits a water sample only against an ACTIVE
    well; a submission against a well in any other registry status is rejected
    with ERR_WELL_NOT_ACTIVE (HTTP 409)."

    Design: Corner/validations/water_sample_on_proposed_well_returns_well_not_active
    """
    aquifer = fx.create_aquifer(api, sensitivity="LOW")
    applicant = fx.create_applicant(api)
    well = fx.create_well(api, applicant["id"], aquifer["id"])  # PROPOSED
    payload = f.water_sample_payload(well["id"], applicant["id"])
    resp = api.create_water_sample(payload, make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_WELL_NOT_ACTIVE)
