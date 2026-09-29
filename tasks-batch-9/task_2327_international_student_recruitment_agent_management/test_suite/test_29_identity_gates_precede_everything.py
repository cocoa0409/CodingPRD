"""The two header checks that run before any body is looked at.

A request with no acting identity is refused before the payload is parsed, and a
caller in the wrong role learns nothing about what the payload was missing.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import api_errors as E
from test_helpers import factories as F
from test_helpers.test_users import HEADERS_WITHOUT_USER_ID, OFFICER, REGISTRAR


class TestMissingIdentity:
    def test_a_well_formed_body_with_no_acting_user_creates_nothing(self, client):
        """The header check answers first, so the agency is never registered.

        "Every request must carry two headers: `X-User-ID`, identifying the acting
        principal, and `X-User-Role`, declaring the capacity in which that principal
        is acting. If either header is absent, or if `X-User-Role` is not one of the
        six declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
        401)."

        Design: Corner/validations/unauthenticated_call_missing_x_user_id_header
        """
        anonymous = client.register_agency(
            F.agency_payload("Anonymous Agency", "IN"), HEADERS_WITHOUT_USER_ID
        )
        validate_error(anonymous, E.ERR_UNAUTHENTICATED, 401)

        _, meta = validate_paginated(client.list_agencies(OFFICER))
        assert meta["total_count"] == 0


class TestRolePrecedesSchema:
    def test_the_wrong_role_hides_the_missing_field_from_the_caller(self, client):
        """Both rules are broken; the answer is the one that ranks higher.

        "If the headers are well formed but the declared role is not permitted for
        the endpoint — or not permitted for the particular action variant being
        requested — the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."

        "Lower-numbered groups are evaluated first, and the first failing check
        produces the response; later checks are never reached and never mask an
        earlier one."

        "2. Role permitted for the endpoint and for the requested action variant —
        `ERR_UNAUTHORIZED`."

        Design: Corner/validations/registrar_unauthorized_outranks_invalid_payload
        """
        refused = client.register_agency({"legal_name": "Wrong Role Agency"}, REGISTRAR)

        body = validate_error(refused, E.ERR_UNAUTHORIZED, 403)
        assert body["error_id"] != E.ERR_INVALID_REQUEST, (
            "a caller with no business on the endpoint learns nothing about the body"
        )
