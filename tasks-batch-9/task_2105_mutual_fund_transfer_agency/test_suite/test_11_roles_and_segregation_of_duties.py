"""Authentication, role authorization, ownership, channel entitlement and duty splits."""

from test_helpers import (
    ApiErrorId,
    create_fund_payload,
    create_nav_record_payload,
    create_purchase_payload,
    create_share_class,
    create_shareholder_account_payload,
    make_account_holder_headers,
    make_accountant_headers,
    make_compliance_headers,
    make_headers,
    open_active_account,
    price,
    read_case,
    read_nav_record,
    read_trade,
    setup_material_case_awaiting_reprocess,
    setup_pending_as_of_order,
    setup_reference_data,
    setup_trading_desk,
    validate_error,
    validate_paginated,
    validate_success,
    MONDAY,
    SINGLE_TIER_BREAKPOINT_TIERS,
    TEST_USERS,
)

OPERATOR = TEST_USERS["operator_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]
DEALER = TEST_USERS["dealer_headers"]


class TestAuthentication:
    def test_a_role_outside_the_five_declared_desks_is_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
        acting user, and `X-User-Role`, declaring the desk that user is acting for. Five
        roles are recognized, and their spellings are exact: `TransferAgentOperator`,
        `FundAccountant`, `ComplianceOfficer`, `DealerOperations`, and `AccountHolder`. A
        request that omits either header, or that presents an `X-User-Role` value outside
        those five, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/unknown_role_header_returns_unauthenticated
        """
        response = api.create_fund(
            create_fund_payload(name="Meridian Growth Fund", fund_family_code="MER"),
            make_headers("PortfolioManager", "pm-1"),
        )
        assert response.status_code == 401
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)


class TestRoleAuthorization:
    def test_the_shareholder_services_desk_may_not_strike_a_nav(self, api):
        """PRD §2.1: "A request whose role is well-formed but is not listed for the
        endpoint being called is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §3.3: "A **NavRecord** is a `FundAccountant`'s statement of what one share class
        was worth on one business date."

        Design: Corner/rbac/transfer_agent_operator_cannot_strike_a_nav_record
        """
        base = setup_reference_data(
            clock=None, tiers=SINGLE_TIER_BREAKPOINT_TIERS, with_registration=False
        )
        response = api.create_nav_record(
            create_nav_record_payload(
                base["share_class"]["id"], valuation_date=MONDAY, total_net_assets=0.00
            ),
            OPERATOR,
        )
        assert response.status_code == 403
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

        _, meta = validate_paginated(
            api.list_share_class_nav_records(base["share_class"]["id"], ACCOUNTANT)
        )
        assert meta["total_count"] == 0


class TestOwnershipAndChannelEntitlement:
    def test_an_account_holder_may_capture_only_on_their_own_account(self, api):
        """PRD §2.1: "When `X-User-Role` is `AccountHolder`, by contrast, `X-User-ID` is the
        `id` of the acting `ShareholderAccount`; ownership checks on any resource that
        references a shareholder account compare the resource's account foreign key to
        `X-User-ID`, and a mismatch is rejected with `ERR_ACCOUNT_OWNERSHIP_REQUIRED`."
        PRD §3.4: "Capture stamps `received_at` from the current logical clock instant and
        `captured_by_user_id` from the caller's `X-User-ID`, and computes `trade_date`, the
        effective pricing date."

        Design: Corner/rbac/account_holder_cannot_capture_a_trade_on_another_account
        """
        desk = setup_trading_desk(
            tiers=SINGLE_TIER_BREAKPOINT_TIERS,
            account_overrides={"primary_owner_name": "Owner One"},
        )
        owner_one = desk["account"]
        owner_two = open_active_account(primary_owner_name="Owner Two")

        forbidden = api.create_trade(
            create_purchase_payload(
                owner_two["id"], desk["share_class"]["id"], 1000.00
            ),
            make_account_holder_headers(owner_one["id"]),
        )
        assert forbidden.status_code == 403
        validate_error(forbidden, ApiErrorId.ERR_ACCOUNT_OWNERSHIP_REQUIRED.value)

        allowed = api.create_trade(
            create_purchase_payload(
                owner_one["id"], desk["share_class"]["id"], 1000.00
            ),
            make_account_holder_headers(owner_one["id"]),
        )
        own_trade = validate_success(allowed, 201)
        assert own_trade["account_id"] == owner_one["id"]
        assert own_trade["captured_by_user_id"] == owner_one["id"]

        _, meta = validate_paginated(
            api.list_trades(OPERATOR, params={"account_id": owner_two["id"]})
        )
        assert meta["total_count"] == 0

    def test_dealer_operations_may_not_open_a_direct_channel_account(self, api):
        """PRD §2.10: "The second is channel entitlement. `DealerOperations` acts on behalf
        of a selling dealer and is therefore confined to the accounts a dealer services —
        those whose `account_channel` is `NETWORKED` or `OMNIBUS`. An attempt by
        `DealerOperations` to open an account, capture an order, or file a reconciliation
        against an account whose `account_channel` is `DIRECT` is rejected with
        `ERR_DEALER_CHANNEL_REQUIRED`."

        Design: Corner/rbac/dealer_operations_cannot_open_a_direct_channel_account
        """
        forbidden = api.create_shareholder_account(
            create_shareholder_account_payload(
                registration_type="INDIVIDUAL", account_channel="DIRECT",
                state_code="NY", primary_owner_name="Dealer Attempt",
            ),
            DEALER,
        )
        assert forbidden.status_code == 403
        validate_error(forbidden, ApiErrorId.ERR_DEALER_CHANNEL_REQUIRED.value)

        allowed = api.create_shareholder_account(
            create_shareholder_account_payload(
                registration_type="INDIVIDUAL", account_channel="NETWORKED",
                state_code="NY", primary_owner_name="Dealer Networked",
                dealer_firm_code="DLR200",
            ),
            DEALER,
        )
        networked = validate_success(allowed, 201)
        assert networked["account_channel"] == "NETWORKED"

        _, meta = validate_paginated(
            api.list_shareholder_accounts(OPERATOR, params={"account_channel": "DIRECT"})
        )
        assert meta["total_count"] == 0


class TestSegregationOfDuties:
    def test_the_capturing_officer_may_not_approve_their_own_as_of_order(self, api):
        """PRD §3.4: "A pending order is released by a `ComplianceOfficer`, moving it
        `PENDING_AS_OF_APPROVAL → RECEIVED`; the approval stamps `approved_by_user_id` from
        the approver's `X-User-ID` and increments the trade's `version`. The approver's
        identifier must differ from the order's `captured_by_user_id`, or the release is
        refused with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.10: "A backdated order is captured by one actor and approved by another: the
        approving compliance officer's `X-User-ID` must differ from the order's
        `captured_by_user_id`."

        Design: Corner/rbac/as_of_approval_by_the_capturing_officer_is_rejected_for_segregation_of_duties
        """
        setup = setup_pending_as_of_order()
        trade = setup["trade"]
        assert trade["trade_date"] == MONDAY
        assert trade["captured_by_user_id"] == "co-1"
        assert trade["execution_status"] == "PENDING_AS_OF_APPROVAL"

        refused = api.approve_as_of_trade(trade["id"], make_compliance_headers("co-1"))
        assert refused.status_code == 403
        validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
        assert read_trade(trade["id"])["execution_status"] == "PENDING_AS_OF_APPROVAL"

        approved = validate_success(
            api.approve_as_of_trade(trade["id"], make_compliance_headers("co-2")), 200
        )
        assert approved["execution_status"] == "RECEIVED"
        assert approved["approved_by_user_id"] == "co-2"

    def test_the_detecting_accountant_may_not_run_the_reprocessing_sweep(self, api):
        """PRD §3.9: "That step is the reprocessing sweep, run by a `FundAccountant` whose
        `X-User-ID` must differ from the case's `detected_by_user_id`, or the run is refused
        with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.10: "A material pricing correction is opened by one fund accountant and
        reprocessed by another: the sweeping accountant's `X-User-ID` must differ from the
        case's `detected_by_user_id`."

        Design: Corner/rbac/reprocess_by_the_detecting_accountant_is_rejected_for_segregation_of_duties
        """
        setup = setup_material_case_awaiting_reprocess()
        case = setup["case"]
        assert case["detected_by_user_id"] == "fa-1"
        assert case["approved_by_user_id"] == "co-1"
        assert case["status"] == "MATERIAL_APPROVED"

        response = api.reprocess_pricing_error_case(
            case["id"], make_accountant_headers("fa-1")
        )
        assert response.status_code == 403
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

        after = read_case(case["id"])
        assert after["status"] == "MATERIAL_APPROVED"
        assert after.get("reprocessed_by_user_id") is None

        record = read_nav_record(setup["nav"]["id"])
        assert record["status"] == "UNDER_ERROR_REVIEW"
        assert record["nav_per_share"] == price(11.0000)
