"""API client: one method per endpoint defined in the Ambulance EMS Billing PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Agency ----
    def create_agency(self, payload, headers=None):
        return self._request("POST", "/agencies", payload, headers=headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/agencies/{agency_id}", headers=headers)

    def list_agency_staff(self, agency_id, headers, params=None):
        return self._request("GET", f"/agencies/{agency_id}/staff", headers=headers, params=params)

    def list_agency_vehicles(self, agency_id, headers, params=None):
        return self._request("GET", f"/agencies/{agency_id}/vehicles", headers=headers, params=params)

    def list_agency_crew_members(self, agency_id, headers, params=None):
        return self._request("GET", f"/agencies/{agency_id}/crew-members", headers=headers, params=params)

    # ---- AgencyStaff ----
    def create_staff(self, payload, headers):
        return self._request("POST", "/staff", payload, headers=headers)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/staff/{staff_id}", headers=headers)

    # ---- PayerPlan ----
    def create_payer_plan(self, payload, headers=None):
        return self._request("POST", "/payer-plans", payload, headers=headers)

    def get_payer_plan(self, plan_id, headers):
        return self._request("GET", f"/payer-plans/{plan_id}", headers=headers)

    def deactivate_payer_plan(self, plan_id, headers):
        return self._request("POST", f"/payer-plans/{plan_id}/deactivate", {}, headers=headers)

    # ---- Patient ----
    def create_patient(self, payload, headers=None):
        return self._request("POST", "/patients", payload, headers=headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    # ---- Vehicle ----
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers=headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def vehicle_out_of_service(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/out-of-service", {}, headers=headers)

    # ---- CrewMember ----
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/crew-members", payload, headers=headers)

    def get_crew_member(self, crew_id, headers):
        return self._request("GET", f"/crew-members/{crew_id}", headers=headers)

    # ---- UnitAssignment ----
    def create_unit_assignment(self, payload, headers):
        return self._request("POST", "/unit-assignments", payload, headers=headers)

    def get_unit_assignment(self, ua_id, headers):
        return self._request("GET", f"/unit-assignments/{ua_id}", headers=headers)

    def list_transport_unit_assignments(self, transport_id, headers, params=None):
        return self._request("GET", f"/transports/{transport_id}/unit-assignments", headers=headers, params=params)

    def list_unit_assignments(self, headers, params=None):
        return self._request("GET", "/unit-assignments", headers=headers, params=params)

    # ---- Transport ----
    def create_transport(self, payload, headers):
        return self._request("POST", "/transports", payload, headers=headers)

    def get_transport(self, transport_id, headers):
        return self._request("GET", f"/transports/{transport_id}", headers=headers)

    def list_transports(self, headers, params=None):
        return self._request("GET", "/transports", headers=headers, params=params)

    def code_transport(self, transport_id, payload, headers):
        return self._request("POST", f"/transports/{transport_id}/code", payload, headers=headers)

    def attest_necessity(self, transport_id, headers, payload=None):
        return self._request("POST", f"/transports/{transport_id}/attest-necessity", payload or {}, headers=headers)

    def sign_pcs(self, transport_id, headers, payload=None):
        return self._request("POST", f"/transports/{transport_id}/sign-pcs", payload or {}, headers=headers)

    def return_documentation(self, transport_id, headers, payload=None):
        return self._request("POST", f"/transports/{transport_id}/return-documentation", payload or {}, headers=headers)

    def void_transport(self, transport_id, headers, payload=None):
        return self._request("POST", f"/transports/{transport_id}/void", payload or {}, headers=headers)

    def list_transport_charges(self, transport_id, headers, params=None):
        return self._request("GET", f"/transports/{transport_id}/charges", headers=headers, params=params)

    # ---- Claim ----
    def create_claim(self, transport_id, payload, headers):
        return self._request("POST", f"/transports/{transport_id}/claims", payload, headers=headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_transport_claims(self, transport_id, headers, params=None):
        return self._request("GET", f"/transports/{transport_id}/claims", headers=headers, params=params)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def appeal_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/appeal", payload or {}, headers=headers)

    def resubmit_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/resubmit", payload or {}, headers=headers)

    # ---- RemittanceLine ----
    def create_remittance(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/remittances", payload, headers=headers)

    def list_remittances(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/remittances", headers=headers, params=params)

    # ---- Payment ----
    def create_payment(self, transport_id, payload, headers):
        return self._request("POST", f"/transports/{transport_id}/payments", payload, headers=headers)

    def list_transport_payments(self, transport_id, headers, params=None):
        return self._request("GET", f"/transports/{transport_id}/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    # ---- Adjustment ----
    def create_adjustment(self, transport_id, payload, headers):
        return self._request("POST", f"/transports/{transport_id}/adjustments", payload, headers=headers)

    def list_adjustments(self, transport_id, headers, params=None):
        return self._request("GET", f"/transports/{transport_id}/adjustments", headers=headers, params=params)


api_client = ApiClient()
