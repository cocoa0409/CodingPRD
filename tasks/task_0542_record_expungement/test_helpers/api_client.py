"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/expungement"


class ApiClient(GenericApiClient):
    # ---- Configuration resources ----
    def create_courtroom(self, payload, headers):
        return self._request("POST", f"{PREFIX}/courtrooms", payload, headers=headers)

    def get_courtroom(self, courtroom_id, headers):
        return self._request("GET", f"{PREFIX}/courtrooms/{courtroom_id}", headers=headers)

    def create_judge(self, payload, headers):
        return self._request("POST", f"{PREFIX}/judges", payload, headers=headers)

    def get_judge(self, judge_id, headers):
        return self._request("GET", f"{PREFIX}/judges/{judge_id}", headers=headers)

    def create_background_vendor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/background-vendors", payload, headers=headers)

    def get_background_vendor(self, vendor_id, headers):
        return self._request("GET", f"{PREFIX}/background-vendors/{vendor_id}", headers=headers)

    # ---- Petitioner ----
    def create_petitioner(self, payload, headers):
        return self._request("POST", f"{PREFIX}/petitioners", payload, headers=headers)

    def get_petitioner(self, petitioner_id, headers):
        return self._request("GET", f"{PREFIX}/petitioners/{petitioner_id}", headers=headers)

    # ---- Criminal records ----
    def create_criminal_record(self, payload, headers):
        return self._request("POST", f"{PREFIX}/criminal-records", payload, headers=headers)

    def get_criminal_record(self, record_id, headers):
        return self._request("GET", f"{PREFIX}/criminal-records/{record_id}", headers=headers)

    def list_criminal_records(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/criminal-records", headers=headers, params=params)

    def screen_criminal_record(self, record_id, headers):
        return self._request("POST", f"{PREFIX}/criminal-records/{record_id}/screen", {}, headers=headers)

    # ---- Petition & items ----
    def create_petition(self, payload, headers):
        return self._request("POST", f"{PREFIX}/petitions", payload, headers=headers)

    def get_petition(self, petition_id, headers):
        return self._request("GET", f"{PREFIX}/petitions/{petition_id}", headers=headers)

    def list_petitions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/petitions", headers=headers, params=params)

    def get_petition_item(self, item_id, headers):
        return self._request("GET", f"{PREFIX}/petition-items/{item_id}", headers=headers)

    def list_petition_items(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/petition-items", headers=headers, params=params)

    def transition_petition(self, petition_id, payload, headers):
        return self._request("POST", f"{PREFIX}/petitions/{petition_id}/transition", payload, headers=headers)

    def pay_fee(self, petition_id, payload, headers):
        return self._request("POST", f"{PREFIX}/petitions/{petition_id}/pay-fee", payload, headers=headers)

    def create_hearing(self, petition_id, payload, headers):
        return self._request("POST", f"{PREFIX}/petitions/{petition_id}/hearings", payload, headers=headers)

    # ---- Fee waivers ----
    def create_fee_waiver(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fee-waivers", payload, headers=headers)

    def get_fee_waiver(self, waiver_id, headers):
        return self._request("GET", f"{PREFIX}/fee-waivers/{waiver_id}", headers=headers)

    def list_fee_waivers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/fee-waivers", headers=headers, params=params)

    def transition_fee_waiver(self, waiver_id, payload, headers):
        return self._request("POST", f"{PREFIX}/fee-waivers/{waiver_id}/transition", payload, headers=headers)

    # ---- Agency notifications & objections ----
    def get_agency_notification(self, notification_id, headers):
        return self._request("GET", f"{PREFIX}/agency-notifications/{notification_id}", headers=headers)

    def list_agency_notifications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/agency-notifications", headers=headers, params=params)

    def transition_agency_notification(self, notification_id, payload, headers):
        return self._request("POST", f"{PREFIX}/agency-notifications/{notification_id}/transition", payload, headers=headers)

    def create_objection(self, notification_id, payload, headers):
        return self._request("POST", f"{PREFIX}/agency-notifications/{notification_id}/objections", payload, headers=headers)

    def get_objection(self, objection_id, headers):
        return self._request("GET", f"{PREFIX}/objections/{objection_id}", headers=headers)

    def list_objections(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/objections", headers=headers, params=params)

    def transition_objection(self, objection_id, payload, headers):
        return self._request("POST", f"{PREFIX}/objections/{objection_id}/transition", payload, headers=headers)

    # ---- Hearing & order ----
    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"{PREFIX}/hearings/{hearing_id}", headers=headers)

    def list_hearings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/hearings", headers=headers, params=params)

    def transition_hearing(self, hearing_id, payload, headers):
        return self._request("POST", f"{PREFIX}/hearings/{hearing_id}/transition", payload, headers=headers)

    def create_court_order(self, hearing_id, payload, headers):
        return self._request("POST", f"{PREFIX}/hearings/{hearing_id}/order", payload, headers=headers)

    def get_court_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/court-orders/{order_id}", headers=headers)

    def list_court_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/court-orders", headers=headers, params=params)

    def vacate_court_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/court-orders/{order_id}/vacate", {}, headers=headers)

    # ---- Sealing distributions ----
    def get_sealing_distribution(self, distribution_id, headers):
        return self._request("GET", f"{PREFIX}/sealing-distributions/{distribution_id}", headers=headers)

    def list_sealing_distributions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sealing-distributions", headers=headers, params=params)

    def transition_sealing_distribution(self, distribution_id, payload, headers):
        return self._request("POST", f"{PREFIX}/sealing-distributions/{distribution_id}/transition", payload, headers=headers)

    # ---- Test-driving: logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)


api_client = ApiClient()
