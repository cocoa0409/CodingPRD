"""Catalog creation, contract CRUD, FK/required-field validation, RBAC, pagination.

Translates corner-design instances from sections entities, endpoints, rbac.
"""
from test_helpers import (
    api_client,
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_coverage_plan_payload,
    create_reinsurance_pool_payload,
    create_contract_payload,
    create_ancillary_product_payload,
    NON_EXISTENT_UUID,
)
from test_helpers.fixtures import (
    create_pool,
    create_active_plan,
    setup_active_contract,
    setup_submitted_claim,
)

ADMIN = TEST_USERS["admin_underwriter_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_create_coverage_plan_returns_201_draft_version_1(api):
    """PRD §3.1: "A coverage plan is created in `DRAFT` status with a marketing `name`".
    PRD §2.4: "a `version` (an integer that starts at 1 and increments by one on every mutation)".

    Design: Corner/entities/create_coverage_plan_returns_201_with_fields
    """
    resp = api.create_coverage_plan(create_coverage_plan_payload(), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT", f"expected DRAFT, got {data['status']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"


def test_get_contract_not_found_returns_404(api):
    """PRD §2.7: "the system checks each segment's resource in order and rejects
    with `ERR_NOT_FOUND` (HTTP 404) at the first path id that does not resolve."

    Design: Corner/entities/get_contract_not_found_returns_404
    """
    resp = api.get_contract(NON_EXISTENT_UUID, CONTRACT_ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_create_contract_missing_vin_returns_invalid_request(api):
    """PRD §2.6: "a missing or ill-typed required field is rejected with
    `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_contract_missing_required_field_returns_invalid_request
    """
    pool = create_pool("Pool X")
    plan = create_active_plan()
    payload = create_contract_payload(plan["id"], pool["id"])
    del payload["vin"]
    resp = api.create_contract(payload, CONTRACT_ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_contract_default_financed_false(api):
    """PRD §3.2: "Two finance fields complete the payload: `financed` defaults to false".
    PRD §3.2: "A freshly sold contract is in `PENDING` status."

    Design: Corner/entities/create_contract_default_financed_false
    """
    pool = create_pool("Pool DF")
    plan = create_active_plan()
    resp = api.create_contract(create_contract_payload(plan["id"], pool["id"], vin="VINDF00001"), CONTRACT_ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["financed"] is False, f"expected financed false, got {data['financed']}"
    assert data["status"] == "PENDING", f"expected PENDING, got {data['status']}"


def test_create_contract_bad_plan_id_returns_fk_not_found(api):
    """PRD §2.7: "Body foreign-key references — `coverage_plan_id`, `reinsurance_pool_id`,
    `contract_id`, `repair_facility_id`, and `claim_id` ... must resolve to existing rows;
    an unresolved body reference is rejected with `ERR_FK_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/contract_fk_not_found_on_bad_plan_id
    """
    pool = create_pool("Pool FK")
    resp = api.create_contract(
        create_contract_payload(NON_EXISTENT_UUID, pool["id"], vin="VINFK00001"),
        CONTRACT_ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND)


def test_ledger_entry_immutable_no_version_field(api):
    """PRD §2.4: "The `LedgerEntry`, the `ClockState`, and the `AuditEvent` carry only
    `id` and `created_at`; they have neither an `updated_at` nor a `version`".
    PRD §3.4: "posts a `RESERVE_SET` entry that increases the pool's `reserve_held_cents`".

    Design: Corner/entities/ledger_entry_immutable_no_version_field
    """
    base = setup_submitted_claim(
        claim_lines=[{"line_type": "PART", "part_number": "EN-3", "requested_amount_cents": 50000, "covered": True}],
    )
    api.start_review_claim(base["claim"]["id"], ADJUSTER)
    resp = api.list_pool_ledger_entries(base["pool"]["id"], AUDITOR)
    entries, _meta = validate_paginated(resp)
    reserve_sets = [e for e in entries if e["entry_type"] == "RESERVE_SET"]
    assert len(reserve_sets) >= 1, "expected a RESERVE_SET ledger entry"
    e = reserve_sets[0]
    assert e["amount_cents"] == 50000, f"expected RESERVE_SET 50000, got {e['amount_cents']}"
    assert "version" not in e, "LedgerEntry must not expose version"
    assert "updated_at" not in e, "LedgerEntry must not expose updated_at"


def test_list_contracts_pagination_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_contracts_pagination_envelope
    """
    setup_active_contract(pool_name="Pool PG", contract_overrides={"vin": "VINPG00001"})
    resp = api.list_contracts(AUDITOR)
    data, meta = validate_paginated(resp)
    assert len(data) >= 1, "expected at least one contract"
    assert "total_count" in meta, "meta must carry total_count"
    assert "has_more" in meta, "meta must carry has_more"


def test_list_claims_for_contract_reverse_reachability(api):
    """PRD §2.7: "The list endpoints rooted at a parent resource ... a contract's
    ancillaries, claims, cancellation, and ledger entries ... are the
    reverse-reachability views over these foreign keys."

    Design: Corner/endpoints/list_claims_for_contract_reverse_reachability
    """
    base = setup_submitted_claim(claim_overrides={"complaint": "x"}, pool_name="Pool RR",
                                 contract_overrides={"vin": "VINRR00001"})
    resp = api.list_contract_claims(base["contract"]["id"], ADJUSTER)
    data, _meta = validate_paginated(resp)
    ids = [c["id"] for c in data]
    assert base["claim"]["id"] in ids, "contract's claim must appear in reverse-reachability list"
    assert len(data) == 1, f"expected exactly one claim, got {len(data)}"


def test_contract_admin_cannot_create_plan(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/contract_admin_cannot_create_plan
    """
    resp = api.create_coverage_plan(create_coverage_plan_payload(), CONTRACT_ADMIN)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "If the `X-User-Role` header is missing or names a role outside this
    set, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    resp = api.list_coverage_plans({"X-User-ID": "nobody"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
