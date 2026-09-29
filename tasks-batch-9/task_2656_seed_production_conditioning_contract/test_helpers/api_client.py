"""HTTP client exposing one method per declared endpoint."""

from __future__ import annotations

from typing import Any

import requests

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/seed-ops"


class ApiClient(GenericApiClient):
    """One method per endpoint; every method returns the raw response."""

    # ------------------------------------------------------------------
    # Administrative clock
    # ------------------------------------------------------------------

    def set_clock(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload=payload, headers=headers)

    # ------------------------------------------------------------------
    # Varieties
    # ------------------------------------------------------------------

    def create_variety(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        return self._request("POST", f"{BASE}/varieties", payload=payload, headers=headers)

    def get_variety(self, variety_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        return self._request("GET", f"{BASE}/varieties/{variety_id}", headers=headers)

    def list_varieties(
        self, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/varieties", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Treatment products
    # ------------------------------------------------------------------

    def create_treatment_product(
        self, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/treatment-products", payload=payload, headers=headers)

    def get_treatment_product(
        self, treatment_product_id: str, headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/treatment-products/{treatment_product_id}", headers=headers)

    def list_treatment_products(
        self, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/treatment-products", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Growers
    # ------------------------------------------------------------------

    def create_grower(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        return self._request("POST", f"{BASE}/growers", payload=payload, headers=headers)

    def get_grower(self, grower_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        return self._request("GET", f"{BASE}/growers/{grower_id}", headers=headers)

    def list_growers(
        self, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/growers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Production fields, history and eligibility
    # ------------------------------------------------------------------

    def create_production_field(
        self, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/production-fields", payload=payload, headers=headers)

    def get_production_field(
        self, production_field_id: str, headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/production-fields/{production_field_id}", headers=headers)

    def list_production_fields(
        self, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/production-fields", headers=headers, params=params)

    def create_field_history_record(
        self, production_field_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/production-fields/{production_field_id}/history", payload=payload, headers=headers
        )

    def get_field_history_record(
        self, field_history_record_id: str, headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/field-history-records/{field_history_record_id}", headers=headers)

    def list_field_history_records(
        self, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/field-history-records", headers=headers, params=params)

    def create_eligibility_assessment(
        self, production_field_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/production-fields/{production_field_id}/eligibility-assessments",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Production contracts
    # ------------------------------------------------------------------

    def create_production_contract(
        self, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/production-contracts", payload=payload, headers=headers)

    def offer_production_contract(
        self,
        production_contract_id: str,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/production-contracts/{production_contract_id}/offer",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def sign_production_contract(
        self, production_contract_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/production-contracts/{production_contract_id}/sign", payload=payload, headers=headers
        )

    def cancel_production_contract(
        self,
        production_contract_id: str,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/production-contracts/{production_contract_id}/cancel",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def get_production_contract(
        self, production_contract_id: str, headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/production-contracts/{production_contract_id}", headers=headers)

    def list_production_contracts(
        self, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/production-contracts", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Field inspections and rogueing
    # ------------------------------------------------------------------

    def create_field_inspection(
        self, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/field-inspections", payload=payload, headers=headers)

    def declare_rogueing(
        self, field_inspection_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/field-inspections/{field_inspection_id}/rogueing-declaration",
            payload=payload,
            headers=headers,
        )

    def verify_rogueing(
        self, field_inspection_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/field-inspections/{field_inspection_id}/rogueing-verification",
            payload=payload,
            headers=headers,
        )

    def get_field_inspection(
        self, field_inspection_id: str, headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/field-inspections/{field_inspection_id}", headers=headers)

    def list_field_inspections(
        self, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/field-inspections", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Harvest equipment
    # ------------------------------------------------------------------

    def create_harvest_equipment(
        self, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/harvest-equipment", payload=payload, headers=headers)

    def certify_equipment_cleanout(
        self, harvest_equipment_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/harvest-equipment/{harvest_equipment_id}/cleanout-certification",
            payload=payload,
            headers=headers,
        )

    def get_harvest_equipment(
        self, harvest_equipment_id: str, headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/harvest-equipment/{harvest_equipment_id}", headers=headers)

    def list_harvest_equipment(
        self, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/harvest-equipment", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Harvest events
    # ------------------------------------------------------------------

    def create_harvest_event(
        self, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/harvest-events", payload=payload, headers=headers)

    def get_harvest_event(self, harvest_event_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        return self._request("GET", f"{BASE}/harvest-events/{harvest_event_id}", headers=headers)

    def list_harvest_events(
        self, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/harvest-events", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Conditioning lines
    # ------------------------------------------------------------------

    def create_conditioning_line(
        self, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/conditioning-lines", payload=payload, headers=headers)

    def get_conditioning_line(
        self, conditioning_line_id: str, headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/conditioning-lines/{conditioning_line_id}", headers=headers)

    def list_conditioning_lines(
        self, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/conditioning-lines", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Conditioning runs
    # ------------------------------------------------------------------

    def create_conditioning_run(
        self, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/conditioning-runs", payload=payload, headers=headers)

    def complete_conditioning_run(
        self, conditioning_run_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/conditioning-runs/{conditioning_run_id}/complete", payload=payload, headers=headers
        )

    def reverse_conditioning_run(
        self, conditioning_run_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/conditioning-runs/{conditioning_run_id}/reversal", payload=payload, headers=headers
        )

    def get_conditioning_run(
        self, conditioning_run_id: str, headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/conditioning-runs/{conditioning_run_id}", headers=headers)

    def list_conditioning_runs(
        self, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/conditioning-runs", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Seed lots
    # ------------------------------------------------------------------

    def create_carryover(
        self, seed_lot_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/seed-lots/{seed_lot_id}/carryover", payload=payload, headers=headers)

    def get_seed_lot(self, seed_lot_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        return self._request("GET", f"{BASE}/seed-lots/{seed_lot_id}", headers=headers)

    def list_seed_lots(
        self, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/seed-lots", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Lot samples and results
    # ------------------------------------------------------------------

    def create_lot_sample(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        return self._request("POST", f"{BASE}/lot-samples", payload=payload, headers=headers)

    def post_lot_sample_results(
        self, lot_sample_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/lot-samples/{lot_sample_id}/results", payload=payload, headers=headers)

    def get_lot_sample(self, lot_sample_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        return self._request("GET", f"{BASE}/lot-samples/{lot_sample_id}", headers=headers)

    def list_lot_samples(
        self, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/lot-samples", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Certification tags
    # ------------------------------------------------------------------

    def create_certification_tag(
        self, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/certification-tags", payload=payload, headers=headers)

    def void_certification_tag(
        self, certification_tag_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/certification-tags/{certification_tag_id}/void", payload=payload, headers=headers
        )

    def get_certification_tag(
        self, certification_tag_id: str, headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/certification-tags/{certification_tag_id}", headers=headers)

    def list_certification_tags(
        self, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/certification-tags", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Settlements
    # ------------------------------------------------------------------

    def create_settlement(self, payload: dict[str, Any], headers: dict[str, str] | None = None) -> requests.Response:
        return self._request("POST", f"{BASE}/settlements", payload=payload, headers=headers)

    def approve_settlement(
        self, settlement_id: str, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/settlements/{settlement_id}/approve",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def dispute_settlement(
        self, settlement_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/settlements/{settlement_id}/dispute", payload=payload, headers=headers
        )

    def pay_settlement(
        self, settlement_id: str, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/settlements/{settlement_id}/pay", payload=payload, headers=headers)

    def get_settlement(self, settlement_id: str, headers: dict[str, str] | None = None) -> requests.Response:
        return self._request("GET", f"{BASE}/settlements/{settlement_id}", headers=headers)

    def list_settlements(
        self, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/settlements", headers=headers, params=params)


api_client = ApiClient()
