"""Resource temporal overlap: closed recruitment-step intervals (touching
conflicts) vs half-open employment intervals (adjacency allowed) (PRD §3.4, §3.6).

Queue A / Difficulty — rule `resource_temporal_overlap`.
"""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_recruiting_perm_case, add_recruitment_step,
    setup_two_h1b_petitions_same_beneficiary, make_employer_agent_headers,
)

USCIS = TEST_USERS["uscis_officer_headers"]


def test_recruitment_step_touching_endpoint_conflicts(api):
    """PRD §3.4: "here the interval is **closed** on both ends — the span runs
    inclusively from `start_date` through `end_date`, so two same-type steps that
    merely touch at an endpoint (one ends exactly where the next begins) still
    conflict and the create is rejected with `ERR_RECRUITMENT_STEP_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/recruitment_step_closed_interval_adjacency_conflicts
    """
    employer, pwd, pc = setup_recruiting_perm_case()
    hdr = make_employer_agent_headers(employer["id"])
    add_recruitment_step(employer["id"], pc["id"], step_type="JOB_ORDER",
                         start_date="2026-05-01T00:00:00Z", end_date="2026-05-31T00:00:00Z")
    res = api.create_recruitment_step(
        {"perm_case_id": pc["id"], "step_type": "JOB_ORDER",
         "start_date": "2026-05-31T00:00:00Z", "end_date": "2026-06-10T00:00:00Z"}, hdr)
    validate_error(res, ApiErrorId.ERR_RECRUITMENT_STEP_OVERLAP, expected_status=409)


def test_recruitment_step_genuine_overlap_conflicts(api):
    """PRD §3.4: "Two `ACTIVE` steps of the *same* `step_type` on one case may not
    overlap in time, and here the interval is **closed** on both ends".

    Design: Difficulty/resource_temporal_overlap/recruitment_step_closed_interval_adjacency_conflicts
    """
    employer, pwd, pc = setup_recruiting_perm_case()
    hdr = make_employer_agent_headers(employer["id"])
    add_recruitment_step(employer["id"], pc["id"], step_type="JOB_ORDER",
                         start_date="2026-05-01T00:00:00Z", end_date="2026-05-31T00:00:00Z")
    res = api.create_recruitment_step(
        {"perm_case_id": pc["id"], "step_type": "JOB_ORDER",
         "start_date": "2026-05-15T00:00:00Z", "end_date": "2026-06-10T00:00:00Z"}, hdr)
    validate_error(res, ApiErrorId.ERR_RECRUITMENT_STEP_OVERLAP, expected_status=409)


def test_employment_adjacency_at_boundary_approves(api):
    """PRD §3.6: "That interval is **half-open**, so two petitions that merely abut
    — one ending exactly when the next begins — do not conflict, whereas any
    genuine overlap is rejected with `ERR_EMPLOYMENT_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/employment_half_open_adjacency_allowed
    """
    ctx = setup_two_h1b_petitions_same_beneficiary(
        pet1_start="2026-10-01T00:00:00Z", pet1_end="2027-10-01T00:00:00Z",
        pet2_start="2027-10-01T00:00:00Z", pet2_end="2028-10-01T00:00:00Z")
    approved = validate_success(
        api.transition_h1b_petition(ctx["petition2"]["id"], {"to_status": "APPROVED"}, USCIS), 200)
    assert approved["status"] == "APPROVED"


def test_employment_adjacency_approval_persists_on_fetch(api):
    """PRD §3.6: "from `SUBMITTED`, the officer approves the petition to
    `APPROVED` or denies it to `DENIED`, each defined only from `SUBMITTED`."

    Design: Difficulty/resource_temporal_overlap/employment_half_open_adjacency_allowed
    """
    ctx = setup_two_h1b_petitions_same_beneficiary(
        pet1_start="2026-10-01T00:00:00Z", pet1_end="2027-10-01T00:00:00Z",
        pet2_start="2027-10-01T00:00:00Z", pet2_end="2028-10-01T00:00:00Z")
    validate_success(
        api.transition_h1b_petition(ctx["petition2"]["id"], {"to_status": "APPROVED"}, USCIS), 200)
    assert validate_success(api.get_h1b_petition(ctx["petition2"]["id"], USCIS), 200)["status"] == "APPROVED"
