"""Campaign lifecycle: the revise-and-resubmit cycle, terminal lockdown, and
aggregate guards on cancel/complete."""
from test_helpers import (
    ApiErrorId, create_advertiser, create_campaign, make_sales_manager_headers,
    setup_bookable_slot, validate_error, validate_success,
)
from test_helpers.factories import create_invoice_payload
from test_helpers.fixtures import SM_CREATOR, SM_APPROVER


class TestCampaignRevisionCycle:
    def test_campaign_revision_cycle_reject_reopens_to_draft(self, api):
        """PRD §3.2: "applying an edit to a `REJECTED` campaign reopens it to
        `DRAFT` and increments the campaign's `version` by one, closing the
        revise-and-resubmit loop."

        Design: Difficulty/non_linear_state_machine/campaign_revision_cycle
        """
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"], creator=SM_CREATOR)
        api.submit_campaign(campaign["id"], make_sales_manager_headers(SM_CREATOR))
        resp = api.reject_campaign(campaign["id"], {"reason": "rate too low"},
                                   make_sales_manager_headers(SM_APPROVER))
        rejected = validate_success(resp)
        assert rejected["campaign_status"] == "REJECTED"
        resp = api.patch_campaign(campaign["id"], {"name": "C1-revised"},
                                  make_sales_manager_headers(SM_CREATOR))
        reopened = validate_success(resp)
        assert reopened["campaign_status"] == "DRAFT"
        assert reopened["name"] == "C1-revised"

    def test_campaign_revision_cycle_resubmit_approve(self, api):
        """PRD §3.2: "Approval moves `SUBMITTED → APPROVED` and stamps
        `approved_by_user_id`"

        Design: Difficulty/non_linear_state_machine/campaign_revision_cycle
        """
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"], creator=SM_CREATOR)
        api.submit_campaign(campaign["id"], make_sales_manager_headers(SM_CREATOR))
        api.reject_campaign(campaign["id"], {"reason": "rate too low"},
                            make_sales_manager_headers(SM_APPROVER))
        api.patch_campaign(campaign["id"], {"name": "C1-revised"},
                           make_sales_manager_headers(SM_CREATOR))
        api.submit_campaign(campaign["id"], make_sales_manager_headers(SM_CREATOR))
        resp = api.approve_campaign(campaign["id"], make_sales_manager_headers(SM_APPROVER))
        approved = validate_success(resp)
        assert approved["campaign_status"] == "APPROVED"
        assert approved["approved_by_user_id"] == SM_APPROVER


class TestCampaignTerminalLockdown:
    def test_campaign_submit_from_canceled_rejected(self, api):
        """PRD §3.2: "Both `COMPLETED` and `CANCELED` are terminal."

        Design: Corner/state_machines/campaign_submit_from_canceled_rejected
        """
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"], creator=SM_CREATOR)
        resp = api.cancel_campaign(campaign["id"], make_sales_manager_headers(SM_CREATOR))
        validate_success(resp)
        resp = api.submit_campaign(campaign["id"], make_sales_manager_headers(SM_CREATOR))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        resp = api.get_campaign(campaign["id"], make_sales_manager_headers(SM_CREATOR))
        assert validate_success(resp)["campaign_status"] == "CANCELED"


class TestCampaignAggregateGuards:
    def test_cancel_blocked_by_reserved_slot(self, api):
        """PRD §3.2: "if any of its slots is still `RESERVED` or `CONFIRMED`,
        cancellation is rejected with `ERR_CAMPAIGN_HAS_ACTIVE_SLOTS`."

        Design: Corner/state_machines/campaign_complete_and_cancel_guards
        """
        ctx = setup_bookable_slot()
        resp = api.cancel_campaign(ctx["campaign"]["id"], make_sales_manager_headers(SM_CREATOR))
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_HAS_ACTIVE_SLOTS)

    def test_complete_blocked_by_open_invoice(self, api):
        """PRD §3.2: "only while the campaign carries no invoice in `DRAFT` or
        `ISSUED`, enforced as `ERR_CAMPAIGN_HAS_OPEN_INVOICES`."

        Design: Corner/state_machines/campaign_complete_and_cancel_guards
        """
        ctx = setup_bookable_slot()
        # Withdraw the only slot so the active-slot guard is cleared.
        api.cancel_slot(ctx["slot"]["id"], make_sales_manager_headers(SM_CREATOR))
        resp = api.create_invoice(ctx["campaign"]["id"], create_invoice_payload(),
                                  make_sales_manager_headers(SM_CREATOR))
        validate_success(resp, expected_status=201)
        resp = api.complete_campaign(ctx["campaign"]["id"], make_sales_manager_headers(SM_CREATOR))
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_HAS_OPEN_INVOICES)
