"""API client: one method per endpoint defined in the PRD endpoint table.

Every path is mounted under `/seafood-ops` per PRD §1.
"""
from prd_bench_local_runner.testing import GenericApiClient

MOUNT = "/seafood-ops"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", f"{MOUNT}/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Counters
    # ------------------------------------------------------------------
    def create_counter(self, payload, headers):
        return self._request("POST", f"{MOUNT}/counters", payload, headers)

    def get_counter(self, counter_id, headers):
        return self._request("GET", f"{MOUNT}/counters/{counter_id}", headers=headers)

    def list_counters(self, headers, params=None):
        return self._request("GET", f"{MOUNT}/counters", headers=headers, params=params)

    def close_verification_cycle(self, counter_id, payload, headers):
        return self._request(
            "POST", f"{MOUNT}/counters/{counter_id}/close-verification-cycle", payload, headers
        )

    # ------------------------------------------------------------------
    # Suppliers
    # ------------------------------------------------------------------
    def create_supplier(self, payload, headers):
        return self._request("POST", f"{MOUNT}/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"{MOUNT}/suppliers/{supplier_id}", headers=headers)

    # ------------------------------------------------------------------
    # Species
    # ------------------------------------------------------------------
    def create_species(self, payload, headers):
        return self._request("POST", f"{MOUNT}/species", payload, headers)

    def get_species(self, species_id, headers):
        return self._request("GET", f"{MOUNT}/species/{species_id}", headers=headers)

    # ------------------------------------------------------------------
    # Supplier lots
    # ------------------------------------------------------------------
    def create_lot(self, payload, headers):
        return self._request("POST", f"{MOUNT}/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"{MOUNT}/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", f"{MOUNT}/lots", headers=headers, params=params)

    def case_lot(self, lot_id, payload, headers):
        return self._request("POST", f"{MOUNT}/lots/{lot_id}/case", payload, headers)

    def record_sales(self, lot_id, payload, headers):
        return self._request("POST", f"{MOUNT}/lots/{lot_id}/record-sales", payload, headers)

    def relabel_lot(self, lot_id, payload, headers):
        return self._request("POST", f"{MOUNT}/lots/{lot_id}/relabel", payload, headers)

    def settle_chargeback(self, lot_id, payload, headers):
        return self._request("POST", f"{MOUNT}/lots/{lot_id}/settle-chargeback", payload, headers)

    def reverse_chargeback(self, lot_id, payload, headers):
        return self._request("POST", f"{MOUNT}/lots/{lot_id}/reverse-chargeback", payload, headers)

    # ------------------------------------------------------------------
    # Case labels
    # ------------------------------------------------------------------
    def create_case_label(self, payload, headers):
        return self._request("POST", f"{MOUNT}/case-labels", payload, headers)

    def get_case_label(self, label_id, headers):
        return self._request("GET", f"{MOUNT}/case-labels/{label_id}", headers=headers)

    def list_case_labels(self, headers, params=None):
        return self._request("GET", f"{MOUNT}/case-labels", headers=headers, params=params)

    def withdraw_case_label(self, label_id, payload, headers):
        return self._request("POST", f"{MOUNT}/case-labels/{label_id}/withdraw", payload, headers)

    # ------------------------------------------------------------------
    # Advertised items
    # ------------------------------------------------------------------
    def create_ad_item(self, payload, headers):
        return self._request("POST", f"{MOUNT}/ad-items", payload, headers)

    def get_ad_item(self, item_id, headers):
        return self._request("GET", f"{MOUNT}/ad-items/{item_id}", headers=headers)

    def list_ad_items(self, headers, params=None):
        return self._request("GET", f"{MOUNT}/ad-items", headers=headers, params=params)

    def clear_ad_cool(self, item_id, payload, headers):
        return self._request("POST", f"{MOUNT}/ad-items/{item_id}/clear-cool", payload, headers)

    def clear_ad_claim(self, item_id, payload, headers):
        return self._request("POST", f"{MOUNT}/ad-items/{item_id}/clear-claim", payload, headers)

    def publish_ad_item(self, item_id, payload, headers):
        return self._request("POST", f"{MOUNT}/ad-items/{item_id}/publish", payload, headers)

    def close_ad_item(self, item_id, payload, headers):
        return self._request("POST", f"{MOUNT}/ad-items/{item_id}/close", payload, headers)

    def retract_ad_item(self, item_id, payload, headers):
        return self._request("POST", f"{MOUNT}/ad-items/{item_id}/retract", payload, headers)

    # ------------------------------------------------------------------
    # Ice-bed readings and cold-chain excursions
    # ------------------------------------------------------------------
    def create_ice_bed_reading(self, payload, headers):
        return self._request("POST", f"{MOUNT}/ice-bed-readings", payload, headers)

    def get_ice_bed_reading(self, reading_id, headers):
        return self._request("GET", f"{MOUNT}/ice-bed-readings/{reading_id}", headers=headers)

    def list_ice_bed_readings(self, headers, params=None):
        return self._request("GET", f"{MOUNT}/ice-bed-readings", headers=headers, params=params)

    def get_excursion(self, excursion_id, headers):
        return self._request("GET", f"{MOUNT}/excursions/{excursion_id}", headers=headers)

    def list_excursions(self, headers, params=None):
        return self._request("GET", f"{MOUNT}/excursions", headers=headers, params=params)

    def resolve_excursion(self, excursion_id, payload, headers):
        return self._request("POST", f"{MOUNT}/excursions/{excursion_id}/resolve", payload, headers)

    # ------------------------------------------------------------------
    # Verification samples
    # ------------------------------------------------------------------
    def create_verification_sample(self, payload, headers):
        return self._request("POST", f"{MOUNT}/verification-samples", payload, headers)

    def get_verification_sample(self, sample_id, headers):
        return self._request("GET", f"{MOUNT}/verification-samples/{sample_id}", headers=headers)

    def list_verification_samples(self, headers, params=None):
        return self._request("GET", f"{MOUNT}/verification-samples", headers=headers, params=params)

    def send_sample_to_lab(self, sample_id, payload, headers):
        return self._request(
            "POST", f"{MOUNT}/verification-samples/{sample_id}/send-to-lab", payload, headers
        )

    def record_sample_result(self, sample_id, payload, headers):
        return self._request(
            "POST", f"{MOUNT}/verification-samples/{sample_id}/result", payload, headers
        )

    def dispute_sample(self, sample_id, payload, headers):
        return self._request(
            "POST", f"{MOUNT}/verification-samples/{sample_id}/dispute", payload, headers
        )

    # ------------------------------------------------------------------
    # Import-monitoring documents
    # ------------------------------------------------------------------
    def create_simp_document(self, payload, headers):
        return self._request("POST", f"{MOUNT}/simp-documents", payload, headers)

    def get_simp_document(self, document_id, headers):
        return self._request("GET", f"{MOUNT}/simp-documents/{document_id}", headers=headers)

    def list_simp_documents(self, headers, params=None):
        return self._request("GET", f"{MOUNT}/simp-documents", headers=headers, params=params)

    def submit_simp_document(self, document_id, payload, headers):
        return self._request(
            "POST", f"{MOUNT}/simp-documents/{document_id}/submit", payload, headers
        )

    def review_simp_document(self, document_id, payload, headers):
        return self._request(
            "POST", f"{MOUNT}/simp-documents/{document_id}/review", payload, headers
        )

    # ------------------------------------------------------------------
    # Sustainability certifications
    # ------------------------------------------------------------------
    def create_certification(self, payload, headers):
        return self._request("POST", f"{MOUNT}/certifications", payload, headers)

    def get_certification(self, certification_id, headers):
        return self._request("GET", f"{MOUNT}/certifications/{certification_id}", headers=headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", f"{MOUNT}/certifications", headers=headers, params=params)

    def review_certification(self, certification_id, payload, headers):
        return self._request(
            "POST", f"{MOUNT}/certifications/{certification_id}/review", payload, headers
        )

    def enforce_certification(self, certification_id, payload, headers):
        return self._request(
            "POST", f"{MOUNT}/certifications/{certification_id}/enforce", payload, headers
        )

    # ------------------------------------------------------------------
    # Shrink events
    # ------------------------------------------------------------------
    def create_shrink_event(self, payload, headers):
        return self._request("POST", f"{MOUNT}/shrink-events", payload, headers)

    def get_shrink_event(self, event_id, headers):
        return self._request("GET", f"{MOUNT}/shrink-events/{event_id}", headers=headers)

    def list_shrink_events(self, headers, params=None):
        return self._request("GET", f"{MOUNT}/shrink-events", headers=headers, params=params)

    def approve_conversion(self, event_id, payload, headers):
        return self._request(
            "POST", f"{MOUNT}/shrink-events/{event_id}/approve-conversion", payload, headers
        )

    def convert_shrink_event(self, event_id, payload, headers):
        return self._request("POST", f"{MOUNT}/shrink-events/{event_id}/convert", payload, headers)

    def post_shrink_event(self, event_id, payload, headers):
        return self._request("POST", f"{MOUNT}/shrink-events/{event_id}/post", payload, headers)

    def reverse_shrink_event(self, event_id, payload, headers):
        return self._request("POST", f"{MOUNT}/shrink-events/{event_id}/reverse", payload, headers)

    # ------------------------------------------------------------------
    # Compliance violations
    # ------------------------------------------------------------------
    def get_violation(self, violation_id, headers):
        return self._request("GET", f"{MOUNT}/violations/{violation_id}", headers=headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", f"{MOUNT}/violations", headers=headers, params=params)

    def cure_violation(self, violation_id, payload, headers):
        return self._request("POST", f"{MOUNT}/violations/{violation_id}/cure", payload, headers)

    def expunge_violation(self, violation_id, payload, headers):
        return self._request("POST", f"{MOUNT}/violations/{violation_id}/expunge", payload, headers)


api_client = ApiClient()
