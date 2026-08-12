"""Outreach campaigns: referral intake linkage rules, half-open window overlap,
the regional budget cap, and derived spend on conversion."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_campaign_payload, decision_payload,
    make_institution_officer_headers,
    create_participant, create_campaign, create_referral,
    setup_certified_institution, setup_documented_participant,
    referral_docs_complete,
)

ADMIN = TEST_USERS["coalition_admin_headers"]
NAV = TEST_USERS["agency_navigator_headers"]
MISSING_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


class TestReferralCampaignLinkage:
    def test_campaign_link_rules(self, api):
        """PRD §3.3: "Navigator intake records the creating navigator's opaque identifier as `agency_user_id` and leaves `campaign_id` null; campaign intake requires `campaign_id` to name an `OutreachCampaign` and leaves `agency_user_id` null. Supplying a `campaign_id` on a `NAVIGATOR` referral, or omitting it on a `CAMPAIGN` referral, is a validation failure. A campaign-named referral additionally requires the campaign to still be `ACTIVE`; referencing a `CLOSED` campaign is rejected with `ERR_INVALID_STATE`."
        PRD §2.9: "Only after every path identifier has resolved are body-carried foreign keys resolved, in the order the fields appear in the request payload, again surfacing `ERR_NOT_FOUND` on the first miss."

        Design: Corner/entities/referral_campaign_link_validation
        """
        p = create_participant()
        campaign = create_campaign()
        get_success_data(api.close_outreach_campaign(campaign["id"], ADMIN))

        # CAMPAIGN intake without campaign_id -> 400
        resp = api.create_referral(
            {"participant_id": p["id"], "created_via": "CAMPAIGN"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

        # CAMPAIGN intake naming a non-existent campaign -> 404
        resp = api.create_referral(
            {"participant_id": p["id"], "created_via": "CAMPAIGN",
             "campaign_id": MISSING_UUID},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

        # CAMPAIGN intake naming a CLOSED campaign -> 409
        resp = api.create_referral(
            {"participant_id": p["id"], "created_via": "CAMPAIGN",
             "campaign_id": campaign["id"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        # NAVIGATOR intake carrying a campaign_id -> 400
        resp = api.create_referral(
            {"participant_id": p["id"], "created_via": "NAVIGATOR",
             "campaign_id": campaign["id"]},
            NAV,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestCampaignWindowOverlap:
    def test_adjacent_campaign_allowed(self, api):
        """PRD §3.10: "Within a `zip_cluster`, a new campaign conflicts with any existing `ACTIVE` campaign whose window overlaps it — overlap exists when the new `window_start` falls before the existing `window_end` and the existing `window_start` falls before the new `window_end`, with adjacency (a `window_start` exactly equal to another's `window_end`) not counting as overlap — and such a conflict is rejected with `ERR_CAMPAIGN_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/campaign_zip_cluster_half_open_overlap
        """
        create_campaign(name="Summer Push", window_start="2026-06-01",
                        window_end="2026-08-01", budget_cents=100000)
        resp = api.create_outreach_campaign(
            create_campaign_payload(name="Fall Push", window_start="2026-08-01",
                                    window_end="2026-10-01", budget_cents=50000),
            ADMIN,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "ACTIVE", (
            "start == prior window_end is adjacency, not overlap (half-open)"
        )

    def test_overlapping_campaign_rejected(self, api):
        """PRD §3.10: "overlap exists when the new `window_start` falls before the existing `window_end` and the existing `window_start` falls before the new `window_end`, with adjacency (a `window_start` exactly equal to another's `window_end`) not counting as overlap — and such a conflict is rejected with `ERR_CAMPAIGN_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/campaign_zip_cluster_half_open_overlap
        """
        create_campaign(name="Summer Push", window_start="2026-06-01",
                        window_end="2026-08-01", budget_cents=100000)
        create_campaign(name="Fall Push", window_start="2026-08-01",
                        window_end="2026-10-01", budget_cents=50000)
        resp = api.create_outreach_campaign(
            create_campaign_payload(name="Overlap Push", window_start="2026-07-15",
                                    window_end="2026-09-01", budget_cents=50000),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_OVERLAP)


class TestCampaignBudgetCap:
    def test_budget_cap_equality_allowed_overage_rejected(self, api):
        """PRD §3.10: "The cluster also carries an aggregate budget cap: the sum of `budget_cents` over the cluster's `ACTIVE` campaigns plus the new campaign's budget must not exceed 500000 cents, with equality allowed, and an overage is rejected with `ERR_CAMPAIGN_BUDGET_EXCEEDED`."

        Design: Corner/calculations/campaign_budget_cap_equality_allowed
        """
        create_campaign(name="Big Push", window_start="2026-06-01",
                        window_end="2026-07-01", budget_cents=450000)
        resp = api.create_outreach_campaign(
            create_campaign_payload(name="Exact Fit", window_start="2026-07-01",
                                    window_end="2026-08-01", budget_cents=50000),
            ADMIN,
        )
        validate_success(resp, 201)  # 450000 + 50000 == cap, equality allowed

        resp = api.create_outreach_campaign(
            create_campaign_payload(name="One Cent Over", window_start="2026-08-01",
                                    window_end="2026-09-01", budget_cents=1),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_BUDGET_EXCEEDED)  # 500001 > cap


class TestCampaignSpendDerivation:
    def test_spent_cents_derived_on_conversion(self, api):
        """PRD §3.10: "A campaign is `ACTIVE` from creation with `spent_cents` zero; `spent_cents` is the product of `per_conversion_cents` and the count of the campaign's referrals in `CLOSED_CONVERTED`."
        PRD §3.6: "The linked referral, if any, moves from `APPLIED` to `CLOSED_CONVERTED`; when that referral carries a `campaign_id`, the campaign's `spent_cents` increases by the campaign's `per_conversion_cents`."

        Design: Corner/cross_cutting_layers/campaign_spend_derived_on_conversion
        """
        ctx = setup_certified_institution()
        inst_id = ctx["institution"]["id"]
        campaign = create_campaign(name="Spring Push", window_start="2026-04-01",
                                   window_end="2026-08-01", per_conversion_cents=1000)
        p = setup_documented_participant()
        ref = create_referral(p["id"], navigator=ADMIN, created_via="CAMPAIGN",
                              campaign_id=campaign["id"])
        referral_docs_complete(ref["id"])
        app_resp = api.create_account_application(
            {"participant_id": p["id"], "institution_id": inst_id,
             "id_type_presented": "MATRICULA_CONSULAR", "referral_id": ref["id"]},
            make_institution_officer_headers(inst_id),
        )
        app = validate_success(app_resp, 201)

        before = get_success_data(api.get_outreach_campaign(campaign["id"], ADMIN))
        assert before["spent_cents"] == 0

        validate_success(
            api.decide_account_application(
                app["id"], decision_payload("APPROVE"),
                make_institution_officer_headers(inst_id),
            ), 200
        )
        referral = get_success_data(api.get_referral(ref["id"], NAV))
        assert referral["status"] == "CLOSED_CONVERTED"
        after = get_success_data(api.get_outreach_campaign(campaign["id"], ADMIN))
        assert after["spent_cents"] == 1000, (
            "one converted referral x per_conversion_cents 1000, derived immediately"
        )
