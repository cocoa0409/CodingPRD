"""Outreach campaign scheduling, deferred execution, and cancellation rules."""
from test_helpers import (
    ApiErrorId,
    advance_days,
    create_outreach_campaign_payload,
    create_scheduled_outreach_campaign,
    create_tenant,
    setup_outreach_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOutreachScheduling:
    def test_outreach_schedule_in_past_rejected(self, api, compliance_officer_headers, tenant_admin_headers):
        """PRD §3.7: "Scheduling the campaign moves it `DRAFT` → `SCHEDULED` and validates the timing: the `scheduled_send_day_index` must be the tenant's current day index or a later day — a send day in the past is rejected with `ERR_SCHEDULE_IN_PAST` (HTTP 422) — and `days_before_expiration` must be at least 1, failing as an invalid transition otherwise."

        Design: Corner/state_machines/outreach_schedule_in_past_rejected
        """
        tenant = create_tenant(legal_name="T1")
        advance_days(tenant["id"], 5)  # tenant clock now at day 5
        camp = validate_success(api.create_outreach_campaign(
            tenant["id"],
            create_outreach_campaign_payload(name="OC", target_state_filter=[],
                                             days_before_expiration=30,
                                             scheduled_send_day_index=2),
            compliance_officer_headers), 201)
        res = api.schedule_outreach_campaign(tenant["id"], camp["id"], compliance_officer_headers)
        validate_error(res, ApiErrorId.ERR_SCHEDULE_IN_PAST, expected_status=422)

    def test_outreach_cancel_after_sending_rejected(self, api, compliance_officer_headers):
        """PRD §3.7: "Cancellation of a campaign already in `SENDING` or `DONE` is rejected with `ERR_CAMPAIGN_ALREADY_SENDING` (HTTP 409)."

        Design: Corner/state_machines/outreach_cancel_after_sending_rejected
        """
        tenant = create_tenant(legal_name="T1")
        camp = create_scheduled_outreach_campaign(
            tenant["id"], name="OC", target_state_filter=[],
            days_before_expiration=30, scheduled_send_day_index=1)
        advance_days(tenant["id"], 1)  # fires the send: SCHEDULED -> SENDING -> DONE
        fetched = validate_success(
            api.get_outreach_campaign(tenant["id"], camp["id"], compliance_officer_headers), 200)
        assert fetched["status"] == "DONE"
        res = api.cancel_outreach_campaign(tenant["id"], camp["id"], compliance_officer_headers)
        validate_error(res, ApiErrorId.ERR_CAMPAIGN_ALREADY_SENDING, expected_status=409)


class TestOutreachEmptyCandidateSet:
    def test_empty_candidate_set_completes_done_with_zero_sent(self, api, compliance_officer_headers, tenant_admin_headers):
        """PRD §3.7: "When a clock advance brings the tenant's `audit_clock_day_index` to a `SCHEDULED` campaign's `scheduled_send_day_index` or past it, the campaign moves `SCHEDULED` → `SENDING` and the system selects candidate certificates: certificates in `APPROVED` status, with a non-null `expiration_date`, whose remaining lifetime — the number of days from the current day to the `expiration_date` — is less than or equal to the campaign's `days_before_expiration`, and whose `ship_to_state` appears in `target_state_filter` when the filter is non-empty."
        PRD §3.7: "Once all notices for the campaign are created, the campaign moves `SENDING` → `DONE` within the same clock advance."

        Design: Difficulty/boundary_precision_check/outreach_empty_candidate_set
        """
        # The only certificate ships to CA and expires on day 365; the campaign
        # filters to TX with a 30-day window, so no candidate can match.
        tenant, cust, cert = setup_outreach_scenario(validity_window_days=365,
                                                     effective_date="2026-08-01")
        tid = tenant["id"]
        camp = create_scheduled_outreach_campaign(
            tid, name="OC1", target_state_filter=["TX"],
            days_before_expiration=30, scheduled_send_day_index=5)
        advance_days(tid, 5)
        fetched = validate_success(
            api.get_outreach_campaign(tid, camp["id"], compliance_officer_headers), 200)
        assert fetched["status"] == "DONE", (
            f"empty candidate set must still drive SENDING -> DONE, got {fetched['status']}")
        assert fetched["sent_count"] == 0

    def test_empty_candidate_set_emits_no_notices(self, api, compliance_officer_headers):
        """PRD §3.7: "For each candidate, in that order, the system emits an `OutreachNotice` — copying the campaign's `scheduled_send_day_index` onto the notice and stamping `sent_at_day_index` with the current day index — and increments the campaign's `sent_count` by one per notice."

        Design: Difficulty/boundary_precision_check/outreach_empty_candidate_set
        """
        tenant, cust, cert = setup_outreach_scenario(validity_window_days=365,
                                                     effective_date="2026-08-01")
        tid = tenant["id"]
        camp = create_scheduled_outreach_campaign(
            tid, name="OC1", target_state_filter=["TX"],
            days_before_expiration=30, scheduled_send_day_index=5)
        advance_days(tid, 5)
        data, meta = validate_paginated(
            api.list_outreach_notices(tid, camp["id"], compliance_officer_headers))
        assert data == [], f"no notices may be emitted for an empty candidate set, got {data}"
        assert meta["total_count"] == 0
