"""Registry basics: owners, properties, applications — creation, envelopes, pagination."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_valid_uuid, is_iso8601_timestamp, NON_EXISTENT_UUID, build_user_headers,
    TEST_USERS, ApiErrorId,
    create_owner_payload, create_property_payload, create_application_payload,
    create_association, register_owner, register_property,
    create_draft_application, add_required_attachments,
    assert_owner, assert_property, assert_application,
    make_homeowner_headers,
)

MANAGER = TEST_USERS["manager_headers"]


def test_create_owner_returns_system_fields(api):
    """Owner registration returns 201 with a server-minted id and echoed inputs.

    PRD §3.1: "the manager registers owners — each scoped to the association
    through its `association_id` — by supplying a `full_name` and a contact `email`"
    PRD §2.4: "`id` (string): a unique, server-generated identifier formatted as a
    UUID, with no type prefix."

    Design: Corner/entities/create_owner_success_returns_system_fields
    """
    assoc = create_association(name="Base HOA")
    res = api.create_owner(assoc["id"], create_owner_payload(
        full_name="Ann A", email="ann.a@x.com"), MANAGER)
    owner = validate_success(res, 201)
    assert_owner(owner)
    assert is_valid_uuid(owner["id"]), "owner id must be a server-minted UUID"
    assert owner["full_name"] == "Ann A"
    assert owner["email"] == "ann.a@x.com"
    assert owner["association_id"] == assoc["id"]
    assert is_iso8601_timestamp(owner["created_at"])
    assert isinstance(owner["version"], int)


def test_create_owner_missing_email_rejected(api):
    """Omitting the required email is rejected and no owner row is created.

    PRD §3.1: owners are registered "by supplying a `full_name` and a contact `email`".
    PRD §2.9: "Request body shape: required fields are present, enum fields hold
    declared members, and unknown fields are rejected; violations yield
    `ERR_INVALID_REQUEST` (400), with enum member violations yielding
    `ERR_INVALID_ENUM` (400)."

    Design: Corner/entities/create_owner_missing_email_rejected
    """
    assoc = create_association(name="Base HOA")
    res = api.create_owner(assoc["id"], {"full_name": "No Email"}, MANAGER)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
    data, meta = validate_paginated(api.list_owners(assoc["id"], MANAGER))
    assert data == [], f"no owner row may be created by a rejected request, got {data}"
    assert meta["total_count"] == 0


def test_create_application_invalid_project_type_returns_invalid_enum(api):
    """project_type outside the declared members fails with ERR_INVALID_ENUM.

    PRD §3.3: "the `project_type` (one of `ADDITION`, `FENCE`, `PAINT`, `ROOF`,
    `SOLAR`, or `OTHER`)"
    PRD §2.9: "enum fields hold declared members, and unknown fields are rejected;
    violations yield `ERR_INVALID_REQUEST` (400), with enum member violations
    yielding `ERR_INVALID_ENUM` (400)."

    Design: Corner/entities/create_application_invalid_project_type_returns_invalid_enum
    """
    assoc = create_association(name="Enum HOA")
    owner = register_owner(assoc["id"])
    prop = register_property(assoc["id"], owner["id"], lot_number="N-1",
                             address="1 Enum Ct")
    payload = create_application_payload(owner["id"], project_type="POOL",
                                         guideline_section="SEC-6.6",
                                         description="pool")
    res = api.create_application(prop["id"], payload,
                                 make_homeowner_headers(owner["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_ENUM)


def test_get_nonexistent_application_returns_not_found(api):
    """A well-formed but unknown application id yields the specific 404.

    PRD §2.9: "Path existence: path template identifiers resolve to existing
    resources, validated left to right; the first unresolved identifier yields
    its specific 404 — `ERR_ASSOCIATION_NOT_FOUND`, `ERR_OWNER_NOT_FOUND`,
    `ERR_PROPERTY_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`"

    Design: Corner/entities/get_nonexistent_application_returns_not_found
    """
    create_association(name="NF HOA")
    res = api.get_application(NON_EXISTENT_UUID, MANAGER)
    validate_error(res, ApiErrorId.ERR_APPLICATION_NOT_FOUND)


def test_property_computed_defaults_on_creation(api):
    """A freshly registered property reports zeroed ledger fields and CLEAR posture.

    PRD §3.1: "A newly registered property starts with its `compliance_posture` at
    `CLEAR`, its `outstanding_fine_balance_cents` at zero, and its
    `open_permit_count` at zero."

    Design: Corner/entities/property_computed_defaults_on_creation
    """
    assoc = create_association(name="Def HOA")
    owner = register_owner(assoc["id"])
    res = api.create_property(assoc["id"], create_property_payload(
        owner["id"], lot_number="D-1", address="1 Default Dr"), MANAGER)
    prop = validate_success(res, 201)
    assert_property(prop)
    assert prop["outstanding_fine_balance_cents"] == 0
    assert prop["open_permit_count"] == 0
    assert prop["compliance_posture"] == "CLEAR"


def test_application_version_increments_per_mutation(api):
    """Each application mutation increments version by exactly one.

    PRD §3.3: "A successful submission stamps `submitted_at` — this stamp is
    written on the first submission only and is never restamped by any later
    resubmission, because the statutory clock of §3.5 anchors to it — and
    increments the application's `version` by one."
    PRD §3.4: "A `Manager` opens committee review on a `SUBMITTED` application,
    moving it to `UNDER_REVIEW`, stamping `review_started_at`, and incrementing
    `version` by one."

    Design: Corner/entities/application_version_progression_on_mutations
    """
    assoc = create_association(name="Ver HOA")
    owner = register_owner(assoc["id"])
    prop = register_property(assoc["id"], owner["id"], lot_number="V-1",
                             address="1 Version Ct")
    app = create_draft_application(prop["id"], owner, project_type="PAINT",
                                   guideline_section="SEC-3.1",
                                   description="repaint")
    add_required_attachments(app["id"], owner["id"])
    v_create = app["version"]

    submitted = validate_success(api.submit_application(
        app["id"], make_homeowner_headers(owner["id"])), 200)
    assert submitted["version"] == v_create + 1, (
        f"submit must increment version by one: {v_create} -> {submitted['version']}")

    under_review = validate_success(api.start_review(app["id"], MANAGER), 200)
    assert under_review["version"] == submitted["version"] + 1, (
        "start-review must increment version by one: "
        f"{submitted['version']} -> {under_review['version']}")


def test_application_initial_state_is_draft(api):
    """A newly created application starts in DRAFT with decision_outcome NONE.

    PRD §3.3: "A new application starts in `DRAFT` status with `decision_outcome`
    at `NONE`, an empty `decision_reason`, an empty `conditions` list, and
    `applicant_hold_days` at zero."

    Design: Corner/state_machines/application_initial_state_is_draft
    """
    assoc = create_association(name="Init HOA")
    owner = register_owner(assoc["id"])
    prop = register_property(assoc["id"], owner["id"], lot_number="I-1",
                             address="1 Init Ct")
    res = api.create_application(prop["id"], create_application_payload(owner["id"]),
                                 make_homeowner_headers(owner["id"]))
    app = validate_success(res, 201)
    assert_application(app)
    assert app["status"] == "DRAFT"
    assert app["decision_outcome"] == "NONE"
    assert app["decision_reason"] == ""
    assert app["conditions"] == []
    assert app["applicant_hold_days"] == 0


def test_error_envelope_shape_on_not_found(api):
    """Error responses carry response_type 'error' with error_id and message.

    PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format"
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id`
    and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."

    Design: Corner/endpoints/error_envelope_shape_on_not_found
    """
    create_association(name="Env HOA")
    res = api.get_property(NON_EXISTENT_UUID, MANAGER)
    validate_error(res, ApiErrorId.ERR_PROPERTY_NOT_FOUND)
    body = res.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_PROPERTY_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert body["meta"]["api_request_id"]


def test_list_owners_pagination_limit_offset(api):
    """limit/offset page through the owner list with correct meta fields.

    PRD §2.3: "Paginated list-based responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/endpoints/list_owners_pagination_limit_offset
    """
    assoc = create_association(name="Page HOA")
    for i in range(1, 4):
        register_owner(assoc["id"], full_name=f"O {i}", email=f"o{i}@x.com")

    data, meta = validate_paginated(api.list_owners(
        assoc["id"], MANAGER, params={"limit": 2}))
    assert len(data) == 2, f"limit=2 must return 2 rows, got {len(data)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    data2, meta2 = validate_paginated(api.list_owners(
        assoc["id"], MANAGER, params={"limit": 2, "offset": 2}))
    assert len(data2) == 1, f"offset=2 with 3 rows must return 1 row, got {len(data2)}"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
