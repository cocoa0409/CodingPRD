"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- server logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- insertion orders ---
    def create_insertion_order(self, payload, headers):
        return self._request("POST", "/insertion-orders", payload, headers)

    def get_insertion_order(self, io_id, headers):
        return self._request("GET", f"/insertion-orders/{io_id}", headers=headers)

    def transition_insertion_order(self, io_id, payload, headers):
        return self._request(
            "POST", f"/insertion-orders/{io_id}/transition", payload, headers
        )

    # --- line items ---
    def create_line_item(self, payload, headers):
        return self._request("POST", "/line-items", payload, headers)

    def list_line_items(self, headers, params=None):
        return self._request("GET", "/line-items", headers=headers, params=params)

    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/line-items/{line_item_id}", headers=headers)

    def patch_line_item(self, line_item_id, payload, headers):
        return self._request("PATCH", f"/line-items/{line_item_id}", payload, headers)

    def transition_line_item(self, line_item_id, payload, headers):
        return self._request(
            "POST", f"/line-items/{line_item_id}/transition", payload, headers
        )

    # --- creatives ---
    def create_creative(self, payload, headers):
        return self._request("POST", "/creatives", payload, headers)

    def list_creatives(self, headers, params=None):
        return self._request("GET", "/creatives", headers=headers, params=params)

    def get_creative(self, creative_id, headers):
        return self._request("GET", f"/creatives/{creative_id}", headers=headers)

    def transition_creative(self, creative_id, payload, headers):
        return self._request(
            "POST", f"/creatives/{creative_id}/transition", payload, headers
        )

    # --- delivery snapshots ---
    def create_delivery_snapshot(self, payload, headers):
        return self._request("POST", "/delivery-snapshots", payload, headers)

    def list_delivery_snapshots(self, line_item_id, headers, params=None):
        return self._request(
            "GET",
            f"/line-items/{line_item_id}/delivery-snapshots",
            headers=headers,
            params=params,
        )

    def transition_delivery_snapshot(self, snapshot_id, payload, headers):
        return self._request(
            "POST", f"/delivery-snapshots/{snapshot_id}/transition", payload, headers
        )

    # --- impression events ---
    def create_impression_event(self, payload, headers):
        return self._request("POST", "/impression-events", payload, headers)

    def list_impression_events(self, line_item_id, headers, params=None):
        return self._request(
            "GET",
            f"/line-items/{line_item_id}/impression-events",
            headers=headers,
            params=params,
        )

    # --- verification reports ---
    def create_verification_report(self, payload, headers):
        return self._request("POST", "/verification-reports", payload, headers)

    def list_verification_reports(self, headers, params=None):
        return self._request(
            "GET", "/verification-reports", headers=headers, params=params
        )

    def get_verification_report(self, report_id, headers):
        return self._request(
            "GET", f"/verification-reports/{report_id}", headers=headers
        )

    def transition_verification_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/verification-reports/{report_id}/transition", payload, headers
        )

    # --- make-goods ---
    def create_make_good(self, payload, headers):
        return self._request("POST", "/make-goods", payload, headers)

    def list_make_goods(self, headers, params=None):
        return self._request("GET", "/make-goods", headers=headers, params=params)

    def get_make_good(self, make_good_id, headers):
        return self._request("GET", f"/make-goods/{make_good_id}", headers=headers)

    def transition_make_good(self, make_good_id, payload, headers):
        return self._request(
            "POST", f"/make-goods/{make_good_id}/transition", payload, headers
        )

    # --- reconciliations ---
    def create_reconciliation(self, payload, headers):
        return self._request("POST", "/reconciliations", payload, headers)

    def list_reconciliations(self, headers, params=None):
        return self._request("GET", "/reconciliations", headers=headers, params=params)

    def get_reconciliation(self, reconciliation_id, headers):
        return self._request(
            "GET", f"/reconciliations/{reconciliation_id}", headers=headers
        )

    def transition_reconciliation(self, reconciliation_id, payload, headers):
        return self._request(
            "POST",
            f"/reconciliations/{reconciliation_id}/transition",
            payload,
            headers,
        )

    # --- wrap reports ---
    def create_wrap_report(self, payload, headers):
        return self._request("POST", "/wrap-reports", payload, headers)

    def list_wrap_reports(self, headers, params=None):
        return self._request("GET", "/wrap-reports", headers=headers, params=params)

    def get_wrap_report(self, wrap_report_id, headers):
        return self._request("GET", f"/wrap-reports/{wrap_report_id}", headers=headers)

    def transition_wrap_report(self, wrap_report_id, payload, headers):
        return self._request(
            "POST", f"/wrap-reports/{wrap_report_id}/transition", payload, headers
        )


api_client = ApiClient()
