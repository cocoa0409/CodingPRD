"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Networks ---
    def create_network(self, payload, headers):
        return self._request("POST", "/networks", payload, headers)

    def list_networks(self, headers, params=None):
        return self._request("GET", "/networks", headers=headers, params=params)

    def get_network(self, network_id, headers):
        return self._request("GET", f"/networks/{network_id}", headers=headers)

    def retire_network(self, network_id, headers):
        return self._request("POST", f"/networks/{network_id}/retire", headers=headers)

    def list_network_contracts(self, network_id, headers):
        return self._request("GET", f"/networks/{network_id}/contracts", headers=headers)

    # --- Medicare benchmarks ---
    def create_benchmark(self, payload, headers):
        return self._request("POST", "/medicare-benchmarks", payload, headers)

    def list_benchmarks(self, headers, params=None):
        return self._request("GET", "/medicare-benchmarks", headers=headers, params=params)

    def get_benchmark(self, benchmark_id, headers):
        return self._request("GET", f"/medicare-benchmarks/{benchmark_id}", headers=headers)

    def publish_benchmark(self, benchmark_id, headers):
        return self._request("POST", f"/medicare-benchmarks/{benchmark_id}/publish", headers=headers)

    # --- Rate parity rules ---
    def create_rate_parity_rule(self, payload, headers):
        return self._request("POST", "/rate-parity-rules", payload, headers)

    def list_rate_parity_rules(self, headers, params=None):
        return self._request("GET", "/rate-parity-rules", headers=headers, params=params)

    def get_rate_parity_rule(self, rule_id, headers):
        return self._request("GET", f"/rate-parity-rules/{rule_id}", headers=headers)

    # --- Providers ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/providers", payload, headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}", headers=headers)

    def create_contract(self, provider_id, payload, headers):
        return self._request("POST", f"/providers/{provider_id}/contracts", payload, headers)

    def list_provider_contracts(self, provider_id, headers):
        return self._request("GET", f"/providers/{provider_id}/contracts", headers=headers)

    # --- Contracts lifecycle ---
    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def begin_negotiation(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/begin-negotiation", headers=headers)

    def submit_for_signature(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/submit-for-signature", headers=headers)

    def counter_offer(self, contract_id, headers, payload=None):
        return self._request("POST", f"/contracts/{contract_id}/counter-offer", payload or {}, headers)

    def sign_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/sign", headers=headers)

    def begin_configuration(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/begin-configuration", headers=headers)

    def begin_testing(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/begin-testing", headers=headers)

    def return_to_configuration(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/return-to-configuration", headers=headers)

    def mark_ready(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/mark-ready", headers=headers)

    def approve_go_live(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/approve-go-live", headers=headers)

    # --- Contract versions ---
    def create_contract_version(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/versions", payload, headers)

    def list_contract_versions(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/versions", headers=headers)

    def get_contract_version(self, version_id, headers):
        return self._request("GET", f"/contract-versions/{version_id}", headers=headers)

    def load_version(self, version_id, headers):
        return self._request("POST", f"/contract-versions/{version_id}/load", headers=headers)

    def validate_version(self, version_id, headers):
        return self._request("POST", f"/contract-versions/{version_id}/validate", headers=headers)

    # --- Fee schedule entries ---
    def create_fee_schedule_entry(self, version_id, payload, headers):
        return self._request("POST", f"/contract-versions/{version_id}/fee-schedule-entries", payload, headers)

    def list_version_entries(self, version_id, headers):
        return self._request("GET", f"/contract-versions/{version_id}/fee-schedule-entries", headers=headers)

    def list_entries(self, headers, params=None):
        return self._request("GET", "/fee-schedule-entries", headers=headers, params=params)

    def get_entry(self, entry_id, headers):
        return self._request("GET", f"/fee-schedule-entries/{entry_id}", headers=headers)

    def map_benchmark(self, entry_id, headers):
        return self._request("POST", f"/fee-schedule-entries/{entry_id}/map-benchmark", headers=headers)

    # --- Carve-outs ---
    def create_carve_out(self, version_id, payload, headers):
        return self._request("POST", f"/contract-versions/{version_id}/carve-outs", payload, headers)

    def list_carve_outs(self, version_id, headers):
        return self._request("GET", f"/contract-versions/{version_id}/carve-outs", headers=headers)

    def get_carve_out(self, carve_out_id, headers):
        return self._request("GET", f"/carve-outs/{carve_out_id}", headers=headers)

    # --- Simulation batches & claims ---
    def create_simulation_batch(self, version_id, payload, headers):
        return self._request("POST", f"/contract-versions/{version_id}/simulation-batches", payload, headers)

    def list_simulation_batches(self, version_id, headers):
        return self._request("GET", f"/contract-versions/{version_id}/simulation-batches", headers=headers)

    def get_simulation_batch(self, batch_id, headers):
        return self._request("GET", f"/simulation-batches/{batch_id}", headers=headers)

    def create_simulation_claim(self, batch_id, payload, headers):
        return self._request("POST", f"/simulation-batches/{batch_id}/claims", payload, headers)

    def list_simulation_claims(self, batch_id, headers):
        return self._request("GET", f"/simulation-batches/{batch_id}/claims", headers=headers)

    def price_batch(self, batch_id, headers):
        return self._request("POST", f"/simulation-batches/{batch_id}/price", headers=headers)

    def score_batch(self, batch_id, headers):
        return self._request("POST", f"/simulation-batches/{batch_id}/score", headers=headers)

    def reopen_batch(self, batch_id, headers):
        return self._request("POST", f"/simulation-batches/{batch_id}/reopen", headers=headers)

    # --- Paid claims ledger ---
    def create_paid_claim(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/paid-claims", payload, headers)

    def list_paid_claims(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/paid-claims", headers=headers)

    def get_paid_claim(self, paid_claim_id, headers):
        return self._request("GET", f"/paid-claims/{paid_claim_id}", headers=headers)

    # --- Retro adjustment runs & adjustments ---
    def list_retro_runs(self, version_id, headers):
        return self._request("GET", f"/contract-versions/{version_id}/retro-adjustment-runs", headers=headers)

    def get_retro_run(self, run_id, headers):
        return self._request("GET", f"/retro-adjustment-runs/{run_id}", headers=headers)

    def compute_retro_run(self, run_id, headers):
        return self._request("POST", f"/retro-adjustment-runs/{run_id}/compute", headers=headers)

    def finalize_retro_run(self, run_id, headers):
        return self._request("POST", f"/retro-adjustment-runs/{run_id}/finalize", headers=headers)

    def void_retro_run(self, run_id, headers):
        return self._request("POST", f"/retro-adjustment-runs/{run_id}/void", headers=headers)

    def list_run_adjustments(self, run_id, headers):
        return self._request("GET", f"/retro-adjustment-runs/{run_id}/adjustments", headers=headers)

    def list_adjustments(self, headers, params=None):
        return self._request("GET", "/retro-adjustments", headers=headers, params=params)

    def get_adjustment(self, adjustment_id, headers):
        return self._request("GET", f"/retro-adjustments/{adjustment_id}", headers=headers)

    def approve_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/retro-adjustments/{adjustment_id}/approve", headers=headers)

    def reject_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/retro-adjustments/{adjustment_id}/reject", headers=headers)

    def settle_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/retro-adjustments/{adjustment_id}/settle", headers=headers)

    # --- Termination notices & continuity of care ---
    def create_termination_notice(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/termination-notices", payload, headers)

    def list_termination_notices(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/termination-notices", headers=headers)

    def get_termination_notice(self, notice_id, headers):
        return self._request("GET", f"/termination-notices/{notice_id}", headers=headers)

    def issue_notice(self, notice_id, headers):
        return self._request("POST", f"/termination-notices/{notice_id}/issue", headers=headers)

    def finalize_notice(self, notice_id, headers):
        return self._request("POST", f"/termination-notices/{notice_id}/finalize", headers=headers)

    def rescind_notice(self, notice_id, headers):
        return self._request("POST", f"/termination-notices/{notice_id}/rescind", headers=headers)

    def create_continuity_case(self, notice_id, payload, headers):
        return self._request("POST", f"/termination-notices/{notice_id}/continuity-cases", payload, headers)

    def list_continuity_cases(self, notice_id, headers):
        return self._request("GET", f"/termination-notices/{notice_id}/continuity-cases", headers=headers)

    def get_continuity_case(self, case_id, headers):
        return self._request("GET", f"/continuity-cases/{case_id}", headers=headers)

    def notify_case(self, case_id, headers):
        return self._request("POST", f"/continuity-cases/{case_id}/notify", headers=headers)

    def activate_coverage(self, case_id, headers):
        return self._request("POST", f"/continuity-cases/{case_id}/activate-coverage", headers=headers)

    def complete_case(self, case_id, headers):
        return self._request("POST", f"/continuity-cases/{case_id}/complete", headers=headers)

    def expire_case(self, case_id, headers):
        return self._request("POST", f"/continuity-cases/{case_id}/expire", headers=headers)

    # --- Audit ---
    def list_audit_events(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/audit-events", headers=headers)

    def get_audit_event(self, event_id, headers):
        return self._request("GET", f"/audit-events/{event_id}", headers=headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
