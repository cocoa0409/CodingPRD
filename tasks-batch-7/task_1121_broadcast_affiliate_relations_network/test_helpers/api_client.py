"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Networks ---
    def create_network(self, payload, headers):
        return self._request("POST", "/networks", payload, headers)

    def get_network(self, network_id, headers):
        return self._request("GET", f"/networks/{network_id}", headers=headers)

    def list_networks(self, headers, params=None):
        return self._request("GET", "/networks", headers=headers, params=params)

    def advance_period(self, network_id, headers):
        return self._request("POST", f"/networks/{network_id}/advance-period", {}, headers)

    # --- Station Groups ---
    def create_station_group(self, payload, headers):
        return self._request("POST", "/station-groups", payload, headers)

    def get_station_group(self, sg_id, headers):
        return self._request("GET", f"/station-groups/{sg_id}", headers=headers)

    # --- Stations ---
    def create_station(self, network_id, payload, headers):
        return self._request("POST", f"/networks/{network_id}/stations", payload, headers)

    def get_station(self, network_id, station_id, headers):
        return self._request("GET", f"/networks/{network_id}/stations/{station_id}", headers=headers)

    def list_stations(self, network_id, headers, params=None):
        return self._request("GET", f"/networks/{network_id}/stations", headers=headers, params=params)

    # --- Territories ---
    def create_territory(self, network_id, payload, headers):
        return self._request("POST", f"/networks/{network_id}/territories", payload, headers)

    def get_territory(self, network_id, territory_id, headers):
        return self._request("GET", f"/networks/{network_id}/territories/{territory_id}", headers=headers)

    # --- Programs ---
    def create_program(self, network_id, payload, headers):
        return self._request("POST", f"/networks/{network_id}/programs", payload, headers)

    def get_program(self, network_id, program_id, headers):
        return self._request("GET", f"/networks/{network_id}/programs/{program_id}", headers=headers)

    # --- Affiliation Agreements ---
    def create_agreement(self, network_id, station_id, payload, headers):
        return self._request(
            "POST", f"/networks/{network_id}/stations/{station_id}/agreements", payload, headers
        )

    def get_agreement(self, network_id, station_id, agreement_id, headers):
        return self._request(
            "GET",
            f"/networks/{network_id}/stations/{station_id}/agreements/{agreement_id}",
            headers=headers,
        )

    def list_agreements(self, network_id, station_id, headers, params=None):
        return self._request(
            "GET",
            f"/networks/{network_id}/stations/{station_id}/agreements",
            headers=headers,
            params=params,
        )

    def submit_agreement(self, network_id, station_id, agreement_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/agreements/{agreement_id}/submit",
            {},
            headers,
        )

    def activate_agreement(self, network_id, station_id, agreement_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/agreements/{agreement_id}/activate",
            {},
            headers,
        )

    def terminate_agreement(self, network_id, station_id, agreement_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/agreements/{agreement_id}/terminate",
            {},
            headers,
        )

    # --- Renewal Offers ---
    def create_renewal_offer(self, network_id, station_id, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/agreements/{agreement_id}/renewal-offers",
            payload,
            headers,
        )

    def get_renewal_offer(self, network_id, station_id, agreement_id, offer_id, headers):
        return self._request(
            "GET",
            f"/networks/{network_id}/stations/{station_id}/agreements/{agreement_id}/renewal-offers/{offer_id}",
            headers=headers,
        )

    def list_renewal_offers(self, network_id, station_id, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"/networks/{network_id}/stations/{station_id}/agreements/{agreement_id}/renewal-offers",
            headers=headers,
            params=params,
        )

    def accept_renewal_offer(self, network_id, station_id, agreement_id, offer_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/agreements/{agreement_id}/renewal-offers/{offer_id}/accept",
            {},
            headers,
        )

    def reject_renewal_offer(self, network_id, station_id, agreement_id, offer_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/agreements/{agreement_id}/renewal-offers/{offer_id}/reject",
            {},
            headers,
        )

    def withdraw_renewal_offer(self, network_id, station_id, agreement_id, offer_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/agreements/{agreement_id}/renewal-offers/{offer_id}/withdraw",
            {},
            headers,
        )

    # --- Clearance Reports ---
    def create_clearance_report(self, network_id, station_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/clearance-reports",
            payload,
            headers,
        )

    def get_clearance_report(self, network_id, station_id, report_id, headers):
        return self._request(
            "GET",
            f"/networks/{network_id}/stations/{station_id}/clearance-reports/{report_id}",
            headers=headers,
        )

    def list_clearance_reports(self, network_id, station_id, headers, params=None):
        return self._request(
            "GET",
            f"/networks/{network_id}/stations/{station_id}/clearance-reports",
            headers=headers,
            params=params,
        )

    def file_clearance_report(self, network_id, station_id, report_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/clearance-reports/{report_id}/file",
            {},
            headers,
        )

    def audit_clearance_report(self, network_id, station_id, report_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/clearance-reports/{report_id}/audit",
            {},
            headers,
        )

    def resolve_cleared_clearance_report(self, network_id, station_id, report_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/clearance-reports/{report_id}/resolve-cleared",
            {},
            headers,
        )

    def resolve_disputed_clearance_report(self, network_id, station_id, report_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/clearance-reports/{report_id}/resolve-disputed",
            {},
            headers,
        )

    # --- Preemption Requests ---
    def create_preemption(self, network_id, station_id, payload, headers):
        return self._request(
            "POST", f"/networks/{network_id}/stations/{station_id}/preemptions", payload, headers
        )

    def get_preemption(self, network_id, station_id, preemption_id, headers):
        return self._request(
            "GET",
            f"/networks/{network_id}/stations/{station_id}/preemptions/{preemption_id}",
            headers=headers,
        )

    def list_preemptions(self, network_id, station_id, headers, params=None):
        return self._request(
            "GET",
            f"/networks/{network_id}/stations/{station_id}/preemptions",
            headers=headers,
            params=params,
        )

    def begin_review_preemption(self, network_id, station_id, preemption_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/preemptions/{preemption_id}/begin-review",
            {},
            headers,
        )

    def approve_preemption(self, network_id, station_id, preemption_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/preemptions/{preemption_id}/approve",
            {},
            headers,
        )

    def deny_preemption(self, network_id, station_id, preemption_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/preemptions/{preemption_id}/deny",
            {},
            headers,
        )

    def counter_preemption(self, network_id, station_id, preemption_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/preemptions/{preemption_id}/counter",
            payload,
            headers,
        )

    def resubmit_preemption(self, network_id, station_id, preemption_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/preemptions/{preemption_id}/resubmit",
            {},
            headers,
        )

    def withdraw_preemption(self, network_id, station_id, preemption_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/preemptions/{preemption_id}/withdraw",
            {},
            headers,
        )

    # --- Avail Allocations ---
    def create_avail_allocation(self, network_id, station_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/avail-allocations",
            payload,
            headers,
        )

    def get_avail_allocation(self, network_id, station_id, alloc_id, headers):
        return self._request(
            "GET",
            f"/networks/{network_id}/stations/{station_id}/avail-allocations/{alloc_id}",
            headers=headers,
        )

    def list_avail_allocations(self, network_id, station_id, headers, params=None):
        return self._request(
            "GET",
            f"/networks/{network_id}/stations/{station_id}/avail-allocations",
            headers=headers,
            params=params,
        )

    def confirm_avail_allocation(self, network_id, station_id, alloc_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/avail-allocations/{alloc_id}/confirm",
            {},
            headers,
        )

    def revoke_avail_allocation(self, network_id, station_id, alloc_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/avail-allocations/{alloc_id}/revoke",
            {},
            headers,
        )

    # --- Retrans Settlements ---
    def create_retrans_settlement(self, network_id, station_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/retrans-settlements",
            payload,
            headers,
        )

    def get_retrans_settlement(self, network_id, station_id, settlement_id, headers):
        return self._request(
            "GET",
            f"/networks/{network_id}/stations/{station_id}/retrans-settlements/{settlement_id}",
            headers=headers,
        )

    def list_retrans_settlements(self, network_id, station_id, headers, params=None):
        return self._request(
            "GET",
            f"/networks/{network_id}/stations/{station_id}/retrans-settlements",
            headers=headers,
            params=params,
        )

    def commit_retrans_settlement(self, network_id, station_id, settlement_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/retrans-settlements/{settlement_id}/commit",
            payload,
            headers,
        )

    def reconcile_retrans_settlement(self, network_id, station_id, settlement_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/retrans-settlements/{settlement_id}/reconcile",
            {},
            headers,
        )

    def void_retrans_settlement(self, network_id, station_id, settlement_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/retrans-settlements/{settlement_id}/void",
            {},
            headers,
        )

    # --- Outage Events ---
    def create_outage_event(self, network_id, station_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/outage-events",
            payload,
            headers,
        )

    def get_outage_event(self, network_id, station_id, event_id, headers):
        return self._request(
            "GET",
            f"/networks/{network_id}/stations/{station_id}/outage-events/{event_id}",
            headers=headers,
        )

    def list_outage_events(self, network_id, station_id, headers, params=None):
        return self._request(
            "GET",
            f"/networks/{network_id}/stations/{station_id}/outage-events",
            headers=headers,
            params=params,
        )

    def confirm_outage_event(self, network_id, station_id, event_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/outage-events/{event_id}/confirm",
            {},
            headers,
        )

    def reject_outage_event(self, network_id, station_id, event_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/outage-events/{event_id}/reject",
            {},
            headers,
        )

    # --- Outage Credits ---
    def get_outage_credit(self, network_id, station_id, credit_id, headers):
        return self._request(
            "GET",
            f"/networks/{network_id}/stations/{station_id}/outage-credits/{credit_id}",
            headers=headers,
        )

    def list_outage_credits(self, network_id, station_id, headers, params=None):
        return self._request(
            "GET",
            f"/networks/{network_id}/stations/{station_id}/outage-credits",
            headers=headers,
            params=params,
        )

    def forfeit_outage_credit(self, network_id, station_id, credit_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/outage-credits/{credit_id}/forfeit",
            {},
            headers,
        )

    # --- Compliance Reports ---
    def create_compliance_report(self, network_id, station_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/compliance-reports",
            payload,
            headers,
        )

    def get_compliance_report(self, network_id, station_id, report_id, headers):
        return self._request(
            "GET",
            f"/networks/{network_id}/stations/{station_id}/compliance-reports/{report_id}",
            headers=headers,
        )

    def list_compliance_reports(self, network_id, station_id, headers, params=None):
        return self._request(
            "GET",
            f"/networks/{network_id}/stations/{station_id}/compliance-reports",
            headers=headers,
            params=params,
        )

    def submit_compliance_report(self, network_id, station_id, report_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/compliance-reports/{report_id}/submit",
            {},
            headers,
        )

    def audit_compliance_report(self, network_id, station_id, report_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/compliance-reports/{report_id}/audit",
            payload,
            headers,
        )

    def resolve_pass_compliance_report(self, network_id, station_id, report_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/compliance-reports/{report_id}/resolve-pass",
            {},
            headers,
        )

    def resolve_fail_compliance_report(self, network_id, station_id, report_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/stations/{station_id}/compliance-reports/{report_id}/resolve-fail",
            {},
            headers,
        )

    # --- Syndication Exclusivity Claims ---
    def create_exclusivity_claim(self, network_id, territory_id, payload, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/territories/{territory_id}/exclusivity-claims",
            payload,
            headers,
        )

    def get_exclusivity_claim(self, network_id, territory_id, claim_id, headers):
        return self._request(
            "GET",
            f"/networks/{network_id}/territories/{territory_id}/exclusivity-claims/{claim_id}",
            headers=headers,
        )

    def list_exclusivity_claims(self, network_id, territory_id, headers, params=None):
        return self._request(
            "GET",
            f"/networks/{network_id}/territories/{territory_id}/exclusivity-claims",
            headers=headers,
            params=params,
        )

    def validate_exclusivity_claim(self, network_id, territory_id, claim_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/territories/{territory_id}/exclusivity-claims/{claim_id}/validate",
            {},
            headers,
        )

    def dismiss_exclusivity_claim(self, network_id, territory_id, claim_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/territories/{territory_id}/exclusivity-claims/{claim_id}/dismiss",
            {},
            headers,
        )

    def settle_exclusivity_claim(self, network_id, territory_id, claim_id, headers):
        return self._request(
            "POST",
            f"/networks/{network_id}/territories/{territory_id}/exclusivity-claims/{claim_id}/settle",
            {},
            headers,
        )

    # --- Flat reverse-reachability GETs (single by id) ---
    def get_station_flat(self, station_id, headers):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    def get_territory_flat(self, territory_id, headers):
        return self._request("GET", f"/territories/{territory_id}", headers=headers)

    def get_agreement_flat(self, agreement_id, headers):
        return self._request("GET", f"/agreements/{agreement_id}", headers=headers)

    def get_program_flat(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def get_clearance_report_flat(self, report_id, headers):
        return self._request("GET", f"/clearance-reports/{report_id}", headers=headers)

    def get_preemption_flat(self, preemption_id, headers):
        return self._request("GET", f"/preemptions/{preemption_id}", headers=headers)

    def get_avail_allocation_flat(self, alloc_id, headers):
        return self._request("GET", f"/avail-allocations/{alloc_id}", headers=headers)

    def get_retrans_settlement_flat(self, settlement_id, headers):
        return self._request("GET", f"/retrans-settlements/{settlement_id}", headers=headers)

    def get_outage_event_flat(self, event_id, headers):
        return self._request("GET", f"/outage-events/{event_id}", headers=headers)

    def get_outage_credit_flat(self, credit_id, headers):
        return self._request("GET", f"/outage-credits/{credit_id}", headers=headers)

    def get_renewal_offer_flat(self, offer_id, headers):
        return self._request("GET", f"/renewal-offers/{offer_id}", headers=headers)

    def get_compliance_report_flat(self, report_id, headers):
        return self._request("GET", f"/compliance-reports/{report_id}", headers=headers)

    def get_exclusivity_claim_flat(self, claim_id, headers):
        return self._request("GET", f"/exclusivity-claims/{claim_id}", headers=headers)


api_client = ApiClient()
