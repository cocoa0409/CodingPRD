"""Role-based access control and segregation of duties."""
from test_helpers import (
    validate_error, ApiErrorId,
    create_jurisdiction, create_registrant, setup_active_registrant,
    file_petition, make_registrant_headers, TEST_USERS,
)

OFFICER = TEST_USERS["registration_officer_headers"]
REVIEWER = TEST_USERS["compliance_reviewer_headers"]


def test_reviewer_cannot_open_flag(api):
    """PRD 2.1: "`ComplianceReviewer` — adjudicates petitions and reads compliance
    rosters and flags. Under segregation of duties, this role cannot open flags or
    record verifications."
    PRD 2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/reviewer_cannot_open_flag_returns_unauthorized
    """
    jur, reg = setup_active_registrant(full_name="Sod S")
    resp = api.create_flag(reg["id"], {"flag_type": "UNREPORTED_MOVE"}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_registrant_cannot_decide_petition(api):
    """PRD 3.8: "A `ComplianceReviewer`, and only a `ComplianceReviewer`, decides a
    petition — this is the segregation-of-duties boundary".
    PRD 2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/registrant_cannot_decide_petition_returns_unauthorized
    """
    jur, reg = setup_active_registrant(full_name="Self S")
    pet = file_petition(reg["id"], petition_type="DEREGISTER")
    resp = api.decide_petition(pet["id"], {"decision": "GRANT"}, make_registrant_headers(reg["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_registrant_cannot_read_other_registrant(api):
    """PRD 2.1: "a `Registrant` acting on any record other than its own is rejected
    with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/registrant_cannot_read_other_registrant_returns_unauthorized
    """
    jur = create_jurisdiction()
    reg1 = create_registrant(jur["id"], full_name="One 1")
    reg2 = create_registrant(jur["id"], full_name="Two 2", date_of_birth="1981-01-01T00:00:00Z")
    resp = api.get_registrant(reg2["id"], make_registrant_headers(reg1["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_request_without_headers_rejected(api):
    """PRD 2.1: "A request missing either header, or presenting a role the system
    does not recognize, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unauthenticated_request_returns_401
    """
    jur = create_jurisdiction()
    reg = create_registrant(jur["id"], full_name="Anon A")
    resp = api.get_registrant(reg["id"], {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
