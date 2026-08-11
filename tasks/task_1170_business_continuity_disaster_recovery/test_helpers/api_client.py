"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

P = "/resilience"


class ApiClient(GenericApiClient):
    # ---- test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", f"{P}/_clock/set_current_utc", payload, headers)

    # ---- contacts ----
    def create_contact(self, payload, headers):
        return self._request("POST", f"{P}/contacts", payload, headers)

    def list_contacts(self, headers, params=None):
        return self._request("GET", f"{P}/contacts", headers=headers, params=params)

    def get_contact(self, contact_id, headers):
        return self._request("GET", f"{P}/contacts/{contact_id}", headers=headers)

    # ---- processes ----
    def create_process(self, payload, headers):
        return self._request("POST", f"{P}/processes", payload, headers)

    def list_processes(self, headers, params=None):
        return self._request("GET", f"{P}/processes", headers=headers, params=params)

    def get_process(self, process_id, headers):
        return self._request("GET", f"{P}/processes/{process_id}", headers=headers)

    def update_process(self, process_id, payload, headers):
        return self._request("PUT", f"{P}/processes/{process_id}", payload, headers)

    def activate_process(self, process_id, headers):
        return self._request("POST", f"{P}/processes/{process_id}/activate", {}, headers)

    def suspend_process(self, process_id, headers):
        return self._request("POST", f"{P}/processes/{process_id}/suspend", {}, headers)

    def resume_process(self, process_id, headers):
        return self._request("POST", f"{P}/processes/{process_id}/resume", {}, headers)

    def retire_process(self, process_id, headers):
        return self._request("POST", f"{P}/processes/{process_id}/retire", {}, headers)

    def list_process_bias(self, process_id, headers):
        return self._request("GET", f"{P}/processes/{process_id}/bias", headers=headers)

    def list_process_plans(self, process_id, headers):
        return self._request("GET", f"{P}/processes/{process_id}/plans", headers=headers)

    def list_process_recovery_capabilities(self, process_id, headers):
        return self._request("GET", f"{P}/processes/{process_id}/recovery-capabilities", headers=headers)

    def list_process_attestations(self, process_id, headers):
        return self._request("GET", f"{P}/processes/{process_id}/attestations", headers=headers)

    def get_blast_radius(self, process_id, headers):
        return self._request("GET", f"{P}/processes/{process_id}/blast-radius", headers=headers)

    def get_gap_pressure(self, process_id, headers):
        return self._request("GET", f"{P}/processes/{process_id}/gap-pressure", headers=headers)

    # ---- BIAs ----
    def create_bia(self, payload, headers):
        return self._request("POST", f"{P}/bias", payload, headers)

    def list_bias(self, headers, params=None):
        return self._request("GET", f"{P}/bias", headers=headers, params=params)

    def get_bia(self, bia_id, headers):
        return self._request("GET", f"{P}/bias/{bia_id}", headers=headers)

    def update_bia(self, bia_id, payload, headers):
        return self._request("PUT", f"{P}/bias/{bia_id}", payload, headers)

    def submit_bia(self, bia_id, headers):
        return self._request("POST", f"{P}/bias/{bia_id}/submit", {}, headers)

    def decide_bia(self, bia_id, payload, headers):
        return self._request("POST", f"{P}/bias/{bia_id}/decide", payload, headers)

    # ---- plans ----
    def create_plan(self, payload, headers):
        return self._request("POST", f"{P}/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", f"{P}/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"{P}/plans/{plan_id}", headers=headers)

    def update_plan(self, plan_id, payload, headers):
        return self._request("PUT", f"{P}/plans/{plan_id}", payload, headers)

    def submit_plan(self, plan_id, headers):
        return self._request("POST", f"{P}/plans/{plan_id}/submit", {}, headers)

    def approve_plan(self, plan_id, headers):
        return self._request("POST", f"{P}/plans/{plan_id}/approve", {}, headers)

    def reject_plan(self, plan_id, headers):
        return self._request("POST", f"{P}/plans/{plan_id}/reject", {}, headers)

    def retire_plan(self, plan_id, headers):
        return self._request("POST", f"{P}/plans/{plan_id}/retire", {}, headers)

    def list_plan_sections(self, plan_id, headers):
        return self._request("GET", f"{P}/plans/{plan_id}/sections", headers=headers)

    def create_plan_section(self, plan_id, payload, headers):
        return self._request("POST", f"{P}/plans/{plan_id}/sections", payload, headers)

    def get_plan_section(self, plan_id, section_id, headers):
        return self._request("GET", f"{P}/plans/{plan_id}/sections/{section_id}", headers=headers)

    def update_plan_section(self, plan_id, section_id, payload, headers):
        return self._request("PUT", f"{P}/plans/{plan_id}/sections/{section_id}", payload, headers)

    def delete_plan_section(self, plan_id, section_id, headers):
        return self._request("DELETE", f"{P}/plans/{plan_id}/sections/{section_id}", headers=headers)

    # ---- dependencies ----
    def create_dependency(self, payload, headers):
        return self._request("POST", f"{P}/dependencies", payload, headers)

    def list_dependencies(self, headers, params=None):
        return self._request("GET", f"{P}/dependencies", headers=headers, params=params)

    def get_dependency(self, dependency_id, headers):
        return self._request("GET", f"{P}/dependencies/{dependency_id}", headers=headers)

    def delete_dependency(self, dependency_id, headers):
        return self._request("DELETE", f"{P}/dependencies/{dependency_id}", headers=headers)

    # ---- third parties ----
    def create_third_party(self, payload, headers):
        return self._request("POST", f"{P}/third-parties", payload, headers)

    def list_third_parties(self, headers, params=None):
        return self._request("GET", f"{P}/third-parties", headers=headers, params=params)

    def get_third_party(self, third_party_id, headers):
        return self._request("GET", f"{P}/third-parties/{third_party_id}", headers=headers)

    def activate_third_party(self, third_party_id, headers):
        return self._request("POST", f"{P}/third-parties/{third_party_id}/activate", {}, headers)

    def suspend_third_party(self, third_party_id, headers):
        return self._request("POST", f"{P}/third-parties/{third_party_id}/suspend", {}, headers)

    def exit_third_party(self, third_party_id, headers):
        return self._request("POST", f"{P}/third-parties/{third_party_id}/exit", {}, headers)

    def list_third_party_assessments(self, third_party_id, headers):
        return self._request("GET", f"{P}/third-parties/{third_party_id}/assessments", headers=headers)

    # ---- assessments ----
    def create_assessment(self, payload, headers):
        return self._request("POST", f"{P}/assessments", payload, headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", f"{P}/assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"{P}/assessments/{assessment_id}", headers=headers)

    def update_assessment(self, assessment_id, payload, headers):
        return self._request("PUT", f"{P}/assessments/{assessment_id}", payload, headers)

    def finalize_assessment(self, assessment_id, headers):
        return self._request("POST", f"{P}/assessments/{assessment_id}/finalize", {}, headers)

    # ---- alternate sites ----
    def create_alternate_site(self, payload, headers):
        return self._request("POST", f"{P}/alternate-sites", payload, headers)

    def list_alternate_sites(self, headers, params=None):
        return self._request("GET", f"{P}/alternate-sites", headers=headers, params=params)

    def get_alternate_site(self, site_id, headers):
        return self._request("GET", f"{P}/alternate-sites/{site_id}", headers=headers)

    def retire_alternate_site(self, site_id, headers):
        return self._request("POST", f"{P}/alternate-sites/{site_id}/retire", {}, headers)

    def list_reservations_of_site(self, site_id, headers):
        return self._request("GET", f"{P}/alternate-sites/{site_id}/reservations", headers=headers)

    def get_site_utilization(self, site_id, headers, params=None):
        return self._request("GET", f"{P}/alternate-sites/{site_id}/utilization", headers=headers, params=params)

    # ---- site reservations ----
    def create_site_reservation(self, payload, headers):
        return self._request("POST", f"{P}/site-reservations", payload, headers)

    def list_site_reservations(self, headers, params=None):
        return self._request("GET", f"{P}/site-reservations", headers=headers, params=params)

    def get_site_reservation(self, reservation_id, headers):
        return self._request("GET", f"{P}/site-reservations/{reservation_id}", headers=headers)

    def release_site_reservation(self, reservation_id, headers):
        return self._request("POST", f"{P}/site-reservations/{reservation_id}/release", {}, headers)

    # ---- exercises ----
    def create_exercise(self, payload, headers):
        return self._request("POST", f"{P}/exercises", payload, headers)

    def list_exercises(self, headers, params=None):
        return self._request("GET", f"{P}/exercises", headers=headers, params=params)

    def get_exercise(self, exercise_id, headers):
        return self._request("GET", f"{P}/exercises/{exercise_id}", headers=headers)

    def update_exercise(self, exercise_id, payload, headers):
        return self._request("PUT", f"{P}/exercises/{exercise_id}", payload, headers)

    def start_exercise(self, exercise_id, headers):
        return self._request("POST", f"{P}/exercises/{exercise_id}/start", {}, headers)

    def complete_exercise(self, exercise_id, payload, headers):
        return self._request("POST", f"{P}/exercises/{exercise_id}/complete", payload, headers)

    def cancel_exercise(self, exercise_id, headers):
        return self._request("POST", f"{P}/exercises/{exercise_id}/cancel", {}, headers)

    def list_exercise_findings(self, exercise_id, headers):
        return self._request("GET", f"{P}/exercises/{exercise_id}/findings", headers=headers)

    def list_exercise_validation_runs(self, exercise_id, headers):
        return self._request("GET", f"{P}/exercises/{exercise_id}/validation-runs", headers=headers)

    # ---- findings ----
    def create_finding(self, payload, headers):
        return self._request("POST", f"{P}/findings", payload, headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", f"{P}/findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"{P}/findings/{finding_id}", headers=headers)

    def remediate_finding(self, finding_id, headers):
        return self._request("POST", f"{P}/findings/{finding_id}/remediate", {}, headers)

    def verify_finding(self, finding_id, headers):
        return self._request("POST", f"{P}/findings/{finding_id}/verify", {}, headers)

    def reject_finding(self, finding_id, payload, headers):
        return self._request("POST", f"{P}/findings/{finding_id}/reject", payload, headers)

    def list_finding_gaps(self, finding_id, headers):
        return self._request("GET", f"{P}/findings/{finding_id}/gaps", headers=headers)

    # ---- recovery capabilities ----
    def create_recovery_capability(self, payload, headers):
        return self._request("POST", f"{P}/recovery-capabilities", payload, headers)

    def list_recovery_capabilities(self, headers, params=None):
        return self._request("GET", f"{P}/recovery-capabilities", headers=headers, params=params)

    def get_recovery_capability(self, capability_id, headers):
        return self._request("GET", f"{P}/recovery-capabilities/{capability_id}", headers=headers)

    def mark_capability_remediated(self, capability_id, headers):
        return self._request("POST", f"{P}/recovery-capabilities/{capability_id}/mark-remediated", {}, headers)

    def list_capability_validation_runs(self, capability_id, headers):
        return self._request("GET", f"{P}/recovery-capabilities/{capability_id}/validation-runs", headers=headers)

    def list_capability_gaps(self, capability_id, headers):
        return self._request("GET", f"{P}/recovery-capabilities/{capability_id}/gaps", headers=headers)

    # ---- validation runs ----
    def create_validation_run(self, payload, headers):
        return self._request("POST", f"{P}/validation-runs", payload, headers)

    def list_validation_runs(self, headers, params=None):
        return self._request("GET", f"{P}/validation-runs", headers=headers, params=params)

    def get_validation_run(self, run_id, headers):
        return self._request("GET", f"{P}/validation-runs/{run_id}", headers=headers)

    # ---- gaps ----
    def create_gap(self, payload, headers):
        return self._request("POST", f"{P}/gaps", payload, headers)

    def list_gaps(self, headers, params=None):
        return self._request("GET", f"{P}/gaps", headers=headers, params=params)

    def get_gap(self, gap_id, headers):
        return self._request("GET", f"{P}/gaps/{gap_id}", headers=headers)

    def start_gap(self, gap_id, headers):
        return self._request("POST", f"{P}/gaps/{gap_id}/start", {}, headers)

    def reopen_gap(self, gap_id, headers):
        return self._request("POST", f"{P}/gaps/{gap_id}/reopen", {}, headers)

    def close_gap(self, gap_id, headers):
        return self._request("POST", f"{P}/gaps/{gap_id}/close", {}, headers)

    def accept_gap_risk(self, gap_id, headers):
        return self._request("POST", f"{P}/gaps/{gap_id}/accept-risk", {}, headers)

    # ---- comm nodes ----
    def create_comm_node(self, payload, headers):
        return self._request("POST", f"{P}/comm-nodes", payload, headers)

    def list_comm_nodes(self, headers, params=None):
        return self._request("GET", f"{P}/comm-nodes", headers=headers, params=params)

    def get_comm_node(self, node_id, headers):
        return self._request("GET", f"{P}/comm-nodes/{node_id}", headers=headers)

    def update_comm_node(self, node_id, payload, headers):
        return self._request("PUT", f"{P}/comm-nodes/{node_id}", payload, headers)

    # ---- activations ----
    def create_activation(self, payload, headers):
        return self._request("POST", f"{P}/activations", payload, headers)

    def list_activations(self, headers, params=None):
        return self._request("GET", f"{P}/activations", headers=headers, params=params)

    def get_activation(self, activation_id, headers):
        return self._request("GET", f"{P}/activations/{activation_id}", headers=headers)

    def deactivate_activation(self, activation_id, headers):
        return self._request("POST", f"{P}/activations/{activation_id}/deactivate", {}, headers)

    def list_activation_notifications(self, activation_id, headers):
        return self._request("GET", f"{P}/activations/{activation_id}/notifications", headers=headers)

    # ---- notifications ----
    def list_notifications(self, headers, params=None):
        return self._request("GET", f"{P}/notifications", headers=headers, params=params)

    def get_notification(self, notification_id, headers):
        return self._request("GET", f"{P}/notifications/{notification_id}", headers=headers)

    def ack_notification(self, notification_id, payload, headers):
        return self._request("POST", f"{P}/notifications/{notification_id}/ack", payload, headers)

    # ---- attestations ----
    def create_attestation(self, payload, headers):
        return self._request("POST", f"{P}/attestations", payload, headers)

    def list_attestations(self, headers, params=None):
        return self._request("GET", f"{P}/attestations", headers=headers, params=params)

    def get_attestation(self, attestation_id, headers):
        return self._request("GET", f"{P}/attestations/{attestation_id}", headers=headers)

    def sign_attestation(self, attestation_id, payload, headers):
        return self._request("POST", f"{P}/attestations/{attestation_id}/sign", payload, headers)

    def revoke_attestation(self, attestation_id, payload, headers):
        return self._request("POST", f"{P}/attestations/{attestation_id}/revoke", payload, headers)


api_client = ApiClient()
