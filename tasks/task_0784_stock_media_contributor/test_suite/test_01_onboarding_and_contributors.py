"""Contributor onboarding, registration defaults, versioning, and tax verification."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    make_contributor_headers,
    create_contributor_payload, create_asset_payload,
    register_contributor, get_contributor, submit_and_verify_tax_form,
    assert_contributor,
)

FINANCE = TEST_USERS["finance_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


def test_register_contributor_returns_201_with_computed_defaults(api):
    """PRD §3.1: "The new `Contributor` is created in `onboarding_status` `PENDING` with every
    computed field at its default: `tax_form_status` `MISSING`, `exclusivity` `NON_EXCLUSIVE`,
    `royalty_level` `BRONZE`, `lifetime_earnings_cents` 0, `available_balance_cents` 0,
    `accepted_asset_count` 0, and `strike_count` 0."

    Design: Corner/entities/corner_create_contributor_returns_201_defaults
    """
    data = validate_success(api.create_contributor(create_contributor_payload(display_name="Zoe")), 201)
    assert_contributor(data)
    assert data["onboarding_status"] == "PENDING"
    assert data["tax_form_status"] == "MISSING"
    assert data["royalty_level"] == "BRONZE"
    assert data["exclusivity"] == "NON_EXCLUSIVE"
    assert data["lifetime_earnings_cents"] == 0
    assert data["available_balance_cents"] == 0
    assert data["accepted_asset_count"] == 0
    assert data["strike_count"] == 0
    assert data["version"] == 1, "version starts at 1 on creation"


def test_get_unknown_contributor_returns_not_found(api):
    """PRD §2.8: "Any unresolved identifier yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/corner_get_contributor_not_found
    """
    resp = api.get_contributor(NON_EXISTENT_UUID, FINANCE)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_contributor_version_increments_by_one_per_mutation(api):
    """PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by exactly 1
    on every mutation of that resource; it is the concurrency token described in §2.6."
    PRD §3.1: "Submitting a tax form creates it in `status` `SUBMITTED`, sets the contributor's
    `tax_form_status` to `SUBMITTED`, and increments the contributor's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/corner_version_increments_on_mutation
    """
    c = register_contributor(api, display_name="Vi")
    submit_and_verify_tax_form(api, c["id"], tax_id="US-13")
    data = get_contributor(api, c["id"])
    assert data["version"] == 3, "create (1) -> tax submit (2) -> verify+activate (3)"


def test_verify_tax_form_moves_form_to_verified(api):
    """PRD §3.1: "Verifying a form that is `SUBMITTED` moves that form to `VERIFIED`, sets the
    contributor's `tax_form_status` to `VERIFIED`, and — if the contributor is still `PENDING` —
    advances the contributor's `onboarding_status` from `PENDING` to `ACTIVE`; both the tax form's
    `version` and the contributor's `version` increment by 1."

    Design: Difficulty/transitive_cascade/taxform_verify_activates_contributor_depth2
    """
    c = register_contributor(api, display_name="Ha")
    ch = make_contributor_headers(c["id"])
    tf = validate_success(api.create_tax_form(c["id"], {"form_type": "W9", "tax_id": "US-777"}, ch), 201)
    decided = validate_success(api.decide_tax_form(tf["id"], {"decision": "VERIFY"}, COMPLIANCE))
    assert decided["status"] == "VERIFIED"


def test_verify_tax_form_activates_pending_contributor(api):
    """PRD §3.1: "Verifying a form that is `SUBMITTED` moves that form to `VERIFIED`, sets the
    contributor's `tax_form_status` to `VERIFIED`, and — if the contributor is still `PENDING` —
    advances the contributor's `onboarding_status` from `PENDING` to `ACTIVE`; both the tax form's
    `version` and the contributor's `version` increment by 1."

    Design: Difficulty/transitive_cascade/taxform_verify_activates_contributor_depth2
    """
    c = register_contributor(api, display_name="Ha2")
    submit_and_verify_tax_form(api, c["id"], tax_id="US-777")
    data = get_contributor(api, c["id"])
    assert data["onboarding_status"] == "ACTIVE"
    assert data["tax_form_status"] == "VERIFIED"


def test_list_contributors_returns_paginated_array(api):
    """PRD §2.3: "The `meta` block of a list response carries the `limit` and `offset` in effect,
    the `total_count` of matching rows before pagination, and a `has_more` boolean that is true
    when rows remain beyond the current page."

    Design: Corner/entities/corner_list_contributors_pagination_envelope
    """
    register_contributor(api, display_name="P1")
    register_contributor(api, display_name="P2")
    data, meta = validate_paginated(api.list_contributors(FINANCE, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True, "limit 1 of 2 rows leaves more"
    assert len(data) == 1


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the four roles
    defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/corner_missing_auth_headers
    """
    resp = api.list_downloads(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_create_asset_with_unresolved_contributor_fk_not_found(api):
    """PRD §2.8: "a body foreign key such as `asset_id`, `contributor_id`, `model_release_id`,
    `similar_to_asset_id`, or `license_tier_code` is validated after the path. Any unresolved
    identifier yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/corner_fk_asset_contributor_not_found
    """
    headers = make_contributor_headers(NON_EXISTENT_UUID)
    resp = api.create_asset(create_asset_payload(NON_EXISTENT_UUID), headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
