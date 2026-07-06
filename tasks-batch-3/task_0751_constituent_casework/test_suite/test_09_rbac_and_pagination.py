"""RBAC denials (unauthorized role, ownership) and case-list pagination."""
from test_helpers import (
    validate_error, validate_paginated, ApiErrorId,
    new_representative, new_constituent, new_case,
    create_representative_payload, make_constituent_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["office_admin_headers"]
CASEWORKER = TEST_USERS["caseworker_headers"]


# --- Corner: rbac / caseworker_cannot_create_representative ---

def test_caseworker_cannot_create_representative(api):
    """PRD §2.1: "If the headers are well-formed and name a known role, but that role
    is not permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/caseworker_cannot_create_representative
    """
    resp = api.create_representative(create_representative_payload(district_name="NY-18"), CASEWORKER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


# --- Corner: rbac / constituent_cannot_read_others_case ---

def test_constituent_cannot_read_others_case(api):
    """PRD §2.1: "ownership checks on any resource that references a constituent compare
    that resource's constituent foreign key to `X-User-ID`" ... "a mismatch is rejected
    with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/constituent_cannot_read_others_case
    """
    rep = new_representative(api)
    owner = new_constituent(api, rep["id"], email="own@x.com")
    other = new_constituent(api, rep["id"], email="oth@x.com")
    case = new_case(api, owner["id"], category="OTHER")
    resp = api.get_case(case["id"], make_constituent_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# --- Corner: endpoints / cases_list_pagination_by_constituent ---

def test_cases_list_pagination_by_constituent(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return;
    when omitted it defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Every list-based response includes the following fields in the `meta`
    object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/cases_list_pagination_by_constituent
    """
    rep = new_representative(api)
    con = new_constituent(api, rep["id"])
    for i in range(3):
        new_case(api, con["id"], category="OTHER", subject=f"S{i}")
    resp = api.list_cases(CASEWORKER, params={"constituent_id": con["id"], "limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"expected 2 items, got {len(data)}"
    assert meta["total_count"] == 3, f"expected total_count 3, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more must be true with 3 cases and limit 2"
