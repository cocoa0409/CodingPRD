"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/dairy/_clock/set_current_utc", payload, headers)

    # --- Producers ---
    def create_producer(self, payload, headers):
        return self._request("POST", "/dairy/producers", payload, headers)

    def list_producers(self, headers, params=None):
        return self._request("GET", "/dairy/producers", headers=headers, params=params)

    def get_producer(self, producer_id, headers):
        return self._request("GET", f"/dairy/producers/{producer_id}", headers=headers)

    # --- Haulers ---
    def create_hauler(self, payload, headers):
        return self._request("POST", "/dairy/haulers", payload, headers)

    def get_hauler(self, hauler_id, headers):
        return self._request("GET", f"/dairy/haulers/{hauler_id}", headers=headers)

    # --- Tanker receipts ---
    def create_tanker_receipt(self, payload, headers):
        return self._request("POST", "/dairy/tanker-receipts", payload, headers)

    def list_tanker_receipts(self, headers, params=None):
        return self._request("GET", "/dairy/tanker-receipts", headers=headers, params=params)

    def get_tanker_receipt(self, receipt_id, headers):
        return self._request("GET", f"/dairy/tanker-receipts/{receipt_id}", headers=headers)

    def release_tanker_receipt(self, receipt_id, payload, headers):
        return self._request("POST", f"/dairy/tanker-receipts/{receipt_id}/release", payload, headers)

    def reject_tanker_receipt(self, receipt_id, payload, headers):
        return self._request("POST", f"/dairy/tanker-receipts/{receipt_id}/reject", payload, headers)

    def divert_tanker_receipt(self, receipt_id, payload, headers):
        return self._request("POST", f"/dairy/tanker-receipts/{receipt_id}/divert", payload, headers)

    # --- Lab tests ---
    def create_lab_test(self, receipt_id, payload, headers):
        return self._request("POST", f"/dairy/tanker-receipts/{receipt_id}/lab-tests", payload, headers)

    def list_lab_tests(self, receipt_id, headers):
        return self._request("GET", f"/dairy/tanker-receipts/{receipt_id}/lab-tests", headers=headers)

    def complete_lab_test(self, receipt_id, test_id, payload, headers):
        return self._request(
            "POST", f"/dairy/tanker-receipts/{receipt_id}/lab-tests/{test_id}/complete", payload, headers
        )

    # --- Component assays ---
    def create_component_assay(self, receipt_id, payload, headers):
        return self._request(
            "POST", f"/dairy/tanker-receipts/{receipt_id}/component-assays", payload, headers
        )

    def list_component_assays(self, receipt_id, headers):
        return self._request(
            "GET", f"/dairy/tanker-receipts/{receipt_id}/component-assays", headers=headers
        )

    # --- Producer settlements ---
    def create_settlement(self, producer_id, payload, headers):
        return self._request("POST", f"/dairy/producers/{producer_id}/settlements", payload, headers)

    def list_settlements(self, producer_id, headers, params=None):
        return self._request(
            "GET", f"/dairy/producers/{producer_id}/settlements", headers=headers, params=params
        )

    def get_settlement(self, producer_id, settlement_id, headers):
        return self._request(
            "GET", f"/dairy/producers/{producer_id}/settlements/{settlement_id}", headers=headers
        )

    def approve_settlement(self, producer_id, settlement_id, payload, headers):
        return self._request(
            "POST", f"/dairy/producers/{producer_id}/settlements/{settlement_id}/approve", payload, headers
        )

    def mark_settlement_paid(self, producer_id, settlement_id, headers):
        return self._request(
            "POST", f"/dairy/producers/{producer_id}/settlements/{settlement_id}/mark-paid", {}, headers
        )

    def cancel_settlement(self, producer_id, settlement_id, headers):
        return self._request(
            "POST", f"/dairy/producers/{producer_id}/settlements/{settlement_id}/cancel", {}, headers
        )

    # --- Pasteurizer runs ---
    def create_pasteurizer_run(self, payload, headers):
        return self._request("POST", "/dairy/pasteurizer-runs", payload, headers)

    def list_pasteurizer_runs(self, headers, params=None):
        return self._request("GET", "/dairy/pasteurizer-runs", headers=headers, params=params)

    def get_pasteurizer_run(self, run_id, headers):
        return self._request("GET", f"/dairy/pasteurizer-runs/{run_id}", headers=headers)

    def start_pasteurizer_run(self, run_id, payload, headers):
        return self._request("POST", f"/dairy/pasteurizer-runs/{run_id}/start", payload, headers)

    def complete_pasteurizer_run(self, run_id, payload, headers):
        return self._request("POST", f"/dairy/pasteurizer-runs/{run_id}/complete", payload, headers)

    def abort_pasteurizer_run(self, run_id, payload, headers):
        return self._request("POST", f"/dairy/pasteurizer-runs/{run_id}/abort", payload, headers)

    def cancel_pasteurizer_run(self, run_id, payload, headers):
        return self._request("POST", f"/dairy/pasteurizer-runs/{run_id}/cancel", payload, headers)

    # --- CIP cycles ---
    def create_cip_cycle(self, run_id, payload, headers):
        return self._request("POST", f"/dairy/pasteurizer-runs/{run_id}/cip-cycles", payload, headers)

    def list_cip_cycles(self, run_id, headers):
        return self._request("GET", f"/dairy/pasteurizer-runs/{run_id}/cip-cycles", headers=headers)

    def validate_cip_cycle(self, run_id, cip_id, payload, headers):
        return self._request(
            "POST", f"/dairy/pasteurizer-runs/{run_id}/cip-cycles/{cip_id}/validate", payload, headers
        )

    def fail_cip_cycle(self, run_id, cip_id, payload, headers):
        return self._request(
            "POST", f"/dairy/pasteurizer-runs/{run_id}/cip-cycles/{cip_id}/fail", payload, headers
        )

    # --- Product batches ---
    def create_batch(self, run_id, payload, headers):
        return self._request("POST", f"/dairy/pasteurizer-runs/{run_id}/batches", payload, headers)

    def list_batches(self, run_id, headers):
        return self._request("GET", f"/dairy/pasteurizer-runs/{run_id}/batches", headers=headers)

    def begin_batch(self, run_id, batch_id, payload, headers):
        return self._request(
            "POST", f"/dairy/pasteurizer-runs/{run_id}/batches/{batch_id}/begin", payload, headers
        )

    def code_batch(self, run_id, batch_id, payload, headers):
        return self._request(
            "POST", f"/dairy/pasteurizer-runs/{run_id}/batches/{batch_id}/code", payload, headers
        )

    def scrap_batch(self, run_id, batch_id, payload, headers):
        return self._request(
            "POST", f"/dairy/pasteurizer-runs/{run_id}/batches/{batch_id}/scrap", payload, headers
        )

    # --- Distribution routes ---
    def create_distribution_route(self, payload, headers):
        return self._request("POST", "/dairy/distribution-routes", payload, headers)

    def get_distribution_route(self, route_id, headers):
        return self._request("GET", f"/dairy/distribution-routes/{route_id}", headers=headers)

    # --- Grade A permits ---
    def create_grade_a_permit(self, payload, headers):
        return self._request("POST", "/dairy/grade-a-permits", payload, headers)

    def get_grade_a_permit(self, permit_id, headers):
        return self._request("GET", f"/dairy/grade-a-permits/{permit_id}", headers=headers)

    def record_inspection(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/dairy/grade-a-permits/{permit_id}/record-inspection", payload, headers
        )

    def suspend_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/dairy/grade-a-permits/{permit_id}/suspend", payload, headers)

    def reinstate_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/dairy/grade-a-permits/{permit_id}/reinstate", payload, headers)

    def revoke_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/dairy/grade-a-permits/{permit_id}/revoke", payload, headers)

    # --- Marketing order pools ---
    def create_marketing_order_pool(self, payload, headers):
        return self._request("POST", "/dairy/marketing-order-pools", payload, headers)

    def get_marketing_order_pool(self, pool_id, headers):
        return self._request("GET", f"/dairy/marketing-order-pools/{pool_id}", headers=headers)

    def announce_pool(self, pool_id, payload, headers):
        return self._request("POST", f"/dairy/marketing-order-pools/{pool_id}/announce", payload, headers)

    def finalize_pool(self, pool_id, payload, headers):
        return self._request("POST", f"/dairy/marketing-order-pools/{pool_id}/finalize", payload, headers)


api_client = ApiClient()
