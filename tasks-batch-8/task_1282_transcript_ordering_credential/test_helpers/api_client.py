"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/registrar/_clock/set_current_utc", payload, headers)

    # --- Students ---
    def create_student(self, payload, headers):
        return self._request("POST", "/registrar/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/registrar/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/registrar/students/{student_id}", headers=headers)

    def update_student(self, student_id, payload, headers):
        return self._request("PATCH", f"/registrar/students/{student_id}", payload, headers)

    def list_student_records(self, student_id, headers, params=None):
        return self._request(
            "GET", f"/registrar/students/{student_id}/records", headers=headers, params=params
        )

    def publish_student_record(self, student_id, payload, headers):
        return self._request(
            "POST", f"/registrar/students/{student_id}/records", payload, headers
        )

    # --- Recipients ---
    def create_recipient(self, payload, headers):
        return self._request("POST", "/registrar/recipients", payload, headers)

    def list_recipients(self, headers, params=None):
        return self._request("GET", "/registrar/recipients", headers=headers, params=params)

    def get_recipient(self, recipient_id, headers):
        return self._request("GET", f"/registrar/recipients/{recipient_id}", headers=headers)

    def update_recipient(self, recipient_id, payload, headers):
        return self._request("PATCH", f"/registrar/recipients/{recipient_id}", payload, headers)

    # --- Holds ---
    def create_hold(self, payload, headers):
        return self._request("POST", "/registrar/holds", payload, headers)

    def list_holds(self, headers, params=None):
        return self._request("GET", "/registrar/holds", headers=headers, params=params)

    def list_student_holds(self, student_id, headers, params=None):
        return self._request(
            "GET", f"/registrar/students/{student_id}/holds", headers=headers, params=params
        )

    def get_hold(self, hold_id, headers):
        return self._request("GET", f"/registrar/holds/{hold_id}", headers=headers)

    def release_hold(self, hold_id, headers):
        return self._request("POST", f"/registrar/holds/{hold_id}/release", headers=headers)

    # --- Identity verifications ---
    def create_identity_verification(self, payload, headers):
        return self._request("POST", "/registrar/identity-verifications", payload, headers)

    def get_identity_verification(self, verification_id, headers):
        return self._request(
            "GET", f"/registrar/identity-verifications/{verification_id}", headers=headers
        )

    def list_student_identity_verifications(self, student_id, headers, params=None):
        return self._request(
            "GET",
            f"/registrar/students/{student_id}/identity-verifications",
            headers=headers,
            params=params,
        )

    def list_order_identity_verifications(self, order_id, headers, params=None):
        return self._request(
            "GET",
            f"/registrar/orders/{order_id}/identity-verifications",
            headers=headers,
            params=params,
        )

    def confirm_identity_verification(self, verification_id, payload, headers):
        return self._request(
            "POST",
            f"/registrar/identity-verifications/{verification_id}/confirm",
            payload,
            headers,
        )

    def reject_identity_verification(self, verification_id, headers):
        return self._request(
            "POST",
            f"/registrar/identity-verifications/{verification_id}/reject",
            headers=headers,
        )

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/registrar/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/registrar/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/registrar/orders/{order_id}", headers=headers)

    def get_quote_preview(self, order_id, headers):
        return self._request(
            "GET", f"/registrar/orders/{order_id}/quote-preview", headers=headers
        )

    def add_line_item(self, order_id, payload, headers):
        return self._request(
            "POST", f"/registrar/orders/{order_id}/line-items", payload, headers
        )

    def list_order_line_items(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/registrar/orders/{order_id}/line-items", headers=headers, params=params
        )

    def submit_order(self, order_id, payload, headers):
        return self._request("POST", f"/registrar/orders/{order_id}/submit", payload, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/registrar/orders/{order_id}/cancel", payload, headers)

    # --- Line items ---
    def list_line_items(self, headers, params=None):
        return self._request("GET", "/registrar/line-items", headers=headers, params=params)

    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/registrar/line-items/{line_item_id}", headers=headers)

    def dispatch_line_item(self, line_item_id, headers):
        return self._request(
            "POST", f"/registrar/line-items/{line_item_id}/dispatch", headers=headers
        )

    def mark_line_item_delivered(self, line_item_id, headers):
        return self._request(
            "POST", f"/registrar/line-items/{line_item_id}/mark-delivered", headers=headers
        )

    def mark_line_item_bounced(self, line_item_id, headers):
        return self._request(
            "POST", f"/registrar/line-items/{line_item_id}/mark-bounced", headers=headers
        )

    # --- Payments ---
    def create_payment(self, payload, headers):
        return self._request("POST", "/registrar/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/registrar/payments/{payment_id}", headers=headers)

    def list_order_payments(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/registrar/orders/{order_id}/payments", headers=headers, params=params
        )

    def capture_payment(self, payment_id, headers):
        return self._request(
            "POST", f"/registrar/payments/{payment_id}/capture", headers=headers
        )

    def refund_payment(self, payment_id, payload, headers):
        return self._request(
            "POST", f"/registrar/payments/{payment_id}/refund", payload, headers
        )

    def void_payment(self, payment_id, headers):
        return self._request("POST", f"/registrar/payments/{payment_id}/void", headers=headers)

    # --- Consent grants ---
    def create_consent_grant(self, payload, headers):
        return self._request("POST", "/registrar/consent-grants", payload, headers)

    def list_consent_grants(self, headers, params=None):
        return self._request("GET", "/registrar/consent-grants", headers=headers, params=params)

    def list_student_consent_grants(self, student_id, headers, params=None):
        return self._request(
            "GET",
            f"/registrar/students/{student_id}/consent-grants",
            headers=headers,
            params=params,
        )

    def get_consent_grant(self, grant_id, headers):
        return self._request("GET", f"/registrar/consent-grants/{grant_id}", headers=headers)

    def revoke_consent_grant(self, grant_id, headers):
        return self._request(
            "POST", f"/registrar/consent-grants/{grant_id}/revoke", headers=headers
        )

    # --- Verification requests ---
    def create_verification_request(self, payload, headers):
        return self._request("POST", "/registrar/verification-requests", payload, headers)

    def list_verification_requests(self, headers, params=None):
        return self._request(
            "GET", "/registrar/verification-requests", headers=headers, params=params
        )

    def get_verification_request(self, request_id, headers):
        return self._request(
            "GET", f"/registrar/verification-requests/{request_id}", headers=headers
        )

    def list_student_verification_requests(self, student_id, headers, params=None):
        return self._request(
            "GET",
            f"/registrar/students/{student_id}/verification-requests",
            headers=headers,
            params=params,
        )

    def begin_review_verification_request(self, request_id, headers):
        return self._request(
            "POST",
            f"/registrar/verification-requests/{request_id}/begin-review",
            headers=headers,
        )

    def approve_verification_request(self, request_id, headers):
        return self._request(
            "POST", f"/registrar/verification-requests/{request_id}/approve", headers=headers
        )

    def deny_verification_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/registrar/verification-requests/{request_id}/deny", payload, headers
        )

    # --- Archived retrievals ---
    def create_archived_retrieval(self, payload, headers):
        return self._request("POST", "/registrar/archived-retrievals", payload, headers)

    def list_archived_retrievals(self, headers, params=None):
        return self._request(
            "GET", "/registrar/archived-retrievals", headers=headers, params=params
        )

    def get_archived_retrieval(self, retrieval_id, headers):
        return self._request(
            "GET", f"/registrar/archived-retrievals/{retrieval_id}", headers=headers
        )

    def list_student_archived_retrievals(self, student_id, headers, params=None):
        return self._request(
            "GET",
            f"/registrar/students/{student_id}/archived-retrievals",
            headers=headers,
            params=params,
        )

    def mark_retrieval_pulled(self, retrieval_id, headers):
        return self._request(
            "POST", f"/registrar/archived-retrievals/{retrieval_id}/mark-pulled", headers=headers
        )

    def attach_record_to_retrieval(self, retrieval_id, payload, headers):
        return self._request(
            "POST",
            f"/registrar/archived-retrievals/{retrieval_id}/attach-record",
            payload,
            headers,
        )

    def attach_retrieval_to_order(self, retrieval_id, headers):
        return self._request(
            "POST",
            f"/registrar/archived-retrievals/{retrieval_id}/attach-to-order",
            headers=headers,
        )

    def mark_retrieval_failed(self, retrieval_id, headers):
        return self._request(
            "POST", f"/registrar/archived-retrievals/{retrieval_id}/mark-failed", headers=headers
        )

    # --- Reissue requests ---
    def create_reissue_request(self, order_id, payload, headers):
        return self._request(
            "POST", f"/registrar/orders/{order_id}/reissue-requests", payload, headers
        )

    def list_reissue_requests(self, headers, params=None):
        return self._request("GET", "/registrar/reissue-requests", headers=headers, params=params)

    def get_reissue_request(self, request_id, headers):
        return self._request("GET", f"/registrar/reissue-requests/{request_id}", headers=headers)

    def approve_reissue_request(self, request_id, headers):
        return self._request(
            "POST", f"/registrar/reissue-requests/{request_id}/approve", headers=headers
        )

    def reject_reissue_request(self, request_id, headers):
        return self._request(
            "POST", f"/registrar/reissue-requests/{request_id}/reject", headers=headers
        )

    # --- Clearinghouse batches ---
    def create_clearinghouse_batch(self, payload, headers):
        return self._request("POST", "/registrar/clearinghouse-batches", payload, headers)

    def list_clearinghouse_batches(self, headers, params=None):
        return self._request(
            "GET", "/registrar/clearinghouse-batches", headers=headers, params=params
        )

    def get_clearinghouse_batch(self, batch_id, headers):
        return self._request(
            "GET", f"/registrar/clearinghouse-batches/{batch_id}", headers=headers
        )

    def lock_clearinghouse_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/registrar/clearinghouse-batches/{batch_id}/lock", headers=headers
        )

    def transmit_clearinghouse_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/registrar/clearinghouse-batches/{batch_id}/transmit", headers=headers
        )

    def ack_clearinghouse_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/registrar/clearinghouse-batches/{batch_id}/ack", headers=headers
        )

    def fail_clearinghouse_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/registrar/clearinghouse-batches/{batch_id}/mark-failed", headers=headers
        )

    # --- Fee schedules ---
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/registrar/fee-schedules", payload, headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/registrar/fee-schedules", headers=headers, params=params)

    def get_fee_schedule(self, schedule_id, headers):
        return self._request("GET", f"/registrar/fee-schedules/{schedule_id}", headers=headers)

    # --- Audit events ---
    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/registrar/audit-events", headers=headers, params=params)


api_client = ApiClient()
