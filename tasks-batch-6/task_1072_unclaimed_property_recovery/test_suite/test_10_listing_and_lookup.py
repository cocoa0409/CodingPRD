"""Read surface: not-found lookup, malformed-create rejection, the paginated list
envelope with filtering, and FK reverse-reachability of evidence under a claim.

Translates queue B (entities not-found, required-field, endpoints listing and
evidence reverse-reachability).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    factories as f, fixtures, TEST_USERS,
)
from test_helpers.test_users import make_holder_headers, make_owner_headers, make_examiner_headers


# ---------------------------------------------------------------------------
# Corner/entities/property_not_found_returns_404
# ---------------------------------------------------------------------------
def test_get_unknown_property_returns_not_found(api):
    """PRD §2.11: "the system validates them from left to right and rejects on the first
    identifier that does not resolve, returning the not-found error specific to that entity kind
    (... ERR_PROPERTY_NOT_FOUND ...), each HTTP 404."

    Design: Corner/entities/property_not_found_returns_404
    """
    validate_error(api.get_property("00000000-0000-0000-0000-000000000000",
                   TEST_USERS["state_admin_headers"]),
                   ApiErrorId.ERR_PROPERTY_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Corner/entities/holder_missing_required_field_returns_invalid
# ---------------------------------------------------------------------------
def test_create_holder_missing_type_returns_invalid(api):
    """PRD §2.11: "A malformed request — a missing required field, a value of the wrong shape, or
    an unrecognized enum member — is rejected with ERR_INVALID_REQUEST (HTTP 400)."
    PRD §3.1: "a holder_type that must be one of BANK, INSURER, UTILITY, BROKER, or OTHER."

    POST /holders without holder_type is rejected.

    Design: Corner/entities/holder_missing_required_field_returns_invalid
    """
    payload = {"legal_name": "Acme Bank", "incorporation_state": "NY"}
    validate_error(api.create_holder(payload, TEST_USERS["state_admin_headers"]),
                   ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Corner/endpoints/list_properties_pagination_envelope
# ---------------------------------------------------------------------------
def test_list_properties_pagination_and_filter(api):
    """PRD §2.3: "Every list-based response includes the following fields inside the envelope's
    meta object: limit, offset, total_count, and has_more."
    PRD §3.2: "Properties can be listed and filtered by their holder, their property type, their
    attached report, their status, and their escheat_state".

    A holder with two properties, filtered by holder_id, returns both with total_count 2.

    Design: Corner/endpoints/list_properties_pagination_envelope
    """
    holder = fixtures.create_holder(api)
    hh = make_holder_headers(holder["id"])
    pt = fixtures.create_property_type(api, code="MO02", dormancy_basis="ISSUANCE")
    for owner_name in ("A", "B"):
        validate_success(api.create_property(f.create_property_payload(
            holder["id"], pt["id"], owner_name=owner_name, owner_last_known_state="CA",
            amount_cents=50000, last_activity_date="2020-01-01T00:00:00Z",
            issue_date="2020-01-01T00:00:00Z"), hh), 201)
    data, meta = validate_paginated(api.list_properties(
        TEST_USERS["state_admin_headers"], params={"holder_id": holder["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
    assert len(data) == 2, f"expected 2 properties, got {len(data)}"


# ---------------------------------------------------------------------------
# Corner/endpoints/evidence_reverse_reachable_via_claim_subresource
# ---------------------------------------------------------------------------
def test_evidence_reverse_reachable_via_claim(api):
    """PRD §3.6: "each EvidenceDocument records the claim_id it supports ... Evidence documents
    for a claim can be listed."
    PRD §2.11: "Some read endpoints address a resource through a parent — for example ... the
    evidence documents of a claim".

    GET /claims/{id}/evidence returns the document uploaded for that claim.

    Design: Corner/endpoints/evidence_reverse_reachable_via_claim_subresource
    """
    ctx = fixtures.escheat_property(api, amount_cents=50000, interest_bearing=False,
                                    dormancy_basis="ISSUANCE", pt_code="MO02",
                                    clock="2026-07-15T00:00:00Z")
    owner = fixtures.create_owner(api)
    oh = make_owner_headers(owner["id"])
    claim = validate_success(api.create_claim(
        f.create_claim_payload(ctx["property"]["id"], owner["id"], "OWNER"), oh), 201)
    ex = make_examiner_headers()
    validate_success(api.examine_claim(claim["id"], ex), 200)
    validate_success(api.request_evidence(claim["id"], ex), 200)
    doc = validate_success(api.upload_evidence(claim["id"], f.evidence_payload("GOV_ID"), oh), 201)
    docs = validate_success(api.list_evidence(claim["id"], ex), 200)
    assert len(docs) == 1, f"expected 1 evidence document, got {len(docs)}"
    assert docs[0]["id"] == doc["id"], "listed evidence must be the uploaded document"
