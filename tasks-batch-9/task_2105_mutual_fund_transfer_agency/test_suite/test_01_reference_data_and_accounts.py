"""Fund and share-class registration, account opening, and account lifecycle reads."""

from test_helpers import (
    ApiErrorId,
    assert_fund,
    assert_share_class,
    assert_shareholder_account,
    create_fund_payload,
    create_share_class_payload,
    create_shareholder_account_payload,
    create_fund,
    money,
    open_account,
    open_active_account,
    price,
    read_account,
    setup_reference_data,
    setup_settled_purchase,
    shares,
    strike_nav,
    validate_error,
    validate_paginated,
    validate_success,
    MONDAY,
    TEST_USERS,
    NO_LOAD_BREAKPOINT_TIERS,
    SINGLE_TIER_BREAKPOINT_TIERS,
)

OPERATOR = TEST_USERS["operator_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_TRADE_ID = "00000000-0000-4000-8000-000000000001"


class TestReferenceDataDefaults:
    def test_fund_registration_applies_declared_defaults(self, api):
        """PRD §3.1: "`cutoff_time_utc` is the fund's daily forward-pricing cutoff
        expressed as a 24-hour `HH:MM:SS` time in UTC and defaults to `16:00:00`;
        orders received strictly before that time of day on a business day price at
        that day's NAV."
        PRD §3.1: "`status` is the fund's offering posture, either `ACTIVE` or
        `CLOSED_TO_NEW`, and defaults to `ACTIVE`."
        PRD §2.5: "Every resource in the system carries an `id`: a server-minted UUID,
        with no type prefix and no client-supplied component."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the
        request that starts with `req_`."

        Design: Corner/entities/fund_creation_applies_declared_defaults_and_system_fields
        """
        response = api.create_fund(
            create_fund_payload(name="Meridian Growth Fund", fund_family_code="MER"),
            ACCOUNTANT,
        )
        fund = validate_success(response, 201)
        assert_fund(fund)
        assert fund["cutoff_time_utc"] == "16:00:00"
        assert fund["status"] == "ACTIVE"
        assert fund["version"] == 1
        assert "_" not in fund["id"], "the id carries no type prefix"

        body = response.json()
        assert body["meta"]["api_request_id"].startswith("req_")

    def test_share_class_registration_starts_with_no_shares_outstanding(self, api):
        """PRD §3.1: "Finally, every class carries `total_shares_outstanding`, a
        computed three-decimal share balance that begins at `0.000`, never goes
        negative, and always equals the sum of `shares` across every position held in
        that class."
        PRD §3.1: "`cdsc_enabled` is a boolean defaulting to false; when it is true,
        redemptions out of the class may carry a contingent deferred sales charge under
        the aging rules in §3.5."
        PRD §3.1: "`twelve_b_one_fee_pct` is the annual 12b-1 distribution fee
        percentage, defaulting to `0.0025`; it is recorded for disclosure and is
        informational only — no calculation in this system consumes it."

        Design: Corner/entities/share_class_creation_initialises_total_shares_outstanding_to_zero
        """
        fund = create_fund()
        response = api.create_share_class(
            create_share_class_payload(
                fund["id"], class_code="A", seed_nav_per_share=10.0000,
                breakpoint_tiers=list(SINGLE_TIER_BREAKPOINT_TIERS),
            ),
            ACCOUNTANT,
        )
        share_class = validate_success(response, 201)
        assert_share_class(share_class)
        assert share_class["total_shares_outstanding"] == shares(0.000)
        assert share_class["cdsc_enabled"] is False
        assert share_class["twelve_b_one_fee_pct"] == price(0.0025)

    def test_account_opening_defaults_to_cash_dividends_in_pending_docs(self, api):
        """PRD §3.2: "A newly opened account is created in `PENDING_DOCS` with
        `tin_certified` false, `household_basis_amount` `0.00`, and `restriction_reason`
        and `closed_at` both null."
        PRD §3.2: "Three optional attributes may accompany them: `dividend_option`, the
        standing instruction for distributions, either `CASH` or `REINVEST` and
        defaulting to `CASH`; `linked_primary_account_id`, discussed below and defaulting
        to null; and `dealer_firm_code`, the selling dealer's firm code, which is required
        when `account_channel` is `NETWORKED` or `OMNIBUS` and must be omitted or null when
        it is `DIRECT`."
        PRD §3.2: "Its `household_basis_variant` is fixed from the channel at creation: an
        account whose `account_channel` is `DIRECT` or `NETWORKED` is a
        `MARKET_VALUE_BASIS` account, and an account whose `account_channel` is `OMNIBUS`
        is a `HISTORICAL_COST_BASIS` account."

        Design: Corner/entities/account_creation_defaults_to_cash_dividends_and_pending_docs
        """
        response = api.create_shareholder_account(
            create_shareholder_account_payload(
                registration_type="UGMA_UTMA", account_channel="DIRECT",
                state_code="CA", primary_owner_name="Minor Custodial",
            ),
            OPERATOR,
        )
        account = validate_success(response, 201)
        assert_shareholder_account(account)
        assert account["dividend_option"] == "CASH"
        assert account["status"] == "PENDING_DOCS"
        assert account["tin_certified"] is False
        assert account["household_basis_amount"] == money(0.00)
        assert account["household_basis_variant"] == "MARKET_VALUE_BASIS"
        assert account.get("linked_primary_account_id") is None
        assert account.get("restriction_reason") is None
        assert account.get("closed_at") is None

    def test_omnibus_channel_selects_the_historical_cost_basis_variant(self, api):
        """PRD §3.2: "Its `household_basis_variant` is fixed from the channel at
        creation: an account whose `account_channel` is `DIRECT` or `NETWORKED` is a
        `MARKET_VALUE_BASIS` account, and an account whose `account_channel` is `OMNIBUS`
        is a `HISTORICAL_COST_BASIS` account."

        Design: Corner/entities/omnibus_account_creation_sets_historical_cost_basis_variant
        """
        omnibus = validate_success(
            api.create_shareholder_account(
                create_shareholder_account_payload(
                    registration_type="CORPORATE", account_channel="OMNIBUS",
                    state_code="NY", primary_owner_name="Omni Street Name",
                    dealer_firm_code="DLR777",
                ),
                OPERATOR,
            ),
            201,
        )
        networked = validate_success(
            api.create_shareholder_account(
                create_shareholder_account_payload(
                    registration_type="CORPORATE", account_channel="NETWORKED",
                    state_code="NY", primary_owner_name="Net Street Name",
                    dealer_firm_code="DLR777",
                ),
                OPERATOR,
            ),
            201,
        )
        assert omnibus["household_basis_variant"] == "HISTORICAL_COST_BASIS"
        assert networked["household_basis_variant"] == "MARKET_VALUE_BASIS"


class TestPathAndBodyValidation:
    def test_reading_an_unknown_fund_returns_the_fund_not_found_code(self, api):
        """PRD §2.7: "Every resource named in the URL path exists, validated left to
        right, so the leftmost missing identifier decides the response."
        PRD §2.7: "The code is the one belonging to the missing resource type:
        `ERR_FUND_NOT_FOUND`, `ERR_SHARE_CLASS_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`,
        `ERR_POSITION_NOT_FOUND`, `ERR_NAV_RECORD_NOT_FOUND`, `ERR_TRADE_NOT_FOUND`,
        `ERR_DISTRIBUTION_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
        `ERR_REGISTRATION_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_RECONCILIATION_NOT_FOUND`
        or `ERR_LEDGER_ENTRY_NOT_FOUND`, each 404."

        Design: Corner/entities/get_fund_with_unknown_id_returns_not_found
        """
        response = api.get_fund(UNKNOWN_ID, OPERATOR)
        assert response.status_code == 404
        validate_error(response, ApiErrorId.ERR_FUND_NOT_FOUND.value)

    def test_reading_an_unknown_trade_returns_the_trade_not_found_code(self, api):
        """PRD §2.7: "Every resource named in the URL path exists, validated left to
        right, so the leftmost missing identifier decides the response."
        PRD §2.7: "The code is the one belonging to the missing resource type:
        `ERR_FUND_NOT_FOUND`, `ERR_SHARE_CLASS_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`,
        `ERR_POSITION_NOT_FOUND`, `ERR_NAV_RECORD_NOT_FOUND`, `ERR_TRADE_NOT_FOUND`,
        `ERR_DISTRIBUTION_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
        `ERR_REGISTRATION_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_RECONCILIATION_NOT_FOUND`
        or `ERR_LEDGER_ENTRY_NOT_FOUND`, each 404."

        Design: Corner/entities/get_trade_with_unknown_id_returns_not_found
        """
        response = api.get_trade(UNKNOWN_TRADE_ID, OPERATOR)
        assert response.status_code == 404
        validate_error(response, ApiErrorId.ERR_TRADE_NOT_FOUND.value)

    def test_share_class_without_a_breakpoint_schedule_is_rejected(self, api):
        """PRD §3.1: "The class's sales-load schedule arrives as `breakpoint_tiers`: an
        ordered array in which each element is an object with a `min_qualifying_amount` in
        dollars to two decimal places and a `load_pct` to four decimal places."
        PRD §2.7: "**Request shape.** Every required field present, every enum value
        inside its declared set, every number within its declared decimal precision and
        sign, every date a well-formed ISO `YYYY-MM-DD` value; `gross_amount` present
        exactly for a `PURCHASE` and absent for a `REDEMPTION` or `EXCHANGE`;
        `shares_requested` present exactly for a `REDEMPTION` or `EXCHANGE` and absent for
        a `PURCHASE`; `exchange_target_share_class_id` present exactly for an `EXCHANGE`;
        `target_share_class_id` present exactly for a `SYSTEMATIC_EXCHANGE`;
        `dealer_firm_code` present exactly when `account_channel` is `NETWORKED` or
        `OMNIBUS`; `breakpoint_tiers` starting at a `min_qualifying_amount` of 0 and
        strictly ascending thereafter. A failure here is `ERR_INVALID_REQUEST` (422)."

        Design: Corner/entities/create_share_class_missing_required_breakpoint_tiers_returns_invalid_request
        """
        fund = create_fund()
        response = api.create_share_class(
            {"fund_id": fund["id"], "class_code": "A", "seed_nav_per_share": 10.0000},
            ACCOUNTANT,
        )
        assert response.status_code == 422
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

        listed, meta = validate_paginated(
            api.list_share_classes(ACCOUNTANT, params={"fund_id": fund["id"]})
        )
        assert meta["total_count"] == 0, "no share class row may survive the rejection"
        assert listed == []

    def test_account_with_an_undeclared_registration_type_is_rejected(self, api):
        """PRD §3.2: "A **ShareholderAccount** is opened by a `TransferAgentOperator` or
        by `DealerOperations` and requires five attributes: the `registration_type`, which
        is the legal registration of the account and is one of `INDIVIDUAL`,
        `JOINT_TENANTS`, `UGMA_UTMA`, `IRA_TRADITIONAL`, `ROTH_IRA`, `TRUST` or
        `CORPORATE`; the `account_channel`, one of `DIRECT`, `NETWORKED` or `OMNIBUS`; the
        `state_code` of the registered owner, exactly two uppercase letters, which selects
        the state registration that the account's purchases will consume; the `tax_id` of
        record, non-empty; and the `primary_owner_name`, also non-empty."
        PRD §2.7: "**Request shape.** Every required field present, every enum value
        inside its declared set, every number within its declared decimal precision and
        sign, every date a well-formed ISO `YYYY-MM-DD` value; `gross_amount` present
        exactly for a `PURCHASE` and absent for a `REDEMPTION` or `EXCHANGE`;
        `shares_requested` present exactly for a `REDEMPTION` or `EXCHANGE` and absent for
        a `PURCHASE`; `exchange_target_share_class_id` present exactly for an `EXCHANGE`;
        `target_share_class_id` present exactly for a `SYSTEMATIC_EXCHANGE`;
        `dealer_firm_code` present exactly when `account_channel` is `NETWORKED` or
        `OMNIBUS`; `breakpoint_tiers` starting at a `min_qualifying_amount` of 0 and
        strictly ascending thereafter. A failure here is `ERR_INVALID_REQUEST` (422)."

        Design: Corner/entities/create_account_with_invalid_registration_type_enum_returns_invalid_request
        """
        response = api.create_shareholder_account(
            create_shareholder_account_payload(
                registration_type="SOLE_PROPRIETOR", account_channel="DIRECT",
                state_code="CA", primary_owner_name="Not A Type",
            ),
            OPERATOR,
        )
        assert response.status_code == 422
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_omnibus_account_without_a_dealer_firm_code_is_rejected(self, api):
        """PRD §3.2: "Three optional attributes may accompany them: `dividend_option`, the
        standing instruction for distributions, either `CASH` or `REINVEST` and defaulting
        to `CASH`; `linked_primary_account_id`, discussed below and defaulting to null; and
        `dealer_firm_code`, the selling dealer's firm code, which is required when
        `account_channel` is `NETWORKED` or `OMNIBUS` and must be omitted or null when it is
        `DIRECT`."
        PRD §2.7: "**Request shape.** Every required field present, every enum value
        inside its declared set, every number within its declared decimal precision and
        sign, every date a well-formed ISO `YYYY-MM-DD` value; `gross_amount` present
        exactly for a `PURCHASE` and absent for a `REDEMPTION` or `EXCHANGE`;
        `shares_requested` present exactly for a `REDEMPTION` or `EXCHANGE` and absent for
        a `PURCHASE`; `exchange_target_share_class_id` present exactly for an `EXCHANGE`;
        `target_share_class_id` present exactly for a `SYSTEMATIC_EXCHANGE`;
        `dealer_firm_code` present exactly when `account_channel` is `NETWORKED` or
        `OMNIBUS`; `breakpoint_tiers` starting at a `min_qualifying_amount` of 0 and
        strictly ascending thereafter. A failure here is `ERR_INVALID_REQUEST` (422)."

        Design: Corner/validations/omnibus_account_without_dealer_firm_code_returns_invalid_request
        """
        rejected = api.create_shareholder_account(
            create_shareholder_account_payload(
                registration_type="CORPORATE", account_channel="OMNIBUS",
                state_code="NY", primary_owner_name="No Dealer Code",
            ),
            OPERATOR,
        )
        assert rejected.status_code == 422
        validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST.value)

        accepted = api.create_shareholder_account(
            create_shareholder_account_payload(
                registration_type="INDIVIDUAL", account_channel="DIRECT",
                state_code="NY", primary_owner_name="Direct Is Fine",
            ),
            OPERATOR,
        )
        direct_account = validate_success(accepted, 201)
        assert direct_account.get("dealer_firm_code") is None


class TestHouseholdLinking:
    def test_linking_to_an_account_that_is_itself_linked_is_rejected(self, api):
        """PRD §3.2: "Linking is single-level and self-exclusive, and all three of the
        following must hold or the request is rejected with `ERR_ROA_LINK_INVALID`: the
        supplied identifier must not be the account's own `id`, it must reference an
        account whose own `linked_primary_account_id` is null, and it must reference an
        account whose `status` is `ACTIVE` or `RESTRICTED`."

        Design: Corner/validations/linking_to_an_already_linked_account_returns_roa_link_invalid
        """
        primary = open_active_account(primary_owner_name="Alpha Primary")
        secondary = open_active_account(
            primary_owner_name="Beta Secondary",
            linked_primary_account_id=primary["id"],
        )

        response = api.create_shareholder_account(
            create_shareholder_account_payload(
                primary_owner_name="Gamma Tertiary",
                linked_primary_account_id=secondary["id"],
            ),
            OPERATOR,
        )
        assert response.status_code == 422
        validate_error(response, ApiErrorId.ERR_ROA_LINK_INVALID.value)

        _, second_level = validate_paginated(
            api.list_shareholder_accounts(
                OPERATOR, params={"linked_primary_account_id": secondary["id"]}
            )
        )
        assert second_level["total_count"] == 0

        _, first_level = validate_paginated(
            api.list_shareholder_accounts(
                OPERATOR, params={"linked_primary_account_id": primary["id"]}
            )
        )
        assert first_level["total_count"] == 1


class TestAccountLifecycleGuards:
    def test_activating_an_already_active_account_is_rejected(self, api):
        """PRD §3.2: "A `TransferAgentOperator` records receipt of the account documents,
        which moves the account `PENDING_DOCS → ACTIVE`; that request supplies
        `tin_certified`, whose value is stamped onto the account, and it recomputes
        `household_basis_amount` — which for a brand-new account is `0.00` — and increments
        the account's `version`."
        PRD §3.2: "An attempt to activate or close an account whose state does not permit
        it answers with `ERR_ACCOUNT_NOT_ACTIVE`."

        Design: Corner/state_machines/activate_on_an_already_active_account_returns_invalid_state
        """
        account = open_account(primary_owner_name="Ida Idempotent")
        activated = validate_success(
            api.activate_shareholder_account(
                account["id"], {"tin_certified": True}, OPERATOR
            )
        )
        assert activated["status"] == "ACTIVE"
        assert activated["tin_certified"] is True

        response = api.activate_shareholder_account(
            account["id"], {"tin_certified": False}, OPERATOR
        )
        assert response.status_code == 409
        validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value)

        after = read_account(account["id"])
        assert after["status"] == "ACTIVE"
        assert after["tin_certified"] is True, "the rejected call must not overwrite it"
        assert after["version"] == activated["version"]

    def test_closing_an_account_that_still_holds_shares_is_rejected(self, api):
        """PRD §3.2: "It is available from either `ACTIVE → CLOSED` or
        `RESTRICTED → CLOSED`, and it requires that every position belonging to the account
        holds exactly `0.000` shares and that the account has no trade still `UNSETTLED`
        whose `execution_status` is anything other than `CANCELLED`."
        PRD §3.2: "An attempt to activate or close an account whose state does not permit
        it answers with `ERR_ACCOUNT_NOT_ACTIVE`."

        Design: Corner/state_machines/close_account_still_holding_shares_returns_invalid_state
        """
        desk = setup_settled_purchase(
            gross_amount=60000.00, account_overrides={"primary_owner_name": "Hank Holder"}
        )
        assert desk["position"]["shares"] == shares(5730.000)

        response = api.close_shareholder_account(desk["account"]["id"], OPERATOR)
        assert response.status_code == 409
        validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value)

        after = read_account(desk["account"]["id"])
        assert after["status"] == "ACTIVE"
        assert after.get("closed_at") is None


class TestAccountReadsAndUpdates:
    def test_patching_the_dividend_option_bumps_the_account_version(self, api):
        """PRD §3.2: "Two attributes may be revised after opening: a
        `TransferAgentOperator` or the `AccountHolder` themselves may submit
        `dividend_option`, `linked_primary_account_id`, or both."
        PRD §2.5: "All resources except share ledger entries additionally carry
        `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation of the record,
        and `version`, an integer that begins at 1 on creation and increments by one on
        every mutation."

        Design: Corner/endpoints/patch_account_dividend_option_updates_the_field_and_bumps_version
        """
        account = open_active_account(
            dividend_option="CASH", primary_owner_name="Pam Patch"
        )
        response = api.update_shareholder_account(
            account["id"], {"dividend_option": "REINVEST"}, OPERATOR
        )
        updated = validate_success(response, 200)
        assert updated["dividend_option"] == "REINVEST"
        assert updated["status"] == "ACTIVE"
        assert updated["tin_certified"] is True
        assert updated.get("linked_primary_account_id") is None
        assert updated["version"] == account["version"] + 1

    def test_account_listing_reports_total_count_and_has_more(self, api):
        """PRD §2.3: "`limit` sets the maximum number of items returned; when it is not
        supplied it defaults to 10, its minimum accepted value is 1, and its maximum
        accepted value is 100."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope. `total_count` reflects the
        number of records matching the request's filters before pagination is applied, and
        `has_more` is true when records matching those filters remain beyond the current
        page."

        Design: Corner/entities/account_listing_paginates_with_total_count_and_has_more
        """
        for name in ("Page One", "Page Two", "Page Three"):
            open_account(primary_owner_name=name)

        first_page, first_meta = validate_paginated(
            api.list_shareholder_accounts(OPERATOR, params={"limit": 2, "offset": 0})
        )
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True

        second_page, second_meta = validate_paginated(
            api.list_shareholder_accounts(OPERATOR, params={"limit": 2, "offset": 2})
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False

    def test_nav_sub_resource_returns_only_the_requested_class(self, api):
        """PRD §3.3: "NAV records may be listed for a share class and narrowed by
        `valuation_date` or by `status`, and may be read individually."
        PRD §3.3: "The strike itself is mechanical. At the moment of the call the class's
        live `total_shares_outstanding` is captured into `shares_outstanding_snapshot`. If
        that snapshot is exactly `0.000` — the class has no shares on the transfer agent's
        books — then `nav_per_share` is set to the class's configured `seed_nav_per_share`."

        Design: Corner/endpoints/nav_record_sub_resource_returns_only_the_requested_class
        """
        base = setup_reference_data(
            tiers=SINGLE_TIER_BREAKPOINT_TIERS, with_registration=False
        )
        other_class = validate_success(
            api.create_share_class(
                create_share_class_payload(
                    base["fund"]["id"], class_code="I", seed_nav_per_share=15.0000,
                    breakpoint_tiers=list(NO_LOAD_BREAKPOINT_TIERS),
                ),
                ACCOUNTANT,
            ),
            201,
        )
        nav_a = strike_nav(base["share_class"]["id"], MONDAY, 0.00, finalize=False)
        nav_i = strike_nav(other_class["id"], MONDAY, 0.00, finalize=False)

        listed, meta = validate_paginated(
            api.list_share_class_nav_records(
                base["share_class"]["id"], ACCOUNTANT, params={"valuation_date": MONDAY}
            )
        )
        assert meta["total_count"] == 1
        assert listed[0]["id"] == nav_a["id"]
        assert listed[0]["nav_per_share"] == price(10.0000)
        assert all(row["id"] != nav_i["id"] for row in listed)
