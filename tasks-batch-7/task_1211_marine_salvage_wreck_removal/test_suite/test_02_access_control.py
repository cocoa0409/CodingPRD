"""Access control and the validation pipeline's early tiers."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    build_user_headers,
    create_contract_payload,
    get_success_data,
    report_casualty,
    validate_error,
    validate_paginated,
)


def test_unknown_role_rejected(api):
    """PRD 2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting operator, and `X-User-Role`, naming the operator's
    capacity. A request missing either header, or presenting a role name outside
    the declared set, is rejected with
    `ERR_MISSING_OR_INVALID_CONTEXT_HEADER`."

    Design: Corner/rbac/unknown_role_rejected
    """
    headers = build_user_headers("pirate-01", "Pirate")
    payload = {
        "casualty_id": NON_EXISTENT_UUID,
        "plan_id": NON_EXISTENT_UUID,
        "form": "NO_CURE_NO_PAY",
    }
    res = api.create_contract(payload, headers)
    validate_error(
        res, ApiErrorId.ERR_MISSING_OR_INVALID_CONTEXT_HEADER, expected_status=400
    )


def test_surveyor_cannot_create_contract_rejected(api, marine_surveyor_headers):
    """PRD 2.1: "A request whose declared role is not authorized for the target
    endpoint is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD 4: the POST /contracts row lists only ContractsOfficer under
    Authorized Role(s).

    Design: Corner/rbac/surveyor_cannot_create_contract_rejected
    """
    casualty = report_casualty(vessel_name="MV Pax")
    payload = create_contract_payload(casualty["id"], NON_EXISTENT_UUID)
    res = api.create_contract(payload, marine_surveyor_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_salvagemaster_cannot_grant_permit_rejected(api, salvage_master_headers):
    """PRD 2.7: "at priority 2 the declared role is checked against the
    endpoint's authorized roles (`ERR_FORBIDDEN_ROLE`). Third, at priority 3,
    existence of every referenced identifier is confirmed (`ERR_NOT_FOUND`)."
    PRD 4: the POST /permits/{permit_id}/grant row lists only
    EnvironmentalOfficer under Authorized Role(s).

    Design: Corner/rbac/salvagemaster_cannot_grant_permit_rejected
    """
    res = api.grant_permit(NON_EXISTENT_UUID, salvage_master_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_contractsofficer_cannot_decide_award_rejected(api, contracts_officer_headers):
    """PRD 2.1: "A request whose declared role is not authorized for the target
    endpoint is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD 4: the POST /awards/{award_id}/decide row lists only Arbitrator under
    Authorized Role(s).

    Design: Corner/rbac/contractsofficer_cannot_decide_award_rejected
    """
    res = api.decide_award(
        NON_EXISTENT_UUID, {"awarded_amount_cents": 1_000_000},
        contracts_officer_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_arbitrator_shared_read_allowed(api, arbitrator_headers):
    """PRD 4: "Endpoints marked "All roles" accept any of the seven declared
    roles." (GET /casualties is marked All roles.)
    PRD 2.3: "every list response includes the fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/rbac/arbitrator_shared_read_allowed
    """
    report_casualty(vessel_name="MV Pax")
    res = api.list_casualties(arbitrator_headers)
    data, meta = validate_paginated(res)
    assert res.status_code == 200
    assert res.json()["response_type"] == "array"
    assert meta["total_count"] == 1
    assert len(data) == 1


def test_schema_error_beats_role_priority_ordering(api, marine_surveyor_headers):
    """PRD 2.7: "Every request passes through a fixed pipeline of validation
    tiers, evaluated in ascending priority order, so that an earlier failure
    masks later checks on the same request. The order is normative. First, at
    priority 0, request schema validation ... Any failure here yields
    `ERR_INVALID_REQUEST`. ... at priority 2 the declared role is checked
    against the endpoint's authorized roles (`ERR_FORBIDDEN_ROLE`)."

    Design: Corner/validations/schema_error_beats_role_priority_ordering
    """
    report_casualty(vessel_name="MV Pax")
    # Missing required casualty_id/plan_id (priority 0) AND wrong role (p2).
    res = api.create_contract({"form": "NO_CURE_NO_PAY"}, marine_surveyor_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_contract_not_found_returns_404(api, contracts_officer_headers):
    """PRD 2.8: "Requests that target a resource through a path of identifiers
    are validated strictly left to right: the server confirms the first
    identifier exists before examining the second, and a request is rejected
    with `ERR_NOT_FOUND` at the first identifier ... that does not correspond to
    an existing resource."

    Design: Corner/entities/contract_not_found_returns_404
    """
    res = api.get_contract(NON_EXISTENT_UUID, contracts_officer_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
