"""Corner: rbac — role-exclusive operations rejected for unauthorized roles."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    register_beneficiary,
    register_donor,
    submit_beneficiary_pending,
    create_campaign_payload,
    make_donor_headers,
)


def test_guest_cannot_create_campaign(api, guest_headers):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    invoke the endpoint, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/guest_cannot_create_campaign
    """
    ben = register_beneficiary(api)
    resp = api.create_campaign(create_campaign_payload(ben["id"]), guest_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_donor_cannot_approve_verification(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    invoke the endpoint, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/donor_cannot_approve_verification
    """
    ben = register_beneficiary(api)
    submit_beneficiary_pending(api, ben["id"])  # PENDING
    donor = register_donor(api)
    resp = api.approve_verification(ben["id"], make_donor_headers(donor["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
