"""The two error families that sit below every business rule.

Each entity family's own 404, and the header check that precedes all of them.
"""

from test_helpers import (
    COMPLIANCE_APPROVER,
    HR_ADMIN,
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    PRIVACY_OFFICER,
    UNKNOWN_ROLE_HEADERS,
    VENDOR_MANAGER,
    ApiErrorId,
    create_program,
    validate_error,
)


def test_every_entity_family_reports_its_own_not_found_code(api):
    """Seven single-resource reads, seven distinct 404 codes.

    PRD §2.11: "Each maps to its own 404: `ERR_PROGRAM_NOT_FOUND`,
    `ERR_JURISDICTION_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
    `ERR_POLICY_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`,
    `ERR_SUBJECT_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`, `ERR_ACCOMMODATION_NOT_FOUND`,
    `ERR_INCIDENT_NOT_FOUND` and `ERR_ASSESSMENT_NOT_FOUND`."

    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    The store is non-empty — a program exists — so nothing is being reported merely
    because the database is blank; each read is looking in its own table.

    Design: Corner/errors/unknown_ids_on_each_single_resource_read_surface_their_own_error_codes
    """
    create_program(api)

    probes = [
        (api.get_vendor(NON_EXISTENT_UUID, VENDOR_MANAGER), ApiErrorId.VENDOR_NOT_FOUND),
        (
            api.get_vendor_contract(NON_EXISTENT_UUID, VENDOR_MANAGER),
            ApiErrorId.CONTRACT_NOT_FOUND,
        ),
        (api.get_policy(NON_EXISTENT_UUID, PRIVACY_OFFICER), ApiErrorId.POLICY_NOT_FOUND),
        (
            api.get_notice_packet(NON_EXISTENT_UUID, PRIVACY_OFFICER),
            ApiErrorId.NOTICE_NOT_FOUND,
        ),
        (api.get_consent_record(NON_EXISTENT_UUID, HR_ADMIN), ApiErrorId.CONSENT_NOT_FOUND),
        (
            api.get_accommodation(NON_EXISTENT_UUID, HR_ADMIN),
            ApiErrorId.ACCOMMODATION_NOT_FOUND,
        ),
        (
            api.get_exposure_assessment(NON_EXISTENT_UUID, COMPLIANCE_APPROVER),
            ApiErrorId.ASSESSMENT_NOT_FOUND,
        ),
    ]

    for response, expected in probes:
        validate_error(response, expected)
        body = response.json()
        assert body["response_type"] == "error", expected
        assert isinstance(body["data"]["message"], str) and body["data"]["message"], expected


def test_authentication_is_settled_before_the_body_or_the_role_is_judged(api):
    """A missing identity and an undeclared role are both 401, never 400 or 403.

    PRD §2.5: "**Header authentication.** Both `X-User-ID` and `X-User-Role` present, and
    `X-User-Role` one of the six declared roles — otherwise `ERR_UNAUTHENTICATED`."

    PRD §2.5: "A request that violates more than one rule always reports the violation
    with the lowest priority number below."

    The first request also carries an `org_type` outside its enum, which would be an
    `ERR_INVALID_REQUEST` at priority three; the header check at priority one settles it
    first. The second request is well-formed and names a role that simply does not
    exist, which is an authentication failure rather than a permission one.

    Design: Corner/errors/request_missing_auth_headers_returns_unauthenticated
    """
    unauthenticated = api.create_program(
        {"org_name": "Northline Retail Group", "org_type": "NONPROFIT", "exposure_ceiling_cents": 1093750},
        NO_AUTH_HEADERS,
    )

    validate_error(unauthenticated, ApiErrorId.UNAUTHENTICATED)

    undeclared_role = api.create_program(
        {"org_name": "Northline Retail Group", "org_type": "HYBRID", "exposure_ceiling_cents": 1093750},
        UNKNOWN_ROLE_HEADERS,
    )

    validate_error(undeclared_role, ApiErrorId.UNAUTHENTICATED)
