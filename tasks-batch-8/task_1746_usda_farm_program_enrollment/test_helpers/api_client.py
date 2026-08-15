"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/fsa/_clock/set_current_utc", payload, headers)

    # --- Farms ---
    def create_farm(self, payload, headers):
        return self._request("POST", "/fsa/farms", payload, headers)

    def get_farm(self, farm_id, headers):
        return self._request("GET", f"/fsa/farms/{farm_id}", headers=headers)

    def list_farms(self, headers, params=None):
        return self._request("GET", "/fsa/farms", headers=headers, params=params)

    def retire_farm(self, farm_id, headers):
        return self._request("POST", f"/fsa/farms/{farm_id}/retire", {}, headers)

    # --- Producers ---
    def create_producer(self, payload, headers):
        return self._request("POST", "/fsa/producers", payload, headers)

    def get_producer(self, producer_id, headers):
        return self._request("GET", f"/fsa/producers/{producer_id}", headers=headers)

    def list_producers(self, headers, params=None):
        return self._request("GET", "/fsa/producers", headers=headers, params=params)

    def file_agi_attestation(self, producer_id, payload, headers):
        return self._request(
            "POST", f"/fsa/producers/{producer_id}/agi-attestations", payload, headers
        )

    def verify_agi_attestation(self, producer_id, headers):
        return self._request(
            "POST", f"/fsa/producers/{producer_id}/agi-attestations/verify", {}, headers
        )

    def flag_agi_noncompliant(self, producer_id, headers):
        return self._request(
            "POST",
            f"/fsa/producers/{producer_id}/agi-attestations/flag-noncompliant",
            {},
            headers,
        )

    def file_conservation_certification(self, producer_id, payload, headers):
        return self._request(
            "POST",
            f"/fsa/producers/{producer_id}/conservation-certifications",
            payload,
            headers,
        )

    def record_conservation_violation(self, producer_id, payload, headers):
        return self._request(
            "POST", f"/fsa/producers/{producer_id}/conservation-violations", payload, headers
        )

    def grant_conservation_exemption(self, producer_id, payload, headers):
        return self._request(
            "POST", f"/fsa/producers/{producer_id}/conservation-exemptions", payload, headers
        )

    # --- Memberships ---
    def create_membership(self, farm_id, payload, headers):
        return self._request("POST", f"/fsa/farms/{farm_id}/memberships", payload, headers)

    def list_farm_memberships(self, farm_id, headers):
        return self._request("GET", f"/fsa/farms/{farm_id}/memberships", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/fsa/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/fsa/memberships/{membership_id}", headers=headers)

    def delete_membership(self, membership_id, headers):
        return self._request("DELETE", f"/fsa/memberships/{membership_id}", headers=headers)

    # --- Tracts / Fields ---
    def create_tract(self, farm_id, payload, headers):
        return self._request("POST", f"/fsa/farms/{farm_id}/tracts", payload, headers)

    def list_farm_tracts(self, farm_id, headers):
        return self._request("GET", f"/fsa/farms/{farm_id}/tracts", headers=headers)

    def get_tract(self, tract_id, headers):
        return self._request("GET", f"/fsa/tracts/{tract_id}", headers=headers)

    def list_tracts(self, headers, params=None):
        return self._request("GET", "/fsa/tracts", headers=headers, params=params)

    def create_field(self, tract_id, payload, headers):
        return self._request("POST", f"/fsa/tracts/{tract_id}/fields", payload, headers)

    def list_tract_fields(self, tract_id, headers):
        return self._request("GET", f"/fsa/tracts/{tract_id}/fields", headers=headers)

    def get_field(self, field_id, headers):
        return self._request("GET", f"/fsa/fields/{field_id}", headers=headers)

    def list_field_acreage_report_lines(self, field_id, headers):
        return self._request(
            "GET", f"/fsa/fields/{field_id}/acreage-report-lines", headers=headers
        )

    # --- Reconstitution ---
    def open_reconstitution(self, farm_id, payload, headers):
        return self._request("POST", f"/fsa/farms/{farm_id}/reconstitutions", payload, headers)

    def finalize_reconstitution(self, farm_id, headers):
        return self._request(
            "POST", f"/fsa/farms/{farm_id}/finalize-reconstitution", {}, headers
        )

    def cancel_reconstitution(self, farm_id, recon_id, headers):
        return self._request(
            "POST", f"/fsa/farms/{farm_id}/reconstitutions/{recon_id}/cancel", {}, headers
        )

    # --- Acreage reports ---
    def create_acreage_report(self, farm_id, payload, headers):
        return self._request("POST", f"/fsa/farms/{farm_id}/acreage-reports", payload, headers)

    def get_acreage_report(self, report_id, headers):
        return self._request("GET", f"/fsa/acreage-reports/{report_id}", headers=headers)

    def list_farm_acreage_reports(self, farm_id, headers, params=None):
        return self._request(
            "GET", f"/fsa/farms/{farm_id}/acreage-reports", headers=headers, params=params
        )

    def add_acreage_report_line(self, report_id, payload, headers):
        return self._request(
            "POST", f"/fsa/acreage-reports/{report_id}/lines", payload, headers
        )

    def list_acreage_report_lines(self, report_id, headers):
        return self._request(
            "GET", f"/fsa/acreage-reports/{report_id}/lines", headers=headers
        )

    def file_acreage_report(self, report_id, headers):
        return self._request("POST", f"/fsa/acreage-reports/{report_id}/file", {}, headers)

    def certify_acreage_report(self, report_id, headers):
        return self._request("POST", f"/fsa/acreage-reports/{report_id}/certify", {}, headers)

    def reject_acreage_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/fsa/acreage-reports/{report_id}/reject", payload, headers
        )

    def reopen_acreage_report(self, report_id, headers):
        return self._request("POST", f"/fsa/acreage-reports/{report_id}/reopen", {}, headers)

    # --- Program elections ---
    def create_program_election(self, farm_id, payload, headers):
        return self._request(
            "POST", f"/fsa/farms/{farm_id}/program-elections", payload, headers
        )

    def get_program_election(self, election_id, headers):
        return self._request("GET", f"/fsa/program-elections/{election_id}", headers=headers)

    def list_election_enrollments(self, election_id, headers):
        return self._request(
            "GET", f"/fsa/program-elections/{election_id}/enrollments", headers=headers
        )

    def list_farm_program_elections(self, farm_id, headers, params=None):
        return self._request(
            "GET", f"/fsa/farms/{farm_id}/program-elections", headers=headers, params=params
        )

    def withdraw_program_election(self, election_id, headers):
        return self._request(
            "POST", f"/fsa/program-elections/{election_id}/withdraw", {}, headers
        )

    # --- Yield records ---
    def create_yield_record(self, farm_id, payload, headers):
        return self._request("POST", f"/fsa/farms/{farm_id}/yield-records", payload, headers)

    def get_yield_record(self, record_id, headers):
        return self._request("GET", f"/fsa/yield-records/{record_id}", headers=headers)

    def list_yield_record_enrollments(self, record_id, headers):
        return self._request(
            "GET", f"/fsa/yield-records/{record_id}/enrollments", headers=headers
        )

    def list_farm_yield_records(self, farm_id, headers, params=None):
        return self._request(
            "GET", f"/fsa/farms/{farm_id}/yield-records", headers=headers, params=params
        )

    def append_yield_observation(self, record_id, payload, headers):
        return self._request(
            "POST", f"/fsa/yield-records/{record_id}/observations", payload, headers
        )

    def list_yield_observations(self, record_id, headers):
        return self._request(
            "GET", f"/fsa/yield-records/{record_id}/observations", headers=headers
        )

    def trigger_yield_update(self, record_id, headers):
        return self._request("POST", f"/fsa/yield-records/{record_id}/updates", {}, headers)

    def certify_yield_record(self, record_id, headers):
        return self._request("POST", f"/fsa/yield-records/{record_id}/certify", {}, headers)

    # --- Enrollments ---
    def create_enrollment(self, farm_id, payload, headers):
        return self._request("POST", f"/fsa/farms/{farm_id}/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/fsa/enrollments/{enrollment_id}", headers=headers)

    def list_enrollment_appeals(self, enrollment_id, headers):
        return self._request(
            "GET", f"/fsa/enrollments/{enrollment_id}/appeals", headers=headers
        )

    def list_farm_enrollments(self, farm_id, headers, params=None):
        return self._request(
            "GET", f"/fsa/farms/{farm_id}/enrollments", headers=headers, params=params
        )

    def submit_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/fsa/enrollments/{enrollment_id}/submit", {}, headers)

    def ced_approve_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/fsa/enrollments/{enrollment_id}/ced-approve", {}, headers
        )

    def certify_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/fsa/enrollments/{enrollment_id}/certify", {}, headers)

    def compute_payment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/fsa/enrollments/{enrollment_id}/compute-payment", payload, headers
        )

    def issue_payment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/fsa/enrollments/{enrollment_id}/issue-payment", {}, headers
        )

    def recertify_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/fsa/enrollments/{enrollment_id}/recertify", {}, headers
        )

    def void_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/fsa/enrollments/{enrollment_id}/void", {}, headers)

    # --- Disaster applications ---
    def create_disaster_application(self, farm_id, payload, headers):
        return self._request(
            "POST", f"/fsa/farms/{farm_id}/disaster-applications", payload, headers
        )

    def get_disaster_application(self, app_id, headers):
        return self._request("GET", f"/fsa/disaster-applications/{app_id}", headers=headers)

    def list_farm_disaster_applications(self, farm_id, headers, params=None):
        return self._request(
            "GET", f"/fsa/farms/{farm_id}/disaster-applications", headers=headers, params=params
        )

    def file_disaster_application(self, app_id, headers):
        return self._request("POST", f"/fsa/disaster-applications/{app_id}/file", {}, headers)

    def assign_disaster_reviewer(self, app_id, headers):
        return self._request(
            "POST", f"/fsa/disaster-applications/{app_id}/assign-reviewer", {}, headers
        )

    def approve_disaster_application(self, app_id, headers):
        return self._request(
            "POST", f"/fsa/disaster-applications/{app_id}/approve", {}, headers
        )

    def deny_disaster_application(self, app_id, payload, headers):
        return self._request(
            "POST", f"/fsa/disaster-applications/{app_id}/deny", payload, headers
        )

    def withdraw_disaster_application(self, app_id, headers):
        return self._request(
            "POST", f"/fsa/disaster-applications/{app_id}/withdraw", {}, headers
        )

    # --- Appeals ---
    def file_appeal(self, payload, headers):
        return self._request("POST", "/fsa/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/fsa/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/fsa/appeals", headers=headers, params=params)

    def list_farm_appeals(self, farm_id, headers, params=None):
        return self._request(
            "GET", f"/fsa/farms/{farm_id}/appeals", headers=headers, params=params
        )

    def assign_appeal_ced(self, appeal_id, headers):
        return self._request("POST", f"/fsa/appeals/{appeal_id}/assign-ced", {}, headers)

    def refer_appeal_to_committee(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/fsa/appeals/{appeal_id}/refer-to-committee", payload, headers
        )

    def uphold_appeal(self, appeal_id, headers):
        return self._request("POST", f"/fsa/appeals/{appeal_id}/uphold", {}, headers)

    def reverse_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/fsa/appeals/{appeal_id}/reverse", payload, headers)

    def remand_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/fsa/appeals/{appeal_id}/remand", payload, headers)

    def close_appeal(self, appeal_id, headers):
        return self._request("POST", f"/fsa/appeals/{appeal_id}/close", {}, headers)


api_client = ApiClient()
