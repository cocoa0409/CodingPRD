"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers
        )

    # --- Species / care-sheet ---
    def create_species(self, payload, headers):
        return self._request("POST", "/species", payload, headers=headers)

    def get_species(self, species_id, headers):
        return self._request("GET", f"/species/{species_id}", headers=headers)

    def list_species(self, headers, params=None):
        return self._request("GET", "/species", headers=headers, params=params)

    def get_care_sheet(self, species_id, headers):
        return self._request("GET", f"/species/{species_id}/care-sheet", headers=headers)

    # --- Animal + quarantine/health ---
    def create_animal(self, payload, headers):
        return self._request("POST", "/animals", payload, headers=headers)

    def get_animal(self, animal_id, headers):
        return self._request("GET", f"/animals/{animal_id}", headers=headers)

    def list_animals(self, headers, params=None):
        return self._request("GET", "/animals", headers=headers, params=params)

    def start_quarantine(self, animal_id, headers):
        return self._request("POST", f"/animals/{animal_id}/start-quarantine", {}, headers=headers)

    def mark_deceased(self, animal_id, headers, payload=None):
        return self._request(
            "POST", f"/animals/{animal_id}/mark-deceased", payload or {}, headers=headers
        )

    def get_animal_quarantine_record(self, animal_id, headers):
        return self._request("GET", f"/animals/{animal_id}/quarantine-record", headers=headers)

    def get_quarantine_record(self, qr_id, headers):
        return self._request("GET", f"/quarantine-records/{qr_id}", headers=headers)

    def add_health_check(self, qr_id, payload, headers):
        return self._request(
            "POST", f"/quarantine-records/{qr_id}/health-checks", payload, headers=headers
        )

    def clear_quarantine(self, qr_id, headers):
        return self._request("POST", f"/quarantine-records/{qr_id}/clear", {}, headers=headers)

    # --- Customer / permit ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers=headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def create_permit(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/customers/{customer_id}/permits", payload, headers=headers
        )

    def list_customer_permits(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/customers/{customer_id}/permits", headers=headers, params=params
        )

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def verify_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/verify", {}, headers=headers)

    def revoke_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/revoke", {}, headers=headers)

    # --- Sale ---
    def create_sale(self, payload, headers):
        return self._request("POST", "/sales", payload, headers=headers)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/sales/{sale_id}", headers=headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/sales", headers=headers, params=params)

    def confirm_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/confirm", {}, headers=headers)

    def fulfill_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/fulfill", {}, headers=headers)

    def void_sale(self, sale_id, headers):
        return self._request("POST", f"/sales/{sale_id}/void", {}, headers=headers)

    # --- Warranty ---
    def create_warranty_claim(self, sale_id, payload, headers):
        return self._request(
            "POST", f"/sales/{sale_id}/warranty-claims", payload, headers=headers
        )

    def get_warranty_claim(self, wc_id, headers):
        return self._request("GET", f"/warranty-claims/{wc_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def approve_claim(self, wc_id, headers):
        return self._request("POST", f"/warranty-claims/{wc_id}/approve", {}, headers=headers)

    def deny_claim(self, wc_id, headers, payload=None):
        return self._request(
            "POST", f"/warranty-claims/{wc_id}/deny", payload or {}, headers=headers
        )

    def resolve_claim(self, wc_id, payload, headers):
        return self._request(
            "POST", f"/warranty-claims/{wc_id}/resolve", payload, headers=headers
        )

    # --- Feeder inventory / subscription ---
    def create_feeder_batch(self, payload, headers):
        return self._request("POST", "/feeder-batches", payload, headers=headers)

    def get_feeder_batch(self, batch_id, headers):
        return self._request("GET", f"/feeder-batches/{batch_id}", headers=headers)

    def list_feeder_batches(self, headers, params=None):
        return self._request("GET", "/feeder-batches", headers=headers, params=params)

    def create_subscription(self, payload, headers):
        return self._request("POST", "/feeder-subscriptions", payload, headers=headers)

    def get_subscription(self, sub_id, headers):
        return self._request("GET", f"/feeder-subscriptions/{sub_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/feeder-subscriptions", headers=headers, params=params)

    def pause_subscription(self, sub_id, headers):
        return self._request("POST", f"/feeder-subscriptions/{sub_id}/pause", {}, headers=headers)

    def resume_subscription(self, sub_id, headers):
        return self._request("POST", f"/feeder-subscriptions/{sub_id}/resume", {}, headers=headers)

    def cancel_subscription(self, sub_id, headers):
        return self._request("POST", f"/feeder-subscriptions/{sub_id}/cancel", {}, headers=headers)

    def create_shipment(self, sub_id, headers):
        return self._request(
            "POST", f"/feeder-subscriptions/{sub_id}/shipments", {}, headers=headers
        )

    def list_subscription_shipments(self, sub_id, headers, params=None):
        return self._request(
            "GET", f"/feeder-subscriptions/{sub_id}/shipments", headers=headers, params=params
        )

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def reverse_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/reverse", {}, headers=headers)

    # --- Habitat build / special order ---
    def create_habitat_build(self, payload, headers):
        return self._request("POST", "/habitat-builds", payload, headers=headers)

    def get_habitat_build(self, hb_id, headers):
        return self._request("GET", f"/habitat-builds/{hb_id}", headers=headers)

    def list_habitat_builds(self, headers, params=None):
        return self._request("GET", "/habitat-builds", headers=headers, params=params)

    def pay_deposit(self, hb_id, headers):
        return self._request("POST", f"/habitat-builds/{hb_id}/pay-deposit", {}, headers=headers)

    def start_build(self, hb_id, headers):
        return self._request("POST", f"/habitat-builds/{hb_id}/start", {}, headers=headers)

    def create_change_order(self, hb_id, payload, headers):
        return self._request(
            "POST", f"/habitat-builds/{hb_id}/change-orders", payload, headers=headers
        )

    def approve_change(self, hb_id, headers):
        return self._request(
            "POST", f"/habitat-builds/{hb_id}/approve-change", {}, headers=headers
        )

    def schedule_install(self, hb_id, payload, headers):
        return self._request(
            "POST", f"/habitat-builds/{hb_id}/schedule-install", payload, headers=headers
        )

    def deliver_build(self, hb_id, headers):
        return self._request("POST", f"/habitat-builds/{hb_id}/deliver", {}, headers=headers)

    def cancel_build(self, hb_id, headers):
        return self._request("POST", f"/habitat-builds/{hb_id}/cancel", {}, headers=headers)

    # --- Expo / event ---
    def create_expo(self, payload, headers):
        return self._request("POST", "/expos", payload, headers=headers)

    def get_expo(self, expo_id, headers):
        return self._request("GET", f"/expos/{expo_id}", headers=headers)

    def list_expos(self, headers, params=None):
        return self._request("GET", "/expos", headers=headers, params=params)

    def open_expo(self, expo_id, headers):
        return self._request("POST", f"/expos/{expo_id}/open", {}, headers=headers)

    def close_expo(self, expo_id, headers):
        return self._request("POST", f"/expos/{expo_id}/close", {}, headers=headers)

    def cancel_expo(self, expo_id, headers):
        return self._request("POST", f"/expos/{expo_id}/cancel", {}, headers=headers)

    def create_expo_assignment(self, expo_id, payload, headers):
        return self._request(
            "POST", f"/expos/{expo_id}/assignments", payload, headers=headers
        )

    def list_expo_assignments(self, expo_id, headers, params=None):
        return self._request(
            "GET", f"/expos/{expo_id}/assignments", headers=headers, params=params
        )

    def get_expo_assignment(self, assignment_id, headers):
        return self._request("GET", f"/expo-assignments/{assignment_id}", headers=headers)

    def list_all_expo_assignments(self, headers, params=None):
        return self._request("GET", "/expo-assignments", headers=headers, params=params)

    # --- Recall ---
    def create_recall(self, payload, headers):
        return self._request("POST", "/recalls", payload, headers=headers)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/recalls/{recall_id}", headers=headers)

    def list_recalls(self, headers, params=None):
        return self._request("GET", "/recalls", headers=headers, params=params)

    def close_recall(self, recall_id, headers):
        return self._request("POST", f"/recalls/{recall_id}/close", {}, headers=headers)


api_client = ApiClient()
