"""API client: one method per endpoint defined in the PRD (§4). All paths are
mounted under the /340b prefix."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- CoveredEntity ----
    def create_covered_entity(self, payload, headers):
        return self._request("POST", "/340b/covered-entities", payload, headers)

    def get_covered_entity(self, ce_id, headers):
        return self._request("GET", f"/340b/covered-entities/{ce_id}", headers=headers)

    def list_covered_entities(self, headers, params=None):
        return self._request("GET", "/340b/covered-entities", headers=headers, params=params)

    def approve_covered_entity(self, ce_id, headers):
        return self._request("POST", f"/340b/covered-entities/{ce_id}/approve", {}, headers)

    def deny_covered_entity(self, ce_id, headers):
        return self._request("POST", f"/340b/covered-entities/{ce_id}/deny", {}, headers)

    def flag_recert_covered_entity(self, ce_id, headers):
        return self._request("POST", f"/340b/covered-entities/{ce_id}/flag-recert", {}, headers)

    def recertify_covered_entity(self, ce_id, headers):
        return self._request("POST", f"/340b/covered-entities/{ce_id}/recertify", {}, headers)

    def terminate_covered_entity(self, ce_id, headers):
        return self._request("POST", f"/340b/covered-entities/{ce_id}/terminate", {}, headers)

    # ---- ChildSite ----
    def create_child_site(self, ce_id, payload, headers):
        return self._request("POST", f"/340b/covered-entities/{ce_id}/child-sites", payload, headers)

    def list_child_sites(self, ce_id, headers, params=None):
        return self._request("GET", f"/340b/covered-entities/{ce_id}/child-sites", headers=headers, params=params)

    def get_child_site(self, cs_id, headers):
        return self._request("GET", f"/340b/child-sites/{cs_id}", headers=headers)

    # ---- Prescriber ----
    def create_prescriber(self, ce_id, payload, headers):
        return self._request("POST", f"/340b/covered-entities/{ce_id}/prescribers", payload, headers)

    def list_prescribers(self, headers, params=None):
        return self._request("GET", "/340b/prescribers", headers=headers, params=params)

    def get_prescriber(self, presc_id, headers):
        return self._request("GET", f"/340b/prescribers/{presc_id}", headers=headers)

    # ---- Patient ----
    def create_patient(self, ce_id, payload, headers):
        return self._request("POST", f"/340b/covered-entities/{ce_id}/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/340b/patients", headers=headers, params=params)

    def get_patient(self, pat_id, headers):
        return self._request("GET", f"/340b/patients/{pat_id}", headers=headers)

    # ---- DrugProduct + CeilingPriceRecord ----
    def create_drug_product(self, payload, headers):
        return self._request("POST", "/340b/drug-products", payload, headers)

    def get_drug_product(self, dp_id, headers):
        return self._request("GET", f"/340b/drug-products/{dp_id}", headers=headers)

    def create_ceiling_price(self, dp_id, payload, headers):
        return self._request("POST", f"/340b/drug-products/{dp_id}/ceiling-prices", payload, headers)

    def list_ceiling_prices(self, dp_id, headers, params=None):
        return self._request("GET", f"/340b/drug-products/{dp_id}/ceiling-prices", headers=headers, params=params)

    def get_effective_ceiling(self, dp_id, headers, params=None):
        return self._request("GET", f"/340b/drug-products/{dp_id}/ceiling-prices/effective", headers=headers, params=params)

    def reconcile_drug_product(self, dp_id, payload, headers):
        return self._request("POST", f"/340b/drug-products/{dp_id}/reconcile", payload, headers)

    # ---- ContractPharmacyArrangement ----
    def create_contract_pharmacy(self, ce_id, payload, headers):
        return self._request("POST", f"/340b/covered-entities/{ce_id}/contract-pharmacies", payload, headers)

    def list_contract_pharmacies(self, ce_id, headers, params=None):
        return self._request("GET", f"/340b/covered-entities/{ce_id}/contract-pharmacies", headers=headers, params=params)

    def get_contract_pharmacy(self, cp_id, headers):
        return self._request("GET", f"/340b/contract-pharmacies/{cp_id}", headers=headers)

    def suspend_contract_pharmacy(self, cp_id, headers):
        return self._request("POST", f"/340b/contract-pharmacies/{cp_id}/suspend", {}, headers)

    def reactivate_contract_pharmacy(self, cp_id, headers):
        return self._request("POST", f"/340b/contract-pharmacies/{cp_id}/reactivate", {}, headers)

    def terminate_contract_pharmacy(self, cp_id, headers):
        return self._request("POST", f"/340b/contract-pharmacies/{cp_id}/terminate", {}, headers)

    # ---- Accumulator ----
    def create_accumulator(self, ce_id, payload, headers):
        return self._request("POST", f"/340b/covered-entities/{ce_id}/accumulators", payload, headers)

    def list_ce_accumulators(self, ce_id, headers, params=None):
        return self._request("GET", f"/340b/covered-entities/{ce_id}/accumulators", headers=headers, params=params)

    def list_accumulators(self, headers, params=None):
        return self._request("GET", "/340b/accumulators", headers=headers, params=params)

    def get_accumulator(self, acc_id, headers):
        return self._request("GET", f"/340b/accumulators/{acc_id}", headers=headers)

    def replenish_accumulator(self, acc_id, payload, headers):
        return self._request("POST", f"/340b/accumulators/{acc_id}/replenish", payload, headers)

    # ---- PrescriptionDispense ----
    def create_dispense(self, payload, headers):
        return self._request("POST", "/340b/dispenses", payload, headers)

    def get_dispense(self, disp_id, headers):
        return self._request("GET", f"/340b/dispenses/{disp_id}", headers=headers)

    def list_dispenses(self, headers, params=None):
        return self._request("GET", "/340b/dispenses", headers=headers, params=params)

    def reverse_dispense(self, disp_id, headers):
        return self._request("POST", f"/340b/dispenses/{disp_id}/reverse", {}, headers)

    def reinstate_dispense(self, disp_id, headers):
        return self._request("POST", f"/340b/dispenses/{disp_id}/reinstate", {}, headers)

    # ---- MedicaidClaim ----
    def create_medicaid_claim(self, disp_id, payload, headers):
        return self._request("POST", f"/340b/dispenses/{disp_id}/medicaid-claims", payload, headers)

    def list_medicaid_claims(self, disp_id, headers, params=None):
        return self._request("GET", f"/340b/dispenses/{disp_id}/medicaid-claims", headers=headers, params=params)

    # ---- AuditFinding ----
    def create_audit_finding(self, payload, headers):
        return self._request("POST", "/340b/audit-findings", payload, headers)

    def create_self_disclosure(self, ce_id, payload, headers):
        return self._request("POST", f"/340b/covered-entities/{ce_id}/self-disclosures", payload, headers)

    def get_audit_finding(self, af_id, headers):
        return self._request("GET", f"/340b/audit-findings/{af_id}", headers=headers)

    def list_ce_audit_findings(self, ce_id, headers, params=None):
        return self._request("GET", f"/340b/covered-entities/{ce_id}/audit-findings", headers=headers, params=params)

    def list_audit_findings(self, headers, params=None):
        return self._request("GET", "/340b/audit-findings", headers=headers, params=params)

    def start_review_audit_finding(self, af_id, headers):
        return self._request("POST", f"/340b/audit-findings/{af_id}/start-review", {}, headers)

    def dispute_audit_finding(self, af_id, headers):
        return self._request("POST", f"/340b/audit-findings/{af_id}/dispute", {}, headers)

    def resolve_audit_finding(self, af_id, headers):
        return self._request("POST", f"/340b/audit-findings/{af_id}/resolve", {}, headers)

    def dismiss_audit_finding(self, af_id, headers):
        return self._request("POST", f"/340b/audit-findings/{af_id}/dismiss", {}, headers)

    def create_finding_repayment(self, af_id, headers):
        return self._request("POST", f"/340b/audit-findings/{af_id}/repayments", {}, headers)

    # ---- RepaymentObligation ----
    def get_repayment_obligation(self, obl_id, headers):
        return self._request("GET", f"/340b/repayment-obligations/{obl_id}", headers=headers)

    def list_ce_repayment_obligations(self, ce_id, headers, params=None):
        return self._request("GET", f"/340b/covered-entities/{ce_id}/repayment-obligations", headers=headers, params=params)

    def list_repayment_obligations(self, headers, params=None):
        return self._request("GET", "/340b/repayment-obligations", headers=headers, params=params)

    def remit_repayment(self, obl_id, payload, headers):
        return self._request("POST", f"/340b/repayment-obligations/{obl_id}/remit", payload, headers)

    def waive_repayment(self, obl_id, headers):
        return self._request("POST", f"/340b/repayment-obligations/{obl_id}/waive", {}, headers)

    # ---- PurchaseOrder ----
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/340b/purchase-orders", payload, headers)

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/340b/purchase-orders/{po_id}", headers=headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/340b/purchase-orders", headers=headers, params=params)


api_client = ApiClient()
