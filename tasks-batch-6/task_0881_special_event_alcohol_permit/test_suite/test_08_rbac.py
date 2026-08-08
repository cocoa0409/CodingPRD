"""Role-based access control and authentication.

Corner: applicant_cannot_open_review, reviewer_cannot_create_venue,
create_venue_unauthenticated_rejected.
"""
from test_helpers import (
    validate_error, ApiErrorId, create_venue_payload, fixtures,
)
from test_helpers.test_users import TEST_USERS

APPLICANT = TEST_USERS["applicant_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


def test_applicant_cannot_open_review(api):
    """PRD §2.1: "If the supplied role is present but is not permitted to perform the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §2.1: "A `PermitClerk` is licensing-authority staff who administer venues and
    inspectors, open and steer the review workflow".

    Design: Corner/rbac/applicant_cannot_open_review
    """
    ctx = fixtures.create_submitted_application(api)
    resp = api.open_review(ctx["application"]["id"], APPLICANT)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_reviewer_cannot_create_venue(api):
    """PRD §2.1: "If the supplied role is present but is not permitted to perform the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §2.1: "A `PermitClerk` is licensing-authority staff who administer venues and
    inspectors".

    Design: Corner/rbac/reviewer_cannot_create_venue
    """
    resp = api.create_venue(create_venue_payload(name="X Hall", address="0 Nowhere",
                                                 occupancy_limit=50), REVIEWER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_create_venue_without_auth_headers_rejected(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring the capacity in which they
    act. If either header is missing or empty, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/create_venue_unauthenticated_rejected
    """
    resp = api.create_venue(create_venue_payload(name="X Hall", address="0 Nowhere",
                                                 occupancy_limit=50), headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
