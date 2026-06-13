"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock (§2.10) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set", {"to_iso8601": to_iso8601}, headers)

    def advance_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/advance", {"to_iso8601": to_iso8601}, headers
        )

    def seed_kennel_licenses(self, payload, headers):
        return self._request("POST", "/_bulk/seed-kennel-licenses", payload, headers)

    # ---- Owner ----
    def create_owner(self, payload, headers):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    def list_owner_pets(self, owner_id, headers, params=None):
        return self._request(
            "GET", f"/owners/{owner_id}/pets", headers=headers, params=params
        )

    def list_owner_licenses(self, owner_id, headers, params=None):
        return self._request(
            "GET", f"/owners/{owner_id}/licenses", headers=headers, params=params
        )

    def list_owner_kennels(self, owner_id, headers, params=None):
        return self._request(
            "GET", f"/owners/{owner_id}/kennels", headers=headers, params=params
        )

    # ---- Pet ----
    def create_pet(self, payload, headers):
        return self._request("POST", "/pets", payload, headers)

    def get_pet(self, pet_id, headers):
        return self._request("GET", f"/pets/{pet_id}", headers=headers)

    def mark_pet_deceased(self, pet_id, headers):
        return self._request(
            "POST", f"/pets/{pet_id}/mark-deceased", headers=headers
        )

    def list_pet_vaccination_records(self, pet_id, headers, params=None):
        return self._request(
            "GET",
            f"/pets/{pet_id}/vaccination-records",
            headers=headers,
            params=params,
        )

    def list_pet_licenses(self, pet_id, headers, params=None):
        return self._request(
            "GET", f"/pets/{pet_id}/licenses", headers=headers, params=params
        )

    def list_pet_dangerous_dog_cases(self, pet_id, headers, params=None):
        return self._request(
            "GET",
            f"/pets/{pet_id}/dangerous-dog-cases",
            headers=headers,
            params=params,
        )

    def list_pet_lost_found_reports(self, pet_id, headers, params=None):
        return self._request(
            "GET",
            f"/pets/{pet_id}/lost-found-reports",
            headers=headers,
            params=params,
        )

    # ---- VaccinationRecord ----
    def create_vaccination_record(self, payload, headers):
        return self._request("POST", "/vaccination-records", payload, headers)

    def get_vaccination_record(self, record_id, headers):
        return self._request(
            "GET", f"/vaccination-records/{record_id}", headers=headers
        )

    # ---- Kennel ----
    def create_kennel(self, payload, headers):
        return self._request("POST", "/kennels", payload, headers)

    def get_kennel(self, kennel_id, headers):
        return self._request("GET", f"/kennels/{kennel_id}", headers=headers)

    def list_kennel_licenses(self, kennel_id, headers, params=None):
        return self._request(
            "GET", f"/kennels/{kennel_id}/licenses", headers=headers, params=params
        )

    def suspend_kennel(self, kennel_id, headers):
        return self._request(
            "POST", f"/kennels/{kennel_id}/suspend", headers=headers
        )

    # ---- License ----
    def create_license(self, payload, headers):
        return self._request("POST", "/licenses", payload, headers)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/licenses/{license_id}", headers=headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/licenses", headers=headers, params=params)

    def submit_license(self, license_id, headers):
        return self._request(
            "POST", f"/licenses/{license_id}/submit", headers=headers
        )

    def start_review_license(self, license_id, headers):
        return self._request(
            "POST", f"/licenses/{license_id}/start-review", headers=headers
        )

    def request_vaccination_proof(self, license_id, headers):
        return self._request(
            "POST",
            f"/licenses/{license_id}/request-vaccination-proof",
            headers=headers,
        )

    def attach_vaccination(self, license_id, payload, headers):
        return self._request(
            "POST", f"/licenses/{license_id}/attach-vaccination", payload, headers
        )

    def approve_license(self, license_id, headers):
        return self._request(
            "POST", f"/licenses/{license_id}/approve", headers=headers
        )

    def reject_license(self, license_id, headers):
        return self._request(
            "POST", f"/licenses/{license_id}/reject", headers=headers
        )

    def issue_tag(self, license_id, headers):
        return self._request(
            "POST", f"/licenses/{license_id}/issue-tag", headers=headers
        )

    def renew_license(self, license_id, headers, payload=None):
        return self._request(
            "POST", f"/licenses/{license_id}/renew", payload or {}, headers
        )

    def pay_penalty(self, license_id, payload, headers):
        return self._request(
            "POST", f"/licenses/{license_id}/pay-penalty", payload, headers
        )

    def revoke_license(self, license_id, headers):
        return self._request(
            "POST", f"/licenses/{license_id}/revoke", headers=headers
        )

    def list_license_tags(self, license_id, headers, params=None):
        return self._request(
            "GET", f"/licenses/{license_id}/tags", headers=headers, params=params
        )

    # ---- DangerousDogCase ----
    def create_dangerous_dog_case(self, payload, headers):
        return self._request("POST", "/dangerous-dog-cases", payload, headers)

    def get_dangerous_dog_case(self, case_id, headers):
        return self._request(
            "GET", f"/dangerous-dog-cases/{case_id}", headers=headers
        )

    def investigate_case(self, case_id, headers):
        return self._request(
            "POST", f"/dangerous-dog-cases/{case_id}/investigate", headers=headers
        )

    def designate_case(self, case_id, headers):
        return self._request(
            "POST", f"/dangerous-dog-cases/{case_id}/designate", headers=headers
        )

    def dismiss_case(self, case_id, headers):
        return self._request(
            "POST", f"/dangerous-dog-cases/{case_id}/dismiss", headers=headers
        )

    def appeal_case(self, case_id, headers):
        return self._request(
            "POST", f"/dangerous-dog-cases/{case_id}/appeal", headers=headers
        )

    def overturn_case(self, case_id, headers):
        return self._request(
            "POST", f"/dangerous-dog-cases/{case_id}/overturn", headers=headers
        )

    def uphold_case(self, case_id, headers):
        return self._request(
            "POST", f"/dangerous-dog-cases/{case_id}/uphold", headers=headers
        )

    # ---- LostFoundReport ----
    def create_lost_found_report(self, payload, headers):
        return self._request("POST", "/lost-found-reports", payload, headers)

    def get_lost_found_report(self, report_id, headers):
        return self._request(
            "GET", f"/lost-found-reports/{report_id}", headers=headers
        )

    def list_lost_found_reports(self, headers, params=None):
        return self._request(
            "GET", "/lost-found-reports", headers=headers, params=params
        )

    def match_report(self, report_id, headers):
        return self._request(
            "POST", f"/lost-found-reports/{report_id}/match", headers=headers
        )

    def resolve_report(self, report_id, headers):
        return self._request(
            "POST", f"/lost-found-reports/{report_id}/resolve", headers=headers
        )

    def unmatch_report(self, report_id, headers):
        return self._request(
            "POST", f"/lost-found-reports/{report_id}/unmatch", headers=headers
        )

    def close_report(self, report_id, headers):
        return self._request(
            "POST", f"/lost-found-reports/{report_id}/close", headers=headers
        )

    # ---- AuditEvent ----
    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/audit-events", headers=headers, params=params)


api_client = ApiClient()
