"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------------- catalogues ----------------
    def create_plan_tier(self, payload, headers):
        return self._request("POST", "/plan-tiers", payload, headers)

    def list_plan_tiers(self, headers, params=None):
        return self._request("GET", "/plan-tiers", headers=headers, params=params)

    def create_carrier_rule(self, payload, headers):
        return self._request("POST", "/carrier-rules", payload, headers)

    def list_carrier_rules(self, headers, params=None):
        return self._request("GET", "/carrier-rules", headers=headers, params=params)

    # ---------------- mailboxes ----------------
    def create_box(self, payload, headers):
        return self._request("POST", "/boxes", payload, headers)

    def list_boxes(self, headers, params=None):
        return self._request("GET", "/boxes", headers=headers, params=params)

    def get_box(self, box_id, headers):
        return self._request("GET", f"/boxes/{box_id}", headers=headers)

    def activate_box(self, box_id, headers):
        return self._request("POST", f"/boxes/{box_id}/activate", {}, headers)

    def change_plan(self, box_id, payload, headers):
        return self._request("POST", f"/boxes/{box_id}/plan-change", payload, headers)

    def get_box_summary(self, box_id, headers):
        return self._request("GET", f"/boxes/{box_id}/summary", headers=headers)

    # ---------------- roster ----------------
    def create_recipient(self, box_id, payload, headers):
        return self._request("POST", f"/boxes/{box_id}/recipients", payload, headers)

    def list_box_recipients(self, box_id, headers, params=None):
        return self._request(
            "GET", f"/boxes/{box_id}/recipients", headers=headers, params=params
        )

    def list_recipients(self, headers, params=None):
        return self._request("GET", "/recipients", headers=headers, params=params)

    def get_recipient(self, recipient_id, headers):
        return self._request("GET", f"/recipients/{recipient_id}", headers=headers)

    def patch_recipient(self, recipient_id, payload, headers):
        return self._request("PATCH", f"/recipients/{recipient_id}", payload, headers)

    def remove_recipient(self, recipient_id, headers):
        return self._request(
            "POST", f"/recipients/{recipient_id}/remove", {}, headers
        )

    # ---------------- Form 1583 ----------------
    def create_form_1583(self, recipient_id, payload, headers):
        return self._request(
            "POST", f"/recipients/{recipient_id}/form-1583", payload, headers
        )

    def list_recipient_forms(self, recipient_id, headers, params=None):
        return self._request(
            "GET", f"/recipients/{recipient_id}/form-1583", headers=headers, params=params
        )

    def get_form_1583(self, form_id, headers):
        return self._request("GET", f"/form-1583/{form_id}", headers=headers)

    def notarize_form(self, form_id, headers):
        return self._request("POST", f"/form-1583/{form_id}/notarize", {}, headers)

    def accept_form(self, form_id, headers):
        return self._request("POST", f"/form-1583/{form_id}/accept", {}, headers)

    def reject_form(self, form_id, payload, headers):
        return self._request("POST", f"/form-1583/{form_id}/reject", payload, headers)

    # ---------------- identification documents ----------------
    def create_id_document(self, recipient_id, payload, headers):
        return self._request(
            "POST", f"/recipients/{recipient_id}/id-documents", payload, headers
        )

    def list_id_documents(self, recipient_id, headers, params=None):
        return self._request(
            "GET",
            f"/recipients/{recipient_id}/id-documents",
            headers=headers,
            params=params,
        )

    def verify_id_document(self, document_id, headers):
        return self._request(
            "POST", f"/id-documents/{document_id}/verify", {}, headers
        )

    # ---------------- inbound mail ----------------
    def create_mail_item(self, box_id, payload, headers):
        return self._request("POST", f"/boxes/{box_id}/mail-items", payload, headers)

    def list_box_mail_items(self, box_id, headers, params=None):
        return self._request(
            "GET", f"/boxes/{box_id}/mail-items", headers=headers, params=params
        )

    def list_mail_items(self, headers, params=None):
        return self._request("GET", "/mail-items", headers=headers, params=params)

    def get_mail_item(self, mail_item_id, headers):
        return self._request("GET", f"/mail-items/{mail_item_id}", headers=headers)

    def match_mail_item(self, mail_item_id, payload, headers):
        return self._request(
            "POST", f"/mail-items/{mail_item_id}/match", payload, headers
        )

    def refuse_mail_item(self, mail_item_id, payload, headers):
        return self._request(
            "POST", f"/mail-items/{mail_item_id}/refuse", payload, headers
        )

    def accept_package(self, mail_item_id, headers):
        return self._request(
            "POST", f"/mail-items/{mail_item_id}/package-acceptance", {}, headers
        )

    def notify_mail_item(self, mail_item_id, headers):
        return self._request(
            "POST", f"/mail-items/{mail_item_id}/notify", {}, headers
        )

    def list_mail_item_usage_entries(self, mail_item_id, headers, params=None):
        return self._request(
            "GET",
            f"/mail-items/{mail_item_id}/usage-entries",
            headers=headers,
            params=params,
        )

    # ---------------- imaging ----------------
    def create_scan_job(self, mail_item_id, payload, headers):
        return self._request(
            "POST", f"/mail-items/{mail_item_id}/scan-jobs", payload, headers
        )

    def list_scan_jobs(self, mail_item_id, headers, params=None):
        return self._request(
            "GET", f"/mail-items/{mail_item_id}/scan-jobs", headers=headers, params=params
        )

    def start_scan_job(self, scan_job_id, headers):
        return self._request("POST", f"/scan-jobs/{scan_job_id}/start", {}, headers)

    def complete_scan_job(self, scan_job_id, headers):
        return self._request("POST", f"/scan-jobs/{scan_job_id}/complete", {}, headers)

    def fail_scan_job(self, scan_job_id, headers):
        return self._request("POST", f"/scan-jobs/{scan_job_id}/fail", {}, headers)

    def retry_scan_job(self, scan_job_id, headers):
        return self._request("POST", f"/scan-jobs/{scan_job_id}/retry", {}, headers)

    # ---------------- dispositions ----------------
    def create_disposition(self, mail_item_id, payload, headers):
        return self._request(
            "POST", f"/mail-items/{mail_item_id}/dispositions", payload, headers
        )

    def list_dispositions(self, mail_item_id, headers, params=None):
        return self._request(
            "GET",
            f"/mail-items/{mail_item_id}/dispositions",
            headers=headers,
            params=params,
        )

    def cancel_disposition(self, disposition_id, headers):
        return self._request(
            "POST", f"/dispositions/{disposition_id}/cancel", {}, headers
        )

    def execute_disposition(self, disposition_id, headers):
        return self._request(
            "POST", f"/dispositions/{disposition_id}/execute", {}, headers
        )

    # ---------------- consolidated forwarding ----------------
    def create_forward_shipment(self, box_id, payload, headers):
        return self._request(
            "POST", f"/boxes/{box_id}/forward-shipments", payload, headers
        )

    def list_box_forward_shipments(self, box_id, headers, params=None):
        return self._request(
            "GET", f"/boxes/{box_id}/forward-shipments", headers=headers, params=params
        )

    def get_forward_shipment(self, shipment_id, headers):
        return self._request(
            "GET", f"/forward-shipments/{shipment_id}", headers=headers
        )

    def ship_forward_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/forward-shipments/{shipment_id}/ship", {}, headers
        )

    def cancel_forward_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/forward-shipments/{shipment_id}/cancel", {}, headers
        )

    # ---------------- cheques and deposit batches ----------------
    def create_deposit_batch(self, box_id, payload, headers):
        return self._request(
            "POST", f"/boxes/{box_id}/deposit-batches", payload, headers
        )

    def list_deposit_batches(self, box_id, headers, params=None):
        return self._request(
            "GET", f"/boxes/{box_id}/deposit-batches", headers=headers, params=params
        )

    def get_deposit_batch(self, batch_id, headers):
        return self._request("GET", f"/deposit-batches/{batch_id}", headers=headers)

    def create_check_deposit(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/deposit-batches/{batch_id}/checks", payload, headers
        )

    def list_check_deposits(self, headers, params=None):
        return self._request("GET", "/check-deposits", headers=headers, params=params)

    def get_check_deposit(self, check_id, headers):
        return self._request("GET", f"/check-deposits/{check_id}", headers=headers)

    def rematch_check_deposit(self, check_id, headers):
        return self._request(
            "POST", f"/check-deposits/{check_id}/rematch", {}, headers
        )

    def return_check_deposit(self, check_id, headers):
        return self._request("POST", f"/check-deposits/{check_id}/return", {}, headers)

    def close_deposit_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/deposit-batches/{batch_id}/close", {}, headers
        )

    # ---------------- registered-agent add-on ----------------
    def create_registered_agent(self, box_id, payload, headers):
        return self._request(
            "POST", f"/boxes/{box_id}/registered-agent", payload, headers
        )

    def list_registered_agents(self, box_id, headers, params=None):
        return self._request(
            "GET", f"/boxes/{box_id}/registered-agent", headers=headers, params=params
        )

    def deactivate_registered_agent(self, box_id, headers):
        return self._request(
            "POST", f"/boxes/{box_id}/registered-agent/deactivate", {}, headers
        )

    # ---------------- compliance ----------------
    def create_compliance_review(self, box_id, payload, headers):
        return self._request(
            "POST", f"/boxes/{box_id}/compliance-reviews", payload, headers
        )

    def list_compliance_reviews(self, box_id, headers, params=None):
        return self._request(
            "GET", f"/boxes/{box_id}/compliance-reviews", headers=headers, params=params
        )

    def suspend_compliance_review(self, review_id, headers):
        return self._request(
            "POST", f"/compliance-reviews/{review_id}/suspend", {}, headers
        )

    def resolve_compliance_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/compliance-reviews/{review_id}/resolve", payload, headers
        )

    # ---------------- billing ----------------
    def list_billing_cycles(self, box_id, headers, params=None):
        return self._request(
            "GET", f"/boxes/{box_id}/billing-cycles", headers=headers, params=params
        )

    def get_billing_cycle(self, cycle_id, headers):
        return self._request("GET", f"/billing-cycles/{cycle_id}", headers=headers)

    def list_cycle_usage_entries(self, cycle_id, headers, params=None):
        return self._request(
            "GET",
            f"/billing-cycles/{cycle_id}/usage-entries",
            headers=headers,
            params=params,
        )

    def close_billing_cycle(self, box_id, headers):
        return self._request(
            "POST", f"/boxes/{box_id}/billing-cycles/close", {}, headers
        )

    # ---------------- cancellation ----------------
    def create_cancellation(self, box_id, payload, headers):
        return self._request(
            "POST", f"/boxes/{box_id}/cancellation", payload, headers
        )

    def list_cancellations(self, box_id, headers, params=None):
        return self._request(
            "GET", f"/boxes/{box_id}/cancellation", headers=headers, params=params
        )

    def withdraw_cancellation(self, box_id, headers):
        return self._request(
            "POST", f"/boxes/{box_id}/cancellation/withdraw", {}, headers
        )

    def finalize_cancellation(self, box_id, headers):
        return self._request(
            "POST", f"/boxes/{box_id}/cancellation/finalize", {}, headers
        )


api_client = ApiClient()
