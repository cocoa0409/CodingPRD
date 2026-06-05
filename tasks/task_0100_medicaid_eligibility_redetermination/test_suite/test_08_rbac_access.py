"""Role-based access control, authentication, and the filtered-list reverse
reachability reads.
"""
from test_helpers import (
    api_client as api,
    TEST_USERS, build_user_headers,
    get_success_data, validate_success, validate_paginated, validate_error, ApiErrorId,
    setup_config, setup_household,
    setup_application_under_review, setup_filed_appeal,
)

CW = TEST_USERS["caseworker_headers"]
APP = TEST_USERS["applicant_headers"]


# ===========================================================================
# Queue B — rbac corner
# ===========================================================================
def test_applicant_cannot_run_determination_returns_forbidden():
    """PRD §2.1: "A request that is authenticated but whose role is not permitted
    to invoke the targeted endpoint per the role matrix is rejected with
    `ERR_FORBIDDEN`."
    PRD §4: the determinations run endpoint is authorized for `CaseWorker` only.

    Design: Corner/rbac/applicant_cannot_run_determination_returns_forbidden
    """
    hh, _member, app = setup_application_under_review(state="CA")
    resp = api.run_determination(app["id"], APP)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_caseworker_cannot_schedule_hearing_returns_forbidden():
    """PRD §2.1: "A request that is authenticated but whose role is not permitted
    to invoke the targeted endpoint per the role matrix is rejected with
    `ERR_FORBIDDEN`."
    PRD §4: scheduling a fair hearing is authorized for `HearingOfficer` only.

    Design: Corner/rbac/caseworker_cannot_schedule_hearing_returns_forbidden
    """
    hh, enr, redet, appeal = setup_filed_appeal(state="CA", cw_id="cw-z1")
    resp = api.schedule_appeal(appeal["id"], CW)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_auth_headers_returns_unauthenticated():
    """PRD §2.1: "A request that omits either header, or that supplies an
    `X-User-Role` value that is not one of these three declared roles, is rejected
    with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    bad = build_user_headers("anon-1", "Anonymous")  # undeclared role
    resp = api.get_household("00000000-0000-4000-8000-000000000009", bad)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# Queue B — endpoints corner (filtered-list reverse reachability)
# ===========================================================================
def test_list_members_filtered_reverse_reachability():
    """PRD §3.10: "A household's members, assets, and applications are listed
    under that household".
    PRD §2.3: "List responses carry the pagination bookkeeping inside the `meta`
    object of the envelope, specifically the fields `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/list_members_filtered_reverse_reachability
    """
    hh = setup_household(state="CA", name="List L")
    api.add_member(hh["id"], {"full_name": "List L", "age": 30, "relationship": "SELF"}, CW)
    api.add_member(hh["id"], {"full_name": "Lou L", "age": 28, "relationship": "SPOUSE"}, CW)
    data, meta = validate_paginated(api.list_members(hh["id"], CW))
    assert len(data) == 2
    assert meta["total_count"] == 2


def test_list_enrollments_filtered_by_household_id():
    """PRD §3.10: "Three flat collections support filtering: enrollments may be
    filtered by `household_id` or `application_id`".

    Design: Corner/endpoints/list_enrollments_filtered_by_household_id
    """
    setup_config(state="CA")
    hh = get_success_data(api.create_household(
        {"state_code": "CA", "fpl_year": 2026, "primary_applicant_name": "Enr E"}, CW))
    api.add_member(hh["id"], {"full_name": "Enr E", "age": 30, "relationship": "SELF"}, CW)
    app = get_success_data(api.create_application(
        hh["id"], {"pathway": "MAGI", "magi_variant": "POINT_IN_TIME"}, CW))
    api.create_enrollment(
        {"household_id": hh["id"], "application_id": app["id"],
         "coverage_start": "2026-01-01T00:00:00Z", "coverage_end": "2026-12-31T00:00:00Z",
         "redetermination_due": "2026-11-01T00:00:00Z"}, CW)
    data, _meta = validate_paginated(api.list_enrollments(CW, params={"household_id": hh["id"]}))
    assert len(data) == 1
    assert data[0]["household_id"] == hh["id"]
