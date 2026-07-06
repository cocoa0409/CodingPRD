"""RBAC enforcement, authentication, and list endpoint behavior.

Covers corner rbac and endpoints (listing/pagination, filtered read) instances.
"""
from test_helpers import (
    TEST_USERS,
    NO_AUTH_HEADERS,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    create_cemetery,
    setup_cemetery_with_gravesite,
    open_and_approve_case,
    create_pmc,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["eligibility_officer_headers"]
CLERK = TEST_USERS["scheduling_clerk_headers"]
HONORS = TEST_USERS["honors_coordinator_headers"]


# ===========================================================================
# Corner: rbac
# ===========================================================================
def test_scheduling_clerk_cannot_run_eligibility(api):
    """PRD §2.1: "An EligibilityOfficer adjudicates veteran and dependent eligibility
    and owns the pre-need memorial certificate determinations."
    PRD §2.1: "When the headers are present but the declared role is not permitted
    for the requested operation, the request is rejected with ERR_UNAUTHORIZED."

    Design: Corner/rbac/scheduling_clerk_cannot_run_eligibility
    """
    cem = create_cemetery(name="Rbac National", honors_squad_capacity=1)
    case = get_success_data(api.create_burial_case(cem["id"], {
        "cemetery_id": cem["id"], "case_type": "AT_NEED", "applicant_role": "VETERAN",
        "requested_class": "STANDARD", "character_of_discharge": "HONORABLE",
        "service_days": 3650,
    }, CLERK))  # opening a case is shared with SchedulingClerk
    resp = api.run_eligibility(cem["id"], case["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_honors_coordinator_cannot_assign_plot(api):
    """PRD §2.1: "A SchedulingClerk owns plot assignment, interment scheduling, and
    the burial case's lifecycle after eligibility."
    PRD §2.1: "When the headers are present but the declared role is not permitted
    for the requested operation, the request is rejected with ERR_UNAUTHORIZED."

    Design: Corner/rbac/honors_coordinator_cannot_assign_plot
    """
    cem, sec, grv = setup_cemetery_with_gravesite(depth_capacity=1, honors_squad_capacity=1)
    case = open_and_approve_case(cem["id"])
    resp = api.assign_plot(cem["id"], case["id"], HONORS, payload={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: X-User-ID, identifying the
    acting user, and X-User-Role, declaring the capacity in which they act. A request
    missing either header is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_headers_unauthenticated
    """
    resp = api.create_cemetery(
        {"name": "NoAuth National", "country_code": "US", "honors_squad_capacity": 1},
        NO_AUTH_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


# ===========================================================================
# Corner: endpoints — listing pagination, filtered PMC list
# ===========================================================================
def test_list_burial_cases_pagination_envelope(api):
    """PRD §2.3: "The limit parameter caps the number of items returned"
    PRD §2.3: "Every list response echoes four fields inside the envelope's meta
    object: limit, offset, total_count, and has_more."

    Design: Corner/endpoints/list_burial_cases_pagination_envelope
    """
    cem = create_cemetery(name="Page National", honors_squad_capacity=1)
    for _ in range(2):
        get_success_data(api.create_burial_case(cem["id"], {
            "cemetery_id": cem["id"], "case_type": "AT_NEED", "applicant_role": "VETERAN",
            "requested_class": "STANDARD", "character_of_discharge": "HONORABLE",
            "service_days": 3650,
        }, OFFICER))
    resp = api.list_burial_cases(cem["id"], ADMIN, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_filtered_list_pmc_by_burial_case_id(api):
    """PRD §4: "the pre-need list accepts burial_case_id and status"

    Design: Corner/endpoints/filtered_list_pmc_by_burial_case_id
    """
    cem = create_cemetery(name="FilterPMC National", honors_squad_capacity=1)
    case = open_and_approve_case(cem["id"], case_type="PRE_NEED")
    pmc = create_pmc(cem["id"], case["id"])
    resp = api.list_pmcs(cem["id"], OFFICER, params={"burial_case_id": case["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["id"] == pmc["id"]
