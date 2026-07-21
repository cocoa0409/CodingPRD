"""RBAC enforcement, optimistic concurrency on supplement create, and pagination."""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated, get_success_data,
    create_adjuster_payload, create_supplement_payload,
    make_client_headers, make_public_adjuster_headers,
)
from test_helpers.fixtures import (
    setup_active_contract, setup_settled_claim, setup_filed_claim,
    new_adjuster, new_client, new_contract, claim_version,
)

FIRM = TEST_USERS["firm_principal_headers"]
CARRIER = TEST_USERS["carrier_headers"]


# ------------------------------------------------------------------ RBAC (corner)
def test_create_adjuster_forbidden_for_carrier(api):
    """PRD §2.1: "When the headers are present and valid but the role is not permitted to
    perform the requested operation — or an ownership-scoped role acts on a resource it does
    not own — the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/create_adjuster_forbidden_for_carrier
    """
    resp = api.create_adjuster(create_adjuster_payload(), CARRIER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)


def test_sign_contract_by_wrong_client_forbidden(api):
    """PRD §2.1: "only the client named on a contract may sign it: a sign request whose
    `X-User-ID` differs from the contract's `client_id` is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/sign_contract_by_wrong_client_forbidden
    """
    adj = new_adjuster(api)
    cli_a = new_client(api, full_name="Cy Client", email="cy@x.com")
    cli_b = new_client(api, full_name="Bea Other", email="bea@x.com")
    con = new_contract(api, cli_a, adj)
    resp = api.sign_contract(con, make_client_headers(cli_b))  # B signs A's contract
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_unauthenticated_missing_headers_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a value the server cannot
    validate, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unauthenticated_missing_headers_rejected
    """
    adj = new_adjuster(api)
    resp = api.get_adjuster(adj, {})  # no X-User-ID / X-User-Role headers
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


# ------------------------------------------------- OCC on supplement create (corner)
def test_occ_stale_claim_version_on_supplement_create_rejected(api):
    """PRD §2.8: "If that value does not equal the claim's current `version` — meaning
    another writer has advanced the claim since the client last read it — the create is
    rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412), preventing the writer from stacking a
    supplement on an outdated view of the available headroom."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_claim_version_on_supplement_create_rejected
    """
    ctx = setup_settled_claim(api, offer_cents=8_000_000)
    pa = make_public_adjuster_headers(ctx["adj"])
    ver = claim_version(api, ctx["clm"])
    # First create succeeds and bumps Claim.version.
    validate_success(api.create_supplement(
        create_supplement_payload(ctx["clm"], ver, amount_cents=1_000_000, reason="FIRST"), pa),
        expected_status=201)
    # Second create reuses the now-stale version.
    resp = api.create_supplement(
        create_supplement_payload(ctx["clm"], ver, amount_cents=500_000, reason="SECOND_STALE"), pa)
    validate_error(resp, ApiErrorId.ERR_STALE_CLAIM_VERSION.value, expected_status=412)


def test_occ_correct_claim_version_on_supplement_create_succeeds(api):
    """PRD §2.8: "When the versions match, the supplement is created and the claim's
    `version` is incremented by one as part of the write."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_claim_version_on_supplement_create_succeeds
    """
    ctx = setup_settled_claim(api, offer_cents=8_000_000)
    pa = make_public_adjuster_headers(ctx["adj"])
    ver = claim_version(api, ctx["clm"])
    data = validate_success(api.create_supplement(
        create_supplement_payload(ctx["clm"], ver, amount_cents=1_000_000), pa),
        expected_status=201)
    assert data["status"] == "DRAFT"


# ------------------------------------------------------- pagination (corner)
def test_list_claims_by_policy_returns_paginated_array(api):
    """PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_claims_by_policy_returns_paginated_array
    """
    ctx = setup_filed_claim(api)
    resp = api.list_claims(FIRM, params={"policy_id": ctx["pol"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert isinstance(data, list) and len(data) == 1
