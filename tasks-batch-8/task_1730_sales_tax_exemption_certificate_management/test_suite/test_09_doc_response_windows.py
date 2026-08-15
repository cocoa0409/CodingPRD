"""Audit sample documentation window: inclusive due-day boundary and the
automatic EXPIRED_NO_RESPONSE transition one day past it."""
from test_helpers import (
    advance_days,
    open_campaign_with_samples,
    request_and_receive_docs,
    setup_customer_with_approved_cert,
    TEST_USERS,
    validate_success,
)

AUD1 = TEST_USERS["auditor_headers"]
CO1 = TEST_USERS["compliance_officer_headers"]


class TestDocResponseWindow:
    def test_receive_docs_on_due_day_succeeds(self, api, auditor_headers, compliance_officer_headers, tenant_admin_headers):
        """PRD §3.8: "A `ComplianceOfficer` records receipt of the paperwork, moving the sample `DOC_REQUESTED` → `DOC_RECEIVED`, but only while the current day is on or before `doc_due_day_index`"
        PRD §2.4: "Every audit sample in `DOC_REQUESTED` whose `doc_due_day_index` falls strictly before the new current day transitions to `EXPIRED_NO_RESPONSE`, pushing the affected customer into `FAILED_SAMPLING` standing as described in §3.8."

        Design: Difficulty/resource_temporal_overlap/outreach_window_vs_doc_request_window
        """
        tenant, cust, cert = setup_customer_with_approved_cert()
        tid = tenant["id"]
        camp, samples = open_campaign_with_samples(
            tid=tid, population_state_filter=["CA"], floor_sample_size=1)
        sample_id = samples[0]["id"]
        # Requested at day 0 -> doc_due_day_index = 0 + 10 = 10.
        validate_success(api.request_docs(tid, sample_id, auditor_headers), 200)
        requested = validate_success(api.get_audit_sample(tid, sample_id, auditor_headers), 200)
        assert requested["outcome"] == "DOC_REQUESTED"
        assert requested["doc_due_day_index"] == 10, (
            "the response window is ten days from the current day index")

        advance_days(tid, 10)  # lands exactly on the due day; strictly-before keeps it open
        received = validate_success(api.receive_docs(tid, sample_id, compliance_officer_headers), 200)
        assert received["outcome"] == "DOC_RECEIVED", (
            "receipt on exactly doc_due_day_index is inside the window")

    def test_sample_expires_one_day_past_due(self, api, auditor_headers, compliance_officer_headers, tenant_admin_headers):
        """PRD §3.8: "Requesting rework loops the sample back `DOC_RECEIVED` → `DOC_REQUESTED` and re-extends `doc_due_day_index` to the current day plus ten."
        PRD §3.8: "a receipt attempted after the deadline is rejected with `ERR_DOC_WINDOW_EXPIRED` (HTTP 409), and when a clock advance carries the current day past the deadline, the sample instead transitions automatically to `EXPIRED_NO_RESPONSE` and the customer's audit standing falls to `FAILED_SAMPLING`."

        Design: Difficulty/resource_temporal_overlap/outreach_window_vs_doc_request_window
        """
        tenant, cust, cert = setup_customer_with_approved_cert()
        tid = tenant["id"]
        camp, samples = open_campaign_with_samples(
            tid=tid, population_state_filter=["CA"], floor_sample_size=1)
        sample_id = samples[0]["id"]
        validate_success(api.request_docs(tid, sample_id, auditor_headers), 200)
        advance_days(tid, 10)  # day 10 == due day
        received = validate_success(api.receive_docs(tid, sample_id, compliance_officer_headers), 200)
        assert received["outcome"] == "DOC_RECEIVED"

        # Rework at day 10 re-extends the deadline to day 20.
        reworked = validate_success(api.request_rework(tid, sample_id, auditor_headers), 200)
        assert reworked["outcome"] == "DOC_REQUESTED"
        assert reworked["doc_due_day_index"] == 20

        advance_days(tid, 11)  # day 21 is strictly past due day 20
        expired = validate_success(api.get_audit_sample(tid, sample_id, auditor_headers), 200)
        assert expired["outcome"] == "EXPIRED_NO_RESPONSE"
        cust_after = validate_success(api.get_customer(tid, cust["id"], auditor_headers), 200)
        assert cust_after["audit_standing"] == "FAILED_SAMPLING"
