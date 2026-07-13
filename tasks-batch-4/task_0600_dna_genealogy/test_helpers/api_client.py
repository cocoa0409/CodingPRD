"""API client: one method per endpoint defined in the PRD (§4). All paths sit under /dna."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock / ops ------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/dna/_clock/set_current_utc", payload, headers)

    def purge_run(self, headers):
        return self._request("POST", "/dna/_ops/purge-run", {}, headers)

    # ---- Customer ---------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/dna/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/dna/customers/{customer_id}", headers=headers)

    def add_credits(self, customer_id, payload, headers):
        return self._request("POST", f"/dna/customers/{customer_id}/credits", payload, headers)

    # ---- Subscription -----------------------------------------------------
    def create_subscription(self, payload, headers):
        return self._request("POST", "/dna/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/dna/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/dna/subscriptions", headers=headers, params=params)

    def change_tier(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/dna/subscriptions/{subscription_id}/change-tier", payload, headers
        )

    def revert_change(self, subscription_id, headers):
        return self._request(
            "POST", f"/dna/subscriptions/{subscription_id}/revert-change", {}, headers
        )

    def billing_event(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/dna/subscriptions/{subscription_id}/billing-event", payload, headers
        )

    # ---- Kit --------------------------------------------------------------
    def create_kit(self, payload, headers):
        return self._request("POST", "/dna/kits", payload, headers)

    def get_kit(self, kit_id, headers):
        return self._request("GET", f"/dna/kits/{kit_id}", headers=headers)

    def list_kits(self, headers, params=None):
        return self._request("GET", "/dna/kits", headers=headers, params=params)

    def activate_kit(self, kit_id, payload, headers):
        return self._request("POST", f"/dna/kits/{kit_id}/activate", payload, headers)

    def receive_kit(self, kit_id, headers):
        return self._request("POST", f"/dna/kits/{kit_id}/receive", {}, headers)

    # ---- Sample -----------------------------------------------------------
    def get_sample(self, sample_id, headers):
        return self._request("GET", f"/dna/samples/{sample_id}", headers=headers)

    def list_samples(self, headers, params=None):
        return self._request("GET", "/dna/samples", headers=headers, params=params)

    def extract_sample(self, sample_id, payload, headers):
        return self._request("POST", f"/dna/samples/{sample_id}/extract", payload, headers)

    def requeue_sample(self, sample_id, headers):
        return self._request("POST", f"/dna/samples/{sample_id}/requeue", {}, headers)

    # ---- Lab instrument / batch -------------------------------------------
    def create_lab_instrument(self, payload, headers):
        return self._request("POST", "/dna/lab-instruments", payload, headers)

    def get_lab_instrument(self, instrument_id, headers):
        return self._request("GET", f"/dna/lab-instruments/{instrument_id}", headers=headers)

    def create_lab_batch(self, payload, headers):
        return self._request("POST", "/dna/lab-batches", payload, headers)

    def get_lab_batch(self, batch_id, headers):
        return self._request("GET", f"/dna/lab-batches/{batch_id}", headers=headers)

    def list_lab_batches(self, headers, params=None):
        return self._request("GET", "/dna/lab-batches", headers=headers, params=params)

    def start_lab_batch(self, batch_id, headers):
        return self._request("POST", f"/dna/lab-batches/{batch_id}/start", {}, headers)

    def finalize_lab_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/dna/lab-batches/{batch_id}/finalize", payload, headers)

    def abort_lab_batch(self, batch_id, headers):
        return self._request("POST", f"/dna/lab-batches/{batch_id}/abort", {}, headers)

    # ---- Consent ----------------------------------------------------------
    def create_consent_grant(self, payload, headers):
        return self._request("POST", "/dna/consent-grants", payload, headers)

    def get_consent_grant(self, grant_id, headers):
        return self._request("GET", f"/dna/consent-grants/{grant_id}", headers=headers)

    def list_consent_grants(self, headers, params=None):
        return self._request("GET", "/dna/consent-grants", headers=headers, params=params)

    def withdraw_consent_grant(self, grant_id, headers):
        return self._request("POST", f"/dna/consent-grants/{grant_id}/withdraw", {}, headers)

    # ---- Reports ----------------------------------------------------------
    def generate_report(self, customer_id, payload, headers):
        return self._request("POST", f"/dna/customers/{customer_id}/reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/dna/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/dna/reports", headers=headers, params=params)

    # ---- Relative matching -------------------------------------------------
    def recompute_matches(self, customer_id, headers):
        return self._request(
            "POST", f"/dna/customers/{customer_id}/matches/recompute", {}, headers
        )

    def get_relative_match(self, match_id, headers):
        return self._request("GET", f"/dna/relative-matches/{match_id}", headers=headers)

    def list_relative_matches(self, headers, params=None):
        return self._request("GET", "/dna/relative-matches", headers=headers, params=params)

    # ---- Family tree -------------------------------------------------------
    def create_family_tree(self, payload, headers):
        return self._request("POST", "/dna/family-trees", payload, headers)

    def get_family_tree(self, tree_id, headers):
        return self._request("GET", f"/dna/family-trees/{tree_id}", headers=headers)

    def list_family_trees(self, headers, params=None):
        return self._request("GET", "/dna/family-trees", headers=headers, params=params)

    def create_tree_person(self, payload, headers):
        return self._request("POST", "/dna/tree-people", payload, headers)

    def get_tree_person(self, person_id, headers):
        return self._request("GET", f"/dna/tree-people/{person_id}", headers=headers)

    def list_tree_people(self, headers, params=None):
        return self._request("GET", "/dna/tree-people", headers=headers, params=params)

    # ---- Record hints ------------------------------------------------------
    def get_record_hint(self, hint_id, headers):
        return self._request("GET", f"/dna/record-hints/{hint_id}", headers=headers)

    def list_record_hints(self, headers, params=None):
        return self._request("GET", "/dna/record-hints", headers=headers, params=params)

    def accept_record_hint(self, hint_id, headers):
        return self._request("POST", f"/dna/record-hints/{hint_id}/accept", {}, headers)

    # ---- Privacy -----------------------------------------------------------
    def create_data_request(self, payload, headers):
        return self._request("POST", "/dna/data-requests", payload, headers)

    def get_data_request(self, request_id, headers):
        return self._request("GET", f"/dna/data-requests/{request_id}", headers=headers)

    def list_data_requests(self, headers, params=None):
        return self._request("GET", "/dna/data-requests", headers=headers, params=params)

    def decide_data_request(self, request_id, payload, headers):
        return self._request("POST", f"/dna/data-requests/{request_id}/decide", payload, headers)

    def cancel_data_request(self, request_id, headers):
        return self._request("POST", f"/dna/data-requests/{request_id}/cancel", {}, headers)


api_client = ApiClient()
