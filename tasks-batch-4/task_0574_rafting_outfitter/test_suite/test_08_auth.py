"""Authentication header enforcement."""
from test_helpers import validate_error


def test_list_trips_missing_auth_header_returns_401(api):
    """PRD §2.1: "Every request must be authenticated with two mandatory HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in
    which they act. A request missing either header, or carrying a malformed one, is
    rejected with `ERR_MISSING_AUTH`."

    Design: Corner/validations/list_trips_missing_auth_header_returns_401
    """
    validate_error(api.list_trips(headers={}), "ERR_MISSING_AUTH")
