"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Distributor ---
    def create_distributor(self, payload, headers):
        return self._request("POST", "/distributors", payload, headers)

    def get_distributor(self, did, headers):
        return self._request("GET", f"/distributors/{did}", headers=headers)

    def list_distributors(self, headers, params=None):
        return self._request("GET", "/distributors", headers=headers, params=params)

    def close_box_office_week(self, did, headers):
        return self._request("POST", f"/distributors/{did}/close_box_office_week", {}, headers)

    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Film ---
    def create_film(self, did, payload, headers):
        return self._request("POST", f"/distributors/{did}/films", payload, headers)

    def get_film(self, did, fid, headers):
        return self._request("GET", f"/distributors/{did}/films/{fid}", headers=headers)

    def list_films(self, did, headers, params=None):
        return self._request("GET", f"/distributors/{did}/films", headers=headers, params=params)

    def open_release(self, did, fid, payload, headers):
        return self._request("POST", f"/distributors/{did}/films/{fid}/open_release", payload, headers)

    def pull_film(self, did, fid, headers):
        return self._request("POST", f"/distributors/{did}/films/{fid}/pull", {}, headers)

    def request_ancillary_handoff(self, did, fid, headers):
        return self._request("POST", f"/distributors/{did}/films/{fid}/request_ancillary_handoff", {}, headers)

    # --- Market ---
    def create_market(self, did, payload, headers):
        return self._request("POST", f"/distributors/{did}/markets", payload, headers)

    def get_market(self, did, mid, headers):
        return self._request("GET", f"/distributors/{did}/markets/{mid}", headers=headers)

    def list_markets(self, did, headers, params=None):
        return self._request("GET", f"/distributors/{did}/markets", headers=headers, params=params)

    # --- Theatre ---
    def create_theatre(self, did, payload, headers):
        return self._request("POST", f"/distributors/{did}/theatres", payload, headers)

    def get_theatre(self, did, tid, headers):
        return self._request("GET", f"/distributors/{did}/theatres/{tid}", headers=headers)

    def list_theatres(self, did, headers, params=None):
        return self._request("GET", f"/distributors/{did}/theatres", headers=headers, params=params)

    def suspend_theatre(self, did, tid, headers):
        return self._request("POST", f"/distributors/{did}/theatres/{tid}/suspend", {}, headers)

    # --- Screen ---
    def create_screen(self, did, tid, payload, headers):
        return self._request("POST", f"/distributors/{did}/theatres/{tid}/screens", payload, headers)

    def get_screen(self, did, tid, sid, headers):
        return self._request("GET", f"/distributors/{did}/theatres/{tid}/screens/{sid}", headers=headers)

    def list_screens(self, did, tid, headers, params=None):
        return self._request("GET", f"/distributors/{did}/theatres/{tid}/screens", headers=headers, params=params)

    # --- AggregateDeal ---
    def create_aggregate_deal(self, did, payload, headers):
        return self._request("POST", f"/distributors/{did}/aggregate-deals", payload, headers)

    def get_aggregate_deal(self, did, aid, headers):
        return self._request("GET", f"/distributors/{did}/aggregate-deals/{aid}", headers=headers)

    def list_aggregate_deals(self, did, headers, params=None):
        return self._request("GET", f"/distributors/{did}/aggregate-deals", headers=headers, params=params)

    def activate_aggregate_deal(self, did, aid, headers):
        return self._request("POST", f"/distributors/{did}/aggregate-deals/{aid}/activate", {}, headers)

    # --- BookingAgreement ---
    def create_booking_agreement(self, did, payload, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements", payload, headers)

    def get_booking_agreement(self, did, baid, headers):
        return self._request("GET", f"/distributors/{did}/booking-agreements/{baid}", headers=headers)

    def list_booking_agreements(self, did, headers, params=None):
        return self._request("GET", f"/distributors/{did}/booking-agreements", headers=headers, params=params)

    def counter_booking_agreement(self, did, baid, payload, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/counter", payload, headers)

    def accept_booking_agreement(self, did, baid, payload, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/accept", payload, headers)

    def decline_booking_agreement(self, did, baid, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/decline", {}, headers)

    def cancel_booking_agreement(self, did, baid, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/cancel", {}, headers)

    def holdover_booking_agreement(self, did, baid, payload, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/holdover", payload, headers)

    def holdover_release_booking_agreement(self, did, baid, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/holdover_release", {}, headers)

    # --- DCPShipment ---
    def create_dcp_shipment(self, did, baid, payload, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/dcp-shipments", payload, headers)

    def get_dcp_shipment(self, did, baid, sid, headers):
        return self._request("GET", f"/distributors/{did}/booking-agreements/{baid}/dcp-shipments/{sid}", headers=headers)

    def list_dcp_shipments(self, did, baid, headers, params=None):
        return self._request("GET", f"/distributors/{did}/booking-agreements/{baid}/dcp-shipments", headers=headers, params=params)

    def mark_dcp_delivered(self, did, baid, sid, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/dcp-shipments/{sid}/mark_delivered", {}, headers)

    def mark_dcp_returned(self, did, baid, sid, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/dcp-shipments/{sid}/mark_returned", {}, headers)

    def mark_dcp_lost(self, did, baid, sid, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/dcp-shipments/{sid}/mark_lost", {}, headers)

    # --- KDMKey ---
    def create_kdm_key(self, did, baid, payload, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/kdm-keys", payload, headers)

    def get_kdm_key(self, did, baid, kid, headers):
        return self._request("GET", f"/distributors/{did}/booking-agreements/{baid}/kdm-keys/{kid}", headers=headers)

    def list_kdm_keys(self, did, baid, headers, params=None):
        return self._request("GET", f"/distributors/{did}/booking-agreements/{baid}/kdm-keys", headers=headers, params=params)

    def extend_kdm_key(self, did, baid, kid, payload, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/kdm-keys/{kid}/extend", payload, headers)

    def revoke_kdm_key(self, did, baid, kid, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/kdm-keys/{kid}/revoke", {}, headers)

    # --- BoxOfficeReport ---
    def create_box_office_report(self, did, baid, payload, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/box-office-reports", payload, headers)

    def get_box_office_report(self, did, baid, rid, headers):
        return self._request("GET", f"/distributors/{did}/booking-agreements/{baid}/box-office-reports/{rid}", headers=headers)

    def list_box_office_reports(self, did, baid, headers, params=None):
        return self._request("GET", f"/distributors/{did}/booking-agreements/{baid}/box-office-reports", headers=headers, params=params)

    def submit_box_office_report(self, did, baid, rid, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/box-office-reports/{rid}/submit", {}, headers)

    def void_box_office_report(self, did, baid, rid, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/box-office-reports/{rid}/void", {}, headers)

    # --- Settlement ---
    def get_settlement(self, did, baid, sid, headers):
        return self._request("GET", f"/distributors/{did}/booking-agreements/{baid}/settlements/{sid}", headers=headers)

    def list_settlements(self, did, baid, headers, params=None):
        return self._request("GET", f"/distributors/{did}/booking-agreements/{baid}/settlements", headers=headers, params=params)

    def mark_settlement_settled(self, did, baid, sid, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/settlements/{sid}/mark_settled", {}, headers)

    def dispute_settlement(self, did, baid, sid, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/settlements/{sid}/dispute", {}, headers)

    def resolve_settlement_dispute(self, did, baid, sid, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/settlements/{sid}/resolve_dispute", {}, headers)

    def write_off_settlement(self, did, baid, sid, headers):
        return self._request("POST", f"/distributors/{did}/booking-agreements/{baid}/settlements/{sid}/write_off", {}, headers)

    # --- HoldoverDecision ---
    def list_holdover_decisions(self, did, baid, headers, params=None):
        return self._request("GET", f"/distributors/{did}/booking-agreements/{baid}/holdover-decisions", headers=headers, params=params)

    # --- MarketingCommitment ---
    def create_marketing_commitment(self, did, mid, payload, headers):
        return self._request("POST", f"/distributors/{did}/markets/{mid}/marketing-commitments", payload, headers)

    def get_marketing_commitment(self, did, mid, mcid, headers):
        return self._request("GET", f"/distributors/{did}/markets/{mid}/marketing-commitments/{mcid}", headers=headers)

    def list_marketing_commitments(self, did, mid, headers, params=None):
        return self._request("GET", f"/distributors/{did}/markets/{mid}/marketing-commitments", headers=headers, params=params)

    def list_distributor_marketing_commitments(self, did, headers, params=None):
        return self._request("GET", f"/distributors/{did}/marketing-commitments", headers=headers, params=params)

    def list_film_marketing_commitments(self, did, fid, headers, params=None):
        return self._request("GET", f"/distributors/{did}/films/{fid}/marketing-commitments", headers=headers, params=params)

    def list_theatre_marketing_commitments(self, did, tid, headers, params=None):
        return self._request("GET", f"/distributors/{did}/theatres/{tid}/marketing-commitments", headers=headers, params=params)

    def commit_marketing_commitment(self, did, mid, mcid, headers):
        return self._request("POST", f"/distributors/{did}/markets/{mid}/marketing-commitments/{mcid}/commit", {}, headers)

    def cancel_marketing_commitment(self, did, mid, mcid, headers):
        return self._request("POST", f"/distributors/{did}/markets/{mid}/marketing-commitments/{mcid}/cancel", {}, headers)

    # --- ZoneClearance ---
    def create_zone_clearance(self, did, mid, payload, headers):
        return self._request("POST", f"/distributors/{did}/markets/{mid}/zone-clearances", payload, headers)

    def get_zone_clearance(self, did, mid, zid, headers):
        return self._request("GET", f"/distributors/{did}/markets/{mid}/zone-clearances/{zid}", headers=headers)

    def list_zone_clearances(self, did, mid, headers, params=None):
        return self._request("GET", f"/distributors/{did}/markets/{mid}/zone-clearances", headers=headers, params=params)

    def list_distributor_zone_clearances(self, did, headers, params=None):
        return self._request("GET", f"/distributors/{did}/zone-clearances", headers=headers, params=params)

    def list_film_zone_clearances(self, did, fid, headers, params=None):
        return self._request("GET", f"/distributors/{did}/films/{fid}/zone-clearances", headers=headers, params=params)

    def list_theatre_zone_clearances(self, did, tid, headers, params=None):
        return self._request("GET", f"/distributors/{did}/theatres/{tid}/zone-clearances", headers=headers, params=params)

    def get_zone_clearance_by_id(self, did, zid, headers):
        return self._request("GET", f"/distributors/{did}/zone-clearances/{zid}", headers=headers)

    def list_zone_clearance_children(self, did, zid, headers, params=None):
        return self._request("GET", f"/distributors/{did}/zone-clearances/{zid}/children", headers=headers, params=params)

    def challenge_zone_clearance(self, did, mid, zid, headers):
        return self._request("POST", f"/distributors/{did}/markets/{mid}/zone-clearances/{zid}/challenge", {}, headers)

    def rule_zone_clearance(self, did, mid, zid, payload, headers):
        return self._request("POST", f"/distributors/{did}/markets/{mid}/zone-clearances/{zid}/rule", payload, headers)

    # --- AncillaryWindow ---
    def create_ancillary_window(self, did, fid, payload, headers):
        return self._request("POST", f"/distributors/{did}/films/{fid}/ancillary-windows", payload, headers)

    def get_ancillary_window(self, did, fid, awid, headers):
        return self._request("GET", f"/distributors/{did}/films/{fid}/ancillary-windows/{awid}", headers=headers)

    def list_ancillary_windows(self, did, fid, headers, params=None):
        return self._request("GET", f"/distributors/{did}/films/{fid}/ancillary-windows", headers=headers, params=params)

    def cancel_ancillary_window(self, did, fid, awid, headers):
        return self._request("POST", f"/distributors/{did}/films/{fid}/ancillary-windows/{awid}/cancel", {}, headers)


api_client = ApiClient()
