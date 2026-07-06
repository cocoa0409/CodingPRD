"""Resource creation defaults, required-field and enum validation, immutability,
filtered listings, and role-based access control.
"""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
    create_account_payload, create_signer_payload, create_request_payload,
    create_document_payload, create_apostille_order_payload,
    TEST_USERS, make_notary_headers,
    setup_world, setup_completed_request,
)

COORD = TEST_USERS["coordinator_headers"]
CLERK = TEST_USERS["apostille_clerk_headers"]
VIEWER = TEST_USERS["viewer_headers"]


# ─── Corner/entities/create_signing_request_returns_201_with_defaults ────────

def test_create_request_returns_201_with_defaults(api):
    """PRD §3.2: "A fresh request starts with `estimate_fee_cents` and `final_fee_cents`
    both at 0."
    PRD §2.4: "an integer `version` that starts at 1 on creation".
    PRD §2.4: "Every resource carries a server-minted `id` that is a UUID with no type
    prefix".

    Design: Corner/entities/create_signing_request_returns_201_with_defaults
    """
    world = setup_world()
    res = api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="GENERAL", delivery_mode="MOBILE",
                               expected_stamp_count=2), COORD)
    request = validate_success(res, 201)
    assert request["status"] == "DRAFT"
    assert request["estimate_fee_cents"] == 0
    assert request["final_fee_cents"] == 0
    assert request["version"] == 1


# ─── Corner/entities/get_request_not_found_returns_404 ───────────────────────

def test_get_request_not_found(api):
    """PRD §2.7: "When a path or body references a resource, existence is validated
    left-to-right: a missing resource anywhere in the chain yields `ERR_NOT_FOUND` before
    any later check runs."

    Design: Corner/entities/get_request_not_found_returns_404
    """
    res = api.get_request(NON_EXISTENT_UUID, VIEWER)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ─── Corner/entities/create_request_missing_required_field_rejected ──────────

def test_create_request_missing_doc_category_rejected(api):
    """PRD §2.8: "Fourth, request-body well-formedness is checked — required fields
    present and well-typed, enum values legal, and any score within the inclusive range 0
    to 100 — yielding `ERR_INVALID_REQUEST`."
    PRD §3.2: "it captures the owning `account_id`, the `signer_id` of the principal, the
    `state_code` where notarization occurs (which selects the governing fee schedule), the
    `doc_category` (one of `GENERAL`, `REAL_ESTATE`, `LOAN_SIGNING`, or `APOSTILLE_BOUND`),
    and the `delivery_mode` (`RON` or `MOBILE`)."

    Design: Corner/entities/create_request_missing_required_field_rejected
    """
    world = setup_world()
    payload = create_request_payload(world["account"]["id"], world["signer"]["id"],
                                     delivery_mode="MOBILE", expected_stamp_count=2)
    del payload["doc_category"]
    res = api.create_request(payload, COORD)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


# ─── Corner/entities/request_default_estimated_travel_miles_zero ─────────────

def test_request_default_estimated_travel_miles_zero(api):
    """PRD §3.2: "It also captures the client-declared `expected_stamp_count` and an
    optional `estimated_travel_miles` (default 0) used only for the provisional estimate."

    Design: Corner/entities/request_default_estimated_travel_miles_zero
    """
    world = setup_world()
    request = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="GENERAL", delivery_mode="MOBILE",
                               expected_stamp_count=2), COORD))
    assert request["estimated_travel_miles"] == 0


# ─── Corner/entities/invalid_enum_id_doc_type_rejected ───────────────────────

def test_create_signer_invalid_id_doc_type_rejected(api):
    """PRD §2.8: "Fourth, request-body well-formedness is checked — required fields
    present and well-typed, enum values legal, and any score within the inclusive range 0
    to 100 — yielding `ERR_INVALID_REQUEST`."
    PRD §3.1: "the government identification presented as `id_doc_type`, one of
    `DRIVERS_LICENSE`, `PASSPORT`, or `STATE_ID`."

    Design: Corner/entities/invalid_enum_id_doc_type_rejected
    """
    world = setup_world()
    payload = create_signer_payload(world["account"]["id"], id_doc_type="PHOTO")
    res = api.create_signer(payload, COORD)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


# ─── Corner/entities/journal_entry_immutable_no_update_endpoint ──────────────

def test_journal_entry_recorded_completed_and_immutable(api):
    """PRD §3.6: "the entry is written with `entry_status` `COMPLETED`. The journal is
    append-only: an entry is never edited, but an operator may administratively void one".
    PRD §2.4: "These are `FeeSchedule` (immutable fee configuration), `JournalEntry` (the
    append-only notarial journal), and `RetentionRecord` (the append-only retention
    ledger). A `JournalEntry` does have a mutable `entry_status` that may move from
    `COMPLETED` to `VOIDED`, but that administrative state change does not introduce a
    `version`".

    Design: Corner/entities/journal_entry_immutable_no_update_endpoint
    """
    world, request, document, journal_ids = setup_completed_request(
        request_overrides={"doc_category": "GENERAL", "delivery_mode": "RON",
                           "expected_stamp_count": 1},
        act_types=("JURAT",))
    entry = get_success_data(api.get_journal_entry(journal_ids[0], VIEWER))
    assert entry["entry_status"] == "COMPLETED"
    assert "version" not in entry


# ─── Corner/endpoints/list_requests_paginated_envelope ───────────────────────

def test_list_requests_returns_array_envelope(api):
    """PRD §2.3: "For every list response, the `meta` object reports `limit`, `offset`,
    `total_count` (the total number of matching records before pagination), and
    `has_more` (true when records remain beyond the current page)."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for
    a list of resources."

    Design: Corner/endpoints/list_requests_paginated_envelope
    """
    world = setup_world()
    for _ in range(2):
        get_success_data(api.create_request(
            create_request_payload(world["account"]["id"], world["signer"]["id"],
                                   doc_category="GENERAL", delivery_mode="MOBILE",
                                   expected_stamp_count=1), COORD))
    data, meta = validate_paginated(api.list_requests(VIEWER, params={"account_id": world["account"]["id"]}))
    assert len(data) == 2
    assert meta["total_count"] >= 2


# ─── Corner/endpoints/documents_filtered_list_by_request_id ──────────────────

def test_list_documents_filtered_by_request(api):
    """PRD §2.7: "child collections (documents, sessions, verifications, journal entries,
    assignments, retention records) are addressed as top-level collections filtered by a
    parent foreign key such as `request_id`."

    Design: Corner/endpoints/documents_filtered_list_by_request_id
    """
    world = setup_world()
    request = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="GENERAL", delivery_mode="MOBILE",
                               expected_stamp_count=1), COORD))
    get_success_data(api.create_document(
        create_document_payload(request["id"], title="A", doc_type="AFFIDAVIT",
                                signing_fee_cents=1000), COORD))
    get_success_data(api.create_document(
        create_document_payload(request["id"], title="B", doc_type="POA",
                                signing_fee_cents=2000), COORD))
    data, meta = validate_paginated(api.list_documents(VIEWER, params={"request_id": request["id"]}))
    assert len(data) == 2
    assert all(d["request_id"] == request["id"] for d in data)


# ─── Corner/rbac/viewer_cannot_create_request ────────────────────────────────

def test_viewer_cannot_create_request(api):
    """PRD §2.1: "If the header is present and valid but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §2.1: "`Viewer` is a read-only auditor that may read any resource but mutate
    nothing."

    Design: Corner/rbac/viewer_cannot_create_request
    """
    world = setup_world()
    res = api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="GENERAL", delivery_mode="MOBILE",
                               expected_stamp_count=1), VIEWER)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


# ─── Corner/rbac/notary_cannot_route_apostille ───────────────────────────────

def test_notary_cannot_route_apostille(api):
    """PRD §2.1: "the mutating operations are partitioned among `CoordinatorOps`,
    `Notary`, and `ApostilleClerk`".
    PRD §2.1: "`ApostilleClerk` is the Secretary-of-State authentication clerk. It
    submits, routes, returns, resubmits, authenticates, and rejects apostille orders."

    Design: Corner/rbac/notary_cannot_route_apostille
    """
    world = setup_world()
    request = get_success_data(api.create_request(
        create_request_payload(world["account"]["id"], world["signer"]["id"],
                               doc_category="APOSTILLE_BOUND", delivery_mode="MOBILE",
                               expected_stamp_count=1), COORD))
    document = get_success_data(api.create_document(
        create_document_payload(request["id"], title="Cert", doc_type="BIRTH_CERT",
                                requires_apostille=True, signing_fee_cents=1000), COORD))
    order = get_success_data(api.create_apostille_order(
        create_apostille_order_payload(document["id"], destination_country="FR",
                                       sos_office_state="CA"), CLERK))
    nheaders = make_notary_headers(world["notary"]["id"])
    res = api.route_apostille_order(order["id"], nheaders)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


# ─── Corner/rbac/missing_role_header_unauthenticated ─────────────────────────

def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or is not one of the recognised role names,
    the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    from test_helpers import build_user_headers
    ghost = build_user_headers("ghost-1", "Ghost")
    res = api.create_account(create_account_payload(), ghost)
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
