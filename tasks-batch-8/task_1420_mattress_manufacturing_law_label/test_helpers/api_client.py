"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/plant/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Retailer ---
    def create_retailer(self, payload, headers):
        return self._request("POST", "/plant/retailers", payload, headers)

    def list_retailers(self, headers, params=None):
        return self._request("GET", "/plant/retailers", headers=headers, params=params)

    def get_retailer(self, retailer_id, headers):
        return self._request("GET", f"/plant/retailers/{retailer_id}", headers=headers)

    def create_credit_adjustment(self, retailer_id, payload, headers):
        return self._request(
            "POST", f"/plant/retailers/{retailer_id}/credit-adjustments", payload, headers
        )

    def list_credit_adjustments(self, retailer_id, headers, params=None):
        return self._request(
            "GET", f"/plant/retailers/{retailer_id}/credit-adjustments",
            headers=headers, params=params,
        )

    # --- MattressModel ---
    def create_model(self, payload, headers):
        return self._request("POST", "/plant/models", payload, headers)

    def list_models(self, headers, params=None):
        return self._request("GET", "/plant/models", headers=headers, params=params)

    def get_model(self, model_id, headers):
        return self._request("GET", f"/plant/models/{model_id}", headers=headers)

    def submit_model_for_certification(self, model_id, headers):
        return self._request(
            "POST", f"/plant/models/{model_id}/submit-for-certification", {}, headers
        )

    def return_model_to_draft(self, model_id, headers):
        return self._request(
            "POST", f"/plant/models/{model_id}/return-to-draft", {}, headers
        )

    def certify_model(self, model_id, headers):
        return self._request("POST", f"/plant/models/{model_id}/certify", {}, headers)

    def activate_model(self, model_id, headers):
        return self._request("POST", f"/plant/models/{model_id}/activate", {}, headers)

    def discontinue_model(self, model_id, headers):
        return self._request("POST", f"/plant/models/{model_id}/discontinue", {}, headers)

    # --- BomLine ---
    def create_bom_line(self, model_id, payload, headers):
        return self._request(
            "POST", f"/plant/models/{model_id}/bom-lines", payload, headers
        )

    def list_bom_lines(self, model_id, headers, params=None):
        return self._request(
            "GET", f"/plant/models/{model_id}/bom-lines", headers=headers, params=params
        )

    def update_bom_line(self, model_id, line_id, payload, headers):
        return self._request(
            "PATCH", f"/plant/models/{model_id}/bom-lines/{line_id}", payload, headers
        )

    # --- ComplianceCertificate ---
    def create_certificate(self, model_id, payload, headers):
        return self._request(
            "POST", f"/plant/models/{model_id}/certificates", payload, headers
        )

    def list_certificates(self, model_id, headers, params=None):
        return self._request(
            "GET", f"/plant/models/{model_id}/certificates", headers=headers, params=params
        )

    def approve_certificate(self, model_id, cert_id, headers):
        return self._request(
            "POST", f"/plant/models/{model_id}/certificates/{cert_id}/approve", {}, headers
        )

    def revoke_certificate(self, model_id, cert_id, headers):
        return self._request(
            "POST", f"/plant/models/{model_id}/certificates/{cert_id}/revoke", {}, headers
        )

    # --- StateLawLabelSpec ---
    def create_law_label_spec(self, payload, headers):
        return self._request("POST", "/plant/law-label-specs", payload, headers)

    def list_law_label_specs(self, headers, params=None):
        return self._request("GET", "/plant/law-label-specs", headers=headers, params=params)

    def get_law_label_spec(self, spec_id, headers):
        return self._request("GET", f"/plant/law-label-specs/{spec_id}", headers=headers)

    def list_spec_law_labels(self, spec_id, headers, params=None):
        return self._request(
            "GET", f"/plant/law-label-specs/{spec_id}/law-labels",
            headers=headers, params=params,
        )

    def publish_law_label_spec(self, spec_id, headers):
        return self._request(
            "POST", f"/plant/law-label-specs/{spec_id}/publish", {}, headers
        )

    # --- LawLabel ---
    def create_law_label(self, model_id, payload, headers):
        return self._request(
            "POST", f"/plant/models/{model_id}/law-labels", payload, headers
        )

    def list_model_law_labels(self, model_id, headers, params=None):
        return self._request(
            "GET", f"/plant/models/{model_id}/law-labels", headers=headers, params=params
        )

    def list_law_labels(self, headers, params=None):
        return self._request("GET", "/plant/law-labels", headers=headers, params=params)

    def get_law_label(self, label_id, headers):
        return self._request("GET", f"/plant/law-labels/{label_id}", headers=headers)

    def approve_law_label(self, model_id, label_id, headers):
        return self._request(
            "POST", f"/plant/models/{model_id}/law-labels/{label_id}/approve", {}, headers
        )

    def reject_law_label(self, model_id, label_id, headers):
        return self._request(
            "POST", f"/plant/models/{model_id}/law-labels/{label_id}/reject", {}, headers
        )

    def activate_law_label(self, model_id, label_id, headers):
        return self._request(
            "POST", f"/plant/models/{model_id}/law-labels/{label_id}/activate", {}, headers
        )

    # --- FoamBatch ---
    def create_foam_batch(self, payload, headers):
        return self._request("POST", "/plant/foam-batches", payload, headers)

    def list_foam_batches(self, headers, params=None):
        return self._request("GET", "/plant/foam-batches", headers=headers, params=params)

    def get_foam_batch(self, batch_id, headers):
        return self._request("GET", f"/plant/foam-batches/{batch_id}", headers=headers)

    def start_cure(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/plant/foam-batches/{batch_id}/start-cure", payload, headers
        )

    def certify_cured(self, batch_id, headers):
        return self._request(
            "POST", f"/plant/foam-batches/{batch_id}/certify-cured", {}, headers
        )

    def quarantine_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/plant/foam-batches/{batch_id}/quarantine", {}, headers
        )

    def release_to_cure(self, batch_id, headers):
        return self._request(
            "POST", f"/plant/foam-batches/{batch_id}/release-to-cure", {}, headers
        )

    def scrap_batch(self, batch_id, headers):
        return self._request("POST", f"/plant/foam-batches/{batch_id}/scrap", {}, headers)

    # --- QuiltRun ---
    def create_quilt_run(self, payload, headers):
        return self._request("POST", "/plant/quilt-runs", payload, headers)

    def list_quilt_runs(self, headers, params=None):
        return self._request("GET", "/plant/quilt-runs", headers=headers, params=params)

    def get_quilt_run(self, run_id, headers):
        return self._request("GET", f"/plant/quilt-runs/{run_id}", headers=headers)

    def start_quilt_run(self, run_id, headers):
        return self._request("POST", f"/plant/quilt-runs/{run_id}/start", {}, headers)

    def complete_quilt_run(self, run_id, headers):
        return self._request("POST", f"/plant/quilt-runs/{run_id}/complete", {}, headers)

    def cancel_quilt_run(self, run_id, headers):
        return self._request("POST", f"/plant/quilt-runs/{run_id}/cancel", {}, headers)

    # --- ProductionOrder ---
    def create_production_order(self, payload, headers):
        return self._request("POST", "/plant/production-orders", payload, headers)

    def list_production_orders(self, headers, params=None):
        return self._request(
            "GET", "/plant/production-orders", headers=headers, params=params
        )

    def get_production_order(self, order_id, headers):
        return self._request(
            "GET", f"/plant/production-orders/{order_id}", headers=headers
        )

    def allocate_materials(self, order_id, payload, headers):
        return self._request(
            "POST", f"/plant/production-orders/{order_id}/allocate-materials",
            payload, headers,
        )

    def start_production(self, order_id, headers):
        return self._request(
            "POST", f"/plant/production-orders/{order_id}/start-production", {}, headers
        )

    def complete_production(self, order_id, headers):
        return self._request(
            "POST", f"/plant/production-orders/{order_id}/complete-production", {}, headers
        )

    def qc_pass_order(self, order_id, headers):
        return self._request(
            "POST", f"/plant/production-orders/{order_id}/qc-pass", {}, headers
        )

    def qc_hold_order(self, order_id, headers):
        return self._request(
            "POST", f"/plant/production-orders/{order_id}/qc-hold", {}, headers
        )

    def qc_release_order(self, order_id, headers):
        return self._request(
            "POST", f"/plant/production-orders/{order_id}/qc-release", {}, headers
        )

    def cancel_order(self, order_id, headers):
        return self._request(
            "POST", f"/plant/production-orders/{order_id}/cancel", {}, headers
        )

    # --- MattressUnit ---
    def list_units(self, headers, params=None):
        return self._request("GET", "/plant/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/plant/units/{unit_id}", headers=headers)

    # --- Shipment ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/plant/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/plant/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/plant/shipments/{shipment_id}", headers=headers)

    def dispatch_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/plant/shipments/{shipment_id}/dispatch", {}, headers
        )

    def deliver_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/plant/shipments/{shipment_id}/deliver", {}, headers
        )

    # --- ReturnRequest ---
    def create_return(self, payload, headers):
        return self._request("POST", "/plant/returns", payload, headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/plant/returns", headers=headers, params=params)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/plant/returns/{return_id}", headers=headers)

    def receive_return(self, return_id, headers):
        return self._request("POST", f"/plant/returns/{return_id}/receive", {}, headers)

    def inspect_return(self, return_id, payload, headers):
        return self._request(
            "POST", f"/plant/returns/{return_id}/inspect", payload, headers
        )

    def resolve_return(self, return_id, payload, headers):
        return self._request(
            "POST", f"/plant/returns/{return_id}/resolve", payload, headers
        )

    # --- WarrantyClaim ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/plant/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request(
            "GET", "/plant/warranty-claims", headers=headers, params=params
        )

    def get_warranty_claim(self, claim_id, headers):
        return self._request(
            "GET", f"/plant/warranty-claims/{claim_id}", headers=headers
        )

    def approve_warranty_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/plant/warranty-claims/{claim_id}/approve", {}, headers
        )

    def deny_warranty_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/plant/warranty-claims/{claim_id}/deny", {}, headers
        )

    def pay_warranty_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/plant/warranty-claims/{claim_id}/pay", {}, headers
        )

    # --- RecyclingIntake ---
    def create_recycling_intake(self, payload, headers):
        return self._request("POST", "/plant/recycling-intakes", payload, headers)

    def list_recycling_intakes(self, headers, params=None):
        return self._request(
            "GET", "/plant/recycling-intakes", headers=headers, params=params
        )

    def get_recycling_intake(self, intake_id, headers):
        return self._request(
            "GET", f"/plant/recycling-intakes/{intake_id}", headers=headers
        )

    def finalize_recycling_intake(self, intake_id, payload, headers):
        return self._request(
            "POST", f"/plant/recycling-intakes/{intake_id}/finalize", payload, headers
        )


api_client = ApiClient()
