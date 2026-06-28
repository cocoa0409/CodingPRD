"""Listing/pagination envelope, auth headers, RBAC denial, OCC happy path.

Queue B (Corner) translations for endpoints, errors, rbac, and the
cross-cutting concurrency happy path.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, make_counselor_headers, make_creditor_rep_headers,
    make_agency_admin_headers,
    create_agency, create_counselor, create_creditor, create_client,
    open_intake_session, complete_session, add_debt_account,
    add_and_accept_account, create_client_payload, activate_payload, api_client,
)


def test_list_clients_pagination_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/list_clients_pagination_envelope
    """
    agency = create_agency()
    counselor = create_counselor(agency["id"])
    create_client(agency["id"], counselor["id"], full_name="Cid")
    cn = make_counselor_headers(counselor["id"])
    resp = api.list_clients(cn, params={"counselor_id": counselor["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_list_debt_accounts_filtered_by_status(api):
    """PRD §4: "GET `/agencies/debt-accounts` List debt accounts"
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_debt_accounts_by_status_filter
    """
    agency = create_agency()
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(agency["id"], counselor["id"], full_name="Deb")
    add_debt_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
    )
    cn = make_counselor_headers(counselor["id"])
    resp = api.list_debt_accounts(cn, params={"client_id": client["id"], "status": "PROPOSED"})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert all(a["status"] == "PROPOSED" for a in data)


def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "Every request to the API must carry two mandatory headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the
    capacity in which they act."
    PRD §2.1: "When either header is missing or malformed, the request is rejected
    with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/errors/missing_auth_header_returns_400
    """
    agency = create_agency()
    resp = api.get_agency(agency["id"], headers={})
    validate_error(
        resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value, expected_status=400
    )


def test_creditorrep_cannot_create_client(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation per the role matrix in Section 4, the request
    is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
    PRD §4: "POST `/agencies/clients` Create a client (intake) | Counselor"

    Design: Corner/rbac/creditorrep_cannot_create_client
    """
    agency = create_agency()
    creditor = create_creditor(agency["id"])
    counselor = create_counselor(agency["id"])
    rep = make_creditor_rep_headers(creditor["id"])
    resp = api.create_client(
        create_client_payload(agency["id"], counselor["id"], full_name="Eli"), rep
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, expected_status=403)


def test_counselor_cannot_accept_proposal(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation per the role matrix in Section 4, the request
    is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
    PRD §4: "POST `/agencies/proposals/{proposalId}/accept` Creditor accepts the
    submitted proposal | CreditorRep"

    Design: Corner/rbac/counselor_cannot_accept_proposal
    """
    agency = create_agency()
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(agency["id"], counselor["id"], full_name="Fox")
    acct = add_debt_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
    )
    cn = make_counselor_headers(counselor["id"])
    resp = api.accept_proposal(acct["proposal_id"], cn)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value, expected_status=403)


def test_activate_with_correct_version_succeeds(api):
    """PRD §2.9: "If `expected_client_version` does not match the client's current
    `version` at the time of the request, the activation is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.5: "The client advances from `INTAKE` to `ACTIVE`, and the client's
    `version` is incremented by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_activates
    """
    agency = create_agency(monthly_fee_cents=3500)
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(agency["id"], counselor["id"])
    session = open_intake_session(client["id"], counselor["id"])
    add_and_accept_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
    )
    complete_session(session["id"], counselor["id"])
    cn = make_counselor_headers(counselor["id"])
    cur = get_success_data(api.get_client(client["id"], cn))
    activated = validate_success(
        api.activate_client(client["id"], activate_payload(cur["version"]), cn), 200
    )
    assert activated["status"] == "ACTIVE"
    assert activated["monthly_deposit_cents"] == 33500
