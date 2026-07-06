"""Entity creation/computed fields, listings, RBAC, contract lifecycle, fees.

Covers the queue B entities / state_machines (contract) / calculations
(early termination) / rbac corner instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    build_user_headers,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    make_client_headers,
    factories,
    fixtures,
)

ADMIN = TEST_USERS["agency_admin_headers"]
AM = TEST_USERS["account_manager_headers"]


# ---------------------------------------------------------------------------
# entities
# ---------------------------------------------------------------------------
def test_create_client_returns_defaults(api):
    """PRD §3.1: "Every client begins life in `PROSPECT` `status` with a
    `health_score` of 100 and an `open_dispute_count` of 0."
    PRD §2.4: "an integer `version` that begins at its creation value and increments
    by one on every mutation".

    POST /clients -> status PROSPECT, health_score 100, open_dispute_count 0, version 1.

    Design: Corner/entities/create_client_returns_defaults
    """
    client = validate_success(
        api.create_client(
            factories.create_client_payload(
                company_name="New Co", primary_domain="new.example"
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    assert client["status"] == "PROSPECT"
    assert client["health_score"] == 100
    assert client["open_dispute_count"] == 0
    assert client["version"] == 1


def test_create_keyword_target_missing_required_field_rejected(api):
    """PRD §3.2: "Keyword strategy is captured as `KeywordTarget` records, each
    created against a client by supplying the `client_id`, the target `phrase`, an
    estimated monthly `search_volume` (zero or greater), and a keyword `difficulty`
    from 0 to 100."
    PRD §2.7: "(5) request-body well-formedness — required fields present, enum values
    legal, numbers within their declared ranges — failing with `ERR_INVALID_REQUEST`".

    Omitting the required search_volume -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_keyword_target_required_field_missing
    """
    client = fixtures.create_prospect_client(
        company_name="KW Co", primary_domain="kw.example"
    )
    resp = api.create_keyword_target(
        {"client_id": client["id"], "phrase": "seo", "difficulty": 30}, AM
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_retainer_invalid_tier_rejected(api):
    """PRD §3.4: "a `tier` of `STARTER`, `GROWTH`, or `DOMINATE`".
    PRD §2.7: "(5) request-body well-formedness — required fields present, enum values
    legal, numbers within their declared ranges — failing with `ERR_INVALID_REQUEST`".

    tier PLATINUM is not a legal enum value -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_retainer_invalid_enum_tier
    """
    client = fixtures.create_audited_client(
        company_name="Enum Co", primary_domain="enum.example"
    )
    resp = api.create_retainer(
        factories.create_retainer_payload(
            client_id=client["id"], tier="PLATINUM", monthly_credits=10,
            wholesale_price_cents=100000,
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_client_not_found(api):
    """PRD §2.6: "The platform validates path identifiers strictly left to right and
    rejects the request with `ERR_NOT_FOUND` at the first identifier that does not
    resolve to an existing resource".

    Design: Corner/entities/get_client_not_found
    """
    resp = api.get_client(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_keyword_priority_score_computed(api):
    """PRD §3.2: "The `priority_score` is the opportunity score `search_volume`
    multiplied by the quantity one minus `difficulty` divided by one hundred, rounded
    half up to two decimal places".

    1000 * (1 - 40/100) = 1000 * 0.6 = 600.0.

    Design: Corner/entities/keyword_priority_score_computed
    """
    client = fixtures.create_prospect_client(
        company_name="Prio Co", primary_domain="prio.example"
    )
    kw = validate_success(
        api.create_keyword_target(
            factories.create_keyword_target_payload(
                client_id=client["id"], phrase="best agency",
                search_volume=1000, difficulty=40,
            ),
            AM,
        ),
        expected_status=201,
    )
    assert kw["priority_score"] == 600.0, (
        f"priority_score should be 600.0, got {kw['priority_score']}"
    )


def test_audit_composite_score_computed(api):
    """PRD §3.1: "The `composite_score` is a weighted blend: weight the
    `technical_score` at four-tenths, the `content_score` at thirty-five hundredths,
    and the `backlink_score` at twenty-five hundredths, sum the three weighted parts,
    and round that sum half up to the nearest whole integer between 0 and 100."

    round_half_up(80*0.4 + 90*0.35 + 70*0.25) = round_half_up(81.0) = 81.

    Design: Corner/entities/audit_composite_score_computed
    """
    client = fixtures.create_prospect_client(
        company_name="Aud Co", primary_domain="aud.example"
    )
    audit = validate_success(
        api.create_audit(
            client["id"],
            {"technical_score": 80, "content_score": 90, "backlink_score": 70},
            ADMIN,
        ),
        expected_status=201,
    )
    assert audit["composite_score"] == 81, (
        f"composite_score should be 81, got {audit['composite_score']}"
    )


def test_site_audit_has_no_version_field(api):
    """PRD §2.4: "Three entities are append-only readings or immutable records and
    therefore carry only `id` and `created_at`; for these, both `updated_at` and
    `version` are absent. These are the `SiteAudit` (a recorded crawl result), the
    `RankSnapshot` (a single SERP reading), and the `Report` (a generated
    point-in-time summary)."

    A retrieved SiteAudit carries no version field.

    Design: Corner/entities/immutable_siteaudit_no_version_field
    """
    client = fixtures.create_prospect_client(
        company_name="Imm Co", primary_domain="imm.example"
    )
    created = validate_success(
        api.create_audit(
            client["id"],
            {"technical_score": 70, "content_score": 70, "backlink_score": 70},
            ADMIN,
        ),
        expected_status=201,
    )
    fetched = validate_success(api.get_audit(created["id"], ADMIN))
    assert fetched["client_id"] == client["id"]
    assert "version" not in fetched, "SiteAudit must not carry a version field"
    assert "updated_at" not in fetched, "SiteAudit must not carry an updated_at field"


def test_list_clients_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when
    omitted it defaults to 10, may be no smaller than 1, and may be no larger than
    100."
    PRD §2.3: "Every list response surfaces `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Two clients exist; GET /clients?limit=1 returns one item with total_count 2 and
    has_more true.

    Design: Corner/entities/list_clients_pagination_envelope
    """
    fixtures.create_prospect_client(company_name="L1", primary_domain="l1.example")
    fixtures.create_prospect_client(company_name="L2", primary_domain="l2.example")
    data, meta = validate_paginated(
        api.list_clients(ADMIN, params={"limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 2, f"total_count should be 2, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert len(data) == 1, f"data length should be 1, got {len(data)}"


# ---------------------------------------------------------------------------
# state_machines (keyword terminal, contract renewal loop)
# ---------------------------------------------------------------------------
def test_dropped_keyword_cannot_drop_again(api):
    """PRD §3.2: "A target may be dropped to the terminal `DROPPED` from either
    `PLANNED` or `TRACKING`, also incrementing its `version`."
    PRD §2.7: "(6) that the target resource is in a state that permits the requested
    transition, failing with `ERR_INVALID_STATE`".

    A DROPPED (terminal) keyword rejects a second drop with ERR_INVALID_STATE.

    Design: Corner/state_machines/terminal_dropped_keyword_cannot_drop_again
    """
    client = fixtures.create_prospect_client(
        company_name="Term Co", primary_domain="term.example"
    )
    kw = get_success_data(
        api.create_keyword_target(
            factories.create_keyword_target_payload(
                client_id=client["id"], phrase="drop me",
                search_volume=100, difficulty=50,
            ),
            AM,
        )
    )
    validate_success(api.drop_keyword_target(kw["id"], AM))
    resp = api.drop_keyword_target(kw["id"], AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_keyword_target(kw["id"], AM))
    assert after["status"] == "DROPPED"


def test_contract_renewal_loop_active_renewed_active(api):
    """PRD §3.5: "If `auto_renew` is true, the contract follows the renewal branch
    from `ACTIVE` to `RENEWED`: `cycles_elapsed` is reset to 0, `early_termination_fee_cents`
    is recomputed, and the contract's `version` increments. Renewal may also be
    triggered manually by an account manager on an `ACTIVE` contract with the same
    effects."
    PRD §3.5: "A contract may also be activated from `RENEWED` back to `ACTIVE` to
    begin the new term, incrementing its `version`."

    Manual renew ACTIVE -> RENEWED (cycles_elapsed 0); activate RENEWED -> ACTIVE.

    Design: Corner/state_machines/contract_renewal_loop_active_to_renewed_to_active
    """
    client, retainer = fixtures.create_active_client_with_active_retainer(
        retainer_overrides={"monthly_credits": 20},
    )
    contract = fixtures.create_active_contract(
        client["id"], retainer["id"], term_cycles=6, auto_renew=True
    )
    renewed = validate_success(api.renew_contract(contract["id"], AM))
    assert renewed["status"] == "RENEWED"
    assert renewed["cycles_elapsed"] == 0, (
        f"renew should reset cycles_elapsed to 0, got {renewed['cycles_elapsed']}"
    )
    reactivated = validate_success(api.activate_contract(contract["id"], AM))
    assert reactivated["status"] == "ACTIVE", (
        f"activate from RENEWED should return to ACTIVE, got {reactivated['status']}"
    )


# ---------------------------------------------------------------------------
# calculations (early termination fee)
# ---------------------------------------------------------------------------
def test_early_termination_fee_floor_and_clamp(api):
    """PRD §3.5: "Otherwise compute a raw fee as the retainer's `billing_price_cents`
    multiplied by the remaining cycles multiplied by one-half, floored to whole cents,
    and then take the larger of that raw fee and a single cycle's `billing_price_cents`
    — so once any cycles remain, the fee is never less than one cycle's billing price."

    Reseller markup 0.30 over wholesale 200000c -> billing 260000c; term 3, elapsed 0,
    remaining 3 -> raw floor(260000*3*0.5)=390000; max(390000, 260000)=390000.

    Design: Corner/calculations/early_termination_fee_floor_clamp
    """
    reseller = fixtures.create_reseller(brand_name="ETF Reseller", markup_pct=0.30)
    client, retainer = fixtures.create_active_client_with_active_retainer(
        client_overrides={
            "company_name": "Etf Co", "primary_domain": "etf.example",
            "reseller_id": reseller["id"],
        },
        retainer_overrides={"wholesale_price_cents": 200000},
    )
    assert retainer["billing_price_cents"] == 260000
    contract = fixtures.create_active_contract(
        client["id"], retainer["id"], term_cycles=3, auto_renew=False
    )
    terminated = validate_success(api.terminate_contract(contract["id"], AM))
    assert terminated["status"] == "TERMINATED"
    assert terminated["early_termination_fee_cents"] == 390000, (
        f"early termination fee should be 390000, "
        f"got {terminated['early_termination_fee_cents']}"
    )


# ---------------------------------------------------------------------------
# rbac
# ---------------------------------------------------------------------------
def test_account_manager_cannot_create_reseller(api):
    """PRD §4: "POST | `/resellers` | Create a white-label reseller | AgencyAdmin".
    PRD §2.1: "A request whose role is syntactically valid but not permitted to
    perform the targeted operation is rejected with `ERR_FORBIDDEN_ROLE`."

    POST /resellers is AgencyAdmin-exclusive; an AccountManager attempt ->
    ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/account_manager_cannot_create_reseller
    """
    resp = api.create_reseller(
        {"brand_name": "Nope", "markup_pct": 0.2},
        build_user_headers("op-1", "AccountManager"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_client_cannot_assign_deliverable(api):
    """PRD §4: "POST | `/deliverables/{id}/assign` | Assign a deliverable (reserves
    credits) | AgencyAdmin, AccountManager".
    PRD §2.1: "A request whose role is syntactically valid but not permitted to
    perform the targeted operation is rejected with `ERR_FORBIDDEN_ROLE`."

    A Client actor attempting deliverable assign -> ERR_FORBIDDEN_ROLE; deliverable
    stays DRAFT.

    Design: Corner/rbac/client_cannot_assign_deliverable
    """
    client, retainer, sprint = fixtures.setup_client_retainer_active_sprint(
        retainer_overrides={"monthly_credits": 20},
    )
    deliverable = fixtures.create_draft_deliverable(
        client["id"], retainer["id"], sprint["id"],
        kind="CONTENT", complexity="STANDARD",
    )
    fresh = validate_success(api.get_retainer(retainer["id"], ADMIN))
    resp = api.assign_deliverable(
        deliverable["id"],
        {"expected_retainer_version": fresh["version"]},
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    after = validate_success(api.get_deliverable(deliverable["id"], ADMIN))
    assert after["status"] == "DRAFT", f"deliverable must stay DRAFT, got {after['status']}"


def test_missing_x_user_id_on_client_role_returns_missing_auth(api):
    """PRD §2.1: "A request that omits either header, or carries a malformed value, is
    rejected with `ERR_MISSING_AUTH`."
    PRD §2.7: "(1) presence and well-formedness of the auth headers, failing with
    `ERR_MISSING_AUTH`, with `X-User-ID` being mandatory for the entity-backed roles".

    A contract sign sent as Client WITHOUT X-User-ID -> ERR_MISSING_AUTH (401),
    checked before any state logic; contract stays PENDING.

    Design: Corner/rbac/missing_x_user_id_on_entity_backed_role_returns_missing_auth
    """
    client = fixtures.create_audited_client(
        company_name="Auth Co", primary_domain="auth.example"
    )
    retainer = get_success_data(
        api.create_retainer(
            factories.create_retainer_payload(
                client_id=client["id"], monthly_credits=20,
                wholesale_price_cents=200000,
            ),
            ADMIN,
        )
    )
    contract = get_success_data(
        api.create_contract(
            factories.create_contract_payload(
                client_id=client["id"], retainer_id=retainer["id"], term_cycles=6
            ),
            AM,
        )
    )
    # Client role with NO X-User-ID header.
    headers = {"X-User-Role": "Client"}
    resp = api.sign_contract(contract["id"], headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)

    after = validate_success(api.get_contract(contract["id"], ADMIN))
    assert after["status"] == "PENDING", f"contract must stay PENDING, got {after['status']}"
