"""Entity creation/retrieval/validation, computed fields, filtered listings,
immutable ledger lines, and RBAC scoping.

Covers the corner entities, endpoints, and rbac sections.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    fixtures,
    factories,
    assert_author,
    assert_contract,
    TEST_USERS,
    ApiErrorId,
    make_agent_headers,
    make_stranger_headers,
    NON_EXISTENT_UUID,
)

PUB = TEST_USERS["publisher_headers"]


# ==========================================================================
# Queue B — entities
# ==========================================================================
def test_create_author_returns_201_with_defaults(api):
    """PRD §2.4: "an integer `version` that begins at 1 and increments by one each
    time the resource is mutated."

    PRD §3.1: "the withholding fraction defaults to 0 when omitted"

    Design: Corner/entities/create_author_returns_201_with_all_fields
    """
    author = validate_success(
        api.create_author({"full_name": "Jane Doe", "email": factories._unique_email("jane")}, PUB), 201
    )
    assert author["version"] == 1
    assert author["tax_withholding_pct"] == 0
    assert_author(author)


def test_get_contract_returns_stored_balances(api):
    """PRD §3.1: "Its `unrecouped_advance_cents` and `lifetime_net_units` are
    computed, house-managed balances: at creation `unrecouped_advance_cents`
    mirrors the supplied `advance_cents` and `lifetime_net_units` is 0."

    PRD §3.1: "A contract is born in `DRAFT` status."

    Design: Corner/entities/get_contract_returns_stored_entity
    """
    author = fixtures.create_author()
    contract = fixtures.create_contract(
        author["id"], advance_cents=500000, reserve_pct=0.25, reserve_hold_periods=2
    )
    reread = validate_success(api.get_contract(contract["id"], PUB))
    assert reread["unrecouped_advance_cents"] == 500000
    assert reread["lifetime_net_units"] == 0
    assert reread["status"] == "DRAFT"
    assert_contract(reread)


def test_list_contracts_paginated_envelope(api):
    """PRD §2.3: "Each list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the envelope's `meta` object, where `total_count` reports
    the size of the full unpaginated set and `has_more` indicates whether further
    pages remain."

    Design: Corner/entities/list_contracts_paginated_envelope
    """
    author = fixtures.create_author()
    fixtures.create_contract(author["id"], advance_cents=100)
    fixtures.create_contract(author["id"], advance_cents=200)

    resp = api.list_contracts(PUB, params={"author_id": author["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_get_contract_not_found(api):
    """PRD §2.6: "the first one that does not resolve to an existing resource fails
    the request with `ERR_NOT_FOUND` (HTTP 404)"

    Design: Corner/entities/get_contract_not_found
    """
    resp = api.get_contract(NON_EXISTENT_UUID, PUB)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_contract_missing_author_id_rejected(api):
    """PRD §2.10: "Request well-formedness comes after that: a missing or malformed
    body, an absent required field, a wrong type, or an enum value outside its
    allowed set yields `ERR_INVALID_REQUEST` (HTTP 422)"

    PRD §3.1: "The create payload names the authoring party through `author_id`"

    Design: Corner/entities/create_contract_missing_required_author_id
    """
    resp = api.create_contract({"advance_cents": 1000}, PUB)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_contract_reserve_defaults_applied(api):
    """PRD §3.1: "`reserve_pct` (the fraction of each period's gross royalty
    withheld against returns, defaulting to 0.25), and `reserve_hold_periods`
    (how many finalized periods a reserve sits before it may be liquidated,
    defaulting to 2)."

    Design: Corner/entities/contract_reserve_pct_default_applied
    """
    author = fixtures.create_author()
    contract = validate_success(
        api.create_contract({"author_id": author["id"], "advance_cents": 0}, PUB), 201
    )
    assert contract["reserve_pct"] == 0.25
    assert contract["reserve_hold_periods"] == 2


def test_subsidiary_author_income_is_computed(api):
    """PRD §3.4: "At registration the system computes the author's credit,
    `author_income_cents`, as the gross `proceeds_cents` multiplied by
    `author_share_pct`, rounded half up to whole cents."

    proceeds 1000000 * share 0.75 = 750000.

    Design: Corner/entities/subsidiary_author_income_computed_input_ignored
    """
    author = fixtures.create_author()
    contract = fixtures.create_contract(author["id"], advance_cents=0)
    right = validate_success(
        api.create_subsidiary_right(
            contract["id"], {"right_type": "FILM", "proceeds_cents": 1000000, "author_share_pct": 0.75}, PUB
        ),
        201,
    )
    assert right["author_income_cents"] == 750000


def test_author_system_fields_generated(api):
    """PRD §2.4: "a system-managed `id` formatted as a UUID with no type prefix, a
    `created_at` timestamp (ISO 8601 UTC with three fractional digits) fixed at
    creation ... and an integer `version` that begins at 1"

    Design: Corner/entities/author_system_fields_generated
    """
    author = validate_success(
        api.create_author({"full_name": "Sys Gen", "email": factories._unique_email("sysgen")}, PUB), 201
    )
    assert is_valid_uuid(author["id"])
    assert is_iso8601_timestamp(author["created_at"])
    assert author["version"] == 1


def test_subsidiary_right_invalid_enum_rejected(api):
    """PRD §2.10: "an enum value outside its allowed set yields
    `ERR_INVALID_REQUEST` (HTTP 422)"

    PRD §3.4: "a `right_type` of `FOREIGN`, `AUDIO`, or `FILM`"

    Design: Corner/entities/subsidiary_right_invalid_enum_type
    """
    author = fixtures.create_author()
    contract = fixtures.create_contract(author["id"], advance_cents=0)
    resp = api.create_subsidiary_right(
        contract["id"], {"right_type": "TELEVISION", "proceeds_cents": 100, "author_share_pct": 0.5}, PUB
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_format_list_price_must_be_positive(api):
    """PRD §2.8: "A format's `list_price_cents` must be strictly greater than 0."

    PRD §2.8: "Inputs that carry a declared range are validated on write, and a
    value outside its range is rejected with `ERR_VALIDATION_RANGE` (HTTP 422)."

    Design: Corner/entities/list_price_must_be_positive
    """
    author = fixtures.create_author()
    contract = fixtures.create_contract(author["id"], advance_cents=0)
    title = fixtures.add_title(contract["id"], name="Bad Price")
    resp = api.create_format(title["id"], {"format_type": "EBOOK", "list_price_cents": 0}, PUB)
    validate_error(resp, ApiErrorId.ERR_VALIDATION_RANGE.value)


def test_statement_line_is_immutable_ledger_artifact(api):
    """PRD §2.4: "A `RoyaltyTier` and a `StatementLine` are immutable once
    created: each carries only an `id` and a `created_at`, and neither bears an
    `updated_at` nor a `version`."

    PRD §3.6: "The `line_type` is one of `ROYALTY` ... the first six categories
    are emitted at finalize for every non-zero component"

    Net 100 at 0.10*3000 yields a ROYALTY line of 30000 with no version field.

    Design: Corner/entities/statementline_is_immutable_no_version
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]
    period = fixtures.run_period_to_closed(cid, fid, "P1", 1, 100, 0)
    s1 = get_success_data(api.generate_statement(period["id"], PUB))
    fixtures.finalize_statement(s1["id"], cid)

    lines = validate_success(api.list_statement_lines(s1["id"], PUB, params={"line_type": "ROYALTY"}))
    royalty = [ln for ln in lines if ln["line_type"] == "ROYALTY"]
    assert royalty, "a ROYALTY line must be emitted at finalize"
    assert any(ln["amount_cents"] == 30000 for ln in royalty)
    for ln in royalty:
        assert "version" not in ln
        assert "updated_at" not in ln


def test_title_under_missing_contract_not_found(api):
    """PRD §2.6: "Many paths address a resource through one or more ancestor
    identifiers. The system validates every identifier in a path strictly left to
    right, and the first one that does not resolve to an existing resource fails
    the request with `ERR_NOT_FOUND` (HTTP 404) before any deeper check runs."

    Design: Corner/entities/title_requires_existing_parent_contract
    """
    resp = api.create_title(NON_EXISTENT_UUID, {"name": "Orphan"}, PUB)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ==========================================================================
# Queue B — endpoints (filtered reads)
# ==========================================================================
def test_list_subsidiary_rights_filtered_by_status(api):
    """PRD §3.10: "Subsidiary-right and statement and reserve listings accept an
    optional `status` filter"

    Design: Corner/endpoints/list_subsidiary_rights_filtered_by_status
    """
    author = fixtures.create_author()
    contract = fixtures.create_contract(author["id"], advance_cents=0)
    r_void = get_success_data(
        api.create_subsidiary_right(
            contract["id"], {"right_type": "FOREIGN", "proceeds_cents": 100, "author_share_pct": 0.5}, PUB
        )
    )
    get_success_data(
        api.create_subsidiary_right(
            contract["id"], {"right_type": "AUDIO", "proceeds_cents": 200, "author_share_pct": 0.5}, PUB
        )
    )
    get_success_data(api.void_subsidiary_right(r_void["id"], PUB))

    rights = validate_success(api.list_contract_subsidiary_rights(contract["id"], PUB, params={"status": "VOID"}))
    assert len(rights) == 1
    assert rights[0]["status"] == "VOID"
    assert rights[0]["id"] == r_void["id"]


def test_list_sales_records_filtered_by_format(api):
    """PRD §3.10: "Sales records can be listed within their period or fetched
    individually, and can also be filtered by `format_id` across the catalogue."

    Design: Corner/endpoints/list_sales_records_filtered_by_format
    """
    base = fixtures.setup_active_contract(
        tiers=fixtures.SINGLE_TIER, advance_cents=0, reserve_pct=0, reserve_hold_periods=1, publish=False
    )
    cid = base["contract"]["id"]
    fid = base["format"]["id"]
    period = fixtures.open_period(cid, "P1", 1)
    record = fixtures.post_sales(period["id"], fid, units_sold=7, units_returned=0)

    records = validate_success(api.list_sales_records(PUB, params={"format_id": fid}))
    assert len(records) == 1
    assert records[0]["id"] == record["id"]
    assert records[0]["units_sold"] == 7


# ==========================================================================
# Queue B — rbac
# ==========================================================================
def test_author_cannot_create_contract(api):
    """PRD §2.1: "Neither `Author` nor `Agent` may perform any posting, accounting,
    or lifecycle operation; such attempts are rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/author_cannot_create_contract
    """
    from test_helpers import make_author_headers

    author = fixtures.create_author()
    headers = make_author_headers(author["id"])
    resp = api.create_contract({"author_id": author["id"], "advance_cents": 0}, headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_agent_cannot_read_unrepresented_contract(api):
    """PRD §2.1: "an `Agent` may read a contract, its children, and the statements
    and lines thereon only when that contract's `agent_id` equals `X-User-ID`"

    PRD §2.1: "A request whose role is recognized but not permitted to perform the
    requested operation — or an entity-backed principal reaching for a resource it
    does not own — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/agent_cannot_read_unrepresented_contract
    """
    author = fixtures.create_author()
    g1 = fixtures.create_agent()
    g2 = fixtures.create_agent()
    contract = fixtures.create_contract(
        author["id"], advance_cents=0, agent_id=g1["id"], agent_commission_pct=0.10
    )

    resp = api.get_contract(contract["id"], make_agent_headers(g2["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_unknown_role_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or supplies an `X-User-Role`
    that is not one of these three, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_headers_unauthenticated
    """
    resp = api.list_contracts(make_stranger_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
