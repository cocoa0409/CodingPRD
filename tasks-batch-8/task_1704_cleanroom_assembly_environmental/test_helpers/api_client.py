"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/cleanroom/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Cleanrooms
    # ------------------------------------------------------------------
    def create_room(self, payload, headers):
        return self._request("POST", "/cleanroom/rooms", payload, headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/cleanroom/rooms", headers=headers, params=params)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/cleanroom/rooms/{room_id}", headers=headers)

    def decommission_room(self, room_id, headers):
        return self._request("POST", f"/cleanroom/rooms/{room_id}/decommission", {}, headers)

    # ------------------------------------------------------------------
    # Sampling points
    # ------------------------------------------------------------------
    def create_sampling_point(self, room_id, payload, headers):
        return self._request("POST", f"/cleanroom/rooms/{room_id}/sampling-points",
                             payload, headers)

    def list_sampling_points(self, room_id, headers):
        return self._request("GET", f"/cleanroom/rooms/{room_id}/sampling-points",
                             headers=headers)

    def get_sampling_point(self, point_id, headers):
        return self._request("GET", f"/cleanroom/sampling-points/{point_id}", headers=headers)

    def retire_sampling_point(self, point_id, headers):
        return self._request("POST", f"/cleanroom/sampling-points/{point_id}/retire",
                             {}, headers)

    # ------------------------------------------------------------------
    # Environmental samples
    # ------------------------------------------------------------------
    def create_sample(self, payload, headers):
        return self._request("POST", "/cleanroom/samples", payload, headers)

    def list_samples(self, headers, params=None):
        return self._request("GET", "/cleanroom/samples", headers=headers, params=params)

    def get_sample(self, sample_id, headers):
        return self._request("GET", f"/cleanroom/samples/{sample_id}", headers=headers)

    # ------------------------------------------------------------------
    # Excursions & investigations
    # ------------------------------------------------------------------
    def list_excursions(self, headers, params=None):
        return self._request("GET", "/cleanroom/excursions", headers=headers, params=params)

    def get_excursion(self, excursion_id, headers):
        return self._request("GET", f"/cleanroom/excursions/{excursion_id}", headers=headers)

    def list_excursion_samples(self, excursion_id, headers):
        return self._request("GET", f"/cleanroom/excursions/{excursion_id}/samples",
                             headers=headers)

    def open_investigation(self, excursion_id, payload, headers):
        return self._request("POST", f"/cleanroom/excursions/{excursion_id}/investigations",
                             payload, headers)

    def list_investigations(self, excursion_id, headers):
        return self._request("GET", f"/cleanroom/excursions/{excursion_id}/investigations",
                             headers=headers)

    def get_investigation(self, investigation_id, headers):
        return self._request("GET", f"/cleanroom/investigations/{investigation_id}",
                             headers=headers)

    def approve_investigation(self, investigation_id, headers):
        return self._request("POST",
                             f"/cleanroom/investigations/{investigation_id}/approve",
                             {}, headers)

    def reject_investigation(self, investigation_id, headers):
        return self._request("POST",
                             f"/cleanroom/investigations/{investigation_id}/reject",
                             {}, headers)

    # ------------------------------------------------------------------
    # Room certifications
    # ------------------------------------------------------------------
    def create_certification(self, room_id, payload, headers):
        return self._request("POST", f"/cleanroom/rooms/{room_id}/certifications",
                             payload, headers)

    def list_room_certifications(self, room_id, headers):
        return self._request("GET", f"/cleanroom/rooms/{room_id}/certifications",
                             headers=headers)

    def get_certification(self, cert_id, headers):
        return self._request("GET", f"/cleanroom/certifications/{cert_id}", headers=headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/cleanroom/certifications", headers=headers,
                             params=params)

    def void_certification(self, room_id, cert_id, headers):
        return self._request("POST",
                             f"/cleanroom/rooms/{room_id}/certifications/{cert_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # Personnel, gowning qualification, entry logs
    # ------------------------------------------------------------------
    def create_personnel(self, payload, headers):
        return self._request("POST", "/cleanroom/personnel", payload, headers)

    def list_personnel(self, headers, params=None):
        return self._request("GET", "/cleanroom/personnel", headers=headers, params=params)

    def get_personnel(self, personnel_id, headers):
        return self._request("GET", f"/cleanroom/personnel/{personnel_id}", headers=headers)

    def suspend_personnel(self, personnel_id, headers):
        return self._request("POST", f"/cleanroom/personnel/{personnel_id}/suspend",
                             {}, headers)

    def reinstate_personnel(self, personnel_id, headers):
        return self._request("POST", f"/cleanroom/personnel/{personnel_id}/reinstate",
                             {}, headers)

    def create_gowning_qualification(self, payload, headers):
        return self._request("POST", "/cleanroom/gowning-qualifications", payload, headers)

    def list_gowning_qualifications(self, headers, params=None):
        return self._request("GET", "/cleanroom/gowning-qualifications", headers=headers,
                             params=params)

    def get_gowning_qualification(self, qual_id, headers):
        return self._request("GET", f"/cleanroom/gowning-qualifications/{qual_id}",
                             headers=headers)

    def revoke_gowning_qualification(self, qual_id, headers):
        return self._request("POST", f"/cleanroom/gowning-qualifications/{qual_id}/revoke",
                             {}, headers)

    def list_room_gowning_qualifications(self, room_id, headers):
        return self._request("GET", f"/cleanroom/rooms/{room_id}/gowning-qualifications",
                             headers=headers)

    def list_personnel_gowning_qualifications(self, personnel_id, headers):
        return self._request("GET",
                             f"/cleanroom/personnel/{personnel_id}/gowning-qualifications",
                             headers=headers)

    def create_entry_log(self, payload, headers):
        return self._request("POST", "/cleanroom/entry-logs", payload, headers)

    def list_entry_logs(self, headers, params=None):
        return self._request("GET", "/cleanroom/entry-logs", headers=headers, params=params)

    def get_entry_log(self, entry_log_id, headers):
        return self._request("GET", f"/cleanroom/entry-logs/{entry_log_id}", headers=headers)

    def exit_entry_log(self, entry_log_id, headers):
        return self._request("POST", f"/cleanroom/entry-logs/{entry_log_id}/exit",
                             {}, headers)

    # ------------------------------------------------------------------
    # Material transfers
    # ------------------------------------------------------------------
    def create_material_transfer(self, payload, headers):
        return self._request("POST", "/cleanroom/material-transfers", payload, headers)

    def list_material_transfers(self, headers, params=None):
        return self._request("GET", "/cleanroom/material-transfers", headers=headers,
                             params=params)

    def get_material_transfer(self, transfer_id, headers):
        return self._request("GET", f"/cleanroom/material-transfers/{transfer_id}",
                             headers=headers)

    def introduce_material_transfer(self, transfer_id, headers):
        return self._request("POST",
                             f"/cleanroom/material-transfers/{transfer_id}/introduce",
                             {}, headers)

    def reject_material_transfer(self, transfer_id, headers):
        return self._request("POST",
                             f"/cleanroom/material-transfers/{transfer_id}/reject",
                             {}, headers)

    # ------------------------------------------------------------------
    # Assembly batches & travelers
    # ------------------------------------------------------------------
    def create_batch(self, payload, headers):
        return self._request("POST", "/cleanroom/batches", payload, headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/cleanroom/batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/cleanroom/batches/{batch_id}", headers=headers)

    def create_traveler(self, batch_id, payload, headers):
        return self._request("POST", f"/cleanroom/batches/{batch_id}/travelers",
                             payload, headers)

    def list_travelers(self, batch_id, headers):
        return self._request("GET", f"/cleanroom/batches/{batch_id}/travelers",
                             headers=headers)

    def get_traveler(self, traveler_id, headers):
        return self._request("GET", f"/cleanroom/travelers/{traveler_id}", headers=headers)

    def start_traveler(self, traveler_id, headers):
        return self._request("POST", f"/cleanroom/travelers/{traveler_id}/start",
                             {}, headers)

    def complete_traveler(self, traveler_id, headers):
        return self._request("POST", f"/cleanroom/travelers/{traveler_id}/complete",
                             {}, headers)

    def void_traveler(self, traveler_id, headers):
        return self._request("POST", f"/cleanroom/travelers/{traveler_id}/void",
                             {}, headers)

    def release_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/cleanroom/batches/{batch_id}/release",
                             payload, headers)

    def reject_batch(self, batch_id, headers):
        return self._request("POST", f"/cleanroom/batches/{batch_id}/reject", {}, headers)

    def resume_batch(self, batch_id, headers):
        return self._request("POST", f"/cleanroom/batches/{batch_id}/resume", {}, headers)

    # ------------------------------------------------------------------
    # Cleaning validation programs & cycles
    # ------------------------------------------------------------------
    def create_cleaning_program(self, payload, headers):
        return self._request("POST", "/cleanroom/cleaning-programs", payload, headers)

    def list_cleaning_programs(self, headers, params=None):
        return self._request("GET", "/cleanroom/cleaning-programs", headers=headers,
                             params=params)

    def get_cleaning_program(self, program_id, headers):
        return self._request("GET", f"/cleanroom/cleaning-programs/{program_id}",
                             headers=headers)

    def activate_cleaning_program(self, program_id, headers):
        return self._request("POST",
                             f"/cleanroom/cleaning-programs/{program_id}/activate",
                             {}, headers)

    def create_cleaning_cycle(self, program_id, payload, headers):
        return self._request("POST", f"/cleanroom/cleaning-programs/{program_id}/cycles",
                             payload, headers)

    def list_cleaning_cycles(self, program_id, headers):
        return self._request("GET", f"/cleanroom/cleaning-programs/{program_id}/cycles",
                             headers=headers)

    def get_cleaning_cycle(self, cycle_id, headers):
        return self._request("GET", f"/cleanroom/cleaning-cycles/{cycle_id}", headers=headers)

    def verify_cleaning_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cleanroom/cleaning-cycles/{cycle_id}/verify",
                             {}, headers)

    def reject_cleaning_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cleanroom/cleaning-cycles/{cycle_id}/reject",
                             {}, headers)

    # ------------------------------------------------------------------
    # Customer audits & findings
    # ------------------------------------------------------------------
    def create_audit(self, payload, headers):
        return self._request("POST", "/cleanroom/audits", payload, headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/cleanroom/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/cleanroom/audits/{audit_id}", headers=headers)

    def open_audit(self, audit_id, headers):
        return self._request("POST", f"/cleanroom/audits/{audit_id}/open", {}, headers)

    def create_audit_finding(self, audit_id, payload, headers):
        return self._request("POST", f"/cleanroom/audits/{audit_id}/findings",
                             payload, headers)

    def list_audit_findings(self, audit_id, headers):
        return self._request("GET", f"/cleanroom/audits/{audit_id}/findings",
                             headers=headers)

    def submit_finding_capa(self, finding_id, headers):
        return self._request("POST", f"/cleanroom/audit-findings/{finding_id}/submit-capa",
                             {}, headers)

    def verify_finding_capa(self, finding_id, headers):
        return self._request("POST", f"/cleanroom/audit-findings/{finding_id}/verify-capa",
                             {}, headers)

    def close_audit(self, audit_id, headers):
        return self._request("POST", f"/cleanroom/audits/{audit_id}/close", {}, headers)


api_client = ApiClient()
