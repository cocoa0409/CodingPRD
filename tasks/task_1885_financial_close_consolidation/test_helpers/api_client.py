"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock / subledger seed (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/close/_clock/set_current_utc", payload, headers)

    def seed_subledger(self, payload, headers):
        return self._request("POST", "/close/_subledger/seed", payload, headers)

    # --- ClosePeriod ---
    def create_period(self, payload, headers):
        return self._request("POST", "/close/periods", payload, headers)

    def get_period(self, period_id, headers):
        return self._request("GET", f"/close/periods/{period_id}", headers=headers)

    def list_periods(self, headers, params=None):
        return self._request("GET", "/close/periods", headers=headers, params=params)

    def open_period(self, period_id, headers):
        return self._request("POST", f"/close/periods/{period_id}/open", headers=headers)

    def soft_lock_period(self, period_id, payload, headers):
        return self._request("POST", f"/close/periods/{period_id}/soft-lock", payload, headers)

    def hard_lock_period(self, period_id, payload, headers):
        return self._request("POST", f"/close/periods/{period_id}/hard-lock", payload, headers)

    def reopen_period(self, period_id, payload, headers):
        return self._request("POST", f"/close/periods/{period_id}/reopen", payload, headers)

    def finalize_period(self, period_id, payload, headers):
        return self._request("POST", f"/close/periods/{period_id}/finalize", payload, headers)

    def consolidate_period(self, period_id, headers):
        return self._request("POST", f"/close/periods/{period_id}/consolidate", headers=headers)

    def list_period_events(self, period_id, headers, params=None):
        return self._request("GET", f"/close/periods/{period_id}/events", headers=headers, params=params)

    # --- Entity ---
    def create_entity(self, payload, headers):
        return self._request("POST", "/close/entities", payload, headers)

    def get_entity(self, entity_id, headers):
        return self._request("GET", f"/close/entities/{entity_id}", headers=headers)

    def list_entities(self, headers, params=None):
        return self._request("GET", "/close/entities", headers=headers, params=params)

    def list_entity_counterparty_lines(self, entity_id, headers):
        return self._request("GET", f"/close/entities/{entity_id}/journal-entry-lines", headers=headers)

    # --- EntityPeriod ---
    def get_entity_period(self, entity_period_id, headers):
        return self._request("GET", f"/close/entity-periods/{entity_period_id}", headers=headers)

    def list_entity_periods(self, headers, params=None):
        return self._request("GET", "/close/entity-periods", headers=headers, params=params)

    def translate_entity_period(self, entity_period_id, headers):
        return self._request("POST", f"/close/entity-periods/{entity_period_id}/translate", headers=headers)

    def mark_entity_period_reconciled(self, entity_period_id, headers):
        return self._request("POST", f"/close/entity-periods/{entity_period_id}/mark-reconciled", headers=headers)

    def mark_entity_period_ready(self, entity_period_id, headers):
        return self._request("POST", f"/close/entity-periods/{entity_period_id}/ready", headers=headers)

    def list_entity_period_events(self, entity_period_id, headers, params=None):
        return self._request("GET", f"/close/entity-periods/{entity_period_id}/events", headers=headers, params=params)

    def list_entity_period_tasks(self, entity_period_id, headers):
        return self._request("GET", f"/close/entity-periods/{entity_period_id}/tasks", headers=headers)

    # --- CloseTask ---
    def create_task(self, period_id, payload, headers):
        return self._request("POST", f"/close/periods/{period_id}/tasks", payload, headers)

    def get_task(self, task_id, headers):
        return self._request("GET", f"/close/tasks/{task_id}", headers=headers)

    def list_period_tasks(self, period_id, headers, params=None):
        return self._request("GET", f"/close/periods/{period_id}/tasks", headers=headers, params=params)

    def start_task(self, task_id, headers):
        return self._request("POST", f"/close/tasks/{task_id}/start", headers=headers)

    def complete_task(self, task_id, headers):
        return self._request("POST", f"/close/tasks/{task_id}/complete", headers=headers)

    def waive_task(self, task_id, headers):
        return self._request("POST", f"/close/tasks/{task_id}/waive", headers=headers)

    def unstart_task(self, task_id, headers):
        return self._request("POST", f"/close/tasks/{task_id}/unstart", headers=headers)

    # --- SubledgerCutoff ---
    def create_subledger_cutoff(self, entity_period_id, payload, headers):
        return self._request("POST", f"/close/entity-periods/{entity_period_id}/subledger-cutoffs", payload, headers)

    def list_subledger_cutoffs(self, entity_period_id, headers):
        return self._request("GET", f"/close/entity-periods/{entity_period_id}/subledger-cutoffs", headers=headers)

    def get_subledger_cutoff(self, cutoff_id, headers):
        return self._request("GET", f"/close/subledger-cutoffs/{cutoff_id}", headers=headers)

    def cut_subledger_cutoff(self, cutoff_id, headers):
        return self._request("POST", f"/close/subledger-cutoffs/{cutoff_id}/cut", headers=headers)

    def confirm_subledger_cutoff(self, cutoff_id, headers):
        return self._request("POST", f"/close/subledger-cutoffs/{cutoff_id}/confirm", headers=headers)

    # --- AccrualEstimate ---
    def create_accrual(self, entity_period_id, payload, headers):
        return self._request("POST", f"/close/entity-periods/{entity_period_id}/accruals", payload, headers)

    def list_accruals_for_entity_period(self, entity_period_id, headers):
        return self._request("GET", f"/close/entity-periods/{entity_period_id}/accruals", headers=headers)

    def list_accruals_for_cutoff(self, cutoff_id, headers):
        return self._request("GET", f"/close/subledger-cutoffs/{cutoff_id}/accruals", headers=headers)

    def true_up_accrual(self, accrual_id, payload, headers):
        return self._request("POST", f"/close/accruals/{accrual_id}/true-up", payload, headers)

    def recompute_accrual(self, accrual_id, headers):
        return self._request("POST", f"/close/accruals/{accrual_id}/recompute", headers=headers)

    def post_accrual(self, accrual_id, headers):
        return self._request("POST", f"/close/accruals/{accrual_id}/post", headers=headers)

    # --- JournalEntry + lines ---
    def create_journal_entry(self, entity_period_id, payload, headers):
        return self._request("POST", f"/close/entity-periods/{entity_period_id}/journal-entries", payload, headers)

    def get_journal_entry(self, je_id, headers):
        return self._request("GET", f"/close/journal-entries/{je_id}", headers=headers)

    def list_journal_entries(self, entity_period_id, headers, params=None):
        return self._request("GET", f"/close/entity-periods/{entity_period_id}/journal-entries", headers=headers, params=params)

    def list_journal_entry_lines(self, je_id, headers):
        return self._request("GET", f"/close/journal-entries/{je_id}/lines", headers=headers)

    def submit_journal_entry(self, je_id, headers):
        return self._request("POST", f"/close/journal-entries/{je_id}/submit", headers=headers)

    def approve_journal_entry(self, je_id, headers):
        return self._request("POST", f"/close/journal-entries/{je_id}/approve", headers=headers)

    def post_journal_entry(self, je_id, headers):
        return self._request("POST", f"/close/journal-entries/{je_id}/post", headers=headers)

    def reject_journal_entry(self, je_id, payload, headers):
        return self._request("POST", f"/close/journal-entries/{je_id}/reject", payload, headers)

    def rework_journal_entry(self, je_id, headers):
        return self._request("POST", f"/close/journal-entries/{je_id}/rework", headers=headers)

    # --- SupportingDocument ---
    def attach_document(self, je_id, payload, headers):
        return self._request("POST", f"/close/journal-entries/{je_id}/documents", payload, headers)

    def list_documents(self, je_id, headers):
        return self._request("GET", f"/close/journal-entries/{je_id}/documents", headers=headers)

    def verify_document(self, doc_id, headers):
        return self._request("POST", f"/close/documents/{doc_id}/verify", headers=headers)

    def reject_document(self, doc_id, headers):
        return self._request("POST", f"/close/documents/{doc_id}/reject", headers=headers)

    # --- Reconciliation + items ---
    def create_reconciliation(self, entity_period_id, payload, headers):
        return self._request("POST", f"/close/entity-periods/{entity_period_id}/reconciliations", payload, headers)

    def list_reconciliations(self, entity_period_id, headers, params=None):
        return self._request("GET", f"/close/entity-periods/{entity_period_id}/reconciliations", headers=headers, params=params)

    def get_reconciliation(self, recon_id, headers):
        return self._request("GET", f"/close/reconciliations/{recon_id}", headers=headers)

    def review_reconciliation(self, recon_id, headers):
        return self._request("POST", f"/close/reconciliations/{recon_id}/review", headers=headers)

    def clear_reconciliation(self, recon_id, headers):
        return self._request("POST", f"/close/reconciliations/{recon_id}/clear", headers=headers)

    def return_reconciliation(self, recon_id, headers):
        return self._request("POST", f"/close/reconciliations/{recon_id}/return", headers=headers)

    def create_reconciling_item(self, recon_id, payload, headers):
        return self._request("POST", f"/close/reconciliations/{recon_id}/items", payload, headers)

    def list_reconciling_items(self, recon_id, headers):
        return self._request("GET", f"/close/reconciliations/{recon_id}/items", headers=headers)

    def list_reconciliation_flux(self, recon_id, headers):
        return self._request("GET", f"/close/reconciliations/{recon_id}/flux", headers=headers)

    def resolve_reconciling_item(self, item_id, headers):
        return self._request("POST", f"/close/reconciling-items/{item_id}/resolve", headers=headers)

    def write_off_reconciling_item(self, item_id, headers):
        return self._request("POST", f"/close/reconciling-items/{item_id}/write-off", headers=headers)

    # --- ElimPair ---
    def create_elim_pair(self, period_id, payload, headers):
        return self._request("POST", f"/close/periods/{period_id}/elim-pairs", payload, headers)

    def list_elim_pairs_for_period(self, period_id, headers, params=None):
        return self._request("GET", f"/close/periods/{period_id}/elim-pairs", headers=headers, params=params)

    def list_elim_pairs_for_entity_period(self, entity_period_id, headers):
        return self._request("GET", f"/close/entity-periods/{entity_period_id}/elim-pairs", headers=headers)

    def match_elim_pair(self, pair_id, headers):
        return self._request("POST", f"/close/elim-pairs/{pair_id}/match", headers=headers)

    def eliminate_elim_pair(self, pair_id, headers):
        return self._request("POST", f"/close/elim-pairs/{pair_id}/eliminate", headers=headers)

    def dispute_elim_pair(self, pair_id, headers):
        return self._request("POST", f"/close/elim-pairs/{pair_id}/dispute", headers=headers)

    # --- FluxExplanation ---
    def create_flux(self, entity_period_id, payload, headers):
        return self._request("POST", f"/close/entity-periods/{entity_period_id}/flux", payload, headers)

    def list_flux(self, entity_period_id, headers, params=None):
        return self._request("GET", f"/close/entity-periods/{entity_period_id}/flux", headers=headers, params=params)

    def explain_flux(self, flux_id, payload, headers):
        return self._request("POST", f"/close/flux/{flux_id}/explain", payload, headers)

    def accept_flux(self, flux_id, headers):
        return self._request("POST", f"/close/flux/{flux_id}/accept", headers=headers)

    def reject_flux(self, flux_id, headers):
        return self._request("POST", f"/close/flux/{flux_id}/reject", headers=headers)

    def reopen_flux(self, flux_id, headers):
        return self._request("POST", f"/close/flux/{flux_id}/reopen", headers=headers)

    # --- FxRate ---
    def create_fx_rate(self, period_id, payload, headers):
        return self._request("POST", f"/close/periods/{period_id}/fx-rates", payload, headers)

    def list_fx_rates(self, period_id, headers, params=None):
        return self._request("GET", f"/close/periods/{period_id}/fx-rates", headers=headers, params=params)


api_client = ApiClient()
