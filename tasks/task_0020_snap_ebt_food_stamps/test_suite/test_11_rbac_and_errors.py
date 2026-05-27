"""Top-of-priority gates: missing auth header → ERR_UNAUTHENTICATED;
wrong-role → ERR_FORBIDDEN.
"""
from test_helpers import (
    validate_error,
    ApiErrorId, TEST_USERS,
)

MER = TEST_USERS["merchant_headers"]


# ─── Corner / errors / missing_x_user_role_header_returns_unauthenticated ──

def test_missing_x_user_role_header_returns_unauthenticated(api):
    """A request without X-User-Role (and X-User-ID) fails priority-1/2
    auth and is rejected with ERR_UNAUTHENTICATED (401).

    PRD §2.1: "Every request to the SNAP API must carry two headers:
    `X-User-ID`, identifying the calling principal, and `X-User-Role`,
    naming the role under which the call is made. Either header missing
    or empty yields `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/missing_x_user_role_header_returns_unauthenticated
    """
    # Bypass the convenience methods to control headers directly: use
    # GenericApiClient._request with an empty header dict.
    resp = api._request("GET", "/snap/households", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ─── Corner / rbac / merchant_cannot_create_household ──

def test_merchant_cannot_create_household(api):
    """POST /snap/households is Caseworker-only per PRD §4. A Merchant
    calling it must be rejected with ERR_FORBIDDEN.

    PRD §4: "POST | `/snap/households` | Create a new household record
    in `PENDING`. | `Caseworker`"
    PRD §2.1: "A header pair that fails the per-endpoint role check
    yields `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/merchant_cannot_create_household
    """
    resp = api.create_household(
        {"case_number": "CA-110001", "state_code": "CA",
         "address_line": "X"},
        MER,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
