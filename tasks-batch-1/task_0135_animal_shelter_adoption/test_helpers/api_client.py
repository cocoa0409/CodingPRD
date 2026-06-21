"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Shelter ----
    def create_shelter(self, payload, headers):
        return self._request("POST", "/shelters", payload, headers)

    def get_shelter(self, shelter_id, headers):
        return self._request("GET", f"/shelters/{shelter_id}", headers=headers)

    def update_shelter(self, shelter_id, payload, headers):
        return self._request("PATCH", f"/shelters/{shelter_id}", payload, headers)

    # ---- Kennel ----
    def create_kennel(self, payload, headers):
        return self._request("POST", "/kennels", payload, headers)

    def get_kennel(self, kennel_id, headers):
        return self._request("GET", f"/kennels/{kennel_id}", headers=headers)

    def list_kennels(self, headers, params=None):
        return self._request("GET", "/kennels", headers=headers, params=params)

    # ---- Animal ----
    def create_animal(self, payload, headers):
        return self._request("POST", "/animals", payload, headers)

    def get_animal(self, animal_id, headers):
        return self._request("GET", f"/animals/{animal_id}", headers=headers)

    def list_animals(self, headers, params=None):
        return self._request("GET", "/animals", headers=headers, params=params)

    def make_available(self, animal_id, headers):
        return self._request("POST", f"/animals/{animal_id}/make-available", {}, headers)

    # ---- IntakeRecord ----
    def create_intake_record(self, payload, headers):
        return self._request("POST", "/intake-records", payload, headers)

    def get_intake_record(self, intake_id, headers):
        return self._request("GET", f"/intake-records/{intake_id}", headers=headers)

    def list_intake_records(self, headers, params=None):
        return self._request("GET", "/intake-records", headers=headers, params=params)

    # ---- KennelAssignment ----
    def create_kennel_assignment(self, payload, headers):
        return self._request("POST", "/kennel-assignments", payload, headers)

    def get_kennel_assignment(self, ka_id, headers):
        return self._request("GET", f"/kennel-assignments/{ka_id}", headers=headers)

    def list_kennel_assignments(self, headers, params=None):
        return self._request("GET", "/kennel-assignments", headers=headers, params=params)

    def get_projected_board(self, ka_id, headers):
        return self._request("GET", f"/kennel-assignments/{ka_id}/projected-board", headers=headers)

    def release_kennel_assignment(self, ka_id, headers):
        return self._request("POST", f"/kennel-assignments/{ka_id}/release", {}, headers)

    # ---- MedicalRecord ----
    def create_medical_record(self, payload, headers):
        return self._request("POST", "/medical-records", payload, headers)

    def get_medical_record(self, record_id, headers):
        return self._request("GET", f"/medical-records/{record_id}", headers=headers)

    def list_medical_records(self, headers, params=None):
        return self._request("GET", "/medical-records", headers=headers, params=params)

    # ---- Microchip ----
    def create_microchip(self, payload, headers):
        return self._request("POST", "/microchips", payload, headers)

    def get_microchip(self, chip_id, headers):
        return self._request("GET", f"/microchips/{chip_id}", headers=headers)

    def list_microchips(self, headers, params=None):
        return self._request("GET", "/microchips", headers=headers, params=params)

    # ---- OwnerClaim ----
    def create_owner_claim(self, payload, headers):
        return self._request("POST", "/owner-claims", payload, headers)

    def get_owner_claim(self, claim_id, headers):
        return self._request("GET", f"/owner-claims/{claim_id}", headers=headers)

    def list_owner_claims(self, headers, params=None):
        return self._request("GET", "/owner-claims", headers=headers, params=params)

    def approve_owner_claim(self, claim_id, headers):
        return self._request("POST", f"/owner-claims/{claim_id}/approve", {}, headers)

    def deny_owner_claim(self, claim_id, headers):
        return self._request("POST", f"/owner-claims/{claim_id}/deny", {}, headers)

    # ---- AdopterAccount ----
    def create_adopter_account(self, payload, headers):
        return self._request("POST", "/adopter-accounts", payload, headers)

    def get_adopter_account(self, adopter_id, headers):
        return self._request("GET", f"/adopter-accounts/{adopter_id}", headers=headers)

    # ---- AdoptionApplication ----
    def create_adoption_application(self, payload, headers):
        return self._request("POST", "/adoption-applications", payload, headers)

    def get_adoption_application(self, app_id, headers):
        return self._request("GET", f"/adoption-applications/{app_id}", headers=headers)

    def list_adoption_applications(self, headers, params=None):
        return self._request("GET", "/adoption-applications", headers=headers, params=params)

    def approve_adoption_application(self, app_id, headers):
        return self._request("POST", f"/adoption-applications/{app_id}/approve", {}, headers)

    def reject_adoption_application(self, app_id, headers):
        return self._request("POST", f"/adoption-applications/{app_id}/reject", {}, headers)

    def finalize_adoption_application(self, app_id, headers):
        return self._request("POST", f"/adoption-applications/{app_id}/finalize", {}, headers)

    def refund_adoption_application(self, app_id, headers):
        return self._request("POST", f"/adoption-applications/{app_id}/refund", {}, headers)

    # ---- FosterHome ----
    def create_foster_home(self, payload, headers):
        return self._request("POST", "/foster-homes", payload, headers)

    def get_foster_home(self, home_id, headers):
        return self._request("GET", f"/foster-homes/{home_id}", headers=headers)

    def list_foster_homes(self, headers, params=None):
        return self._request("GET", "/foster-homes", headers=headers, params=params)

    # ---- FosterPlacement ----
    def create_foster_placement(self, payload, headers):
        return self._request("POST", "/foster-placements", payload, headers)

    def get_foster_placement(self, placement_id, headers):
        return self._request("GET", f"/foster-placements/{placement_id}", headers=headers)

    def list_foster_placements(self, headers, params=None):
        return self._request("GET", "/foster-placements", headers=headers, params=params)

    def return_foster_placement(self, placement_id, headers):
        return self._request("POST", f"/foster-placements/{placement_id}/return", {}, headers)

    # ---- EuthanasiaDecision ----
    def create_euthanasia_decision(self, payload, headers):
        return self._request("POST", "/euthanasia-decisions", payload, headers)

    def get_euthanasia_decision(self, dec_id, headers):
        return self._request("GET", f"/euthanasia-decisions/{dec_id}", headers=headers)

    def list_euthanasia_decisions(self, headers, params=None):
        return self._request("GET", "/euthanasia-decisions", headers=headers, params=params)

    def approve_euthanasia_decision(self, dec_id, headers):
        return self._request("POST", f"/euthanasia-decisions/{dec_id}/approve", {}, headers)

    def reject_euthanasia_decision(self, dec_id, headers):
        return self._request("POST", f"/euthanasia-decisions/{dec_id}/reject", {}, headers)

    def execute_euthanasia_decision(self, dec_id, headers):
        return self._request("POST", f"/euthanasia-decisions/{dec_id}/execute", {}, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    # ---- Raw list helper for pagination-error tests ----
    def list_animals_raw(self, headers, query_string):
        """GET /animals with a raw query string (e.g. 'limit=500') for limit-bound tests."""
        return self._request("GET", f"/animals?{query_string}", headers=headers)


api_client = ApiClient()
