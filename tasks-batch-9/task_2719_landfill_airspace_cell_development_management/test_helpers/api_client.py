"""API client: one method per endpoint defined in the PRD."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


def _body(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Action endpoints that take no input fields still post an empty JSON object."""
    return {} if payload is None else payload


class ApiClient(GenericApiClient):
    # ----- logical clock -----
    def set_current_utc(self, current_utc: str, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ----- landfills -----
    def create_landfill(self, payload, headers):
        return self._request("POST", "/landfills", payload, headers)

    def get_landfill(self, landfill_id, headers):
        return self._request("GET", f"/landfills/{landfill_id}", headers=headers)

    def list_landfills(self, headers, params=None):
        return self._request("GET", "/landfills", headers=headers, params=params)

    def set_operating_status(self, landfill_id, payload, headers):
        return self._request(
            "POST", f"/landfills/{landfill_id}/operating-status", _body(payload), headers
        )

    def get_remaining_life_projection(self, landfill_id, headers):
        return self._request(
            "GET", f"/landfills/{landfill_id}/remaining-life-projection", headers=headers
        )

    def list_landfill_cells(self, landfill_id, headers, params=None):
        return self._request(
            "GET", f"/landfills/{landfill_id}/cells", headers=headers, params=params
        )

    # ----- cells -----
    def create_cell(self, payload, headers):
        return self._request("POST", "/cells", payload, headers)

    def get_cell(self, cell_id, headers):
        return self._request("GET", f"/cells/{cell_id}", headers=headers)

    def list_cells(self, headers, params=None):
        return self._request("GET", "/cells", headers=headers, params=params)

    def begin_cell_construction(self, cell_id, headers, payload=None):
        return self._request(
            "POST", f"/cells/{cell_id}/begin-construction", _body(payload), headers
        )

    def authorize_waste_placement(self, cell_id, payload, headers):
        return self._request(
            "POST", f"/cells/{cell_id}/authorize-waste-placement", _body(payload), headers
        )

    def activate_cell(self, cell_id, headers, payload=None):
        return self._request("POST", f"/cells/{cell_id}/activate", _body(payload), headers)

    def close_cell(self, cell_id, payload, headers):
        return self._request("POST", f"/cells/{cell_id}/close", _body(payload), headers)

    def list_cell_liner_qa_packages(self, cell_id, headers, params=None):
        return self._request(
            "GET", f"/cells/{cell_id}/liner-qa-packages", headers=headers, params=params
        )

    def list_cell_gas_wells(self, cell_id, headers, params=None):
        return self._request(
            "GET", f"/cells/{cell_id}/gas-wells", headers=headers, params=params
        )

    # ----- liner CQA packages -----
    def create_liner_qa_package(self, payload, headers):
        return self._request("POST", "/liner-qa-packages", payload, headers)

    def get_liner_qa_package(self, package_id, headers):
        return self._request("GET", f"/liner-qa-packages/{package_id}", headers=headers)

    def list_liner_qa_packages(self, headers, params=None):
        return self._request("GET", "/liner-qa-packages", headers=headers, params=params)

    def begin_liner_qa_review(self, package_id, headers, payload=None):
        return self._request(
            "POST", f"/liner-qa-packages/{package_id}/begin-review", _body(payload), headers
        )

    def return_liner_qa_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"/liner-qa-packages/{package_id}/return", _body(payload), headers
        )

    def resubmit_liner_qa_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"/liner-qa-packages/{package_id}/resubmit", _body(payload), headers
        )

    def approve_liner_qa_package(self, package_id, payload, headers):
        return self._request(
            "POST", f"/liner-qa-packages/{package_id}/approve", _body(payload), headers
        )

    # ----- aerial surveys -----
    def create_aerial_survey(self, payload, headers):
        return self._request("POST", "/aerial-surveys", payload, headers)

    def get_aerial_survey(self, survey_id, headers):
        return self._request("GET", f"/aerial-surveys/{survey_id}", headers=headers)

    def list_aerial_surveys(self, headers, params=None):
        return self._request("GET", "/aerial-surveys", headers=headers, params=params)

    def void_aerial_survey(self, survey_id, payload, headers):
        return self._request(
            "POST", f"/aerial-surveys/{survey_id}/void", _body(payload), headers
        )

    # ----- operating days -----
    def create_operating_day(self, payload, headers):
        return self._request("POST", "/operating-days", payload, headers)

    def get_operating_day(self, day_id, headers):
        return self._request("GET", f"/operating-days/{day_id}", headers=headers)

    def list_operating_days(self, headers, params=None):
        return self._request("GET", "/operating-days", headers=headers, params=params)

    def close_operating_day(self, day_id, headers, payload=None):
        return self._request(
            "POST", f"/operating-days/{day_id}/close", _body(payload), headers
        )

    def amend_operating_day(self, day_id, payload, headers):
        return self._request(
            "POST", f"/operating-days/{day_id}/amend", _body(payload), headers
        )

    def list_operating_day_waste_loads(self, day_id, headers, params=None):
        return self._request(
            "GET", f"/operating-days/{day_id}/waste-loads", headers=headers, params=params
        )

    # ----- waste loads -----
    def create_waste_load(self, payload, headers):
        return self._request("POST", "/waste-loads", payload, headers)

    def get_waste_load(self, load_id, headers):
        return self._request("GET", f"/waste-loads/{load_id}", headers=headers)

    def list_waste_loads(self, headers, params=None):
        return self._request("GET", "/waste-loads", headers=headers, params=params)

    def clear_screening(self, load_id, payload, headers):
        return self._request(
            "POST", f"/waste-loads/{load_id}/clear-screening", _body(payload), headers
        )

    def flag_waste_load(self, load_id, payload, headers):
        return self._request(
            "POST", f"/waste-loads/{load_id}/flag", _body(payload), headers
        )

    def reject_waste_load(self, load_id, payload, headers):
        return self._request(
            "POST", f"/waste-loads/{load_id}/reject", _body(payload), headers
        )

    def certify_weight(self, load_id, payload, headers):
        return self._request(
            "POST", f"/waste-loads/{load_id}/certify-weight", _body(payload), headers
        )

    # ----- special-waste approvals -----
    def create_special_waste_approval(self, payload, headers):
        return self._request("POST", "/special-waste-approvals", payload, headers)

    def get_special_waste_approval(self, approval_id, headers):
        return self._request(
            "GET", f"/special-waste-approvals/{approval_id}", headers=headers
        )

    def list_special_waste_approvals(self, headers, params=None):
        return self._request(
            "GET", "/special-waste-approvals", headers=headers, params=params
        )

    def approve_special_waste_approval(self, approval_id, payload, headers):
        return self._request(
            "POST", f"/special-waste-approvals/{approval_id}/approve", _body(payload), headers
        )

    def deny_special_waste_approval(self, approval_id, payload, headers):
        return self._request(
            "POST", f"/special-waste-approvals/{approval_id}/deny", _body(payload), headers
        )

    def revoke_special_waste_approval(self, approval_id, payload, headers):
        return self._request(
            "POST", f"/special-waste-approvals/{approval_id}/revoke", _body(payload), headers
        )

    # ----- treatment agreements -----
    def create_treatment_agreement(self, payload, headers):
        return self._request("POST", "/treatment-agreements", payload, headers)

    def get_treatment_agreement(self, agreement_id, headers):
        return self._request("GET", f"/treatment-agreements/{agreement_id}", headers=headers)

    def list_treatment_agreements(self, headers, params=None):
        return self._request("GET", "/treatment-agreements", headers=headers, params=params)

    def suspend_treatment_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/treatment-agreements/{agreement_id}/suspend", _body(payload), headers
        )

    def reinstate_treatment_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/treatment-agreements/{agreement_id}/reinstate", _body(payload), headers
        )

    def list_agreement_leachate_shipments(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/treatment-agreements/{agreement_id}/leachate-shipments",
            headers=headers,
            params=params,
        )

    # ----- leachate shipments -----
    def create_leachate_shipment(self, payload, headers):
        return self._request("POST", "/leachate-shipments", payload, headers)

    def get_leachate_shipment(self, shipment_id, headers):
        return self._request("GET", f"/leachate-shipments/{shipment_id}", headers=headers)

    def list_leachate_shipments(self, headers, params=None):
        return self._request("GET", "/leachate-shipments", headers=headers, params=params)

    def dispatch_leachate_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/leachate-shipments/{shipment_id}/dispatch", _body(payload), headers
        )

    def confirm_leachate_acceptance(self, shipment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/leachate-shipments/{shipment_id}/confirm-acceptance",
            _body(payload),
            headers,
        )

    def reject_leachate_at_gate(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/leachate-shipments/{shipment_id}/reject-at-gate", _body(payload), headers
        )

    def cancel_leachate_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/leachate-shipments/{shipment_id}/cancel", _body(payload), headers
        )

    # ----- gas wells -----
    def create_gas_well(self, payload, headers):
        return self._request("POST", "/gas-wells", payload, headers)

    def get_gas_well(self, well_id, headers):
        return self._request("GET", f"/gas-wells/{well_id}", headers=headers)

    def list_gas_wells(self, headers, params=None):
        return self._request("GET", "/gas-wells", headers=headers, params=params)

    def connect_gas_well(self, well_id, headers, payload=None):
        return self._request(
            "POST", f"/gas-wells/{well_id}/connect", _body(payload), headers
        )

    def tune_gas_well(self, well_id, payload, headers):
        return self._request("POST", f"/gas-wells/{well_id}/tune", _body(payload), headers)

    def take_gas_well_offline(self, well_id, payload, headers):
        return self._request(
            "POST", f"/gas-wells/{well_id}/take-offline", _body(payload), headers
        )

    def abandon_gas_well(self, well_id, payload, headers):
        return self._request(
            "POST", f"/gas-wells/{well_id}/abandon", _body(payload), headers
        )

    # ----- surface-emission scans -----
    def create_surface_emission_scan(self, payload, headers):
        return self._request("POST", "/surface-emission-scans", payload, headers)

    def get_surface_emission_scan(self, scan_id, headers):
        return self._request("GET", f"/surface-emission-scans/{scan_id}", headers=headers)

    def list_surface_emission_scans(self, headers, params=None):
        return self._request("GET", "/surface-emission-scans", headers=headers, params=params)

    def resolve_surface_emission_scan(self, scan_id, payload, headers):
        return self._request(
            "POST", f"/surface-emission-scans/{scan_id}/resolve", _body(payload), headers
        )

    # ----- closure cost estimates -----
    def create_closure_cost_estimate(self, payload, headers):
        return self._request("POST", "/closure-cost-estimates", payload, headers)

    def get_closure_cost_estimate(self, estimate_id, headers):
        return self._request("GET", f"/closure-cost-estimates/{estimate_id}", headers=headers)

    def list_closure_cost_estimates(self, headers, params=None):
        return self._request("GET", "/closure-cost-estimates", headers=headers, params=params)

    def certify_closure_cost_estimate(self, estimate_id, headers, payload=None):
        return self._request(
            "POST", f"/closure-cost-estimates/{estimate_id}/certify", _body(payload), headers
        )

    def fund_assurance(self, estimate_id, payload, headers):
        return self._request(
            "POST",
            f"/closure-cost-estimates/{estimate_id}/fund-assurance",
            _body(payload),
            headers,
        )

    # ----- host community agreements -----
    def create_host_community_agreement(self, payload, headers):
        return self._request("POST", "/host-community-agreements", payload, headers)

    def get_host_community_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/host-community-agreements/{agreement_id}", headers=headers
        )

    def list_host_community_agreements(self, headers, params=None):
        return self._request(
            "GET", "/host-community-agreements", headers=headers, params=params
        )

    def execute_host_community_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/host-community-agreements/{agreement_id}/execute", _body(payload), headers
        )

    def open_host_agreement_amendment(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/host-community-agreements/{agreement_id}/open-amendment",
            _body(payload),
            headers,
        )

    def execute_host_agreement_amendment(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/host-community-agreements/{agreement_id}/execute-amendment",
            _body(payload),
            headers,
        )

    def terminate_host_community_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/host-community-agreements/{agreement_id}/terminate",
            _body(payload),
            headers,
        )


api_client = ApiClient()
