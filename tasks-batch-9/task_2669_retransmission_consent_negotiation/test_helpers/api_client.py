"""API client: one method per endpoint defined in the PRD.

Every path is mounted under the /retrans prefix, except the logical-clock
test-driving endpoint.
"""

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/retrans"


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- stations
    def create_station(self, payload, headers):
        return self._request("POST", f"{BASE}/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"{BASE}/stations/{station_id}", headers=headers)

    def create_affiliation_agreement(self, station_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/stations/{station_id}/affiliation-agreements",
            payload, headers,
        )

    def list_affiliation_agreements(self, station_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/stations/{station_id}/affiliation-agreements",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------ distributors
    def create_distributor(self, payload, headers):
        return self._request("POST", f"{BASE}/distributors", payload, headers)

    def get_distributor(self, distributor_id, headers):
        return self._request(
            "GET", f"{BASE}/distributors/{distributor_id}", headers=headers
        )

    # --------------------------------------------------------------- elections
    def create_election(self, payload, headers):
        return self._request("POST", f"{BASE}/elections", payload, headers)

    def list_elections(self, headers, params=None):
        return self._request("GET", f"{BASE}/elections", headers=headers, params=params)

    def get_election(self, election_id, headers):
        return self._request("GET", f"{BASE}/elections/{election_id}", headers=headers)

    def amend_election(self, election_id, payload, headers):
        return self._request(
            "PATCH", f"{BASE}/elections/{election_id}", payload, headers
        )

    def file_election(self, election_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/elections/{election_id}/file", payload, headers
        )

    def withdraw_election(self, election_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/elections/{election_id}/withdraw", payload, headers
        )

    def list_election_negotiations(self, election_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/elections/{election_id}/negotiations",
            headers=headers, params=params,
        )

    # ------------------------------------------------------ subscriber reports
    def create_subscriber_report(self, payload, headers):
        return self._request("POST", f"{BASE}/subscriber-reports", payload, headers)

    def list_subscriber_reports(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/subscriber-reports", headers=headers, params=params
        )

    def get_subscriber_report(self, report_id, headers):
        return self._request(
            "GET", f"{BASE}/subscriber-reports/{report_id}", headers=headers
        )

    def create_audit_finding(self, report_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/subscriber-reports/{report_id}/audit-findings",
            payload, headers,
        )

    def list_audit_findings(self, report_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/subscriber-reports/{report_id}/audit-findings",
            headers=headers, params=params,
        )

    def list_report_fee_settlements(self, report_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/subscriber-reports/{report_id}/fee-settlements",
            headers=headers, params=params,
        )

    def resolve_audit_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/audit-findings/{finding_id}/resolve", payload, headers
        )

    # ------------------------------------------------------------ negotiations
    def get_negotiation(self, negotiation_id, headers):
        return self._request(
            "GET", f"{BASE}/negotiations/{negotiation_id}", headers=headers
        )

    def create_offer(self, negotiation_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/negotiations/{negotiation_id}/offers", payload, headers
        )

    def list_negotiation_offers(self, negotiation_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/negotiations/{negotiation_id}/offers",
            headers=headers, params=params,
        )

    def list_offers(self, headers, params=None):
        return self._request("GET", f"{BASE}/offers", headers=headers, params=params)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"{BASE}/offers/{offer_id}", headers=headers)

    def accept_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/offers/{offer_id}/accept", payload, headers
        )

    def reject_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/offers/{offer_id}/reject", payload, headers
        )

    def create_good_faith_log_entry(self, negotiation_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/negotiations/{negotiation_id}/good-faith-log",
            payload, headers,
        )

    def list_good_faith_log(self, negotiation_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/negotiations/{negotiation_id}/good-faith-log",
            headers=headers, params=params,
        )

    def declare_impasse(self, negotiation_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/negotiations/{negotiation_id}/declare-impasse",
            payload, headers,
        )

    def create_blackout_notice(self, negotiation_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/negotiations/{negotiation_id}/blackout-notices",
            payload, headers,
        )

    def list_blackout_notices(self, negotiation_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/negotiations/{negotiation_id}/blackout-notices",
            headers=headers, params=params,
        )

    # --------------------------------------------------------------- agreements
    def list_agreements(self, headers, params=None):
        return self._request("GET", f"{BASE}/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"{BASE}/agreements/{agreement_id}", headers=headers)

    def decide_network_approval(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/agreements/{agreement_id}/network-approval",
            payload, headers,
        )

    def execute_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/agreements/{agreement_id}/execute", payload, headers
        )

    def get_fee_projection(self, agreement_id, headers):
        return self._request(
            "GET", f"{BASE}/agreements/{agreement_id}/fee-projection", headers=headers
        )

    def create_interim_extension(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/agreements/{agreement_id}/interim-extensions",
            payload, headers,
        )

    def list_interim_extensions(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/agreements/{agreement_id}/interim-extensions",
            headers=headers, params=params,
        )

    def create_rights_dispute(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/agreements/{agreement_id}/rights-disputes",
            payload, headers,
        )

    def list_rights_disputes(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/agreements/{agreement_id}/rights-disputes",
            headers=headers, params=params,
        )

    def resolve_rights_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/rights-disputes/{dispute_id}/resolve", payload, headers
        )

    # ----------------------------------------------------------- fee settlements
    def create_fee_settlement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/agreements/{agreement_id}/fee-settlements",
            payload, headers,
        )

    def list_fee_settlements(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/agreements/{agreement_id}/fee-settlements",
            headers=headers, params=params,
        )

    def true_up_fee_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/fee-settlements/{settlement_id}/true-up", payload, headers
        )

    def void_fee_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/fee-settlements/{settlement_id}/void", payload, headers
        )

    # -------------------------------------------------- maintenance and clock
    def run_expiration_sweep(self, payload, headers):
        return self._request("POST", f"{BASE}/expiration-sweep", payload, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
