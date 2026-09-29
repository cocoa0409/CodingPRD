"""API client: one method per endpoint defined in the PRD (§4).

All paths are absolute.  The logical clock capability sits outside the
`/public-art` mount.
"""

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/public-art"


class ApiClient(GenericApiClient):
    # ---------------- artists ----------------
    def create_artist(self, payload, headers):
        return self._request("POST", f"{BASE}/artists", payload, headers)

    def get_artist(self, artist_id, headers):
        return self._request("GET", f"{BASE}/artists/{artist_id}", headers=headers)

    def list_artists(self, headers, params=None):
        return self._request("GET", f"{BASE}/artists", headers=headers, params=params)

    # ---------------- sites ----------------
    def create_site(self, payload, headers):
        return self._request("POST", f"{BASE}/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"{BASE}/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", f"{BASE}/sites", headers=headers, params=params)

    # ---------------- artworks ----------------
    def create_artwork(self, payload, headers):
        return self._request("POST", f"{BASE}/artworks", payload, headers)

    def get_artwork(self, artwork_id, headers):
        return self._request("GET", f"{BASE}/artworks/{artwork_id}", headers=headers)

    def list_artworks(self, headers, params=None):
        return self._request("GET", f"{BASE}/artworks", headers=headers, params=params)

    def relocate_artwork(self, artwork_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/artworks/{artwork_id}/relocate", payload, headers
        )

    # ---------------- maintenance protocols ----------------
    def create_maintenance_protocol(self, payload, headers):
        return self._request("POST", f"{BASE}/maintenance-protocols", payload, headers)

    def get_maintenance_protocol(self, protocol_id, headers):
        return self._request(
            "GET", f"{BASE}/maintenance-protocols/{protocol_id}", headers=headers
        )

    def list_maintenance_protocols(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/maintenance-protocols", headers=headers, params=params
        )

    # ---------------- conservators ----------------
    def create_conservator(self, payload, headers):
        return self._request("POST", f"{BASE}/conservators", payload, headers)

    def get_conservator(self, conservator_id, headers):
        return self._request(
            "GET", f"{BASE}/conservators/{conservator_id}", headers=headers
        )

    def list_conservators(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/conservators", headers=headers, params=params
        )

    def suspend_conservator(self, conservator_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/conservators/{conservator_id}/suspend", payload, headers
        )

    # ---------------- condition assessments ----------------
    def create_condition_assessment(self, payload, headers):
        return self._request("POST", f"{BASE}/condition-assessments", payload, headers)

    def get_condition_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"{BASE}/condition-assessments/{assessment_id}", headers=headers
        )

    def list_condition_assessments(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/condition-assessments", headers=headers, params=params
        )

    def add_assessment_photo(self, assessment_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/condition-assessments/{assessment_id}/photos",
            payload,
            headers,
        )

    def submit_condition_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/condition-assessments/{assessment_id}/submit",
            payload,
            headers,
        )

    def request_assessment_revision(self, assessment_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/condition-assessments/{assessment_id}/request-revision",
            payload,
            headers,
        )

    def finalize_condition_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/condition-assessments/{assessment_id}/finalize",
            payload,
            headers,
        )

    # ---------------- maintenance visits ----------------
    def create_maintenance_visit(self, payload, headers):
        return self._request("POST", f"{BASE}/maintenance-visits", payload, headers)

    def get_maintenance_visit(self, visit_id, headers):
        return self._request(
            "GET", f"{BASE}/maintenance-visits/{visit_id}", headers=headers
        )

    def list_maintenance_visits(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/maintenance-visits", headers=headers, params=params
        )

    def start_maintenance_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/maintenance-visits/{visit_id}/start", payload, headers
        )

    def complete_maintenance_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/maintenance-visits/{visit_id}/complete", payload, headers
        )

    # ---------------- treatment proposals ----------------
    def create_treatment_proposal(self, payload, headers):
        return self._request("POST", f"{BASE}/treatment-proposals", payload, headers)

    def get_treatment_proposal(self, proposal_id, headers):
        return self._request(
            "GET", f"{BASE}/treatment-proposals/{proposal_id}", headers=headers
        )

    def list_treatment_proposals(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/treatment-proposals", headers=headers, params=params
        )

    def add_proposal_line_item(self, proposal_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/treatment-proposals/{proposal_id}/line-items",
            payload,
            headers,
        )

    def submit_treatment_proposal(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/treatment-proposals/{proposal_id}/submit", payload, headers
        )

    def request_proposal_revision(self, proposal_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/treatment-proposals/{proposal_id}/request-revision",
            payload,
            headers,
        )

    def approve_treatment_proposal(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/treatment-proposals/{proposal_id}/approve", payload, headers
        )

    def reject_treatment_proposal(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/treatment-proposals/{proposal_id}/reject", payload, headers
        )

    def start_treatment_execution(self, proposal_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/treatment-proposals/{proposal_id}/start-execution",
            payload,
            headers,
        )

    def complete_treatment_proposal(self, proposal_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/treatment-proposals/{proposal_id}/complete",
            payload,
            headers,
        )

    # ---------------- artist consultations ----------------
    def create_artist_consultation(self, payload, headers):
        return self._request("POST", f"{BASE}/artist-consultations", payload, headers)

    def get_artist_consultation(self, consultation_id, headers):
        return self._request(
            "GET", f"{BASE}/artist-consultations/{consultation_id}", headers=headers
        )

    def list_artist_consultations(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/artist-consultations", headers=headers, params=params
        )

    def respond_to_consultation(self, consultation_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/artist-consultations/{consultation_id}/respond",
            payload,
            headers,
        )

    # ---------------- moral-rights notices ----------------
    def create_moral_rights_notice(self, payload, headers):
        return self._request("POST", f"{BASE}/moral-rights-notices", payload, headers)

    def get_moral_rights_notice(self, notice_id, headers):
        return self._request(
            "GET", f"{BASE}/moral-rights-notices/{notice_id}", headers=headers
        )

    def list_moral_rights_notices(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/moral-rights-notices", headers=headers, params=params
        )

    def acknowledge_moral_rights_notice(self, notice_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/moral-rights-notices/{notice_id}/acknowledge",
            payload,
            headers,
        )

    # ---------------- deaccession cases ----------------
    def create_deaccession_case(self, payload, headers):
        return self._request("POST", f"{BASE}/deaccession-cases", payload, headers)

    def get_deaccession_case(self, case_id, headers):
        return self._request(
            "GET", f"{BASE}/deaccession-cases/{case_id}", headers=headers
        )

    def list_deaccession_cases(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/deaccession-cases", headers=headers, params=params
        )

    def advance_deaccession_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/deaccession-cases/{case_id}/advance", payload, headers
        )

    def cast_deaccession_ballot(self, case_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/deaccession-cases/{case_id}/votes", payload, headers
        )

    def execute_deaccession_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/deaccession-cases/{case_id}/execute", payload, headers
        )

    # ---------------- funding pools ----------------
    def create_funding_pool(self, payload, headers):
        return self._request("POST", f"{BASE}/funding-pools", payload, headers)

    def get_funding_pool(self, pool_id, headers):
        return self._request("GET", f"{BASE}/funding-pools/{pool_id}", headers=headers)

    def list_funding_pools(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/funding-pools", headers=headers, params=params
        )

    # ---------------- funding allocations ----------------
    def create_funding_allocation(self, payload, headers):
        return self._request("POST", f"{BASE}/funding-allocations", payload, headers)

    def get_funding_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"{BASE}/funding-allocations/{allocation_id}", headers=headers
        )

    def list_funding_allocations(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/funding-allocations", headers=headers, params=params
        )

    def release_funding_allocation(self, allocation_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/funding-allocations/{allocation_id}/release",
            payload,
            headers,
        )

    # ---------------- damage incidents ----------------
    def create_damage_incident(self, payload, headers):
        return self._request("POST", f"{BASE}/damage-incidents", payload, headers)

    def get_damage_incident(self, incident_id, headers):
        return self._request(
            "GET", f"{BASE}/damage-incidents/{incident_id}", headers=headers
        )

    def list_damage_incidents(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/damage-incidents", headers=headers, params=params
        )

    def triage_damage_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/damage-incidents/{incident_id}/triage", payload, headers
        )

    def file_insurance_claim(self, incident_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/damage-incidents/{incident_id}/file-claim", payload, headers
        )

    def resolve_insurance_claim(self, incident_id, payload, headers):
        return self._request(
            "POST",
            f"{BASE}/damage-incidents/{incident_id}/resolve-claim",
            payload,
            headers,
        )

    # ---------------- operations ----------------
    def run_cycle(self, payload, headers):
        return self._request("POST", f"{BASE}/ops/run-cycle", payload, headers)

    def set_current_utc(self, payload, headers):
        """The clock capability sits outside the /public-art mount."""
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
