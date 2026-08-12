"""List pagination + filtering and immediate-consistency mutation responses."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    setup_basic_case,
    create_new_hire,
    create_case,
    create_onboarding_case_payload,
    approve_required_tasks,
)

HR = TEST_USERS["hr_admin_headers"]


def test_cases_list_pagination_and_phase_filter(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it
    defaults to 10 when omitted, accepts a minimum of 1, and rejects values
    above 100."
    PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."
    PRD §3.2: "Cases can be listed with filters on `new_hire_id`,
    `role_profile_id`, `manager_id`, `buddy_id`, `orientation_session_id`,
    `phase`, and `health`"

    Design: Corner/endpoints/cases_list_pagination_and_phase_filter
    """
    ctx = setup_basic_case()
    profile = ctx["profile"]
    mgr = ctx["manager"]
    bud = ctx["buddy"]
    nh2 = create_new_hire()
    case2 = create_case(mgr, bud, nh2, profile)
    get_success_data(api.withdraw_case(case2["id"], HR))

    # phase filter returns exactly the withdrawn case.
    resp = api.list_onboarding_cases(HR, params={"phase": "WITHDRAWN"})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert data[0]["id"] == case2["id"]

    # limit=1 over 2 cases returns 1 entry with has_more=True.
    resp2 = api.list_onboarding_cases(HR, params={"limit": 1})
    data2, meta2 = validate_paginated(resp2)
    assert len(data2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is True

    # limit=200 exceeds the 100 maximum -> ERR_VALIDATION.
    resp3 = api.list_onboarding_cases(HR, params={"limit": 200})
    validate_error(resp3, ApiErrorId.ERR_VALIDATION)


def test_mutation_responses_reflect_final_state_immediately(api):
    """PRD §2.11: "the system keeps the whole aggregate consistent without
    waiting for clients to touch each other resource."

    Design: Corner/consistency_model/mutation_responses_reflect_final_state_immediately
    """
    ctx = setup_basic_case()
    case_id = ctx["case"]["id"]
    approve_required_tasks(case_id, ctx["new_hire"])

    # The mutation response itself shows the new phase; a follow-up GET agrees.
    resp = api.submit_for_clearance(case_id, HR)
    data = validate_success(resp)
    assert data["phase"] == "CLEARANCE_IN_PROGRESS"

    case = get_success_data(api.get_onboarding_case(case_id, HR))
    assert case["phase"] == "CLEARANCE_IN_PROGRESS"
