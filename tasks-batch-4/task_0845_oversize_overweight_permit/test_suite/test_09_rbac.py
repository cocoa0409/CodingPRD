"""Role-based access control denials and carrier ownership enforcement."""
from test_helpers import (
    TEST_USERS, make_carrier_headers,
    validate_error,
    ApiErrorId,
    new_carrier, new_permit, add_segment, submit,
    create_structure_payload,
)

OFFICER = TEST_USERS["permit_officer_headers"]
ENFORCER = TEST_USERS["enforcement_officer_headers"]


def test_carrier_cannot_create_structure(api):
    """PRD §2.1: "When a role is authenticated but not permitted to perform the
    requested operation ... the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/error_carrier_cannot_create_structure
    """
    carrier = new_carrier(api)
    resp = api.create_structure(create_structure_payload(name="Hack Span"),
                                make_carrier_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_enforcement_cannot_issue_permit(api):
    """PRD §2.1: "When a role is authenticated but not permitted to perform the
    requested operation ... the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/error_enforcement_cannot_issue_permit
    """
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"])
    resp = api.issue_permit(permit["id"], ENFORCER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_permit_officer_cannot_begin_superload_review(api):
    """PRD §2.1: "including a `Carrier` acting on a resource it does not own, or a
    `PermitOfficer` attempting to begin review on a superload, which only a
    `BridgeEngineer` may do — the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/error_permitofficer_cannot_begin_superload_review
    """
    carrier = new_carrier(api)
    permit = new_permit(api, carrier["id"], gross_weight_lbs=210000, num_axles=13)
    add_segment(api, permit["id"], carrier["id"])
    submit(api, permit["id"], carrier["id"])
    resp = api.begin_review(permit["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_carrier_cannot_submit_other_carriers_permit(api):
    """PRD §2.1: "ownership checks on any resource that references a carrier
    compare that resource's `carrier_id` to `X-User-ID`".
    PRD §2.1: "a `Carrier` acting on a resource it does not own ... the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/error_carrier_cannot_act_on_other_carriers_permit
    """
    carrier_a = new_carrier(api, usdot_number="USDOT-R4A")
    carrier_b = new_carrier(api, usdot_number="USDOT-R4B")
    permit = new_permit(api, carrier_a["id"])
    add_segment(api, permit["id"], carrier_a["id"])
    resp = api.submit_permit(permit["id"], make_carrier_headers(carrier_b["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
