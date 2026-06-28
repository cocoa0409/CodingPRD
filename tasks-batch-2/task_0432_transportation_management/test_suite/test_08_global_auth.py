"""System-wide authentication header enforcement."""
from test_helpers import validate_error, ApiErrorId


def test_missing_user_context_returns_401(api):
    """PRD §2.1: "Every request must be authenticated through two mandatory HTTP
    headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`,
    which declares the operational capacity under which the request is made. If
    either header is missing or empty, the request is rejected with
    `ERR_MISSING_USER_CONTEXT`."

    Design: Corner/rbac/missing_user_context_returns_401
    """
    resp = api.list_carriers({})  # no X-User-ID / X-User-Role headers
    validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT.value)
