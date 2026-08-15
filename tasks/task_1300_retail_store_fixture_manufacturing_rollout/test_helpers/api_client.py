"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- RolloutProgram ---
    def create_rollout_program(self, payload, headers):
        return self._request("POST", "/rollout-programs", payload, headers)

    def list_rollout_programs(self, headers, params=None):
        return self._request("GET", "/rollout-programs", params or {}, headers)

    def get_rollout_program(self, program_id, headers):
        return self._request("GET", f"/rollout-programs/{program_id}",
                             headers=headers)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/rollout-programs/{program_id}/activate",
                             {}, headers)

    def initiate_closeout(self, program_id, headers):
        return self._request("POST",
                             f"/rollout-programs/{program_id}/initiate-closeout",
                             {}, headers)

    def finalize_closeout(self, program_id, headers):
        return self._request("POST",
                             f"/rollout-programs/{program_id}/finalize-closeout",
                             {}, headers)

    # --- FixturePrototype ---
    def create_fixture_prototype(self, payload, headers):
        return self._request("POST", "/fixture-prototypes", payload, headers)

    def list_fixture_prototypes(self, headers, params=None):
        return self._request("GET", "/fixture-prototypes", params or {}, headers)

    def get_fixture_prototype(self, prototype_id, headers):
        return self._request("GET", f"/fixture-prototypes/{prototype_id}",
                             headers=headers)

    def patch_fixture_prototype(self, prototype_id, payload, headers):
        return self._request("PATCH", f"/fixture-prototypes/{prototype_id}",
                             payload, headers)

    def submit_prototype_review(self, prototype_id, headers):
        return self._request("POST",
                             f"/fixture-prototypes/{prototype_id}/submit-review",
                             {}, headers)

    def request_value_engineering(self, prototype_id, headers):
        return self._request(
            "POST",
            f"/fixture-prototypes/{prototype_id}/request-value-engineering",
            {}, headers)

    def approve_prototype(self, prototype_id, headers):
        return self._request("POST",
                             f"/fixture-prototypes/{prototype_id}/approve",
                             {}, headers)

    # --- StoreKitConfig ---
    def create_store_kit_config(self, payload, headers):
        return self._request("POST", "/store-kit-configs", payload, headers)

    def list_store_kit_configs(self, headers, params=None):
        return self._request("GET", "/store-kit-configs", params or {}, headers)

    def get_store_kit_config(self, kit_id, headers):
        return self._request("GET", f"/store-kit-configs/{kit_id}",
                             headers=headers)

    def patch_store_kit_config(self, kit_id, payload, headers):
        return self._request("PATCH", f"/store-kit-configs/{kit_id}",
                             payload, headers)

    def freeze_kit(self, kit_id, headers):
        return self._request("POST", f"/store-kit-configs/{kit_id}/freeze",
                             {}, headers)

    def release_kit(self, kit_id, payload, headers):
        return self._request("POST", f"/store-kit-configs/{kit_id}/release",
                             payload, headers)

    def cancel_kit(self, kit_id, headers):
        return self._request("POST", f"/store-kit-configs/{kit_id}/cancel",
                             {}, headers)

    # --- ProductionWave ---
    def create_production_wave(self, payload, headers):
        return self._request("POST", "/production-waves", payload, headers)

    def list_production_waves(self, headers, params=None):
        return self._request("GET", "/production-waves", params or {}, headers)

    def get_production_wave(self, wave_id, headers):
        return self._request("GET", f"/production-waves/{wave_id}",
                             headers=headers)

    def commit_wave(self, wave_id, headers):
        return self._request("POST", f"/production-waves/{wave_id}/commit",
                             {}, headers)

    def complete_wave(self, wave_id, headers):
        return self._request("POST", f"/production-waves/{wave_id}/complete",
                             {}, headers)

    def cancel_wave(self, wave_id, headers):
        return self._request("POST", f"/production-waves/{wave_id}/cancel",
                             {}, headers)

    # --- StagingReservation ---
    def create_staging_reservation(self, payload, headers):
        return self._request("POST", "/staging-reservations", payload, headers)

    def list_staging_reservations(self, headers, params=None):
        return self._request("GET", "/staging-reservations", params or {},
                             headers)

    def get_staging_reservation(self, reservation_id, headers):
        return self._request("GET", f"/staging-reservations/{reservation_id}",
                             headers=headers)

    def release_staging_reservation(self, reservation_id, headers):
        return self._request("POST",
                             f"/staging-reservations/{reservation_id}/release",
                             {}, headers)

    # --- InstallDelivery ---
    def create_install_delivery(self, payload, headers):
        return self._request("POST", "/install-deliveries", payload, headers)

    def list_install_deliveries(self, headers, params=None):
        return self._request("GET", "/install-deliveries", params or {},
                             headers)

    def get_install_delivery(self, delivery_id, headers):
        return self._request("GET", f"/install-deliveries/{delivery_id}",
                             headers=headers)

    def dispatch_delivery(self, delivery_id, headers):
        return self._request("POST",
                             f"/install-deliveries/{delivery_id}/dispatch",
                             {}, headers)

    def confirm_delivery(self, delivery_id, headers):
        return self._request("POST",
                             f"/install-deliveries/{delivery_id}/confirm-delivery",
                             {}, headers)

    def fail_delivery(self, delivery_id, headers):
        return self._request("POST", f"/install-deliveries/{delivery_id}/fail",
                             {}, headers)

    # --- DamageClaim ---
    def create_damage_claim(self, payload, headers):
        return self._request("POST", "/damage-claims", payload, headers)

    def list_damage_claims(self, headers, params=None):
        return self._request("GET", "/damage-claims", params or {}, headers)

    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"/damage-claims/{claim_id}",
                             headers=headers)

    def approve_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/approve",
                             {}, headers)

    def reject_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/reject",
                             {}, headers)

    # --- InstallSignoff ---
    def create_install_signoff(self, payload, headers):
        return self._request("POST", "/install-signoffs", payload, headers)

    def list_install_signoffs(self, headers, params=None):
        return self._request("GET", "/install-signoffs", params or {}, headers)

    def get_install_signoff(self, signoff_id, headers):
        return self._request("GET", f"/install-signoffs/{signoff_id}",
                             headers=headers)

    def approve_install_signoff(self, signoff_id, headers):
        return self._request("POST", f"/install-signoffs/{signoff_id}/approve",
                             {}, headers)

    def reject_install_signoff(self, signoff_id, payload, headers):
        return self._request("POST", f"/install-signoffs/{signoff_id}/reject",
                             payload, headers)

    def resubmit_install_signoff(self, signoff_id, payload, headers):
        return self._request("POST",
                             f"/install-signoffs/{signoff_id}/resubmit",
                             payload, headers)

    # --- AtticStockLedger ---
    def list_attic_stock_ledgers(self, headers, params=None):
        return self._request("GET", "/attic-stock-ledgers", params or {},
                             headers)

    def get_attic_stock_ledger(self, ledger_id, headers):
        return self._request("GET", f"/attic-stock-ledgers/{ledger_id}",
                             headers=headers)

    def adjust_attic_stock_ledger(self, ledger_id, payload, headers):
        return self._request("POST",
                             f"/attic-stock-ledgers/{ledger_id}/adjust",
                             payload, headers)

    def dispose_attic_stock_ledger(self, ledger_id, payload, headers):
        return self._request("POST",
                             f"/attic-stock-ledgers/{ledger_id}/dispose",
                             payload, headers)

    # --- Logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
