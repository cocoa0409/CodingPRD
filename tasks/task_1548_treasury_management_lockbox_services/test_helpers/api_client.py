"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PRD §2.5 / §4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Bank
    # ------------------------------------------------------------------
    def create_bank(self, payload, headers):
        return self._request("POST", "/banks", payload, headers)

    def get_bank(self, bank_id, headers):
        return self._request("GET", f"/banks/{bank_id}", headers=headers)

    def suspend_bank(self, bank_id, headers):
        return self._request("POST", f"/banks/{bank_id}/suspend", {}, headers)

    def resume_bank(self, bank_id, headers):
        return self._request("POST", f"/banks/{bank_id}/resume", {}, headers)

    def liquidate_bank(self, bank_id, headers):
        return self._request("POST", f"/banks/{bank_id}/liquidate", {}, headers)

    def close_business_day(self, bank_id, headers):
        return self._request("POST", f"/banks/{bank_id}/close_business_day", {}, headers)

    def close_analysis_cycle(self, bank_id, headers, customer_id=None):
        payload = {}
        if customer_id is not None:
            payload["customer_id"] = customer_id
        return self._request("POST", f"/banks/{bank_id}/close_analysis_cycle",
                             payload, headers)

    # ------------------------------------------------------------------
    # Customer
    # ------------------------------------------------------------------
    def create_customer(self, bank_id, payload, headers):
        return self._request("POST", f"/banks/{bank_id}/customers", payload, headers)

    def get_customer(self, bank_id, customer_id, headers):
        return self._request("GET", f"/banks/{bank_id}/customers/{customer_id}",
                             headers=headers)

    def list_customers(self, bank_id, headers, params=None):
        return self._request("GET", f"/banks/{bank_id}/customers",
                             headers=headers, params=params)

    def begin_onboarding(self, bank_id, customer_id, headers):
        return self._request(
            "POST", f"/banks/{bank_id}/customers/{customer_id}/begin_onboarding",
            {}, headers)

    def suspend_customer(self, bank_id, customer_id, headers):
        return self._request(
            "POST", f"/banks/{bank_id}/customers/{customer_id}/suspend", {}, headers)

    def resume_customer(self, bank_id, customer_id, headers):
        return self._request(
            "POST", f"/banks/{bank_id}/customers/{customer_id}/resume", {}, headers)

    def terminate_customer(self, bank_id, customer_id, headers):
        return self._request(
            "POST", f"/banks/{bank_id}/customers/{customer_id}/terminate", {}, headers)

    # ------------------------------------------------------------------
    # ServiceAgreement
    # ------------------------------------------------------------------
    def create_agreement(self, bank_id, customer_id, payload, headers):
        return self._request(
            "POST", f"/banks/{bank_id}/customers/{customer_id}/agreements",
            payload, headers)

    def get_agreement(self, bank_id, customer_id, agreement_id, headers):
        return self._request(
            "GET",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}",
            headers=headers)

    def list_agreements(self, bank_id, customer_id, headers, params=None):
        return self._request(
            "GET", f"/banks/{bank_id}/customers/{customer_id}/agreements",
            headers=headers, params=params)

    def implement_agreement(self, bank_id, customer_id, agreement_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}/implement",
            {}, headers)

    def activate_agreement(self, bank_id, customer_id, agreement_id,
                           expected_agreement_version, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}/activate",
            {"expected_agreement_version": expected_agreement_version}, headers)

    def suspend_agreement(self, bank_id, customer_id, agreement_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}/suspend",
            {}, headers)

    def resume_agreement(self, bank_id, customer_id, agreement_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}/resume",
            {}, headers)

    def terminate_agreement(self, bank_id, customer_id, agreement_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}/terminate",
            {}, headers)

    # ------------------------------------------------------------------
    # LockboxSite
    # ------------------------------------------------------------------
    def create_site(self, bank_id, customer_id, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}/sites",
            payload, headers)

    def get_site(self, bank_id, customer_id, agreement_id, site_id, headers):
        return self._request(
            "GET",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}",
            headers=headers)

    def list_sites(self, bank_id, customer_id, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}/sites",
            headers=headers, params=params)

    def go_live_site(self, bank_id, customer_id, agreement_id, site_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/go_live",
            {}, headers)

    def suspend_site(self, bank_id, customer_id, agreement_id, site_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/suspend",
            {}, headers)

    def decommission_site(self, bank_id, customer_id, agreement_id, site_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/decommission",
            {}, headers)

    # ------------------------------------------------------------------
    # AvailabilitySchedule
    # ------------------------------------------------------------------
    def create_availability_schedule(self, bank_id, customer_id, agreement_id,
                                     site_id, payload, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/availability_schedules",
            payload, headers)

    def get_availability_schedule(self, bank_id, customer_id, agreement_id,
                                  site_id, schedule_id, headers):
        return self._request(
            "GET",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/availability_schedules/{schedule_id}",
            headers=headers)

    def list_availability_schedules(self, bank_id, customer_id, agreement_id,
                                    site_id, headers, params=None):
        return self._request(
            "GET",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/availability_schedules",
            headers=headers, params=params)

    def retire_availability_schedule(self, bank_id, customer_id, agreement_id,
                                     site_id, schedule_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/availability_schedules/{schedule_id}/retire",
            {}, headers)

    # ------------------------------------------------------------------
    # TransmissionFormat
    # ------------------------------------------------------------------
    def create_transmission_format(self, bank_id, customer_id, agreement_id,
                                   payload, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/transmission_formats",
            payload, headers)

    def get_transmission_format(self, bank_id, customer_id, agreement_id,
                                format_id, headers):
        return self._request(
            "GET",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/transmission_formats/{format_id}",
            headers=headers)

    def list_transmission_formats(self, bank_id, customer_id, agreement_id,
                                  headers, params=None):
        return self._request(
            "GET",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/transmission_formats",
            headers=headers, params=params)

    def activate_transmission_format(self, bank_id, customer_id, agreement_id,
                                     format_id, expected_agreement_version, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/transmission_formats/{format_id}/activate",
            {"expected_agreement_version": expected_agreement_version}, headers)

    def retire_transmission_format(self, bank_id, customer_id, agreement_id,
                                   format_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/transmission_formats/{format_id}/retire",
            {}, headers)

    # ------------------------------------------------------------------
    # RemittanceBatch
    # ------------------------------------------------------------------
    def create_batch(self, bank_id, customer_id, agreement_id, site_id,
                     payload, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/batches",
            payload, headers)

    def get_batch(self, bank_id, customer_id, agreement_id, site_id, batch_id,
                  headers):
        return self._request(
            "GET",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/batches/{batch_id}",
            headers=headers)

    def list_batches(self, bank_id, customer_id, agreement_id, site_id, headers,
                     params=None):
        return self._request(
            "GET",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/batches",
            headers=headers, params=params)

    def begin_capture(self, bank_id, customer_id, agreement_id, site_id, batch_id,
                      headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/batches/{batch_id}/begin_capture",
            {}, headers)

    def balance_batch(self, bank_id, customer_id, agreement_id, site_id, batch_id,
                      headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/batches/{batch_id}/balance",
            {}, headers)

    def force_out_of_balance(self, bank_id, customer_id, agreement_id, site_id,
                             batch_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/batches/{batch_id}/force_out_of_balance",
            {}, headers)

    def resume_capture(self, bank_id, customer_id, agreement_id, site_id, batch_id,
                       headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/batches/{batch_id}/resume_capture",
            {}, headers)

    def close_batch(self, bank_id, customer_id, agreement_id, site_id, batch_id,
                    headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/batches/{batch_id}/close",
            {}, headers)

    def transmit_batch(self, bank_id, customer_id, agreement_id, site_id, batch_id,
                       headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/batches/{batch_id}/transmit",
            {}, headers)

    def acknowledge_transmission(self, bank_id, customer_id, agreement_id, site_id,
                                 batch_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/batches/{batch_id}/acknowledge_transmission",
            {}, headers)

    def mark_transmission_failed(self, bank_id, customer_id, agreement_id, site_id,
                                 batch_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/batches/{batch_id}/mark_transmission_failed",
            {}, headers)

    # ------------------------------------------------------------------
    # RemittanceItem
    # ------------------------------------------------------------------
    def create_item(self, bank_id, customer_id, agreement_id, site_id, batch_id,
                    payload, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/batches/{batch_id}/items",
            payload, headers)

    def get_item(self, bank_id, customer_id, agreement_id, site_id, batch_id,
                 item_id, headers):
        return self._request(
            "GET",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/batches/{batch_id}/items/{item_id}",
            headers=headers)

    def list_items(self, bank_id, customer_id, agreement_id, site_id, batch_id,
                   headers, params=None):
        return self._request(
            "GET",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/batches/{batch_id}/items",
            headers=headers, params=params)

    def accept_item(self, bank_id, customer_id, agreement_id, site_id, batch_id,
                    item_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/batches/{batch_id}/items/{item_id}/accept",
            {}, headers)

    def return_item(self, bank_id, customer_id, agreement_id, site_id, batch_id,
                    item_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/batches/{batch_id}/items/{item_id}/return",
            {}, headers)

    def raise_exception(self, bank_id, customer_id, agreement_id, site_id,
                        batch_id, item_id, payload, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/agreements/{agreement_id}"
            f"/sites/{site_id}/batches/{batch_id}/items/{item_id}/raise_exception",
            payload, headers)

    # ------------------------------------------------------------------
    # ExceptionItem
    # ------------------------------------------------------------------
    def get_exception_item(self, bank_id, customer_id, exception_id, headers):
        return self._request(
            "GET",
            f"/banks/{bank_id}/customers/{customer_id}/exception_items/{exception_id}",
            headers=headers)

    def list_exception_items(self, bank_id, customer_id, headers, params=None):
        return self._request(
            "GET", f"/banks/{bank_id}/customers/{customer_id}/exception_items",
            headers=headers, params=params)

    def decide_exception(self, bank_id, customer_id, exception_id, decision,
                         headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/exception_items/{exception_id}"
            f"/decide",
            {"decision": decision}, headers)

    def escalate_exception(self, bank_id, customer_id, exception_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/exception_items/{exception_id}"
            f"/escalate",
            {}, headers)

    # ------------------------------------------------------------------
    # ImageRetrievalRequest
    # ------------------------------------------------------------------
    def create_image_request(self, bank_id, customer_id, payload, headers):
        return self._request(
            "POST", f"/banks/{bank_id}/customers/{customer_id}/image_requests",
            payload, headers)

    def get_image_request(self, bank_id, customer_id, request_id, headers):
        return self._request(
            "GET",
            f"/banks/{bank_id}/customers/{customer_id}/image_requests/{request_id}",
            headers=headers)

    def list_image_requests(self, bank_id, customer_id, headers, params=None):
        return self._request(
            "GET", f"/banks/{bank_id}/customers/{customer_id}/image_requests",
            headers=headers, params=params)

    def fulfill_image_request(self, bank_id, customer_id, request_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/image_requests/{request_id}"
            f"/fulfill",
            {}, headers)

    def deny_image_request(self, bank_id, customer_id, request_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/image_requests/{request_id}"
            f"/deny",
            {}, headers)

    # ------------------------------------------------------------------
    # AnalysisCycle / AnalysisLineItem
    # ------------------------------------------------------------------
    def get_analysis_cycle(self, bank_id, customer_id, cycle_id, headers):
        return self._request(
            "GET",
            f"/banks/{bank_id}/customers/{customer_id}/analysis_cycles/{cycle_id}",
            headers=headers)

    def list_analysis_cycles(self, bank_id, customer_id, headers, params=None):
        return self._request(
            "GET", f"/banks/{bank_id}/customers/{customer_id}/analysis_cycles",
            headers=headers, params=params)

    def settle_analysis_cycle(self, bank_id, customer_id, cycle_id,
                              expected_cycle_version, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/analysis_cycles/{cycle_id}"
            f"/settle",
            {"expected_cycle_version": expected_cycle_version}, headers)

    def list_line_items(self, bank_id, customer_id, cycle_id, headers, params=None):
        return self._request(
            "GET",
            f"/banks/{bank_id}/customers/{customer_id}/analysis_cycles/{cycle_id}"
            f"/line_items",
            headers=headers, params=params)

    def get_line_item(self, bank_id, customer_id, cycle_id, line_item_id, headers):
        return self._request(
            "GET",
            f"/banks/{bank_id}/customers/{customer_id}/analysis_cycles/{cycle_id}"
            f"/line_items/{line_item_id}",
            headers=headers)

    # ------------------------------------------------------------------
    # SLAIncident
    # ------------------------------------------------------------------
    def create_sla_incident(self, bank_id, customer_id, payload, headers):
        return self._request(
            "POST", f"/banks/{bank_id}/customers/{customer_id}/sla_incidents",
            payload, headers)

    def get_sla_incident(self, bank_id, customer_id, incident_id, headers):
        return self._request(
            "GET",
            f"/banks/{bank_id}/customers/{customer_id}/sla_incidents/{incident_id}",
            headers=headers)

    def list_sla_incidents(self, bank_id, customer_id, headers, params=None):
        return self._request(
            "GET", f"/banks/{bank_id}/customers/{customer_id}/sla_incidents",
            headers=headers, params=params)

    def confirm_sla_incident(self, bank_id, customer_id, incident_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/sla_incidents/{incident_id}"
            f"/confirm",
            {}, headers)

    def reject_sla_incident(self, bank_id, customer_id, incident_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/sla_incidents/{incident_id}"
            f"/reject",
            {}, headers)

    # ------------------------------------------------------------------
    # ErrorCreditRequest
    # ------------------------------------------------------------------
    def create_error_credit_request(self, bank_id, customer_id, payload, headers):
        return self._request(
            "POST", f"/banks/{bank_id}/customers/{customer_id}/error_credit_requests",
            payload, headers)

    def get_error_credit_request(self, bank_id, customer_id, request_id, headers):
        return self._request(
            "GET",
            f"/banks/{bank_id}/customers/{customer_id}/error_credit_requests"
            f"/{request_id}",
            headers=headers)

    def list_error_credit_requests(self, bank_id, customer_id, headers, params=None):
        return self._request(
            "GET", f"/banks/{bank_id}/customers/{customer_id}/error_credit_requests",
            headers=headers, params=params)

    def approve_error_credit(self, bank_id, customer_id, request_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/error_credit_requests"
            f"/{request_id}/approve",
            {}, headers)

    def approve_partial_error_credit(self, bank_id, customer_id, request_id,
                                     approved_credit_cents, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/error_credit_requests"
            f"/{request_id}/approve_partial",
            {"approved_credit_cents": approved_credit_cents}, headers)

    def deny_error_credit(self, bank_id, customer_id, request_id, headers):
        return self._request(
            "POST",
            f"/banks/{bank_id}/customers/{customer_id}/error_credit_requests"
            f"/{request_id}/deny",
            {}, headers)


api_client = ApiClient()
