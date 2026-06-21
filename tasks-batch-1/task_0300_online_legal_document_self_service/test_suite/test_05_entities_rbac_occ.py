"""Entity CRUD basics, defaults, immutability, listing/pagination, RBAC gates,
and optimistic-concurrency on revision creation.

Queue B (Corner): entities, rbac, cross_cutting_complexity_layers.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error, validate_paginated,
    is_valid_uuid, build_user_headers,
    create_customer_payload, create_clause_template_payload,
    create_document_revision_payload, full_answers,
    make_customer_headers, make_attorney_headers, TEST_USERS,
    setup_active_account, create_clause_templates, create_project,
    setup_assembled_project, setup_assembled_with_revision, create_revision,
    assert_assembled_clause,
)

ADMIN = TEST_USERS["admin_headers"]
CUSTOMER = TEST_USERS["customer_headers"]


# ─── Queue B (Corner): entities ───────────────────────

def test_create_customer_returns_201_with_fields(api):
    """PRD §3.1: "Everything begins with a Customer, created with an email (the login
    email, unique among customers), a full_name (the customer's legal name), and a
    state_of_residence."
    PRD §2.4: "Every such resource has an id — a server-minted UUID with no type prefix —
    and a created_at timestamp" ... "an integer version that begins at 1"

    Design: Corner/entities/create_customer_returns_201_with_fields
    """
    res = api.create_customer(
        create_customer_payload(email="c-unique@x.com", full_name="C", state_of_residence="CA"),
        CUSTOMER)
    cust = validate_success(res, 201)
    assert cust["email"] == "c-unique@x.com"
    assert cust["full_name"] == "C"
    assert cust["state_of_residence"] == "CA"
    assert is_valid_uuid(cust["id"]) and "_" not in cust["id"]
    assert cust["version"] == 1


def test_get_customer_not_found_returns_404(api):
    """PRD §2.8: "the system resolves those identifiers and rejects the request with
    ERR_NOT_FOUND (HTTP 404) if any of them does not correspond to an existing resource."

    Design: Corner/entities/get_customer_not_found_returns_404
    """
    res = api.get_customer("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_customer_missing_required_field_rejected(api):
    """PRD §2.8: "Well-formedness of the request body itself — required fields present, enum
    values within their allowed sets, a non-empty signer list — is enforced with
    ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_customer_missing_required_field_rejected
    """
    res = api.create_customer({"email": "c@x.com", "full_name": "C"}, CUSTOMER)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_customer_invalid_enum_state_rejected(api):
    """PRD §2.10: "A customer's state_of_residence, a clause template's state_code, a
    project's state_code, an attorney's bar_state, and a notary referral's
    referral_state_code are each one of the two-letter codes CA, NY, TX, or FL."
    PRD §2.8: "Well-formedness of the request body itself — required fields present, enum
    values within their allowed sets, a non-empty signer list — is enforced with
    ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_customer_invalid_enum_state_rejected
    """
    res = api.create_customer(
        {"email": "c@x.com", "full_name": "C", "state_of_residence": "ZZ"}, CUSTOMER)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_project_attorney_review_addon_defaults_false(api):
    """PRD §3.2: "The customer may also set attorney_review_addon (whether the paid
    attorney-review add-on is elected, defaulting to false when omitted)."
    PRD §3.2: "The project is born in DRAFT status." ... "the project's credit_held flag is
    set true to mark that it is holding one of that subscription's credits"

    Design: Corner/entities/project_attorney_review_addon_defaults_false
    """
    plan, cust, ch, sub = setup_active_account(state="CA", tier="STANDARD")
    proj = create_project(cust, ch, sub, "WILL", "CA", "Defaults")
    assert proj["attorney_review_addon"] is False, proj
    assert proj["status"] == "DRAFT", proj
    assert proj["credit_held"] is True, proj


def test_assembled_clause_has_no_version_field(api):
    """PRD §2.4: "The AssembledClause resource is immutable once written: it is a frozen
    snapshot of a clause template taken at assembly time, and it carries only id and
    created_at. An AssembledClause has no updated_at field and no version field"
    PRD §3.4: "copying each template's body_text, clause_key, and is_mandatory into the
    frozen clause"

    Design: Corner/entities/assembled_clause_has_no_version_field
    """
    ctx = setup_assembled_project(state="CA", document_type="WILL", addon=False, mandatory_clauses=1)
    ch = ctx["customer_headers"]
    res = api.list_assembled_clauses(ch, params={"document_project_id": ctx["project"]["id"]})
    clauses = res.json()["data"]
    assert len(clauses) == 1, clauses
    ac = clauses[0]
    assert ac["clause_key"] == "C1", ac
    assert ac["is_mandatory"] is True, ac
    assert ac["body_text"] == "c1", ac
    assert_assembled_clause(ac)


def test_list_clause_templates_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the meta object
    of the response envelope: limit, offset, total_count, and has_more."
    PRD §2.2: "The response_type is either "object" for a single resource or "array" for a
    list of resources."

    Design: Corner/entities/list_clause_templates_pagination_envelope
    """
    create_clause_templates("WILL", "CA", 1, 1, key_prefix="W")
    res = api.list_clause_templates(
        ADMIN, params={"document_type": "WILL", "state_code": "CA", "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
    assert len(data) == 1, data


# ─── Queue B (Corner): rbac ───────────────────────────

def test_customer_cannot_create_clause_template(api):
    """PRD §2.1: "When the header is present and valid but the named role is not permitted
    to perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE
    (HTTP 403)."
    PRD §4: clause-template creation is authorized for PlatformAdmin only.

    Design: Corner/rbac/customer_cannot_create_clause_template
    """
    res = api.create_clause_template(
        create_clause_template_payload("X1", "WILL", "CA", True, "x"), CUSTOMER)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_customer_cannot_transition_attorney_review(api):
    """PRD §2.1: "When the header is present and valid but the named role is not permitted
    to perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE
    (HTTP 403)."
    PRD §4: advancing an attorney review is authorized for Attorney only.

    Design: Corner/rbac/customer_cannot_transition_attorney_review
    """
    from test_helpers import create_attorney_payload, create_attorney_review_payload
    ctx = setup_assembled_project(state="CA", document_type="WILL", addon=True, mandatory_clauses=1)
    ch = ctx["customer_headers"]
    att = get_success_data(api.create_attorney(create_attorney_payload(bar_state="CA"), ADMIN))
    review = get_success_data(api.create_attorney_review(
        create_attorney_review_payload(ctx["project"]["id"], att["id"],
                                       "2026-03-12T10:00:00.000Z", "2026-03-12T12:00:00.000Z"), ch))
    res = api.transition_attorney_review(review["id"], {"to_status": "IN_REVIEW"}, ch)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_wrong_attorney_cannot_advance_review(api):
    """PRD §2.1: "an attorney may only advance a review whose attorney_id equals X-User-ID,
    and an attempt to advance someone else's review is rejected with ERR_NOT_REVIEW_OWNER
    (HTTP 403)."

    Design: Corner/rbac/wrong_attorney_cannot_advance_review
    """
    from test_helpers import create_attorney_payload, create_attorney_review_payload
    ctx = setup_assembled_project(state="CA", document_type="WILL", addon=True, mandatory_clauses=1)
    ch = ctx["customer_headers"]
    attA = get_success_data(api.create_attorney(create_attorney_payload(full_name="Atty A", bar_state="CA"), ADMIN))
    attB = get_success_data(api.create_attorney(create_attorney_payload(full_name="Atty B", bar_state="CA"), ADMIN))
    review = get_success_data(api.create_attorney_review(
        create_attorney_review_payload(ctx["project"]["id"], attA["id"],
                                       "2026-03-13T10:00:00.000Z", "2026-03-13T12:00:00.000Z"), ch))
    res = api.transition_attorney_review(
        review["id"], {"to_status": "IN_REVIEW"}, make_attorney_headers(attB["id"]))
    validate_error(res, "ERR_NOT_REVIEW_OWNER")


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If the X-User-Role header is missing or names a value outside this set,
    the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    res = api.get_customer("00000000-0000-4000-8000-000000000000",
                           build_user_headers("nobody", "Nobody"))
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── Queue B (Corner): cross_cutting_complexity_layers ──

def test_occ_stale_project_version_on_revision_create(api):
    """PRD §2.6: "The server compares this value against the project's current version. If
    they match, the revision is created and the project's version advances. If another
    writer has already created a revision (or otherwise advanced the project) since the
    client last read it, the supplied value is stale, and the create is rejected with
    ERR_STALE_PROJECT_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_project_version_on_revision_create
    """
    ctx = setup_assembled_project(state="CA", document_type="WILL", addon=False, mandatory_clauses=1)
    ch = ctx["customer_headers"]
    observed_version = ctx["project"]["version"]
    # First create succeeds and bumps the project version.
    validate_success(api.create_document_revision(
        create_document_revision_payload(ctx["project"]["id"], observed_version), ch), 201)
    # Second create with the same (now stale) version is rejected.
    res = api.create_document_revision(
        create_document_revision_payload(ctx["project"]["id"], observed_version), ch)
    validate_error(res, "ERR_STALE_PROJECT_VERSION")


def test_occ_correct_version_succeeds_and_supersedes(api):
    """PRD §3.6: "The new revision is the project's FINAL revision; any prior revision of
    the same project that was FINAL is flipped to SUPERSEDED, so exactly one revision per
    project is FINAL at a time. Creating a revision advances the project's version by one"
    PRD §3.6: "On creation the new revision is assigned a revision_number — a 1-based
    sequence within the project, ordered by creation time (created_at ascending)"

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_supersedes
    """
    ctx = setup_assembled_with_revision(state="CA", document_type="WILL", mandatory_clauses=1)
    ch = ctx["customer_headers"]
    rev1 = ctx["revision"]
    live = get_success_data(api.get_document_project(ctx["project"]["id"], ch))
    rev2 = validate_success(api.create_document_revision(
        create_document_revision_payload(ctx["project"]["id"], live["version"]), ch), 201)
    assert rev2["revision_number"] == 2, rev2
    rev1_after = get_success_data(api.get_document_revision(rev1["id"], ch))
    assert rev1_after["status"] == "SUPERSEDED", rev1_after
