"""Role-based access control, ownership gating, pagination, and list filtering.

Covers the rbac and endpoints corner instances.
"""
from test_helpers import validate_success, validate_error, validate_paginated, ApiErrorId
from test_helpers import factories as fac
from test_helpers import fixtures as fx


# ==========================================================================
# Corner — RBAC
# ==========================================================================
def test_rightsholder_cannot_register_application(api, rightsholder_headers):
    """PRD §2.1: "An Examiner ... registers or refuses applications." (register is
    Examiner-exclusive) and §2.6: "Authorization. The role must be permitted for
    the endpoint per the access rules of §2.1, otherwise ERR_FORBIDDEN."

    Design: Corner/rbac/rightsholder_cannot_register_application
    """
    work = fx.create_work()
    app = fx.create_application(work["id"])
    validate_error(api.register_application(app["id"], rightsholder_headers), ApiErrorId.ERR_FORBIDDEN)


def test_examiner_cannot_create_work(api, examiner_headers):
    """PRD §2.1: "A RightsHolder is an author, claimant, or rights owner. This role
    registers works ..." (POST works is RightsHolder-exclusive); §2.6 authorization
    failure yields ERR_FORBIDDEN.

    Design: Corner/rbac/examiner_cannot_create_work
    """
    validate_error(api.create_work(fac.create_work_payload(), examiner_headers), ApiErrorId.ERR_FORBIDDEN)


def test_complainant_cannot_file_application(api, complainant_headers):
    """PRD §2.1: "A RightsHolder ... files and submits applications" (POST
    applications is RightsHolder-exclusive); §2.6 authorization failure yields
    ERR_FORBIDDEN.

    Design: Corner/rbac/complainant_cannot_file_application
    """
    work = fx.create_work()
    resp = api.create_application(fac.create_application_payload(work["id"]), complainant_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_non_owner_rightsholder_cannot_submit(api, rightsholder2_headers):
    """PRD §2.1: "For submitting an application, paying its fee, responding to its
    correspondence, and withdrawing it, the acting X-User-ID must equal the
    applicant_user_id recorded on that Application; if it does not, the request is
    rejected with ERR_NOT_RESOURCE_OWNER."

    Design: Corner/rbac/non_owner_rightsholder_submit_returns_not_owner
    """
    work = fx.create_work()           # created by rh-user-1
    app = fx.create_application(work["id"])  # applicant_user_id == rh-user-1
    resp = api.submit_application(app["id"], rightsholder2_headers)  # acting rh-user-2
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)


def test_missing_role_returns_unauthenticated(api, unknown_role_headers):
    """PRD §2.1: "If the X-User-Role header is missing or names a role the system
    does not recognize, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_role_returns_unauthenticated
    """
    validate_error(api.list_works(unknown_role_headers), ApiErrorId.ERR_UNAUTHENTICATED)


# ==========================================================================
# Corner — pagination / listing
# ==========================================================================
def test_works_list_pagination_envelope(api, rightsholder_headers):
    """PRD §2.3: "List responses carry the pagination fields limit, offset,
    total_count, and has_more inside the meta object, where total_count reflects
    the total number of matching resources before the page window is applied and
    has_more indicates whether further pages remain."

    Design: Corner/endpoints/works_list_pagination_envelope
    """
    fx.create_work(title="W1")
    fx.create_work(title="W2", author_name="B", owner_shares=[{"name": "B", "share_bps": 10000}])
    data, meta = validate_paginated(api.list_works(rightsholder_headers, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_invalid_pagination_rejected(api, rightsholder_headers):
    """PRD §2.3: "A request whose limit falls outside the range of 1 through 100, or
    whose offset is negative, is rejected with ERR_INVALID_PAGINATION."

    Design: Corner/endpoints/invalid_pagination_returns_error
    """
    validate_error(api.list_works(rightsholder_headers, params={"limit": 0}), ApiErrorId.ERR_INVALID_PAGINATION)


def test_deposits_filtered_by_application_fk(api, rightsholder_headers):
    """PRD §4: "the list filters shown below (such as work_id, status,
    application_id, license_id, takedown_id, work_type, and registration_status)
    are optional." (GET /copyright/deposits filtered by application_id)

    Design: Corner/endpoints/deposits_filtered_by_application_fk
    """
    work = fx.create_work()
    app = fx.create_application(work["id"])
    dep = fx.get_success_data(api.create_deposit(fac.create_deposit_payload(app["id"]), rightsholder_headers))
    data, meta = validate_paginated(api.list_deposits(rightsholder_headers, params={"application_id": app["id"]}))
    assert meta["total_count"] == 1
    assert [d["id"] for d in data] == [dep["id"]]
