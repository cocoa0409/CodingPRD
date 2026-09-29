"""Typed API client: one method per endpoint in PRD §4.

Every method returns the raw ``requests.Response`` so the calling test can
decide whether to run it through ``validate_success``, ``validate_error`` or
``validate_paginated``.
"""

from typing import Any, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

Headers = dict[str, str]
Payload = dict[str, Any]


class ApiClient(GenericApiClient):
    # ----------------------------------------------------------------
    # Logical clock (PRD §2.5)
    # ----------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ----------------------------------------------------------------
    # Equipment models (PRD §3.1)
    # ----------------------------------------------------------------

    def create_equipment_model(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/equipment-models", payload, headers)

    def list_equipment_models(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/equipment-models", None, headers, params=params)

    def get_equipment_model(
        self, model_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"/equipment-models/{model_id}", None, headers)

    def patch_equipment_model(
        self, model_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("PATCH", f"/equipment-models/{model_id}", payload, headers)

    # ----------------------------------------------------------------
    # Certification listings (PRD §3.1, §3.2)
    # ----------------------------------------------------------------

    def create_certification_listing(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/certification-listings", payload, headers)

    def list_certification_listings(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/certification-listings", None, headers, params=params
        )

    def get_certification_listing(
        self, listing_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/certification-listings/{listing_id}", None, headers
        )

    def submit_certification_listing(
        self,
        listing_id: str,
        payload: Optional[Payload] = None,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/certification-listings/{listing_id}/submissions",
            payload or {},
            headers,
        )

    def record_agency_decision(
        self, listing_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/certification-listings/{listing_id}/agency-decisions",
            payload,
            headers,
        )

    # ----------------------------------------------------------------
    # Chain accounts (PRD §3.3)
    # ----------------------------------------------------------------

    def create_chain_account(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/chain-accounts", payload, headers)

    def list_chain_accounts(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/chain-accounts", None, headers, params=params)

    def get_chain_account(
        self, account_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"/chain-accounts/{account_id}", None, headers)

    def patch_chain_account(
        self, account_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("PATCH", f"/chain-accounts/{account_id}", payload, headers)

    # ----------------------------------------------------------------
    # Chain configurations (PRD §3.3, §3.5)
    # ----------------------------------------------------------------

    def create_chain_configuration(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/chain-configurations", payload, headers)

    def list_chain_configurations(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/chain-configurations", None, headers, params=params
        )

    def get_chain_configuration(
        self, config_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"/chain-configurations/{config_id}", None, headers)

    def get_configuration_price_quote(
        self, config_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/chain-configurations/{config_id}/price-quote", None, headers
        )

    def submit_chain_configuration(
        self,
        config_id: str,
        payload: Optional[Payload] = None,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/chain-configurations/{config_id}/submissions",
            payload or {},
            headers,
        )

    def record_engineering_decision(
        self, config_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/chain-configurations/{config_id}/engineering-decisions",
            payload,
            headers,
        )

    def sign_off_branding(
        self, config_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/chain-configurations/{config_id}/branding-signoff",
            payload,
            headers,
        )

    def release_chain_configuration(
        self,
        config_id: str,
        payload: Optional[Payload] = None,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/chain-configurations/{config_id}/release", payload or {}, headers
        )

    # ----------------------------------------------------------------
    # Performance validations (PRD §3.4)
    # ----------------------------------------------------------------

    def create_performance_validation(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/performance-validations", payload, headers)

    def list_performance_validations(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/performance-validations", None, headers, params=params
        )

    def get_performance_validation(
        self, validation_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/performance-validations/{validation_id}", None, headers
        )

    def add_test_run(
        self, validation_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/performance-validations/{validation_id}/test-runs", payload, headers
        )

    def conclude_performance_validation(
        self,
        validation_id: str,
        payload: Optional[Payload] = None,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/performance-validations/{validation_id}/conclusion",
            payload or {},
            headers,
        )

    def retest_performance_validation(
        self,
        validation_id: str,
        payload: Optional[Payload] = None,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/performance-validations/{validation_id}/retest",
            payload or {},
            headers,
        )

    # ----------------------------------------------------------------
    # Construction programmes and site orders (PRD §3.6)
    # ----------------------------------------------------------------

    def create_construction_program(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/construction-programs", payload, headers)

    def list_construction_programs(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/construction-programs", None, headers, params=params
        )

    def get_construction_program(
        self, program_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/construction-programs/{program_id}", None, headers
        )

    def create_site_order(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/site-orders", payload, headers)

    def list_site_orders(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/site-orders", None, headers, params=params)

    def get_site_order(
        self, site_order_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"/site-orders/{site_order_id}", None, headers)

    def waive_commitment(
        self, site_order_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/site-orders/{site_order_id}/commitment-waiver", payload, headers
        )

    def record_fulfillment_event(
        self, site_order_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/site-orders/{site_order_id}/fulfillment-events", payload, headers
        )

    # ----------------------------------------------------------------
    # Build lines and production slots (PRD §3.7)
    # ----------------------------------------------------------------

    def create_build_line(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/build-lines", payload, headers)

    def list_build_lines(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/build-lines", None, headers, params=params)

    def get_build_line(
        self, line_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"/build-lines/{line_id}", None, headers)

    def create_production_slot(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/production-slots", payload, headers)

    def list_production_slots(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/production-slots", None, headers, params=params)

    def get_production_slot(
        self, slot_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"/production-slots/{slot_id}", None, headers)

    def advance_build_progress(
        self, slot_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/production-slots/{slot_id}/build-progress", payload, headers
        )

    def cancel_production_slot(
        self, slot_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/production-slots/{slot_id}/cancellation", payload, headers
        )

    # ----------------------------------------------------------------
    # Connected units (PRD §3.8, §3.9)
    # ----------------------------------------------------------------

    def create_connected_unit(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/connected-units", payload, headers)

    def list_connected_units(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/connected-units", None, headers, params=params)

    def get_connected_unit(
        self, unit_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"/connected-units/{unit_id}", None, headers)

    def post_telemetry(
        self, unit_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/connected-units/{unit_id}/telemetry", payload, headers
        )

    def push_recipe(
        self, unit_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/connected-units/{unit_id}/recipe-pushes", payload, headers
        )

    def coverage_action(
        self, unit_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/connected-units/{unit_id}/coverage-actions", payload, headers
        )

    # ----------------------------------------------------------------
    # Firmware campaigns (PRD §3.8)
    # ----------------------------------------------------------------

    def create_firmware_campaign(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/firmware-campaigns", payload, headers)

    def list_firmware_campaigns(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/firmware-campaigns", None, headers, params=params)

    def get_firmware_campaign(
        self, campaign_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"/firmware-campaigns/{campaign_id}", None, headers)

    def schedule_firmware_campaign(
        self,
        campaign_id: str,
        payload: Optional[Payload] = None,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/firmware-campaigns/{campaign_id}/schedule", payload or {}, headers
        )

    def start_firmware_campaign(
        self,
        campaign_id: str,
        payload: Optional[Payload] = None,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/firmware-campaigns/{campaign_id}/start", payload or {}, headers
        )

    def report_unit_result(
        self, campaign_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/firmware-campaigns/{campaign_id}/unit-results", payload, headers
        )

    def close_firmware_campaign(
        self, campaign_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/firmware-campaigns/{campaign_id}/close", payload, headers
        )

    # ----------------------------------------------------------------
    # Service partners and technician certifications (PRD §3.9)
    # ----------------------------------------------------------------

    def create_service_partner(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/service-partners", payload, headers)

    def list_service_partners(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/service-partners", None, headers, params=params)

    def get_service_partner(
        self, partner_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"/service-partners/{partner_id}", None, headers)

    def partner_authorization(
        self, partner_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/service-partners/{partner_id}/authorization", payload, headers
        )

    def create_technician_certification(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/technician-certifications", payload, headers)

    def list_technician_certifications(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/technician-certifications", None, headers, params=params
        )

    def get_technician_certification(
        self, certification_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/technician-certifications/{certification_id}", None, headers
        )

    def grade_technician_certification(
        self, certification_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/technician-certifications/{certification_id}/grade",
            payload,
            headers,
        )

    # ----------------------------------------------------------------
    # Warranty claims (PRD §3.9)
    # ----------------------------------------------------------------

    def create_warranty_claim(
        self, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("POST", "/warranty-claims", payload, headers)

    def list_warranty_claims(
        self, headers: Optional[Headers] = None, params: Optional[Payload] = None
    ) -> requests.Response:
        return self._request("GET", "/warranty-claims", None, headers, params=params)

    def get_warranty_claim(
        self, claim_id: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request("GET", f"/warranty-claims/{claim_id}", None, headers)

    def adjudicate_warranty_claim(
        self, claim_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/adjudication", payload, headers
        )

    def reverse_warranty_claim(
        self, claim_id: str, payload: Payload, headers: Optional[Headers] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/reversal", payload, headers
        )

    # ----------------------------------------------------------------
    # Raw escape hatch for header-less / malformed-header probes
    # ----------------------------------------------------------------

    def raw_request(
        self,
        method: str,
        path: str,
        payload: Optional[Payload] = None,
        headers: Optional[Headers] = None,
        params: Optional[Payload] = None,
    ) -> requests.Response:
        return self._request(method, path, payload, headers, params=params)


api_client = ApiClient()
