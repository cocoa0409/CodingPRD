"""Authentication, role authorization, and entity-backed ownership."""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_applicant_headers,
    applicant_payload, unit_payload,
)
from test_helpers.fixtures import (
    create_applicant, setup_active_tenancy, setup_drawn_active_entry,
    create_unit, create_offer, file_grievance,
)

IC = TEST_USERS["intake_clerk_headers"]
HS = TEST_USERS["housing_specialist_headers"]
PM = TEST_USERS["property_manager_headers"]


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers: X-User-ID ... and
    X-User-Role .... If either header is missing, or if X-User-Role is not one of the
    recognized roles, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/errors/request_missing_auth_returns_401
    """
    resp = api.create_applicant(applicant_payload("NoAuth"), {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_intake_clerk_cannot_create_unit(api):
    """PRD §2.1: "A PropertyManager owns unit creation and decides grievances and
    evictions." PRD §2.1: "A role attempting an operation outside its authority ... is
    rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/intakeclerk_cannot_create_unit_forbidden
    """
    resp = api.create_unit(unit_payload("U-X", bedroom_size=2, income_limit_cents=5000000), IC)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_housing_specialist_cannot_decide_grievance(api):
    """PRD §2.1: "A PropertyManager owns unit creation and decides grievances and
    evictions." PRD §2.1: "A role attempting an operation outside its authority ... is
    rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/housingspecialist_cannot_decide_grievance_forbidden
    """
    ctx = setup_active_tenancy(api, applicant_name="RB1")
    griev = file_grievance(api, ctx["tenancy"]["id"], "GRIEVANCE", "repair",
                           as_applicant=ctx["applicant"]["id"])
    resp = api.decide_grievance(griev["id"], {"outcome": "SUSTAINED"}, HS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_accept_offer_by_non_owner_forbidden(api):
    """PRD §2.1: "an Applicant acting on a resource it does not own, is rejected with
    ERR_UNAUTHORIZED (HTTP 403). ... an Applicant may only accept or refuse an offer ...
    that belongs to its own household; the applicant behind an offer is reached through
    the offer's waitlist entry".

    Design: Corner/rbac/accept_offer_by_non_owner_forbidden
    """
    ctx = setup_drawn_active_entry(api, applicant_name="OwnerA")
    other = create_applicant(api, "OtherB")
    unit = create_unit(api, bedroom_size=2)
    offer = create_offer(api, ctx["entry_id"], unit["id"])
    resp = api.accept_offer(offer["id"], make_applicant_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert get_success_data(api.get_offer(offer["id"], HS))["status"] == "PENDING"
