"""Resource CRUD, access control, listing, and computed-read breadth tests.

All tests in this file translate non-stub instances from the corner-design index
(queue B). Each test docstring carries its own corner-design tag.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    create_program_payload,
    create_beneficiary_payload,
    create_contribution_payload,
    make_program_admin_headers,
    make_medicaid_agency_headers,
    make_beneficiary_headers,
    make_invalid_role_headers,
    setup_program_and_option,
    setup_certified_beneficiary,
    setup_open_account,
    create_program,
    create_beneficiary,
    add_representative,
    create_pending_certification,
    post_contribution,
    get_account,
)

ADMIN = make_program_admin_headers()


# ---------------------------------------------------------------------------
# Section: entities
# ---------------------------------------------------------------------------
def test_create_beneficiary_returns_201_with_defaults(api):
    """PRD 3.2: "A newly registered beneficiary is born with `eligibility_status` of
    `UNCERTIFIED`, with the computed `is_deceased` flag false."
    PRD 3.2: "`other_countable_resources_cents` (non-ABLE countable resources, defaulting
    to zero), `receives_ssi` and `receives_medicaid` (both defaulting to false)"

    Design: Corner/entities/create_beneficiary_returns_201_with_defaults
    """
    program = create_program()
    resp = api.create_beneficiary(
        create_beneficiary_payload(program["id"], full_name="New Ben"), ADMIN
    )
    data = validate_success(resp, 201)
    assert data["eligibility_status"] == "UNCERTIFIED"
    assert data["is_deceased"] is False
    assert data["other_countable_resources_cents"] == 0
    assert data["receives_ssi"] is False


def test_get_account_not_found_returns_404(api):
    """PRD 2.5: "the server validates them strictly left to right and rejects the request
    with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource."

    Design: Corner/entities/get_account_not_found_returns_404
    """
    resp = api.get_account(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_list_contributions_paginated_envelope(api):
    """PRD 2.3: "`limit` sets the maximum number of items returned"
    PRD 2.3: "The `meta` object of every list response carries the `limit`, `offset`,
    `total_count`, and `has_more` fields."

    Design: Corner/entities/list_contributions_paginated_envelope
    """
    _, _, beneficiary, account = setup_open_account()
    post_contribution(account["id"], 100_000, account["version"])
    v2 = get_account(account["id"])["version"]
    post_contribution(account["id"], 200_000, v2)

    resp = api.list_contributions(ADMIN, params={"account_id": account["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"limit=1 must return one item, got {len(data)}"
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True


def test_account_computed_ledger_correct_after_contribution(api):
    """PRD 3.3: "Its `basis_cents` is the sum of the amounts of all `POSTED` contributions
    (the cost basis)."
    PRD 3.3: "Its `balance_cents` is basis plus earnings minus what has been distributed."
    PRD 3.3: "`regular_contrib_ytd_cents` sums the amounts of `POSTED` `REGULAR` and
    `ROLLOVER_529` contributions in the current calendar year"

    Design: Corner/entities/account_computed_ledger_correct_after_contribution
    """
    _, _, _, account = setup_open_account()
    post_contribution(account["id"], 300_000, account["version"])
    data = validate_success(api.get_account(account["id"], ADMIN))
    assert data["balance_cents"] == 300_000
    assert data["basis_cents"] == 300_000
    assert data["earnings_cents"] == 0
    assert data["regular_contrib_ytd_cents"] == 300_000


def test_system_fields_id_version_generated(api):
    """PRD 2.4: "Every primary resource carries a server-minted `id` formatted as a UUID
    with no type prefix"
    PRD 2.4: "an integer `version` that begins at its initial value and increases by one
    on every mutation of that resource."

    Design: Corner/entities/system_fields_id_version_generated_input_ignored
    """
    resp = api.create_program(create_program_payload(), ADMIN)
    data = validate_success(resp, 201)
    assert data["version"] == 1, f"a freshly created resource has version 1, got {data['version']}"
    assert is_valid_uuid(data["id"]), "id must be a UUID with no type prefix"
    assert "_" not in data["id"], "id must have no type prefix"


def test_create_beneficiary_missing_required_field_returns_invalid_request(api):
    """PRD 2.5: "then request-body well-formedness — required fields present, correctly
    typed, enum members valid, and any `amount_cents` strictly greater than zero
    (`ERR_INVALID_REQUEST`)"

    Design: Corner/entities/create_beneficiary_missing_required_field_returns_invalid_request
    """
    program = create_program()
    payload = create_beneficiary_payload(program["id"])
    del payload["disability_onset_date"]
    resp = api.create_beneficiary(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


# ---------------------------------------------------------------------------
# Section: endpoints
# ---------------------------------------------------------------------------
def test_get_means_test_computed_read_ssi_ok(api):
    """PRD 3.7: "the portion of the ABLE balance that counts against SSI is the amount by
    which `balance_cents` exceeds the program's `ssi_suspension_threshold_cents`, floored at
    zero — so a balance at or below one hundred thousand dollars contributes nothing."
    PRD 3.7: "if that total is strictly greater than the program's `ssi_resource_limit_cents`
    (two thousand dollars), the account's `ssi_posture` is `SSI_SUSPENDED`, and otherwise it
    is `SSI_OK`."

    Design: Corner/endpoints/get_means_test_computed_read_ssi_ok
    """
    _, _, beneficiary, account = setup_open_account(
        beneficiary_overrides={"other_countable_resources_cents": 0}
    )
    post_contribution(account["id"], 50_000, account["version"])
    resp = api.means_test(account["id"], "SSI", make_beneficiary_headers(beneficiary["id"]))
    data = validate_success(resp)
    assert data["total_countable_cents"] == 0
    assert data["ssi_posture"] == "SSI_OK"
    assert data["affects_benefit"] is False


def test_revoke_representative_action_endpoint(api):
    """PRD 3.5: "A representative may be revoked by a `ProgramAdministrator` or the owning
    `Beneficiary`; an `ACTIVE` representative moves to `REVOKED` and can no longer act on the
    account."

    Design: Corner/endpoints/revoke_representative_action_endpoint
    """
    _, _, beneficiary, account = setup_open_account()
    rep = add_representative(account["id"], beneficiary["id"], relationship="PARENT")
    resp = api.revoke_representative(rep["id"], make_beneficiary_headers(beneficiary["id"]))
    data = validate_success(resp)
    assert data["status"] == "REVOKED"


def test_fk_reverse_list_certifications_by_beneficiary(api):
    """PRD 3.2: "Certifications are readable by any role and may be listed and optionally
    filtered by `beneficiary_id`."

    Design: Corner/endpoints/fk_reverse_list_certifications_by_beneficiary
    """
    program, _ = setup_program_and_option()
    beneficiary = create_beneficiary(program["id"])
    cert = create_pending_certification(beneficiary["id"])
    resp = api.list_certifications(ADMIN, params={"beneficiary_id": beneficiary["id"]})
    data, _ = validate_paginated(resp)
    assert len(data) == 1, f"expected one certification, got {len(data)}"
    assert data[0]["id"] == cert["id"]


# ---------------------------------------------------------------------------
# Section: errors
# ---------------------------------------------------------------------------
def test_error_unauthenticated_missing_role_header(api):
    """PRD 2.1: "A request that omits `X-User-Role`, or whose value is not one of these four,
    is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/error_unauthenticated_missing_role_header
    """
    program = create_program()
    resp = api.get_program(program["id"], make_invalid_role_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_error_forbidden_medicaid_agency_cannot_open_account(api):
    """PRD 2.1: "A syntactically valid role that is not permitted to perform the requested
    operation (per the role authorizations in Section 4) is rejected with `ERR_FORBIDDEN`."

    Design: Corner/errors/error_forbidden_medicaid_agency_cannot_open_account
    """
    _, option, beneficiary = setup_certified_beneficiary()
    resp = api.create_account(
        {"beneficiary_id": beneficiary["id"], "investment_option_id": option["id"]},
        make_medicaid_agency_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)


def test_error_not_account_owner_other_beneficiary(api):
    """PRD 2.1: "In both cases, an account-scoped write by a principal who is neither the
    owning beneficiary nor an active representative of that account is rejected with
    `ERR_NOT_ACCOUNT_OWNER`."

    Design: Corner/errors/error_not_account_owner_other_beneficiary
    """
    program, _, beneficiary_a, account_a = setup_open_account()
    beneficiary_b = create_beneficiary(program["id"], full_name="Other B")
    resp = api.create_contribution(
        account_a["id"],
        create_contribution_payload(100_000, account_a["version"]),
        make_beneficiary_headers(beneficiary_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_ACCOUNT_OWNER.value, 403)


def test_error_invalid_request_nonpositive_amount(api):
    """PRD 2.5: "required fields present, correctly typed, enum members valid, and any
    `amount_cents` strictly greater than zero (`ERR_INVALID_REQUEST`)"

    Design: Corner/errors/error_invalid_request_nonpositive_amount
    """
    _, _, _, account = setup_open_account()
    resp = api.create_contribution(
        account["id"], create_contribution_payload(0, account["version"]), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


# ---------------------------------------------------------------------------
# Section: rbac
# ---------------------------------------------------------------------------
def test_beneficiary_cannot_reverse_contribution_forbidden(api):
    """PRD 3.6: "A posted contribution may be reversed by a `ProgramAdministrator` as a
    compensating action"
    PRD 2.1: "A syntactically valid role that is not permitted to perform the requested
    operation (per the role authorizations in Section 4) is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/beneficiary_cannot_reverse_contribution_forbidden
    """
    _, _, beneficiary, account = setup_open_account()
    ben_headers = make_beneficiary_headers(beneficiary["id"])
    contrib = post_contribution(account["id"], 100_000, account["version"], headers=ben_headers)
    resp = api.reverse_contribution(contrib["id"], ben_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)
    after = validate_success(api.get_contribution(contrib["id"], ADMIN))
    assert after["status"] == "POSTED", "a forbidden reversal must not change the contribution"


def test_medicaid_agency_cannot_be_used_for_contribution(api):
    """PRD 2.1: "A syntactically valid role that is not permitted to perform the requested
    operation (per the role authorizations in Section 4) is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/medicaid_agency_cannot_be_used_for_contribution
    """
    _, _, _, account = setup_open_account()
    resp = api.create_contribution(
        account["id"], create_contribution_payload(100_000, account["version"]),
        make_medicaid_agency_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)


# ---------------------------------------------------------------------------
# Section: consistency_model
# ---------------------------------------------------------------------------
def test_immediate_visibility_balance_after_contribution(api):
    """PRD 3.6: "Posting raises the account's `basis_cents` and `balance_cents` by
    `amount_cents`"
    PRD 2.4: "When the server derives a computed field on an entity (for example, refreshing
    an `Account`'s balance or an `Account`'s `ssi_posture`), that derivation is a mutation:
    it advances `updated_at` and increments `version`."

    Design: Corner/consistency_model/immediate_visibility_balance_after_contribution
    """
    _, _, _, account = setup_open_account()
    post_contribution(account["id"], 250_000, account["version"])
    data = validate_success(api.get_account(account["id"], ADMIN))
    assert data["balance_cents"] == 250_000, "GET right after the contribution shows the new balance"
