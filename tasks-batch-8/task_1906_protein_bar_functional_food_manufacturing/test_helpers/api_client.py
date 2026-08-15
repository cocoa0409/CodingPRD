"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """PRD-specific endpoint methods; transport inherited from the framework."""

    # -- Suppliers (§3.1) ---------------------------------------------------
    def create_supplier(self, payload, headers):
        return self._request("POST", "/mfg/suppliers", payload, headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", "/mfg/suppliers", headers=headers, params=params)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/mfg/suppliers/{supplier_id}", headers=headers)

    def update_supplier(self, supplier_id, payload, headers):
        return self._request("PATCH", f"/mfg/suppliers/{supplier_id}", payload, headers)

    # -- Ingredients (§3.1) -------------------------------------------------
    def create_ingredient(self, payload, headers):
        return self._request("POST", "/mfg/ingredients", payload, headers)

    def list_ingredients(self, headers, params=None):
        return self._request("GET", "/mfg/ingredients", headers=headers, params=params)

    def get_ingredient(self, ingredient_id, headers):
        return self._request("GET", f"/mfg/ingredients/{ingredient_id}", headers=headers)

    # -- Ingredient lots (§3.2) ---------------------------------------------
    def create_ingredient_lot(self, payload, headers):
        return self._request("POST", "/mfg/ingredient-lots", payload, headers)

    def list_ingredient_lots(self, headers, params=None):
        return self._request("GET", "/mfg/ingredient-lots", headers=headers, params=params)

    def get_ingredient_lot(self, lot_id, headers):
        return self._request("GET", f"/mfg/ingredient-lots/{lot_id}", headers=headers)

    def release_lot(self, lot_id, headers):
        return self._request("POST", f"/mfg/ingredient-lots/{lot_id}/release", {}, headers)

    def reject_lot(self, lot_id, headers):
        return self._request("POST", f"/mfg/ingredient-lots/{lot_id}/reject", {}, headers)

    # -- Brand customers (§3.3) ---------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/mfg/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/mfg/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/mfg/customers/{customer_id}", headers=headers)

    # -- Manufacturing agreements (§3.3) ------------------------------------
    def create_agreement(self, payload, headers):
        return self._request("POST", "/mfg/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/mfg/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/mfg/agreements/{agreement_id}", headers=headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/mfg/agreements/{agreement_id}/activate", {}, headers)

    def suspend_agreement(self, agreement_id, headers):
        return self._request("POST", f"/mfg/agreements/{agreement_id}/suspend", {}, headers)

    def resume_agreement(self, agreement_id, headers):
        return self._request("POST", f"/mfg/agreements/{agreement_id}/resume", {}, headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/mfg/agreements/{agreement_id}/terminate", {}, headers)

    def get_agreement_quote(self, agreement_id, cases, headers):
        return self._request(
            "GET", f"/mfg/agreements/{agreement_id}/quote",
            headers=headers, params={"cases": cases},
        )

    # -- Formulas and revisions (§3.4) --------------------------------------
    def create_formula(self, payload, headers):
        return self._request("POST", "/mfg/formulas", payload, headers)

    def list_formulas(self, headers, params=None):
        return self._request("GET", "/mfg/formulas", headers=headers, params=params)

    def get_formula(self, formula_id, headers):
        return self._request("GET", f"/mfg/formulas/{formula_id}", headers=headers)

    def create_revision(self, formula_id, payload, headers):
        return self._request("POST", f"/mfg/formulas/{formula_id}/revisions", payload, headers)

    def list_revisions(self, formula_id, headers, params=None):
        return self._request(
            "GET", f"/mfg/formulas/{formula_id}/revisions", headers=headers, params=params
        )

    def get_revision(self, revision_id, headers):
        return self._request("GET", f"/mfg/revisions/{revision_id}", headers=headers)

    def submit_revision(self, revision_id, headers):
        return self._request("POST", f"/mfg/revisions/{revision_id}/submit", {}, headers)

    def verify_nutrition(self, revision_id, headers):
        return self._request(
            "POST", f"/mfg/revisions/{revision_id}/verify-nutrition", {}, headers
        )

    def send_claim_review(self, revision_id, headers):
        return self._request(
            "POST", f"/mfg/revisions/{revision_id}/send-claim-review", {}, headers
        )

    def approve_revision(self, revision_id, headers):
        return self._request("POST", f"/mfg/revisions/{revision_id}/approve", {}, headers)

    def reject_back_revision(self, revision_id, headers):
        return self._request("POST", f"/mfg/revisions/{revision_id}/reject-back", {}, headers)

    def list_revision_shelf_life_studies(self, revision_id, headers, params=None):
        return self._request(
            "GET", f"/mfg/revisions/{revision_id}/shelf-life-studies",
            headers=headers, params=params,
        )

    def list_revision_claim_reviews(self, revision_id, headers, params=None):
        return self._request(
            "GET", f"/mfg/revisions/{revision_id}/claim-reviews",
            headers=headers, params=params,
        )

    # -- Production lines, slots, day availability (§3.6) -------------------
    def create_line(self, payload, headers):
        return self._request("POST", "/mfg/lines", payload, headers)

    def list_lines(self, headers, params=None):
        return self._request("GET", "/mfg/lines", headers=headers, params=params)

    def get_line(self, line_id, headers):
        return self._request("GET", f"/mfg/lines/{line_id}", headers=headers)

    def list_line_slots(self, line_id, headers, params=None):
        return self._request(
            "GET", f"/mfg/lines/{line_id}/slots", headers=headers, params=params
        )

    def list_line_changeovers(self, line_id, headers, params=None):
        return self._request(
            "GET", f"/mfg/lines/{line_id}/changeovers", headers=headers, params=params
        )

    def get_day_availability(self, line_id, date, headers):
        return self._request(
            "GET", f"/mfg/lines/{line_id}/day-availability",
            headers=headers, params={"date": date},
        )

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"/mfg/slots/{slot_id}", headers=headers)

    # -- Production runs (§3.6, §3.8) ---------------------------------------
    def create_production_run(self, payload, headers):
        return self._request("POST", "/mfg/production-runs", payload, headers)

    def list_production_runs(self, headers, params=None):
        return self._request("GET", "/mfg/production-runs", headers=headers, params=params)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/mfg/production-runs/{run_id}", headers=headers)

    def schedule_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/mfg/production-runs/{run_id}/schedule", payload, headers
        )

    def verify_pre_run(self, run_id, headers):
        return self._request(
            "POST", f"/mfg/production-runs/{run_id}/verify-pre-run", {}, headers
        )

    def start_run(self, run_id, headers):
        return self._request("POST", f"/mfg/production-runs/{run_id}/start", {}, headers)

    def complete_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/mfg/production-runs/{run_id}/complete", payload, headers
        )

    def cancel_run(self, run_id, headers):
        return self._request("POST", f"/mfg/production-runs/{run_id}/cancel", {}, headers)

    def list_run_slots(self, run_id, headers):
        return self._request("GET", f"/mfg/production-runs/{run_id}/slots", headers=headers)

    def list_run_changeovers(self, run_id, headers):
        return self._request(
            "GET", f"/mfg/production-runs/{run_id}/changeovers", headers=headers
        )

    def list_run_retain_samples(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/mfg/production-runs/{run_id}/retain-samples",
            headers=headers, params=params,
        )

    def get_run_lot_release(self, run_id, headers):
        return self._request(
            "GET", f"/mfg/production-runs/{run_id}/lot-release", headers=headers
        )

    def create_retain_sample(self, run_id, payload, headers):
        return self._request(
            "POST", f"/mfg/production-runs/{run_id}/retain-samples", payload, headers
        )

    # -- Changeover events (§3.7) -------------------------------------------
    def get_changeover(self, changeover_id, headers):
        return self._request("GET", f"/mfg/changeovers/{changeover_id}", headers=headers)

    def log_cleaning(self, changeover_id, headers):
        return self._request(
            "POST", f"/mfg/changeovers/{changeover_id}/log-cleaning", {}, headers
        )

    def record_swab(self, changeover_id, payload, headers):
        return self._request(
            "POST", f"/mfg/changeovers/{changeover_id}/record-swab", payload, headers
        )

    def validate_changeover(self, changeover_id, headers):
        return self._request(
            "POST", f"/mfg/changeovers/{changeover_id}/validate", {}, headers
        )

    def fail_changeover(self, changeover_id, headers):
        return self._request("POST", f"/mfg/changeovers/{changeover_id}/fail", {}, headers)

    # -- Shelf-life studies and pulls (§3.9) --------------------------------
    def create_shelf_life_study(self, payload, headers):
        return self._request("POST", "/mfg/shelf-life-studies", payload, headers)

    def get_shelf_life_study(self, study_id, headers):
        return self._request("GET", f"/mfg/shelf-life-studies/{study_id}", headers=headers)

    def terminate_study(self, study_id, headers):
        return self._request(
            "POST", f"/mfg/shelf-life-studies/{study_id}/terminate", {}, headers
        )

    def record_pull(self, study_id, payload, headers):
        return self._request(
            "POST", f"/mfg/shelf-life-studies/{study_id}/pulls", payload, headers
        )

    def list_pulls(self, study_id, headers, params=None):
        return self._request(
            "GET", f"/mfg/shelf-life-studies/{study_id}/pulls",
            headers=headers, params=params,
        )

    def get_projection(self, study_id, headers):
        return self._request(
            "GET", f"/mfg/shelf-life-studies/{study_id}/projection", headers=headers
        )

    # -- Lot releases (§3.8) ------------------------------------------------
    def get_lot_release(self, release_id, headers):
        return self._request("GET", f"/mfg/lot-releases/{release_id}", headers=headers)

    def record_qc(self, release_id, payload, headers):
        return self._request(
            "POST", f"/mfg/lot-releases/{release_id}/record-qc", payload, headers
        )

    def decide_lot_release(self, release_id, payload, headers):
        return self._request(
            "POST", f"/mfg/lot-releases/{release_id}/decide", payload, headers
        )

    # -- Claim reviews (§3.5) -----------------------------------------------
    def create_claim_review(self, payload, headers):
        return self._request("POST", "/mfg/claim-reviews", payload, headers)

    def get_claim_review(self, review_id, headers):
        return self._request("GET", f"/mfg/claim-reviews/{review_id}", headers=headers)

    def start_claim_review(self, review_id, headers):
        return self._request(
            "POST", f"/mfg/claim-reviews/{review_id}/start-review", {}, headers
        )

    def approve_claim_review(self, review_id, headers):
        return self._request("POST", f"/mfg/claim-reviews/{review_id}/approve", {}, headers)

    def request_revision_claim_review(self, review_id, headers):
        return self._request(
            "POST", f"/mfg/claim-reviews/{review_id}/request-revision", {}, headers
        )

    def resubmit_claim_review(self, review_id, headers):
        return self._request(
            "POST", f"/mfg/claim-reviews/{review_id}/resubmit", {}, headers
        )

    # -- Logical clock (§2.4) -----------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/mfg/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
