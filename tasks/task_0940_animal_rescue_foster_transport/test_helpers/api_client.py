"""API client: one method per endpoint. All routes are mounted under /rescue."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/rescue"


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------------- organizations ----------------
    def create_organization(self, payload, headers):
        return self._request("POST", f"{PREFIX}/organizations", payload, headers)

    def get_organization(self, organization_id, headers):
        return self._request("GET", f"{PREFIX}/organizations/{organization_id}", headers=headers)

    def set_records_freeze(self, organization_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/organizations/{organization_id}/records-freeze", payload, headers
        )

    # ---------------- persons ----------------
    def create_person(self, payload, headers):
        return self._request("POST", f"{PREFIX}/persons", payload, headers)

    def get_person(self, person_id, headers):
        return self._request("GET", f"{PREFIX}/persons/{person_id}", headers=headers)

    # ---------------- animals ----------------
    def create_animal(self, payload, headers):
        return self._request("POST", f"{PREFIX}/animals", payload, headers)

    def get_animal(self, animal_id, headers):
        return self._request("GET", f"{PREFIX}/animals/{animal_id}", headers=headers)

    def list_animals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/animals", headers=headers, params=params)

    def update_animal_restrictions(self, animal_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/animals/{animal_id}/restrictions", payload, headers
        )

    def record_identification(self, animal_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/animals/{animal_id}/identification", payload, headers
        )

    def get_animal_eligibility(self, animal_id, headers):
        return self._request("GET", f"{PREFIX}/animals/{animal_id}/eligibility", headers=headers)

    # ---------------- litters ----------------
    def create_litter(self, payload, headers):
        return self._request("POST", f"{PREFIX}/litters", payload, headers)

    def get_litter(self, litter_id, headers):
        return self._request("GET", f"{PREFIX}/litters/{litter_id}", headers=headers)

    def list_litters(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/litters", headers=headers, params=params)

    def approve_litter_split(self, litter_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/litters/{litter_id}/split-approval", payload, headers
        )

    # ---------------- intake records ----------------
    def create_intake_record(self, animal_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/animals/{animal_id}/intake-records", payload, headers
        )

    def get_intake_record(self, intake_record_id, headers):
        return self._request(
            "GET", f"{PREFIX}/intake-records/{intake_record_id}", headers=headers
        )

    def list_intake_records(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/intake-records", headers=headers, params=params)

    def reclaim(self, intake_record_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/intake-records/{intake_record_id}/reclaim", payload, headers
        )

    # ---------------- holds ----------------
    def create_hold(self, animal_id, payload, headers):
        return self._request("POST", f"{PREFIX}/animals/{animal_id}/holds", payload, headers)

    def get_hold(self, hold_id, headers):
        return self._request("GET", f"{PREFIX}/holds/{hold_id}", headers=headers)

    def list_holds(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/holds", headers=headers, params=params)

    def release_hold(self, hold_id, headers):
        return self._request("POST", f"{PREFIX}/holds/{hold_id}/release", {}, headers)

    # ---------------- foster homes ----------------
    def create_foster_home(self, payload, headers):
        return self._request("POST", f"{PREFIX}/foster-homes", payload, headers)

    def get_foster_home(self, foster_home_id, headers):
        return self._request("GET", f"{PREFIX}/foster-homes/{foster_home_id}", headers=headers)

    def list_foster_homes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/foster-homes", headers=headers, params=params)

    # ---------------- foster applications ----------------
    def create_foster_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/foster-applications", payload, headers)

    def get_foster_application(self, foster_application_id, headers):
        return self._request(
            "GET", f"{PREFIX}/foster-applications/{foster_application_id}", headers=headers
        )

    def list_foster_applications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/foster-applications", headers=headers, params=params
        )

    def decide_foster_application(self, foster_application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/foster-applications/{foster_application_id}/decision",
            payload, headers,
        )

    def record_home_check(self, foster_application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/foster-applications/{foster_application_id}/home-check",
            payload, headers,
        )

    def change_foster_application_status(self, foster_application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/foster-applications/{foster_application_id}/status-change",
            payload, headers,
        )

    # ---------------- foster placements ----------------
    def create_foster_placement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/foster-placements", payload, headers)

    def get_foster_placement(self, placement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/foster-placements/{placement_id}", headers=headers
        )

    def list_foster_placements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/foster-placements", headers=headers, params=params)

    def activate_foster_placement(self, placement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/foster-placements/{placement_id}/activate", {}, headers
        )

    def end_foster_placement(self, placement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/foster-placements/{placement_id}/end", payload, headers
        )

    def transfer_foster_placement(self, placement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/foster-placements/{placement_id}/transfer", payload, headers
        )

    # ---------------- medical records ----------------
    def create_medical_record(self, animal_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/animals/{animal_id}/medical-records", payload, headers
        )

    def get_medical_record(self, medical_record_id, headers):
        return self._request(
            "GET", f"{PREFIX}/medical-records/{medical_record_id}", headers=headers
        )

    def list_medical_records(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/medical-records", headers=headers, params=params)

    def complete_medical_record(self, medical_record_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/medical-records/{medical_record_id}/complete",
            payload if payload is not None else {}, headers,
        )

    # ---------------- health certificates ----------------
    def issue_health_certificate(self, animal_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/animals/{animal_id}/health-certificates", payload, headers
        )

    def get_health_certificate(self, certificate_id, headers):
        return self._request(
            "GET", f"{PREFIX}/health-certificates/{certificate_id}", headers=headers
        )

    def list_health_certificates(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/health-certificates", headers=headers, params=params
        )

    # ---------------- transport runs ----------------
    def create_transport_run(self, payload, headers):
        return self._request("POST", f"{PREFIX}/transport-runs", payload, headers)

    def get_transport_run(self, run_id, headers):
        return self._request("GET", f"{PREFIX}/transport-runs/{run_id}", headers=headers)

    def list_transport_runs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/transport-runs", headers=headers, params=params)

    def start_transport_run(self, run_id, headers):
        return self._request("POST", f"{PREFIX}/transport-runs/{run_id}/start", {}, headers)

    def abort_transport_run(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/transport-runs/{run_id}/abort",
            payload if payload is not None else {}, headers,
        )

    def create_transport_leg(self, run_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/transport-runs/{run_id}/transport-legs", payload, headers
        )

    # ---------------- transport legs ----------------
    def get_transport_leg(self, leg_id, headers):
        return self._request("GET", f"{PREFIX}/transport-legs/{leg_id}", headers=headers)

    def list_transport_legs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/transport-legs", headers=headers, params=params)

    def depart_transport_leg(self, leg_id, headers):
        return self._request("POST", f"{PREFIX}/transport-legs/{leg_id}/depart", {}, headers)

    def arrive_transport_leg(self, leg_id, headers):
        return self._request("POST", f"{PREFIX}/transport-legs/{leg_id}/arrive", {}, headers)

    def abort_transport_leg(self, leg_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/transport-legs/{leg_id}/abort",
            payload if payload is not None else {}, headers,
        )

    # ---------------- manifest entries ----------------
    def create_manifest_entry(self, leg_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/transport-legs/{leg_id}/manifest-entries", payload, headers
        )

    def get_manifest_entry(self, entry_id, headers):
        return self._request("GET", f"{PREFIX}/manifest-entries/{entry_id}", headers=headers)

    def list_manifest_entries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/manifest-entries", headers=headers, params=params)

    def bump_manifest_entry(self, entry_id, headers):
        return self._request("DELETE", f"{PREFIX}/manifest-entries/{entry_id}", headers=headers)

    # ---------------- adoption applications ----------------
    def create_adoption_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/adoption-applications", payload, headers)

    def get_adoption_application(self, application_id, headers):
        return self._request(
            "GET", f"{PREFIX}/adoption-applications/{application_id}", headers=headers
        )

    def list_adoption_applications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/adoption-applications", headers=headers, params=params
        )

    def screen_adoption_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/adoption-applications/{application_id}/screen", payload, headers
        )

    def resubmit_adoption_application(self, application_id, headers):
        return self._request(
            "POST", f"{PREFIX}/adoption-applications/{application_id}/resubmit", {}, headers
        )

    # ---------------- adoptions ----------------
    def create_adoption(self, payload, headers):
        return self._request("POST", f"{PREFIX}/adoptions", payload, headers)

    def get_adoption(self, adoption_id, headers):
        return self._request("GET", f"{PREFIX}/adoptions/{adoption_id}", headers=headers)

    def list_adoptions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/adoptions", headers=headers, params=params)

    def pay_adoption(self, adoption_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/adoptions/{adoption_id}/payment", payload, headers
        )

    def return_adoption(self, adoption_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/adoptions/{adoption_id}/return",
            payload if payload is not None else {}, headers,
        )

    def redeem_alteration_proof(self, adoption_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/adoptions/{adoption_id}/alteration-proof", payload, headers
        )

    # ---------------- outcomes ----------------
    def create_outcome(self, animal_id, payload, headers):
        return self._request("POST", f"{PREFIX}/animals/{animal_id}/outcomes", payload, headers)

    def get_outcome(self, outcome_id, headers):
        return self._request("GET", f"{PREFIX}/outcomes/{outcome_id}", headers=headers)

    def list_outcomes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/outcomes", headers=headers, params=params)

    def live_release_report(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/reports/live-release-rate", headers=headers, params=params
        )

    # ---------------- contributions ----------------
    def create_contribution(self, payload, headers):
        return self._request("POST", f"{PREFIX}/contributions", payload, headers)

    def get_contribution(self, contribution_id, headers):
        return self._request("GET", f"{PREFIX}/contributions/{contribution_id}", headers=headers)

    def list_contributions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/contributions", headers=headers, params=params)

    def redesignate_contribution(self, contribution_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contributions/{contribution_id}/redesignate", payload, headers
        )

    # ---------------- partner commitments ----------------
    def create_partner_commitment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/partner-commitments", payload, headers)

    def get_partner_commitment(self, commitment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/partner-commitments/{commitment_id}", headers=headers
        )

    def list_partner_commitments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/partner-commitments", headers=headers, params=params
        )

    def expire_sweep_partner_commitments(self, headers):
        return self._request("POST", f"{PREFIX}/partner-commitments/expire-sweep", {}, headers)

    # ---------------- raw escape hatch (path-level probes) ----------------
    def raw_get(self, path, headers, params=None):
        return self._request("GET", f"{PREFIX}{path}", headers=headers, params=params)


api_client = ApiClient()
