"""Entity CRUD, defaults, computed fields, type constraints, immutability,
fraud-score discovery boundary, and basic state-machine corner cases.

Queue B: entities, calculations (fraud boundary lives in difficulty), validations,
and several state_machines corner instances. Queue A: boundary fraud score.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID,
    make_admin_headers, make_compliance_headers, make_brand_headers, make_creator_headers,
    ApiErrorId,
    create_brand, create_creator, create_clean_creator,
    create_draft_campaign, setup_pending_payout, setup_settled_payout,
)

ADMIN = make_admin_headers()
COMPLIANCE = make_compliance_headers()


class TestBrandCreation:
    def test_create_brand_returns_201_with_computed_budget(self, api):
        """PRD §3.1: "A freshly registered brand starts with committed_cents at 0 and
        available_budget_cents equal to its full budget_cents."

        Design: Corner/entities/create_brand_returns_201_with_computed_budget_fields
        """
        resp = api.create_brand(
            {"legal_name": "Acme", "contact_email": "ops@acme.com", "budget_cents": 250000}, ADMIN)
        brand = validate_success(resp, expected_status=201)
        assert brand["committed_cents"] == 0
        assert brand["available_budget_cents"] == 250000
        assert brand["version"] == 1


class TestCreatorCreationAndRetrieval:
    def test_get_creator_returns_initial_computed_fields(self, api):
        """PRD §3.1: "A new creator begins with discovery_status of NEW, brand_safety_status
        of CLEAR, and ytd_paid_cents of 0."

        Design: Corner/entities/get_creator_returns_stored_entity
        """
        creator = create_creator(handle="@plain1", primary_platform="INSTAGRAM")
        fetched = validate_success(api.get_creator(creator["id"], ADMIN))
        assert fetched["discovery_status"] == "NEW"
        assert fetched["brand_safety_status"] == "CLEAR"
        assert fetched["ytd_paid_cents"] == 0

    def test_list_creators_pagination_envelope(self, api):
        """PRD §2.3: "List responses surface the pagination state inside the meta object via
        limit, offset, total_count (the count of all records matching the query, ignoring the
        page window), and has_more (true when records remain beyond the current page)."

        Two creators, limit=1 -> total_count 2, has_more true, one row returned.

        Design: Corner/entities/list_creators_pagination_envelope
        """
        create_creator(handle="@pa1", primary_platform="INSTAGRAM")
        create_creator(handle="@pb1", primary_platform="TIKTOK")
        data, meta = validate_paginated(api.list_creators(ADMIN, params={"limit": 1, "offset": 0}))
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert len(data) == 1

    def test_get_creator_not_found(self, api):
        """PRD §2.8: "if any referenced resource in the path or body does not exist the request
        is rejected with ERR_NOT_FOUND (HTTP 404)."

        Design: Corner/entities/get_creator_not_found_returns_404
        """
        resp = api.get_creator(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_create_creator_invalid_platform_rejected(self, api):
        """PRD §3.1: "The primary_platform is one of INSTAGRAM, TIKTOK, or YOUTUBE."
        PRD §2.10: "then request-body shape — required fields present, correct types, enum
        values in range, and numeric bounds such as "at least 0" or "at least 1" honored
        (ERR_INVALID_REQUEST)".

        Design: Corner/entities/creator_invalid_platform_enum_returns_invalid_request
        """
        resp = api.create_creator({"handle": "@bad1", "primary_platform": "FACEBOOK"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_duplicate_creator_handle_rejected(self, api):
        """PRD §3.1: "The handle must be non-empty and unique across all creators; a collision
        is rejected with ERR_DUPLICATE_VALUE."

        Design: Corner/validations/duplicate_creator_handle_rejected
        """
        create_creator(handle="@dupe1", primary_platform="INSTAGRAM")
        resp = api.create_creator({"handle": "@dupe1", "primary_platform": "TIKTOK"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VALUE.value)


class TestCampaignFieldsAndValidation:
    def test_create_campaign_missing_budget_rejected(self, api):
        """PRD §3.3: "Creating one supplies the brand_id (which must match the acting brand),
        a non-empty title, a campaign_budget_cents earmark (at least 1)".
        PRD §2.10: "a malformed payload surfaces as ERR_INVALID_REQUEST before any state or
        business rule is consulted".

        Design: Corner/entities/create_campaign_missing_required_field_returns_invalid_request
        """
        brand = create_brand(budget_cents=100_000)
        bh = make_brand_headers(brand["id"])
        resp = api.create_campaign(
            {"brand_id": brand["id"], "title": "NoBudget",
             "starts_at": "2026-02-01T00:00:00Z", "ends_at": "2026-03-01T00:00:00Z"}, bh)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_campaign_requires_ftc_disclosure_default_true(self, api):
        """PRD §3.3: "an optional requires_ftc_disclosure flag (defaulting to true, signalling
        that sponsored content must carry an FTC #ad disclosure)".

        Design: Corner/entities/campaign_requires_ftc_disclosure_default_true
        """
        brand = create_brand(budget_cents=100_000)
        bh = make_brand_headers(brand["id"])
        resp = api.create_campaign(
            {"brand_id": brand["id"], "title": "Def", "campaign_budget_cents": 50000,
             "starts_at": "2026-02-01T00:00:00Z", "ends_at": "2026-03-01T00:00:00Z"}, bh)
        campaign = validate_success(resp, expected_status=201)
        assert campaign["requires_ftc_disclosure"] is True

    def test_campaign_starts_after_ends_rejected(self, api):
        """PRD §3.3: "The end must fall strictly after the start; a campaign whose starts_at is
        not before its ends_at is rejected with ERR_VALIDATION."

        Design: Corner/validations/campaign_starts_after_ends_rejected
        """
        brand = create_brand(budget_cents=100_000)
        bh = make_brand_headers(brand["id"])
        resp = api.create_campaign(
            {"brand_id": brand["id"], "title": "SE", "campaign_budget_cents": 50000,
             "requires_ftc_disclosure": False,
             "starts_at": "2026-03-01T00:00:00Z", "ends_at": "2026-02-01T00:00:00Z"}, bh)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestComputedAndImmutable:
    def test_ftc_disclosure_computed_from_caption(self, api):
        """PRD §3.6: "The submission's has_ftc_disclosure is true exactly when the caption is
        non-null and, ignoring letter case, contains either the token #ad or the token
        #sponsored; otherwise it is false. This is a plain case-insensitive substring test
        over the caption text alone."

        A caption containing '#AD' (mixed case) sets has_ftc_disclosure true.

        Design: Corner/entities/ftc_disclosure_computed_from_caption
        """
        from test_helpers import setup_active_contract
        ctx = setup_active_contract(offer_amount_cents=60_000, base_rate_cents=60_000,
                                    requires_ftc_disclosure=True)
        ch = make_creator_headers(ctx["creator"]["id"])
        resp = api.create_content_submission(
            {"deliverable_id": ctx["deliverable"]["id"], "contract_id": ctx["contract"]["id"],
             "media_url": "https://x/ftc", "caption": "check this out #AD friends"}, ch)
        sub = validate_success(resp, expected_status=201)
        assert sub["has_ftc_disclosure"] is True

    def test_audience_snapshot_has_no_version_field(self, api):
        """PRD §2.4: "Two entities are append-only telemetry records and are deliberately not
        versioned: AudienceSnapshot and ConversionEvent carry only an id and a created_at —
        they have neither an updated_at nor a version field, because once written they are
        never mutated."

        Design: Corner/entities/audience_snapshot_immutable_no_version_field
        """
        creator = create_creator(handle="@imm1", primary_platform="TIKTOK")
        resp = api.create_audience_snapshot(creator["id"], {
            "follower_count": 1000, "avg_engagement_rate": 0.05,
            "estimated_reach": 500, "fake_follower_pct": 0.05}, ADMIN)
        snap = validate_success(resp, expected_status=201)
        assert "id" in snap
        assert "created_at" in snap
        assert "version" not in snap
        assert "updated_at" not in snap


class TestFraudScoreBoundary:
    def test_fraud_score_59_discoverable(self, api):
        """PRD §2.11: "DISCOVERABLE when the latest snapshot's fraud_score is below the
        fraud-block threshold of 60, and SUPPRESSED when the latest snapshot's fraud_score is
        at or above 60."
        PRD §3.2: "take fake_follower_pct, express it on a 0-to-100 scale by multiplying by
        100, and weight it by 0.7." (engagement at the 0.05 ceiling contributes 0).

        fake_follower_pct 0.84 at engagement 0.05 -> fraud_score 59 (<60) -> DISCOVERABLE.

        Design: Difficulty/boundary_precision_check/fraud_score_discovery_boundary_at_60
        """
        creator = create_creator(handle="@fraud59a", primary_platform="INSTAGRAM")
        resp = api.create_audience_snapshot(creator["id"], {
            "follower_count": 100000, "avg_engagement_rate": 0.05,
            "estimated_reach": 40000, "fake_follower_pct": 0.84}, ADMIN)
        snap = validate_success(resp, expected_status=201)
        assert snap["fraud_score"] == 59
        fetched = get_success_data(api.get_creator(creator["id"], ADMIN))
        assert fetched["discovery_status"] == "DISCOVERABLE"

    def test_fraud_score_60_suppressed(self, api):
        """PRD §2.11: "DISCOVERABLE when the latest snapshot's fraud_score is below the
        fraud-block threshold of 60, and SUPPRESSED when the latest snapshot's fraud_score is
        at or above 60."
        PRD §3.2: "take fake_follower_pct, express it on a 0-to-100 scale by multiplying by
        100, and weight it by 0.7."

        fake_follower_pct 0.85 at engagement 0.05 -> fraud_score 60 (>=60) -> SUPPRESSED.

        Design: Difficulty/boundary_precision_check/fraud_score_discovery_boundary_at_60
        """
        creator = create_creator(handle="@fraud60a", primary_platform="INSTAGRAM")
        resp = api.create_audience_snapshot(creator["id"], {
            "follower_count": 100000, "avg_engagement_rate": 0.05,
            "estimated_reach": 40000, "fake_follower_pct": 0.85}, ADMIN)
        snap = validate_success(resp, expected_status=201)
        assert snap["fraud_score"] == 60
        fetched = get_success_data(api.get_creator(creator["id"], ADMIN))
        assert fetched["discovery_status"] == "SUPPRESSED"


class TestStateMachineCornerCases:
    def test_cancel_already_cancelled_campaign(self, api):
        """PRD §2.10: "a transition attempted from a state where it is not defined surfaces as
        ERR_INVALID_STATE before the concurrency and business checks run."
        PRD §3.3: "CLOSED and CANCELLED are the terminal states for a campaign."

        Cancelling a CANCELLED campaign -> ERR_INVALID_STATE.

        Design: Corner/state_machines/cancel_already_cancelled_campaign_returns_invalid_state
        """
        brand = create_brand(budget_cents=100_000)
        bh = make_brand_headers(brand["id"])
        campaign, _ = create_draft_campaign(brand["id"], with_deliverable=False,
                                            campaign_budget_cents=50_000)
        cancelled = validate_success(api.cancel_campaign(
            campaign["id"], {"expected_campaign_version": campaign["version"]}, bh))
        resp = api.cancel_campaign(
            campaign["id"], {"expected_campaign_version": cancelled["version"]}, bh)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_open_campaign_with_no_deliverables_rejected(self, api):
        """PRD §3.3: "Opening requires the acting brand to own the campaign, requires that the
        campaign already has at least one deliverable, and requires that its window be valid
        (starts_at before ends_at)."

        Opening a DRAFT campaign with zero deliverables -> ERR_INVALID_STATE.

        Design: Corner/state_machines/open_campaign_with_no_deliverables_returns_invalid_state
        """
        brand = create_brand(budget_cents=100_000)
        bh = make_brand_headers(brand["id"])
        campaign, _ = create_draft_campaign(brand["id"], with_deliverable=False,
                                            campaign_budget_cents=50_000)
        resp = api.open_campaign(
            campaign["id"], {"expected_campaign_version": campaign["version"]}, bh)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_settle_pending_payout_without_release_rejected(self, api):
        """PRD §3.9: "Settling a RELEASED payout moves it RELEASED → SETTLED".
        PRD §2.10: "a transition attempted from a state where it is not defined surfaces as
        ERR_INVALID_STATE".

        Settling a PENDING (un-released) payout -> ERR_INVALID_STATE.

        Design: Corner/state_machines/settle_pending_payout_without_release_returns_invalid_state
        """
        ctx = setup_pending_payout(offer_amount_cents=80_000, content_type="VIDEO")
        resp = api.settle_payout(ctx["payout"]["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_file_voided_1099_rejected(self, api):
        """PRD §3.11: "Alternatively a GENERATED form can be voided, moving it
        GENERATED → VOIDED with no precondition."
        PRD §3.11: "FILED and VOIDED are the terminal states of a 1099."

        A generated 1099 voided, then filed -> ERR_INVALID_STATE (VOIDED is terminal).

        Design: Corner/state_machines/file_voided_1099_terminal_lockdown
        """
        ctx = setup_settled_payout(offer_amount_cents=80_000, content_type="VIDEO")
        forms = validate_success(api.list_creator_tax_forms(ctx["creator"]["id"], COMPLIANCE))
        assert len(forms) == 1
        form_id = forms[0]["id"]
        get_success_data(api.void_tax_form(form_id, COMPLIANCE))
        resp = api.file_tax_form(form_id, COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
