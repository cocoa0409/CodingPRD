"""API client: one method per endpoint defined in the PRD.

Every collection is a peer directly beneath /floodplain; there are no nested
resource paths.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/floodplain"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Communities
    # ------------------------------------------------------------------
    def create_community(self, payload, headers):
        return self._request("POST", f"{PREFIX}/communities", payload, headers)

    def get_community(self, community_id, headers):
        return self._request("GET", f"{PREFIX}/communities/{community_id}", headers=headers)

    def amend_community_standards(self, community_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/communities/{community_id}", payload, headers)

    def get_compliance_summary(self, community_id, headers):
        return self._request(
            "GET", f"{PREFIX}/communities/{community_id}/compliance-summary", headers=headers
        )

    def open_inspection_sweep(self, community_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/communities/{community_id}/inspection-sweep", payload, headers
        )

    # ------------------------------------------------------------------
    # FIRM panels
    # ------------------------------------------------------------------
    def file_firm_panel(self, payload, headers):
        return self._request("POST", f"{PREFIX}/firm-panels", payload, headers)

    def get_firm_panel(self, panel_id, headers):
        return self._request("GET", f"{PREFIX}/firm-panels/{panel_id}", headers=headers)

    def list_firm_panels(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/firm-panels", headers=headers, params=params)

    def activate_firm_panel(self, panel_id, headers):
        return self._request("POST", f"{PREFIX}/firm-panels/{panel_id}/activate", None, headers)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    def create_property(self, payload, headers):
        return self._request("POST", f"{PREFIX}/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"{PREFIX}/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/properties", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Structures
    # ------------------------------------------------------------------
    def create_structure(self, payload, headers):
        return self._request("POST", f"{PREFIX}/structures", payload, headers)

    def get_structure(self, structure_id, headers):
        return self._request("GET", f"{PREFIX}/structures/{structure_id}", headers=headers)

    def list_structures(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/structures", headers=headers, params=params)

    def correct_structure_market_value(self, structure_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/structures/{structure_id}", payload, headers)

    def get_improvement_summary(self, structure_id, headers):
        return self._request(
            "GET", f"{PREFIX}/structures/{structure_id}/improvement-summary", headers=headers
        )

    # ------------------------------------------------------------------
    # Development permits
    # ------------------------------------------------------------------
    def create_permit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"{PREFIX}/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/permits", headers=headers, params=params)

    def submit_permit(self, permit_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/permits/{permit_id}/submit", payload, headers)

    def review_permit(self, permit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/permits/{permit_id}/review", payload, headers)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"{PREFIX}/permits/{permit_id}/issue", None, headers)

    def close_permit(self, permit_id, headers):
        return self._request("POST", f"{PREFIX}/permits/{permit_id}/close", None, headers)

    # ------------------------------------------------------------------
    # Elevation certificates
    # ------------------------------------------------------------------
    def file_certificate(self, payload, headers):
        return self._request("POST", f"{PREFIX}/elevation-certificates", payload, headers)

    def get_certificate(self, certificate_id, headers):
        return self._request(
            "GET", f"{PREFIX}/elevation-certificates/{certificate_id}", headers=headers
        )

    def list_certificates(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/elevation-certificates", headers=headers, params=params
        )

    def review_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/elevation-certificates/{certificate_id}/review", payload, headers
        )

    def amend_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/elevation-certificates/{certificate_id}/amend", payload, headers
        )

    # ------------------------------------------------------------------
    # Improvement ledger
    # ------------------------------------------------------------------
    def append_improvement_record(self, payload, headers):
        return self._request("POST", f"{PREFIX}/improvement-records", payload, headers)

    def get_improvement_record(self, record_id, headers):
        return self._request(
            "GET", f"{PREFIX}/improvement-records/{record_id}", headers=headers
        )

    def list_improvement_records(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/improvement-records", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Determination cases
    # ------------------------------------------------------------------
    def open_determination_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/determination-cases", payload, headers)

    def get_determination_case(self, case_id, headers):
        return self._request("GET", f"{PREFIX}/determination-cases/{case_id}", headers=headers)

    def list_determination_cases(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/determination-cases", headers=headers, params=params
        )

    def determine_case(self, case_id, headers):
        return self._request(
            "POST", f"{PREFIX}/determination-cases/{case_id}/determine", None, headers
        )

    def appeal_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/determination-cases/{case_id}/appeal", payload, headers
        )

    def decide_appeal(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/determination-cases/{case_id}/appeal-decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Post-disaster inspections
    # ------------------------------------------------------------------
    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"{PREFIX}/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/inspections", headers=headers, params=params)

    def assess_inspection(self, inspection_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/assess", payload, headers
        )

    def finalize_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"{PREFIX}/inspections/{inspection_id}/finalize", None, headers
        )

    # ------------------------------------------------------------------
    # Enforcement
    # ------------------------------------------------------------------
    def create_violation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/violations", payload, headers)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"{PREFIX}/violations/{violation_id}", headers=headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/violations", headers=headers, params=params)

    def resolve_violation(self, violation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/violations/{violation_id}/resolve", payload, headers
        )

    def create_remediation_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/remediation-orders", payload, headers)

    def get_remediation_order(self, order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/remediation-orders/{order_id}", headers=headers
        )

    def list_remediation_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/remediation-orders", headers=headers, params=params
        )

    def extend_remediation_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/remediation-orders/{order_id}/extend", payload, headers
        )

    def resolve_remediation_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/remediation-orders/{order_id}/resolve", payload, headers
        )

    # ------------------------------------------------------------------
    # Repetitive loss areas
    # ------------------------------------------------------------------
    def create_loss_area(self, payload, headers):
        return self._request("POST", f"{PREFIX}/repetitive-loss-areas", payload, headers)

    def get_loss_area(self, area_id, headers):
        return self._request(
            "GET", f"{PREFIX}/repetitive-loss-areas/{area_id}", headers=headers
        )

    def list_loss_areas(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/repetitive-loss-areas", headers=headers, params=params
        )

    def analyze_loss_area(self, area_id, headers):
        return self._request(
            "POST", f"{PREFIX}/repetitive-loss-areas/{area_id}/analyze", None, headers
        )

    def designate_loss_area(self, area_id, headers):
        return self._request(
            "POST", f"{PREFIX}/repetitive-loss-areas/{area_id}/designate", None, headers
        )

    def launch_outreach(self, area_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/repetitive-loss-areas/{area_id}/outreach", payload, headers
        )

    def record_outreach_delivery(self, area_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/repetitive-loss-areas/{area_id}/record-outreach-delivery",
            payload,
            headers,
        )

    def complete_outreach(self, area_id, headers):
        return self._request(
            "POST", f"{PREFIX}/repetitive-loss-areas/{area_id}/complete-outreach", None, headers
        )

    # ------------------------------------------------------------------
    # Higher-standards submissions
    # ------------------------------------------------------------------
    def draft_higher_standard(self, payload, headers):
        return self._request("POST", f"{PREFIX}/higher-standards", payload, headers)

    def get_higher_standard(self, standard_id, headers):
        return self._request(
            "GET", f"{PREFIX}/higher-standards/{standard_id}", headers=headers
        )

    def list_higher_standards(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/higher-standards", headers=headers, params=params)

    def submit_higher_standard(self, standard_id, headers):
        return self._request(
            "POST", f"{PREFIX}/higher-standards/{standard_id}/submit", None, headers
        )

    def verify_higher_standard(self, standard_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/higher-standards/{standard_id}/verify", payload, headers
        )

    # ------------------------------------------------------------------
    # Recertification cycles
    # ------------------------------------------------------------------
    def create_crs_cycle(self, payload, headers):
        return self._request("POST", f"{PREFIX}/crs-cycles", payload, headers)

    def get_crs_cycle(self, cycle_id, headers):
        return self._request("GET", f"{PREFIX}/crs-cycles/{cycle_id}", headers=headers)

    def list_crs_cycles(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/crs-cycles", headers=headers, params=params)

    def submit_crs_cycle(self, cycle_id, headers):
        return self._request("POST", f"{PREFIX}/crs-cycles/{cycle_id}/submit", None, headers)

    def record_verification_visit(self, cycle_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/crs-cycles/{cycle_id}/verify-visit", payload, headers
        )

    def certify_crs_cycle(self, cycle_id, headers):
        return self._request("POST", f"{PREFIX}/crs-cycles/{cycle_id}/certify", None, headers)

    def lapse_crs_cycle(self, cycle_id, headers):
        return self._request("POST", f"{PREFIX}/crs-cycles/{cycle_id}/lapse", None, headers)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
