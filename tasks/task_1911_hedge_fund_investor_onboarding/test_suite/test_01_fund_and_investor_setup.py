"""Fund/share-class/investor onboarding basics: creation, defaults, retrieval, listing."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_fund,
    assert_investor,
    assert_share_class,
    create_fund_payload,
    create_investor_payload,
    create_share_class_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFundCreation:
    def test_fund_creation_returns_201_with_all_fields(self, api, fund_admin_headers):
        """PRD §3.1: "The fund's suspension_status starts as NOT_SUSPENDED, its
        current_nav_period_id starts as null because no NAV period is open yet,
        and its total_net_assets_cents starts at 0."

        Design: Corner/entities/fund_creation_returns_201_with_all_fields
        """
        payload = create_fund_payload(
            fund_name="Alpha", domicile="Cayman", gate_threshold_pct=0.25,
            lockup_months_default=12, notice_days_default=30,
            fiscal_year_end_month=12,
        )
        resp = api.create_fund(payload, fund_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_fund(data)
        assert is_valid_uuid(data["id"])
        assert data["version"] == 1
        assert data["suspension_status"] == "NOT_SUSPENDED"
        assert data["current_nav_period_id"] is None
        assert data["total_net_assets_cents"] == 0


class TestShareClassDefaults:
    def test_share_class_default_open_flags_true(self, api, fund_admin_headers):
        """PRD §3.1: "Each share class also exposes two system-managed flags —
        is_open_for_subscription and is_open_for_redemption — both of which
        default to true."

        Design: Corner/entities/share_class_default_open_flags_true
        """
        fund = validate_success(api.create_fund(create_fund_payload(), fund_admin_headers), 201)
        resp = api.create_share_class(
            fund["id"],
            create_share_class_payload(
                class_code="A",
                min_initial_investment_cents=1000,
                min_additional_investment_cents=500,
                management_fee_bps=100,
                performance_fee_bps=1000,
            ),
            fund_admin_headers,
        )
        sc = validate_success(resp, 201)
        assert_share_class(sc)
        assert sc["is_open_for_subscription"] is True
        assert sc["is_open_for_redemption"] is True


class TestInvestorDefaults:
    def test_investor_aggregate_unfunded_commitment_computed(self, api, fund_admin_headers):
        """PRD §3.2: "New investors start with kyc_status set to NOT_STARTED,
        accreditation_status set to UNVERIFIED, and
        aggregate_unfunded_commitment_cents at 0."

        Design: Corner/entities/investor_aggregate_unfunded_commitment_computed
        """
        inv = validate_success(
            api.create_investor(create_investor_payload(), fund_admin_headers), 201
        )
        resp = api.get_investor(inv["id"], fund_admin_headers)
        data = validate_success(resp, 200)
        assert_investor(data)
        assert data["aggregate_unfunded_commitment_cents"] == 0
        assert data["kyc_status"] == "NOT_STARTED"
        assert data["accreditation_status"] == "UNVERIFIED"


class TestFundNotFound:
    def test_get_nonexistent_fund_returns_404(self, api, fund_admin_headers):
        """PRD §5: ERR_NOT_FOUND — "Referenced entity does not exist".

        Design: Corner/entities/get_nonexistent_fund_returns_404
        """
        resp = api.get_fund(NON_EXISTENT_UUID, fund_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestFundListPagination:
    def test_list_funds_pagination_envelope(self, api, fund_admin_headers):
        """PRD §2.3: "Paginated list responses include the following fields in
        the meta object of the response envelope: limit, offset, total_count,
        and has_more."

        Design: Corner/entities/list_funds_pagination_envelope
        """
        api.create_fund(create_fund_payload(fund_name="F1"), fund_admin_headers)
        api.create_fund(create_fund_payload(fund_name="F2"), fund_admin_headers)
        resp = api.list_funds(fund_admin_headers)
        data, meta = validate_paginated(resp)
        assert meta["total_count"] >= 2
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"pagination meta missing {key}"


class TestFundRequiredFields:
    def test_missing_required_field_returns_invalid_request(self, api, fund_admin_headers):
        """PRD §5: ERR_INVALID_REQUEST — "Missing required field, malformed
        value, or invalid enum". Creating a fund without fund_name must be
        rejected 400 ERR_INVALID_REQUEST.

        Design: Corner/entities/missing_required_field_returns_invalid_request
        """
        payload = create_fund_payload()
        payload.pop("fund_name")
        resp = api.create_fund(payload, fund_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestInvestorEnum:
    def test_invalid_enum_investor_type_rejected(self, api, fund_admin_headers):
        """PRD §5: ERR_INVALID_REQUEST — "Missing required field, malformed
        value, or invalid enum". investor_type must be one of the enumerated
        values in PRD §3.2.

        Design: Corner/entities/invalid_enum_investor_type_rejected
        """
        payload = create_investor_payload(investor_type="FOOBAR")
        resp = api.create_investor(payload, fund_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestKycCaseComputedFields:
    def test_kyc_case_auto_populates_required_documents(self, api, fund_admin_headers, compliance_officer_headers):
        """PRD §3.2: "the system populates required_documents from the
        combination of investor_type and risk_rating."

        Design: Corner/entities/kyc_case_auto_populates_required_documents
        """
        inv = validate_success(
            api.create_investor(
                create_investor_payload(investor_type="CORPORATION"),
                fund_admin_headers,
            ),
            201,
        )
        resp = api.create_kyc_case(
            inv["id"],
            {"risk_rating": "MEDIUM", "pep_hit": False, "sanctions_hit": False, "adverse_media_hit": False},
            compliance_officer_headers,
        )
        case = validate_success(resp, 201)
        assert isinstance(case["required_documents"], list)
        assert len(case["required_documents"]) > 0
        # Initial state on creation is OPEN before the auto-transition kicks in;
        # the case may already have auto-moved to AWAITING_DOCUMENTS.
        assert case["status"] in ("OPEN", "AWAITING_DOCUMENTS")
