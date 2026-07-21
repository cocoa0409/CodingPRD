"""Claim withdrawal lockdown, list pagination, carrier ownership, and the
user-context header gate."""
from test_helpers import (
    validate_error, validate_paginated,
    create_carrier, create_adverse_party, refer_claim, setup_referred_claim,
    create_claim_payload, build_user_headers, make_carrier_user_headers,
)
from test_helpers import TEST_USERS

READER = TEST_USERS["reader_headers"]


def test_withdraw_already_withdrawn_claim_rejected(api):
    """PRD §3.9: "A `CarrierUser` who owns a claim may withdraw the referral at any
    pre-recovery stage, which moves the claim to `WITHDRAWN`".
    PRD §2.11: "(7) that the target resource is in a state permitting the requested
    transition (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/withdraw_already_withdrawn_claim_returns_invalid_state
    """
    ctx = setup_referred_claim(api)
    owner = make_carrier_user_headers(ctx["carrier"]["id"])
    api.withdraw_claim(ctx["claim"]["id"], owner)  # first withdraw -> WITHDRAWN
    resp = api.withdraw_claim(ctx["claim"]["id"], owner)
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_list_claims_pagination_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_claims_pagination_envelope
    """
    carrier = create_carrier(api)
    ap = create_adverse_party(api)
    refer_claim(api, carrier["id"], ap["id"], claim_reference="CLM-P1")
    refer_claim(api, carrier["id"], ap["id"], claim_reference="CLM-P2")
    resp = api.list_claims(READER, params={"carrier_id": carrier["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_carrier_user_referring_foreign_carrier_rejected(api):
    """PRD §2.1: "A carrier-owned action on a claim the caller does not own —
    referring, withdrawing, accepting a settlement for, or attaching a document to it —
    is rejected with `ERR_NOT_CLAIM_OWNER`."

    Design: Corner/rbac/carrieruser_refer_foreign_carrier_returns_not_claim_owner
    """
    carrier = create_carrier(api, name="Owner Ins", naic_code="66666")
    ap = create_adverse_party(api)
    payload = create_claim_payload(carrier["id"], ap["id"], claim_reference="CLM-OWN")
    foreign = build_user_headers("11111111-1111-4111-8111-111111111111", "CarrierUser")
    resp = api.create_claim(payload, foreign)
    validate_error(resp, "ERR_NOT_CLAIM_OWNER", 403)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "Every request to the API must carry two mandatory headers:
    `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the
    operational capacity in which the request is made. If either header is missing or
    malformed, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_returns_error
    """
    resp = api.list_claims({})
    validate_error(resp, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400)
