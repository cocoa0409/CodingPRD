"""Header-context auth and Buyer-role list scoping (PRD §2.1, §2.10)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    make_buyer_headers,
    register_buyer,
    setup_draft_agreement,
    validate_error,
    validate_paginated,
)

AGENT = TEST_USERS["sales_agent_headers"]


def test_buyer_agreement_list_scoped_to_own():
    """PRD §2.10: "Buyers see only their own commercial records. On the list
    endpoints for agreements, option selections, incentive requests, and
    milestones, a `Buyer` caller's results are filtered to records whose owning
    agreement's `buyer_id` equals the caller's identity; likewise, a `Buyer`
    reading a single agreement may read only their own. Staff roles are
    unscoped."

    Design: Corner/rbac/buyer_agreement_list_scoped_to_own
    """
    bundle = setup_draft_agreement()
    bea = bundle["buyer"]
    ben = register_buyer(full_name="Ben Buyer", email="ben@example.com")

    _data, meta_staff = validate_paginated(api_client.list_agreements(AGENT))
    assert meta_staff["total_count"] == 1, "staff roles are unscoped"

    _data, meta_ben = validate_paginated(
        api_client.list_agreements(make_buyer_headers(ben["id"]))
    )
    assert meta_ben["total_count"] == 0, "Ben sees none of Bea's records"

    data_bea, meta_bea = validate_paginated(
        api_client.list_agreements(make_buyer_headers(bea["id"]))
    )
    assert meta_bea["total_count"] == 1
    assert data_bea[0]["id"] == bundle["agreement"]["id"]


def test_request_missing_auth_headers_unauthenticated():
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring the caller's
    operational capacity. A request missing either header, or naming a role the
    system does not recognize, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/rbac/request_missing_auth_headers_unauthenticated
    """
    resp = api_client.list_lots(headers={})
    validate_error(
        resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400
    )
