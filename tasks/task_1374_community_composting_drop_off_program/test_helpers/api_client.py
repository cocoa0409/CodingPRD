"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ clock
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --------------------------------------------------------------- programs
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/activate",
                             headers=headers)

    def suspend_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/suspend",
                             headers=headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/close",
                             headers=headers)

    def run_ops(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/run_ops",
                             headers=headers)

    # ------------------------------------------------------------------ sites
    def create_site(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/sites",
                             payload, headers)

    def list_sites(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/sites",
                             headers=headers, params=params)

    def get_site(self, program_id, site_id, headers):
        return self._request("GET", f"/programs/{program_id}/sites/{site_id}",
                             headers=headers)

    def commission_site(self, program_id, site_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/sites/{site_id}/commission",
            headers=headers)

    def decommission_site(self, program_id, site_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/sites/{site_id}/decommission",
            headers=headers)

    def archive_site(self, program_id, site_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/sites/{site_id}/archive",
            headers=headers)

    # ----------------------------------------------------------- agreements
    def create_host_agreement(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/host-agreements",
                             payload, headers)

    def list_host_agreements(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/host-agreements",
                             headers=headers, params=params)

    def get_host_agreement(self, program_id, agreement_id, headers):
        return self._request(
            "GET", f"/programs/{program_id}/host-agreements/{agreement_id}",
            headers=headers)

    def activate_host_agreement(self, program_id, agreement_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/host-agreements/{agreement_id}/activate",
            headers=headers)

    def breach_notice_host_agreement(self, program_id, agreement_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/host-agreements/{agreement_id}/breach-notice",
            headers=headers)

    def cure_host_agreement(self, program_id, agreement_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/host-agreements/{agreement_id}/cure",
            headers=headers)

    def terminate_host_agreement(self, program_id, agreement_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/host-agreements/{agreement_id}/terminate",
            headers=headers)

    # --------------------------------------------------------------- materials
    def create_material(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/materials",
                             payload, headers)

    def list_materials(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/materials",
                             headers=headers, params=params)

    def patch_material(self, program_id, material_id, payload, headers):
        return self._request(
            "PATCH", f"/programs/{program_id}/materials/{material_id}",
            payload, headers)

    # ------------------------------------------------------------- participants
    def register_participant(self, program_id, payload, headers):
        return self._request(
            "POST", f"/programs/{program_id}/participants/register",
            payload, headers)

    def list_participants(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/participants",
                             headers=headers, params=params)

    def get_participant(self, program_id, participant_id, headers):
        return self._request(
            "GET", f"/programs/{program_id}/participants/{participant_id}",
            headers=headers)

    def verify_participant(self, program_id, participant_id, payload, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/participants/{participant_id}/verify",
            payload, headers)

    def suspend_participant(self, program_id, participant_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/participants/{participant_id}/suspend",
            headers=headers)

    def reinstate_participant(self, program_id, participant_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/participants/{participant_id}/reinstate",
            headers=headers)

    def deactivate_participant(self, program_id, participant_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/participants/{participant_id}/deactivate",
            headers=headers)

    # ------------------------------------------------------------------ grants
    def create_grant(self, program_id, participant_id, payload, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/participants/{participant_id}/grants",
            payload, headers)

    def list_grants(self, program_id, participant_id, headers, params=None):
        return self._request(
            "GET",
            f"/programs/{program_id}/participants/{participant_id}/grants",
            headers=headers, params=params)

    def revoke_grant(self, program_id, participant_id, grant_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/participants/{participant_id}/grants/{grant_id}/revoke",
            headers=headers)

    # ------------------------------------------------------------------- drops
    def create_drop(self, program_id, site_id, payload, headers):
        return self._request(
            "POST", f"/programs/{program_id}/sites/{site_id}/drops",
            payload, headers)

    def list_drops(self, program_id, site_id, headers, params=None):
        return self._request(
            "GET", f"/programs/{program_id}/sites/{site_id}/drops",
            headers=headers, params=params)

    def get_drop(self, program_id, site_id, drop_id, headers):
        return self._request(
            "GET", f"/programs/{program_id}/sites/{site_id}/drops/{drop_id}",
            headers=headers)

    def accept_drop(self, program_id, site_id, drop_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/sites/{site_id}/drops/{drop_id}/accept",
            headers=headers)

    def reject_drop(self, program_id, site_id, drop_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/sites/{site_id}/drops/{drop_id}/reject",
            headers=headers)

    # ---------------------------------------------------- contamination reports
    def create_contamination_report(self, program_id, site_id, payload, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/sites/{site_id}/contamination-reports",
            payload, headers)

    def list_contamination_reports(self, program_id, site_id, headers, params=None):
        return self._request(
            "GET",
            f"/programs/{program_id}/sites/{site_id}/contamination-reports",
            headers=headers, params=params)

    def send_report_feedback(self, program_id, site_id, report_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/sites/{site_id}/contamination-reports/{report_id}/send-feedback",
            headers=headers)

    def resolve_contamination_report(self, program_id, site_id, report_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/sites/{site_id}/contamination-reports/{report_id}/resolve",
            headers=headers)

    def dismiss_contamination_report(self, program_id, site_id, report_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/sites/{site_id}/contamination-reports/{report_id}/dismiss",
            headers=headers)

    # ----------------------------------------------------------------- partners
    def create_partner(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/partners",
                             payload, headers)

    def list_partners(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/partners",
                             headers=headers, params=params)

    # ------------------------------------------------------------------- routes
    def create_route(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/routes",
                             payload, headers)

    def list_routes(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/routes",
                             headers=headers, params=params)

    def get_route(self, program_id, route_id, headers):
        return self._request("GET", f"/programs/{program_id}/routes/{route_id}",
                             headers=headers)

    def dispatch_route(self, program_id, route_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/routes/{route_id}/dispatch",
            headers=headers)

    def complete_route(self, program_id, route_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/routes/{route_id}/complete",
            headers=headers)

    def cancel_route(self, program_id, route_id, headers):
        return self._request(
            "POST", f"/programs/{program_id}/routes/{route_id}/cancel",
            headers=headers)

    # ------------------------------------------------------------------- stops
    def create_stop(self, program_id, route_id, payload, headers):
        return self._request(
            "POST", f"/programs/{program_id}/routes/{route_id}/stops",
            payload, headers)

    def list_stops(self, program_id, route_id, headers, params=None):
        return self._request(
            "GET", f"/programs/{program_id}/routes/{route_id}/stops",
            headers=headers, params=params)

    def collect_stop(self, program_id, route_id, stop_id, payload, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/routes/{route_id}/stops/{stop_id}/collect",
            payload, headers)

    def skip_stop(self, program_id, route_id, stop_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/routes/{route_id}/stops/{stop_id}/skip",
            headers=headers)

    def cancel_stop(self, program_id, route_id, stop_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/routes/{route_id}/stops/{stop_id}/cancel",
            headers=headers)

    # ------------------------------------------------------------------ batches
    def list_batches(self, program_id, partner_id, headers, params=None):
        return self._request(
            "GET", f"/programs/{program_id}/partners/{partner_id}/batches",
            headers=headers, params=params)

    def get_batch(self, program_id, partner_id, batch_id, headers):
        return self._request(
            "GET",
            f"/programs/{program_id}/partners/{partner_id}/batches/{batch_id}",
            headers=headers)

    def close_batch(self, program_id, partner_id, batch_id, payload, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/partners/{partner_id}/batches/{batch_id}/close",
            payload, headers)

    # ------------------------------------------------------------- distributions
    def create_distribution(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/distributions",
                             payload, headers)

    def list_distributions(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/distributions",
                             headers=headers, params=params)

    def get_distribution(self, program_id, distribution_id, headers):
        return self._request(
            "GET", f"/programs/{program_id}/distributions/{distribution_id}",
            headers=headers)

    def create_allocation(self, program_id, distribution_id, payload, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/distributions/{distribution_id}/allocations",
            payload, headers)

    def list_allocations(self, program_id, distribution_id, headers, params=None):
        return self._request(
            "GET",
            f"/programs/{program_id}/distributions/{distribution_id}/allocations",
            headers=headers, params=params)

    def distribute_allocation(self, program_id, distribution_id, allocation_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/distributions/{distribution_id}/allocations/{allocation_id}/distribute",
            headers=headers)

    def cancel_allocation(self, program_id, distribution_id, allocation_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/distributions/{distribution_id}/allocations/{allocation_id}/cancel",
            headers=headers)

    def close_distribution(self, program_id, distribution_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/distributions/{distribution_id}/close",
            headers=headers)

    def cancel_distribution(self, program_id, distribution_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/distributions/{distribution_id}/cancel",
            headers=headers)

    # --------------------------------------------------------------- complaints
    def create_complaint(self, program_id, site_id, payload, headers):
        return self._request(
            "POST", f"/programs/{program_id}/sites/{site_id}/complaints",
            payload, headers)

    def list_complaints(self, program_id, site_id, headers, params=None):
        return self._request(
            "GET", f"/programs/{program_id}/sites/{site_id}/complaints",
            headers=headers, params=params)

    def acknowledge_complaint(self, program_id, site_id, complaint_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/sites/{site_id}/complaints/{complaint_id}/acknowledge",
            headers=headers)

    def resolve_complaint(self, program_id, site_id, complaint_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/sites/{site_id}/complaints/{complaint_id}/resolve",
            headers=headers)

    def reopen_complaint(self, program_id, site_id, complaint_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/sites/{site_id}/complaints/{complaint_id}/reopen",
            headers=headers)

    def close_complaint(self, program_id, site_id, complaint_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/sites/{site_id}/complaints/{complaint_id}/close",
            headers=headers)

    # -------------------------------------------------------- diversion reports
    def create_diversion_report(self, program_id, payload, headers):
        return self._request(
            "POST", f"/programs/{program_id}/diversion-reports",
            payload, headers)

    def list_diversion_reports(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/programs/{program_id}/diversion-reports",
            headers=headers, params=params)

    def get_diversion_report(self, program_id, report_id, headers):
        return self._request(
            "GET", f"/programs/{program_id}/diversion-reports/{report_id}",
            headers=headers)

    def certify_diversion_report(self, program_id, report_id, headers):
        return self._request(
            "POST",
            f"/programs/{program_id}/diversion-reports/{report_id}/certify",
            headers=headers)


api_client = ApiClient()
