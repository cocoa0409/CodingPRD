"""API client: one method per endpoint the PRD declares."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------ logical clock
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------ Recipe
    def create_recipe(self, payload, headers):
        return self._request("POST", "/recipes", payload, headers)

    def revise_recipe(self, recipe_id, payload, headers):
        return self._request("POST", f"/recipes/{recipe_id}/revise", payload, headers)

    def get_recipe(self, recipe_id, headers):
        return self._request("GET", f"/recipes/{recipe_id}", headers=headers)

    def list_recipe_label_approvals(self, recipe_id, headers, params=None):
        return self._request(
            "GET", f"/recipes/{recipe_id}/label-approvals", headers=headers, params=params
        )

    # ------------------------------------------------------------ LabelApproval
    def create_label_approval(self, payload, headers):
        return self._request("POST", "/label-approvals", payload, headers)

    def submit_label_approval(self, label_approval_id, headers, payload=None):
        return self._request(
            "POST", f"/label-approvals/{label_approval_id}/submit", payload or {}, headers
        )

    def approve_label_approval(self, label_approval_id, headers, payload=None):
        return self._request(
            "POST", f"/label-approvals/{label_approval_id}/approve", payload or {}, headers
        )

    # ------------------------------------------------------------ ScobyCulture
    def create_scoby_culture(self, payload, headers):
        return self._request("POST", "/scoby-cultures", payload, headers)

    def reverify_scoby_culture(self, culture_id, headers, payload=None):
        return self._request(
            "POST", f"/scoby-cultures/{culture_id}/reverify", payload or {}, headers
        )

    def reverify_result_scoby_culture(self, culture_id, payload, headers):
        return self._request(
            "POST", f"/scoby-cultures/{culture_id}/reverify-result", payload, headers
        )

    def retire_scoby_culture(self, culture_id, payload, headers):
        return self._request(
            "POST", f"/scoby-cultures/{culture_id}/retire", payload or {}, headers
        )

    def get_scoby_culture(self, culture_id, headers):
        return self._request("GET", f"/scoby-cultures/{culture_id}", headers=headers)

    def list_scoby_culture_daughters(self, culture_id, headers, params=None):
        return self._request(
            "GET", f"/scoby-cultures/{culture_id}/daughters", headers=headers, params=params
        )

    # ------------------------------------------------------------ Vessel
    def create_vessel(self, payload, headers):
        return self._request("POST", "/vessels", payload, headers)

    def cip_start_vessel(self, vessel_id, headers, payload=None):
        return self._request("POST", f"/vessels/{vessel_id}/cip-start", payload or {}, headers)

    def cip_complete_vessel(self, vessel_id, headers, payload=None):
        return self._request(
            "POST", f"/vessels/{vessel_id}/cip-complete", payload or {}, headers
        )

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/vessels/{vessel_id}", headers=headers)

    # ------------------------------------------------------------ IngredientLot
    def create_ingredient_lot(self, payload, headers):
        return self._request("POST", "/ingredient-lots", payload, headers)

    def quarantine_ingredient_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/ingredient-lots/{lot_id}/quarantine", payload or {}, headers
        )

    def clear_quarantine_ingredient_lot(self, lot_id, headers, payload=None):
        return self._request(
            "POST", f"/ingredient-lots/{lot_id}/clear-quarantine", payload or {}, headers
        )

    def get_ingredient_lot(self, lot_id, headers):
        return self._request("GET", f"/ingredient-lots/{lot_id}", headers=headers)

    def list_ingredient_lot_uses(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/ingredient-lots/{lot_id}/uses", headers=headers, params=params
        )

    # ------------------------------------------------------------ Batch
    def create_batch(self, payload, headers):
        return self._request("POST", "/batches", payload, headers)

    def advance_batch_to_f2(self, batch_id, headers, payload=None):
        return self._request(
            "POST", f"/batches/{batch_id}/advance-to-f2", payload or {}, headers
        )

    def complete_batch_f2(self, batch_id, headers, payload=None):
        return self._request("POST", f"/batches/{batch_id}/complete-f2", payload or {}, headers)

    def dump_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/batches/{batch_id}/dump", payload or {}, headers)

    def qa_signoff_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/batches/{batch_id}/qa-signoff", payload or {}, headers)

    def create_qa_reading(self, batch_id, payload, headers):
        return self._request("POST", f"/batches/{batch_id}/qa-readings", payload, headers)

    def create_ingredient_use(self, batch_id, payload, headers):
        return self._request("POST", f"/batches/{batch_id}/ingredient-uses", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/batches", headers=headers, params=params)

    def list_batch_qa_readings(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/batches/{batch_id}/qa-readings", headers=headers, params=params
        )

    def list_batch_ingredient_uses(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/batches/{batch_id}/ingredient-uses", headers=headers, params=params
        )

    def void_batch_ingredient_use(self, use_id, payload, headers):
        return self._request(
            "POST", f"/batch-ingredient-uses/{use_id}/void", payload or {}, headers
        )

    # ------------------------------------------------------------ PackagingRun
    def create_packaging_run(self, payload, headers):
        return self._request("POST", "/packaging-runs", payload, headers)

    def add_packaging_run_source(self, run_id, payload, headers):
        return self._request("POST", f"/packaging-runs/{run_id}/sources", payload, headers)

    def start_packaging_run(self, run_id, headers, payload=None):
        return self._request("POST", f"/packaging-runs/{run_id}/start", payload or {}, headers)

    def complete_packaging_run(self, run_id, headers, payload=None):
        return self._request(
            "POST", f"/packaging-runs/{run_id}/complete", payload or {}, headers
        )

    def abort_packaging_run(self, run_id, payload, headers):
        return self._request("POST", f"/packaging-runs/{run_id}/abort", payload or {}, headers)

    def get_packaging_run(self, run_id, headers):
        return self._request("GET", f"/packaging-runs/{run_id}", headers=headers)

    def list_packaging_runs(self, headers, params=None):
        return self._request("GET", "/packaging-runs", headers=headers, params=params)

    # ------------------------------------------------------------ FinishedLot
    def release_finished_lot(self, lot_id, headers, payload=None):
        return self._request("POST", f"/finished-lots/{lot_id}/release", payload or {}, headers)

    def quarantine_finished_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/finished-lots/{lot_id}/quarantine", payload or {}, headers
        )

    def clear_quarantine_finished_lot(self, lot_id, headers, payload=None):
        return self._request(
            "POST", f"/finished-lots/{lot_id}/clear-quarantine", payload or {}, headers
        )

    def recall_finished_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/finished-lots/{lot_id}/recall", payload or {}, headers)

    def get_finished_lot(self, lot_id, headers):
        return self._request("GET", f"/finished-lots/{lot_id}", headers=headers)

    def list_finished_lots(self, headers, params=None):
        return self._request("GET", "/finished-lots", headers=headers, params=params)

    def list_finished_lot_shipment_lines(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/finished-lots/{lot_id}/shipment-lines", headers=headers, params=params
        )

    def list_finished_lot_allocations(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/finished-lots/{lot_id}/allocations", headers=headers, params=params
        )

    def list_finished_lot_recall_notices(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/finished-lots/{lot_id}/recall-notices", headers=headers, params=params
        )

    # ------------------------------------------------------------ Keg
    def create_keg(self, payload, headers):
        return self._request("POST", "/kegs", payload, headers)

    def fill_keg(self, keg_id, payload, headers):
        return self._request("POST", f"/kegs/{keg_id}/fill", payload, headers)

    def tap_keg(self, keg_id, headers, payload=None):
        return self._request("POST", f"/kegs/{keg_id}/tap", payload or {}, headers)

    def untap_keg(self, keg_id, headers, payload=None):
        return self._request("POST", f"/kegs/{keg_id}/untap", payload or {}, headers)

    def issue_keg(self, keg_id, payload, headers):
        return self._request("POST", f"/kegs/{keg_id}/issue", payload, headers)

    def return_keg(self, keg_id, payload, headers):
        return self._request("POST", f"/kegs/{keg_id}/return", payload, headers)

    def get_keg(self, keg_id, headers):
        return self._request("GET", f"/kegs/{keg_id}", headers=headers)

    def list_kegs(self, headers, params=None):
        return self._request("GET", "/kegs", headers=headers, params=params)

    def list_keg_fills(self, keg_id, headers, params=None):
        return self._request("GET", f"/kegs/{keg_id}/fills", headers=headers, params=params)

    # ------------------------------------------------------------ Account
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def activate_account(self, account_id, headers, payload=None):
        return self._request("POST", f"/accounts/{account_id}/activate", payload or {}, headers)

    def credit_hold_account(self, account_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/credit-hold", payload or {}, headers
        )

    def create_account_payment(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/payments", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_account_recall_notices(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/recall-notices", headers=headers, params=params
        )

    # ------------------------------------------------------------ Shipment
    def create_shipment(self, payload, headers):
        return self._request("POST", "/shipments", payload, headers)

    def add_shipment_line(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/lines", payload, headers)

    def confirm_shipment(self, shipment_id, headers, payload=None):
        return self._request("POST", f"/shipments/{shipment_id}/confirm", payload or {}, headers)

    def deliver_shipment(self, shipment_id, headers, payload=None):
        return self._request("POST", f"/shipments/{shipment_id}/deliver", payload or {}, headers)

    def cancel_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/shipments/{shipment_id}/cancel", payload or {}, headers
        )

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def list_shipment_lines(self, shipment_id, headers, params=None):
        return self._request(
            "GET", f"/shipments/{shipment_id}/lines", headers=headers, params=params
        )

    # ------------------------------------------------------------ Subscription
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def pause_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/pause", payload, headers)

    def resume_subscription(self, subscription_id, headers, payload=None):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/resume", payload or {}, headers
        )

    def skip_subscription(self, subscription_id, headers, payload=None):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/skip", payload or {}, headers
        )

    def cancel_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/cancel", payload or {}, headers
        )

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def list_subscription_allocations(self, subscription_id, headers, params=None):
        return self._request(
            "GET",
            f"/subscriptions/{subscription_id}/allocations",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------ Allocations
    def create_subscription_allocation(self, payload, headers):
        return self._request("POST", "/subscription-allocations", payload, headers)

    def ship_subscription_allocation(self, allocation_id, headers, payload=None):
        return self._request(
            "POST", f"/subscription-allocations/{allocation_id}/ship", payload or {}, headers
        )

    # ------------------------------------------------------------ Taproom
    def create_taproom_fill(self, payload, headers):
        return self._request("POST", "/taproom-fills", payload, headers)

    def inspect_taproom_fill(self, fill_id, headers, payload=None):
        return self._request(
            "POST", f"/taproom-fills/{fill_id}/inspect", payload or {}, headers
        )

    def pour_taproom_fill(self, fill_id, headers, payload=None):
        return self._request("POST", f"/taproom-fills/{fill_id}/pour", payload or {}, headers)

    # ------------------------------------------------------------ RecallNotice
    def acknowledge_recall_notice(self, notice_id, payload, headers):
        return self._request(
            "POST", f"/recall-notices/{notice_id}/acknowledge", payload or {}, headers
        )


api_client = ApiClient()
