"""
Authorization: role exclusivity on two writes, peer isolation between two
wholesalers holding the same role, and the read that escrow staff legitimately
share.
"""

from test_helpers import (
    ApiErrorId,
    acknowledge_disclosures,
    add_buyer,
    assert_pagination_meta,
    assert_purchase_contract,
    assert_seller_lead,
    assert_nulls,
    build_draft_contract,
    build_underwritten_lead,
    factories,
    make_cash_buyer_headers,
    make_seller_headers,
    make_title_agent_headers,
    make_wholesaler_headers,
    read_contract,
    read_lead,
    record_lead,
    register_wholesaler,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    TITLE_AGENT_1,
)


class TestRoleExclusiveWrites:
    """Two writes each belong to exactly one role."""

    def test_cash_buyer_cannot_put_a_lead_under_contract(self, api):
        """
        "When the headers are well formed but the named role is not permitted to
        invoke the endpoint, the request fails with `ERR_FORBIDDEN_ROLE` (HTTP
        403)."

        "A wholesaler puts a screened lead under contract by naming the
        `seller_lead_id` and the `deal_analysis_id` that justifies the price,
        then the commercial terms: `purchase_price_cents` payable to the seller
        (strictly positive), `earnest_money_cents` the wholesaler will place
        into escrow (strictly positive), `inspection_period_days` as a whole
        number of days between 1 and 30 inclusive, and the three instants that
        bound the deal."

        Design: Corner/rbac/cash_buyer_cannot_create_purchase_contract_forbidden_role
        """
        scenario = build_underwritten_lead(api, clock="2026-08-06T00:00:00Z")
        buyer = add_buyer(api, scenario.w_id)
        body = factories.purchase_contract_payload(
            scenario.lead_id,
            scenario.analysis_id,
            purchase_price_cents=18000000,
            earnest_money_cents=500000,
            option_start_at="2026-08-06T00:00:00Z",
        )

        response = api.create_purchase_contract(
            body, make_cash_buyer_headers(buyer["id"])
        )
        validate_error(response, ApiErrorId.FORBIDDEN_ROLE, 403)

        _, meta = validate_paginated(
            api.list_purchase_contracts(
                make_wholesaler_headers(scenario.w_id),
                {"seller_lead_id": scenario.lead_id},
            )
        )
        assert_pagination_meta(meta, total_count=0)
        assert_seller_lead(
            read_lead(api, scenario.lead_id, scenario.w_id), status="SCREENED"
        )

        # The very same body from the owning wholesaler is accepted, so the
        # denial turned on the role alone.
        validate_success(
            api.create_purchase_contract(
                body, make_wholesaler_headers(scenario.w_id)
            ),
            201,
        )

    def test_wholesaler_cannot_sign_the_contract_it_authored(self, api):
        """
        "**Signing.** The seller drives `contract_status` from `DRAFT` to
        `SIGNED`, and it is the seller alone who may do so."

        "**`ERR_FORBIDDEN_ROLE`** (403) — the caller's role is not among those
        the endpoint permits. Applies to every endpoint."

        Design: Corner/rbac/wholesaler_cannot_sign_its_own_contract_forbidden_role
        """
        scenario = build_draft_contract(
            api,
            clock="2026-08-06T00:00:00Z",
            contract_kwargs={
                "purchase_price_cents": 18000000,
                "earnest_money_cents": 500000,
            },
        )
        acknowledge_disclosures(api, scenario.pc_id, scenario.lead_id)

        response = api.sign_purchase_contract(
            scenario.pc_id, make_wholesaler_headers(scenario.w_id)
        )
        validate_error(response, ApiErrorId.FORBIDDEN_ROLE, 403)

        unchanged = read_contract(api, scenario.pc_id, scenario.w_id)
        assert_purchase_contract(unchanged, contract_status="DRAFT")
        assert_nulls(
            unchanged,
            "signed_at",
            "inspection_deadline_at",
            label="purchase_contract",
        )

        _, meta = validate_paginated(
            api.list_earnest_money_deposits(
                TITLE_AGENT_1, {"purchase_contract_id": scenario.pc_id}
            )
        )
        assert_pagination_meta(meta, total_count=0)


class TestPeerIsolationBetweenWholesalers:
    """Holding the role is not holding the resource."""

    def test_rival_wholesaler_screening_another_desks_lead_is_not_the_owner(self, api):
        """
        "Any mismatch between the acting principal and the target aggregate is
        rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403), and because ownership
        is an authorization concern it outranks every state precondition — a
        wholesaler poking at a rival's cancelled contract gets 403, never 409."

        "**`ERR_NOT_RESOURCE_OWNER`** (403) — the acting principal does not own
        the target aggregate: a wholesaler acting on another wholesaler's lead,
        campaign, contract, buyer, offer, agreement or analysis".

        Design: Corner/rbac/wholesaler_cannot_screen_another_wholesalers_lead_returns_not_resource_owner
        """
        set_clock(api, "2026-08-04T00:00:00Z")
        owner = register_wholesaler(
            api, legal_name="Keystone Property Partners LLC", state_code="TX"
        )
        rival = register_wholesaler(
            api, legal_name="Cascade Doorstep Homes LLC", state_code="TX"
        )
        lead = record_lead(api, owner["id"])

        response = api.protection_screen(
            lead["id"],
            factories.protection_screen_payload("STATUTORY"),
            make_wholesaler_headers(rival["id"]),
        )
        validate_error(response, ApiErrorId.NOT_RESOURCE_OWNER, 403)

        untouched = read_lead(api, lead["id"], owner["id"])
        assert_seller_lead(untouched, status="PROSPECT", version=1)
        assert_nulls(
            untouched,
            "protection_tier",
            "net_equity_cents",
            "equity_pct",
            "screened_at",
            label="seller_lead",
        )

        # Identical call, owning desk: only ownership differed.
        screened = validate_success(
            api.protection_screen(
                lead["id"],
                factories.protection_screen_payload("STATUTORY"),
                make_wholesaler_headers(owner["id"]),
            ),
            200,
        )
        assert_seller_lead(screened, status="SCREENED", version=2)


class TestSharedReadForEscrowStaff:
    """A non-owning role that the read endpoint nevertheless permits."""

    def test_title_agent_reads_the_whole_contract_without_writing(self, api):
        """
        "| GET | `/purchase-contracts/{purchase_contract_id}` | Read one
        purchase contract with all three status dimensions and the double-close
        schedule. | Wholesaler, Seller, CashBuyer, TitleAgent,
        ComplianceOfficer, PlatformAdmin |"

        "When `X-User-Role` is `TitleAgent`, `X-User-ID` is an opaque operator
        identifier not tied to any persisted entity; the server records it — as
        `cleared_by_user_id` and `funded_by_user_id` on a `TitleOrder` — and
        compares those two recorded values against one another for dual
        control, but never compares either to an entity's `id`."

        Design: Corner/rbac/title_agent_shared_read_access_to_purchase_contract_is_permitted
        """
        scenario = build_draft_contract(
            api,
            clock="2026-08-06T00:00:00Z",
            contract_kwargs={
                "purchase_price_cents": 18000000,
                "earnest_money_cents": 500000,
            },
        )

        response = api.get_purchase_contract(
            scenario.pc_id, make_title_agent_headers("ta-alpha")
        )
        fetched = validate_success(response, 200)

        assert_purchase_contract(
            fetched,
            id=scenario.pc_id,
            seller_lead_id=scenario.lead_id,
            deal_analysis_id=scenario.analysis_id,
            purchase_price_cents=18000000,
            earnest_money_cents=500000,
            contract_status="DRAFT",
            assignment_status="NOT_MARKETED",
            structure_election="UNDECIDED",
            version=1,
        )
        assert fetched == scenario.contract, (
            "escrow staff read the full representation, not a redacted subset: "
            f"{scenario.contract} was returned as {fetched}"
        )
        seller_view = validate_success(
            api.get_purchase_contract(
                scenario.pc_id, make_seller_headers(scenario.lead_id)
            ),
            200,
        )
        assert seller_view == fetched, "the read is not role-dependent"
