"""API client: one method per endpoint defined in the PRD (all under /licensing)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # The runner restarts the server (SIGKILL) before every test. A pooled
        # keep-alive connection to the previous server generation can race the
        # incoming RST and fail mid-write with ConnectionResetError /
        # RemoteDisconnected on an otherwise-healthy fresh server. Sending
        # every request on a fresh TCP connection removes that race; this is a
        # transport concern only and changes nothing the tests assert.
        self.session.headers["Connection"] = "close"

    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/licensing/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Titles
    # ------------------------------------------------------------------
    def create_title(self, payload, headers):
        return self._request("POST", "/licensing/titles", payload, headers)

    def list_titles(self, headers, params=None):
        return self._request("GET", "/licensing/titles", headers=headers, params=params)

    def get_title(self, title_id, headers):
        return self._request("GET", f"/licensing/titles/{title_id}", headers=headers)

    # ------------------------------------------------------------------
    # Rights holders
    # ------------------------------------------------------------------
    def create_rights_holder(self, payload, headers):
        return self._request("POST", "/licensing/rights-holders", payload, headers)

    def list_rights_holders(self, headers, params=None):
        return self._request("GET", "/licensing/rights-holders", headers=headers, params=params)

    def get_rights_holder(self, holder_id, headers):
        return self._request("GET", f"/licensing/rights-holders/{holder_id}", headers=headers)

    # ------------------------------------------------------------------
    # Platforms
    # ------------------------------------------------------------------
    def create_platform(self, payload, headers):
        return self._request("POST", "/licensing/platforms", payload, headers)

    def list_platforms(self, headers, params=None):
        return self._request("GET", "/licensing/platforms", headers=headers, params=params)

    def get_platform(self, platform_id, headers):
        return self._request("GET", f"/licensing/platforms/{platform_id}", headers=headers)

    # ------------------------------------------------------------------
    # Rights slots
    # ------------------------------------------------------------------
    def create_rights_slot(self, payload, headers):
        return self._request("POST", "/licensing/rights-slots", payload, headers)

    def list_rights_slots(self, headers, params=None):
        return self._request("GET", "/licensing/rights-slots", headers=headers, params=params)

    def get_rights_slot(self, slot_id, headers):
        return self._request("GET", f"/licensing/rights-slots/{slot_id}", headers=headers)

    def withdraw_rights_slot(self, slot_id, headers):
        return self._request("POST", f"/licensing/rights-slots/{slot_id}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # Avail packages
    # ------------------------------------------------------------------
    def create_avail_package(self, payload, headers):
        return self._request("POST", "/licensing/avail-packages", payload, headers)

    def list_avail_packages(self, headers, params=None):
        return self._request("GET", "/licensing/avail-packages", headers=headers, params=params)

    def get_avail_package(self, package_id, headers):
        return self._request("GET", f"/licensing/avail-packages/{package_id}", headers=headers)

    def offer_package(self, package_id, headers):
        return self._request("POST", f"/licensing/avail-packages/{package_id}/offer", {}, headers)

    def accept_package(self, package_id, accepted_slot_ids, headers):
        return self._request("POST", f"/licensing/avail-packages/{package_id}/accept",
                             {"accepted_slot_ids": accepted_slot_ids}, headers)

    def decline_package(self, package_id, headers):
        return self._request("POST", f"/licensing/avail-packages/{package_id}/decline", {}, headers)

    def withdraw_package(self, package_id, headers):
        return self._request("POST", f"/licensing/avail-packages/{package_id}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # License agreements
    # ------------------------------------------------------------------
    def create_license_agreement(self, payload, headers):
        return self._request("POST", "/licensing/license-agreements", payload, headers)

    def list_license_agreements(self, headers, params=None):
        return self._request("GET", "/licensing/license-agreements", headers=headers, params=params)

    def get_license_agreement(self, license_id, headers):
        return self._request("GET", f"/licensing/license-agreements/{license_id}", headers=headers)

    def activate_license(self, license_id, headers):
        return self._request("POST", f"/licensing/license-agreements/{license_id}/activate",
                             {}, headers)

    def extend_license(self, license_id, new_license_end, expected_license_version, headers):
        return self._request("POST", f"/licensing/license-agreements/{license_id}/extend",
                             {"new_license_end": new_license_end,
                              "expected_license_version": expected_license_version}, headers)

    def terminate_license(self, license_id, headers):
        return self._request("POST", f"/licensing/license-agreements/{license_id}/terminate",
                             {}, headers)

    def submit_revenue_report(self, license_id, payload, headers):
        return self._request("POST", f"/licensing/license-agreements/{license_id}/revenue-reports",
                             payload, headers)

    # ------------------------------------------------------------------
    # Revenue reports
    # ------------------------------------------------------------------
    def list_revenue_reports(self, headers, params=None):
        return self._request("GET", "/licensing/revenue-reports", headers=headers, params=params)

    def get_revenue_report(self, report_id, headers):
        return self._request("GET", f"/licensing/revenue-reports/{report_id}", headers=headers)

    def reverse_revenue_report(self, report_id, headers):
        return self._request("POST", f"/licensing/revenue-reports/{report_id}/reverse",
                             {}, headers)

    # ------------------------------------------------------------------
    # Delivery batches
    # ------------------------------------------------------------------
    def create_delivery_batch(self, payload, headers):
        return self._request("POST", "/licensing/delivery-batches", payload, headers)

    def list_delivery_batches(self, headers, params=None):
        return self._request("GET", "/licensing/delivery-batches", headers=headers, params=params)

    def get_delivery_batch(self, batch_id, headers):
        return self._request("GET", f"/licensing/delivery-batches/{batch_id}", headers=headers)

    def submit_delivery_batch(self, batch_id, headers):
        return self._request("POST", f"/licensing/delivery-batches/{batch_id}/submit", {}, headers)

    def resubmit_delivery_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/licensing/delivery-batches/{batch_id}/resubmit",
                             payload, headers)

    # ------------------------------------------------------------------
    # Takedown notices (read-only surface)
    # ------------------------------------------------------------------
    def list_takedown_notices(self, headers, params=None):
        return self._request("GET", "/licensing/takedown-notices", headers=headers, params=params)

    def get_takedown_notice(self, notice_id, headers):
        return self._request("GET", f"/licensing/takedown-notices/{notice_id}", headers=headers)

    # ------------------------------------------------------------------
    # Royalty statements
    # ------------------------------------------------------------------
    def create_royalty_statement(self, payload, headers):
        return self._request("POST", "/licensing/royalty-statements", payload, headers)

    def list_royalty_statements(self, headers, params=None):
        return self._request("GET", "/licensing/royalty-statements", headers=headers, params=params)

    def get_royalty_statement(self, statement_id, headers):
        return self._request("GET", f"/licensing/royalty-statements/{statement_id}",
                             headers=headers)

    def finalize_statement(self, statement_id, headers):
        return self._request("POST", f"/licensing/royalty-statements/{statement_id}/finalize",
                             {}, headers)

    def mark_statement_paid(self, statement_id, headers):
        return self._request("POST", f"/licensing/royalty-statements/{statement_id}/mark-paid",
                             {}, headers)


api_client = ApiClient()
