"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Program & clock ---
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/programs/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/programs/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/programs/members", headers=headers, params=params)

    def disenroll_member(self, member_id, payload, headers):
        return self._request("POST", f"/programs/members/{member_id}/disenroll", payload, headers)

    # --- Providers ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/programs/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/programs/providers/{provider_id}", headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/programs/providers", headers=headers, params=params)

    def suspend_provider(self, provider_id, headers):
        return self._request("POST", f"/programs/providers/{provider_id}/suspend", {}, headers)

    # --- Submitters ---
    def create_submitter(self, payload, headers):
        return self._request("POST", "/programs/submitters", payload, headers)

    def get_submitter(self, submitter_id, headers):
        return self._request("GET", f"/programs/submitters/{submitter_id}", headers=headers)

    def list_submitters(self, headers, params=None):
        return self._request("GET", "/programs/submitters", headers=headers, params=params)

    def suspend_submitter(self, submitter_id, headers):
        return self._request("POST", f"/programs/submitters/{submitter_id}/suspend", {}, headers)

    # --- Submission cycles ---
    def create_cycle(self, payload, headers):
        return self._request("POST", "/programs/cycles", payload, headers)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/programs/cycles/{cycle_id}", headers=headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/programs/cycles", headers=headers, params=params)

    def close_cycle(self, cycle_id, headers):
        return self._request("POST", f"/programs/cycles/{cycle_id}/close", {}, headers)

    def compute_risk_scores(self, cycle_id, headers):
        return self._request("POST", f"/programs/cycles/{cycle_id}/compute-risk-scores", {}, headers)

    def request_extension(self, cycle_id, payload, headers):
        return self._request("POST", f"/programs/cycles/{cycle_id}/request-extension", payload, headers)

    def approve_extension(self, cycle_id, headers):
        return self._request("POST", f"/programs/cycles/{cycle_id}/approve-extension", {}, headers)

    def deny_extension(self, cycle_id, headers):
        return self._request("POST", f"/programs/cycles/{cycle_id}/deny-extension", {}, headers)

    # --- Capitation rate schedules ---
    def create_rate_schedule(self, payload, headers):
        return self._request("POST", "/programs/rate-schedules", payload, headers)

    def get_rate_schedule(self, schedule_id, headers):
        return self._request("GET", f"/programs/rate-schedules/{schedule_id}", headers=headers)

    def list_rate_schedules(self, headers, params=None):
        return self._request("GET", "/programs/rate-schedules", headers=headers, params=params)

    # --- Encounters ---
    def create_encounter(self, payload, headers):
        return self._request("POST", "/programs/encounters", payload, headers)

    def get_encounter(self, encounter_id, headers):
        return self._request("GET", f"/programs/encounters/{encounter_id}", headers=headers)

    def list_encounters(self, headers, params=None):
        return self._request("GET", "/programs/encounters", headers=headers, params=params)

    def list_encounter_lines(self, encounter_id, headers, params=None):
        return self._request("GET", f"/programs/encounters/{encounter_id}/lines", headers=headers, params=params)

    def list_encounter_findings(self, encounter_id, headers, params=None):
        return self._request("GET", f"/programs/encounters/{encounter_id}/findings", headers=headers, params=params)

    def validate_encounter(self, encounter_id, headers):
        return self._request("POST", f"/programs/encounters/{encounter_id}/validate", {}, headers)

    def correct_encounter(self, encounter_id, payload, headers):
        return self._request("POST", f"/programs/encounters/{encounter_id}/correct", payload, headers)

    def replace_encounter(self, encounter_id, payload, headers):
        return self._request("POST", f"/programs/encounters/{encounter_id}/replace", payload, headers)

    def void_encounter(self, encounter_id, payload, headers):
        return self._request("POST", f"/programs/encounters/{encounter_id}/void", payload, headers)

    # --- Submission batches ---
    def create_batch(self, payload, headers):
        return self._request("POST", "/programs/batches", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/programs/batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/programs/batches", headers=headers, params=params)

    def add_encounter_to_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/programs/batches/{batch_id}/encounters", payload, headers)

    def seal_batch(self, batch_id, headers):
        return self._request("POST", f"/programs/batches/{batch_id}/seal", {}, headers)

    def unseal_batch(self, batch_id, headers):
        return self._request("POST", f"/programs/batches/{batch_id}/unseal", {}, headers)

    def transmit_batch(self, batch_id, headers):
        return self._request("POST", f"/programs/batches/{batch_id}/transmit", {}, headers)

    def acknowledge_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/programs/batches/{batch_id}/acknowledge", payload, headers)

    def reconcile_batch(self, batch_id, headers):
        return self._request("POST", f"/programs/batches/{batch_id}/reconcile", {}, headers)

    # --- Audits ---
    def create_audit(self, payload, headers):
        return self._request("POST", "/programs/audits", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/programs/audits/{audit_id}", headers=headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/programs/audits", headers=headers, params=params)

    def determine_audit(self, audit_id, headers):
        return self._request("POST", f"/programs/audits/{audit_id}/determine", {}, headers)

    # --- Penalties ---
    def get_penalty(self, penalty_id, headers):
        return self._request("GET", f"/programs/penalties/{penalty_id}", headers=headers)

    def list_penalties(self, headers, params=None):
        return self._request("GET", "/programs/penalties", headers=headers, params=params)

    def appeal_penalty(self, penalty_id, headers):
        return self._request("POST", f"/programs/penalties/{penalty_id}/appeal", {}, headers)

    def resolve_penalty(self, penalty_id, payload, headers):
        return self._request("POST", f"/programs/penalties/{penalty_id}/resolve", payload, headers)

    def pay_penalty(self, penalty_id, headers):
        return self._request("POST", f"/programs/penalties/{penalty_id}/pay", {}, headers)

    # --- Capitation statements ---
    def create_statement(self, payload, headers):
        return self._request("POST", "/programs/capitation-statements", payload, headers)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/programs/capitation-statements/{statement_id}", headers=headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/programs/capitation-statements", headers=headers, params=params)

    def reconcile_statement(self, statement_id, headers):
        return self._request("POST", f"/programs/capitation-statements/{statement_id}/reconcile", {}, headers)

    # --- Risk snapshots ---
    def get_risk_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/programs/risk-snapshots/{snapshot_id}", headers=headers)

    def list_risk_snapshots(self, headers, params=None):
        return self._request("GET", "/programs/risk-snapshots", headers=headers, params=params)

    # --- Provider scorecards ---
    def get_scorecard(self, scorecard_id, headers):
        return self._request("GET", f"/programs/scorecards/{scorecard_id}", headers=headers)

    def list_scorecards(self, headers, params=None):
        return self._request("GET", "/programs/scorecards", headers=headers, params=params)

    def acknowledge_scorecard_remediation(self, scorecard_id, headers):
        return self._request("POST", f"/programs/scorecards/{scorecard_id}/acknowledge-remediation", {}, headers)


api_client = ApiClient()
