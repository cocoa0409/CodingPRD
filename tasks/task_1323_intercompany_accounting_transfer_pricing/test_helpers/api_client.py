"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/tp/_clock/set_current_utc", payload, headers)

    # --- FiscalYear ---
    def create_fiscal_year(self, payload, headers):
        return self._request("POST", "/tp/fiscal_years", payload, headers)

    def get_fiscal_year(self, fiscal_year_id, headers):
        return self._request("GET", f"/tp/fiscal_years/{fiscal_year_id}",
                             headers=headers)

    def begin_closing(self, fiscal_year_id, headers):
        return self._request("POST",
                             f"/tp/fiscal_years/{fiscal_year_id}/begin_closing",
                             headers=headers)

    def close_fiscal_year(self, fiscal_year_id, headers):
        return self._request("POST", f"/tp/fiscal_years/{fiscal_year_id}/close",
                             headers=headers)

    # --- LegalEntity ---
    def create_legal_entity(self, payload, headers):
        return self._request("POST", "/tp/legal_entities", payload, headers)

    def get_legal_entity(self, legal_entity_id, headers):
        return self._request("GET", f"/tp/legal_entities/{legal_entity_id}",
                             headers=headers)

    def deactivate_legal_entity(self, legal_entity_id, headers):
        return self._request("POST",
                             f"/tp/legal_entities/{legal_entity_id}/deactivate",
                             headers=headers)

    # --- IntercompanyAgreement ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/tp/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/tp/agreements/{agreement_id}",
                             headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/tp/agreements", headers=headers,
                             params=params)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/tp/agreements/{agreement_id}/activate",
                             headers=headers)

    def start_amendment(self, agreement_id, payload, headers):
        return self._request("POST",
                             f"/tp/agreements/{agreement_id}/start_amendment",
                             payload, headers)

    def approve_amendment(self, agreement_id, headers):
        return self._request("POST",
                             f"/tp/agreements/{agreement_id}/approve_amendment",
                             headers=headers)

    def discard_amendment(self, agreement_id, headers):
        return self._request("POST",
                             f"/tp/agreements/{agreement_id}/discard_amendment",
                             headers=headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST",
                             f"/tp/agreements/{agreement_id}/terminate",
                             headers=headers)

    # --- ICTransaction ---
    def create_transaction(self, payload, headers):
        return self._request("POST", "/tp/transactions", payload, headers)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/tp/transactions/{transaction_id}",
                             headers=headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/tp/transactions", headers=headers,
                             params=params)

    def match_transaction(self, transaction_id, headers):
        return self._request("POST",
                             f"/tp/transactions/{transaction_id}/match",
                             headers=headers)

    # --- TrueUpRun ---
    def create_true_up_run(self, payload, headers):
        return self._request("POST", "/tp/true_up_runs", payload, headers)

    def get_true_up_run(self, true_up_run_id, headers):
        return self._request("GET", f"/tp/true_up_runs/{true_up_run_id}",
                             headers=headers)

    def list_true_up_runs(self, headers, params=None):
        return self._request("GET", "/tp/true_up_runs", headers=headers,
                             params=params)

    def compute_true_up_run(self, true_up_run_id, headers):
        return self._request("POST",
                             f"/tp/true_up_runs/{true_up_run_id}/compute",
                             headers=headers)

    def recompute_true_up_run(self, true_up_run_id, headers):
        return self._request("POST",
                             f"/tp/true_up_runs/{true_up_run_id}/recompute",
                             headers=headers)

    def approve_true_up_run(self, true_up_run_id, headers):
        return self._request("POST",
                             f"/tp/true_up_runs/{true_up_run_id}/approve",
                             headers=headers)

    def post_true_up_run(self, true_up_run_id, headers):
        return self._request("POST", f"/tp/true_up_runs/{true_up_run_id}/post",
                             headers=headers)

    # --- BenchmarkingStudy ---
    def create_benchmarking_study(self, payload, headers):
        return self._request("POST", "/tp/benchmarking_studies", payload,
                             headers)

    def get_benchmarking_study(self, benchmarking_study_id, headers):
        return self._request("GET",
                             f"/tp/benchmarking_studies/{benchmarking_study_id}",
                             headers=headers)

    def list_benchmarking_studies(self, headers, params=None):
        return self._request("GET", "/tp/benchmarking_studies", headers=headers,
                             params=params)

    def approve_benchmarking_study(self, benchmarking_study_id, headers):
        return self._request(
            "POST",
            f"/tp/benchmarking_studies/{benchmarking_study_id}/approve",
            headers=headers)

    def refresh_benchmarking_study(self, benchmarking_study_id, payload,
                                   headers):
        return self._request(
            "POST",
            f"/tp/benchmarking_studies/{benchmarking_study_id}/refresh",
            payload, headers)

    # --- DocPackage ---
    def create_doc_package(self, payload, headers):
        return self._request("POST", "/tp/doc_packages", payload, headers)

    def get_doc_package(self, doc_package_id, headers):
        return self._request("GET", f"/tp/doc_packages/{doc_package_id}",
                             headers=headers)

    def list_doc_packages(self, headers, params=None):
        return self._request("GET", "/tp/doc_packages", headers=headers,
                             params=params)

    def submit_doc_package(self, doc_package_id, headers):
        return self._request("POST",
                             f"/tp/doc_packages/{doc_package_id}/submit",
                             headers=headers)

    def approve_doc_package(self, doc_package_id, headers):
        return self._request("POST",
                             f"/tp/doc_packages/{doc_package_id}/approve",
                             headers=headers)

    def file_doc_package(self, doc_package_id, headers):
        return self._request("POST", f"/tp/doc_packages/{doc_package_id}/file",
                             headers=headers)

    # --- AuditCase ---
    def create_audit_case(self, payload, headers):
        return self._request("POST", "/tp/audit_cases", payload, headers)

    def get_audit_case(self, audit_case_id, headers):
        return self._request("GET", f"/tp/audit_cases/{audit_case_id}",
                             headers=headers)

    def list_audit_cases(self, headers, params=None):
        return self._request("GET", "/tp/audit_cases", headers=headers,
                             params=params)

    def attach_doc(self, audit_case_id, payload, headers):
        return self._request("POST",
                             f"/tp/audit_cases/{audit_case_id}/attach_doc",
                             payload, headers)

    def submit_response(self, audit_case_id, headers):
        return self._request("POST",
                             f"/tp/audit_cases/{audit_case_id}/submit_response",
                             headers=headers)

    def resolve_audit_case(self, audit_case_id, headers):
        return self._request("POST",
                             f"/tp/audit_cases/{audit_case_id}/resolve",
                             headers=headers)

    # --- CashPool ---
    def create_cash_pool(self, payload, headers):
        return self._request("POST", "/tp/cash_pools", payload, headers)

    def get_cash_pool(self, cash_pool_id, headers):
        return self._request("GET", f"/tp/cash_pools/{cash_pool_id}",
                             headers=headers)

    def list_cash_pools(self, headers, params=None):
        return self._request("GET", "/tp/cash_pools", headers=headers,
                             params=params)

    def post_sweeps(self, cash_pool_id, payload, headers):
        return self._request("POST", f"/tp/cash_pools/{cash_pool_id}/sweeps",
                             payload, headers)

    def begin_netting(self, cash_pool_id, headers):
        return self._request("POST",
                             f"/tp/cash_pools/{cash_pool_id}/begin_netting",
                             headers=headers)

    def settle_cash_pool(self, cash_pool_id, headers):
        return self._request("POST", f"/tp/cash_pools/{cash_pool_id}/settle",
                             headers=headers)


api_client = ApiClient()
