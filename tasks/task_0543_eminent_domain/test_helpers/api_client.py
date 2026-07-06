"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Project ----------------------------------------------------------
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_parcels(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/parcels",
                             headers=headers, params=params)

    # ---- Parcel -----------------------------------------------------------
    def create_parcel(self, payload, headers):
        return self._request("POST", "/parcels", payload, headers)

    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"/parcels/{parcel_id}", headers=headers)

    def clear_ownership(self, parcel_id, headers):
        return self._request("POST", f"/parcels/{parcel_id}/clear-ownership",
                             {}, headers)

    # ---- OwnershipInterest ------------------------------------------------
    def create_ownership_interest(self, parcel_id, payload, headers):
        return self._request("POST", f"/parcels/{parcel_id}/ownership-interests",
                             payload, headers)

    def list_ownership_interests(self, parcel_id, headers, params=None):
        return self._request("GET", f"/parcels/{parcel_id}/ownership-interests",
                             headers=headers, params=params)

    # ---- Appraisal --------------------------------------------------------
    def create_appraisal(self, parcel_id, payload, headers):
        return self._request("POST", f"/parcels/{parcel_id}/appraisals",
                             payload, headers)

    def get_appraisal(self, appraisal_id, headers):
        return self._request("GET", f"/appraisals/{appraisal_id}", headers=headers)

    def list_appraisals(self, parcel_id, headers, params=None):
        return self._request("GET", f"/parcels/{parcel_id}/appraisals",
                             headers=headers, params=params)

    def finalize_appraisal(self, appraisal_id, headers):
        return self._request("POST", f"/appraisals/{appraisal_id}/finalize",
                             {}, headers)

    # ---- InspectionAppointment --------------------------------------------
    def create_inspection_appointment(self, appraisal_id, payload, headers):
        return self._request("POST",
                             f"/appraisals/{appraisal_id}/inspection-appointments",
                             payload, headers)

    def list_inspection_appointments(self, appraisal_id, headers, params=None):
        return self._request("GET",
                             f"/appraisals/{appraisal_id}/inspection-appointments",
                             headers=headers, params=params)

    # ---- Negotiation ------------------------------------------------------
    def create_negotiation(self, parcel_id, payload, headers):
        return self._request("POST", f"/parcels/{parcel_id}/negotiations",
                             payload, headers)

    def get_negotiation(self, negotiation_id, headers):
        return self._request("GET", f"/negotiations/{negotiation_id}",
                             headers=headers)

    def list_negotiations(self, parcel_id, headers, params=None):
        return self._request("GET", f"/parcels/{parcel_id}/negotiations",
                             headers=headers, params=params)

    def create_round(self, negotiation_id, payload, headers):
        return self._request("POST", f"/negotiations/{negotiation_id}/rounds",
                             payload, headers)

    def list_rounds(self, negotiation_id, headers, params=None):
        return self._request("GET", f"/negotiations/{negotiation_id}/rounds",
                             headers=headers, params=params)

    # ---- Condemnation -----------------------------------------------------
    def create_condemnation(self, parcel_id, headers):
        return self._request("POST", f"/parcels/{parcel_id}/condemnations",
                             {}, headers)

    def get_condemnation(self, condemnation_id, headers):
        return self._request("GET", f"/condemnations/{condemnation_id}",
                             headers=headers)

    def list_condemnations(self, parcel_id, headers, params=None):
        return self._request("GET", f"/parcels/{parcel_id}/condemnations",
                             headers=headers, params=params)

    def deposit(self, condemnation_id, payload, headers):
        return self._request("POST", f"/condemnations/{condemnation_id}/deposit",
                             payload, headers)

    def grant_possession(self, condemnation_id, headers):
        return self._request("POST",
                             f"/condemnations/{condemnation_id}/grant-possession",
                             {}, headers)

    def award(self, condemnation_id, payload, headers):
        return self._request("POST", f"/condemnations/{condemnation_id}/award",
                             payload, headers)

    # ---- RelocationBenefit ------------------------------------------------
    def create_relocation_benefit(self, parcel_id, payload, headers):
        return self._request("POST", f"/parcels/{parcel_id}/relocation-benefits",
                             payload, headers)

    def get_relocation_benefit(self, benefit_id, headers):
        return self._request("GET", f"/relocation-benefits/{benefit_id}",
                             headers=headers)

    def list_relocation_benefits(self, parcel_id, headers, params=None):
        return self._request("GET", f"/parcels/{parcel_id}/relocation-benefits",
                             headers=headers, params=params)

    def approve_relocation_benefit(self, benefit_id, headers):
        return self._request("POST",
                             f"/relocation-benefits/{benefit_id}/approve",
                             {}, headers)

    def deny_relocation_benefit(self, benefit_id, payload, headers):
        return self._request("POST", f"/relocation-benefits/{benefit_id}/deny",
                             payload, headers)

    def pay_relocation_benefit(self, benefit_id, headers):
        return self._request("POST", f"/relocation-benefits/{benefit_id}/pay",
                             {}, headers)

    # ---- UtilityRelocation ------------------------------------------------
    def create_utility_relocation(self, parcel_id, payload, headers):
        return self._request("POST", f"/parcels/{parcel_id}/utility-relocations",
                             payload, headers)

    def get_utility_relocation(self, relocation_id, headers):
        return self._request("GET", f"/utility-relocations/{relocation_id}",
                             headers=headers)

    def list_utility_relocations(self, parcel_id, headers, params=None):
        return self._request("GET", f"/parcels/{parcel_id}/utility-relocations",
                             headers=headers, params=params)

    def schedule_utility(self, relocation_id, payload, headers):
        return self._request("POST",
                             f"/utility-relocations/{relocation_id}/schedule",
                             payload, headers)

    def complete_utility(self, relocation_id, headers):
        return self._request("POST",
                             f"/utility-relocations/{relocation_id}/complete",
                             {}, headers)

    # ---- Escrow -----------------------------------------------------------
    def create_escrow(self, parcel_id, payload, headers):
        return self._request("POST", f"/parcels/{parcel_id}/escrows",
                             payload, headers)

    def get_escrow(self, escrow_id, headers):
        return self._request("GET", f"/escrows/{escrow_id}", headers=headers)

    def list_escrows(self, parcel_id, headers, params=None):
        return self._request("GET", f"/parcels/{parcel_id}/escrows",
                             headers=headers, params=params)

    def fund_escrow(self, escrow_id, headers):
        return self._request("POST", f"/escrows/{escrow_id}/fund", {}, headers)

    def close_escrow(self, escrow_id, headers):
        return self._request("POST", f"/escrows/{escrow_id}/close", {}, headers)

    def rescind_escrow(self, escrow_id, headers):
        return self._request("POST", f"/escrows/{escrow_id}/rescind", {}, headers)


api_client = ApiClient()
