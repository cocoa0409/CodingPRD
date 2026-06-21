"""API client: one method per endpoint defined in the PRD (Genetic & Molecular Lab).

All paths are mounted under /lab. The base _request() is inherited from
GenericApiClient; it handles the success/error envelope.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/lab/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    def get_clock(self, headers):
        return self._request("GET", "/lab/_clock", headers=headers)

    # ---- Gene ----
    def create_gene(self, payload, headers):
        return self._request("POST", "/lab/genes", payload, headers=headers)

    def list_genes(self, headers, params=None):
        return self._request("GET", "/lab/genes", headers=headers, params=params)

    def get_gene(self, gene_id, headers):
        return self._request("GET", f"/lab/genes/{gene_id}", headers=headers)

    def list_gene_panel_genes(self, gene_id, headers, params=None):
        return self._request("GET", f"/lab/genes/{gene_id}/panel-genes",
                             headers=headers, params=params)

    # ---- Panel ----
    def create_panel(self, payload, headers):
        return self._request("POST", "/lab/panels", payload, headers=headers)

    def list_panels(self, headers, params=None):
        return self._request("GET", "/lab/panels", headers=headers, params=params)

    def get_panel(self, panel_id, headers):
        return self._request("GET", f"/lab/panels/{panel_id}", headers=headers)

    def publish_panel(self, panel_id, headers):
        return self._request("POST", f"/lab/panels/{panel_id}/publish", {}, headers=headers)

    def add_panel_gene(self, panel_id, payload, headers):
        return self._request("POST", f"/lab/panels/{panel_id}/panel-genes",
                             payload, headers=headers)

    def list_panel_panel_genes(self, panel_id, headers, params=None):
        return self._request("GET", f"/lab/panels/{panel_id}/panel-genes",
                             headers=headers, params=params)

    def get_panel_gene(self, panel_gene_id, headers):
        return self._request("GET", f"/lab/panel-genes/{panel_gene_id}", headers=headers)

    def list_panel_genes(self, headers, params=None):
        return self._request("GET", "/lab/panel-genes", headers=headers, params=params)

    # ---- Provider ----
    def create_provider(self, payload, headers):
        return self._request("POST", "/lab/providers", payload, headers=headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/lab/providers/{provider_id}", headers=headers)

    # ---- TestOrder ----
    def create_test_order(self, payload, headers):
        return self._request("POST", "/lab/test-orders", payload, headers=headers)

    def list_test_orders(self, headers, params=None):
        return self._request("GET", "/lab/test-orders", headers=headers, params=params)

    def get_test_order(self, order_id, headers):
        return self._request("GET", f"/lab/test-orders/{order_id}", headers=headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/lab/test-orders/{order_id}/cancel",
                             payload, headers=headers)

    # ---- Requisition ----
    def create_requisition(self, order_id, payload, headers):
        return self._request("POST", f"/lab/test-orders/{order_id}/requisition",
                             payload, headers=headers)

    def list_order_requisitions(self, order_id, headers, params=None):
        return self._request("GET", f"/lab/test-orders/{order_id}/requisition",
                             headers=headers, params=params)

    def get_requisition(self, requisition_id, headers):
        return self._request("GET", f"/lab/requisitions/{requisition_id}", headers=headers)

    def list_requisitions(self, headers, params=None):
        return self._request("GET", "/lab/requisitions", headers=headers, params=params)

    def submit_requisition(self, order_id, headers):
        return self._request("POST", f"/lab/test-orders/{order_id}/requisition/submit",
                             {}, headers=headers)

    # ---- Consent ----
    def create_consent(self, order_id, payload, headers):
        return self._request("POST", f"/lab/test-orders/{order_id}/consents",
                             payload, headers=headers)

    def list_order_consents(self, order_id, headers, params=None):
        return self._request("GET", f"/lab/test-orders/{order_id}/consents",
                             headers=headers, params=params)

    def get_consent(self, consent_id, headers):
        return self._request("GET", f"/lab/consents/{consent_id}", headers=headers)

    def list_consents(self, headers, params=None):
        return self._request("GET", "/lab/consents", headers=headers, params=params)

    def sign_consent(self, order_id, consent_id, headers):
        return self._request("POST",
                             f"/lab/test-orders/{order_id}/consents/{consent_id}/sign",
                             {}, headers=headers)

    def revoke_consent(self, order_id, consent_id, headers):
        return self._request("POST",
                             f"/lab/test-orders/{order_id}/consents/{consent_id}/revoke",
                             {}, headers=headers)

    # ---- Specimen ----
    def create_specimen(self, order_id, payload, headers):
        return self._request("POST", f"/lab/test-orders/{order_id}/specimens",
                             payload, headers=headers)

    def list_order_specimens(self, order_id, headers, params=None):
        return self._request("GET", f"/lab/test-orders/{order_id}/specimens",
                             headers=headers, params=params)

    def get_specimen(self, specimen_id, headers):
        return self._request("GET", f"/lab/specimens/{specimen_id}", headers=headers)

    def list_specimens(self, headers, params=None):
        return self._request("GET", "/lab/specimens", headers=headers, params=params)

    def accession_specimen(self, order_id, specimen_id, headers):
        return self._request("POST",
                             f"/lab/test-orders/{order_id}/specimens/{specimen_id}/accession",
                             {}, headers=headers)

    # ---- Sequencing / Classification ----
    def start_sequencing(self, order_id, headers):
        return self._request("POST", f"/lab/test-orders/{order_id}/sequencing/start",
                             {}, headers=headers)

    def create_variant(self, order_id, payload, headers):
        return self._request("POST", f"/lab/test-orders/{order_id}/variants",
                             payload, headers=headers)

    def list_order_variants(self, order_id, headers, params=None):
        return self._request("GET", f"/lab/test-orders/{order_id}/variants",
                             headers=headers, params=params)

    def get_variant(self, variant_id, headers):
        return self._request("GET", f"/lab/variants/{variant_id}", headers=headers)

    def list_variants(self, headers, params=None):
        return self._request("GET", "/lab/variants", headers=headers, params=params)

    def classify_variant(self, order_id, variant_id, payload, headers):
        return self._request("POST",
                             f"/lab/test-orders/{order_id}/variants/{variant_id}/classify",
                             payload, headers=headers)

    def complete_classification(self, order_id, headers):
        return self._request("POST",
                             f"/lab/test-orders/{order_id}/classification/complete",
                             {}, headers=headers)

    # ---- Report ----
    def create_report(self, order_id, headers):
        return self._request("POST", f"/lab/test-orders/{order_id}/reports",
                             {}, headers=headers)

    def list_order_reports(self, order_id, headers, params=None):
        return self._request("GET", f"/lab/test-orders/{order_id}/reports",
                             headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/lab/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/lab/reports", headers=headers, params=params)

    def sign_out_report(self, order_id, report_id, headers):
        return self._request("POST",
                             f"/lab/test-orders/{order_id}/reports/{report_id}/sign-out",
                             {}, headers=headers)

    def amend_report(self, order_id, report_id, payload, headers):
        return self._request("POST",
                             f"/lab/test-orders/{order_id}/reports/{report_id}/amend",
                             payload, headers=headers)

    # ---- Billing ----
    def list_order_billing(self, order_id, headers, params=None):
        return self._request("GET", f"/lab/test-orders/{order_id}/billing",
                             headers=headers, params=params)

    def get_billing(self, billing_id, headers):
        return self._request("GET", f"/lab/billings/{billing_id}", headers=headers)

    def list_billings(self, headers, params=None):
        return self._request("GET", "/lab/billings", headers=headers, params=params)

    def auth_decision(self, order_id, payload, headers):
        return self._request("POST", f"/lab/test-orders/{order_id}/billing/auth-decision",
                             payload, headers=headers)

    def convert_self_pay(self, order_id, headers):
        return self._request("POST", f"/lab/test-orders/{order_id}/billing/convert-self-pay",
                             {}, headers=headers)

    def collect(self, order_id, payload, headers):
        return self._request("POST", f"/lab/test-orders/{order_id}/billing/collect",
                             payload, headers=headers)

    # ---- Sequencer (instrument) ----
    def create_sequencer(self, payload, headers):
        return self._request("POST", "/lab/sequencers", payload, headers=headers)

    def list_sequencers(self, headers, params=None):
        return self._request("GET", "/lab/sequencers", headers=headers, params=params)

    def get_sequencer(self, sequencer_id, headers):
        return self._request("GET", f"/lab/sequencers/{sequencer_id}", headers=headers)

    def schedule_run(self, sequencer_id, payload, headers):
        return self._request("POST", f"/lab/sequencers/{sequencer_id}/runs",
                             payload, headers=headers)

    def list_sequencer_runs(self, sequencer_id, headers, params=None):
        return self._request("GET", f"/lab/sequencers/{sequencer_id}/runs",
                             headers=headers, params=params)

    def get_run(self, run_id, headers):
        return self._request("GET", f"/lab/sequencer-runs/{run_id}", headers=headers)

    def list_runs(self, headers, params=None):
        return self._request("GET", "/lab/sequencer-runs", headers=headers, params=params)

    def start_run(self, sequencer_id, run_id, headers):
        return self._request("POST", f"/lab/sequencers/{sequencer_id}/runs/{run_id}/start",
                             {}, headers=headers)

    def finish_run(self, sequencer_id, run_id, headers):
        return self._request("POST", f"/lab/sequencers/{sequencer_id}/runs/{run_id}/finish",
                             {}, headers=headers)

    def abort_run(self, sequencer_id, run_id, headers):
        return self._request("POST", f"/lab/sequencers/{sequencer_id}/runs/{run_id}/abort",
                             {}, headers=headers)

    # ---- GeneticCounselorProfile ----
    def create_counselor(self, payload, headers):
        return self._request("POST", "/lab/counselors", payload, headers=headers)

    def list_counselors(self, headers, params=None):
        return self._request("GET", "/lab/counselors", headers=headers, params=params)

    def get_counselor(self, counselor_id, headers):
        return self._request("GET", f"/lab/counselors/{counselor_id}", headers=headers)

    # ---- CounselorReferral ----
    def create_referral(self, order_id, payload, headers):
        return self._request("POST", f"/lab/test-orders/{order_id}/referrals",
                             payload, headers=headers)

    def list_order_referrals(self, order_id, headers, params=None):
        return self._request("GET", f"/lab/test-orders/{order_id}/referrals",
                             headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/lab/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/lab/referrals", headers=headers, params=params)

    def schedule_referral(self, order_id, referral_id, payload, headers):
        return self._request("POST",
                             f"/lab/test-orders/{order_id}/referrals/{referral_id}/schedule",
                             payload, headers=headers)

    def complete_referral(self, order_id, referral_id, headers):
        return self._request("POST",
                             f"/lab/test-orders/{order_id}/referrals/{referral_id}/complete",
                             {}, headers=headers)

    def cancel_referral(self, order_id, referral_id, headers):
        return self._request("POST",
                             f"/lab/test-orders/{order_id}/referrals/{referral_id}/cancel",
                             {}, headers=headers)


api_client = ApiClient()
