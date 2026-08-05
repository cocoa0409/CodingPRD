"""Community-program linkage: tier eligibility, OCC stale-version guard, and
supersession of the prior non-terminal linkage."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, LOW_TIER_MEASURES,
    setup_active_care_plan,
)

INTAKE = TEST_USERS["intake_headers"]
SUPER = TEST_USERS["supervisor_headers"]


# --- A14: cross_entity_state_dependency / linkage_requires_assessment_tier_elevated

def test_link_low_tier_assessment_rejected(api):
    """PRD §3.8: "the referenced assessment must be FINALIZED with a fall_risk_tier
    of either MODERATE or HIGH; an assessment whose tier is LOW (or an assessment
    not finalized) makes the patient ineligible, and the request is rejected with
    ERR_TIER_NOT_ELIGIBLE."

    Design: Difficulty/cross_entity_state_dependency/linkage_requires_assessment_tier_elevated
    """
    ctx = setup_active_care_plan(api, assessment_overrides=dict(LOW_TIER_MEASURES))
    plan = get_success_data(api.get_care_plan(ctx["care_plan"]["id"], INTAKE))
    resp = api.create_community_linkage(
        {"patient_id": ctx["patient"]["id"], "care_plan_id": ctx["care_plan"]["id"],
         "assessment_id": ctx["assessment"]["id"], "program_name": "MATTER_OF_BALANCE",
         "expected_care_plan_version": plan["version"]},
        INTAKE,
    )
    validate_error(resp, ApiErrorId.ERR_TIER_NOT_ELIGIBLE, 422)


def test_link_low_tier_assessment_returns_422_status(api):
    """PRD §3.8: "an assessment whose tier is LOW ... makes the patient ineligible,
    and the request is rejected with ERR_TIER_NOT_ELIGIBLE."

    Design: Difficulty/cross_entity_state_dependency/linkage_requires_assessment_tier_elevated
    """
    ctx = setup_active_care_plan(api, assessment_overrides=dict(LOW_TIER_MEASURES))
    plan = get_success_data(api.get_care_plan(ctx["care_plan"]["id"], INTAKE))
    assert ctx["assessment"]["fall_risk_tier"] == "LOW"
    resp = api.create_community_linkage(
        {"patient_id": ctx["patient"]["id"], "care_plan_id": ctx["care_plan"]["id"],
         "assessment_id": ctx["assessment"]["id"], "program_name": "MATTER_OF_BALANCE",
         "expected_care_plan_version": plan["version"]},
        INTAKE,
    )
    assert resp.status_code == 422


# --- B: corner_linkage_occ_stale_plan_version_conflict -----------------------

def test_stale_plan_version_on_second_linkage_rejected(api):
    """PRD §2.5: "If that value does not equal the plan's current version at the
    moment of the write, the request is rejected with ERR_STALE_PLAN_VERSION (HTTP
    412), because the client has not observed a supersession that already advanced
    the plan."

    Design: Corner/cross_cutting/corner_linkage_occ_stale_plan_version_conflict
    """
    ctx = setup_active_care_plan(api)  # HIGH tier, eligible
    v0 = get_success_data(api.get_care_plan(ctx["care_plan"]["id"], INTAKE))["version"]
    link1 = get_success_data(api.create_community_linkage(
        {"patient_id": ctx["patient"]["id"], "care_plan_id": ctx["care_plan"]["id"],
         "assessment_id": ctx["assessment"]["id"], "program_name": "MATTER_OF_BALANCE",
         "expected_care_plan_version": v0}, INTAKE))
    # v0 is now stale (the create above advanced the plan version).
    resp = api.create_community_linkage(
        {"patient_id": ctx["patient"]["id"], "care_plan_id": ctx["care_plan"]["id"],
         "assessment_id": ctx["assessment"]["id"], "program_name": "STEPPING_ON",
         "expected_care_plan_version": v0}, INTAKE)
    validate_error(resp, ApiErrorId.ERR_STALE_PLAN_VERSION, 412)
    link1_after = get_success_data(api.get_community_linkage(link1["id"], INTAKE))
    assert link1_after["status"] == "REFERRED"


# --- B: corner_linkage_supersede_withdraws_prior -----------------------------

def test_fresh_linkage_supersedes_prior(api):
    """PRD §3.8: "Creating a fresh linkage supersedes any prior linkage on the same
    plan that is still in REFERRED or ENROLLED, moving that prior linkage to the
    terminal WITHDRAWN state as a side effect of the create ... A newly created
    linkage opens in REFERRED."

    Design: Corner/cross_cutting/corner_linkage_supersede_withdraws_prior
    """
    ctx = setup_active_care_plan(api)  # HIGH tier
    v1 = get_success_data(api.get_care_plan(ctx["care_plan"]["id"], INTAKE))["version"]
    link1 = get_success_data(api.create_community_linkage(
        {"patient_id": ctx["patient"]["id"], "care_plan_id": ctx["care_plan"]["id"],
         "assessment_id": ctx["assessment"]["id"], "program_name": "MATTER_OF_BALANCE",
         "expected_care_plan_version": v1}, INTAKE))
    v2 = get_success_data(api.get_care_plan(ctx["care_plan"]["id"], INTAKE))["version"]
    link2 = get_success_data(api.create_community_linkage(
        {"patient_id": ctx["patient"]["id"], "care_plan_id": ctx["care_plan"]["id"],
         "assessment_id": ctx["assessment"]["id"], "program_name": "OTAGO",
         "expected_care_plan_version": v2}, INTAKE))
    assert get_success_data(api.get_community_linkage(link1["id"], INTAKE))["status"] == "WITHDRAWN"
    assert get_success_data(api.get_community_linkage(link2["id"], INTAKE))["status"] == "REFERRED"
