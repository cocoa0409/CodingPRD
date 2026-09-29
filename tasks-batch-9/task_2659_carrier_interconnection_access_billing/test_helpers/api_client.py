"""Typed API client: one method per endpoint of the interconnection API.

Every method returns the raw ``requests.Response`` so that tests can assert on
status codes as well as bodies. Query filters are passed as ``params``.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per endpoint in the carrier interconnection access billing API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers=None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Carriers
    # ------------------------------------------------------------------
    def create_carrier(self, payload, headers=None):
        return self._request("POST", "/interconnection/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers=None):
        return self._request(
            "GET", f"/interconnection/carriers/{carrier_id}", headers=headers
        )

    def list_carriers(self, headers=None, params=None):
        return self._request(
            "GET", "/interconnection/carriers", headers=headers, params=params
        )

    def get_carrier_reserve_summary(self, carrier_id, headers=None):
        return self._request(
            "GET",
            f"/interconnection/carriers/{carrier_id}/reserve-summary",
            headers=headers,
        )

    def list_carrier_agreements(self, carrier_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/interconnection/carriers/{carrier_id}/agreements",
            headers=headers,
            params=params,
        )

    def list_carrier_factor_filings(self, carrier_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/interconnection/carriers/{carrier_id}/traffic-factor-filings",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Agreements and negotiation offers
    # ------------------------------------------------------------------
    def create_agreement(self, payload, headers=None):
        return self._request("POST", "/interconnection/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers=None):
        return self._request(
            "GET", f"/interconnection/agreements/{agreement_id}", headers=headers
        )

    def list_agreements(self, headers=None, params=None):
        return self._request(
            "GET", "/interconnection/agreements", headers=headers, params=params
        )

    def append_offer(self, agreement_id, payload, headers=None):
        return self._request(
            "POST",
            f"/interconnection/agreements/{agreement_id}/offers",
            payload,
            headers,
        )

    def list_agreement_offers(self, agreement_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/interconnection/agreements/{agreement_id}/offers",
            headers=headers,
            params=params,
        )

    def get_offer(self, offer_id, headers=None):
        return self._request(
            "GET", f"/interconnection/negotiation-offers/{offer_id}", headers=headers
        )

    def list_offers(self, headers=None, params=None):
        return self._request(
            "GET", "/interconnection/negotiation-offers", headers=headers, params=params
        )

    def accept_offer(self, offer_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/interconnection/negotiation-offers/{offer_id}/accept",
            payload if payload is not None else {},
            headers,
        )

    def activate_agreement(self, agreement_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/interconnection/agreements/{agreement_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def terminate_agreement(self, agreement_id, payload, headers=None):
        return self._request(
            "POST",
            f"/interconnection/agreements/{agreement_id}/terminate",
            payload,
            headers,
        )

    def withdraw_agreement(self, agreement_id, payload, headers=None):
        return self._request(
            "POST",
            f"/interconnection/agreements/{agreement_id}/withdraw",
            payload,
            headers,
        )

    def get_reciprocal_settlement(self, agreement_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/interconnection/agreements/{agreement_id}/reciprocal-settlement",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Trunk groups
    # ------------------------------------------------------------------
    def create_trunk_group(self, payload, headers=None):
        return self._request("POST", "/interconnection/trunk-groups", payload, headers)

    def get_trunk_group(self, trunk_group_id, headers=None):
        return self._request(
            "GET", f"/interconnection/trunk-groups/{trunk_group_id}", headers=headers
        )

    def list_trunk_groups(self, headers=None, params=None):
        return self._request(
            "GET", "/interconnection/trunk-groups", headers=headers, params=params
        )

    def list_agreement_trunk_groups(self, agreement_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/interconnection/agreements/{agreement_id}/trunk-groups",
            headers=headers,
            params=params,
        )

    def provision_trunk_group(self, trunk_group_id, payload, headers=None):
        return self._request(
            "POST",
            f"/interconnection/trunk-groups/{trunk_group_id}/provision",
            payload,
            headers,
        )

    def activate_trunk_group(self, trunk_group_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/interconnection/trunk-groups/{trunk_group_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def disconnect_trunk_group(self, trunk_group_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/interconnection/trunk-groups/{trunk_group_id}/disconnect",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Traffic measurements
    # ------------------------------------------------------------------
    def create_traffic_measurement(self, trunk_group_id, payload, headers=None):
        return self._request(
            "POST",
            f"/interconnection/trunk-groups/{trunk_group_id}/traffic-measurements",
            payload,
            headers,
        )

    def list_trunk_group_measurements(self, trunk_group_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/interconnection/trunk-groups/{trunk_group_id}/traffic-measurements",
            headers=headers,
            params=params,
        )

    def get_traffic_measurement(self, measurement_id, headers=None):
        return self._request(
            "GET",
            f"/interconnection/traffic-measurements/{measurement_id}",
            headers=headers,
        )

    def list_traffic_measurements(self, headers=None, params=None):
        return self._request(
            "GET",
            "/interconnection/traffic-measurements",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Trunk augment orders
    # ------------------------------------------------------------------
    def list_trunk_group_augment_orders(self, trunk_group_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/interconnection/trunk-groups/{trunk_group_id}/augment-orders",
            headers=headers,
            params=params,
        )

    def get_augment_order(self, order_id, headers=None):
        return self._request(
            "GET",
            f"/interconnection/trunk-augment-orders/{order_id}",
            headers=headers,
        )

    def list_augment_orders(self, headers=None, params=None):
        return self._request(
            "GET",
            "/interconnection/trunk-augment-orders",
            headers=headers,
            params=params,
        )

    def accept_augment_order(self, order_id, payload, headers=None):
        return self._request(
            "POST",
            f"/interconnection/trunk-augment-orders/{order_id}/accept",
            payload,
            headers,
        )

    def reject_augment_order(self, order_id, payload, headers=None):
        return self._request(
            "POST",
            f"/interconnection/trunk-augment-orders/{order_id}/reject",
            payload,
            headers,
        )

    def complete_augment_order(self, order_id, payload, headers=None):
        return self._request(
            "POST",
            f"/interconnection/trunk-augment-orders/{order_id}/complete",
            payload,
            headers,
        )

    def reverse_augment_order(self, order_id, payload, headers=None):
        return self._request(
            "POST",
            f"/interconnection/trunk-augment-orders/{order_id}/reverse",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Tariff filings
    # ------------------------------------------------------------------
    def create_tariff_filing(self, payload, headers=None):
        return self._request("POST", "/interconnection/tariff-filings", payload, headers)

    def get_tariff_filing(self, filing_id, headers=None):
        return self._request(
            "GET", f"/interconnection/tariff-filings/{filing_id}", headers=headers
        )

    def list_tariff_filings(self, headers=None, params=None):
        return self._request(
            "GET", "/interconnection/tariff-filings", headers=headers, params=params
        )

    def approve_tariff_filing(self, filing_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/interconnection/tariff-filings/{filing_id}/approve",
            payload if payload is not None else {},
            headers,
        )

    def withdraw_tariff_filing(self, filing_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/interconnection/tariff-filings/{filing_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Traffic factor filings
    # ------------------------------------------------------------------
    def create_factor_filing(self, payload, headers=None):
        return self._request(
            "POST", "/interconnection/traffic-factor-filings", payload, headers
        )

    def get_factor_filing(self, factor_filing_id, headers=None):
        return self._request(
            "GET",
            f"/interconnection/traffic-factor-filings/{factor_filing_id}",
            headers=headers,
        )

    def list_factor_filings(self, headers=None, params=None):
        return self._request(
            "GET",
            "/interconnection/traffic-factor-filings",
            headers=headers,
            params=params,
        )

    def review_factor_filing(self, factor_filing_id, payload, headers=None):
        return self._request(
            "POST",
            f"/interconnection/traffic-factor-filings/{factor_filing_id}/review",
            payload,
            headers,
        )

    def audit_factor_filing(self, factor_filing_id, payload, headers=None):
        return self._request(
            "POST",
            f"/interconnection/traffic-factor-filings/{factor_filing_id}/audit",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Usage batches and call detail records
    # ------------------------------------------------------------------
    def create_usage_batch(self, payload, headers=None):
        return self._request("POST", "/interconnection/usage-batches", payload, headers)

    def get_usage_batch(self, batch_id, headers=None):
        return self._request(
            "GET", f"/interconnection/usage-batches/{batch_id}", headers=headers
        )

    def list_usage_batches(self, headers=None, params=None):
        return self._request(
            "GET", "/interconnection/usage-batches", headers=headers, params=params
        )

    def append_call_detail_record(self, batch_id, payload, headers=None):
        return self._request(
            "POST",
            f"/interconnection/usage-batches/{batch_id}/call-detail-records",
            payload,
            headers,
        )

    def list_batch_call_detail_records(self, batch_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/interconnection/usage-batches/{batch_id}/call-detail-records",
            headers=headers,
            params=params,
        )

    def get_call_detail_record(self, cdr_id, headers=None):
        return self._request(
            "GET", f"/interconnection/call-detail-records/{cdr_id}", headers=headers
        )

    def list_call_detail_records(self, headers=None, params=None):
        return self._request(
            "GET",
            "/interconnection/call-detail-records",
            headers=headers,
            params=params,
        )

    def jurisdictionalize_batch(self, batch_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/interconnection/usage-batches/{batch_id}/jurisdictionalize",
            payload if payload is not None else {},
            headers,
        )

    def rate_batch(self, batch_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/interconnection/usage-batches/{batch_id}/rate",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Access invoices
    # ------------------------------------------------------------------
    def create_invoice(self, payload, headers=None):
        return self._request(
            "POST", "/interconnection/access-invoices", payload, headers
        )

    def get_invoice(self, invoice_id, headers=None):
        return self._request(
            "GET", f"/interconnection/access-invoices/{invoice_id}", headers=headers
        )

    def list_invoices(self, headers=None, params=None):
        return self._request(
            "GET", "/interconnection/access-invoices", headers=headers, params=params
        )

    def issue_invoice(self, invoice_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/interconnection/access-invoices/{invoice_id}/issue",
            payload if payload is not None else {},
            headers,
        )

    def apply_payment(self, invoice_id, payload, headers=None):
        return self._request(
            "POST",
            f"/interconnection/access-invoices/{invoice_id}/payments",
            payload,
            headers,
        )

    def write_off_invoice(self, invoice_id, payload, headers=None):
        return self._request(
            "POST",
            f"/interconnection/access-invoices/{invoice_id}/write-off",
            payload,
            headers,
        )

    def list_invoice_disputes(self, invoice_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/interconnection/access-invoices/{invoice_id}/disputes",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Billing disputes
    # ------------------------------------------------------------------
    def create_dispute(self, payload, headers=None):
        return self._request(
            "POST", "/interconnection/billing-disputes", payload, headers
        )

    def get_dispute(self, dispute_id, headers=None):
        return self._request(
            "GET", f"/interconnection/billing-disputes/{dispute_id}", headers=headers
        )

    def list_disputes(self, headers=None, params=None):
        return self._request(
            "GET", "/interconnection/billing-disputes", headers=headers, params=params
        )

    def acknowledge_dispute(self, dispute_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/interconnection/billing-disputes/{dispute_id}/acknowledge",
            payload if payload is not None else {},
            headers,
        )

    def resolve_dispute(self, dispute_id, payload, headers=None):
        return self._request(
            "POST",
            f"/interconnection/billing-disputes/{dispute_id}/resolve",
            payload,
            headers,
        )

    def escalate_dispute(self, dispute_id, payload, headers=None):
        return self._request(
            "POST",
            f"/interconnection/billing-disputes/{dispute_id}/escalate",
            payload,
            headers,
        )

    def withdraw_dispute(self, dispute_id, payload, headers=None):
        return self._request(
            "POST",
            f"/interconnection/billing-disputes/{dispute_id}/withdraw",
            payload,
            headers,
        )

    def run_dispute_deadline_sweep(self, payload=None, headers=None):
        return self._request(
            "POST",
            "/interconnection/dispute-deadline-sweeps",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Reconciliation cases
    # ------------------------------------------------------------------
    def create_reconciliation_case(self, payload, headers=None):
        return self._request(
            "POST", "/interconnection/reconciliation-cases", payload, headers
        )

    def get_reconciliation_case(self, case_id, headers=None):
        return self._request(
            "GET",
            f"/interconnection/reconciliation-cases/{case_id}",
            headers=headers,
        )

    def list_reconciliation_cases(self, headers=None, params=None):
        return self._request(
            "GET",
            "/interconnection/reconciliation-cases",
            headers=headers,
            params=params,
        )

    def list_batch_reconciliation_cases(self, batch_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/interconnection/usage-batches/{batch_id}/reconciliation-cases",
            headers=headers,
            params=params,
        )

    def evaluate_reconciliation_case(self, case_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/interconnection/reconciliation-cases/{case_id}/evaluate",
            payload if payload is not None else {},
            headers,
        )

    def adjust_reconciliation_case(self, case_id, payload, headers=None):
        return self._request(
            "POST",
            f"/interconnection/reconciliation-cases/{case_id}/adjust",
            payload,
            headers,
        )

    def accept_reconciliation_case(self, case_id, payload=None, headers=None):
        return self._request(
            "POST",
            f"/interconnection/reconciliation-cases/{case_id}/accept",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Reserve ledger
    # ------------------------------------------------------------------
    def get_reserve_ledger_entry(self, entry_id, headers=None):
        return self._request(
            "GET",
            f"/interconnection/reserve-ledger-entries/{entry_id}",
            headers=headers,
        )

    def list_reserve_ledger_entries(self, headers=None, params=None):
        return self._request(
            "GET",
            "/interconnection/reserve-ledger-entries",
            headers=headers,
            params=params,
        )


# Module-level singleton shared by the fixtures and the test suite.
api_client = ApiClient()
